"""Settings: preferences that save as you change them, and the honest status of the rest.

The password and phone access are changed here too (routes/access.py). What is left in
the environment (how long finds are kept, ports, logging) is listed read-only under
Advanced with where each value came from, so nothing that shapes the app is hidden.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from vinted_bot.engine import health, self_update
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.web import core, security, views
from vinted_bot.web.routes.searches import bookmarklet

router = APIRouter()

_COMMON_ZONES = (
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/London",
    "Europe/Dublin",
    "Europe/Lisbon",
    "Europe/Warsaw",
    "Europe/Prague",
    "Europe/Vienna",
    "Europe/Stockholm",
    "Europe/Helsinki",
    "Europe/Athens",
    "America/New_York",
    "UTC",
)


@router.get("/settings")
async def settings_page(request: Request) -> Response:
    context = core.ctx(request)
    repo = context.repo
    prefs = await repo.app_settings(default_timezone=context.settings.timezone)
    tz = ZoneInfo(prefs.timezone)
    snapshot = await health.snapshot(repo)
    now = int(time.time())
    queries = await repo.list_queries()
    sites: dict[str, dict[str, Any]] = {}
    for search in snapshot.searches:
        if search.paused:
            continue
        site = sites.setdefault(
            search.tld, {"tld": search.tld, "ok": True, "last": None, "same_results": 0}
        )
        if search.last_status == "http_403":
            site["ok"] = False
        # The watchdog's "same results lately": Vinted answers, one search just isn't moving.
        if search.checks_without_new_listings >= context.settings.watchdog_stale_cycles:
            site["same_results"] += 1
        if search.last_success_at:
            site["last"] = max(site["last"] or 0, search.last_success_at)
    totals = await repo.totals(tz)
    base = context.settings.web_public_url or str(request.base_url).rstrip("/")
    zones = list(_COMMON_ZONES)
    if prefs.timezone not in zones:
        zones.insert(0, prefs.timezone)
    blocked = await repo.list_blocked_sellers()
    last_update = await self_update.last_outcome(repo)
    access = await security.access(context.settings, repo)
    return await core.render(
        request,
        "settings.html",
        {
            "nav": "settings",
            "prefs": prefs,
            "zones": zones,
            "all_zones": sorted(available_timezones()),
            "local_time": datetime.now(tz).strftime("%H:%M"),
            "sites": [
                {
                    **site,
                    "name": f"vinted.{site['tld']}",
                    "last": views.ago(now - site["last"]) if site["last"] else "not yet",
                }
                for site in sites.values()
            ],
            "main_tld": queries[0].tld
            if queries
            else views.guess_tld(request.headers.get("accept-language")),
            "can_diagnose": context.client is not None,
            "finds": totals.listings_found,
            "blocked": [
                {
                    "id": b.seller_id,
                    "login": b.login or f"Seller {b.seller_id}",
                    "tld": f"vinted.{b.tld}" if b.tld else "",
                    "reason": b.reason,
                    "when": datetime.fromtimestamp(b.created_at, tz).strftime("%-d %b"),
                }
                for b in blocked
            ],
            "db_path": str(context.settings.db_path.resolve().parent),
            "retention": context.settings.item_retention_days,
            "access": access,
            "phone": core.phone_addresses(context.settings, access),
            "listen_error": context.listen_error,
            # A ready-made password to paste, so nobody has to invent one on the spot.
            "suggested_password": security.suggest_password(),
            "bookmarklet": bookmarklet(base),
            "self_hosting": core.SELF_HOSTING_URL,
            "install": context.updater.install,
            "update_last": last_update,
            "update_last_when": _when(last_update, tz),
        },
        snapshot=snapshot,
    )


def _when(outcome: self_update.Outcome | None, tz: ZoneInfo) -> str | None:
    if outcome is None or not outcome.at:
        return None
    moment = datetime.fromtimestamp(outcome.at, tz)
    # Not %-d: Windows' strftime refuses it.
    return f"{moment.day} {moment:%b, %H:%M}"


async def _set_auto_update(context: core.WebContext, enabled: bool) -> None:
    if enabled and not context.updater.install.can_update_automatically:
        raise InvalidInputError(
            "auto_update",
            "This copy can't update itself unattended. The Updates section says how to update it.",
        )
    await context.repo.set_auto_update(enabled)


@router.post("/settings")
async def save_setting(request: Request) -> Response:
    """Save one preference. The page sends each change as it happens."""
    context = core.ctx(request)
    repo = context.repo
    form = await request.form()
    key = str(form.get("key") or "")
    value = str(form.get("value") or "")
    try:
        match key:
            case "timezone":
                await repo.set_timezone(value)
            case "timezone_guess":
                # Sent once by a browser when the computer's own zone couldn't be read.
                if await core.needs_timezone(core.ctx(request)):
                    await repo.set_timezone(value)
            case "theme":
                await repo.set_theme(value)
            case "update_check":
                await repo.set_update_check(value == "1")
            case "auto_update":
                await _set_auto_update(context, value == "1")
            case "healthcheck_url":
                url = value.strip()
                if url and not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                await repo.set_healthcheck_url(url or None)
            case _:
                return JSONResponse({"ok": False, "error": "Unknown setting."}, status_code=400)
    except InvalidInputError as exc:
        return JSONResponse({"ok": False, "field": key, "error": exc.message}, status_code=400)
    return JSONResponse({"ok": True})


@router.post("/settings/blocked/{seller_id}/unblock")
async def unblock(request: Request, seller_id: int) -> Response:
    await core.ctx(request).repo.unblock_seller(seller_id)
    return core.redirect("/settings#blocked", "Unblocked. Their listings can alert you again.")
