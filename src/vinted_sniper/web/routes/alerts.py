"""Where alerts go: the destination cards, adding one, testing one, Telegram pairing.

Telegram is connected from here, with no command line: the dashboard creates a pairing
code, the person sends `/start <code>` to their bot (a link does it in one tap), and the
running bot claims the code and records the chat. The page polls until it has.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from vinted_sniper.botctl.telegram_bot import create_pairing
from vinted_sniper.db.repo import Destination
from vinted_sniper.deliver import send_test
from vinted_sniper.engine.validation import InvalidInputError
from vinted_sniper.log import get_logger
from vinted_sniper.web import core, data, destinations

log = get_logger(__name__)
router = APIRouter()

_TELEGRAM_API = "https://api.telegram.org"


async def bot_username(context: core.WebContext) -> str | None:
    """The configured bot's @name, asked of Telegram once and remembered.

    Shown so people know which bot to message. A failed lookup is remembered too: the
    pairing still works with the code alone, so there is no reason to keep asking.
    """
    token = context.settings.telegram_bot_token
    if token is None or context.http is None:
        return None
    if not context.bot_checked:
        context.bot_checked = True
        try:
            response = await context.http.get(
                f"{_TELEGRAM_API}/bot{token.get_secret_value()}/getMe", timeout=10.0
            )
            result = response.json().get("result") or {}
            context.bot_username = result.get("username")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            # Never log the URL: it contains the bot token.
            log.info("telegram.getme_failed", error=type(exc).__name__)
    return context.bot_username


async def telegram_setup(context: core.WebContext) -> dict[str, Any]:
    return {
        "configured": context.settings.telegram_bot_token is not None,
        "bot": await bot_username(context),
    }


@router.get("/alerts")
async def alerts_page(request: Request) -> Response:
    context = core.ctx(request)
    return await core.render(
        request,
        "alerts.html",
        {
            "nav": "alerts",
            "dests": await data.destinations(context),
            "telegram": await telegram_setup(context),
            "apprise": destinations.apprise_installed(),
            "providers": destinations.EMAIL_PROVIDERS,
            "ntfy_topic": destinations.new_ntfy_topic(),
        },
    )


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.post("/destinations")
async def add_destination(request: Request) -> Response:
    context = core.ctx(request)
    assert context.http is not None  # opened by the app's lifespan
    form = await request.form()
    kind = str(form.get("kind") or "")
    try:
        name, config = destinations.build(kind, form)  # type: ignore[arg-type]
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
        config = destinations.options(destination.kind, form, destination.config)  # type: ignore[arg-type]
        destinations.check(destination.kind, config, context.settings, context.http)
    except InvalidInputError as exc:
        return JSONResponse({"ok": False, "field": exc.field, "error": exc.message}, 400)
    await context.repo.update_destination_config(destination_id, config)
    return JSONResponse({"ok": True})


@router.post("/destinations/{destination_id}/test")
async def test_destination(request: Request, destination_id: int) -> JSONResponse:
    context = core.ctx(request)
    destination = await _destination(request, destination_id)
    queries = await context.repo.list_queries()
    result = await send_test(
        destination,
        settings=context.settings,
        tld=queries[0].tld if queries else "ie",
        client=context.http,
    )
    if result.ok and destination.failure_count:
        await context.repo.reset_destination_failures(destination_id)
    return JSONResponse({"ok": result.ok, "message": result.message, "detail": result.detail})


@router.post("/destinations/{destination_id}/delete")
async def remove_destination(request: Request, destination_id: int) -> Response:
    destination = await _destination(request, destination_id)
    await core.ctx(request).repo.deactivate_destination(destination.id, data.REMOVED)
    response = RedirectResponse(core.url("alerts"), status_code=303)
    response.set_cookie("vs_toast", f"Removed {destination.name}.", max_age=30, samesite="lax")
    return response


@router.post("/destinations/telegram/pair")
async def start_pairing(request: Request) -> JSONResponse:
    context = core.ctx(request)
    if context.settings.telegram_bot_token is None:
        return JSONResponse(
            {
                "error": "Telegram needs a bot first. Add VINTED_SNIPER_TELEGRAM_BOT_TOKEN "
                "to the settings file and restart vinted-sniper."
            },
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
    result = await send_test(destination, settings=context.settings, tld=tld, client=context.http)
    return {"ok": result.ok, "message": result.message, "detail": result.detail}
