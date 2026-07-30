-- 0003_solar.sql — Xanbus (CAN) solar/charger telemetry, read directly off
-- the Conext bus by the Pi's xanbus-reader service (see docs/xanbus-decode.md).
-- Independent of `readings` (BMS/RS485, 5s cadence): different source, own
-- clock grid (15s, wall-clock aligned), own trust level per field.
--
-- Idempotent — safe to re-run. Auto-applies when DB_MIGRATE=1.

-- Series table: the ~6 numeric fields worth charting, one row per 15s
-- bucket. Only solar_w and dc_w carry min/max — those are the two channels
-- where a transient (cloud edge, load spike) matters and a bucket mean
-- would hide it; the reader polls CAN continuously and folds each interval
-- down to mean/min/max, so downsampling old rows later stays lossless
-- (mean-of-means, min-of-mins, max-of-maxes are exact).
--
-- schema_version lets us reinterpret or purge rows from an early field
-- definition without a migration — see docs/xanbus-decode.md for which
-- fields are validated vs still-provisional at any given version.
CREATE TABLE IF NOT EXISTS solar_readings (
    source_id       TEXT        NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    schema_version  SMALLINT    NOT NULL DEFAULT 1,

    -- MPPT output to the battery (127173 assoc 0x03, src=MPPT). The
    -- validated solar-production number — see xanbus-decode.md for why
    -- this replaces the PV-input fields (0x15), which this hardware
    -- never populates.
    solar_w         REAL,
    solar_w_min     REAL,
    solar_w_max     REAL,
    solar_a         REAL,

    -- PV array voltage (127173 assoc 0x15). Array health, not production.
    pv_v            REAL,

    -- Inverter's DC-bus view (127172, src=SW): battery voltage + net DC
    -- current/power at the inverter. Sign convention: POSITIVE = into the
    -- battery / into the DC bus.
    dc_v            REAL,
    dc_a            REAL,
    dc_w            REAL,
    dc_w_min        REAL,
    dc_w_max        REAL,

    -- How many raw CAN samples fed this bucket. Low/zero is a reader- or
    -- bus-health signal (expect ~dozens at a 10-25 Hz native poll rate).
    sample_n        SMALLINT,

    PRIMARY KEY (source_id, ts)
);

CREATE INDEX IF NOT EXISTS solar_readings_source_ts_desc
    ON solar_readings (source_id, ts DESC);

-- Event table: sparse, on-change signals (charge-stage transitions,
-- inverter mode, generator start/stop with its V/A/W attached in `data`,
-- config setpoint changes, node dropouts). Same schema-loose JSONB shape
-- as `ble_events` — deliberately duplicated rather than shared, since the
-- two streams are unrelated telemetry (RS485/BLE vs Xanbus) and keeping
-- them separate tables avoids coupling their evolution.
CREATE TABLE IF NOT EXISTS xanbus_events (
    id          BIGSERIAL PRIMARY KEY,
    source_id   TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    event       TEXT        NOT NULL,
    data        JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS xanbus_events_source_ts_desc
    ON xanbus_events (source_id, ts DESC);
