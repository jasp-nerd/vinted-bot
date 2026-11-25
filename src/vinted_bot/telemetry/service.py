"""Deciding whether to send usage statistics, and sending them.

Like t3code and most open-source apps that measure use, this is on unless switched off:
in the dashboard (Settings, Advanced) or with VINTED_BOT_TELEMETRY=false, which wins.
It is always off in CI, under pytest, when running from a copy of the source code and in
mock mode, so development and tests never count as installs.

Events go in batches to a small proxy on the maintainer's server, which passes them to
PostHog without the sender's address. Each install is a random id kept in the database;
nothing ties it to a person. When sending fails, the batch waits and is tried again with
growing pauses, for half an hour at most; after that it is dropped rather than retried
forever.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping
from http import HTTPStatus
from typing import Any

import httpx

from vinted_bot import __version__
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine import self_update
from vinted_bot.log import get_logger
from vinted_bot.telemetry import facts, recorder

log = get_logger(__name__)

ENDPOINT = "https://ingest.jaspnerd.dev"
# PostHog's project key: it can only add events, never read them, so it is not a secret.
PROJECT_KEY = "phc_ufH4FPmt6CHvaEDyqrNHqd2P5Xd8qCFx5ysgpoymKcxk"  # gitleaks:allow

FLUSH_EVERY_S = 60.0
SAVE_EVERY_S = 600.0
HEARTBEAT_EVERY_S = 86_400
BATCH_SIZE = 50
SHUTDOWN_FLUSH_S = 3.0
RETRY_FIRST_S = 60.0
RETRY_MAX_S = 900.0
GIVE_UP_AFTER_S = 1800.0
# The batch itself was refused; sending it again cannot help.
_REJECTED = frozenset({400, 401, 403, 413})

_SWITCH_KEY = "telemetry"
_INSTALL_ID_KEY = "telemetry_install_id"
_INSTALLED_AT_KEY = "telemetry_installed_at"
_VERSION_KEY = "telemetry_version"
_HEARTBEAT_KEY = "telemetry_heartbeat_at"
_COUNTERS_KEY = "telemetry_counters"
_MILESTONES_KEY = "telemetry_milestones"


# --- Whether to send ----------------------------------------------------------------


def from_environment(settings: Settings) -> bool:
    """Whether VINTED_BOT_TELEMETRY decides, instead of the dashboard's switch."""
    return "telemetry" in settings.model_fields_set


def never_here(
    settings: Settings, install: self_update.Install, environ: Mapping[str, str]
) -> bool:
    """CI, tests, a copy of the source and mock mode are development, not an install."""
    return (
        settings.fetch_mode != "live"
        or install.kind is self_update.InstallKind.SOURCE
        or any(environ.get(name) for name in ("CI", "GITHUB_ACTIONS", "PYTEST_CURRENT_TEST"))
    )


async def switched_on(settings: Settings, repo: Repo) -> bool:
    """The setting as the dashboard shows it: the environment's, else the switch's."""
    if from_environment(settings):
        return settings.telemetry
    return await repo.get_state_value(_SWITCH_KEY) != "0"


async def set_switch(repo: Repo, on: bool) -> None:
    """The dashboard's switch. Off means off now: anything waiting to be sent is dropped."""
    await repo.set_state_value(_SWITCH_KEY, "1" if on else "0")
    if not on:
        recorder.deactivate()


# --- Sending ------------------------------------------------------------------------


