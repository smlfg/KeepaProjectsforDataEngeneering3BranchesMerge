# 100-Punkte Plan: Keyboard Price Arbitrage Engine
## Keepa → Elasticsearch → N:N Cross-Market Arbitrage

**Vision:** Alle Keyboard-ASINs auf allen EU-Märkten tracken. Preisdifferenzen identifizieren.
Schweizer Markt als Premium-Zielmarkt (CH-Layout, hohe Kaufkraft, niedrige Zölle).

---

## PHASE 1: Foundation Fix (Punkte 1–15)
*Ziel: Sauberes Datenmodell das N:N Arbitrage ermöglicht*

- [ ] 1.  ES doc_id: `asin` → `{asin}_{domain}` (jeder Markt bekommt eigenes Dokument)
- [ ] 2.  Feld `list_price` korrekt benennen (`original_price` → `list_price` konsistent)
- [ ] 3.  Domain DE (domain_id=3, amazon.de) in Scanner hinzufügen
- [ ] 4.  Keepa Domain IDs vollständig: NL(14), SE(19), PL(20), BE(21)
- [ ] 5.  CH-Markt-Strategie: amazon.de domain=3 als CH-Proxy (Schweizer kaufen dort)
- [ ] 6.  ES-Mapping: `layout` (keyword), `currency` (keyword), `price_eur` (float) hinzufügen
- [ ] 7.  Währungs-Normalisierung: GBP→EUR, CHF→EUR, PLN→EUR, SEK→EUR
- [ ] 8.  `collected_at` Timestamp korrekt auf alle Dokumente
- [ ] 9.  Test: `curl keepa-deals/_count` zeigt Dokumente pro Domain (nicht überschrieben)
- [ ] 10. Test: Basis-Scheduler läuft noch stabil nach allen Änderungen
- [ ] 11. Seed CSV: DE (domain_id=3) als 5. Markt hinzufügen → 203 × 5 = 1015 Targets
- [ ] 12. Scheduler: DOMAIN_MAP um DE erweitern (bisher nur UK/FR/IT/ES)
- [ ] 13. Watchdog: Token-Check läuft noch korrekt
- [ ] 14. ES Index löschen + neu erstellen mit sauberem Mapping
- [ ] 15. ✅ CHECKPOINT: 5 Domains × mehrere ASINs in ES, alle mit individuellem doc_id

## PHASE 2: Layout Detection (Punkte 16–28)
*Ziel: Jedem Keyboard-Deal ein Layout zuordnen*

- [ ] 16. Layout-Detection-Funktion aus Titel: `detect_layout(title) → "QWERTZ"|"QWERTY"|"AZERTY"|"CH"|"Nordic"|"Unknown"`
- [ ] 17. QWERTZ-Signale: "qwertz", "deutsch", "german", "DE layout", "layout DE"
- [ ] 18. AZERTY-Signale: "azerty", "français", "french layout", "FR layout"
- [ ] 19. CH-Layout-Signale: "schweizer", "swiss", "CH layout", "suisse"
- [ ] 20. Nordic-Signale: "nordic", "scandinavian", "NO/DK/FI/SE layout"
- [ ] 21. QWERTY-UK/US-Signale: "uk layout", "us layout", "english", "international"
- [ ] 22. Fallback: Markt-basierte Vermutung (IT→QWERTY-IT, DE→QWERTZ, FR→AZERTY)
- [ ] 23. `layout`-Feld in ES Mapping + alle neuen Dokumente mit Layout indexieren
- [ ] 24. EXCLUDE-Logik: Produkte die klar kein Keyboard sind (Headset, Maus, Numpad)
- [ ] 25. EXCLUDE-Keywords: "headset", "mouse", "maus", "numpad", "controller", "gamepad"
- [ ] 26. Test: Layout-Detection auf die 1 bestehenden Deals prüfen
- [ ] 27. Discovery-Script: Layout auch in seed_targets_eu_qwertz.csv speichern
- [ ] 28. ✅ CHECKPOINT: Alle ES-Dokumente haben `layout` Feld

## PHASE 3: Preisvergleich Engine (Punkte 29–45)
*Ziel: Für jeden ASIN Preise über alle Märkte vergleichen*

