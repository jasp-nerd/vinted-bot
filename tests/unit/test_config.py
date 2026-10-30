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


def test_unknown_environment_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, wat_is_this=True)  # type: ignore[call-arg]


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


def test_an_unknown_time_zone_is_refused() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        Settings(_env_file=None, timezone="Mars/Olympus")  # type: ignore[call-arg]


def test_a_value_from_the_environment_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINTED_BOT_WEB_PORT", "8123")

    assert Settings(_env_file=None).source("web_port") == "environment"  # type: ignore[call-arg]


def test_a_value_from_the_env_file_says_so(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VINTED_BOT_WEB_PORT=8123\n", encoding="utf-8")

    assert Settings(_env_file=env_file).source("web_port") == "env file"  # type: ignore[call-arg]


def test_an_unset_value_is_the_default() -> None:
    assert Settings(_env_file=None).source("web_port") == "default"  # type: ignore[call-arg]


def test_every_setting_says_what_it_does() -> None:
    """The dashboard's Advanced list shows these; a blank one would hide a setting's purpose."""
    assert [name for name, field in Settings.model_fields.items() if not field.description] == []
