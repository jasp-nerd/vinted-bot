"""The facts reported with each start and each daily heartbeat.

`environment` describes the computer and how vinted-bot was installed and set up;
`snapshot` describes what it is set to do. Both are counts, yes-or-no answers and values
from fixed lists: how many searches check every 5 seconds, not what they look for; which
kinds of filter are in use, not their values; how many destinations of each kind, not
where they point.
"""

from __future__ import annotations

import contextlib
import os
import platform
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vinted_bot import __version__, managed
from vinted_bot.config import Settings, in_container
from vinted_bot.db.repo import Query, Repo
from vinted_bot.engine import self_update, updates

# The search filters Vinted's own links use, by name (never their values). Anything else in
# a pasted link counts as "other": a name made up in an address bar is text someone typed.
_KNOWN_PARAMS = frozenset(
    {
        "search_text",
        "order",
        "price_from",
        "price_to",
        "currency",
        "is_for_swap",
        "catalog_ids",
        "brand_ids",
        "size_ids",
        "status_ids",
        "color_ids",
        "material_ids",
        "patterns_ids",
        "video_game_rating_ids",
        "video_game_platform_ids",
    }
)


def _bracket(value: float, edges: tuple[float, ...], unit: str) -> str:
    """`value` as a range (2-4GB) rather than the exact figure."""
    low = 0.0
    for edge in edges:
        if value < edge:
            return f"{low:g}-{edge:g}{unit}"
        low = edge
    return f"{low:g}+{unit}"


def _memory_gb() -> float | None:
    with contextlib.suppress(AttributeError, ValueError, OSError):
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    return None


def _read(path: str) -> str | None:
    with contextlib.suppress(OSError, UnicodeDecodeError):
        return Path(path).read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
    return None


def device() -> str | None:
    """The kind of machine, when it is one people choose to run this on."""
    model = _read("/proc/device-tree/model") or ""
    if model.startswith("Raspberry Pi"):
        # "Raspberry Pi 4 Model B Rev 1.4" -> "Raspberry Pi 4"
        return " ".join(model.split()[:3])
    if Path("/etc/synoinfo.conf").exists() or Path("/etc.defaults/VERSION").exists():
        return "Synology"
    if Path("/etc/unraid-version").exists():
        return "Unraid"
    if Path("/etc/config/qpkg.conf").exists():
        return "QNAP"
    if "microsoft" in platform.release().lower():
        return "WSL"
    return None


def operating_system() -> dict[str, Any]:
    system = platform.system()
    facts: dict[str, Any] = {"os": {"Darwin": "macOS"}.get(system, system)}
    if system == "Darwin":
        facts["os_version"] = platform.mac_ver()[0]
    elif system == "Windows":
        facts["os_version"] = platform.version()
    elif system == "Linux":
        with contextlib.suppress(OSError):
            release = platform.freedesktop_os_release()
            facts["distro"] = release.get("ID")
            facts["os_version"] = release.get("VERSION_ID")
    return facts


async def environment(
    settings: Settings, repo: Repo, install: self_update.Install, *, proxies: int
) -> dict[str, Any]:
    """The computer, the install, and how the app around the searches is set up."""
    prefs = await repo.app_settings(default_timezone=settings.timezone)
    memory = _memory_gb()
    db_mb: str | None = None
    with contextlib.suppress(OSError):
        db_mb = _bracket(settings.db_path.stat().st_size / 1024**2, (1, 10, 50, 200, 1000), "MB")
    password = settings.web_auth_token is not None
    if not password and settings.web_enabled:
        from vinted_bot.web import security  # noqa: PLC0415 - FastAPI only when it runs

        password = await security.password_required(settings, repo)
    return {
        **operating_system(),
        "arch": platform.machine().lower(),
        "python": platform.python_version(),
        "install": install.kind.value,
        "supervisor": install.supervisor,
        "container": in_container(),
        "machine": device(),
        "cpus": os.cpu_count(),
        "memory": _bracket(memory, (1, 2, 4, 8, 16, 32), "GB") if memory else None,
        "database": db_mb,
        "timezone": prefs.timezone,
        "theme": prefs.theme,
        "impersonate": settings.http_impersonate,
        "proxies": proxies,
        "web": settings.web_enabled,
        "phone_access": await managed.phone_access(repo),
        "password": password,
        "public_url": settings.web_public_url is not None,
        "telegram_bot": await managed.telegram_token(settings, repo) is not None,
        "update_check": prefs.update_check,
        "auto_update": prefs.auto_update,
        "can_update_itself": install.can_update_automatically,
        "update_available": updates.is_newer(prefs.latest_version),
        "latest_version": prefs.latest_version,
        "healthcheck": prefs.healthcheck_url is not None,
        "onboarded": prefs.onboarded,
    }


