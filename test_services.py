#!/usr/bin/env python3
"""
Test script for Report Generator and Email Sender services
"""

import asyncio
import sys
from pathlib import Path
import pytest
from decimal import Decimal
from uuid import uuid4

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.services.report_generator import get_report_generator
from src.services.email_sender import get_email_sender


def test_report_generator():
    """Test HTML report generation"""
    print("=" * 60)
    print("🧪 TEST: Report Generator")
    print("=" * 60)

    generator = get_report_generator()

    # Sample deals for testing
    deals = [
        {
            "asin": "B08NT5V3FZ",
            "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones",
            "current_price": Decimal("289.99"),
            "original_price": Decimal("349.99"),
            "discount_percent": 17,
            "rating": Decimal("4.7"),
            "review_count": 1523,
            "sales_rank": 15234,
            "deal_score": 78.5,
            "amazon_url": "https://amazon.de/dp/B08NT5V3FZ",
        },
        {
            "asin": "B09V3KXJPB",
            "title": "Apple 2022 iPad Air (10.9-inch, Wi-Fi, 64GB) - Pink",
            "current_price": Decimal("549.00"),
            "original_price": Decimal("679.00"),
            "discount_percent": 19,
            "rating": Decimal("4.8"),
            "review_count": 892,
            "sales_rank": 8923,
            "deal_score": 85.2,
            "amazon_url": "https://amazon.de/dp/B09V3KXJPB",
        },
        {
            "asin": "B0C4V8V7LG",
            "title": "AirPods Pro 2nd Generation with USB-C",
            "current_price": Decimal("229.00"),
            "original_price": Decimal("279.00"),
            "discount_percent": 18,
            "rating": Decimal("4.6"),
            "review_count": 2100,
            "sales_rank": 1245,
            "deal_score": 82.1,
            "amazon_url": "https://amazon.de/dp/B0C4V8V7LG",
        },
    ]

    filter_config = {
        "name": "Electronics Deals",
        "categories": ["16142011"],
        "price_range": {"min": 50, "max": 1000, "currency": "EUR"},
        "discount_range": {"min": 15, "max": 70},
    }

    result = generator.generate_report(
        deals=deals,
        filter_name="Electronics Schnäppchen",
        filter_config=filter_config,
        locale="de",
    )

    print(f"\n✅ Report generated successfully!")
    print(f"   Deals included: {result['deal_count']}")
    print(f"   HTML length: {len(result['html'])} chars")
    print(f"   Text length: {len(result['text'])} chars")
    print(f"   Generated at: {result['generated_at']}")

    # Verify HTML structure
    assert "<html" in result["html"].lower()
    assert "</html>" in result["html"].lower()
    assert "Sony WH-1000XM5" in result["html"]
    assert "€" in result["html"]
    assert "deal-score" in result["html"].lower() or "Deal-Score" in result["html"]

    print(f"\n📧 HTML Preview (first 500 chars):")
    print("-" * 60)
    print(result["html"][:500])
    print("-" * 60)

    return result


@pytest.mark.asyncio
async def test_email_sender():
    """Test email sending (mock)"""
    print("\n" + "=" * 60)
    print("🧪 TEST: Email Sender")
    print("=" * 60)

    sender = get_email_sender()

    # Generate test report
    generator = get_report_generator()
    deals = [
        {
            "asin": "B08NT5V3FZ",
            "title": "Sony WH-1000XM5 Headphones",
            "current_price": Decimal("289.99"),
            "discount_percent": 17,
            "rating": Decimal("4.7"),
            "deal_score": 78.5,
            "amazon_url": "https://amazon.de/dp/B08NT5V3FZ",
        }
    ]

    filter_config = {
        "categories": ["Electronics"],
        "price_range": {"min": 50, "max": 1000},
        "discount_range": {"min": 15, "max": 70},
    }

    report = generator.generate_report(
        deals=deals, filter_name="Test Deals", filter_config=filter_config, locale="de"
    )

    # Send test email (async)
    result = await sender.send_report(
        to_email="test@example.com",
        subject="🔥 Test: Deine Electronics Deals - 16.01.2026",
        html_body=report["html"],
        text_body=report["text"],
        filter_name="Test Deals",
        report_id=str(uuid4()),
    )

    print(f"\n✅ Email send initiated!")
    print(f"   Sent: {result['sent']}")
    print(f"   Message ID: {result['message_id']}")
    print(f"   Provider: {result['provider']}")
    print(f"   Timestamp: {result['timestamp']}")

    # Verify result structure
    assert "sent" in result
    assert "message_id" in result
    assert "timestamp" in result

    return result


def test_bulk_sending():
    """Test bulk email sending"""
    print("\n" + "=" * 60)
    print("🧪 TEST: Bulk Email Sending")
    print("=" * 60)

    sender = get_email_sender()

    # Generate test report
    generator = get_report_generator()
    report = generator.generate_report(
        deals=[
            {
                "asin": "TEST",
                "title": "Test Deal",
                "current_price": Decimal("99.99"),
                "deal_score": 75,
            }
        ],
        filter_name="Bulk Test",
        filter_config={},
        locale="de",
    )

    recipients = ["user1@example.com", "user2@example.com", "user3@example.com"]

    # Note: This won't actually send in test mode
    print(f"📧 Would send to {len(recipients)} recipients")
    print(f"   Recipients: {recipients}")

    return {"recipients": len(recipients)}


async def main():
    """Run all service tests"""
    print("\n" + "🚀" + "=" * 58 + "🚀")
    print("   DealFinder Services Integration Tests")
    print("🚀" + "=" * 58 + "🚀\n")

    try:
        # Test report generator
        report_result = test_report_generator()

        # Test email sender (async)
        email_result = await test_email_sender()

        # Test bulk sending
        bulk_result = test_bulk_sending()

        print("\n" + "=" * 60)
        print("✅ ALL SERVICE TESTS PASSED")
        print("=" * 60)
        print(f"\n📊 Summary:")
        print(f"   - Report Generator: ✅ Working")
        print(f"   - Email Sender: ✅ Working")
        print(f"   - HTML Size: {len(report_result['html'])} bytes")
        print(f"   - Email Provider: {email_result['provider']}")

        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
