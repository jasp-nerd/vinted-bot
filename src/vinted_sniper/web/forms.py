"""Reading the search editor and the setup's search step.

A form comes back as plain strings. This turns them into a search the repository will
accept, or into a message per field that the page shows next to that field, so a typo
never becomes a 422 page or a half-saved search. The same checks run again in the
repository before anything is written.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from vinted_sniper.db.repo import Query
from vinted_sniper.engine import validation
from vinted_sniper.engine.validation import InvalidInputError
from vinted_sniper.vinted import urls

# The filters the editor shows as their own controls. Anything else a pasted link carries
# (materials, patterns, price_to...) is kept as it was, so editing never broadens a search.
BUILDER_LISTS = ("catalog_ids", "brand_ids", "size_ids", "status_ids", "color_ids")
_MANAGED = {"search_text", "order", *BUILDER_LISTS}

INTERVAL_PRESETS = (30, 60, 120, 300, 900)


@dataclass
class SearchForm:
    """What the editor shows: the values as typed, and what is wrong with them."""

    values: dict[str, Any]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedSearch:
    """A search ready to store."""

    name: str
    url: str
    tld: str
    params: dict[str, str]
    poll_interval_s: int
    filters: dict[str, Any]
    destination_ids: list[int]


def _ids(raw: str) -> str:
    return ",".join(part.strip() for part in raw.split(",") if part.strip().isdigit())


def _text(form: Mapping[str, Any], key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


def _list(form: Any, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(value) for value in form.getlist(key)]
    value = form.get(key)
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []


def default_values(*, tld: str, interval: int, color: str) -> dict[str, Any]:
    """An empty editor for a new search."""
    return {
        "name": "",
        "tld": tld,
        "link": "",
        "search_text": "",
        **dict.fromkeys(BUILDER_LISTS, ""),
        "labels": "{}",
        "extra_params": "{}",
        "include_terms": "",
        "banned_keywords": "",
        "regex": "",
        "min_total_price": "",
        "max_total_price": "",
        "deal_on": False,
        "deal_only_pct": "20",
        "seller_min_rating": "",
        "seller_min_reviews": "",
        "skip_unrated_sellers": False,
        "countries": [],
        "interval": str(interval),
        "max_age_min": "",
        "quiet_on": False,
        "quiet_start": "23:00",
        "quiet_end": "07:30",
        "quiet_mode": "hold",
        "dest": [],
        "color": color,
        "tags": "",
        "notes": "",
        "extra_tlds": [],
    }


def values_from_query(query: Query, routes: list[int]) -> dict[str, Any]:
    """The editor filled in from a stored search."""
    params = query.params
    return {
        "name": query.name,
        "tld": query.tld,
        "link": "",
        "search_text": params.get("search_text", ""),
        **{key: params.get(key, "") for key in BUILDER_LISTS},
        "labels": "{}",
        "extra_params": json.dumps({k: v for k, v in params.items() if k not in _MANAGED}),
        "include_terms": ",".join(query.include_terms),
        "banned_keywords": ",".join(query.banned_keywords),
        "regex": query.regex or "",
        "min_total_price": _plain(query.min_total_price),
        "max_total_price": _plain(query.max_total_price),
        "deal_on": query.deal_only_pct is not None,
        "deal_only_pct": str(query.deal_only_pct or 20),
        "seller_min_rating": f"{query.seller_min_rating:g}" if query.seller_min_rating else "",
        "seller_min_reviews": str(query.seller_min_reviews or ""),
        "skip_unrated_sellers": query.skip_unrated_sellers,
        "countries": list(query.countries or []),
        "interval": str(query.poll_interval_s),
        "max_age_min": str(query.max_age_min or ""),
        "quiet_on": query.quiet_start is not None,
        "quiet_start": query.quiet_start or "23:00",
        "quiet_end": query.quiet_end or "07:30",
        "quiet_mode": query.quiet_mode,
        "dest": [str(destination_id) for destination_id in routes],
        "color": query.color or "",
        "tags": ",".join(query.tags),
        "notes": query.notes or "",
        "extra_tlds": list(query.extra_tlds),
    }


def values_from_link(link: str, base: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Prefill the editor from a pasted Vinted link. Returns the values and any problem."""
    try:
        normalised = urls.normalise_search_url(link)
    except urls.InvalidSearchURLError as exc:
        return {**base, "link": link}, _sentence(str(exc))
    tld = urls.extract_tld(normalised)
    params = urls.parse_search_params(normalised)
    values = {
        **base,
        "tld": tld,
        "search_text": params.get("search_text", ""),
        **{key: params.get(key, "") for key in BUILDER_LISTS},
        "extra_params": json.dumps({k: v for k, v in params.items() if k not in _MANAGED}),
    }
    return values, None


def _plain(amount: Any) -> str:
    return "" if amount is None else f"{amount:f}".rstrip("0").rstrip(".")


def _sentence(message: str) -> str:
    message = message.strip()
    return message[:1].upper() + message[1:] if message else message


def values_from_form(form: Any) -> dict[str, Any]:
    """The editor's values as posted, for showing them again next to any errors."""
    values: dict[str, Any] = {
        key: _text(form, key)
        for key in (
            "name",
            "tld",
            "link",
            "search_text",
            *BUILDER_LISTS,
            "labels",
            "extra_params",
            "include_terms",
            "banned_keywords",
            "regex",
            "min_total_price",
            "max_total_price",
            "deal_only_pct",
            "seller_min_rating",
            "seller_min_reviews",
            "interval",
            "max_age_min",
            "quiet_start",
            "quiet_end",
            "quiet_mode",
            "color",
            "tags",
            "notes",
        )
    }
    for flag in ("deal_on", "skip_unrated_sellers", "quiet_on"):
        values[flag] = bool(_text(form, flag))
    for many in ("countries", "dest", "extra_tlds"):
        values[many] = _list(form, many)
    values["labels"] = values["labels"] or "{}"
    values["extra_params"] = values["extra_params"] or "{}"
    return values


