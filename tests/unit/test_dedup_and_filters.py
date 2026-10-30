from __future__ import annotations

import time
from decimal import Decimal

import pytest

from vinted_bot.db.repo import Query
from vinted_bot.engine import dedup, filters
from vinted_bot.vinted.models import Item

NOW = 1_760_000_000


def item(item_id: int, *, ts: int | None = NOW, **kwargs: object) -> Item:
    defaults: dict[str, object] = {
        "item_id": item_id,
        "tld": "fr",
        "title": f"Item {item_id}",
        "url": f"https://www.vinted.fr/items/{item_id}",
        "photo_ts": ts,
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


# --- Deduplication -----------------------------------------------------------------


def select(
    listings: list[Item],
    *,
    seen: set[int] | None = None,
    floor: int | None = None,
    first_run: bool = False,
    now: int = NOW,
    window_s: int = 1200,
    full: bool = False,
) -> dedup.Selection:
    return dedup.select(
        items=listings,
        seen_ids=seen or set(),
        floor_item_id=floor,
        now=now,
        freshness_window_s=window_s,
        is_first_run=first_run,
        page_is_full=full,
    )


def test_first_check_offers_the_whole_page_and_raises_the_floor_to_its_newest() -> None:
    result = select([item(1), item(3), item(2)], first_run=True)

    assert [i.item_id for i in result.new] == [1, 2, 3]
    assert result.floor_item_id == 3, "nothing already on the shelf may count as new later"


def test_first_check_can_announce_exactly_one_as_a_smoke_test() -> None:
    listings = [item(1), item(3), item(2)]

    assert [i.item_id for i in dedup.first_run_pick(listings, "newest")] == [3]
    assert dedup.first_run_pick(listings, "silent") == []


def test_listings_older_than_the_freshness_window_are_ignored() -> None:
    result = select([item(1, ts=NOW - 5000), item(2, ts=NOW - 60)])

    assert [i.item_id for i in result.new] == [2]
    assert result.skipped_stale == 1


def test_listings_this_search_already_judged_are_ignored() -> None:
    result = select([item(1), item(2)], seen={1})

    assert [i.item_id for i in result.new] == [2]


def test_old_stock_pulled_up_below_the_floor_is_not_new() -> None:
    """A deletion pulls listing 90 onto the first page; it was never new, only unseen."""
    result = select([item(90, ts=None), item(105, ts=None)], seen={105}, floor=100)

    assert result.new == []


def test_a_late_listing_inside_the_watched_range_is_still_announced() -> None:
    """The bug the old timestamp mark had: a listing that surfaces after a newer one was
    already announced was dropped forever. Below the newest but above the floor is news."""
    result = select([item(120, ts=None), item(110, ts=None)], seen={120}, floor=100)

    assert [i.item_id for i in result.new] == [110]


def test_new_listings_come_out_in_upload_order() -> None:
    result = select([item(3), item(1), item(2)])

    assert [i.item_id for i in result.new] == [1, 2, 3]


def test_a_listing_without_a_timestamp_is_judged_on_its_id() -> None:
    result = select([item(101, ts=None)], floor=100)

    assert [i.item_id for i in result.new] == [101]


def test_the_floor_only_rises() -> None:
    """A quiet search's page reaches far back; the floor must not follow it down."""
    result = select([item(50), item(150)], seen={50, 150}, floor=100)

    assert result.floor_item_id == 100


def test_the_floor_follows_a_full_page_up() -> None:
    result = select([item(300), item(250)], seen={250, 300}, floor=100, full=True)

    assert result.floor_item_id == 250


def test_a_short_page_leaves_the_floor_alone() -> None:
    """A page that was not full held every result: nothing was below it to keep out."""
    result = select([item(300), item(250)], seen={250, 300}, floor=100)

    assert result.floor_item_id == 100


def test_the_watchdog_markers_ignore_what_this_search_has_seen() -> None:
    result = select([item(7, ts=NOW), item(5, ts=NOW - 10)], seen={5, 7})

    assert result.newest_raw_id == 7, "a quiet search still proves the catalog is moving"
    assert result.newest_raw_ts == NOW
    assert result.new == []


def test_freshness_window_uses_real_clock_units() -> None:
    """A regression guard: the window is seconds, and a 20-minute window is 1200 of them."""
    now = int(time.time())

    result = select([item(1, ts=now - 19 * 60), item(2, ts=now - 21 * 60)], now=now)

    assert [i.item_id for i in result.new] == [1]


# --- Filters -----------------------------------------------------------------------


def test_the_price_limit_counts_buyer_protection() -> None:
    # Vinted's own price filter would allow this: the asking price is under the limit.
    listing = item(1, price=Decimal("18.00"), total_price=Decimal("20.50"))

    rejection = filters.check(listing, search(max_total_price=Decimal("20.00")))

    assert rejection is not None
    assert rejection.reason == "over_budget"
    assert "buyer protection" in rejection.detail


def test_a_listing_exactly_on_the_limit_is_kept() -> None:
    listing = item(1, price=Decimal("18.00"), total_price=Decimal("20.00"))

    assert filters.matches(listing, search(max_total_price=Decimal("20.00")))


def test_the_asking_price_is_used_when_there_is_no_total() -> None:
    listing = item(1, price=Decimal("25.00"))

    assert not filters.matches(listing, search(max_total_price=Decimal("20.00")))


def test_boosted_listings_are_skipped() -> None:
    rejection = filters.check(item(1, promoted=True), search())

    assert rejection is not None
    assert rejection.reason == "promoted"


@pytest.mark.parametrize("title", ["Nike REPLICA shoes", "replica bag", "Cheap Replica"])
def test_excluded_words_match_regardless_of_case(title: str) -> None:
    listing = item(1, title=title)

    assert not filters.matches(listing, search(banned_keywords=["replica"]))


def test_excluded_words_do_not_reject_everything_else() -> None:
    assert filters.matches(item(1, title="Nike Air Max"), search(banned_keywords=["replica"]))


def test_condition_filter() -> None:
    listing = item(1, condition="Satisfactory")

    assert not filters.matches(listing, search(conditions=["New with tags", "Very good"]))
    assert filters.matches(listing, search(conditions=["Satisfactory"]))


def test_no_filters_means_everything_matches() -> None:
    assert filters.matches(item(1, price=Decimal("999")), search())
