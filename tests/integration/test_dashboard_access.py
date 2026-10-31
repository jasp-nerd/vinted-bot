"""The dashboard password and phone access, set from Settings.

Two rules matter more than any screen: other devices are only let in while there is a
password, and the password only goes while they are not. The last tests run the real
server and move it between addresses.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.conftest import LOCAL_CLIENT
from vinted_bot import cli, managed
from vinted_bot.config import DASHBOARD_MANAGED, Settings
from vinted_bot.db import Database
from vinted_bot.db.repo import Repo
from vinted_bot.web import security
from vinted_bot.web.server import SESSION_COOKIE, create_app, serve

BASE = "http://127.0.0.1"
PASSWORD = "plum-tree-42"


@pytest.fixture(autouse=True)
def home_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """This computer is on a home network, whatever network the test runs on."""
    monkeypatch.setattr("vinted_bot.web.core.lan_addresses", lambda: ["192.168.1.20"])


@pytest.fixture
def changed() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
def make_client(tmp_path: Path, repo: Repo) -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def build(*, address: str = LOCAL_CLIENT[0], **overrides: Any) -> TestClient:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            db_path=tmp_path / "app.db",
            **overrides,
        )
        client = TestClient(create_app(settings, repo), base_url=BASE, client=(address, 50000))
        client.__enter__()
        opened.append(client)
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def _set(client: TestClient, new: str, current: str | None = None) -> Any:
    data = {"new_password": new}
    if current is not None:
        data["current_password"] = current
    return client.post("/settings/password", data=data)


def _phone(client: TestClient, allow: bool, **fields: str) -> Any:
    return client.post("/settings/phone", data={"allow": "1" if allow else "0", **fields})


# --- The password ---------------------------------------------------------------------


def test_a_password_set_in_settings_locks_the_dashboard(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)

    visitor = make_client()

    assert visitor.get("/", follow_redirects=False).headers["location"].startswith("/login")


def test_whoever_set_the_password_stays_signed_in(client: TestClient) -> None:
    _set(client, PASSWORD)

    assert client.get("/settings", follow_redirects=False).status_code == 200


def test_the_new_password_signs_in(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)
    visitor = make_client()

    visitor.post("/login", data={"password": PASSWORD})

    assert visitor.get("/settings", follow_redirects=False).status_code == 200


async def test_the_password_is_stored_only_as_a_fingerprint(client: TestClient, repo: Repo) -> None:
    _set(client, PASSWORD)

    stored = await repo.get_state_value("web_password")

    assert stored is not None and PASSWORD not in stored


def test_a_short_password_is_refused(client: TestClient) -> None:
    answer = _set(client, "short")

    assert (answer.status_code, answer.json()["field"]) == (400, "new_password")


def test_changing_needs_the_current_password(client: TestClient) -> None:
    _set(client, PASSWORD)

    assert _set(client, "another-one-9", current="wrong-guess").status_code == 403


def test_changing_signs_every_other_browser_out(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)
    other = make_client()
    other.post("/login", data={"password": PASSWORD})

    _set(client, "another-one-9", current=PASSWORD)

    assert other.get("/settings", follow_redirects=False).status_code == 303


def test_after_a_change_only_the_new_password_works(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)
    _set(client, "another-one-9", current=PASSWORD)
    visitor = make_client()

    assert visitor.post("/login", data={"password": PASSWORD}).status_code == 401


def test_removing_the_password_opens_the_dashboard_again(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)

    client.post("/settings/password/remove", data={"current_password": PASSWORD})

    assert make_client().get("/settings", follow_redirects=False).status_code == 200


def test_removing_needs_the_current_password(client: TestClient) -> None:
    _set(client, PASSWORD)

    answer = client.post("/settings/password/remove", data={"current_password": "nope-nope"})

    assert answer.status_code == 403


async def test_the_password_stays_while_other_devices_can_connect(
    client: TestClient, repo: Repo
) -> None:
    _phone(client, True, new_password=PASSWORD)

    client.post("/settings/password/remove", data={"current_password": PASSWORD})

    assert await security.password_required(Settings(_env_file=None), repo)  # type: ignore[call-arg]


def test_wrong_current_passwords_count_towards_the_sign_in_limit(client: TestClient) -> None:
    _set(client, PASSWORD)
    for _ in range(security.LOGIN_ATTEMPTS):
        _set(client, "another-one-9", current="wrong-guess")

    # Even the right one waits now, like a sign-in would.
    assert _set(client, "another-one-9", current=PASSWORD).status_code == 403


def test_a_nine_character_password_is_too_short(client: TestClient) -> None:
    assert _set(client, "plum-tree").status_code == 400


def test_five_wrong_passwords_make_sign_in_wait(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)
    visitor = make_client()
    for _ in range(security.LOGIN_ATTEMPTS):
        visitor.post("/login", data={"password": "wrong-guess"})

    # Even the right one waits now, for the rest of the quarter hour.
    answer = visitor.post("/login", data={"password": PASSWORD}, follow_redirects=False)

    assert (answer.status_code, int(answer.headers["retry-after"]) > 14 * 60) == (429, True)


def _from(client: TestClient, address: str) -> TestClient:
    """Another device talking to the same running dashboard."""
    return TestClient(client.app, base_url=BASE, client=(address, 50000))


def test_wrong_passwords_when_removing_count_towards_the_sign_in_limit(
    client: TestClient,
) -> None:
    _set(client, PASSWORD)
    for _ in range(security.LOGIN_ATTEMPTS):
        client.post("/settings/password/remove", data={"current_password": "wrong-guess"})

    answer = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)

    assert answer.status_code == 429


def test_the_sign_in_limit_is_per_address(client: TestClient) -> None:
    _set(client, PASSWORD)
    guesser = _from(client, "192.168.1.66")
    for _ in range(security.LOGIN_ATTEMPTS):
        guesser.post("/login", data={"password": "wrong-guess"})

    answer = _from(client, "192.168.1.67").post(
        "/login", data={"password": PASSWORD}, follow_redirects=False
    )

    assert answer.status_code == 303


def test_a_suggested_password_is_long_enough_and_easy_to_type() -> None:
    suggestion = security.suggest_password()

    assert len(suggestion) >= security.MIN_PASSWORD_LENGTH and not set("01ilo") & set(suggestion)


# --- A password from the environment ----------------------------------------------------


@pytest.fixture
def pinned(make_client: Callable[..., TestClient]) -> TestClient:
    client = make_client(web_auth_token=SecretStr("from-the-env-1"))
    client.post("/login", data={"password": "from-the-env-1"})
    return client


def test_a_password_from_the_environment_cannot_be_changed_here(pinned: TestClient) -> None:
    answer = _set(pinned, PASSWORD, current="from-the-env-1")

    assert "VINTED_BOT_WEB_AUTH_TOKEN" in answer.json()["error"]


def test_settings_say_the_password_comes_from_the_environment(pinned: TestClient) -> None:
    assert "set by VINTED_BOT_WEB_AUTH_TOKEN" in pinned.get("/settings").text


def test_the_sign_in_page_says_where_a_forgotten_password_is(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _set(client, PASSWORD)

    assert "vinted-bot reset-password" in make_client().get("/login").text


def test_in_docker_the_sign_in_page_gives_the_docker_command(
    make_client: Callable[..., TestClient], client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.web.routes.auth.in_container", lambda: True)
    _set(client, PASSWORD)

    page = make_client().get("/login").text

    assert "docker compose exec vinted-bot vinted-bot reset-password" in page


def test_in_docker_an_environment_password_is_changed_in_the_compose_file(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.web.routes.auth.in_container", lambda: True)

    page = make_client(web_auth_token=SecretStr("from-the-env-1")).get("/login").text

    assert ("docker compose up -d" in page, ".env file" in page) == (True, False)


def test_in_docker_your_data_is_said_to_be_in_the_volume(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "in_container", lambda: True)

    page = client.get("/settings").text

    assert ("data volume" in page, "one file on this computer" in page) == (True, False)


# --- Phone access -----------------------------------------------------------------------


async def test_phone_access_without_a_password_needs_one(client: TestClient, repo: Repo) -> None:
    answer = _phone(client, True)

    assert (answer.status_code, await managed.phone_access(repo)) == (400, False)


async def test_phone_access_sets_the_password_given_with_it(client: TestClient, repo: Repo) -> None:
    _phone(client, True, new_password=PASSWORD)

    assert await security.password_matches(Settings(_env_file=None), repo, PASSWORD)  # type: ignore[call-arg]


async def test_phone_access_moves_the_server_to_every_interface(
    client: TestClient, repo: Repo
) -> None:
    _phone(client, True, new_password=PASSWORD)

    assert await managed.web_host(Settings(_env_file=None), repo) == "0.0.0.0"  # type: ignore[call-arg]


async def test_turning_phone_access_off_returns_to_this_computer(
    client: TestClient, repo: Repo
) -> None:
    _phone(client, True, new_password=PASSWORD)

    _phone(client, False)

    assert await managed.web_host(Settings(_env_file=None), repo) == "127.0.0.1"  # type: ignore[call-arg]


async def test_with_a_password_already_set_none_is_asked_for(
    client: TestClient, repo: Repo
) -> None:
    _set(client, PASSWORD)

    _phone(client, True)

    assert await managed.phone_access(repo)


async def test_a_host_from_the_environment_wins(
    make_client: Callable[..., TestClient], repo: Repo
) -> None:
    pinned = make_client(web_host="192.168.1.20")

    answer = _phone(pinned, True, new_password=PASSWORD)

    assert (answer.status_code, await managed.phone_access(repo)) == (400, False)


def test_in_docker_the_switch_explains_the_port_mapping(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "in_container", lambda: True)

    assert "port mapping" in _phone(client, True, new_password=PASSWORD).json()["error"]


def test_settings_show_where_the_phone_can_open_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.web.core.lan_addresses", lambda: ["192.168.1.20"])
    _phone(client, True, new_password=PASSWORD)

    assert 'data-qr="http://192.168.1.20:8000"' in client.get("/settings").text


def test_phone_access_is_refused_on_a_network_with_only_a_public_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A university network gave a tester's laptop 130.37.84.245, and the switch offered it."""
    monkeypatch.setattr("vinted_bot.web.core.lan_addresses", lambda: [])

    answer = _phone(client, True, new_password=PASSWORD)

    assert (answer.status_code, "Tailscale" in answer.json()["error"]) == (400, True)


