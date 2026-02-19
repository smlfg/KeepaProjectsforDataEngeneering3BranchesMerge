#!/usr/bin/env python3
"""
EU QWERTZ Keyboard Discovery - IMPROVED VERSION
==============================================
- Stronger QWERTZ filtering
- Better rate limiting
- Known QWERTZ brands priority
"""

import asyncio
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("discover")

KEEPA_API_BASE = "https://api.keepa.com"
DOMAINS = {"UK": 2, "FR": 4, "IT": 8, "ES": 9}

# STRONG QWERTZ indicators - must have at least ONE
QWERTZ_INDICATORS = [
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
    "iso-de",
    "iso german",
]

# NEUTRAL - could be QWERTZ but not guaranteed
NEUTRAL_KEYWORDS = [
    "keyboard",
    "keypad",
    "mechanical",
    "gaming",
    "cherry mx",
    "cherry",
    "logitech",
    "razer",
    "corsair",
    "keychron",
    "steelseries",
    "ducky",
    "anne",
    "royal kludge",
    "hyperx",
    "msi",
]

# KNOWN QWERTZ BRANDS (high confidence)
QWERTZ_BRANDS = [
    "cherry",
    "cherry mx",
    "cherry kc",
    "logitech k120",
    "logitech k400",
    "logitech k380",
    "microsoft sculpt",
    "microsoft surface keyboard",
    "perixx",
    "fortez",
    "keychron k",
    "keychron q",
    "coolermaster",
    "thermaltake",
    "razer blackwidow",
    "corsair k70",
    "corsair k95",
    "steelseries apex",
]

# Pool: Known keyboard ASINs (prioritized by QWERTZ likelihood)
ASIN_POOL = [
    # Cherry - GERMAN brand, HIGH confidence QWERTZ
    "B009EOZ41Y",
    "B00VBGT00Q",
    "B007VDPID6",
    "B082TN5P76",
    "B08STKPTJ8",
    "B09K4ZYWKZ",
    "B0B9ZK5M5W",
    "B00FVKLR42",
    "B079PRXQPL",
    "B0187CKZVE",
    "B00XBGG62Y",
    "B06XKNR8LJ",
    "B0794WQSPS",
    "B07PM8T4Y1",
    "B00VBGT0J6",
    "B07PMBHH1D",
    "B07PM9HWK1",
    "B07PM9HWDT",
    "B07PMB5N38",
    "B07PMBHH1D",
    "B07PM9HWK1",
    "B0794WQSPS",
    # Logitech - many have QWERTZ variants
    "B003ELVLKU",
    "B014EUQOGK",
    "B00ZK4RK3K",
    "B01E8KO2B0",
    "B07WGFC44F",
    "B01N4FXKH5",
    "B07QKD9V4F",
    "B07FWHKJXH",
    "B08CVY5G6Q",
    "B08CRDDXDC",
    "B08DTGCKKX",
    "B0B3QDNV44",
    "B09QX3PLWB",
    "B09F3Z8P3B",
    "B07CMQF9C7",
    "B09MTYZBXF",
    "B0B7NQHTSB",
    "B09TPJQ8GV",
    "B07C7DTGMF",
    "B07R7FFVG4",
    "B0BG9XFMC4",
    "B0BKRGMKM1",
    "B09ZVB8VKQ",
    # Microsoft
    "B07H4Z4JQG",
    "B00450LDR4",
    "B077XCXZKK",
    "B09ZD1J9ZQ",
    "B0BQHRSQG5",
    "B09H2KQTWF",
    "B0795DW9MT",
    "B01NABDNPH",
    "B01MZYSL9C",
    "B019YH3KOQ",
    # Corsair (gaming, often QWERTZ in EU)
    "B07S92G6DL",
    "B07VLBPZMV",
    "B0BFB6YRRX",
    "B09GH5YPLT",
    "B08FWF2LRZ",
    "B07GGTZQX2",
    "B07K6MMPFK",
    "B07RFSVGDN",
    "B09Q2M2WGH",
    "B08FK7YPBB",
    # Razer
    "B07T5XVYQL",
    "B0821CRNDX",
    "B09JD4ND26",
    "B07YM2DLBP",
    "B09NYNKPBK",
    "B08BF4NGWN",
    "B083BXTV5N",
    "B07S5G9VTF",
    "B09K3T6YN6",
    "B0948RZPRD",
    # SteelSeries
    "B09M1PQ8RN",
    "B09GR7HS6D",
    "B08X4FJF1N",
    "B08PC2ZQMM",
    "B07FXTJN7Y",
    "B09B96KFQX",
    "B07BHV6SHW",
    "B09VSWSRWK",
    "B0BCKPWXPT",
    "B09S9NKNG1",
    # Keychron
    "B08JQ5GTRN",
    "B08WZJQSQ3",
    "B09CGBBVMK",
    "B0BGGWYJXT",
    "B09JGGBMDR",
    "B09CGHTB5N",
    "B0BJZT3JF8",
    "B09JGB7NLC",
    "B0BM7N7TDN",
    "B0B4YDTMJJ",
    # Ducky / Qisan
    "B08VK6D4YH",
    "B09T3WMVT5",
    "B08G4ZJLHW",
    "B09VFKLG2N",
    "B09K65D68K",
    "B08VK6RPWJ",
    "B07VZ3XKPJ",
    "B09DFQN5D3",
    "B0B75PKX2G",
    "B09NYPFKPX",
    # ASUS / Perixx / Misc
    "B083GTF9BR",
    "B0B3QDKN4D",
    "B09NQ5WX6X",
    "B0948RY6XV",
    "B09CGPGQBR",
    "B00MBLQGGE",
    "B07ZTFHQFP",
    "B07DHNX4XB",
    "B07PMBHH1D",
    "B07PM9HWK1",
]
ASIN_POOL = list(dict.fromkeys(ASIN_POOL))