- [ ] 29. ES-Aggregation: Für jeden ASIN max/min Preis über alle Domains
- [ ] 30. Arbitrage-Berechnung: `margin = max_price - min_price - shipping_cost`
- [ ] 31. Versandkosten-Modell: Pauschal nach Route (DE→CH: 8€, IT→DE: 6€, ES→DE: 10€)
- [ ] 32. Neue ES-Collection: `keepa-arbitrage` mit berechneten Opportunities
- [ ] 33. Arbitrage-Dokument: `{asin, buy_domain, sell_domain, buy_price, sell_price, margin, margin_pct}`
- [ ] 34. Job in Scheduler: `_calculate_arbitrage()` nach jeder Collection
- [ ] 35. Nur Opportunities mit `margin > 15€` speichern (unter Versandkosten lohnt nicht)
- [ ] 36. `margin_pct`: `(sell - buy) / buy * 100` als Ranking-Grundlage
- [ ] 37. Duplikat-Check: Nur neue/geänderte Opportunities upserten
- [ ] 38. Test: Simulierte Preisdaten → Arbitrage-Calculation korrekt?
- [ ] 39. Schweizer Customs-Kalkulation: Wert > CHF 150 → +8.1% MWST einrechnen
- [ ] 40. Netto-Margin nach MWST und Versand berechnen
- [ ] 41. `roi_pct` Feld: Return on Investment für Händler
- [ ] 42. Mindest-Lagerumschlag: Nur ASINs mit Sales Rank < 100.000
- [ ] 43. Keepa csv[SALES] einlesen und `sales_rank` Feld befüllen
- [ ] 44. Arbitrage-Filter: `sales_rank AND margin_eur > 15 AND roi_pct > 20`
- [ ] 45. ✅ CHECKPOINT: `keepa-arbitrage` Index hat echte Opportunities

## PHASE 4: Schweiz-Fokus (Punkte 46–58)
*Ziel: CH als Premium-Zielmarkt hervorheben*

- [ ] 46. Schweizer Retail-Preise research: Digitec.ch, Galaxus.ch als Benchmark
- [ ] 47. `digitec_price` Feld: manuell oder via Scraping für Top-ASINs
- [ ] 48. Schweizer Margin: `ch_margin = digitec_price - amazon_de_price - shipping`
- [ ] 49. CH-Layout Detection verbessern: Logitech CH-spezifische ASINs identifizieren
- [ ] 50. CH Layout ASINs: Separate Liste als Priority-Targets
- [ ] 51. Zoll-Kalkulation CH: Gewicht-basierte Duties (meist 0 für Electronics)
- [ ] 52. CHF/EUR Wechselkurs: Live-Kurs via API (exchangerate-api.com, kostenlos)
- [ ] 53. `price_chf` Feld: Automatisch konvertiert
- [ ] 54. Schweizer Versandkosten: DHL.ch Pauschal nach Gewicht-Klassen modellieren
- [ ] 55. ricardo.ch / tutti.ch Preise als Sell-Price-Benchmark (manuell/research)
- [ ] 56. `ch_opportunity_score`: Kombiniert margin + sales_rank + layout_match
- [ ] 57. Top 10 CH-Opportunities täglich loggen
- [ ] 58. ✅ CHECKPOINT: CH-spezifischer Score in Arbitrage-Dokumenten

## PHASE 5: Ranking & Scoring (Punkte 59–72)
*Ziel: Opportunities ranken, beste Deals zuerst*

- [ ] 59. Composite Score Formel: `score = (margin_pct * 0.4) + (1/log(sales_rank) * 0.3) + (layout_premium * 0.3)`
- [ ] 60. Layout-Premium: CH=1.5, QWERTZ=1.2, AZERTY=1.1, QWERTY=1.0
- [ ] 61. Markt-Premium: CH-Ziel=1.5, DE-Ziel=1.2, andere=1.0
- [ ] 62. Volatilität-Bonus: Produkte mit sinkenden Preisen → bessere Entry-Points
- [ ] 63. `deal_freshness`: Wie lange ist der Preis schon auf diesem Level? (aus Keepa Historie)
- [ ] 64. Saison-Faktor: Back-to-school (August), Weihnachten (Dez) → höhere Sell-Preise
- [ ] 65. Confidence-Score: Wieviele Datenpunkte haben wir? Mehr = zuverlässiger
- [ ] 66. ES Percolator: Auto-Alert wenn Score > Threshold
- [ ] 67. Täglicher Ranking-Report in `/tmp/arbitrage_daily.log`
- [ ] 68. Top-3 Opportunities prominent loggen: `🏆 CH-Opportunity: B014EUQOGK | +42€ | Score: 8.7`
- [ ] 69. Blacklist für False Positives: `data/asin_blacklist.txt`
- [ ] 70. Whitelist für verifizierte CH-Keyboards: `data/ch_verified_asins.txt`
- [ ] 71. Test: Ranking-Output auf Plausibilität prüfen
- [ ] 72. ✅ CHECKPOINT: `opportunity_score` Feld in allen Arbitrage-Dokumenten

