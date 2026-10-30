"""The Finds page, the actions on a listing, and the live stream of new finds.

The live stream is Server-Sent Events: the page opens `/api/live` and the server sends
each newly found listing as a ready-made card. The database is the message bus. Every
listing gets a `seq` when it is stored, and the stream simply asks for anything after
the last one it sent, once a second or so. No queue to lose things in, and a reconnect
picks up exactly where it left off through Last-Event-ID.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from vinted_bot.db.repo import FeedItem, MarkFilter
from vinted_bot.engine import health, validation
from vinted_bot.web import core, data, support, views

router = APIRouter()

PAGE_SIZE = 60
# Sorting by deal or price looks at this many recent finds rather than paging.
SORT_WINDOW = 240

# How often the live stream looks for new finds, and how long one connection lasts before
# the browser is asked to reconnect (EventSource does that by itself, losing nothing).
LIVE_POLL_S = 1.5
LIVE_MAX_S = 300.0
LIVE_KEEPALIVE_S = 20.0


def _card(it: dict[str, Any]) -> str:
    return core.TEMPLATES.get_template("partials/card.html").render(it=it)


async def _feed(
    request: Request, *, before: int | None = None
) -> tuple[list[dict[str, Any]], int | None]:
    """The finds the page's filters ask for, and the cursor for "Show older"."""
    context = core.ctx(request)
    params = request.query_params
    tz = await core.timezone(context)
    show = params.get("show", "all")
    marks: dict[str, MarkFilter] = {"saved": "saved", "hidden": "hidden"}
    mark = marks.get(show, "visible")
    since = None
    if show == "today":
        since = int(datetime.now(tz).replace(hour=0, minute=0, second=0).timestamp())
    search = params.get("search", "")
    sort = params.get("sort", "newest")
    windowed = sort != "newest" or show == "deals"
    low, high = params.get("min", ""), params.get("max", "")
    # A filter with a mistake in it is shown with its message and not applied.
    prices_ok = not price_errors(low, high)
    entries: list[FeedItem] = await context.repo.items_feed(
        query_id=int(search) if search.isdigit() else None,
        mark=mark,
        text=params.get("q") or None,
        min_price=_price(low) if prices_ok else None,
        max_price=_price(high) if prices_ok else None,
        before_seq=before,
        since=since,
        limit=SORT_WINDOW if windowed else PAGE_SIZE,
    )
    now = int(time.time())
    # Blocking a seller hides what they already listed too, the way Vinted's own block
    # does. Filtered here rather than in SQL: the list is short and the feed page is too.
    blocked = await context.repo.blocked_seller_ids()
    cards = [
        views.item_view(entry, now) for entry in entries if entry.item.seller_id not in blocked
    ]
    if show == "deals":
        cards = [card for card in cards if card["deal_pct"]]
    if sort == "deal":
        cards.sort(key=lambda card: -(card["deal_pct"] or 0))
    elif sort == "cheap":
        cards.sort(key=lambda card: card["total_num"] if card["total_num"] is not None else 1e12)
    more = None if windowed or len(entries) < PAGE_SIZE else entries[-1].seq
    return cards, more


def _price(raw: str | None) -> Decimal | None:
    try:
        return validation.parse_price(raw)
    except validation.InvalidInputError:
        return None


def price_errors(low: str, high: str) -> dict[str, str]:
    """What is wrong with the Price filter, in the editor's words, so nothing is ignored
    silently while the chip still looks switched on."""
    errors: dict[str, str] = {}
    for key, raw in (("min", low), ("max", high)):
        if raw.strip() and _price(raw) is None:
            errors[key] = "Type a price like 35 or 12,50."
    low_value, high_value = _price(low), _price(high)
    if low_value is not None and high_value is not None and low_value > high_value:
        errors["min"] = "The lowest price is higher than the highest. Swap them?"
    return errors


@router.get("/")
async def home(request: Request) -> Response:
    context = core.ctx(request)
    repo = context.repo
    prefs = await repo.app_settings(default_timezone=context.settings.timezone)
    queries = await repo.list_queries()
    if not queries and not prefs.onboarded:
        return RedirectResponse(core.url("welcome_1"), status_code=303)
    snapshot = await health.snapshot(repo)
    tz = await core.timezone(context)
    rows = await data.searches(context, snapshot, tz)
    cards, more = await _feed(request)
    totals = await repo.totals(tz)
    states = [s for s in snapshot.searches if s.last_success_at]
    last_check = max((s.last_success_at or 0 for s in states), default=None)
    params = request.query_params
    low, high = params.get("min", ""), params.get("max", "")
    price_problems = price_errors(low, high)
    price_on = (_price(low) is not None or _price(high) is not None) and not price_problems
    filtered = (
        any(params.get(key) for key in ("q", "search"))
        or price_on
        or params.get("show", "all") not in ("all", "")
    )
    waiting = [row for row in rows if row["status"] in ("stuck", "blocked", "stale")]
    no_destinations = not [d for d in await repo.list_destinations() if data.can_send(d)]
    # Asked only when everything works; a problem on the page comes first.
    trouble = bool(waiting) or no_destinations
    return await core.render(
        request,
        "index.html",
        {
            "nav": "home",
            "items": cards,
            "more": more,
            "searches": rows,
            "waiting": len(waiting),
            "paused": len([row for row in rows if row["paused"]]),
            "found_today": totals.found_today,
            "found_total": totals.listings_found,
            "empty": not cards and not filtered,
            "filtered": filtered,
            "show": params.get("show", "all"),
            "search_filter": params.get("search", ""),
            "q": params.get("q", ""),
            "min": low,
            "max": high,
            "price_on": price_on,
            "price_errors": price_problems,
            "sort": params.get("sort", "newest"),
            "last_check_s": int(time.time()) - last_check if last_check else None,
            "latest_seq": await repo.latest_seq(),
            "no_destinations": no_destinations,
            # The Hidden chip only appears once something is hidden: it's how to undo it.
            "has_hidden": bool(await repo.items_feed(mark="hidden", limit=1)),
            "support_look": None if trouble else await support.card_on_visit(repo),
        },
        snapshot=snapshot,
    )


