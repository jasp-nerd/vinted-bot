"""Every SQL statement in the application.

Keeping them here means there is one place to look when the schema changes, and the rest
of the code deals in ordinary Python objects rather than rows.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

import aiosqlite

from vinted_bot.db.connection import Database
from vinted_bot.deals import deal_percent, margin
from vinted_bot.engine import validation
from vinted_bot.vinted.models import Item, SellerProfile

# New searches take the next colour from this, so a dashboard with several searches can
# tell them apart at a glance without anyone choosing.
PALETTE = (
    "#007782",
    "#D04555",
    "#F9BB42",
    "#28865A",
    "#6C5DD3",
    "#E07A2E",
    "#2F6FDE",
    "#B5487F",
)

# A median of a handful of listings says more about luck than about the market.
TYPICAL_PRICE_MIN_SAMPLES = 15
TYPICAL_PRICE_WINDOW_S = 14 * 86_400

# "Why wasn't this sent?" only needs recent history.
REJECTIONS_KEEP = 2_000
REJECTIONS_MAX_AGE_S = 7 * 86_400

_CENT = Decimal("0.01")

# The id clock's resolution; see `Repo.note_listing_id`.
_ID_CLOCK_STEP_S = 60

Mark = Literal["saved", "hidden"]
MarkFilter = Literal["visible", "saved", "hidden", "unmarked", "all"]
NotificationKind = Literal["listing", "price_drop", "sold", "reserved", "removed", "seller_upload"]

# --- Row types ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Query:
    """A saved search."""

    id: int
    name: str
    url: str
    tld: str
    params: dict[str, str]
    poll_interval_s: int
    paused: bool
    banned_keywords: list[str] = field(default_factory=list)
    max_total_price: Decimal | None = None
    conditions: list[str] | None = None
    countries: list[str] | None = None
    # Every term must appear in the title; a term may offer alternatives as "a|b".
    include_terms: list[str] = field(default_factory=list)
    regex: str | None = None
    min_total_price: Decimal | None = None
    seller_min_rating: float | None = None
    seller_min_reviews: int | None = None
    skip_unrated_sellers: bool = False
    # Only alert when the total is at least this many percent under the typical price.
    deal_only_pct: int | None = None
    max_age_min: int | None = None
    color: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    quiet_mode: str = "hold"
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    extra_tlds: list[str] = field(default_factory=list)
    # What a find resells for, in this search's own site's currency, and what reselling
    # costs: the selling platform's cut in percent and the postage. See migration 0005.
    resale_price: Decimal | None = None
    resale_fee_pct: float | None = None
    resale_shipping: Decimal | None = None
    # Skip anything that would leave less than this after reselling.
    min_margin: Decimal | None = None
    # Announce nothing until this time (unix seconds). Set from an alert's mute button,
    # never from the edit form, so saving the form does not end or start a mute.
    muted_until: int | None = None

    def margin_on(self, item: Item) -> Decimal | None:
        """What reselling this listing would leave, or None without a resale price."""
        return margin(
            item.total_price if item.total_price is not None else item.price,
            item.currency,
            site=self.tld,
            resale_price=self.resale_price,
            fee_pct=self.resale_fee_pct,
            shipping=self.resale_shipping,
        )

    def is_muted(self, now: int) -> bool:
        return self.muted_until is not None and now < self.muted_until

    @property
    def sites(self) -> list[str]:
        """Every country site this search runs on, its own first."""
        return [self.tld, *self.extra_tlds]

    @property
    def needs_seller_profile(self) -> bool:
        """Whether a filter needs what only the member page says.

        The catalog stopped carrying seller ratings, so the rating filters go through the
        same cached lookup as the country filter.
        """
        return bool(
            self.countries
            or self.seller_min_rating is not None
            or self.seller_min_reviews is not None
            or self.skip_unrated_sellers
        )


@dataclass(frozen=True, slots=True)
class QueryState:
    """What happened last time we checked a search."""

    query_id: int
    last_polled_at: int | None = None
    last_success_at: int | None = None
    last_status: str | None = None
    last_error: str | None = None
    newest_item_ts: int | None = None
    newest_raw_ts: int | None = None
    stale_cycles: int = 0
    items_seen_total: int = 0
    count_403: int = 0
    count_429: int = 0
    # The lowest listing id still worth considering new; see migration 0004.
    floor_item_id: int | None = None
    newest_raw_id: int | None = None
    raw_advanced_at: int | None = None

    @property
    def is_first_run(self) -> bool:
        """True until a check has completed, which is what suppresses the opening flood."""
        return self.last_success_at is None


@dataclass(frozen=True, slots=True)
class Destination:
    """Somewhere notifications go."""

    id: int
    kind: str
    name: str
    config: dict[str, Any]
    active: bool = True
    notify_status: bool = False
    failure_count: int = 0
    deactivated_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PendingNotification:
    """One queued notification, joined with what it needs to render."""

    outbox_id: int
    destination_id: int
    # None for watch notifications, which no search produced.
    query_id: int | None
    # The search's name, or the watch's label.
    query_name: str
    attempts: int
    item: Item
    # When the poller first saw the listing, which is the honest "found it" moment even
    # if delivery retries push the message out later.
    detected_at: int | None = None
    query_color: str | None = None
    # The search's median total price when this listing was recorded; None until there
    # is enough history for a median to mean anything.
    typical_price: Decimal | None = None
    # Deliver without a sound: quiet hours in 'silent' mode.
    silent: bool = False
    # 'listing', 'price_drop', 'sold', 'reserved', 'removed' or 'seller_upload'.
    kind: str = "listing"
    previous_price: Decimal | None = None
    watch_id: int | None = None
    # What reselling it would leave, from the search's resale price; None without one.
    margin: Decimal | None = None

    @property
    def deal_pct(self) -> int | None:
        """Percent under the typical price, for a "deal" badge. None without history."""
        return deal_percent(self.item.total_price, self.typical_price)


@dataclass(frozen=True, slots=True)
class RejectedListing:
    """A new listing a search turned down, and why.

    `final` is False when the reason may not hold next time — a seller lookup that
    failed — so the listing is logged but left to be judged again on the next check.
    """

    item: Item
    reason: str
    detail: str
    final: bool = True


@dataclass(frozen=True, slots=True)
class RejectionRecord:
    """One row of "why wasn't this sent?"."""

    id: int
    query_id: int
    item_id: int
    reason: str
    detail: str
    title: str | None
    total_price: Decimal | None
    currency: str | None
    photo_url: str | None
    url: str | None
    created_at: int


@dataclass(frozen=True, slots=True)
class FeedItem:
    """A listing as the dashboard shows it: the listing, where it came from, its mark."""

    seq: int
    item: Item
    first_seen_at: int
    query_id: int | None
    query_name: str | None
    query_color: str | None
    watch_id: int | None
    typical_price: Decimal | None
    seller_country: str | None
    mark: str | None

    @property
    def deal_pct(self) -> int | None:
        return deal_percent(self.item.total_price, self.typical_price)


@dataclass(frozen=True, slots=True)
class BlockedSeller:
    seller_id: int
    login: str | None
    tld: str | None
    reason: str | None
    created_at: int


@dataclass(frozen=True, slots=True)
class Watch:
    """A listing watched for price drops and its sale, or a seller watched for uploads."""

    id: int
    kind: str
    tld: str
    target_id: int
    label: str
    last_price: Decimal | None
    currency: str | None
    last_status: str | None
    last_checked_at: int | None
    next_check_at: int
    last_error: str | None
    active: bool
    created_at: int
    # Seller watches: the newest listing id seen so far; see migration 0006.
    seen_up_to: int | None = None

    @property
    def is_first_check(self) -> bool:
        return self.last_checked_at is None


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Preferences people change from the dashboard, as opposed to process settings."""

    timezone: str
    healthcheck_url: str | None
    update_check: bool
    onboarded: bool
    theme: str
    latest_version: str | None
    # Install a newer release by itself, in the small hours; off unless someone asks.
    auto_update: bool


THEMES = ("system", "light", "dark")


@dataclass(frozen=True, slots=True)
class SupportState:
    """Where the dashboard's request for support stands. web/support.py decides from it."""

    times_shown: int
    # 0 until the card has shown once.
    last_shown_at: int
    # Chose "Don't show again". Giving or starring doesn't count: the card stays.
    opted_out: bool
    # When an alert last reached someone, or None if none ever has.
    last_alert_at: int | None


@dataclass(frozen=True, slots=True)
class DailyFinds:
    day: str
    query_id: int
    count: int


@dataclass(frozen=True, slots=True)
class HeatCell:
    # Monday is 0, as in Python's datetime.
    weekday: int
    hour: int
    count: int


@dataclass(frozen=True, slots=True)
class DailyMedian:
    day: str
    query_id: int
    currency: str
    median: Decimal


@dataclass(frozen=True, slots=True)
class Activity:
    """Everything the stats page charts, from one pass over recent finds."""

    daily_finds: list[DailyFinds]
    heatmap: list[HeatCell]
    daily_medians: list[DailyMedian]
    # How long after its photo was taken a listing reached us. None while Vinted's
    # catalog does not report photo times.
    latency_p50_s: int | None
    latency_p90_s: int | None
    latency_samples: int


@dataclass(frozen=True, slots=True)
class DeliveryCounts:
    destination_id: int
    name: str
    kind: str
    sent: int
    failed: int
    pending: int


@dataclass(frozen=True, slots=True)
class Totals:
    searches: int
    active_searches: int
    listings_found: int
    found_today: int
    notifications_sent: int
    notifications_pending: int
    watches: int
    blocked_sellers: int


