"""Pacing: staying inside what the platforms allow before they have to say so."""

from __future__ import annotations

import pytest

from vinted_sniper.deliver.ratelimit import Gate, TokenBucket

# --- Pacing ------------------------------------------------------------------------


async def test_the_bucket_spaces_requests_out() -> None:
    clock = {"now": 0.0}
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["now"] += seconds

    bucket = TokenBucket(2.0, capacity=1.0, clock=lambda: clock["now"], sleep=sleep)

    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()

    assert slept, "a burst past the capacity has to wait"
    assert sum(slept) == pytest.approx(1.0, abs=0.01), "two per second means half a second each"


def test_a_closed_gate_reopens_on_its_own() -> None:
    clock = {"now": 100.0}
    gate = Gate(clock=lambda: clock["now"])

    assert gate.wait_s == 0.0
    gate.close_for(5.0)
    assert gate.wait_s == pytest.approx(5.0)

    clock["now"] += 5.1
    assert gate.wait_s == 0.0
