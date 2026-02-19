#!/usr/bin/env python3
"""
Validate domain-aware seed targets against Keepa /product endpoint.

Input:  CSV with at least columns: asin, domain_id, market
Output: CSV with validated rows including title/prices and validation flags
Resume: progress is checkpointed in JSON after each successful batch
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KEEPA_API_BASE = "https://api.keepa.com"

DOMAIN_NAMES = {
    1: "US",
    2: "UK",
    3: "DE",
    4: "FR",
    8: "IT",
    9: "ES",
}

KEYBOARD_KEYWORDS = [
    "keyboard",
    "tastatur",
    "clavier",
    "tastiera",
    "teclado",
    "mechanical",
    "gaming",
    "wireless",
]

QWERTZ_HINT_KEYWORDS = [
    "qwertz",
    "german",
    "deutsch",
    "de layout",
    "iso de",
    "deutsches layout",
]

OUTPUT_FIELDS = [
    "asin",
    "domain_id",
    "market",
    "title",
    "new_price",
    "used_price",
    "list_price",
    "discount_percent",
    "rating",
    "reviews",
    "is_qwertz_candidate",
    "price_present",
    "validated_at",
    "source",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_api_key() -> str:
    env_key = os.environ.get("KEEPA_API_KEY", "").strip().strip('"').strip("'")
    if env_key:
        return env_key

    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("KEEPA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return ""


def key_for(asin: str, domain_id: int) -> str:
    return f"{asin.upper()}:{domain_id}"


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except Exception:
        return None
    return v


def latest_price(csv_slot: Any) -> float | None:
    if not isinstance(csv_slot, list) or len(csv_slot) < 2:
        return None
    last = csv_slot[-1]
    if not isinstance(last, (int, float)) or last <= 0:
        return None
    return round(float(last) / 100.0, 2)


def get_price_from_csv(csv_data: Any, idx: int) -> float | None:
    if not isinstance(csv_data, list) or len(csv_data) <= idx:
        return None
    return latest_price(csv_data[idx])


def title_has_any(title: str, keywords: List[str]) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in keywords)


def load_targets(input_csv: Path) -> List[Dict[str, Any]]:
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    targets: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    with input_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            asin = str(row.get("asin", "")).strip().upper()
            if len(asin) != 10 or not asin.startswith("B"):
                continue

            try:
                domain_id = int(row.get("domain_id", 0) or 0)
            except Exception:
                continue
            if domain_id <= 0:
                continue

            market = str(row.get("market") or DOMAIN_NAMES.get(domain_id, "")).strip().upper()
            k = key_for(asin, domain_id)
            if k in seen:
                continue

            seen.add(k)
            targets.append(
                {
                    "asin": asin,
                    "domain_id": domain_id,
                    "market": market or DOMAIN_NAMES.get(domain_id, ""),
                }
            )

    return targets


def load_existing_validated(output_csv: Path) -> Set[str]:
    if not output_csv.exists():
        return set()

    keys: Set[str] = set()
    with output_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            asin = str(row.get("asin", "")).strip().upper()
            if len(asin) != 10:
                continue
            try:
                domain_id = int(row.get("domain_id", 0) or 0)
            except Exception:
                continue
            if domain_id <= 0:
                continue
            keys.add(key_for(asin, domain_id))

    return keys


def load_progress(progress_path: Path) -> Dict[str, Any]:
    if not progress_path.exists():
        return {
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "processed_keys": [],
            "stats": {
                "batches": 0,
                "requests": 0,
                "rate_limits": 0,
                "errors": 0,
                "validated_rows": 0,
                "tokens_consumed": 0,
            },
        }

    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "processed_keys": [],
            "stats": {
                "batches": 0,
                "requests": 0,
                "rate_limits": 0,
                "errors": 0,
                "validated_rows": 0,
                "tokens_consumed": 0,
            },
        }

    data.setdefault("processed_keys", [])
    data.setdefault("stats", {})
    for k in ("batches", "requests", "rate_limits", "errors", "validated_rows", "tokens_consumed"):
        data["stats"].setdefault(k, 0)
    data.setdefault("started_at", now_iso())
    data.setdefault("updated_at", now_iso())
    return data


def save_progress(progress_path: Path, progress: Dict[str, Any]) -> None:
    progress["updated_at"] = now_iso()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def append_validated_rows(output_csv: Path, rows: List[Dict[str, Any]]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    exists = output_csv.exists()
    with output_csv.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


async def wait_for_tokens(client: httpx.AsyncClient, api_key: str, min_tokens: int) -> Dict[str, Any]:
    for _ in range(60):
        try:
            resp = await client.get(
                f"{KEEPA_API_BASE}/token",
                params={"key": api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                tokens_left = int(data.get("tokensLeft", data.get("tokens", 0)) or 0)
                refill_in = int(data.get("refillIn", 60) or 60)
                if tokens_left >= min_tokens:
                    return {"tokens_left": tokens_left, "refill_in": refill_in}
                await asyncio.sleep(max(5, min(refill_in + 2, 90)))
            else:
                await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(10)

    return {"tokens_left": 0, "refill_in": 60}


async def fetch_product_batch(
    client: httpx.AsyncClient,
    api_key: str,
    domain_id: int,
    asins: List[str],
    retry_limit: int = 4,
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    stats = {"requests": 0, "tokens_consumed": 0, "rate_limits": 0, "errors": 0}

    for _ in range(retry_limit):
        try:
            resp = await client.get(
                f"{KEEPA_API_BASE}/product",
                params={
                    "key": api_key,
                    "domain": domain_id,
                    "asin": ",".join(asins),
                },
                timeout=45,
            )
            stats["requests"] += 1

            if resp.status_code == 429:
                stats["rate_limits"] += 1
                retry_after = int(resp.headers.get("Retry-After", 60) or 60)
                await asyncio.sleep(max(10, retry_after + 2))
                continue

            if resp.status_code != 200:
                stats["errors"] += 1
                return {}, stats

            data = resp.json()
            stats["tokens_consumed"] += int(data.get("tokensConsumed", 0) or 0)
            return data, stats
        except Exception:
            stats["errors"] += 1
            await asyncio.sleep(5)

    return {}, stats


def validate_products(
    payload: Dict[str, Any],
    domain_id: int,
    market: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    products = payload.get("products") or []

    for p in products:
        asin = str(p.get("asin") or "").strip().upper()
        if len(asin) != 10 or not asin.startswith("B"):
            continue

        title = str(p.get("title") or "").strip()
        if not title:
            continue

        if not title_has_any(title, KEYBOARD_KEYWORDS):
            continue

        csv_data = p.get("csv") or []
        list_price = get_price_from_csv(csv_data, 0) or get_price_from_csv(csv_data, 1)
        new_price = get_price_from_csv(csv_data, 1)
        used_price = get_price_from_csv(csv_data, 2) or get_price_from_csv(csv_data, 9)
        price_present = any(x is not None for x in (list_price, new_price, used_price))
        if not price_present:
            continue

        discount_percent = None
        if used_price is not None and list_price is not None and list_price > 0:
            discount_percent = round((1 - used_price / list_price) * 100.0, 1)

        rating = parse_float(p.get("rating"))
        rating_out = round(rating / 10.0, 2) if rating else None

        row = {
            "asin": asin,
            "domain_id": domain_id,
            "market": market or DOMAIN_NAMES.get(domain_id, ""),
            "title": title[:180],
            "new_price": new_price if new_price is not None else "",
            "used_price": used_price if used_price is not None else "",
            "list_price": list_price if list_price is not None else "",
            "discount_percent": discount_percent if discount_percent is not None else "",
            "rating": rating_out if rating_out is not None else "",
            "reviews": p.get("reviewCount") or "",
            "is_qwertz_candidate": "true" if title_has_any(title, QWERTZ_HINT_KEYWORDS) else "false",
            "price_present": "true",
            "validated_at": now_iso(),
            "source": "keepa_product_validation",
        }
        rows.append(row)

    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate seed targets via Keepa /product")
    p.add_argument("--input", default="data/seed_targets_raw_pool.csv")
    p.add_argument("--output", default="data/seed_targets_validated_qwertz.csv")
    p.add_argument("--progress", default="data/seed_validation_progress.json")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--max-batches", type=int, default=0, help="0 = no limit")
    p.add_argument("--min-tokens", type=int, default=12)
    p.add_argument("--sleep-between", type=float, default=1.5)
    return p.parse_args()


async def run_validation(args: argparse.Namespace) -> int:
    api_key = load_api_key()
    if not api_key:
        print("ERROR: missing KEEPA_API_KEY")
        return 2

    input_csv = (ROOT / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input)
    output_csv = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    progress_path = (ROOT / args.progress).resolve() if not Path(args.progress).is_absolute() else Path(args.progress)

    targets = load_targets(input_csv)
    if not targets:
        print("ERROR: no valid targets in input CSV")
        return 1

    progress = load_progress(progress_path)
    processed: Set[str] = set(str(x) for x in progress.get("processed_keys", []))
    processed |= load_existing_validated(output_csv)

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for t in targets:
        k = key_for(t["asin"], t["domain_id"])
        if k in processed:
            continue
        grouped.setdefault(t["domain_id"], []).append(t)

    total_remaining = sum(len(v) for v in grouped.values())
    print(
        f"Validation start: total_targets={len(targets)} processed={len(processed)} remaining={total_remaining}"
    )

    batch_counter = 0
    async with httpx.AsyncClient() as client:
        for domain_id, rows in grouped.items():
            market = rows[0].get("market") or DOMAIN_NAMES.get(domain_id, "")
            asins = [r["asin"] for r in rows]

            for i in range(0, len(asins), max(1, int(args.batch_size))):
                if args.max_batches > 0 and batch_counter >= args.max_batches:
                    progress["processed_keys"] = sorted(processed)
                    save_progress(progress_path, progress)
                    print("Reached --max-batches limit, checkpoint saved.")
                    return 0

                batch = asins[i : i + max(1, int(args.batch_size))]
                status = await wait_for_tokens(client, api_key, max(1, int(args.min_tokens)))
                print(
                    f"domain={domain_id}/{market} batch={batch_counter + 1} size={len(batch)} tokens_left={status.get('tokens_left', '?')}"
                )

                payload, stats = await fetch_product_batch(client, api_key, domain_id, batch)
                progress_stats = progress["stats"]
                progress_stats["batches"] += 1
                progress_stats["requests"] += stats["requests"]
                progress_stats["rate_limits"] += stats["rate_limits"]
                progress_stats["errors"] += stats["errors"]
                progress_stats["tokens_consumed"] += stats["tokens_consumed"]

                if payload:
                    validated_rows = validate_products(payload, domain_id, market)
                    if validated_rows:
                        append_validated_rows(output_csv, validated_rows)
                        progress_stats["validated_rows"] += len(validated_rows)
                        print(f"  validated_rows+={len(validated_rows)}")

                    for asin in batch:
                        processed.add(key_for(asin, domain_id))

                    progress["processed_keys"] = sorted(processed)
                    save_progress(progress_path, progress)
                else:
                    print("  batch failed (kept for future retry)")

                batch_counter += 1
                await asyncio.sleep(max(0.0, float(args.sleep_between)))

    progress["processed_keys"] = sorted(processed)
    save_progress(progress_path, progress)
    print(
        "Validation complete: processed={} validated_rows={} tokens_consumed={} errors={} rate_limits={}".format(
            len(processed),
            progress["stats"]["validated_rows"],
            progress["stats"]["tokens_consumed"],
            progress["stats"]["errors"],
            progress["stats"]["rate_limits"],
        )
    )
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(run_validation(args))


if __name__ == "__main__":
    raise SystemExit(main())