## PHASE 6: Kibana Dashboards (Punkte 73–84)
*Ziel: Visuelle Auswertung für Prof + eigenen Überblick*

- [ ] 73. Kibana Index Pattern: `keepa-deals` + `keepa-arbitrage`
- [ ] 74. Dashboard 1: "Market Overview" — Preise pro ASIN × Domain (Heatmap)
- [ ] 75. Dashboard 2: "Top Arbitrage Opportunities" — sortiert nach Score
- [ ] 76. Dashboard 3: "Switzerland Focus" — CH-spezifische Opportunities
- [ ] 77. Dashboard 4: "Price History" — Zeitreihe pro ASIN + Domain
- [ ] 78. Dashboard 5: "Layout Distribution" — Wieviele QWERTZ/QWERTY/CH im System
- [ ] 79. Saved Search: "CH Opportunities > 20€ margin"
- [ ] 80. Saved Search: "QWERTZ Keyboards unter 60€ auf amazon.it"
- [ ] 81. Kibana Lens: Multi-line chart — gleiche ASIN, alle Domains, Preise über Zeit
- [ ] 82. Data Table: ASIN | Buy-Market | Sell-Market | Margin | Score — exportierbar als CSV
- [ ] 83. Watcher/Alert (wenn Kibana Platinum → sonst: eigener Python-Alert)
- [ ] 84. ✅ CHECKPOINT: Alle 5 Dashboards funktionieren mit echten Daten

## PHASE 7: Scale & ASIN-Pool (Punkte 85–94)
*Ziel: Von 203 auf 1000+ ASINs*

- [ ] 85. Neue Marken hinzufügen: Rapoo, Kensington, Bakker, Periboard
- [ ] 86. CH-spezifische Brands: CSL, Delock (schweizer Fachhändler-Brands)
- [ ] 87. Keepa Sales-Rank Filter in Discovery: Nur ASINs mit rank < 200.000
- [ ] 88. Auto-Discovery über Keepa /product "Similar ASINs" Feld
- [ ] 89. Competitor-ASIN Mining: Aus Keepa `frequentlyBoughtTogether`
- [ ] 90. NL/BE Domains (14/21) hinzufügen als weitere Source-Märkte
- [ ] 91. SE (19) und PL (20) als Günstig-Märkte prüfen
- [ ] 92. Batch-Size anpassen wenn Pool > 500 ASINs: kleinere Batches, mehr Zyklen
- [ ] 93. Quarantine-Liste: ASINs die dauernd Errors geben automatisch raus
- [ ] 94. ✅ CHECKPOINT: 1000+ ASINs in Pool, Scheduler läuft stabil

## PHASE 8: Tests & Docs (Punkte 95–100)
*Ziel: Stabile Basis, Prof-ready*

- [ ] 95. Integration-Test: Komplett-Durchlauf Keepa→ES→Arbitrage→Score in < 60s
- [ ] 96. Chaos-Test: ES ausschalten → Scheduler läuft weiter, Watchdog startet ES neu
- [ ] 97. Token-Test: 0 Tokens → Scheduler wartet, kein Crash
- [ ] 98. FOR_SMLFLG.md aktualisieren: Arbitrage-Engine, CH-Fokus, Scoring
- [ ] 99. Professor-Präsentation: Kibana Screenshot + Architektur-Diagramm + Top-10 Opportunities
- [ ] 100. ✅ FINAL: Live-Demo — ASIN eingeben → Arbitrage-Opportunity in < 5s sehen

---

## Implementierungs-Reihenfolge (MCP)
1. **Gemini**: Research CH-Layout ASINs, NL/PL/SE Domain IDs
2. **OpenCode**: Phase 1 (Foundation Fix) — kritischste Änderungen zuerst
3. **Test**: Basis-System läuft noch
4. **OpenCode**: Phase 2+3 (Layout Detection + Arbitrage Engine)
5. **Test**: Arbitrage-Dokumente in ES vorhanden
6. **OpenCode**: Phase 5 (Ranking)
7. **Test**: Score plausibel
8. **OpenCode**: Phase 6 (Kibana Index Pattern automatisch)

---
*Stand: 19. Februar 2026 — Phase 1 beginnt jetzt*
