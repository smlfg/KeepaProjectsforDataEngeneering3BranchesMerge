"""
Elasticsearch Service - Async Elasticsearch client for indexing Keepa deals
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from src.config import get_settings

logger = logging.getLogger("elasticsearch_service")


class ElasticsearchService:
    """
    Service for interacting with Elasticsearch.
    Provides async client and bulk indexing capabilities for Keepa deals.
    """

    INDEX_NAME = "keepa-deals"

    def __init__(self, hosts: Optional[List[str]] = None):
        """
        Initialize the Elasticsearch client.

        Args:
            hosts: List of Elasticsearch hosts (defaults to http://localhost:9200)
        """
        self.settings = get_settings()

        if hosts is None:
            hosts = ["http://localhost:9200"]

        self.client = AsyncElasticsearch(hosts=hosts)
        logger.info(f"Elasticsearch client initialized with hosts: {hosts}")

    async def create_index(self) -> bool:
        """
        Create the keepa-deals index if it doesn't exist.

        Returns:
            True if index exists or was created, False otherwise
        """
        try:
            exists = await self.client.indices.exists(index=self.INDEX_NAME)

            if not exists:
                await self.client.indices.create(
                    index=self.INDEX_NAME,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "asin": {"type": "keyword"},
                                "title": {"type": "text", "analyzer": "standard"},
                                "category": {"type": "keyword"},
                                "current_price": {"type": "float"},
                                "original_price": {"type": "float"},
                                "discount_percent": {"type": "integer"},
                                "rating": {"type": "float"},
                                "review_count": {"type": "integer"},
                                "sales_rank": {"type": "long"},
                                "amazon_url": {"type": "keyword"},
                                "image_url": {"type": "keyword"},
                                "is_amazon_seller": {"type": "boolean"},
                                "collected_at": {"type": "date"},
                                "domain": {"type": "keyword"},
                                "deal_score": {"type": "float"},
                                "layout": {"type": "keyword"},
                                "currency": {"type": "keyword"},
                                "price_eur": {"type": "float"},
                            }
                        },
                    },
                )
                logger.info(f"Created Elasticsearch index: {self.INDEX_NAME}")
            else:
                logger.debug(f"Index {self.INDEX_NAME} already exists")

            await self._setup_ingest_pipeline()
            await self._setup_index_template()
            await self._setup_alias()

            return True

        except Exception as e:
            logger.error(f"Error creating index: {e}")
            return False

    async def index_deals(self, deals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Bulk index deals into the keepa-deals index.

        Args:
            deals: List of deal dictionaries to index

        Returns:
            Dict with success status and statistics
        """
        try:
            if not deals:
                logger.warning("No deals to index")
                return {"success": True, "indexed": 0, "errors": 0}

            # Ensure index exists
            await self.create_index()

            # Prepare actions for bulk indexing
            actions = []
            timestamp = datetime.now(timezone.utc).isoformat()

            for deal in deals:
                asin = deal.get("asin")
                domain = deal.get("domain", "XX")
                doc_id = f"{asin}_{domain}" if asin else f"unknown_{domain}_{timestamp}"

                doc = {
                    "asin": deal.get("asin"),
                    "title": deal.get("title", ""),
                    "category": deal.get("category"),
                    "current_price": float(deal.get("current_price", 0))
                    if deal.get("current_price")
                    else None,
                    "original_price": float(deal.get("list_price", 0))
                    if deal.get("list_price")
                    else None,
                    "discount_percent": deal.get("discount_percent"),
                    "rating": float(deal.get("rating", 0))
                    if deal.get("rating")
                    else None,
                    "review_count": deal.get("reviews"),
                    "sales_rank": deal.get("sales_rank"),
                    "amazon_url": deal.get("amazon_url"),
                    "image_url": deal.get("image_url"),
                    "is_amazon_seller": deal.get("amazon_seller", False),
                    "collected_at": timestamp,
                    "domain": deal.get("domain"),
                    "deal_score": float(deal.get("deal_score", 0))
                    if deal.get("deal_score")
                    else None,
                    "layout": deal.get("layout", "Unknown"),
                    "currency": deal.get("currency", "EUR"),
                    "price_eur": deal.get("price_eur")
                    or float(deal.get("current_price") or 0),
                }

                action = {
                    "_op_type": "update",
                    "_index": self.INDEX_NAME,
                    "_id": doc_id,
                    "doc": doc,
                    "doc_as_upsert": True,
                }
                actions.append(action)

            # Perform bulk indexing
            success, errors = await async_bulk(
                self.client,
                actions,
                raise_on_error=False,
                raise_on_exception=False,
                chunk_size=500,
                pipeline="keepa-pipeline",
            )

            logger.info(
                f"Indexed {success} deals to Elasticsearch (errors: {len(errors) if errors else 0})"
            )

            return {
                "success": True,
                "indexed": success,
                "errors": len(errors) if errors else 0,
                "error_details": errors[:5] if errors else [],
            }

        except ConnectionError as e:
            logger.warning("ES not reachable, skipping index")
            return {
                "success": False,
                "indexed": 0,
                "errors": 0,
                "error": "ES not reachable",
            }

        except Exception as e:
            logger.error(f"Error indexing deals: {e}")
            return {
                "success": False,
                "indexed": 0,
                "errors": len(deals),
                "error": str(e),
            }

    async def search_deals(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        min_discount: Optional[int] = None,
        max_price: Optional[float] = None,
        min_rating: Optional[float] = None,
        size: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Search deals in Elasticsearch.

        Args:
            query: Text query for title search
            category: Filter by category
            min_discount: Minimum discount percentage
            max_price: Maximum current price
            min_rating: Minimum rating
            size: Number of results to return

        Returns:
            List of deal documents
        """
        try:
            must_clauses = []
            filter_clauses = []

            if query:
                must_clauses.append(
                    {"match": {"title": {"query": query, "fuzziness": "AUTO"}}}
                )

            if category:
                filter_clauses.append({"term": {"category": category}})

            if min_discount:
                filter_clauses.append(
                    {"range": {"discount_percent": {"gte": min_discount}}}
                )

            if max_price:
                filter_clauses.append({"range": {"current_price": {"lte": max_price}}})

            if min_rating:
                filter_clauses.append({"range": {"rating": {"gte": min_rating}}})

            search_body = {
                "size": size,
                "sort": [
                    {"timestamp": {"order": "desc"}},
                    {"deal_score": {"order": "desc"}},
                ],
                "query": {
                    "bool": {
                        "must": must_clauses if must_clauses else [{"match_all": {}}],
                        "filter": filter_clauses,
                    }
                },
            }

            response = await self.client.search(index=self.INDEX_NAME, body=search_body)

            hits = response.get("hits", {}).get("hits", [])
            deals = [hit["_source"] for hit in hits]

            logger.info(f"Found {len(deals)} deals in Elasticsearch")
            return deals

        except Exception as e:
            logger.error(f"Error searching deals: {e}")
            return []

    ARBITRAGE_INDEX = "keepa-arbitrage"

    async def create_arbitrage_index(self) -> bool:
        """Create the keepa-arbitrage index if it doesn't exist."""
        try:
            exists = await self.client.indices.exists(index=self.ARBITRAGE_INDEX)
            if not exists:
                await self.client.indices.create(
                    index=self.ARBITRAGE_INDEX,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "asin": {"type": "keyword"},
                                "title": {"type": "text"},
                                "buy_domain": {"type": "keyword"},
                                "sell_domain": {"type": "keyword"},
                                "buy_price": {"type": "float"},
                                "sell_price": {"type": "float"},
                                "margin_eur": {"type": "float"},
                                "margin_pct": {"type": "float"},
                                "shipping_cost": {"type": "float"},
                                "layout": {"type": "keyword"},
                                "calculated_at": {"type": "date"},
                            }
                        },
                    },
                )
                logger.info(f"Created Elasticsearch index: {self.ARBITRAGE_INDEX}")
            return True
        except Exception as e:
            logger.error(f"Error creating arbitrage index: {e}")
            return False

    async def index_arbitrage(
        self, opportunities: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Bulk upsert arbitrage opportunities into keepa-arbitrage index."""
        if not opportunities:
            return {"success": True, "indexed": 0, "errors": 0}
        try:
            await self.create_arbitrage_index()
            timestamp = datetime.now(timezone.utc).isoformat()
            actions = []
            for opp in opportunities:
                doc_id = f"{opp['asin']}_{opp['buy_domain']}_{opp['sell_domain']}"
                action = {
                    "_op_type": "update",
                    "_index": self.ARBITRAGE_INDEX,
                    "_id": doc_id,
                    "doc": {**opp, "calculated_at": timestamp},
                    "doc_as_upsert": True,
                }
                actions.append(action)
            success, errors = await async_bulk(
                self.client,
                actions,
                raise_on_error=False,
                raise_on_exception=False,
            )
            logger.info(f"Indexed {success} arbitrage opportunities")
            return {
                "success": True,
                "indexed": success,
                "errors": len(errors) if errors else 0,
            }
        except ConnectionError:
            return {
                "success": False,
                "indexed": 0,
                "errors": 0,
                "error": "ES not reachable",
            }
        except Exception as e:
            logger.error(f"Error indexing arbitrage: {e}")
            return {
                "success": False,
                "indexed": 0,
                "errors": len(opportunities),
                "error": str(e),
            }

    async def _setup_ingest_pipeline(self) -> None:
        """Übung 2: Ingest Pipeline — enriches documents on write."""
        try:
            await self.client.ingest.put_pipeline(
                id="keepa-pipeline",
                body={
                    "description": "Keepa deal enrichment pipeline",
                    "processors": [
                        {
                            "set": {
                                "field": "processed_at",
                                "value": "{{_ingest.timestamp}}",
                            }
                        },
                        {"set": {"field": "pipeline_version", "value": "v1"}},
                        {"uppercase": {"field": "layout", "ignore_missing": True}},
                    ],
                },
            )
            logger.info("Ingest pipeline 'keepa-pipeline' ready")
        except Exception as e:
            logger.warning(f"Ingest pipeline setup skipped: {e}")

    async def _setup_index_template(self) -> None:
        """Übung 2: Index Template — applies settings to all keepa-* indices."""
        try:
            await self.client.indices.put_index_template(
                name="keepa-template",
                body={
                    "index_patterns": ["keepa-*"],
                    "template": {
                        "settings": {
                            "number_of_shards": 1,
                            "number_of_replicas": 0,
                            "index.default_pipeline": "keepa-pipeline",
                        }
                    },
                },
            )
            logger.info("Index template 'keepa-template' ready")
        except Exception as e:
            logger.warning(f"Index template setup skipped: {e}")

    async def _setup_alias(self) -> None:
        """Übung 1+2: Alias 'keepa-all' spans both indices."""
        try:
            for idx in [self.INDEX_NAME, self.ARBITRAGE_INDEX]:
                if await self.client.indices.exists(index=idx):
                    await self.client.indices.put_alias(index=idx, name="keepa-all")
            logger.info("Alias 'keepa-all' ready")
        except Exception as e:
            logger.warning(f"Alias setup skipped: {e}")

    async def close(self):
        """Close the Elasticsearch connection."""
        await self.client.close()
        logger.info("Elasticsearch connection closed")


# Singleton instance
_elasticsearch_service: Optional[ElasticsearchService] = None


def get_elasticsearch_service() -> ElasticsearchService:
    """
    Get or create the Elasticsearch service singleton.

    Returns:
        ElasticsearchService instance
    """
    global _elasticsearch_service
    if _elasticsearch_service is None:
        _elasticsearch_service = ElasticsearchService()
    return _elasticsearch_service


async def close_elasticsearch_service():
    """Close the Elasticsearch service connection."""
    global _elasticsearch_service
    if _elasticsearch_service is not None:
        await _elasticsearch_service.close()
        _elasticsearch_service = None
