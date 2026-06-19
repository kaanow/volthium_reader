# Cloud architecture — Railway-hosted telemetry

> Status: **v1 implemented** as of 2026-06-18 — code lives in `cloud/`, tests in `cloud/tests/`.
> Not yet deployed to Railway; instructions are below.

Companion to [`production_design.md`](production_design.md). That doc covers
the on-pack hardware (ESP32 BLE central, display-side node, etc.). This doc
covers what happens *off-pack*: how the reader (Pi today, ESP32 tomorrow)
ships data to a Railway instance, what gets stored, and how it's viewed
remotely.

## Goal

Telemetry from the Barge Inn 24V pack visible from anywhere, stored
indefinitely, without breaking the existing local CSV + local dashboard.
Local stays the offline fallback; cloud is the remote-viewable copy.

## Shape

```
   READER (Pi today, ESP32 later)         RAILWAY
   ┌─────────────────────────┐            ┌──────────────────────────┐
   │ scripts/log.py          │            │ FastAPI ingest service   │
   │  → data/pack.csv  ←── unchanged ──── │   POST /ingest           │
   │  → cloud uploader ──── HTTPS POST ─→ │   bearer auth per source │
   │     batches of rows                  │     ↓                    │
   │     remembers offset                 │   Postgres (Railway     │
   │     in state file                    │     add-on)              │
   └─────────────────────────┘            │     readings table       │
                                          │     derived cols filled │
                                          │     on insert            │
                                          │     ↓                    │
                                          │ Browser dashboard        │
                                          │   port of scripts/       │
                                          │   dashboard.py, reads    │
                                          │   from Postgres          │
                                          │   public URL (no auth)   │
                                          └──────────────────────────┘
```

## Timestamp convention — applies to ALL code in this repo

**Wire format**: ISO-8601 UTC with a trailing `Z`. Example: `2026-05-17T19:13:00Z`.

**Rationale**: ESP32 firmware will NTP-sync to UTC and has no native concept
of local time. Picking UTC + `Z` everywhere on the wire means the Pi sender,
the ESP32 sender, and the server all use the same string format with no tz
math, and the server never has to guess what zone a naive timestamp came from.

Concrete rules:

- **On the wire (uploader → server, including future ESP32 firmware)**:
  ISO-8601 UTC with a `Z` suffix. No offsets, no fractional seconds unless a
  device genuinely has sub-second precision.
- **In Postgres**: store as `TIMESTAMPTZ`. Postgres canonicalizes to UTC
  internally; clients can render in any zone.
- **In the local `data/pack.csv`**: stays as it is today (naive local time).
  This is a quirk of the existing logger; do NOT change it as part of the
  cloud work — the local dashboard already parses it. The uploader is
  responsible for converting `pack.csv`'s naive local time to UTC `Z` before
  POSTing.
- **In cloud dashboard output**: render in the Barge Inn's local time
  (America/Toronto unless changed) for human readability; underlying data
  stays UTC.
- **ESP32 firmware (future)**: stamp readings with UTC from NTP at capture
  time, format as `Z`-suffixed ISO-8601. If NTP is unavailable at boot,
  buffer readings without timestamps and discard them rather than send wrong
  times — a gap is better than a lie.

## Wire protocol

`POST /ingest` with `Authorization: Bearer <token>` and JSON body:

```json
{
  "source_id": "pi-barge",
  "readings": [
    {
      "ts": "2026-05-17T19:13:00Z",
      "state": "discharging",
      "v_a": 13.215, "v_b": 13.217,
      "i_a": -3.2,   "i_b": -3.0,
      "soc_a": 70,   "soc_b": 68,
      "t_a": 23,     "t_b": 23,
      "remaining_ah_a": 158.0, "remaining_ah_b": 142.0,
      "delta_v_a": 0.008,      "delta_v_b": 0.009,
      "name_a": "V-12V200AH-0533",
      "name_b": "V-12V200AH-0667"
    }
    /* ...up to N rows per batch... */
  ]
}
```

Notes:

- Payload contains **only what the reader natively produces from the BMS**.
  Server derives `pack_v`, `pack_i`, `pack_p`, `smoothed_i`, `smoothed_p`,
  `minutes_remaining` — anything that depends on EMA/projection tunables
  belongs on the server so we can tune without re-flashing.
- Server upserts on `(source_id, ts)`. Retries are safe.
- Batch size: target 60 rows per POST (10 minutes at 10 s cadence).
- Names of fields match `pack.csv` columns 1:1 for the raw subset, so the
  uploader is a column-projection of the CSV, not a remapping.

