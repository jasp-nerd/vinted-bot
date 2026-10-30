"""Stats: how the searches have been doing, on the reader's own clock.

Only what the database actually knows. Vinted's catalog stopped saying when a listing
was posted, so there is no "time from listing to alert" here: a number we would have to
guess is worse than no number.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from vinted_sniper.web import core, views

router = APIRouter()

RANGES = (7, 30, 90)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _nice_max(value: int) -> tuple[int, list[int]]:
    """A round top for an axis and its ticks, so the gridlines read 0, 10, 20."""
    top = max(value, 4)
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if top / step <= 4:  # noqa: PLR2004
            ceiling = -(-top // step) * step
            return ceiling, list(range(0, ceiling + 1, step))
    return top, [0, top]


@router.get("/stats")
async def stats(request: Request, days: int = 30, search: str = "") -> Response:
    context = core.ctx(request)
    repo = context.repo
    days = days if days in RANGES else 30
    only = int(search) if search.isdigit() else None
    tz = await core.timezone(context)
    queries = {query.id: query for query in await repo.list_queries()}

    activity = await repo.activity(tz, days=days * 2)
    today = datetime.now(tz).date()
    day_keys = [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]
    earlier_start = (today - timedelta(days=days * 2 - 1)).isoformat()
    per_day = dict.fromkeys(day_keys, 0)
    earlier = 0
    for row in activity.daily_finds:
        if only is not None and row.query_id != only:
            continue
        if row.day in per_day:
            per_day[row.day] += row.count
        elif earlier_start <= row.day < day_keys[0]:
            earlier += row.count
    total = sum(per_day.values())
    change = round((total - earlier) / earlier * 100) if earlier else None

    in_range = await repo.activity(tz, days=days)
    heat = [[0] * 24 for _ in range(7)]
    for cell in in_range.heatmap:
        heat[cell.weekday][cell.hour] = cell.count
    heat_max = max((max(row) for row in heat), default=0) or 1

    medians: dict[tuple[int, str], list[Decimal]] = defaultdict(list)
    for median in in_range.daily_medians:
        if only is None or median.query_id == only:
            medians[(median.query_id, median.currency)].append(median.median)
    prices: list[dict[str, Any]] = [
        {
            "name": queries[qid].name if qid in queries else "Deleted search",
            "color": views.color_css(queries[qid].color if qid in queries else None),
            "value": float(statistics.median(values)),
            "label": views.money(statistics.median(values), currency),
        }
        for (qid, currency), values in sorted(medians.items())
    ]
    price_top = max((float(p["value"]) for p in prices), default=1.0) or 1.0

    delivery = await repo.delivery_counts()
    sent = sum(row.sent for row in delivery)
    failed = sum(row.failed for row in delivery)
    ymax, ticks = _nice_max(max(per_day.values(), default=0))
    first = datetime.fromisoformat(day_keys[0])
    labels = [
        datetime.fromisoformat(day).strftime("%-d %b" if i == 0 or day.endswith("-01") else "%-d")
        for i, day in enumerate(day_keys)
    ]
    totals = await repo.totals(tz)
    busiest = max(((d, h) for d in range(7) for h in range(24)), key=lambda dh: heat[dh[0]][dh[1]])
    page: dict[str, Any] = {
        "nav": "stats",
        "days": days,
        "ranges": RANGES,
        "search": only,
        "searches": [
            {"id": q.id, "name": q.name, "color": views.color_css(q.color)}
            for q in queries.values()
        ],
        "total": total,
        "change": change,
        "today": totals.found_today if only is None else per_day[day_keys[-1]],
        "sent": sent,
        "failed": failed,
        "delivered_pct": round(sent / (sent + failed) * 100, 1) if sent + failed else None,
        "finds_per_day": list(per_day.values()),
        "day_labels": labels,
        "day_tips": [
            f"<b>{count} finds</b><br>{datetime.fromisoformat(day).strftime('%a %-d %b')}"
            for day, count in per_day.items()
        ],
        "label_every": 7 if days <= 30 else 14,  # noqa: PLR2004
        "ymax": ymax,
        "ticks": ticks,
        "range_text": f"{first.strftime('%-d %b')} to {today.strftime('%-d %b')}",
        "heat": heat,
        "heat_max": heat_max,
        "has_heat": any(any(row) for row in heat),
        "busiest": f"{WEEKDAYS[busiest[0]]} {busiest[1]:02d}:00 to {(busiest[1] + 1) % 24:02d}:00",
        "weekdays": WEEKDAYS,
        "prices": prices,
        "price_top": price_top,
        "delivery": [
            {
                "name": row.name,
                "kind": row.kind,
                "sent": row.sent,
                "failed": row.failed,
                "pct": round(row.sent / (row.sent + row.failed) * 100, 1)
                if row.sent + row.failed
                else None,
            }
            for row in delivery
        ],
    }
    return await core.render(request, "stats.html", page)
