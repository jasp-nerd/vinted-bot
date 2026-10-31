"""Noticing that the computer woke from sleep or moved to another network.

Either one makes the backoff the searches built up meaningless: a search that failed
for an hour because the laptop's lid was shut, or because the café's Wi-Fi was gone, is
now on a sixteen-minute wait for a network that is working again. Asyncio's timers make
it worse, since they run on the monotonic clock, which stands still while the computer
sleeps, so a wait set before sleeping resumes after it with all its time left.

So this looks every half minute at two things that cost nothing: the wall clock jumping
ahead of the monotonic one (the computer slept), and the address this computer would
send from changing (a new network; asking the OS sends no packet). Either sets the
shared event the searches wait on, and they check again promptly (engine/poller.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time

from vinted_bot.log import get_logger

log = get_logger(__name__)

CHECK_EVERY_S = 30.0

# The wall clock running this far ahead of the monotonic one between two looks means
# the computer slept. Well above any clock correction, well below any real nap.
SLEPT_AFTER_S = 120.0

# A documentation address stands for "the internet": the default route.
INTERNET = "192.0.2.1"


def local_address(towards: str = INTERNET) -> str | None:
    """The IPv4 address this computer would send from towards `towards`, or None
    without a route. Connecting a UDP socket only asks the routing table."""
    with (
        contextlib.suppress(OSError),
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe,
    ):
        probe.connect((towards, 9))
        return str(probe.getsockname()[0])
    return None


def woke_reason(slept_s: float, address_before: str | None, address_now: str | None) -> str | None:
    """Why the searches should check again now, or None for no reason."""
    if slept_s > SLEPT_AFTER_S:
        return "slept"
    # Losing the network is no reason: checks would only fail. Getting one back is.
    if address_now is not None and address_now != address_before:
        return "network_changed"
    return None


async def wait_for_any(seconds: float, *events: asyncio.Event) -> asyncio.Event | None:
    """Sleep up to `seconds`, ending early when one of `events` is set. Returns the first
    that was set, or None when the time ran out."""
    waiters = {asyncio.ensure_future(event.wait()): event for event in events}
    try:
        done, _ = await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
    return next((waiters[waiter] for waiter in done), None)


async def watch(stop: asyncio.Event, woke: asyncio.Event) -> None:
    """Set `woke` (briefly) whenever the computer woke up or changed networks."""
    wall, steady, address = time.time(), time.monotonic(), local_address()
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CHECK_EVERY_S)
        now_wall, now_steady, now_address = time.time(), time.monotonic(), local_address()
        slept_s = (now_wall - wall) - (now_steady - steady)
        if reason := woke_reason(slept_s, address, now_address):
            log.info("app.woke_up", reason=reason, slept_s=round(slept_s), address=now_address)
            # Everyone waiting now is woken; clearing straight away keeps it a signal
            # rather than a state.
            woke.set()
            woke.clear()
        wall, steady, address = now_wall, now_steady, now_address
