# SII Energy Measurement Analytics Platform — CLAUDE.md

## Project Purpose

Cloud-based data ingestion and analytics system for Italian SII (Sistema Informativo
Integrato) electricity measurement XML files. The system:

- Receives XML/ZIP files from a dedicated Italian server that is directly connected to the DigitalOcean droplet — no VPN or WebDAV required
- Parses multiple SII-standard XML flow types dynamically (data-driven, never hardcoded)
- Stores structured data in PostgreSQL (one schema per account/client)
- Serves data via FastAPI REST API
- Visualizes via React dashboard

**12 client accounts** (e.g. BAT, Dinamo Trade, CH4, etc.) — data must never be mixed.
Each account has its own PostgreSQL schema. Password rotation every 3 months.

---

## Stack

- **Backend**: Python 3.14, FastAPI, SQLAlchemy (async) ≥2.0.37, Alembic, Pydantic v2
- **Frontend**: React 18, TypeScript, Vite, Recharts, TanStack Query, Tailwind CSS
- **Database**: PostgreSQL 16 (local Docker on DigitalOcean droplet), one schema per account
- **Infrastructure**: DigitalOcean Droplet (4 vCPU / 8 GB RAM / 160 GB SSD) at `104.248.32.23`; Italian server pushes/syncs XML files directly to the droplet — no VPN needed
- **Scheduler**: APScheduler — nightly at 02:00 UTC, plus manual trigger via API
- **Ingestion**: Reads XML/ZIP files from a local directory on the droplet populated by the Italian server
- **CI/CD**: GitHub Actions — push to `staging` → deploys staging stack (port 8080); push to `main` → deploys production. See `.github/workflows/deploy.yml`.

---

## Project Structure

```
backend/
  ingestion/        # file_walker.py — walks local XML/ZIP files synced from Italian server
  parser/           # filename_parser, shape_detector, curve_parser, totalizer_parser, router
  models/           # SQLAlchemy ORM: measurements, files, corrections, pod_metadata
  db/               # session.py (async, schema-scoped), upsert.py
  core/             # config.py (pydantic-settings)
  tests/            # pytest test suite

frontend/           # (Milestone 3 — not yet built)

database/
  migrations/       # Alembic migration files (not yet active on Windows dev machine)

data/               # Local XML files (one folder per account)
  BAT/
    2G_<PIVAdist>_<PIVAutente>/   # meter-type subfolder
      <YYYY>/                     # year subfolder
        <MMDD>/                   # day subfolder
          *.xml.zip               # compressed XML files

reports/            # Generated HTML client confirmation reports (report.py)

report.py           # Standalone: connects to DB, outputs reports/<account>.html
```

---

## Key Commands

```bash
# Backend — install and run (local dev)
pip install -r requirements.txt
uvicorn backend.api.main:app --reload --port 8000

# Database — create tables (Alembic not yet configured for Windows async; use this instead)
py -c "import asyncio; from backend.models.base import Base; from backend.db.session import engine; asyncio.run(Base.metadata.create_all(engine.sync_engine))"

# Manual ingestion trigger (also runs nightly at 02:00)
py -m backend.ingestion.ingest --account=BAT
py -m backend.ingestion.ingest --all

# Client data confirmation report
py report.py --account=BAT        # generates reports/report_bat.html

# Run tests
pytest backend/tests/ -v

# Docker — full stack (local)
docker-compose up --build

# ── Deploy ────────────────────────────────────────────────────────────────────
# All deploys are triggered by git push — GitHub Actions handles the rest.

# Deploy to staging (test at http://104.248.32.23:8080/)
git checkout staging
git push origin staging

# Promote to production (live at https://forecast.dinamoservice.it/)
git checkout main
git merge staging
git push origin main

# Check deploy status
# → https://github.com/STG-707/cloudbased-xml/actions
```

> **Windows note:** Use `py` not `python`. psycopg requires `WindowsSelectorEventLoopPolicy`
> (already set in `session.py` and `ingest.py`). Do NOT use asyncpg — it requires C++ build
> tools that aren't available on this machine.

---

