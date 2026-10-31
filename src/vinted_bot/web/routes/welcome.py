"""The first-run setup: country, a first search, where alerts go, a real test, done.

Answers travel from step to step in one hidden field. The search and the place for alerts
are stored at the test step, as soon as there is something worth keeping: the last screen
tells people they can close the tab, and by then their phone is subscribed to a topic
that has to exist. The ids of what was stored travel along too, so going back and
changing an answer updates those rows instead of adding a second search. Telegram's
place exists even earlier: pairing needs a waiting destination for the bot to claim.

The answers are also kept in app_state after every step, and every step that stores or
sends something answers with a redirect to a page that only reads (post, redirect, get).
A reload, Back in the browser or a bookmark then shows the same step again instead of
sending a second test, losing the answers or showing an error page. Running setup again
later reuses a search or place that is already exactly the same.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, TypeGuard

from fastapi import APIRouter, Request
from fastapi.datastructures import FormData
from fastapi.responses import RedirectResponse, Response

from vinted_bot.db.repo import DuplicateSearchError, Query, Repo
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.vinted import urls
from vinted_bot.web import core, data, destinations, forms, security, support, views
from vinted_bot.web.routes import alerts

router = APIRouter()


def _submitted(form: Any) -> TypeGuard[FormData]:
    """Whether a step's form was sent forward, rather than reached by Back or from before."""
    return form is not None and bool(form.get("submitted")) and not form.get("back")


# Where the answers so far are kept between steps, until setup finishes or is skipped.
_SETUP_KEY = "setup_answers"


def _parse(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def _state(context: core.WebContext, raw: Any) -> dict[str, Any]:
    """The answers a step's form carried, or, when it carried none (a plain load, a
    reload after a redirect), the ones kept from the last step."""
    if raw is not None:
        return _parse(raw)
    return _parse(await context.repo.get_state_value(_SETUP_KEY))


async def _keep(context: core.WebContext, state: dict[str, Any]) -> None:
    await context.repo.set_state_value(_SETUP_KEY, json.dumps(state))


async def _page(
    request: Request,
    template: str,
    step: int,
    state: dict[str, Any],
    status_code: int = 200,
    **extra: Any,
) -> Response:
    context = core.ctx(request)
    if step:
        await _keep(context, state)
    return core.TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "step": step,
            "state": state,
            "state_json": json.dumps(state),
            "app": None,
            "guess_timezone": await core.needs_timezone(context),
            **extra,
        },
        status_code=status_code,
    )


@router.get("/welcome")
async def hello(request: Request) -> Response:
    return await _page(request, "welcome-1.html", 0, {})


@router.api_route("/welcome/country", methods=["GET", "POST"])
async def country(request: Request) -> Response:
    form = await request.form() if request.method == "POST" else {}
    state = await _state(core.ctx(request), form.get("state"))
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
    state = await _state(context, form.get("state") if form else None)
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
                await _keep(context, state)
                return RedirectResponse("/welcome/alerts", status_code=303)
        state["search"] = values
    return await _search_page(request, state, errors)


async def _search_page(request: Request, state: dict[str, Any], errors: dict[str, str]) -> Response:
    context = core.ctx(request)
    tld = state.get("tld") or "nl"
    interval = max(context.settings.poll_default_interval_s, 60)
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
        local=next(((code, name) for t, code, name in views.COUNTRIES if t == tld), None),
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
        kind=dest.get("kind") or "",
        form=dest.get("form") or {},
        ntfy_topic=(dest.get("form") or {}).get("ntfy_topic") or await _setup_topic(context),
        errors=errors or {},
        telegram=await alerts.telegram_setup(context),
        providers=destinations.EMAIL_PROVIDERS,
        security_modes=destinations.EMAIL_SECURITY,
        webhook=True,
    )


