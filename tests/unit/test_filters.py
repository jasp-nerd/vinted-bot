"""The richer filters: words, patterns, prices, sellers and deals."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vinted_sniper.db.repo import Query
from vinted_sniper.engine import filters
from vinted_sniper.vinted.models import Item, SellerProfile


def item(**kwargs: object) -> Item:
    defaults: dict[str, object] = {
        "item_id": 1,
        "tld": "fr",
        "title": "Nike Air Max 90",
        "url": "https://www.vinted.fr/items/1",
        "total_price": Decimal("20.00"),
        "currency": "EUR",
        "seller_id": 5,
    }
    defaults.update(kwargs)
    return Item(**defaults)  # type: ignore[arg-type]


def search(**kwargs: object) -> Query:
    defaults: dict[str, object] = {
        "id": 1,
        "name": "test",
        "url": "https://www.vinted.fr/catalog?search_text=x",
        "tld": "fr",
        "params": {},
        "poll_interval_s": 60,
        "paused": False,
    }
    defaults.update(kwargs)
    return Query(**defaults)  # type: ignore[arg-type]


def reason(listing: Item, query: Query, **kwargs: object) -> str | None:
    rejection = filters.Rules(query).check(listing, **kwargs)  # type: ignore[arg-type]
    return rejection.reason if rejection else None


# --- Words -------------------------------------------------------------------------


def test_every_included_term_must_appear() -> None:
    query = search(include_terms=["nike", "max"])

    assert reason(item(title="Nike Air Max"), query) is None
    assert reason(item(title="Nike Air Force"), query) == "missing_keyword"


def test_an_included_term_can_offer_alternatives() -> None:
    query = search(include_terms=["air max|airmax"])

    assert reason(item(title="Nike AIRMAX 95"), query) is None


def test_included_terms_ignore_accents_and_case() -> None:
    assert reason(item(title="Veste CAFÉ racer"), search(include_terms=["cafe"])) is None


def test_the_brand_counts_as_part_of_the_title() -> None:
    """The title often leaves the brand out because Vinted shows it separately."""
    assert reason(item(title="Air Max 90", brand="Nike"), search(include_terms=["nike"])) is None


def test_excluded_words_match_whole_words_only() -> None:
    """A substring match let "art" exclude "smartphone" and "party"."""
    query = search(banned_keywords=["art"])

    assert reason(item(title="Smartphone party case"), query) is None
    assert reason(item(title="Art deco lamp"), query) == "banned_keyword"


def test_a_trailing_star_matches_any_ending() -> None:
    assert reason(item(title="Spare parts"), search(banned_keywords=["part*"])) == "banned_keyword"


def test_the_regex_must_match_the_title() -> None:
    query = search(regex=r"\b(9[05])\b")

    assert reason(item(title="Air Max 90"), query) is None
    assert reason(item(title="Air Max 97"), query) == "regex"


# --- Prices and condition ----------------------------------------------------------


def test_a_minimum_total_price_skips_suspiciously_cheap_listings() -> None:
    query = search(min_total_price=Decimal("15"))

    assert reason(item(total_price=Decimal("9.99")), query) == "under_minimum"


def test_an_unknown_condition_is_not_a_mismatch() -> None:
    """The new catalog often has no condition; rejecting those rejected everything."""
    assert reason(item(condition=None), search(conditions=["New with tags"])) is None


def test_blocked_sellers_are_skipped() -> None:
    assert reason(item(seller_id=5), search(), blocked_sellers=frozenset({5})) == "blocked_seller"


# --- Sellers -----------------------------------------------------------------------


def profile(**kwargs: object) -> SellerProfile:
    defaults: dict[str, object] = {"seller_id": 5, "tld": "fr", "country_code": "FR"}
    defaults.update(kwargs)
    return SellerProfile(**defaults)  # type: ignore[arg-type]


def test_sellers_outside_the_allowed_countries_are_skipped() -> None:
    rejection = filters.check_seller(item(), search(countries=["BE"]), profile(country_code="fr"))

    assert rejection is not None
    assert rejection.reason == "seller_country"


def test_sellers_inside_the_allowed_countries_pass() -> None:
    assert filters.check_seller(item(), search(countries=["FR"]), profile()) is None


def test_without_a_profile_the_country_cannot_be_judged_and_passes() -> None:
    assert filters.check_seller(item(), search(countries=["BE"]), None) is None


def test_the_rating_comes_from_the_profile_when_the_listing_has_none() -> None:
    query = search(seller_min_rating=4.5)

    # A member page reports stars out of five, unlike the listing's 0..1 fraction.
    rejection = filters.check_seller(item(), query, profile(rating=4.0, feedback_count=40))

    assert rejection is not None
    assert rejection.reason == "low_rating"


def test_a_profile_rating_in_stars_above_the_minimum_passes() -> None:
    query = search(seller_min_rating=4.5)

    assert filters.check_seller(item(), query, profile(rating=4.8, feedback_count=40)) is None


@pytest.mark.parametrize(
    ("query_kwargs", "expected"),
    [
        ({"skip_unrated_sellers": True}, "unrated_seller"),
        ({"seller_min_reviews": 3}, "few_reviews"),
        ({"seller_min_rating": 4.0}, None),
    ],
)
def test_a_seller_with_no_reviews(query_kwargs: dict[str, object], expected: str | None) -> None:
    rejection = filters.check_seller(item(), search(**query_kwargs), profile(feedback_count=0))

    assert (rejection.reason if rejection else None) == expected


def test_a_lookup_is_only_needed_when_the_listing_lacks_seller_data() -> None:
    query = search(seller_min_rating=4.0)

    assert filters.needs_lookup(item(), query)
    assert not filters.needs_lookup(item(seller_rating=0.9, seller_feedback_count=10), query)
    assert filters.needs_lookup(item(seller_rating=0.9), search(countries=["FR"]))


# --- Deals -------------------------------------------------------------------------


def test_a_deal_only_search_wants_a_big_enough_discount() -> None:
    query = search(deal_only_pct=30)

    assert filters.check_deal(item(total_price=Decimal("14")), query, Decimal("20")) is None
    rejection = filters.check_deal(item(total_price=Decimal("16")), query, Decimal("20"))
    assert rejection is not None
    assert rejection.reason == "not_a_deal"


def test_without_history_nothing_is_called_a_deal() -> None:
    rejection = filters.check_deal(item(), search(deal_only_pct=10), None)

    assert rejection is not None
    assert "history" in rejection.detail


def test_searches_that_do_not_ask_for_deals_are_not_judged_on_them() -> None:
    assert filters.check_deal(item(), search(), None) is None


# --- Margin --------------------------------------------------------------------------------


def test_a_listing_that_leaves_too_little_after_reselling_is_skipped() -> None:
    """Resold at 30 with 10% fees and 3 postage leaves 24, minus 20 paid is 4."""
    rule = search(
        resale_price=Decimal("30"),
        resale_fee_pct=10,
        resale_shipping=Decimal("3"),
        min_margin=Decimal("5"),
    )

    rejection = filters.check(item(), rule)

    assert rejection is not None and rejection.reason == "low_margin"


def test_the_margin_rejection_says_what_was_left_and_what_was_wanted() -> None:
    rule = search(resale_price=Decimal("30"), min_margin=Decimal("15"))

    rejection = filters.check(item(), rule)

    assert rejection is not None and rejection.detail == (
        "reselling at 30 would leave about 10.00 after fees and postage; "
        "this search wants at least 15"
    )


def test_a_listing_with_enough_margin_passes() -> None:
    rule = search(resale_price=Decimal("30"), min_margin=Decimal("10"))

    assert filters.check(item(), rule) is None


def test_a_margin_in_another_currency_is_not_judged() -> None:
    """A pound listing on a euro search has no margin to compare, so it is let through."""
    rule = search(resale_price=Decimal("30"), min_margin=Decimal("15"))

    assert filters.check(item(tld="co.uk", currency="GBP"), rule) is None
