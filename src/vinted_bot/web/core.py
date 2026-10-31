"""What every dashboard page shares: the running app's parts, templates, and the shell.

`WebContext` holds the things the routes need (settings, the repository, the Vinted
client for previews) and lives on `app.state`. It is a plain record, not a container:
the app factory fills it once and nothing registers itself into it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
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

from vinted_bot import __version__
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine import health, updates, wakeups
from vinted_bot.engine.self_update import InstallKind, Phase, Updater
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.taxonomy import Taxonomy
from vinted_bot.web import security, support, views
from vinted_bot.web.preview import PreviewService
from vinted_bot.web.security import LoginThrottle

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"
SESSION_COOKIE = "vinted_bot_session"
FLASH_COOKIE = "vs_toast"
TROUBLESHOOTING_URL = "https://github.com/jasp-nerd/vinted-bot/blob/main/docs/troubleshooting.md"
SELF_HOSTING_URL = "https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md"


@dataclass
class WebContext:
    settings: Settings
    repo: Repo
    updater: Updater
    taxonomy: Taxonomy | None = None
    client: VintedClient | None = None
    # Which watch kinds this build can run (Watcher.available_kinds).
    watch_kinds: frozenset[str] = frozenset()
    # Set when the app shuts down, so open live streams end instead of holding it up.
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    previews: PreviewService | None = None
    # For test sends and the Telegram bot's name; opened with the app, closed with it.
    http: httpx.AsyncClient | None = None
    # Each token's bot @name, as Telegram told us, or None when it couldn't say.
    bot_names: dict[str, str | None] = field(default_factory=dict)
    # Set when the bot's token changes, for the running app to restart the bot on it.
    telegram_token_changed: asyncio.Event = field(default_factory=asyncio.Event)
    login_throttle: LoginThrottle = field(default_factory=LoginThrottle)
    # Set when phone access changes, for the server to listen on the new address.
    rebind: asyncio.Event = field(default_factory=asyncio.Event)
    # Where the server listens right now (None while it moves), and why the last move
    # failed, if it did.
    listening_on: str | None = None
    listen_error: str | None = None


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
TEMPLATES.env.globals.update(url=url, static=static, money=views.money, support_links=support.links)
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

    # Installing updates by itself means checking for them too, whatever the other switch says.
    checking = prefs.update_check or prefs.auto_update
    update = update_offer(context.updater, prefs.latest_version if checking else None)
    access = await security.access(context.settings, context.repo)

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
        "auth": access.password,
        "exposed": context.settings.web_enabled and access.exposed_without_password,
        "new_count": 0,
        "troubleshooting": TROUBLESHOOTING_URL,
        "guess_timezone": await needs_timezone(context),
    }


# A container may have come from a NAS app store rather than a compose file, and the app
# cannot tell which, so the update hint names both.
_DOCKER_HINT = (
    "Installed from a NAS app store? Update the app there. Started with docker compose? "
    "In the folder with its docker-compose.yml, run:"
)


def update_offer(updater: Updater, latest: str | None) -> dict[str, Any] | None:
    """What the update banner and the settings page offer, or None for nothing to say.

    An update under way is shown even with the check switched off, since someone started it.
    """
    busy = updater.phase is not Phase.IDLE
    if not busy and not updates.is_newer(latest):
        return None
    version = updater.target if busy and updater.target else latest
    assert version is not None  # is_newer(None) is False
    install = updater.install
    return {
        "version": version,
        "notes": updates.release_notes_url(version),
        "can_upgrade": install.can_upgrade,
        "restarts": install.restarts_itself,
        "command": install.manual_command,
        "hint": _DOCKER_HINT if install.kind is InstallKind.DOCKER else install.manual_hint,
        "status": updater.status(),
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


# Where the probes below pretend to send: "the internet" (the default route) for the home
# network, and Tailscale's own resolver for its network when it runs.
_PROBES = (wakeups.INTERNET, "100.100.100.100")


def lan_addresses() -> list[str]:
    """This computer's private IPv4 addresses a phone can open the dashboard at.

    Asking the OS which interface it would send through (wakeups.local_address, which
    sends nothing) gives the address that matters: once towards the internet, for the
    home network, and once towards Tailscale's resolver, which only routes somewhere of
    its own while Tailscale runs. Only when neither helps, as on a computer with no route
    out, are the addresses its own name resolves to tried: that list also holds virtual
    machines' and containers' networks, which a phone can't reach.

    Only private addresses (security.is_local_address) are offered. Some networks
    (universities, offices) give every computer a public one, and offering that would
    send people to an address the dashboard refuses anyway, as it should: it would be
    on the internet.
    """
    found = [address for target in _PROBES if (address := wakeups.local_address(target))]
    if not _usable(found):
        with contextlib.suppress(OSError):
            for *_, sockaddr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                found.append(str(sockaddr[0]))
    return _usable(found)


def _usable(addresses: list[str]) -> list[str]:
    usable: list[str] = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        unusable = ip.is_loopback or ip.is_link_local or ip.is_unspecified
        if not unusable and security.is_local_address(address) and address not in usable:
            usable.append(address)
    return usable


def phone_addresses(settings: Settings, access: security.Access) -> list[str]:
    """The addresses a phone on the same network can open the dashboard at.

    Only this computer can while it listens on loopback, so there is nothing to offer.
    Inside a container the machine's own address is not visible, so only a configured
    public URL is trusted there.
    """
    if settings.web_public_url:
        return [settings.web_public_url.rstrip("/")]
    if access.loopback or access.container:
        return []
    return [f"http://{address}:{settings.web_port}" for address in lan_addresses()]
