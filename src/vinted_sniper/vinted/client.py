"""Talking to Vinted: searches, members, wardrobes, item pages, and a health check.

Every call goes through `_request`, so they all share the session, the route out, the
cookie bookkeeping and the error types. The care goes into reading responses: a 200
from Vinted is not a promise that the body is what was asked for, and the tools that
assumed it was are the ones whose issue trackers fill up with tracebacks.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, Final, Literal, TypeVar

from vinted_sniper.log import get_logger
from vinted_sniper.vinted import headers as hdr
from vinted_sniper.vinted import urls
from vinted_sniper.vinted.errors import (
    ApiChangedError,
    AuthExpiredError,
    BlockedError,
    InvalidSearchError,
    MalformedResponseError,
    NetworkError,
    RateLimitedError,
    VintedError,
)
from vinted_sniper.vinted.item_page import parse_item_page
from vinted_sniper.vinted.models import (
    Diagnosis,
    Item,
    ItemSnapshot,
    ParseError,
    SellerProfile,
    parse_item,
    parse_seller,
)
from vinted_sniper.vinted.session import SessionManager
from vinted_sniper.vinted.transport import Response, Transport, TransportError

log = get_logger(__name__)

# Vinted's own frontend sends a timestamp slightly behind the wall clock. Matching that,
# jitter included, is free and keeps our requests from looking machine-timed.
_TIME_SKEW_RANGE_S = (0, 180)

# Vinted's ways of saying "your token is no longer valid" inside a body: the numeric code
# of /api/v2, and the string code of the svc-* services.
_INVALID_TOKEN_CODES: Final = frozenset({100, "UNAUTHORIZED"})

# The site caps this well below what you might ask for; 96 is what its own pages request.
PER_PAGE = 96

# A deleted listing's page answers 404; one taken down by Vinted can answer 410.
_GONE_STATUSES: Final = frozenset({HTTPStatus.NOT_FOUND, HTTPStatus.GONE})

_RequestStyle = Literal["catalogue", "api", "page"]
_T = TypeVar("_T")


class VintedClient:
    """Reads search results, members and listings from one or more Vinted country sites."""

    def __init__(
        self,
        transport: Transport | None,
        sessions: SessionManager,
        *,
        keep_raw: bool = False,
        rng: random.Random | None = None,
    ) -> None:
        self._transport = transport
        self._sessions = sessions
        self._keep_raw = keep_raw
        self._rng = rng or random.Random()

    async def search(self, tld: str, params: dict[str, str]) -> list[Item]:
        """Return the current first page of a search, newest first.

        `params` are a stored search's parameters (see `urls.parse_search_params`); they
        are translated to the search service's names here, on every request, so searches
        saved before Vinted renamed its filters keep working.

        Raises the error types in `errors.py`; the poller decides what each one means for
        the session and the schedule.
        """
        return await self._search(tld, params, per_page=PER_PAGE)

    async def _search(self, tld: str, params: dict[str, str], *, per_page: int) -> list[Item]:
        query = urls.catalogue_params(params)
        query["per_page"] = str(per_page)
        query["time"] = str(int(time.time()) - self._rng.randint(*_TIME_SKEW_RANGE_S))
        return await self._request(
            tld, urls.catalog_endpoint(tld), "catalogue", query, self._read_items(tld)
        )

    async def seller(self, tld: str, seller_id: int) -> SellerProfile | None:
        """A member's country, rating and review count, or None if the member is gone.

        Answered anonymously by `/api/v2/users/{id}`. A refusal (403, 429) is raised, not
        turned into None: "we could not look" and "there is nothing to see" call for
        different things from a cache.
        """
        return await self._request(
            tld,
            urls.user_endpoint(tld, seller_id),
            "api",
            {"localize": "false"},
            lambda response: _read_seller(response, tld),
            gone_ok=True,
        )

    async def seller_items(self, tld: str, seller_id: int, per_page: int = 20) -> list[Item]:
        """A member's listings, newest upload first. Empty if the member is gone.

        Read from the member's wardrobe, which (unlike search) still carries each
        listing's photo time, every photo, and brand, size and condition as fields.
        """
        read_items = self._read_items(tld)
        return await self._request(
            tld,
            urls.wardrobe_endpoint(tld, seller_id),
            "api",
            {"page": "1", "per_page": str(per_page), "order": "newest_first"},
            lambda response: [] if response.status_code in _GONE_STATUSES else read_items(response),
            gone_ok=True,
        )

    async def item_snapshot(self, tld: str, item_id: int) -> ItemSnapshot:
        """Re-read a listing from its public page: price, availability, full details.

        A listing whose page is gone (404/410) comes back with status 'gone' rather than
        an error, because for a watcher that is an answer, not a failure.
        """

        def read(response: Response) -> ItemSnapshot:
            if response.status_code in _GONE_STATUSES:
                return ItemSnapshot(item_id=item_id, tld=tld, status="gone")
            return parse_item_page(response.text, tld, item_id)

        return await self._request(
            tld, urls.item_url(tld, item_id), "page", None, read, gone_ok=True
        )

    def _read_items(self, tld: str) -> Callable[[Response], list[Item]]:
        return lambda response: _parse_items(response, tld, keep_raw=self._keep_raw)

    async def diagnose(self, tld: str) -> Diagnosis:
        """Check, step by step, whether this computer can use Vinted, and say so plainly.

        Never raises for anything Vinted or the network does: the point is to turn those
        failures into a sentence the dashboard can show.
        """
        started = time.monotonic()
        site = f"vinted.{tld}"

        def finish(*, reachable: bool, session: bool, catalog: bool, **rest: Any) -> Diagnosis:
            return Diagnosis(
                tld=tld,
                reachable=reachable,
                got_session_cookie=session,
                catalog_ok=catalog,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                **rest,
            )

        try:
            await self._sessions.get(tld)
        except BlockedError as exc:
            return finish(
                reachable=True,
                session=False,
                catalog=False,
                http_status=exc.status_code,
                problem="blocked",
                message=(
                    f"{site} answered, but would not start a session for this computer. Your "
                    "IP address looks blocked or challenged by Vinted. That is about the "
                    "network you are on, not your searches; see the troubleshooting guide."
                ),
            )
        except NetworkError as exc:
            return finish(
                reachable=exc.status_code is not None,
                session=False,
                catalog=False,
                http_status=exc.status_code,
                problem="offline" if exc.status_code is None else "unexpected",
                message=_unreachable_message(site, exc),
            )

        try:
            await self._diagnostic_search(tld)
        except VintedError as exc:
            problem, message = _catalog_failure(site, exc)
            return finish(
                reachable=True,
                session=True,
                catalog=False,
                http_status=exc.status_code,
                problem=problem,
                message=message,
            )
        return finish(
            reachable=True,
            session=True,
            catalog=True,
            http_status=HTTPStatus.OK,
            message=f"{site} is reachable from this computer and searches work.",
        )

    async def _diagnostic_search(self, tld: str) -> None:
        """One small unfiltered search, renewing an expired session once on the way."""
        params = {"order": "newest_first"}
        try:
            await self._search(tld, params, per_page=1)
        except AuthExpiredError:
            await self._sessions.invalidate(tld)
            await self._search(tld, params, per_page=1)

    async def _request(
        self,
        tld: str,
        url: str,
        style: _RequestStyle,
        params: dict[str, str] | None,
        read: Callable[[Response], _T],
        *,
        gone_ok: bool = False,
    ) -> _T:
        """One GET through the site's session, read by `read`, with errors typed.

        `gone_ok` lets 404 and 410 through to `read` for callers to whom "not there" is
        an answer. A refusal, whether in the status or in the body, marks the session as
        failed so that replacing it is not mistaken for a replacement already done.
        """
        session = await self._sessions.get(tld)
        transport = self._transport or self._sessions.transport_for(session)
        if style == "catalogue":
            headers = hdr.catalogue_headers(
                tld, session.identity, locale=session.locale, anon_id=session.anon_id
            )
        elif style == "api":
            headers = hdr.api_headers(tld, session.identity, referer=urls.site_root(tld))
        else:
            headers = hdr.page_headers(tld, session.identity)

        try:
            response = await transport.get(
                url, headers=headers, cookies=session.cookie_header, params=params
            )
        except TransportError as exc:
            raise NetworkError(str(exc)) from exc

        try:
            if not (gone_ok and response.status_code in _GONE_STATUSES):
                raise_for_status(response, tld)
            await self._sessions.note_request(session)
            await self._sessions.merge_cookies(session, response.cookies)
            return read(response)
        except (AuthExpiredError, BlockedError):
            session.failed = True
            raise


def raise_for_status(response: Response, tld: str) -> None:
    """Turn an HTTP status into the error type that says what to do about it."""
    status = response.status_code

    if status == HTTPStatus.OK:
        return

    if status == HTTPStatus.UNAUTHORIZED:
        raise AuthExpiredError(f"vinted.{tld} rejected the session token", status_code=status)

    if status in (HTTPStatus.FORBIDDEN, HTTPStatus.PROXY_AUTHENTICATION_REQUIRED):
        raise BlockedError(f"vinted.{tld} refused the request with {status}", status_code=status)

    if status == HTTPStatus.TOO_MANY_REQUESTS:
        raise RateLimitedError(_retry_after(response))

    if status == HTTPStatus.NOT_FOUND:
        raise ApiChangedError(
            f"vinted.{tld} answered 404 where this app expects data: Vinted has moved or "
            "removed it, and the app needs an update",
            status_code=status,
        )

    if status == HTTPStatus.BAD_REQUEST:
        raise InvalidSearchError(
            f"vinted.{tld} refused the request's parameters "
            f"({_error_message(response) or 'no reason given'}); check the search's filters",
            status_code=status,
        )

    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise NetworkError(f"vinted.{tld} returned {status}", status_code=status)

    raise NetworkError(f"vinted.{tld} returned an unexpected {status}", status_code=status)


def _error_message(response: Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    message = payload.get("message") if isinstance(payload, dict) else None
    return message if isinstance(message, str) else None


def _unreachable_message(site: str, exc: NetworkError) -> str:
    if exc.status_code is None:
        return (
            f"This computer could not connect to {site}. Check the internet connection, "
            "and any proxy set in the app's settings."
        )
    return (
        f"{site} answered its homepage with an error ({exc.status_code}). This is usually "
        "temporary on Vinted's side; try again in a few minutes."
    )


def _catalog_failure(site: str, exc: VintedError) -> tuple[str, str]:
    """The problem code and the sentence for a search that failed after a session worked."""
    if isinstance(exc, BlockedError):
        return "blocked", (
            f"{site} gave this computer a session but refused its search. Your IP address "
            "looks blocked or challenged by Vinted; see the troubleshooting guide."
        )
    if isinstance(exc, RateLimitedError):
        return "rate_limited", (
            f"{site} says too many requests came from this address. Wait a few minutes; "
            "checking searches less often helps."
        )
    if isinstance(exc, ApiChangedError):
        return "api_changed", (
            f"{site} no longer answers searches where this app asks. Vinted has changed its "
            "site; update the app to the latest version."
        )
    if isinstance(exc, NetworkError) and exc.status_code is None:
        return "offline", (
            f"This computer reached {site} but the search request did not complete. Check "
            "the connection and try again."
        )
    return "unexpected", (
        f"{site} answered the search with something unexpected ({exc}). If this keeps "
        "happening, update the app."
    )


def _retry_after(response: Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _json_object(response: Response, tld: str) -> dict[str, Any]:
    """The body as a JSON object, refusing anything else."""
    try:
        payload: Any = response.json()
    except ValueError as exc:
        # Most often this is an anti-bot interstitial served with a 200.
        preview = response.text[:200].replace("\n", " ")
        raise MalformedResponseError(f"vinted.{tld} did not return JSON: {preview!r}") from exc

    if not isinstance(payload, dict):
        raise MalformedResponseError(
            f"vinted.{tld} returned {type(payload).__name__}, expected an object"
        )
    return payload


def _read_seller(response: Response, tld: str) -> SellerProfile | None:
    if response.status_code in _GONE_STATUSES:
        return None
    user = _json_object(response, tld).get("user")
    if not isinstance(user, dict):
        raise MalformedResponseError(f"vinted.{tld} returned a member without a user object")
    try:
        return parse_seller(user, tld)
    except ParseError as exc:
        message = f"vinted.{tld} returned an unusable member: {exc}"
        raise MalformedResponseError(message) from exc


def _parse_items(response: Response, tld: str, *, keep_raw: bool) -> list[Item]:
    """Read a list of listings (search or wardrobe), refusing anything that is not one."""
    payload = _json_object(response, tld)

    if (message := payload.get("message")) and "items" not in payload:
        if payload.get("code") in _INVALID_TOKEN_CODES:
            raise AuthExpiredError(f"vinted.{tld} says: {message}")
        raise MalformedResponseError(f"vinted.{tld} says: {message}")

    raw_items = payload.get("items")
    if raw_items is None:
        raise MalformedResponseError(
            f"vinted.{tld} returned no items field; keys were {sorted(payload)[:8]}"
        )
    if not isinstance(raw_items, list):
        raise MalformedResponseError(
            f"vinted.{tld} returned items as {type(raw_items).__name__}, expected a list"
        )

    items: list[Item] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(parse_item(entry, tld, keep_raw=keep_raw))
        except ParseError as exc:
            # One malformed listing should not cost you the other ninety-five.
            log.warning("item.unparsed", tld=tld, error=str(exc))
    return items
