"""The dashboard's web server: the app factory, its guards, and running it.

On by default, bound to localhost unless you say otherwise. It exists because editing a
config file is where most people give up: pasting a Vinted link into a box is not.

Three guards sit in front of every route, because the database behind it holds webhook
addresses and chat ids:

* Sign-in, when VINTED_SNIPER_WEB_AUTH_TOKEN is set. The cookie holds a value derived
  from the password, not the password.
* A same-origin check on every change (POST, PUT, DELETE). Browsers always say where a
  cross-site request came from, so a page elsewhere cannot add, delete or reroute your
  searches through your browser, password or not. This is the CSRF defence: SameSite
  cookies plus the Origin check, no tokens in forms to forget.
* A Host check while the dashboard listens on loopback, so a DNS-rebinding page cannot
  read it either. Behind a reverse proxy, VINTED_SNIPER_WEB_PUBLIC_URL names the
  address it is reached by.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from urllib.parse import quote, urlparse

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Repo
from vinted_sniper.log import get_logger
from vinted_sniper.vinted.client import VintedClient
from vinted_sniper.vinted.taxonomy import Taxonomy
from vinted_sniper.web import core
from vinted_sniper.web.preview import PreviewService
from vinted_sniper.web.routes import (
    alerts,
    api,
    auth,
    finds,
    searches,
    settings_page,
    stats,
    watchlist,
    welcome,
)

log = get_logger(__name__)

SESSION_COOKIE = core.SESSION_COOKIE

# Reachable without signing in: the sign-in page itself, the container health check,
# the files the sign-in page needs, and the RSS feed (which checks its own key).
_PUBLIC_PREFIXES = ("/static/", "/rss/")
_PUBLIC_PATHS = {"/login", "/healthz", "/manifest.webmanifest", "/favicon.ico"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _allowed_hosts(settings: Settings) -> set[str] | None:
    """Host names the dashboard answers to, or None when any will do."""
    if not settings.web_is_loopback:
        # Listening beyond this machine is a decision someone made; the password is
        # the guard there, and the names it is reached by are not ours to guess.
        return None
    hosts = {*_LOOPBACK_NAMES, settings.web_host}
    if settings.web_public_url:
        hosts.add((urlparse(settings.web_public_url).hostname or "").lower())
    return hosts


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _same_origin(request: Request, settings: Settings) -> bool:
    """Whether a state-changing request came from a page of this dashboard.

    Browsers send Origin on every cross-site POST, and Referer when Origin is absent.
    A request with neither did not come from a web page (curl, a script) and cannot be a
    forged browser request.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or source == "null":
        return source is None
    origin_host = (urlparse(source).netloc or "").lower()
    own = {request.headers.get("host", "").lower()}
    if settings.web_public_url:
        own.add(urlparse(settings.web_public_url).netloc.lower())
    return origin_host in own


def _wants_html(request: Request) -> bool:
    return not request.url.path.startswith("/api/") and "text/html" in request.headers.get(
        "accept", "text/html"
    )


