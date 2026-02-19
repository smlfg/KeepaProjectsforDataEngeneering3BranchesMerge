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

## Architektur — wie die Teile zusammenhängen

```
┌─────────────────────────────────────────────────────────────────────┐
│                           DEIN RECHNER                              │
│                                                                     │
│  ┌──────────────────────┐      ┌──────────────────────────────────┐ │
│  │  systemd User Service │      │  Docker Container                │ │
│  │  keepa-scheduler      │      │                                  │ │
│  │                       │      │  ┌────────────┐  ┌───────────┐  │ │
│  │  Python Prozess:      │      │  │Elasticsearch│  │  Kibana   │  │ │
│  │  scheduler.py         │─────▶│  │  :9200     │  │   :5601   │  │ │
│  │  (APScheduler)        │      │  └────────────┘  └───────────┘  │ │
│  │                       │      └──────────────────────────────────┘ │
│  │  Alle 5 Minuten:      │                                           │
│  │  → Keepa API abfragen │  ┌───────────────────────────────────────┐ │
│  │  → Preise parsen      │  │  Cron Job (alle 5 Min)                │ │
│  │  → ES indexieren      │  │  keepa-watchdog.sh                    │ │
│  └──────────────────────┘  │  → Service noch aktiv?                │ │
│                             │  → ES erreichbar?                     │ │
│  ┌──────────────────────┐  │  → Tokens > 1000? → Discovery starten │ │
│  │  data/               │  └───────────────────────────────────────┘ │
│  │  seed_targets_eu_    │                                           │
│  │  qwertz.csv          │◀── discover_eu_qwertz_asins.py            │
│  │  (813 Zeilen)        │    (203 Kandidaten → validiert via /product)│
│  └──────────────────────┘                  ▼ Internet               │
│                                   ┌──────────────────────┐          │
│                                   │  api.keepa.com       │          │
│                                   │  /product  ✅ works   │          │
│                                   │  /token    ✅ works   │          │
│                                   │  /deals    ❌ 404     │          │
│                                   │  /query    ❌ 500     │          │
│                                   └──────────────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Die Dateien — und was jede tut

```
KeepaProjectsforDataEngeneering3BranchesMerge/
│
├── src/
│   ├── config.py                      ← Alle Einstellungen (API Key, Batch-Größe etc.)
│   └── services/
│       ├── keepa_client.py            ← Kommuniziert mit Keepa, parst CSV-Preisdaten
│       ├── elasticsearch_service.py   ← Speichert Deals in ES, erstellt Index + Mapping
│       └── scheduler.py               ← Das Herz: lädt Targets, sammelt Deals alle 5 Min
│
├── scripts/
│   └── discover_eu_qwertz_asins.py   ← Validiert 203 ASIN-Kandidaten via /product
│
├── data/
│   ├── seed_targets_eu_qwertz.csv     ← 813 Zeilen: jede ASIN × jeder EU-Markt
│   ├── seed_asins_eu_qwertz.json      ← JSON-Version der validierten ASINs
│   └── seed_asins_eu_qwertz.txt       ← Rohe ASIN-Liste (kommagetrennt)
│
├── docker-compose.yml                 ← Startet Elasticsearch + Kibana (+ Postgres, Redis)
├── .env                               ← API-Key, Batch-Größe, Intervall, Seed-Dateipfade
└── ~/.local/bin/keepa-watchdog.sh     ← Nachtwächter (Cron, alle 5 Min)
```

---

## Das Herz des Systems: wie Deals gefunden werden

### Das Keepa CSV-Format — der schwierigste Teil

Keepa gibt Preise nicht einfach als `{"price": 99.99}` zurück. Stattdessen kommt ein Array im sogenannten **CSV-Format** (kein echtes CSV — das ist nur Keepas interner Name):

```python
csv[0]  = Amazon-Preis-Geschichte     [timestamp1, preis1, timestamp2, preis2, ...]
csv[1]  = Neuer Marketplace-Preis     [timestamp1, preis1, timestamp2, preis2, ...]
csv[2]  = Gebraucht-Preis             [timestamp1, preis1, ...]
csv[9]  = Warehouse Deal (WHD)        [timestamp1, preis1, ...]
```

**Drei wichtige Regeln:**
- Preise sind **Ganzzahlen in Cent** → durch 100 dividieren für Euro
- `-1` bedeutet: kein Preis verfügbar (Amazon verkauft dieses Produkt nicht direkt)
- Der **letzte Wert** im Array ist der aktuellste Preis

```python
def _get_latest_price(csv_array) -> float | None:
    if not csv_array or len(csv_array) < 2:
        return None
    price_int = csv_array[-1]    # letztes Element = aktueller Preis
    if price_int == -1:
        return None
    return price_int / 100.0     # Cent → Euro
