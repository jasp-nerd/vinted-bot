"""Turning the "add a place for alerts" forms into a destination config.

Each kind asks for what a person actually has in hand (a Discord webhook link, an ntfy
topic, an email address and app password) and builds the stored config from it, so
nobody has to learn Apprise's URL syntax to get email. Every config is then handed to the
real sender's constructor, which is the one place that knows what a sender needs, so a
bad address is refused here rather than switched off in the background later.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from vinted_bot.config import Settings
from vinted_bot.db.repo import Destination
from vinted_bot.deals import TIERS
from vinted_bot.deliver.base import SenderConfigError
from vinted_bot.deliver.dispatcher import build_sender
from vinted_bot.engine.validation import InvalidInputError

KINDS = ("ntfy", "telegram", "discord", "apprise", "webhook")

_DISCORD_WEBHOOK = re.compile(
    r"^(?:https?://)?(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/(\d+)/([\w-]+)",
    re.IGNORECASE,
)
_DISCORD_CHANNEL = re.compile(r"discord(?:app)?\.com/channels/", re.IGNORECASE)
_NTFY_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ROLE_ID = re.compile(r"^<?@?&?(\d{5,25})>?$")
_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")
_MAIL_SERVER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")

# Email providers people pick from, as the domain Apprise knows their mail server by.
# "custom" is any other server, described by its address, port and kind of encryption.
EMAIL_PROVIDERS = {
    "gmail": ("Gmail", "gmail.com"),
    "outlook": ("Outlook or Hotmail", "outlook.com"),
    "yahoo": ("Yahoo", "yahoo.com"),
    "icloud": ("iCloud", "icloud.com"),
    "custom": ("Another provider, or my own mail server", ""),
}

# How a custom mail server is reached: the label, Apprise's mode and the usual port.
EMAIL_SECURITY = {
    "starttls": ("STARTTLS, usually port 587", "starttls", 587),
    "ssl": ("SSL/TLS, usually port 465", "ssl", 465),
    "none": ("None, for a server on your own network", "insecure", 25),
}


def new_ntfy_topic() -> str:
    """A topic name nobody will guess: ntfy topics are public to anyone who knows them."""
    return f"mags-{secrets.token_hex(3)}-{secrets.token_hex(2)}"


def _field(form: Mapping[str, Any], key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


def discord_url(raw: str) -> str:
    """A Discord webhook link, with or without https://, or a sentence saying what is wrong."""
    text = raw.strip()
    if not text:
        raise InvalidInputError("discord_url", "Paste the webhook link from Discord.")
    if _DISCORD_CHANNEL.search(text):
        raise InvalidInputError(
            "discord_url",
            "That's a link to the channel itself, not its webhook link. Follow the steps "
            "above and use Copy Webhook URL. It starts with discord.com/api/webhooks/.",
        )
    match = _DISCORD_WEBHOOK.match(text)
    if match is None:
        raise InvalidInputError(
            "discord_url",
            "That isn't a Discord webhook link. It starts with discord.com/api/webhooks/.",
        )
    return f"https://discord.com/api/webhooks/{match.group(1)}/{match.group(2)}"


def discord_mention(raw: str) -> str | None:
    """A role to ping. Webhooks cannot look names up, so it has to be the role's number."""
    text = raw.strip()
    if not text:
        return None
    if text in {"@everyone", "@here"}:
        return text
    match = _ROLE_ID.match(text)
    if match is None:
        raise InvalidInputError(
            "mention",
            "Use @everyone, @here, or a role's ID number. In Discord, turn on Developer "
            "Mode, right-click the role and choose Copy Role ID.",
        )
    return f"<@&{match.group(1)}>"


def ntfy_config(raw: str) -> dict[str, Any]:
    text = raw.strip().rstrip("/")
    if text.startswith(("https://", "http://")):
        return {"url": text}
    if not _NTFY_TOPIC.match(text):
        raise InvalidInputError(
            "ntfy_topic", "A topic is one word: letters, numbers, - and _ only."
        )
    return {"topic": text}


def email_url(form: Mapping[str, Any]) -> str:
    """The Apprise mailto link for an email address, its provider and an app password."""
    address = _field(form, "email_address")
    if _EMAIL.match(address) is None:
        raise InvalidInputError("email_address", "Type the email address alerts should go to.")
    provider = _field(form, "email_provider") or "gmail"
    if provider == "custom":
        return _custom_server_url(form, address)
    if provider not in EMAIL_PROVIDERS:
        raise InvalidInputError("email_provider", "Pick your email provider from the list.")
    password = _field(form, "email_password")
    if not password:
        raise InvalidInputError(
            "email_password",
            "Add an app password. Gmail, Outlook and iCloud make one for you in your "
            "account's security settings; your normal password usually won't work.",
        )
    user = address.split("@", 1)[0]
    host = EMAIL_PROVIDERS[provider][1]
    return f"mailtos://{quote(user, safe='')}:{quote(password, safe='')}@{host}?to={quote(address)}"