async def test_a_refused_switch_stays_off(
    client: TestClient, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.web.core.lan_addresses", lambda: [])

    _phone(client, True, new_password=PASSWORD)

    assert not await managed.phone_access(repo)


def test_turning_phone_access_off_works_without_a_private_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _phone(client, True, new_password=PASSWORD)
    monkeypatch.setattr("vinted_bot.web.core.lan_addresses", lambda: [])

    assert _phone(client, False).status_code == 200


# --- Who can connect --------------------------------------------------------------------


async def test_with_phone_access_on_a_visitor_from_the_internet_is_refused(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _phone(client, True, new_password=PASSWORD)

    answer = make_client(address="130.37.84.245").get("/login")

    assert (answer.status_code, "Not on this network" in answer.text) == (403, True)


def test_with_phone_access_on_a_phone_on_the_wifi_gets_the_sign_in_page(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _phone(client, True, new_password=PASSWORD)

    assert make_client(address="192.168.1.30").get("/login").status_code == 200


def test_with_phone_access_on_the_internet_cannot_guess_passwords(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _phone(client, True, new_password=PASSWORD)

    answer = make_client(address="130.37.84.245").post("/login", data={"password": PASSWORD})

    assert answer.status_code == 403


def test_with_phone_access_on_the_internet_does_not_even_get_the_styles(
    make_client: Callable[..., TestClient], client: TestClient
) -> None:
    _phone(client, True, new_password=PASSWORD)

    assert make_client(address="130.37.84.245").get("/static/css/app.css").status_code == 403


def test_a_host_from_the_environment_refuses_the_internet_too(
    make_client: Callable[..., TestClient],
) -> None:
    visitor = make_client(address="130.37.84.245", web_host="0.0.0.0")

    assert visitor.get("/healthz").status_code == 403


def test_in_docker_requests_from_the_bridge_are_served(
    make_client: Callable[..., TestClient],
) -> None:
    """Port-mapped requests reach the container from Docker's bridge gateway."""
    visitor = make_client(address="172.17.0.1", web_host="0.0.0.0")

    assert visitor.get("/manifest.webmanifest").status_code == 200


def test_tailscale_devices_are_served(make_client: Callable[..., TestClient]) -> None:
    visitor = make_client(address="100.101.102.103", web_host="0.0.0.0")

    assert visitor.get("/manifest.webmanifest").status_code == 200


def test_a_public_proxy_address_lets_the_internet_in(
    make_client: Callable[..., TestClient],
) -> None:
    visitor = make_client(
        address="130.37.84.245",
        web_host="0.0.0.0",
        web_public_url="https://finds.example.org",
    )

    answer = visitor.get("/manifest.webmanifest", headers={"host": "finds.example.org"})

    assert answer.status_code == 200


def test_allowing_the_internet_lets_it_in(make_client: Callable[..., TestClient]) -> None:
    visitor = make_client(address="130.37.84.245", web_host="0.0.0.0", web_allow_public=True)

    assert visitor.get("/manifest.webmanifest").status_code == 200


def test_on_loopback_the_client_address_is_not_judged(
    make_client: Callable[..., TestClient],
) -> None:
    """Only this computer can connect then; a local proxy may still name the visitor."""
    assert make_client(address="130.37.84.245").get("/manifest.webmanifest").status_code == 200


async def test_the_moment_before_the_server_moves_back_is_guarded(
    make_client: Callable[..., TestClient], client: TestClient, repo: Repo
) -> None:
    """Phone access off, but the server still listens everywhere until it has moved."""
    visitor = make_client(address="130.37.84.245")
    visitor.app.state.ctx.listening_on = "0.0.0.0"  # type: ignore[attr-defined]

    assert visitor.get("/healthz").status_code == 403


# --- Forgotten passwords -------------------------------------------------------------------


async def test_reset_password_prints_a_new_one_that_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The handler, not cli.main: main configures logging for the whole test process.
    settings = Settings(_env_file=None, db_path=tmp_path / "reset.db")  # type: ignore[call-arg]

    assert await cli._cmd_reset_password(settings) == 0
    printed = capsys.readouterr().out.split("is:\n\n  ", 1)[1].split("\n", 1)[0]

    async with Database(tmp_path / "reset.db") as db:
        assert await security.password_matches(settings, Repo(db), printed)


async def test_reset_password_leaves_an_environment_password_alone(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, db_path=tmp_path / "reset.db", web_auth_token=SecretStr("from-env-1")
    )

    assert await cli._cmd_reset_password(settings) == 2


# --- The real server, moving --------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _wait_for(
    http: httpx.AsyncClient, port: int, host: str, *, error: bool = False
) -> dict[str, Any]:
    """The access status once the server listens on `host` (and reports an error)."""
    async with asyncio.timeout(10):
        while True:
            try:
                answer = await http.get(f"http://127.0.0.1:{port}/api/access")
                status = dict(answer.json()) if answer.status_code == 200 else {}
                if status.get("listening_on") == host and bool(status.get("error")) == error:
                    return status
            except httpx.TransportError:
                pass  # between the old address and the new one
            await asyncio.sleep(0.05)


async def test_the_server_moves_to_every_interface_and_back_without_stopping(
    tmp_path: Path, repo: Repo
) -> None:
    port = _free_port()
    settings = Settings(_env_file=None, db_path=tmp_path / "app.db", web_port=port)  # type: ignore[call-arg]
    stop = asyncio.Event()
    running = asyncio.create_task(serve(settings, repo, stop))
    origin = {"origin": f"http://127.0.0.1:{port}"}
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            await _wait_for(http, port, "127.0.0.1")
            moved = await http.post(
                f"http://127.0.0.1:{port}/settings/phone",
                data={"allow": "1", "new_password": PASSWORD},
                headers=origin,
            )
            http.cookies.set(SESSION_COOKIE, moved.cookies[SESSION_COOKIE])
            await _wait_for(http, port, "0.0.0.0")
            await http.post(
                f"http://127.0.0.1:{port}/settings/phone", data={"allow": "0"}, headers=origin
            )
            back = await _wait_for(http, port, "127.0.0.1")
    finally:
        stop.set()
        await asyncio.wait_for(running, 10)

    assert back["error"] is None


async def test_an_address_that_cannot_be_taken_keeps_the_old_one_and_says_why(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An address from the documentation range: no machine has it, so it cannot be bound.
    monkeypatch.setattr(managed, "EVERY_INTERFACE", "203.0.113.7")
    port = _free_port()
    settings = Settings(_env_file=None, db_path=tmp_path / "app.db", web_port=port)  # type: ignore[call-arg]
    stop = asyncio.Event()
    running = asyncio.create_task(serve(settings, repo, stop))
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            await _wait_for(http, port, "127.0.0.1")
            await http.post(
                f"http://127.0.0.1:{port}/settings/phone",
                data={"allow": "1", "new_password": PASSWORD},
                headers={"origin": f"http://127.0.0.1:{port}"},
            )
            status = await _wait_for(http, port, "127.0.0.1", error=True)
    finally:
        stop.set()
        await asyncio.wait_for(running, 10)

    assert "203.0.113.7" in status["error"]


async def test_a_port_already_in_use_stops_the_app_at_start(tmp_path: Path, repo: Repo) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = int(taken.getsockname()[1])
        settings = Settings(_env_file=None, db_path=tmp_path / "app.db", web_port=port)  # type: ignore[call-arg]

        with pytest.raises(SystemExit):
            await serve(settings, repo, asyncio.Event())


# --- Advanced: what the environment sets ------------------------------------------------


def test_advanced_lists_every_setting_without_a_control_of_its_own(client: TestClient) -> None:
    page = client.get("/settings").text

    missing = [
        name
        for name in Settings.model_fields
        if name not in DASHBOARD_MANAGED and f"VINTED_BOT_{name.upper()}" not in page
    ]
    assert missing == []


def test_advanced_says_a_time_zone_read_from_the_computer_came_from_there(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It said "From the .env file" on a computer with no .env file."""
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delenv("VINTED_BOT_TIMEZONE", raising=False)

    assert Settings(_env_file=None).source("timezone") == "system"  # type: ignore[call-arg]


def test_advanced_says_a_time_zone_came_from_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    monkeypatch.delenv("VINTED_BOT_TIMEZONE", raising=False)

    assert Settings(_env_file=None).source("timezone") == "TZ"  # type: ignore[call-arg]


def test_advanced_says_a_value_came_from_the_environment(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINTED_BOT_ITEM_RETENTION_DAYS", "90")

    page = make_client(item_retention_days=90).get("/settings").text

    assert '<b>90</b> <span class="t-sm">· From the environment</span>' in page


def test_advanced_never_shows_a_secret(make_client: Callable[..., TestClient], repo: Repo) -> None:
    client = make_client(telegram_bot_token=SecretStr("123456789:" + "S" * 35))

    assert "S" * 35 not in client.get("/settings").text
