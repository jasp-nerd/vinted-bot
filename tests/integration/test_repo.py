"""The repository's read and write API, against a real database."""

from __future__ import annotations

import csv
import io
import time
from dataclasses import replace
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from vinted_bot.db import export
from vinted_bot.db.connection import Database
from vinted_bot.db.repo import PALETTE, Query, RejectedListing, Repo
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.vinted.models import Item, SellerProfile

UTC = ZoneInfo("UTC")


def listing(item_id: int, **kwargs: object) -> Item:
    defaults: dict[str, object] = {
        "item_id": item_id,
        "tld": "fr",
        "title": f"Listing {item_id}",
        "url": f"https://www.vinted.fr/items/{item_id}",
        "price": Decimal("15.00"),
        "total_price": Decimal("16.45"),
        "currency": "EUR",
    }
    defaults.update(kwargs)
    return Item(**defaults)  # type: ignore[arg-type]


async def add(repo: Repo, name: str = "nike", **kwargs: Any) -> Query:
    query_id = await repo.add_query(
        name=name,
        url=f"https://www.vinted.fr/catalog?search_text={name}",
        tld="fr",
        params={"search_text": name},
        poll_interval_s=60,
        **kwargs,
    )
    query = await repo.get_query(query_id)
    assert query is not None
    return query


# --- Searches ----------------------------------------------------------------------


async def test_every_new_field_round_trips(repo: Repo) -> None:
    query = await add(
        repo,
        include_terms=["air max|airmax"],
        regex=r"\b90\b",
        min_total_price=Decimal("5"),
        seller_min_rating=4.5,
        seller_min_reviews=3,
        skip_unrated_sellers=True,
        countries=["FR"],
        deal_only_pct=20,
        max_age_min=15,
        quiet_start="23:00",
        quiet_end="07:00",
        quiet_mode="silent",
        notes="for the kid",
        tags=["shoes"],
        extra_tlds=["be"],
    )

    assert (query.include_terms, query.regex, query.min_total_price) == (
        ["air max|airmax"],
        r"\b90\b",
        Decimal("5.00"),
    )
    assert (query.seller_min_rating, query.seller_min_reviews, query.skip_unrated_sellers) == (
        4.5,
        3,
        True,
    )
    assert (query.quiet_start, query.quiet_end, query.quiet_mode) == ("23:00", "07:00", "silent")
    assert (query.notes, query.tags, query.extra_tlds, query.sites) == (
        "for the kid",
        ["shoes"],
        ["be"],
        ["fr", "be"],
    )


async def test_the_resale_fields_round_trip(repo: Repo) -> None:
    query = await add(
        repo,
        resale_price="60",
        resale_fee_pct="12,5",
        resale_shipping=Decimal("4.5"),
        min_margin="10",
    )

    assert (
        query.resale_price,
        query.resale_fee_pct,
        query.resale_shipping,
        query.min_margin,
    ) == (Decimal("60.00"), 12.5, Decimal("4.50"), Decimal("10.00"))


async def test_a_minimum_margin_needs_a_resale_price(repo: Repo) -> None:
    with pytest.raises(InvalidInputError, match="resells for"):
        await add(repo, min_margin="10")


async def test_a_duplicate_keeps_the_resale_maths(repo: Repo) -> None:
    query = await add(repo, resale_price="60", resale_fee_pct=10)

    copy_id = await repo.duplicate_query(query.id)
    assert copy_id is not None
    copy = await repo.get_query(copy_id)

    assert copy is not None and (copy.resale_price, copy.resale_fee_pct) == (Decimal("60.00"), 10)


async def test_muting_a_search_records_until_when(repo: Repo) -> None:
    query = await add(repo)

    await repo.mute_query(query.id, 1_900_000_000)

    stored = await repo.get_query(query.id)
    assert stored is not None and stored.muted_until == 1_900_000_000


async def test_muting_drops_what_the_search_already_queued(repo: Repo) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])

    await repo.mute_query(query.id, int(time.time()) + 3600)

    assert await repo.outbox_depth() == 0


async def test_saving_the_edit_form_leaves_a_mute_alone(repo: Repo) -> None:
    """The form never shows the mute, so a stale copy of the search must not clear it."""
    query = await add(repo)
    await repo.mute_query(query.id, 1_900_000_000)

    await repo.update_query(replace(query, name="renamed"))

    stored = await repo.get_query(query.id)
    assert stored is not None and stored.muted_until == 1_900_000_000


