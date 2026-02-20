"""
Scheduler Service - Daily Deal Report Automation
Uses APScheduler for robust cron-based scheduling
"""

import asyncio
import csv
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.executors.asyncio import AsyncIOExecutor

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.data.database import AsyncSessionLocal
from src.data.repositories import FilterRepository, ReportRepository, UserRepository
from src.services.keepa_client import get_keepa_client
from src.services.keepa_client import KeepaRateLimitError, NoDealAccessError
from src.services.deal_scoring import get_deal_scoring_service
from src.services.report_generator import get_report_generator
from src.services.email_sender import get_email_sender
from src.services.elasticsearch_service import get_elasticsearch_service
from src.utils.pipeline_logger import (
    log_filter,
    log_es_index,
    log_arbitrage,
    log_targets,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("scheduler")


class DealOrchestrator:
    """
    Orchestrates the daily deal report workflow:
    1. Load active filters
    2. Find deals via Keepa API
    3. Score and rank deals
    4. Generate HTML report
    5. Send email
    """

    def __init__(self):
        self.settings = get_settings()
        self.keepa_client = get_keepa_client()
        self.scoring_service = get_deal_scoring_service()
        self.report_generator = get_report_generator()
        self.email_sender = get_email_sender()
        self.elasticsearch_service = get_elasticsearch_service()

        # Seed file tracking for hot-reload
        self._last_seed_mtime: float = 0.0
        self._cached_targets: list[dict] = []
        self._initial_load_done: bool = False

        # Stats tracking
        self.stats = {
            "filters_processed": 0,
            "deals_found": 0,
            "emails_sent": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

    async def run_daily_job(self):
        """Execute the daily deal report workflow"""
        logger.info("🚀 Starting daily deal report job")
        self.stats = {
            "filters_processed": 0,
            "deals_found": 0,
            "emails_sent": 0,
            "errors": 0,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": None,
        }

        try:
            # Step 1: Load active filters
            filters = await self._load_active_filters()
            logger.info(f"📋 Loaded {len(filters)} active filters")

            if not filters:
                logger.warning("No active filters found - skipping execution")
                return

            # Step 2: Process filters in parallel (batches of 10)
            semaphore = asyncio.Semaphore(10)

            async def process_filter_with_limit(filter_obj):
                async with semaphore:
                    return await self._process_filter(filter_obj)

            tasks = [process_filter_with_limit(f) for f in filters]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Step 3: Aggregate results
            for result in results:
                if isinstance(result, Exception):
                    self.stats["errors"] += 1
                    logger.error(f"Filter processing error: {result}")
                else:
                    self.stats["filters_processed"] += result.get(
                        "filters_processed", 0
                    )
                    self.stats["deals_found"] += result.get("deals_found", 0)
                    self.stats["emails_sent"] += result.get("emails_sent", 0)

        except Exception as e:
            logger.error(f"Critical error in daily job: {e}")
            self.stats["errors"] += 1

        finally:
            self.stats["end_time"] = datetime.now(timezone.utc).isoformat()

        # Log final stats
        duration = (
            datetime.fromisoformat(self.stats["end_time"])
            - datetime.fromisoformat(self.stats["start_time"])
        ).total_seconds()

        logger.info(f"""
╔══════════════════════════════════════════════════════╗
║         DAILY JOB COMPLETED                          ║
╠══════════════════════════════════════════════════════╣
║  Filters Processed: {self.stats["filters_processed"]:<28}║
║  Deals Found:       {self.stats["deals_found"]:<28}║
║  Emails Sent:       {self.stats["emails_sent"]:<28}║
║  Errors:            {self.stats["errors"]:<28}║
║  Duration:          {duration:.1f} seconds{" ":<21}║
╚══════════════════════════════════════════════════════╝
        """)

        # Generate ops report
        await self._send_ops_report()

    async def _load_active_filters(self) -> list:
        """Load all active filters scheduled for today"""
        async with AsyncSessionLocal() as session:
            repo = FilterRepository(session)
            filters = await repo.get_active_for_scheduling()
            return filters

    async def _process_filter(self, filter_obj) -> dict:
        """
        Process a single filter:
        1. Get deals from Keepa
        2. Score deals
        3. Generate report
        4. Send email
        """
        result = {
            "filter_id": str(filter_obj.id),
            "filter_name": filter_obj.name,
            "filters_processed": 1,
            "deals_found": 0,
            "emails_sent": 0,
            "error": None,
        }

        try:
            # Get filter config
            config = filter_obj
            categories = config.categories or []
            price_range = config.price_range or {"min": 0, "max": 10000}
            discount_range = config.discount_range or {"min": 0, "max": 100}

            # Step 1: Find deals via Keepa API
            deals = await self._find_deals(
                categories=categories,
                price_min=price_range.get("min", 0),
                price_max=price_range.get("max", 10000),
                discount_min=discount_range.get("min", 0),
                discount_max=discount_range.get("max", 100),
                min_rating=float(config.min_rating) if config.min_rating else 4.0,
                max_sales_rank=config.max_sales_rank or 100000,
            )

            if not deals:
                logger.info(f"No deals found for filter: {filter_obj.name}")
                return result

            result["deals_found"] = len(deals)

            # Step 2: Generate report
            filter_config = {
                "categories": categories,
                "price_range": price_range,
                "discount_range": discount_range,
            }

            report_data = self.report_generator.generate_report(
                deals=deals,
                filter_name=filter_obj.name,
                filter_config=filter_config,
                locale="de",
            )

            # Step 3: Save report to DB
            async with AsyncSessionLocal() as session:
                report_repo = ReportRepository(session)
                report = await report_repo.create(
                    filter_id=filter_obj.id,
                    deals=report_data["deals"],
                    deal_count=report_data["deal_count"],
                )

            # Step 4: Get user email
            async with AsyncSessionLocal() as session:
                user_repo = UserRepository(session)
                user = await user_repo.get_by_id(filter_obj.user_id)
                user_email = user.email if user else None

            if not user_email:
                logger.warning(f"No email found for user: {filter_obj.user_id}")
                return result

            # Step 5: Send email
            today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
            subject = f"🔥 {filter_obj.name} - {today}"

            email_result = await self.email_sender.send_report(
                to_email=user_email,
                subject=subject,
                html_body=report_data["html"],
                text_body=report_data["text"],
                filter_name=filter_obj.name,
                report_id=str(report.id),
            )

            if email_result["sent"]:
                # Mark report as sent
                async with AsyncSessionLocal() as session:
                    report_repo = ReportRepository(session)
                    await report_repo.mark_sent(report.id, email_result["message_id"])

                result["emails_sent"] = 1
                logger.info(
                    f"✅ Email sent to {user_email} for filter: {filter_obj.name}"
                )

        except Exception as e:
            logger.error(f"Error processing filter {filter_obj.id}: {e}")
            result["error"] = str(e)
            self.stats["errors"] += 1

        return result

    async def _find_deals(
        self,
        categories: list,
        price_min: float,
        price_max: float,
        discount_min: int,
        discount_max: int,
        min_rating: float,
        max_sales_rank: int,
    ) -> list:
        """
        Find deals via Keepa API with fallback to cached data
        """
        # Convert price to cents for Keepa API
        price_min_cents = int(price_min * 100)
        price_max_cents = int(price_max * 100)

        # Build category string
        category_str = ",".join(categories) if categories else "0"

        try:
            # Try Keepa API first
            response = await self.keepa_client.get_products(
                asins=[],  # We would need to search first
                domain_id=3,  # Amazon.de
            )

            # Parse products
            products = self.keepa_client.parse_products(response["raw"])

            # For now, return mock deals (in production, use Keepa search)
            # This is a placeholder - real implementation would use Keepa's search endpoint
            logger.info(f"Found {len(products)} products from Keepa")

            # Score deals
            scored_deals = self.scoring_service.rank_deals(products)

            return scored_deals[:15]  # Top 15 deals

        except Exception as e:
            logger.error(f"Keepa API error, using fallback: {e}")
            # Return empty list - in production, could use cached deals
            return []

    async def _send_ops_report(self):
        """Send operations report to monitoring channel"""
        # In production, this would send to Slack/email
        logger.info(f"""
╔══════════════════════════════════════════════════════╗
║         OPERATIONS REPORT                            ║
╠══════════════════════════════════════════════════════╣
║  Job ID:         {str(uuid4())[:8]:<28}║
║  Start Time:     {self.stats["start_time"]:<28}║
║  End Time:       {self.stats["end_time"]:<28}║
║  Status:         {"SUCCESS" if self.stats["errors"] == 0 else "PARTIAL":<28}║
╚══════════════════════════════════════════════════════╝
        """)

    # ── Bad-ASIN quarantine (in-memory, reset on restart) ────────────────────
    _quarantine: set = set()

    @staticmethod
    def _detect_layout(title: str, domain: str) -> str:
        """Detect keyboard layout from title + market context."""
        t = (title or "").lower()
        # Explicit layout signals (highest confidence)
        if any(
            kw in t
            for kw in ["qwertz", "deutsch", "german layout", "layout de", "de layout"]
        ):
            return "QWERTZ"
        if any(
            kw in t
            for kw in ["azerty", "français", "french layout", "layout fr", "fr layout"]
        ):
            return "AZERTY"
        if any(
            kw in t
            for kw in ["ch layout", "swiss layout", "schweizer", "suisse", "svizzera"]
        ):
            return "CH"
        if any(
            kw in t
            for kw in ["nordic", "scandinavian", "no layout", "se layout", "dk layout"]
        ):
            return "Nordic"
        if any(
            kw in t
            for kw in [
                "uk layout",
                "us layout",
                "english layout",
                "international",
                "iso uk",
            ]
        ):
            return "QWERTY-UK"
        if any(kw in t for kw in ["italiano", "layout it", "it layout"]):
            return "QWERTY-IT"
        if any(kw in t for kw in ["español", "layout es", "es layout"]):
            return "QWERTY-ES"
        # Market-based fallback (lower confidence)
        market_defaults = {
            "DE": "QWERTZ",
            "AT": "QWERTZ",
            "CH": "CH",
            "FR": "AZERTY",
            "IT": "QWERTY-IT",
            "ES": "QWERTY-ES",
            "UK": "QWERTY-UK",
            "NL": "QWERTY-NL",
        }
        return market_defaults.get(domain, "Unknown")

    def _load_targets(self) -> list[dict]:
        """
        Load domain-specific targets. Priority:
          1. DEAL_TARGETS_FILE CSV  (asin,domain_id,market columns)
          2. DEAL_SEED_ASINS env   (comma-separated ASINs → expanded to all 4 EU domains)
          3. DEAL_SEED_FILE JSON   (by_domain format → expanded to target list)
          4. hardcoded minimal defaults
        Returns list of {"asin": str, "domain_id": int, "market": str}

        Auto-reloads when seed file changes (detected via mtime).
        """
        DOMAIN_EU = {"UK": 2, "DE": 3, "FR": 4, "IT": 8, "ES": 9, "AT": 16}
        settings = get_settings()
        root = Path(__file__).parent.parent.parent

        # Priority 1 – CSV targets file (domain-aware)
        csv_path = root / settings.deal_targets_file

        # Check if seed file has been updated since last load
        if csv_path.exists():
            current_mtime = os.path.getmtime(csv_path)
            if self._cached_targets and current_mtime == self._last_seed_mtime:
                # File unchanged - return cached targets
                return self._cached_targets
            if current_mtime > self._last_seed_mtime:
                # File has been updated - clear cache to force reload
                self._cached_targets = []
                logger.info(f"Seed file updated, will reload targets")
        loaded_targets = []
        validated_count = 0
        domain_counts: dict[int, int] = {}

        if csv_path.exists():
            try:
                targets = []
                validated_targets = []
                with open(csv_path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    fieldnames = {str(x).strip() for x in (reader.fieldnames or [])}
                    has_metadata_columns = any(
                        col in fieldnames
                        for col in (
                            "title",
                            "new_price",
                            "used_price",
                            "list_price",
                            "deal_price",
                            "discount_percent",
                            "validated_at",
                        )
                    )

                    for row in reader:
                        asin = (row.get("asin") or "").strip()
                        domain_id = int(row.get("domain_id") or 0)
                        market = (row.get("market") or row.get("domain") or "").strip()
                        if asin and domain_id:
                            target = {
                                "asin": asin,
                                "domain_id": domain_id,
                                "market": market,
                            }
                            targets.append(target)
                            domain_counts[domain_id] = (
                                domain_counts.get(domain_id, 0) + 1
                            )

                            title = (row.get("title") or "").strip()
                            has_price = any(
                                (row.get(k) or "").strip()
                                for k in (
                                    "new_price",
                                    "used_price",
                                    "list_price",
                                    "deal_price",
                                )
                            )
                            if title or has_price:
                                validated_targets.append(target)
                                validated_count += 1

                if validated_targets:
                    logger.info(
                        f"🎯 Seed source: {settings.deal_targets_file} "
                        f"({len(validated_targets)} validated targets, "
                        f"domain_counts={dict(sorted(domain_counts.items()))})"
                    )
                    loaded_targets = validated_targets

                # If metadata columns exist but no row has title/price, treat file as raw/unvalidated.
                elif targets and has_metadata_columns:
                    logger.warning(
                        f"⚠️  Ignoring raw target file {settings.deal_targets_file}: "
                        f"{len(targets)} rows but no validated title/price metadata."
                    )
                    loaded_targets = targets
                elif targets:
                    logger.info(
                        f"🎯 Seed source: {settings.deal_targets_file} ({len(targets)} targets)"
                    )
                    loaded_targets = targets
            except Exception as e:
                logger.warning(f"Could not read targets CSV: {e}")

        # Check if DE (domain_id=3) targets exist; if not, add fallback DE ASINs
        de_count = domain_counts.get(3, 0)
        if de_count == 0 and loaded_targets:
            logger.warning(
                f"⚠️  No DE (domain_id=3) targets found in {settings.deal_targets_file}. "
                f"Found domains: {list(domain_counts.keys())}. "
                f"Adding fallback DE QWERTZ ASINs to ensure DE deals are collected."
            )
            fallback_de_asins = [
                "B08DG4C63H",  # Trust Taro - available in DE
                "B00F35N1KS",  # CHERRY KC 1000
                "B09N9CY637",  # CHERRY STREAM KEYBOARD TKL
                "B08ZNSJ152",  # Dell KM5221W
                "B003UL1RGC",  # Logitech K120
            ]
            for asin in fallback_de_asins:
                loaded_targets.append(
                    {
                        "asin": asin,
                        "domain_id": 3,  # DE
                        "market": "DE",
                    }
                )
            logger.info(f"➕ Added {len(fallback_de_asins)} fallback DE targets")

        if loaded_targets:
            # Cache targets and update modification time
            if csv_path.exists():
                self._last_seed_mtime = os.path.getmtime(csv_path)
            self._cached_targets = loaded_targets
            if not hasattr(self, "_initial_load_done") or not self._initial_load_done:
                self._initial_load_done = True
            else:
                logger.info(
                    f"Reloaded {len(loaded_targets)} ASINs from updated seed file"
                )
            log_targets(domain_counts)
            return loaded_targets

        # Priority 2 – DEAL_SEED_ASINS env (expand to all 4 domains)
        if settings.deal_seed_asins:
            asins = [
                a.strip() for a in settings.deal_seed_asins.split(",") if a.strip()
            ]
            if asins:
                targets = [
                    {"asin": a, "domain_id": did, "market": m}
                    for m, did in DOMAIN_EU.items()
                    for a in asins
                ]
                logger.info(
                    f"🌱 Seed source: DEAL_SEED_ASINS env ({len(targets)} targets across 4 domains)"
                )
                return targets

        # Priority 3 – JSON seed file
        json_path = root / settings.deal_seed_file
        if not json_path.exists():
            json_path = root / "data" / "seed_asins_eu_qwertz.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text())
                by_domain = data.get("by_domain", {})
                targets = []
                for market, entries in by_domain.items():
                    did = DOMAIN_EU.get(market, 0)
                    if not did:
                        continue
                    for entry in entries or []:
                        asin = entry.get("asin") if isinstance(entry, dict) else entry
                        if asin:
                            targets.append(
                                {"asin": asin, "domain_id": did, "market": market}
                            )
                if targets:
                    logger.info(
                        f"🌱 Seed source: {json_path.name} ({len(targets)} targets)"
                    )
                    return targets
            except Exception as e:
                logger.warning(f"Could not read seed JSON: {e}")

        # Priority 4 – hardcoded minimal defaults
        logger.warning(
            "🌱 Seed source: hardcoded defaults — run discovery script to improve"
        )
        defaults = ["B01NABDNPH", "B014EUQOGK", "B01E8KO2B0"]
        return [
            {"asin": a, "domain_id": did, "market": m}
            for m, did in DOMAIN_EU.items()
            for a in defaults
        ]

    async def _collect_to_elasticsearch(self):
        """
        Collect deals and index them to Elasticsearch (product_only mode).
        Interval: DEAL_SCAN_INTERVAL_SECONDS (default 300s)
        Batch:    DEAL_SCAN_BATCH_SIZE (default 50 ASINs per call)
        """
        logger.info("📊 Starting deal collection job (product_only)")
        start_time = datetime.now(timezone.utc)

        settings = get_settings()
        batch_size = settings.deal_scan_batch_size
        DOMAIN_NAMES = {2: "UK", 3: "DE", 4: "FR", 8: "IT", 9: "ES", 14: "NL", 16: "AT"}
        KEYBOARD_KEYWORDS = [
            "tastatur",  # DE
            "clavier",  # FR
            "tastiera",  # IT
            "teclado",  # ES
            "toetsenbord",  # NL
            "klawiatura",  # PL
            "keyboard",  # EN (allgemein)
            "qwertz",  # Layout DE/AT/CH — wichtigstes Signal
            "azerty",  # Layout FR/BE
            "mechanisch",  # DE mechanisch
            "mechanical",  # EN mechanical
            "gaming tastatur",
            "gaming keyboard",
            "keychron",  # Brand: meist QWERTZ/ISO verfügbar
            "ducky",  # Brand: QWERTZ-Varianten verfügbar
            "anne pro",  # Brand: QWERTZ-Varianten verfügbar
            # ENTFERNT: "qwerty" (matcht EN/ES-Layouts → False Positives)
            # ENTFERNT: "cherry", "razer", "logitech k", "corsair k" (layout-agnostisch)
        ]

        targets = self._load_targets()
        if not targets:
            logger.warning("No targets — skipping. Run discovery script first.")
            return

        # Group by domain_id for batched API calls
        targets_by_domain: dict[int, list[str]] = {}
        for t in targets:
            did = t["domain_id"]
            if t["asin"] not in self._quarantine:
                targets_by_domain.setdefault(did, [])
                targets_by_domain[did].append(t["asin"])

        total_targets = sum(len(v) for v in targets_by_domain.values())
        logger.info(f"   targets={total_targets} batch_size={batch_size}")

        try:
            all_deals: list[dict] = []
            asins_processed = 0

            for domain_id, asins in targets_by_domain.items():
                domain_name = DOMAIN_NAMES.get(domain_id, str(domain_id))
                if not asins:
                    continue

                for i in range(0, len(asins), batch_size):
                    batch = asins[i : i + batch_size]
                    asins_processed += len(batch)
                    try:
                        deals = await self.keepa_client.get_products_with_deals(
                            asins=batch,
                            domain_id=domain_id,
                            min_discount=10,
                        )
                        for d in deals:
                            d["layout"] = self._detect_layout(
                                d.get("title", ""), d.get("domain", "")
                            )
                        all_deals.extend(deals)
                        if deals:
                            logger.info(
                                f"  → {domain_name}: {len(deals)} deals "
                                f"from {len(batch)} ASINs"
                            )
                        else:
                            logger.debug(
                                f"  → {domain_name}: 0 deals from {len(batch)} ASINs: {batch[:3]}..."
                            )
                    except NoDealAccessError as e:
                        logger.error(f"API plan limitation: {e}")
                        return
                    except KeepaRateLimitError:
                        logger.warning(
                            f"⚠️ Rate limit on {domain_name} — waiting 60s before retry..."
                        )
                        await asyncio.sleep(60)  # Wait for token refill
                        try:
                            deals = await self.keepa_client.get_products_with_deals(
                                asins=batch,
                                domain_id=domain_id,
                                min_discount=10,
                            )
                            all_deals.extend(deals)
                            if deals:
                                logger.info(
                                    f"  → {domain_name}: {len(deals)} deals after wait"
                                )
                        except KeepaRateLimitError:
                            logger.error(
                                f"Still rate limited after wait — skipping domain {domain_name}"
                            )
                            continue
                        else:
                            for d in deals:
                                d["layout"] = self._detect_layout(
                                    d.get("title", ""), d.get("domain", "")
                                )
                    except Exception as e:
                        logger.warning(f"  → {domain_name} batch error: {e}")

            # Filter: keyboard evidence
            keyboard_deals = [
                d
                for d in all_deals
                if any(kw in (d.get("title") or "").lower() for kw in KEYBOARD_KEYWORDS)
            ]

            # Log filter results for each deal
            asins_in_keyboard = {d.get("asin") for d in keyboard_deals}
            for d in all_deals:
                asin = d.get("asin", "")
                if asin in asins_in_keyboard:
                    log_filter(asin=asin, filtered_in=True, reason="qwertz_keyword")
                else:
                    log_filter(asin=asin, filtered_in=False, reason="no_keyword_match")

            valid_deals = keyboard_deals if keyboard_deals else all_deals

            # Count by domain
            domain_counts: dict[str, int] = {}
            for d in valid_deals:
                dom = d.get("domain", "?")
                domain_counts[dom] = domain_counts.get(dom, 0) + 1

            job_time = datetime.now(timezone.utc).strftime("%H:%M")

            logger.info(
                f"   asins_processed={asins_processed} "
                f"valid_deals_found={len(valid_deals)} "
                f"keyboard={len(keyboard_deals)}"
            )

            if not valid_deals:
                logger.info("No deals found this cycle — nothing to index")
                return

            # Index to Elasticsearch
            result = await self.elasticsearch_service.index_deals(valid_deals)
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            es_indexed = result.get("indexed", 0)
            es_errors = result.get("errors", 0)

            log_es_index(docs_indexed=es_indexed, errors=es_errors)

            if result["success"]:
                logger.info(
                    f"✅ [{job_time} UTC] "
                    + " ".join(f"{d}:{c}" for d, c in domain_counts.items())
                    + f" | total:{len(valid_deals)} es_indexed:{es_indexed}"
                    + f" | {duration:.1f}s"
                )
            else:
                logger.error(f"❌ ES index failed: {result.get('error')}")

            # Phase 3: Calculate arbitrage after every successful collection
            await self._calculate_arbitrage()

            # Kafka: publish raw deals (fire-and-forget — ES is primary sink)
            try:
                from src.services.kafka_producer import KeepaKafkaProducer

                _producer = KeepaKafkaProducer(self.settings.kafka_bootstrap_servers)
                await _producer.start()
                published = await _producer.publish_deals(valid_deals)
                await _producer.stop()
                logger.info(f"📨 Kafka: {published} deals → keepa-raw-deals")
            except Exception as e:
                logger.warning(f"Kafka publish skipped (Kafka not available): {e}")

        except Exception as e:
            logger.error(f"❌ Collection job failed: {e}", exc_info=True)

    async def _calculate_arbitrage(self):
        """
        Phase 3: Cross-market arbitrage engine.
        Reads all deals from keepa-deals, finds ASIN pairs where margin > 15€ after shipping.
        Indexes results into keepa-arbitrage.
        """
        SHIPPING: dict[tuple, float] = {
            ("IT", "DE"): 6.0,
            ("ES", "DE"): 10.0,
            ("FR", "DE"): 7.0,
            ("UK", "DE"): 9.0,
            ("IT", "ES"): 8.0,
            ("FR", "ES"): 8.0,
            ("IT", "FR"): 7.0,
            ("UK", "FR"): 8.0,
            ("UK", "IT"): 9.0,
            ("ES", "FR"): 8.0,
        }
        MIN_MARGIN = 15.0

        try:
            response = await self.elasticsearch_service.client.search(
                index=self.elasticsearch_service.INDEX_NAME,
                body={
                    "size": 1000,
                    "query": {
                        "bool": {"filter": [{"exists": {"field": "current_price"}}]}
                    },
                    "_source": ["asin", "title", "domain", "current_price", "layout"],
                },
            )
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return

            # Group by ASIN — only keep entries with a price
            by_asin: dict[str, list] = {}
            for h in hits:
                s = h["_source"]
                asin = s.get("asin")
                if asin and s.get("current_price"):
                    by_asin.setdefault(asin, []).append(s)

            opportunities = []
            for asin, entries in by_asin.items():
                if len(entries) < 2:
                    continue
                entries_sorted = sorted(entries, key=lambda x: x["current_price"])
                cheapest = entries_sorted[0]
                for sell_entry in entries_sorted[1:]:
                    buy_dom = cheapest["domain"]
                    sell_dom = sell_entry["domain"]
                    buy_price = cheapest["current_price"]
                    sell_price = sell_entry["current_price"]
                    shipping = SHIPPING.get(
                        (buy_dom, sell_dom),
                        SHIPPING.get((sell_dom, buy_dom), 10.0),
                    )
                    margin = sell_price - buy_price - shipping
                    if margin >= MIN_MARGIN:
                        margin_pct = (sell_price - buy_price) / buy_price * 100
                        opportunities.append(
                            {
                                "asin": asin,
                                "title": cheapest.get("title", ""),
                                "buy_domain": buy_dom,
                                "sell_domain": sell_dom,
                                "buy_price": round(buy_price, 2),
                                "sell_price": round(sell_price, 2),
                                "margin_eur": round(margin, 2),
                                "margin_pct": round(margin_pct, 1),
                                "shipping_cost": shipping,
                                "layout": cheapest.get("layout", "Unknown"),
                            }
                        )

            if opportunities:
                result = await self.elasticsearch_service.index_arbitrage(opportunities)
                top_margin = max((o["margin_eur"] for o in opportunities), default=0.0)
                log_arbitrage(
                    opportunities_found=len(opportunities), top_margin_eur=top_margin
                )
                logger.info(
                    f"🏆 Arbitrage: {len(opportunities)} opportunities "
                    f"(errors: {result.get('errors', 0)})"
                )
                top3 = sorted(
                    opportunities, key=lambda x: x["margin_eur"], reverse=True
                )[:3]
                for opp in top3:
                    logger.info(
                        f"   💰 {opp['asin']} | {opp['buy_domain']}→{opp['sell_domain']}"
                        f" | +{opp['margin_eur']:.1f}€ ({opp['margin_pct']:.0f}%)"
                        f" | {opp['layout']}"
                    )
            else:
                log_arbitrage(opportunities_found=0, top_margin_eur=0.0)
                logger.info("📊 Arbitrage: no opportunities ≥ 15€ margin this cycle")

        except Exception as e:
            logger.warning(f"Arbitrage calculation skipped: {e}")


class DealScheduler:
    """
    APScheduler-based scheduler for daily deal reports
    """

    def __init__(self):
        self.settings = get_settings()
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.orchestrator = DealOrchestrator()

    def setup_scheduler(self) -> AsyncIOScheduler:
        """Configure and return the scheduler"""
        # Job stores - using memory store for simplicity
        # For production, use SQLAlchemyJobStore with PostgreSQL
        jobstores = {"default": MemoryJobStore()}

        # Executors — asyncio for async jobs, thread pool for sync jobs
        executors = {
            "default": AsyncIOExecutor(),
            "threadpool": ThreadPoolExecutor(max_workers=10),
        }

        # Job defaults
        job_defaults = {
            "coalesce": False,
            "max_instances": 1,
            "misfire_grace_time": 3600,  # 1 hour grace time
        }

        # Create scheduler
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",  # All times in UTC
        )

        # Add daily job at 06:00 UTC
        self.scheduler.add_job(
            func=self.orchestrator.run_daily_job,
            trigger=CronTrigger(hour=6, minute=0, second=0, timezone="UTC"),
            id="daily_deal_report",
            name="Daily Deal Report @ 06:00 UTC",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Add configurable interval job for Elasticsearch indexing
        interval_secs = self.settings.deal_scan_interval_seconds
        self.scheduler.add_job(
            func=self.orchestrator._collect_to_elasticsearch,
            trigger=IntervalTrigger(seconds=interval_secs, timezone="UTC"),
            id="elasticsearch_collection",
            name=f"Elasticsearch Deal Collection ({interval_secs}s)",
            replace_existing=True,
            misfire_grace_time=interval_secs,
        )

        logger.info(
            f"✅ Scheduler configured for daily @ 06:00 UTC "
            f"+ deal collector every {interval_secs}s "
            f"(batch_size={self.settings.deal_scan_batch_size})"
        )

        return self.scheduler

    def start(self):
        """Start the scheduler"""
        if not self.scheduler:
            self.setup_scheduler()

        self.scheduler.start()
        logger.info("🚀 DealFinder Scheduler started")

        # Print schedule
        job = self.scheduler.get_job("daily_deal_report")
        if job:
            logger.info(f"📅 Next run: {job.next_run_time}")

    def stop(self):
        """Stop the scheduler gracefully"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("🛑 Scheduler stopped")

    def run_now(self):
        """Manually trigger the daily job (for testing)"""
        logger.info("⚡ Manual trigger - running daily job now")
        asyncio.create_task(self.orchestrator.run_daily_job())


# Global scheduler instance
_scheduler: Optional[DealScheduler] = None


def get_scheduler() -> DealScheduler:
    """Get or create scheduler singleton"""
    global _scheduler
    if _scheduler is None:
        _scheduler = DealScheduler()
    return _scheduler


async def run_scheduler():
    """Entry point for running the scheduler"""
    scheduler = get_scheduler()

    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum} - shutting down...")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start scheduler
    scheduler.start()

    # Keep the main coroutine running
    try:
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour
    except asyncio.CancelledError:
        scheduler.stop()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════╗
║         DealFinder Scheduler                         ║
║  Daily Deal Report Automation                        ║
╚══════════════════════════════════════════════════════╝
    """)

    asyncio.run(run_scheduler())
