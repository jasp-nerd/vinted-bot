"""Usage statistics from the dashboard: which pages are opened and which actions are used.

Recorded by route, as the code names it (`/searches/{query_id}/edit`), so no id, search
or address someone typed is ever part of it. See docs/telemetry.md.
"""

from __future__ import annotations

import re
from http import HTTPStatus

from fastapi import Request, Response

from vinted_bot import telemetry

# What the pages' own scripts ask for in the background, not something a person did.
_BACKGROUND = frozenset(
    {
        "/api/out",
        "/api/preview",
        "/api/live",
        "/api/finds",
        "/api/health",
        "/api/access",
        "/api/update",
        "/healthz",
        "/favicon.ico",
        "/manifest.webmanifest",
        "/sw.js",
        "/offline",
        "/api/filters/{tld}/brands",
        "/api/filters/{tld}/categories",
        "/api/filters/{tld}/facets/{code}",
        "/destinations/telegram/pair/{destination_id}",
    }
)

# Things fetched with GET that are still something a person chose to do.
_GET_FEATURES = frozenset(
    {"/export.{fmt}", "/destinations/{destination_id}/preview", "/rss/{query_id}.xml"}
)

# A form that saves at every change is one use, not twenty.
_ONCE_PER_S = 600.0
# A feed reader asks every few minutes; once a day says the feed is used.
_FEED_ONCE_PER_S = 86_400.0

_LANGUAGE = re.compile(r"^\s*([a-z]{2})\b", re.IGNORECASE)


def _device(user_agent: str) -> str:
    if "iPad" in user_agent or "Tablet" in user_agent:
        return "tablet"
    if "Mobi" in user_agent or "Android" in user_agent:
        return "phone"
    return "desktop"


def _language(accept_language: str) -> str | None:
    match = _LANGUAGE.match(accept_language)
    return match.group(1).lower() if match else None


def record(request: Request, response: Response) -> None:
    """Note a page view or a use of a feature, once the response is ready."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if (
        not isinstance(path, str)
        or response.status_code >= HTTPStatus.BAD_REQUEST
        or path in _BACKGROUND
    ):
        return
    if request.method == "GET":
        if path in _GET_FEATURES:
            fmt = request.path_params.get("fmt")
            telemetry.event(
                "feature_used",
                feature=path,
                format=fmt if fmt in {"csv", "json"} else None,
                once_per_s=_FEED_ONCE_PER_S if path.startswith("/rss/") else None,
                key=path,
            )
        elif response.headers.get("content-type", "").startswith("text/html"):
            telemetry.event(
                "page_viewed",
                page=path,
                screen=_device(request.headers.get("user-agent", "")),
                language=_language(request.headers.get("accept-language", "")),
            )
        return
    telemetry.event("feature_used", feature=path, once_per_s=_ONCE_PER_S, key=path)


# Outside links the dashboard offers, by the name the page's script sends for them.
OUT_LINKS = frozenset(
    {"kofi", "sponsors", "star", "issue", "website", "docs", "release_notes", "vinted"}
)
_PLACE = re.compile(r"^[a-z0-9_-]{1,24}$")


def record_out_link(body: str) -> None:
    """A click on a link that leaves the dashboard, as `name:place` (see app.js)."""
    name, _, place = body.strip().partition(":")
    if name in OUT_LINKS:
        telemetry.event("link_opened", link=name, place=place if _PLACE.match(place) else None)