async def test_new_searches_get_colours_from_the_palette_in_turn(repo: Repo) -> None:
    first = await add(repo, "one")
    second = await add(repo, "two")

    assert (first.color, second.color) == (PALETTE[0], PALETTE[1])


async def test_an_invalid_regex_is_refused_at_save_time(repo: Repo) -> None:
    with pytest.raises(InvalidInputError, match="does not work"):
        await add(repo, regex="nike (air")


async def test_a_negative_price_never_reaches_the_database(repo: Repo) -> None:
    with pytest.raises(InvalidInputError):
        await add(repo, max_total_price=Decimal("-5"))

    assert await repo.list_queries() == []


async def test_an_edit_saves_every_field_and_validates(repo: Repo) -> None:
    query = await add(repo)

    await repo.update_query(replace(query, name="renamed", banned_keywords=["fake"]))
    stored = await repo.get_query(query.id)

    assert stored is not None
    assert (stored.name, stored.banned_keywords) == ("renamed", ["fake"])
    with pytest.raises(InvalidInputError):
        await repo.update_query(replace(query, quiet_start="25:00", quiet_end="07:00"))


async def test_a_duplicate_keeps_the_rules_and_routes_but_starts_paused(repo: Repo) -> None:
    query = await add(repo, banned_keywords=["fake"], deal_only_pct=10)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.route(query.id, destination_id)

    copy_id = await repo.duplicate_query(query.id)
    assert copy_id is not None
    copy = await repo.get_query(copy_id)

    assert copy is not None
    assert (copy.name, copy.url, copy.paused) == ("nike (copy)", query.url, True)
    assert (copy.banned_keywords, copy.deal_only_pct) == (["fake"], 10)
    assert await repo.explicit_routes(copy_id) == [destination_id]


# --- Routing -----------------------------------------------------------------------


async def test_an_unrouted_search_goes_to_every_active_destination(repo: Repo) -> None:
    """Adding the search first and Discord second used to mean silence forever."""
    query = await add(repo)
    later = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})

    assert await repo.destination_ids_for_query(query.id) == [later]


async def test_explicit_routes_replace_the_default(repo: Repo) -> None:
    query = await add(repo)
    chosen = await repo.add_destination(kind="ntfy", name="a", config={"topic": "a"})
    await repo.add_destination(kind="ntfy", name="b", config={"topic": "b"})
    await repo.route(query.id, chosen)

    assert await repo.destination_ids_for_query(query.id) == [chosen]


async def test_one_listing_reaches_each_destination_once_across_searches(repo: Repo) -> None:
    first = await add(repo, "one")
    second = await add(repo, "two")
    shared = await repo.add_destination(kind="ntfy", name="shared", config={"topic": "s"})

    await repo.record_new_items(first, [listing(1)], [shared])
    await repo.record_new_items(second, [listing(1)], [shared])

    assert await repo.outbox_depth() == 1


# --- Listings ----------------------------------------------------------------------


async def test_prices_come_back_with_two_decimals(repo: Repo) -> None:
    """15.00 stored as REAL used to come back as "15.0" in every alert."""
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1, price=Decimal("15"))], [destination_id])

    (notification,) = await repo.claim_batch(destination_id, 10)

    assert str(notification.item.price) == "15.00"


async def test_a_notification_carries_its_search_colour_typical_price_and_quiet_flag(
    repo: Repo,
) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(
        query,
        [listing(1)],
        [destination_id],
        typical_prices={"EUR": Decimal("20")},
        silent=True,
    )

    (notification,) = await repo.claim_batch(destination_id, 10)

    assert (notification.query_color, notification.typical_price, notification.silent) == (
        query.color,
        Decimal("20.00"),
        True,
    )
    assert notification.deal_pct == 18


async def test_a_notification_carries_the_margin_its_search_works_out(repo: Repo) -> None:
    """60 resold at 10% is 54, minus 4 postage is 50, minus 16.45 paid is 33.55."""
    query = await add(
        repo, resale_price=Decimal("60"), resale_fee_pct=10, resale_shipping=Decimal("4")
    )
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])

    (notification,) = await repo.claim_batch(destination_id, 10)

    assert notification.margin == Decimal("33.55")


async def test_a_notification_from_a_search_without_a_resale_price_has_no_margin(
    repo: Repo,
) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])

    (notification,) = await repo.claim_batch(destination_id, 10)

    assert notification.margin is None


