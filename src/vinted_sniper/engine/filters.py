"""Deciding whether a listing is worth telling you about.

Vinted's own filters get you most of the way there; these cover what its search cannot.
The important one is price: Vinted filters on the asking price, but you pay the asking
price plus buyer protection, so a `price_to=30` search happily returns things that cost you
33. Filtering on the total is the difference between a useful alert and a misleading one.

The checks come in three tiers, by what they cost:

* `Rules.check` needs only the listing: words, patterns, prices, condition, the blocklist.
* `check_seller` needs the seller's member page (country, rating), which costs a request
  the first time, so it only runs for listings that passed everything cheaper.
* `check_deal` needs the search's typical price, which the poller reads once per check.

Every rejection carries a reason and a sentence, because a search that stays quiet should
be able to say why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from vinted_sniper.db.repo import Query, deal_percent
from vinted_sniper.engine.validation import TITLE_REGEX_FLAGS, fold
from vinted_sniper.vinted.models import Item, SellerProfile

# Vinted's own rating is a fraction; people think in stars.
_STARS = 5


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why a listing was skipped. Worth keeping around: it is what makes a quiet search
    explainable rather than suspicious."""

    reason: str
    detail: str


def _word_pattern(term: str) -> re.Pattern[str] | None:
    """Match a word or phrase as whole words; a trailing * allows any ending.

    Whole words, because a plain substring test let "art" exclude "smartphone" and
    "party". Text is folded first, so case and accents never matter.
    """
    folded = fold(term.strip())
    prefix = folded.endswith("*")
    folded = folded.rstrip("*").strip()
    if not folded:
        return None
    tail = "" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w){re.escape(folded)}{tail}")


class Rules:
    """A search's text rules, compiled once for the life of its poller."""

    def __init__(self, query: Query) -> None:
        self.query = query
        self._banned = [
            (word, pattern)
            for word in query.banned_keywords
            if (pattern := _word_pattern(word)) is not None
        ]
        # Each term is a list of alternatives, any one of which satisfies it.
        self._include = [
            (term, patterns)
            for term in query.include_terms
            if (patterns := [p for alt in term.split("|") if (p := _word_pattern(alt))])
        ]
        self._regex = re.compile(query.regex, TITLE_REGEX_FLAGS) if query.regex else None
        self._conditions = {fold(condition) for condition in query.conditions or []}

    def check(
        self, item: Item, *, blocked_sellers: frozenset[int] = frozenset()
    ) -> Rejection | None:
        """Return why this listing should be skipped, or None if it passes the cheap rules."""
        return (
            _check_origin(item, blocked_sellers)
            or self._check_text(item)
            or _check_price(item, self.query)
            or self._check_condition(item)
        )

    def _check_text(self, item: Item) -> Rejection | None:
        text = fold(" ".join(filter(None, [item.title, item.brand])))
        for word, pattern in self._banned:
            if pattern.search(text):
                return Rejection("banned_keyword", f"title contains {word!r}")
        for term, alternatives in self._include:
            if not any(pattern.search(text) for pattern in alternatives):
                return Rejection("missing_keyword", f"title lacks {term!r}")
        if self._regex is not None and not self._regex.search(item.title):
            return Rejection("regex", f"title does not match {self.query.regex!r}")
        return None

    def _check_condition(self, item: Item) -> Rejection | None:
        # The new catalog often leaves condition out. Unknown is not a mismatch: the
        # condition is better asked of Vinted itself, through the search URL.
        if (
            self._conditions
            and item.condition is not None
            and fold(item.condition) not in self._conditions
        ):
            return Rejection("condition", f"condition {item.condition!r} not wanted")
        return None


def _check_origin(item: Item, blocked_sellers: frozenset[int]) -> Rejection | None:
    if item.promoted:
        # Boosted listings resurface old stock. They are not new, whatever the feed says.
        return Rejection("promoted", "listing is a paid bump")
    if item.seller_id is not None and item.seller_id in blocked_sellers:
        return Rejection(
            "blocked_seller", f"seller {item.seller_login or item.seller_id} is blocked"
        )
    return None


