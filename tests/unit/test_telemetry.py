"""Usage statistics: what is kept out of reports, and how recording behaves."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import structlog

from vinted_bot import telemetry
from vinted_bot.telemetry import errors, recorder
from vinted_bot.telemetry.scrub import MAX_LENGTH, scrub

# --- Scrubbing --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kept", "gone"),
    [
        (
            "POST https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/sendMessage",
            "api.telegram.org",
            "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        ),
        (
            "token 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw was refused",  # gitleaks:allow
            "<token>",
            "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        ),
        (
            "404 for https://discord.com/api/webhooks/1234/abcdefghijklmnopqrstuvwxyz0123456789ABCD",
            "discord.com",
            "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
        ),
        ("proxy http://anna:hunter2@203.0.113.9:8080 refused", "<url>", "hunter2"),
        ("could not reach https://ntfy.my-house.example/alerts", "<url>", "my-house"),
        ("mail to anna.jansen@example.org bounced", "<email>", "anna.jansen"),
        ("connect to 192.168.1.20:8000 failed", "<ip>", "192.168.1.20"),
        ("bad key 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822c", "<secret>", "9f86d081884c"),
        ("search 'nike air max 90' is invalid", "'<text>'", "nike air"),
    ],
)
def test_scrub_removes_what_could_identify_someone(text: str, kept: str, gone: str) -> None:
    cleaned = scrub(text)

    assert kept in cleaned
    assert gone not in cleaned


def test_scrub_keeps_what_says_what_went_wrong() -> None:
    assert scrub("KeyError: 'search_text'") == "KeyError: 'search_text'"
    assert (
        scrub("vinted.fr refused the request with 403") == "vinted.fr refused the request with 403"
    )
    assert scrub("checked at 12:30:45") == "checked at 12:30:45"


def test_scrub_hides_the_home_folder_and_user_name() -> None:
    home = Path("/Users/anna")

    assert scrub("cannot open /Users/anna/data/app.db", home=home) == "cannot open ~/data/app.db"
    assert "bob" not in scrub("cannot open /home/bob/app.db", home=home)
    assert "carol" not in scrub(r"cannot open C:\Users\carol\app.db", home=home)


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("connect to 2a02:a45:1b2c::1f4 failed", "2a02"),
        ("fe80::1%en0 refused", "fe80"),
        ("cannot open /volume1/homes/jane/vinted/app.db", "jane"),
        (r"cannot open C:\Users\Jane Doe\AppData\app.db", "Jane"),
        ("proxy bob:pa55@proxy.example.com:3128 refused", "bob"),
        ("Failed to connect to gate.smartproxy.com port 7000", "smartproxy"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==", "dXNlcjpw"),
        ("https%3A%2F%2Fdiscord.com%2Fapi%2Fwebhooks%2F123%2Fsecret", "secret"),
        ("user%40gmail.com", "user"),
        ("invalid literal for int() with base 10: 'jordan'", "jordan"),
        ("vinted.fr did not return JSON: '<html>Blocked 81.2.3.4</html>'", "Blocked"),
    ],
)
def test_scrub_catches_what_slipped_through_before(text: str, gone: str) -> None:
    assert gone not in scrub(text, home=Path("/Users/anna"))


def test_scrub_cuts_long_text() -> None:
    assert len(scrub("x " * 1000)) == MAX_LENGTH


# --- Exceptions -------------------------------------------------------------------------


def _raise_from_here() -> None:
    try:
        int("not a number")
    except ValueError as exc:
        raise RuntimeError("parsing failed") from exc


def test_an_exception_becomes_frames_without_paths_from_the_disk() -> None:
    with pytest.raises(RuntimeError) as caught:
        _raise_from_here()

    listed = errors.exception_list(caught.value, handled=True)

    assert [e["type"] for e in listed] == ["RuntimeError", "ValueError"]
    frame = listed[0]["stacktrace"]["frames"][-1]
    assert frame["function"] == "_raise_from_here"
    assert frame["filename"] == "test_telemetry.py"
    assert not frame["in_app"]
    assert str(Path.home()) not in str(listed)


def test_frames_from_the_package_carry_their_line_of_code() -> None:
    with pytest.raises(TypeError) as caught:
        scrub(None)  # type: ignore[arg-type]

    frames = errors.exception_list(caught.value, handled=True)[0]["stacktrace"]["frames"]
    ours = [f for f in frames if f["in_app"]]

    assert ours, frames
    assert ours[-1]["filename"] == "vinted_bot/telemetry/scrub.py"
    assert ours[-1]["context_line"]


# --- Recording --------------------------------------------------------------------------


def test_nothing_is_kept_until_recording_is_switched_on() -> None:
    telemetry.count("checks_ok")
    telemetry.event("page_viewed", page="/")
    telemetry.capture_message("poll.malformed_response", "bad")

    assert recorder.take_events() == []
    assert recorder.take_totals() == ({}, {})


def test_counts_and_measurements_add_up_to_a_daily_summary() -> None:
    recorder.activate()
    telemetry.count("checks_ok", 3)
    telemetry.count("checks_ok")
    for ms in (100, 200, 300, 400):
        telemetry.sample("vinted_search_ms", ms)

    counters, timings = recorder.take_totals()

    assert counters == {"checks_ok": 4}
    assert timings["vinted_search_ms"]["count"] == 4
    assert timings["vinted_search_ms"]["sum"] == 1000, "exact, for averages across installs"
    assert timings["vinted_search_ms"]["max"] == 400
    assert recorder.take_totals() == ({}, {})


def test_a_form_that_saves_at_every_change_is_one_use() -> None:
    recorder.activate()
    for _ in range(5):
        telemetry.event("feature_used", feature="/settings", once_per_s=600, key="/settings")

    assert len(recorder.take_events()) == 1


def test_the_same_error_is_reported_once_an_hour_and_the_rest_counted() -> None:
    recorder.activate()
    for _ in range(3):
        try:
            _raise_from_here()
        except RuntimeError as exc:
            telemetry.capture_exception(exc, where="test")

    reports = recorder.take_events()
    counters, _ = recorder.take_totals()

    assert len(reports) == 1
    assert reports[0].name == "$exception"
    assert counters["errors_repeated"] == 2


def test_switching_off_forgets_what_was_waiting() -> None:
    recorder.activate()
    telemetry.event("page_viewed", page="/")
    telemetry.count("checks_ok")

    recorder.deactivate()

    assert recorder.take_events() == []
    assert recorder.peek_counters() == {}


# --- From the log -----------------------------------------------------------------------


@pytest.fixture
def logged() -> Any:
    """A logger with the app's level filter and processor, writing nowhere."""
    return structlog.wrap_logger(
        structlog.ReturnLogger(),
        processors=[
            structlog.stdlib.add_log_level,
            recorder.log_processor,
            structlog.processors.KeyValueRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def test_warnings_are_counted_by_name_and_errors_reported(logged: Any) -> None:
    recorder.activate()

    logged.info("poll.new_items", count=2)
    logged.warning("poll.rate_limited", retry_in_s=30)
    logged.error("poll.malformed_response", error="expected a list at 'items'")
    try:
        _raise_from_here()
    except RuntimeError:
        logged.exception("poller.crashed", error="parsing failed")

    reports = recorder.take_events()
    counters, _ = recorder.take_totals()

    assert counters["log:poll.rate_limited"] == 1
    assert "log:poll.new_items" not in counters
    assert [r.properties["where"] for r in reports] == ["poll.malformed_response", "poller.crashed"]
    assert reports[0].properties["$exception_list"][0]["type"] == "poll.malformed_response"
    assert reports[1].properties["$exception_list"][0]["type"] == "RuntimeError"
