"""The Alerts page's "What it looks like": a sample alert drawn from what would be sent.

`deliver.preview_payload` returns the exact message a Discord or Telegram place would
receive for an invented listing, with that place's own options (card or compact, one
photo or all, the ping). This turns that message into something a browser can show:
the text with its bold and small lines, the photos and the buttons. Nothing here decides
what an alert says; a change to the senders shows up here without a change to this file.

Everything is escaped first and only a short list of tags is let back in, since a
Telegram caption is HTML and a listing's title is whatever the seller typed.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any

from vinted_bot.deliver import preview_payload

# Discord component types (Components V2): container, section, text, thumbnail, gallery,
# action row and button.
_CONTAINER, _SECTION, _TEXT, _THUMBNAIL, _GALLERY, _ROW, _BUTTON = 17, 9, 10, 11, 12, 1, 2

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MENTION = re.compile(r"&lt;@(&amp;)?!?(\d+)&gt;")
_TIMESTAMP = re.compile(r"&lt;t:\d+:R&gt;")
_ESCAPED = re.compile(r"\\([\\*_~|`>#\-\[\]()<:])")

# The tags a Telegram message may keep, and the one attribute worth keeping on any.
_KEEP = {"b", "strong", "i", "em", "mark", "p", "h3", "table", "tr", "td", "footer", "blockquote"}


def look(destination_kind: str, config: dict[str, Any], tld: str) -> dict[str, Any] | None:
    """A sample alert for the page, or None for kinds that have no picture worth drawing."""
    match destination_kind:
        case "discord":
            return _discord(preview_payload("discord", config=config, tld=tld))
        case "telegram":
            return _telegram(preview_payload("telegram", config=config, tld=tld))
        case _:
            return None


def _discord(payload: dict[str, Any]) -> dict[str, Any]:
    lines: list[dict[str, str]] = []
    photos: list[str] = []
    buttons: list[str] = []
    accent = None
    for block in payload.get("components") or []:
        if block.get("type") == _CONTAINER:
            accent = block.get("accent_color")
        for part in _flatten(block):
            kind = part.get("type")
            if kind == _TEXT:
                lines.extend(_discord_text(str(part.get("content") or "")))
            elif kind in {_GALLERY, _THUMBNAIL}:
                media = part.get("items") or [part]
                photos.extend(str((m.get("media") or {}).get("url") or "") for m in media)
            elif kind == _BUTTON and part.get("label"):
                buttons.append(str(part["label"]))
    return {
        "kind": "discord",
        "name": payload.get("username") or "vinted-bot",
        "accent": f"#{accent:06x}" if isinstance(accent, int) else None,
        "lines": lines,
        "photos": [p for p in photos if p.startswith("https://")][:4],
        "buttons": [buttons],
    }


def _flatten(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Every component inside a block, the block itself first, in reading order."""
    found = [block]
    for child in block.get("components") or []:
        found.extend(_flatten(child))
    if accessory := block.get("accessory"):
        found.append(accessory)
    return found


def _discord_text(content: str) -> list[dict[str, str]]:
    lines = []
    for raw in content.splitlines():
        small = raw.startswith("-# ")
        text = html.escape(_ESCAPED.sub(r"\1", raw.removeprefix("-# ")), quote=False)
        text = _BOLD.sub(r"<b>\1</b>", text)
        text = _MENTION.sub(lambda m: "@role" if m.group(1) else "@someone", text)
        text = _TIMESTAMP.sub("just now", text)
        lines.append({"html": text, "small": "1" if small else ""})
    return lines


def _telegram(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params") or {}
    rich = params.get("rich_message") or {}
    body = str(rich.get("html") or params.get("caption") or params.get("text") or "")
    photos = [str(params["photo"])] if params.get("photo") else []
    clean = _Sanitiser()
    clean.feed(body)
    photos.extend(clean.photos)
    keyboard = (params.get("reply_markup") or {}).get("inline_keyboard") or []
    return {
        "kind": "telegram",
        "name": "Your bot",
        "accent": None,
        "html": clean.text().replace("\n", "<br>"),
        "photos": [p for p in photos if p.startswith("https://")][:4],
        "buttons": [[str(b.get("text") or "") for b in row] for row in keyboard],
    }


class _Sanitiser(HTMLParser):
    """Telegram's HTML with only plain formatting kept; links become plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self.photos: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.photos.extend(value for name, value in attrs if name == "src" and value)
        elif tag == "br":
            self._out.append("\n")
        elif tag in _KEEP:
            self._out.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _KEEP:
            self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._out.append(html.escape(data, quote=False))

    def text(self) -> str:
        return "".join(self._out).strip()