STATS = {"tokens": 0, "found": 0, "errors": 0, "filtered": 0}


def get_api_key() -> str:
    api_key = os.environ.get("KEEPA_API_KEY", "")
    if not api_key:
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("KEEPA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return api_key


def is_likely_qwertz(title: str) -> bool:
    """Check if product title indicates QWERTZ layout."""
    title_lower = title.lower()

    # STRONG indicator - definitely QWERTZ
    for indicator in QWERTZ_INDICATORS:
        if indicator in title_lower:
            return True

    # Check for brand + neutral keyword (likely QWERTZ in EU)
    has_brand = any(brand in title_lower for brand in QWERTZ_BRANDS)
    has_neutral = any(kw in title_lower for kw in NEUTRAL_KEYWORDS)

    if has_brand and has_neutral:
        return True

    return False


async def check_tokens(client, api_key):
    try:
        resp = await client.get(
            f"{KEEPA_API_BASE}/token", params={"key": api_key}, timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except:
        pass
    return {"tokensLeft": 0, "refillIn": 60}


async def wait_for_tokens(client, api_key, needed=10, max_wait=120):
    """Wait for tokens with timeout."""
    start = time.time()
    while True:
        status = await check_tokens(client, api_key)
        tokens = status.get("tokensLeft", 0)
        if tokens >= needed:
            return tokens

        elapsed = time.time() - start
        if elapsed > max_wait:
            log.warning(f"⏱️ Token wait timeout after {elapsed:.0f}s")
            return tokens

        wait = min(status.get("refillIn", 60), 30)
        log.info(f"⏳ Tokens: {tokens}/{needed}, waiting {wait}s...")
        await asyncio.sleep(wait + 2)


async def validate_batch(client, api_key, asins, domain_id, domain_name, batch_size=30):
    validated = []

    for i in range(0, len(asins), batch_size):
        batch = asins[i : i + batch_size]

        # Wait for tokens
        await wait_for_tokens(client, api_key, needed=15)

        try:
            resp = await client.get(
                f"{KEEPA_API_BASE}/product",
                params={"key": api_key, "domain": domain_id, "asin": ",".join(batch)},
                timeout=30,
            )

            if resp.status_code == 429:
                log.warning(f"  Rate limited, waiting 60s...")
                await asyncio.sleep(60)
                continue

            if resp.status_code != 200:
                STATS["errors"] += 1
                continue

            data = resp.json()
            STATS["tokens"] += data.get("tokensConsumed", 0)

            for p in data.get("products", []):
                asin = p.get("asin", "")
                title = p.get("title", "")

                if not title:
                    continue

                # QWERTZ FILTER
                if not is_likely_qwertz(title):
                    STATS["filtered"] += 1
                    continue

                csv_data = p.get("csv", [])

                def price(idx):
                    if len(csv_data) > idx and csv_data[idx] and csv_data[idx][-1] > 0:
                        return csv_data[idx][-1] / 100
                    return None

                new_p, used_p, list_p = price(1), price(2), price(0)
                list_p = list_p or new_p

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
                        "validated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        except Exception as e:
            log.warning(f"  Error: {e}")
            STATS["errors"] += 1

        # Pause between batches
        await asyncio.sleep(2)

    return validated


async def discover(target=1000):
    api_key = get_api_key()
    if not api_key:
        log.error("No API key!")
        return []

    all_validated = []
    seen = set()

    async with httpx.AsyncClient() as client:
        for domain_name, domain_id in DOMAINS.items():
            log.info(f"\n{'=' * 40}")
            log.info(f"🔍 {domain_name} (ID={domain_id})")

            validated = await validate_batch(
                client, api_key, ASIN_POOL, domain_id, domain_name
            )

            for v in validated:
                key = (v["asin"], v["domain"])
                if key not in seen:
                    seen.add(key)
                    all_validated.append(v)
                    STATS["found"] += 1

            log.info(f"  ✅ {len(validated)} QWERTZ | Total: {len(all_validated)}")

    return all_validated


def save_results(results, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        writer.writerows(results)

    log.info(f"💾 Saved {len(results)} validated QWERTZ to {output_path}")

    # Also save JSON
    json_path = output_path.with_suffix(".json")
    payload = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "domains": list(DOMAINS.keys()),
            "total": len(results),
            "stats": STATS,
        },
        "by_domain": {d: [] for d in DOMAINS},
        "all_asins": [r["asin"] for r in results],
    }
    for r in results:
        payload["by_domain"][r["domain"]].append(r)

    json_path.write_text(json.dumps(payload, indent=2))
    log.info(f"💾 Saved JSON to {json_path}")


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=1000)
    parser.add_argument("--output", default="data/seed_targets_eu_qwertz.csv")
    args = parser.parse_args()

    log.info(f"🚀 QWERTZ Discovery - Target: {args.target}")
    log.info(f"   Pool: {len(ASIN_POOL)} ASINs | Domains: {list(DOMAINS.keys())}")

    start = time.time()
    results = await discover(args.target)

    elapsed = time.time() - start
    log.info(f"\n{'=' * 50}")
    log.info(f"📊 DONE: {len(results)} QWERTZ in {elapsed / 60:.1f} min")
    log.info(
        f"   Tokens: {STATS['tokens']} | Filtered: {STATS['filtered']} | Errors: {STATS['errors']}"
    )

    save_results(results, Path(__file__).parent.parent / args.output)


if __name__ == "__main__":
    asyncio.run(main())
