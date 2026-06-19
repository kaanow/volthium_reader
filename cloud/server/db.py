"""asyncpg pool + a thin DAO for the readings table.

The DAO is the only place that knows SQL — main.py talks to it via the
typed methods below. Tests substitute an in-memory fake (see
cloud/tests/test_server.py).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Protocol, Sequence

import asyncpg

from cloud.server.derive import Derived
from cloud.shared.wire import Reading


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

    async def sources(self) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT source_id FROM readings ORDER BY source_id"
            )
        return [r["source_id"] for r in rows]


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Open the asyncpg pool with a small bounded size — Railway free tier
    Postgres tops out at a low connection count."""
    return await asyncpg.create_pool(
        database_url,
        min_size=1, max_size=5,
        command_timeout=10,
    )