## XML File Types — SII Standard (v2.3, May 2025)

### File Naming Convention

```
<PIVAdistributor>_<PIVAutente>_<AAAAMM>_<CodFlusso>_<Timestamp>_<Progressivo><CodiceDP>__<SM>.xml
```

Example: `01234567890_12345678901_201301_PDO2G_20130218060523_1DP0001_R.xml`

- `AAAAMM` → reference month/year (e.g. `201301` = January 2013)
- `Timestamp` → file generation datetime, used for deduplication
- `Progressivo` → version sequence number, used for deduplication
- `SM` → `R` (a regime / standard) or `NR` (non a regime / transitional)

### Flow Code Classification

**Flusso 1 — Periodic measurements:**
`PDO`, `PDO2G`, `PNO`, `PNO2G`, `VNO`, `VNO2G`, `SNM`, `SNM2G`,
`EIN`, `EIN2G`, `SM`, `SM2G`, `RT`, `RT2G`, `DS`, `DS2G`,
`AV`, `AV2G`, `VP`, `VP2G`, `INT`

**Flusso 2 — Corrections (rettifiche):**
`RFO`, `RFO2G`, `RNO`, `RNO2G`, `RSN`, `RSN2G`, `RNV`, `RNV2G`,
`RIN`, `RIN2G`, `SMR`, `SMR2G`, `RTR`, `RTR2G`, `DSR`, `DSR2G`,
`AVR`, `AVR2G`, `VPR`, `VPR2G`, `INTR`

**Separate (different tag structure):**
`F2G` → goes to `pod_metadata` table, contains dispatching point (CodContrDisp)

---

## Two Data Shapes — CRITICAL

After reading real sample files, there are two fundamentally different XML structures:

### Shape 1 — Curve files (quarter-hourly time series)

Files: `PDO`, `PDO2G`, `PNO2G_R`, `VNO2G`, `RFO2G`, and all Flusso 2 corrections

These contain `<Ea>` elements with 96 attributes E1–E96, where the element's **text
content is the day number** of the month:

```xml
<Ea E1="1,740" E2="2,460" ... E96="2,070">01</Ea>
<Ea E1="1,680" E2="1,590" ... E96="1,920">02</Ea>
```

One `<Ea>` per day. A monthly PDO file has 28–31 `<Ea>` elements.
The actual date = day number + `MeseAnno` (e.g. day `01` + `01/2013` = `2013-01-01`).

**Target table: `measurements`**

### Shape 2 — Totalizer files (band totals, no curves)

Files: `PNO`, `PNO2G_NR`, `SNM2G`, `SNM`

No `<Ea>` element at all. Instead, flat energy-by-tariff-band tags:

```xml
<EaF1>30,000</EaF1>
<EaF2>15,000</EaF2>
<EaF3>24,998</EaF3>
<ErF1>0,785</ErF1>
<PotF1>200,000</PotF1>
```

Date comes from `<DataMisura>DD/MM/YYYY</DataMisura>`.

**Target table: `measurements_totalizer`**

---

## Data Classification Rules — CRITICAL

### Rule A — Primary measurements (quarter-hourly curves)

**Condition:** `<TipoDato>E</TipoDato>` AND `<Ea>` element present with 96 attributes

→ Insert into `measurements` table

### Rule B — Secondary/estimated measurements

**Condition:** `<TipoDato>S</TipoDato>` AND `<Ea>` element present with 96 attributes

→ Insert into `measurements_secondary` table
→ Used as fallback only when no `E` record exists for that POD+date+period

### Rule C — Totalizer measurements (no curves)

**Condition:** No `<Ea>` element present (regardless of TipoDato)

→ Insert into `measurements_totalizer` table

### Query Rule

```sql
-- Always prefer E data; fall back to S only when E is absent
IF EXISTS (SELECT 1 FROM measurements WHERE pod=? AND data_misura=? AND tipo_dato='E')
  → use measurements
ELSE
  → use measurements_secondary
```

### TipoDato values (from XSD)

- `E` → Effective/real (measured, validated) — primary source
- `S` → Estimated (distributor estimate, validated) — fallback
- `A` → Self-read (autolettura) — treat same as `E` if `Validato='S'`

