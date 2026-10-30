"""Anonymous sessions.

Vinted hands a session cookie to anyone who loads the site. That cookie is all the catalog
API asks for, which is why this app never logs in and never touches an account: there is no
password to store, nothing to get locked out of, and nothing for Vinted to sanction beyond
an address.

Sessions are kept in the database so a restart does not mean a fresh handshake with every
country site, and are replaced on a timer because refusals track how long a session has
been alive more than how fast it is used.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

from vinted_bot.db import Database
from vinted_bot.log import get_logger
from vinted_bot.vinted import headers as hdr
from vinted_bot.vinted import urls
from vinted_bot.vinted.errors import BlockedError, NetworkError
from vinted_bot.vinted.proxies import QUARANTINE_BLOCKED_S, QUARANTINE_NETWORK_S, ProxyRotation
from vinted_bot.vinted.transport import Transport, TransportError, TransportPool

log = get_logger(__name__)

# The cookie the catalog API actually checks. We keep the whole jar anyway — the site sets
# others that travel with it, and dropping them makes the request look assembled by hand.
SESSION_COOKIE = "access_token_web"

# Set by the homepage alongside the token. The search service wants the first echoed back
# as X-Anon-Id and the second as Locale, which is what picks the market and currency.
ANON_ID_COOKIE = "anon_id"
LOCALE_COOKIE = "anonymous-iso-locale"

# Several searches on one site hit the same refusal at once, and each asks for a new
# session. A session younger than this that has not itself been refused was minted in
# answer to that same refusal, so replacing it again would only multiply homepage loads
# at the worst possible moment.
_JUST_MINTED_S: Final = 30


@dataclass(slots=True)
class Session:
    """One country site's anonymous session."""

    tld: str
    cookies: dict[str, str]
    identity: hdr.BrowserIdentity
    created_at: int
    request_count: int = 0
    # The route this session's cookie was minted through. Replaying it from somewhere else
    # is the kind of inconsistency anti-bot systems look for, so it travels with it.
    proxy: str | None = None
    # Set when Vinted refused a request made with this session (401 or 403). Lets
    # `invalidate` and `rotate` tell the refused session from its replacement.
    failed: bool = False

    def age_s(self, now: int | None = None) -> int:
        return (now if now is not None else int(time.time())) - self.created_at

    @property
    def cookie_header(self) -> dict[str, str]:
        return dict(self.cookies)

    @property
    def anon_id(self) -> str | None:
        return self.cookies.get(ANON_ID_COOKIE)

    @property
    def locale(self) -> str:
        """The locale the site chose for this visitor, e.g. 'pl-PL'."""
        return self.cookies.get(LOCALE_COOKIE) or hdr.fallback_locale(self.tld)


