#!/usr/bin/env python3
"""
EU QWERTZ/EU Keyboard ASIN Discovery Script - VERSION 2
=========================================================
Mit smartem Rate-Limiting und Token-Tracking.

Usage:
    python scripts/discover_eu_qwertz_asins_v2.py --max-per-domain 20 --batch-size 10

Output:
    data/seed_asins_eu_qwertz.json
"""

import argparse
import asyncio
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
log = logging.getLogger("discover_v2")

DOMAINS = {
    "UK": 2,
    "FR": 4,
    "IT": 8,
    "ES": 9,
}

KEEPA_API_BASE = "https://api.keepa.com"

KEYBOARD_EVIDENCE = [
    "keyboard",
    "tastatur",
    "clavier",
    "tastiera",
    "teclado",
    "qwerty",
    "qwertz",
    "azerty",
    "mechanical",
    "mécanique",
    "klawiatura",
    "toetsenbord",
    "wireless keyboard",
    "gaming keyboard",
    "mx keys",
    "k380",
    "k120",
    "g915",
    "g815",
    "g413",
    "cherry mx",
    "cherry kc",
    "razer huntsman",
    "razer blackwidow",
    "corsair k70",
    "corsair k55",
    "steelseries apex",
    "keychron",
    "ducky",
    "anne pro",
    "royal kludge",
    "logitech k",
    "microsoft sculpt",
    "microsoft surface keyboard",
]

CANDIDATE_POOL = [
    "B07WGFC44F",
    "B01N4FXKH5",
    "B003ELVLKU",
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
    "B009EOZ41Y",
    "B00VBGT00Q",
    "B007VDPID6",
    "B014EUQOGK",
    "B00ZK4RK3K",
    "B01E8KO2B0",
    "B082TN5P76",
    "B08STKPTJ8",
    "B09K4ZYWKZ",
    "B0B9ZK5M5W",
    "B00FVKLR42",
    "B079PRXQPL",
    "B0187CKZVE",
    "B00XBGG62Y",
    "B06XKNR8LJ",
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
    "B083GTF9BR",
    "B0B3QDKN4D",
    "B09NQ5WX6X",
    "B0948RY6XV",
    "B09CGPGQBR",
    "B00MBLQGGE",
    "B07ZTFHQFP",
    "B01E8KO2B0",
    "B00450LDR4",
    "B009EOZ41Y",
]
CANDIDATE_POOL = list(dict.fromkeys(CANDIDATE_POOL))

_bad_asins = set()

stats = {
    "requests": 0,
    "tokens_used": 0,
    "rate_limits": 0,
    "success": 0,
    "errors": 0,
}


def _latest_price(csv_slot):
    if not csv_slot or len(csv_slot) < 2:
        return None
    val = csv_slot[-1]
    return val / 100.0 if val != -1 else None


def _has_keyboard_evidence(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in KEYBOARD_EVIDENCE)