@router.post("/support/hide")
async def hide_support_card(request: Request) -> Response:
    """The support card's "Don't show again". The page script posts it in the background;
    without the script the form posts here and lands back on Finds."""
    await core.ctx(request).repo.opt_out_of_support_card()
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True})
    return RedirectResponse(core.url("home"), status_code=303)


@router.get("/api/finds")
async def older_finds(request: Request, before: int) -> JSONResponse:
    cards, more = await _feed(request, before=before)
    return JSONResponse({"html": "".join(_card(card) for card in cards), "more": more})


# --- Actions on one listing ------------------------------------------------------------


async def _entry(request: Request, item_id: int) -> FeedItem:
    entry = await core.ctx(request).repo.feed_item(item_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="That listing is no longer stored.")
    return entry


@router.post("/api/items/{item_id}/mark")
async def mark_item(request: Request, item_id: int) -> JSONResponse:
    await _entry(request, item_id)
    form = await request.form()
    mark = str(form.get("mark") or "")
    if mark not in ("saved", "hidden", "none"):
        return JSONResponse({"error": "Mark it saved, hidden or none."}, status_code=400)
    await core.ctx(request).repo.set_mark(item_id, None if mark == "none" else mark)  # type: ignore[arg-type]
    return JSONResponse({"ok": True, "mark": mark})


@router.post("/api/items/{item_id}/block-seller")
async def block_seller(request: Request, item_id: int) -> JSONResponse:
    item = (await _entry(request, item_id)).item
    if item.seller_id is None:
        return JSONResponse(
            {"error": "Vinted didn't say who sells this one, so there is no one to block."},
            status_code=400,
        )
    await core.ctx(request).repo.block_seller(
        item.seller_id, login=item.seller_login, tld=item.tld, reason="Blocked from Finds"
    )
    return JSONResponse({"ok": True, "seller": item.seller_login or str(item.seller_id)})


@router.post("/api/items/{item_id}/watch")
async def watch_item(request: Request, item_id: int) -> JSONResponse:
    item = (await _entry(request, item_id)).item
    return await _add_watch(request, "item", item.tld, item.item_id, item.title)


@router.post("/api/items/{item_id}/follow-seller")
async def follow_seller(request: Request, item_id: int) -> JSONResponse:
    item = (await _entry(request, item_id)).item
    if item.seller_id is None:
        return JSONResponse(
            {"error": "Vinted didn't say who sells this one, so there is no one to follow."},
            status_code=400,
        )
    label = item.seller_login or f"Seller {item.seller_id}"
    return await _add_watch(request, "seller", item.tld, item.seller_id, label)


async def _add_watch(
    request: Request, kind: str, tld: str, target_id: int, label: str
) -> JSONResponse:
    context = core.ctx(request)
    if context.watch_kinds and kind not in context.watch_kinds:
        return JSONResponse(
            {"error": "This copy of vinted-bot can't run that kind of watch."}, status_code=400
        )
    try:
        await context.repo.add_watch(
            kind="item" if kind == "item" else "seller",
            tld=tld,
            target_id=target_id,
            label=label,
        )
    except validation.InvalidInputError as exc:
        return JSONResponse({"error": exc.message}, status_code=409)
    return JSONResponse({"ok": True})


# --- Live --------------------------------------------------------------------------------


@router.get("/api/live")
async def live(request: Request, after: int | None = None) -> StreamingResponse:
    """New finds as they are stored, as `item` events carrying the rendered card."""
    context = core.ctx(request)
    resume = request.headers.get("last-event-id", "")
    start = int(resume) if resume.isdigit() else after
    cursor: int = start if start is not None else await context.repo.latest_seq()

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        started = time.monotonic()
        quiet_since = started
        yield "retry: 3000\n\n"
        while time.monotonic() - started < LIVE_MAX_S and not context.stop.is_set():
            if await request.is_disconnected():
                return
            now = int(time.time())
            entries = await context.repo.items_after(cursor)
            blocked = await context.repo.blocked_seller_ids() if entries else set()
            for entry in entries:
                cursor = entry.seq
                if entry.item.seller_id in blocked:
                    continue
                card = views.item_view(entry, now)
                card["is_new"] = True
                payload = {
                    "seq": entry.seq,
                    "id": card["id"],
                    "title": card["title"],
                    "total": card["total"],
                    "photo": card["photo"],
                    "deal_pct": card["deal_pct"],
                    "search": card["search"]["name"],
                    "html": _card(card),
                }
                yield f"id: {entry.seq}\nevent: item\ndata: {json.dumps(payload)}\n\n"
                quiet_since = time.monotonic()
            if time.monotonic() - quiet_since > LIVE_KEEPALIVE_S:
                yield ": keepalive\n\n"
                quiet_since = time.monotonic()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(context.stop.wait(), timeout=LIVE_POLL_S)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
