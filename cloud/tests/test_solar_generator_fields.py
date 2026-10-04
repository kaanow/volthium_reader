"""schema_version 3: the generator's AC side, sampled per bucket.

WHY THESE COLUMNS EXIST: gen_v/gen_a/gen_va were already being aggregated per
15 s bucket by the reader into columns that did not exist, so every sample was
discarded. The 1h43m generator run of 2026-10-03 therefore left exactly two
data points behind, both at transitions — and `gen_start` fires when AC
voltage crosses 50 V, 17 s before the charger engaged, so the only generator
current on record is from a moment with legitimately no load.

"Is the generator current decode right?" was unanswerable, not answered.

THE DEPLOY ORDER IS PART OF THE DESIGN. SolarReading sets
extra="forbid", so a reader that sends a field the server does not know makes
the server reject the WHOLE batch with 422 — not ignore the field. That has
happened: pv_v_min/max on 2026-08-05 stalled solar ingest for 43 minutes.
So the server learns the fields first, then the Pi starts sending them. The
tests here are what make "the server already knows" checkable before the Pi
is touched.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cloud.shared.wire import SolarReading


MIGRATIONS = Path(__file__).resolve().parents[1] / "server" / "migrations"


class WireAcceptsGeneratorFieldsTests(unittest.TestCase):

    def test_the_model_accepts_the_three_generator_fields(self):
        r = SolarReading(ts="2026-10-04T15:00:00Z", schema_version=3,
                         gen_v=121.2, gen_a=11.6, gen_va=1400.0)
        self.assertEqual((r.gen_v, r.gen_a, r.gen_va), (121.2, 11.6, 1400.0))

    def test_they_are_optional_so_older_readers_still_validate(self):
        """The Pi runs whatever commit it last pulled. A row without them must
        stay valid, or deploying the server breaks the reader already in the
        field — the mirror image of the 422 hazard."""
        r = SolarReading(ts="2026-10-04T15:00:00Z", schema_version=2)
        self.assertIsNone(r.gen_v)
        self.assertIsNone(r.gen_a)
        self.assertIsNone(r.gen_va)

    def test_unknown_fields_are_STILL_rejected(self):
        """Widening the model must not become loosening it. extra="forbid" is
        what makes a decoder typo surface as a 422 instead of silently
        vanishing, so it has to keep biting for fields nobody declared."""
        with self.assertRaises(Exception):
            SolarReading(ts="2026-10-04T15:00:00Z", gen_hz=30.0)

    def test_gen_hz_is_not_a_column_or_a_field(self):
        """It decodes to a constant 30.00 including when gen_v is 0.0, so it
        is a misdecode. It stays in the event payload as gen_hz_unverified
        until the real offset is found from a raw capture; giving it a column
        would launder it into looking like data."""
        self.assertNotIn("gen_hz", SolarReading.model_fields)


class InsertPathTests(unittest.TestCase):

    def test_column_list_and_value_tuple_stay_the_same_length(self):
        """A half-applied edit here is an asyncpg error at runtime and nowhere
        else — the suite has no live Postgres. DERIVED from the source so it
        cannot drift: count the names, count the r.<attr> references."""
        import inspect
        from cloud.server import db as db_mod
        src = inspect.getsource(db_mod.AsyncpgReadingsDAO.insert_solar)
        cols = re.search(r"cols = \((.*?)\)\n", src, re.S).group(1)
        n_cols = len(re.findall(r'"(\w+)"', cols))
        rows = re.search(r"rows = \[\((.*?)\) for r in readings\]", src, re.S)
        n_vals = len(re.findall(r"\br\.\w+", rows.group(1))) + 1   # +1 source_id
        self.assertEqual(
            n_cols, n_vals,
            f"insert_solar names {n_cols} columns but supplies {n_vals} "
            f"values — a partially applied edit")

    def test_the_generator_columns_are_actually_inserted(self):
        import inspect
        from cloud.server import db as db_mod
        src = inspect.getsource(db_mod.AsyncpgReadingsDAO.insert_solar)
        for f in ("gen_v", "gen_a", "gen_va"):
            self.assertIn(f'"{f}"', src, f"{f} missing from the column list")
            self.assertRegex(src, rf"\br\.{f}\b", f"{f} value never supplied")


class MigrationSafetyTests(unittest.TestCase):
    """The lesson from taking the API down on 2026-10-04, as a test.

    apply_all() runs inside the FastAPI lifespan handler BEFORE the app
    serves. A CREATE INDEX there outran the platform healthcheck, the
    container was killed, and each restart began the build again — 502 on
    every path including /healthz for ~13 min.

    ADD COLUMN is safe precisely because it is O(1) metadata when there is no
    volatile DEFAULT. Add a DEFAULT and Postgres may rewrite the table, which
    puts work proportional to table size back on the startup path. So pin the
    shape, not just the intent.
    """

    @staticmethod
    def _statements(sql: str) -> list[str]:
        """Comment-stripped statements. Strip comments from the WHOLE file
        BEFORE splitting: the rollback note in 0006 contains a semicolon, so
        splitting first puts a statement boundary inside a comment block and
        yields comment-only fragments that no assertion can sensibly apply to.
        """
        code = "\n".join(l for l in sql.splitlines()
                          if not l.strip().startswith("--"))
        return [s.strip() for s in code.split(";") if s.strip()]

    def _sql(self, name: str) -> str:
        return (MIGRATIONS / name).read_text()

    def test_generator_columns_are_added_without_a_default(self):
        stmts = self._statements(self._sql("0006_solar_generator_fields.sql"))
        self.assertEqual(len(stmts), 3, f"expected 3 ALTERs, got {stmts}")
        for s in stmts:
            self.assertRegex(s, r"ADD COLUMN IF NOT EXISTS",
                             "must be idempotent — apply_all re-runs every file")
            self.assertNotRegex(
                s.upper(), r"\bDEFAULT\b",
                "a DEFAULT can trigger a table rewrite, and this runs on the "
                "startup path — see the 2026-10-04 outage")

    def test_no_index_is_built_on_an_ALREADY_POPULATED_table(self):
        """The real distinction, which my first version of this test got
        wrong. 0001-0003 all CREATE INDEX and are perfectly safe: each indexes
        a table it CREATEs in the same file, so the table is empty and the
        build is instant. What killed the API was an index on ble_events,
        which already held millions of rows.

        So the rule is not "no CREATE INDEX in migrations" — that would block
        legitimate work and I nearly shipped it. The rule is: an index must
        either accompany its table's creation, or be built out-of-band.
        """
        offenders = []
        for f in sorted(MIGRATIONS.glob("*.sql")):
            code = "\n".join(l for l in f.read_text().splitlines()
                              if not l.strip().startswith("--"))
            created = {t.lower() for t in re.findall(
                r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)", code, re.I)}
            for idx_table in re.findall(
                    r"CREATE\s+INDEX(?:\s+CONCURRENTLY)?"
                    r"(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+\s+ON\s+(\w+)", code, re.I):
                if idx_table.lower() not in created:
                    offenders.append(f"{f.name}: index on {idx_table}")
        self.assertEqual(
            offenders, [],
            f"index built during app startup on a table this migration does "
            f"not create, so it is already populated: {offenders}. Build it "
            f"out-of-band — a slow build is killed by the healthcheck and "
            f"retried forever.")


if __name__ == "__main__":
    unittest.main()
