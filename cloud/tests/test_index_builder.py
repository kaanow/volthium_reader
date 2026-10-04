"""Expensive indexes must be built off the startup path, and must not matter.

On 2026-10-04 a CREATE INDEX inside a migration took the whole API down for
~13 minutes: apply_all runs in the FastAPI lifespan handler BEFORE the app
serves, so the build outran the platform healthcheck, the container was
killed, and each restart began the index again.

The index is still needed. /api/events filters on `event` while ble_events is
indexed only on (source_id, ts), so measured against production today:

    event=read_ok          0.25 s     (it is the newest row)
    event=wedge_snapshot   1.28 s
    event=zzz_nonexistent  5.25 s     (a guaranteed full scan)
    event=read_fail        9.96 s     <- the statement timeout is 10 s

read_fail sits ON the boundary and flaps — 500/10.2 s and 200/0.6 s minutes
apart — and that is the probe status_check uses for the PRIMARY telemetry
path.
"""

from __future__ import annotations

import inspect
import unittest

from cloud.server import index_builder as IB
from cloud.server import main as main_mod


class BuildsAreConcurrentAndIdempotentTests(unittest.TestCase):

    def test_every_index_is_built_concurrently(self):
        """CONCURRENTLY takes no write lock, so ingest keeps flowing."""
        for name, _table, ddl in IB.WANTED:
            with self.subTest(index=name):
                self.assertIn("CONCURRENTLY", ddl)

    def test_every_index_is_idempotent(self):
        for name, _table, ddl in IB.WANTED:
            with self.subTest(index=name):
                self.assertIn("IF NOT EXISTS", ddl)

    def test_the_wanted_list_is_not_empty(self):
        """Otherwise every assertion here passes vacuously."""
        self.assertTrue(IB.WANTED)

    def test_the_index_that_caused_the_outage_is_the_one_being_built(self):
        names = {n for n, _t, _d in IB.WANTED}
        self.assertIn("ble_events_source_event_ts_desc", names)


class FailureCannotAffectAvailabilityTests(unittest.IsolatedAsyncioTestCase):

    async def test_a_failing_build_is_swallowed(self):
        """An optimisation must never be able to take the API down. That is
        the entire lesson of the incident this module exists to avoid."""
        class _Pool:
            def acquire(self):
                raise RuntimeError("database on fire")
        out = await IB.ensure_indexes(_Pool())
        self.assertTrue(all(v.startswith("failed") for v in out.values()))

    async def test_ensure_indexes_never_raises(self):
        class _Pool:
            def acquire(self):
                raise OSError("connection reset")
        await IB.ensure_indexes(_Pool())   # must not raise

    def test_an_INVALID_index_is_dropped_before_rebuilding(self):
        """The trap that made CONCURRENTLY unattractive in a migration: a
        failed build leaves an INVALID index, IF NOT EXISTS then skips it
        forever, and it looks applied while the planner ignores it."""
        src = inspect.getsource(IB.ensure_indexes)
        self.assertIn("DROP INDEX CONCURRENTLY", src)
        self.assertIn("_invalid_indexes", src)

    def test_validity_is_checked_AFTER_building_too(self):
        """Building is not the same as succeeding."""
        src = inspect.getsource(IB.ensure_indexes)
        i = src.index("await conn.execute(ddl)")
        self.assertIn("_invalid_indexes", src[i:],
                      "a build that lands INVALID would be reported as ok")


class ItRunsOffTheStartupPathTests(unittest.TestCase):

    def test_the_lifespan_does_not_await_the_build(self):
        """Awaiting it would put the build back on the startup path, which is
        the exact shape of the outage."""
        src = inspect.getsource(main_mod.lifespan)
        self.assertIn("run_in_background", src)
        self.assertNotIn("await ensure_indexes", src)

    def test_it_is_scheduled_as_a_task(self):
        src = inspect.getsource(IB.run_in_background)
        self.assertIn("create_task", src)

    def test_it_waits_before_adding_io(self):
        self.assertGreaterEqual(IB.START_DELAY_S, 10)

    def test_the_build_timeout_is_generous_not_tight(self):
        """Off the critical path, so a multi-million-row build is allowed to
        be slow. The point is that it cannot block, not that it is fast."""
        self.assertGreaterEqual(IB.BUILD_TIMEOUT_S, 600)

    def test_the_task_is_cancelled_on_shutdown(self):
        src = inspect.getsource(main_mod.lifespan)
        self.assertIn("cancel()", src)

    def test_no_migration_builds_an_index_on_a_populated_table(self):
        """The startup path must STAY clean — this module existing does not
        make it safe to put one back in a migration."""
        import re
        from pathlib import Path
        d = Path(main_mod.__file__).parent / "migrations"
        for f in sorted(d.glob("*.sql")):
            code = "\n".join(l for l in f.read_text().splitlines()
                             if not l.strip().startswith("--"))
            created = {t.lower() for t in re.findall(
                r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)", code, re.I)}
            for tbl in re.findall(
                    r"CREATE\s+INDEX[^;]*?\sON\s+(\w+)", code, re.I):
                with self.subTest(file=f.name):
                    self.assertIn(tbl.lower(), created,
                                  f"{f.name} indexes a pre-existing table")


if __name__ == "__main__":
    unittest.main()