```

### Warum "product_heuristic" statt direkter Deal-Suche?

Das war die wichtigste Erkenntnis der gesamten Session: **Nicht alle Keepa-Endpoints sind auf allen Plänen verfügbar.**

| Endpoint | Was er tut | Status auf unserem Plan |
|----------|------------|------------------------|
| `/token` | Token-Status prüfen | ✅ funktioniert |
| `/product` | Produktdaten + Preishistorie | ✅ funktioniert |
| `/deals` | Direkte Deal-Suche | ❌ 404 Not Found |
| `/query` | Produktsuche nach Keyword | ❌ 500 Internal Error |
| `/search` | Kategorie-Suche | ❌ 500 Internal Error |
| `/bestsellers` | Bestseller-Listen | ❌ 500 Internal Error |

Die Lösung: Wir rufen `/product` mit einer Liste bekannter ASINs auf und **berechnen Deals selbst** durch Preisvergleich:

```python
# Wenn WHD-Preis oder Gebraucht-Preis existiert UND
# günstiger als Amazon-Preis/Neupreis → ist ein Deal

list_price = amazon_price or new_price    # Fallback wenn Amazon-Preis null
discount_pct = int((1 - deal_price / list_price) * 100)
if discount_pct >= 10:                    # 10% Mindestrabatt
    pass  # → Deal gefunden!
```

---

## Das Token-System: Keepas Währung

Keepa arbeitet mit **Tokens** — jede API-Anfrage kostet welche:

```
Keepa Token-Wirtschaft
───────────────────────────────────
Refill:       +1200 Tokens alle 5 Min
Pro Zyklus:   ~34 Tokens (813 ASINs ÷ 50/Batch × 2 Tokens)
Reserve:      ~1166 Tokens nach jedem Zyklus
Discovery:    ~200 Tokens (203 Kandidaten, 4 Domains)
───────────────────────────────────
Fazit: Token-Budget ist kein Problem.
```

Der Watchdog prüft den Token-Stand. Wenn Discovery laufen soll, brauchen wir >1000 Tokens — sonst warten wir auf den nächsten Refill.

---

## Die Bugs — was schiefging und wie wir's gefixt haben

### Bug #1: Validation zu streng — 0 ASINs validiert

**Problem:** Das Discovery-Script prüfte, ob ein Produkt einen *aktuellen* Preis hat. Viele Keyboards haben aber `amazon_price = -1` (nicht von Amazon direkt verkauft), besitzen aber trotzdem gebrauchte oder WHD-Preise in der Geschichte.

**Symptom:** 203 Kandidaten eingegeben, 0 validierte ASINs rausgekommen.

**Fix:** Die Pflicht-Preis-Prüfung entfernt. Jetzt reicht: Titel enthält Keyboard-Schlüsselwort.

```python
# Vorher (zu streng):
prices = [x for x in [amazon_p, new_p, used_p, whd_p] if x is not None]
if not prices:
    continue  # Rausgefiltert! Obwohl Produkt real existiert

# Nachher (korrekt):
# Preis ist optional — Titel + Keyboard-Keyword genügt
if not title_has_keyboard_evidence:
    continue
```

**Lehre:** *Niemals Validierungslogik auf Daten aufbauen, die optional sein können. Frage dich zuerst: Was bedeutet "valid" wirklich? Für uns: "existiert das Produkt und ist es eine Tastatur?" — nicht "hat es gerade einen Preis?"*

---

### Bug #2: SyntaxError bei Laufzeit statt beim Import

**Problem:** `keepa-scheduler.service` startete und crashte sofort. Fehlermeldung: `SyntaxError: unexpected 'except'` in Zeile 471.

**Ursache:** Ein `try:`-Block ohne `except:` in `_collect_to_elasticsearch()`. Python liest die ganze Datei beim Import, bemerkt das Problem aber erst wenn die Funktion tatsächlich aufgerufen wird.

```python
# Vorher (kaputt — try ohne except):
try:
    all_deals = []
    for domain_id, asins in targets_by_domain.items():
        ...
# ← hier fehlte das except!

class DealScheduler:   # Python: "Moment, ich hab ein offenes try...??"
    ...
