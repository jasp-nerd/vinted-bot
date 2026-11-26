"""Starting everything up and shutting it down cleanly.

One process, one event loop, one SQLite file. A task per search, a dispatcher, a watchdog,
a heartbeat, and optionally the web UI and the Telegram bot. A supervisor keeps the running
searches in step with what is in the database, so adding one in the web UI takes effect
without a restart.

Shutdown matters more than it sounds. Docker sends SIGTERM and waits about ten seconds
before killing the process; a loop sitting in a sixty-second sleep will be killed mid-send
every single time. So nothing here sleeps — everything waits on a stop event with a
timeout, which comes back the instant a signal arrives.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import signal
import sqlite3
import subprocess
import sys
import webbrowser
from collections.abc import Awaitable, Callable

import httpx

from vinted_bot import control, instance, shortcuts, telemetry
from vinted_bot.config import MAX_BACKOFF_S, Settings
from vinted_bot.db import Database, apply_pending
from vinted_bot.db.repo import Query, Repo
from vinted_bot.deliver.dispatcher import Dispatcher
from vinted_bot.engine import awake, rates, self_update, updates, wakeups
from vinted_bot.engine.health import Heartbeat
from vinted_bot.engine.poller import Poller
from vinted_bot.engine.watchdog import Watchdog
from vinted_bot.engine.watcher import Watcher
from vinted_bot.log import get_logger
from vinted_bot.telemetry.service import Telemetry, asyncio_errors
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.proxies import ProxyRotation
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.taxonomy import Taxonomy
from vinted_bot.vinted.transport import Transport, TransportPool, build_transport

log = get_logger(__name__)

# How often to look whether someone asked vinted-bot to stop (Settings, `vinted-bot stop`).
STOP_CHECK_INTERVAL_S = 1.0

# How often to notice searches added, paused or edited elsewhere.
SUPERVISE_INTERVAL_S = 15.0

# Housekeeping: prune old listings and the rejections log, check for a newer release.
HOUSEKEEPING_INTERVAL_S = 3600.0


# Searches started in the same pass — all of them, after a restart — begin this far apart
# (plus jitter), so they do not hit the site in the same second.
STARTUP_SPACING_S = 2.0

# How long `run --open` waits for the dashboard to start listening.
_OPEN_BROWSER_WAIT_S = 20.0


class Application:
    """The whole running system."""

    def __init__(
        self,
        settings: Settings,
        *,
        supervise_interval_s: float = SUPERVISE_INTERVAL_S,
        open_browser: bool = False,
        install: self_update.Install | None = None,
    ) -> None:
        self._settings = settings
        # How this copy was installed; worked out at startup unless a test says.
        self._install = install
        self._supervise_interval_s = supervise_interval_s
        self._open_browser = open_browser
        self._stop = asyncio.Event()
        self._work_available = asyncio.Event()
        # Set by engine/wakeups.py when the computer woke up or changed networks.
        self._woke = asyncio.Event()
        # Set when a search starts, so a search spanning currencies gets its exchange
        # rates at once rather than at the next five-minutely look.
        self._rates_wanted = asyncio.Event()
        # Set by the dashboard when the Telegram bot's token is added, replaced or removed.
        self._telegram_token_changed = asyncio.Event()
        self._rng = random.Random()
        self._poller_tasks: dict[int, asyncio.Task[None]] = {}
        # The search as its poller was started with it. Any edit makes it unequal, and
        # the poller is restarted with the new rules on the next pass.
        self._poller_signatures: dict[int, Query] = {}
        # Crashes in a row per search, for spacing out restarts. A crash after at least
        # one good check starts the count again.
        self._crashes: dict[int, int] = {}

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> int:
        """Run until stopped. The exit code: RESTART_EXIT_CODE after an update."""
        settings = self._settings

        async with Database(settings.db_path) as db:
            await apply_pending(db)
            repo = Repo(db)

            proxies = ProxyRotation.from_file(settings.proxy_file)
            pool = _transport_pool(settings)
            # For the health check ping, the daily update check and usage statistics,
            # never for Vinted.
            http = httpx.AsyncClient(timeout=10.0)
            updater = self_update.Updater(settings, repo, self._stop, self._install)
            usage = Telemetry(
                settings, repo, self._stop, http, updater.install, proxies=len(proxies.proxies)
            )
            try:
                sessions = SessionManager(
                    db,
                    pool,
                    rotate_after_minutes=settings.session_rotate_minutes,
                    proxies=proxies,
                )
                client = VintedClient(
                    None,
                    sessions,
                    keep_raw=settings.keep_raw_json,
                    searches_per_s=settings.max_searches_per_s,
                )
                dispatcher = Dispatcher(
                    repo=repo,
                    settings=settings,
                    stop=self._stop,
                    work_available=self._work_available,
                )
                watchdog = Watchdog(
                    repo=repo,
                    sessions=sessions,
                    settings=settings,
                    stop=self._stop,
                    announce=dispatcher.notify_status,
                )
                heartbeat = Heartbeat(repo, self._stop, http=http)
                watcher = Watcher(
                    repo=repo,
                    stop=self._stop,
                    work_available=self._work_available,
                    item_snapshot=client.item_snapshot,
                    seller_items=client.seller_items,
                )

                await self._starting(repo, updater)

                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(dispatcher.run(), name="dispatcher")
                        tg.create_task(watchdog.run(), name="watchdog")
                        tg.create_task(heartbeat.run(), name="heartbeat")
                        tg.create_task(watcher.run(), name="watcher")
                        self._start_chores(
                            tg, repo, http, updater=updater, dispatcher=dispatcher, usage=usage
                        )
                        tg.create_task(
                            self._supervise(tg, repo, client, sessions), name="supervisor"
                        )

                        tg.create_task(self._run_telegram_bot(repo), name="telegram-bot")
                        if settings.web_enabled:
                            taxonomy = Taxonomy(sessions, repo)
                            tg.create_task(
                                self._run_web(
                                    repo, taxonomy, client, watcher.available_kinds, updater
                                ),
                                name="web",
                            )
                            if self._open_browser:
                                tg.create_task(self._open_dashboard(), name="open-browser")
                except* Exception as group:
                    for error in group.exceptions:
                        log.exception("app.task_failed", error=str(error))
                    raise
                # A shutdown halfway through an upgrade would leave it half installed.
                await updater.settle()
            finally:
                # Outside the task group, so a crash that ended it is still reported.
                await usage.shutdown()
                await http.aclose()
                await pool.aclose()

        if updater.restart_requested:
            log.info("app.stopped", restarting_for="update")
            return self_update.RESTART_EXIT_CODE
        log.info("app.stopped")
        return 0

    def _start_chores(
        self,
        tg: asyncio.TaskGroup,
        repo: Repo,
        http: httpx.AsyncClient,
        *,
        updater: self_update.Updater,
        dispatcher: Dispatcher,
        usage: Telemetry,
    ) -> None:
        """The background jobs that are not about searches or alerts."""
        tg.create_task(usage.run(), name="telemetry")
        tg.create_task(wakeups.watch(self._stop, self._woke), name="wakeups")
        tg.create_task(
            self._housekeeping(repo, http, updater.install, dispatcher.notify_status),
            name="housekeeping",
        )
        if self._settings.fetch_mode == "live":
            tg.create_task(
                rates.keep_fresh(repo, http, self._stop, self._rates_wanted), name="rates"
            )
        tg.create_task(updater.run_automatically(), name="auto-update")
        tg.create_task(self._report_update(repo, dispatcher), name="update-report")
        tg.create_task(self._watch_for_stop(), name="stop-request")
        tg.create_task(awake.keep(repo, self._settings, self._stop), name="keep-awake")

    async def _watch_for_stop(self) -> None:
        """Shut down cleanly when someone stops vinted-bot on purpose (instance.py)."""
        while not self._stop.is_set():
            if instance.is_stopped(self._settings):
                log.info("app.stop_requested")
                self._stop.set()
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=STOP_CHECK_INTERVAL_S)

    # --- Supervision ---------------------------------------------------------------

    async def _supervise(
        self,
        tg: asyncio.TaskGroup,
        repo: Repo,
        client: VintedClient,
        sessions: SessionManager,
    ) -> None:
        """Keep one running task per active search."""
        while not self._stop.is_set():
            try:
                await self._reconcile(tg, repo, client, sessions)
            except Exception as exc:
                log.exception("supervisor.failed", error=str(exc))

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._supervise_interval_s)

        for task in self._poller_tasks.values():
            task.cancel()

    async def _reconcile(
        self,
        tg: asyncio.TaskGroup,
        repo: Repo,
        client: VintedClient,
        sessions: SessionManager,
    ) -> None:
        queries = {query.id: query for query in await repo.list_queries(include_paused=False)}

        for query_id in list(self._poller_tasks):
            query = queries.get(query_id)
            task = self._poller_tasks[query_id]
            changed = query is not None and query != self._poller_signatures.get(query_id)
            if query is None or changed or task.done():
                task.cancel()
                del self._poller_tasks[query_id]
                self._poller_signatures.pop(query_id, None)
                if query is None or changed:
                    # An edit is a reason to try again straight away.
                    self._crashes.pop(query_id, None)
                if query is None:
                    log.info("poller.stopped", query_id=query_id)

        starting = [
            query for query_id, query in queries.items() if query_id not in self._poller_tasks
        ]
        for position, query in enumerate(starting):
            query_id = query.id
            # The first starts at once, so a newly added search checks straight away.
            delay = position * STARTUP_SPACING_S
            if position:
                delay += self._rng.uniform(0, STARTUP_SPACING_S)
            delay = min(delay, float(query.poll_interval_s))
            if crashes := self._crashes.get(query_id, 0):
                delay = self._restart_delay(query, crashes)
            poller = Poller(
                query,
                repo=repo,
                client=client,
                sessions=sessions,
                settings=self._settings,
                stop=self._stop,
                work_available=self._work_available,
                seller_lookup=client.seller,
                start_delay_s=delay,
                woke=self._woke,
            )
            self._poller_tasks[query_id] = tg.create_task(
                self._guard(poller), name=f"poll:{query_id}"
            )
            self._poller_signatures[query_id] = query
            self._rates_wanted.set()
            telemetry.milestone("first_search")
            log.info(
                "poller.started",
                query_id=query_id,
                query=query.name,
                tld=query.tld,
                sites=query.sites,
                every_s=query.poll_interval_s,
                start_in_s=round(delay, 1),
            )

    def _restart_delay(self, query: Query, crashes: int) -> float:
        """How long a crashed search waits before its next start: the backoff ladder.

        Restarting at once would turn a search that crashes on every check into one that
        asks Vinted for something every supervisor pass, forever.
        """
        step = min(2.0 ** (crashes - 1) * query.poll_interval_s, MAX_BACKOFF_S)
        return step + self._rng.uniform(0, step * 0.15)

    async def _guard(self, poller: Poller) -> None:
        """Run a search's loop so that its failure cannot take the others down with it."""
        query_id = poller.query.id
        try:
            await poller.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            crashes = 1 if poller.successes else self._crashes.get(query_id, 0) + 1
            self._crashes[query_id] = crashes
            log.exception(
                "poller.crashed",
                query_id=query_id,
                error=str(exc),
                crashes_in_a_row=crashes,
            )

    # --- Background chores ---------------------------------------------------------

    async def _housekeeping(
        self,
        repo: Repo,
        http: httpx.AsyncClient,
        install: self_update.Install,
        notify: Callable[[str], Awaitable[None]],
    ) -> None:
        while not self._stop.is_set():
            try:
                pruned = await repo.prune_items(self._settings.item_retention_days)
                rejections = await repo.prune_rejections()
                if pruned or rejections:
                    log.debug("housekeeping.pruned", items=pruned, rejections=rejections)
                # Offline mode is offline: no call to GitHub either.
                if self._settings.fetch_mode == "live":
                    await updates.check_for_update(repo, http)
                    await self_update.announce_new_version(repo, install, self._settings, notify)
            except sqlite3.OperationalError as exc:
                # A locked database; the next pass an hour from now will catch up.
                log.warning("housekeeping.db_unavailable", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=HOUSEKEEPING_INTERVAL_S)

    async def _report_update(self, repo: Repo, dispatcher: Dispatcher) -> None:
        """Say how the update that restarted the app went (self_update.finish_pending)."""
        try:
            await self_update.finish_pending(repo, dispatcher.notify_status)
        except sqlite3.OperationalError as exc:
            # A locked database: the note stays, and the next start reports it instead.
            log.warning("update.report_failed", error=str(exc))

    async def _run_telegram_bot(self, repo: Repo) -> None:
        from vinted_bot.botctl.telegram_bot import keep_running  # noqa: PLC0415

        await keep_running(
            self._settings,
            repo,
            stop=self._stop,
            token_changed=self._telegram_token_changed,
        )

    async def _run_web(
        self,
        repo: Repo,
        taxonomy: Taxonomy,
        client: VintedClient,
        watch_kinds: frozenset[str],
        updater: self_update.Updater,
    ) -> None:
        # Imported here so CLI commands that never serve the dashboard skip loading FastAPI.
        from vinted_bot.web.server import serve  # noqa: PLC0415

        try:
            await serve(
                self._settings,
                repo,
                self._stop,
                taxonomy,
                client=client,
                watch_kinds=watch_kinds,
                updater=updater,
                telegram_token_changed=self._telegram_token_changed,
            )
        except Exception as exc:
            log.exception("web.failed", error=str(exc))

    async def _open_dashboard(self) -> None:
        """Open the dashboard in a browser once it is listening (`run --open`)."""
        url = self._settings.dashboard_url
        if url is None:  # pragma: no cover - only scheduled while the web UI is on
            return
        host = (
            "127.0.0.1" if self._settings.web_host in {"0.0.0.0", "::"} else self._settings.web_host
        )
        deadline = asyncio.get_running_loop().time() + _OPEN_BROWSER_WAIT_S
        while not self._stop.is_set() and asyncio.get_running_loop().time() < deadline:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, self._settings.web_port), timeout=1.0
                )
            except (OSError, TimeoutError):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=0.25)
                continue
            writer.close()
            await writer.wait_closed()
            # webbrowser can block while it launches a process, so it gets a thread.
            await asyncio.to_thread(webbrowser.open, url)
            log.info("web.opened", url=url)
            return
        log.warning("web.open_timed_out", url=url)

    # --- Signals -------------------------------------------------------------------

    async def _starting(self, repo: Repo, updater: self_update.Updater) -> None:
        settings = self._settings
        await self_update.default_for_new_install(repo, updater.install, settings)
        if settings.supervised:
            await _upgrade_service(settings, repo)
        self._install_signal_handlers()
        log.info(
            "app.starting",
            db=str(settings.db_path),
            fetch_mode=settings.fetch_mode,
            web=settings.web_enabled,
            install=updater.install.kind.value,
            supervisor=settings.supervised,
        )

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        # And errors in tasks nobody awaited, for the error reports.
        loop.set_exception_handler(asyncio_errors)
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._on_signal, sig)

    def _on_signal(self, sig: signal.Signals) -> None:
        log.info("app.signal", signal=sig.name)
        self._stop.set()


