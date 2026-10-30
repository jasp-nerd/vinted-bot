"""The dashboard's web server: the app factory, its guards, and running it.

On by default, bound to localhost unless you say otherwise. It exists because editing a
config file is where most people give up: pasting a Vinted link into a box is not.

Three guards sit in front of every route, because the dashboard can add, remove and
reroute alerts. The rules themselves live in web/security.py:

* A Host check, however the server is bound, so a DNS-rebinding page cannot read the
  dashboard or post to it. Behind a reverse proxy or under a name on your network,
  VINTED_BOT_WEB_PUBLIC_URL or VINTED_BOT_WEB_ALLOWED_HOSTS names the address.
* A same-origin check on every change (POST, PUT, DELETE). Browsers always say where a
  cross-site request came from, so a page elsewhere cannot add, delete or reroute your
  searches through your browser, password or not. This is the CSRF defence: SameSite
  cookies plus the Origin check, no tokens in forms to forget.
* Sign-in, when VINTED_BOT_WEB_AUTH_TOKEN is set. The cookie holds a random session
  token that signing out, or changing the password, revokes.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from urllib.parse import quote

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine.self_update import Updater
from vinted_bot.log import get_logger
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.taxonomy import Taxonomy
from vinted_bot.web import core, security
from vinted_bot.web.preview import PreviewService
from vinted_bot.web.routes import (
    alerts,
    api,
    auth,
    finds,
    searches,
    settings_page,
    stats,
    updating,
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


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return not request.url.path.startswith("/api/") and "application/json" not in accept


def create_app(
    settings: Settings,
    repo: Repo,
    taxonomy: Taxonomy | None = None,
    *,
    client: VintedClient | None = None,
    watch_kinds: frozenset[str] = frozenset(),
    stop: asyncio.Event | None = None,
    http: httpx.AsyncClient | None = None,
    updater: Updater | None = None,
) -> FastAPI:
    """The dashboard. `client` enables live previews and the reachability check.

    `http` is used for test sends and the Telegram lookup; one is opened with the app
    when not given. `updater` is the running app's; a dashboard on its own gets one that
    stops only itself.
    """
    stop = stop or asyncio.Event()
    context = core.WebContext(
        settings=settings,
        repo=repo,
        updater=updater or Updater(settings, repo, stop),
        taxonomy=taxonomy,
        client=client,
        watch_kinds=watch_kinds,
        stop=stop,
        previews=PreviewService(client) if client is not None else None,
    )
    token = settings.web_auth_token
    allowed_hosts = security.allowed_hosts(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await security.sync_password(repo, token)
        context.http = http or httpx.AsyncClient(timeout=20.0)
        try:
            yield
        finally:
            context.stop.set()
            if http is None:
                await context.http.aclose()

    app = FastAPI(title="vinted-bot", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.ctx = context

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        host = security.host_name(request.headers.get("host", ""))
        if host and not security.host_allowed(host, allowed_hosts):
            return _unknown_host(request, host)
        if request.method not in _SAFE_METHODS and not security.same_origin(
            request, settings, allowed_hosts
        ):
            return JSONResponse(
                {"error": "This change did not come from the dashboard, so it was refused."},
                status_code=403,
            )
        public = path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)
        if (
            not public
            and token is not None
            and not await security.session_valid(repo, request.cookies.get(SESSION_COOKIE))
        ):
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
    for module in (
        auth,
        api,
        finds,
        searches,
        alerts,
        watchlist,
        stats,
        settings_page,
        updating,
        welcome,
    ):
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

    @app.exception_handler(Exception)
    async def crashed(request: Request, exc: Exception) -> Response:
        # Starlette logs the traceback and re-raises after this; the handler only makes
        # sure the person sees a page that says what to do instead of plain text.
        log.error("web.unhandled", path=request.url.path, error=type(exc).__name__)
        return await _problem(
            request,
            500,
            "Something went wrong on our side",
            "What you did may have worked anyway. Reload the page to check.",
            shell=False,
        )

    return app


def _unknown_host(request: Request, host: str) -> Response:
    """The 400 for a host name the dashboard was not told about, saying how to allow it.

    No page shell: the shell reads the database, and this request is not trusted to.
    """
    message = (
        f"This dashboard does not answer to the name {host!r}, which protects it from web "
        "pages that point their own name at your computer (DNS rebinding). If that is "
        "really how you reach it, add the name to VINTED_BOT_WEB_ALLOWED_HOSTS "
        "(comma-separated), or set VINTED_BOT_WEB_PUBLIC_URL to the full address, and "
        "restart. Opening it by IP address, such as http://192.168.1.20:8000, always works."
    )
    if not _wants_html(request):
        return JSONResponse({"error": message}, status_code=400)
    return core.TEMPLATES.TemplateResponse(
        request,
        "error.html",
        {"title": "Unknown address", "message": message, "app": None},
        status_code=400,
    )


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
    updater: Updater | None = None,
) -> None:
    """Run the web UI until the app shuts down."""
    app = create_app(
        settings,
        repo,
        taxonomy,
        client=client,
        watch_kinds=watch_kinds,
        stop=stop,
        updater=updater,
    )
    config = uvicorn.Config(
        app,
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
            hint="anyone who can open the dashboard can change your alerts; keep the "
            "published port on 127.0.0.1 or set VINTED_BOT_WEB_AUTH_TOKEN",
        )
    await stop.wait()
    server.should_exit = True
    await serving
