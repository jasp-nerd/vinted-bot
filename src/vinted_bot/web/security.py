"""Who may use the dashboard: the devices it lets in, the names it answers to, where
changes may come from, sign-in sessions, wrong-password pacing and the feed key.

Kept apart from the routes because each of these is a rule worth reading in one place.

**Devices (who connects).** Phone access listens on every network interface, and some
networks (universities, offices, a laptop plugged straight into a modem) give a computer
a public internet address: then anyone on the internet could reach the sign-in page.
So whenever the server listens beyond this computer, a request is only served when it
comes from this computer or a private network: home and office ranges (RFC 1918),
self-assigned addresses, Tailscale's 100.64.0.0/10 and their IPv6 counterparts. Docker's
port mapping hands requests on from its bridge, a private address, so LAN access to a
container still works. Putting the dashboard on the internet on purpose, behind a
reverse proxy, is said with VINTED_BOT_WEB_PUBLIC_URL or VINTED_BOT_WEB_ALLOWED_HOSTS
naming a public host, or VINTED_BOT_WEB_ALLOW_PUBLIC=true. A proxy on the same machine or
network needs none of these, since its own address is the one seen here.

**Host names (DNS rebinding).** A web page elsewhere can point its own name at
127.0.0.1, and the browser then treats the dashboard as that page's own site: the page can
read it and post to it. The Host header is what gives that away, so the dashboard only
answers to names it was told about: loopback, the host of VINTED_BOT_WEB_PUBLIC_URL,
VINTED_BOT_WEB_ALLOWED_HOSTS, and names no public DNS can hand out: any bare IP address,
single-label names such as `nas` and the private-use suffixes routers and VPNs hand out
(`.local`, `.lan`, `.home`, `.home.arpa`, `.internal`, `.fritz.box`, Tailscale's
`.ts.net`). A rebinding page always arrives under a public name, so opening it as
http://192.168.1.20:8000 or http://umbrel.local from a phone stays possible. This holds
however the server is bound, the Docker image's 0.0.0.0 included, because the port
mapping that decides who can connect is invisible from here.

**Origins (CSRF).** A change (POST and the like) must come from a page of this dashboard:
its Origin, or Referer when Origin is missing, must be the very address the request was
sent to, and that address must itself pass the host check. Comparing to the request's own
Host alone is what let a rebinding page through, since it controls both.

**The password.** Set in Settings, or by VINTED_BOT_WEB_AUTH_TOKEN, which wins when set
(see managed.py for why the environment wins). The dashboard's own is never stored, only
a salted scrypt fingerprint; it is read on every request rather than remembered, so
`vinted-bot reset-password` takes effect in a running app. Other devices may only be let
in while there is a password, and it can only be removed while there are none.

**Sessions.** Signing in mints a random token. The browser keeps the token; the database
keeps only its hash, so signing out, or changing the password, revokes it for good. For
the environment's password a fingerprint is kept too, to notice it changed at a restart.

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
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Request
from pydantic import SecretStr

from vinted_bot import managed
from vinted_bot.config import Settings, in_container
from vinted_bot.db.repo import Repo
from vinted_bot.engine.validation import InvalidInputError

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WILDCARDS = frozenset({"0.0.0.0", "::", "[::]"})

# Thirty days: a password is asked for once per browser, not once per visit.
SESSION_MAX_AGE_S = 30 * 86_400
# Signed-in browsers remembered at once. The oldest is forgotten past this.
_MAX_SESSIONS = 20

# Wrong passwords allowed from one address before it has to wait.
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_S = 15 * 60

_SESSIONS_KEY = "web_sessions"
# The environment's password, fingerprinted to notice a change at restart.
_ENV_PASSWORD_KEY = "web_password_check"
# The password set in Settings, fingerprinted to check it.
_PASSWORD_KEY = "web_password"
_FEED_KEY = "rss_key"

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
# Suggested passwords skip letters that read alike (l, 1, o, 0, i) so they can be typed
# from a phone screen. Twelve of these is about 59 bits: far beyond guessing at five
# tries per quarter hour.
_FRIENDLY = "abcdefghjkmnpqrstuvwxyz23456789"

# scrypt cost: about 50 ms, paid once per start, not per request.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


# --- Devices --------------------------------------------------------------------------

# This computer, private networks, self-assigned addresses and Tailscale (CGNAT), in both
# IP versions. Spelled out rather than ipaddress's is_private, which also counts
# documentation and benchmarking ranges and leaves 100.64.0.0/10 out.
_LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def is_local_address(address: str) -> bool:
    """Whether a client address is this computer or a private network (see above).

    Anything that is not an IP address at all counts as not local, so an odd transport
    fails closed.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0].strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in network for network in _LOCAL_NETWORKS)


def public_allowed(settings: Settings) -> bool:
    """Whether the operator put the dashboard on the internet on purpose.

    Naming a public host as its address says so as clearly as the switch made for it:
    nobody types finds.example.org into VINTED_BOT_WEB_PUBLIC_URL by accident.
    """
    if settings.web_allow_public:
        return True
    names = list(settings.allowed_host_names)
    if settings.web_public_url:
        names.append((urlparse(settings.web_public_url).hostname or "").lower())
    return any(_is_public_name(name) for name in names if name)


