"""JSON for the pages' scripts, plus the feeds and downloads.

The builder's filter lookups are thin pass-throughs: the taxonomy service does the
talking to Vinted, and a dashboard started without it (tests, or the web UI alone)
answers 503 rather than pretending the picker can work.
"""

from __future__ import annotations

import hmac
import time
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Literal
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from vinted_sniper.db import export as exporter
from vinted_sniper.db.repo import FeedItem, Query
from vinted_sniper.engine import health
from vinted_sniper.vinted import urls
from vinted_sniper.vinted.errors import VintedError
from vinted_sniper.vinted.taxonomy import FACET_CODES, Taxonomy
from vinted_sniper.web import core, forms, views
from vinted_sniper.web.preview import TooSoonError, judge

router = APIRouter()

# An autocomplete needs two letters before it is worth asking Vinted.
_MIN_BRAND_QUERY = 2


@router.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    alive = await health.is_alive(core.ctx(request).repo)
    return JSONResponse({"alive": alive}, status_code=200 if alive else 503)


@router.get("/api/health")
async def api_health(request: Request) -> JSONResponse:
    snapshot = await health.snapshot(core.ctx(request).repo)
    return JSONResponse(snapshot.as_dict())


# --- The builder's filter data ---------------------------------------------------------


def _taxonomy(request: Request) -> Taxonomy:
    service = core.ctx(request).taxonomy
    if service is None:
        raise HTTPException(status_code=503, detail="The search builder is not available.")
    return service


def _known_tld(tld: str) -> str:
    if tld not in urls.KNOWN_TLDS:
        raise HTTPException(status_code=404, detail=f"vinted.{tld} is not a Vinted site.")
    return tld


def _id_list(raw: str) -> str:
    """Reduce user input to a comma-separated list of numeric ids, dropping the rest."""
    return ",".join(part.strip() for part in raw.split(",") if part.strip().isdigit())


@router.get("/api/filters/{tld}/categories")
async def filter_categories(request: Request, tld: str) -> JSONResponse:
    service = _taxonomy(request)
    try:
        tree = await service.categories(_known_tld(tld))
    except VintedError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"categories": tree})


@router.get("/api/filters/{tld}/brands")
async def filter_brands(
    request: Request, tld: str, q: str = "", catalog_ids: str = ""
) -> JSONResponse:
    service = _taxonomy(request)
    if len(q.strip()) < _MIN_BRAND_QUERY:
        return JSONResponse({"brands": []})
    try:
        brands = await service.brands(_known_tld(tld), q, _id_list(catalog_ids))
    except VintedError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"brands": brands})


@router.get("/api/filters/{tld}/facets/{code}")
async def filter_facet(
    request: Request, tld: str, code: str, catalog_ids: str = ""
) -> JSONResponse:
    service = _taxonomy(request)
    if code not in FACET_CODES:
        raise HTTPException(status_code=404, detail=f"No filter called {code!r}.")
    try:
        options = await service.facet_options(_known_tld(tld), code, _id_list(catalog_ids))
    except VintedError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"options": options})


# --- Preview and reachability ------------------------------------------------------


@router.post("/api/preview")
async def preview(request: Request) -> JSONResponse:
    """What a search in the editor would match on Vinted right now, and why not the rest."""
    context = core.ctx(request)
    values = forms.values_from_form(await request.form())
    parsed, errors = forms.best_effort(
        values, default_interval=context.settings.poll_default_interval_s
    )
    if parsed is None:
        return JSONResponse({"errors": errors, "count": None})
    if context.previews is None:
        return JSONResponse(
            {"errors": errors, "error": "Previews work while the app itself is running."},
            status_code=503,
        )
    try:
        items = await context.previews.listings(parsed.tld, parsed.params)
    except TooSoonError as exc:
        return JSONResponse({"wait": round(exc.wait_s, 1)}, status_code=429)
    except VintedError as exc:
        return JSONResponse(
            {"errors": errors, "error": f"Vinted didn't answer the preview: {exc}"},
            status_code=502,
        )
    query = Query(
        id=0,
        name=parsed.name,
        url=parsed.url,
        tld=parsed.tld,
        params=parsed.params,
        poll_interval_s=parsed.poll_interval_s,
        paused=False,
        **parsed.filters,
    )
    editing = request.query_params.get("search", "")
    typical = (
        await context.repo.typical_prices(int(editing)) if editing.isdigit() else {}
    )
    outcome = judge(items, query, typical)
    now = int(time.time())
    newest = outcome.matched[0] if outcome.matched else None
    return JSONResponse(
        {
            "errors": errors,
            "count": len(outcome.matched),
            "seen": outcome.seen,
            "site": f"vinted.{parsed.tld}",
            "url": parsed.url,
            "newest": (
                views.ago(now - newest.photo_ts)
                if newest is not None and newest.photo_ts
                else None
            ),
            "thumbs": [
                {
                    "photo": item.photo_url,
                    "total": views.money(item.total_price or item.price, item.currency),
                    "url": item.url,
                    "title": item.title,
                }
                for item in outcome.matched[:3]
            ],
            "receipt": [
                {
                    "label": views.REJECTION_WORDS.get(reason, (reason, "x"))[0],
                    "icon": views.REJECTION_WORDS.get(reason, (reason, "x"))[1],
                    "removed": count,
                }
                for reason, count in outcome.removed
            ],
            "seller_filters": query.needs_seller_profile,
        }
    )


