-- 0001_readings.sql — initial schema for the cloud telemetry store.
--
-- Idempotent: safe to re-run. The server's auto-migrate path (DB_MIGRATE=1)
-- executes this on every boot. For one-shot Railway setup, paste it into
-- `railway run psql $DATABASE_URL` instead.

CREATE TABLE IF NOT EXISTS readings (
    source_id           TEXT        NOT NULL,
    ts                  TIMESTAMPTZ NOT NULL,
    state               TEXT,

    -- raw, from wire (per-battery)
    v_a                 REAL,
    v_b                 REAL,
    i_a                 REAL,
    i_b                 REAL,
    soc_a               REAL,
    soc_b               REAL,
    t_a                 REAL,
    t_b                 REAL,
    remaining_ah_a      REAL,
    remaining_ah_b      REAL,
    delta_v_a           REAL,
    delta_v_b           REAL,
    name_a              TEXT,
    name_b              TEXT,
    problem_code_a      INT,
    problem_code_b      INT,
    cell_voltages_a     REAL[],   -- always length CELLS_PER_BATTERY (4) when present
    cell_voltages_b     REAL[],

    -- derived, server-computed at insert time
    pack_v              REAL,
    pack_i              REAL,
    pack_p              REAL,
    smoothed_i          REAL,
    smoothed_p          REAL,
    minutes_remaining   REAL,

    PRIMARY KEY (source_id, ts)
);

-- Hot path: "give me the recent rows for a source", newest-first. The
-- primary key covers this lookup but an explicit DESC index avoids the
-- planner picking a less-optimal plan after the table grows.
CREATE INDEX IF NOT EXISTS readings_source_ts_desc
    ON readings (source_id, ts DESC);