---

## Italian Decimal Format — CRITICAL

All numeric values use **comma as decimal separator**: `1,740` means `1.740` kWh.

The parser must replace `,` with `.` before converting to float. This applies to
ALL numeric fields: Ea values, EaF1–F6, ErF1–F6, PotF1–F6, PotMax, Ka, Kr, Kp.

---

## DST (Daylight Saving Time) Handling

Do NOT reject files with fewer or more than 96 Ea values per day:

- **Spring forward** (ora solare → legale): `Dst=1`, E9–E12 are NULL → 92 valid values
- **Fall back** (ora legale → solare): Two `<Ea>` elements for same period:
  - `Dst=2`: first half, E1–E12
  - `Dst=3`: second half, E9–E96

Store `Dst` attribute per measurement row. Validate 96 periods only for `Dst=0` days.

---

## Deduplication Logic — CRITICAL

**Unique key per measurement:** `(account_id, pod, data_misura, periodo, tipo_dato)`

**Priority on conflict:**
1. Latest `file_timestamp` (from filename) wins
2. If timestamps equal → highest `progressivo` (from filename) wins

**PostgreSQL upsert pattern:**

```sql
INSERT INTO measurements (account_id, pod, data_misura, periodo, tipo_dato, ea_kwh, ...)
VALUES (...)
ON CONFLICT (account_id, pod, data_misura, periodo, tipo_dato)
DO UPDATE SET
  ea_kwh        = EXCLUDED.ea_kwh,
  er_kvarh      = EXCLUDED.er_kvarh,
  file_timestamp = EXCLUDED.file_timestamp,
  progressivo   = EXCLUDED.progressivo,
  source_file   = EXCLUDED.source_file,
  cod_flusso    = EXCLUDED.cod_flusso
WHERE
  EXCLUDED.file_timestamp > measurements.file_timestamp
  OR (EXCLUDED.file_timestamp = measurements.file_timestamp
      AND EXCLUDED.progressivo > measurements.progressivo);
```

Flusso 2 correction files (RFO, RNO, etc.) upsert into the same table — they are
not stored separately. Motivazione=3 (annullamento) deletes the record.

---

## Database Schema

**One PostgreSQL database, one schema per account.**
Schema name = account identifier (e.g. `bat`, `dinamo_trade`, `ch4`).

### `files` — ingestion log

```sql
file_id           SERIAL PRIMARY KEY
file_name         TEXT NOT NULL UNIQUE
account_id        TEXT NOT NULL
cod_flusso        TEXT                    -- PDO2G, RFO, SNM2G, etc.
piva_distributore TEXT
piva_utente       TEXT
mese_anno         TEXT                    -- MM/YYYY from filename AAAAMM
file_timestamp    TIMESTAMP               -- from filename
progressivo       INTEGER                 -- from filename
sm_status         TEXT                    -- R or NR
processed_at      TIMESTAMP DEFAULT now()
status            TEXT                    -- ok / rejected / duplicate / error
error_message     TEXT
```

### `measurements` — quarter-hourly curves (Rule A, TipoDato=E)

```sql
id                BIGSERIAL PRIMARY KEY
account_id        TEXT NOT NULL
pod               TEXT NOT NULL
data_misura       DATE NOT NULL           -- full date: day from Ea + MeseAnno
periodo           SMALLINT NOT NULL       -- 1 to 96
ea_kwh            NUMERIC(10,3)           -- active energy kWh (Italian comma converted)
er_kvarh          NUMERIC(10,3)           -- reactive energy kVarh
dst               SMALLINT DEFAULT 0     -- 0=normal, 1=spring, 2=fall part1, 3=fall part2
tipo_dato         CHAR(1) NOT NULL        -- E, S, A
raccolta          CHAR(1)                 -- P=periodic, S=switch, V=voltura, T=technical
validato          CHAR(1)                 -- S=valid, N=not valid
tensione          INTEGER                 -- voltage V
trattamento       CHAR(1)                 -- O=hourly, F=band, M=monorario
pot_max           NUMERIC(10,3)
causa_ostativa    BOOLEAN
cod_flusso        TEXT
mese_anno         TEXT
file_timestamp    TIMESTAMP
progressivo       INTEGER
source_file       TEXT
UNIQUE (account_id, pod, data_misura, periodo, tipo_dato)
```

