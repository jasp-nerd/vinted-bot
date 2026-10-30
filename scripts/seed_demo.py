"""Fill a fresh database with invented searches, finds and history, for screenshots and demos.

    uv run python scripts/seed_demo.py /tmp/demo.db
    VINTED_SNIPER_DB_PATH=/tmp/demo.db VINTED_SNIPER_FETCH_MODE=mock \\
        VINTED_SNIPER_MOCK_SCENARIO_DIR=scripts/demo uv run vinted-sniper run

Every listing, seller and price here is made up; the photos are AI-generated and hosted
with the project site. Not part of the package. It writes through the repository like the
app does, then backdates timestamps with a few direct statements so the stats have a
month of history to draw. That shortcut is fine for a throwaway demo file and is exactly
why this lives in scripts/ rather than in the app.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from vinted_sniper.db import Database, apply_pending
from vinted_sniper.db.repo import Repo
from vinted_sniper.vinted import urls
from vinted_sniper.vinted.models import Item
from vinted_sniper.web.views import SLOT_COLORS

HERE = Path(__file__).parent
PHOTO_BASE = "https://vinted-sniper.jaspnerd.dev/assets/demo"
FEE_FIXED = Decimal("0.70")
FEE_RATE = Decimal("0.05")

# (name, site, search words, max total, slugs it finds, extra filters)
SEARCHES = [
    (
        "Denim under €35",
        "nl",
        "levi's",
        Decimal(35),
        ["straight-leg-jeans", "denim-jacket", "corduroy-trousers", "cargo-trousers"],
        {"banned_keywords": ["replica", "damaged"]},
    ),
    (
        "Coats and knits",
        "fr",
        "manteau laine",
        Decimal(110),
        ["trench-coat", "wool-coat", "cable-knit-sweater", "puffer-jacket"],
        {"deal_only_pct": None},
    ),
    (
        "Kids raincoats 98 to 110",
        "be",
        "regenjas",
        Decimal(20),
        ["kids-raincoat", "baby-romper-set"],
        {"quiet_start": "22:30", "quiet_end": "07:00"},
    ),
    (
        "Retro sportswear to resell",
        "de",
        "vintage trikot",
        Decimal(60),
        [
            "retro-football-shirt",
            "vintage-windbreaker",
            "running-shoes",
            "chunky-sneakers",
            "grey-hoodie",
        ],
        {
            "resale_price": Decimal(55),
            "resale_fee_pct": 10.0,
            "resale_shipping": Decimal("4.50"),
            "min_margin": Decimal(8),
        },
    ),
    (
        "Bags and scarves",
        "nl",
        "leather bag",
        Decimal(80),
        ["leather-handbag", "silk-scarf"],
        {"tags": ["gifts"]},
    ),
    (
        "Summer dresses",
        "es",
        "vestido midi",
        Decimal(30),
        ["floral-summer-dress", "breton-top", "flannel-shirt", "suede-boots", "leather-jacket"],
        {},
    ),
]

SELLERS = [
    "lou_atelier",
    "marchenoir",
    "jonasvintage",
    "kasia.closet",
    "tess.thrifts",
    "petitgrenier",
    "brocantine",
    "noor.wardrobe",
    "emilie_rangement",
    "wardrobe.of.ana",
]


def total_of(price: Decimal) -> Decimal:
    return (price + FEE_FIXED + price * FEE_RATE).quantize(Decimal("0.01"))


async def seed(
    path: Path, catalog: dict[str, dict[str, Any]], *, days: int, rng: random.Random
) -> None:
    async with Database(path) as db:
        await apply_pending(db)
        repo = Repo(db)
        now = int(time.time())

        phone = await repo.add_destination(
            kind="ntfy",
            name="My phone",
            config={
                "topic": "mags-demo-7f3k",
                "tiers": ["steal", "deal", "normal"],
                "silent_tiers": ["normal"],
            },
        )
        discord = await repo.add_destination(
            kind="discord",
            name="Flip Club #finds",
            config={
                "url": "https://discord.com/api/webhooks/1/demo",
                "style": "card",
                "ping_tiers": ["steal"],
            },
        )
        await repo.add_destination(kind="telegram", name="Telegram", config={"chat_id": "1000001"})

        item_id = 7_000_000_000
        planned: list[tuple[int, int, Item, dict[str, Decimal]]] = []
        query_ids: list[int] = []
        for index, (name, tld, words, budget, slugs, extra) in enumerate(SEARCHES):
            params = {"search_text": words, "order": "newest_first"}
            url = urls.normalise_search_url(
                f"https://www.vinted.{tld}/catalog?search_text={words.replace(' ', '+')}"
            )
            query_id = await repo.add_query(
                name=name,
                url=url,
                tld=tld,
                params=params,
                poll_interval_s=60,
                max_total_price=budget,
                color=SLOT_COLORS[index % len(SLOT_COLORS)],
                **{k: v for k, v in extra.items() if v is not None},
            )
            await repo.set_routes(query_id, [phone] if index % 2 else [phone, discord])
            typical = {
                "EUR": (
                    sum(Decimal(str(catalog[s]["price"])) for s in slugs)
                    / len(slugs)
                    * Decimal("1.12")
                ).quantize(Decimal("0.01"))
            }
            for day in range(days, -1, -1):
                for _ in range(rng.randint(0, 3 if day else 4)):
                    slug = rng.choice(slugs)
                    entry = catalog[slug]
                    price = (
                        Decimal(str(entry["price"])) * Decimal(str(rng.uniform(0.7, 1.2)))
                    ).quantize(Decimal("1"))
                    item_id += rng.randint(1, 900)
                    seller = rng.choice(SELLERS)
                    item = Item(
                        item_id=item_id,
                        tld=tld,
                        title=entry["title"],
                        url=urls.item_url(tld, item_id),
                        brand=entry.get("brand") if entry.get("brand") != "Unbranded" else None,
                        size=entry.get("size"),
                        condition=entry.get("condition"),
                        price=price,
                        total_price=total_of(price),
                        currency="EUR",
                        photo_url=f"{PHOTO_BASE}/{slug}.jpg",
                        photo_urls=(f"{PHOTO_BASE}/{slug}.jpg",),
                        seller_login=seller,
                        seller_id=100 + SELLERS.index(seller),
                        seller_rating=rng.choice([None, 0.92, 0.96, 1.0]),
                        seller_feedback_count=rng.choice([None, 7, 41, 128, 212]),
                    )
                    seen = now - day * 86_400 - rng.randint(60, 86_000 if day else 5_000)
                    planned.append((seen, query_id, item, typical))
            query_ids.append(query_id)

        # Stored oldest first, so the feed's order (by when each was stored) is by time.
        for seen, query_id, item, typical in sorted(planned, key=lambda row: row[0]):
            query = await repo.get_query(query_id)
            assert query is not None
            await repo.record_new_items(query, [item], [phone], typical_prices=typical)
            await db.execute(
                "UPDATE items SET first_seen_at = ? WHERE item_id = ?", (seen, item.item_id)
            )
            await db.execute(
                "UPDATE query_items SET first_seen_at = ? WHERE item_id = ?", (seen, item.item_id)
            )
        for query_id in query_ids:
            await repo.record_success(
                query_id,
                newest_raw_ts=now - 120,
                newest_item_ts=now - 120,
                seen=rng.randint(4_000, 30_000),
                stale_cycles=0,
                newest_raw_id=item_id,
            )

        # A month of delivery: most sent, a handful failed.
        await db.execute("UPDATE outbox SET status = 'sent' WHERE status = 'pending'")
        await db.execute("UPDATE outbox SET status = 'failed' WHERE id % 37 = 0")
        # One search that Vinted asked to slow down, to show how that reads.
        await repo.record_failure(4, "http_429", "rate limited for 30s")
        # Something to look at on the other pages.
        await repo.block_seller(990, login="bulkdeals_eu", tld="fr", reason="Only replicas")
        await repo.add_watch(kind="seller", tld="nl", target_id=103, label="kasia.closet")
        await repo.set_onboarded(True)
        await repo.heartbeat()
    print(f"Demo database written to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    catalog = {
        entry["slug"]: entry for entry in json.loads((HERE / "demo/catalog.json").read_text())
    }
    args.path.unlink(missing_ok=True)
    asyncio.run(seed(args.path, catalog, days=args.days, rng=random.Random(args.seed)))


if __name__ == "__main__":
    main()
