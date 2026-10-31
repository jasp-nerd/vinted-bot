"""Stats: how the searches have been doing, on the reader's own clock.

Only what the database actually knows. Vinted's catalog stopped saying when a listing
was posted, so there is no "time from listing to alert" here: a number we would have to
guess is worse than no number.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from vinted_bot.web import core, data, views

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


# Fewer finds than this in the period before, and a percentage says more about luck.
_MIN_TO_COMPARE = 10
# Past this, "+3843%" stops meaning anything; say "more than 10 times" instead.
_MAX_SHOWN_RATIO = 10


def _change(total: int, earlier: int) -> dict[str, Any] | None:
    """How this period compares with the one before, or None when there's nothing to say."""
    if earlier < _MIN_TO_COMPARE:
        return None
    if total > earlier * _MAX_SHOWN_RATIO:
        return {"text": f"More than {_MAX_SHOWN_RATIO} times", "up": True}
    pct = round((total - earlier) / earlier * 100)
    return {"text": f"{'+' if pct > 0 else ''}{pct}%", "up": pct > 0}


def _axis_label(day: str, *, first: bool) -> str:
    """The chart's day label: "1 Mar" where a month starts (and on the first bar), else "7"."""
    moment = datetime.fromisoformat(day)
    return views.day_month(moment) if first or moment.day == 1 else str(moment.day)


def _weekday_date(day: str) -> str:
    moment = datetime.fromisoformat(day)
    return f"{moment:%a} {views.day_month(moment)}"


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
    change = _change(total, earlier)

    in_range = await repo.activity(tz, days=days)
    heat = [[0] * 24 for _ in range(7)]
    for cell in in_range.heatmap:
        heat[cell.weekday][cell.hour] = cell.count
    heat_max = max((max(row) for row in heat), default=0) or 1

    # The same typical price the search's own page and the deal badges use, so the
    # number never differs between pages.
    prices: list[dict[str, Any]] = []
    for query in queries.values():
        if only is not None and query.id != only:
            continue
        for currency, typical in (await repo.typical_prices(query.id)).items():
            prices.append(
                {
                    "name": query.name,
                    "color": views.color_css(query.color),
                    "value": float(typical),
                    "label": views.money(typical, currency),
                }
            )
    price_top = max((float(p["value"]) for p in prices), default=1.0) or 1.0

    # Places removed from the Alerts page keep their rows for history, not for this list.
    removed = {d.id for d in await repo.list_destinations() if data.is_removed(d)}
    delivery = [row for row in await repo.delivery_counts() if row.destination_id not in removed]
    sent = sum(row.sent for row in delivery)
    failed = sum(row.failed for row in delivery)
    ymax, ticks = _nice_max(max(per_day.values(), default=0))
    first = datetime.fromisoformat(day_keys[0])
    labels = [_axis_label(day, first=i == 0) for i, day in enumerate(day_keys)]
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
        "places_sent": len([row for row in delivery if row.sent]),
        "delivered_pct": round(sent / (sent + failed) * 100, 1) if sent + failed else None,
        "finds_per_day": list(per_day.values()),
        "day_labels": labels,
        "day_tips": [
            f"<b>{count} finds</b><br>{_weekday_date(day)}" for day, count in per_day.items()
        ],
        "label_every": 7 if days <= 30 else 14,  # noqa: PLR2004
        "ymax": ymax,
        "ticks": ticks,
        "range_text": f"{views.day_month(first)} to {views.day_month(today)}",
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
