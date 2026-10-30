"""Signing in, when the dashboard has a password."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from vinted_sniper.web import core

router = APIRouter()

# Thirty days: a password is asked for once per browser, not once per visit.
SESSION_MAX_AGE_S = 30 * 86_400


def _safe_next(target: str | None) -> str:
    """Only ever send people back to a page of this dashboard after signing in."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


@router.get("/login")
async def login_form(request: Request, next: str | None = None) -> Response:  # noqa: A002
    if core.ctx(request).settings.web_auth_token is None:
        return RedirectResponse("/", status_code=303)
    return core.TEMPLATES.TemplateResponse(
        request, "login.html", {"error": None, "next": _safe_next(next)}
    )


@router.post("/login")
async def login(
    request: Request,
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",  # noqa: A002
) -> Response:
    token = core.ctx(request).settings.web_auth_token
    if token is None:
        return RedirectResponse("/", status_code=303)
    if not hmac.compare_digest(password.encode(), token.get_secret_value().encode()):
        return core.TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {
                "error": "That password didn't match. Check caps lock and try again.",
                "next": _safe_next(next),
            },
            status_code=401,
        )
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        core.SESSION_COOKIE,
        core.session_value(token),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=SESSION_MAX_AGE_S,
    )
    return response


@router.post("/logout")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(core.SESSION_COOKIE)
    return response
