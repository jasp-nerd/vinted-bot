"""Signing in, when the dashboard has a password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from vinted_bot.config import in_container
from vinted_bot.web import core, security

router = APIRouter()


def _safe_next(target: str | None) -> str:
    """Only ever send people back to a page of this dashboard after signing in."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return "/"


def sign_in(request: Request, response: Response, token: str) -> None:
    """Give this browser the session cookie for `token` (security.start_session)."""
    response.set_cookie(
        core.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=security.SESSION_MAX_AGE_S,
    )


def _form(request: Request, error: str | None, next: str, status_code: int = 200) -> Response:
    context = core.ctx(request)
    return core.TEMPLATES.TemplateResponse(
        request,
        "login.html",
        {
            "error": error,
            "next": _safe_next(next),
            "from_env": security.password_from_env(context.settings),
            "container": in_container(),
        },
        status_code=status_code,
    )


@router.get("/login")
async def login_form(request: Request, next: str | None = None) -> Response:
    context = core.ctx(request)
    if not await security.password_required(context.settings, context.repo):
        return RedirectResponse("/", status_code=303)
    return _form(request, None, next or "/")


@router.post("/login")
async def login(
    request: Request,
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",
) -> Response:
    context = core.ctx(request)
    if not await security.password_required(context.settings, context.repo):
        return RedirectResponse("/", status_code=303)
    address = request.client.host if request.client else "unknown"
    if wait_s := context.login_throttle.wait_s(address):
        minutes = max(1, round(wait_s / 60))
        response = _form(
            request,
            f"Too many wrong passwords. Wait {minutes} min and try again.",
            next,
            status_code=429,
        )
        response.headers["Retry-After"] = str(wait_s)
        return response
    if not await security.password_matches(context.settings, context.repo, password):
        context.login_throttle.failed(address)
        return _form(
            request,
            "That password didn't match. Check caps lock and try again.",
            next,
            status_code=401,
        )
    context.login_throttle.succeeded(address)
    response = RedirectResponse(_safe_next(next), status_code=303)
    sign_in(request, response, await security.start_session(context.repo))
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Sign out, revoking the session on the server too, not just in this browser."""
    await security.end_session(core.ctx(request).repo, request.cookies.get(core.SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(core.SESSION_COOKIE)
    return response