async def test_a_second_search_alerts_with_its_own_typical_price(repo: Repo) -> None:
    """A broad search stored the listing first; the narrow one judges it by its own median."""
    broad = await add(repo, "nike")
    narrow = await add(repo, "airmax90")
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    item = listing(77, total_price=Decimal("40.00"))
    await repo.record_new_items(
        broad, [item], [destination_id], notify=[], typical_prices={"EUR": Decimal("25.00")}
    )

    await repo.record_new_items(
        narrow, [item], [destination_id], typical_prices={"EUR": Decimal("80.00")}
    )

    [pending] = await repo.claim_batch(destination_id, 5)
    assert pending.typical_price == Decimal("80.00")


async def test_a_second_search_fills_in_the_seller_country(repo: Repo) -> None:
    first = await add(repo, "nike")
    second = await add(repo, "airmax90", countries=["FR"])
    item = listing(77, seller_id=5)
    await repo.record_new_items(first, [item], [])

    await repo.record_new_items(second, [item], [], seller_countries={5: "FR"})

    [entry] = await repo.items_feed()
    assert entry.seller_country == "FR"


async def test_a_notification_carries_what_a_seller_lookup_learned(repo: Repo) -> None:
    """The catalog no longer carries ratings; the lookup for a filter did, then was dropped."""
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.cache_seller(
        SellerProfile(seller_id=5, tld="fr", country_code="DE", rating=4.9, feedback_count=351)
    )
    await repo.record_new_items(query, [listing(1, seller_id=5)], [destination_id])

    (notification,) = await repo.claim_batch(destination_id, 10)

    item = notification.item
    stars = round((item.seller_rating or 0) * 5, 1)
    assert (stars, item.seller_feedback_count, notification.seller_country) == (4.9, 351, "DE")


async def test_held_notifications_wait_and_do_not_expire_while_held(repo: Repo) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    later = int(time.time()) + 3600
    await repo.record_new_items(query, [listing(1)], [destination_id], hold_until=later)

    assert await repo.claim_batch(destination_id, 10) == []
    assert await repo.expire_stale_notifications(older_than_minutes=0) == 0


async def test_the_typical_price_is_a_median_once_there_is_enough_history(repo: Repo) -> None:
    query = await add(repo)
    prices = [Decimal(p) for p in range(10, 25)]
    await repo.record_new_items(
        query, [listing(i, total_price=p) for i, p in enumerate(prices[:-1], 1)], []
    )
    assert await repo.typical_prices(query.id) == {}, "14 finds are not enough"

    await repo.record_new_items(query, [listing(99, total_price=prices[-1])], [])

    assert await repo.typical_prices(query.id) == {"EUR": Decimal("17.00")}


async def test_the_typical_price_keeps_currencies_apart(repo: Repo) -> None:
    query = await add(repo)
    euros = [listing(i, total_price=Decimal(10)) for i in range(1, 16)]
    pounds = [listing(i, total_price=Decimal(99), currency="GBP") for i in range(100, 103)]
    await repo.record_new_items(query, euros + pounds, [])

    assert await repo.typical_prices(query.id) == {"EUR": Decimal("10.00")}


async def test_a_listing_seen_by_one_search_is_still_unseen_by_another(repo: Repo) -> None:
    first = await add(repo, "one")
    second = await add(repo, "two")
    await repo.record_new_items(first, [listing(1)], [])

    assert await repo.seen_by_query(first.id, [1]) == {1}
    assert await repo.seen_by_query(second.id, [1]) == set()


async def test_saved_listings_survive_pruning(repo: Repo, db: Database) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1), listing(2)], [])
    await repo.set_mark(1, "saved")
    await db.execute("UPDATE items SET first_seen_at = 0")

    await repo.prune_items(older_than_days=30)

    assert await repo.known_item_ids([1, 2]) == {1}


# --- Rejections --------------------------------------------------------------------


