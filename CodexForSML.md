# DealFinder — Das große Abenteuer: Keepa → Elasticsearch

*Ein ehrlicher Bericht über wie dieses System gebaut wurde, was schiefging, was wir gelernt haben, und warum es jetzt nachts alleine läuft.*

---

## Was ist dieses Projekt überhaupt?

Stell dir vor, du willst täglich wissen: **Welche QWERTZ-Tastaturen sind gerade auf Amazon UK, FR, IT und ES im Angebot?** Nicht nur auf .de — sondern auf den europäischen Märkten, wo dieselben Logitech- und Cherry-Tastaturen manchmal 30% billiger sind.

Das manuell zu machen ist absurd — hunderte Produktseiten auf vier Amazon-Websites, täglich, mehrsprachig. Also baut man ein System, das das automatisch tut.

**Das System macht folgendes:**
1. Alle 5 Minuten: Fragt Keepa (Amazons Preis-Historien-API) nach Deals
2. Speichert gefundene Deals in Elasticsearch (eine Such-Datenbank)
3. Zeigt alles live in Kibana (ein Dashboard-Tool)
4. Überwacht sich nachts selbst via Watchdog (Cron-Job)

---

## 1. System Architecture

### systemd + Python venv (Not Docker)

The system runs as a **systemd user service** (`~/.config/systemd/user/keepa-scheduler.service`) rather than in Docker. This decision was made for simplicity and direct environment access:

```ini
[Service]
Type=simple
WorkingDirectory=/home/smlflg/DataEngeeneeringKEEPA/Input/KeepaProjectsforDataEngeneering3BranchesMerge
Environment=PYTHONPATH=.
ExecStart=/home/smlflg/DataEngeeneeringKEEPA/.venv/bin/python -m src.services.scheduler
Restart=on-failure
```

**Why systemd over Docker?**
- Direct access to Python environment and local files
- Simpler debugging — logs go to `/tmp/scheduler_new.log`
- No container orchestration overhead for a single-service app
- Easy integration with system startup (`systemctl --user enable keepa-scheduler`)

**Trade-offs:** Less portable, requires manual dependency management on the host.

---

## 2. Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.x |
| Web Framework | FastAPI | ≥0.109.0 |
| Async HTTP | httpx | ≥0.26.0 |
| Scheduler | APScheduler | (via pip) |
| Database | PostgreSQL + SQLAlchemy | ≥2.0.25 |
| Primary Store | Elasticsearch | ≥8.0.0 |
| Message Queue | RabbitMQ (aio-pika) | ≥9.4.0 |
| Cache | Redis | ≥5.0.1 |
| Email | SendGrid API | — |
| Deployment | systemd | — |

---

## 3. Data Flow: Discovery → Seed → Scheduler → Elasticsearch

