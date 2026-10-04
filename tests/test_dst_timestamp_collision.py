"""The autumn DST transition must not silently discard an hour of readings.

Found by the 2026-10-04 full-stack review, 28 days before it would have fired.

scripts/log.py wrote `datetime.now().isoformat()` — NAIVE local time. On
2026-11-01 the site's local hour 01:00-01:59 happens twice (PDT -> PST). Both
passes wrote identical naive strings; the uploader's `.astimezone()` resolved
the ambiguity to fold=0 (PDT) for both; both mapped to the same wire UTC; the
second pass collided on the readings primary key and `ON CONFLICT DO NOTHING`
dropped ~720 rows — one hour of the PRIMARY telemetry stream.

WHY IT IS THE WORST CLASS FOR THIS SYSTEM: gap analysis cannot see it. The
database stays perfectly contiguous while an hour of reality is missing,
ingest returns HTTP 200, and no alert fires on either paging path. The only
trace is `accepted=0 dup=60` in a journal nobody reads. It had never been
observed because this deployment's first boot was 2026-06-05, after the spring
transition.

Spring forward is the harmless mirror: the local hour 02:00-02:59 never
occurs, so rows are ABSENT rather than overwritten — and absence is what gap
analysis can actually see.
"""

from __future__ import annotations

import datetime as dt
import inspect
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloud" / "uploader"))
from uploader import _local_to_utc_z   # noqa: E402

PDT = dt.timezone(dt.timedelta(hours=-7))
PST = dt.timezone(dt.timedelta(hours=-8))


class AmbiguousHourTests(unittest.TestCase):

    def _written(self, aware: dt.datetime) -> str:
        """What log.py now writes for that instant, per _ts_now()."""
        return aware.astimezone(aware.tzinfo).isoformat(timespec="seconds")

    def test_the_two_passes_of_the_repeated_hour_do_not_collide(self):
        """The defect, stated directly."""
        first = self._written(dt.datetime(2026, 11, 1, 1, 30, tzinfo=PDT))
        second = self._written(dt.datetime(2026, 11, 1, 1, 30, tzinfo=PST))
        self.assertNotEqual(
            first, second,
            "both passes write the same string, so the second will collide")
        self.assertNotEqual(
            _local_to_utc_z(first), _local_to_utc_z(second),
            "distinct local strings must still map to distinct wire instants, "
            "or ON CONFLICT DO NOTHING discards the second hour")

    def test_the_wire_instants_are_exactly_an_hour_apart(self):
        """Not merely different — correct. 01:30 PDT is 08:30Z and 01:30 PST
        is 09:30Z, two real instants an hour apart."""
        a = _local_to_utc_z(self._written(
            dt.datetime(2026, 11, 1, 1, 30, tzinfo=PDT)))
        b = _local_to_utc_z(self._written(
            dt.datetime(2026, 11, 1, 1, 30, tzinfo=PST)))
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        delta = (dt.datetime.strptime(b, fmt) - dt.datetime.strptime(a, fmt))
        self.assertEqual(delta, dt.timedelta(hours=1))
        self.assertEqual(a, "2026-11-01T08:30:00Z")
        self.assertEqual(b, "2026-11-01T09:30:00Z")

    def test_a_whole_repeated_hour_survives(self):
        """720 rows at the 5 s cadence, not just one sample."""
        wire = set()
        for tz in (PDT, PST):
            for sec in range(0, 3600, 5):
                t = dt.datetime(2026, 11, 1, 1, 0, tzinfo=tz) \
                    + dt.timedelta(seconds=sec)
                wire.add(_local_to_utc_z(self._written(t)))
        self.assertEqual(
            len(wire), 1440,
            f"expected 1440 distinct instants across the doubled hour, got "
            f"{len(wire)} — the rest would be dropped on insert")


class BackwardCompatibilityTests(unittest.TestCase):
    """pack.csv is 345 MB of history. Old rows must keep parsing."""

    def test_existing_naive_rows_still_convert(self):
        for naive, expect in (("2026-10-04T09:15:00", "2026-10-04T16:15:00Z"),
                              ("2026-06-05T00:00:01", "2026-06-05T07:00:01Z")):
            with self.subTest(naive=naive):
                self.assertEqual(_local_to_utc_z(naive), expect)

    def test_the_local_wall_clock_is_preserved_not_switched_to_utc(self):
        """Writing UTC would silently reinterpret the column mid-file: old
        rows are local. Anything reading the date prefix for "today" would
        break at the boundary. The offset form keeps the wall clock."""
        import log
        out = log._ts_now()
        self.assertRegex(out, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
        parsed = dt.datetime.fromisoformat(out)
        self.assertIsNotNone(parsed.tzinfo, "must be offset-aware")
        local_now = dt.datetime.now()
        self.assertEqual((parsed.year, parsed.month, parsed.day, parsed.hour),
                         (local_now.year, local_now.month, local_now.day,
                          local_now.hour),
                         "the wall-clock reading must match local time")


class TheWriterIsNotNaiveTests(unittest.TestCase):

    def test_log_py_does_not_write_a_bare_naive_now(self):
        """The literal defect: `datetime.now().isoformat()` with no offset."""
        import log
        src = inspect.getsource(log)
        rows = [l for l in src.splitlines()
                if '"ts"' in l and not l.strip().startswith("#")]
        self.assertTrue(rows, "could not find the ts column writer")
        for line in rows:
            self.assertNotRegex(
                line, r"datetime\.now\(\)\.isoformat",
                "the ts column is being written as naive local time again; "
                "that loses an hour at every autumn DST transition")

    def test_the_helper_attaches_an_offset(self):
        import log
        self.assertIn("astimezone", inspect.getsource(log._ts_now))

    def test_the_other_two_write_paths_stay_utc(self):
        """solar and events were already immune; they must stay that way."""
        xt = (Path(__file__).resolve().parents[1]
              / "scripts" / "xanbus_telemetry.py").read_text()
        self.assertNotRegex(
            xt, r"datetime\.now\(\)\.isoformat",
            "the solar path must not adopt naive local time")


if __name__ == "__main__":
    unittest.main()