```

**Fix:** `except Exception as e: logger.error(f"❌ Collection job failed: {e}", exc_info=True)` hinzugefügt.

**Lehre:** *Schreib `try:` und `except Exception:` immer direkt nacheinander, dann füll den Inhalt aus. Nie ein try ohne handler stehen lassen.*

---

### Bug #3: 0 Deals trotz laufendem System

**Problem:** Scheduler lief, Keepa wurde erfolgreich abgefragt, aber `valid_deals=0` in jedem 5-Minuten-Zyklus.

**Ursache:** `list_price = amazon_price` — aber für `B014EUQOGK` (Cherry MX Board) auf IT war `amazon_price = None`. Der Marketplace-Neupreis (`csv[1]`) war aber `112.03 EUR`.

```python
# Vorher:
amazon_price = self._get_latest_price(csv_data[0])
list_price = amazon_price    # Wenn None → kein Deal möglich → übersprungen

# Nachher (eine Zeile, die alles änderte):
new_price = self._get_latest_price(csv_data[1])   # ← Neu!
list_price = amazon_price or new_price             # ← Fallback!
```

**Lehre:** *Bei Amazon verkauft nicht immer Amazon selbst. `csv[0]` ist auf .it, .es, .fr oft -1. Immer Fallback auf `csv[1]` (Marketplace-Neupreis) einbauen.*

---

### Bug #4: Watchdog zeigt "tokens=?" statt einer Zahl

**Problem:** Watchdog meldete `Keepa tokens: left=? refill_in=?s` — konnte den Token-Stand nicht lesen.

**Ursache:** Keepa antwortet gzip-komprimiert. `curl` ohne `--compressed` liefert binäre Bytes statt JSON. `0x8b` ist das zweite Byte des gzip-Magic-Headers `\x1f\x8b`.

```bash
# Vorher:
TOKEN_JSON=$(curl -s "https://api.keepa.com/token?key=${API_KEY}")

# Nachher:
TOKEN_JSON=$(curl -s --compressed "https://api.keepa.com/token?key=${API_KEY}")
```

**Lehre:** *Web-APIs antworten fast immer gzip-komprimiert (spart bis zu 80% Bandwidth). `curl --compressed` dekomprimiert automatisch.*

---

### Bug #5: Der "andere KI hat's falsch gemacht"-Moment

Ein anderer KI-Assistent hatte einen 699-Zeilen-Discovery-Script gebaut der `/query`, `/search` und `/bestsellers` benutzte. Das Script lief, lieferte aber 33 Fehler hintereinander.

**Diagnose:** Nicht Verbindungsproblem, nicht Code-Bug — **Plan-Limitation**. HTTP 500 von Keepa bedeutet in diesem Fall "nicht in deinem Plan enthalten", nicht "interner Serverfehler".

**Wie wir's bewiesen haben:**
```bash
curl https://api.keepa.com/token?key=... → HTTP 200  # Verbindung ok
curl https://api.keepa.com/query?key=...  → HTTP 500  # Plan-Problem
```

**Lehre:** *Wenn ein Endpoint systematisch fehlschlägt obwohl Verbindung und Key okay sind: zuerst die Plan-Dokumentation lesen, nicht den Code debuggen.*

---

## Das Discovery-System: Wie wir ASINs finden ohne Suche

Da wir nicht suchen können (kein `/search`), nutzen wir: **Candidate Pool → Validation → Domain-Aware Targets**.

### Schritt 1: 203 Kandidaten zusammenstellen

Manuell recherchierte ASINs von bekannten Keyboard-Herstellern: Logitech, Cherry, Microsoft, Corsair, Razer, SteelSeries, Keychron, Ducky, HyperX, ASUS ROG, Perixx, Trust, Hama.

### Schritt 2: Validation via `/product`

Für jeden Kandidaten: Keepa-Produktdaten holen, prüfen ob Titel Keyboard-Keywords enthält:
```python
KEYBOARD_EVIDENCE = ["tastatur", "keyboard", "clavier", "tastiera",
                     "teclado", "cherry", "logitech k", "qwerty", "qwertz"]
