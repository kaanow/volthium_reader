"""SQL migration files for the readings DB.

Files are numbered (0001_, 0002_, ...) and applied in lexicographic order
by `apply_all()`. Each file is run in its entirety as one query — keep them
idempotent so re-runs are safe.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg


MIGRATIONS_DIR = Path(__file__).parent


async def apply_all(pool: asyncpg.Pool) -> int:
    """Apply every .sql file in order. Returns the count applied."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    async with pool.acquire() as conn:
        for f in files:
            await conn.execute(f.read_text())
    return len(files)
