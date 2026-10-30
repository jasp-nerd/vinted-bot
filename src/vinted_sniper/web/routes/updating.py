"""The "Update now" button and the progress it shows.

The button posts here, the upgrade runs in the background (engine/self_update.py), and
the page polls the status until it is done, or until a new process answers after the
restart. Like every other change, the POST passes the same-origin check in server.py, so
a page elsewhere cannot make the dashboard update itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vinted_sniper.engine import self_update
from vinted_sniper.web import core

router = APIRouter()


async def _status(request: Request) -> dict[str, object]:
    context = core.ctx(request)
    last = await self_update.last_outcome(context.repo)
    return {**context.updater.status(), "last": last.as_dict() if last else None}


@router.get("/api/update")
async def update_status(request: Request) -> JSONResponse:
    return JSONResponse(await _status(request), headers={"Cache-Control": "no-store"})


@router.post("/api/update")
async def update_now(request: Request) -> JSONResponse:
    try:
        await core.ctx(request).updater.start()
    except self_update.UpdateRefusedError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    return JSONResponse({"ok": True, **await _status(request)}, status_code=202)
