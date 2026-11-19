# Air Quality Archive Explorer

Browse historical air-quality measurements from the **OpenAQ open-data archive**, station
by station, with each station's actual data coverage shown up front. Historical data,
honestly labeled: this tool never claims live or current conditions - every station
surface shows the exact months the archive holds for it, staleness badges mark how old
the most recent archived month is, and data-quality warning signs are flagged instead of
hidden.

<img width="1280" alt="Station detail view: one month of daily PM2.5 at Karve Road Pune with the India 24-hour threshold, per-day coverage, and quality flags" src="https://github.com/user-attachments/assets/c83d0ef0-5e42-4a84-a1d6-f5b4ed7d0338">

## What it does

- **Coverage first.** For any station, one archive listing request returns the exact set
  of months with records (e.g. Karve Road Pune: 43 months, 2018-03 through 2025-05, with
  the 2023-24 gap visible). Staleness badges: green (data through last ~2 months), amber
  (≤ 1 year old), red (older).
- **Daily detail on demand.** Pick a station and month: the app reads that month's
  day-files from the archive and shows daily mean/min/max with per-day sampling coverage
  (coverage is cadence-aware: hourly, 30-min and 15-min schedules are each compared
  against their own expected sample count).
- **Exceedance counting against named reference levels.** US EPA 24h PM2.5 (35 µg/m³),
  WHO 2021 24h PM2.5 (15 µg/m³), India NAAQS 24h PM2.5 (60 µg/m³) and PM10 (100 µg/m³),
  US EPA 24h PM10 (150 µg/m³) - each with its source. These are daily screening levels,
  not regulatory determinations (the legal standards have statistical forms, e.g. the US
  level is a 98th percentile over 3 years, that this tool does not compute). Days below
  2/3 sampling coverage are excluded from counting, mirroring the ≥16-of-24-hours
  convention used for 24-hour sub-indices.
- **Quality flags, not silent cleanup.** Days with one constant reading at ≥90% coverage
  (a stuck-sensor sign) and days peaking above 1000 µg/m³ (beyond standard AQI scales,
  likely sensor faults) are flagged amber and called out in the summary - shown as
  archived, never silently dropped. Real example found while building this: a station
  whose archived PM2.5 reads a constant 100.0 µg/m³ for most of a month.
- **Shareable station links.** `#station=<locationId>` opens a station directly,
  `#station=<id>&month=YYYY-MM` also loads a month, e.g.
  `http://localhost:5000/#station=5661&month=2025-03`.

## Why the archive and not the API

The OpenAQ v3 REST API requires an API key (it answers 401 without one). The
[open-data archive on S3](https://openaq-data-archive.s3.amazonaws.com) is part of the
AWS Open Data program and needs no credentials, so this tool - including its station
catalog - is built entirely from keyless archive listings and object reads. The shipped
catalog (`data/catalog.json` plus its listed part file, 1573 unique stations across
141 named cities, harvested 2026-11-19) is a
**sample** of the archive, not a complete directory; re-probe any location id live, or
regenerate a bigger sample with the bootstrap script.

## Measured example (real output, 2026-11-17)

Karve Road Pune (location 5661, provider tag MPCB-3379567), parameter pm25,
month 2025-03, standard India NAAQS 24h PM2.5 (60 µg/m³):

- Archive coverage: **43 months, 2018-03 through 2025-05**
- **31 local days** read from 31 day-files; **29 days** with ≥2/3 sampling coverage
- **12 days above 60 µg/m³** among the valid days; 2 thin days excluded from counting
- **3 suspect days** (constant reading all day) flagged
- 2 days (2025-03-05/06) peaked at 3344.8 µg/m³ - beyond standard scales, flagged as
  likely sensor faults and shown as archived

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py          # http://localhost:5000
```

Tests (no network needed):

```bash
python -m pytest tests/ -q     # 10 tests
```

Regenerate or enlarge the station catalog (reads only the keyless archive):

```bash
python scripts/bootstrap_catalog.py --sample 400 --seed 7
```

## How it works

```
openaq_explorer/
  s3archive.py   keyless S3 listings + day-file reads; coverage in 1 request/location
  aggregate.py   daily stats with cadence-aware coverage; stuck-sensor detection
  standards.py   reference 24h thresholds with named sources
  catalog.py     station metadata harvested from the archive itself
app.py           Flask JSON API + serves ui.html
ui.html          single-page UI (no build step, no JS dependencies)
tests/           unit tests over parsing, aggregation, flags, standards
```

Archive record layout: `records/csv.gz/locationid={id}/year={yyyy}/month={mm}/location-{id}-{yyyymmdd}.csv.gz`,
each a gzipped CSV of measurements with location name, coordinates, parameter, units and
timezone-aware timestamps. Daily stats group by each record's own local date; edge days
at month boundaries can be partial and simply show lower coverage.

## Data attribution and honesty notes

- Source data: [OpenAQ](https://openaq.org) open-data archive (AWS Open Data). Original
  monitoring providers are preserved in each station record (e.g. `MPCB-3379567`).
- This is a historical archive viewer. It does not show live conditions and must not be
  used as a current-air-quality source.
- The reference thresholds are screening levels with named sources; nothing here is a
  regulatory or health determination.
- The catalog is a harvested sample with its harvest date; coverage windows reflect the
  archive at that time and are re-checked live when a station is opened.

## License

MIT - see [LICENSE](LICENSE).
