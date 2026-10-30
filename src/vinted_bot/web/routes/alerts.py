"""Where alerts go: the destination cards, adding one, testing one, Telegram pairing.

Telegram is connected from here, with no command line and no settings file: the person
pastes the token BotFather gave them (checked with Telegram before it is kept), the
dashboard creates a pairing code, the person sends `/start <code>` to their bot (a link
does it in one tap), and the running bot claims the code and records the chat. The page
polls until it has.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from vinted_bot import managed
from vinted_bot.botctl.telegram_bot import create_pairing
from vinted_bot.db.repo import Destination
from vinted_bot.deliver import send_test
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.log import get_logger
from vinted_bot.web import core, data, destinations, sample_alert

log = get_logger(__name__)
router = APIRouter()

_TELEGRAM_API = "https://api.telegram.org"


async def telegram_bot_name(http: httpx.AsyncClient, token: str) -> str:
    """Ask Telegram which bot a token belongs to. Raises InvalidInputError saying why not.

    The request URL holds the token, so neither it nor httpx's message about it (which
    quotes the URL) is ever logged: only the kind of error.
    """
    try:
        response = await http.get(f"{_TELEGRAM_API}/bot{token}/getMe", timeout=10.0)
    except httpx.HTTPError as exc:
        log.info("telegram.getme_failed", error=type(exc).__name__)
        raise InvalidInputError(
            "telegram_token",
            "Couldn't reach Telegram to check the token. Is this computer online? Try "
            "again in a moment.",
        ) from exc
    # 401 for a token that was never valid or was revoked, 404 for one that is mangled.
    if response.status_code in {401, 404}:
        raise InvalidInputError(
            "telegram_token",
            "Telegram says that token isn't valid. Copy it again from BotFather: it's the "
            'line under "Use this token to access the HTTP API". If you made a new token '
            "since, the old one stopped working.",
        )
    try:
        username = (response.json().get("result") or {}).get("username")
    except (ValueError, AttributeError):
        username = None
    if response.status_code != 200 or not isinstance(username, str):  # noqa: PLR2004
        log.info("telegram.getme_failed", status=response.status_code)
        raise InvalidInputError(
            "telegram_token",
            f"Telegram didn't answer as expected (status {response.status_code}). Try "
            "again in a moment.",
        )
    return username


async def bot_username(context: core.WebContext) -> str | None:
    """The bot's @name, asked of Telegram once per token and remembered.

    Shown so people know which bot to message. A failed lookup is remembered too: the
    pairing still works with the code alone, so there is no reason to keep asking.
    """
    token = await managed.telegram_token(context.settings, context.repo)
    if token is None or context.http is None:
        return None
    if token not in context.bot_names:
        try:
            context.bot_names[token] = await telegram_bot_name(context.http, token)
        except InvalidInputError:
            context.bot_names[token] = None
    return context.bot_names[token]


async def telegram_ready(context: core.WebContext) -> bool:
    return await managed.telegram_token(context.settings, context.repo) is not None


async def telegram_setup(context: core.WebContext) -> dict[str, Any]:
    """What the Telegram choice and the bot card show. The token itself only masked."""
    token = await managed.telegram_token(context.settings, context.repo)
    return {
        "configured": token is not None,
        "from_env": managed.telegram_token_from_env(context.settings),
        "masked": managed.mask_token(token) if token else None,
        "bot": await bot_username(context),
    }


async def save_telegram_token(context: core.WebContext, raw: str) -> str:
    """Check a pasted token with Telegram and keep it. Returns the bot's @name.

    The running bot is told at once, so the pairing link works straight after.
    """
    assert context.http is not None  # opened by the app's lifespan
    if managed.telegram_token_from_env(context.settings):
        raise InvalidInputError(
            "telegram_token",
            "This copy's bot token comes from VINTED_BOT_TELEGRAM_BOT_TOKEN in its "
            "environment, so it's changed there.",
        )
    token = managed.find_telegram_token(raw)
    if token is None:
        raise InvalidInputError(
            "telegram_token",
            "That isn't a bot token. It's a number, a colon, then a long code, like "
            "123456789:AAH4k... BotFather sends it right after you name your bot.",
        )
    name = await telegram_bot_name(context.http, token)
    await managed.set_telegram_token(context.repo, token)
    context.bot_names[token] = name
    context.telegram_token_changed.set()
    log.info("telegram.token_saved", bot=name)
    return name


@router.get("/alerts")
async def alerts_page(request: Request) -> Response:
    context = core.ctx(request)
    return await core.render(
        request,
        "alerts.html",
        {
            "nav": "alerts",
            "dests": await data.destinations(context, tz=await core.timezone(context)),
            "telegram": await telegram_setup(context),
            "providers": destinations.EMAIL_PROVIDERS,
            "security_modes": destinations.EMAIL_SECURITY,
            "ntfy_topic": await ntfy_topic(context, fresh_if_used=True),
        },
    )


# The ntfy name offered for a new place, kept until something uses it. Someone who reads
# it, installs ntfy and comes back to a reloaded page must still see the name they typed.
_NTFY_TOPIC_KEY = "ntfy_topic_offered"


async def ntfy_topic(context: core.WebContext, *, fresh_if_used: bool) -> str:
    """The ntfy name to offer, the same one on every load and after a restart.

    Setup keeps offering its name even once a place uses it (going back to the step must
    show the name the phone subscribed to). The Alerts page asks for a fresh one when a
    place already uses it, so a second phone place doesn't share the first one's topic.
    """
    repo = context.repo
    topic = await repo.get_state_value(_NTFY_TOPIC_KEY)
    if topic and fresh_if_used:
        used = {
            str(d.config.get("topic") or "")
            for d in await repo.list_destinations()
            if d.kind == "ntfy" and not data.is_removed(d)
        }
        if topic in used:
            topic = None
    if not topic:
        topic = destinations.new_ntfy_topic()
        await repo.set_state_value(_NTFY_TOPIC_KEY, topic)
    return topic


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.post("/destinations")
async def add_destination(request: Request) -> Response:
    context = core.ctx(request)
    assert context.http is not None  # opened by the app's lifespan
    form = await request.form()
    kind = str(form.get("kind") or "")
    try:
        name, config = destinations.build(kind, form)
        destinations.check(kind, config, context.settings, context.http)
    except InvalidInputError as exc:
        return JSONResponse({"ok": False, "field": exc.field, "error": exc.message}, 400)
    destination_id = await context.repo.add_destination(kind=kind, name=name, config=config)
    if _wants_json(request):
        return JSONResponse({"ok": True, "id": destination_id})
    return RedirectResponse(core.url("alerts"), status_code=303)


async def _destination(request: Request, destination_id: int) -> Destination:
    destination = await core.ctx(request).repo.get_destination(destination_id)
    if destination is None:
        raise HTTPException(status_code=404, detail="No such place for alerts.")
    return destination


@router.post("/destinations/{destination_id}/options")
async def set_options(request: Request, destination_id: int) -> Response:
    context = core.ctx(request)
    assert context.http is not None
    destination = await _destination(request, destination_id)
    form = await request.form()
    try:
        config = destinations.options(destination.kind, form, destination.config)
        destinations.check(destination.kind, config, context.settings, context.http)
    except InvalidInputError as exc:
        return JSONResponse({"ok": False, "field": exc.field, "error": exc.message}, 400)
    await context.repo.update_destination_config(destination_id, config)
    notify = bool(form.get("notify_status"))
    if notify != destination.notify_status:
        await context.repo.set_notify_status(destination_id, notify)
    return JSONResponse({"ok": True})


@router.get("/destinations/{destination_id}/preview")
async def preview(request: Request, destination_id: int) -> Response:
    """The card's "What it looks like": a sample alert with this place's own options."""
    context = core.ctx(request)
    destination = await _destination(request, destination_id)
    sample = sample_alert.look(destination.kind, destination.config, await _sample_tld(context))
    if sample is None:
        raise HTTPException(status_code=404, detail="No picture of this kind of alert.")
    return HTMLResponse(core.TEMPLATES.get_template("partials/sample_alert.html").render(a=sample))


async def _sample_tld(context: core.WebContext) -> str:
    """The site the sample pretends to be from: the one the searches use, so the alert
    speaks their language and currency."""
    queries = await context.repo.list_queries()
    return queries[0].tld if queries else "ie"


@router.post("/destinations/{destination_id}/test")
async def test_destination(request: Request, destination_id: int) -> JSONResponse:
    context = core.ctx(request)
    destination = await _destination(request, destination_id)
    result = await send_test(
        destination,
        settings=context.settings,
        telegram_token=await managed.telegram_token(context.settings, context.repo),
        tld=await _sample_tld(context),
        client=context.http,
    )
    if result.ok and destination.failure_count:
        await context.repo.reset_destination_failures(destination_id)
    await data.record_test(context.repo, destination_id, ok=result.ok, message=result.message)
    return JSONResponse({"ok": result.ok, "message": result.message, "detail": result.detail})


@router.post("/destinations/{destination_id}/delete")
async def remove_destination(request: Request, destination_id: int) -> Response:
    destination = await _destination(request, destination_id)
    await core.ctx(request).repo.deactivate_destination(destination.id, data.REMOVED)
    return core.redirect(core.url("alerts"), f"Removed {destination.name}.")


@router.post("/destinations/telegram/token")
async def set_telegram_token(request: Request) -> JSONResponse:
    context = core.ctx(request)
    form = await request.form()
    try:
        name = await save_telegram_token(context, str(form.get("telegram_token") or ""))
    except InvalidInputError as exc:
        return JSONResponse({"ok": False, "field": exc.field, "error": exc.message}, 400)
    return JSONResponse({"ok": True, **await telegram_setup(context), "bot": name})


@router.post("/destinations/telegram/token/remove")
async def remove_telegram_token(request: Request) -> Response:
    context = core.ctx(request)
    if managed.telegram_token_from_env(context.settings):
        raise HTTPException(
            status_code=400,
            detail="The bot token comes from VINTED_BOT_TELEGRAM_BOT_TOKEN in this copy's "
            "environment, so it's removed there.",
        )
    await managed.set_telegram_token(context.repo, None)
    context.telegram_token_changed.set()
    log.info("telegram.token_removed")
    return core.redirect(core.url("alerts"), "Removed the Telegram bot.")


@router.post("/destinations/telegram/pair")
async def start_pairing(request: Request) -> JSONResponse:
    context = core.ctx(request)
    if await managed.telegram_token(context.settings, context.repo) is None:
        return JSONResponse(
            {"error": "Telegram needs a bot first. Paste the token BotFather gave you."},
            status_code=400,
        )
    destination_id, code = await create_pairing(context.repo, "Telegram")
    bot = await bot_username(context)
    return JSONResponse(
        {
            "id": destination_id,
            "code": code,
            "command": f"/start {code}",
            "bot": bot,
            "link": f"https://t.me/{bot}?start={code}" if bot else None,
        }
    )


@router.get("/destinations/telegram/pair/{destination_id}")
async def pairing_status(request: Request, destination_id: int) -> JSONResponse:
    destination = await _destination(request, destination_id)
    chat = destination.config.get("chat_id")
    return JSONResponse({"connected": bool(chat), "chat": chat})


async def test_unsaved(
    context: core.WebContext, kind: str, name: str, config: dict[str, Any], tld: str
) -> dict[str, Any]:
    """Send a sample through a destination that is not stored yet (the setup's test step)."""
    destination = Destination(id=0, kind=kind, name=name, config=config)
    result = await send_test(
        destination,
        settings=context.settings,
        telegram_token=await managed.telegram_token(context.settings, context.repo),
        tld=tld,
        client=context.http,
    )
    return {"ok": result.ok, "message": result.message, "detail": result.detail}