### `measurements_secondary` — estimated curves (Rule B, TipoDato=S)

Same structure as `measurements`. Used as fallback.

### `measurements_totalizer` — band totals (Rule C, no Ea curves)

```sql
id                BIGSERIAL PRIMARY KEY
account_id        TEXT NOT NULL
pod               TEXT NOT NULL
data_misura       DATE                    -- from DataMisura
data_prest        DATE                    -- switching/voltura date if present
mese_anno         TEXT
tipo_dato         CHAR(1)
raccolta          CHAR(1)
validato          CHAR(1)
tensione          INTEGER
trattamento       CHAR(1)
pot_max           NUMERIC(10,3)
ea_f1             NUMERIC(10,3)           -- active energy band F1 kWh
ea_f2             NUMERIC(10,3)
ea_f3             NUMERIC(10,3)
ea_f4             NUMERIC(10,3)
ea_f5             NUMERIC(10,3)
ea_f6             NUMERIC(10,3)
ea_m              NUMERIC(10,3)           -- monorario total
er_f1             NUMERIC(10,3)
er_f2             NUMERIC(10,3)
er_f3             NUMERIC(10,3)
pot_f1            NUMERIC(10,3)
pot_f2            NUMERIC(10,3)
pot_f3            NUMERIC(10,3)
tipo_rettifica    CHAR(1)                 -- present in Flusso 2 files
motivazione       SMALLINT                -- 1–6, correction reason
data_rilevazione  DATE
cod_flusso        TEXT
file_timestamp    TIMESTAMP
progressivo       INTEGER
source_file       TEXT
```

### `corrections` — Flusso 2 audit log

```sql
id                BIGSERIAL PRIMARY KEY
account_id        TEXT NOT NULL
pod               TEXT NOT NULL
mese_anno         TEXT
data_misura       DATE
tipo_rettifica    CHAR(1)
motivazione       SMALLINT                -- 1=replaces estimate, 2=replaces error,
                                          -- 3=cancel/annul, 4=fraud, 5=meter fault,
                                          -- 6=incoherent estimate
data_rilevazione  DATE
cod_flusso        TEXT
source_file       TEXT
processed_at      TIMESTAMP DEFAULT now()
```

### `pod_metadata` — F2G dispatching point lookup

```sql
id                BIGSERIAL PRIMARY KEY
account_id        TEXT NOT NULL
pod               TEXT NOT NULL
codice_dp         TEXT                    -- dispatching contract code
tensione          INTEGER
trattamento       CHAR(1)
valid_from        DATE
valid_to          DATE
source_file       TEXT
UNIQUE (account_id, pod, valid_from)
```

---

## API Endpoints

```
GET  /accounts                                    # list all accounts
GET  /pods?account=BAT                            # list PODs for account
GET  /measurements?account=BAT&pod=IT123E...&date=2013-01-01
GET  /measurements/month?account=BAT&pod=IT123E...&mese_anno=01/2013
GET  /aggregation/daily?account=BAT&pod=IT123E...&mese_anno=01/2013
GET  /aggregation/monthly?account=BAT&pod=IT123E...&year=2013
GET  /totals?account=BAT&pod=IT123E...&mese_anno=01/2013
POST /sync                                        # trigger manual ingestion
POST /sync/{account}                              # trigger for one account
GET  /sync/status                                 # last sync results
GET  /files?account=BAT&status=rejected           # file processing log
```

---

## Aggregation Logic

**Daily aggregation** (per POD per day): sum of all 96 `ea_kwh` periods.
Query rule: use `measurements` (TipoDato=E) if present; else `measurements_secondary`.

**Monthly aggregation**: sum of all daily totals for the month.

**Dispatching point join**: join `measurements` with `pod_metadata` on
`(account_id, pod)` to filter by `codice_dp` from F2G.

