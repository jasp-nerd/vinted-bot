"""Signing in, when the dashboard has a password."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from vinted_sniper.web import core, security

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only ever send people back to a page of this dashboard after signing in."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


@router.get("/login")
async def login_form(request: Request, next: str | None = None) -> Response:
    if core.ctx(request).settings.web_auth_token is None:
        return RedirectResponse("/", status_code=303)
    return core.TEMPLATES.TemplateResponse(
        request, "login.html", {"error": None, "next": _safe_next(next)}
    )


@router.post("/login")
async def login(
    request: Request,
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    context = core.ctx(request)
    token = context.settings.web_auth_token
    if token is None:
        return RedirectResponse("/", status_code=303)
    address = request.client.host if request.client else "unknown"
    if wait_s := context.login_throttle.wait_s(address):
        minutes = max(1, round(wait_s / 60))
        return core.TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "error": f"Too many wrong passwords. Wait {minutes} min and try again.",
                "next": _safe_next(next),
            },
            status_code=429,
            headers={"Retry-After": str(wait_s)},
        )
    if not hmac.compare_digest(password.encode(), token.get_secret_value().encode()):
        context.login_throttle.failed(address)
        return core.TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "error": "That password didn't match. Check caps lock and try again.",
                "next": _safe_next(next),
            },
            status_code=401,
        )
    context.login_throttle.succeeded(address)
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        core.SESSION_COOKIE,
        await security.start_session(context.repo),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=security.SESSION_MAX_AGE_S,
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Sign out, revoking the session on the server too, not just in this browser."""
    await security.end_session(core.ctx(request).repo, request.cookies.get(core.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(core.SESSION_COOKIE)
    return response