# --- Conversions -------------------------------------------------------------------


def _json_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    value = json.loads(raw)
    return [str(v) for v in value] if isinstance(value, list) else None


def _money(value: float | None) -> Decimal | None:
    """Read a stored price back as the two-decimal amount it was.

    Prices are stored as REAL, and Decimal(str(15.0)) is "15.0" — which is not how
    anyone writes fifteen euros, and not what the webhook payload documents.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(_CENT)


def _real(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _validated(query: Query) -> Query:
    """Run every typed field through the same checks the entry points use."""
    quiet_start, quiet_end, quiet_mode = validation.parse_quiet_hours(
        query.quiet_start, query.quiet_end, query.quiet_mode
    )
    min_price = validation.parse_price(query.min_total_price, field="min_total_price")
    max_price = validation.parse_price(query.max_total_price, field="max_total_price")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise validation.InvalidInputError(
            "min_total_price", "The minimum price is above the maximum."
        )
    resale_price = validation.parse_price(query.resale_price, field="resale_price")
    min_margin = validation.parse_price(query.min_margin, field="min_margin")
    if min_margin is not None and resale_price is None:
        raise validation.InvalidInputError(
            "min_margin", "Set what it resells for first: the margin is worked out from that."
        )
    return replace(
        query,
        name=validation.parse_name(query.name, fallback=f"vinted.{query.tld}"),
        poll_interval_s=validation.parse_interval(query.poll_interval_s, default=60),
        banned_keywords=validation.parse_words(query.banned_keywords, field="banned_keywords"),
        include_terms=validation.parse_words(query.include_terms, field="include_terms"),
        regex=validation.parse_regex(query.regex),
        min_total_price=min_price,
        max_total_price=max_price,
        countries=validation.parse_countries(query.countries) or None,
        seller_min_rating=validation.parse_rating(query.seller_min_rating),
        seller_min_reviews=validation.parse_count(
            query.seller_min_reviews, field="seller_min_reviews"
        ),
        deal_only_pct=validation.parse_percent(query.deal_only_pct, field="deal_only_pct"),
        max_age_min=validation.parse_minutes(query.max_age_min, field="max_age_min"),
        color=validation.parse_color(query.color),
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        quiet_mode=quiet_mode,
        notes=validation.parse_notes(query.notes),
        tags=validation.parse_words(query.tags, field="tags"),
        extra_tlds=validation.parse_tlds(query.extra_tlds, primary=query.tld),
        resale_price=resale_price,
        resale_fee_pct=validation.parse_fee_pct(query.resale_fee_pct),
        resale_shipping=validation.parse_price(query.resale_shipping, field="resale_shipping"),
        min_margin=min_margin,
    )


# The columns that decide what a search fetches, as opposed to how it judges the results.
_FETCH_COLUMNS = ("url", "tld", "params_json", "extra_tlds_json")


def _query_columns(query: Query) -> dict[str, Any]:
    """The editable columns of a search, in storage form."""
    return {
        "name": query.name,
        "url": query.url,
        "tld": query.tld,
        "params_json": json.dumps(query.params),
        "poll_interval_s": query.poll_interval_s,
        "paused": int(query.paused),
        "banned_keywords_json": json.dumps(query.banned_keywords),
        "include_terms_json": json.dumps(query.include_terms),
        "regex": query.regex,
        "min_total_price": _real(query.min_total_price),
        "max_total_price": _real(query.max_total_price),
        "conditions_json": json.dumps(query.conditions) if query.conditions else None,
        "countries_json": json.dumps(query.countries) if query.countries else None,
        "seller_min_rating": query.seller_min_rating,
        "seller_min_reviews": query.seller_min_reviews,
        "skip_unrated_sellers": int(query.skip_unrated_sellers),
        "deal_only_pct": query.deal_only_pct,
        "max_age_min": query.max_age_min,
        "color": query.color,
        "quiet_start": query.quiet_start,
        "quiet_end": query.quiet_end,
        "quiet_mode": query.quiet_mode,
        "notes": query.notes,
        "tags_json": json.dumps(query.tags),
        "extra_tlds_json": json.dumps(query.extra_tlds),
        "resale_price": _real(query.resale_price),
        "resale_fee_pct": query.resale_fee_pct,
        "resale_shipping": _real(query.resale_shipping),
        "min_margin": _real(query.min_margin),
    }


def _item_from_row(row: aiosqlite.Row) -> Item:
    """Rebuild a listing from an `items` row (selected as i.*)."""
    return Item(
        item_id=row["item_id"],
        tld=row["tld"],
        title=row["title"] or f"Listing {row['item_id']}",
        url=row["url"],
        brand=row["brand"],
        size=row["size"],
        condition=row["condition"],
        price=_money(row["price"]),
        total_price=_money(row["total_price"]),
        currency=row["currency"],
        photo_url=row["photo_url"],
        photo_urls=tuple(json.loads(row["photo_urls_json"] or "[]")),
        photo_ts=row["photo_ts"],
        seller_login=row["seller_login"],
        seller_id=row["seller_id"],
        seller_rating=row["seller_rating"],
        seller_feedback_count=row["seller_feedback_count"],
        favourite_count=row["favourite_count"] or 0,
        view_count=row["view_count"] or 0,
    )


def _item_values(item: Item, now: int, *, keep_raw: bool) -> tuple[Any, ...]:
    return (
        item.item_id,
        item.tld,
        item.title,
        item.brand,
        item.size,
        item.condition,
        _real(item.price),
        _real(item.total_price),
        item.currency,
        item.url,
        item.photo_url,
        json.dumps(list(item.photo_urls)) if item.photo_urls else None,
        item.photo_ts,
        item.seller_login,
        item.seller_id,
        item.seller_rating,
        item.seller_feedback_count,
        item.favourite_count,
        item.view_count,
        json.dumps(item.raw) if (keep_raw and item.raw) else None,
        now,
    )


# The highest `seq` ever handed out, saved before housekeeping deletes listings. Without
# it a quiet month empties `items` and numbering restarts at 1, below the cursor an open
# dashboard tab resumes from, so it would miss every find until the count caught up.
_SEQ_FLOOR_KEY = "items_seq_floor"

# Every insert of a listing goes through this, so `seq` — the feed's cursor — is always
# assigned. Writes are serialised on one connection, so MAX(seq) + 1 cannot race.
# A second search finding a stored listing may know its seller's country when the first
# did not, so that one column is filled in on a conflict.
_INSERT_ITEM = (
    "INSERT INTO items (item_id, tld, title, brand, size, condition, price, total_price, "
    "currency, url, photo_url, photo_urls_json, photo_ts, seller_login, seller_id, "
    "seller_rating, seller_feedback_count, favourite_count, view_count, raw_json, "
    "first_seen_at, query_id, typical_price, seller_country, watch_id, seq) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
    f"(SELECT MAX(COALESCE(MAX(seq), 0), "
    f"COALESCE((SELECT CAST(value AS INTEGER) FROM app_state WHERE key = '{_SEQ_FLOOR_KEY}'), 0)"
    ") + 1 FROM items)) "
    "ON CONFLICT(item_id) DO UPDATE SET "
    "seller_country = COALESCE(items.seller_country, excluded.seller_country)"
)

# A listing is shown under the first search that matched it, with that search's typical
# price: two searches can disagree about what the same listing is worth.
_FEED_SELECT = (
    "SELECT i.*, m.mark, q.id AS feed_query_id, q.name AS feed_query_name, "
    "q.color AS feed_query_color, "
    "CASE WHEN fqi.query_id IS NULL THEN i.typical_price ELSE fqi.typical_price END "
    "AS feed_typical_price FROM items i "
    "LEFT JOIN item_marks m ON m.item_id = i.item_id "
    "LEFT JOIN query_items fqi ON fqi.rowid = ("
    "  SELECT qi.rowid FROM query_items qi "
    "  WHERE qi.item_id = i.item_id AND qi.status = 'matched' "
    "  ORDER BY qi.first_seen_at LIMIT 1) "
    "LEFT JOIN queries q ON q.id = fqi.query_id "
)

# A listing belongs in the feed if a search matched it or a seller watch turned it up.
# Listings seeded by a first check, or stored only so an item watch can render, do not.
_IN_FEED = (
    "(i.watch_id IS NOT NULL OR EXISTS (SELECT 1 FROM query_items qi "
    "WHERE qi.item_id = i.item_id AND qi.status = 'matched'))"
)


def _feed_item(row: aiosqlite.Row) -> FeedItem:
    return FeedItem(
        seq=row["seq"] or 0,
        item=_item_from_row(row),
        first_seen_at=row["first_seen_at"],
        query_id=row["feed_query_id"],
        query_name=row["feed_query_name"],
        query_color=row["feed_query_color"],
        watch_id=row["watch_id"],
        typical_price=_money(row["feed_typical_price"]),
        seller_country=row["seller_country"],
        mark=row["mark"],
    )


def _pending(row: aiosqlite.Row) -> PendingNotification:
    """A claimed outbox row, joined with its listing and search, ready to render."""
    item = _item_from_row(row)
    return PendingNotification(
        outbox_id=row["outbox_id"],
        destination_id=row["destination_id"],
        query_id=row["outbox_query_id"],
        query_name=row["query_name"] or row["watch_label"] or "search",
        attempts=row["attempts"],
        item=item,
        detected_at=row["search_first_seen_at"] or row["first_seen_at"],
        query_color=row["query_color"],
        typical_price=_money(row["search_typical_price"]),
        silent=bool(row["silent"]),
        kind=row["outbox_kind"],
        previous_price=_money(row["previous_price"]),
        watch_id=row["outbox_watch_id"],
        margin=margin(
            item.total_price if item.total_price is not None else item.price,
            item.currency,
            site=row["query_tld"] or item.tld,
            resale_price=_money(row["resale_price"]),
            fee_pct=row["resale_fee_pct"],
            shipping=_money(row["resale_shipping"]),
        ),
    )


def _percentile(sorted_values: list[int], fraction: float) -> int:
    index = min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))
    return sorted_values[index]


class Repo:
    """Data access for the whole app."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- Searches ------------------------------------------------------------------

    async def add_query(
        self,
        *,
        name: str,
        url: str,
        tld: str,
        params: dict[str, str],
        poll_interval_s: int,
        banned_keywords: list[str] | None = None,
        max_total_price: Decimal | None = None,
        **filters: Any,
    ) -> int:
        """Store a new search. Raises `InvalidInputError` for anything it cannot hold.

        `filters` takes any other `Query` field by name — include_terms, regex,
        quiet_start and the rest — so callers name what they set and nothing else.
        """
        count = int(await self._db.fetch_value("SELECT COUNT(*) FROM queries") or 0)
        filters.setdefault("color", PALETTE[count % len(PALETTE)])
        query = _validated(
            Query(
                id=0,
                name=name,
                url=url,
                tld=tld,
                params=params,
                poll_interval_s=poll_interval_s,
                paused=False,
                banned_keywords=banned_keywords or [],
                max_total_price=max_total_price,
                **filters,
            )
        )
        columns = _query_columns(query)
        now = int(time.time())
        names = [*columns, "created_at", "updated_at"]
        async with self._db.transaction() as conn:
            cursor = await conn.execute(
                f"INSERT INTO queries ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                (*columns.values(), now, now),
            )
            query_id = cursor.lastrowid or 0
            await conn.execute("INSERT INTO query_state (query_id) VALUES (?)", (query_id,))
        return query_id

    async def update_query(self, query: Query) -> Query:
        """Save every editable field of a search. Returns it as stored.

        Takes a whole `Query` — usually `dataclasses.replace(await get_query(id), ...)` —
        so an edit form cannot forget a field and blank it. The running poller notices
        the change on the supervisor's next pass and restarts with the new rules.

        Changing what the search fetches (its link, site or extra sites) makes it a
        different search as far as "new" goes: its floor belonged to the old results, so
        the next check starts over and records the page without announcing it, and its
        typical price starts again from the new results.
        """
        stored = _validated(query)
        columns = _query_columns(stored)
        assignments = ", ".join(f"{name} = ?" for name in columns)
        now = int(time.time())
        async with self._db.transaction() as conn:
            async with conn.execute(
                f"SELECT {', '.join(_FETCH_COLUMNS)} FROM queries WHERE id = ?", (stored.id,)
            ) as cursor:
                before = await cursor.fetchone()
            await conn.execute(
                f"UPDATE queries SET {assignments}, updated_at = ? WHERE id = ?",
                (*columns.values(), now, stored.id),
            )
            if before is not None and any(before[name] != columns[name] for name in _FETCH_COLUMNS):
                await conn.execute(
                    "UPDATE query_state SET last_success_at = NULL, floor_item_id = NULL, "
                    "newest_raw_id = NULL, raw_advanced_at = NULL, stale_cycles = 0, "
                    "history_from = ? WHERE query_id = ?",
                    (now, stored.id),
                )
        return stored

    async def duplicate_query(self, query_id: int, *, name: str | None = None) -> int | None:
        """Copy a search with its routes, paused, so it can be changed before it runs.

        The copy starts from scratch: it seeds silently on its first check like any new
        search, rather than inheriting what the original has already seen.
        """
        original = await self.get_query(query_id)
        if original is None:
            return None
        copy_id = await self.add_query(
            name=name or f"{original.name} (copy)"[: validation.MAX_NAME_LENGTH],
            url=original.url,
            tld=original.tld,
            params=original.params,
            poll_interval_s=original.poll_interval_s,
            banned_keywords=original.banned_keywords,
            max_total_price=original.max_total_price,
            include_terms=original.include_terms,
            regex=original.regex,
            min_total_price=original.min_total_price,
            conditions=original.conditions,
            countries=original.countries,
            seller_min_rating=original.seller_min_rating,
            seller_min_reviews=original.seller_min_reviews,
            skip_unrated_sellers=original.skip_unrated_sellers,
            deal_only_pct=original.deal_only_pct,
            max_age_min=original.max_age_min,
            color=original.color,
            quiet_start=original.quiet_start,
            quiet_end=original.quiet_end,
            quiet_mode=original.quiet_mode,
            notes=original.notes,
            tags=original.tags,
            extra_tlds=original.extra_tlds,
            resale_price=original.resale_price,
            resale_fee_pct=original.resale_fee_pct,
            resale_shipping=original.resale_shipping,
            min_margin=original.min_margin,
        )
        await self.set_paused(copy_id, True)
        await self._db.execute(
            "INSERT INTO query_destinations (query_id, destination_id) "
            "SELECT ?, destination_id FROM query_destinations WHERE query_id = ?",
            (copy_id, query_id),
        )
        return copy_id

    async def list_queries(self, *, include_paused: bool = True) -> list[Query]:
        sql = "SELECT * FROM queries"
        if not include_paused:
            sql += " WHERE paused = 0"
        return [self._to_query(row) for row in await self._db.fetch_all(sql + " ORDER BY id")]

    async def get_query(self, query_id: int) -> Query | None:
        row = await self._db.fetch_one("SELECT * FROM queries WHERE id = ?", (query_id,))
        return self._to_query(row) if row else None

    async def find_query_by_url(self, url: str) -> Query | None:
        row = await self._db.fetch_one(
            "SELECT * FROM queries WHERE url = ? ORDER BY id LIMIT 1", (url,)
        )
        return self._to_query(row) if row else None

    async def set_paused(self, query_id: int, paused: bool) -> None:
        await self._db.execute(
            "UPDATE queries SET paused = ?, updated_at = ? WHERE id = ?",
            (int(paused), int(time.time()), query_id),
        )

    async def mute_query(self, query_id: int, until: int) -> None:
        """Announce nothing from this search until `until`, starting with what is queued.

        What is already waiting goes too: someone who mutes a search from an alert wants
        the next hour quiet, not the backlog delivered first.
        """
        async with self._db.transaction() as conn:
            await conn.execute("UPDATE queries SET muted_until = ? WHERE id = ?", (until, query_id))
            await conn.execute(
                "UPDATE outbox SET status = 'cancelled', last_error = 'search muted' "
                "WHERE query_id = ? AND status = 'pending' AND kind = 'listing'",
                (query_id,),
            )

    async def delete_query(self, query_id: int) -> None:
        await self._db.execute("DELETE FROM queries WHERE id = ?", (query_id,))

    @staticmethod
    def _to_query(row: aiosqlite.Row) -> Query:
        return Query(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            tld=row["tld"],
            params=json.loads(row["params_json"]),
            poll_interval_s=row["poll_interval_s"],
            paused=bool(row["paused"]),
            banned_keywords=_json_list(row["banned_keywords_json"]) or [],
            max_total_price=_money(row["max_total_price"]),
            conditions=_json_list(row["conditions_json"]),
            countries=_json_list(row["countries_json"]),
            include_terms=_json_list(row["include_terms_json"]) or [],
            regex=row["regex"],
            min_total_price=_money(row["min_total_price"]),
            seller_min_rating=row["seller_min_rating"],
            seller_min_reviews=row["seller_min_reviews"],
            skip_unrated_sellers=bool(row["skip_unrated_sellers"]),
            deal_only_pct=row["deal_only_pct"],
            max_age_min=row["max_age_min"],
            color=row["color"],
            quiet_start=row["quiet_start"],
            quiet_end=row["quiet_end"],
            quiet_mode=row["quiet_mode"],
            notes=row["notes"],
            tags=_json_list(row["tags_json"]) or [],
            extra_tlds=_json_list(row["extra_tlds_json"]) or [],
            resale_price=_money(row["resale_price"]),
            resale_fee_pct=row["resale_fee_pct"],
            resale_shipping=_money(row["resale_shipping"]),
            min_margin=_money(row["min_margin"]),
            muted_until=row["muted_until"],
        )

    # --- Search state --------------------------------------------------------------

    async def get_state(self, query_id: int) -> QueryState:
        row = await self._db.fetch_one("SELECT * FROM query_state WHERE query_id = ?", (query_id,))
        if row is None:
            await self._db.execute(
                "INSERT OR IGNORE INTO query_state (query_id) VALUES (?)", (query_id,)
            )
            return QueryState(query_id=query_id)
        return self._to_state(row)

    async def all_states(self) -> list[QueryState]:
        return [
            self._to_state(row) for row in await self._db.fetch_all("SELECT * FROM query_state")
        ]

    @staticmethod
    def _to_state(row: aiosqlite.Row) -> QueryState:
        return QueryState(
            query_id=row["query_id"],
            last_polled_at=row["last_polled_at"],
            last_success_at=row["last_success_at"],
            last_status=row["last_status"],
            last_error=row["last_error"],
            newest_item_ts=row["newest_item_ts"],
            newest_raw_ts=row["newest_raw_ts"],
            stale_cycles=row["stale_cycles"],
            items_seen_total=row["items_seen_total"],
            count_403=row["count_403"],
            count_429=row["count_429"],
            floor_item_id=row["floor_item_id"],
            newest_raw_id=row["newest_raw_id"],
            raw_advanced_at=row["raw_advanced_at"],
        )

    async def record_failure(self, query_id: int, status: str, error: str) -> None:
        """Note a failed check. The counters feed the health view and the troubleshooting docs."""
        column = {"http_403": "count_403", "http_429": "count_429"}.get(status)
        bump = f", {column} = {column} + 1" if column else ""
        await self._db.execute(
            "UPDATE query_state SET last_polled_at = ?, last_status = ?, last_error = ?"
            f"{bump} WHERE query_id = ?",
            (int(time.time()), status, error[:500], query_id),
        )

    async def record_success(
        self,
        query_id: int,
        *,
        newest_raw_ts: int | None,
        newest_item_ts: int | None,
        seen: int,
        stale_cycles: int,
        newest_raw_id: int | None = None,
        floor_item_id: int | None = None,
    ) -> None:
        now = int(time.time())
        await self._db.execute(
            "UPDATE query_state SET last_polled_at = ?, last_success_at = ?, last_status = 'ok', "
            "last_error = NULL, newest_raw_ts = ?, "
            "newest_item_ts = COALESCE(?, newest_item_ts), "
            "raw_advanced_at = CASE WHEN ? IS NOT NULL AND newest_raw_id IS NOT ? "
            "  THEN ? ELSE raw_advanced_at END, "
            "newest_raw_id = COALESCE(?, newest_raw_id), "
            "floor_item_id = COALESCE(?, floor_item_id), "
            "items_seen_total = items_seen_total + ?, stale_cycles = ? WHERE query_id = ?",
            (
                now,
                now,
                newest_raw_ts,
                newest_item_ts,
                newest_raw_id,
                newest_raw_id,
                now,
                newest_raw_id,
                floor_item_id,
                seen,
                stale_cycles,
                query_id,
            ),
        )
        if newest_raw_id is not None:
            await self.note_listing_id(newest_raw_id, now=now)

    async def note_listing_id(self, item_id: int, *, now: int | None = None) -> None:
        """Record that a listing id existed at this moment, if it is the newest seen yet.

        Ids are handed out in upload order, so every lower id existed then too. Thinned to
        one step a minute: a coarser step only makes the "already listed by" answer later,
        never earlier, so it can never call a fresh listing old.
        """
        at = now if now is not None else int(time.time())
        await self._db.execute(
            "INSERT INTO id_clock (item_id, seen_at) SELECT ?, ? "
            "WHERE ? > COALESCE((SELECT MAX(item_id) FROM id_clock), 0) "
            "AND ? >= COALESCE((SELECT MAX(seen_at) FROM id_clock), 0) + ?",
            (item_id, at, item_id, at, _ID_CLOCK_STEP_S),
        )

    async def listed_by(self, item_ids: list[int]) -> dict[int, int]:
        """For each listing id, the earliest moment it is known to have been on Vinted.

        Known because some check saw a newer id by then; ids are given out in upload
        order. Missing for ids newer than anything seen, whose age nothing here can tell.
        """
        if not item_ids:
            return {}
        values = ",".join(["(?)"] * len(item_ids))
        rows = await self._db.fetch_all(
            f"WITH wanted(id) AS (VALUES {values}) SELECT id, "
            "(SELECT c.seen_at FROM id_clock c WHERE c.item_id >= wanted.id "
            " ORDER BY c.item_id LIMIT 1) AS seen_at FROM wanted",
            item_ids,
        )
        return {row["id"]: row["seen_at"] for row in rows if row["seen_at"] is not None}

    # --- Destinations --------------------------------------------------------------

    async def add_destination(
        self,
        *,
        kind: str,
        name: str,
        config: dict[str, Any],
        notify_status: bool = False,
    ) -> int:
        return await self._db.insert(
            "INSERT INTO destinations (kind, name, config_json, notify_status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, name, json.dumps(config), int(notify_status), int(time.time())),
        )

    async def list_destinations(self, *, active_only: bool = False) -> list[Destination]:
        sql = "SELECT * FROM destinations"
        if active_only:
            sql += " WHERE active = 1"
        return [self._to_destination(row) for row in await self._db.fetch_all(sql + " ORDER BY id")]

    async def get_destination(self, destination_id: int) -> Destination | None:
        row = await self._db.fetch_one("SELECT * FROM destinations WHERE id = ?", (destination_id,))
        return self._to_destination(row) if row else None

    async def update_destination_config(self, destination_id: int, config: dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE destinations SET config_json = ? WHERE id = ?",
            (json.dumps(config), destination_id),
        )

    async def deactivate_destination(self, destination_id: int, reason: str) -> None:
        """Stop sending to a destination for good.

        Used when the far end says the target is gone — a deleted webhook, a bot the user
        blocked. Retrying those forever is what gets an address rate-limited or banned.
        """
        await self._db.execute(
            "UPDATE destinations SET active = 0, deactivated_reason = ? WHERE id = ?",
            (reason[:500], destination_id),
        )
        await self._db.execute(
            "UPDATE outbox SET status = 'cancelled', last_error = ? "
            "WHERE destination_id = ? AND status IN ('pending', 'sending')",
            (f"destination disabled: {reason[:200]}", destination_id),
        )

    async def note_destination_failure(self, destination_id: int) -> None:
        await self._db.execute(
            "UPDATE destinations SET failure_count = failure_count + 1 WHERE id = ?",
            (destination_id,),
        )

    async def reset_destination_failures(self, destination_id: int) -> None:
        await self._db.execute(
            "UPDATE destinations SET failure_count = 0 WHERE id = ?", (destination_id,)
        )

    @staticmethod
    def _to_destination(row: aiosqlite.Row) -> Destination:
        return Destination(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            config=json.loads(row["config_json"]),
            active=bool(row["active"]),
            notify_status=bool(row["notify_status"]),
            failure_count=row["failure_count"],
            deactivated_reason=row["deactivated_reason"],
        )

    # --- Routing -------------------------------------------------------------------

    async def route(self, query_id: int, destination_id: int) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO query_destinations (query_id, destination_id) VALUES (?, ?)",
            (query_id, destination_id),
        )

    async def unroute(self, query_id: int, destination_id: int) -> None:
        await self._db.execute(
            "DELETE FROM query_destinations WHERE query_id = ? AND destination_id = ?",
            (query_id, destination_id),
        )

    async def set_routes(self, query_id: int, destination_ids: Iterable[int]) -> list[int]:
        """Replace a search's routes in one go; empty means "every destination".

        Ids that name no destination are dropped rather than failing halfway through,
        which used to leave a search half-routed after a stale form was submitted.
        Returns the routes as stored.
        """
        wanted = sorted(set(destination_ids))
        async with self._db.transaction() as conn:
            await conn.execute("DELETE FROM query_destinations WHERE query_id = ?", (query_id,))
            if wanted:
                placeholders = ",".join("?" * len(wanted))
                await conn.execute(
                    "INSERT INTO query_destinations (query_id, destination_id) "
                    f"SELECT ?, id FROM destinations WHERE id IN ({placeholders}) "
                    "AND EXISTS (SELECT 1 FROM queries WHERE id = ?)",
                    (query_id, *wanted, query_id),
                )
        return await self.explicit_routes(query_id)

    async def explicit_routes(self, query_id: int) -> list[int]:
        """The destinations someone picked for a search; empty means "all of them"."""
        rows = await self._db.fetch_all(
            "SELECT destination_id FROM query_destinations WHERE query_id = ? "
            "ORDER BY destination_id",
            (query_id,),
        )
        return [row["destination_id"] for row in rows]

    async def destination_ids_for_query(self, query_id: int) -> list[int]:
        """Where a search's alerts go.

        A search nobody routed goes to every active destination. Searches added before
        any destination existed used to stay silent forever, and the obvious order of
        setting things up — paste a search, then add Discord — is exactly that case.
        """
        rows = await self._db.fetch_all(
            "SELECT d.id FROM destinations d "
            "JOIN query_destinations qd ON qd.destination_id = d.id "
            "WHERE qd.query_id = ? AND d.active = 1 ORDER BY d.id",
            (query_id,),
        )
        if rows:
            return [row["id"] for row in rows]
        return await self._default_destinations(
            "SELECT 1 FROM queries q WHERE q.id = ? AND NOT EXISTS "
            "(SELECT 1 FROM query_destinations qd WHERE qd.query_id = q.id)",
            query_id,
        )

    async def _default_destinations(self, unrouted_sql: str, owner_id: int) -> list[int]:
        """Every active destination, if `unrouted_sql` confirms the owner has no routes."""
        if await self._db.fetch_one(unrouted_sql, (owner_id,)) is None:
            return []
        rows = await self._db.fetch_all("SELECT id FROM destinations WHERE active = 1 ORDER BY id")
        return [row["id"] for row in rows]

    async def status_destination_ids(self) -> list[int]:
        rows = await self._db.fetch_all(
            "SELECT id FROM destinations WHERE active = 1 AND notify_status = 1"
        )
        return [row["id"] for row in rows]

    # --- Items and the outbox ------------------------------------------------------

    async def known_item_ids(self, item_ids: list[int]) -> set[int]:
        """Which of these listings have we stored, for any reason?"""
        if not item_ids:
            return set()
        placeholders = ",".join("?" * len(item_ids))
        rows = await self._db.fetch_all(
            f"SELECT item_id FROM items WHERE item_id IN ({placeholders})", item_ids
        )
        return {row["item_id"] for row in rows}

    async def seen_by_query(self, query_id: int, item_ids: list[int]) -> set[int]:
        """Which of these listings has this search already made its mind up about?

        Per search, not global: a listing another search found is still news to this
        one's destinations. The outbox's one-per-destination rule stops anyone hearing
        about it twice.
        """
        if not item_ids:
            return set()
        placeholders = ",".join("?" * len(item_ids))
        rows = await self._db.fetch_all(
            f"SELECT item_id FROM query_items WHERE query_id = ? AND item_id IN ({placeholders})",
            (query_id, *item_ids),
        )
        return {row["item_id"] for row in rows}

    async def record_new_items(
        self,
        query: Query,
        items: list[Item],
        destination_ids: list[int],
        *,
        notify: list[Item] | None = None,
        seeded: bool = False,
        rejected: Sequence[RejectedListing] = (),
        typical_prices: Mapping[str, Decimal] | None = None,
        seller_countries: Mapping[int, str] | None = None,
        hold_until: int | None = None,
        silent: bool = False,
        keep_raw: bool = False,
    ) -> int:
        """Store what a check decided and queue its notifications, in one transaction.

        Doing it all at once is what makes a crash safe: either a listing is recorded and
        its notifications are queued, or neither happened and the next check finds it again.

        `notify` is the subset worth telling someone about, which is not always everything
        being recorded: a search's first check records the whole page (`seeded`) so those
        listings are never mistaken for new, while announcing at most one of them; deal-only
        searches record every match but announce only the deals. Passing None means every
        recorded listing is announced.

        `hold_until` queues the notifications for later (quiet hours in hold mode) and
        `silent` asks for a soundless delivery (silent mode).
        """
        if not items and not rejected:
            return 0

        to_announce = items if notify is None else notify
        announced_ids = {item.item_id for item in to_announce} if destination_ids else set()
        prices = typical_prices or {}
        countries = seller_countries or {}
        now = int(time.time())

        async with self._db.transaction() as conn:
            await conn.executemany(
                _INSERT_ITEM,
                [
                    (
                        *_item_values(item, now, keep_raw=keep_raw),
                        query.id,
                        _real(prices.get(item.currency or "")),
                        countries.get(item.seller_id) if item.seller_id is not None else None,
                        None,
                    )
                    for item in items
                ],
            )
            await conn.executemany(
                "INSERT OR IGNORE INTO query_items "
                "(query_id, item_id, status, announced, first_seen_at, typical_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        query.id,
                        item.item_id,
                        "seeded" if seeded and item.item_id not in announced_ids else "matched",
                        int(item.item_id in announced_ids),
                        now,
                        _real(prices.get(item.currency or "")),
                    )
                    for item in items
                ],
            )
            # A listing logged as skipped while its seller could not be looked up, and
            # matched since, should not still claim to have been skipped.
            await conn.executemany(
                "DELETE FROM rejections WHERE query_id = ? AND item_id = ?",
                [(query.id, item.item_id) for item in items],
            )
            await self._write_rejections(conn, query.id, rejected, now)

            if announced_ids:
                await conn.executemany(
                    "INSERT OR IGNORE INTO outbox (item_id, query_id, destination_id, kind, "
                    "silent, held_until, next_attempt_at, created_at) "
                    "VALUES (?, ?, ?, 'listing', ?, ?, ?, ?)",
                    [
                        (
                            item.item_id,
                            query.id,
                            destination_id,
                            int(silent),
                            hold_until,
                            hold_until or now,
                            now,
                        )
                        for item in to_announce
                        for destination_id in destination_ids
                    ],
                )
        return len(items)

    @staticmethod
    async def _write_rejections(
        conn: aiosqlite.Connection,
        query_id: int,
        rejected: Sequence[RejectedListing],
        now: int,
    ) -> None:
        if not rejected:
            return
        await conn.executemany(
            "INSERT INTO rejections (query_id, item_id, reason, detail, title, total_price, "
            "currency, photo_url, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(query_id, item_id) DO UPDATE SET "
            "reason = excluded.reason, detail = excluded.detail",
            [
                (
                    query_id,
                    entry.item.item_id,
                    entry.reason,
                    entry.detail[:500],
                    entry.item.title,
                    _real(entry.item.total_price or entry.item.price),
                    entry.item.currency,
                    entry.item.photo_url,
                    entry.item.url,
                    now,
                )
                for entry in rejected
            ],
        )
        await conn.executemany(
            "INSERT OR IGNORE INTO query_items "
            "(query_id, item_id, status, announced, first_seen_at) "
            "VALUES (?, ?, 'rejected', 0, ?)",
            [(query_id, entry.item.item_id, now) for entry in rejected if entry.final],
        )

    async def typical_prices(self, query_id: int, *, now: int | None = None) -> dict[str, Decimal]:
        """The median total price of what a search found lately, per currency.

        Per currency because a search running on vinted.fr and vinted.co.uk sees euros and
        pounds, and a median of both is a number nobody has paid. One query per check,
        however many listings it turned up.
        """
        since = (now or int(time.time())) - TYPICAL_PRICE_WINDOW_S
        rows = await self._db.fetch_all(
            "SELECT i.currency, i.total_price FROM query_items qi "
            "JOIN items i ON i.item_id = qi.item_id "
            "WHERE qi.query_id = ? AND qi.status IN ('seeded', 'matched') "
            "AND qi.first_seen_at >= ? AND qi.first_seen_at > COALESCE("
            "  (SELECT s.history_from FROM query_state s WHERE s.query_id = qi.query_id), 0) "
            "AND i.total_price IS NOT NULL AND i.currency IS NOT NULL",
            (query_id, since),
        )
        by_currency: dict[str, list[Decimal]] = defaultdict(list)
        for row in rows:
            by_currency[row["currency"]].append(Decimal(str(row["total_price"])))
        return {
            currency: statistics.median(prices).quantize(_CENT)
            for currency, prices in by_currency.items()
            if len(prices) >= TYPICAL_PRICE_MIN_SAMPLES
        }

    async def prune_items(self, older_than_days: int) -> int:
        """Forget old listings, except the ones someone saved or is watching.

        A search's record of what it has decided about is only forgotten below its floor,
        where the floor alone keeps a listing from being judged again. Above it, a match
        still for sale after a month would otherwise come back as a new find.
        """
        cutoff = int(time.time()) - older_than_days * 86_400
        async with self._db.transaction() as conn:
            await conn.execute(
                "DELETE FROM query_items WHERE first_seen_at < ? AND item_id <= COALESCE("
                "(SELECT s.floor_item_id FROM query_state s "
                " WHERE s.query_id = query_items.query_id), -1)",
                (cutoff,),
            )
            await conn.execute(
                "DELETE FROM id_clock WHERE seen_at < ? "
                "AND item_id < (SELECT MAX(item_id) FROM id_clock)",
                (cutoff,),
            )
            async with conn.execute("SELECT MAX(seq) FROM items") as seq_cursor:
                highest = await seq_cursor.fetchone()
            if highest is not None and highest[0] is not None:
                await conn.execute(
                    "INSERT INTO app_state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = CAST(MAX("
                    "CAST(value AS INTEGER), CAST(excluded.value AS INTEGER)) AS TEXT)",
                    (_SEQ_FLOOR_KEY, str(highest[0])),
                )
            cursor = await conn.execute(
                "DELETE FROM items WHERE first_seen_at < ? "
                "AND item_id NOT IN (SELECT item_id FROM item_marks WHERE mark = 'saved') "
                "AND item_id NOT IN (SELECT target_id FROM watches WHERE kind = 'item')",
                (cutoff,),
            )
            return max(cursor.rowcount, 0)

    async def recent_items(self, limit: int = 50) -> list[aiosqlite.Row]:
        return await self._db.fetch_all(
            "SELECT i.*, q.name AS query_name FROM items i "
            "LEFT JOIN queries q ON q.id = i.query_id "
            "ORDER BY i.first_seen_at DESC LIMIT ?",
            (limit,),
        )

    # --- Outbox delivery -----------------------------------------------------------

    async def destinations_with_work(self) -> list[int]:
        rows = await self._db.fetch_all(
            "SELECT DISTINCT destination_id FROM outbox "
            "WHERE status = 'pending' AND next_attempt_at <= ?",
            (int(time.time()),),
        )
        return [row["destination_id"] for row in rows]

    async def claim_batch(
        self, destination_id: int, limit: int, *, lease_seconds: int = 120
    ) -> list[PendingNotification]:
        """Take the next few notifications for a destination.

        Ordered by insertion so listings arrive in the order they were found, and leased so
        that a process killed mid-send does not strand them.
        """
        now = int(time.time())
        async with self._db.transaction() as conn:
            async with conn.execute(
                "SELECT o.id AS outbox_id, o.destination_id, o.query_id AS outbox_query_id, "
                "o.watch_id AS outbox_watch_id, o.attempts, o.kind AS outbox_kind, "
                "o.previous_price, o.silent, q.name AS query_name, q.color AS query_color, "
                "q.tld AS query_tld, q.resale_price, q.resale_fee_pct, q.resale_shipping, "
                "w.label AS watch_label, qi.first_seen_at AS search_first_seen_at, "
                "CASE WHEN o.query_id IS NULL THEN i.typical_price ELSE qi.typical_price END "
                "AS search_typical_price, i.* FROM outbox o "
                "JOIN items i ON i.item_id = o.item_id "
                "LEFT JOIN queries q ON q.id = o.query_id "
                "LEFT JOIN query_items qi ON qi.query_id = o.query_id AND qi.item_id = o.item_id "
                "LEFT JOIN watches w ON w.id = o.watch_id "
                "WHERE o.destination_id = ? AND o.status = 'pending' AND o.next_attempt_at <= ? "
                "ORDER BY o.id LIMIT ?",
                (destination_id, now, limit),
            ) as cursor:
                rows = list(await cursor.fetchall())

            if rows:
                await conn.executemany(
                    "UPDATE outbox SET status = 'sending', lease_expires_at = ? WHERE id = ?",
                    [(now + lease_seconds, row["outbox_id"]) for row in rows],
                )

        return [_pending(row) for row in rows]

    async def mark_sent(self, outbox_ids: list[int]) -> None:
        if not outbox_ids:
            return
        now = int(time.time())
        await self._db.execute_many(
            "UPDATE outbox SET status = 'sent', sent_at = ?, lease_expires_at = NULL WHERE id = ?",
            [(now, outbox_id) for outbox_id in outbox_ids],
        )

    async def mark_retry(self, outbox_ids: list[int], *, delay_s: float, error: str) -> None:
        """Put notifications back in the queue after a failure."""
        if not outbox_ids:
            return
        next_attempt = int(time.time() + delay_s)
        await self._db.execute_many(
            "UPDATE outbox SET status = 'pending', attempts = attempts + 1, "
            "next_attempt_at = ?, lease_expires_at = NULL, last_error = ? WHERE id = ?",
            [(next_attempt, error[:500], outbox_id) for outbox_id in outbox_ids],
        )

    async def mark_failed(self, outbox_ids: list[int], error: str) -> None:
        if not outbox_ids:
            return
        await self._db.execute_many(
            "UPDATE outbox SET status = 'failed', lease_expires_at = NULL, last_error = ? "
            "WHERE id = ?",
            [(error[:500], outbox_id) for outbox_id in outbox_ids],
        )

    async def mark_cancelled(self, outbox_ids: list[int], reason: str) -> None:
        """Take notifications out of the queue on purpose: not sent, and not a failure.

        For alerts a destination asked not to get, such as a non-deal for a destination
        that only wants steals. Counting those as failures made healthy destinations look
        broken on the alerts and stats pages.
        """
        if not outbox_ids:
            return
        await self._db.execute_many(
            "UPDATE outbox SET status = 'cancelled', lease_expires_at = NULL, last_error = ? "
            "WHERE id = ?",
            [(reason[:500], outbox_id) for outbox_id in outbox_ids],
        )

    async def discard_pending_for(self, destination_id: int, reason: str) -> int:
        """Throw away what is queued for a destination without sending it."""
        return await self._db.execute(
            "UPDATE outbox SET status = 'cancelled', last_error = ? "
            "WHERE destination_id = ? AND status = 'pending'",
            (reason[:500], destination_id),
        )

    async def recover_leases(self) -> int:
        """Return notifications stranded by a crash to the queue. Run once at startup.

        Anything still marked as sending was interrupted mid-flight: this process is the
        only writer, and it has only just started, so no live worker can be holding one.
        """
        return await self._db.execute(
            "UPDATE outbox SET status = 'pending', lease_expires_at = NULL WHERE status = 'sending'"
        )

    async def expire_stale_notifications(self, older_than_minutes: int) -> int:
        """Drop notifications too old to be worth sending.

        An alert about a listing from two hours ago is not news, and quietly flushing them
        keeps a destination that was offline from dumping its whole backlog on return. Age
        counts from the end of quiet hours for anything held through them.
        """
        cutoff = int(time.time()) - older_than_minutes * 60
        return await self._db.execute(
            "UPDATE outbox SET status = 'cancelled', last_error = 'expired before delivery' "
            "WHERE status = 'pending' AND COALESCE(held_until, created_at) < ?",
            (cutoff,),
        )

    async def outbox_depth(self) -> int:
        value = await self._db.fetch_value(
            "SELECT COUNT(*) FROM outbox WHERE status IN ('pending', 'sending')"
        )
        return int(value or 0)

    async def notifications_due(self, now: int) -> int:
        """Notifications being sent, or waiting to be sent, right now.

        Not the whole outbox: one held for quiet hours or waiting out a retry delay is
        safe in the database across a restart, and counting those would keep anyone with
        overnight quiet hours from ever being updated at night.
        """
        value = await self._db.fetch_value(
            "SELECT COUNT(*) FROM outbox WHERE status = 'sending' "
            "OR (status = 'pending' AND next_attempt_at <= ?)",
            (now,),
        )
        return int(value or 0)

    # --- Sellers -------------------------------------------------------------------

    async def cached_seller(self, seller_id: int, *, max_age_s: int) -> SellerProfile | None:
        row = await self._db.fetch_one(
            "SELECT * FROM seller_cache WHERE seller_id = ? AND fetched_at >= ?",
            (seller_id, int(time.time()) - max_age_s),
        )
        if row is None:
            return None
        return SellerProfile(
            seller_id=row["seller_id"],
            tld=row["tld"],
            login=row["login"],
            country_code=row["country"],
            rating=row["rating"],
            feedback_count=row["reviews"],
        )

    async def cache_seller(self, profile: SellerProfile) -> None:
        await self._db.execute(
            "INSERT INTO seller_cache (seller_id, tld, country, rating, reviews, login, "
            "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(seller_id) DO UPDATE SET tld = excluded.tld, "
            "country = excluded.country, rating = excluded.rating, "
            "reviews = excluded.reviews, login = excluded.login, fetched_at = excluded.fetched_at",
            (
                profile.seller_id,
                profile.tld,
                profile.country_code,
                profile.rating,
                profile.feedback_count,
                profile.login,
                int(time.time()),
            ),
        )

    async def block_seller(
        self,
        seller_id: int,
        *,
        login: str | None = None,
        tld: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Never alert on this seller again, in any search."""
        await self._db.execute(
            "INSERT INTO blocked_sellers (seller_id, login, tld, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(seller_id) DO UPDATE SET "
            "login = COALESCE(excluded.login, login), reason = excluded.reason",
            (seller_id, login, tld, reason, int(time.time())),
        )

    async def unblock_seller(self, seller_id: int) -> None:
        await self._db.execute("DELETE FROM blocked_sellers WHERE seller_id = ?", (seller_id,))

    async def list_blocked_sellers(self) -> list[BlockedSeller]:
        rows = await self._db.fetch_all("SELECT * FROM blocked_sellers ORDER BY created_at DESC")
        return [
            BlockedSeller(
                seller_id=row["seller_id"],
                login=row["login"],
                tld=row["tld"],
                reason=row["reason"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def blocked_seller_ids(self) -> set[int]:
        rows = await self._db.fetch_all("SELECT seller_id FROM blocked_sellers")
        return {row["seller_id"] for row in rows}

    # --- Marks and rejections ------------------------------------------------------

    async def set_mark(self, item_id: int, mark: Mark | None) -> None:
        """Save or hide a listing in the dashboard; None clears it."""
        if mark is None:
            await self._db.execute("DELETE FROM item_marks WHERE item_id = ?", (item_id,))
            return
        await self._db.execute(
            "INSERT INTO item_marks (item_id, mark, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET mark = excluded.mark, "
            "created_at = excluded.created_at",
            (item_id, mark, int(time.time())),
        )

    async def rejections_for(self, query_id: int, *, limit: int = 100) -> list[RejectionRecord]:
        """The listings a search skipped most recently, and why."""
        rows = await self._db.fetch_all(
            "SELECT * FROM rejections WHERE query_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (query_id, limit),
        )
        return [
            RejectionRecord(
                id=row["id"],
                query_id=row["query_id"],
                item_id=row["item_id"],
                reason=row["reason"],
                detail=row["detail"],
                title=row["title"],
                total_price=_money(row["total_price"]),
                currency=row["currency"],
                photo_url=row["photo_url"],
                url=row["url"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def rejection_counts(self, query_id: int, *, since: int) -> dict[str, int]:
        """How many listings each reason turned away since a moment, for "why so quiet?"."""
        rows = await self._db.fetch_all(
            "SELECT reason, COUNT(*) AS n FROM rejections WHERE query_id = ? AND created_at >= ? "
            "GROUP BY reason ORDER BY n DESC",
            (query_id, since),
        )
        return {row["reason"]: row["n"] for row in rows}

    async def prune_rejections(
        self, *, keep: int = REJECTIONS_KEEP, max_age_s: int = REJECTIONS_MAX_AGE_S
    ) -> int:
        cutoff = int(time.time()) - max_age_s
        async with self._db.transaction() as conn:
            old = await conn.execute("DELETE FROM rejections WHERE created_at < ?", (cutoff,))
            excess = await conn.execute(
                "DELETE FROM rejections WHERE id NOT IN "
                "(SELECT id FROM rejections ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            return max(old.rowcount, 0) + max(excess.rowcount, 0)

    # --- The dashboard's feed ------------------------------------------------------

    async def items_feed(
        self,
        *,
        query_id: int | None = None,
        mark: MarkFilter = "visible",
        text: str | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        before_seq: int | None = None,
        since: int | None = None,
        limit: int = 60,
        offset: int = 0,
    ) -> list[FeedItem]:
        """Found listings, newest first, filtered the way the dashboard's grid needs.

        `mark` is 'visible' (everything not hidden, the default), 'saved', 'hidden',
        'unmarked' or 'all'. `before_seq` pages backwards from a cursor; `since` is a
        first-seen epoch. Text matches title, brand and seller, case-insensitively.
        """
        clauses = [_IN_FEED]
        params: list[Any] = []
        if query_id is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM query_items qx WHERE qx.item_id = i.item_id "
                "AND qx.query_id = ? AND qx.status = 'matched')"
            )
            params.append(query_id)
        clauses.append(
            {
                "visible": "(m.mark IS NULL OR m.mark != 'hidden')",
                "saved": "m.mark = 'saved'",
                "hidden": "m.mark = 'hidden'",
                "unmarked": "m.mark IS NULL",
                "all": "1 = 1",
            }[mark]
        )
        if text and text.strip():
            needle = f"%{text.strip().lower()}%"
            clauses.append(
                "(LOWER(i.title) LIKE ? OR LOWER(COALESCE(i.brand, '')) LIKE ? "
                "OR LOWER(COALESCE(i.seller_login, '')) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        if min_price is not None:
            clauses.append("COALESCE(i.total_price, i.price) >= ?")
            params.append(float(min_price))
        if max_price is not None:
            clauses.append("COALESCE(i.total_price, i.price) <= ?")
            params.append(float(max_price))
        if before_seq is not None:
            clauses.append("i.seq < ?")
            params.append(before_seq)
        if since is not None:
            clauses.append("i.first_seen_at >= ?")
            params.append(since)
        rows = await self._db.fetch_all(
            f"{_FEED_SELECT} WHERE {' AND '.join(clauses)} ORDER BY i.seq DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [_feed_item(row) for row in rows]

    async def all_found(self, *, query_id: int | None = None) -> list[FeedItem]:
        """Every listing still stored that a search matched, newest first, for export."""
        # LIMIT -1 is SQLite for "no limit".
        return await self.items_feed(query_id=query_id, mark="all", limit=-1)

    async def items_after(self, cursor: int, *, limit: int = 50) -> list[FeedItem]:
        """Listings found after a cursor, oldest first: what a live feed appends next.

        The cursor is `FeedItem.seq`; start from `latest_seq()`.
        """
        rows = await self._db.fetch_all(
            f"{_FEED_SELECT} WHERE {_IN_FEED} AND i.seq > ? ORDER BY i.seq LIMIT ?",
            (cursor, limit),
        )
        return [_feed_item(row) for row in rows]

    async def feed_item(self, item_id: int) -> FeedItem | None:
        """One stored listing as the feed shows it, for the dashboard's per-card actions."""
        row = await self._db.fetch_one(f"{_FEED_SELECT} WHERE i.item_id = ?", (item_id,))
        return _feed_item(row) if row else None

    async def newest_find_at(self) -> dict[int, int]:
        """When each search last matched something, for "quiet for five hours"."""
        rows = await self._db.fetch_all(
            "SELECT query_id, MAX(first_seen_at) AS newest FROM query_items "
            "WHERE status = 'matched' GROUP BY query_id"
        )
        return {row["query_id"]: row["newest"] for row in rows}

    async def delivery_for_query(self, query_id: int) -> DeliveryCounts:
        """Sent, failed and waiting alerts for one search, across its destinations."""
        row = await self._db.fetch_one(
            "SELECT SUM(status = 'sent') AS sent, SUM(status = 'failed') AS failed, "
            "SUM(status IN ('pending', 'sending')) AS pending FROM outbox WHERE query_id = ?",
            (query_id,),
        )
        return DeliveryCounts(
            destination_id=0,
            name="",
            kind="",
            sent=(row["sent"] if row else 0) or 0,
            failed=(row["failed"] if row else 0) or 0,
            pending=(row["pending"] if row else 0) or 0,
        )

    async def latest_seq(self) -> int:
        value = await self._db.fetch_value(
            "SELECT MAX(COALESCE((SELECT MAX(seq) FROM items), 0), "
            "COALESCE((SELECT CAST(value AS INTEGER) FROM app_state WHERE key = ?), 0))",
            (_SEQ_FLOOR_KEY,),
        )
        return int(value or 0)

    async def rss_items(self, query_id: int, *, limit: int = 50) -> list[FeedItem]:
        """A search's own matches for its RSS feed, without the listings it seeded silently."""
        return await self.items_feed(query_id=query_id, mark="all", limit=limit)

    # --- Watches -------------------------------------------------------------------

    async def add_watch(
        self,
        *,
        kind: Literal["item", "seller"],
        tld: str,
        target_id: int,
        label: str,
        destination_ids: Iterable[int] = (),
    ) -> int:
        """Start watching a listing or a seller. The first check is due straight away.

        Raises `InvalidInputError` if the same thing is already watched.
        """
        existing = await self._db.fetch_one(
            "SELECT id FROM watches WHERE kind = ? AND target_id = ?", (kind, target_id)
        )
        if existing is not None:
            raise validation.InvalidInputError("target_id", "That is already being watched.")
        now = int(time.time())
        label = validation.parse_name(label, fallback=f"{kind} {target_id}")
        async with self._db.transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO watches (kind, tld, target_id, label, next_check_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, tld, target_id, label, now, now),
            )
            watch_id = cursor.lastrowid or 0
            await conn.executemany(
                "INSERT OR IGNORE INTO watch_destinations (watch_id, destination_id) VALUES (?, ?)",
                [(watch_id, destination_id) for destination_id in destination_ids],
            )
        return watch_id

    async def list_watches(self, *, active_only: bool = False) -> list[Watch]:
        sql = "SELECT * FROM watches"
        if active_only:
            sql += " WHERE active = 1"
        return [self._to_watch(row) for row in await self._db.fetch_all(sql + " ORDER BY id")]

    async def get_watch(self, watch_id: int) -> Watch | None:
        row = await self._db.fetch_one("SELECT * FROM watches WHERE id = ?", (watch_id,))
        return self._to_watch(row) if row else None

    async def update_watch(self, watch_id: int, *, label: str, active: bool) -> None:
        await self._db.execute(
            "UPDATE watches SET label = ?, active = ? WHERE id = ?",
            (validation.parse_name(label, fallback=f"watch {watch_id}"), int(active), watch_id),
        )

    async def delete_watch(self, watch_id: int) -> None:
        await self._db.execute("DELETE FROM watches WHERE id = ?", (watch_id,))

    async def route_watch(self, watch_id: int, destination_id: int) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO watch_destinations (watch_id, destination_id) VALUES (?, ?)",
            (watch_id, destination_id),
        )

    async def unroute_watch(self, watch_id: int, destination_id: int) -> None:
        await self._db.execute(
            "DELETE FROM watch_destinations WHERE watch_id = ? AND destination_id = ?",
            (watch_id, destination_id),
        )

    async def destination_ids_for_watch(self, watch_id: int) -> list[int]:
        """Where a watch's alerts go: its routes, or every active destination if it has none."""
        rows = await self._db.fetch_all(
            "SELECT d.id FROM destinations d "
            "JOIN watch_destinations wd ON wd.destination_id = d.id "
            "WHERE wd.watch_id = ? AND d.active = 1 ORDER BY d.id",
            (watch_id,),
        )
        if rows:
            return [row["id"] for row in rows]
        return await self._default_destinations(
            "SELECT 1 FROM watches w WHERE w.id = ? AND NOT EXISTS "
            "(SELECT 1 FROM watch_destinations wd WHERE wd.watch_id = w.id)",
            watch_id,
        )

    async def due_watches(self, *, now: int, limit: int) -> list[Watch]:
        rows = await self._db.fetch_all(
            "SELECT * FROM watches WHERE active = 1 AND next_check_at <= ? "
            "ORDER BY next_check_at LIMIT ?",
            (now, limit),
        )
        return [self._to_watch(row) for row in rows]

    async def record_watch_check(
        self,
        watch_id: int,
        *,
        next_check_at: int,
        price: Decimal | None = None,
        currency: str | None = None,
        status: str | None = None,
        error: str | None = None,
        active: bool = True,
    ) -> None:
        """Note a watch's check. A failed check keeps the last good price and status."""
        await self._db.execute(
            "UPDATE watches SET last_checked_at = ?, next_check_at = ?, "
            "last_price = COALESCE(?, last_price), currency = COALESCE(?, currency), "
            "last_status = COALESCE(?, last_status), last_error = ?, active = ? WHERE id = ?",
            (
                int(time.time()),
                next_check_at,
                _real(price),
                currency,
                status,
                error[:500] if error else None,
                int(active),
                watch_id,
            ),
        )

    async def queue_watch_event(
        self,
        watch: Watch,
        item: Item,
        *,
        kind: NotificationKind,
        destination_ids: list[int],
        previous_price: Decimal | None = None,
    ) -> None:
        """Queue a price drop, sale or reservation for a watched listing.

        The listing is stored (or its price refreshed) so the notification renders from
        the same row as every other alert.
        """
        now = int(time.time())
        async with self._db.transaction() as conn:
            await conn.execute(
                _INSERT_ITEM, (*_item_values(item, now, keep_raw=False), None, None, None, None)
            )
            await conn.execute(
                "UPDATE items SET price = COALESCE(?, price), "
                "total_price = COALESCE(?, total_price) WHERE item_id = ?",
                (_real(item.price), _real(item.total_price), item.item_id),
            )
            await conn.executemany(
                "INSERT INTO outbox (item_id, watch_id, destination_id, kind, previous_price, "
                "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (item.item_id, watch.id, destination_id, kind, _real(previous_price), now, now)
                    for destination_id in destination_ids
                ],
            )

    async def record_seller_uploads(
        self,
        watch: Watch,
        items: list[Item],
        *,
        notify: list[Item],
        destination_ids: list[int],
        seen_up_to: int = 0,
    ) -> None:
        """Store a watched seller's new listings and queue the ones worth announcing.

        `seen_up_to` is the newest id on the wardrobe page. The watch keeps the highest
        it has seen, so a listing is announced once however long it stays for sale, even
        after housekeeping has forgotten the stored copy.
        """
        now = int(time.time())
        async with self._db.transaction() as conn:
            await conn.execute(
                "UPDATE watches SET seen_up_to = MAX(COALESCE(seen_up_to, 0), ?) WHERE id = ?",
                (seen_up_to, watch.id),
            )
            if not items:
                return
            await conn.executemany(
                _INSERT_ITEM,
                [
                    (*_item_values(item, now, keep_raw=False), None, None, None, watch.id)
                    for item in items
                ],
            )
            await conn.executemany(
                "INSERT INTO outbox (item_id, watch_id, destination_id, kind, next_attempt_at, "
                "created_at) VALUES (?, ?, ?, 'seller_upload', ?, ?)",
                [
                    (item.item_id, watch.id, destination_id, now, now)
                    for item in notify
                    for destination_id in destination_ids
                ],
            )

    @staticmethod
    def _to_watch(row: aiosqlite.Row) -> Watch:
        return Watch(
            id=row["id"],
            kind=row["kind"],
            tld=row["tld"],
            target_id=row["target_id"],
            label=row["label"],
            last_price=_money(row["last_price"]),
            currency=row["currency"],
            last_status=row["last_status"],
            last_checked_at=row["last_checked_at"],
            next_check_at=row["next_check_at"],
            last_error=row["last_error"],
            active=bool(row["active"]),
            created_at=row["created_at"],
            seen_up_to=row["seen_up_to"],
        )

    # --- Stats ---------------------------------------------------------------------

    async def activity(self, tz: ZoneInfo, *, days: int = 30, now: int | None = None) -> Activity:
        """Finds per day per search, when they happen, what they cost, how fast we were.

        One read of recent matches, grouped in Python: SQLite has no time zones, and the
        whole point of "finds by hour" is the reader's own clock.
        """
        since = (now or int(time.time())) - days * 86_400
        rows = await self._db.fetch_all(
            "SELECT qi.query_id, qi.first_seen_at, i.total_price, i.currency, i.photo_ts "
            "FROM query_items qi JOIN items i ON i.item_id = qi.item_id "
            "WHERE qi.status = 'matched' AND qi.first_seen_at >= ?",
            (since,),
        )
        finds: dict[tuple[str, int], int] = defaultdict(int)
        heat: dict[tuple[int, int], int] = defaultdict(int)
        prices: dict[tuple[str, int, str], list[Decimal]] = defaultdict(list)
        latencies: list[int] = []
        for row in rows:
            local = datetime.fromtimestamp(row["first_seen_at"], tz)
            day = local.date().isoformat()
            finds[(day, row["query_id"])] += 1
            heat[(local.weekday(), local.hour)] += 1
            if row["total_price"] is not None and row["currency"]:
                prices[(day, row["query_id"], row["currency"])].append(
                    Decimal(str(row["total_price"]))
                )
            if row["photo_ts"] is not None and row["first_seen_at"] >= row["photo_ts"]:
                latencies.append(row["first_seen_at"] - row["photo_ts"])

        latencies.sort()
        return Activity(
            daily_finds=[
                DailyFinds(day=day, query_id=query_id, count=count)
                for (day, query_id), count in sorted(finds.items())
            ],
            heatmap=[
                HeatCell(weekday=weekday, hour=hour, count=count)
                for (weekday, hour), count in sorted(heat.items())
            ],
            daily_medians=[
                DailyMedian(
                    day=day,
                    query_id=query_id,
                    currency=currency,
                    median=statistics.median(values).quantize(_CENT),
                )
                for (day, query_id, currency), values in sorted(prices.items())
            ],
            latency_p50_s=_percentile(latencies, 0.5) if latencies else None,
            latency_p90_s=_percentile(latencies, 0.9) if latencies else None,
            latency_samples=len(latencies),
        )

    async def delivery_counts(self) -> list[DeliveryCounts]:
        """Sent, failed and waiting notifications per destination, over everything kept."""
        rows = await self._db.fetch_all(
            "SELECT d.id, d.name, d.kind, "
            "SUM(o.status = 'sent') AS sent, SUM(o.status = 'failed') AS failed, "
            "SUM(o.status IN ('pending', 'sending')) AS pending "
            "FROM destinations d LEFT JOIN outbox o ON o.destination_id = d.id "
            "GROUP BY d.id ORDER BY d.id"
        )
        return [
            DeliveryCounts(
                destination_id=row["id"],
                name=row["name"],
                kind=row["kind"],
                sent=row["sent"] or 0,
                failed=row["failed"] or 0,
                pending=row["pending"] or 0,
            )
            for row in rows
        ]

    async def totals(self, tz: ZoneInfo) -> Totals:
        """The headline numbers. "Today" starts at midnight on the reader's clock."""
        midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        row = await self._db.fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM queries) AS searches, "
            "(SELECT COUNT(*) FROM queries WHERE paused = 0) AS active_searches, "
            "(SELECT COUNT(DISTINCT item_id) FROM query_items WHERE status = 'matched') "
            "  AS listings_found, "
            "(SELECT COUNT(DISTINCT item_id) FROM query_items "
            "  WHERE status = 'matched' AND first_seen_at >= ?) AS found_today, "
            "(SELECT COUNT(*) FROM outbox WHERE status = 'sent') AS sent, "
            "(SELECT COUNT(*) FROM outbox WHERE status IN ('pending', 'sending')) AS pending, "
            "(SELECT COUNT(*) FROM watches WHERE active = 1) AS watches, "
            "(SELECT COUNT(*) FROM blocked_sellers) AS blocked",
            (int(midnight.timestamp()),),
        )
        assert row is not None  # an aggregate always returns one row
        return Totals(
            searches=row["searches"],
            active_searches=row["active_searches"],
            listings_found=row["listings_found"],
            found_today=row["found_today"],
            notifications_sent=row["sent"],
            notifications_pending=row["pending"],
            watches=row["watches"],
            blocked_sellers=row["blocked"],
        )

    # --- App settings --------------------------------------------------------------

    async def app_settings(self, *, default_timezone: str) -> AppSettings:
        """The dashboard's preferences, with defaults for anything never set."""
        rows = await self._db.fetch_all(
            "SELECT key, value FROM app_state WHERE key IN "
            "('timezone', 'healthcheck_url', 'update_check', 'onboarded', 'theme', "
            "'latest_version', 'auto_update')"
        )
        values = {row["key"]: row["value"] for row in rows}
        return AppSettings(
            timezone=values.get("timezone") or default_timezone,
            healthcheck_url=values.get("healthcheck_url") or None,
            update_check=values.get("update_check", "1") == "1",
            onboarded=values.get("onboarded") == "1",
            theme=values.get("theme") or "system",
            latest_version=values.get("latest_version") or None,
            auto_update=values.get("auto_update") == "1",
        )

    async def set_timezone(self, name: str) -> None:
        await self.set_state_value("timezone", validation.parse_timezone(name))

    async def set_healthcheck_url(self, url: str | None) -> None:
        """A URL pinged on every heartbeat (healthchecks.io and friends); None turns it off."""
        cleaned = (url or "").strip()
        if cleaned and not cleaned.startswith(("http://", "https://")):
            raise validation.InvalidInputError(
                "healthcheck_url", "The health check address must start with https://."
            )
        await self.set_state_value("healthcheck_url", cleaned)

    async def set_update_check(self, enabled: bool) -> None:
        await self.set_state_value("update_check", "1" if enabled else "0")

    async def set_auto_update(self, enabled: bool) -> None:
        await self.set_state_value("auto_update", "1" if enabled else "0")

    async def set_onboarded(self, done: bool) -> None:
        await self.set_state_value("onboarded", "1" if done else "0")

    async def set_theme(self, theme: str) -> None:
        if theme not in THEMES:
            raise validation.InvalidInputError("theme", "The theme is system, light or dark.")
        await self.set_state_value("theme", theme)

    async def set_latest_version(self, version: str) -> None:
        await self.set_state_value("latest_version", version)

    # --- Asking for support --------------------------------------------------------

    async def support_state(self) -> SupportState:
        rows = await self._db.fetch_all(
            "SELECT key, value FROM app_state WHERE key IN "
            "('support_times_shown', 'support_last_shown_at', 'support_opted_out')"
        )
        values = {row["key"]: row["value"] for row in rows}
        # Read from the outbox rather than counted separately, so it can't drift from
        # what was actually delivered.
        last_alert = await self._db.fetch_value(
            "SELECT MAX(sent_at) FROM outbox WHERE status = 'sent'"
        )
        return SupportState(
            times_shown=int(values.get("support_times_shown") or 0),
            last_shown_at=int(values.get("support_last_shown_at") or 0),
            opted_out=values.get("support_opted_out") == "1",
            last_alert_at=int(last_alert) if last_alert is not None else None,
        )

    async def record_support_card_shown(self, times_shown: int, at: int) -> None:
        await self.set_state_value("support_times_shown", str(times_shown))
        await self.set_state_value("support_last_shown_at", str(at))

    async def opt_out_of_support_card(self) -> None:
        await self.set_state_value("support_opted_out", "1")

    # --- Miscellaneous state -------------------------------------------------------

    async def set_state_value(self, key: str, value: str) -> None:
        await self._db.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    async def get_state_value(self, key: str) -> str | None:
        value = await self._db.fetch_value("SELECT value FROM app_state WHERE key = ?", (key,))
        return str(value) if value is not None else None

    async def heartbeat(self) -> None:
        await self.set_state_value("heartbeat_at", str(int(time.time())))
