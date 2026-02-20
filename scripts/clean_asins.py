#!/usr/bin/env python3
"""
ASIN Cleaner & Validator
=========================
Bereinigt Roh-ASINs vom Web Agent, filtert QWERTZ, entfernt ungültige.

Usage:
    python scripts/clean_asins.py --input data/amazon_agent_raw.txt --output data/qwertz_cleaned.csv
    python scripts/clean_asins.py --input data/amazon_agent_raw.txt --validate --keepa-key KEY
"""

import argparse
import csv
import re
import sys
from pathlib import Path

QWERTZ_KEYWORDS = [
    "qwertz",
    "german",
    "deutsch",
    "germany",
    "layout",
    "tastatur",
    "tastiera",
    "teclado",
    "clavier",
    "iso",
    "deutschland",
]

EXCLUDE_KEYWORDS = [
    "qwerty us",
    "qwerty uk",
    "qwerty us layout",
    "qwerty uk layout",
    "azerty",
    " french",
    " français",
]


def parse_agent_output(text: str) -> list[dict]:
    """Parst die rohe Ausgabe vom Web Agent."""
    results = []

    lines = text.strip().split("\n")
    current_market = None

    for line in lines:
        line = line.strip()

        if not line:
            continue

        if line.startswith("UK)") or "amazon.co.uk" in line.lower():
            current_market = "UK"
            continue
        elif line.startswith("FR)") or "amazon.fr" in line.lower():
            current_market = "FR"
            continue
        elif line.startswith("IT)") or "amazon.it" in line.lower():
            current_market = "IT"
            continue
        elif line.startswith("ES)") or "amazon.es" in line.lower():
            current_market = "ES"
            continue

        asin_match = re.search(r"(B[A-Z0-9]{9})", line, re.IGNORECASE)
        if asin_match and current_market:
            asin = asin_match.group(1).upper()

            title = line
            price = None
            price_match = re.search(
                r"(?:€|EUR|£)\s*([\d]+[.,]?\d*)", line, re.IGNORECASE
            )
            if price_match:
                price_str = price_match.group(1).replace(",", ".")
                try:
                    price = float(price_str)
                except:
                    pass

            results.append(
                {
                    "asin": asin,
                    "title": title[:150],
                    "price": price,
                    "market": current_market,
                    "raw_line": line,
                }
            )

    return results


def is_qwertz(title: str) -> bool:
    """Prüft ob Titel QWERTZ-Layout hat."""
    if not title:
        return False

    title_lower = title.lower()

    for kw in EXCLUDE_KEYWORDS:
        if kw in title_lower:
            return False

    for kw in QWERTZ_KEYWORDS:
        if kw in title_lower:
            return True

    return False


def clean_asins(entries: list[dict]) -> list[dict]:
    """Filtert und bereinigt ASINs."""
    cleaned = []
    seen = set()

    for entry in entries:
        asin = entry.get("asin", "")
        title = entry.get("title", "")
        market = entry.get("market", "")

        if not asin or len(asin) != 10:
            continue

        if not title or title == "N/A":
            continue

        if not is_qwertz(title):
            continue

        key = (asin, market)
        if key in seen:
            continue
        seen.add(key)

        cleaned.append(
            {
                "asin": asin,
                "title": title,
                "market": market,
                "price": entry.get("price"),
            }
        )

    return cleaned


