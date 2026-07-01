-- 0002_ble_events.sql — structured BLE diagnostic events from the reader.
--
-- The reader emits ~5-9 records per read cycle (scan_result, teardown,
-- read_ok/fail, cycle_done, plus wedge_detected / adapter_recovery on
-- bad cycles, plus raw_frame when VOLTHIUM_CAPTURE_RAW=1). Stream is
-- schema-loose because the event taxonomy evolves as we learn — the
-- payload lives in a JSONB `data` column so new fields don't need a
-- migration.
--
-- Volume estimate at 10 s cycle cadence: ~400 KB/hr raw JSON → ~10 MB/day
-- → ~3.5 GB/year per source. Comfortable on any Railway Postgres plan.
--
-- Idempotent — safe to re-run. Auto-applies when DB_MIGRATE=1.

CREATE TABLE IF NOT EXISTS ble_events (
    id          BIGSERIAL PRIMARY KEY,
    source_id   TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    event       TEXT        NOT NULL,
    data        JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Hot path: "what did source X do recently?" and "give me all raw_frame
-- events for lab replay". BRIN on ts would also work for append-only data
-- but BTREE keeps range queries fast even for narrow windows.
CREATE INDEX IF NOT EXISTS ble_events_source_ts_desc
    ON ble_events (source_id, ts DESC);

-- For lab replay we filter on event='raw_frame' first, then narrow to a
-- session — a partial index on that predicate keeps it small.
CREATE INDEX IF NOT EXISTS ble_events_raw_frame_ts
    ON ble_events (source_id, ts DESC)
    WHERE event = 'raw_frame';
