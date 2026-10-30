"""The whole app, start to finish, without touching the network.

Uses the same offline mode that `VINTED_BOT_FETCH_MODE=mock` gives you, so this is
also a demonstration that the mode works.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
import structlog

from vinted_bot.app import Application
from vinted_bot.config import Settings
from vinted_bot.db import Database, apply_pending
from vinted_bot.db.repo import Repo
from vinted_bot.engine.poller import Poller


def write_scenario(directory: Path, *, item_count: int = 3) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    (directory / "root.json").write_text(
        json.dumps({"status": 200, "body": "<html></html>", "cookies": {"access_token_web": "x"}})
    )
    (directory / "catalog.json").write_text(
        json.dumps(
            {
                "status": 200,
                "body": {
                    "items": [
                        {
                            "id": 1000 + index,
                            "title": f"Mock listing {index}",
                            "url": f"https://www.vinted.fr/items/{1000 + index}",
                            "brand_title": "Nike",
                            "size_title": "M",
                            "status": "Very good",
                            "price": {"amount": "12.00", "currency_code": "EUR"},
                            "total_item_price": {"amount": "13.90", "currency_code": "EUR"},
                            "photo": {
                                "full_size_url": "https://images.vinted.net/x.jpeg",
                                "high_resolution": {"id": "x", "timestamp": now - index},
                            },
                            "user": {"id": 1, "login": "seller"},
                        }
                        for index in range(item_count)
                    ]
                },
            }
        )
    )


@pytest.fixture
def offline_settings(tmp_path: Path) -> Settings:
    scenario = tmp_path / "scenario"
    write_scenario(scenario)
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=tmp_path / "app.db",
        fetch_mode="mock",
        mock_scenario_dir=scenario,
        poll_default_interval_s=10,
        first_run_mode="newest",
        log_level="WARNING",
        # No dashboard here: these tests are about the polling loop, and binding a real
        # port would make them fail whenever anything else is using it.
        web_enabled=False,
    )


async def run_briefly(app: Application, seconds: float = 0.6) -> None:
    """Start the app, let it settle, then ask it to stop the way a signal would."""
    task = asyncio.create_task(app.run())
    await asyncio.sleep(seconds)
    app.request_stop()
    await asyncio.wait_for(task, timeout=5)


async def test_the_app_finds_listings_and_queues_them(offline_settings: Settings) -> None:
    async with Database(offline_settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)
        query_id = await repo.add_query(
            name="mock search",
            url="https://www.vinted.fr/catalog?search_text=nike",
            tld="fr",
            params={"search_text": "nike"},
            poll_interval_s=10,
        )
        destination_id = await repo.add_destination(
            kind="webhook", name="sink", config={"url": "https://example.invalid/hook"}
        )
        await repo.route(query_id, destination_id)

    await run_briefly(Application(offline_settings))

    async with Database(offline_settings.db_path) as db:
        repo = Repo(db)
        state = await repo.get_state(query_id)
        assert state.last_status == "ok"
        assert state.last_success_at is not None
        # first_run_mode="newest" announces exactly one listing as a delivery test.
        assert len(await repo.known_item_ids([1000, 1001, 1002])) == 3
        assert await repo.get_state_value("heartbeat_at") is not None


async def test_shutdown_is_prompt(offline_settings: Settings) -> None:
    """A slow shutdown means Docker kills the process mid-send instead of letting it finish."""
    app = Application(offline_settings)
    task = asyncio.create_task(app.run())
    await asyncio.sleep(0.4)

    started = time.monotonic()
    app.request_stop()
    await asyncio.wait_for(task, timeout=5)
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"took {elapsed:.1f}s to stop; sleeps must be interruptible"


async def test_a_search_added_while_running_is_picked_up(offline_settings: Settings) -> None:
    async with Database(offline_settings.db_path) as db:
        await apply_pending(db)

    app = Application(offline_settings, supervise_interval_s=0.1)
    task = asyncio.create_task(app.run())
    await asyncio.sleep(0.3)

    async with Database(offline_settings.db_path) as db:
        repo = Repo(db)
        query_id = await repo.add_query(
            name="added later",
            url="https://www.vinted.fr/catalog?search_text=added",
            tld="fr",
            params={"search_text": "added"},
            poll_interval_s=10,
        )

    # The supervisor reconciles on its own schedule; give it a moment to notice.
    await asyncio.sleep(0.3)
    app.request_stop()
    await asyncio.wait_for(task, timeout=5)

    async with Database(offline_settings.db_path) as db:
        state = await Repo(db).get_state(query_id)

    assert state.last_polled_at is not None, "a search added while running should start itself"


async def add_search(settings: Settings, text: str) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        return await Repo(db).add_query(
            name=text,
            url=f"https://www.vinted.fr/catalog?search_text={text}",
            tld="fr",
            params={"search_text": text},
            poll_interval_s=10,
        )


async def test_searches_started_together_are_spread_out(offline_settings: Settings) -> None:
    """After a restart every search used to fire in the same second."""
    for text in ("one", "two", "three"):
        await add_search(offline_settings, text)

    with structlog.testing.capture_logs() as events:
        await run_briefly(Application(offline_settings), seconds=0.3)

    delays = [e["start_in_s"] for e in events if e["event"] == "poller.started"]
    assert delays[0] == 0, "the first search still checks straight away"
    assert delays[1] >= 2.0
    assert delays[2] >= 4.0


async def test_a_search_that_keeps_crashing_is_restarted_with_backoff(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restarting a crashed search at once would hammer Vinted every supervisor pass."""
    query_id = await add_search(offline_settings, "crashy")

    async def crash(self: Poller) -> float:
        raise RuntimeError("boom")

    monkeypatch.setattr(Poller, "tick", crash)

    with structlog.testing.capture_logs() as events:
        await run_briefly(Application(offline_settings, supervise_interval_s=0.05), seconds=0.4)

    starts = [e for e in events if e["event"] == "poller.started" and e["query_id"] == query_id]
    assert [e["start_in_s"] >= 10 for e in starts] == [False, True]


