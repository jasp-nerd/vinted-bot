"""Noticing when Vinted stops telling us about new listings.

There is a failure mode that looks exactly like success: after a while, the catalog keeps
answering with a cheerful 200 and the same results it gave an hour ago, while new listings
pile up behind it. Nothing errors, nothing retries, and the alerts simply stop. People
assume the tool is broken and cannot tell why, because from the inside everything is fine.

The tell is comparative. A search whose newest listing has not moved for many checks might
just be a quiet corner of the market — but if a different search on the same site is still
turning up new things, the quiet one is stuck rather than slow. That distinction is the
whole trick, and it is why this runs across searches instead of inside the poller.

The opposite case is loud in the log and silent everywhere else: every search on a site
failing, usually because Vinted blocks this address. Each search backs off on its own and
nothing tells you the whole site is down, so that gets a status notice of its own once it
has lasted a while, and another when the site answers again.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from vinted_bot.config import Settings
from vinted_bot.db.repo import Query, QueryState, Repo
from vinted_bot.log import get_logger
from vinted_bot.vinted.session import SessionManager

log = get_logger(__name__)

# How long a site must have been advancing for us to trust it as a comparison.
_RECENT_MOVEMENT_S = 900

# How long every search on a site must have been failing before it counts as down. Shorter
# than this is the backoff ladder doing its job after a blip.
SITE_DOWN_AFTER_S = 900

_TROUBLESHOOTING = "https://github.com/jasp-nerd/vinted-bot/blob/main/docs/troubleshooting.md"


@dataclass(frozen=True, slots=True)
class StaleSearch:
    query_id: int
    name: str
    tld: str
    stale_cycles: int
    last_new_listing_at: int | None


class Watchdog:
    """Watches the watchers."""

    def __init__(
        self,
        *,
        repo: Repo,
        sessions: SessionManager,
        settings: Settings,
        stop: asyncio.Event,
        announce: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._repo = repo
        self._sessions = sessions
        self._settings = settings
        self._stop = stop
        self._announce = announce
        self._already_warned: set[int] = set()
        # Site -> when every search on it was first seen failing; and the sites announced
        # as down, so each incident gets one notice and one all-clear.
        self._failing_since: dict[str, int] = {}
        self._announced_down: set[str] = set()

    async def run(self, interval_s: float = 120.0) -> None:
        while not self._stop.is_set():
            try:
                await self.check()
            except Exception as exc:
                # One bad pass (a locked database, usually) must not end the watching.
                log.exception("watchdog.failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval_s)

    async def check(self, *, now: int | None = None) -> list[StaleSearch]:
        """Find searches that have gone quiet while their neighbours have not.

        Also notices a whole site failing; see `_check_sites`.
        """
        queries = {query.id: query for query in await self._repo.list_queries(include_paused=False)}
        states = {state.query_id: state for state in await self._repo.all_states()}
        now = now or int(time.time())
        await self._check_sites(queries, states, now)
        if not queries:
            return []

        moving_sites = {
            queries[query_id].tld
            for query_id, state in states.items()
            if query_id in queries
            and state.last_success_at is not None
            and state.stale_cycles == 0
            and now - state.last_success_at < _RECENT_MOVEMENT_S
        }

        stale: list[StaleSearch] = []
        for query_id, state in states.items():
            query = queries.get(query_id)
            if query is None or state.is_first_run:
                continue
            if state.stale_cycles < self._settings.watchdog_stale_cycles:
                self._already_warned.discard(query_id)
                continue
            if query.tld not in moving_sites:
                # The whole site is quiet. That is a slow night, not a stuck feed.
                continue
            stale.append(
                StaleSearch(
                    query_id=query_id,
                    name=query.name,
                    tld=query.tld,
                    stale_cycles=state.stale_cycles,
                    last_new_listing_at=state.newest_raw_ts,
                )
            )

        for search in stale:
            await self._react(search)
        return stale

    async def _check_sites(
        self, queries: dict[int, Query], states: dict[int, QueryState], now: int
    ) -> None:
        """Announce a site where every search has been failing a while, and its recovery."""
        by_site: dict[str, list[QueryState]] = defaultdict(list)
        for query_id, query in queries.items():
            if (state := states.get(query_id)) is not None and state.last_status is not None:
                by_site[query.tld].append(state)

        for site in set(self._failing_since) | set(by_site):
            site_states = by_site.get(site, [])
            if not site_states:
                # Its searches were paused or removed: nothing to announce either way.
                self._failing_since.pop(site, None)
                self._announced_down.discard(site)
                continue
            if any(state.last_status == "ok" for state in site_states):
                await self._site_recovered(site, now)
                continue
            newest_success = max((s.last_success_at or 0 for s in site_states), default=0)
            since = self._failing_since.setdefault(site, newest_success or now)
            if now - since >= SITE_DOWN_AFTER_S and site not in self._announced_down:
                self._announced_down.add(site)
                await self._site_down(site, since, now, site_states)

    async def _site_down(
        self, site: str, since: int, now: int, site_states: list[QueryState]
    ) -> None:
        minutes = round((now - since) / 60)
        last_error = next((s.last_error for s in site_states if s.last_error), None)
        log.warning(
            "watchdog.site_down",
            tld=site,
            searches=len(site_states),
            failing_min=minutes,
            last_error=last_error,
        )
        if self._announce is not None:
            await self._announce(
                f"Every search on vinted.{site} has been failing for {minutes} minutes, so "
                f"nothing new is being found there. Last error: {last_error or 'unknown'}. "
                "This usually means Vinted is blocking this address for a while; the app "
                f"keeps trying on its own. More in {_TROUBLESHOOTING}"
            )

    async def _site_recovered(self, site: str, now: int) -> None:
        since = self._failing_since.pop(site, None)
        if site not in self._announced_down:
            return
        self._announced_down.discard(site)
        minutes = round((now - since) / 60) if since is not None else None
        log.info("watchdog.site_recovered", tld=site, down_min=minutes)
        if self._announce is not None:
            await self._announce(
                f"vinted.{site} is answering again: searches there are back to normal"
                + (f" after about {minutes} minutes." if minutes is not None else ".")
            )

    async def _react(self, search: StaleSearch) -> None:
        if search.query_id in self._already_warned:
            return
        self._already_warned.add(search.query_id)

        log.warning(
            "watchdog.stale_search",
            query_id=search.query_id,
            query=search.name,
            tld=search.tld,
            checks_without_new_listings=search.stale_cycles,
            action=self._settings.watchdog_action,
        )

        if self._settings.watchdog_action == "rotate":
            await self._sessions.rotate(search.tld)
            log.info("watchdog.session_rotated", tld=search.tld)

        if self._announce is not None:
            action = (
                "Started a fresh session; if it stays quiet"
                if self._settings.watchdog_action == "rotate"
                else "If it stays quiet"
            )
            await self._announce(
                f"“{search.name}” has seen nothing new for {search.stale_cycles} checks "
                f"while other vinted.{search.tld} searches keep finding listings. "
                f"{action}, see the troubleshooting guide."
            )