_FILTERS: dict[str, Callable[[Query], bool]] = {
    "banned_keywords": lambda q: bool(q.banned_keywords),
    "include_terms": lambda q: bool(q.include_terms),
    "regex": lambda q: q.regex is not None,
    "min_total_price": lambda q: q.min_total_price is not None,
    "max_total_price": lambda q: q.max_total_price is not None,
    "conditions": lambda q: bool(q.conditions),
    "seller_countries": lambda q: bool(q.countries),
    "seller_min_rating": lambda q: q.seller_min_rating is not None,
    "seller_min_reviews": lambda q: q.seller_min_reviews is not None,
    "skip_unrated_sellers": lambda q: q.skip_unrated_sellers,
    "deal_only": lambda q: q.deal_only_pct is not None,
    "max_age": lambda q: q.max_age_min is not None,
    "quiet_hours": lambda q: q.quiet_start is not None,
    "resale": lambda q: q.resale_price is not None or q.min_margin is not None,
    "tags": lambda q: bool(q.tags),
    "notes": lambda q: bool(q.notes),
    "muted": lambda q: q.muted_until is not None,
}


def _searches(queries: list[Query]) -> dict[str, Any]:
    active = [q for q in queries if not q.paused]
    filters: Counter[str] = Counter()
    params: Counter[str] = Counter()
    for query in queries:
        filters.update(name for name, used in _FILTERS.items() if used(query))
        params.update(name if name in _KNOWN_PARAMS else "other" for name in query.params)
    return {
        "searches": len(queries),
        "searches_paused": len(queries) - len(active),
        "intervals": dict(Counter(str(q.poll_interval_s) for q in active)),
        "sites": sorted({site for q in queries for site in q.sites}),
        "multi_site_searches": sum(1 for q in queries if q.extra_tlds),
        "quiet_mode": dict(Counter(q.quiet_mode for q in queries if q.quiet_start)),
        "filters": dict(filters),
        "params": dict(params),
    }


async def snapshot(repo: Repo, *, timezone: str) -> dict[str, Any]:
    """What the app is set to do: searches, destinations and watches, as counts."""
    queries = await repo.list_queries()
    destinations = await repo.list_destinations()
    watches = await repo.list_watches()
    totals = await repo.totals(ZoneInfo(timezone))
    return {
        **_searches(queries),
        "destinations": dict(Counter(d.kind for d in destinations if d.active)),
        "destinations_off": sum(1 for d in destinations if not d.active),
        "status_alerts": sum(1 for d in destinations if d.notify_status),
        "watches": dict(Counter(w.kind for w in watches if w.active)),
        "blocked_sellers": totals.blocked_sellers,
        "finds": totals.listings_found,
        "alerts_sent": totals.notifications_sent,
    }


def base_properties(install: self_update.Install) -> dict[str, Any]:
    """Sent with every event, so any one of them can be split by version or system."""
    return {
        "version": __version__,
        "install": install.kind.value,
        "os": operating_system()["os"],
        "arch": platform.machine().lower(),
    }
