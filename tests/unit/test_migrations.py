from __future__ import annotations

from pathlib import Path

import pytest

from vinted_bot.db import Database, apply_pending, current_version
from vinted_bot.db.migrations import discover


async def test_fresh_database_gets_full_schema(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        applied = await apply_pending(db)

        assert applied == len(discover())
        assert await current_version(db) == applied

        tables = {
            row["name"]
            for row in await db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"queries", "query_state", "destinations", "items", "outbox", "sessions"} <= tables


async def test_second_run_applies_nothing(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await apply_pending(db)
        version_after_first = await current_version(db)

        assert await apply_pending(db) == 0
        assert await current_version(db) == version_after_first


async def test_gap_in_numbering_is_rejected(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text("CREATE TABLE a (x INTEGER);")
    (migrations / "0003_later.sql").write_text("CREATE TABLE b (x INTEGER);")

    with pytest.raises(ValueError, match="gap or duplicate"):
        discover(migrations)


async def test_database_newer_than_code_is_refused(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await db.execute("PRAGMA user_version = 99")

        with pytest.raises(RuntimeError, match="newer release"):
            await apply_pending(db)


async def test_foreign_keys_cascade_on_delete(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await apply_pending(db)
        await db.execute(
            "INSERT INTO queries (id, name, url, tld, params_json, created_at, updated_at) "
            "VALUES (1, 'test', 'https://www.vinted.fr/catalog?x=1', 'fr', '{}', 0, 0)"
        )
        await db.execute("INSERT INTO query_state (query_id) VALUES (1)")

        await db.execute("DELETE FROM queries WHERE id = 1")

        assert await db.fetch_one("SELECT 1 FROM query_state WHERE query_id = 1") is None


async def test_poll_interval_floor_is_enforced_by_schema(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await apply_pending(db)

        with pytest.raises(Exception, match="CHECK constraint failed"):
            await db.execute(
                "INSERT INTO queries "
                "(name, url, tld, params_json, poll_interval_s, created_at, updated_at) "
                "VALUES ('fast', 'https://www.vinted.fr/catalog?y=1', 'fr', '{}', 2, 0, 0)"
            )


async def _database_at_version_3(path: Path, tmp_path: Path) -> Database:
    """A database as 1.x left it, with a little of everything in it."""
    old = tmp_path / "old-migrations"
    old.mkdir()
    for migration in discover()[:3]:
        (old / migration.name).write_text(migration.path.read_text(encoding="utf-8"))
    db = Database(path)
    await db.connect()
    await apply_pending(db, old)
    await db.execute(
        "INSERT INTO queries (id, name, url, tld, params_json, created_at, updated_at) "
        "VALUES (1, 'nike', 'https://www.vinted.fr/catalog?search_text=nike', 'fr', '{}', 0, 0)"
    )
    await db.execute("INSERT INTO query_state (query_id, newest_item_ts) VALUES (1, 100)")
    await db.execute(
        "INSERT INTO destinations (id, kind, name, config_json, created_at) "
        "VALUES (7, 'discord', 'd', '{}', 0)"
    )
    await db.execute("INSERT INTO query_destinations VALUES (1, 7)")
    for item_id, seen_at in ((50, 20), (40, 10), (60, 30)):
        await db.execute(
            "INSERT INTO items (item_id, query_id, tld, url, total_price, first_seen_at) "
            "VALUES (?, 1, 'fr', 'u', 12.5, ?)",
            (item_id, seen_at),
        )
    await db.execute(
        "INSERT INTO outbox (item_id, query_id, destination_id, status, next_attempt_at, "
        "created_at) VALUES (60, 1, 7, 'sent', 0, 0)"
    )
    return db


async def test_an_existing_database_upgrades_with_its_data_intact(tmp_path: Path) -> None:
    db = await _database_at_version_3(tmp_path / "app.db", tmp_path)
    try:
        assert await apply_pending(db) == len(discover()) - 3

        routes = await db.fetch_all("SELECT * FROM query_destinations")
        assert [(r["query_id"], r["destination_id"]) for r in routes] == [(1, 7)]
        state = await db.fetch_one("SELECT * FROM query_state WHERE query_id = 1")
        assert state is not None and state["newest_item_ts"] == 100
        outbox = await db.fetch_one("SELECT kind, status FROM outbox")
        assert outbox is not None and (outbox["kind"], outbox["status"]) == ("listing", "sent")
    finally:
        await db.close()


async def test_the_upgrade_numbers_existing_listings_in_the_order_they_were_found(
    tmp_path: Path,
) -> None:
    db = await _database_at_version_3(tmp_path / "app.db", tmp_path)
    try:
        await apply_pending(db)

        rows = await db.fetch_all("SELECT item_id FROM items ORDER BY seq")
        assert [row["item_id"] for row in rows] == [40, 50, 60]
    finally:
        await db.close()


async def test_the_upgrade_credits_existing_listings_to_their_search(tmp_path: Path) -> None:
    """Announced listings become matches; the rest were seeded by the first check."""
    db = await _database_at_version_3(tmp_path / "app.db", tmp_path)
    try:
        await apply_pending(db)

        rows = await db.fetch_all("SELECT item_id, status FROM query_items ORDER BY item_id")
        assert [(r["item_id"], r["status"]) for r in rows] == [
            (40, "seeded"),
            (50, "seeded"),
            (60, "matched"),
        ]
    finally:
        await db.close()


async def test_after_the_upgrade_deleting_a_search_still_cascades(tmp_path: Path) -> None:
    """The rebuilt searches table must still be the parent its children point at."""
    db = await _database_at_version_3(tmp_path / "app.db", tmp_path)
    try:
        await apply_pending(db)

        await db.execute("DELETE FROM queries WHERE id = 1")

        assert await db.fetch_one("SELECT 1 FROM query_destinations") is None
        assert await db.fetch_one("SELECT 1 FROM query_state") is None
    finally:
        await db.close()


async def test_apprise_destinations_are_allowed_after_the_upgrade(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await apply_pending(db)

        await db.execute(
            "INSERT INTO destinations (kind, name, config_json, created_at) "
            "VALUES ('apprise', 'a', '{}', 0)"
        )

        assert await db.fetch_value("SELECT COUNT(*) FROM destinations") == 1


async def test_a_failing_migration_leaves_nothing_half_done(tmp_path: Path) -> None:
    """A regression guard: executescript used to commit each statement as it went."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_init.sql").write_text("CREATE TABLE a (x INTEGER);")
    (migrations / "0002_broken.sql").write_text(
        "ALTER TABLE a ADD COLUMN y INTEGER;\nTHIS IS NOT SQL;"
    )

    async with Database(tmp_path / "app.db") as db:
        with pytest.raises(Exception, match="syntax error"):
            await apply_pending(db, migrations)

        columns = [row["name"] for row in await db.fetch_all("PRAGMA table_info(a)")]
        assert columns == ["x"], "the first statement of the failed file must be rolled back"
        assert await current_version(db) == 1


async def test_foreign_keys_are_back_on_after_migrating(tmp_path: Path) -> None:
    async with Database(tmp_path / "app.db") as db:
        await apply_pending(db)

        assert await db.fetch_value("PRAGMA foreign_keys") == 1