```sql
-- Example: daily sum for a POD, preferring E over S
SELECT
  m.pod,
  m.data_misura,
  SUM(m.ea_kwh) AS daily_kwh
FROM measurements m
WHERE m.account_id = :account
  AND m.pod = :pod
  AND m.mese_anno = :mese_anno
  AND m.tipo_dato = 'E'
GROUP BY m.pod, m.data_misura
ORDER BY m.data_misura;
```

---

## Ingestion Pipeline

XML/ZIP files are delivered to the DigitalOcean droplet by the Italian server (direct
connection — no VPN, no WebDAV). Files are **transient** — once successfully ingested,
the source ZIP is deleted to keep disk usage stable. Only the parsed DB records are
kept permanently.

```
1. Sync — Italian server pushes XML/ZIP files to /opt/sii/data/<account>/
2. Parse — read ZIP bytes in-memory (no extraction to disk); route to correct parser
3. Validate — shape detection, DST handling, Italian decimal conversion
4. Mark processed — upsert into measurements/totalizer/pod_metadata; log status='ok' in files table
5. Delete ZIP — source file deleted after confirmed DB commit; errors keep ZIP for retry
6. Log corrections in `corrections` table for Flusso 2 files
```

**Key implementation details:**
- ZIPs are read entirely in-memory via `zipfile.ZipFile.read()` + `ET.fromstring(bytes)`
- `_load_processed_names()` pre-loads all `status='ok'` filenames in one query per account
  (avoids 1 SELECT per file); already-processed files are deleted without re-parsing
- 5 files processed concurrently (asyncio.Semaphore); chunks of 100 to bound memory
- Errored files (status='error') are NOT deleted — retried on every subsequent run
- upsert uses `ON CONFLICT index_elements` (not named constraint) to avoid schema-prefix issues
- Batch rows deduplicated before INSERT to prevent CardinalityViolation
- Batches chunked at 3400 rows (3400 × 19 cols < 65535 param limit)

**Scheduling:**
- Nightly: APScheduler fires at 02:00 UTC — `ingest --all`
- Manual: `POST /sync` or `POST /sync/{account}` via API / Sync page in UI
- Historical backfill: `backfill_all.py` runs on server (`nohup python3 /opt/sii/backfill_all.py &`)
- Cron (`sync_sii.sh`): rsyncs from Italian server then calls `POST /api/sync/{account}`; if API returns 409 (another sync running) it **skips** that account rather than falling back to docker exec (prevents concurrent ingest)

---

## Code Conventions

**Python:**
- Type hints on all functions and class attributes
- Pydantic v2 models for all API request/response schemas
- Async SQLAlchemy sessions — never use synchronous DB calls
- All DB access through ORM models, never raw SQL strings with f-strings
- All secrets in `.env` via `pydantic-settings` — never hardcoded anywhere
- Never log credentials or secrets, even at DEBUG level
- Every rejected/incomplete file must be logged in `files` table — never silently discard
- Parser must never hardcode flow type names — detect from XML attributes and tag presence

**Database:**
- All schema changes through Alembic migrations — never raw `ALTER TABLE`
- Add indexes on `(account_id, pod, data_misura)` and `(account_id, mese_anno)`
- Dedup queries use `ON CONFLICT DO UPDATE` — never application-level loops
- Always specify schema in queries: `SET search_path TO bat, public`

**Testing (pytest):**
- Every parser function has a test using a real sample XML file as fixture
- Required test cases for validator:
  - Valid file: exactly 96 Ea attributes, TipoDato=E → accepted
  - 95 attributes, Dst=0 → rejected and logged
  - TipoDato=S, 96 attributes → goes to secondary table
  - DST spring-forward day (Dst=1, 92 values) → accepted
  - Italian decimal `1,740` → parsed as float `1.740`
  - Duplicate file lower progressivo → existing record preserved
  - Duplicate file higher progressivo → existing record replaced
  - Motivazione=3 (annullamento) → record deleted

---

## Environment Variables

