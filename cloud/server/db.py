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
from cloud.shared.wire import BleEvent, Reading


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
                            AND abs(i_a - i_b) >= $4) AS on,
                           (i_b - i_a) AS di
                    FROM readings
                    WHERE source_id = $1 AND ts >= $2 AND ts < $3
                ),
                m AS (SELECT ts, on, di, LAG(on) OVER (ORDER BY ts) AS prev FROM f),
                g AS (
                    SELECT ts, on, di,
                           SUM(CASE WHEN on IS DISTINCT FROM prev THEN 1 ELSE 0 END)
                               OVER (ORDER BY ts) AS grp
                    FROM m
                )
                SELECT MIN(ts) AS start, MAX(ts) AS "end", AVG(di) AS di_avg
                FROM g WHERE on
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


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Open the asyncpg pool with a small bounded size — Railway free tier
    Postgres tops out at a low connection count."""
    return await asyncpg.create_pool(
        database_url,
        min_size=1, max_size=5,
        command_timeout=10,
    )