class SessionManager:
    """Creates, stores and replaces anonymous sessions, one per country site."""

    def __init__(
        self,
        db: Database,
        transport: Transport | TransportPool,
        *,
        rotate_after_minutes: int = 60,
        proxies: ProxyRotation | None = None,
    ) -> None:
        self._db = db
        self._pool: TransportPool | None = None
        self._transport: Transport | None = None
        if isinstance(transport, TransportPool):
            self._pool = transport
        else:
            self._transport = transport
        self._rotate_after_s = rotate_after_minutes * 60
        self._proxies = proxies or ProxyRotation()
        self._cache: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, tld: str) -> asyncio.Lock:
        return self._locks.setdefault(tld, asyncio.Lock())

    def transport_for(self, session: Session) -> Transport:
        """The client that reaches Vinted the same way this session was created."""
        if self._pool is not None:
            return self._pool.get(session.proxy)
        if self._transport is None:  # pragma: no cover - one of the two is always set
            raise RuntimeError("SessionManager was built without a transport")
        return self._transport

    async def get(self, tld: str) -> Session:
        """Return a usable session for a site, creating or replacing it as needed.

        Creation is serialised per site: ten searches starting together on vinted.it
        should cost one homepage load, not ten in the same second.
        """
        if (session := self._usable(self._cache.get(tld))) is not None:
            return session
        async with self._lock(tld):
            session = self._usable(self._cache.get(tld)) or self._usable(await self._load(tld))
            if session is None:
                session = await self.bootstrap(tld)
            self._cache[tld] = session
            return session

    def _usable(self, session: Session | None) -> Session | None:
        if session is not None and session.age_s() >= self._rotate_after_s:
            log.info("session.expired", tld=session.tld, age_s=session.age_s())
            return None
        return session

    async def invalidate(self, tld: str) -> None:
        """Drop a session so the next call starts a new one.

        If the current session is not the one that was refused but one minted moments
        ago, it is kept: it is the answer to the very failure being reported, already
        obtained by another search on the same site.
        """
        async with self._lock(tld):
            await self._drop(tld)

    async def rotate(self, tld: str, *, blocked: bool = False) -> Session:
        """Replace a session outright, with a different browser persona.

        When the old one was refused rather than merely old, its route is set aside too:
        a new cookie down the same blocked path buys nothing. A replacement minted moments
        ago is kept, as in `invalidate`.
        """
        await self.discard(tld, blocked=blocked)
        return await self.get(tld)

    async def discard(self, tld: str, *, blocked: bool = False) -> None:
        """Drop a refused session without minting its replacement.

        Like `rotate`, but the homepage load is left to whoever next needs the site. A
        poller that has just been refused would otherwise make that load from inside its
        error handler, where a homepage that refuses too has nowhere to go.
        """
        async with self._lock(tld):
            previous = await self._drop(tld)
            if blocked and previous is not None:
                self._proxies.bench(previous.proxy, QUARANTINE_BLOCKED_S, "refused by Vinted")

    async def _drop(self, tld: str) -> Session | None:
        """Forget the current session unless it is a fresh replacement. Returns it if dropped."""
        current = self._cache.get(tld)
        if current is not None and not current.failed and current.age_s() < _JUST_MINTED_S:
            log.debug("session.already_replaced", tld=tld, age_s=current.age_s())
            return None
        self._cache.pop(tld, None)
        await self._db.execute("DELETE FROM sessions WHERE tld = ?", (tld,))
        return current

    async def bootstrap(self, tld: str) -> Session:
        """Load the site's homepage the way a browser would, and keep what it sets."""
        identity = hdr.pick_identity()
        proxy = self._proxies.acquire()
        root = urls.site_root(tld)
        transport = self._pool.get(proxy) if self._pool is not None else self._transport
        if transport is None:  # pragma: no cover - one of the two is always set
            raise RuntimeError("SessionManager was built without a transport")

        try:
            response = await transport.get(
                root,
                headers=hdr.document_headers(tld, identity),
                follow_redirects=True,
            )
        except TransportError as exc:
            self._proxies.bench(proxy, QUARANTINE_NETWORK_S, "could not connect")
            raise NetworkError(f"could not reach {root}: {exc}") from exc

        if response.status_code == HTTPStatus.FORBIDDEN:
            self._proxies.bench(proxy, QUARANTINE_BLOCKED_S, "refused at the homepage")
            raise BlockedError(
                f"vinted.{tld} refused the connection before we could get a session. "
                "This is usually the address you are coming from rather than the app; "
                "see docs/troubleshooting.md.",
                status_code=response.status_code,
            )
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            raise NetworkError(
                f"vinted.{tld} answered {response.status_code} on the homepage",
                status_code=response.status_code,
            )

        cookies = dict(response.cookies)
        if SESSION_COOKIE not in cookies:
            raise BlockedError(
                f"vinted.{tld} served a page but set no {SESSION_COOKIE} cookie. "
                "Run the check in docs/troubleshooting.md to see whether your address is "
                "being challenged.",
                status_code=response.status_code,
            )

        session = Session(
            tld=tld,
            cookies=cookies,
            identity=identity,
            created_at=int(time.time()),
            proxy=proxy,
        )
        await self._save(session)
        self._cache[tld] = session
        log.info("session.created", tld=tld, cookies=len(cookies), via_proxy=proxy is not None)
        return session

    async def note_request(self, session: Session) -> None:
        """Record that a session was used. Cheap bookkeeping the health view reads."""
        session.request_count += 1
        await self._db.execute(
            "UPDATE sessions SET last_used_at = ?, request_count = ? WHERE tld = ?",
            (int(time.time()), session.request_count, session.tld),
        )

    async def merge_cookies(self, session: Session, new_cookies: dict[str, str]) -> None:
        """Fold cookies from a response back into the stored session."""
        if not new_cookies:
            return
        session.cookies.update(new_cookies)
        await self._save(session)

    async def _save(self, session: Session) -> None:
        await self._db.execute(
            "INSERT INTO sessions (tld, cookies_json, user_agent, created_at, last_used_at, "
            "request_count) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tld) DO UPDATE SET cookies_json = excluded.cookies_json, "
            "user_agent = excluded.user_agent, created_at = excluded.created_at, "
            "last_used_at = excluded.last_used_at, request_count = excluded.request_count",
            (
                session.tld,
                json.dumps(session.cookies),
                session.identity.user_agent,
                session.created_at,
                int(time.time()),
                session.request_count,
            ),
        )

    async def _load(self, tld: str) -> Session | None:
        row = await self._db.fetch_one(
            "SELECT cookies_json, user_agent, created_at, request_count FROM sessions "
            "WHERE tld = ?",
            (tld,),
        )
        if row is None:
            return None

        try:
            cookies = json.loads(row["cookies_json"])
        except json.JSONDecodeError:
            await self._db.execute("DELETE FROM sessions WHERE tld = ?", (tld,))
            return None

        if not isinstance(cookies, dict) or SESSION_COOKIE not in cookies:
            await self._db.execute("DELETE FROM sessions WHERE tld = ?", (tld,))
            return None

        return Session(
            tld=tld,
            cookies=cookies,
            identity=hdr.identity_for_user_agent(row["user_agent"]),
            created_at=int(row["created_at"]),
            request_count=int(row["request_count"]),
        )
