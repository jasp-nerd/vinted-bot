"""Process settings, read once from the environment at startup.

Everything a *user* owns — searches, destinations, routing, per-search filters — lives in
SQLite instead, managed through the CLI or web UI. Keeping those two apart means there is
never a question of which copy of a setting wins.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vinted_bot.engine.validation import InvalidInputError, parse_timezone

# Not configurable. Polling faster than this earns 403s without finding items any sooner,
# because Vinted's own catalog lags behind uploads by far more than a few seconds.
MIN_POLL_INTERVAL_S = 10

# Ceiling for the 403 backoff ladder.
MAX_BACKOFF_S = 900


def in_container() -> bool:
    """Whether we are inside Docker or Podman.

    There, 0.0.0.0 is the only bind that works with published ports, and how far the
    dashboard is exposed is decided by the port mapping, which the app cannot see. The
    shipped docker-compose.yml publishes to the host's loopback only.
    """
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


# Where 1.x kept the database, relative to wherever the app was started.
LEGACY_DB_PATH = Path("./data/app.db")


def system_timezone() -> str:
    """The computer's own time zone, or UTC when it can't be told.

    Without this the default was UTC, and on a computer in Amsterdam every time on the
    dashboard and every quiet hour was an hour off. Read the way tzlocal does it, without
    the dependency: the /etc/localtime link (Linux and macOS) points into the zoneinfo
    folder, and Debian also writes the name to /etc/timezone. TZ itself is read by the
    field below. Windows has neither; the dashboard asks the browser there instead.
    """
    candidates: list[str] = []
    with contextlib.suppress(OSError):
        target = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in target:
            candidates.append(target.split("zoneinfo/", 1)[1])
    with contextlib.suppress(OSError):
        candidates.append(Path("/etc/timezone").read_text(encoding="utf-8").strip())
    for name in candidates:
        with contextlib.suppress(InvalidInputError):
            return parse_timezone(name)
    return "UTC"


def default_db_path() -> Path:
    """Where the database lives when VINTED_BOT_DB_PATH does not say.

    In a container: ./data/app.db (the image sets the variable to /data/app.db anyway).
    Outside one, if ./data/app.db already exists it is kept, so an upgrade never strands
    someone's searches in a file the app has stopped reading. Otherwise the platform's
    per-user data folder (~/.local/share/vinted-bot on Linux, ~/Library/Application
    Support/vinted-bot on macOS, %LOCALAPPDATA%\\vinted-bot on Windows), so the
    data does not depend on which directory the app happened to be started from.
    """
    if in_container() or LEGACY_DB_PATH.exists():
        return LEGACY_DB_PATH
    return platformdirs.user_data_path("vinted-bot", appauthor=False) / "app.db"


class Settings(BaseSettings):
    """Static configuration. Every field is documented in docs/configuration.md."""

    model_config = SettingsConfigDict(
        env_prefix="VINTED_BOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        # The timezone field also answers to TZ, which containers and systemd already set.
        populate_by_name=True,
    )

    # --- Storage -------------------------------------------------------------------
    db_path: Path = Field(
        default_factory=default_db_path,
        description="Path to the SQLite database file. Its parent directory is created on "
        "start. Defaults to ./data/app.db if that exists, else the per-user data folder.",
    )
    item_retention_days: int = Field(
        default=30,
        ge=1,
        description="Delete stored items older than this. Does not cause re-notification: "
        "what each search and seller watch has already seen is kept apart from the items.",
    )
    keep_raw_json: bool = Field(
        default=False,
        description="Store each item's raw API payload. Useful for debugging schema drift, "
        "but it keeps more seller data on disk than notifications need.",
    )

    # --- Time ----------------------------------------------------------------------
    timezone: str = Field(
        default_factory=system_timezone,
        validation_alias=AliasChoices("VINTED_BOT_TIMEZONE", "TZ"),
        description="IANA time zone for quiet hours and the stats page, such as "
        "Europe/Paris. Falls back to TZ, then to the computer's own time zone. The "
        "dashboard's settings page overrides it.",
    )

    # --- Logging -------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # --- Vinted transport ----------------------------------------------------------
    http_impersonate: bool = Field(
        default=False,
        description="Route Vinted requests through curl_cffi with a browser TLS fingerprint. "
        "Requires the 'impersonate' extra. Only needed if plain requests start getting 403s.",
    )
    proxy_file: Path | None = Field(
        default=None,
        description="Optional text file of proxy URLs, one per line. Off by default.",
    )
    session_rotate_minutes: int = Field(
        default=60,
        ge=1,
        description="Discard and re-bootstrap a site session once it reaches this age. "
        "Blocks correlate with session age more than with request rate.",
    )
    request_timeout_s: float = Field(default=15.0, gt=0)

    # --- Polling -------------------------------------------------------------------
    poll_default_interval_s: int = Field(
        default=60,
        ge=MIN_POLL_INTERVAL_S,
        description="Default seconds between checks for a new search. Per-search overrides "
        "live in the database.",
    )
    freshness_window_min: int = Field(
        default=20,
        ge=1,
        description="Skip listings the app can tell were already on Vinted this many minutes "
        "ago (it saw a newer listing by then). And after a gap longer than this, such as "
        "the app being off, the first check records what it missed without announcing it, "
        "so a restart never replays yesterday's catalog. A search's own 'ignore listings "
        "older than' overrides it.",
    )
    first_run_mode: Literal["silent", "newest"] = Field(
        default="silent",
        description="What a brand-new search does on its first check: 'silent' notifies "
        "nothing, 'newest' sends exactly one item so you can confirm delivery works.",
    )

    # --- Watchdog ------------------------------------------------------------------
    watchdog_stale_cycles: int = Field(
        default=10,
        ge=2,
        description="Consecutive checks with no newer listing before a search is called stale.",
    )
    watchdog_action: Literal["warn", "rotate"] = Field(
        default="rotate",
        description="What to do about a stale search: log a warning, or also force a new session.",
    )

    # --- Delivery ------------------------------------------------------------------
    outbox_expiry_minutes: int = Field(
        default=60,
        ge=1,
        description="Give up on an undelivered notification after this long. A two-hour-old "
        "listing alert is not worth sending.",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description="Enables Telegram delivery and the /start binding bot when set.",
    )

    # --- Updating ------------------------------------------------------------------
    supervised: Literal["launchd", "systemd", "windows-launcher"] | None = Field(
        default=None,
        description="Set by the installers' start-at-login entries (the LaunchAgent, the "
        "systemd unit and the Windows launcher) to say that something starts the app again "
        "when it exits. With it, an update from the dashboard restarts the app into the new "
        "version by itself; without it, the dashboard says how to restart.",
    )

    # --- Development ---------------------------------------------------------------
    fetch_mode: Literal["live", "mock"] = Field(
        default="live",
        description="'mock' replays recorded responses from disk instead of calling Vinted.",
    )
    mock_scenario_dir: Path | None = None

    # --- Web UI --------------------------------------------------------------------
    web_enabled: bool = True
    web_host: str = Field(
        default="127.0.0.1",
        description="Loopback by default. Only widen this behind a reverse proxy you trust.",
    )
    web_port: int = Field(default=8000, ge=1, le=65535)
    web_auth_token: SecretStr | None = Field(
        default=None,
        description="Optional. When set, the dashboard asks for it as a password. Set it "
        "before exposing the dashboard beyond localhost: anyone who can open it can add, "
        "remove and reroute your alerts.",
    )
    web_public_url: str | None = Field(
        default=None,
        description="The address the dashboard is reachable at from wherever you read your "
        "alerts — set it when the dashboard sits behind a reverse proxy or a tunnel. It "
        "becomes the Dashboard link in Discord messages. Unset, that link points at "
        "http://<web_host>:<web_port>.",
    )
    web_allowed_hosts: str | None = Field(
        default=None,
        description="Extra host names the dashboard answers to, comma-separated, such as "
        "'nas.local,finds.example.org'. Loopback names, any IP address and the host of "
        "web_public_url are always allowed; every other name gets a 400, which is what "
        "stops a DNS-rebinding web page from reading or changing the dashboard.",
    )

    @property
    def dashboard_url(self) -> str | None:
        """Where a notification may link the dashboard, or None while the web UI is off."""
        if not self.web_enabled:
            return None
        if self.web_public_url:
            return self.web_public_url.rstrip("/")
        # A wildcard bind is an instruction to the server, not an address a reader's
        # browser can open; loopback is the only honest guess left.
        host = "127.0.0.1" if self.web_host in {"0.0.0.0", "::"} else self.web_host
        return f"http://{host}:{self.web_port}"

    @property
    def allowed_host_names(self) -> list[str]:
        """`web_allowed_hosts` as a list of lower-case names, ports dropped."""
        names = []
        for raw in (self.web_allowed_hosts or "").split(","):
            name = raw.strip().lower()
            if "://" in name:
                name = name.split("://", 1)[1]
            name = name.split("/", 1)[0]
            if name.count(":") == 1:
                name = name.split(":", 1)[0]
            if name:
                names.append(name)
        return names

    @property
    def web_is_loopback(self) -> bool:
        """Whether the dashboard is reachable only from this machine."""
        return self.web_host in {"127.0.0.1", "localhost", "::1"}

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            return parse_timezone(value)
        except InvalidInputError as exc:
            raise ValueError(exc.message) from exc

    @model_validator(mode="after")
    def _check_coherent(self) -> Settings:
        if self.fetch_mode == "mock" and self.mock_scenario_dir is None:
            raise ValueError(
                "VINTED_BOT_FETCH_MODE is 'mock' but VINTED_BOT_MOCK_SCENARIO_DIR is not set."
            )
        return self

    @property
    def web_is_exposed_without_a_password(self) -> bool:
        """Whether the dashboard could be reached from another machine with no sign-in.

        Not treated as fatal: refusing would stop `docker compose up` working at all. And
        inside a container this stays quiet, because 0.0.0.0 is the only bind that works
        there and the port mapping — which the app cannot see — is what actually decides
        who can reach it.
        """
        if not self.web_enabled or self.web_auth_token is not None:
            return False
        return not self.web_is_loopback and not in_container()
