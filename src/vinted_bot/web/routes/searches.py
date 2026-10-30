"""Searches: the list, the editor, one search's page, and the changes made from them.

Every form here answers a mistake by showing the form again with a sentence beside the
field, never with an error page, and nothing is written until the whole form is good.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from vinted_bot.db.repo import Query
from vinted_bot.engine import health
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.web import core, data, forms, security, views

router = APIRouter()


async def _query(request: Request, query_id: int) -> Query:
    query = await core.ctx(request).repo.get_query(query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="No such search.")
    return query


@router.get("/searches")
async def searches_page(request: Request) -> Response:
    context = core.ctx(request)
    snapshot = await health.snapshot(context.repo)
    rows = await data.searches(context, snapshot, await core.timezone(context))
    # Problems first, the way the Finds band sorts them, so the one that needs a look
    # isn't fifth in the list.
    rows.sort(key=lambda row: _ORDER.get(row["status"], len(_ORDER)))
    counts = {
        "running": len([row for row in rows if row["status"] != "paused"]),
        "waiting": len([row for row in rows if row["status"] in WAITING]),
        "paused": len([row for row in rows if row["status"] == "paused"]),
    }
    base = context.settings.web_public_url or str(request.base_url).rstrip("/")
    return await core.render(
        request,
        "searches.html",
        {
            "nav": "searches",
            "searches": rows,
            "counts": counts,
            "dests": await data.destinations(context),
            "bookmarklet": bookmarklet(base),
        },
        snapshot=snapshot,
    )


# Statuses that mean "running, but Vinted isn't giving us what we need", and the order
# the lists show statuses in: anything that needs a look first.
WAITING = ("blocked", "stuck", "stale")
_ORDER = {"blocked": 0, "stuck": 1, "stale": 2, "quiet": 3, "watching": 4, "paused": 5}


def bookmarklet(base: str) -> str:
    """A bookmark that opens the current Vinted page as a new search in this dashboard."""
    target = f"{base}{core.url('search_new')}?url="
    return (
        "javascript:(function(){window.open("
        f"'{target}'+encodeURIComponent(location.href),'_blank')}})()"
    )


# --- The editor --------------------------------------------------------------------


async def _editor(
    request: Request,
    values: dict[str, Any],
    *,
    query: Query | None,
    errors: dict[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    context = core.ctx(request)
    prefs = await context.repo.app_settings(default_timezone=context.settings.timezone)
    typical = await context.repo.typical_prices(query.id) if query else {}
    blocked = await context.repo.list_blocked_sellers()
    return await core.render(
        request,
        "search-edit.html",
        {
            "nav": "searches",
            "s": query,
            "f": values,
            "errors": errors or {},
            "dests": await data.destinations(context),
            "countries": views.COUNTRIES,
            "slots": views.SLOT_COLORS,
            "presets": forms.INTERVAL_PRESETS,
            "timezone": prefs.timezone,
            "typical": [views.money(v, c) for c, v in typical.items()],
            "link_price": _link_price(values),
            "blocked_count": len(blocked),
            "currency": views.symbol(views.currency_for(values["tld"])),
            "previews": context.previews is not None,
            "builder": context.taxonomy is not None,
        },
        status_code=status_code,
    )


def _link_price(values: dict[str, Any]) -> str | None:
    """The item-price limit a pasted link carries, which the editor has no field for."""
    try:
        extra = json.loads(values.get("extra_params") or "{}")
    except ValueError:
        return None
    if not isinstance(extra, dict):
        return None
    params = {str(k): str(v) for k, v in extra.items()}
    return views.link_price(params, views.currency_for(str(values.get("tld") or "")))


async def _new_values(request: Request) -> dict[str, Any]:
    context = core.ctx(request)
    queries = await context.repo.list_queries()
    # The site most searches use: the one the person shops on, not the last one added.
    sites = Counter(query.tld for query in queries)
    tld = (
        sites.most_common(1)[0][0]
        if sites
        else views.guess_tld(request.headers.get("accept-language"))
    )
    return forms.default_values(
        tld=tld,
        interval=max(context.settings.poll_default_interval_s, 60),
        color=views.SLOT_COLORS[len(queries) % len(views.SLOT_COLORS)],
    )


@router.get("/searches/new")
async def new_search(request: Request, url: str = "") -> Response:
    """The editor, empty, or filled from a link (`?url=`, which the bookmarklet uses)."""
    values = await _new_values(request)
    errors: dict[str, str] = {}
    if url:
        values, problem = forms.values_from_link(url, values)
        if problem:
            errors["link"] = problem
    return await _editor(request, values, query=None, errors=errors)


@router.post("/searches")
async def create_search(request: Request) -> Response:
    context = core.ctx(request)
    values = forms.values_from_form(await request.form())
    parsed, errors = forms.collect_errors(
        values, default_interval=context.settings.poll_default_interval_s
    )
    if parsed is None:
        return await _editor(request, values, query=None, errors=errors, status_code=400)
    try:
        query_id = await context.repo.add_query(
            name=parsed.name,
            url=parsed.url,
            tld=parsed.tld,
            params=parsed.params,
            poll_interval_s=parsed.poll_interval_s,
            **parsed.filters,
        )
    except InvalidInputError as exc:
        return await _editor(
            request, values, query=None, errors={exc.field: exc.message}, status_code=400
        )
    await context.repo.set_routes(query_id, parsed.destination_ids)
    return core.redirect(
        core.url("search_detail", id=query_id),
        "Watching it now. The first check skips what's already there, so only new "
        "listings alert you.",
    )


@router.post("/searches/bulk")
async def bulk(request: Request) -> Response:
    """Pause, resume, delete or reroute several searches at once."""
    repo = core.ctx(request).repo
    form = await request.form()
    ids = [int(str(v)) for v in form.getlist("ids") if str(v).isdigit()]
    queries = await repo.list_queries()
    known = {query.id for query in queries}
    paused = {query.id for query in queries if query.paused}
    action = str(form.get("action") or "")
    chosen = [query_id for query_id in ids if query_id in known]
    # Count only what changes: "Resumed 6" after resuming two paused ones reads as a lie.
    if action == "pause":
        chosen = [query_id for query_id in chosen if query_id not in paused]
    elif action == "resume":
        chosen = [query_id for query_id in chosen if query_id in paused]
    dests = [int(str(v)) for v in form.getlist("dest") if str(v).isdigit()]
    for query_id in chosen:
        match action:
            case "pause":
                await repo.set_paused(query_id, True)
            case "resume":
                await repo.set_paused(query_id, False)
            case "delete":
                await repo.delete_query(query_id)
            case "routes":
                await repo.set_routes(query_id, dests)
    words = {"pause": "Paused", "resume": "Resumed", "delete": "Deleted", "routes": "Rerouted"}
    count = len(chosen)
    noun = "search" if count == 1 else "searches"
    return core.redirect(core.url("searches"), f"{words.get(action, 'Changed')} {count} {noun}.")


@router.get("/searches/{query_id}/edit")
async def edit_search(request: Request, query_id: int) -> Response:
    query = await _query(request, query_id)
    routes = await core.ctx(request).repo.explicit_routes(query_id)
    return await _editor(request, forms.values_from_query(query, routes), query=query)


@router.post("/searches/{query_id}")
async def update_search(request: Request, query_id: int) -> Response:
    context = core.ctx(request)
    query = await _query(request, query_id)
    values = forms.values_from_form(await request.form())
    parsed, errors = forms.collect_errors(
        values, default_interval=context.settings.poll_default_interval_s
    )
    if parsed is None:
        return await _editor(request, values, query=query, errors=errors, status_code=400)
    try:
        await context.repo.update_query(
            replace(
                query,
                name=parsed.name,
                url=parsed.url,
                tld=parsed.tld,
                params=parsed.params,
                poll_interval_s=parsed.poll_interval_s,
                **parsed.filters,
            )
        )
    except InvalidInputError as exc:
        return await _editor(
            request, values, query=query, errors={exc.field: exc.message}, status_code=400
        )
    await context.repo.set_routes(query_id, parsed.destination_ids)
    return core.redirect(
        core.url("search_detail", id=query_id),
        "Changes saved. They apply from the next check.",
    )


# --- One search ----------------------------------------------------------------------


@router.get("/searches/{query_id}")
async def search_detail(request: Request, query_id: int) -> Response:
    context = core.ctx(request)
    repo = context.repo
    query = await _query(request, query_id)
    snapshot = await health.snapshot(repo)
    tz = await core.timezone(context)
    row = next(r for r in await data.searches(context, snapshot, tz) if r["id"] == query_id)
    now = int(time.time())

    today = datetime.now(tz).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(13, -1, -1)]
    activity = await repo.activity(tz, days=15)
    per_day = dict.fromkeys(days, 0)
    for entry in activity.daily_finds:
        if entry.query_id == query_id and entry.day in per_day:
            per_day[entry.day] += entry.count
    finds = await repo.items_feed(query_id=query_id, mark="all", limit=24)
    yesterday_by_now = await _yesterday_by_now(context, query_id, tz)

    rejections = await repo.rejections_for(query_id, limit=60)
    reasons = await repo.rejection_counts(query_id, since=now - 7 * 86_400)
    delivery = await repo.delivery_for_query(query_id)
    typical = await repo.typical_prices(query_id)
    state = await repo.get_state(query_id)

    return await core.render(
        request,
        "search-detail.html",
        {
            "nav": "searches",
            "s": row,
            # Not "q": the page frame puts "q" in the header's search box.
            "query": query,
            "finds_today": per_day[days[-1]],
            "finds_yesterday": yesterday_by_now,
            # Nothing before today: "same as yesterday" would compare with a day it
            # wasn't running.
            "first_day": not any(list(per_day.values())[:-1]),
            "finds_14": sum(per_day.values()),
            "spark": list(per_day.values()),
            "typical": [views.money(v, c) for c, v in typical.items()],
            "delivery": delivery,
            "items": [views.item_view(entry, now) for entry in finds],
            "rejections": [
                {
                    "photo": r.photo_url,
                    "title": r.title or f"Listing {r.item_id}",
                    "why": views.REJECTION_WORDS.get(r.reason, (r.reason, "x"))[0],
                    "detail": r.detail,
                    "icon": views.REJECTION_WORDS.get(r.reason, (r.reason, "circle-x"))[1],
                    "price": views.money(r.total_price, r.currency),
                    "age": views.ago(now - r.created_at),
                    "url": r.url,
                }
                for r in rejections
            ],
            "reasons": [
                (views.REJECTION_WORDS.get(reason, (reason, ""))[0], count)
                for reason, count in reasons.items()
            ],
            "quiet": views.quiet_summary(query),
            "timeline": _timeline(state, query, now, tz),
            "state": state,
            "rss": f"/rss/{query_id}.xml"
            + (
                f"?key={await security.feed_key(repo)}"
                if context.settings.web_auth_token is not None
                else ""
            ),
            "vinted_url": query.url,
        },
        snapshot=snapshot,
    )


async def _yesterday_by_now(context: core.WebContext, query_id: int, tz: Any) -> int:
    """Finds yesterday up to this time of day, for "2 more than yesterday by now"."""
    now = datetime.now(tz)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now - timedelta(days=1)
    # LIMIT -1 is SQLite for "no limit"; `since` already bounds this to two days.
    entries = await context.repo.items_feed(
        query_id=query_id, mark="all", since=int(start.timestamp()), limit=-1
    )
    return len([e for e in entries if e.first_seen_at <= end.timestamp()])


def _timeline(state: Any, query: Query, now: int, tz: Any) -> list[dict[str, str]]:
    """What the search's state can tell about recent checks, newest first.

    There is no per-check history in the database, so this is the last of each kind
    of event rather than a full log.
    """
    events: list[tuple[int, dict[str, str]]] = []
    if state.last_success_at:
        events.append(
            (
                state.last_success_at,
                {
                    "text": "Last check went fine",
                    "detail": f"{state.items_seen_total:,} listings looked at since it started",
                    "kind": "ok",
                },
            )
        )
    if state.last_status and state.last_status != "ok" and state.last_polled_at:
        events.append(
            (
                state.last_polled_at,
                {
                    "text": "The last check didn't work",
                    "detail": (state.last_error or state.last_status)[:200],
                    "kind": "bad",
                },
            )
        )
    if state.raw_advanced_at:
        events.append(
            (
                state.raw_advanced_at,
                {
                    "text": "Vinted showed something new",
                    "detail": "The newest listing on this search changed",
                    "kind": "ok",
                },
            )
        )
    if state.count_403 or state.count_429:
        events.append(
            (
                now,
                {
                    "text": "Times Vinted slowed us down",
                    "detail": f"Refused {state.count_403} times, asked to wait "
                    f"{state.count_429} times, since this search started",
                    "kind": "warn",
                },
            )
        )
    if query.quiet_start and query.quiet_end:
        events.append(
            (
                0,
                {
                    "text": f"Quiet hours {query.quiet_start} to {query.quiet_end}",
                    "detail": views.quiet_summary(query) or "",
                    "kind": "quiet",
                },
            )
        )
    events.sort(key=lambda pair: -pair[0])
    return [
        {**event, "time": views.clock(moment, tz) if moment else "Daily"}
        for moment, event in events
    ]


# --- Changes from the list -------------------------------------------------------------


@router.post("/searches/{query_id}/pause")
async def pause(request: Request, query_id: int) -> Response:
    await _query(request, query_id)
    form = await request.form()
    paused = str(form.get("paused", "1")) == "1"
    await core.ctx(request).repo.set_paused(query_id, paused)
    toast = (
        "Paused. No checks and no alerts until you resume."
        if paused
        else "Watching again. First check in a few seconds."
    )
    back = str(form.get("back") or "")
    target = back if back.startswith("/") and not back.startswith("//") else core.url("searches")
    return core.redirect(target, toast)


@router.post("/searches/{query_id}/unmute")
async def unmute(request: Request, query_id: int) -> Response:
    await _query(request, query_id)
    await core.ctx(request).repo.mute_query(query_id, int(time.time()))
    return core.redirect(core.url("search_detail", id=query_id), "Unmuted. Alerts are back on.")


@router.post("/searches/{query_id}/duplicate")
async def duplicate(request: Request, query_id: int) -> Response:
    copy_id = await core.ctx(request).repo.duplicate_query(query_id)
    if copy_id is None:
        raise HTTPException(status_code=404, detail="No such search.")
    return core.redirect(
        core.url("search_edit", id=copy_id),
        "Copied. The copy is paused until you save it the way you want.",
    )


@router.post("/searches/{query_id}/delete")
async def delete(request: Request, query_id: int) -> Response:
    query = await _query(request, query_id)
    await core.ctx(request).repo.delete_query(query_id)
    return core.redirect(core.url("searches"), f'Deleted "{query.name}".')


@router.post("/searches/{query_id}/routes")
async def set_routes(request: Request, query_id: int) -> Response:
    await _query(request, query_id)
    form = await request.form()
    ids = [int(str(v)) for v in form.getlist("dest") if str(v).isdigit()]
    await core.ctx(request).repo.set_routes(query_id, ids)
    return core.redirect(core.url("searches"), "Saved where alerts go.")