async def test_editing_a_search_restarts_it_with_the_new_rules(
    offline_settings: Settings,
) -> None:
    query_id = await add_search(offline_settings, "edited")
    app = Application(offline_settings, supervise_interval_s=0.1)

    with structlog.testing.capture_logs() as events:
        task = asyncio.create_task(app.run())
        await asyncio.sleep(0.3)
        async with Database(offline_settings.db_path) as db:
            repo = Repo(db)
            query = await repo.get_query(query_id)
            assert query is not None
            await repo.update_query(replace(query, banned_keywords=["fake"]))
        await asyncio.sleep(0.3)
        app.request_stop()
        await asyncio.wait_for(task, timeout=5)

    starts = [e for e in events if e["event"] == "poller.started" and e["query_id"] == query_id]
    assert len(starts) == 2


async def test_a_search_on_two_sites_records_each_listing_once(
    offline_settings: Settings,
) -> None:
    async with Database(offline_settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)
        query_id = await repo.add_query(
            name="both",
            url="https://www.vinted.fr/catalog?search_text=nike",
            tld="fr",
            params={"search_text": "nike"},
            poll_interval_s=10,
            extra_tlds=["be"],
        )
        await repo.add_destination(kind="webhook", name="sink", config={"url": "x"})

    await run_briefly(Application(offline_settings))

    async with Database(offline_settings.db_path) as db:
        repo = Repo(db)
        assert (await repo.get_state(query_id)).last_status == "ok"
        assert await repo.seen_by_query(query_id, [1000, 1001, 1002]) == {1000, 1001, 1002}
        assert await repo.outbox_depth() == 1, "newest mode announces one, not one per site"
