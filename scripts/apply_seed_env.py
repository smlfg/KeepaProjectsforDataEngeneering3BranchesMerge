#!/usr/bin/env python3
"""
apply_seed_env.py — Safely writes DEAL_SEED_ASINS into .env
Usage: python scripts/apply_seed_env.py [--txt data/seed_asins_eu_qwertz.txt]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--txt", default="data/seed_asins_eu_qwertz.txt")
    args = parser.parse_args()

    txt_path = ROOT / args.txt
    if not txt_path.exists():
        print(f"❌ Seed file not found: {txt_path}")
        print("   Run: python scripts/discover_eu_qwertz_asins.py first")
        sys.exit(1)

    asins = txt_path.read_text().strip()
    if not asins:
        print("❌ Seed file is empty")
        sys.exit(1)

    env_path = ROOT / ".env"
    if env_path.exists():
        lines = env_path.read_text().splitlines()
        new_lines = [l for l in lines if not l.startswith("DEAL_SEED_ASINS=")]
    else:
        new_lines = []

    new_lines.append(f'DEAL_SEED_ASINS="{asins}"')
    env_path.write_text("\n".join(new_lines) + "\n")

    count = len(asins.split(","))
    print(f"✅ Wrote {count} ASINs to .env as DEAL_SEED_ASINS")
    print(f"   Restart the scheduler to pick up the new seeds.")

if __name__ == "__main__":
    main()
