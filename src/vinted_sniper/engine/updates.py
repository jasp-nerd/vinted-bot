"""Noticing that a newer release exists.

Once a day, one anonymous request to GitHub's public releases API, and the answer is stored
for the dashboard to show. Nothing is downloaded from here: installing a release is
self_update.py's job, which only ever runs uv or pipx against PyPI, and only uses the
version found here to decide whether to. People who would rather it never asked can
switch it off in the dashboard's settings.
"""

from __future__ import annotations

import re
import time

import httpx

from vinted_sniper import __version__
from vinted_sniper.db.repo import Repo
from vinted_sniper.log import get_logger

log = get_logger(__name__)

RELEASES_URL = "https://api.github.com/repos/jasp-nerd/vinted-sniper/releases/latest"
CHECK_EVERY_S = 86_400

RELEASE_PAGE = "https://github.com/jasp-nerd/vinted-sniper/releases/tag/v{version}"

_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)")


def _parts(version: str) -> tuple[int, ...] | None:
    match = _VERSION.match(version.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str | None, current: str = __version__) -> bool:
    """Whether `latest` is a later release than `current`. Unparseable means no."""
    if latest is None:
        return False
    theirs, ours = _parts(latest), _parts(current)
    return theirs is not None and ours is not None and theirs > ours


def release_notes_url(version: str) -> str:
    """The GitHub release page for a version: what changed, in the maintainer's words."""
    return RELEASE_PAGE.format(version=version.lstrip("v"))


async def check_for_update(repo: Repo, http: httpx.AsyncClient, *, now: int | None = None) -> None:
    """Ask GitHub for the latest release if the last answer is a day old and checks are on."""
    moment = now or int(time.time())
    if await repo.get_state_value("update_check") == "0":
        return
    last = await repo.get_state_value("update_checked_at")
    if last is not None and moment - int(last) < CHECK_EVERY_S:
        return
    # Recorded before asking, so a GitHub outage costs one request a day, not one an hour.
    await repo.set_state_value("update_checked_at", str(moment))
    try:
        response = await http.get(
            RELEASES_URL, headers={"Accept": "application/vnd.github+json"}, timeout=10.0
        )
    except httpx.HTTPError as exc:
        log.info("updates.check_failed", error=type(exc).__name__)
        return
    if response.is_error:
        # 404 until the first release is published; nothing to report either way.
        log.info("updates.check_failed", status=response.status_code)
        return
    try:
        release = response.json()
    except ValueError:
        log.info("updates.check_failed", error="response was not JSON")
        return
    tag = release.get("tag_name") if isinstance(release, dict) else None
    if isinstance(tag, str) and _parts(tag) is not None:
        await repo.set_latest_version(tag.lstrip("v"))
        if is_newer(tag):
            log.info("updates.available", current=__version__, latest=tag)
