from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vinted_sniper.engine.quiet import window_end

PARIS = ZoneInfo("Europe/Paris")


def at(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=PARIS)


def test_outside_the_window_there_is_no_end() -> None:
    assert window_end("23:00", "07:00", at(12)) is None


def test_late_evening_in_an_overnight_window_ends_tomorrow_morning() -> None:
    assert window_end("23:00", "07:00", at(23, 30)) == at(7, day=11)


def test_small_hours_in_an_overnight_window_end_this_morning() -> None:
    assert window_end("23:00", "07:00", at(2)) == at(7)


def test_a_daytime_window_ends_the_same_day() -> None:
    assert window_end("13:00", "15:00", at(14)) == at(15)


def test_the_end_minute_itself_is_outside() -> None:
    assert window_end("23:00", "07:00", at(7)) is None


def test_no_window_set_means_never_quiet() -> None:
    assert window_end(None, None, at(3)) is None
