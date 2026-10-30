"""The watchdog, and the storage guarantees everything else assumes."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from tests.conftest import ScriptedTransport
from vinted_bot.config import Settings
from vinted_bot.db.connection import Database
from vinted_bot.db.repo import Repo
from vinted_bot.engine import health
from vinted_bot.engine.watchdog import Watchdog
from vinted_bot.vinted.models import Item
from vinted_bot.vinted.session import SessionManager


async def add_search(repo: Repo, name: str, tld: str = "fr") -> int:
    return await repo.add_query(
        name=name,
        url=f"https://www.vinted.{tld}/catalog?search_text={name}",
        tld=tld,
        params={"search_text": name},
        poll_interval_s=60,
    )


async def set_state(db: Database, query_id: int, **columns: Any) -> None:
    assignments = ", ".join(f"{key} = ?" for key in columns)
    await db.execute(
        f"UPDATE query_state SET {assignments} WHERE query_id = ?",
        (*columns.values(), query_id),
    )


def make_watchdog(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> tuple[Watchdog, list[str]]:
    announcements: list[str] = []

    async def announce(message: str) -> None:
        announcements.append(message)

    watchdog = Watchdog(
        repo=repo,
        sessions=SessionManager(db, transport),
        settings=settings,
        stop=asyncio.Event(),
        announce=announce,
    )
    return watchdog, announcements


async def test_a_frozen_search_is_spotted_when_its_neighbours_keep_moving(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    stuck = await add_search(repo, "stuck")
    healthy = await add_search(repo, "healthy")
    now = int(time.time())

    await set_state(db, stuck, last_success_at=now, stale_cycles=15, newest_raw_ts=now - 9000)
    await set_state(db, healthy, last_success_at=now, stale_cycles=0, newest_raw_ts=now - 30)

    watchdog, announcements = make_watchdog(repo, db, transport, settings)
    stale = await watchdog.check()

    assert [s.query_id for s in stale] == [stuck]
    assert announcements, "the point is that you find out"


async def test_a_genuinely_quiet_site_is_not_mistaken_for_a_frozen_one(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    first = await add_search(repo, "one")
    second = await add_search(repo, "two")
    now = int(time.time())

    # Nothing new anywhere on the site: a slow night, not a stuck feed.
    await set_state(db, first, last_success_at=now, stale_cycles=20, newest_raw_ts=now - 9000)
    await set_state(db, second, last_success_at=now, stale_cycles=20, newest_raw_ts=now - 9000)

    watchdog, announcements = make_watchdog(repo, db, transport, settings)

    assert await watchdog.check() == []
    assert announcements == []


async def test_a_search_that_has_never_run_is_not_called_stale(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    new = await add_search(repo, "new")
    busy = await add_search(repo, "busy")
    now = int(time.time())
    await set_state(db, busy, last_success_at=now, stale_cycles=0, newest_raw_ts=now - 10)
    await set_state(db, new, stale_cycles=99)

    watchdog, _ = make_watchdog(repo, db, transport, settings)

    assert await watchdog.check() == []


async def test_the_same_search_is_only_reported_once(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    stuck = await add_search(repo, "stuck")
    healthy = await add_search(repo, "healthy")
    now = int(time.time())
    await set_state(db, stuck, last_success_at=now, stale_cycles=15, newest_raw_ts=now - 9000)
    await set_state(db, healthy, last_success_at=now, stale_cycles=0, newest_raw_ts=now - 30)

    watchdog, announcements = make_watchdog(repo, db, transport, settings)
    await watchdog.check()
    await watchdog.check()
    await watchdog.check()

    assert len(announcements) == 1, "a stuck search should not become a stuck notification"


async def test_being_stale_starts_a_new_session(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    stuck = await add_search(repo, "stuck")
    healthy = await add_search(repo, "healthy")
    now = int(time.time())
    await set_state(db, stuck, last_success_at=now, stale_cycles=15, newest_raw_ts=now - 9000)
    await set_state(db, healthy, last_success_at=now, stale_cycles=0, newest_raw_ts=now - 30)

    watchdog, _ = make_watchdog(repo, db, transport, settings)
    await watchdog.check()

    assert any("/api/v2/" not in request["url"] for request in transport.requests)


# --- Health reporting ---------------------------------------------------------------


async def test_the_health_view_separates_quiet_from_broken(repo: Repo, db: Database) -> None:
    ok = await add_search(repo, "fine")
    broken = await add_search(repo, "broken")
    now = int(time.time())

    await set_state(db, ok, last_success_at=now, last_status="ok")
    await set_state(db, broken, last_success_at=now - 600, last_status="http_403", count_403=4)

    snapshot = await health.snapshot(repo)
    states = {search.name: search.state for search in snapshot.searches}

    assert states == {"fine": "ok", "broken": "failing"}


async def test_a_missing_heartbeat_reads_as_not_running(repo: Repo) -> None:
    assert await health.is_alive(repo) is False

    await repo.heartbeat()

    assert await health.is_alive(repo) is True


# --- Storage ------------------------------------------------------------------------


async def test_concurrent_writers_do_not_trip_over_each_other(repo: Repo, db: Database) -> None:
    """SQLite allows one writer at a time; writes are serialised so that is never an error."""
    query_id = await add_search(repo, "busy")

    async def bump(index: int) -> None:
        await db.execute(
            "UPDATE query_state SET items_seen_total = items_seen_total + 1 WHERE query_id = ?",
            (query_id,),
        )
        await repo.set_state_value(f"key-{index}", str(index))

    await asyncio.gather(*(bump(index) for index in range(25)))

    state = await repo.get_state(query_id)
    assert state.items_seen_total == 25, "no update may be lost to a lock"


async def test_reads_work_while_a_write_transaction_is_open(repo: Repo, db: Database) -> None:
    query_id = await add_search(repo, "one")

    async with db.transaction() as conn:
        await conn.execute(
            "UPDATE query_state SET items_seen_total = 7 WHERE query_id = ?", (query_id,)
        )
        # Reads do not queue behind the write lock, which is what keeps the dashboard
        # responsive while searches are being recorded.
        rows = await db.fetch_all("SELECT * FROM queries")
        assert len(rows) == 1

    assert (await repo.get_state(query_id)).items_seen_total == 7


async def test_a_failed_transaction_leaves_nothing_behind(repo: Repo, db: Database) -> None:
    query_id = await add_search(repo, "one")

    try:
        async with db.transaction() as conn:
            await conn.execute(
                "UPDATE query_state SET items_seen_total = 99 WHERE query_id = ?", (query_id,)
            )
            raise RuntimeError("something went wrong mid-write")
    except RuntimeError:
        pass

    assert (await repo.get_state(query_id)).items_seen_total == 0


async def test_deleting_a_search_takes_its_state_and_routes_with_it(
    repo: Repo, db: Database
) -> None:
    query_id = await add_search(repo, "one")
    destination_id = await repo.add_destination(kind="ntfy", name="phone", config={"topic": "t"})
    await repo.route(query_id, destination_id)

    await repo.delete_query(query_id)

    assert await db.fetch_one("SELECT 1 FROM query_state WHERE query_id = ?", (query_id,)) is None
    assert await repo.destination_ids_for_query(query_id) == []
    assert await repo.get_destination(destination_id) is not None, "the destination survives"


async def test_old_listings_are_pruned(repo: Repo, db: Database) -> None:
    query_id = await add_search(repo, "one")
    query = await repo.get_query(query_id)
    assert query is not None

    await repo.record_new_items(
        query,
        [Item(item_id=1, tld="fr", title="old", url="https://www.vinted.fr/items/1")],
        [],
    )
    await db.execute("UPDATE items SET first_seen_at = ?", (int(time.time()) - 90 * 86_400,))

    assert await repo.prune_items(older_than_days=30) == 1
    assert await repo.known_item_ids([1]) == set()


async def test_a_search_failing_since_it_was_added_reads_as_failing(
    repo: Repo, db: Database
) -> None:
    """It used to read "starting" forever, hiding the error under a grey pill."""
    query_id = await add_search(repo, "broken")
    await set_state(db, query_id, last_status="network", last_error="404")

    snapshot = await health.snapshot(repo)

    assert [search.state for search in snapshot.searches] == ["failing"]


async def test_the_warn_only_watchdog_does_not_claim_to_rotate(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    stuck = await add_search(repo, "stuck")
    healthy = await add_search(repo, "healthy")
    now = int(time.time())
    await set_state(db, stuck, last_success_at=now, stale_cycles=15, newest_raw_ts=now - 9000)
    await set_state(db, healthy, last_success_at=now, stale_cycles=0, newest_raw_ts=now - 30)

    watchdog, announcements = make_watchdog(
        repo, db, transport, settings.model_copy(update={"watchdog_action": "warn"})
    )
    await watchdog.check()

    assert "fresh session" not in announcements[0]


# --- A whole site failing -----------------------------------------------------------


async def all_blocked(repo: Repo, db: Database, *, since: int) -> list[int]:
    ids = [await add_search(repo, "one"), await add_search(repo, "two")]
    for query_id in ids:
        await set_state(db, query_id, last_success_at=since, last_status="http_403")
        await repo.record_failure(query_id, "http_403", "Blocked: 403 from the catalog")
    return ids


async def test_every_search_on_a_site_failing_for_a_while_is_announced_once(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    now = int(time.time())
    await all_blocked(repo, db, since=now - 1200)
    watchdog, announcements = make_watchdog(repo, db, transport, settings)

    await watchdog.check(now=now)
    await watchdog.check(now=now + 120)

    assert len(announcements) == 1
    assert announcements[0].startswith("Every search on vinted.fr has been failing for 20 min")


async def test_a_short_outage_is_left_to_the_backoff(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    now = int(time.time())
    await all_blocked(repo, db, since=now - 300)
    watchdog, announcements = make_watchdog(repo, db, transport, settings)

    await watchdog.check(now=now)

    assert announcements == []


async def test_one_search_still_working_means_the_site_is_not_down(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    now = int(time.time())
    first, _ = await all_blocked(repo, db, since=now - 3600)
    await set_state(db, first, last_status="ok", last_success_at=now)
    watchdog, announcements = make_watchdog(repo, db, transport, settings)

    await watchdog.check(now=now)

    assert announcements == []


async def test_a_site_that_answers_again_gets_an_all_clear(
    repo: Repo, db: Database, transport: ScriptedTransport, settings: Settings
) -> None:
    now = int(time.time())
    first, _ = await all_blocked(repo, db, since=now - 1200)
    watchdog, announcements = make_watchdog(repo, db, transport, settings)
    await watchdog.check(now=now)
    await set_state(db, first, last_status="ok", last_success_at=now + 60)

    await watchdog.check(now=now + 120)

    assert announcements[-1].startswith("vinted.fr is answering again")
