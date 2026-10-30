"""Watchlist: listings watched for a price drop or a sale, and sellers whose uploads you follow."""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from vinted_sniper.engine.validation import InvalidInputError
from vinted_sniper.vinted import urls
from vinted_sniper.web import core, views

router = APIRouter()

_ITEM = re.compile(r"/items/(\d+)")
_MEMBER = re.compile(r"/member/(\d+)(?:-([^/?#]+))?")

_STATUS_WORDS = {
    "available": ("ok", "Available"),
    "reserved": ("reserved", "Reserved"),
    "sold": ("sold", "Sold"),
    "gone": ("sold", "Removed by the seller"),
}


def parse_watch_link(text: str) -> tuple[Literal["item", "seller"], str, int, str]:
    """A pasted listing or member link as (kind, site, id, label). Raises InvalidInputError."""
    raw = text.strip()
    if not raw:
        raise InvalidInputError("url", "Paste a link to a Vinted listing or a member's page.")
    link = raw if re.match(r"(?i)^https?://", raw) else f"https://{raw}"
    try:
        tld = urls.extract_tld(link)
    except urls.InvalidSearchURLError as exc:
        raise InvalidInputError("url", "That isn't a Vinted link.") from exc
    if item := _ITEM.search(link):
        return "item", tld, int(item.group(1)), f"Listing {item.group(1)}"
    if member := _MEMBER.search(link):
        return "seller", tld, int(member.group(1)), member.group(2) or f"Seller {member.group(1)}"
    raise InvalidInputError(
        "url",
        "That's a Vinted link, but not to a listing or a member. Open the listing (or the "
        "seller's page) and copy its address.",
    )


@router.get("/watchlist")
async def watchlist(request: Request) -> Response:
    return await _page(request)


async def _page(request: Request, *, error: str = "", link: str = "") -> Response:
    context = core.ctx(request)
    now = int(time.time())
    items: list[dict[str, Any]] = []
    sellers: list[dict[str, Any]] = []
    for watch in await context.repo.list_watches():
        checked = views.ago(now - watch.last_checked_at) if watch.last_checked_at else "not yet"
        if watch.kind == "item":
            stored = await context.repo.feed_item(watch.target_id)
            status, label = _STATUS_WORDS.get(watch.last_status or "", ("ok", "Waiting for a first look"))
            items.append(
                {
                    "id": watch.id,
                    "title": stored.item.title if stored else watch.label,
                    "photo": stored.item.photo_url if stored else None,
                    "tld": f"vinted.{watch.tld}",
                    "now": views.money(watch.last_price, watch.currency) or "Price not read yet",
                    "status": status,
                    "status_label": label,
                    "checked": checked,
                    "error": watch.last_error,
                    "url": urls.item_url(watch.tld, watch.target_id),
                    "active": watch.active,
                }
            )
        else:
            sellers.append(
                {
                    "id": watch.id,
                    "login": watch.label,
                    "initial": (watch.label[:1] or "?").upper(),
                    "tld": f"vinted.{watch.tld}",
                    "checked": checked,
                    "error": watch.last_error,
                    "url": urls.member_url(watch.tld, watch.target_id),
                    "on": watch.active,
                }
            )
    return await core.render(
        request,
        "watchlist.html",
        {
            "nav": "watchlist",
            "items": items,
            "sellers": sellers,
            "kinds": context.watch_kinds,
            "error": error,
            "link": link,
        },
    )


@router.post("/watchlist")
async def add(request: Request) -> Response:
    context = core.ctx(request)
    form = await request.form()
    text = str(form.get("url") or "")
    try:
        kind, tld, target_id, label = parse_watch_link(text)
        if context.watch_kinds and kind not in context.watch_kinds:
            raise InvalidInputError("url", "This copy of vinted-sniper can't run that kind of watch.")
        await context.repo.add_watch(kind=kind, tld=tld, target_id=target_id, label=label)
    except InvalidInputError as exc:
        page = await _page(request, error=exc.message, link=text)
        page.status_code = 400
        return page
    noun = "listing" if kind == "item" else "seller"
    return core.redirect(core.url("watchlist"), f"Watching this {noun} now. First look within a minute.")


async def _watch_or_404(request: Request, watch_id: int) -> Any:
    watch = await core.ctx(request).repo.get_watch(watch_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="No such watch.")
    return watch


@router.post("/watchlist/{watch_id}/toggle")
async def toggle(request: Request, watch_id: int) -> Response:
    watch = await _watch_or_404(request, watch_id)
    await core.ctx(request).repo.update_watch(watch_id, label=watch.label, active=not watch.active)
    return core.redirect(core.url("watchlist"), "Alerts on." if not watch.active else "Alerts off.")


@router.post("/watchlist/{watch_id}/delete")
async def delete(request: Request, watch_id: int) -> Response:
    watch = await _watch_or_404(request, watch_id)
    await core.ctx(request).repo.delete_watch(watch_id)
    return core.redirect(core.url("watchlist"), f"Stopped watching {watch.label}.")
