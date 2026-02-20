#!/usr/bin/env python3
"""
Flat/Slim Keyboard ASIN Discovery Script
==========================================
Discover flat/slim keyboards across EU markets using Keepa API.

Usage:
    python scripts/discover_flat_keyboards.py

Output:
    data/seed_flat_keyboards.csv
"""

import argparse
import asyncio
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "keepa_client_module",
    Path(__file__).parent.parent / "src" / "services" / "keepa_client.py",
)
keepa_client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keepa_client_module)
KeepaClient = keepa_client_module.KeepaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("discover_flat_keyboards")

DOMAINS = {
    "UK": 2,
    "DE": 3,
    "FR": 4,
    "IT": 8,
    "ES": 9,
}

KEYWORDS = {
    "UK": ["slim keyboard", "flat keyboard", "low profile keyboard", "thin keyboard"],
    "DE": ["flache tastatur", "slim tastatur", "flach tastatur", "ultra slim tastatur"],
    "FR": ["clavier plat", "clavier slim", "clavier fin"],
    "IT": ["tastiera slim", "tastiera piatta"],
    "ES": ["teclado plano", "teclado slim", "teclado ultrafino"],
}

LAYOUT_KEYWORDS = {
    "UK": ["qwerty", "uk layout", "british"],
    "DE": ["qwertz", "deutsch", "german layout", "qwertztastatur"],
    "FR": ["azerty", "francais", "french layout"],
    "IT": ["italiano", "italian layout", "qwerty"],
    "ES": ["espanol", "spanish layout", "qwerty"],
}

ALL_KEYWORDS = {
    "UK": KEYWORDS["UK"] + LAYOUT_KEYWORDS["UK"],
    "DE": KEYWORDS["DE"] + LAYOUT_KEYWORDS["DE"],
    "FR": KEYWORDS["FR"] + LAYOUT_KEYWORDS["FR"],
    "IT": KEYWORDS["IT"] + LAYOUT_KEYWORDS["IT"],
    "ES": KEYWORDS["ES"] + LAYOUT_KEYWORDS["ES"],
}

stats = {
    "searches": 0,
    "asins_found": 0,
    "products_fetched": 0,
    "validated": 0,
    "errors": 0,
}


async def search_keyword(
    client: KeepaClient, keyword: str, domain_id: int, page: int = 1
) -> list[str]:
    """Search for products with a keyword and return ASINs."""
    try:
        response = await client.search_products(
            search_term=keyword,
            domain_id=domain_id,
            page=page,
        )
        stats["searches"] += 1

        products = response.get("raw", {}).get("products", [])
        asins = [p.get("asin") for p in products if p.get("asin")]
        stats["asins_found"] += len(asins)

        return asins
    except Exception as e:
        log.warning(f"Search failed for '{keyword}' on domain {domain_id}: {e}")
        stats["errors"] += 1
        return []


async def validate_product(
    client: KeepaClient, asin: str, domain_id: int, market: str
) -> dict | None:
    """Validate a product: check price data and layout keywords in title."""
    try:
        response = await client.get_products([asin], domain_id)
        stats["products_fetched"] += 1

        products = response.get("raw", {}).get("products", [])
        if not products:
            return None

        product = products[0]
        title = (product.get("title") or "").lower()
        csv_data = product.get("csv") or []

        amazon_price = None
        new_price = None

        if len(csv_data) > 0 and csv_data[0] and len(csv_data[0]) >= 2:
            val = csv_data[0][-1]
            if val != -1:
                amazon_price = val / 100.0

        if len(csv_data) > 1 and csv_data[1] and len(csv_data[1]) >= 2:
            val = csv_data[1][-1]
            if val != -1:
                new_price = val / 100.0

        if amazon_price is None and new_price is None:
            return None

        layout_kws = LAYOUT_KEYWORDS.get(market, [])
        if not any(kw in title for kw in layout_kws):
            return None

        return {
            "asin": asin,
            "domain_id": domain_id,
            "market": market,
            "title": product.get("title", "")[:200],
            "new_price": new_price if new_price else amazon_price,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        log.warning(f"Validation failed for {asin}: {e}")
        stats["errors"] += 1
        return None


async def discover_market(
    client: KeepaClient, market: str, domain_id: int, max_per_keyword: int = 20
) -> list[dict]:
    """Discover flat/slim keyboards for a specific market."""
    log.info(f"Discovering flat keyboards for {market} (domain={domain_id})")

    keywords = ALL_KEYWORDS.get(market, [])
    all_asins = set()

    for keyword in keywords:
        log.info(f"  Searching: '{keyword}'")

        for page in range(1, 3):
            asins = await search_keyword(client, keyword, domain_id, page)
            all_asins.update(asins)

            if len(asins) == 0:
                break

            await asyncio.sleep(2)

    log.info(f"  Found {len(all_asins)} unique ASINs")

    validated = []
    asin_list = list(all_asins)

    batch_size = 10
    for i in range(0, len(asin_list), batch_size):
        batch = asin_list[i : i + batch_size]

        for asin in batch:
            result = await validate_product(client, asin, domain_id, market)
            if result:
                validated.append(result)
                stats["validated"] += 1
                log.info(f"    Validated: {asin}")

            await asyncio.sleep(1)

        if len(validated) >= max_per_keyword:
            break

        await asyncio.sleep(3)

    log.info(f"  {len(validated)} validated products for {market}")
    return validated[:max_per_keyword]


async def discover_all_markets(
    client: KeepaClient, max_per_market: int = 20
) -> list[dict]:
    """Discover flat/slim keyboards across all markets."""
    results = []

    for market, domain_id in DOMAINS.items():
        validated = await discover_market(client, market, domain_id, max_per_market)
        results.extend(validated)

        await asyncio.sleep(5)

    return results


def write_csv(results: list[dict], output_path: Path):
    """Write results to CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["asin", "domain_id", "market", "title", "new_price", "validated_at"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    log.info(f"Written {len(results)} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Discover flat/slim keyboard ASINs via Keepa"
    )
    parser.add_argument("--max-per-market", type=int, default=20)
    parser.add_argument("--output", type=str, default="data/seed_flat_keyboards.csv")
    args = parser.parse_args()

    api_key = os.environ.get("KEEPA_API_KEY", "")
    if not api_key:
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("KEEPA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        log.error("KEEPA_API_KEY not set.")
        sys.exit(1)

    log.info("Starting flat/slim keyboard discovery")
    log.info(f"   Markets: {', '.join(DOMAINS.keys())}")

    client = KeepaClient(api_key=api_key)

    results = asyncio.run(discover_all_markets(client, args.max_per_market))

    output_path = Path(__file__).parent.parent / args.output
    write_csv(results, output_path)

    log.info(f"Discovery complete: {len(results)} validated entries")
    log.info(f"Stats: {stats}")


if __name__ == "__main__":
    main()
