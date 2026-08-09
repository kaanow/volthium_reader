"""asyncpg pool + a thin DAO for the readings table.

The DAO is the only place that knows SQL — main.py talks to it via the
typed methods below. Tests substitute an in-memory fake (see
cloud/tests/test_server.py).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional, Protocol, Sequence

import asyncpg

from cloud.server.derive import Derived
from cloud.shared.wire import BleEvent, Reading, SolarReading


class ReadingsDAO(Protocol):
    """The subset of DB operations the ingest + dashboard endpoints need.
    Implemented by AsyncpgReadingsDAO in prod and by a fake in tests."""

    async def latest_smoothed(
        self, source_id: str, before_ts: datetime
    ) -> tuple[Optional[float], Optional[float]]:
        """Return (smoothed_i, smoothed_p) from the most recent row
        STRICTLY BEFORE `before_ts` for this source. Used as the prior for
        a batch's first reading. (Returns (None, None) if no prior exists.)"""

    async def insert(
        self,
        source_id: str,
        readings: Sequence[Reading],
        deriveds: Sequence[Derived],
    ) -> tuple[int, int]:
        """Insert N readings + their derived fields. Returns
        (accepted, duplicates). Idempotent on (source_id, ts) via
        ON CONFLICT DO NOTHING."""

    async def recent(
        self, source_id: Optional[str], limit: int
    ) -> list[dict]:
        """Most recent `limit` rows, newest-first. If source_id is None,
        the latest source's rows are returned (helps the dashboard when
        only one device is sending)."""

    async def sources(self) -> list[str]:
        """Distinct source_ids that have ever uploaded."""

    async def insert_events(
        self, source_id: str, events: Sequence[BleEvent]
    ) -> int:
        """Bulk-insert BLE diagnostic events. Returns count inserted. No
        uniqueness constraint — events are append-only telemetry, duplicates
        from an uploader retry are cheap to store and easy to filter out."""


