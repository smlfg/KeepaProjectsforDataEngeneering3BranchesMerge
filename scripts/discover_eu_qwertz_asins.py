#!/usr/bin/env python3
"""
EU QWERTZ/EU Keyboard ASIN Discovery Script
============================================
Discovers and validates keyboard ASINs in EU markets (UK, FR, IT, ES)
using the Keepa /product endpoint (since /search is not available on basic plans).

Usage:
    python scripts/discover_eu_qwertz_asins.py
    python scripts/discover_eu_qwertz_asins.py --max-per-domain 30 --min-discount 5

Outputs:
    data/seed_asins_eu_qwertz.json  - Full metadata per validated ASIN
    data/seed_asins_eu_qwertz.txt   - Comma-separated ASIN list for env usage
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

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("discover")

# ── Domain config ─────────────────────────────────────────────────────────────
DOMAINS = {
    "UK": 2,   # amazon.co.uk
    "FR": 4,   # amazon.fr
    "IT": 8,   # amazon.it
    "ES": 9,   # amazon.es
}

KEEPA_API_BASE = "https://api.keepa.com"

# ── Layout/keyboard evidence keywords (title matching) ────────────────────────
KEYBOARD_EVIDENCE = [
    "keyboard", "tastatur", "clavier", "tastiera", "teclado",
    "qwertz", "azerty", "mechanical", "mécanique",
    "klawiatura", "toetsenbord", "wireless keyboard", "gaming keyboard",
    "mx keys", "k380", "k120", "g915", "g815", "g413",
    "cherry mx", "cherry kc", "razer huntsman", "razer blackwidow",
    "corsair k70", "corsair k55", "steelseries apex",
    "keychron", "ducky", "anne pro", "royal kludge",
    "logitech k", "microsoft sculpt", "microsoft surface keyboard",
]

# ── Bad-ASIN quarantine (in-memory) ──────────────────────────────────────────
_bad_asins: set[str] = set()

# ── Large static candidate pool ───────────────────────────────────────────────
# Mix of EU-listed keyboards from popular brands.
# These are verified against live Keepa responses during validation.
CANDIDATE_POOL = [
    # ── Logitech ──────────────────────────────────────────────────────────────
    "B07WGFC44F", "B01N4FXKH5", "B003ELVLKU", "B07QKD9V4F", "B07FWHKJXH",
    "B08CVY5G6Q", "B08CRDDXDC", "B08DTGCKKX", "B0B3QDNV44", "B09QX3PLWB",
    "B09F3Z8P3B", "B07CMQF9C7", "B09MTYZBXF", "B0B7NQHTSB", "B09TPJQ8GV",
    "B07C7DTGMF", "B07R7FFVG4", "B0BG9XFMC4", "B0BKRGMKM1", "B09ZVB8VKQ",
    "B07KQL9C1H", "B07YN2F4ZF", "B08R1MHS9C", "B09Y7J1ZLQ", "B09MLKZP8K",
    "B09MTYXNWK", "B0BHM5VP6C", "B0CKWQXMQJ", "B0BRDCT46B", "B0BRDBT7PR",
    "B0BRDDK8TW", "B0BRD9XTXR", "B09CGHTB5N", "B0B4Y2MYVJ", "B07Y5VFXZL",
    "B08H97NYGJ", "B09B9KCP8Y", "B08R3LH8BF", "B0C1XZV9YF", "B0BWZQJ5KW",
    # ── Cherry (EU-stronghold brand) ──────────────────────────────────────────
    "B009EOZ41Y", "B00VBGT00Q", "B007VDPID6", "B014EUQOGK", "B00ZK4RK3K",
    "B082TN5P76", "B08STKPTJ8", "B09K4ZYWKZ", "B0B9ZK5M5W",
    "B00FVKLR42", "B079PRXQPL", "B0187CKZVE", "B00XBGG62Y", "B06XKNR8LJ",
    "B07PMBHH1D", "B07PM9HWK1", "B0794WQSPS", "B07PM8T4Y1", "B00VBGT0J6",
    "B0814FXW5G", "B07DHNX4XB", "B00MBLQGGE", "B09B96KFQX", "B07BHV6SHW",
    "B07PM9HWDT", "B07PMB5N38", "B09BSLJKFH", "B09BS7JLTT", "B0C4FHFVMT",
    # ── Microsoft ─────────────────────────────────────────────────────────────
    "B07H4Z4JQG", "B00450LDR4", "B077XCXZKK", "B09ZD1J9ZQ", "B0BQHRSQG5",
    "B09H2KQTWF", "B0795DW9MT", "B01NABDNPH", "B01MZYSL9C", "B019YH3KOQ",
    "B07YGBMHCK", "B08HQ3VZ77", "B07YH9BMKW", "B08GYWKLZN", "B0BWMQPL88",
    "B0C9G5SM3H", "B0BG56B64Q", "B0B53BMVQR", "B09ZTHKFN3", "B07YGBVF81",
    # ── Corsair ───────────────────────────────────────────────────────────────
    "B07S92G6DL", "B07VLBPZMV", "B0BFB6YRRX", "B09GH5YPLT", "B08FWF2LRZ",
    "B07GGTZQX2", "B07K6MMPFK", "B07RFSVGDN", "B09Q2M2WGH", "B08FK7YPBB",
    "B09R7CXJJ5", "B09T3WMVT5", "B0BVPNWB5T", "B0BWRB9LFG", "B0BG7TW9HC",
    "B0BG7Q4VZ6", "B0BG7Q7VBL", "B0C3CXBGDK", "B0C3CX7NSV", "B0C17K93XZ",
    # ── Razer ─────────────────────────────────────────────────────────────────
    "B07T5XVYQL", "B0821CRNDX", "B09JD4ND26", "B07YM2DLBP", "B09NYNKPBK",
    "B08BF4NGWN", "B083BXTV5N", "B07S5G9VTF", "B09K3T6YN6", "B0948RZPRD",
    "B08P281G8Z", "B09BYJJT5X", "B09BYK2GGZ", "B09NYLKPBK", "B0BKPWJ82K",
    "B0BT7GLTL2", "B0BT7NHGPN", "B0BWGF2YCH", "B09F3Z8P3B", "B0C63VHVLP",
    # ── SteelSeries ───────────────────────────────────────────────────────────
    "B09M1PQ8RN", "B09GR7HS6D", "B08X4FJF1N", "B08PC2ZQMM", "B07FXTJN7Y",
    "B09B96KFQX", "B09VSWSRWK", "B0BCKPWXPT", "B09S9NKNG1",
    "B09VT7MB3P", "B09M2Q9SBJ", "B0BM3B84FZ", "B0BM3BDL1M", "B09YW5PBVB",
    "B0BQLLFG2W", "B0BM3BFZ8B", "B0C13VDDBQ", "B0C13YM2SR", "B0C9G3FMWK",
    # ── Keychron ──────────────────────────────────────────────────────────────
    "B08JQ5GTRN", "B08WZJQSQ3", "B09CGBBVMK", "B0BGGWYJXT", "B09JGGBMDR",
    "B0BJZT3JF8", "B09JGB7NLC", "B0BM7N7TDN", "B0B4YDTMJJ",
    "B0C93VJX4Q", "B0BJ1MV3XN", "B0C93VHX6S", "B0BZ2LZ2LB", "B0BZ2L2TLL",
    "B0C4VVKZMJ", "B0C4VX2NJS", "B0C7G2Y4MF", "B0BN5M4D5F", "B0BN5NSQNF",
    # ── Ducky ─────────────────────────────────────────────────────────────────
    "B08VK6D4YH", "B08G4ZJLHW", "B09VFKLG2N", "B09K65D68K",
    "B08VK6RPWJ", "B07VZ3XKPJ", "B09DFQN5D3", "B0B75PKX2G", "B09NYPFKPX",
    "B09NYNHPVT", "B0BKRGMKM1", "B09T3WMVT5", "B0BM7N7TDN", "B0B3QDNV44",
    # ── HyperX ────────────────────────────────────────────────────────────────
    "B09T3WMVT5", "B08VK6D4YH", "B09VSWSRWK", "B09K4ZYWKZ", "B09B96KFQX",
    "B07FZ5GPH3", "B08P39WJV2", "B09QNLXNVQ", "B0BCKPWXPT", "B09GR7HS6D",
    "B09YW5PBVB", "B0BM3B84FZ", "B0913WWVPH", "B08JJDZ7R2", "B0BKRHHVTL",
    # ── ASUS / ROG ────────────────────────────────────────────────────────────
    "B083GTF9BR", "B0B3QDKN4D", "B09NQ5WX6X", "B0948RY6XV", "B09CGPGQBR",
    "B09P2PNQJP", "B09P2MVMBZ", "B09VT7MB3P", "B0BQXL4ZLY", "B09YYH4WMP",
    "B0BKRJ4GQS", "B0BM3BGMP9", "B0BVLV2GZF", "B0C9G3FMWK", "B0C3CX7NSV",
    # ── Perixx / Rapoo / Budget EU keyboards ──────────────────────────────────
    "B00MBLQGGE", "B07ZTFHQFP", "B08H97NYGJ", "B07W7VFJTS", "B07WRQKQLX",
    "B08R1MHS9C", "B08HWPMQ2X", "B07CWJFNWW", "B07WGFC44F", "B07YGBMHCK",
    "B08GYWKLZN", "B097NZD9T1", "B09B3W2P7T", "B08HZRR6MN", "B08HZQ7R2S",
    # ── Qisan / Magicforce / Budget Mechanical ────────────────────────────────
    "B01E8KO2B0", "B07YN2F4ZF", "B07KQL9C1H", "B01MZYSL9C", "B07FZ5GPH3",
    "B08P39WJV2", "B097NZD9T1", "B09B3W2P7T", "B09QX3PLWB", "B09F3Z8P3B",
    # ── Apple (Renewed units common in EU) ────────────────────────────────────
    "B01NABDNPH", "B019YH3KOQ", "B08GYWKLZN", "B0795DW9MT", "B07YGBVF81",
    "B09ZTHKFN3", "B09ZTHKFN3", "B0C9G5SM3H", "B0BG56B64Q", "B0B53BMVQR",
    # ── Trust / Hama / Hori (EU budget/gaming brands) ─────────────────────────
    "B07W7VFJTS", "B07WRQKQLX", "B08HWPMQ2X", "B07CWJFNWW", "B08HZRR6MN",
    "B08HZQ7R2S", "B097NZD9T1", "B09B3W2P7T", "B08H97NYGJ", "B07YN2F4ZF",
]
# deduplicate
CANDIDATE_POOL = list(dict.fromkeys(CANDIDATE_POOL))


def _latest_price(csv_slot) -> float | None:
    """Return latest price from a Keepa CSV slot (divide by 100, skip -1)."""
    if not csv_slot or len(csv_slot) < 2:
        return None
    val = csv_slot[-1]
    return val / 100.0 if val != -1 else None


def _has_keyboard_evidence(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in KEYBOARD_EVIDENCE)


async def validate_batch(
    client: httpx.AsyncClient,
    api_key: str,
    asins: list[str],
    domain_id: int,
    domain_name: str,
    error_stats: dict,
) -> list[dict]:
    """
    Call Keepa /product for a batch of ASINs and return validated deal candidates.
    Returns list of metadata dicts for valid keyboard products.
    error_stats dict is updated in-place with http_errors/timeouts/connection_errors/json_errors.
    """
    params = {
        "key": api_key,
        "domain": domain_id,
        "asin": ",".join(asins),
    }
    try:
        resp = await client.get(f"{KEEPA_API_BASE}/product", params=params, timeout=30.0)
        if resp.status_code != 200:
            log.warning(f"  {domain_name}: /product HTTP {resp.status_code}")
            error_stats["http_errors"] += 1
            return []

        try:
            data = resp.json()
        except Exception:
            error_stats["json_errors"] += 1
            log.warning(f"  {domain_name}: JSON decode error")
            return []

        tokens = data.get("tokensConsumed", 0)
        products = data.get("products", [])
        log.debug(f"  {domain_name}: {len(products)} products, {tokens} tokens")

    except httpx.TimeoutException as e:
        error_stats["timeouts"] += 1
        log.warning(f"  {domain_name}: request timeout: {e}")
        return []
    except httpx.ConnectError as e:
        error_stats["connection_errors"] += 1
        log.warning(f"  {domain_name}: connection error: {e}")
        return []
    except Exception as e:
        error_stats["connection_errors"] += 1
        log.warning(f"  {domain_name}: request failed: {type(e).__name__}: {e}")
        return []

    validated = []
    for p in products:
        asin = (p.get("asin") or "").strip().upper()
        title = (p.get("title") or "").strip()

        # Basic validity checks
        if len(asin) != 10 or not asin.startswith("B"):
            _bad_asins.add(asin)
            continue
        if not title:
            continue  # no title = not available in this domain

        # Must have keyboard evidence in title
        if not _has_keyboard_evidence(title):
            continue

        csv = p.get("csv") or []

        def price(idx):
            return _latest_price(csv[idx]) if len(csv) > idx else None

        amazon_p = price(0)
        new_p    = price(1)
        used_p   = price(2)
        whd_p    = price(9)

        # Collect available prices (may be empty if all currently -1)
        prices = [x for x in [amazon_p, new_p, used_p, whd_p] if x is not None]

        list_price  = amazon_p or new_p or (max(prices) if prices else None)
        deal_price  = whd_p or used_p
        discount    = None
        if deal_price and list_price and list_price > 0:
            discount = round((1 - deal_price / list_price) * 100, 1)

        rating = p.get("rating")
        rating_val = rating / 10.0 if rating else None
        reviews = p.get("reviewCount") or 0

        validated.append({
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
        })

    return validated


async def discover(
    api_key: str,
    max_per_domain: int = 50,
    batch_size: int = 50,
    min_discount: float = 0.0,
) -> dict[str, list[dict]]:
    """
    Main discovery loop. Returns {domain_name: [validated_asin_meta, ...]}.
    """
    results: dict[str, list[dict]] = {d: [] for d in DOMAINS}
    error_stats = {"http_errors": 0, "timeouts": 0, "connection_errors": 0, "json_errors": 0}

    async with httpx.AsyncClient() as client:
        for domain_name, domain_id in DOMAINS.items():
            log.info(f"🔍 Validating {domain_name} (domain={domain_id})")
            found: list[dict] = []
            candidates = [a for a in CANDIDATE_POOL if a not in _bad_asins]

            for i in range(0, len(candidates), batch_size):
                if len(found) >= max_per_domain:
                    break
                batch = candidates[i : i + batch_size]
                log.info(f"  Batch {i//batch_size + 1}: {len(batch)} ASINs")
                validated = await validate_batch(client, api_key, batch, domain_id, domain_name, error_stats)

                if min_discount > 0:
                    validated = [v for v in validated if (v.get("discount_percent") or 0) >= min_discount]

                found.extend(validated)
                log.info(f"  → {len(validated)} valid this batch | total so far: {len(found)}")

                # Token-friendly pause between batches
                if i + batch_size < len(candidates):
                    await asyncio.sleep(1.0)

            results[domain_name] = found[:max_per_domain]
            log.info(f"✅ {domain_name}: {len(results[domain_name])} validated ASINs")

    total_errors = sum(error_stats.values())
    if total_errors:
        log.warning(
            f"⚠️  Error summary: http={error_stats['http_errors']} "
            f"timeout={error_stats['timeouts']} "
            f"connection={error_stats['connection_errors']} "
            f"json={error_stats['json_errors']}"
        )
    return results


def write_outputs(results: dict[str, list[dict]], output_dir: Path) -> tuple[Path, Path]:
    """Write JSON metadata + TXT ASIN list to data/ directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all unique ASINs (deduplicated)
    seen: set[str] = set()
    all_meta: list[dict] = []
    for domain_entries in results.values():
        for entry in domain_entries:
            if entry["asin"] not in seen:
                seen.add(entry["asin"])
                all_meta.append(entry)

    json_path = output_dir / "seed_asins_eu_qwertz.json"
    txt_path  = output_dir / "seed_asins_eu_qwertz.txt"

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

    # CSV with domain-aware targets (one row per asin+domain combination)
    import csv as _csv_mod
    csv_path = output_dir / "seed_targets_eu_qwertz.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = _csv_mod.DictWriter(
            f,
            fieldnames=["asin", "domain_id", "market", "title", "new_price", "used_price", "discount_percent"],
        )
        writer.writeheader()
        for domain_name, entries in results.items():
            for entry in entries:
                writer.writerow({
                    "asin": entry["asin"],
                    "domain_id": entry["domain_id"],
                    "market": entry["domain"],
                    "title": (entry.get("title") or "")[:80],
                    "new_price": entry.get("new_price") or "",
                    "used_price": entry.get("used_price") or "",
                    "discount_percent": entry.get("discount_percent") or "",
                })

    log.info(f"📄 JSON: {json_path}  ({len(all_meta)} ASINs)")
    log.info(f"📄 TXT:  {txt_path}")
    log.info(f"📄 CSV: {csv_path}  (domain-aware targets)")
    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(description="Discover EU keyboard ASINs via Keepa")
    parser.add_argument("--max-per-domain", type=int, default=50,
                        help="Max validated ASINs per domain (default: 50)")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="ASINs per Keepa /product call (default: 50)")
    parser.add_argument("--min-discount", type=float, default=0.0,
                        help="Only keep ASINs with this %% discount or more (default: 0)")
    parser.add_argument("--output-dir", type=str, default="data",
                        help="Output directory (default: data/)")
    args = parser.parse_args()

    api_key = os.environ.get("KEEPA_API_KEY", "")
    if not api_key:
        # Try to load from .env file
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("KEEPA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        log.error("KEEPA_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    # Preflight: verify connectivity + API key before discovery
    log.info("🔍 Preflight: checking Keepa API connectivity...")
    try:
        import httpx as _httpx_pre
        r = _httpx_pre.get(f"https://api.keepa.com/token?key={api_key}", timeout=10)
        if r.status_code == 200:
            d = r.json()
            log.info(
                f"✅ Keepa API OK — tokens_left={d.get('tokensLeft','?')} "
                f"refill_in={d.get('refillIn','?')}s"
            )
        else:
            log.error(f"❌ Keepa /token returned HTTP {r.status_code} — check API key or plan")
            sys.exit(1)
    except Exception as e:
        log.error(f"❌ Keepa connectivity failed: {type(e).__name__}: {e}")
        sys.exit(1)

    log.info(f"🚀 Starting EU QWERTZ ASIN discovery")
    log.info(f"   Domains: {', '.join(DOMAINS.keys())}")
    log.info(f"   Candidates in pool: {len(CANDIDATE_POOL)}")
    log.info(f"   Max per domain: {args.max_per_domain}")
    log.info(f"   Batch size: {args.batch_size}")

    results = asyncio.run(discover(
        api_key=api_key,
        max_per_domain=args.max_per_domain,
        batch_size=args.batch_size,
        min_discount=args.min_discount,
    ))

    total = sum(len(v) for v in results.values())
    log.info(f"\n{'='*50}")
    log.info(f"Discovery complete: {total} total validated entries")
    for domain, entries in results.items():
        log.info(f"  {domain}: {len(entries)} ASINs")

    output_dir = Path(__file__).parent.parent / args.output_dir
    json_path, txt_path = write_outputs(results, output_dir)

    log.info(f"\n✅ Done! To use these seeds:")
    log.info(f"   export DEAL_SEED_ASINS=$(cat {txt_path})")
    log.info(f"   or: python scripts/apply_seed_env.py")


if __name__ == "__main__":
    main()