def _is_public_name(name: str) -> bool:
    if name in LOOPBACK_NAMES:
        return False
    if _is_ip_address(name):
        return not is_local_address(name)
    return not _is_local_name(name)


def client_allowed(settings: Settings, listening_beyond_loopback: bool, client: str) -> bool:
    """Whether a request from `client` may be served at all (see "Devices" above)."""
    if not listening_beyond_loopback:
        return True
    return is_local_address(client) or public_allowed(settings)


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


# Names only a home network, a router or a VPN hands out: mDNS, the suffixes routers use
# (RFC 8375's home.arpa, the reserved .internal, and the common .lan, .home and FRITZ!Box
# ones) and Tailscale's MagicDNS.
_PRIVATE_SUFFIXES = (
    ".local",
    ".lan",
    ".home",
    ".home.arpa",
    ".internal",
    ".fritz.box",
    ".ts.net",
)


def _is_local_name(host: str) -> bool:
    """A name only this network can resolve: `nas.local`, `nas.lan` or a bare `nas`.

    A rebinding page needs a name the attacker controls in public DNS, and none of these
    can be one: the private-use suffixes never leave the network (or, for .ts.net, are
    handed out only by Tailscale), and public names always have a dot. NAS boxes and
    routers are opened exactly this way (umbrel.local, nas, fritz.box), and got a 400
    until someone found VINTED_BOT_WEB_ALLOWED_HOSTS.
    """
    name = host.rstrip(".")
    if not name or ":" in name:
        return False
    # The leading dot lets the router's own name, fritz.box, count as well as its devices.
    return "." not in name or f".{name}".endswith(_PRIVATE_SUFFIXES)


def host_allowed(host: str, allowed: frozenset[str]) -> bool:
    return host in allowed or _is_ip_address(host) or _is_local_name(host)


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


async def _matches(password: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt = stored.split("$", 1)[0]
    candidate = await asyncio.to_thread(_fingerprint, password, salt)
    return hmac.compare_digest(candidate, stored)


async def sync_password(repo: Repo, password: SecretStr | None) -> None:
    """Revoke every session if the environment's password is not the one they were
    issued under.

    Run once when the dashboard starts, which is the only time that password can change.
    """
    if password is None:
        return
    secret = password.get_secret_value()
    if await _matches(secret, await repo.get_state_value(_ENV_PASSWORD_KEY)):
        return
    fresh = await asyncio.to_thread(_fingerprint, secret, secrets.token_hex(16))
    await repo.set_state_value(_SESSIONS_KEY, "{}")
    await repo.set_state_value(_ENV_PASSWORD_KEY, fresh)


# --- The password -------------------------------------------------------------------


def password_from_env(settings: Settings) -> bool:
    return settings.web_auth_token is not None


async def password_required(settings: Settings, repo: Repo) -> bool:
    if settings.web_auth_token is not None:
        return True
    return await repo.get_state_value(_PASSWORD_KEY) is not None


async def password_matches(settings: Settings, repo: Repo, password: str) -> bool:
    if settings.web_auth_token is not None:
        expected = settings.web_auth_token.get_secret_value()
        return hmac.compare_digest(password.encode(), expected.encode())
    return await _matches(password, await repo.get_state_value(_PASSWORD_KEY))


def suggest_password() -> str:
    """A strong password that is easy to type on a phone, like `k7qm-4tzr-p9xe`."""
    groups = ("".join(secrets.choice(_FRIENDLY) for _ in range(4)) for _ in range(3))
    return "-".join(groups)


def check_new_password(password: str) -> str:
    """A new password as typed, or InvalidInputError saying what is wrong with it."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInputError(
            "new_password",
            f"Use at least {MIN_PASSWORD_LENGTH} characters. The suggested one is easy to "
            "type and hard to guess.",
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidInputError("new_password", "That's longer than a password needs to be.")
    return password


async def set_password(repo: Repo, password: str | None) -> None:
    """Set, change or (with None) remove the dashboard's own password.

    Every signed-in browser is signed out either way: a password change is often made
    because someone else knew the old one.
    """
    if password is None:
        await repo.delete_state_value(_PASSWORD_KEY)
    else:
        fresh = await asyncio.to_thread(_fingerprint, password, secrets.token_hex(16))
        await repo.set_state_value(_PASSWORD_KEY, fresh)
    await repo.set_state_value(_SESSIONS_KEY, "{}")


# --- Who can connect ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Access:
    """Who can open the dashboard, and whether the environment decided each part."""

    host: str
    host_from_env: bool
    password: bool
    password_from_env: bool
    container: bool

    @property
    def loopback(self) -> bool:
        """Only this computer can connect."""
        return self.host in LOOPBACK_HOSTS

    @property
    def exposed_without_password(self) -> bool:
        """Other machines could connect, with no sign-in.

        Inside a container this stays quiet: 0.0.0.0 is the only bind that works there,
        and the port mapping, which the app cannot see, decides who can connect.
        """
        return not self.password and not self.loopback and not self.container


async def access(settings: Settings, repo: Repo) -> Access:
    return Access(
        host=await managed.web_host(settings, repo),
        host_from_env=managed.web_host_from_env(settings),
        password=await password_required(settings, repo),
        password_from_env=password_from_env(settings),
        container=in_container(),
    )


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
