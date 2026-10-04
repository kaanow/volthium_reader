"""SQL migration files for the readings DB.

Files are numbered (0001_, 0002_, ...) and applied in lexicographic order
by `apply_all()`. Each file is run in its entirety as one query — keep them
idempotent so re-runs are safe.
"""

from __future__ import annotations

from pathlib import Path

import logging

import asyncpg

log = logging.getLogger("volthium-cloud")


MIGRATIONS_DIR = Path(__file__).parent


# This runs INSIDE the FastAPI lifespan handler, BEFORE the app serves. That
# is not a background task — it is boot. A CREATE INDEX here took the API down
# for ~13 minutes on 2026-10-04: the build outran the platform healthcheck,
# the container was killed, and each restart began the index again.
#
# Three hazards the revert did not address, all live until now:
#
#   1. NO lock_timeout. Even ADD COLUMN, which is O(1) metadata, takes an
#      ACCESS EXCLUSIVE lock — and that lock QUEUES AHEAD of every subsequent
#      request. One slow in-flight read on solar_readings therefore blocks the
#      ALTER, which then blocks every read AND ingest behind it, on the
#      pre-serve path. A bounded wait turns that from a wedge into a clean
#      failure.
#   2. NO coordination. Railway starts the new container while the old one is
#      still serving, so two copies run apply_all concurrently.
#   3. NO ledger. Every file re-executes on every boot, so idempotence is an
#      assumption about the live database rather than a property of the files.
#      `CREATE INDEX IF NOT EXISTS` is a no-op only while that index exists BY
#      NAME; if one is ever dropped, the next boot rebuilds it on a populated
#      table and reproduces the outage with no commit to review.
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "30s"
ADVISORY_LOCK_KEY = 0x564F4C54          # "VOLT"


async def apply_all(pool: asyncpg.Pool) -> int:
    """Apply every .sql file in order. Returns the count applied.

    Bounded and serialised. A migration that cannot get its lock now FAILS
    rather than wedging boot, which is the difference between a deploy that
    rolls back and an API that 502s until someone notices.
    """
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.acquire() as conn:
        # Serialise across concurrent deploys. Session-scoped, so it is
        # released when this connection returns to the pool.
        await conn.execute(f"SELECT pg_advisory_lock({ADVISORY_LOCK_KEY})")
        try:
            await conn.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
            await conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
            for f in files:
                try:
                    await conn.execute(f.read_text())
                except Exception:
                    # Name the FILE. "applied N migration file(s)" told us
                    # nothing about which one, in the one place where knowing
                    # matters most.
                    log.exception("migration FAILED: %s", f.name)
                    raise
        finally:
            await conn.execute(
                f"SELECT pg_advisory_unlock({ADVISORY_LOCK_KEY})")
    return len(files)