def _params(values: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """The site and Vinted parameters the form describes. Raises InvalidInputError."""
    if values["link"]:
        try:
            normalised = urls.normalise_search_url(values["link"])
        except urls.InvalidSearchURLError as exc:
            raise InvalidInputError("link", _sentence(str(exc))) from exc
        return urls.extract_tld(normalised), urls.parse_search_params(normalised)

    tld = values["tld"].lower().removeprefix("vinted.")
    if tld not in urls.KNOWN_TLDS:
        raise InvalidInputError("tld", "Pick one of Vinted's country sites.")
    try:
        extra = json.loads(values["extra_params"])
    except ValueError:
        extra = {}
    params: dict[str, str] = {
        str(k): str(v)
        for k, v in (extra if isinstance(extra, dict) else {}).items()
        if str(k) not in _MANAGED
    }
    if values["search_text"]:
        params["search_text"] = values["search_text"]
    for key in BUILDER_LISTS:
        if ids := _ids(values[key]):
            params[key] = ids
    params["order"] = "newest_first"
    return tld, params


def search_url(tld: str, params: dict[str, str]) -> str:
    """The canonical address of a search. Raises InvalidInputError for an empty one."""
    if len(params) <= 1:
        raise InvalidInputError(
            "search_text",
            "Add some words, a category or a brand, so the search isn't all of Vinted.",
        )
    try:
        return urls.normalise_search_url(
            f"https://www.vinted.{tld}/catalog?{urlencode(params, safe=',')}"
        )
    except urls.InvalidSearchURLError as exc:
        raise InvalidInputError("search_text", _sentence(str(exc))) from exc


def parse_search(values: dict[str, Any], *, default_interval: int) -> ParsedSearch:
    """Everything the editor holds, checked. Raises InvalidInputError for the first problem.

    `collect_errors` wraps this to gather every problem at once.
    """
    tld, params = _params(values)
    url = search_url(tld, params)
    min_price = validation.parse_price(values["min_total_price"], field="min_total_price")
    max_price = validation.parse_price(values["max_total_price"], field="max_total_price")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise InvalidInputError(
            "min_total_price", "The lowest price is higher than the highest. Swap them?"
        )
    quiet_start, quiet_end, quiet_mode = validation.parse_quiet_hours(
        values["quiet_start"] if values["quiet_on"] else None,
        values["quiet_end"] if values["quiet_on"] else None,
        values["quiet_mode"] or "hold",
    )
    filters: dict[str, Any] = {
        "max_total_price": max_price,
        "min_total_price": min_price,
        "include_terms": validation.parse_words(values["include_terms"], field="include_terms"),
        "banned_keywords": validation.parse_words(
            values["banned_keywords"], field="banned_keywords"
        ),
        "regex": validation.parse_regex(values["regex"]),
        "deal_only_pct": (
            validation.parse_percent(values["deal_only_pct"], field="deal_only_pct")
            if values["deal_on"]
            else None
        ),
        "seller_min_rating": validation.parse_rating(values["seller_min_rating"]),
        "seller_min_reviews": validation.parse_count(
            values["seller_min_reviews"], field="seller_min_reviews"
        ),
        "skip_unrated_sellers": values["skip_unrated_sellers"],
        "countries": validation.parse_countries(values["countries"]) or None,
        "max_age_min": validation.parse_minutes(values["max_age_min"], field="max_age_min"),
        "quiet_start": quiet_start,
        "quiet_end": quiet_end,
        "quiet_mode": quiet_mode,
        "color": validation.parse_color(values["color"]),
        "tags": validation.parse_words(values["tags"], field="tags"),
        "notes": validation.parse_notes(values["notes"]),
        "extra_tlds": validation.parse_tlds(values["extra_tlds"], primary=tld),
    }
    name = validation.parse_name(
        values["name"], fallback=validation.default_search_name(params, tld)
    )
    interval = validation.parse_interval(values["interval"], default=default_interval)
    destinations = [int(raw) for raw in values["dest"] if str(raw).isdigit()]
    return ParsedSearch(name, url, tld, params, interval, filters, destinations)


def collect_errors(
    values: dict[str, Any], *, default_interval: int
) -> tuple[ParsedSearch | None, dict[str, str]]:
    """Parse the form, with a message for every field that is wrong, not just the first."""
    parsed, errors = best_effort(values, default_interval=default_interval)
    return (None if errors else parsed), errors


def best_effort(
    values: dict[str, Any], *, default_interval: int
) -> tuple[ParsedSearch | None, dict[str, str]]:
    """The search with every faulty field left blank, and what was wrong with each.

    Blanking a failing field and parsing again means one mistake does not hide the next,
    and the preview can still run on everything else. Bounded by the number of fields.
    """
    errors: dict[str, str] = {}
    trial = dict(values)
    for _ in range(len(values) + 1):
        try:
            return parse_search(trial, default_interval=default_interval), errors
        except InvalidInputError as exc:
            if exc.field in errors or exc.field not in trial or exc.field == "search_text":
                # An empty search cannot be fixed by blanking more of it.
                errors.setdefault(exc.field, exc.message)
                break
            errors[exc.field] = exc.message
            trial[exc.field] = [] if isinstance(trial[exc.field], list) else ""
            if exc.field in {"quiet_start", "quiet_end", "quiet_mode"}:
                trial["quiet_on"] = False
    return None, errors
