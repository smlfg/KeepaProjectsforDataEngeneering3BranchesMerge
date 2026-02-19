# Keepa Arbitrage Engine — Data Engineering Project

> Automated keyboard deal discovery: Keepa API → Kafka → Elasticsearch → Kibana

## Quickstart

```bash
# 1. Start all services
docker-compose up -d

# 2. Start scheduler (systemd)
systemctl --user start keepa-scheduler.service

# 3. Open Kibana Dashboard
open http://localhost:5601
```

## Architecture

```
Keepa API
    │
    ▼
Scheduler (5-min cycle)
    │
    ├──► Elasticsearch ──► Kibana Dashboard
    │      keepa-deals          (visualizations)
    │      keepa-arbitrage
    │      [Alias: keepa-all]
    │      [Ingest Pipeline: keepa-pipeline]
    │
    └──► Kafka "keepa-raw-deals"
              │
              ├── Consumer Group A: es-indexer
              └── Consumer Group B: arbitrage (independent!)
```

## Kafka Consumer Demo

Open two terminals:

```bash
# Terminal 1 — Consumer Group A (es-indexer)
python scripts/kafka_consumer_a.py

# Terminal 2 — Consumer Group B (arbitrage, same messages!)
python scripts/kafka_consumer_b.py
```

Both consumers receive every deal independently — this demonstrates **independent consumer groups** from VL7.

## Cluster Demo (3-Node ES + 3-Broker Kafka)

```bash
docker-compose -f docker-compose.yml -f docker-compose.cluster.yml up -d
```

This starts a production-like cluster: 3 ES nodes with cross-node replication, 3 Kafka brokers with replication factor 3.

## Verification Checklist

```bash
# ES health
curl -s localhost:9200/_cluster/health | python3 -c "import sys,json; h=json.load(sys.stdin); print(f'ES: {h[\"status\"]} | nodes={h[\"number_of_nodes\"]}')"

# Ingest Pipeline
curl -s localhost:9200/_ingest/pipeline/keepa-pipeline | python3 -c "import sys,json; print('Pipeline OK:', json.load(sys.stdin)['keepa-pipeline']['description'])"

# Alias
curl -s localhost:9200/_alias/keepa-all | python3 -c "import sys,json; print('Alias covers:', list(json.load(sys.stdin).keys()))"

# Kafka topics
docker exec $(docker ps -qf name=kafka) /opt/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092

# Processed_at field (after one scheduler cycle)
curl -s "localhost:9200/keepa-deals/_search?size=1" | python3 -c "
import sys,json; s=json.load(sys.stdin)['hits']['hits'][0]['_source']
print(f'processed_at={s.get(\"processed_at\")} pipeline={s.get(\"pipeline_version\")} layout={s.get(\"layout\")}')"
```

## Architecture Decisions

| Decision | Rationale | Alternative Considered |
|----------|-----------|------------------------|
| Elasticsearch as primary sink | Low latency, native Kibana integration | PostgreSQL (no native viz) |
| Kafka as secondary bus | Decouples consumers, enables replay | RabbitMQ (no replay) |
| KRaft mode (no ZooKeeper) | Simpler ops, Kafka 3.x default | ZooKeeper-based (deprecated) |
| Ingest Pipeline | Server-side enrichment, no client changes needed | Logstash (extra component) |
| Index Template | Consistent mapping for all keepa-* indices | Manual per-index settings |
| Alias keepa-all | Single query endpoint across both indices | Union queries (verbose) |
| asyncio throughout | Single-threaded, no locking complexity | Threading (race conditions) |
