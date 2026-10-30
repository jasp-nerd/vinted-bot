"""Setting up the Telegram bot from the dashboard: no settings file, no restart.

Telegram is an httpx mock that knows one good token, so these run offline.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from vinted_bot import managed
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.web.server import create_app

GOOD = "123456789:" + "A" * 35
REVOKED = "987654321:" + "B" * 35
BASE = "http://127.0.0.1"


class Telegram:
    """Answers getMe like Telegram: a bot for the good token, 401 for any other."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx.ConnectError("no route to host", request=request)
        if request.url.path == f"/bot{GOOD}/getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "mags_test_bot"}})
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})


@pytest.fixture
def telegram() -> Telegram:
    return Telegram()


@pytest.fixture
def changed() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
def make_client(
    tmp_path: Path, repo: Repo, telegram: Telegram, changed: asyncio.Event
) -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def build(**overrides: Any) -> TestClient:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            db_path=tmp_path / "app.db",
            **overrides,
        )
        http = httpx.AsyncClient(transport=httpx.MockTransport(telegram.handler))
        app = create_app(settings, repo, http=http, telegram_token_changed=changed)
        client = TestClient(app, base_url=BASE)
        client.__enter__()
        opened.append(client)
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def _save(client: TestClient, token: str) -> Any:
    return client.post("/destinations/telegram/token", data={"telegram_token": token})


async def test_a_good_token_is_kept(client: TestClient, repo: Repo) -> None:
    _save(client, GOOD)

    assert await managed.telegram_token(Settings(_env_file=None), repo) == GOOD  # type: ignore[call-arg]


def test_saving_names_the_bot(client: TestClient) -> None:
    assert _save(client, GOOD).json()["bot"] == "mags_test_bot"


def test_the_answer_shows_the_token_only_masked(client: TestClient) -> None:
    answer = _save(client, GOOD)

    assert (GOOD in answer.text, answer.json()["masked"]) == (False, "123456789:•••••AAAA")


def test_saving_tells_the_running_bot(client: TestClient, changed: asyncio.Event) -> None:
    _save(client, GOOD)

    assert changed.is_set()


async def test_a_token_telegram_refuses_is_not_kept(client: TestClient, repo: Repo) -> None:
    answer = _save(client, REVOKED)

    assert (answer.status_code, await repo.get_state_value("telegram_bot_token")) == (400, None)


def test_a_refused_token_says_to_copy_it_again(client: TestClient) -> None:
    assert "Copy it again from BotFather" in _save(client, REVOKED).json()["error"]


def test_something_that_is_not_a_token_is_refused_without_asking_telegram(
    client: TestClient, telegram: Telegram
) -> None:
    answer = _save(client, "my bot")

    assert (answer.json()["field"], telegram.requests) == ("telegram_token", [])


def test_botfathers_whole_message_can_be_pasted(client: TestClient) -> None:
    message = (
        "Done! Congratulations on your new bot.\nUse this token to access the HTTP API:\n"
        f"{GOOD}\nKeep your token secure"
    )

    assert _save(client, message).json()["ok"] is True


async def test_telegram_out_of_reach_keeps_nothing(
    client: TestClient, telegram: Telegram, repo: Repo
) -> None:
    telegram.down = True

    answer = _save(client, GOOD)

    assert (answer.status_code, await repo.get_state_value("telegram_bot_token")) == (400, None)


def test_the_token_is_never_logged(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    _save(client, GOOD)
    _save(client, REVOKED)

    output = capsys.readouterr()
    assert GOOD.split(":")[1] not in output.out + output.err


async def test_the_alerts_page_shows_the_bot_but_not_its_token(
    client: TestClient, repo: Repo
) -> None:
    await managed.set_telegram_token(repo, GOOD)

    page = client.get("/alerts").text

    assert ("@mags_test_bot" in page, GOOD in page) == (True, False)


async def test_removing_the_bot_forgets_its_token(
    client: TestClient, repo: Repo, changed: asyncio.Event
) -> None:
    await managed.set_telegram_token(repo, GOOD)

    client.post("/destinations/telegram/token/remove")

    assert (await repo.get_state_value("telegram_bot_token"), changed.is_set()) == (None, True)


def test_pairing_works_straight_after_saving_a_token(client: TestClient) -> None:
    _save(client, GOOD)

    started = client.post("/destinations/telegram/pair").json()

    assert started["link"] == f"https://t.me/mags_test_bot?start={started['code']}"


# --- A token from the environment ---------------------------------------------------


@pytest.fixture
def pinned(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(telegram_bot_token=SecretStr(GOOD))


def test_a_token_from_the_environment_cannot_be_replaced_here(pinned: TestClient) -> None:
    assert "VINTED_BOT_TELEGRAM_BOT_TOKEN" in _save(pinned, REVOKED).json()["error"]


def test_a_token_from_the_environment_cannot_be_removed_here(pinned: TestClient) -> None:
    assert pinned.post("/destinations/telegram/token/remove").status_code == 400


def test_the_page_says_where_the_token_comes_from(pinned: TestClient) -> None:
    page = pinned.get("/alerts").text

    assert 'comes from <span class="code">VINTED_BOT_TELEGRAM_BOT_TOKEN</span>' in page


# --- Setup ----------------------------------------------------------------------------


def _setup_alerts_step(client: TestClient, **fields: str) -> Any:
    state = {"tld": "fr", "search": {"link": "https://www.vinted.fr/catalog?search_text=nike"}}
    return client.post(
        "/welcome/alerts",
        data={"state": json.dumps(state), "submitted": "1", "kind": "telegram", **fields},
    )


def test_setup_without_a_token_asks_for_one(client: TestClient) -> None:
    page = _setup_alerts_step(client).text

    assert "Paste your bot&#39;s token from BotFather first." in page


def test_setup_with_a_made_up_token_says_it_is_not_valid(client: TestClient) -> None:
    page = _setup_alerts_step(client, telegram_token=REVOKED)

    assert (page.status_code, "isn&#39;t valid" in page.text) == (400, True)


def test_setup_with_a_good_token_moves_on_to_connecting_the_chat(client: TestClient) -> None:
    page = _setup_alerts_step(client, telegram_token=GOOD).text

    assert '<div class="stack-lg" data-pair>' in page


def test_setup_never_writes_a_typed_token_back_into_the_page(client: TestClient) -> None:
    page = _setup_alerts_step(client, telegram_token=REVOKED).text

    assert REVOKED.split(":")[1] not in page
