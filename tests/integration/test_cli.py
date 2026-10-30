"""The command line's commands, parsed the way a person types them, against a throwaway
database. They call the command handlers rather than `main`, which also configures
logging for the whole process and would leave every later test writing to a closed stream.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vinted_bot import cli
from vinted_bot.config import Settings
from vinted_bot.db import Database, apply_pending
from vinted_bot.db.repo import Query, Repo
from vinted_bot.vinted.models import Item

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