class AsyncpgReadingsDAO:
    """Postgres-backed ReadingsDAO."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def latest_smoothed(
        self, source_id: str, before_ts: datetime
    ) -> tuple[Optional[float], Optional[float]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT smoothed_i, smoothed_p
                   FROM readings
                   WHERE source_id = $1 AND ts < $2
                   ORDER BY ts DESC LIMIT 1""",
                source_id, before_ts,
            )
        if row is None:
            return (None, None)
        return (row["smoothed_i"], row["smoothed_p"])

    async def insert(
        self,
        source_id: str,
        readings: Sequence[Reading],
        deriveds: Sequence[Derived],
    ) -> tuple[int, int]:
        if not readings:
            return (0, 0)
        rows = []
        for r, d in zip(readings, deriveds):
            rows.append((
                source_id, r.ts, r.state,
                r.v_a, r.v_b, r.i_a, r.i_b,
                r.soc_a, r.soc_b, r.t_a, r.t_b,
                r.remaining_ah_a, r.remaining_ah_b,
                r.delta_v_a, r.delta_v_b,
                r.name_a, r.name_b,
                r.problem_code_a, r.problem_code_b,
                r.cell_voltages_a, r.cell_voltages_b,
                d.pack_v, d.pack_i, d.pack_p,
                d.smoothed_i, d.smoothed_p, d.minutes_remaining,
            ))
        async with self.pool.acquire() as conn:
            # executemany doesn't expose per-row conflict counts; instead,
            # use a single multi-row INSERT and count via RETURNING. For
            # large batches this is one round-trip.
            placeholders = ",".join(
                "(" + ",".join(f"${i*27 + j + 1}" for j in range(27)) + ")"
                for i in range(len(rows))
            )
            flat = [v for row in rows for v in row]
            inserted = await conn.fetch(
                f"""INSERT INTO readings (
                    source_id, ts, state,
                    v_a, v_b, i_a, i_b,
                    soc_a, soc_b, t_a, t_b,
                    remaining_ah_a, remaining_ah_b,
                    delta_v_a, delta_v_b,
                    name_a, name_b,
                    problem_code_a, problem_code_b,
                    cell_voltages_a, cell_voltages_b,
                    pack_v, pack_i, pack_p,
                    smoothed_i, smoothed_p, minutes_remaining
                ) VALUES {placeholders}
                ON CONFLICT (source_id, ts) DO NOTHING
                RETURNING ts""",
                *flat,
            )
        accepted = len(inserted)
        return (accepted, len(rows) - accepted)

    async def recent(
        self, source_id: Optional[str], limit: int
    ) -> list[dict]:
        async with self.pool.acquire() as conn:
            if source_id is None:
                src = await conn.fetchval(
                    "SELECT source_id FROM readings ORDER BY ts DESC LIMIT 1"
                )
                if src is None:
                    return []
                source_id = src
            rows = await conn.fetch(
                """SELECT * FROM readings
                   WHERE source_id = $1
                   ORDER BY ts DESC LIMIT $2""",
                source_id, limit,
            )
        return [dict(r) for r in rows]

    async def recent_since(
        self, source_id: Optional[str], since: datetime, limit: int
    ) -> list[dict]:
        """Rows STRICTLY AFTER `since`, OLDEST-first, capped at `limit`.
        Powers the dashboard's incremental poll and status_check's windowed
        fetch — both previously re-downloaded the whole history every call
        (the 9 GB/day egress). Resolves source_id=None like recent()."""
        async with self.pool.acquire() as conn:
            if source_id is None:
                src = await conn.fetchval(
                    "SELECT source_id FROM readings ORDER BY ts DESC LIMIT 1"
                )
                if src is None:
                    return []
                source_id = src
            rows = await conn.fetch(
                """SELECT * FROM readings
                   WHERE source_id = $1 AND ts > $2
                   ORDER BY ts ASC LIMIT $3""",
                source_id, since, limit,
            )
        return [dict(r) for r in rows]

    async def sources(self) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT source_id FROM readings ORDER BY source_id"
            )
        return [r["source_id"] for r in rows]

    async def insert_events(
        self, source_id: str, events: Sequence[BleEvent]
    ) -> int:
        if not events:
            return 0
        rows = [(source_id, e.ts, e.event, json.dumps(e.data)) for e in events]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO ble_events (source_id, ts, event, data)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                rows,
            )
        return len(rows)

    async def recent_events(
        self,
        source_id: str,
        event: str,
        since: datetime,
        limit: int = 20,
    ) -> list[dict]:
        """Fetch events of a specific kind for a source, since `since`,
        newest first. Used by EventAlertMonitor to react to reader-side
        incidents. Parses JSONB data into a dict for the caller."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT source_id, ts, event, data
                   FROM ble_events
                   WHERE source_id = $1 AND event = $2 AND ts >= $3
                   ORDER BY ts DESC
                   LIMIT $4""",
                source_id, event, since, limit,
            )
        out = []
        for r in rows:
            d = dict(r)
            ts = d.get("ts")
            if ts is not None and hasattr(ts, "isoformat"):
                d["ts"] = ts.isoformat().replace("+00:00", "Z")
            if isinstance(d.get("data"), str):
                try:
                    d["data"] = json.loads(d["data"])
                except json.JSONDecodeError:
                    d["data"] = {}
            out.append(d)
        return out


    # --- history / analytics queries ---------------------------------------
    # Prod-only (not part of the ReadingsDAO protocol): the /api/history/*
    # endpoints isinstance-check for AsyncpgReadingsDAO and return empty
    # shapes otherwise, mirroring the /api/events pattern.

    async def history_series(
        self, source_id: str, since: datetime, until: datetime, bucket_s: int
    ) -> list[dict]:
        """Time-bucketed aggregates for the range explorer. One row per
        bucket: avg/min/max power, avg pack voltage, per-battery avg SOC and
        temperature, per-battery max cell imbalance, sample count. Buckets
        are epoch-aligned so ranges are stable across refreshes."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                       to_timestamp(floor(extract(epoch FROM ts) / $4) * $4) AS bucket,
                       COUNT(*)        AS n,
                       AVG(pack_p)     AS p_avg,
                       MIN(pack_p)     AS p_min,
                       MAX(pack_p)     AS p_max,
                       AVG(pack_v)     AS v_avg,
                       AVG(soc_a)      AS soc_a,
                       AVG(soc_b)      AS soc_b,
                       AVG(t_a)        AS t_a,
                       AVG(t_b)        AS t_b,
                       MAX(delta_v_a)  AS dv_a,
                       MAX(delta_v_b)  AS dv_b,
                       AVG(i_a)        AS i_a,
                       AVG(i_b)        AS i_b,
                       -- Signed mean asymmetry — used ONLY for DIRECTION (which
                       -- battery is being charged), not the on/off decision.
                       AVG(i_a - i_b)  AS di_avg,
                       -- Robust charger detection: the FRACTION of readings in
                       -- the bucket whose INSTANTANEOUS |i_a - i_b| clears the
                       -- empirical 2.5 A bar (same threshold the reader uses).
                       -- Threshold-then-average, NOT average-then-threshold:
                       -- the two BMS current shunts carry a ~2-3% SYSTEMATIC
                       -- offset that SCALES with load, so at ~40 A a bucket's
                       -- mean di_avg reaches ~1.2 A with NO charger present —
                       -- which false-tripped the old |di_avg|>0.8 shading rule
                       -- (2026-07-21). Instantaneous divergence at high load
                       -- still sits ~1 A (< 2.5), so this fraction stays near 0
                       -- without a charger and near 1 with one. Random load-
                       -- transient skew (±60 A momentary) is a handful of
                       -- readings, so it never pushes the fraction over ~0.5.
                       -- cast to float8 so it serializes as a JSON number
                       -- (AVG of numeric literals is `numeric` → JSON string).
                       AVG(CASE WHEN i_a IS NOT NULL AND i_b IS NOT NULL
                                 AND abs(i_a - i_b) >= 2.5
                                THEN 1.0 ELSE 0.0 END)::float8 AS charger_frac
                   FROM readings
                   WHERE source_id = $1 AND ts >= $2 AND ts < $3
                   GROUP BY 1 ORDER BY 1""",
                source_id, since, until, float(bucket_s),
            )
        return [dict(r) for r in rows]

    async def history_daily(
        self, source_id: str, days: int, tz: str
    ) -> list[dict]:
        """Per-local-day ledger: Wh charged in / drawn out (trapezoid-free
        rectangle integration, per-row dt capped at 60 s so data gaps don't
        fabricate energy), SOC floor/ceiling, temp range, coverage seconds
        (→ availability)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH t AS (
                       SELECT ts, pack_p, soc_a, soc_b, t_a, t_b,
                              LEAST(COALESCE(EXTRACT(EPOCH FROM
                                  (LEAD(ts) OVER (ORDER BY ts) - ts)), 0), 60)
                                  AS dt
                       FROM readings
                       WHERE source_id = $1
                         AND ts >= (now() - make_interval(days => $2::int))
                   )
                   SELECT
                       (ts AT TIME ZONE $3)::date               AS day,
                       SUM(CASE WHEN pack_p > 0 THEN pack_p * dt
                                ELSE 0 END) / 3600.0            AS wh_in,
                       SUM(CASE WHEN pack_p < 0 THEN -pack_p * dt
                                ELSE 0 END) / 3600.0            AS wh_out,
                       MIN(LEAST(soc_a, soc_b))                 AS soc_min,
                       MAX(GREATEST(soc_a, soc_b))              AS soc_max,
                       MIN(LEAST(t_a, t_b))                     AS t_min,
                       MAX(GREATEST(t_a, t_b))                  AS t_max,
                       SUM(dt)::float8                          AS covered_s,
                       COUNT(*)                                 AS n
                   FROM t
                   GROUP BY 1 ORDER BY 1""",
                source_id, days, tz,
            )
        return [dict(r) for r in rows]

    async def history_profile(
        self, source_id: str, days: int, tz: str
    ) -> list[dict]:
        """Average power by local hour-of-day over the window — the daily
        rhythm. Split into charge/discharge components so the chart can show
        when energy typically comes in vs goes out."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                       EXTRACT(HOUR FROM ts AT TIME ZONE $3)::int AS hour,
                       AVG(pack_p)                                AS p_avg,
                       AVG(GREATEST(pack_p, 0))                   AS p_in,
                       AVG(LEAST(pack_p, 0))                      AS p_out,
                       COUNT(*)                                   AS n
                   FROM readings
                   WHERE source_id = $1
                     AND ts >= (now() - make_interval(days => $2::int))
                     AND pack_p IS NOT NULL
                   GROUP BY 1 ORDER BY 1""",
                source_id, days, tz,
            )
        return [dict(r) for r in rows]

    async def history_gaps(
        self, source_id: str, since: datetime, min_gap_s: float = 300.0
    ) -> list[dict]:
        """Telemetry outages in the window: consecutive-sample gaps longer
        than min_gap_s, newest first. The endpoint decorates each gap with
        the wedge classification recorded nearest its start."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """WITH g AS (
                       SELECT ts, LEAD(ts) OVER (ORDER BY ts) AS nxt
                       FROM readings
                       WHERE source_id = $1 AND ts >= $2
                   )
                   SELECT ts  AS gap_start,
                          nxt AS gap_end,
                          EXTRACT(EPOCH FROM (nxt - ts))::float8 AS duration_s
                   FROM g
                   WHERE nxt - ts > make_interval(secs => $3)
                   ORDER BY ts DESC
                   LIMIT 100""",
                source_id, since, float(min_gap_s),
            )
        return [dict(r) for r in rows]

    async def history_charger_intervals(
        self, source_id: str, since: datetime, until: datetime,
        threshold: float = 2.5, min_dur_s: float = 180.0,
    ) -> list[dict]:
        """Contiguous runs where |i_a - i_b| >= threshold for >= min_dur_s —
        i.e. an external per-battery charger on the series pack. Returns absolute
        [start, end, battery] intervals, so the imbalance-chart overlay renders
        a real balancing session at ANY zoom (unlike the bucketed charger_frac,
        which dilutes a short session below the shade threshold when zoomed out).
        Gaps-and-islands: number the on/off transitions, keep the on-runs."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH f AS (
                    SELECT ts,
                           (i_a IS NOT NULL AND i_b IS NOT NULL
                            AND abs(i_a - i_b) >= $4) AS chg,
                           (i_b - i_a) AS di
                    FROM readings
                    WHERE source_id = $1 AND ts >= $2 AND ts < $3
                ),
                m AS (SELECT ts, chg, di, LAG(chg) OVER (ORDER BY ts) AS prev FROM f),
                g AS (
                    SELECT ts, chg, di,
                           SUM(CASE WHEN chg IS DISTINCT FROM prev THEN 1 ELSE 0 END)
                               OVER (ORDER BY ts) AS grp
                    FROM m
                )
                SELECT MIN(ts) AS start, MAX(ts) AS "end", AVG(di) AS di_avg
                FROM g WHERE chg
                GROUP BY grp
                HAVING EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) >= $5
                ORDER BY start""",
                source_id, since, until, float(threshold), float(min_dur_s),
            )
        out = []
        for r in rows:
            d = dict(r)
            d["battery"] = "B" if (d.get("di_avg") or 0) > 0 else "A"
            out.append(d)
        return out

    async def history_alarms(
        self, source_id: str, since: datetime,
    ) -> list[dict]:
        """Alarm EPISODES per battery: contiguous runs where problem_code != 0.
        Returns [start, end, battery, codes] where `codes` is the bitwise-OR of
        every problem_code seen in the run (so an episode captures all flags
        that fired). Retroactive decode of stored data — the reader only names
        alarms going forward, but the raw code was always logged."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH long AS (
                    SELECT ts, problem_code_a AS pc, 'A' AS bat
                    FROM readings
                    WHERE source_id = $1 AND ts >= $2 AND problem_code_a IS NOT NULL
                    UNION ALL
                    SELECT ts, problem_code_b, 'B'
                    FROM readings
                    WHERE source_id = $1 AND ts >= $2 AND problem_code_b IS NOT NULL
                ),
                m AS (
                    SELECT ts, bat, pc, (pc <> 0) AS active,
                           LAG(pc <> 0) OVER (PARTITION BY bat ORDER BY ts) AS prev
                    FROM long
                ),
                g AS (
                    SELECT ts, bat, pc, active,
                           SUM(CASE WHEN active IS DISTINCT FROM prev THEN 1 ELSE 0 END)
                               OVER (PARTITION BY bat ORDER BY ts) AS grp
                    FROM m
                )
                SELECT bat, MIN(ts) AS start, MAX(ts) AS "end",
                       bit_or(pc) AS codes, COUNT(*) AS samples
                FROM g WHERE active
                GROUP BY bat, grp
                ORDER BY start""",
                source_id, since,
            )
        return [dict(r) for r in rows]

    async def history_stats(self, source_id: str) -> dict:
        """Lifetime records for the stats strip. Extremes carry their
        timestamps so the page can say WHEN, not just how much."""
        async with self.pool.acquire() as conn:
            base = await conn.fetchrow(
                """SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                          COUNT(*) AS n
                   FROM readings WHERE source_id = $1""",
                source_id,
            )
            if base is None or base["n"] == 0:
                return {}
            energy = await conn.fetchrow(
                """WITH t AS (
                       SELECT pack_p,
                              LEAST(COALESCE(EXTRACT(EPOCH FROM
                                  (LEAD(ts) OVER (ORDER BY ts) - ts)), 0), 60)
                                  AS dt
                       FROM readings WHERE source_id = $1
                   )
                   SELECT SUM(CASE WHEN pack_p > 0 THEN pack_p * dt
                                   ELSE 0 END) / 3600.0 AS wh_in,
                          SUM(CASE WHEN pack_p < 0 THEN -pack_p * dt
                                   ELSE 0 END) / 3600.0 AS wh_out,
                          SUM(dt)::float8 AS covered_s
                   FROM t""",
                source_id,
            )
            deepest = await conn.fetchrow(
                """SELECT ts, LEAST(soc_a, soc_b) AS soc
                   FROM readings
                   WHERE source_id = $1 AND soc_a IS NOT NULL
                     AND soc_b IS NOT NULL
                   ORDER BY LEAST(soc_a, soc_b) ASC, ts ASC LIMIT 1""",
                source_id,
            )
            peak_out = await conn.fetchrow(
                """SELECT ts, pack_p FROM readings
                   WHERE source_id = $1 AND pack_p IS NOT NULL
                   ORDER BY pack_p ASC, ts ASC LIMIT 1""",
                source_id,
            )
            peak_in = await conn.fetchrow(
                """SELECT ts, pack_p FROM readings
                   WHERE source_id = $1 AND pack_p IS NOT NULL
                   ORDER BY pack_p DESC, ts ASC LIMIT 1""",
                source_id,
            )
            coldest = await conn.fetchrow(
                """SELECT ts, LEAST(t_a, t_b) AS t FROM readings
                   WHERE source_id = $1 AND t_a IS NOT NULL AND t_b IS NOT NULL
                   ORDER BY LEAST(t_a, t_b) ASC, ts ASC LIMIT 1""",
                source_id,
            )
            hottest = await conn.fetchrow(
                """SELECT ts, GREATEST(t_a, t_b) AS t FROM readings
                   WHERE source_id = $1 AND t_a IS NOT NULL AND t_b IS NOT NULL
                   ORDER BY GREATEST(t_a, t_b) DESC, ts ASC LIMIT 1""",
                source_id,
            )
            worst_dv = await conn.fetchrow(
                """SELECT ts, GREATEST(delta_v_a, delta_v_b) AS dv
                   FROM readings
                   WHERE source_id = $1 AND delta_v_a IS NOT NULL
                     AND delta_v_b IS NOT NULL
                   ORDER BY GREATEST(delta_v_a, delta_v_b) DESC, ts ASC
                   LIMIT 1""",
                source_id,
            )
            # Per-battery records — only the stats where A and B genuinely
            # differ and the split is informative. MAX(remaining_ah) is each
            # BMS's effective capacity (its reading at 100% SOC); the two
            # differ (~228 vs ~209 Ah), which is the likely root of the
            # persistent A>B imbalance.
            perbat = await conn.fetchrow(
                """SELECT MAX(remaining_ah_a) AS cap_a,
                          MAX(remaining_ah_b) AS cap_b,
                          MIN(soc_a) AS soc_min_a, MIN(soc_b) AS soc_min_b,
                          MIN(t_a)   AS t_min_a,   MAX(t_a)   AS t_max_a,
                          MIN(t_b)   AS t_min_b,   MAX(t_b)   AS t_max_b,
                          MAX(delta_v_a) AS dv_a,  MAX(delta_v_b) AS dv_b
                   FROM readings WHERE source_id = $1""",
                source_id,
            )
        out = {
            "first_ts": base["first_ts"], "last_ts": base["last_ts"],
            "samples": base["n"],
            "wh_in": energy["wh_in"], "wh_out": energy["wh_out"],
            "covered_s": energy["covered_s"],
        }
        if deepest:
            out["deepest_soc"] = deepest["soc"]
            out["deepest_soc_ts"] = deepest["ts"]
        if peak_out:
            out["peak_out_w"] = peak_out["pack_p"]
            out["peak_out_ts"] = peak_out["ts"]
        if peak_in:
            out["peak_in_w"] = peak_in["pack_p"]
            out["peak_in_ts"] = peak_in["ts"]
        if coldest:
            out["coldest_c"] = coldest["t"]
            out["coldest_ts"] = coldest["ts"]
        if hottest:
            out["hottest_c"] = hottest["t"]
            out["hottest_ts"] = hottest["ts"]
        if worst_dv:
            out["worst_delta_v"] = worst_dv["dv"]
            out["worst_delta_v_ts"] = worst_dv["ts"]
        if perbat:
            out["per_battery"] = {
                "a": {
                    "capacity_ah": perbat["cap_a"], "soc_min": perbat["soc_min_a"],
                    "t_min": perbat["t_min_a"], "t_max": perbat["t_max_a"],
                    "worst_delta_v": perbat["dv_a"],
                },
                "b": {
                    "capacity_ah": perbat["cap_b"], "soc_min": perbat["soc_min_b"],
                    "t_min": perbat["t_min_b"], "t_max": perbat["t_max_b"],
                    "worst_delta_v": perbat["dv_b"],
                },
            }
        return out


    # --- solar (Xanbus/CAN) -------------------------------------------------
    # Same prod-only pattern as the history queries: /api/solar/* endpoints
    # isinstance-check for AsyncpgReadingsDAO.

    async def insert_solar(
        self, source_id: str, readings: Sequence["SolarReading"]
    ) -> tuple[int, int]:
        """Insert solar buckets, idempotent on (source_id, ts). Returns
        (accepted, duplicates) — same contract as insert()."""
        if not readings:
            return (0, 0)
        cols = ("source_id", "ts", "schema_version",
                "solar_w", "solar_w_min", "solar_w_max", "solar_a",
                "pv_v", "pv_v_min", "pv_v_max",
                "dc_v", "dc_a", "dc_w", "dc_w_min", "dc_w_max",
                "sample_n")
        rows = [(source_id, r.ts, r.schema_version,
                 r.solar_w, r.solar_w_min, r.solar_w_max, r.solar_a,
                 r.pv_v, r.pv_v_min, r.pv_v_max,
                 r.dc_v, r.dc_a, r.dc_w, r.dc_w_min, r.dc_w_max,
                 r.sample_n) for r in readings]
        n = len(cols)
        placeholders = ",".join(
            "(" + ",".join(f"${i*n + j + 1}" for j in range(n)) + ")"
            for i in range(len(rows))
        )
        flat = [v for row in rows for v in row]
        async with self.pool.acquire() as conn:
            inserted = await conn.fetch(
                f"""INSERT INTO solar_readings ({", ".join(cols)})
                    VALUES {placeholders}
                    ON CONFLICT (source_id, ts) DO NOTHING
                    RETURNING ts""",
                *flat,
            )
        accepted = len(inserted)
        return (accepted, len(rows) - accepted)

    async def solar_since(
        self, source_id: Optional[str], since: Optional[datetime], limit: int
    ) -> list[dict]:
        """Solar rows for the live tile. With `since`: strictly-after,
        oldest-first (incremental poll — the readings recent_since pattern).
        Without: newest-first recent rows."""
        async with self.pool.acquire() as conn:
            if source_id is None:
                src = await conn.fetchval(
                    "SELECT source_id FROM solar_readings ORDER BY ts DESC LIMIT 1"
                )
                if src is None:
                    return []
                source_id = src
            if since is not None:
                rows = await conn.fetch(
                    """SELECT * FROM solar_readings
                       WHERE source_id = $1 AND ts > $2
                       ORDER BY ts ASC LIMIT $3""",
                    source_id, since, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT * FROM solar_readings
                       WHERE source_id = $1
                       ORDER BY ts DESC LIMIT $2""",
                    source_id, limit,
                )
                rows = list(reversed(rows))
        return [dict(r) for r in rows]

    async def solar_series(
        self, source_id: str, since: datetime, until: datetime, bucket_s: int
    ) -> list[dict]:
        """Bucketed solar aggregates for the range explorer — the
        history_series shape, so the charts layer treats both alike.
        min/max fold the stored per-15s min/max (exact, not approximated)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                       to_timestamp(floor(extract(epoch FROM ts) / $4) * $4) AS bucket,
                       COUNT(*)         AS n,
                       AVG(solar_w)     AS solar_w,
                       MIN(solar_w_min) AS solar_w_min,
                       MAX(solar_w_max) AS solar_w_max,
                       AVG(pv_v)        AS pv_v,
                       -- Added 2026-08-07 with the history explorer. The
                       -- array-voltage ENVELOPE is the diagnostic: a clamp
                       -- reads as a narrow band pinned just above dc_v, and
                       -- the MPPT's ~1.1 V reporting dither is invisible in
                       -- the average alone — which is what defeated the latch
                       -- detector for a day. Exact fold, not approximated.
                       MIN(pv_v_min)    AS pv_v_min,
                       MAX(pv_v_max)    AS pv_v_max,
                       AVG(dc_v)        AS dc_v,
                       AVG(dc_a)        AS dc_a,
                       AVG(dc_w)        AS dc_w,
                       MIN(dc_w_min)    AS dc_w_min,
                       MAX(dc_w_max)    AS dc_w_max
                   FROM solar_readings
                   WHERE source_id = $1 AND ts >= $2 AND ts < $3
                   GROUP BY bucket ORDER BY bucket""",
                source_id, since, until, bucket_s,
            )
        return [dict(r) for r in rows]

