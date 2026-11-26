"""Keeping a Mac awake while it's plugged in, for as long as vinted-bot runs.

Alerts stop while a Mac sleeps. macOS's own `caffeinate -s` holds off sleep while the Mac
is on power (a closed MacBook lid still sleeps), and `-w` ends that the moment this
process does, so a crash never leaves the Mac unable to sleep. It used to be fixed in the
LaunchAgent at install time; here Settings switches it while the app runs. On by default
for copies the installer set up, off for anyone running it by hand.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys

from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.log import get_logger

log = get_logger(__name__)

KEY = "keep_awake"
CHECK_EVERY_S = 5.0


def available(platform: str = sys.platform) -> bool:
    return platform == "darwin" and shutil.which("caffeinate") is not None


async def wanted(repo: Repo, settings: Settings) -> bool:
    value = await repo.get_state_value(KEY)
    if value is None:
        return settings.supervised == "launchd"
    return value == "1"


async def set_wanted(repo: Repo, on: bool) -> None:
    await repo.set_state_value(KEY, "1" if on else "0")


async def keep(repo: Repo, settings: Settings, stop: asyncio.Event) -> None:
    """Hold the Mac awake while the setting says so, following it as it changes."""
    if not available():
        return
    holder: asyncio.subprocess.Process | None = None
    try:
        while not stop.is_set():
            want = await wanted(repo, settings)
            if want and (holder is None or holder.returncode is not None):
                holder = await asyncio.create_subprocess_exec(
                    "caffeinate",
                    "-s",
                    "-w",
                    str(os.getpid()),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                log.info("awake.holding")
            elif not want and holder is not None:
                holder.terminate()
                holder = None
                log.info("awake.released")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=CHECK_EVERY_S)
    finally:
        if holder is not None and holder.returncode is None:
            holder.terminate()
