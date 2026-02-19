"""
Consumer Group B: arbitrage
Reads SAME events independently from Consumer A (VL7: Independent Consumer Groups)
Run with: python scripts/kafka_consumer_b.py
"""

import asyncio
import json

from aiokafka import AIOKafkaConsumer


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
            d = msg.value
            print(
                f"  → ASIN={d.get('asin')} | layout={d.get('layout')} "
                f"| discount={d.get('discount_percent')}%"
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