async def _setup_topic(context: core.WebContext) -> str:
    """The ntfy name setup offers: the one a phone place already uses, when setup runs
    again, so the same answer finds the same place instead of a second phone place."""
    for destination in await context.repo.list_destinations():
        if destination.kind == "ntfy" and data.can_send(destination):
            topic = destination.config.get("topic")
            if isinstance(topic, str) and topic and not destination.config.get("server"):
                return topic
    return await alerts.ntfy_topic(context, fresh_if_used=False)


@router.api_route("/welcome/alerts", methods=["GET", "POST"])
async def where(request: Request) -> Response:
    context = core.ctx(request)
    form = await request.form() if request.method == "POST" else None
    state = await _state(context, form.get("state") if form else None)
    if not state.get("search"):
        return RedirectResponse("/welcome/search", status_code=303)
    if not _submitted(form):
        return await _alerts_page(request, state)
    kind = str(form.get("kind") or "")
    fields = {k: str(v) for k, v in form.items() if k not in {"state", "submitted"}}
    if kind == "skip":
        state["dest"] = {"kind": "skip"}
        return await _to_ready(context, state)
    if kind == "telegram":
        return await _telegram_answer(request, state, fields)
    assert context.http is not None
    try:
        name, config = destinations.build(kind, fields)
        destinations.check(kind, config, context.settings, context.http)
    except InvalidInputError as exc:
        state["dest"] = {"kind": kind, "form": fields}
        return await _alerts_page(request, state, {exc.field: exc.message})
    state["dest"] = {"kind": kind, "name": name, "config": config, "form": fields}
    return await _test(request, state)


async def _to_ready(context: core.WebContext, state: dict[str, Any]) -> Response:
    await _save(context, state)
    await _keep(context, state)
    return RedirectResponse("/welcome/ready", status_code=303)


async def _telegram_answer(
    request: Request, state: dict[str, Any], fields: dict[str, str]
) -> Response:
    """Continue with Telegram picked: check a pasted token, else the chat must be connected."""
    context = core.ctx(request)
    if fields.get("telegram_token") and not await alerts.telegram_ready(context):
        # A token pasted, then Continue instead of "Check and save": check it now.
        state["dest"] = {"kind": "telegram", "form": {}}
        try:
            await alerts.save_telegram_token(context, fields["telegram_token"])
        except InvalidInputError as exc:
            return await _alerts_page(request, state, {exc.field: exc.message})
        return await _alerts_page(request, state)
    pairing = state.get("telegram") or {}
    destination_id = int(fields.get("telegram_id") or pairing.get("id") or 0)
    destination = await context.repo.get_destination(destination_id) if destination_id else None
    if destination is None or not destination.config.get("chat_id"):
        # Never the token: the answers travel in the page, and it's a secret.
        kept = {k: v for k, v in fields.items() if k != "telegram_token"}
        state["dest"] = {"kind": "telegram", "form": kept}
        if not await alerts.telegram_ready(context):
            problem = {"telegram_token": "Paste your bot's token from BotFather first."}
        else:
            problem = {"telegram": "Send the code to your bot first, then press Continue."}
        return await _alerts_page(request, state, problem)
    state["dest"] = {"kind": "telegram", "id": destination_id, "name": destination.name}
    return await _test(request, state)


async def _test(request: Request, state: dict[str, Any]) -> Response:
    """Send the test, store what there is, then show the result on a page of its own."""
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
    state["test"] = result
    # Kept now, not on the last screen: from here on the person may simply walk away.
    await _save(context, state)
    await _keep(context, state)
    return RedirectResponse("/welcome/test", status_code=303)


@router.get("/welcome/test")
async def test_result(request: Request) -> Response:
    """How the test went, read back from the kept answers: a reload sends nothing."""
    state = await _state(core.ctx(request), None)
    dest = state.get("dest") or {}
    result = state.get("test")
    if not isinstance(result, dict) or dest.get("kind") not in destinations.KINDS:
        return RedirectResponse("/welcome/alerts", status_code=303)
    return await _page(
        request,
        "welcome-5.html",
        4,
        state,
        failed=not result.get("ok"),
        result=result,
        kind=dest["kind"],
        kind_name=views.KIND_NAMES.get(dest["kind"], dest["kind"]),
        dest_name=dest.get("name", ""),
    )


