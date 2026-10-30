"""Turning a pasted Vinted search URL into something we can poll.

Users paste whatever is in their address bar. That URL carries tracking parameters that
change on every page load, sometimes points at a brand or category page rather than a
search, and always belongs to one country's site. This module reduces all of that to a
canonical URL (used as the uniqueness key for a search) plus the parameters to store.

The stored parameters keep the address bar's vocabulary (`catalog_ids`, `brand_ids`,
`size_ids`...) rather than the API's. Vinted renamed every filter when it moved search to
`svc-catalogue` in September 2026, and the names will move again; translating at request
time in `catalogue_params` means a rename touches one function instead of every stored
search.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlparse

# Vinted runs one site per country. The domain decides the catalog, the currency and the
# sellers you see, so it travels with the search from bootstrap through to the link in
# your notification.
KNOWN_TLDS: Final[frozenset[str]] = frozenset(
    {
        "fr", "de", "nl", "es", "it", "pl", "be", "at", "cz", "sk", "lt", "pt",
        "se", "ro", "hu", "gr", "fi", "dk", "ie", "lu", "hr", "si", "ee", "lv",
        "bg", "co.uk", "com",
    }
)  # fmt: skip

# Query parameters the site adds for its own bookkeeping. They differ between two visits
# to the same search, so they must not reach the uniqueness key.
_VOLATILE_PARAMS: Final[frozenset[str]] = frozenset(
    {
        "time",
        "search_id",
        "page",
        "per_page",
        "disabled_personalization",
        "referrer",
        "utm_source",
        "utm_medium",
        "utm_campaign",
    }
)

# Address-bar names that do not follow the `<filter>_ids` pattern, mapped to the stored
# name. Vinted's own page treats `catalog[]` as the category; the singular forms are what
# older links and some share buttons produce.
_PARAM_ALIASES: Final[dict[str, str]] = {
    "catalog": "catalog_ids",
    "brand": "brand_ids",
    "status": "status_ids",
    "size": "size_ids",
    "color": "color_ids",
}

# Parameters that take a single value rather than a list.
_SCALAR_PARAMS: Final[frozenset[str]] = frozenset(
    {"search_text", "price_from", "price_to", "currency", "order", "is_for_swap"}
)
_PRICE_PARAMS: Final[frozenset[str]] = frozenset({"price_from", "price_to"})

# Any `<filter>_ids` list. Vinted's page reads every such key as a filter, so new filters
# (patterns, video game platforms...) work here without a code change.
_IDS_PARAM = re.compile(r"^([a-z][a-z0-9_]*)_ids$")
# The API's own spelling, accepted so a URL copied from the browser's network tab works.
_ATTRIBUTE_PARAM = re.compile(r"^attribute_ids\[([a-z][a-z0-9_]*)\]$")

_BRAND_PATH = re.compile(r"^/brand/(\d+)")
_CATALOG_PATH = re.compile(r"^/catalog/(\d+)")
_CATALOG_BRAND_PATH = re.compile(r"^/catalog/(\d+)[^/]*/brand/(\d+)")
_ITEM_PATH = re.compile(r"^/items/\d+")
_MEMBER_PATH = re.compile(r"^/member/\d+")

# Long enough for any search the site itself builds; short enough that the stored query
# never turns into a request Vinted answers with 414.
MAX_URL_LENGTH: Final = 4000

# Pasted share text ("Check this out on Vinted: https://...") has the URL in the middle.
_URL_IN_TEXT = re.compile(r"(?i)\b(?:https?://)?(?:[a-z0-9-]+\.)*vinted\.[a-z.]+/\S*")


class InvalidSearchURLError(ValueError):
    """The pasted text is not a Vinted search URL we can work with."""


def _host_of(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    return host


def extract_tld(url: str) -> str:
    """Return the country suffix of a Vinted URL, e.g. 'fr' or 'co.uk'."""
    host = _host_of(url)
    if not host.startswith("vinted."):
        raise InvalidSearchURLError(f"{url!r} is not a vinted.* address")

    tld = host.removeprefix("vinted.")
    if tld not in KNOWN_TLDS:
        raise InvalidSearchURLError(
            f"{tld!r} is not a Vinted country site. Known sites: {', '.join(sorted(KNOWN_TLDS))}"
        )
    return tld


def _ids(value: str) -> list[str]:
    """The numeric ids in one parameter value. Vinted's page drops anything else too."""
    return [part.strip() for part in value.split(",") if part.strip().isdigit()]


