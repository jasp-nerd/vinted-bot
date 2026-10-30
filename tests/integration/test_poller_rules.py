"""The poller's new decisions: routing across searches, rejections, deals, quiet hours,
several sites, and seller lookups. Real poller, real database, scripted Vinted."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tests.conftest import ScriptedTransport
from vinted_bot.config import Settings
from vinted_bot.db.connection import Database
from vinted_bot.db.repo import Repo
from vinted_bot.engine.poller import Poller, SellerLookup
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.errors import BlockedError, NetworkError, RateLimitedError
from vinted_bot.vinted.models import SellerProfile
from vinted_bot.vinted.session import SessionManager

MakeItem = Callable[..., dict[str, Any]]


async def poller(
    transport: ScriptedTransport,
    repo: Repo,
    settings: Settings,
    db: Database,
    *,
    name: str = "nike",
    seller_lookup: SellerLookup | None = None,
    **filters: Any,
) -> Poller:
    query_id = await repo.add_query(
        name=name,
        url=f"https://www.vinted.fr/catalog?search_text={name}",
        tld="fr",
        params={"search_text": name},
        poll_interval_s=60,
        **filters,
    )
    query = await repo.get_query(query_id)
    assert query is not None
    sessions = SessionManager(db, transport)
    return Poller(
        query,
        repo=repo,
        client=VintedClient(transport, sessions),
        sessions=sessions,
        settings=settings,
        stop=asyncio.Event(),
        seller_lookup=seller_lookup,
        rng=random.Random(1),
    )


async def seed(poll: Poller, transport: ScriptedTransport, make_item: MakeItem) -> None:
    """Run the silent first check over one old listing, id 100."""
    transport.queue_catalog([make_item(100, photo_ts=int(time.time()) - 60)])
    await poll.tick()


async def queued_ids(repo: Repo, destination_id: int) -> list[int]:
    return [n.item.item_id for n in await repo.claim_batch(destination_id, 100)]


async def test_two_searches_matching_one_listing_each_reach_their_own_destination(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    """The global "seen it" set used to starve the second search's destination."""
    first = await poller(transport, repo, settings, db, name="a")
    second = await poller(transport, repo, settings, db, name="b")
    to_a = await repo.add_destination(kind="webhook", name="a", config={"url": "a"})
    to_b = await repo.add_destination(kind="webhook", name="b", config={"url": "b"})
    await repo.route(first.query.id, to_a)
    await repo.route(second.query.id, to_b)
    await seed(first, transport, make_item)
    await seed(second, transport, make_item)

    now = int(time.time())
    transport.queue_catalog([make_item(200, photo_ts=now)])
    await first.tick()
    transport.queue_catalog([make_item(200, photo_ts=now)])
    await second.tick()

    assert await queued_ids(repo, to_a) == [200]
    assert await queued_ids(repo, to_b) == [200]


async def test_a_skipped_listing_is_logged_with_its_reason(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db, max_total_price=Decimal("20"))
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()), price="50.0")])
    await poll.tick()

    (rejection,) = await repo.rejections_for(poll.query.id)
    assert (rejection.item_id, rejection.reason) == (200, "over_budget")


async def test_a_listing_that_surfaces_late_is_still_announced(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    transport.queue_catalog([make_item(300, photo_ts=None)])
    await poll.tick()

    # 250 was uploaded before 300 but only reaches the catalog now.
    transport.queue_catalog([make_item(300, photo_ts=None), make_item(250, photo_ts=None)])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [300, 250]


async def test_old_stock_pulled_onto_the_first_page_is_not_announced(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(100, photo_ts=None), make_item(42, photo_ts=None)])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == []


async def test_deal_only_searches_record_everything_and_announce_only_deals(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db, deal_only_pct=30)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    now = int(time.time())
    # Fifteen listings at 20.00 make the typical price.
    transport.queue_catalog([make_item(i, photo_ts=now - 60, price="20.0") for i in range(1, 16)])
    await poll.tick()

    transport.queue_catalog(
        [make_item(100, photo_ts=now, price="19.0"), make_item(101, photo_ts=now, price="5.0")]
    )
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [101]
    assert await repo.seen_by_query(poll.query.id, [100, 101]) == {100, 101}
    reasons = {r.item_id: r.reason for r in await repo.rejections_for(poll.query.id)}
    assert reasons == {100: "not_a_deal"}


