"""Noticing sleep and network changes, and what a search does about them."""

from __future__ import annotations

import asyncio

import pytest

from vinted_bot.engine.wakeups import wait_for_any, woke_reason


def test_the_wall_clock_running_ahead_means_the_computer_slept() -> None:
    assert woke_reason(3 * 3600, "192.168.1.20", "192.168.1.20") == "slept"


def test_a_new_address_means_a_new_network() -> None:
    assert woke_reason(0, "192.168.1.20", "10.0.0.5") == "network_changed"


def test_a_network_coming_back_is_a_reason_to_check() -> None:
    assert woke_reason(0, None, "192.168.1.20") == "network_changed"


@pytest.mark.parametrize(("before", "now"), [("192.168.1.20", "192.168.1.20"), ("10.0.0.5", None)])
def test_nothing_changing_or_losing_the_network_is_no_reason(before: str, now: None) -> None:
    assert woke_reason(2, before, now) is None


async def test_waiting_says_which_event_ended_it() -> None:
    first, second = asyncio.Event(), asyncio.Event()
    second.set()

    assert await wait_for_any(5, first, second) is second


async def test_waiting_runs_out_with_nothing_set() -> None:
    assert await wait_for_any(0.01, asyncio.Event()) is None
