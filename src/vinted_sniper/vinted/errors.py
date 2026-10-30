"""What can go wrong when talking to Vinted.

These are separate types because each one calls for a different response, and conflating
them is how the other tools in this space ended up retrying their way into longer blocks.
"""

from __future__ import annotations


class VintedError(Exception):
    """Base class for everything in this module.

    Carries the HTTP status when there was one, so a diagnosis can say what Vinted
    actually answered rather than guessing from the type.
    """

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthExpiredError(VintedError):
    """The session cookie is no longer accepted.

    Cheap to fix: throw the session away and load the homepage again. Vinted returns this
    as a 401 with code 100, usually after the anonymous token quietly ages out.
    """


class BlockedError(VintedError):
    """Vinted is refusing this client, not this request.

    A fresh cookie will not help — the refusal is aimed at the address or the TLS
    fingerprint. The only useful responses are to slow down, rotate the session, or go out
    through a different address.
    """


class RateLimitedError(VintedError):
    """Too many requests. Vinted usually says how long to wait."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        wait = f" for {retry_after:.0f}s" if retry_after else ""
        super().__init__(f"rate limited{wait}", status_code=429)


class MalformedResponseError(VintedError):
    """A 200 that is not the catalog payload we expect.

    Worth its own type: it usually means the response shape changed, which needs a code
    fix, not a retry.
    """


class ApiChangedError(MalformedResponseError):
    """An endpoint we rely on answered 404: Vinted moved or removed it.

    Not transient, and not something a retry or a new session fixes. It needs a new
    version of this app, so it is reported loudly instead of looking like a network blip.
    """


class InvalidSearchError(MalformedResponseError):
    """Vinted refused the search's parameters (HTTP 400).

    The search itself needs editing; asking again with the same filters gets the same
    answer.
    """


class NetworkError(VintedError):
    """The request never completed. Almost always transient."""