def create_app(
    settings: Settings,
    repo: Repo,
    taxonomy: Taxonomy | None = None,
    *,
    client: VintedClient | None = None,
    watch_kinds: frozenset[str] = frozenset(),
    stop: asyncio.Event | None = None,
) -> FastAPI:
    """The dashboard. `client` enables live previews and the reachability check."""
    context = core.WebContext(
        settings=settings,
        repo=repo,
        taxonomy=taxonomy,
        client=client,
        watch_kinds=watch_kinds,
        stop=stop or asyncio.Event(),
        previews=PreviewService(client) if client is not None else None,
    )
    token = settings.web_auth_token
    allowed_hosts = _allowed_hosts(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        context.http = httpx.AsyncClient(timeout=20.0)
        try:
            yield
        finally:
            context.stop.set()
            await context.http.aclose()

    app = FastAPI(title="vinted-sniper", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.ctx = context

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if allowed_hosts is not None:
            host = _host_name(request.headers.get("host", ""))
            if host and host not in allowed_hosts:
                return Response(
                    f"This dashboard does not answer to {host!r}. If you reach it through a "
                    "reverse proxy or tunnel, set VINTED_SNIPER_WEB_PUBLIC_URL to that address.",
                    status_code=400,
                    media_type="text/plain",
                )
        if request.method not in _SAFE_METHODS and not _same_origin(request, settings):
            return JSONResponse(
                {"error": "This change did not come from the dashboard, so it was refused."},
                status_code=403,
            )
        public = path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)
        if not public and not core.signed_in(request, token):
            if request.method == "GET" and _wants_html(request):
                target = path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse(f"/login?next={quote(target, safe='/')}", status_code=303)
            return JSONResponse({"error": "Sign in first."}, status_code=401)
        response = await call_next(request)
        if path.startswith("/static/") and "v" in request.query_params:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    app.mount("/static", StaticFiles(directory=core.STATIC_DIR), name="static")
    for module in (auth, api, finds, searches, alerts, watchlist, stats, settings_page, welcome):
        app.include_router(module.router)

    @app.exception_handler(RequestValidationError)
    async def bad_form(request: Request, exc: RequestValidationError) -> Response:
        log.info("web.bad_request", path=request.url.path, errors=len(exc.errors()))
        return await _problem(
            request,
            400,
            "That didn't make sense to us",
            "Something in what was sent was missing or in the wrong shape. Go back and "
            "check the form; if it keeps happening, reload the page.",
        )

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> Response:
        detail = getattr(exc, "detail", None)
        message = detail if isinstance(detail, str) and detail != "Not Found" else None
        return await _problem(
            request, 404, "Nothing here", message or "That page or item doesn't exist any more."
        )

    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> Response:
        return await _problem(request, exc.status_code, "That didn't work", str(exc.detail))

    @app.exception_handler(sqlite3.OperationalError)
    async def busy(request: Request, exc: sqlite3.OperationalError) -> Response:
        log.warning("web.db_unavailable", path=request.url.path, error=str(exc))
        return await _problem(
            request,
            503,
            "Busy for a moment",
            "The database is being used by something else (a backup or the command line). "
            "Nothing was lost. Try again in a few seconds.",
            shell=False,
        )

    return app


async def _problem(
    request: Request, status: int, title: str, message: str, *, shell: bool = True
) -> Response:
    if not _wants_html(request):
        return JSONResponse({"error": message}, status_code=status)
    if not shell:
        return core.TEMPLATES.TemplateResponse(
            request,
            "error.html",
            {"title": title, "message": message, "app": None},
            status_code=status,
        )
    return await core.render(
        request, "error.html", {"title": title, "message": message}, status_code=status
    )


class _QuietServer(uvicorn.Server):
    """A server that leaves signal handling to the application.

    uvicorn would otherwise take over SIGTERM and SIGINT, and two sets of handlers means a
    shutdown that only half happens.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def serve(
    settings: Settings,
    repo: Repo,
    stop: asyncio.Event,
    taxonomy: Taxonomy | None = None,
    *,
    client: VintedClient | None = None,
    watch_kinds: frozenset[str] = frozenset(),
) -> None:
    """Run the web UI until the app shuts down."""
    config = uvicorn.Config(
        create_app(settings, repo, taxonomy, client=client, watch_kinds=watch_kinds, stop=stop),
        host=settings.web_host,
        port=settings.web_port,
        log_config=None,
        access_log=False,
        # Live streams end on the stop event; this bounds anything else still open.
        timeout_graceful_shutdown=3,
    )
    server = _QuietServer(config)
    serving = asyncio.create_task(server.serve())
    log.info("web.listening", host=settings.web_host, port=settings.web_port)
    if settings.web_is_exposed_without_a_password:
        log.warning(
            "web.no_password",
            host=settings.web_host,
            hint="the dashboard shows your webhook URLs; keep the published port on "
            "127.0.0.1 or set VINTED_SNIPER_WEB_AUTH_TOKEN",
        )
    await stop.wait()
    server.should_exit = True
    await serving