def validate_with_keepa(entries: list[dict], api_key: str) -> list[dict]:
    """Validiert ASINs mit Keepa API."""
    import asyncio
    import httpx
    from datetime import datetime, timezone

    DOMAINS = {"UK": 2, "FR": 4, "IT": 8, "ES": 9}

    validated = []

    asins_by_domain = {}
    for e in entries:
        domain = e["market"]
        if domain not in asins_by_domain:
            asins_by_domain[domain] = []
        asins_by_domain[domain].append(e["asin"])

    async def run():
        nonlocal validated

        async with httpx.AsyncClient() as client:
            for domain_name, domain_id in DOMAINS.items():
                if domain_name not in asins_by_domain:
                    continue

                asins = asins_by_domain[domain_name]
                print(f"Validating {domain_name}: {len(asins)} ASINs...")

                for i in range(0, len(asins), 30):
                    batch = asins[i : i + 30]

                    try:
                        resp = await client.get(
                            "https://api.keepa.com/product",
                            params={
                                "key": api_key,
                                "domain": domain_id,
                                "asin": ",".join(batch),
                            },
                            timeout=30,
                        )

                        if resp.status_code != 200:
                            print(f"  Error: {resp.status_code}")
                            continue

                        data = resp.json()
                        products = data.get("products", [])

                        for p in products:
                            asin = p.get("asin", "")
                            title = p.get("title", "")

                            if not title:
                                continue

                            csv_data = p.get("csv", [])

                            def price(idx):
                                if (
                                    len(csv_data) > idx
                                    and csv_data[idx]
                                    and csv_data[idx][-1] > 0
                                ):
                                    return csv_data[idx][-1] / 100
                                return None

                            new_p = price(1)
                            used_p = price(2)
                            list_p = price(0) or new_p

                            discount = None
                            if used_p and list_p and list_p > 0:
                                discount = round((1 - used_p / list_p) * 100, 1)

                            rating = p.get("rating")
                            if rating:
                                rating = rating / 10

                            validated.append(
                                {
                                    "asin": asin,
                                    "domain": domain_name,
                                    "domain_id": domain_id,
                                    "title": title[:150],
                                    "new_price": new_p,
                                    "used_price": used_p,
                                    "list_price": list_p,
                                    "discount_percent": discount,
                                    "rating": rating,
                                    "validated_at": datetime.now(
                                        timezone.utc
                                    ).isoformat(),
                                }
                            )

                    except Exception as e:
                        print(f"  Error: {e}")

                    await asyncio.sleep(1)

    asyncio.run(run())
    return validated


def save_csv(entries: list[dict], output_path: Path):
    """Speichert als CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["asin", "title", "market", "price"]
    if entries and "domain" in entries[0]:
        fieldnames = [
            "asin",
            "domain",
            "domain_id",
            "title",
            "new_price",
            "used_price",
            "list_price",
            "discount_percent",
            "rating",
            "validated_at",
        ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entries)

    print(f"✅ Saved {len(entries)} entries to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Clean and validate ASINs")
    parser.add_argument(
        "--input", "-i", required=True, help="Input file (raw agent output or CSV)"
    )
    parser.add_argument(
        "--output", "-o", default="data/qwertz_cleaned.csv", help="Output CSV"
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate with Keepa API"
    )
    parser.add_argument("--keepa-key", help="Keepa API key (or set KEEPA_API_KEY env)")
    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input file {input_path} not found")
        sys.exit(1)

    content = input_path.read_text(encoding="utf-8")

    if content.startswith("asin"):
        print("Detected CSV format...")
        reader = csv.DictReader(content.splitlines())
        entries = list(reader)
    else:
        print("Detected raw text format...")
        entries = parse_agent_output(content)

    print(f"Parsed: {len(entries)} entries")

    cleaned = clean_asins(entries)
    print(f"After QWERTZ filter: {len(cleaned)} entries")

    if args.validate:
        api_key = args.keepa_key
        if not api_key:
            import os

            api_key = os.environ.get("KEEPA_API_KEY", "")

        if not api_key:
            print("Error: No Keepa API key. Set --keepa-key or KEEPA_API_KEY")
            sys.exit(1)

        print("Validating with Keepa...")
        validated = validate_with_keepa(cleaned, api_key)
        print(f"Keepa validation: {len(validated)} valid entries")
        cleaned = validated

    output_path = Path(args.output)
    save_csv(cleaned, output_path)

    summary = {}
    for e in cleaned:
        m = e.get("market") or e.get("domain", "?")
        summary[m] = summary.get(m, 0) + 1

    print("\nSummary:")
    for m, c in sorted(summary.items()):
        print(f"  {m}: {c}")


if __name__ == "__main__":
    main()
