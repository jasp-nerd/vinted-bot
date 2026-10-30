"""Everything that touches Vinted: URLs, sessions, the requests, and the shapes they return."""

from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.errors import (
    ApiChangedError,
    AuthExpiredError,
    BlockedError,
    InvalidSearchError,
    MalformedResponseError,
    NetworkError,
    RateLimitedError,
    VintedError,
)
from vinted_bot.vinted.models import Diagnosis, Item, ItemSnapshot, SellerProfile, parse_item
from vinted_bot.vinted.session import Session, SessionManager

__all__ = [
    "ApiChangedError",
    "AuthExpiredError",
    "BlockedError",
    "Diagnosis",
    "InvalidSearchError",
    "Item",
    "ItemSnapshot",
    "MalformedResponseError",
    "NetworkError",
    "RateLimitedError",
    "SellerProfile",
    "Session",
    "SessionManager",
    "VintedClient",
    "VintedError",
    "parse_item",
]
