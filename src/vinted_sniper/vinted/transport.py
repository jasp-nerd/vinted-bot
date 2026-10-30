"""How bytes get to Vinted and back.

Everything above this file works against the `Transport` protocol, which is what makes the
HTTP client a swappable detail. Plain httpx is the default and, at the polling rates this
app uses, it is enough. If that changes, `CurlCffiTransport` presents a browser's TLS
fingerprint instead, and nothing else in the codebase has to know.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Protocol, Self, runtime_checkable
from urllib.parse import urljoin

import httpx

# Browsers give up around twenty; Vinted's own chains are one or two hops (bare domain to
# www, item id to slug). Anything longer is a loop.
_MAX_REDIRECTS: Final = 5
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True, slots=True)
class Response:
    """Just the parts of a response this app cares about."""

    status_code: int
    text: str
    headers: dict[str, str]
    cookies: dict[str, str]

    def json(self) -> Any:
        return json.loads(self.text)


class TransportError(Exception):
    """The request never produced a response: DNS, TLS, timeout, connection reset."""


@runtime_checkable
class Transport(Protocol):
    """The whole surface the rest of the app needs from an HTTP client."""

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        cookies: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response: ...

    async def aclose(self) -> None: ...


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


# One hop of a request: URL, headers (Cookie included), params -> response, Set-Cookie.
_SendOnce = Callable[
    [str, dict[str, str], dict[str, str] | None], Awaitable[tuple[Response, dict[str, str]]]
]


async def follow(
    send_once: _SendOnce,
    url: str,
    *,
    headers: dict[str, str],
    cookies: dict[str, str] | None,
    params: dict[str, str] | None,
    follow_redirects: bool,
) -> Response:
    """Run a GET, following redirects by hand so the cookies stay ours.

    Both HTTP clients keep a cookie jar of their own and use it in place of the Cookie
    header on every redirect hop. A shared jar outlives the session it came from, so a
    "fresh" session would go out carrying the old one's token as well. Following hops
    here means the only cookies sent are the session's plus whatever this very request
    was given along the way, and the caller gets every cookie set on any hop, not just
    the last one.
    """
    jar = dict(cookies or {})
    collected: dict[str, str] = {}
    for _ in range(_MAX_REDIRECTS + 1):
        hop_headers = dict(headers)
        if jar:
            hop_headers["Cookie"] = cookie_header(jar)
        response, set_cookies = await send_once(url, hop_headers, params)
        jar.update(set_cookies)
        collected.update(set_cookies)
        location = response.headers.get("location")
        if not follow_redirects or response.status_code not in _REDIRECT_STATUSES or not location:
            return Response(
                status_code=response.status_code,
                text=response.text,
                headers=response.headers,
                cookies=collected,
            )
        # The redirect target carries its own query string; ours belonged to the first URL.
        url, params = urljoin(url, location), None
    raise TransportError(f"more than {_MAX_REDIRECTS} redirects starting from {url}")


class _RefuseAllCookies(DefaultCookiePolicy):
    """A cookie policy that stores nothing, so the client's own jar stays empty."""

    def set_ok(self, cookie: Any, request: Any) -> bool:
        del cookie, request
        return False