async def test_rejections_explain_what_a_search_skipped(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(
        query, [], [], rejected=[RejectedListing(listing(5), "over_budget", "too dear")]
    )

    (record,) = await repo.rejections_for(query.id)

    assert (record.item_id, record.reason, record.title) == (5, "over_budget", "Listing 5")
    assert await repo.seen_by_query(query.id, [5]) == {5}, "a final rejection is not re-judged"


async def test_a_provisional_rejection_is_judged_again(repo: Repo) -> None:
    query = await add(repo)
    rejected = RejectedListing(listing(5), "seller_unknown", "lookup failed", final=False)
    await repo.record_new_items(query, [], [], rejected=[rejected])

    assert await repo.seen_by_query(query.id, [5]) == set()


async def test_a_later_match_clears_its_old_rejection(repo: Repo) -> None:
    query = await add(repo)
    rejected = RejectedListing(listing(5), "seller_unknown", "lookup failed", final=False)
    await repo.record_new_items(query, [], [], rejected=[rejected])

    await repo.record_new_items(query, [listing(5)], [])

    assert await repo.rejections_for(query.id) == []


async def test_the_rejection_log_is_capped(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(
        query,
        [],
        [],
        rejected=[RejectedListing(listing(i), "promoted", "bump") for i in range(1, 6)],
    )

    assert await repo.prune_rejections(keep=2) == 3
    assert [r.item_id for r in await repo.rejections_for(query.id)] == [5, 4]


# --- Feed, marks and sellers -------------------------------------------------------


async def test_the_feed_shows_matches_newest_first_with_their_search(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(3), listing(1)], [])

    feed = await repo.items_feed()

    assert [entry.item.item_id for entry in feed] == [1, 3]
    assert (feed[0].query_name, feed[0].query_color) == ("nike", query.color)


async def test_the_feed_leaves_out_what_a_first_check_seeded(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1)], [], seeded=True)

    assert await repo.items_feed() == []
    assert await repo.rss_items(query.id) == []


async def test_hidden_listings_leave_the_feed_and_saved_ones_can_be_listed(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1), listing(2), listing(3)], [])
    await repo.set_mark(1, "hidden")
    await repo.set_mark(2, "saved")

    assert [e.item.item_id for e in await repo.items_feed()] == [3, 2]
    assert [e.item.item_id for e in await repo.items_feed(mark="saved")] == [2]
    assert [e.item.item_id for e in await repo.items_feed(mark="hidden")] == [1]


async def test_the_feed_filters_by_search_text_and_price(repo: Repo) -> None:
    one = await add(repo, "one")
    two = await add(repo, "two")
    await repo.record_new_items(one, [listing(1, title="Red coat")], [])
    await repo.record_new_items(two, [listing(2, total_price=Decimal("90"))], [])

    assert [e.item.item_id for e in await repo.items_feed(query_id=one.id)] == [1]
    assert [e.item.item_id for e in await repo.items_feed(text="RED")] == [1]
    assert [e.item.item_id for e in await repo.items_feed(min_price=Decimal(50))] == [2]


async def test_a_live_feed_picks_up_from_its_cursor(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1)], [])
    cursor = await repo.latest_seq()

    await repo.record_new_items(query, [listing(2), listing(3)], [])

    assert [e.item.item_id for e in await repo.items_after(cursor)] == [2, 3]


async def test_the_feed_cursor_keeps_rising_after_everything_is_pruned(
    repo: Repo, db: Database
) -> None:
    """An open tab resumes from its last cursor; numbering must not restart below it."""
    query = await add(repo)
    await repo.record_new_items(query, [listing(1), listing(2)], [])
    await db.execute("UPDATE items SET first_seen_at = first_seen_at - 31 * 86400")
    await repo.prune_items(30)

    await repo.record_new_items(query, [listing(3)], [])

    [entry] = await repo.items_feed()
    assert entry.seq == 3


async def test_blocking_a_seller_is_listed_and_reversible(repo: Repo) -> None:
    await repo.block_seller(42, login="spammer", tld="fr", reason="fakes")

    assert [s.login for s in await repo.list_blocked_sellers()] == ["spammer"]
    await repo.unblock_seller(42)
    assert await repo.blocked_seller_ids() == set()


async def test_seller_profiles_are_cached_for_a_while(repo: Repo, db: Database) -> None:
    await repo.cache_seller(SellerProfile(seller_id=7, tld="fr", country_code="FR"))

    cached = await repo.cached_seller(7, max_age_s=60)
    assert cached is not None and cached.country_code == "FR"

    await db.execute("UPDATE seller_cache SET fetched_at = 0")
    assert await repo.cached_seller(7, max_age_s=60) is None


# --- Stats and export --------------------------------------------------------------