```
┌─────────────────────────────────────────────────────────────────────────┐
│  1. DISCOVERY (one-time / periodic)                                    │
│     scripts/discover_eu_qwertz_asins.py                                │
│     ┌──────────────────┐                                               │
│     │ Static ASIN Pool │  ~100 candidates (Logitech, Cherry,          │
│     │ (CANDIDATE_POOL) │  Microsoft, Corsair, Razer, Keychron...)     │
│     └────────┬─────────┘                                               │
│              │ validate against Keepa /product API                     │
│              ▼                                                          │
│     ┌──────────────────────────────────────────┐                        │
│     │ Keepa API → filter: keyboard keywords   │                        │
│     │ → only products with "keyboard",         │                        │
│     │   "tastatur", "qwertz" in title          │                        │
│     └────────────────────┬─────────────────────┘                        │
│                          │                                              │
│                          ▼                                              │
│     data/seed_asins_eu_qwertz.json + .txt                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. SEED APPLICATION                                                   │
│     scripts/apply_seed_env.py                                          │
│     → writes DEAL_SEED_ASINS to .env                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. SCHEDULER (continuous)                                             │
│     src/services/scheduler.py                                          │
│                                                                          │
│     ┌─────────────────────────────────────────────────────────────┐   │
│     │ APScheduler                                                  │   │
│     │  • Daily job @ 06:00 UTC — generate email reports          │   │
│     │  • Interval job @ every 300s — collect deals → ES          │   │
│     └─────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                    ┌───────────────┴───────────────┐                   │
│                    ▼                               ▼                   │
│     ┌────────────────────────┐   ┌────────────────────────┐          │
│     │ Keepa API Client      │   │ Elasticsearch Service   │          │
│     │ • get_products()      │   │ • index_deals()        │          │
│     │ • get_products_with_deals() | • search_deals()     │          │
│     │ • Rate limiting       │   │ • Bulk upserts         │          │
│     │ • Token consumption   │   │                        │          │
│     └────────────────────────┘   └────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Why Static ASIN Pool?

The Keepa API has two endpoints for deal discovery:
- `/search` — keyword search (only on **Premium plans**)
- `/product` — fetch by ASIN (available on all plans)

Since the project started with a **Basic plan**, the discovery workflow was designed to:
1. Start with a curated list of known keyboard ASINs
2. Validate each against `/product` to check for current deals
3. Store valid ASINs in a seed file
4. The scheduler repeatedly checks seed ASINs for deal conditions

This is a **clever workaround** for API plan limitations — you don't need the expensive search endpoint if you have a smart pool of candidates.

---

## 4. Key Components & Responsibilities

### 4.1 `scheduler.py` — DealOrchestrator + DealScheduler

Two classes work together:

**DealOrchestrator** — The actual work:
- `_load_active_filters()` — loads user filter configs from PostgreSQL
- `_process_filter()` — single filter: get deals → score → generate report → send email
- `_collect_to_elasticsearch()` — **the interval job**:
  - Loads seed ASINs (priority: env var → generated file → config → hardcoded)
  - Iterates domains: UK (2), FR (4), IT (8), ES (9)
  - Batch calls to Keepa (`get_products_with_deals()`)
  - Filters by keyboard keywords
  - Indexes to Elasticsearch

**DealScheduler** — APScheduler wrapper:
- Uses `AsyncIOScheduler` with `IntervalTrigger` (every 300s default)
- Also schedules daily email job at 06:00 UTC
- Graceful shutdown on SIGTERM/SIGINT

### 4.2 `elasticsearch_service.py`

- Creates `keepa-deals` index on first run (if not exists)
- **Bulk upsert** — uses `doc_as_upsert: True` to update existing deals
- Handles connection errors gracefully (logs warning, continues)
- Search capabilities with filters (category, discount, price, rating)

### 4.3 `keepa_client.py`

- Handles all Keepa API communication
- **Rate limiting** — reads `X-RateLimit-Remaining` header, respects limits
- **Token tracking** — logs `tokensConsumed` per request
- Exception hierarchy: `KeepaApiError` → `KeepaRateLimitError`, `KeepaAuthError`, `NoDealAccessError`
- **Retry logic** — uses `tenacity` with exponential backoff (30s–120s)
- Two deal-finding strategies:
  1. `get_deals()` — uses `/deals` endpoint (Premium plan only)
  2. `get_products_with_deals()` — **heuristic approach** using CSV price arrays:
     - `csv[0]` = Amazon price history
     - `csv[1]` = New price history
     - `csv[2]` = Used price history
     - `csv[9]` = Warehouse Deal (WHD) price history

### 4.4 Discovery Script (`discover_eu_qwertz_asins.py`)

- **Static candidate pool** — ~100 ASINs from major keyboard brands
- Validates each against Keepa `/product` API
- Filters by **keyboard evidence keywords** in title
- Outputs two files:
  - `data/seed_asins_eu_qwertz.json` — full metadata per ASIN
  - `data/seed_asins_eu_qwertz.txt` — comma-separated for env var

### 4.5 Apply Seed Script (`apply_seed_env.py`)

- Reads the generated `.txt` file
- Writes `DEAL_SEED_ASINS="..."` to `.env`
- Requires service restart to pick up new seeds

---

## 5. Lessons Learned

### 5.1 Keepa API Rate Limiting & Token Economics

**The Problem:** Keepa charges by **tokens** (not requests). Every API call consumes tokens based on:
- Number of ASINs requested
- Data fields requested
- Domain complexity

**The Solution:**
- Batch requests (50 ASINs per call) to amortize token cost
- Implemented **in-memory quarantine** — failed ASINs are skipped for the session
- Added **sleep delays** (1s) between batches to avoid hitting rate limits
- Used `tenacity` retry with exponential backoff for transient failures

**Key Learning:** Design for token efficiency. The static ASIN pool approach works because you pay once to validate, then cheap repeated checks on a small set.

### 5.2 datetime.utcnow() Deprecation

**The Bug:** Early versions used `datetime.utcnow()` which is deprecated in Python 3.12+ and produces runtime warnings.

**The Fix:**
```python
# Before (deprecated)
datetime.utcnow().isoformat()

