from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from vinted_bot import config
from vinted_bot.config import MIN_POLL_INTERVAL_S, Settings


def test_defaults_are_conservative() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.poll_default_interval_s >= MIN_POLL_INTERVAL_S
    assert settings.first_run_mode == "silent", "a new search must not replay the catalog"
    assert settings.keep_raw_json is False, "storing seller payloads should be opt-in"
    assert settings.web_host == "127.0.0.1", "the web UI must not listen publicly by default"
    assert settings.web_is_loopback


def test_no_password_is_allowed_on_localhost() -> None:
    """Anyone who can reach localhost is already on the machine."""
    settings = Settings(_env_file=None, web_enabled=True)  # type: ignore[call-arg]

    assert settings.web_auth_token is None
    assert settings.web_is_exposed_without_a_password is False


def test_a_passwordless_dashboard_on_a_public_address_is_flagged() -> None:
    """Not fatal — a container always binds 0.0.0.0 — but it must be visible in the logs."""
    settings = Settings(_env_file=None, web_enabled=True, web_host="0.0.0.0")  # type: ignore[call-arg]

    assert settings.web_is_exposed_without_a_password is True


def test_a_token_clears_the_exposure_warning() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, web_enabled=True, web_host="0.0.0.0", web_auth_token=SecretStr("s")
    )

    assert settings.web_is_exposed_without_a_password is False


def test_web_ui_starts_when_token_is_supplied() -> None:
    settings = Settings(_env_file=None, web_enabled=True, web_auth_token=SecretStr("s3cret"))  # type: ignore[call-arg]

    assert settings.web_enabled is True
    assert settings.web_auth_token is not None
    assert "s3cret" not in repr(settings), "secrets must not leak through repr"


def test_mock_mode_requires_a_scenario_directory() -> None:
    with pytest.raises(ValidationError, match="MOCK_SCENARIO_DIR"):
        Settings(_env_file=None, fetch_mode="mock")  # type: ignore[call-arg]


def test_poll_interval_below_floor_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, poll_default_interval_s=1)  # type: ignore[call-arg]


def test_unknown_keys_do_not_stop_the_app_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover VINTED_SNIPER_ line or another program's PUID used to be fatal."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PUID=1000\nVINTED_SNIPER_WEB_PORT=9000\n", encoding="utf-8")

    assert Settings().web_port == 8000


def test_unknown_vinted_keys_are_named_for_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PUID=1000\n# VINTED_BOT_OLD=1\nVINTED_SNIPER_WEB_PORT=9000\nVINTED_BOT_WEB_PORT=8001\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VINTED_BOT_WEB_PROT", "8002")

    assert Settings.unknown_keys() == ["VINTED_BOT_WEB_PROT", "VINTED_SNIPER_WEB_PORT"]


def test_an_existing_data_folder_keeps_being_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrading must not strand someone's searches in a file the app stopped reading."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "in_container", lambda: False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "app.db").write_bytes(b"")

    assert config.default_db_path() == config.LEGACY_DB_PATH


def test_a_fresh_install_uses_the_user_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "in_container", lambda: False)

    path = config.default_db_path()

    assert path.name == "app.db"
    assert path.parent.name == "vinted-bot"


def test_a_container_keeps_the_relative_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "in_container", lambda: True)

    assert config.default_db_path() == config.LEGACY_DB_PATH


def test_the_time_zone_falls_back_to_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")

    assert Settings(_env_file=None).timezone == "Europe/Paris"  # type: ignore[call-arg]


@pytest.mark.parametrize("value", [":/etc/localtime", "CET-1CEST,M3.5.0,M10.5.0/3", "Mars/Olympus"])
def test_a_time_zone_the_app_cannot_read_falls_back_with_a_warning(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Systems set TZ in POSIX forms zoneinfo cannot read; that stopped the app starting."""
    monkeypatch.setattr(config, "system_timezone", lambda: "Europe/Amsterdam")
    monkeypatch.setenv("TZ", value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.timezone == "Europe/Amsterdam"
    assert "Europe/Amsterdam is used" in settings.warnings[0]


def test_a_bad_setting_is_explained_in_one_paragraph() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, web_port="abc")  # type: ignore[call-arg,arg-type]

    assert config.explain(raised.value).startswith(
        "vinted-bot can't start because of its settings. VINTED_BOT_WEB_PORT is set to 'abc': "
    )
