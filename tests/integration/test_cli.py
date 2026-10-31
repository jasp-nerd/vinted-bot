"""The command line's commands, parsed the way a person types them, against a throwaway
database. They call the command handlers rather than `main`, which also configures
logging for the whole process and would leave every later test writing to a closed stream.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import ScriptedTransport
from vinted_bot import cli
from vinted_bot.config import Settings
from vinted_bot.db import Database, apply_pending
from vinted_bot.db.repo import Query, Repo
from vinted_bot.vinted.models import Item
from vinted_bot.vinted.transport import TransportSession

URL = "https://www.vinted.fr/catalog?search_text=barbour"


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli.db"
    monkeypatch.setenv("VINTED_BOT_DB_PATH", str(path))
    return path


def run(*argv: str) -> int:
    args = cli.build_parser().parse_args(argv)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    handler = {"watch": cli._cmd_watch, "export": cli._cmd_export}[args.command]
    return asyncio.run(handler(settings, args))


def stored_queries(path: Path) -> list[Query]:
    async def read() -> list[Query]:
        async with Database(path) as db:
            await apply_pending(db)
            return await Repo(db).list_queries()

    return asyncio.run(read())


def test_watch_takes_the_new_filters(db_path: Path) -> None:
    code = run(
        "watch",
        URL,
        "--max-price",
        "12,50",
        "--include",
        "jacket|veste",
        "--countries",
        "fr,be",
        "--quiet",
        "23:00-07:00",
        "--also-on",
        "be",
        "--deal",
        "20",
    )

    (query,) = stored_queries(db_path)
    assert code == 0
    assert (str(query.max_total_price), query.include_terms, query.countries) == (
        "12.50",
        ["jacket|veste"],
        ["FR", "BE"],
    )
    assert (query.quiet_start, query.quiet_end, query.extra_tlds, query.deal_only_pct) == (
        "23:00",
        "07:00",
        ["be"],
        20,
    )


def test_watch_refuses_a_broken_regex_without_storing_anything(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run("watch", URL, "--regex", "jacket (")

    assert code == 2
    assert "does not work" in capsys.readouterr().err
    assert stored_queries(db_path) == []


def test_watch_refuses_destination_ids_that_are_not_numbers(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--to 1,a used to end in a traceback."""
    assert run("watch", URL, "--to", "1,a") == 2
    assert "--to takes destination ids" in capsys.readouterr().err


def test_export_writes_found_listings_as_json(db_path: Path, tmp_path: Path) -> None:
    async def setup() -> None:
        async with Database(db_path) as db:
            await apply_pending(db)
            repo = Repo(db)
            query_id = await repo.add_query(
                name="b", url=URL, tld="fr", params={}, poll_interval_s=60
            )
            query = await repo.get_query(query_id)
            assert query is not None
            await repo.record_new_items(
                query, [Item(item_id=5, tld="fr", title="Barbour", url="https://x/5")], []
            )

    asyncio.run(setup())
    out = tmp_path / "found.json"

    assert run("export", "--format", "json", "--output", str(out)) == 0

    assert [row["item_id"] for row in json.loads(out.read_text())] == [5]


def test_a_bad_setting_ends_with_a_sentence_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VINTED_BOT_WEB_PORT", "abc")

    code = cli.main(["status"])

    assert (code, "VINTED_BOT_WEB_PORT is set to 'abc'" in capsys.readouterr().err) == (2, True)


