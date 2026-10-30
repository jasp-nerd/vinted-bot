"""When the dashboard asks for support. The rules are ported from Canvas Course Downloader."""

from __future__ import annotations

from dataclasses import replace

from vinted_bot.db.repo import SupportState
from vinted_bot.web import support

DAY = 24 * 60 * 60
NOW = 1_900_000_000
NEVER = SupportState(times_shown=0, last_shown_at=0, opted_out=False, last_alert_at=NOW - 60)


def test_it_shows_after_the_first_alert_since_many_people_only_set_up_once() -> None:
    assert support.card_for(NEVER, NOW) == 0


def test_it_never_asks_before_an_alert_has_reached_anyone() -> None:
    assert support.card_for(replace(NEVER, last_alert_at=None), NOW) is None


def test_it_shows_at_most_once_a_week_as_repeats_bring_in_less_each_time() -> None:
    shown = replace(NEVER, times_shown=1, last_shown_at=NOW - 6 * DAY)

    assert support.card_for(shown, NOW) is None


def test_a_week_later_it_shows_again_in_the_next_look() -> None:
    shown = replace(NEVER, times_shown=1, last_shown_at=NOW - 7 * DAY)

    assert support.card_for(shown, NOW) == 1


def test_a_week_later_it_still_waits_for_another_alert() -> None:
    """Only right after it was useful, not whenever someone happens to look."""
    shown = replace(NEVER, times_shown=1, last_shown_at=NOW - 8 * DAY, last_alert_at=NOW - 9 * DAY)

    assert support.card_for(shown, NOW) is None


def test_it_takes_turns_between_three_looks_so_it_stays_noticeable() -> None:
    looks = [support.card_for(replace(NEVER, times_shown=n), NOW) for n in range(4)]

    assert looks == [0, 1, 2, 0]


def test_only_dont_show_again_stops_it() -> None:
    assert support.card_for(replace(NEVER, opted_out=True), NOW) is None


def test_links_say_where_they_were_clicked() -> None:
    assert support.links("settings")["kofi"] == (
        "https://ko-fi.com/jaspnerd?utm_source=vinted-bot&utm_medium=settings"
    )
