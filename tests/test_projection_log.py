"""Tests for the advisor projection log.

Mirrors the test_calibration_log pattern: fixture a tempdir, exercise
the rate-limit boundary, verify round-trip read/write, check optional-
field handling.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.projection_log import (  # noqa: E402
    LogEntry,
    append_entry,
    last_entry,
    read_log,
    record_if_due,
)


def _call_record(path, now_dt, *, start=80.0, sr=70.0, eve=88.0, low=68.0,
                 coef=8.15, kwh=5.62, sunrise="2026-05-19T05:09",
                 source="test", min_minutes_between=25):
    """Compact wrapper to keep test bodies readable."""
    return record_if_due(
        start_soc_pct=start,
        projected_sunrise_soc=sr,
        projected_tomorrow_evening_soc=eve,
        projected_low_soc=low,
        solar_model_coefficient=coef,
        today_irradiance_kwh_m2=kwh,
        sunrise_iso=sunrise,
        source=source,
        now=now_dt,
        min_minutes_between=min_minutes_between,
        path=path,
    )


class TestProjectionLog(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "projection_log.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ---------- read/empty ----------

    def test_read_returns_empty_when_file_missing(self) -> None:
        self.assertEqual(read_log(self.path), [])

    def test_last_entry_is_none_when_empty(self) -> None:
        self.assertIsNone(last_entry(self.path))

    # ---------- first record + round-trip ----------

    def test_first_record_always_writes(self) -> None:
        wrote = _call_record(self.path, datetime(2026, 5, 18, 22, 0))
        self.assertTrue(wrote)
        log = read_log(self.path)
        self.assertEqual(len(log), 1)
        self.assertAlmostEqual(log[0].start_soc_pct, 80.0, places=2)
        self.assertAlmostEqual(log[0].projected_sunrise_soc, 70.0, places=2)
        self.assertAlmostEqual(log[0].projected_low_soc, 68.0, places=2)
        self.assertEqual(log[0].source, "test")

    def test_round_trip_preserves_all_fields(self) -> None:
        _call_record(
            self.path, datetime(2026, 5, 18, 22, 0),
            start=84.5, sr=69.4, eve=90.3, low=69.2,
            coef=8.149, kwh=5.62, sunrise="2026-05-19T05:09",
            source="advisor-invocation",
        )
        log = read_log(self.path)
        self.assertEqual(len(log), 1)
        e = log[0]
        self.assertAlmostEqual(e.start_soc_pct, 84.5, places=2)
        self.assertAlmostEqual(e.projected_sunrise_soc, 69.4, places=2)
        self.assertAlmostEqual(e.projected_tomorrow_evening_soc, 90.3, places=2)
        self.assertAlmostEqual(e.projected_low_soc, 69.2, places=2)
        self.assertAlmostEqual(e.solar_model_coefficient, 8.149, places=3)
        self.assertAlmostEqual(e.today_irradiance_kwh_m2, 5.62, places=3)
        self.assertEqual(e.sunrise_iso, "2026-05-19T05:09")
        self.assertEqual(e.source, "advisor-invocation")
        # Timestamp round-trips with seconds-precision
        self.assertIn("2026-05-18T22:00", e.ts)

    # ---------- rate limit boundary ----------

    def test_rate_limit_blocks_call_inside_window(self) -> None:
        """Two calls 5 min apart with min=25 → second is suppressed."""
        _call_record(self.path, datetime(2026, 5, 18, 22, 0))
        wrote = _call_record(self.path, datetime(2026, 5, 18, 22, 5))
        self.assertFalse(wrote)
        self.assertEqual(len(read_log(self.path)), 1)

    def test_rate_limit_passes_exact_threshold(self) -> None:
        """Call exactly at min_minutes_between → admitted (the check
        uses `<` strictly, so equality means 'enough time has passed')."""
        _call_record(self.path, datetime(2026, 5, 18, 22, 0))
        wrote = _call_record(self.path, datetime(2026, 5, 18, 22, 25))
        self.assertTrue(wrote)
        self.assertEqual(len(read_log(self.path)), 2)

    def test_rate_limit_passes_after_window(self) -> None:
        """30 min apart with min=25 → admitted."""
        _call_record(self.path, datetime(2026, 5, 18, 22, 0))
        wrote = _call_record(self.path, datetime(2026, 5, 18, 22, 30))
        self.assertTrue(wrote)
        self.assertEqual(len(read_log(self.path)), 2)

    def test_min_minutes_between_can_be_overridden(self) -> None:
        """A test or special caller can pass a different threshold."""
        _call_record(self.path, datetime(2026, 5, 18, 22, 0))
        # With min=1, even a 2-min gap admits the next row
        wrote = _call_record(
            self.path, datetime(2026, 5, 18, 22, 2),
            min_minutes_between=1,
        )
        self.assertTrue(wrote)
        self.assertEqual(len(read_log(self.path)), 2)

    def test_dashboard_subprocess_burst_produces_one_row(self) -> None:
        """Simulate the dashboard hitting the advisor 5 times in 5 min.
        Without rate-limit we'd write 5 rows; with rate-limit we get 1."""
        for minute in [0, 1, 2, 3, 4]:
            _call_record(self.path, datetime(2026, 5, 18, 22, minute))
        self.assertEqual(len(read_log(self.path)), 1)

    # ---------- optional fields ----------

    def test_none_irradiance_is_written_as_empty(self) -> None:
        """If Open-Meteo is unreachable, today_irradiance_kwh_m2 may be
        None. The log row should still be written, with that field
        blank rather than crashing."""
        wrote = record_if_due(
            start_soc_pct=80.0,
            projected_sunrise_soc=70.0,
            projected_tomorrow_evening_soc=88.0,
            projected_low_soc=68.0,
            solar_model_coefficient=8.15,
            today_irradiance_kwh_m2=None,
            sunrise_iso="2026-05-19T05:09",
            source="test",
            now=datetime(2026, 5, 18, 22, 0),
            path=self.path,
        )
        self.assertTrue(wrote)
        log = read_log(self.path)
        self.assertIsNone(log[0].today_irradiance_kwh_m2)

    # ---------- multiple entries ----------

    def test_log_preserves_order_oldest_first(self) -> None:
        """Newer rows append at the end; read_log returns them in
        file order (oldest first). The CLI's `--tail` slices the end."""
        _call_record(self.path, datetime(2026, 5, 18, 22, 0), start=84.0)
        _call_record(self.path, datetime(2026, 5, 18, 23, 0), start=82.0)
        _call_record(self.path, datetime(2026, 5, 19,  0, 0), start=80.0)
        log = read_log(self.path)
        self.assertEqual(len(log), 3)
        self.assertAlmostEqual(log[0].start_soc_pct, 84.0)
        self.assertAlmostEqual(log[1].start_soc_pct, 82.0)
        self.assertAlmostEqual(log[2].start_soc_pct, 80.0)

    def test_append_entry_creates_file_with_header(self) -> None:
        """First write produces a header row. CSV consumers (DictReader)
        rely on it."""
        e = LogEntry(
            ts="2026-05-18T22:00:00",
            start_soc_pct=80.0,
            projected_sunrise_soc=70.0,
            projected_tomorrow_evening_soc=88.0,
            projected_low_soc=68.0,
            solar_model_coefficient=8.15,
            today_irradiance_kwh_m2=5.62,
            sunrise_iso="2026-05-19T05:09",
            source="test",
        )
        append_entry(e, self.path)
        with self.path.open() as f:
            first_line = f.readline().rstrip()
        self.assertIn("ts,", first_line)
        self.assertIn("start_soc_pct", first_line)
        self.assertIn("projected_sunrise_soc", first_line)


if __name__ == "__main__":
    unittest.main()