@router.post("/api/diagnose")
async def diagnose(request: Request) -> JSONResponse:
    """Can this computer use Vinted right now? One small request, answered in words."""
    context = core.ctx(request)
    form = await request.form()
    tld = str(form.get("tld") or "")
    if tld not in urls.KNOWN_TLDS:
        return JSONResponse({"error": "Pick one of Vinted's country sites."}, status_code=400)
    if context.client is None:
        return JSONResponse(
            {"error": "The check works while the app itself is running."}, status_code=503
        )
    result = await context.client.diagnose(tld)
    return JSONResponse(result.model_dump())


# --- Feeds and downloads -----------------------------------------------------------


@router.get("/rss/{query_id}.xml")
async def rss(request: Request, query_id: int, key: str = "") -> Response:
    """A search's finds for a feed reader. Feed readers cannot sign in, so the key is in the URL."""
    context = core.ctx(request)
    token = context.settings.web_auth_token
    if token is not None and not (
        key and hmac.compare_digest(key.encode(), token.get_secret_value().encode())
    ):
        return Response("Add ?key=<your dashboard password> to the feed address.", 401)
    query = await context.repo.get_query(query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="No such search.")
    entries = await context.repo.rss_items(query_id)
    return Response(content=_rss_feed(query, entries), media_type="application/rss+xml")


def _rss_feed(query: Query, entries: list[FeedItem]) -> str:
    rows = []
    for entry in entries:
        item = entry.item
        total = item.total_price if item.total_price is not None else item.price
        description = f"{views.money(total, item.currency)} incl. fees"
        published = format_datetime(datetime.fromtimestamp(entry.first_seen_at, tz=UTC))
        rows.append(
            "<item>"
            f"<title>{xml_escape(item.title)}</title>"
            f"<link>{xml_escape(item.url)}</link>"
            f"<guid isPermaLink='false'>{item.item_id}</guid>"
            f"<pubDate>{published}</pubDate>"
            f"<description>{xml_escape(description)}</description>"
            "</item>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        f"<title>{xml_escape(query.name)}</title>"
        "<description>New Vinted listings matching this search</description>"
        f"<link>{xml_escape(query.url)}</link>"
        f"{''.join(rows)}"
        "</channel></rss>"
    )


@router.get("/export.{fmt}")
async def export(request: Request, fmt: Literal["csv", "json"], search: int | None = None) -> Response:
    """Every stored find, the same columns as `vinted-sniper export`."""
    entries = await core.ctx(request).repo.all_found(query_id=search)
    stamp = time.strftime("%Y-%m-%d")
    return Response(
        exporter.render(entries, fmt),
        media_type="text/csv" if fmt == "csv" else "application/json",
        headers={
            "Content-Disposition": f'attachment; filename="vinted-sniper-finds-{stamp}.{fmt}"'
        },
    )


@router.get("/manifest.webmanifest")
async def manifest() -> JSONResponse:
    icon = core.static
    body: dict[str, Any] = {
        "name": "vinted-sniper",
        "short_name": "Finds",
        "description": "New Vinted listings for your searches, as they appear.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#007782",
        "icons": [
            {"src": icon("img/icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": icon("img/icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": icon("img/icons/icon-maskable-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JSONResponse(body, media_type="application/manifest+json")


@router.get("/favicon.ico")
def favicon() -> Response:
    return Response(
        (core.STATIC_DIR / "img/icons/favicon.ico").read_bytes(),
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )
