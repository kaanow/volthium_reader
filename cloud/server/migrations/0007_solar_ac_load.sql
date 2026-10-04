-- 0007_solar_ac_load.sql — the cabin's own AC load, per bucket.
--
-- WHY THIS IS NEW DATA RATHER THAN A NEW FIELD: docs/what-to-distrust.md
-- treats the cabin AC load as UNMEASURABLE, and that premise underpins task
-- #32, the whole load_wh argument, the fridge-split work and the
-- energy_balance residual. The premise was wrong.
--
-- PGN 126998 carries three 25-byte line blocks. The decoder read blocks 1 and
-- 2, found zeros for assoc 0x33, and a code comment concluded "this decode
-- does not work: it reports 0 V / 0 A / 0 VA while the inverter is
-- demonstrably producing AC". The device reports it fine — on BLOCK 3, which
-- was never read. Verified against 7378 reassembled payloads from the
-- 2026-10-04 capture: 233.1 V, 0.87 A, 59.95 Hz, 202 VA, with |VA| matching
-- |V*I| to -0.57%. 233 V is the 240 V split-phase output, not a decode error.
--
-- This is what lets the dashboard's Loads tile show a NUMBER during a
-- generator run instead of "not metered", and it is the first direct
-- measurement of house consumption this system has ever had — every previous
-- figure was the inverter's DC input, which is blind to the bus-wired fridge
-- and includes charging.
--
-- SAFE ON THE STARTUP PATH: ADD COLUMN with no volatile DEFAULT is O(1)
-- catalog metadata in Postgres 11+, the same shape as 0004 and 0006. The
-- hazard that took the API down on 2026-10-04 was a CREATE INDEX whose cost
-- scales with the table, which this is not. See the note in 0006.
--
-- Rollback:
--   ALTER TABLE solar_readings DROP COLUMN load_v, DROP COLUMN load_a,
--                              DROP COLUMN load_va;
--
-- Idempotent — safe to re-run. Auto-applies when DB_MIGRATE=1.

ALTER TABLE solar_readings ADD COLUMN IF NOT EXISTS load_v  REAL;
ALTER TABLE solar_readings ADD COLUMN IF NOT EXISTS load_a  REAL;
ALTER TABLE solar_readings ADD COLUMN IF NOT EXISTS load_va REAL;