@router.post("/welcome/test")
async def test_again(request: Request) -> Response:
    context = core.ctx(request)
    form = await request.form()
    state = await _state(context, form.get("state"))
    if form.get("next") == "ready" and not (state.get("test") or {}).get("ok"):
        # "Skip, show finds only here" after a test that didn't arrive.
        state["dest"] = {"kind": "skip"}
    if form.get("next") == "ready" or not state.get("dest"):
        return await _to_ready(context, state)
    return await _test(request, state)


@router.get("/welcome/ready")
async def ready(request: Request) -> Response:
    return await _ready(request, await _state(core.ctx(request), None))


async def _ready(request: Request, state: dict[str, Any]) -> Response:
    context = core.ctx(request)
    values = state.get("search") or {}
    tld = state.get("tld") or "nl"
    interval = max(context.settings.poll_default_interval_s, 60)
    if not values:
        return RedirectResponse("/welcome/search", status_code=303)
    parsed, _ = forms.collect_errors(
        _search_values(state, tld, interval), default_interval=interval
    )
    if parsed is None:
        return RedirectResponse("/welcome/search", status_code=303)
    dest = state.get("dest") or {}
    access = await security.access(context.settings, context.repo)
    return await _page(
        request,
        "welcome-6.html",
        5,
        state,
        country=views.COUNTRY_NAMES.get(tld, tld),
        tld=tld,
        summary=views.search_summary(_preview_query(parsed)),
        dest_kind=dest.get("kind", "skip"),
        dest_name=dest.get("name") or views.KIND_NAMES.get(dest.get("kind", ""), ""),
        access=access,
        phone=core.phone_addresses(context.settings, access),
        suggested_password=security.suggest_password(),
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
    """The last screen's button. Everything is stored already; this checks it once more."""
    context = core.ctx(request)
    form = await request.form()
    state = await _state(context, form.get("state"))
    errors = await _save(context, state)
    if errors:
        state["search"] = {**(state.get("search") or {}), "mode": "paste"}
        return await _search_page(request, state, errors)
    await context.repo.delete_state_value(_SETUP_KEY)
    return core.redirect("/", "All set. Your search is running.")


@router.get("/welcome/finish")
async def finish_again() -> Response:
    """The last step's address, reloaded: there is nothing to do but show it again."""
    return RedirectResponse("/welcome/ready", status_code=303)


async def _save(context: core.WebContext, state: dict[str, Any]) -> dict[str, str]:
    """Store the search, and the place for alerts once its test arrived.

    Safe to call on every step after the test: the ids in `state["saved"]` make it
    update what an earlier call stored. Returns the search's field errors, if any.
    """
    repo = context.repo
    tld = state.get("tld") or "nl"
    interval = max(context.settings.poll_default_interval_s, 60)
    parsed, errors = forms.collect_errors(
        _search_values(state, tld, interval), default_interval=interval
    )
    if parsed is None:
        return errors or {"link": "Something about this search changed. Check it again."}
    stored = state.get("saved")
    saved: dict[str, Any] = stored if isinstance(stored, dict) else {}
    destination_id = await _save_destination(repo, state, _int(saved.get("destination_id")))
    # A search that was already there is never setup's to change, so its id is not one to
    # update on the next step either.
    own_id = None if saved.get("kept") else _int(saved.get("query_id"))
    try:
        query_id, kept = await _save_query(repo, parsed, own_id)
    except InvalidInputError as exc:
        return {exc.field if exc.field in parsed.filters else "link": exc.message}
    if not kept:
        await repo.set_routes(query_id, [destination_id] if destination_id else [])
    elif destination_id and await repo.explicit_routes(query_id):
        # Its routes are its own too. With none it already sends everywhere, setup's place
        # included; with some, setup's place joins them, since that's where the test went.
        await repo.route(query_id, destination_id)
    await data.remember_brand_names(repo, str((state.get("search") or {}).get("labels") or ""))
    await repo.set_onboarded(True)
    if not isinstance(stored, dict):
        await support.note_setup(repo)
    state["saved"] = {"query_id": query_id, "destination_id": destination_id, "kept": kept}
    return {}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


async def _save_query(
    repo: Repo, parsed: forms.ParsedSearch, query_id: int | None
) -> tuple[int, bool]:
    """Store setup's search. Returns its id, and True when it was one already there.

    Setup run again with a link that is already watched keeps that search as it is: it
    may have been renamed, priced and filtered since, and setup asked about none of that.
    Overwriting it with setup's few answers lost all of it.
    """
    existing = await repo.get_query(query_id) if query_id else None
    if existing is None:
        try:
            new_id = await repo.add_query(
                name=parsed.name,
                url=parsed.url,
                tld=parsed.tld,
                params=parsed.params,
                poll_interval_s=parsed.poll_interval_s,
                **parsed.filters,
            )
        except DuplicateSearchError as exc:
            return exc.existing.id, True
        return new_id, False
    await repo.update_query(
        replace(
            existing,
            name=parsed.name,
            url=parsed.url,
            tld=parsed.tld,
            params=parsed.params,
            poll_interval_s=parsed.poll_interval_s,
            **parsed.filters,
        )
    )
    return existing.id, False


async def _save_destination(repo: Repo, state: dict[str, Any], saved_id: int | None) -> int | None:
    """The place alerts go, or None for "only on this page".

    A place whose test has not arrived (yet) is not stored: the search waits for it with
    whatever an earlier, working answer stored. A place the person moved away from is
    removed, since a search with no route sends to every place there is.
    """
    dest = state.get("dest") or {}
    kind = dest.get("kind")
    tested = bool((state.get("test") or {}).get("ok"))
    saved = await repo.get_destination(saved_id) if saved_id else None
    if saved is not None and data.is_removed(saved):
        saved = None
    if kind not in destinations.KINDS:
        if saved is not None:
            await repo.deactivate_destination(saved.id, data.REMOVED)
        return None
    if not tested:
        return saved.id if saved is not None else None
    if kind == "telegram":
        wanted = _int(dest.get("id"))
    elif saved is not None and saved.kind == kind and saved.active:
        await repo.update_destination_config(saved.id, dest["config"])
        wanted = saved.id
    elif same := await _same_destination(repo, kind, dest["config"]):
        wanted = same
    else:
        wanted = await repo.add_destination(
            kind=kind, name=dest["name"], config=dest["config"], notify_status=True
        )
        await data.record_test(repo, wanted, ok=True, message="Setup's test arrived.")
    if wanted is not None:
        # Setup's place is where someone expects to hear that a search stopped working.
        await repo.set_notify_status(wanted, True)
    if saved is not None and saved.id != wanted:
        await repo.deactivate_destination(saved.id, data.REMOVED)
    return wanted


async def _same_destination(repo: Repo, kind: str, config: dict[str, Any]) -> int | None:
    """A working place that already sends exactly here, from an earlier run of setup."""
    for destination in await repo.list_destinations():
        if destination.kind == kind and data.can_send(destination):
            stored = {k: v for k, v in destination.config.items() if k in config}
            if stored == config:
                return destination.id
    return None


@router.post("/welcome/skip")
async def skip(request: Request) -> Response:
    context = core.ctx(request)
    await context.repo.set_onboarded(True)
    await context.repo.delete_state_value(_SETUP_KEY)
    return RedirectResponse(core.url("searches"), status_code=303)


@router.get("/welcome/skip")
async def skip_reloaded() -> Response:
    """Skipping is a button; its address on its own just goes back to the start."""
    return RedirectResponse(core.url("welcome_1"), status_code=303)
