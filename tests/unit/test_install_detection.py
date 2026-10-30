"""Telling how this copy was installed, which decides whether it may update itself.

Each case builds the marker files the real installers leave (uv's receipt, pipx's metadata,
a git checkout) in a temporary folder, rather than describing them to a fake.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vinted_sniper.config import Settings
from vinted_sniper.engine.self_update import Install, InstallKind, detect


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def uv_tool_env(tmp_path: Path, bin_dir: Path | None = None) -> Path:
    """A uv tool environment as `uv tool install` lays it out."""
    prefix = tmp_path / "tools" / "vinted-sniper"
    prefix.mkdir(parents=True)
    command = (bin_dir or tmp_path / "bin") / "vinted-sniper"
    (prefix / "uv-receipt.toml").write_text(
        "[tool]\n"
        'requirements = [{ name = "vinted-sniper" }]\n'
        "entrypoints = [\n"
        f'    {{ name = "vinted-sniper", install-path = "{command}", from = "vinted-sniper" }},\n'
        "]\n"
    )
    return prefix


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def detect_in(tmp_path: Path, prefix: Path, **overrides: Any) -> Install:
    kwargs: dict[str, Any] = {
        "prefix": prefix,
        "package_dir": tmp_path / "site-packages" / "vinted_sniper",
        "container": False,
        "environ": {"PATH": ""},
        "home": tmp_path / "home",
        "windows": False,
        "system_bins": (),
    }
    kwargs.update(overrides)
    return detect(kwargs.pop("settings", settings()), **kwargs)


def test_a_uv_tool_install_is_recognised_by_its_receipt(tmp_path: Path) -> None:
    install = detect_in(tmp_path, uv_tool_env(tmp_path))

    assert install.kind is InstallKind.UV_TOOL


def test_uv_is_found_in_the_installers_folder_when_path_is_bare(tmp_path: Path) -> None:
    """launchd starts the app with PATH=/usr/bin:/bin..., where uv never is."""
    uv = executable(tmp_path / "home" / ".local" / "bin" / "uv")

    install = detect_in(tmp_path, uv_tool_env(tmp_path))

    assert install.tool == uv


def test_uv_named_by_uvs_own_variable_wins(tmp_path: Path) -> None:
    executable(tmp_path / "home" / ".local" / "bin" / "uv")
    chosen = executable(tmp_path / "elsewhere" / "uv")

    install = detect_in(tmp_path, uv_tool_env(tmp_path), environ={"UV": str(chosen)})

    assert install.tool == chosen


def test_the_upgrade_is_pointed_at_this_copys_tool_folders(tmp_path: Path) -> None:
    """So a different UV_TOOL_DIR in uv's defaults cannot upgrade some other copy."""
    bin_dir = tmp_path / "custom-bin"
    prefix = uv_tool_env(tmp_path, bin_dir=bin_dir)

    install = detect_in(tmp_path, prefix)

    assert install.tool_env == {"UV_TOOL_DIR": str(prefix.parent), "UV_TOOL_BIN_DIR": str(bin_dir)}


def test_a_homebrew_uv_is_found_after_path(tmp_path: Path) -> None:
    brew = tmp_path / "homebrew" / "bin"
    uv = executable(brew / "uv")

    install = detect_in(tmp_path, uv_tool_env(tmp_path), system_bins=(brew,))

    assert install.tool == uv


def test_without_uv_anywhere_it_cannot_update_itself(tmp_path: Path) -> None:
    install = detect_in(tmp_path, uv_tool_env(tmp_path))

    assert not install.can_upgrade


def test_a_pipx_install_is_recognised_by_its_metadata(tmp_path: Path) -> None:
    prefix = tmp_path / "pipx" / "venvs" / "vinted-sniper"
    prefix.mkdir(parents=True)
    (prefix / "pipx_metadata.json").write_text("{}")
    pipx = executable(tmp_path / "home" / ".local" / "bin" / "pipx")

    install = detect_in(tmp_path, prefix)

    assert (install.kind, install.tool, install.tool_env["PIPX_HOME"]) == (
        InstallKind.PIPX,
        pipx,
        str(tmp_path / "pipx"),
    )


def test_a_container_never_updates_itself_whatever_is_inside(tmp_path: Path) -> None:
    executable(tmp_path / "home" / ".local" / "bin" / "uv")

    install = detect_in(
        tmp_path, uv_tool_env(tmp_path), container=True, settings=settings(supervised="systemd")
    )

    assert (install.kind, install.can_upgrade) == (InstallKind.DOCKER, False)


def test_a_git_checkout_is_a_source_install(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")

    install = detect_in(tmp_path, tmp_path / ".venv", package_dir=root / "src" / "vinted_sniper")

    assert install.kind is InstallKind.SOURCE


def test_uvx_runs_from_uvs_cache(tmp_path: Path) -> None:
    install = detect_in(tmp_path, tmp_path / "cache" / "archive-v0" / "abc123")

    assert install.kind is InstallKind.UVX


def test_anything_else_is_a_plain_pip_install(tmp_path: Path) -> None:
    install = detect_in(tmp_path, tmp_path / "venv")

    assert (install.kind, install.manual_command) == (
        InstallKind.OTHER,
        "pip install --upgrade vinted-sniper",
    )


def test_docker_is_told_to_pull_the_new_image() -> None:
    install = Install(kind=InstallKind.DOCKER, supervisor=None)

    assert install.manual_command == "docker compose pull && docker compose up -d"


def test_automatic_updates_need_something_to_restart_the_app(tmp_path: Path) -> None:
    uv = executable(tmp_path / "uv")
    unsupervised = Install(kind=InstallKind.UV_TOOL, supervisor=None, tool=uv)
    supervised = Install(kind=InstallKind.UV_TOOL, supervisor="launchd", tool=uv)

    assert (unsupervised.can_upgrade, unsupervised.can_update_automatically) == (True, False)
    assert supervised.can_update_automatically


def test_the_supervisor_comes_from_the_installers_variable(tmp_path: Path) -> None:
    install = detect_in(tmp_path, uv_tool_env(tmp_path), settings=settings(supervised="launchd"))

    assert install.supervisor == "launchd"


def test_on_windows_only_the_launcher_can_upgrade(tmp_path: Path) -> None:
    """A running program's files are locked there; the launcher upgrades while it is stopped."""
    uv = executable(tmp_path / "uv.exe")
    alone = Install(kind=InstallKind.UV_TOOL, supervisor=None, tool=uv, windows=True)
    launched = Install(kind=InstallKind.UV_TOOL, supervisor="windows-launcher", windows=True)

    assert (alone.can_upgrade, launched.can_upgrade) == (False, True)


def test_the_upgrade_command_is_fixed_and_names_only_the_package(tmp_path: Path) -> None:
    uv = executable(tmp_path / "uv")
    install = Install(kind=InstallKind.UV_TOOL, supervisor=None, tool=uv)

    assert install.upgrade_command() == [
        str(uv),
        "tool",
        "upgrade",
        "vinted-sniper",
        "--no-progress",
    ]
