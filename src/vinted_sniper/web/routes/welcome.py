"""The first-run setup: country, a first search, where alerts go, a real test, done.

Answers travel from step to step in one hidden field and nothing is stored until "Open
my finds", so leaving halfway leaves nothing half-made. The one exception is Telegram:
pairing needs a waiting destination for the bot to claim, so that is created when the
person asks for a code (and reused if they ask again).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from vinted_sniper.db.repo import Query
from vinted_sniper.engine.validation import InvalidInputError
from vinted_sniper.vinted import urls
from vinted_sniper.web import core, destinations, forms, views
from vinted_sniper.web.routes import alerts

router = APIRouter()


def _submitted(form: Any) -> bool:
    """Whether a step's form was sent forward, rather than reached by Back or from before."""
    return form is not None and bool(form.get("submitted")) and not form.get("back")


def _state(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def _page(
    request: Request,
    template: str,
    step: int,
    state: dict[str, Any],
    status_code: int = 200,
    **extra: Any,
) -> Response:
    return core.TEMPLATES.TemplateResponse(
        request,
        template,
        {"step": step, "state": state, "state_json": json.dumps(state), "app": None, **extra},
        status_code=status_code,
    )


@router.get("/welcome")
async def hello(request: Request) -> Response:
    return await _page(request, "welcome-1.html", 0, {})


@router.api_route("/welcome/country", methods=["GET", "POST"])
async def country(request: Request) -> Response:
    form = await request.form() if request.method == "POST" else {}
    state = _state(form.get("state"))
    tld = state.get("tld") or views.guess_tld(request.headers.get("accept-language"))
    return await _page(
        request,
        "welcome-2.html",
        1,
        state,
        tld=tld,
        guessed="tld" not in state,
        countries=views.COUNTRIES,
        currency=lambda t: views.symbol(views.currency_for(t)),
    )


def _search_values(state: dict[str, Any], tld: str, interval: int) -> dict[str, Any]:
    values = forms.default_values(tld=tld, interval=interval, color=views.SLOT_COLORS[0])
    saved = state.get("search")
    if isinstance(saved, dict):
        values.update({k: v for k, v in saved.items() if k in values})
    values["tld"] = tld
    return values


@router.api_route("/welcome/search", methods=["GET", "POST"])
async def search(request: Request) -> Response:
    context = core.ctx(request)
    form = await request.form() if request.method == "POST" else None
    state = _state(form.get("state") if form else None)
    if form is not None and form.get("tld") and not form.get("back"):
        tld = str(form.get("tld")).removeprefix("vinted.")
        state["tld"] = tld if tld in urls.KNOWN_TLDS else "nl"
    tld = state.get("tld") or views.guess_tld(request.headers.get("accept-language"))
    state["tld"] = tld
    interval = max(context.settings.poll_default_interval_s, 60)
    errors: dict[str, str] = {}
    if _submitted(form):
        values = forms.values_from_form(form)
        values["tld"] = tld
        values["interval"] = str(interval)
        values["mode"] = str(form.get("mode") or "paste")
        if values["mode"] == "paste" and not values["link"]:
            errors["link"] = "Paste the link you copied from Vinted, or choose Build one here."
        else:
            if values["mode"] == "build":
                values["link"] = ""
            parsed, errors = forms.collect_errors(values, default_interval=interval)
            if parsed is not None:
                state["search"] = values
                state["tld"] = parsed.tld
                return await _alerts_page(request, state)
        state["search"] = values
    return await _page(
        request,
        "welcome-3.html",
        2,
        state,
        status_code=400 if errors else 200,
        f=_search_values(state, tld, interval),
        mode=(state.get("search") or {}).get("mode", "paste"),
        errors=errors,
        currency=views.symbol(views.currency_for(tld)),
        previews=context.previews is not None,
        builder=context.taxonomy is not None,
    )


async def _alerts_page(
    request: Request, state: dict[str, Any], errors: dict[str, str] | None = None
) -> Response:
    context = core.ctx(request)
    dest = state.get("dest") or {}
    return await _page(
        request,
        "welcome-4.html",
        3,
        state,
        status_code=400 if errors else 200,
        kind=dest.get("kind") or "ntfy",
        form=dest.get("form") or {},
        ntfy_topic=(dest.get("form") or {}).get("ntfy_topic") or destinations.new_ntfy_topic(),
        errors=errors or {},
        telegram=await alerts.telegram_setup(context),
        apprise=destinations.apprise_installed(),
        providers=destinations.EMAIL_PROVIDERS,
    )


@router.api_route("/welcome/alerts", methods=["GET", "POST"])
async def where(request: Request) -> Response:
    context = core.ctx(request)
    form = await request.form() if request.method == "POST" else None
    state = _state(form.get("state") if form else None)
    if not _submitted(form):
        return await _alerts_page(request, state)
    kind = str(form.get("kind") or "")
    fields = {k: str(v) for k, v in form.items() if k not in {"state", "submitted"}}
    if kind == "skip":
        state["dest"] = {"kind": "skip"}
        return await _ready(request, state)
    if kind == "telegram":
        pairing = state.get("telegram") or {}
        destination_id = int(fields.get("telegram_id") or pairing.get("id") or 0)
        destination = await context.repo.get_destination(destination_id) if destination_id else None
        if destination is None or not destination.config.get("chat_id"):
            state["dest"] = {"kind": "telegram", "form": fields}
            return await _alerts_page(
                request,
                state,
                {"telegram": "Send the code to your bot first, then press Continue."},
            )
        state["dest"] = {"kind": "telegram", "id": destination_id, "name": destination.name}
        return await _test(request, state)
    assert context.http is not None
    try:
        name, config = destinations.build(kind, fields)
        destinations.check(kind, config, context.settings, context.http)
    except InvalidInputError as exc:
        state["dest"] = {"kind": kind, "form": fields}
        return await _alerts_page(request, state, {exc.field: exc.message})
    state["dest"] = {"kind": kind, "name": name, "config": config, "form": fields}
    return await _test(request, state)


async def _test(request: Request, state: dict[str, Any]) -> Response:
    context = core.ctx(request)
    dest = state["dest"]
    tld = state.get("tld") or "nl"
    if dest["kind"] == "telegram":
        destination = await context.repo.get_destination(int(dest["id"]))
        if destination is None:
            return await _alerts_page(request, state, {"telegram": "Connect the chat again."})
        result = await alerts.test_unsaved(
            context, "telegram", destination.name, destination.config, tld
        )
    else:
        result = await alerts.test_unsaved(context, dest["kind"], dest["name"], dest["config"], tld)
    state["test"] = {"ok": result["ok"]}
    return await _page(
        request,
        "welcome-5.html",
        4,
        state,
        failed=not result["ok"],
        result=result,
        kind=dest["kind"],
        kind_name=views.KIND_NAMES.get(dest["kind"], dest["kind"]),
        dest_name=dest.get("name", ""),
    )


@router.post("/welcome/test")
async def test_again(request: Request) -> Response:
    form = await request.form()
    state = _state(form.get("state"))
    if form.get("next") == "ready" or not state.get("dest"):
        return await _ready(request, state)
    return await _test(request, state)


async def _ready(request: Request, state: dict[str, Any]) -> Response:
    context = core.ctx(request)
    values = state.get("search") or {}
    tld = state.get("tld") or "nl"
    interval = max(context.settings.poll_default_interval_s, 60)
    parsed, _ = forms.collect_errors(
        _search_values(state, tld, interval), default_interval=interval
    )
    dest = state.get("dest") or {}
    return await _page(
        request,
        "welcome-6.html",
        5,
        state,
        country=views.COUNTRY_NAMES.get(tld, tld),
        tld=tld,
        summary=views.search_summary(_preview_query(parsed)) if parsed else values.get("link"),
        dest_kind=dest.get("kind", "skip"),
        dest_name=dest.get("name") or views.KIND_NAMES.get(dest.get("kind", ""), ""),
        phone=core.phone_address(context.settings),
        loopback=context.settings.web_is_loopback,
        self_hosting=core.SELF_HOSTING_URL,
    )


def _preview_query(parsed: forms.ParsedSearch) -> Query:
    return Query(
        id=0,
        name=parsed.name,
        url=parsed.url,
        tld=parsed.tld,
        params=parsed.params,
        poll_interval_s=parsed.poll_interval_s,
        paused=False,
        **parsed.filters,
    )


@router.post("/welcome/finish")
async def finish(request: Request) -> Response:
    """Store everything the setup collected, checked again first so nothing is half-made."""
    context = core.ctx(request)
    repo = context.repo
    form = await request.form()
    state = _state(form.get("state"))
    tld = state.get("tld") or "nl"
    interval = max(context.settings.poll_default_interval_s, 60)
    parsed, errors = forms.collect_errors(
        _search_values(state, tld, interval), default_interval=interval
    )
    if parsed is None:
        state["search"] = {**(state.get("search") or {}), "mode": "paste"}
        return await _page(
            request,
            "welcome-3.html",
            2,
            state,
            status_code=400,
            f=_search_values(state, tld, interval),
            mode="paste",
            errors=errors or {"link": "Something about this search changed. Check it again."},
            currency=views.symbol(views.currency_for(tld)),
            previews=context.previews is not None,
            builder=context.taxonomy is not None,
        )
    dest = state.get("dest") or {}
    route: list[int] = []
    if dest.get("kind") == "telegram" and dest.get("id"):
        route = [int(dest["id"])]
    elif dest.get("kind") in destinations.KINDS and isinstance(dest.get("config"), dict):
        route = [
            await repo.add_destination(kind=dest["kind"], name=dest["name"], config=dest["config"])
        ]
    query_id = await repo.add_query(
        name=parsed.name,
        url=parsed.url,
        tld=parsed.tld,
        params=parsed.params,
        poll_interval_s=parsed.poll_interval_s,
        **parsed.filters,
    )
    await repo.set_routes(query_id, route)
    await repo.set_onboarded(True)
    return core.redirect(
        "/",
        "You're set. The first check skips what's already on Vinted, so only new "
        "listings alert you.",
    )


@router.post("/welcome/skip")
async def skip(request: Request) -> Response:
    await core.ctx(request).repo.set_onboarded(True)
    return RedirectResponse(core.url("searches"), status_code=303)