```env
# Database — local PostgreSQL on DigitalOcean (Docker container named "db")
# Production: db is the Docker Compose service name
DATABASE_URL=postgresql+psycopg://sii:sii_db_2024@db:5432/sii
# Local dev (SSH tunnel or port-forward): postgresql+psycopg://sii:sii_db_2024@localhost:5433/sii

# Data directory — where the Italian server deposits XML/ZIP files
# Each account has a subfolder: DATA_DIR/BAT/, DATA_DIR/CH4/, etc.
DATA_DIR=/opt/sii/data

# App
SECRET_KEY=...
ENVIRONMENT=production
LOG_LEVEL=INFO

# Monitoring (optional — only needed when docker-compose.monitoring.yml is deployed)
GRAFANA_PASSWORD=change_me_in_production
```

---

## Multi-Account Architecture

Each account is an isolated PostgreSQL schema:

```sql
-- Create schema for new account
CREATE SCHEMA IF NOT EXISTS bat;
SET search_path TO bat;
-- Then run all table migrations inside this schema
```

Account-to-schema mapping is stored in a `public.accounts` table:

```sql
CREATE TABLE public.accounts (
  account_id    TEXT PRIMARY KEY,
  schema_name   TEXT NOT NULL,
  display_name  TEXT,
  active        BOOLEAN DEFAULT true,
  created_at    TIMESTAMP DEFAULT now()
);
```

---

## Milestones

**Milestone 1** — Ingestion + parsing + DB setup ✅
- [x] XML parser (both shapes: curve and totalizer) — `backend/parser/`
- [x] Italian decimal converter — `parse_italian_float()` in curve/totalizer parsers
- [x] DST handling — Dst attribute read and stored per measurement
- [x] Flusso 2 corrections + annullamento — `backend/db/upsert.py`
- [x] Deduplication upsert (file_timestamp + progressivo priority) — `upsert.py`
- [x] File logging — `files` table, every file logged with status
- [x] DB models — `measurements`, `measurements_secondary`, `measurements_totalizer`,
      `corrections`, `pod_metadata`, `files`
- [x] PostgreSQL connection — local Docker on DigitalOcean, psycopg driver
- [x] Client confirmation report — `report.py` → `reports/<account>.html`
- [x] F2G parser (`pod_metadata` table)
- [x] Alembic migrations configured
- [x] pytest test suite (parser, auth, security, performance, health, ingestion lock, smoke)

**Milestone 2** — APIs + scheduler + data pipeline ✅
- [x] FastAPI endpoints (all routes in API Endpoints section)
- [x] Aggregation engine (daily + monthly rollup)
- [x] Nightly scheduler (APScheduler at 02:00 UTC)
- [x] Ingestion concurrency guard (409 on double-trigger) — `backend/ingestion/lock.py`
- [x] Italian server direct connection — XML files delivered to local `data/` directory
      (no Nextcloud, no VPN — replaced by direct server-to-server link)
- [ ] Full historical backfill for all 12 accounts (BAT currently has data to 03/2025)

**Milestone 3** — Dashboard + deployment ✅
- [x] React dashboard (POD filter, date filter, chart, export CSV/Excel)
- [x] Forecast engine — generate monthly forecasts with loss rules + dispatching weights
- [x] Excel exports — by dispatching point, per-POD (96 periods), source measurements
- [x] Manual sync trigger in UI (Sync page)
- [x] Docker setup + DigitalOcean Droplet deployment
- [x] Nginx reverse proxy (HTTPS, rate limiting, security headers)
- [x] Prometheus + Grafana monitoring stack (`docker-compose.monitoring.yml`)
- [x] API hot-standby replica (`api2` at 172.20.0.20, nginx `backup` upstream)
- [x] GitHub Actions CI/CD — push to `staging` or `main` auto-deploys
- [x] Staging environment (port 8080, `sii_staging` DB, `staging-api` container)

**Pending**
- [ ] Historical data backfill — pipe remaining accounts' XML archives through ingestion
- [ ] Add GitHub Secrets (`DEPLOY_HOST`, `DEPLOY_SSH_KEY`) to enable first CI/CD run
- [ ] Create `/opt/sii/.env.staging` on server (copy from `.env.staging.example`)

