"""Found listings as CSV or JSON, for a spreadsheet or someone else's script.

Shared by `vinted-sniper export` and the dashboard's download button, so both produce the
same columns in the same order.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any, Literal

from vinted_sniper.db.repo import FeedItem

ExportFormat = Literal["csv", "json"]

COLUMNS = (
    "item_id",
    "site",
    "title",
    "brand",
    "size",
    "condition",
    "price",
    "total_price",
    "currency",
    "typical_price",
    "deal_pct",
    "search",
    "seller",
    "seller_country",
    "mark",
    "found_at",
    "listed_at",
    "url",
    "photo_url",
)


def _iso(epoch: int | None) -> str | None:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat() if epoch is not None else None


def _record(entry: FeedItem) -> dict[str, Any]:
    item = entry.item
    return {
        "item_id": item.item_id,
        "site": f"vinted.{item.tld}",
        "title": item.title,
        "brand": item.brand,
        "size": item.size,
        "condition": item.condition,
        # Strings, so 15.00 stays 15.00 rather than becoming a float.
        "price": str(item.price) if item.price is not None else None,
        "total_price": str(item.total_price) if item.total_price is not None else None,
        "currency": item.currency,
        "typical_price": str(entry.typical_price) if entry.typical_price is not None else None,
        "deal_pct": entry.deal_pct,
        "search": entry.query_name,
        "seller": item.seller_login,
        "seller_country": entry.seller_country,
        "mark": entry.mark,
        "found_at": _iso(entry.first_seen_at),
        "listed_at": _iso(item.photo_ts),
        "url": item.url,
        "photo_url": item.photo_url,
    }


def render(entries: list[FeedItem], fmt: ExportFormat) -> str:
    """Render listings in the chosen format, newest first as given."""
    records = [_record(entry) for entry in entries]
    if fmt == "json":
        return json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: _cell(value) for key, value in record.items()} for record in records)
    return buffer.getvalue()


# What makes a spreadsheet read a cell as a formula rather than text.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> Any:
    """A CSV cell that a spreadsheet will show, not run.

    Titles and seller names are whatever a Vinted seller typed, and a title such as
    `=HYPERLINK(...)` would otherwise run as a formula when the export is opened in Excel
    or LibreOffice. A leading apostrophe is the convention both read as "this is text".
    Only strings are touched, so a negative deal percentage stays a number.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value