def normalise_price(value: str) -> str | None:
    """A price as the API accepts it: a plain decimal with a dot.

    People type `12,50`, and the catalogue answers that with a 400 rather than ignoring
    it. Anything that is not a non-negative number is dropped instead of guessed at.
    """
    cleaned = value.strip().replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return format(amount.normalize(), "f")


def parse_search_params(url: str) -> dict[str, str]:
    """Extract the filters a pasted search URL is asking for, in the stored vocabulary.

    Category and brand landing pages carry their filter in the path rather than the query
    string, so those are folded in too.
    """
    parsed = urlparse(url)
    collected: dict[str, list[str]] = {}

    def add(key: str, values: list[str]) -> None:
        bucket = collected.setdefault(key, [])
        bucket.extend(value for value in values if value not in bucket)

    if both := _CATALOG_BRAND_PATH.match(parsed.path):
        add("catalog_ids", [both.group(1)])
        add("brand_ids", [both.group(2)])
    elif brand := _BRAND_PATH.match(parsed.path):
        add("brand_ids", [brand.group(1)])
    elif catalog := _CATALOG_PATH.match(parsed.path):
        add("catalog_ids", [catalog.group(1)])

    for raw_key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key = raw_key.removesuffix("[]")
        if key in _VOLATILE_PARAMS:
            continue
        if key in _SCALAR_PARAMS:
            scalar = normalise_price(value) if key in _PRICE_PARAMS else value
            if scalar:
                collected[key] = [scalar]
        elif stored := _stored_list_name(key):
            add(stored, _ids(value))
        # Anything else is a tracking or display parameter. Passing unknown names through
        # has historically produced empty result sets rather than errors.

    params = {key: ",".join(values) for key, values in collected.items() if values}

    # We only ever want what was posted since the last check, newest first.
    params["order"] = "newest_first"
    return params


def _stored_list_name(key: str) -> str | None:
    """The stored name for a list filter, whichever spelling the URL used."""
    if alias := _PARAM_ALIASES.get(key):
        return alias
    if _IDS_PARAM.match(key):
        return key
    if attribute := _ATTRIBUTE_PARAM.match(key):
        return f"{attribute.group(1)}_ids"
    return None


def catalogue_params(params: dict[str, str]) -> dict[str, str]:
    """Translate stored search parameters into what `svc-catalogue` understands.

    Every list filter became `attribute_ids[<name>]` (comma-separated) in September
    2026. The old names still get a 200, with the filter silently ignored, which is why
    this translation happens on every request rather than trusting what was stored.
    """
    translated: dict[str, str] = {}
    for key, value in params.items():
        if key in _PRICE_PARAMS:
            if (price := normalise_price(value)) is not None:
                translated[key] = price
        elif key in _SCALAR_PARAMS:
            translated[key] = value
        elif (stored := _stored_list_name(key)) and (ids := _ids(value)):
            name = stored.removesuffix("_ids")
            existing = translated.get(f"attribute_ids[{name}]")
            merged = [*existing.split(","), *ids] if existing else ids
            translated[f"attribute_ids[{name}]"] = ",".join(dict.fromkeys(merged))
    return translated


def _first_url(text: str) -> str:
    """Pull the Vinted address out of whatever was pasted, share text included."""
    text = text.strip()
    if match := _URL_IN_TEXT.search(text):
        text = match.group(0)
    if not re.match(r"(?i)^https?://", text):
        text = f"https://{text}"
    return text


