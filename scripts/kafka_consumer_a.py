"""
Consumer Group A: es-indexer
Reads from keepa-raw-deals — demonstrates Producer/Consumer pattern (Übung 5)
Run with: python scripts/kafka_consumer_a.py
"""

import asyncio
import json

from aiokafka import AIOKafkaConsumer


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
            d = msg.value
            print(
                f"  → ASIN={d.get('asin')} | domain={d.get('domain')} "
                f"| price={d.get('current_price')}€ | layout={d.get('layout')}"
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