def _custom_server_url(form: Mapping[str, Any], address: str) -> str:
    """A mail server given by hand: its name, port, encryption and an optional sign-in.

    The sign-in is optional because a relay on your own network often has none. Without
    a user name it signs in as the address itself, which is what most providers expect.
    """
    server = _field(form, "email_smtp").lower()
    if not server:
        raise InvalidInputError(
            "email_smtp", "Add your provider's outgoing mail server, like smtp.example.com."
        )
    if _MAIL_SERVER.match(server) is None:
        raise InvalidInputError(
            "email_smtp",
            "Only the server's name or address, like smtp.example.com, without https:// or a port.",
        )
    security = _field(form, "email_security") or "starttls"
    if security not in EMAIL_SECURITY:
        raise InvalidInputError("email_security", "Pick the kind of encryption from the list.")
    _, mode, port = EMAIL_SECURITY[security]
    if raw_port := _field(form, "email_port"):
        if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:  # noqa: PLR2004
            raise InvalidInputError("email_port", "The port is a number, like 587.")
        port = int(raw_port)
    user = _field(form, "email_user")
    password = _field(form, "email_password")
    if user and not password:
        raise InvalidInputError(
            "email_password",
            "Add the password for that user name, or leave both empty for a server that "
            "doesn't ask you to sign in.",
        )
    login = f"{quote(user or address, safe='')}:{quote(password, safe='')}@" if password else ""
    scheme = "mailto" if security == "none" else "mailtos"
    sender = quote(address)
    return f"{scheme}://{login}{server}:{port}?smtp={server}&mode={mode}&from={sender}&to={sender}"


def build(kind: str, form: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The name and config a form describes. Raises InvalidInputError naming the field."""
    name = _field(form, "name")
    match kind:
        case "discord":
            return name or "Discord", {"url": discord_url(_field(form, "discord_url"))}
        case "ntfy":
            return name or "Phone (ntfy)", ntfy_config(_field(form, "ntfy_topic"))
        case "apprise":
            link = _field(form, "apprise_url")
            urls = [link] if link else [email_url(form)]
            return name or "Email", {"urls": urls}
        case "webhook":
            url = _field(form, "webhook_url")
            if not url.startswith(("https://", "http://")):
                raise InvalidInputError("webhook_url", "The address must start with https://.")
            config: dict[str, Any] = {"url": url}
            if secret := _field(form, "webhook_secret"):
                config["secret"] = secret
            return name or "My app", config
        case _:
            raise InvalidInputError("kind", "Pick where alerts should go.")


def options(kind: str, form: Mapping[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """A destination's display options from its card on the Alerts page."""
    updated = dict(config)
    # Tiers replace the 1.x "deals only" switch; keeping both would let them disagree.
    updated.pop("deals_only", None)
    updated["tiers"] = _tier_list(form, "tiers")
    updated["silent_tiers"] = _tier_list(form, "silent_tiers")
    if not updated["tiers"]:
        raise InvalidInputError("tiers", "Pick at least one kind of listing to receive.")
    if kind == "discord":
        updated["ping_tiers"] = _tier_list(form, "ping_tiers")
        updated["style"] = "compact" if _field(form, "style") == "compact" else "card"
        mention = discord_mention(_field(form, "mention"))
        updated.pop("mention", None)
        if mention:
            updated["mention"] = mention
    elif kind == "telegram":
        updated["style"] = "gallery" if _field(form, "style") == "gallery" else "photo"
    elif kind == "ntfy":
        priority = _field(form, "priority") or "3"
        if priority not in {"2", "3", "4", "5"}:
            raise InvalidInputError("priority", "Pick a priority from the list.")
        updated["priority"] = int(priority)
    return updated


def _tier_list(form: Any, key: str) -> list[str]:
    raw = form.getlist(key) if hasattr(form, "getlist") else form.get(key) or []
    return [tier for tier in TIERS if tier in {str(value) for value in raw}]


def check(kind: str, config: dict[str, Any], settings: Settings, http: httpx.AsyncClient) -> None:
    """Ask the real sender whether it can work with this config. Raises InvalidInputError."""
    if kind == "telegram":
        return
    try:
        build_sender(Destination(id=0, kind=kind, name=kind, config=config), settings, http)
    except SenderConfigError as exc:
        raise InvalidInputError("config", f"That won't work: {exc}.") from exc
