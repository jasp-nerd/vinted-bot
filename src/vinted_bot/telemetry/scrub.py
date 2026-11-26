"""Taking anything private out of error text before it is reported.

An exception's message is written for a log on the user's own computer, so it can quote a
Telegram bot token (it is part of every Bot API URL), a Discord webhook, a proxy's
password, an email address, a file path with the user's name in it, or what someone typed.
Each pattern below replaces one of those with a placeholder. What is left says what went
wrong without saying whose it was.
"""

from __future__ import annotations

import contextlib
import ipaddress
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_LENGTH = 300

# Hosts that say something useful about an error and nothing about the user. Any other
# URL, such as someone's own ntfy server or Apprise target, is replaced whole.
_KNOWN_HOSTS = re.compile(
    r"^(?:[a-z0-9-]+\.)*(?:vinted\.[a-z.]+|vinted\.net|telegram\.org|discord\.com|"
    r"discordapp\.com|ntfy\.sh|github\.com|githubusercontent\.com|pypi\.org|"
    r"frankfurter\.app|hc-ping\.com|jaspnerd\.dev)$"
)

_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>()\[\]{}]+", re.IGNORECASE)
_TELEGRAM_TOKEN = re.compile(r"\b\d{5,20}:[A-Za-z0-9_-]{30,64}\b")
# user:password@host without a scheme, as proxies are often written.
_CREDENTIALS = re.compile(r"[^\s:@/'\"]+:[^\s@/'\"]+@[^\s/'\",;]+")
_AUTHORIZATION = re.compile(r"\b(Basic|Bearer|Token)\s+[A-Za-z0-9+/=._~-]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# A host name with a port: what a proxy or a server of one's own looks like in an error.
_HOST_PORT = re.compile(
    r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})(:\d{1,5}|\s+port\s+\d{1,5})", re.IGNORECASE
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
# Anything with two colons that Python accepts as IPv6 (::1, fe80::1, 2a02:a45::1f4);
# a time of day (12:30:45) isn't one.
_IPV6_CANDIDATE = re.compile(
    r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:%\w+)?(?![\w:])"
)
_WINDOWS_HOME = re.compile(r"([A-Za-z]:\\+Users\\+)[^\\'\"]+", re.IGNORECASE)
_UNIX_HOME = re.compile(r"/(Users|home)/[^/\s'\"]+")
# Absolute paths: a NAS share or a folder named after someone says who it is. Only a file
# name (it has a dot) is kept.
_UNIX_PATH = re.compile(r"(?<![\w.~/<>-])/(?:[^/\s'\"]+/)+([^/\s'\"]*)")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:[\\/](?:[^\\/\s'\"]+[\\/])*([^\\/\s'\"]*)")
# Keys, tokens, webhook secrets: long runs with no spaces.
_SECRET = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
# Quoted text is usually what someone typed or what a server sent back (a search name, a
# title, a block page). Only identifiers in code style (field_name, module.name) stay.
_QUOTED = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+$")


def _url(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        parts = urlsplit(text)
    except ValueError:
        return "<url>"
    host = (parts.hostname or "").lower()
    if host and _KNOWN_HOSTS.match(host):
        return f"{parts.scheme}://{host}/…"
    return "<url>"


def _host_port(match: re.Match[str]) -> str:
    return match.group(0) if _KNOWN_HOSTS.match(match.group(1).lower()) else "<host>"


def _ipv6(match: re.Match[str]) -> str:
    try:
        ipaddress.IPv6Address(match.group(0).split("%", 1)[0])
    except ValueError:
        return match.group(0)
    return "<ip>"


def _path(match: re.Match[str]) -> str:
    name = match.group(1)
    return f"<path>/{name}" if "." in name else "<path>"


def _quoted(match: re.Match[str]) -> str:
    inner = match.group(1) if match.group(1) is not None else match.group(2)
    return match.group(0) if _IDENTIFIER.match(inner) else "'<text>'"


def scrub(text: str, *, home: Path | None = None) -> str:
    """`text` with anything that could identify someone replaced, and cut to length."""
    with contextlib.suppress(ValueError):
        # Percent-encoded addresses and emails would slip past everything below.
        text = unquote(text)
    home_dir = str(home or Path.home())
    if len(home_dir) > 1:
        text = text.replace(home_dir, "~")
    text = _URL.sub(_url, text)
    text = _TELEGRAM_TOKEN.sub("<token>", text)
    text = _CREDENTIALS.sub("<credentials>", text)
    text = _AUTHORIZATION.sub(r"\1 <secret>", text)
    text = _EMAIL.sub("<email>", text)
    text = _HOST_PORT.sub(_host_port, text)
    text = _IPV4.sub("<ip>", text)
    text = _IPV6_CANDIDATE.sub(_ipv6, text)
    text = _WINDOWS_HOME.sub(r"\1<user>", text)
    text = _UNIX_HOME.sub(r"/\1/<user>", text)
    text = _UNIX_PATH.sub(_path, text)
    text = _WINDOWS_PATH.sub(_path, text)
    text = _SECRET.sub("<secret>", text)
    text = _QUOTED.sub(_quoted, text)
    if len(text) > MAX_LENGTH:
        text = text[: MAX_LENGTH - 1] + "…"
    return text