class Telemetry:
    """Runs beside everything else: once a minute, decide, then send what was recorded."""

    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        stop: asyncio.Event,
        http: httpx.AsyncClient,
        install: self_update.Install,
        *,
        proxies: int = 0,
        endpoint: str = ENDPOINT,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._stop = stop
        self._http = http
        self._install = install
        self._proxies = proxies
        self._url = endpoint.rstrip("/") + "/batch/"
        self._environ = os.environ if environ is None else environ
        self._clock = clock
        self._on = False
        self._install_id = ""
        self._base: dict[str, Any] = {}
        self._started_at = clock()
        self._saved_at = 0.0
        self._retry_at = 0.0
        self._failing_since: float | None = None
        self._failures = 0

    async def run(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=FLUSH_EVERY_S)

    async def tick(self) -> None:
        """One pass. Never raises: usage statistics must not stop the app."""
        try:
            await self._tick()
        except (sqlite3.OperationalError, httpx.HTTPError, ValueError) as exc:
            log.debug("telemetry.skipped", error=type(exc).__name__)

    async def shutdown(self) -> None:
        """Say the app stopped, keep today's counts, and send what fits in a moment."""
        if not self._on:
            return
        try:
            recorder.event("app_stopped", uptime_s=round(self._clock() - self._started_at))
            await self._save_counters()
            await asyncio.wait_for(self._flush(), timeout=SHUTDOWN_FLUSH_S)
        except (TimeoutError, sqlite3.OperationalError, httpx.HTTPError):
            pass

    async def _tick(self) -> None:
        allowed = not never_here(self._settings, self._install, self._environ) and (
            await switched_on(self._settings, self._repo)
        )
        if self._on and not recorder.is_active():
            # Switched off in the dashboard (which stops recording at once) since the last
            # pass; switched back on, it starts over like a fresh start.
            self._on = False
        if not allowed:
            if self._on:
                recorder.deactivate()
                self._on = False
            return
        if not self._on:
            await self._begin()
        await self._milestones()
        await self._heartbeat_if_due()
        if self._clock() - self._saved_at >= SAVE_EVERY_S:
            await self._save_counters()
        await self._flush()

    # --- Lifecycle events -------------------------------------------------------

    async def _begin(self) -> None:
        repo = self._repo
        now = int(self._clock())
        install_id = await repo.get_state_value(_INSTALL_ID_KEY)
        recorder.activate()
        self._on = True
        if install_id is None:
            install_id = uuid.uuid4().hex
            await repo.set_state_value(_INSTALL_ID_KEY, install_id)
            prefs = await repo.app_settings(default_timezone=self._settings.timezone)
            # A database with searches in it was installed before this version counted.
            if not prefs.onboarded and not await repo.list_queries():
                await repo.set_state_value(_INSTALLED_AT_KEY, str(now))
                recorder.event("app_installed")
        self._install_id = install_id
        self._base = facts.base_properties(self._install)
        with contextlib.suppress(ValueError, TypeError):
            recorder.restore_counters(json.loads(await repo.get_state_value(_COUNTERS_KEY) or "{}"))

        previous = await repo.get_state_value(_VERSION_KEY)
        if previous is not None and previous != __version__:
            recorder.event("app_updated", from_version=previous, to_version=__version__)
        await repo.set_state_value(_VERSION_KEY, __version__)
        if await repo.get_state_value(_HEARTBEAT_KEY) is None:
            await repo.set_state_value(_HEARTBEAT_KEY, str(now))

        recorder.count("starts")
        recorder.event(
            "app_started",
            **await self._facts(),
            days_since_install=await self._days_since_install(now),
        )

    async def _facts(self) -> dict[str, Any]:
        return {
            **await facts.environment(
                self._settings, self._repo, self._install, proxies=self._proxies
            ),
            **await facts.snapshot(self._repo, timezone=self._settings.timezone),
        }

    async def _installed_at(self) -> int | None:
        value = await self._repo.get_state_value(_INSTALLED_AT_KEY)
        return int(value) if value and value.isdigit() else None

    async def _days_since_install(self, now: int) -> int | None:
        installed = await self._installed_at()
        return None if installed is None else (now - installed) // 86_400

    async def _milestones(self) -> None:
        reached = recorder.take_milestones()
        if not reached:
            return
        raw = await self._repo.get_state_value(_MILESTONES_KEY)
        done: set[str] = set(json.loads(raw)) if raw else set()
        installed = await self._installed_at()
        now = int(self._clock())
        for name, properties in reached.items():
            if name in done:
                continue
            done.add(name)
            # Only for installs counted from the start: for older ones it isn't a first.
            if installed is not None:
                recorder.event(name, seconds_since_install=now - installed, **properties)
        await self._repo.set_state_value(_MILESTONES_KEY, json.dumps(sorted(done)))

    async def _heartbeat_if_due(self) -> None:
        now = int(self._clock())
        last = await self._repo.get_state_value(_HEARTBEAT_KEY)
        since = int(last) if last and last.isdigit() else now
        if now - since < HEARTBEAT_EVERY_S:
            return
        counters, timings = recorder.take_totals()
        recorder.event(
            "app_heartbeat",
            **await self._facts(),
            counters=counters,
            timings=timings,
            period_s=now - since,
            uptime_s=round(self._clock() - self._started_at),
            days_since_install=await self._days_since_install(now),
        )
        await self._repo.set_state_value(_HEARTBEAT_KEY, str(now))
        await self._save_counters()

    async def _save_counters(self) -> None:
        """Keep the day's counts in the database, so a restart doesn't lose them."""
        await self._repo.set_state_value(_COUNTERS_KEY, json.dumps(recorder.peek_counters()))
        self._saved_at = self._clock()

    # --- Delivery ---------------------------------------------------------------

    def _payload(self, batch: list[recorder.Pending]) -> dict[str, Any]:
        return {
            "api_key": PROJECT_KEY,
            "batch": [
                {
                    "uuid": pending.uuid,
                    "event": pending.name,
                    "distinct_id": self._install_id,
                    "timestamp": pending.timestamp,
                    "properties": {
                        **self._base,
                        **pending.properties,
                        "$lib": "vinted-bot",
                        "$lib_version": __version__,
                        # One install is not a person: no profile, no location.
                        "$process_person_profile": False,
                        "$geoip_disable": True,
                    },
                }
                for pending in batch
            ],
        }

    async def _flush(self) -> None:
        now = self._clock()
        if now < self._retry_at:
            return
        events = recorder.take_events()
        while events:
            batch, events = events[:BATCH_SIZE], events[BATCH_SIZE:]
            status = await self._send(batch)
            if status is None:
                self._failing_since, self._failures = None, 0
                continue
            if status in _REJECTED:
                log.debug("telemetry.rejected", status=status, events=len(batch))
                continue
            self._failures += 1
            self._failing_since = self._failing_since or now
            if now - self._failing_since >= GIVE_UP_AFTER_S:
                log.debug("telemetry.dropped", events=len(batch) + len(events))
                self._failing_since, self._failures = None, 0
                return
            self._retry_at = now + min(RETRY_FIRST_S * 2 ** (self._failures - 1), RETRY_MAX_S)
            recorder.requeue(batch + events)
            return

    async def _send(self, batch: list[recorder.Pending]) -> int | None:
        """None when the batch arrived, else the status (503 for no answer at all)."""
        try:
            response = await self._http.post(self._url, json=self._payload(batch), timeout=10.0)
        except httpx.HTTPError:
            return HTTPStatus.SERVICE_UNAVAILABLE
        return None if response.is_success else response.status_code


def asyncio_errors(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """The event loop's handler for errors nothing awaited: report, then log as usual."""
    exc = context.get("exception")
    if isinstance(exc, BaseException):
        recorder.capture_exception(exc, where="asyncio", handled=False)
    loop.default_exception_handler(context)
