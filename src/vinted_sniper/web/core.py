"""What every dashboard page shares: the running app's parts, templates, and the shell.

`WebContext` holds the things the routes need (settings, the repository, the Vinted
client for previews) and lives on `app.state`. It is a plain record, not a container:
the app factory fills it once and nothing registers itself into it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import socket
import time
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from vinted_sniper import __version__
from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Repo
from vinted_sniper.engine import health, updates
from vinted_sniper.vinted.client import VintedClient
from vinted_sniper.vinted.taxonomy import Taxonomy
from vinted_sniper.web import views
from vinted_sniper.web.preview import PreviewService
from vinted_sniper.web.security import LoginThrottle

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"
SESSION_COOKIE = "vinted_sniper_session"
FLASH_COOKIE = "vs_toast"
RELEASES_URL = "https://github.com/jasp-nerd/vinted-sniper/releases/latest"
TROUBLESHOOTING_URL = "https://github.com/jasp-nerd/vinted-sniper/blob/main/docs/troubleshooting.md"
SELF_HOSTING_URL = "https://github.com/jasp-nerd/vinted-sniper/blob/main/docs/self-hosting.md"


@dataclass
class WebContext:
    settings: Settings
    repo: Repo
    taxonomy: Taxonomy | None = None
    client: VintedClient | None = None
    # Which watch kinds this build can run (Watcher.available_kinds).
    watch_kinds: frozenset[str] = frozenset()
    # Set when the app shuts down, so open live streams end instead of holding it up.
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    previews: PreviewService | None = None
    # For test sends and the Telegram bot's name; opened with the app, closed with it.
    http: httpx.AsyncClient | None = None
    bot_username: str | None = None
    bot_checked: bool = False
    login_throttle: LoginThrottle = field(default_factory=LoginThrottle)


def ctx(request: Request) -> WebContext:
    context: WebContext = request.app.state.ctx
    return context


# --- Templates ---------------------------------------------------------------------

ROUTES = {
    "home": "/",
    "searches": "/searches",
    "search_new": "/searches/new",
    "search_edit": "/searches/{id}/edit",
    "search_detail": "/searches/{id}",
    "watchlist": "/watchlist",
    "alerts": "/alerts",
    "stats": "/stats",
    "settings": "/settings",
    "login": "/login",
    "welcome_1": "/welcome",
    "welcome_2": "/welcome/country",
    "welcome_3": "/welcome/search",
    "welcome_4": "/welcome/alerts",
    "welcome_5": "/welcome/test",
    "welcome_6": "/welcome/ready",
}


def url(name: str, **params: Any) -> str:
    return ROUTES[name].format(**params)


@cache
def _digest(path: str) -> str:
    return hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]


def static(path: str) -> str:
    """A static file's address with its content hash, so a new release is never stale."""
    return f"/static/{path}?v={_digest(path)}"


TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))
TEMPLATES.env.trim_blocks = True
TEMPLATES.env.lstrip_blocks = True
TEMPLATES.env.globals.update(url=url, static=static, money=views.money)
TEMPLATES.env.filters["tojson_attr"] = json.dumps


async def timezone(context: WebContext) -> ZoneInfo:
    prefs = await context.repo.app_settings(default_timezone=context.settings.timezone)
    return ZoneInfo(prefs.timezone)


async def needs_timezone(context: WebContext) -> bool:
    """Whether to ask the browser for its time zone: none was set and none could be read.

    Only then, so a zone someone picked, or set with TZ, is never replaced by a guess.
    """
    settings = context.settings
    if settings.timezone != "UTC" or "timezone" in settings.model_fields_set:
        return False
    return await context.repo.get_state_value("timezone") is None


async def shell(context: WebContext, snapshot: health.Snapshot | None = None) -> dict[str, Any]:
    """What the frame around every page shows: counts, banners, the next-check ring."""
    snapshot = snapshot or await health.snapshot(context.repo)
    prefs = await context.repo.app_settings(default_timezone=context.settings.timezone)
    queries = {query.id: query for query in await context.repo.list_queries()}
    states = {state.query_id: state for state in await context.repo.all_states()}
    now = int(time.time())
    active = [search for search in snapshot.searches if not search.paused]

    waits = []
    for search in active:
        state, query = states.get(search.query_id), queries.get(search.query_id)
        if state and query and state.last_polled_at:
            waits.append(max(state.last_polled_at + query.poll_interval_s - now, 0))
    next_check = min(waits) if waits else None
    interval = min((queries[s.query_id].poll_interval_s for s in active), default=60)

    refused = [search for search in active if search.last_status == "http_403"]
    blocked = None
    if refused:
        sites = sorted({f"vinted.{search.tld}" for search in refused})
        blocked = {"site": ", ".join(sites), "searches": len(refused)}

    update = None
    if prefs.update_check and updates.is_newer(prefs.latest_version):
        update = {"version": prefs.latest_version, "url": RELEASES_URL}

    return {
        "version": __version__,
        "searches_active": len(active),
        "searches_total": len(snapshot.searches),
        "next_check_s": next_check,
        "tick": round(1 - (next_check or 0) / interval, 3) if next_check is not None else 1,
        "alive": snapshot.alive,
        "blocked": blocked,
        "new_version": update,
        "theme": prefs.theme,
        "auth": context.settings.web_auth_token is not None,
        "exposed": context.settings.web_is_exposed_without_a_password,
        "new_count": 0,
        "troubleshooting": TROUBLESHOOTING_URL,
        "guess_timezone": await needs_timezone(context),
    }


async def render(
    request: Request,
    template: str,
    page: dict[str, Any],
    *,
    status_code: int = 200,
    snapshot: health.Snapshot | None = None,
) -> HTMLResponse:
    context = ctx(request)
    # A confirmation from the change that redirected here, shown once.
    raw_flash = request.cookies.get(FLASH_COOKIE)
    flash = unquote(raw_flash) if raw_flash else None
    response = TEMPLATES.TemplateResponse(
        request,
        template,
        {"app": await shell(context, snapshot), "flash": flash, **page},
        status_code=status_code,
    )
    if raw_flash:
        response.delete_cookie(FLASH_COOKIE)
    return response


def redirect(target: str, flash: str | None = None) -> RedirectResponse:
    """Redirect after a change, carrying a confirmation the next page shows once."""
    response = RedirectResponse(target, status_code=303)
    if flash:
        # Cookie values are Latin-1 on the wire, and names carry euro signs and emoji.
        response.set_cookie(
            FLASH_COOKIE, quote(flash, safe=""), max_age=30, samesite="lax", httponly=True
        )
    return response


def phone_address(settings: Settings) -> str | None:
    """The address a phone on the same Wi-Fi can open the dashboard at, if there is one.

    Loopback means only this computer can, so there is nothing to offer. Inside a
    container the machine's own address is not visible, so only a configured public URL
    is trusted there.
    """
    if settings.web_public_url:
        return settings.web_public_url.rstrip("/")
    if settings.web_is_loopback or in_container():
        return None
    # Connecting a UDP socket sends nothing; it only asks the OS which interface it
    # would use, which is the address the local network knows this machine by.
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))
        return f"http://{probe.getsockname()[0]}:{settings.web_port}"
    return None


def in_container() -> bool:
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
