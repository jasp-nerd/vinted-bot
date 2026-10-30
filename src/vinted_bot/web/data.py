"""Gathering what several pages show: every search with its state, every destination.

`views` words a single row; this reads the rows. Kept apart so the pure wording stays
testable without a database.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from vinted_bot import managed
from vinted_bot.db.repo import Destination, Query, Repo
from vinted_bot.deliver.dispatcher import awaiting_pairing
from vinted_bot.engine import health
from vinted_bot.web import views
from vinted_bot.web.core import WebContext

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
    active = [d for d in destinations.values() if can_send(d)]
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
        kept = [destinations[i] for i in routes if i in destinations]
        targets = [d for d in kept if not is_removed(d)] if routes else active
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
                # A route to a place that was switched off still shows, marked, so the
                # search does not look like it sends somewhere it can't.
                "dest_off": [not d.active for d in targets],
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
    context: WebContext, queries: list[Query] | None = None, tz: ZoneInfo | None = None
) -> list[dict[str, Any]]:
    """Every destination still switched on or worth explaining, worded for the cards."""
    repo = context.repo
    queries = queries if queries is not None else await repo.list_queries()
    counts = {row.destination_id: row for row in await repo.delivery_counts()}
    routes = {query.id: await repo.explicit_routes(query.id) for query in queries}
    telegram_ready = await managed.telegram_token(context.settings, repo) is not None
    found: list[Destination] = await repo.list_destinations()
    cards = []
    for destination in found:
        if is_removed(destination):
            continue
        used_by = [
            {"id": q.id, "name": q.name, "color": views.color_css(q.color)}
            for q in queries
            if destination.id in routes[q.id] or (not routes[q.id] and can_send(destination))
        ]
        delivery = counts.get(destination.id)
        cards.append(
            views.destination_view(
                destination,
                sent=delivery.sent if delivery else 0,
                failed=delivery.failed if delivery else 0,
                searches=used_by,
                last_test=await last_test(repo, destination.id),
                telegram_ready=telegram_ready,
                tz=tz,
            )
        )
    return cards


# Brand names by id, as picked in the builder or read off a preview. A stored search keeps
# only ids (they are what Vinted's search takes), and nothing turns an id back into a name.
_BRAND_NAMES_KEY = "brand_names"
_MAX_BRAND_NAMES = 2000


async def remember_brand_names(repo: Repo, labels: str) -> None:
    """Keep the names behind an editor's brand chips (its `labels` field) for next time."""
    try:
        parsed = json.loads(labels or "{}")
    except ValueError:
        return  # a mangled hidden field only costs the names, which are cosmetic
    if not isinstance(parsed, dict):
        return
    fresh = {
        key.removeprefix("brand:"): str(name)[:80]
        for key, name in parsed.items()
        if isinstance(key, str) and key.startswith("brand:") and key[6:].isdigit()
    }
    if not fresh:
        return
    known = {**await _brand_names(repo), **fresh}
    kept = dict(list(known.items())[-_MAX_BRAND_NAMES:])
    await repo.set_state_value(_BRAND_NAMES_KEY, json.dumps(kept))


async def brand_labels(repo: Repo, brand_ids: str) -> str:
    """The editor's `labels` field for these brand ids: the names that are known."""
    known = await _brand_names(repo)
    ids = [part for part in brand_ids.split(",") if part in known]
    return json.dumps({f"brand:{brand_id}": known[brand_id] for brand_id in ids})


async def _brand_names(repo: Repo) -> dict[str, str]:
    raw = await repo.get_state_value(_BRAND_NAMES_KEY)
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _test_key(destination_id: int) -> str:
    return f"destination_test:{destination_id}"


async def record_test(repo: Repo, destination_id: int, *, ok: bool, message: str) -> None:
    """Remember how the latest test send went, so the card can say "Test arrived".

    Kept in app_state rather than the destination's config: the config is what the
    sender reads, and a test result is not something it should ever see.
    """
    value = {"ok": ok, "at": int(time.time()), "message": message}
    await repo.set_state_value(_test_key(destination_id), json.dumps(value))


async def last_test(repo: Repo, destination_id: int) -> dict[str, Any] | None:
    raw = await repo.get_state_value(_test_key(destination_id))
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def can_send(destination: Destination) -> bool:
    """Switched on and finished: a Telegram place still waiting for its chat is neither
    a place alerts go nor a reason to stop saying "finds only show on this page"."""
    return destination.active and not awaiting_pairing(destination)


async def set_notify_status(repo: Repo, destination_id: int, *, on: bool) -> None:
    """Switch a place's status alerts (watchdog, "updated itself") on or off.

    Adapter: Repo has no setter for `notify_status` on this branch. It moves into Repo
    (db/repo.py, where SQL lives) when the backend branch that owns it is merged.
    """
    await repo._db.execute(
        "UPDATE destinations SET notify_status = ? WHERE id = ?", (int(on), destination_id)
    )


def is_removed(destination: Destination) -> bool:
    """Removed from the Alerts page: kept for history, shown nowhere else."""
    return not destination.active and destination.deactivated_reason == REMOVED


# What a destination removed from the Alerts page is marked with. Its row stays so past
# alerts keep their history; the page just stops showing it.
REMOVED = "removed from the dashboard"
