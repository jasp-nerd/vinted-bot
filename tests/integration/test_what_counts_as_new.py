"""What counts as a new listing across downtime, upgrades, edits and housekeeping.

Search results no longer carry a photo time, so these run on the catalog's real shape: a
listing id and nothing to say how old it is. Each case is one way the app used to announce
a page of old listings as new.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.conftest import ScriptedTransport
from tests.integration.test_poller import poller_for
from vinted_sniper.config import Settings
from vinted_sniper.db import Database, apply_pending
from vinted_sniper.db.migrations import discover
from vinted_sniper.db.repo import Query, Repo

DAY = 86_400


def listing(item_id: int, price: str = "10.0") -> dict[str, Any]:
    """A catalog entry as svc-catalogue returns it: no photo timestamp."""
    return {
        "id": item_id,
        "title": f"Item {item_id}",
        "url": f"https://www.vinted.nl/items/{item_id}",
        "brand_title": "Levi's",
        "size_title": "M",
        "status": "Very good",
        "price": {"amount": price, "currency_code": "EUR"},
        "total_item_price": {"amount": price, "currency_code": "EUR"},
        "photo": {"full_size_url": f"https://images.vinted.net/{item_id}.jpeg"},
        "user": {"id": 1, "login": "seller"},
    }


def page(first: int, count: int = 96) -> list[dict[str, Any]]:
    return [listing(first + n) for n in range(count)]


async def a_search(repo: Repo, text: str = "levis", **kwargs: Any) -> Query:
    query_id = await repo.add_query(
        name=text,
        url=f"https://www.vinted.nl/catalog?search_text={text}",
        tld="nl",
        params={"search_text": text, "order": "newest_first"},
        poll_interval_s=60,
        **kwargs,
    )
    await repo.add_destination(kind="webhook", name="w", config={"url": "http://127.0.0.1:1/x"})
    query = await repo.get_query(query_id)
    assert query is not None
    return query


async def check(
    query: Query, transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    """One check by a freshly started poller, as after a restart."""
    poller, _ = poller_for(query, transport, repo, settings, db=db)
    await poller.tick()


async def queued(db: Any) -> int:
    return int(await db.fetch_value("SELECT COUNT(*) FROM outbox") or 0)


async def last_checked(db: Any, query_id: int, seconds_ago: int) -> None:
    await db.execute(
        "UPDATE query_state SET last_success_at = ? WHERE query_id = ?",
        (int(time.time()) - seconds_ago, query_id),
    )


# --- Downtime --------------------------------------------------------------------------


async def test_a_restart_after_a_day_off_records_the_missed_page_quietly(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000))
    await check(query, transport, repo, settings, db)
    await last_checked(db, query.id, seconds_ago=DAY)

    transport.queue_catalog(page(5000))
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 0


async def test_after_catching_up_new_listings_are_announced_again(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000))
    await check(query, transport, repo, settings, db)
    await last_checked(db, query.id, seconds_ago=DAY)
    transport.queue_catalog(page(5000))
    await check(query, transport, repo, settings, db)

    transport.queue_catalog([listing(6000), *page(5000, 95)])
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 1


async def test_a_quick_restart_still_announces_what_is_new(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000))
    await check(query, transport, repo, settings, db)
    await last_checked(db, query.id, seconds_ago=120)

    transport.queue_catalog([listing(2000), listing(2001), *page(1000, 94)])
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 2


async def test_a_listing_known_to_be_older_than_the_window_is_skipped(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    """A narrow search turns up a listing the app saw a newer id than an hour ago, such
    as one whose price was just cut into range: not a new listing."""
    query = await a_search(repo)
    await repo.note_listing_id(9000, now=int(time.time()) - 3600)
    transport.queue_catalog([listing(1000)])
    await check(query, transport, repo, settings, db)

    transport.queue_catalog([listing(5000), listing(1000)])
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 0


async def test_a_listing_seen_within_the_window_is_announced(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    await repo.note_listing_id(9000, now=int(time.time()) - 300)
    transport.queue_catalog([listing(1000)])
    await check(query, transport, repo, settings, db)

    transport.queue_catalog([listing(5000), listing(1000)])
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 1


async def test_a_search_can_ignore_listings_sooner_than_the_app_wide_window(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    """The editor's "ignore listings older than" and `add --max-age` do something."""
    query = await a_search(repo, max_age_min=3)
    await repo.note_listing_id(9000, now=int(time.time()) - 300)
    transport.queue_catalog([listing(1000)])
    await check(query, transport, repo, settings, db)

    transport.queue_catalog([listing(5000), listing(1000)])
    await check(query, transport, repo, settings, db)

    assert await queued(db) == 0


async def test_every_check_moves_the_id_clock(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000, 5))
    await check(query, transport, repo, settings, db)

    assert set(await repo.listed_by([1004, 1005])) == {1004}


# --- Upgrading from 1.x ----------------------------------------------------------------


