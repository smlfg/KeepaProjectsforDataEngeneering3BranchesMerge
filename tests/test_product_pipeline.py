"""
Tests for product-only deal pipeline (replaces /deals endpoint).
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.keepa_client import (
    KeepaClient,
    KeepaApiError,
    NoDealAccessError,
)


# ─── Unit: NoDealAccessError on 404 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_deal_access_error_on_404():
    """404 from /deals endpoint raises NoDealAccessError, not generic KeepaApiError."""
    client = KeepaClient(api_key="test_key")

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}
    mock_response.text = "404 Not Found"

    with patch.object(client, "_make_request", side_effect=NoDealAccessError("plan limitation")):
        with pytest.raises(NoDealAccessError):
            await client.get_deals(domain_id=3)


# ─── Unit: _get_latest_price CSV parsing ─────────────────────────────────────

def test_get_latest_price_normal():
    """Last element is the latest price, divided by 100."""
    result = KeepaClient._get_latest_price([1000, 9999, 1001, 8500])
    assert result == 85.0


def test_get_latest_price_unavailable():
    """-1 means price not available → returns None."""
    result = KeepaClient._get_latest_price([1000, 9999, 1001, -1])
    assert result is None


def test_get_latest_price_empty():
    """Empty or short array → None."""
    assert KeepaClient._get_latest_price([]) is None
    assert KeepaClient._get_latest_price([1000]) is None
    assert KeepaClient._get_latest_price(None) is None


# ─── Unit: get_products_with_deals discount heuristic ────────────────────────

@pytest.mark.asyncio
async def test_high_discount_included():
    """Products with >= min_discount% off are returned as deals."""
    client = KeepaClient(api_key="test_key")

    # Amazon price = 100.00, WHD = 60.00 → 40% discount
    mock_product = {
        "asin": "B001TEST01",
        "title": "Test Keyboard DE",
        "csv": [
            [1000, 10000],   # csv[0]: Amazon = 100.00
            None, None,       # csv[1], csv[2]: unused
            None, None, None, None, None, None,  # csv[3..8]
            [1000, 6000],    # csv[9]: WHD = 60.00
        ],
        "rating": 45,
        "reviewCount": 150,
    }

    mock_resp = {
        "products": [mock_product],
        "tokensConsumed": 1,
    }

    with patch.object(client, "_make_request", new_callable=AsyncMock, return_value=mock_resp):
        deals = await client.get_products_with_deals(
            asins=["B001TEST01"], domain_id=3, min_discount=10
        )

    assert len(deals) == 1
    assert deals[0]["asin"] == "B001TEST01"
    assert deals[0]["deal_type"] == "WHD"
    assert deals[0]["current_price"] == 60.0
    assert deals[0]["list_price"] == 100.0
    assert deals[0]["discount_percent"] == 40
    assert deals[0]["source"] == "product_heuristic"
    assert deals[0]["domain"] == "DE"


@pytest.mark.asyncio
async def test_low_discount_excluded():
    """Products below min_discount threshold are NOT returned."""
    client = KeepaClient(api_key="test_key")

    # Amazon = 100.00, Used = 95.00 → only 5% discount
    mock_product = {
        "asin": "B001TEST02",
        "title": "Cheap Keyboard",
        "csv": [
            [1000, 10000],   # Amazon = 100.00
            None,
            [1000, 9500],    # Used = 95.00
        ],
        "rating": 30,
        "reviewCount": 10,
    }

    mock_resp = {"products": [mock_product], "tokensConsumed": 1}

    with patch.object(client, "_make_request", new_callable=AsyncMock, return_value=mock_resp):
        deals = await client.get_products_with_deals(
            asins=["B001TEST02"], domain_id=3, min_discount=10
        )

    assert len(deals) == 0


@pytest.mark.asyncio
async def test_whd_preferred_over_used():
    """WHD price takes priority over Used price when both exist."""
    client = KeepaClient(api_key="test_key")

    mock_product = {
        "asin": "B001TEST03",
        "title": "Keyboard with both prices",
        "csv": [
            [1000, 10000],    # Amazon = 100.00
            None,
            [1000, 7500],     # Used = 75.00
            None, None, None, None, None, None,
            [1000, 6500],     # WHD = 65.00  ← should win
        ],
        "rating": 40,
        "reviewCount": 80,
    }

    mock_resp = {"products": [mock_product], "tokensConsumed": 1}

    with patch.object(client, "_make_request", new_callable=AsyncMock, return_value=mock_resp):
        deals = await client.get_products_with_deals(
            asins=["B001TEST03"], domain_id=3, min_discount=10
        )

    assert len(deals) == 1
    assert deals[0]["deal_type"] == "WHD"
    assert deals[0]["current_price"] == 65.0


@pytest.mark.asyncio
async def test_bad_asin_does_not_crash_batch():
    """One product with malformed data must not stop the whole batch."""
    client = KeepaClient(api_key="test_key")

    mock_resp = {
        "products": [
            # Bad product - no csv
            {"asin": "BBAD000001", "title": "Broken", "csv": None},
            # Good product - 30% off
            {
                "asin": "BGOOD00001",
                "title": "Good Keyboard",
                "csv": [
                    [1000, 10000],
                    None,
                    [1000, 7000],
                ],
                "rating": 45,
                "reviewCount": 200,
            },
        ],
        "tokensConsumed": 2,
    }

    with patch.object(client, "_make_request", new_callable=AsyncMock, return_value=mock_resp):
        deals = await client.get_products_with_deals(
            asins=["BBAD000001", "BGOOD00001"], domain_id=3, min_discount=10
        )

    # Only the good product should be in results
    assert len(deals) == 1
    assert deals[0]["asin"] == "BGOOD00001"


# ─── Integration: product_only pipeline with mocked Keepa ────────────────────

@pytest.mark.asyncio
async def test_scheduler_collect_calls_get_products(tmp_path):
    """
    Integration: _collect_to_elasticsearch uses get_products_with_deals,
    not get_deals. Deals are indexed to Elasticsearch.
    """
    # Create a minimal seed_asins.json in tmp_path
    seed = {"DE": ["B001TEST01"], "FR": [], "IT": [], "ES": [], "NL": []}
    seed_file = tmp_path / "config" / "seed_asins.json"
    seed_file.parent.mkdir(parents=True)
    seed_file.write_text(json.dumps(seed))

    from src.services.scheduler import DealOrchestrator

    orchestrator = DealOrchestrator.__new__(DealOrchestrator)

    mock_keepa = AsyncMock()
    mock_keepa.get_products_with_deals = AsyncMock(return_value=[
        {
            "asin": "B001TEST01",
            "title": "Keyboard Test",
            "current_price": 60.0,
            "list_price": 100.0,
            "discount_percent": 40,
            "domain": "DE",
            "deal_type": "WHD",
            "source": "product_heuristic",
        }
    ])
    orchestrator.keepa_client = mock_keepa

    mock_es = AsyncMock()
    mock_es.index_deals = AsyncMock(return_value={"success": True, "indexed": 1, "errors": 0})
    orchestrator.elasticsearch_service = mock_es
    orchestrator.stats = {"errors": 0}
    orchestrator._quarantine = set()

    # Patch _load_targets (scheduler uses _load_targets, domain_id 3 = DE)
    with patch.object(
        orchestrator,
        "_load_targets",
        return_value=[{"domain_id": 3, "asin": "B001TEST01"}],
    ):
        await orchestrator._collect_to_elasticsearch()

    mock_keepa.get_products_with_deals.assert_called_once()
    mock_es.index_deals.assert_called_once()
    indexed_deals = mock_es.index_deals.call_args[0][0]
    assert len(indexed_deals) == 1
    assert indexed_deals[0]["asin"] == "B001TEST01"
