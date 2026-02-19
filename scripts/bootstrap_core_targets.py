#!/usr/bin/env python3
"""
Create a small core target file for immediate scanning.

The core set is built from DEAL_SEED_ASINS (or a fallback list) and expanded to
UK/FR/IT/ES domains.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DOMAINS: List[Tuple[str, int]] = [("UK", 2), ("FR", 4), ("IT", 8), ("ES", 9)]
FALLBACK_ASINS = ["B003ELVLKU", "B014EUQOGK", "B01E8KO2B0", "B01NABDNPH"]


def load_asins() -> List[str]:
    raw = os.environ.get("DEAL_SEED_ASINS", "").strip().strip('"').strip("'")

    if not raw:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("DEAL_SEED_ASINS="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not raw:
        return FALLBACK_ASINS[:]

    out = []
    seen = set()
    for token in raw.split(","):
        asin = token.strip().upper()
        if len(asin) == 10 and asin.startswith("B") and asin not in seen:
            seen.add(asin)
            out.append(asin)

    return out or FALLBACK_ASINS[:]


def write_core(output_path: Path, asins: List[str]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["asin", "domain_id", "market"])
        writer.writeheader()
        for market, domain_id in DOMAINS:
            for asin in asins:
                writer.writerow(
                    {
                        "asin": asin,
                        "domain_id": domain_id,
                        "market": market,
                    }
                )
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Create core seed target CSV")
    parser.add_argument("--output", default="data/seed_targets_core_qwertz.csv")
    args = parser.parse_args()

    out = (ROOT / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    asins = load_asins()
    rows = write_core(out, asins)

    print(f"Core seed created: {out}")
    print(f"ASINs: {len(asins)} | target rows: {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
