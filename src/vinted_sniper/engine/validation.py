"""Turning what someone typed into values a search can safely hold.

The dashboard, the CLI and the Telegram bot all accept the same inputs, and they had
already started to disagree: the CLI refused "12,50" as a price while the dashboard stored
it as "no limit", and a negative interval became the fastest one allowed. Every entry point
calls these instead, and the repository runs the same checks again before it writes, so a
bad search cannot be stored whichever way it arrives.

Each helper accepts either the raw text or an already-typed value, returns the normalised
form, and raises `InvalidInputError` with a sentence fit to show the person who typed it.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vinted_sniper.vinted import urls

# Matching is case-insensitive everywhere a person types a pattern, because nobody
# expects "Nike" and "nike" to be different listings.
TITLE_REGEX_FLAGS = re.IGNORECASE

MIN_INTERVAL_S = 10
MAX_INTERVAL_S = 86_400
MAX_PRICE = Decimal(1_000_000)
MAX_NAME_LENGTH = 120
MAX_WORDS = 50
MAX_WORD_LENGTH = 100
MAX_REGEX_LENGTH = 500
MAX_NOTES_LENGTH = 2_000
MAX_RATING = 5.0

QUIET_MODES = ("hold", "drop", "silent")

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_COLOR = re.compile(r"^#?([0-9a-fA-F]{6})$")
_COUNTRY = re.compile(r"^[A-Za-z]{2}$")
_WORD_SPLIT = re.compile(r"[,\n]")


class InvalidInputError(ValueError):
    """Something typed into a search cannot be used, with a message saying why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def parse_price(value: str | Decimal | float | None, *, field: str = "price") -> Decimal | None:
    """A price limit. Blank means no limit; a decimal comma is fine; nonsense is refused.

    "12,50" is how most of Vinted's users write twelve and a half. Treating it as "no
    limit" — what the dashboard used to do — turns a budget into a firehose.
    """
    if value is None:
        return None
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise InvalidInputError(field, f"{value!r} is not a price.") from exc
    if not amount.is_finite():
        raise InvalidInputError(field, f"{value!r} is not a price.")
    if amount < 0:
        raise InvalidInputError(field, "A price cannot be negative.")
    if amount > MAX_PRICE:
        raise InvalidInputError(field, "That price is too large to be a real limit.")
    return amount.quantize(Decimal("0.01"))


def parse_interval(value: str | int | None, *, default: int) -> int:
    """Seconds between checks. Blank means the default; out of range is refused, not clamped.

    Clamping is how "-5" used to become "every ten seconds", the most aggressive setting
    there is. Saying no is kinder than quietly doing the opposite of what was meant.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        seconds = int(str(value).strip())
    except ValueError as exc:
        raise InvalidInputError(
            "interval", "The interval must be a whole number of seconds."
        ) from exc
    if seconds < MIN_INTERVAL_S:
        raise InvalidInputError(
            "interval",
            f"Checking more often than every {MIN_INTERVAL_S} seconds finds nothing sooner "
            "and gets you blocked.",
        )
    if seconds > MAX_INTERVAL_S:
        raise InvalidInputError("interval", "Check at least once a day (86400 seconds).")
    return seconds


def parse_words(value: str | list[str] | None, *, field: str = "words") -> list[str]:
    """A list of words or phrases, from comma- or line-separated text."""
    if value is None:
        return []
    parts = _WORD_SPLIT.split(value) if isinstance(value, str) else value
    words: list[str] = []
    for part in parts:
        word = part.strip()
        if not word or word in words:
            continue
        if len(word) > MAX_WORD_LENGTH:
            raise InvalidInputError(field, f"{word[:20]!r}… is too long for a keyword.")
        words.append(word)
    if len(words) > MAX_WORDS:
        raise InvalidInputError(field, f"At most {MAX_WORDS} keywords.")
    return words


def parse_regex(value: str | None) -> str | None:
    """A regular expression for titles, compiled now so a typo fails here, not at 3am."""
    if value is None or not value.strip():
        return None
    pattern = value.strip()
    if len(pattern) > MAX_REGEX_LENGTH:
        raise InvalidInputError("regex", "That pattern is too long.")
    try:
        re.compile(pattern, TITLE_REGEX_FLAGS)
    except re.error as exc:
        raise InvalidInputError("regex", f"That pattern does not work: {exc}.") from exc
    return pattern


def parse_hhmm(value: str | None, *, field: str) -> str | None:
    """A time of day as HH:MM, 24-hour."""
    if value is None or not value.strip():
        return None
    match = _HHMM.match(value.strip())
    if match is None:
        raise InvalidInputError(field, f"{value!r} is not a time like 23:00.")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_quiet_hours(
    start: str | None, end: str | None, mode: str | None
) -> tuple[str | None, str | None, str]:
    """Quiet hours come as a pair or not at all; a window that starts where it ends is empty."""
    start_hhmm = parse_hhmm(start, field="quiet_start")
    end_hhmm = parse_hhmm(end, field="quiet_end")
    quiet_mode = (mode or "hold").strip().lower()
    if quiet_mode not in QUIET_MODES:
        raise InvalidInputError("quiet_mode", "Quiet hours can hold, drop or silence alerts.")
    if (start_hhmm is None) != (end_hhmm is None):
        raise InvalidInputError("quiet_end", "Quiet hours need both a start and an end.")
    if start_hhmm is not None and start_hhmm == end_hhmm:
        raise InvalidInputError("quiet_end", "Quiet hours must end at a different time.")
    return start_hhmm, end_hhmm, quiet_mode


def parse_color(value: str | None) -> str | None:
    """A hex colour as #RRGGBB."""
    if value is None or not value.strip():
        return None
    match = _COLOR.match(value.strip())
    if match is None:
        raise InvalidInputError("color", f"{value!r} is not a colour like #007782.")
    return f"#{match.group(1).upper()}"