```

### Schritt 3: Domain-aware CSV

Das Ergebnis: `data/seed_targets_eu_qwertz.csv` mit 813 Zeilen:
```csv
asin,domain_id,market,title,new_price,used_price,discount_percent
B014EUQOGK,2,UK,Cherry MX Board 3.0S,89.99,,
B014EUQOGK,4,FR,Cherry MX Board 3.0S,94.99,,
B014EUQOGK,8,IT,Cherry MX Board 3.0S,112.03,,
B014EUQOGK,9,ES,Cherry MX Board 3.0S,99.99,,
```

**Warum domain-spezifisch?** Ein ASIN der auf amazon.it verfügbar ist, könnte auf amazon.fr nicht existieren. Blind alle ASINs auf alle Märkte zu schicken verschwendet Tokens für Abfragen die sowieso -1 zurückgeben.

---

## Die Priority Chain: Wie der Scheduler Targets lädt

Das ist ein klassisches **Priority Chain Pattern** — eine der elegantesten Patterns in der Softwareentwicklung:

```python
def _load_targets(self) -> list[dict]:
    # 1. CSV-Datei (domain-aware, beste Quelle)
    if csv_path.exists():
        return load_from_csv(csv_path)

    # 2. DEAL_SEED_ASINS Env-Variable (wird auf alle 4 Domains expandiert)
    if settings.deal_seed_asins:
        return expand_to_all_domains(asins_from_env)

    # 3. JSON-Datei (älteres Format, als Fallback)
    if json_path.exists():
        return load_from_json(json_path)

    # 4. Hardcoded Minimal-Defaults (Notfallbetrieb)
    return [{"asin": "B014EUQOGK", "domain_id": 2, "market": "UK"}, ...]
```

Du kannst das Verhalten ändern **ohne Code zu ändern**: einfach die CSV-Datei ersetzen oder eine Env-Variable setzen. Der Code wählt automatisch die beste verfügbare Quelle.

---

## Das autonome Watchdog-System

```bash
# Läuft alle 5 Minuten via cron:
*/5 * * * * /home/smlflg/.local/bin/keepa-watchdog.sh
```

Der Watchdog macht drei Dinge (Log: `/tmp/keepa-watchdog.log`):

**1. Scheduler Self-Healing:**
```bash
if ! systemctl --user is-active --quiet keepa-scheduler.service; then
    systemctl --user restart keepa-scheduler.service
