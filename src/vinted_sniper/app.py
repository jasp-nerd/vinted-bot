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
import webbrowser

import httpx

from vinted_sniper.config import MAX_BACKOFF_S, Settings
from vinted_sniper.db import Database, apply_pending
from vinted_sniper.db.repo import Query, Repo
from vinted_sniper.deliver.dispatcher import Dispatcher
from vinted_sniper.engine import updates
from vinted_sniper.engine.health import Heartbeat
from vinted_sniper.engine.poller import Poller
from vinted_sniper.engine.watchdog import Watchdog
from vinted_sniper.engine.watcher import Watcher
from vinted_sniper.log import get_logger
from vinted_sniper.vinted.client import VintedClient
from vinted_sniper.vinted.proxies import ProxyRotation
from vinted_sniper.vinted.session import SessionManager
from vinted_sniper.vinted.taxonomy import Taxonomy
from vinted_sniper.vinted.transport import Transport, TransportPool, build_transport

log = get_logger(__name__)

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
    ) -> None:
        self._settings = settings
        self._supervise_interval_s = supervise_interval_s
        self._open_browser = open_browser
        self._stop = asyncio.Event()
        self._work_available = asyncio.Event()
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

    async def run(self) -> None:
        settings = self._settings

        async with Database(settings.db_path) as db:
            await apply_pending(db)
            repo = Repo(db)

            proxies = ProxyRotation.from_file(settings.proxy_file)
            mock_dir = settings.mock_scenario_dir if settings.fetch_mode == "mock" else None

            def build(proxy: str | None) -> Transport:
                return build_transport(
                    impersonate=settings.http_impersonate,
                    timeout=settings.request_timeout_s,
                    proxy=proxy,
                    mock_dir=mock_dir,
                )

            pool = TransportPool(build)
            # For the health check ping and the daily update check, never for Vinted.
            http = httpx.AsyncClient(timeout=10.0)
            try:
                sessions = SessionManager(
                    db,
                    pool,
                    rotate_after_minutes=settings.session_rotate_minutes,
                    proxies=proxies,
                )
                client = VintedClient(None, sessions, keep_raw=settings.keep_raw_json)
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

                self._install_signal_handlers()
                log.info(
                    "app.starting",
                    db=str(settings.db_path),
                    fetch_mode=settings.fetch_mode,
                    web=settings.web_enabled,
                )

                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(dispatcher.run(), name="dispatcher")
                        tg.create_task(watchdog.run(), name="watchdog")
                        tg.create_task(heartbeat.run(), name="heartbeat")
                        tg.create_task(watcher.run(), name="watcher")
                        tg.create_task(self._housekeeping(repo, http), name="housekeeping")
                        tg.create_task(
                            self._supervise(tg, repo, client, sessions), name="supervisor"
                        )

                        if settings.telegram_bot_token is not None:
                            tg.create_task(self._run_telegram_bot(repo), name="telegram-bot")
                        if settings.web_enabled:
                            taxonomy = Taxonomy(sessions, repo)
                            tg.create_task(
                                self._run_web(repo, taxonomy, client, watcher.available_kinds),
                                name="web",
                            )
                            if self._open_browser:
                                tg.create_task(self._open_dashboard(), name="open-browser")
                except* Exception as group:
                    for error in group.exceptions:
                        log.exception("app.task_failed", error=str(error))
                    raise
            finally:
                await http.aclose()
                await pool.aclose()

        log.info("app.stopped")

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
            )
            self._poller_tasks[query_id] = tg.create_task(
                self._guard(poller), name=f"poll:{query_id}"
            )
            self._poller_signatures[query_id] = query
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

    async def _housekeeping(self, repo: Repo, http: httpx.AsyncClient) -> None:
        while not self._stop.is_set():
            try:
                pruned = await repo.prune_items(self._settings.item_retention_days)
                rejections = await repo.prune_rejections()
                if pruned or rejections:
                    log.debug("housekeeping.pruned", items=pruned, rejections=rejections)
                # Offline mode is offline: no call to GitHub either.
                if self._settings.fetch_mode == "live":
                    await updates.check_for_update(repo, http)
            except sqlite3.OperationalError as exc:
                # A locked database; the next pass an hour from now will catch up.
                log.warning("housekeeping.db_unavailable", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=HOUSEKEEPING_INTERVAL_S)

    async def _run_telegram_bot(self, repo: Repo) -> None:
        from vinted_sniper.botctl.telegram_bot import run_bot  # noqa: PLC0415

        token = self._settings.telegram_bot_token
        if token is None:  # pragma: no cover - guarded by the caller
            return
        try:
            await run_bot(token.get_secret_value(), repo=repo, stop=self._stop)
        except Exception as exc:
            log.exception("telegram_bot.failed", error=str(exc))

    async def _run_web(
        self,
        repo: Repo,
        taxonomy: Taxonomy,
        client: VintedClient,
        watch_kinds: frozenset[str],
    ) -> None:
        # Imported here so CLI commands that never serve the dashboard skip loading FastAPI.
        from vinted_sniper.web.server import serve  # noqa: PLC0415

        try:
            await serve(
                self._settings,
                repo,
                self._stop,
                taxonomy,
                client=client,
                watch_kinds=watch_kinds,
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

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._on_signal, sig)

    def _on_signal(self, sig: signal.Signals) -> None:
        log.info("app.signal", signal=sig.name)
        self._stop.set()


async def run(settings: Settings, *, open_browser: bool = False) -> None:
    await Application(settings, open_browser=open_browser).run()