## Source IDs

A short string per **reader device**, not per pack. The Barge Inn pack only
has one pack but may have multiple readers during transitions.

- `pi-barge` — the Pi (or Mac dev rig) running `scripts/log.py`
- `esp32-barge` — the future ESP32-S3 battery-side node

Hardcoded in env / firmware config. The server schema lets these coexist; the
dashboard merges by default but can filter.

## Auth

**Per-device bearer tokens** in `Authorization: Bearer <token>`. One env var
per token on the server (`READER_TOKEN_PI`, `READER_TOKEN_ESP32`), one
matching env var on each device. Adding the ESP32 doesn't require re-keying
the Pi.

Tokens are random 32-byte URL-safe strings, rotated by editing env vars on
both ends. No PKI, no OAuth.

## Dashboard

Public Railway URL, no auth. Read-only. Same chart layout as
`scripts/dashboard.py` (port to a Postgres query).

## Server schema (sketch)

```sql
CREATE TABLE readings (
  source_id      TEXT        NOT NULL,
  ts             TIMESTAMPTZ NOT NULL,
  -- raw, from wire
  state          TEXT,
  v_a            REAL, v_b REAL,
  i_a            REAL, i_b REAL,
  soc_a          INT,  soc_b INT,
  t_a            INT,  t_b INT,
  remaining_ah_a REAL, remaining_ah_b REAL,
  delta_v_a      REAL, delta_v_b REAL,
  name_a         TEXT, name_b TEXT,
  -- derived, filled at insert time by the ingest service
  pack_v             REAL,
  pack_i             REAL,
  pack_p             REAL,
  smoothed_i         REAL,
  smoothed_p         REAL,
  minutes_remaining  REAL,
  PRIMARY KEY (source_id, ts)
);
```

Storage estimate at 10 s cadence: ~3M rows/yr per source, ~500 MB/yr with
indexes. Plain Postgres handles this without partitioning for years. If
queries get slow add a `readings_1m` rollup table later — don't pre-optimize.

## Out of scope (deliberately)

- Multiple packs / multiple sites — single pack is enough; if the Barge Inn
  ever splits we add a `pack_id` column then.
- MQTT / WebSockets — no benefit at 10 s cadence; HTTPS POST is simpler and
  ESP32-native.
- mTLS — per-device bearer is plenty given the threat model (one residential
  Wi-Fi, one residential cabin).
- Server-side EMA replays / backfills — derive on insert; if tunables change
  we re-derive in place with a one-off SQL update.
- Server-side hybrid-Ah anchor mode (the `use_remaining_ah_anchor=True` path
  in `volthium/estimator.py`) — needs per-source persistent state beyond
  smoothed_i/p. Skipped for v1 because the local CSV still has it and the
  cloud dashboard doesn't show displayed_ah yet.

---

# Implementation — what was built, where it lives, how to deploy

## Repo layout

```
cloud/
  shared/wire.py            ← Pydantic models for the wire (the contract)
  server/
    main.py                 ← FastAPI app: /ingest, /api/*, /healthz, /
    config.py               ← env-var config
    derive.py               ← server-side EMA + projection (mirrors estimator.py)
    db.py                   ← asyncpg-backed ReadingsDAO + Protocol
    migrations/0001_readings.sql
    static/index.html       ← dashboard (vanilla HTML/JS/SVG, no build)
    Dockerfile              ← multi-stage slim image
    railway.json            ← Dockerfile builder + /healthz healthcheck
    requirements.txt        ← fastapi, uvicorn, asyncpg, pydantic
  uploader/uploader.py      ← Pi-side: tails pack.csv, posts batches
  tests/                    ← 36 unit tests; no Postgres needed
```

Edge changes (also part of v1):

- `scripts/log.py` — added `problem_code_a/b` and `cell_a_1..4`, `cell_b_1..4`
  columns; auto-archives old CSV on schema drift to `pack.csv.vN-HHMM`.
- `scripts/dashboard.py` — `CSV_HEADER_FALLBACK` updated to match.
- `tests/test_log_schema.py` — 7 new tests pinning the new columns + the
  archive behavior.

## Env vars