fi
```

**2. Elasticsearch Auto-Start:**
```bash
ES_STATUS=$(curl -s --compressed -o /dev/null -w "%{http_code}" http://localhost:9200/)
if [ "$ES_STATUS" != "200" ]; then
    docker compose up -d elasticsearch
fi
```

**3. Token-Budget + Discovery-Trigger:**
```bash
# Wenn Tokens > 1000 UND CSV-Datei älter als 24h → Discovery starten
if [ "$TOKENS_LEFT" -gt 1000 ] && [ CSV ist alt ]; then
    python scripts/discover_eu_qwertz_asins.py
fi
```

Das ist **selbstheilendes System-Design** — ein Pattern das du bei jedem Produktivsystem (Netflix, Google, Amazon) findest.

---

## Technologien und warum wir sie nutzen

| Technologie | Warum |
|-------------|-------|
| **Python asyncio** | Viele API-Calls gleichzeitig ohne Threads — effizienter |
| **APScheduler** | Cron-ähnliche Jobs in Python (IntervalTrigger + CronTrigger) |
| **httpx** | Async HTTP-Client (besser als `requests` für asyncio-Code) |
| **tenacity** | Automatisches Retry bei Rate-Limits mit exponential backoff |
| **Elasticsearch** | Speichert und durchsucht Deals; skaliert auf Millionen Dokumente |
| **Kibana** | Visualisiert ES-Daten ohne SQL zu schreiben |
| **Docker Compose** | ES + Kibana als Container — sauber, isoliert, einfach zu starten |
| **systemd user service** | Scheduler läuft auch ohne Login, startet bei Boot automatisch |
| **pydantic-settings** | Typsichere Konfiguration aus .env-Datei mit Validierung |

---

## Wie gute Engineers denken: Was wir gelernt haben

### 1. Systematisch debuggen, nicht raten
Als Deals nicht funktionierten: zuerst `/token` testen, dann `/product`, dann prüfen ob Deals berechnet werden. Von außen nach innen. Nicht sofort den Code umschreiben.

### 2. Plan-Limitations sind real
APIs haben Pläne. Was in der Dokumentation steht, muss nicht auf allen Plänen funktionieren. `curl url | python3 -m json.tool` ist dein bester Freund für schnelle Tests.

### 3. Fallbacks, immer
```python
list_price = amazon_price or new_price  # Eine Zeile, die 0 Deals zu echten Deals machte
```

### 4. Optional Data ist optional
Wenn Daten fehlen können, müssen alle Berechnungen mit `None` umgehen können. Niemals `None * 0.9` schreiben ohne zu prüfen.

### 5. Logging ist nicht optional
```
✅ [02:35 UTC] IT:3 UK:1 | total:4 es_indexed:4 | 8.3s
```
Ohne das weißt du nicht was das System die ganze Nacht gemacht hat.

### 6. Self-healing > Monitoring
Ein Watchdog der Probleme selbst löst ist wertvoller als ein Alert der dich nachts aufweckt.

### 7. Richtige Werkzeuge für richtige Jobs
Elasticsearch für Deals (Volltextsuche, Zeitreihen, Aggregationen). PostgreSQL für Nutzer-Daten (relationale Daten, Joins). Das ist nicht Überengineering — das ist das richtige Werkzeug wählen.

---

## Nächste Phase: Preisänderungen erkennen

Im Moment werden Deals **überschrieben** (upsert). Wenn ein Keyboard heute 89€ kostet und morgen 79€, siehst du nur den aktuellen Preis.

Für Preishistorie: eine kleine Code-Änderung in `elasticsearch_service.py`:
```python
# Statt (überschreibt):
"_id": asin

# Neu (append — behält alle historischen Werte):
"_id": f"{asin}_{domain}_{datetime.now().strftime('%Y%m%d_%H%M')}"
```

Dann kannst du in Kibana eine Zeitreihe zeigen: "B014EUQOGK auf IT in den letzten 30 Tagen".

---

## Kontrollbefehle für den Alltag

```bash
# System-Status
systemctl --user status keepa-scheduler.service
tail -30 /tmp/scheduler_new.log
tail -20 /tmp/keepa-watchdog.log

# Wieviele Deals hat Elasticsearch?
curl -s http://localhost:9200/keepa-deals/_count | python3 -m json.tool

# Kibana öffnen
http://localhost:5601

# Token-Stand prüfen
source .env && curl -s --compressed "https://api.keepa.com/token?key=$KEEPA_API_KEY" | python3 -m json.tool

# Discovery manuell starten (wenn Tokens voll)
cd /home/smlflg/DataEngeeneeringKEEPA/Input/KeepaProjectsforDataEngeneering3BranchesMerge
/home/smlflg/DataEngeeneeringKEEPA/.venv/bin/python scripts/discover_eu_qwertz_asins.py

# Scheduler neustarten
systemctl --user restart keepa-scheduler.service

# Cron-Jobs prüfen (Watchdog)
crontab -l
```

---

## Fragen zum Nachdenken

**1. Warum ist `csv[9]` (WHD) interessanter als `csv[2]` (Gebraucht)?**
WHD-Deals kommen direkt von Amazon mit Garantie und Returns. Gebraucht-Angebote kommen von Drittverkäufern — gleicher Preis, aber anderes Risiko.

**2. Warum Elasticsearch und nicht PostgreSQL für Deals?**
ES ist für Suche und Aggregationen optimiert. "Zeige alle Deals mit >20% Rabatt auf Mechanical Keyboards in IT/ES" ist in ES eine Query, in SQL ein komplexer JOIN mit LIKE-Suchen.

**3. Was passiert wenn Keepa die Token-Kosten erhöht?**
429-Fehler häufen sich, der Rate-Limit-Handler wartet 60s, das Log zeigt sofort was passiert. Dann `DEAL_SCAN_BATCH_SIZE` oder `DEAL_SCAN_INTERVAL_SECONDS` in `.env` anpassen — kein Code-Change nötig.

**4. Warum 203 Kandidaten und nicht 2000?**
Token-Budget. 2000 × 4 Märkte = 8000 Targets = ~320 Tokens pro Zyklus (26% des Refill-Budgets). Mit 203: ~34 Tokens = 2,8% — genug Puffer für Retries und Discovery.

**5. Warum systemd statt Docker für den Scheduler?**
Für einen einzigen Python-Prozess ist systemd einfacher. Docker wäre sinnvoll wenn: mehrere Services, Isolation nötig, oder Deployment auf fremden Servern geplant. Hier: ein Rechner, eine Aufgabe — systemd gewinnt.

---

*Geschrieben am 19. Februar 2026. Das System läuft autonom seit 02:30 Uhr und sammelt QWERTZ-Keyboard-Deals aus UK, FR, IT und ES. Watchdog aktiv, alle 5 Minuten.*
