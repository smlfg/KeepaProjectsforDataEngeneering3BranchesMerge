"""
Consumer Group A: es-indexer
Reads from keepa-raw-deals — demonstrates Producer/Consumer pattern (Übung 5)
Run with: python scripts/kafka_consumer_a.py
"""

import asyncio
import json
import time

from aiokafka import AIOKafkaConsumer

from src.utils.pipeline_logger import log_kafka_consume, PipelineStage


async def main():
    consumer = AIOKafkaConsumer(
        "keepa-raw-deals",
        bootstrap_servers="localhost:9092",
        group_id="es-indexer",
        value_deserializer=lambda m: json.loads(m.decode()),
        auto_offset_reset="earliest",
    )
    await consumer.start()
    print("[Consumer A / group=es-indexer] Listening on keepa-raw-deals...")
    try:
        async for msg in consumer:
            start_time = time.perf_counter()
            d = msg.value
            print(
                f"  → ASIN={d.get('asin')} | domain={d.get('domain')} "
                f"| price={d.get('current_price')}€ | layout={d.get('layout')}"
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            log_kafka_consume(
                stage=PipelineStage.LOAD,
                topic=msg.topic,
                group_id="es-indexer",
                messages_processed=1,
                duration_ms=round(duration_ms, 2),
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