| Var                          | Default          | Purpose                                        |
| ---------------------------- | ---------------- | ---------------------------------------------- |
| `DATABASE_URL`               | (required)       | Postgres URL. Railway's add-on injects this.   |
| `READER_TOKEN_PI_BARGE`      | (required)       | Bearer token authorizing `source_id=pi-barge`. |
| `READER_TOKEN_ESP32_BARGE`   | (later)          | Same, for the future ESP32 reader.             |
| `EMA_ALPHA`                  | `0.15`           | Smoothing factor — matches `estimator.py`.     |
| `CAPACITY_AH`                | `200.0`          | Per battery, for projection.                   |
| `FLOOR_PCT`                  | `10.0`           | "Empty" floor SOC.                             |
| `CEILING_PCT`                | `95.0`           | "Full" target SOC (LiFePO4 absorption-onset).  |
| `IDLE_CURRENT_A`             | `0.5`            | |I| below this → state=idle, no projection.    |
| `DISPLAY_TZ`                 | `America/Toronto`| Dashboard rendering tz (cosmetic only).        |
| `DB_MIGRATE`                 | `1`              | If truthy, runs migrations/*.sql on boot.      |

Token-naming rule: env var `READER_TOKEN_<UPPER_SNAKE>` authorizes
`source_id=<lower-kebab>`. So `READER_TOKEN_PI_BARGE=...` ↔ `pi-barge`.

## Railway deploy steps

1. **Push the repo to a GitHub remote** Railway can read. (Right now the
   software-side clone is in `volthium_sw/volthium_reader/` and points at
   `git@github.com:kaanow/volthium_reader.git`. If a new remote is wanted to
   keep cloud history separate, create one and add it.)

2. **Create a Railway project**, then:
   - Add a **PostgreSQL** plugin. Railway auto-injects `DATABASE_URL`.
   - Add a **Service from GitHub repo**, pointing at this repo.
   - In the service settings: **Builder = Dockerfile**, **Dockerfile path =
     `cloud/server/Dockerfile`**, **Root directory = `/` (repo root)**.
     `railway.json` already encodes this — Railway picks it up automatically.
   - Set env vars:
     - `READER_TOKEN_PI_BARGE` — generate with
       `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
     - Anything from the table above you want to override.

3. **Deploy**. The healthcheck path `/healthz` is wired in `railway.json`;
   Railway will mark the service healthy once it responds 200.

4. **Confirm the schema applied**:
   ```
   railway run psql $DATABASE_URL -c "\\d readings"
   ```
   Should show all 27 columns. (If `DB_MIGRATE=0` was set, run
   `cloud/server/migrations/0001_readings.sql` manually.)

5. **Note the public URL** Railway assigns; that's the dashboard.

## Wiring up the Pi-side uploader

On the Mac (and later the Pi), once Railway is live:

```bash
.venv/bin/pip install -r cloud/uploader/requirements.txt

export READER_TOKEN=<the same value that's in READER_TOKEN_PI_BARGE>

# First run — dry-run mode to confirm the row shape looks right:
.venv/bin/python -m cloud.uploader.uploader \
    --csv data/pack.csv \
    --url https://<your>.up.railway.app \
    --source-id pi-barge \
    --dry-run

# Then for real, alongside scripts/log.py:
.venv/bin/python -m cloud.uploader.uploader \
    --csv data/pack.csv \
    --url https://<your>.up.railway.app \
    --source-id pi-barge \
    --log data/uploader.log
```

The uploader maintains its read position in
`data/pack.csv.cloud_state` (JSON: `{offset_bytes, inode, header}`). Delete
that file to re-upload from the top.

## ESP32 hand-off (future)

When the firmware is ready:

1. Build the same JSON payload — see `cloud/shared/wire.py:Reading` for the
   exact field names and types. Pydantic's `extra="forbid"` means unknown
   fields are rejected; if you add a field on-device, add it here first.
2. NTP-sync to UTC and emit timestamps as ISO-8601 with `Z`. The server
   422s on naive timestamps.
3. Configure `source_id="esp32-barge"` and add `READER_TOKEN_ESP32_BARGE`
   in Railway env vars. Pi keeps running alongside; rows from each device
   coexist via the `(source_id, ts)` primary key.

## Where to pick this up

- **Not done yet**: deploying to Railway (needs the user's account), running
  the uploader against real Railway (needs the URL), porting the analytics
  panels from `scripts/dashboard.py` (advisor, harvest, projection — all
  shell out to sibling scripts that depend on local CSV layout, so they're
  local-only for now).
- **Local CSV schema**: the next time `scripts/log.py` runs, it'll detect
  the old 22-col `data/pack.csv` and archive it to `data/pack.csv.v1-HHMM`,
  then start a fresh 32-col file. This is intentional and safe.
- **Test command**: `.venv/bin/python -m unittest discover -s cloud/tests`
  for the cloud tests; `tests/test_log_schema.py` for the edge changes.
  Both run on Python 3.11 (the repo's normal 3.13 setup also works).