class HttpxTransport:
    """The default client.

    One connection pool for the process, so TLS handshakes and HTTP/2 connections are
    reused rather than rebuilt on every poll.
    """

    def __init__(self, timeout: float = 15.0, proxy: str | None = None) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy,
            follow_redirects=False,
            # Cookies are held by the session layer, which persists them across restarts.
            # A jar that refuses everything keeps httpx from becoming a second source of
            # truth that leaks one session's cookies into the next.
            cookies=httpx.Cookies(CookieJar(policy=_RefuseAllCookies())),
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        cookies: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response:
        return await follow(
            self._send_once,
            url,
            headers=headers,
            cookies=cookies,
            params=params,
            follow_redirects=follow_redirects,
        )

    async def _send_once(
        self, url: str, headers: dict[str, str], params: dict[str, str] | None
    ) -> tuple[Response, dict[str, str]]:
        try:
            response = await self._client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise TransportError(str(exc)) from exc

        set_cookies = dict(response.cookies)
        return (
            Response(
                status_code=response.status_code,
                text=response.text,
                headers={k.lower(): v for k, v in response.headers.items()},
                cookies=set_cookies,
            ),
            set_cookies,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class CurlCffiTransport:
    """Optional client that reproduces a real browser's TLS handshake.

    Only worth reaching for if plain requests start coming back 403 while the same search
    loads fine in your browser. Needs the `impersonate` extra.
    """

    def __init__(
        self, timeout: float = 15.0, proxy: str | None = None, impersonate: str = "chrome"
    ) -> None:
        try:
            from curl_cffi import requests as curl_requests  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "VINTED_SNIPER_HTTP_IMPERSONATE is on but curl_cffi is not installed. "
                "Install it with: uv sync --extra impersonate"
            ) from exc

        self._session = curl_requests.AsyncSession(
            timeout=timeout,
            proxy=proxy,
            impersonate=impersonate,
            # Same reason as the httpx jar: cookies belong to the session layer.
            discard_cookies=True,
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        cookies: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response:
        return await follow(
            self._send_once,
            url,
            headers=headers,
            cookies=cookies,
            params=params,
            follow_redirects=follow_redirects,
        )

    async def _send_once(
        self, url: str, headers: dict[str, str], params: dict[str, str] | None
    ) -> tuple[Response, dict[str, str]]:
        try:
            response = await self._session.get(
                url, headers=headers, params=params, allow_redirects=False
            )
        except Exception as exc:  # curl_cffi raises its own error hierarchy
            raise TransportError(str(exc)) from exc
        set_cookies = dict(response.cookies)
        return (
            Response(
                status_code=response.status_code,
                text=response.text,
                headers={k.lower(): v for k, v in response.headers.items() if v is not None},
                cookies=set_cookies,
            ),
            set_cookies,
        )

    async def aclose(self) -> None:
        await self._session.close()


@dataclass
class MockTransport:
    """Replays responses from disk.

    Used by the test suite and by `FETCH_MODE=mock`, so you can develop against a recorded
    catalog — or a recorded 403 — without touching the real site.

    A scenario directory holds JSON files describing responses, one per kind of request:
    `catalog.json` (search), `user.json` (member profile), `wardrobe.json` (a member's
    listings), `item.json` (an item page), `filters.json` (filter options) and `root.json`
    (any other page, the homepage included). Each may instead be a list, in which case
    successive calls walk through it and the last entry repeats.
    """

    scenario_dir: Path
    _cursors: dict[str, int] = field(default_factory=dict)

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        cookies: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response:
        del headers, cookies, params, follow_redirects
        name = _scenario_name(url)
        path = self.scenario_dir / f"{name}.json"
        if not path.exists():
            raise TransportError(f"mock scenario has no {path.name} for {url}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            index = min(self._cursors.get(name, 0), len(payload) - 1)
            self._cursors[name] = index + 1
            payload = payload[index]

        body = payload.get("body", {})
        return Response(
            status_code=int(payload.get("status", 200)),
            text=body if isinstance(body, str) else json.dumps(body),
            headers={k.lower(): v for k, v in payload.get("headers", {}).items()},
            cookies=payload.get("cookies", {}),
        )

    async def aclose(self) -> None:
        return None


def _scenario_name(url: str) -> str:
    for marker, name in (
        ("/svc-catalogue/", "catalog"),
        ("/svc-filters/", "filters"),
        ("/api/v2/users/", "user"),
        ("/api/v2/wardrobe/", "wardrobe"),
        ("/items/", "item"),
    ):
        if marker in url:
            return name
    return "root"


def build_transport(
    *,
    impersonate: bool,
    timeout: float,
    proxy: str | None = None,
    mock_dir: Path | None = None,
) -> Transport:
    """Pick the client to use, given how the app is configured."""
    if mock_dir is not None:
        return MockTransport(scenario_dir=mock_dir)
    if impersonate:
        return CurlCffiTransport(timeout=timeout, proxy=proxy)
    return HttpxTransport(timeout=timeout, proxy=proxy)


class TransportPool:
    """One transport per route out.

    Without proxies this is a single client, which is the common case. With proxies it is
    one per proxy, built the first time that proxy is used and kept afterwards, so a
    connection pool is not thrown away every time a session rotates.
    """

    def __init__(self, build: Callable[[str | None], Transport]) -> None:
        self._build = build
        self._transports: dict[str | None, Transport] = {}

    def get(self, proxy: str | None = None) -> Transport:
        transport = self._transports.get(proxy)
        if transport is None:
            transport = self._build(proxy)
            self._transports[proxy] = transport
        return transport

    async def aclose(self) -> None:
        for transport in self._transports.values():
            with contextlib.suppress(Exception):
                await transport.aclose()
        self._transports.clear()


class TransportSession:
    """Owns a transport for the lifetime of a `with` block."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    async def __aenter__(self) -> Transport:
        return self.transport

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.transport.aclose()

    @classmethod
    def build(
        cls,
        *,
        impersonate: bool,
        timeout: float,
        proxy: str | None = None,
        mock_dir: Path | None = None,
    ) -> Self:
        return cls(
            build_transport(
                impersonate=impersonate, timeout=timeout, proxy=proxy, mock_dir=mock_dir
            )
        )