def test_watching_a_link_twice_names_the_search_that_has_it(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run("watch", URL, "--name", "Barbour")

    code = run("watch", URL)

    assert (code, "“Barbour”" in capsys.readouterr().err) == (1, True)


def run_command(*argv: str) -> int:
    args = cli.build_parser().parse_args(argv)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    match args.command:
        case "destination":
            return asyncio.run(cli._cmd_destination(settings, args))
        case "backup":
            return asyncio.run(cli._cmd_backup(settings, args.file))
        case _:
            return asyncio.run(cli._cmd_check(settings, args.url))


def stored_destinations(path: Path) -> list[dict[str, object]]:
    async def read() -> list[dict[str, object]]:
        async with Database(path) as db:
            await apply_pending(db)
            return [d.config for d in await Repo(db).list_destinations()]

    return asyncio.run(read())


def test_a_discord_destination_that_is_not_a_webhook_link_is_refused(db_path: Path) -> None:
    """It used to be stored, exit 0, and switched off in the background later."""
    assert run_command("destination", "discord", "notaurl") == 2
    assert stored_destinations(db_path) == []


def test_a_full_ntfy_topic_address_is_kept_as_an_address(db_path: Path) -> None:
    """Stored as a topic, it went to ntfy.sh/https://... instead of the person's server."""
    run_command("destination", "ntfy", "https://ntfy.example.org/deals")

    assert stored_destinations(db_path) == [{"url": "https://ntfy.example.org/deals"}]


def test_an_apprise_destination_can_be_added_from_the_command_line(db_path: Path) -> None:
    run_command("destination", "apprise", "json://localhost/hook")

    assert stored_destinations(db_path) == [{"urls": ["json://localhost/hook"]}]


def test_a_telegram_chat_id_must_be_a_number(db_path: Path) -> None:
    assert run_command("destination", "telegram", "@mychannel") == 2


def test_a_backup_holds_what_is_still_in_the_write_ahead_log(db_path: Path, tmp_path: Path) -> None:
    """Copying app.db by hand while the app ran gave an empty database."""
    copy = tmp_path / "backup.db"

    async def while_the_app_runs() -> int:
        async with Database(db_path) as running:
            await apply_pending(running)
            await Repo(running).add_query(
                name="b", url=URL, tld="fr", params={"search_text": "b"}, poll_interval_s=60
            )
            settings = Settings(_env_file=None)  # type: ignore[call-arg]
            return await cli._cmd_backup(settings, str(copy))

    asyncio.run(while_the_app_runs())

    assert [query.url for query in stored_queries(copy)] == [URL]


def test_a_backup_never_overwrites_a_file(db_path: Path, tmp_path: Path) -> None:
    run("watch", URL)
    existing = tmp_path / "keep.db"
    existing.write_bytes(b"precious")

    assert run_command("backup", str(existing)) == 2
    assert existing.read_bytes() == b"precious"


def test_check_goes_through_the_proxy_file_like_a_search(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proxies = tmp_path / "proxies.txt"
    proxies.write_text("http://proxy.example:8080\n", encoding="utf-8")
    monkeypatch.setenv("VINTED_BOT_PROXY_FILE", str(proxies))
    used: list[str | None] = []

    def build(**kwargs: object) -> TransportSession:
        used.append(kwargs.get("proxy"))  # type: ignore[arg-type]
        return TransportSession(ScriptedTransport())

    monkeypatch.setattr(TransportSession, "build", build)

    run_command("check", "--url", URL)

    assert used == ["http://proxy.example:8080"]


def test_a_backup_to_a_folder_that_cannot_be_written_says_so(
    db_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It ended in sqlite3.OperationalError's traceback."""
    run("watch", URL)

    code = run_command("backup", str(tmp_path / "no-such-folder" / "backup.db"))

    assert (code, "Couldn't write the backup" in capsys.readouterr().err) == (1, True)


def test_export_into_a_reader_that_stops_early_ends_quietly(db_path: Path) -> None:
    """`vinted-bot export | head` ended in a BrokenPipeError traceback.

    A real process, since the fix rewires the process's own standard output.
    """
    command = [sys.executable, "-m", "vinted_bot", "export"]
    env = {**os.environ, "VINTED_BOT_DB_PATH": str(db_path)}
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    ) as export:
        assert export.stdout is not None and export.stderr is not None
        export.stdout.close()  # the reader is gone before anything is written
        errors = export.stderr.read().decode()
        code = export.wait(timeout=60)

    assert (code, "Traceback" in errors) == (0, False)


def test_a_discord_channel_link_is_explained_without_pointing_at_steps_above(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The dashboard's wording, "follow the steps above", made no sense in a terminal."""
    run_command("destination", "discord", "https://discord.com/channels/123/456")

    error = capsys.readouterr().err
    assert ("Copy Webhook URL" in error, "above" in error) == (True, False)


def test_an_apprise_address_it_does_not_know_is_refused_in_our_words_only(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Apprise logged its own line, with the address in it, before the explanation; the
    command line's logging printed it."""
    code = run_command("destination", "apprise", "nosuchservice://secret-token@host")

    assert (code, "secret-token" in caplog.text) == (2, False)


def test_a_link_differing_only_in_letter_case_is_a_duplicate(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Vinted's search ignores case, so search_text=Barbour watches the same listings."""
    run("watch", URL)

    assert run("watch", URL.replace("barbour", "Barbour")) == 1


def test_searches_lists_each_search_s_sites_words_and_countries(
    db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run("watch", URL, "--include", "jacket", "--countries", "fr,be", "--also-on", "be")
    capsys.readouterr()

    asyncio.run(cli._cmd_searches(Settings(_env_file=None)))  # type: ignore[call-arg]

    listed = capsys.readouterr().out
    assert ("vinted.fr, vinted.be" in listed, "jacket" in listed, "FR, BE" in listed) == (
        True,
        True,
        True,
    )
