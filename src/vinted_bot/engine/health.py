"""Answering "is this thing still working?"

The most common complaint about tools like this is not that they break, but that you cannot
tell whether they have. "No notifications" looks identical whether the search is quiet, the
address is blocked, or the process died an hour ago. Everything here exists to separate
those three cases.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import httpx

from vinted_bot.db.repo import Repo
from vinted_bot.log import get_logger

log = get_logger(__name__)

# If the heartbeat is older than this, the process is wedged rather than idle. Comfortably
# longer than the slowest normal check plus its backoff.
HEARTBEAT_STALE_S = 300

# Checks without a new listing before the health view calls a search stale. The watchdog
# uses its own configurable threshold; this is only for the one-word summary.
STALE_SUMMARY_CYCLES = 10


@dataclass(frozen=True, slots=True)
class SearchHealth:
    query_id: int
    name: str
    tld: str
    paused: bool
    last_success_at: int | None
    last_status: str | None
    last_error: str | None
    newest_listing_at: int | None
    checks_without_new_listings: int
    items_total: int
    blocks: int
    rate_limits: int

    @property
    def state(self) -> str:
        """A one-word summary, chosen so the unhappy cases are never mistaken for quiet."""
        if self.paused:
            return "paused"
        # Failing comes before starting: a search that has failed every check since it
        # was added has never succeeded either, and "starting" would hide that forever.
        if self.last_status and self.last_status != "ok":
            return "failing"
        if self.last_success_at is None:
            return "starting"
        if self.checks_without_new_listings >= STALE_SUMMARY_CYCLES:
            return "stale"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "name": self.name,
            "tld": self.tld,
            "state": self.state,
            "last_success_at": self.last_success_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "newest_listing_at": self.newest_listing_at,
            "checks_without_new_listings": self.checks_without_new_listings,
            "items_total": self.items_total,
            "blocks": self.blocks,
            "rate_limits": self.rate_limits,
        }


@dataclass(frozen=True, slots=True)
class Snapshot:
    generated_at: int
    heartbeat_at: int | None
    searches: list[SearchHealth]
    queued_notifications: int
    active_destinations: int

    @property
    def alive(self) -> bool:
        if self.heartbeat_at is None:
            return False
        return (self.generated_at - self.heartbeat_at) < HEARTBEAT_STALE_S

    def as_dict(self) -> dict[str, Any]:
        return {
            "alive": self.alive,
            "generated_at": self.generated_at,
            "heartbeat_at": self.heartbeat_at,
            "queued_notifications": self.queued_notifications,
            "active_destinations": self.active_destinations,
            "searches": [search.as_dict() for search in self.searches],
        }


async def snapshot(repo: Repo) -> Snapshot:
    """Gather the current state of every search in one pass."""
    queries = await repo.list_queries()
    states = {state.query_id: state for state in await repo.all_states()}

    searches = []
    for query in queries:
        state = states.get(query.id)
        searches.append(
            SearchHealth(
                query_id=query.id,
                name=query.name,
                tld=query.tld,
                paused=query.paused,
                last_success_at=state.last_success_at if state else None,
                last_status=state.last_status if state else None,
                last_error=state.last_error if state else None,
                # The catalog stopped reporting photo times; when the newest listing id
                # last moved is the closest stand-in.
                newest_listing_at=(state.newest_raw_ts or state.raw_advanced_at) if state else None,
                checks_without_new_listings=state.stale_cycles if state else 0,
                items_total=state.items_seen_total if state else 0,
                blocks=state.count_403 if state else 0,
                rate_limits=state.count_429 if state else 0,
            )
        )

    heartbeat = await repo.get_state_value("heartbeat_at")
    return Snapshot(
        generated_at=int(time.time()),
        heartbeat_at=int(heartbeat) if heartbeat else None,
        searches=searches,
        queued_notifications=await repo.outbox_depth(),
        active_destinations=len(await repo.list_destinations(active_only=True)),
    )


class Heartbeat:
    """Writes a timestamp the container health check can read, and pings an outside monitor.

    Checking that the process exists proves very little; a poller can be alive and stuck.
    This only gets written when the main loop actually comes round again. If a health
    check URL is set (healthchecks.io, Uptime Kuma and the like), each beat also GETs it,
    so a dead machine is noticed by something that is not on it.
    """

    def __init__(
        self,
        repo: Repo,
        stop: asyncio.Event,
        *,
        interval_s: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._repo = repo
        self._stop = stop
        self._interval_s = interval_s
        self._http = http

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.beat()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_s)

    async def beat(self) -> None:
        """One heartbeat. Never raises: a missed beat is what the health check is for.

        A database locked by a backup or the CLI used to escape from here and take the
        whole process down with it, which is the opposite of what a heartbeat is for.
        """
        try:
            await self._repo.heartbeat()
            url = await self._repo.get_state_value("healthcheck_url")
        except sqlite3.OperationalError as exc:
            log.warning("heartbeat.db_unavailable", error=str(exc))
            return
        if url and self._http is not None:
            await _ping(self._http, url)


async def _ping(http: httpx.AsyncClient, url: str) -> None:
    """GET a monitor's URL. The URL itself stays out of the logs: it is the monitor's secret."""
    try:
        response = await http.get(url, timeout=10.0)
    except httpx.HTTPError as exc:
        # The monitor will notice the missing ping, which is its job; ours is to keep going.
        log.warning("heartbeat.ping_failed", error=type(exc).__name__)
        return
    if response.is_error:
        log.warning("heartbeat.ping_rejected", status=response.status_code)


async def is_alive(repo: Repo) -> bool:
    """Used by `vinted-bot heartbeat`, which is what Docker's health check runs."""
    raw = await repo.get_state_value("heartbeat_at")
    if raw is None:
        return False
    return (int(time.time()) - int(raw)) < HEARTBEAT_STALE_S