# After (correct)
from datetime import datetime, timezone
datetime.now(timezone.utc).isoformat()
```

**Key Learning:** Always use timezone-aware datetimes. `utcnow()` returns naive datetime which can cause subtle bugs in timezone-aware systems.

### 5.3 Missing Exception Block

**The Bug:** In an earlier version, the scheduler was missing an `except` block, causing unhandled exceptions to crash the entire process.

**The Fix:**
```python
try:
    # ... work ...
except NoDealAccessError as e:
    logger.error(f"API plan limitation: {e}")
    return  # Graceful degradation
except KeepaRateLimitError:
    logger.warning(f"Rate limit on {domain_name} — skipping rest")
    break
except Exception as e:
    logger.warning(f"  → {domain_name} batch error: {e}")
```

**Key Learning:** Always catch specific exceptions before generic ones. For a long-running scheduler, graceful degradation is better than crash.

### 5.4 Elasticsearch as Primary Store (vs PostgreSQL)

**The Decision:** The project moved from using PostgreSQL for deal storage to Elasticsearch.

**Why Elasticsearch?**
- **Full-text search** on product titles
- **Time-series friendly** — naturally stores `collected_at` timestamps
- **Easy aggregations** — can query "deals by domain", "average discount", etc.
- **Upsert support** — `doc_as_upsert: True` lets you update deals by ASIN without worrying about duplicates

**Why Keep PostgreSQL?**
- Still needed for **user data, filters, reports** (structured relational data)
- Session management, authentication, settings

**Key Learning:** Use the right tool for the right job. Elasticsearch ≠ database replacement — it's a search and analytics engine.

### 5.5 systemd vs Docker

**The Decision:** systemd user service instead of Docker container.

**Why systemd?**
- Direct file access to project directory
- Simple logging to `/tmp/scheduler_new.log`
- No port mapping or network configuration
- `systemctl --user` is sufficient for a personal automation project

**Why Not Docker?**
- Would need volume mounts for persistence
- Additional complexity for a single process
- Harder to debug (need `docker exec`)

**Key Learning:** Don't use a tool because it's trendy. For a personal automation project, the simplest solution that works is best.

---

## 6. Next Steps: Cross-Market Arbitrage

The foundation is in place for **cross-market arbitrage detection**:

1. **Current state:** Deals are indexed by domain (UK, FR, IT, ES)
2. **What's missing:**
   - **Price correlation** — same ASIN across domains, compare prices
   - **Arbitrage detection** — if DE price < ES price - shipping margin → alert
   - **Historical analysis** — track price history to spot anomalies

**Proposed enhancements:**
- Add a **cross-domain lookup job** — query same ASIN across all 4 domains
- Store correlated deals in ES with `cross_domain_price_diff` field
- Add **SMTP/email notification** when arbitrage threshold exceeded

**Keepa limitation to watch:** The Basic plan only allows 2,000 API requests/day. Cross-market correlation would double/triple token consumption. Plan accordingly.

---

## 7. Code Quality Notes

- **Async-first:** Uses `asyncio`, `AsyncIOScheduler`, `AsyncElasticsearch`
- **Type hints:** Extensive use of Python type annotations
- **Singleton pattern:** Clients are singletons (`get_keepa_client()`, `get_elasticsearch_service()`)
- **Environment config:** Uses `pydantic-settings` with `.env` support

---

## Summary

The KeepaDealFinder is a well-architected automation pipeline that works around API limitations (Basic plan) using creative approaches (static ASIN pool, CSV heuristic for deals). It demonstrates solid engineering practices:

- Async/await everywhere
- Graceful error handling
- Token-efficient API usage
- Hybrid storage (PostgreSQL for users, ES for deals)
- Simple deployment (systemd)

The biggest risk is **Keepa API plan costs** — token consumption scales with the number of ASINs and domains. The current design is conservative (batches, quarantines) which is smart for cost control.

---

## 8. Delta-Update (Stand: 19. Februar 2026)

Dieser Abschnitt ergänzt den bisherigen Text mit dem **aktuellen Betriebsstand** aus Code, Dateien und Logs.

### 8.1 Aktueller Seed-Stand (wichtig für Prüfung + Betrieb)

- `data/seed_asins_eu_qwertz.txt` enthält aktuell **203** eindeutige ASINs.
- `data/seed_asins_eu_qwertz.json` enthält in `_meta`:
  - `unique_asins: 203`
  - `target_rows: 812`
  - `domains: UK, FR, IT, ES`
- `data/seed_targets_eu_qwertz.csv` war zuletzt zeitweise **leer/header-only**.
  - Folge: Der Scheduler fällt auf `DEAL_SEED_ASINS` zurück.
  - In den Logs ist das sichtbar als:
    - `Seed source: DEAL_SEED_ASINS env (16 targets across 4 domains)`
    - oder (wenn CSV befüllt): `Seed source: data/seed_targets_eu_qwertz.csv (...)`.

### 8.2 Verbindliche Seed-Quelle-Priorität im Code

In `src/services/scheduler.py` (`_load_targets`) gilt:

1. `DEAL_TARGETS_FILE` (CSV: `asin,domain_id,market`)
2. `DEAL_SEED_ASINS` (Env, Expansion auf UK/FR/IT/ES)
3. `DEAL_SEED_FILE` (JSON mit `by_domain`)
4. hardcoded Defaults

Das ist die wichtigste technische Stelle für die Frage:  
"Warum zieht der Collector gerade diese Targets?"

### 8.3 Scheduler/Keepa Ist-Verhalten aus Logs

Beobachtet am 19. Februar 2026:

- Phasen mit **HTTP 429** (Rate Limit) auf allen 4 Domains.
- Phasen mit **HTTP 200** und gefundenen Deals (z. B. IT/ES).
- Trotzdem zeitweise `es_indexed:0`, weil beim ES-Indexing ein Fehler auftritt:
  - `Error creating index: BadRequestError(400, 'None')`
  - danach Bulk-Index mit Fehlern.

Interpretation:
- Keepa-Abfrage funktioniert grundsätzlich.
- Der Engpass ist nicht nur Token-Limit, sondern auch die **ES-Index-Erstellung/Mapping-Kompatibilität**.

### 8.4 Watchdog + Cron (Ops)

Aktuell genutzt:

- Script: `~/.local/bin/keepa-watchdog.sh`
- Cron-Eintrag:
  - `*/5 * * * * /home/smlflg/.local/bin/keepa-watchdog.sh`
- Logdatei:
  - `/tmp/keepa-watchdog.log`

Watchdog-Aufgaben:

- prüft `keepa-scheduler.service`, startet bei Ausfall neu
- prüft Elasticsearch (`keepa-deals/_count`)
- prüft Keepa Tokens (`tokensLeft`, `refillIn`)
- nutzt `curl --compressed` (wichtig für gzip-korrekte Token-Antworten)

### 8.5 Runbook: Reihenfolge "erst ASIN-Liste, dann Preischeck"

Diese Reihenfolge ist korrekt und sollte beibehalten werden:

1. **Seed-Liste füllen/prüfen**
   - Ziel: valide, domain-aware Targets in `seed_targets_eu_qwertz.csv`
   - Mindestprüfung:
     - ASIN-Liste > 0
     - CSV enthält echte Datenzeilen (nicht nur Header)
2. **Dann erst Price/Deal-Collection aktiv fahren**
   - konservative Werte in `.env`:
     - `DEAL_SCAN_BATCH_SIZE=8..12`
     - `DEAL_SCAN_INTERVAL_SECONDS=600..900`
   - damit weniger 429 bei kleinem Token-Budget
3. **Monitoring**
   - `/tmp/scheduler_new.log`
   - `/tmp/keepa-watchdog.log`
   - `keepa-deals` Dokumentanzahl

### 8.6 Prüfungs-Story (Kurzform)

Wenn in der Prüfung gefragt wird "Warum diese Architektur?":

- Keepa Basic/Pricing-Limits erfordern token-effizientes Design.
- Deshalb domain-aware Seed-Pipeline statt teurer Vollsuche.
- Scheduler arbeitet robust mit Fallbacks und Quarantäne.
- Watchdog stabilisiert den Dauerbetrieb.
- Der aktuelle nächste technische Fokus ist:
  - stabile Seed-Befüllung
  - ES-Indexing-Fehler (400) beheben
  - dann über Nacht kontinuierlich sammeln.

### 8.7 Offene Risiken (transparent benennen)

- Token-Limit/429 bei zu aggressivem Scan-Takt
- inkonsistente Seed-Dateien (JSON zeigt 812 Zielzeilen, CSV evtl. leer)
- ES `BadRequestError(400)` bei Index-Erstellung
- Service-Restarts schlagen teilweise fehl (im Watchdog-Log sichtbar)

Diese Risiken sind nicht "Projekt kaputt", sondern klare technische Baustellen mit reproduzierbaren Logs.
