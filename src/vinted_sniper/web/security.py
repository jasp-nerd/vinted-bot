"""Who may use the dashboard: the names it answers to, where changes may come from,
sign-in sessions, wrong-password pacing and the feed key.

Kept apart from the routes because each of these is a rule worth reading in one place.

**Host names (DNS rebinding).** A web page elsewhere can point its own name at
127.0.0.1, and the browser then treats the dashboard as that page's own site: the page can
read it and post to it. The Host header is what gives that away, so the dashboard only
answers to names it was told about: loopback, the host of VINTED_SNIPER_WEB_PUBLIC_URL,
VINTED_SNIPER_WEB_ALLOWED_HOSTS, and any bare IP address (a rebinding page always arrives
under a name, never an address, so opening it as http://192.168.1.20:8000 from a phone
stays possible). This holds however the server is bound, the Docker image's 0.0.0.0
included, because the port mapping that decides who can connect is invisible from here.

**Origins (CSRF).** A change (POST and the like) must come from a page of this dashboard:
its Origin, or Referer when Origin is missing, must be the very address the request was
sent to, and that address must itself pass the host check. Comparing to the request's own
Host alone is what let a rebinding page through, since it controls both.

**Sessions.** Signing in mints a random token. The browser keeps the token; the database
keeps only its hash, so signing out, or changing the password, revokes it for good. The
password itself is never stored, only a salted scrypt fingerprint used to notice that it
changed.

**The feed key.** Feed readers cannot sign in, so a feed's address carries a key. It is a
random value of its own, never the password, because feed addresses end up in reader
settings and proxy logs.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from collections import deque
from urllib.parse import urlparse

from fastapi import Request
from pydantic import SecretStr

from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Repo

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_WILDCARDS = frozenset({"0.0.0.0", "::", "[::]"})

# Thirty days: a password is asked for once per browser, not once per visit.
SESSION_MAX_AGE_S = 30 * 86_400
# Signed-in browsers remembered at once. The oldest is forgotten past this.
_MAX_SESSIONS = 20

# Wrong passwords allowed from one address before it has to wait.
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_S = 15 * 60

_SESSIONS_KEY = "web_sessions"
_PASSWORD_KEY = "web_password_check"
_FEED_KEY = "rss_key"

# scrypt cost: about 50 ms, paid once per start, not per request.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


# --- Host names and origins ---------------------------------------------------------


def allowed_hosts(settings: Settings) -> frozenset[str]:
    """The host names the dashboard answers to, besides any IP address."""
    names = set(LOOPBACK_NAMES)
    if settings.web_host not in _WILDCARDS:
        names.add(host_name(settings.web_host))
    if settings.web_public_url:
        names.add((urlparse(settings.web_public_url).hostname or "").lower())
    names.update(settings.allowed_host_names)
    names.discard("")
    return frozenset(names)


def host_name(netloc: str) -> str:
    """The name part of a Host header or URL authority, lower-cased, without the port."""
    host = netloc.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def host_allowed(host: str, allowed: frozenset[str]) -> bool:
    return host in allowed or _is_ip_address(host)


def same_origin(request: Request, settings: Settings, allowed: frozenset[str]) -> bool:
    """Whether a state-changing request came from a page of this dashboard.

    Browsers send Origin on every cross-site POST, and Referer when Origin is absent.
    A request with neither did not come from a web page (curl, a script) and cannot be a
    forged browser request.
    """
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or source == "null":
        return source is None
    origin = (urlparse(source).netloc or "").lower()
    own = {request.headers.get("host", "").lower()}
    if settings.web_public_url:
        own.add(urlparse(settings.web_public_url).netloc.lower())
    return origin in own and host_allowed(host_name(origin), allowed)


# --- Sessions -----------------------------------------------------------------------


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fingerprint(password: str, salt: str) -> str:
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return f"{salt}${derived.hex()}"


async def sync_password(repo: Repo, password: SecretStr | None) -> None:
    """Revoke every session if the password is not the one they were issued under.

    Run once when the dashboard starts, which is the only time the password can change.
    """
    if password is None:
        return
    secret = password.get_secret_value()
    stored = await repo.get_state_value(_PASSWORD_KEY)
    if stored and "$" in stored:
        salt = stored.split("$", 1)[0]
        current = await asyncio.to_thread(_fingerprint, secret, salt)
        if hmac.compare_digest(current, stored):
            return
    fresh = await asyncio.to_thread(_fingerprint, secret, secrets.token_hex(16))
    await repo.set_state_value(_SESSIONS_KEY, "{}")
    await repo.set_state_value(_PASSWORD_KEY, fresh)


async def _sessions(repo: Repo, now: int) -> dict[str, int]:
    raw = await repo.get_state_value(_SESSIONS_KEY)
    try:
        loaded = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        loaded = {}
    if not isinstance(loaded, dict):
        return {}
    return {
        key: issued
        for key, issued in loaded.items()
        if isinstance(issued, int) and now - issued < SESSION_MAX_AGE_S
    }


async def start_session(repo: Repo) -> str:
    """Sign a browser in. Returns the token for its cookie."""
    now = int(time.time())
    token = secrets.token_urlsafe(32)
    sessions = await _sessions(repo, now)
    sessions[_digest(token)] = now
    newest = sorted(sessions.items(), key=lambda pair: pair[1])[-_MAX_SESSIONS:]
    await repo.set_state_value(_SESSIONS_KEY, json.dumps(dict(newest)))
    return token


async def session_valid(repo: Repo, token: str | None) -> bool:
    if not token:
        return False
    return _digest(token) in await _sessions(repo, int(time.time()))


async def end_session(repo: Repo, token: str | None) -> None:
    if not token:
        return
    now = int(time.time())
    sessions = await _sessions(repo, now)
    if sessions.pop(_digest(token), None) is not None:
        await repo.set_state_value(_SESSIONS_KEY, json.dumps(sessions))


# --- Wrong passwords ----------------------------------------------------------------


class LoginThrottle:
    """Wrong passwords per address, so the sign-in page cannot be used to guess.

    In memory on purpose: a restart forgetting it costs an attacker a restart they cannot
    cause, and it keeps a locked database from locking people out.
    """

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}

    def wait_s(self, address: str, now: float | None = None) -> int:
        """Seconds this address must wait before trying again; 0 when it may."""
        at = time.time() if now is None else now
        recent = self._recent(address, at)
        if len(recent) < LOGIN_ATTEMPTS:
            return 0
        return max(1, int(recent[0] + LOGIN_WINDOW_S - at))

    def failed(self, address: str, now: float | None = None) -> None:
        at = time.time() if now is None else now
        self._recent(address, at).append(at)

    def succeeded(self, address: str) -> None:
        self._failures.pop(address, None)

    def _recent(self, address: str, now: float) -> deque[float]:
        recent = self._failures.setdefault(address, deque(maxlen=LOGIN_ATTEMPTS))
        while recent and recent[0] <= now - LOGIN_WINDOW_S:
            recent.popleft()
        return recent


# --- The feed key -------------------------------------------------------------------


async def feed_key(repo: Repo) -> str:
    """The key in feed addresses, made the first time it is asked for."""
    key = await repo.get_state_value(_FEED_KEY)
    if not key:
        key = secrets.token_urlsafe(18)
        await repo.set_state_value(_FEED_KEY, key)
    return key
