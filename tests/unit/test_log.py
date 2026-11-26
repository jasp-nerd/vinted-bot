"""Log lines carry the time on the reader's clock, and logging never stops the app."""

from __future__ import annotations

import io
import sys
from zoneinfo import ZoneInfo

import pytest
import structlog

from vinted_bot import log
from vinted_bot.log import local_timestamps


def test_log_timestamps_use_the_configured_time_zone_with_its_offset() -> None:
    stamp = local_timestamps(ZoneInfo("Asia/Kolkata"))

    event = stamp(None, "info", {"event": "app.starting"})

    assert event["timestamp"].endswith("+05:30")


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_the_windows_icon_starts_without_anywhere_to_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # pythonw, which the Windows icon runs, has no stderr at all.
    monkeypatch.setattr(sys, "stderr", None)
    before = structlog.get_config()
    try:
        log.configure()
        log.get_logger(__name__).info("app.starting")
    finally:
        structlog.configure(**before)


def test_a_windows_terminal_gets_plain_lines_without_colorama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "colorama", None)  # not installed

    # A real console, or NUL standing in for pythonw's missing stderr: both say "terminal".
    assert not log.colors_for(_Terminal())


def test_a_terminal_elsewhere_gets_colours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    assert log.colors_for(_Terminal())
    assert not log.colors_for(io.StringIO())
