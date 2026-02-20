"""Async Kafka Producer — publishes raw deals to keepa-raw-deals topic."""

import json
import logging
from typing import Any, Dict, List

from aiokafka import AIOKafkaProducer

from src.utils.pipeline_logger import log_kafka_produce, PipelineStage

logger = logging.getLogger("kafka_producer")
TOPIC = "keepa-raw-deals"


class KeepaKafkaProducer:
    def __init__(self, bootstrap_servers: str = "localhost:9092"):
        self.bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        await self._producer.start()
        logger.info(f"Kafka producer connected to {self.bootstrap_servers}")

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish_deals(self, deals: List[Dict[str, Any]]) -> int:
        """Publish deals to Kafka topic. Returns count published."""
        if not self._producer:
            return 0

        log_kafka_produce(
            stage=PipelineStage.EXTRACT,
            topic=TOPIC,
            message_count=len(deals),
            before_send=True,
        )

        for deal in deals:
            await self._producer.send(TOPIC, value=deal)
        await self._producer.flush()

        log_kafka_produce(
            stage=PipelineStage.EXTRACT,
            topic=TOPIC,
            message_count=len(deals),
            before_send=False,
        )

        return len(deals)
