#!/usr/bin/env python3
"""
Test script for Keepa API connection and Deal Scoring
"""

import asyncio
import sys
from pathlib import Path
import pytest
from decimal import Decimal

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.services.keepa_client import get_keepa_client
from src.services.deal_scoring import get_deal_scoring_service


@pytest.mark.asyncio
async def test_keepa_api():
    """Test Keepa API connection"""
    print("=" * 60)
    print("TEST: Keepa API Connection")
    print("=" * 60)

    client = get_keepa_client()
    print(f"API Key Hash: {client.api_key_hash}")
    print(f"Initial Rate Limit: {client.rate_limit_remaining}")

    # Test getting specific products
    print("\nFetching product details...")
    asins = ["B08NT5V3FZ", "B07Y8S8R6G", "B09V3KXJPB"]  # Example ASINs
    product_result = await client.get_products(asins=asins, domain_id=3)

    print(f"Products found: {product_result['metadata']['products_found']}")
    print(f"Tokens consumed: {product_result['metadata']['tokens_consumed']}")

    # Parse products
    products = client.parse_products(product_result["raw"])
    for p in products:
        title = (p.get("title") or "Unknown Product")[:60]
        print(f"  - {title}...")
        print(
            f"    Price: €{p.get('current_price')} | Rating: {p.get('rating')} | Rank: {p.get('sales_rank')}"
        )

    return product_result


def test_deal_scoring():
    """Test deal scoring service"""
    print("\n" + "=" * 60)
    print("TEST: Deal Scoring")
    print("=" * 60)

    scoring_service = get_deal_scoring_service()

    # Test cases
    test_deals = [
        {
            "asin": "B0088PUEPK",
            "title": "Sony WH-1000XM5 Wireless Headphones",
            "current_price": Decimal("289.99"),
            "original_price": Decimal("349.99"),
            "discount_percent": 17,
            "rating": Decimal("4.7"),
            "review_count": 1523,
            "sales_rank": 15234,
            "is_amazon_seller": True,
            "seller_name": "Amazon",
        },
        {
            "asin": "B0000000001",
            "title": "Suspicious Product",
            "current_price": Decimal("9.99"),
            "original_price": Decimal("99.99"),
            "discount_percent": 90,
            "rating": Decimal("5.0"),
            "review_count": 1,  # Suspicious!
            "sales_rank": 500000,
            "is_amazon_seller": False,
            "seller_name": "Imported Wholesale",
        },
        {
            "asin": "B0000000002",
            "title": "Regular Product",
            "current_price": Decimal("49.99"),
            "original_price": Decimal("79.99"),
            "discount_percent": 37,
            "rating": Decimal("4.2"),
            "review_count": 45,
            "sales_rank": 25000,
            "is_amazon_seller": False,
            "seller_name": "RegularStore",
        },
    ]

    ranked_deals = scoring_service.rank_deals(test_deals)

    for i, deal in enumerate(ranked_deals, 1):
        print(f"\n#{i}: {deal['title']}")
        print(f"   ASIN: {deal['asin']}")
        print(f"   Price: €{deal['current_price']} ({deal['discount_percent']}% off)")
        print(f"   Rating: {deal['rating']} ({deal['review_count']} reviews)")
        print(f"   Sales Rank: #{deal['sales_rank']}")
        print(f"   Deal Score: {deal.get('deal_score', 'N/A')}")
        print(f"   Score Breakdown: {deal.get('score_breakdown', 'N/A')}")

    return ranked_deals


async def main():
    """Run all tests"""
    print("\n🚀 DealFinder Integration Tests\n")

    try:
        # Test Keepa API
        keepa_result = await test_keepa_api()

        # Test Deal Scoring
        scored_deals = test_deal_scoring()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print(f"\n📊 Summary:")
        print(f"   - Keepa API: Working")
        print(f"   - Products found: {len(keepa_result['raw'].get('products', []))}")
        print(f"   - Scoring: {len(scored_deals)} deals scored")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