async def test_the_typical_price_is_stored_with_each_listing(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    now = int(time.time())
    transport.queue_catalog([make_item(i, photo_ts=now - 60, price="20.0") for i in range(1, 16)])
    await poll.tick()

    transport.queue_catalog([make_item(100, photo_ts=now, price="10.0")])
    await poll.tick()

    (notification,) = await repo.claim_batch(destination_id, 10)
    assert notification.typical_price == Decimal("22.70")
    # 10.00 asking is 11.70 with protection: 48% under 22.70.
    assert notification.deal_pct == 48


def _window_around_now() -> tuple[str, str]:
    now = datetime.now(UTC)
    return (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime(
        "%H:%M"
    )


async def test_quiet_hours_in_hold_mode_queue_for_the_end_of_the_window(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    start, end = _window_around_now()
    poll = await poller(transport, repo, settings, db, quiet_start=start, quiet_end=end)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await repo.outbox_depth() == 1
    assert await queued_ids(repo, destination_id) == [], "held until the window ends"


async def test_quiet_hours_in_drop_mode_record_but_never_send(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    start, end = _window_around_now()
    poll = await poller(
        transport, repo, settings, db, quiet_start=start, quiet_end=end, quiet_mode="drop"
    )
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await repo.outbox_depth() == 0
    assert [e.item.item_id for e in await repo.items_feed()] == [200]
    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["quiet_hours"]


async def test_quiet_hours_in_silent_mode_send_without_a_sound(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    start, end = _window_around_now()
    poll = await poller(
        transport, repo, settings, db, quiet_start=start, quiet_end=end, quiet_mode="silent"
    )
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    (notification,) = await repo.claim_batch(destination_id, 10)
    assert notification.silent is True


async def muted(poll: Poller, repo: Repo, until: int) -> None:
    """Mute the search and hand the poller the stored copy, as the supervisor does."""
    await repo.mute_query(poll.query.id, until)
    query = await repo.get_query(poll.query.id)
    assert query is not None
    poll.query = query


async def test_a_muted_search_records_but_never_sends(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    await muted(poll, repo, int(time.time()) + 3600)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert (
        await repo.outbox_depth(),
        [r.reason for r in await repo.rejections_for(poll.query.id)],
    ) == (
        0,
        ["muted"],
    )


async def test_a_search_speaks_again_once_its_mute_runs_out(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    await muted(poll, repo, int(time.time()) - 1)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await repo.outbox_depth() == 1


async def test_a_listing_below_the_minimum_margin_is_logged_not_sent(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(
        transport, repo, settings, db, resale_price=Decimal("10"), min_margin=Decimal("5")
    )
    await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["low_margin"]


async def test_a_search_on_several_sites_fetches_each_and_announces_once(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db, extra_tlds=["be"])
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    now = int(time.time())
    transport.queue_catalog([make_item(100, photo_ts=now - 60)])
    transport.queue_catalog([make_item(100, photo_ts=now - 60)])
    await poll.tick()

    transport.queue_catalog([make_item(200, photo_ts=now)])
    transport.queue_catalog([make_item(200, photo_ts=now), make_item(201, photo_ts=now)])
    await poll.tick()

    catalog_hosts = {r["url"].split("/")[2] for r in transport.requests if "/svc-" in r["url"]}
    assert catalog_hosts == {"api.vinted.fr", "api.vinted.be"}
    assert await queued_ids(repo, destination_id) == [200, 201]


class FakeSellers:
    """Stands in for the transport's member-page lookup, counting its calls."""

    def __init__(self, *answers: SellerProfile | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[int] = []

    async def __call__(self, tld: str, seller_id: int) -> SellerProfile | None:
        self.calls.append(seller_id)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def french(seller_id: int = 1) -> SellerProfile:
    return SellerProfile(seller_id=seller_id, tld="fr", country_code="FR", feedback_count=10)


async def test_the_country_filter_skips_foreign_sellers(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(SellerProfile(seller_id=1, tld="fr", country_code="DE"))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == []
    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["seller_country"]


async def test_seller_lookups_are_cached_between_checks(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(french())
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    now = int(time.time())

    transport.queue_catalog([make_item(200, photo_ts=now)])
    await poll.tick()
    transport.queue_catalog([make_item(201, photo_ts=now)])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [200, 201]
    assert sellers.calls == [1], "one lookup per seller, not per listing"
    (entry, _) = await repo.items_feed()
    assert entry.seller_country == "FR"


async def test_a_failed_seller_lookup_is_tried_again_next_check(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(NetworkError("timed out"), french())
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    now = int(time.time())

    transport.queue_catalog([make_item(200, photo_ts=now)])
    await poll.tick()
    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["seller_unknown"]

    transport.queue_catalog([make_item(200, photo_ts=now)])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [200]
    assert await repo.rejections_for(poll.query.id) == []


async def test_seller_ratings_come_from_the_lookup_now_listings_lack_them(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(SellerProfile(seller_id=1, tld="fr", rating=0.6, feedback_count=20))
    poll = await poller(transport, repo, settings, db, seller_min_rating=4.5, seller_lookup=sellers)
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()), user={"id": 1})])
    await poll.tick()

    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["low_rating"]


async def test_without_a_lookup_seller_filters_let_listings_through(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db, countries=["BE"])
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [200]


async def test_blocked_sellers_are_never_announced(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await repo.block_seller(1, login="seller")
    await seed(poll, transport, make_item)

    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == []


async def test_network_backoff_keeps_its_jitter_past_the_cap(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database
) -> None:
    """Clipping the jitter away made every failing search retry in the same second."""
    poll = await poller(transport, repo, settings, db)
    delays = []
    for _ in range(4):
        transport.queue_status(503, "busy")
        delays.append(await poll.tick())

    assert delays[-1] > 120.0


async def test_a_rate_limited_seller_lookup_stops_lookups_for_as_long_as_asked(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    """A 429 on a member page ends lookups for the check and the Retry-After that follows."""
    sellers = FakeSellers(RateLimitedError(30), french(), french(2))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    await seed(poll, transport, make_item)
    now = int(time.time())

    transport.queue_catalog(
        [make_item(200, photo_ts=now), make_item(201, photo_ts=now, user={"id": 2})]
    )
    await poll.tick()
    transport.queue_catalog(
        [make_item(200, photo_ts=now), make_item(201, photo_ts=now, user={"id": 2})]
    )
    await poll.tick()

    assert sellers.calls == [1], "no lookup while Vinted asked us to wait"


async def test_listings_waiting_on_paused_lookups_are_logged_as_undecided(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(BlockedError("refused"), french(2))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    await seed(poll, transport, make_item)
    now = int(time.time())

    transport.queue_catalog(
        [make_item(200, photo_ts=now), make_item(201, photo_ts=now, user={"id": 2})]
    )
    await poll.tick()

    rejections = await repo.rejections_for(poll.query.id)
    assert sorted((r.item_id, r.reason) for r in rejections) == [
        (200, "seller_unknown"),
        (201, "seller_unknown"),
    ]


async def test_a_listing_older_than_the_freshness_window_is_logged_as_too_old(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db)
    await seed(poll, transport, make_item)
    two_hours_ago = int(time.time()) - 7200
    transport.queue_catalog([make_item(101, photo_ts=two_hours_ago)])

    await poll.tick()

    assert [(r.item_id, r.reason) for r in await repo.rejections_for(poll.query.id)] == [
        (101, "too_old")
    ]


async def test_a_too_old_listing_a_rule_skips_anyway_is_not_logged_as_too_old(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(transport, repo, settings, db, banned_keywords=["item"])
    await seed(poll, transport, make_item)
    transport.queue_catalog([make_item(101, photo_ts=int(time.time()) - 7200)])

    await poll.tick()

    assert await repo.rejections_for(poll.query.id) == []


async def test_a_limit_converts_a_listing_from_a_site_with_another_currency(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    poll = await poller(
        transport, repo, settings, db, extra_tlds=["co.uk"], max_total_price=Decimal("20")
    )
    await repo.set_state_value("exchange_rates", '{"fetched_at": 1, "rates": {"GBP": "0.8"}}')
    now = int(time.time())
    transport.queue_catalog([make_item(100, photo_ts=now - 60)])
    transport.queue_catalog([])
    await poll.tick()
    pounds = {"amount": "18.00", "currency_code": "GBP"}
    in_pounds = make_item(200, photo_ts=now) | {"price": pounds, "total_item_price": pounds}
    transport.queue_catalog([])
    transport.queue_catalog([in_pounds])

    await poll.tick()

    assert [r.reason for r in await repo.rejections_for(poll.query.id)] == ["over_budget"]


async def test_a_listing_waiting_on_its_seller_is_judged_after_it_leaves_the_page(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    """On a busy search undecided listings fell off the page and were never judged."""
    sellers = FakeSellers(NetworkError("timed out"), french())
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    destination_id = await repo.add_destination(kind="webhook", name="w", config={"url": "x"})
    await seed(poll, transport, make_item)
    transport.queue_catalog([make_item(200, photo_ts=int(time.time()))])
    await poll.tick()

    transport.queue_catalog([])
    await poll.tick()

    assert await queued_ids(repo, destination_id) == [200]


def busy_page(first: int, count: int) -> list[dict[str, Any]]:
    """Listings from as many different sellers, none of them cached."""
    now = int(time.time())
    return [
        {
            "id": first + n,
            "title": f"Item {first + n}",
            "url": f"https://www.vinted.fr/items/{first + n}",
            "price": {"amount": "10.0", "currency_code": "EUR"},
            "photo": {"high_resolution": {"timestamp": now}},
            "user": {"id": first + n, "login": f"seller{n}"},
        }
        for n in range(count)
    ]


async def test_a_busy_search_looks_up_more_sellers_once_it_has_used_its_budget(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(*(french(1000 + n) for n in range(60)))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    await seed(poll, transport, make_item)

    transport.queue_catalog(busy_page(1000, 15))
    await poll.tick()
    transport.queue_catalog(busy_page(2000, 25))
    await poll.tick()

    assert len(sellers.calls) == 10 + 20


async def test_a_listing_left_waiting_by_the_budget_says_so(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Database, make_item: MakeItem
) -> None:
    sellers = FakeSellers(*(french(1000 + n) for n in range(10)))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    await seed(poll, transport, make_item)
    transport.queue_catalog(busy_page(1000, 15))

    await poll.tick()

    details = {r.detail for r in await repo.rejections_for(poll.query.id)}
    assert details == {
        "waiting for a seller lookup: 5 listings were still waiting after this check's 10 "
        "lookups; tried again on the next check, for up to 20 min"
    }


async def test_a_listing_still_undecided_after_the_freshness_window_is_given_up(
    transport: ScriptedTransport,
    repo: Repo,
    settings: Settings,
    db: Database,
    make_item: MakeItem,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sellers = FakeSellers(*(NetworkError("timed out") for _ in range(3)))
    poll = await poller(transport, repo, settings, db, countries=["FR"], seller_lookup=sellers)
    await seed(poll, transport, make_item)
    start = time.time()
    transport.queue_catalog([make_item(200, photo_ts=int(start))])
    await poll.tick()

    for minutes in (15, 30):
        monkeypatch.setattr(time, "time", lambda m=minutes: start + m * 60)
        transport.queue_catalog([])
        await poll.tick()

    (rejection,) = await repo.rejections_for(poll.query.id)
    assert rejection.detail.startswith("gave up after 30 min without the seller's details")
    assert await repo.seen_by_query(poll.query.id, [200]) == {200}