async def wait_for_tokens(client: httpx.AsyncClient, api_key: str, min_tokens: int = 5):
    """Check token status and wait if needed - ADAPTED FOR 20 TOKENS/MIN."""
    for attempt in range(20):
        try:
            resp = await client.get(
                f"{KEEPA_API_BASE}/token", params={"key": api_key}, timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                tokens = data.get("tokens", 0)
                refill_in = data.get("refillIn", 0)

                if tokens >= min_tokens:
                    return True

                log.info(
                    f"⏳ Waiting for tokens... ({tokens} available, {refill_in}s until refill)"
                )
                await asyncio.sleep(min(refill_in + 2, 65))
            else:
                await asyncio.sleep(3)
        except Exception as e:
            log.warning(f"Token check failed: {e}")
            await asyncio.sleep(10)

    log.warning("Token wait timeout, continuing anyway...")
    return True


async def validate_batch(
    client: httpx.AsyncClient,
    api_key: str,
    asins: list[str],
    domain_id: int,
    domain_name: str,
) -> list[dict]:
    """Call Keepa /product for a batch of ASINs with rate-limit handling."""

    params = {
        "key": api_key,
        "domain": domain_id,
        "asin": ",".join(asins),
    }

    products = []

    for attempt in range(3):
        try:
            resp = await client.get(
                f"{KEEPA_API_BASE}/product", params=params, timeout=30.0
            )

            stats["requests"] += 1

            if resp.status_code == 429:
                stats["rate_limits"] += 1
                retry_after = int(resp.headers.get("Retry-After", 60))
                log.warning(
                    f"⚠️ Rate limited on {domain_name}, waiting {retry_after}s..."
                )
                await asyncio.sleep(retry_after + 5)
                continue

            if resp.status_code != 200:
                log.warning(f"  {domain_name}: HTTP {resp.status_code}")
                stats["errors"] += 1
                return []

            data = resp.json()
            tokens = data.get("tokensConsumed", 0)
            stats["tokens_used"] += tokens

            products = data.get("products", [])
            stats["success"] += 1
            break

        except Exception as e:
            log.warning(f"  {domain_name}: request failed: {e}")
            stats["errors"] += 1
            await asyncio.sleep(5)
            continue

    validated = []
    for p in products:
        asin = (p.get("asin") or "").strip().upper()
        title = (p.get("title") or "").strip()

        if len(asin) != 10 or not asin.startswith("B"):
            _bad_asins.add(asin)
            continue
        if not title:
            continue

        if not _has_keyboard_evidence(title):
            continue

        csv = p.get("csv") or []

        def price(idx):
            return _latest_price(csv[idx]) if len(csv) > idx else None

        amazon_p = price(0)
        new_p = price(1)
        used_p = price(2)
        whd_p = price(9)

        prices = [x for x in [amazon_p, new_p, used_p, whd_p] if x is not None]

        list_price = amazon_p or new_p or (max(prices) if prices else None)
        deal_price = whd_p or used_p
        discount = None
        if deal_price and list_price and list_price > 0:
            discount = round((1 - deal_price / list_price) * 100, 1)

        rating = p.get("rating")
        rating_val = rating / 10.0 if rating else None
        reviews = p.get("reviewCount") or 0

        validated.append(
            {
                "asin": asin,
                "title": title[:120],
                "domain": domain_name,
                "domain_id": domain_id,
                "amazon_price": amazon_p,
                "new_price": new_p,
                "used_price": used_p,
                "whd_price": whd_p,
                "list_price": list_price,
                "deal_price": deal_price,
                "discount_percent": discount,
                "rating": rating_val,
                "reviews": reviews,
                "validated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return validated


async def discover(
    api_key: str,
    max_per_domain: int = 20,
    batch_size: int = 10,
    min_discount: float = 0.0,
) -> dict[str, list[dict]]:
    """Main discovery loop with smart rate limiting."""

    results: dict[str, list[dict]] = {d: [] for d in DOMAINS}

    async with httpx.AsyncClient() as client:
        for domain_name, domain_id in DOMAINS.items():
            log.info(f"🔍 Validating {domain_name} (domain={domain_id})")

            await wait_for_tokens(client, api_key, min_tokens=10)

            found: list[dict] = []
            candidates = [a for a in CANDIDATE_POOL if a not in _bad_asins]

            for i in range(0, len(candidates), batch_size):
                if len(found) >= max_per_domain:
                    break

                batch = candidates[i : i + batch_size]
                log.info(f"  Batch {i // batch_size + 1}: {len(batch)} ASINs")

                validated = await validate_batch(
                    client, api_key, batch, domain_id, domain_name
                )

                if min_discount > 0:
                    validated = [
                        v
                        for v in validated
                        if (v.get("discount_percent") or 0) >= min_discount
                    ]

                found.extend(validated)
                log.info(f"  → {len(validated)} valid | total: {len(found)}")

                # PAUSE between batches: 20 tokens/min = ~3s per token
                # Batch of 10 ASINs = ~10 tokens = wait 30s+ between batches
                pause_seconds = max(35, batch_size * 3)
                if i + batch_size < len(candidates):
                    log.info(f"  ⏳ Rate limit: pausing {pause_seconds}s...")
                    await asyncio.sleep(pause_seconds)

            results[domain_name] = found[:max_per_domain]
            log.info(f"✅ {domain_name}: {len(results[domain_name])} validated ASINs")

    return results


def write_outputs(
    results: dict[str, list[dict]], output_dir: Path
) -> tuple[Path, Path]:
    """Write JSON metadata + TXT ASIN list."""
    output_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    all_meta: list[dict] = []
    for domain_entries in results.values():
        for entry in domain_entries:
            if entry["asin"] not in seen:
                seen.add(entry["asin"])
                all_meta.append(entry)

    json_path = output_dir / "seed_asins_eu_qwertz.json"
    txt_path = output_dir / "seed_asins_eu_qwertz.txt"

    payload = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "domains": list(DOMAINS.keys()),
            "total_asins": len(all_meta),
        },
        "by_domain": results,
        "all_asins": [e["asin"] for e in all_meta],
    }

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    txt_path.write_text(",".join(e["asin"] for e in all_meta))

    log.info(f"📄 JSON: {json_path}  ({len(all_meta)} ASINs)")
    log.info(f"📄 TXT:  {txt_path}")
    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(
        description="Discover EU keyboard ASINs via Keepa (v2)"
    )
    parser.add_argument("--max-per-domain", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--min-discount", type=float, default=0.0)
    parser.add_argument("--output-dir", type=str, default="data")
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

    log.info(f"🚀 Starting EU QWERTZ ASIN discovery (v2)")
    log.info(f"   Domains: {', '.join(DOMAINS.keys())}")
    log.info(f"   Candidates: {len(CANDIDATE_POOL)}")
    log.info(f"   Max per domain: {args.max_per_domain}")

    results = asyncio.run(
        discover(
            api_key=api_key,
            max_per_domain=args.max_per_domain,
            batch_size=args.batch_size,
            min_discount=args.min_discount,
        )
    )

    total = sum(len(v) for v in results.values())
    log.info(f"\n{'=' * 50}")
    log.info(f"Discovery complete: {total} total validated entries")
    log.info(f"Stats: {stats}")

    for domain, entries in results.items():
        log.info(f"  {domain}: {len(entries)} ASINs")

    output_dir = Path(__file__).parent.parent / args.output_dir
    json_path, txt_path = write_outputs(results, output_dir)

    log.info(f"\n✅ Done!")
    log.info(f"   Requests: {stats['requests']}, Tokens: {stats['tokens_used']}")
    log.info(f"   Rate limits hit: {stats['rate_limits']}")


if __name__ == "__main__":
    main()