async def _upgrade_service(settings: Settings, repo: Repo) -> None:
    """Bring a start-at-login entry from an older installer up to date (control.py), and
    keep its choice about keeping the Mac awake, which now lives in Settings."""
    try:
        kept_awake = await asyncio.to_thread(control.upgrade_service, settings)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.warning("app.service_upgrade_failed", error=str(exc))
        return
    if kept_awake is not None:
        log.info("app.service_upgraded")
        if await repo.get_state_value(awake.KEY) is None:
            await awake.set_wanted(repo, kept_awake)


def _make_icon(settings: Settings) -> None:
    """Under the installers' service, make sure there is an icon to open vinted-bot with:
    copies that updated themselves from before icons existed get theirs this way."""
    if not settings.supervised or settings.fetch_mode != "live":
        return
    if self_update.detect(settings).kind is self_update.InstallKind.SOURCE:
        return
    try:
        if shortcuts.ensure(settings):
            log.info("app.icon_made")
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("app.icon_failed", error=str(exc))


def _transport_pool(settings: Settings) -> TransportPool:
    """Where Vinted requests go: one transport per proxy, or one without."""
    mock_dir = settings.mock_scenario_dir if settings.fetch_mode == "mock" else None

    def build(proxy: str | None) -> Transport:
        return build_transport(
            impersonate=settings.http_impersonate,
            timeout=settings.request_timeout_s,
            proxy=proxy,
            mock_dir=mock_dir,
        )

    return TransportPool(build)


async def run(settings: Settings, *, open_browser: bool = False) -> int:
    """`vinted-bot run`: one copy per database, and stopped stays stopped.

    A background service starting it at login while someone had stopped it exits at once
    with 0, which none of the services restart from. Started by hand, it runs anyway: that
    is someone asking for it.
    """
    if settings.supervised and instance.is_stopped(settings):
        log.info("app.stopped_on_purpose", hint="open vinted-bot to start it again")
        control.leave_stopped(settings)
        return 0
    try:
        with instance.Instance(settings):
            # Only the copy that actually runs clears a stop: a second `run` refused below
            # must not cancel one that is on its way.
            instance.clear_stopped(settings)
            _make_icon(settings)
            return await Application(settings, open_browser=open_browser).run()
    except instance.AlreadyRunningError as exc:
        url = exc.running.url if exc.running else f"http://localhost:{settings.web_port}"
        log.warning("app.already_running", url=url)
        print(
            f"vinted-bot is already running, at {url}. To open it, type: vinted-bot",
            file=sys.stderr,
        )
        # A service that finds a copy started by hand has nothing to retry.
        return 0 if settings.supervised else 1