async def test_activity_counts_finds_per_day_and_hour(repo: Repo, db: Database) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1, photo_ts=1_000), listing(2)], [])
    noon = int(time.time()) // 86_400 * 86_400 + 12 * 3600
    await db.execute("UPDATE query_items SET first_seen_at = ?", (noon,))
    await db.execute("UPDATE items SET first_seen_at = ?", (noon,))

    activity = await repo.activity(UTC, now=noon)

    assert [(d.query_id, d.count) for d in activity.daily_finds] == [(query.id, 2)]
    assert [(c.hour, c.count) for c in activity.heatmap] == [(12, 2)]
    assert activity.daily_medians[0].median == Decimal("16.45")
    assert activity.latency_samples == 1


async def test_delivery_counts_per_destination(repo: Repo) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1), listing(2)], [destination_id])
    batch = await repo.claim_batch(destination_id, 1)
    await repo.mark_sent([batch[0].outbox_id])

    (counts,) = await repo.delivery_counts()

    assert (counts.sent, counts.failed, counts.pending) == (1, 0, 1)


async def test_totals(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1)], [])
    await repo.block_seller(9)

    totals = await repo.totals(UTC)

    assert (totals.searches, totals.listings_found, totals.found_today) == (1, 1, 1)
    assert totals.blocked_sellers == 1


async def test_export_as_csv_keeps_prices_exact(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1)], [])

    rendered = export.render(await repo.all_found(), "csv")

    header, row = rendered.splitlines()
    assert header.startswith("item_id,site,title")
    assert ",15.00,16.45,EUR," in row


@pytest.mark.parametrize("title", ['=HYPERLINK("http://x")', "+1", "-1+1", "@SUM(A1)", "\tx"])
async def test_export_as_csv_never_hands_a_spreadsheet_a_formula(repo: Repo, title: str) -> None:
    """Titles are whatever a seller typed; a spreadsheet must show them, not run them."""
    query = await add(repo)
    await repo.record_new_items(query, [listing(1, title=title)], [])

    rendered = export.render(await repo.all_found(), "csv")

    [row] = list(csv.DictReader(io.StringIO(rendered)))
    assert row["title"] == "'" + title


async def test_export_as_json(repo: Repo) -> None:
    query = await add(repo)
    await repo.record_new_items(query, [listing(1)], [])

    rendered = export.render(await repo.all_found(), "json")

    assert '"total_price": "16.45"' in rendered


# --- App settings ------------------------------------------------------------------


async def test_app_settings_default_until_changed(repo: Repo) -> None:
    defaults = await repo.app_settings(default_timezone="Europe/Paris")

    assert (defaults.timezone, defaults.update_check, defaults.onboarded, defaults.theme) == (
        "Europe/Paris",
        True,
        False,
        "system",
    )


async def test_app_settings_are_stored_and_checked(repo: Repo) -> None:
    await repo.set_timezone("Europe/Amsterdam")
    await repo.set_update_check(False)
    await repo.set_onboarded(True)
    await repo.set_theme("dark")
    await repo.set_healthcheck_url("https://hc-ping.com/abc")

    stored = await repo.app_settings(default_timezone="UTC")

    assert stored.timezone == "Europe/Amsterdam"
    assert (stored.update_check, stored.onboarded, stored.theme) == (False, True, "dark")
    assert stored.healthcheck_url == "https://hc-ping.com/abc"
    with pytest.raises(InvalidInputError):
        await repo.set_timezone("Nowhere/Special")


# --- Asking for support -----------------------------------------------------------------


async def test_support_state_starts_with_nothing_delivered(repo: Repo) -> None:
    state = await repo.support_state()

    assert (state.times_shown, state.last_shown_at, state.opted_out, state.last_alert_at) == (
        0,
        0,
        False,
        None,
    )


async def test_support_state_counts_only_alerts_that_were_delivered(repo: Repo) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])

    assert (await repo.support_state()).last_alert_at is None


async def test_support_state_knows_when_an_alert_last_reached_someone(repo: Repo) -> None:
    query = await add(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])
    (pending,) = await repo.claim_batch(destination_id, 1)
    before = int(time.time())
    await repo.mark_sent([pending.outbox_id])

    last = (await repo.support_state()).last_alert_at

    assert last is not None and last >= before


async def test_support_card_showing_is_remembered(repo: Repo) -> None:
    await repo.record_support_card_shown(2, 1_900_000_000)

    state = await repo.support_state()

    assert (state.times_shown, state.last_shown_at) == (2, 1_900_000_000)


async def test_dont_show_again_is_remembered(repo: Repo) -> None:
    await repo.opt_out_of_support_card()

    assert (await repo.support_state()).opted_out
