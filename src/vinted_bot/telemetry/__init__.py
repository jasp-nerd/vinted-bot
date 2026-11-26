"""Usage statistics and error reports, as docs/telemetry.md describes them.

Any part of the app records through the functions here: `count` and `sample` add to the
day's totals, `event` notes something that happened, `capture_exception` reports an
error. Nothing is kept or sent until `service.Telemetry` switches recording on, and it
only does that when sending is allowed (see `service.allowed`), so calling these is free
in tests, in development and for anyone who turned it off.

Two rules keep what leaves the computer small and predictable:

- **Names and properties are ours, never the user's.** Event names, counter names and
  property values come from this code or from fixed lists (a route's template, a channel's
  kind, a filter's name), never from what someone typed: no search terms, listing titles,
  addresses, tokens or URLs.
- **Error text goes through `scrub.scrub`** before it is kept, because an exception's
  message can quote a URL with a token in it.
"""

from __future__ import annotations

from vinted_bot.telemetry.recorder import (
    capture_exception,
    capture_message,
    count,
    event,
    milestone,
    sample,
)

__all__ = [
    "capture_exception",
    "capture_message",
    "count",
    "event",
    "milestone",
    "sample",
]
