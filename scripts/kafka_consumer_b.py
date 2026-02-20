"""
Consumer Group B: arbitrage
Reads SAME events independently from Consumer A (VL7: Independent Consumer Groups)
Run with: python scripts/kafka_consumer_b.py
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
        group_id="arbitrage",
        value_deserializer=lambda m: json.loads(m.decode()),
        auto_offset_reset="earliest",
    )
    await consumer.start()
    print("[Consumer B / group=arbitrage] Same events, independent processing...")
    try:
        async for msg in consumer:
            start_time = time.perf_counter()
            d = msg.value
            print(
                f"  → ASIN={d.get('asin')} | layout={d.get('layout')} "
                f"| discount={d.get('discount_percent')}%"
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            log_kafka_consume(
                stage=PipelineStage.LOAD,
                topic=msg.topic,
                group_id="arbitrage",
                messages_processed=1,
                duration_ms=round(duration_ms, 2),
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
