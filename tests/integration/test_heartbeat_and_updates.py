"""The heartbeat's outside ping, its survival of a locked database, and the update check."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable

import httpx

from vinted_bot.db.connection import Database
from vinted_bot.db.repo import Repo
from vinted_bot.engine import health, updates
from vinted_bot.engine.health import Heartbeat


def recording_client(
    respond: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


async def test_a_heartbeat_pings_the_health_check_url(repo: Repo) -> None:
    await repo.set_healthcheck_url("https://hc-ping.com/abc")
    http, seen = recording_client(lambda _: httpx.Response(200))

    await Heartbeat(repo, asyncio.Event(), http=http).beat()

    assert [str(request.url) for request in seen] == ["https://hc-ping.com/abc"]


async def test_a_failing_ping_does_not_stop_the_heartbeat(repo: Repo) -> None:
    await repo.set_healthcheck_url("https://hc-ping.com/abc")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    http, _ = recording_client(refuse)

    await Heartbeat(repo, asyncio.Event(), http=http).beat()

    assert await health.is_alive(repo)


async def test_no_url_means_no_ping(repo: Repo) -> None:
    http, seen = recording_client(lambda _: httpx.Response(200))

    await Heartbeat(repo, asyncio.Event(), http=http).beat()

    assert seen == []


async def test_a_locked_database_skips_a_beat_instead_of_killing_the_process(
    repo: Repo, db: Database
) -> None:
    """A backup tool or the CLI holding the lock used to take the whole app down."""
    await db.execute("PRAGMA busy_timeout = 0")
    blocker = sqlite3.connect(db.path, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        await Heartbeat(repo, asyncio.Event()).beat()
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert await repo.get_state_value("heartbeat_at") is None


def release(tag: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, text=json.dumps({"tag_name": tag}))


async def test_the_update_check_stores_the_latest_release(repo: Repo) -> None:
    http, _ = recording_client(release("v9.1.0"))

    await updates.check_for_update(repo, http, now=1_000_000)

    assert (await repo.app_settings(default_timezone="UTC")).latest_version == "9.1.0"
    assert updates.is_newer("9.1.0")


async def test_the_update_check_asks_at_most_once_a_day(repo: Repo) -> None:
    http, seen = recording_client(release("v9.1.0"))

    await updates.check_for_update(repo, http, now=1_000_000)
    await updates.check_for_update(repo, http, now=1_000_000 + 3600)

    assert len(seen) == 1


async def test_the_update_check_can_be_turned_off(repo: Repo) -> None:
    await repo.set_update_check(False)
    http, seen = recording_client(release("v9.1.0"))

    await updates.check_for_update(repo, http, now=1_000_000)

    assert seen == []


async def test_a_github_error_is_not_a_crash(repo: Repo) -> None:
    http, _ = recording_client(lambda _: httpx.Response(404, text="Not Found"))

    await updates.check_for_update(repo, http, now=1_000_000)

    assert (await repo.app_settings(default_timezone="UTC")).latest_version is None


def test_version_comparison() -> None:
    assert updates.is_newer("v0.2.0", current="0.1.9")
    assert not updates.is_newer("0.1.0", current="0.1.0")
    assert not updates.is_newer("nightly", current="0.1.0")
