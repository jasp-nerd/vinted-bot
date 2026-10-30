"""Gathering what several pages show: every search with its state, every destination.

`views` words a single row; this reads the rows. Kept apart so the pure wording stays
testable without a database.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from vinted_sniper.db.repo import Destination, Query
from vinted_sniper.engine import health
from vinted_sniper.web import views
from vinted_sniper.web.core import WebContext

# How recently a site must have shown something new to count as moving (the watchdog's).
_RECENT_MOVEMENT_S = 900


async def searches(
    context: WebContext, snapshot: health.Snapshot, tz: ZoneInfo
) -> list[dict[str, Any]]:
    """Every search, worded for the lists: status, reason, where it sends, finds today."""
    repo = context.repo
    now = int(time.time())
    queries = await repo.list_queries()
    by_id = {search.query_id: search for search in snapshot.searches}
    newest = await repo.newest_find_at()
    destinations = {d.id: d for d in await repo.list_destinations()}
    active = [d for d in destinations.values() if d.active]
    today = datetime.now(tz).date().isoformat()
    activity = await repo.activity(tz, days=1)
    finds_today: dict[int, int] = {}
    for row in activity.daily_finds:
        if row.day == today:
            finds_today[row.query_id] = finds_today.get(row.query_id, 0) + row.count
    moving = {
        search.tld
        for search in snapshot.searches
        if search.last_success_at
        and search.checks_without_new_listings == 0
        and now - search.last_success_at < _RECENT_MOVEMENT_S
    }

    rows = []
    for query in queries:
        routes = await repo.explicit_routes(query.id)
        targets = [destinations[i] for i in routes if i in destinations] if routes else active
        status = views.search_status(
            query,
            by_id.get(query.id),
            now=now,
            newest_find=newest.get(query.id),
            site_is_moving=query.tld in moving,
            stale_after=context.settings.watchdog_stale_cycles,
        )
        rows.append(
            {
                "id": query.id,
                "name": query.name,
                "color": views.color_css(query.color),
                "status": status.key,
                "status_label": status.label,
                "why": status.why,
                "tld": f"vinted.{query.tld}",
                "sites": ", ".join(f"vinted.{site}" for site in query.sites),
                "summary": views.search_summary(query),
                "dests": [d.kind for d in targets],
                "dest_names": [d.name for d in targets],
                "routes_all": not routes,
                "interval_human": views.every(query.poll_interval_s),
                "finds_today": finds_today.get(query.id, 0),
                "newest": views.ago(now - newest[query.id])
                if query.id in newest
                else "nothing yet",
                "paused": query.paused,
                "muted": query.is_muted(now),
                "tags": query.tags,
                "query": query,
            }
        )
    return rows


async def destinations(
    context: WebContext, queries: list[Query] | None = None
) -> list[dict[str, Any]]:
    """Every destination still switched on or worth explaining, worded for the cards."""
    repo = context.repo
    queries = queries if queries is not None else await repo.list_queries()
    counts = {row.destination_id: row for row in await repo.delivery_counts()}
    routes = {query.id: await repo.explicit_routes(query.id) for query in queries}
    found: list[Destination] = await repo.list_destinations()
    cards = []
    for destination in found:
        if not destination.active and destination.deactivated_reason == REMOVED:
            continue
        used_by = [
            {"id": q.id, "name": q.name, "color": views.color_css(q.color)}
            for q in queries
            if destination.id in routes[q.id] or (not routes[q.id] and destination.active)
        ]
        delivery = counts.get(destination.id)
        cards.append(
            views.destination_view(
                destination,
                sent=delivery.sent if delivery else 0,
                failed=delivery.failed if delivery else 0,
                searches=used_by,
            )
        )
    return cards


# What a destination removed from the Alerts page is marked with. Its row stays so past
# alerts keep their history; the page just stops showing it.
REMOVED = "removed from the dashboard"
