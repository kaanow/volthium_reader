-- 0004_solar_pv_extremes.sql — array-voltage extremes per bucket.
--
-- The MPPT diode-clamp latch is a SLIDE down the IV curve; a bucket mean
-- hides how far the array moved within the interval, which is exactly the
-- signal that shows the approach to a latch and the recovery from one.
-- Reader emits these from schema_version 2 onward.
--
-- Idempotent — safe to re-run. Auto-applies when DB_MIGRATE=1.

ALTER TABLE solar_readings ADD COLUMN IF NOT EXISTS pv_v_min REAL;
ALTER TABLE solar_readings ADD COLUMN IF NOT EXISTS pv_v_max REAL;