def _check_price(item: Item, query: Query) -> Rejection | None:
    if query.max_total_price is None and query.min_total_price is None:
        return None
    payable = item.total_price if item.total_price is not None else item.price
    if payable is None:
        return Rejection("no_price", "listing has no price to compare")
    if query.max_total_price is not None and payable > query.max_total_price:
        return Rejection(
            "over_budget",
            f"{payable} above limit {query.max_total_price} (buyer protection included)",
        )
    if query.min_total_price is not None and payable < query.min_total_price:
        return Rejection("under_minimum", f"{payable} below minimum {query.min_total_price}")
    return None


def check(item: Item, query: Query) -> Rejection | None:
    """The cheap rules for one listing, compiling them on the spot. Pollers use `Rules`."""
    return Rules(query).check(item)


def matches(item: Item, query: Query) -> bool:
    return check(item, query) is None


def needs_lookup(item: Item, query: Query) -> bool:
    """Whether judging this listing's seller takes a member-page lookup.

    A country filter always does. The rating filters only do when the listing itself does
    not say — the old catalog carried ratings, the new one does not.
    """
    if query.countries:
        return True
    wants_rating = (
        query.seller_min_rating is not None
        or query.seller_min_reviews is not None
        or query.skip_unrated_sellers
    )
    return wants_rating and item.seller_rating is None and item.seller_feedback_count is None


def check_seller(item: Item, query: Query, profile: SellerProfile | None) -> Rejection | None:
    """Judge the seller, from the listing's own fields and a member-page profile if we have one.

    A missing profile means the lookup is unavailable, and a filter that cannot be judged
    lets the listing through: skipping everything because one input is unknown is how a
    search goes silent with no explanation.
    """
    return _check_country(query, profile) or _check_reputation(item, query, profile)


def _check_country(query: Query, profile: SellerProfile | None) -> Rejection | None:
    if not query.countries or profile is None:
        return None
    country = (profile.country_code or "").upper()
    if not country:
        return Rejection("seller_country", "seller's country is not public")
    if country not in query.countries:
        return Rejection("seller_country", f"seller is in {country}")
    return None


def _check_reputation(item: Item, query: Query, profile: SellerProfile | None) -> Rejection | None:
    rating = item.seller_rating
    if rating is None and profile is not None and profile.rating is not None:
        # Listings carry Vinted's 0..1 fraction; a member page reports stars out of five.
        rating = profile.rating / _STARS
    reviews = item.seller_feedback_count
    if reviews is None and profile is not None:
        reviews = profile.feedback_count
    if rating is None and reviews is None:
        return None

    if reviews == 0 or (reviews is None and not rating):
        return _check_unrated(query)

    if query.seller_min_reviews is not None and (reviews or 0) < query.seller_min_reviews:
        return Rejection("few_reviews", f"{reviews} reviews, want {query.seller_min_reviews}")
    if query.seller_min_rating is not None and rating is not None:
        stars = rating * _STARS
        if stars < query.seller_min_rating:
            return Rejection(
                "low_rating", f"rated {stars:.1f} stars, want {query.seller_min_rating:g}"
            )
    return None


def _check_unrated(query: Query) -> Rejection | None:
    """A new seller has no rating to compare, so only the filters about reviews apply."""
    if query.skip_unrated_sellers:
        return Rejection("unrated_seller", "seller has no reviews yet")
    if query.seller_min_reviews:
        return Rejection("few_reviews", "seller has no reviews yet")
    return None


def check_deal(item: Item, query: Query, typical: Decimal | None) -> Rejection | None:
    """For deal-only searches: is this far enough under what the search usually finds?"""
    if query.deal_only_pct is None:
        return None
    pct = deal_percent(item.total_price or item.price, typical)
    if pct is None:
        return Rejection("not_a_deal", "not enough history yet to know a typical price")
    if pct < query.deal_only_pct:
        return Rejection(
            "not_a_deal", f"{pct}% under the typical {typical}, want {query.deal_only_pct}%"
        )
    return None
