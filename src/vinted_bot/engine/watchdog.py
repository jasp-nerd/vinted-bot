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
failing, because Vinted blocks this address or because this computer lost its connection.
Each search backs off on its own and nothing tells you the whole site is down, so that
gets a status notice of its own once it has lasted a while, and another when the site
answers again. The two causes are worded apart: blaming Vinted for a laptop that lost
its Wi-Fi sends people looking in the wrong place.

How long "a while" is counts only time the app was awake to see. A laptop that slept for
three hours and finds no network for its first minute awake has not been failing for
three hours.
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

# A gap this long between two passes (they run every two minutes) means the computer
# slept, or the app was stopped in its tracks: failures from before it are not counted.
_ASLEEP_AFTER_S = 600

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
        # The last pass, and the moment after the most recent gap; see _ASLEEP_AFTER_S.
        self._last_check_at: int | None = None
        self._awake_since = 0

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
        self._note_gap(now)
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

    def _note_gap(self, now: int) -> None:
        """Start counting failures afresh after the computer slept.

        A site already announced as down keeps its start, so its all-clear still says how
        long the whole incident lasted.
        """
        if self._last_check_at is not None and now - self._last_check_at > _ASLEEP_AFTER_S:
            log.info("watchdog.gap", asleep_s=now - self._last_check_at)
            self._awake_since = now
            self._failing_since = {
                site: since
                for site, since in self._failing_since.items()
                if site in self._announced_down
            }
        self._last_check_at = now

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
            since = self._failing_since.setdefault(
                site, max(newest_success or now, self._awake_since)
            )
            if now - since >= SITE_DOWN_AFTER_S and site not in self._announced_down:
                # Marked only once the notice is queued: a pass that fails before that
                # tries again next time instead of never.
                await self._site_down(site, since, now, site_states)
                self._announced_down.add(site)

    async def _site_down(
        self, site: str, since: int, now: int, site_states: list[QueryState]
    ) -> None:
        last_error = next((s.last_error for s in site_states if s.last_error), None)
        log.warning(
            "watchdog.site_down",
            tld=site,
            searches=len(site_states),
            failing_min=round((now - since) / 60),
            last_error=last_error,
        )
        if self._announce is not None:
            await self._announce(site_down_message(site, now - since, site_states))

    async def _site_recovered(self, site: str, now: int) -> None:
        since = self._failing_since.pop(site, None)
        if site not in self._announced_down:
            return
        self._announced_down.discard(site)
        log.info(
            "watchdog.site_recovered",
            tld=site,
            down_min=round((now - since) / 60) if since is not None else None,
        )
        if self._announce is not None:
            await self._announce(
                f"vinted.{site} is answering again: searches there are back to normal"
                + (f" after about {_duration(now - since)}." if since is not None else ".")
            )

    async def _react(self, search: StaleSearch) -> None:
        if search.query_id in self._already_warned:
            return

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
        self._already_warned.add(search.query_id)


def site_down_message(site: str, failing_s: int, site_states: list[QueryState]) -> str:
    """The notice for a site where every search has been failing, worded for the cause.

    Only network errors means this computer could not reach Vinted at all; a refusal
    means Vinted answered and said no. Anything else is said as it is.
    """
    statuses = {state.last_status for state in site_states}
    last_error = next((state.last_error for state in site_states if state.last_error), None)
    opening = (
        f"Every search on vinted.{site} has been failing for {_duration(failing_s)}, so "
        "nothing new is being found there."
    )
    if statuses == {"network"}:
        cause = (
            " This computer can't reach Vinted: it seems to be offline, or its network "
            "(Wi-Fi, a VPN, a firewall) is in the way. Vinted itself isn't refusing anything."
        )
    elif "http_403" in statuses:
        cause = " Vinted is turning this address away for a while, which usually passes."
    else:
        cause = ""
    detail = f" Last error: {last_error}." if last_error else ""
    return (
        f"{opening}{cause}{detail} The app keeps trying on its own and says here when it "
        f"works again. More in {_TROUBLESHOOTING}"
    )


def _duration(seconds: int) -> str:
    """'25 minutes', 'about 3 hours': as precise as anyone reading it needs."""
    minutes = max(1, round(seconds / 60))
    if minutes < 90:  # noqa: PLR2004
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"about {round(minutes / 60)} hours"
