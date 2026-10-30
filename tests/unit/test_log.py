"""Log lines carry the time on the reader's clock."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from vinted_bot.log import local_timestamps


def test_log_timestamps_use_the_configured_time_zone_with_its_offset() -> None:
    stamp = local_timestamps(ZoneInfo("Asia/Kolkata"))

    event = stamp(None, "info", {"event": "app.starting"})

    assert event["timestamp"].endswith("+05:30")
