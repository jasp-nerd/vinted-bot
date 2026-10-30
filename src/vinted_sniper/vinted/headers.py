"""What our requests look like on the wire.

Three request shapes matter. Fetching the homepage to pick up a session cookie should look
like a person opening the site in a tab. Calls to the site's own `/api/v2` (members,
wardrobes, brands) should look like the page's background requests. Calls to the separate
`api.` host (search and filters, since September 2026) carry a few extra headers the site's
frontend adds there, and two of them decide which market answers. Sending the wrong shape
for any of these is the cheapest way to stand out, so they are kept apart here rather than
assembled ad hoc at the call site.

Header order is part of the picture too — browsers send these in a consistent order — so
these dictionaries are built in the order they should go out, and nothing downstream
sorts them.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

_AGENTS_FILE = Path(__file__).parent / "agents.json"

# Vinted serves each country in its own language. Asking vinted.de for English is a small
# inconsistency, and small inconsistencies are what fingerprinting looks for.
_ACCEPT_LANGUAGE: Final[dict[str, str]] = {
    "fr": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "de": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "nl": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "es": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "it": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "be": "fr-BE,fr;q=0.9,nl-BE;q=0.8,nl;q=0.7,en;q=0.6",
    "at": "de-AT,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "cz": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    "sk": "sk-SK,sk;q=0.9,en-US;q=0.8,en;q=0.7",
    "lt": "lt-LT,lt;q=0.9,en-US;q=0.8,en;q=0.7",
    "pt": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "se": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "ro": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "hu": "hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7",
    "gr": "el-GR,el;q=0.9,en-US;q=0.8,en;q=0.7",
    "fi": "fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7",
    "dk": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7",
    "ie": "en-IE,en;q=0.9,en-US;q=0.8",
    "lu": "fr-LU,fr;q=0.9,de-LU;q=0.8,en;q=0.7",
    "hr": "hr-HR,hr;q=0.9,en-US;q=0.8,en;q=0.7",
    "si": "sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7",
    "ee": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
    "lv": "lv-LV,lv;q=0.9,en-US;q=0.8,en;q=0.7",
    "bg": "bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7",
    "co.uk": "en-GB,en;q=0.9,en-US;q=0.8",
    "com": "en-US,en;q=0.9",
}
_DEFAULT_ACCEPT_LANGUAGE: Final = "en-US,en;q=0.9"


@dataclass(frozen=True, slots=True)
class BrowserIdentity:
    """One consistent browser persona: user agent and the client hints that match it."""

    user_agent: str
    brand: str
    version: str
    platform: str
    mobile: bool

    @property
    def sec_ch_ua(self) -> str | None:
        """The Sec-CH-UA header Chromium browsers send. Firefox and Safari send none."""
        if self.brand not in ("Chromium", "Microsoft Edge"):
            return None
        parts = [
            f'"{self.brand}";v="{self.version}"',
            '"Not(A:Brand";v="24"',
            f'"Google Chrome";v="{self.version}"'
            if self.brand == "Chromium"
            else f'"Chromium";v="{self.version}"',
        ]
        return ", ".join(parts)

    @property
    def sec_ch_ua_platform(self) -> str:
        return f'"{self.platform}"'


@lru_cache(maxsize=1)
def _load_agents() -> tuple[list[BrowserIdentity], list[int]]:
    data: dict[str, Any] = json.loads(_AGENTS_FILE.read_text(encoding="utf-8"))
    identities: list[BrowserIdentity] = []
    weights: list[int] = []
    for entry in data["agents"]:
        identities.append(
            BrowserIdentity(
                user_agent=entry["ua"],
                brand=entry["brand"],
                version=entry["version"],
                platform=entry["platform"],
                mobile=bool(entry["mobile"]),
            )
        )
        weights.append(int(entry["share"]))
    if not identities:
        raise RuntimeError("agents.json contains no browser identities")
    return identities, weights


def pick_identity(rng: random.Random | None = None) -> BrowserIdentity:
    """Choose a browser persona, favouring the ones most people actually run."""
    identities, weights = _load_agents()
    chooser = rng or random
    return chooser.choices(identities, weights=weights, k=1)[0]


def identity_for_user_agent(user_agent: str) -> BrowserIdentity:
    """Recover the persona behind a stored user agent, so a resumed session stays coherent."""
    identities, _ = _load_agents()
    for identity in identities:
        if identity.user_agent == user_agent:
            return identity
    # The pool changed under a stored session. Treat it as a plain unknown browser rather
    # than inventing client hints that contradict the user agent string.
    return BrowserIdentity(
        user_agent=user_agent, brand="Unknown", version="0", platform="Unknown", mobile=False
    )


def accept_language(tld: str) -> str:
    return _ACCEPT_LANGUAGE.get(tld, _DEFAULT_ACCEPT_LANGUAGE)


def fallback_locale(tld: str) -> str:
    """The site's locale when the session did not say, e.g. 'fr-FR'.

    Only a fallback: the homepage sets the real one in its `anonymous-iso-locale` cookie,
    and the two differ where Vinted has no translation (vinted.bg answers `bg-BG` with
    untranslated keys such as `size.776.title`).
    """
    return accept_language(tld).split(",", 1)[0]


def document_headers(tld: str, identity: BrowserIdentity) -> dict[str, str]:
    """Headers for loading the site itself — the request that earns us a session cookie."""
    headers = {
        "User-Agent": identity.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8",
        "Accept-Language": accept_language(tld),
        # Vinted has been serving Brotli without always announcing it. httpx is installed
        # with the brotli and zstd extras so that this is safe to ask for.
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Connection": "keep-alive",
    }
    if sec_ch_ua := identity.sec_ch_ua:
        headers["Sec-CH-UA"] = sec_ch_ua
        headers["Sec-CH-UA-Mobile"] = "?1" if identity.mobile else "?0"
        headers["Sec-CH-UA-Platform"] = identity.sec_ch_ua_platform
    return headers


def api_headers(tld: str, identity: BrowserIdentity, referer: str | None = None) -> dict[str, str]:
    """Headers for `/api/v2` calls on the site's own host — members, wardrobes, brands."""
    origin = f"https://www.vinted.{tld}"
    headers = {
        "User-Agent": identity.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": accept_language(tld),
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": origin,
        "Referer": referer or f"{origin}/catalog",
        "DNT": "1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }
    if sec_ch_ua := identity.sec_ch_ua:
        headers["Sec-CH-UA"] = sec_ch_ua
        headers["Sec-CH-UA-Mobile"] = "?1" if identity.mobile else "?0"
        headers["Sec-CH-UA-Platform"] = identity.sec_ch_ua_platform
    return headers


def catalogue_headers(
    tld: str, identity: BrowserIdentity, *, locale: str, anon_id: str | None
) -> dict[str, str]:
    """Headers for the search and filter services on the separate `api.` host.

    `Locale` picks the market: without it every site answers with the euro-priced French
    catalog, so a price limit typed in złoty would be compared against euros. `X-Anon-Id`
    ties the request to the session the homepage handed out, as the site's own frontend
    does. The request is cross-host, hence `same-site` and an explicit Origin.
    """
    origin = f"https://www.vinted.{tld}"
    headers = {
        "User-Agent": identity.user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": accept_language(tld),
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Origin": origin,
        "Referer": f"{origin}/",
        "Locale": locale,
        "Platform": "web",
        "X-Next-App": "marketplace-web",
    }
    if anon_id:
        headers["X-Anon-Id"] = anon_id
    headers.update(
        {
            "DNT": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Connection": "keep-alive",
        }
    )
    if sec_ch_ua := identity.sec_ch_ua:
        headers["Sec-CH-UA"] = sec_ch_ua
        headers["Sec-CH-UA-Mobile"] = "?1" if identity.mobile else "?0"
        headers["Sec-CH-UA-Platform"] = identity.sec_ch_ua_platform
    return headers


def page_headers(tld: str, identity: BrowserIdentity) -> dict[str, str]:
    """Headers for opening another page of the site from within it — an item page."""
    headers = document_headers(tld, identity)
    headers["Sec-Fetch-Site"] = "same-origin"
    headers["Referer"] = f"https://www.vinted.{tld}/"
    return headers
