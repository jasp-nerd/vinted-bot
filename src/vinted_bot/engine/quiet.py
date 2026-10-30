"""Quiet hours: when a search should not wake anyone up.

A window is two wall-clock times in the app's time zone. When the start is later than the
end the window runs through midnight (23:00 to 07:00), which is the case people actually
want and the one that is easy to get wrong.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta


def _clock(hhmm: str) -> time:
    hours, minutes = hhmm.split(":")
    return time(int(hours), int(minutes))


def window_end(start: str | None, end: str | None, now: datetime) -> datetime | None:
    """If `now` falls inside the window, when the window ends; otherwise None.

    `now` must carry the app's time zone, and the end comes back in it. Times that a
    daylight-saving jump skips are resolved the way zoneinfo resolves them.
    """
    if start is None or end is None:
        return None
    begins, ends = _clock(start), _clock(end)
    current = now.timetz().replace(tzinfo=None)

    # A start later than the end means the window runs through midnight.
    inside = begins <= current < ends if begins < ends else current >= begins or current < ends
    if not inside:
        return None

    end_day = now.date()
    if current >= ends:
        end_day += timedelta(days=1)
    return datetime.combine(end_day, ends, tzinfo=now.tzinfo)