---

## XML Tag Paths — CRITICAL (verified against real BAT files)

Fields are NOT flat children of `<DatiPod>`. Actual structure:

```
<DatiPod>
  <Pod>IT001E...</Pod>
  <DatiPdp>
    <Trattamento>O</Trattamento>
    <Tensione>230</Tensione>
  </DatiPdp>
  <Misura>
    <TipoDato>E</TipoDato>      ← optional in Flusso 2 files
    <Raccolta>P</Raccolta>
    <Validato>S</Validato>
    <PotMax>6,000</PotMax>
    <CausaOstativa>NO</CausaOstativa>   ← string "SI"/"NO", convert to bool
    <Ea E1="1,740" ... E96="2,070">01</Ea>
    ...
  </Misura>
</DatiPod>
```

- `TipoDato`, `Raccolta`, `Validato`, `PotMax`, `CausaOstativa`, `Ea` → inside `<Misura>`
- `Trattamento`, `Tensione` → inside `<DatiPdp>`
- `TipoDato` is **optional** — absent in Flusso 2 correction files

---

## Known Edge Cases

- **SM status optional:** Older files (pre-2022) have no `_R`/`_NR` suffix in the filename.
  The regex must treat SM as optional; default to `None` when absent.
- **Motivazione=3 (annullamento):** Flusso 2 with this code means DELETE the record,
  not update it. The `<Misura>` section is absent in this case.
- **PNO2G NR vs R:** Same CodFlusso, different SM flag in filename. NR files have
  no `<Ea>` curves even though they are 2G meters. Check SM field, not just CodFlusso.
- **Multiple PODs per file:** The spec allows one file to contain multiple `<DatiPod>`
  blocks. The parser must loop over all of them.
- **Max file size:** 25 MB uncompressed per spec — ZIP files may contain multiple XMLs.
- **Switching files (SNM, SNM2G):** `DataMisura` = day before switching,
  `DataPrest` = switching activation date. Both must be stored.
- **VNO2G:** Has both `<Ea>` curves AND `<EaF1-4>` totalizers. Store curves in
  `measurements`, totalizer values in `measurements_totalizer`.
- **F2G files:** Completely different tag structure from all other files.
  Route by CodFlusso check before any other parsing.
- **Flow types found in real BAT data (25 unique):** DS2G, F2G, PDO, PDO2G, PNO, PNO2G,
  RFO, RFO2G, RNO, RNO2G, RNV, RSN, RSN2G, RT2G, S2G, SM2G, SMIS, SNF, SNM, SNM2G,
  SOF, SOS, VNO, VNO2G, VP2G — some (SMIS, SNF, SOF, S2G) are not in the spec but appear
  in real files and parse correctly as curve or totalizer via shape detection.

## Key Fixes & Architectural Decisions

### Forecast route — session/search_path isolation (`backend/api/routes/forecast.py`)

After `session.commit()`, SQLAlchemy 2.0 releases the connection back to the pool. Pool connections don't inherit `SET search_path TO schema, public` that was issued on the previous checkout. If a single session is used for both reads and chunk writes (with mid-loop commits), INSERT statements after the first commit land on `public.forecast_periods` (which lacks `ea_kwh`) rather than the account schema's table.

Fix: three separate session contexts per forecast job — (1) isolated delete session, (2) long-lived read session kept open for the entire generator with no commits, (3) a fresh write session per chunk so `SET search_path` is re-executed on every insert.

The forecast logic lives in `_run_forecast_job()` (module-level) and is launched via `start_forecast_job(account_id, mese_anno)`, which both the `/generate` endpoint and the ANAGRAFICA upload endpoint call.

### Dispatching weights — global fallback (`backend/forecast/engine.py`)

The old combined `WHERE account_id = :acct OR account_id IS NULL` query was fragile: account-specific rows could suppress global ones depending on sort order. Fix: explicit two-step query — step 1 fetches account-specific weights, step 2 fetches global (`account_id IS NULL`) fallback only for puntos not covered in step 1. Global weights entered in "All accounts" mode now reliably apply to all accounts that don't have account-specific overrides.

