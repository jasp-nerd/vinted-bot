"""The loop that watches one search.

Each search gets its own task. What matters here is what happens when a check fails: the
error types from the Vinted layer each mean something different, and treating them the same
is how a tool talks itself into a longer block. A rejected token is cheap to fix. A refused
connection is not, and hammering it makes it worse.

A search may run on several country sites. One poller fetches each in turn and judges the
combined results, so there is one set of decisions and one floor rather than several that
disagree. If any site fails, the whole check counts as failed and backs off: the listings
the other sites returned are still there next time.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from vinted_bot.config import MAX_BACKOFF_S, Settings
from vinted_bot.db.repo import Query, QueryState, RejectedListing, Repo
from vinted_bot.engine import dedup, filters, quiet
from vinted_bot.log import get_logger
from vinted_bot.vinted.client import PER_PAGE, VintedClient
from vinted_bot.vinted.errors import (
    AuthExpiredError,
    BlockedError,
    MalformedResponseError,
    NetworkError,
    RateLimitedError,
    VintedError,
)
from vinted_bot.vinted.models import Item, SellerProfile
from vinted_bot.vinted.session import SessionManager

log = get_logger(__name__)

SellerLookup = Callable[[str, int], Awaitable[SellerProfile | None]]

# Spread checks out so a dozen searches do not all fire on the same second.
_JITTER_FRACTION = 0.15

# A network error retries sooner than a block, but no sooner than this ceiling allows.
_NETWORK_BACKOFF_CAP_S = 120.0

# Member pages change slowly; a week-old country is still the right country.
SELLER_CACHE_S = 7 * 86_400

# Seller lookups per check. A normal check has a handful of new listings; this only bites
# when a burst arrives, and the rest wait for the next check rather than hammering the site.
_MAX_LOOKUPS_PER_CHECK = 10

# How long seller lookups stop after Vinted refuses one (403), or answers 429 without
# saying how long to wait. The catalog itself keeps being checked meanwhile.
_LOOKUP_PAUSE_S = 600.0

# A rejected token is normally fixed by one homepage load. If fresh tokens keep being
# rejected this many times in a row, something else is wrong, and retrying every few
# seconds is just hammering: from here on a 401 backs off like any other refusal.
_AUTH_FAILURES_BEFORE_BACKOFF = 3

# A gap since the last good check longer than this many check intervals (or than the
# freshness window, whichever is longer) means the app was off or blocked; see dedup.
_CATCH_UP_INTERVALS = 3


@dataclass(slots=True)
class _Verdicts:
    """What one check decided about the listings that were new to it."""

    matched: list[Item] = field(default_factory=list)
    announce: list[Item] = field(default_factory=list)
    rejected: list[RejectedListing] = field(default_factory=list)
    seller_countries: dict[int, str] = field(default_factory=dict)
    # Seller profiles fetched or read from the cache during this check, by seller id.
    profiles: dict[int, SellerProfile | None] = field(default_factory=dict)
    lookups_made: int = 0


class Poller:
    """Checks one saved search, forever, until asked to stop."""

    def __init__(
        self,
        query: Query,
        *,
        repo: Repo,
        client: VintedClient,
        sessions: SessionManager,
        settings: Settings,
        stop: asyncio.Event,
        work_available: asyncio.Event | None = None,
        seller_lookup: SellerLookup | None = None,
        start_delay_s: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.query = query
        self._repo = repo
        self._client = client
        self._sessions = sessions
        self._settings = settings
        self._stop = stop
        self._work_available = work_available
        self._seller_lookup = seller_lookup
        self._start_delay_s = start_delay_s
        self._rng = rng or random.Random()
        self._rules = filters.Rules(query)
        self._consecutive_errors = 0
        self._consecutive_auth_failures = 0
        # Seller lookups are off until then after Vinted refused one (epoch seconds).
        self._lookups_paused_until = 0.0
        # Completed checks, so the supervisor can tell a poller that crashed straight away
        # from one that ran for a while first.
        self.successes = 0
        # The site being fetched when an error escapes, so the right session is replaced.
        self._site = query.tld
        self._warned_no_lookup = False
        self._log = log.bind(query_id=query.id, query=query.name, tld=query.tld)

    async def run(self) -> None:
        """Check on a schedule until the stop event is set."""
        await self._wait(self._start_delay_s)
        while not self._stop.is_set():
            delay = await self.tick()
            await self._wait(delay)

    async def tick(self) -> float:
        """Run one check. Returns how long to wait before the next one."""
        try:
            await self._check()
        except AuthExpiredError as exc:
            return await self._auth_expired(exc)
        except BlockedError as exc:
            # Vinted is refusing this client. A fresh cookie will not change that, so back
            # off hard and come back with a different session. The session is only
            # dropped here: minting the replacement is the next check's first step, so a
            # homepage that refuses us too is one more refusal on this same ladder rather
            # than an error escaping the loop.
            self._consecutive_errors += 1
            await self._repo.record_failure(self.query.id, "http_403", str(exc))
            await self._sessions.discard(self._site, blocked=True)
            delay = self._backoff()
            self._log.warning(
                "poll.blocked", site=self._site, error=str(exc), retry_in_s=round(delay)
            )
            return delay
        except RateLimitedError as exc:
            self._consecutive_errors += 1
            await self._repo.record_failure(self.query.id, "http_429", str(exc))
            delay = exc.retry_after or self._backoff()
            self._log.warning("poll.rate_limited", site=self._site, retry_in_s=round(delay))
            return float(delay)
        except MalformedResponseError as exc:
            # Not a retry problem: either the response shape changed or something was
            # served in its place. Keep going at normal pace and make it visible.
            self._consecutive_errors += 1
            await self._repo.record_failure(self.query.id, "malformed", str(exc))
            self._log.error("poll.malformed_response", site=self._site, error=str(exc))
            return self._interval()
        except NetworkError as exc:
            self._consecutive_errors += 1
            await self._repo.record_failure(self.query.id, "network", str(exc))
            delay = self._backoff(cap=_NETWORK_BACKOFF_CAP_S)
            self._log.warning(
                "poll.network_error", site=self._site, error=str(exc), retry_in_s=round(delay)
            )
            return delay

        self._consecutive_errors = 0
        self._consecutive_auth_failures = 0
        self.successes += 1
        return self._interval()

    async def _auth_expired(self, exc: AuthExpiredError) -> float:
        """A rejected token: retried promptly at first, on the backoff ladder if it persists."""
        # The anonymous token aged out. A new one costs a single page load.
        self._consecutive_auth_failures += 1
        await self._repo.record_failure(self.query.id, "http_401", str(exc))
        await self._sessions.invalidate(self._site)
        if self._consecutive_auth_failures < _AUTH_FAILURES_BEFORE_BACKOFF:
            self._log.info("poll.session_expired", site=self._site, error=str(exc))
            return min(5.0, float(self.query.poll_interval_s))
        self._consecutive_errors += 1
        delay = self._backoff()
        self._log.warning(
            "poll.auth_keeps_failing",
            site=self._site,
            error=str(exc),
            in_a_row=self._consecutive_auth_failures,
            retry_in_s=round(delay),
        )
        return delay

    async def _fetch(self) -> tuple[list[Item], bool]:
        """Every site's first page, in order, and whether each page was full.

        Listing ids are shared across sites, so one floor covers them all.
        """
        items: list[Item] = []
        all_full = True
        for site in self.query.sites:
            self._site = site
            page = await self._client.search(site, self.query.params)
            all_full = all_full and len(page) >= PER_PAGE
            items.extend(page)
        self._site = self.query.tld
        return items, all_full

    async def _check(self) -> None:
        items, page_is_full = await self._fetch()
        state = await self._repo.get_state(self.query.id)
        ids = [item.item_id for item in items]
        seen = await self._repo.seen_by_query(self.query.id, ids)
        window_s = (self.query.max_age_min or self._settings.freshness_window_min) * 60
        now = int(time.time())
        catching_up = dedup.needs_catch_up(
            state.last_success_at,
            now=now,
            gap_s=max(window_s, _CATCH_UP_INTERVALS * self.query.poll_interval_s),
        )
        quiet = state.is_first_run or catching_up
        selection = dedup.select(
            items=items,
            seen_ids=seen,
            floor_item_id=state.floor_item_id,
            now=now,
            freshness_window_s=window_s,
            is_first_run=quiet,
            page_is_full=page_is_full,
            listed_by=await self._repo.listed_by([i for i in ids if i not in seen]),
        )

        if quiet:
            announced = await self._seed(selection.new, announce=state.is_first_run)
        else:
            announced = await self._judge(
                selection.new, too_old=self._too_old(selection.too_old, now=now, window_s=window_s)
            )

        if announced and self._work_available is not None:
            self._work_available.set()

        await self._repo.record_success(
            self.query.id,
            newest_raw_ts=selection.newest_raw_ts,
            newest_item_ts=dedup.newest_timestamp(selection.new),
            seen=len(items),
            stale_cycles=self._stale_cycles(state, selection),
            newest_raw_id=selection.newest_raw_id,
            floor_item_id=selection.floor_item_id,
        )

        if state.is_first_run:
            self._log.info(
                "poll.seeded",
                recorded=len(selection.new),
                announced=announced,
                mode=self._settings.first_run_mode,
            )
        elif catching_up:
            self._log.info(
                "poll.caught_up",
                recorded=len(selection.new),
                offline_min=round((now - (state.last_success_at or now)) / 60),
                hint="listings from while the app was not checking are recorded, not announced",
            )
        elif announced:
            self._log.info("poll.new_items", count=announced, returned=len(items))
        else:
            self._log.debug("poll.nothing_new", returned=len(items), judged=len(selection.new))

    @staticmethod
    def _stale_cycles(state: QueryState, selection: dedup.Selection) -> int:
        """Checks in a row whose newest listing has not moved, for the watchdog."""
        if selection.newest_raw_id is None:
            return state.stale_cycles
        if selection.newest_raw_id == state.newest_raw_id:
            return state.stale_cycles + 1
        return 0

    async def _seed(self, unseen: list[Item], *, announce: bool = True) -> int:
        """Record a page without shouting about it. Returns how many announced.

        For a new search's first check, and with `announce` off for a catch-up after a
        gap. Only listings passing the cheap rules are kept, so the typical price is built
        from what the search actually wants. No seller lookups: nothing here is announced
        except perhaps one, and a first page of ninety-six would be ninety-six requests.
        """
        blocked = frozenset(await self._repo.blocked_seller_ids())
        keep = [item for item in unseen if self._rules.check(item, blocked_sellers=blocked) is None]
        pick = dedup.first_run_pick(keep, self._settings.first_run_mode) if announce else []
        if not keep:
            return 0
        destination_ids = await self._repo.destination_ids_for_query(self.query.id)
        await self._repo.record_new_items(
            self.query,
            keep,
            destination_ids,
            notify=pick,
            seeded=True,
            typical_prices=await self._repo.typical_prices(self.query.id),
            keep_raw=self._settings.keep_raw_json,
        )
        return len(pick) if destination_ids else 0

    def _too_old(
        self, entries: list[tuple[Item, int]], *, now: int, window_s: int
    ) -> list[RejectedListing]:
        """Log listings that turned up after the freshness window, unless a rule skips them
        anyway: "Not sent" should show what the search would have wanted."""
        rejected = []
        for item, listed in entries:
            if self._rules.check(item) is not None:
                continue
            detail = (
                f"already on Vinted {round((now - listed) / 60)} min ago; this search "
                f"ignores listings older than {window_s // 60} min"
            )
            rejected.append(RejectedListing(item, "too_old", detail))
        return rejected

    async def _judge(self, new: list[Item], *, too_old: list[RejectedListing]) -> int:
        """Filter what is new, record the verdicts, queue the alerts. Returns how many queued."""
        if not new and not too_old:
            return 0
        verdicts = _Verdicts(rejected=list(too_old))
        blocked = frozenset(await self._repo.blocked_seller_ids())
        for item in new:
            rejection = self._rules.check(item, blocked_sellers=blocked)
            if rejection is None:
                rejection, final = await self._judge_seller(item, verdicts)
            else:
                final = True
            if rejection is None:
                verdicts.matched.append(item)
            else:
                verdicts.rejected.append(
                    RejectedListing(item, rejection.reason, rejection.detail, final=final)
                )

        typical = await self._repo.typical_prices(self.query.id)
        for item in verdicts.matched:
            if deal := filters.check_deal(item, self.query, typical.get(item.currency or "")):
                verdicts.rejected.append(
                    RejectedListing(item, deal.reason, deal.detail, final=False)
                )
            else:
                verdicts.announce.append(item)

        self._apply_mute(verdicts)
        hold_until, silent = await self._apply_quiet_hours(verdicts)
        destination_ids = await self._repo.destination_ids_for_query(self.query.id)
        await self._repo.record_new_items(
            self.query,
            verdicts.matched,
            destination_ids,
            notify=verdicts.announce,
            rejected=verdicts.rejected,
            typical_prices=typical,
            seller_countries=verdicts.seller_countries,
            hold_until=hold_until,
            silent=silent,
            keep_raw=self._settings.keep_raw_json,
        )
        return len(verdicts.announce) if destination_ids else 0

    async def _judge_seller(
        self, item: Item, verdicts: _Verdicts
    ) -> tuple[filters.Rejection | None, bool]:
        """The seller checks for one listing: (rejection or None, whether it is final)."""
        if not self.query.needs_seller_profile:
            return None, True
        profile: SellerProfile | None = None
        if filters.needs_lookup(item, self.query):
            if self._seller_lookup is None:
                self._warn_no_lookup()
            else:
                profile = await self._seller_profile(item, verdicts)
                if profile is None:
                    # Not final: a lookup that failed this time may work next time.
                    paused = time.time() < self._lookups_paused_until
                    detail = (
                        "seller lookups are paused because Vinted refused them; "
                        "tried again on a later check"
                        if paused
                        else "could not look up the seller just now"
                    )
                    return filters.Rejection("seller_unknown", detail), False
                if profile.country_code:
                    verdicts.seller_countries[profile.seller_id] = profile.country_code
        return filters.check_seller(item, self.query, profile), True

    async def _seller_profile(self, item: Item, verdicts: _Verdicts) -> SellerProfile | None:
        """A seller's member page, from this check's memo, the cache, or one request."""
        seller_id = item.seller_id
        if seller_id is None or self._seller_lookup is None:
            return None
        if seller_id in verdicts.profiles:
            return verdicts.profiles[seller_id]
        cached = await self._repo.cached_seller(seller_id, max_age_s=SELLER_CACHE_S)
        if cached is not None:
            verdicts.profiles[seller_id] = cached
            return cached
        if verdicts.lookups_made >= _MAX_LOOKUPS_PER_CHECK:
            return None
        if time.time() < self._lookups_paused_until:
            return None
        verdicts.lookups_made += 1
        try:
            profile = await self._seller_lookup(item.tld, seller_id)
        except (BlockedError, RateLimitedError) as exc:
            # Vinted is refusing these lookups. Asking again for the next listing in the
            # same check would only add to the refusals: stop until the pause is over,
            # honouring Retry-After when given. The listings wait, logged as undecided.
            retry_after = exc.retry_after if isinstance(exc, RateLimitedError) else None
            pause = float(retry_after or _LOOKUP_PAUSE_S)
            self._lookups_paused_until = time.time() + pause
            self._log.warning(
                "poll.seller_lookups_paused",
                seller_id=seller_id,
                error=str(exc),
                retry_in_s=round(pause),
            )
            profile = None
        except VintedError as exc:
            # The listing is logged as undecided and judged again next check, by which
            # time the session has usually sorted itself out.
            self._log.info("poll.seller_lookup_failed", seller_id=seller_id, error=str(exc))
            profile = None
        verdicts.profiles[seller_id] = profile
        if profile is not None:
            await self._repo.cache_seller(profile)
        return profile

    def _warn_no_lookup(self) -> None:
        if not self._warned_no_lookup:
            self._warned_no_lookup = True
            self._log.warning(
                "poll.seller_filters_unavailable",
                hint="seller country and rating filters need seller lookups, which this "
                "build cannot do yet; listings are passed through unjudged",
            )

    def _apply_mute(self, verdicts: _Verdicts) -> None:
        """Announce nothing while the search is muted; log what was held back and why."""
        now = int(time.time())
        if not verdicts.announce or not self.query.is_muted(now):
            return
        minutes = max(1, round(((self.query.muted_until or now) - now) / 60))
        verdicts.rejected.extend(
            RejectedListing(item, "muted", f"search muted for another {minutes} min", final=False)
            for item in verdicts.announce
        )
        verdicts.announce = []

    async def _apply_quiet_hours(self, verdicts: _Verdicts) -> tuple[int | None, bool]:
        """Hold, drop or silence this check's alerts if the search is in its quiet hours."""
        if not verdicts.announce or self.query.quiet_start is None:
            return None, False
        app = await self._repo.app_settings(default_timezone=self._settings.timezone)
        ends = quiet.window_end(
            self.query.quiet_start, self.query.quiet_end, datetime.now(ZoneInfo(app.timezone))
        )
        if ends is None:
            return None, False
        match self.query.quiet_mode:
            case "drop":
                verdicts.rejected.extend(
                    RejectedListing(
                        item, "quiet_hours", f"quiet until {self.query.quiet_end}", final=False
                    )
                    for item in verdicts.announce
                )
                verdicts.announce = []
                return None, False
            case "silent":
                return None, True
            case _:
                return int(ends.timestamp()), False

    def _interval(self) -> float:
        base = float(self.query.poll_interval_s)
        return base + self._rng.uniform(0, base * _JITTER_FRACTION)

    def _backoff(self, *, cap: float = MAX_BACKOFF_S) -> float:
        """Exponential backoff with jitter, capped so a search never sleeps forever.

        The jitter goes on after the cap. Clipping it away is what made every failing
        search retry in the same second.
        """
        step = min(2.0**self._consecutive_errors * self.query.poll_interval_s, cap)
        return step + self._rng.uniform(0, step * _JITTER_FRACTION)

    async def _wait(self, seconds: float) -> None:
        """Sleep, but wake immediately if the app is shutting down."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