def parse_percent(value: str | int | None, *, field: str) -> int | None:
    """A whole percentage strictly between 0 and 100."""
    whole = _parse_int(value, field=field)
    if whole is not None and not 1 <= whole <= 99:  # noqa: PLR2004 - the bounds of a percentage
        raise InvalidInputError(field, "Pick a percentage between 1 and 99.")
    return whole


def parse_fee_pct(value: str | float | None) -> float | None:
    """The cut a resale platform keeps, in percent: "10" for eBay, "0" or blank for Vinted.

    Decimals are allowed ("12,9" is a real fee); 100 is not, since nothing would be left.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        pct = float(str(value).strip().rstrip("%").strip().replace(",", "."))
    except ValueError as exc:
        raise InvalidInputError("resale_fee_pct", f"{value!r} is not a percentage.") from exc
    if not 0 <= pct < 100:  # noqa: PLR2004 - the bounds of a percentage
        raise InvalidInputError("resale_fee_pct", "Pick a fee from 0 up to (not including) 100%.")
    return pct


def parse_rating(value: str | float | None) -> float | None:
    """A minimum seller rating in stars, 0 to 5."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        stars = float(str(value).strip().replace(",", "."))
    except ValueError as exc:
        raise InvalidInputError("seller_min_rating", f"{value!r} is not a rating.") from exc
    if not 0 <= stars <= MAX_RATING:
        raise InvalidInputError("seller_min_rating", "Ratings go from 0 to 5 stars.")
    return stars


def parse_count(value: str | int | None, *, field: str) -> int | None:
    """A whole number of zero or more."""
    whole = _parse_int(value, field=field)
    if whole is not None and whole < 0:
        raise InvalidInputError(field, "That cannot be negative.")
    return whole


def parse_minutes(value: str | int | None, *, field: str) -> int | None:
    """A positive number of minutes."""
    whole = _parse_int(value, field=field)
    if whole is not None and whole < 1:
        raise InvalidInputError(field, "That needs to be at least one minute.")
    return whole


def parse_countries(value: str | list[str] | None) -> list[str]:
    """Two-letter country codes, upper-cased: 'fr, BE' becomes ['FR', 'BE']."""
    codes: list[str] = []
    for word in parse_words(value, field="countries"):
        if _COUNTRY.match(word) is None:
            raise InvalidInputError("countries", f"{word!r} is not a two-letter country code.")
        if word.upper() not in codes:
            codes.append(word.upper())
    return codes


def parse_tlds(value: str | list[str] | None, *, primary: str) -> list[str]:
    """Extra Vinted sites to run a search on, without the one it already runs on."""
    sites: list[str] = []
    for word in parse_words(value, field="extra_tlds"):
        tld = word.lower().removeprefix("vinted.").removeprefix(".")
        if tld not in urls.KNOWN_TLDS:
            raise InvalidInputError("extra_tlds", f"vinted.{tld} is not a Vinted country site.")
        if tld != primary and tld not in sites:
            sites.append(tld)
    return sites


def parse_name(value: str | None, *, fallback: str) -> str:
    """A display name, falling back when blank and refusing a novel."""
    name = (value or "").strip() or fallback
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidInputError("name", f"Keep the name under {MAX_NAME_LENGTH} characters.")
    return name


def parse_notes(value: str | None) -> str | None:
    notes = (value or "").strip()
    if len(notes) > MAX_NOTES_LENGTH:
        raise InvalidInputError("notes", f"Keep notes under {MAX_NOTES_LENGTH} characters.")
    return notes or None


def parse_timezone(value: str) -> str:
    """An IANA time zone name such as Europe/Paris."""
    name = value.strip().lstrip(":")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidInputError(
            "timezone", f"{value!r} is not a time zone like Europe/Paris."
        ) from exc
    return name


def default_search_name(params: dict[str, str], tld: str) -> str:
    """What to call a search nobody named: its search text, or the site it watches."""
    text = (params.get("search_text") or "").strip()
    return text[:MAX_NAME_LENGTH] if text else f"vinted.{tld}"


def fold(text: str) -> str:
    """Lower-case and strip accents, so 'Café' and 'cafe' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _parse_int(value: str | int | None, *, field: str) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise InvalidInputError(field, f"{value!r} is not a whole number.") from exc
