"""Who can open the dashboard: its password, and phone access.

Both used to mean editing a settings file and restarting. Here a password is set,
changed or removed in Settings, and one switch lets the phone and other devices on the
same network in: the server moves to every network interface inside the running app
(web/server.py), with no restart.

Two rules hold whatever is clicked: other devices are only let in while there is a
password, and the password can only be removed while they are not. The environment
(VINTED_BOT_WEB_AUTH_TOKEN, VINTED_BOT_WEB_HOST) still wins, and in a container the port
mapping decides who can connect, so the switch is not offered there.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from vinted_bot import managed
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.log import get_logger
from vinted_bot.web import core, security
from vinted_bot.web.routes.auth import sign_in

log = get_logger(__name__)
router = APIRouter()


def _refused(field: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "field": field, "error": message}, status_code=status)


async def _current_password_ok(request: Request, typed: str) -> bool:
    """Whether `typed` is the password now, counting a wrong one like a wrong sign-in."""
    context = core.ctx(request)
    address = request.client.host if request.client else "unknown"
    if context.login_throttle.wait_s(address):
        return False
    if await security.password_matches(context.settings, context.repo, typed):
        return True
    context.login_throttle.failed(address)
    return False


async def _set_new_password(request: Request, typed: str, response: JSONResponse) -> None:
    """Store a new password and keep this browser signed in under it."""
    context = core.ctx(request)
    await security.set_password(context.repo, security.check_new_password(typed))
    sign_in(request, response, await security.start_session(context.repo))


_FROM_ENV = (
    "This dashboard's password comes from VINTED_BOT_WEB_AUTH_TOKEN in its environment, "
    "so it's changed there."
)


@router.post("/settings/password")
async def set_password(request: Request) -> Response:
    """Set a first password, or change it, which needs the current one."""
    context = core.ctx(request)
    if security.password_from_env(context.settings):
        return _refused("new_password", _FROM_ENV)
    form = await request.form()
    if await security.password_required(context.settings, context.repo):
        current = str(form.get("current_password") or "")
        if not await _current_password_ok(request, current):
            return _refused("current_password", "That isn't the current password.", 403)
    response = JSONResponse({"ok": True})
    try:
        await _set_new_password(request, str(form.get("new_password") or ""), response)
    except InvalidInputError as exc:
        return _refused(exc.field, exc.message)
    log.info("web.password_set")
    return response


@router.post("/settings/password/remove")
async def remove_password(request: Request) -> Response:
    context = core.ctx(request)
    if security.password_from_env(context.settings):
        return _refused("current_password", _FROM_ENV)
    access = await security.access(context.settings, context.repo)
    if not access.loopback:
        return _refused(
            "current_password",
            "Other devices can open this page, so it keeps its password. Turn off "
            '"Allow my phone and other devices" first.',
        )
    form = await request.form()
    if not await _current_password_ok(request, str(form.get("current_password") or "")):
        return _refused("current_password", "That isn't the current password.", 403)
    await security.set_password(context.repo, None)
    log.info("web.password_removed")
    response = JSONResponse({"ok": True})
    response.delete_cookie(core.SESSION_COOKIE)
    return response


_NO_PRIVATE_NETWORK = (
    "This computer isn't on a home or office network right now: the network it's on gives "
    "it a public internet address (common at universities and offices), or none at all. "
    "Phone access there would put this page on the internet, so it stays off. Try again "
    "on your home Wi-Fi, or install Tailscale (free) on this computer and your phone to "
    "reach it from anywhere."
)


@router.post("/settings/phone")
async def phone_access(request: Request) -> Response:
    """Let other devices in, or keep the dashboard to this computer.

    Turning it on without a password needs one in the same request, so there is never
    a moment when the dashboard is open to the network without one.
    """
    context = core.ctx(request)
    access = await security.access(context.settings, context.repo)
    if access.container:
        return _refused(
            "phone",
            "In Docker the port mapping decides who can open this page. The settings "
            "page says how to change it.",
        )
    if access.host_from_env:
        return _refused(
            "phone",
            f"VINTED_BOT_WEB_HOST is set to {context.settings.web_host} in this copy's "
            "environment, so that's where it listens.",
        )
    form = await request.form()
    allow = form.get("allow") == "1"
    if allow and not context.settings.web_public_url and not core.lan_addresses():
        return _refused("phone", _NO_PRIVATE_NETWORK)
    response = JSONResponse({"ok": True})
    if allow and not access.password:
        try:
            await _set_new_password(request, str(form.get("new_password") or ""), response)
        except InvalidInputError as exc:
            return _refused(exc.field, exc.message)
        log.info("web.password_set")
    await managed.set_phone_access(context.repo, allow)
    log.info("web.phone_access", allowed=allow)
    context.listen_error = None
    context.rebind.set()
    return response


@router.get("/api/access")
async def access_status(request: Request) -> JSONResponse:
    """Where the dashboard listens now, for the page to wait out a move."""
    context = core.ctx(request)
    access = await security.access(context.settings, context.repo)
    body: dict[str, Any] = {
        "listening_on": context.listening_on,
        "wanted": access.host,
        "addresses": core.phone_addresses(context.settings, access),
        "error": context.listen_error,
    }
    return JSONResponse(body)