async def database_from_1x(path: Path, tmp_path: Path, *, last_check_ago: int) -> Database:
    """A 1.x database with one search that recorded listings 100 to 120, then upgraded."""
    old = tmp_path / "1x-migrations"
    old.mkdir(exist_ok=True)
    for migration in discover()[:3]:
        (old / migration.name).write_text(migration.path.read_text(encoding="utf-8"))
    db = Database(path)
    await db.connect()
    await apply_pending(db, old)
    now = int(time.time())
    await db.execute(
        "INSERT INTO queries (id, name, url, tld, params_json, created_at, updated_at) "
        "VALUES (1, 'levis', 'https://www.vinted.nl/catalog?search_text=levis', 'nl', "
        '\'{"search_text": "levis"}\', 0, 0)'
    )
    await db.execute(
        "INSERT INTO query_state (query_id, last_success_at) VALUES (1, ?)", (now - last_check_ago,)
    )
    await db.execute(
        "INSERT INTO destinations (id, kind, name, config_json, created_at) "
        "VALUES (1, 'webhook', 'w', '{\"url\": \"http://127.0.0.1:1/x\"}', 0)"
    )
    for item_id in range(100, 121):
        await db.execute(
            "INSERT INTO items (item_id, query_id, tld, url, total_price, first_seen_at) "
            "VALUES (?, 1, 'nl', 'u', 10, ?)",
            (item_id, now - last_check_ago),
        )
    await apply_pending(db)
    return db


async def test_the_upgrade_gives_1x_searches_a_floor(tmp_path: Path) -> None:
    db = await database_from_1x(tmp_path / "app.db", tmp_path, last_check_ago=60)
    try:
        state = await Repo(db).get_state(1)

        assert state.floor_item_id == 120
    finally:
        await db.close()


async def test_the_first_check_after_a_quick_upgrade_announces_only_newer_listings(
    tmp_path: Path, transport: ScriptedTransport, settings: Settings
) -> None:
    db = await database_from_1x(tmp_path / "app.db", tmp_path, last_check_ago=60)
    try:
        repo = Repo(db)
        query = await repo.get_query(1)
        assert query is not None
        # Two uploads since 1.x stopped, and a page of what 1.x had not stored.
        transport.queue_catalog([listing(122), listing(121), *page(1, 94)])

        await check(query, transport, repo, settings, db)

        assert await queued(db) == 2
    finally:
        await db.close()


async def test_the_first_check_after_a_long_upgrade_floods_nothing(
    tmp_path: Path, transport: ScriptedTransport, settings: Settings
) -> None:
    db = await database_from_1x(tmp_path / "app.db", tmp_path, last_check_ago=3 * DAY)
    try:
        repo = Repo(db)
        query = await repo.get_query(1)
        assert query is not None
        transport.queue_catalog(page(10_000))

        await check(query, transport, repo, settings, db)

        assert await queued(db) == 0
    finally:
        await db.close()


# --- Editing a search ------------------------------------------------------------------


async def test_changing_what_a_search_looks_for_starts_it_over_quietly(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo, "rare")
    transport.queue_catalog(page(1000, 5))
    await check(query, transport, repo, settings, db)

    edited = await repo.update_query(
        replace(
            query,
            url="https://www.vinted.nl/catalog?search_text=nike",
            params={"search_text": "nike", "order": "newest_first"},
        )
    )
    transport.queue_catalog(page(900_000))
    await check(edited, transport, repo, settings, db)

    assert await queued(db) == 0


async def test_renaming_a_search_keeps_its_place(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000, 5))
    await check(query, transport, repo, settings, db)

    await repo.update_query(replace(query, name="Levi's 501"))

    assert (await repo.get_state(query.id)).floor_item_id == 1004


async def test_changing_what_a_search_looks_for_restarts_its_typical_price(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog([listing(1000 + n, price="80.0") for n in range(20)])
    await check(query, transport, repo, settings, db)
    assert await repo.typical_prices(query.id)

    await repo.update_query(
        replace(query, url="https://www.vinted.nl/catalog?search_text=x", params={"q": "x"})
    )

    assert await repo.typical_prices(query.id) == {}


# --- Housekeeping ----------------------------------------------------------------------


async def test_a_match_still_for_sale_after_pruning_is_not_found_again(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    """A narrow search's month-old match must not come back as a new find."""
    query = await a_search(repo, "rare")
    transport.queue_catalog([listing(1000)])
    await check(query, transport, repo, settings, db)
    transport.queue_catalog([listing(1001), listing(1000)])
    await check(query, transport, repo, settings, db)
    await db.execute("UPDATE query_items SET first_seen_at = first_seen_at - 31 * 86400")
    await db.execute("UPDATE items SET first_seen_at = first_seen_at - 31 * 86400")
    await repo.prune_items(30)

    transport.queue_catalog([listing(1001), listing(1000)])
    await check(query, transport, repo, settings, db)

    assert await repo.items_feed() == []


async def test_pruning_forgets_what_lies_below_the_floor(
    transport: ScriptedTransport, repo: Repo, settings: Settings, db: Any
) -> None:
    query = await a_search(repo)
    transport.queue_catalog(page(1000))
    await check(query, transport, repo, settings, db)
    await db.execute("UPDATE query_items SET first_seen_at = first_seen_at - 31 * 86400")

    await repo.prune_items(30)

    assert await db.fetch_value("SELECT COUNT(*) FROM query_items") == 0