def normalise_search_url(url: str) -> str:
    """Return a stable canonical URL for a search.

    Two pastes of the same search produce the same string here, which is what lets the
    database reject duplicates instead of polling the same catalog twice.
    """
    if not url.strip():
        raise InvalidSearchURLError("no URL given")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidSearchURLError(
            f"that URL is {len(url)} characters long; a Vinted search is well under "
            f"{MAX_URL_LENGTH}. Copy it again from the address bar."
        )
    url = _first_url(url)

    tld = extract_tld(url)
    path = urlparse(url).path
    if _ITEM_PATH.match(path):
        raise InvalidSearchURLError(
            "that is a link to a single listing, not a search. Open Vinted, search for what "
            "you want, then copy the address bar once results are showing."
        )
    if _MEMBER_PATH.match(path):
        raise InvalidSearchURLError(
            "that is a link to a member's profile, not a search. To follow a seller's new "
            "uploads, add a seller watch instead."
        )

    params = parse_search_params(url)
    if len(params) == 1:  # only the order we added ourselves
        raise InvalidSearchURLError(
            "that URL has no search filters on it. Open Vinted, set up the search you want, "
            "then copy the address bar once results are showing."
        )

    # Spaces go out as '+', a literal '+' as %2B: the same as the site's own links, and
    # the only encoding that survives the round trip through parse_qsl unchanged.
    query = urlencode(sorted(params.items()), safe=",")
    return f"https://www.vinted.{tld}/catalog?{query}"


def api_host(tld: str) -> str:
    """The host the site's own pages send API calls to.

    `api.` in front of the country domain everywhere, except the US site, whose frontend
    keeps the `www` (api.www.vinted.com).
    """
    if tld == "com":
        return "api.www.vinted.com"
    return f"api.vinted.{tld}"


def catalog_endpoint(tld: str) -> str:
    return f"https://{api_host(tld)}/svc-catalogue/items"


def brands_endpoint(tld: str) -> str:
    """Brand autocomplete, the same one the site's search box uses."""
    return f"https://www.vinted.{tld}/api/v2/brands"


def filters_search_endpoint(tld: str) -> str:
    """Search within one filter's options — e.g. brands that exist in a category."""
    return f"https://{api_host(tld)}/svc-filters/filters/search"


def filters_facets_endpoint(tld: str) -> str:
    """The options of one filter (condition, colour, size…), scoped to a category."""
    return f"https://{api_host(tld)}/svc-filters/filters/facets"


def user_endpoint(tld: str, user_id: int) -> str:
    """A member's public profile: country, rating, review count. Works anonymously."""
    return f"https://www.vinted.{tld}/api/v2/users/{user_id}"


def wardrobe_endpoint(tld: str, user_id: int) -> str:
    """A member's listings, newest first. Works anonymously."""
    return f"https://www.vinted.{tld}/api/v2/wardrobe/{user_id}/items"


def catalog_page(tld: str) -> str:
    """The search page itself — its HTML embeds the category tree and the CSRF token."""
    return f"https://www.vinted.{tld}/catalog"


def site_root(tld: str) -> str:
    return f"https://www.vinted.{tld}/"


def item_url(tld: str, item_id: int) -> str:
    return f"https://www.vinted.{tld}/items/{item_id}"


def member_url(tld: str, user_id: int) -> str:
    """A seller's profile page. The site accepts the bare id; no login slug needed."""
    return f"https://www.vinted.{tld}/member/{user_id}"


def message_seller_url(tld: str, item_id: int) -> str:
    """Deep link to the 'ask the seller' screen for a listing."""
    return f"https://www.vinted.{tld}/items/{item_id}/want_it/new"


def buy_url(tld: str, item_id: int) -> str:
    """Deep link that opens checkout for a listing.

    This only opens the page in the user's own browser, where they log in and decide.
    Nothing here buys anything on their behalf.
    """
    return (
        f"https://www.vinted.{tld}/transaction/buy/new"
        f"?source_screen=item&transaction%5Bitem_id%5D={item_id}"
    )