### Auto-forecast after ANAGRAFICA upload (`backend/api/routes/admin.py`)

`POST /admin/anagrafica/upload` now automatically calls `start_forecast_job(account_id, mese_anno)` after a successful upsert and returns `forecast_job_id` in the response. The frontend shows the job ID in the upload success message. No separate manual forecast trigger is needed after uploading ANAGRAFICA.

### Sync tab vs admin uploads

The Sync tab (`/sync/status`) tracks XML file ingestion runs (nightly scheduler at 02:00 UTC + manual `POST /sync`). Admin uploads (ANAGRAFICA, loss config, dispatching weights) are configuration operations — they do not appear in the Sync tab. The Sync tab is empty until at least one ingestion sync runs.

### API failover — health endpoint returns 503 on DB failure (`backend/api/main.py`)

`/api/health` previously always returned HTTP 200 even when the DB was unreachable (body said `"status":"degraded"` but HTTP code stayed 200). The Docker healthcheck uses `urllib.request.urlopen` which only fails on non-2xx codes, so a DB outage never marked the container unhealthy and nginx never promoted `api2`. Fix: health now returns `JSONResponse(status_code=503, ...)` when `db_status != "ok"`. Failover chain: DB down → 503 → Docker marks `sii-api-1` unhealthy → nginx routes to `api2` (172.20.0.20, 2.5 GB / 2 CPU).

### Backfill stale lock PID check (`backend/ingestion/lock.py`)

If `backfill_all.py` is killed (SIGKILL, OOM, server crash), `.backfill_status.json` is left with `"running": true` permanently, blocking all subsequent syncs with 409 forever. Fix: `backfill_active()` now reads `"pid"` from the status file and calls `os.kill(pid, 0)` to check liveness. If the process is dead, the lock is treated as stale and `False` is returned. `backfill_all.py` writes its own PID into the status file on every `write_status()` call.

### Sync visibility — cron uses API trigger (`server_scripts/sync_sii.sh`)

Originally `sync_sii.sh` called `docker exec sii-api-1 python -m backend.ingestion.ingest` directly, bypassing the API's `IngestionGuard`. This meant syncs were invisible in the Sync tab and multiple cron instances could run concurrently. Fix: `sync_sii.sh` now calls `POST /api/sync/{account}`, polls `/api/sync/status` until done, and falls back to `docker exec` only when the API itself is unreachable (5xx/timeout). HTTP 409 (lock held) skips the account silently — it will be retried on the next cron run.

### Concurrent cron guard (`server_scripts/sync_sii.sh`)

Multiple cron slots (02:30, 04:30, …) could spawn overlapping `sync_sii.sh` processes, each triggering its own ingest runs and saturating the DB. Fix: a PID-based lock file at `/var/run/sync_sii.lock` — new instances exit immediately if a previous one is still alive.

### Coverage cache invalidation (`backend/api/routes/sync.py`)

`_coverage_cache` had a 60-second TTL but was never explicitly invalidated after a sync completed. The UI showed stale coverage data after every sync. Fix: added `_coverage_cache["expires"] = 0.0` in the `finally` block of `_run_ingest()` so the next coverage request always fetches fresh data.

### CI/CD deployment architecture

All production and staging deploys flow through GitHub Actions (`.github/workflows/deploy.yml`). The server no longer has files edited directly — `git reset --hard origin/<branch>` on the server ensures the working tree always matches the committed state. Deploy key at `/root/.ssh/deploy_key` (ed25519) is in GitHub Secrets as `DEPLOY_SSH_KEY`. The server's git state was previously diverged (direct edits); it has been reset to track `origin/main`.

**Staging environment:**
- `staging-api` container at `172.20.0.30`, 1 GB / 1 CPU
- Database: `sii_staging` (separate PostgreSQL database, same instance)
- nginx: port 8080 HTTP server block → `http://104.248.32.23:8080/`
- Config: `/opt/sii/.env.staging` (never committed)
- `docker-compose.staging.yml` overlay brings up staging-api alongside production stack

---

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
