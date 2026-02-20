#!/usr/bin/env python3
"""
Amazon QWERTZ Keyboard Scraper - FAST VERSION
============================================
Schneller Scraper mit Playwright für ASIN-Sammlung.
"""

import asyncio
import csv
import json
import random
import time
from pathlib import Path
from datetime import datetime, timezone
from playwright.async_api import async_playwright

SEARCH_KEYWORDS = {
    "UK": ["QWERTZ keyboard", "german keyboard", "mechanical keyboard"],
    "FR": ["clavier qwertz", "clavier mecanique", "clavier layout allemand"],
    "IT": ["tastiera qwertz", "tastiera meccanica", "tastiera layout tedesco"],
    "ES": ["teclado qwertz", "teclado mecanico", "teclado alem"],
}

RESULTS = []


async def scrape_keyword(
    page, market: str, keyword: str, max_results: int = 25
) -> list[dict]:
    """Sucht ein Keyword und sammelt ASINs."""

    results = []

    # Baue URL
    search = keyword.replace(" ", "+")
    url = f"https://www.amazon.{'co.uk' if market == 'UK' else market.lower()}/s?k={search}&rh=n:560774&crid=1"

    print(f"  🔍 {market}/{keyword}...")

    try:
        await page.goto(url, timeout=20000)
        await asyncio.sleep(1.5)

        # Check for issues
        if "captcha" in page.url.lower():
            print(f"  ⚠️ CAPTCHA!")
            return results

        # Warte auf Produkte
        try:
            await page.wait_for_selector(".s-result-item", timeout=5000)
        except:
            print(f"  ⚠️ Keine Produkte gefunden")
            return results

        # Scrape Produkte
        products = await page.query_selector_all(".s-result-item[data-asin]")

        for product in products[:max_results]:
            try:
                asin = await product.get_attribute("data-asin")
                if not asin or len(asin) != 10:
                    continue

                # Title
                title_elem = await product.query_selector(
                    "h2 a span, .a-color-base a span"
                )
                title = await title_elem.inner_text() if title_elem else "N/A"
                title = title.strip()[:100] if title else "N/A"

                # Price
                price_elem = await product.query_selector(".a-price-whole")
                price = None
                if price_elem:
                    try:
                        price_text = await price_elem.inner_text()
                        price = float(
                            price_text.replace(",", ".")
                            .replace("€", "")
                            .replace("£", "")
                            .strip()
                        )
                    except:
                        pass

                results.append(
                    {
                        "asin": asin.upper(),
                        "title": title,
                        "price": price,
                        "market": market,
                        "keyword": keyword,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            except Exception as e:
                continue

        print(f"    → {len(results)} ASINs")

    except Exception as e:
        print(f"  ❌ Error: {e}")

    return results


async def scrape_market(market: str) -> list[dict]:
    """Scrapt einen kompletten Markt."""

    all_results = []
    seen = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Inject anti-detection
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        for keyword in SEARCH_KEYWORDS[market]:
            await asyncio.sleep(random.uniform(1, 2))

            results = await scrape_keyword(page, market, keyword, max_results=20)

            for r in results:
                if r["asin"] not in seen:
                    seen.add(r["asin"])
                    all_results.append(r)

        await browser.close()

    return all_results


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--market", "-m", default="all", help="UK, FR, IT, ES oder all")
    parser.add_argument("--output", "-o", default="data/amazon_asins_raw.csv")
    args = parser.parse_args()

    print(f"🚀 Amazon ASIN Scraper")
    print(f"   Market: {args.market}")

    all_results = []

    markets = (
        [args.market.upper()] if args.market != "all" else list(SEARCH_KEYWORDS.keys())
    )

    for market in markets:
        print(f"\n{'=' * 50}")
        print(f"🌍 SCRAPING {market}")
        results = await scrape_market(market)
        all_results.extend(results)
        print(f"   Total: {len(results)} ASINs")

    # Save
    output = Path(__file__).parent.parent / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["asin", "title", "price", "market", "keyword", "scraped_at"]
        )
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n✅ Saved {len(all_results)} ASINs to {output}")

    # JSON
    json_path = output.with_suffix(".json")
    with open(json_path, "w") as f:
        json.dump(
            {
                "_meta": {"total": len(all_results), "markets": markets},
                "asins": [r["asin"] for r in all_results],
            },
            f,
            indent=2,
        )

    print(f"✅ JSON saved to {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
