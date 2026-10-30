"""The dashboard's web server: the app factory, its guards, and running it.

On by default, bound to localhost unless you say otherwise. It exists because editing a
config file is where most people give up: pasting a Vinted link into a box is not.

Four guards sit in front of every route, because the dashboard can add, remove and
reroute alerts. The rules themselves live in web/security.py:

* A device check while the server listens beyond this computer: only this computer and
  private networks (home, office, Tailscale) are served, unless the operator put the
  dashboard on the internet on purpose (VINTED_BOT_WEB_ALLOW_PUBLIC, or a public
  VINTED_BOT_WEB_PUBLIC_URL). Phone access on a network that hands out public addresses
  must not mean the sign-in page is on the internet.
* A Host check, however the server is bound, so a DNS-rebinding page cannot read the
  dashboard or post to it. The static files (styles, icons) are exempt: they are public
  anyway, and the page explaining a refused name needs them to look like the rest.
  Behind a reverse proxy or under a name on your network, VINTED_BOT_WEB_PUBLIC_URL or
  VINTED_BOT_WEB_ALLOWED_HOSTS names the address.
* A same-origin check on every change (POST, PUT, DELETE). Browsers always say where a
  cross-site request came from, so a page elsewhere cannot add, delete or reroute your
  searches through your browser, password or not. This is the CSRF defence: SameSite
  cookies plus the Origin check, no tokens in forms to forget.
* Sign-in, when there is a password (set in Settings, or VINTED_BOT_WEB_AUTH_TOKEN). The
  cookie holds a random session token that signing out, or changing the password, revokes.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import socket
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from urllib.parse import quote

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from vinted_bot import managed
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine.self_update import Updater
from vinted_bot.log import get_logger
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.taxonomy import Taxonomy
from vinted_bot.web import core, security
from vinted_bot.web.preview import PreviewService
from vinted_bot.web.routes import (
    access,
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
    telegram_token_changed: asyncio.Event | None = None,
) -> FastAPI:
    """The dashboard. `client` enables live previews and the reachability check.

    `http` is used for test sends and the Telegram lookup; one is opened with the app
    when not given. `updater` is the running app's; a dashboard on its own gets one that
    stops only itself. `telegram_token_changed` is set when the bot's token changes, so
    the running app can restart the bot on it.
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
        telegram_token_changed=telegram_token_changed or asyncio.Event(),
    )
    allowed_hosts = security.allowed_hosts(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await security.sync_password(repo, settings.web_auth_token)
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
        client = request.client.host if request.client else ""
        if not security.client_allowed(settings, await _beyond_loopback(context), client):
            log.info("web.refused_client", client=client, path=path)
            return _refused_client(request, client)
        host = security.host_name(request.headers.get("host", ""))
        if (
            host
            and not path.startswith("/static/")
            and not security.host_allowed(host, allowed_hosts)
        ):
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
            and await security.password_required(settings, repo)
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
        access,
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


async def _beyond_loopback(context: core.WebContext) -> bool:
    """Whether other machines can connect: the server listens, or is about to listen,
    somewhere other than loopback.

    Both are asked so that the moment between turning phone access off and the server
    moving back is guarded too.
    """
    listening = context.listening_on
    if listening is not None and listening not in security.LOOPBACK_HOSTS:
        return True
    wanted = await managed.web_host(context.settings, context.repo)
    return wanted not in security.LOOPBACK_HOSTS


_REFUSED_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not on this network</title>
<body style="font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 1rem">
<h1 style="font-size:1.4rem">Not on this network</h1>
<p>{message}</p></body></html>"""


def _refused_client(request: Request, client: str) -> Response:
    """The 403 for a visitor from outside this computer's networks.

    Plain on purpose: nothing about the dashboard, its styles included, is served to the
    internet, and the page reads no database.
    """
    message = (
        f"This dashboard only opens for this computer and devices on its own home or office "
        f"network (or Tailscale). Your address, {client or 'unknown'}, is not one of those. "
        "If you run this dashboard and meant to put it on the internet, set "
        "VINTED_BOT_WEB_PUBLIC_URL to its public address, or VINTED_BOT_WEB_ALLOW_PUBLIC=true, "
        "and start it again."
    )
    if not _wants_html(request):
        return JSONResponse({"error": message}, status_code=403)
    return HTMLResponse(_REFUSED_PAGE.format(message=html.escape(message)), status_code=403)


def _unknown_host(request: Request, host: str) -> Response:
    """The 400 for a host name the dashboard was not told about, saying how to allow it.

    No page shell: the shell reads the database, and this request is not trusted to.
    """
    message = (
        f"This dashboard does not answer to the name {host!r}, which protects it from web "
        "pages that point their own name at your computer (DNS rebinding). If that is "
        "really how you reach it, add the name to VINTED_BOT_WEB_ALLOWED_HOSTS "
        "(comma-separated), or set VINTED_BOT_WEB_PUBLIC_URL to the full address, then "
        "start vinted-bot again. In Docker that means running docker compose up -d (a plain "
        "restart keeps the old settings), or saving the app's settings in a NAS app store. "
        "Opening it by IP address, such as http://192.168.1.20:8000, always works."
    )
    if not _wants_html(request):
        return JSONResponse({"error": message}, status_code=400)
    # No link back: every page on this name answers the same, so it would only loop.
    return core.TEMPLATES.TemplateResponse(
        request,
        "error.html",
        {"title": "Unknown address", "message": message, "app": None, "no_way_back": True},
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


# What uvicorn exits with when it cannot listen; kept so a taken port still ends the app.
_CANNOT_LISTEN_EXIT_CODE = 3


def _listen(host: str, port: int) -> socket.socket:
    """A listening socket on host:port. Raises OSError when the address is taken.

    Made here rather than by uvicorn so that a failure is an exception this module can
    handle: uvicorn exits the whole process when it cannot bind.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    return socket.create_server((host, port), family=family)


async def serve(
    settings: Settings,
    repo: Repo,
    stop: asyncio.Event,
    taxonomy: Taxonomy | None = None,
    *,
    client: VintedClient | None = None,
    watch_kinds: frozenset[str] = frozenset(),
    updater: Updater | None = None,
    telegram_token_changed: asyncio.Event | None = None,
) -> None:
    """Run the web UI until the app shuts down, moving it when phone access changes.

    Turning phone access on or off sets `context.rebind`: the server stops listening on
    the old address and starts on the new one, inside this process. The app, its open
    database and its running searches carry on untouched, and nothing needs to be there
    to start it again, which a process restart would.
    """
    app = create_app(
        settings,
        repo,
        taxonomy,
        client=client,
        watch_kinds=watch_kinds,
        stop=stop,
        updater=updater,
        telegram_token_changed=telegram_token_changed,
    )
    context: core.WebContext = app.state.ctx
    # The app's startup and shutdown run once around every server below, not per server.
    async with app.router.lifespan_context(app):
        host = await managed.web_host(settings, repo)
        try:
            sock = _listen(host, settings.web_port)
        except OSError as exc:
            log.error("web.cannot_listen", host=host, port=settings.web_port, error=str(exc))
            raise SystemExit(_CANNOT_LISTEN_EXIT_CODE) from exc
        while await _serve_until_moved(app, sock, host):
            context.rebind.clear()
            wanted = await managed.web_host(settings, repo)
            try:
                sock = _listen(wanted, settings.web_port)
            except OSError as exc:
                # The old address was just let go of, so it is free to take back.
                log.error("web.cannot_move", host=wanted, error=str(exc))
                context.listen_error = f"Couldn't listen on {wanted}: {exc.strerror or exc}"
                sock = _listen(host, settings.web_port)
            else:
                context.listen_error = None
                host = wanted


async def _serve_until_moved(app: FastAPI, sock: socket.socket, host: str) -> bool:
    """Serve on `sock` until the app stops or phone access changes. True for the latter."""
    context: core.WebContext = app.state.ctx
    settings = context.settings
    config = uvicorn.Config(
        app,
        host=host,
        port=settings.web_port,
        lifespan="off",
        log_config=None,
        access_log=False,
        # Live streams end on the stop event; this bounds anything else still open.
        timeout_graceful_shutdown=3,
    )
    server = _QuietServer(config)
    # What the OS says the socket is bound to, not what was asked for.
    context.listening_on = str(sock.getsockname()[0])
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    stopping = asyncio.create_task(context.stop.wait())
    moving = asyncio.create_task(context.rebind.wait())
    try:
        log.info("web.listening", host=context.listening_on, port=settings.web_port)
        if (await security.access(settings, context.repo)).exposed_without_password:
            log.warning(
                "web.no_password",
                host=host,
                hint="anyone who can open the dashboard can change your alerts; keep the "
                "published port on 127.0.0.1 or set a password in Settings",
            )
        await asyncio.wait({stopping, moving, serving}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in (stopping, moving):
            waiter.cancel()
        await asyncio.gather(stopping, moving, return_exceptions=True)
        server.should_exit = True
        await serving
        context.listening_on = None
    return context.rebind.is_set() and not context.stop.is_set()