# A single 2026-08-09 10:10 bucket stored dc_w = -27844 W (the inverter's own
# DC draw, decoded wrong) while dc_v and dc_a in the same frame were both fine.
# It made today's ledger report load_wh = -758, a negative house load.
#
# The decoder now rejects these at the source (xanbus_telemetry._batt_sts2
# cross-checks dc_w against |dc_v*dc_a|), but that only protects data written
# from now on — the bad row is already stored, and read paths should not be
# able to render a physically impossible number regardless of what is in the
# table. So sanitise on the way out too.
#
# NULL, not a clamped bound: a corrupt sample is MISSING data, not a real
# measurement that happened to sit at the limit. Clamping to 0 would quietly
# invent a reading; NULL makes SUM/AVG skip it, which is the honest answer.
# The bound is deliberately loose — the observed range is 1-131 W and the
# inverter is 4 kW, so 6000 W cannot be reached legitimately.
def _dc_w_sane(col: str = "dc_w") -> str:
    return f"CASE WHEN {col} BETWEEN 0 AND 6000 THEN {col} END"


    async def solar_energy_daily(
        self, source_id: str, days: int, tz: str
    ) -> list[dict]:
        """Per-local-day energy ledger with the solar split. Production is
        INFERRED from the two trustworthy meters (BMS battery power +
        inverter DC draw) whenever that exceeds the MPPT's self-report —
        the MPPT under-reads when its array is pinned near battery voltage
        (verified vs its own Modbus, 2026-08-04). 15s buckets joined across
        readings & solar_readings, integrated per day.

        The inferred branch is a DIFFERENCE OF TWO MISCALIBRATED METERS and
        must be gated on daylight. They disagree by ~33 W: the BMS puts the
        non-fridge baseline at 80 W where the inverter claims 113 W (see
        docs/xanbus-unknowns.md #12). Ungated, `batt + dc_w` stays positive
        all night and the ledger credits phantom sun — measured 2026-08-07:
        **54 Wh of "solar" across 2.2 hours of full darkness**, ~25 W of pure
        bias, every night.

        So force production to zero below the darkness threshold, where the
        true value is known rather than inferred. Gate on ARRAY VOLTAGE, not
        reported power: during a clamp the MPPT reports single-digit watts in
        broad daylight, so a power gate would zero out exactly the hours the
        inferred branch exists to rescue. In daylight the branch still carries
        the meter bias — it is the best available number, not an exact one."""
        async with self.pool.acquire() as conn:
            sane_s = _dc_w_sane("s.dc_w")
            rows = await conn.fetch(
                f"""WITH r AS (
                       SELECT to_timestamp(floor(extract(epoch FROM ts)/15)*15) AS b,
                              AVG(pack_p) AS batt
                       FROM readings WHERE source_id = $1
                         AND ts > now() - ($2 || ' days')::interval
                       GROUP BY b
                   ), s AS (
                       SELECT ts AS b, solar_w, dc_w, pv_v
                       FROM solar_readings WHERE source_id = $1
                         AND ts > now() - ($2 || ' days')::interval
                   ), j AS (
                       SELECT s.b,
                              CASE WHEN COALESCE(s.pv_v, 0) < 15
                                   THEN COALESCE(s.solar_w, 0)
                                   ELSE GREATEST(COALESCE(s.solar_w,0),
                                                 COALESCE(r.batt,0)
                                                 + COALESCE({sane_s},0))
                              END AS prod_w,
                              {sane_s}  AS load_w,
                              COALESCE(r.batt,0)  AS batt_w
                       FROM s LEFT JOIN r USING (b)
                   )
                   SELECT (b AT TIME ZONE $3)::date AS day,
                          SUM(GREATEST(prod_w,0)) * 15 / 3600.0  AS solar_wh,
                          SUM(load_w) * 15 / 3600.0              AS load_wh,
                          SUM(GREATEST(batt_w,0))  * 15 / 3600.0 AS batt_in_wh,
                          SUM(GREATEST(-batt_w,0)) * 15 / 3600.0 AS batt_out_wh,
                          COUNT(*) * 15 / 86400.0                AS coverage
                   FROM j GROUP BY day ORDER BY day""",
                source_id, str(days), tz,
            )
        return [dict(r) for r in rows]

    async def load_heatmap(
        self, source_id: str, days: int, tz: str
    ) -> list[dict]:
        """hour-of-day x day matrix of average inverter DC draw (house
        load proxy) from solar_readings.dc_w."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT (ts AT TIME ZONE $3)::date AS day,
                          extract(hour FROM ts AT TIME ZONE $3)::int AS hour,
                          AVG({_dc_w_sane()}) AS load_w
                   FROM solar_readings
                   WHERE source_id = $1
                     AND ts > now() - ($2 || ' days')::interval
                   GROUP BY day, hour ORDER BY day, hour""",
                source_id, str(days), tz,
            )
        return [dict(r) for r in rows]

    async def dc_load_profile(self, source_id: str, hours: float) -> dict:
        """Characterise the unmetered DC load (the 24 V fridge) from the BMS.

        It is only DIRECTLY measurable in darkness: with no solar, whatever
        the battery supplies beyond the inverter's own draw is DC load. The
        signature is strongly bimodal — compressor on vs off — so we split the
        samples at the point of maximum between-class variance (Otsu) rather
        than assuming a threshold.

        Deliberately does NOT extrapolate into daylight. During the day the
        arithmetic would have to lean on the MPPT's output-current reading,
        which under-reports (see docs/xanbus-unknowns.md #5), and an invented
        number is worse than an honest gap."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""WITH s AS (
                       SELECT to_timestamp(floor(extract(epoch FROM ts)/15)*15) AS b,
                              AVG(pv_v) AS pv_v,
                              AVG({_dc_w_sane()}) AS dc_w
                       FROM solar_readings
                       WHERE source_id = $1 AND ts > now() - ($2 || ' hours')::interval
                       GROUP BY b
                   )
                   SELECT r.ts, r.pack_p, s.dc_w
                   FROM readings r
                   JOIN s ON s.b = to_timestamp(floor(extract(epoch FROM r.ts)/15)*15)
                   WHERE r.source_id = $1
                     AND r.ts > now() - ($2 || ' hours')::interval
                     AND r.pack_p IS NOT NULL
                     -- Darkness by ARRAY VOLTAGE, never by reported power.
                     -- During a diode-clamp latch the MPPT reports 3-12 W
                     -- while ~380 W actually flows, so a power-based filter
                     -- lets latched DAYLIGHT hours in and wrecks the split
                     -- (first attempt returned 255 W at 83% duty). Voltage
                     -- sensing is the one MPPT measurement we trust.
                     AND COALESCE(s.pv_v, 0) < 15
                   ORDER BY r.ts""",
                source_id, str(hours),
            )
        vals = [float(r["pack_p"]) for r in rows]
        out = {"samples": len(vals), "hours": hours}
        if len(vals) < 120:
            out["note"] = "not enough dark samples yet"
            return out

        lo_v, hi_v = min(vals), max(vals)
        best = None
        for i in range(1, 200):
            t = lo_v + (hi_v - lo_v) * i / 200
            a = [v for v in vals if v <= t]
            b = [v for v in vals if v > t]
            if len(a) < 20 or len(b) < 20:
                continue
            wa, wb = len(a) / len(vals), len(b) / len(vals)
            ma = sum(a) / len(a)
            mb = sum(b) / len(b)
            score = wa * wb * (ma - mb) ** 2
            if best is None or score > best[0]:
                best = (score, t, ma, mb, len(a))
        if best is None:
            out["note"] = "no clean split — load may not be cycling"
            return out
        _score, split, mean_on, mean_off, n_on = best
        draw = mean_off - mean_on            # both negative; ON is more negative
        duty = n_on / len(vals)
        out.update(
            split_w=round(split, 1),
            draw_w=round(draw, 1),
            duty=round(duty, 3),
            baseline_w=round(-mean_off, 1),  # everything else on the bus
            kwh_per_day=round(draw * duty * 24 / 1000, 3),
            bimodal=bool(draw > 20),
        )
        return out

    async def insert_xanbus_events(
        self, source_id: str, events: Sequence[BleEvent]
    ) -> int:
        if not events:
            return 0
        rows = [(source_id, e.ts, e.event, json.dumps(e.data)) for e in events]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO xanbus_events (source_id, ts, event, data)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                rows,
            )
        return len(rows)

    async def recent_xanbus_events(
        self,
        source_id: Optional[str],
        event: Optional[str],
        since: Optional[datetime],
        limit: int = 200,
    ) -> list[dict]:
        """Xanbus event stream for the dashboard timeline. All filters
        optional — mirrors /api/events semantics.

        `event` accepts a COMMA-SEPARATED list as well as a single name. The
        stream is dominated by chg_stage/chg_target (~350/day), so a plain
        `limit` covers only about 8 hours and buries the rare events that
        actually matter — the history page's MPPT log came up empty for
        exactly that reason. Filtering here instead of in the browser also
        means we ship ~20 rows rather than 2000."""
        where, params = ["TRUE"], []
        if source_id:
            params.append(source_id)
            where.append(f"source_id = ${len(params)}")
        if event:
            names = [e.strip() for e in event.split(",") if e.strip()]
            if len(names) == 1:
                params.append(names[0])
                where.append(f"event = ${len(params)}")
            elif names:
                params.append(names)
                where.append(f"event = ANY(${len(params)}::text[])")
        if since:
            params.append(since)
            where.append(f"ts >= ${len(params)}")
        params.append(limit)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT source_id, ts, event, data FROM xanbus_events
                    WHERE {" AND ".join(where)}
                    ORDER BY ts DESC LIMIT ${len(params)}""",
                *params,
            )
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("data"), str):
                try:
                    d["data"] = json.loads(d["data"])
                except json.JSONDecodeError:
                    d["data"] = {}
            out.append(d)
        return out


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Open the asyncpg pool with a small bounded size — Railway free tier
    Postgres tops out at a low connection count."""
    return await asyncpg.create_pool(
        database_url,
        min_size=1, max_size=5,
        command_timeout=10,
    )
