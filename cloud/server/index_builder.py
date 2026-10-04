"""Build expensive indexes AFTER the app is serving, never during startup.

WHY THIS MODULE EXISTS. On 2026-10-04 a `CREATE INDEX` in a migration took the
whole API down for ~13 minutes: migrations run inside the FastAPI lifespan
handler BEFORE the app serves, so the build outran the platform healthcheck,
the container was killed, and every restart began the index again — a crash
loop that could not converge. It was reverted.

But the index is still needed, and the need is live rather than theoretical.
`/api/events` filters on `event` while ble_events is indexed only on
(source_id, ts), so any event that is not the dominant read_ok walks the ts
index backwards across the table. Measured against production today:

    event=read_ok          0.25 s     (it is the newest row)
    event=wedge_snapshot   1.28 s
    event=zzz_nonexistent  5.25 s     (a guaranteed full scan)
    event=read_fail        9.96 s     <- the statement timeout is 10 s

read_fail sits ON the boundary and FLAPS: measured 500/10.2 s and 200/0.6 s
minutes apart on the same query, depending on cache state. That is the probe
status_check uses for the PRIMARY telemetry path, so the health check
intermittently errors instead of answering — and it gets worse as the archive
grows.

WHAT MAKES THIS SAFE WHERE THE MIGRATION WAS NOT:

  1. It runs AFTER the app is serving, as a background task. A slow build
     delays nothing and kills nothing; the healthcheck is already passing.
  2. CONCURRENTLY, so it takes no write lock — ingest keeps flowing.
  3. Failure is LOGGED AND DROPPED. The index is an optimisation; the `since`
     bound added alongside it is what the health check actually relies on.
  4. It handles the hazard that made CONCURRENTLY unattractive in a
     migration: a build that fails partway leaves an INVALID index, which
     `IF NOT EXISTS` would then skip forever — looking applied while doing
     nothing. This checks pg_index.indisvalid and drops before rebuilding.

CONCURRENTLY cannot run inside a transaction, which is also why this does not
belong in apply_all(): that runs each file as a single statement under an
advisory lock, and wrapping DDL in a transaction is exactly what forbids it.
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg

log = logging.getLogger("volthium-cloud")


# (index name, table, definition). Kept as data so adding one is a line, and
# so a test can assert every entry is CONCURRENT and idempotent.
WANTED: tuple[tuple[str, str, str], ...] = (
    (
        "ble_events_source_event_ts_desc",
        "ble_events",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ble_events_source_event_ts_desc ON ble_events "
        "(source_id, event, ts DESC)",
    ),
)

# Generous: this is off the critical path and a multi-million-row build is
# legitimately slow. The point is that it cannot block anything, not that it
# is quick.
BUILD_TIMEOUT_S = 1800
# Let the app settle before adding I/O. Nothing depends on the index existing
# promptly; it has been absent for months.
START_DELAY_S = 60


async def _invalid_indexes(conn: asyncpg.Connection, name: str) -> bool:
    """Is `name` present but INVALID (a failed CONCURRENTLY build)?

    This is the trap that made CONCURRENTLY unattractive inside a migration:
    the index exists, so IF NOT EXISTS skips it forever, and it is never used
    by the planner. It looks applied and does nothing.
    """
    row = await conn.fetchrow(
        "SELECT i.indisvalid FROM pg_class c "
        "JOIN pg_index i ON i.indexrelid = c.oid "
        "WHERE c.relname = $1",
        name,
    )
    return row is not None and not row["indisvalid"]


async def ensure_indexes(pool: asyncpg.Pool) -> dict:
    """Build any missing index. Returns a per-index outcome, for logging.

    Never raises: every failure is reported and swallowed, because an
    optimisation must not be able to affect availability. That is the whole
    lesson of the outage this module exists to avoid repeating.
    """
    out: dict = {}
    for name, table, ddl in WANTED:
        try:
            async with pool.acquire() as conn:
                if await _invalid_indexes(conn, name):
                    log.warning("index %s exists but is INVALID — dropping "
                                "so it can be rebuilt", name)
                    await conn.execute(
                        f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
                await conn.execute(
                    f"SET statement_timeout = '{BUILD_TIMEOUT_S}s'")
                await conn.execute(ddl)
                if await _invalid_indexes(conn, name):
                    out[name] = "built-but-invalid"
                    log.error("index %s built INVALID", name)
                else:
                    out[name] = "ok"
                    log.info("index %s present", name)
        except Exception as exc:  # noqa: BLE001 — availability wins
            out[name] = f"failed: {type(exc).__name__}"
            log.warning("index %s could not be built (continuing): %s",
                        name, exc)
    return out


async def run_in_background(pool: asyncpg.Pool) -> asyncio.Task:
    """Schedule the build after a delay, once the app is already serving."""
    async def _go():
        try:
            await asyncio.sleep(START_DELAY_S)
            result = await ensure_indexes(pool)
            log.info("index builder finished: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("index builder crashed (ignored)")
    return asyncio.create_task(_go())
