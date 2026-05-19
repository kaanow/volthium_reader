"""Tests for `scripts.live_ratio_log`.

Sister of test_confidence_log.py — rate-limited append-only CSV
logger that records the advisor's live_ratio + drift snapshot on
each invocation. Each row should land at the configured cadence
(~25 min default) and the None-handling for early-morning days
(when live_ratio isn't populated yet) must be tight.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import live_ratio_log as lrl_mod  # noqa: E402


class TestLiveRatioLog(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "live_ratio_log.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_log_reads_as_empty_list(self) -> None:
        """Missing file must NOT crash callers."""
        self.assertEqual(lrl_mod.read_log(self.path), [])
        self.assertIsNone(lrl_mod.last_entry(self.path))

    def test_first_due_invocation_writes_row(self) -> None:
        """Empty log → any due invocation produces a seed row."""
        wrote = lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=7.30,
            solar_ah_so_far=2.0,
            irradiance_kwh_m2_so_far=0.27,
            solar_model_coefficient=8.15,
            drift_pct=-10.4,
            advisory_fired=False,
            path=self.path,
            now=datetime(2026, 5, 19, 9, 30, 0),
        )
        self.assertTrue(wrote)
        entries = lrl_mod.read_log(self.path)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertAlmostEqual(e.live_ratio_ah_per_kwh_m2, 7.30, places=2)
        self.assertAlmostEqual(e.drift_pct, -10.4, places=1)
        self.assertFalse(e.advisory_fired)

    def test_record_skipped_when_live_ratio_missing(self) -> None:
        """Early-morning days have live_ratio=None until the irradiance/
        Ah accumulator crosses today_harvest's threshold. The logger
        must SKIP those — no row should be written. Symmetrical to
        the dashboard advisor panel that hides the chip too."""
        wrote = lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=None,
            solar_ah_so_far=0.1,
            irradiance_kwh_m2_so_far=0.05,
            solar_model_coefficient=8.15,
            drift_pct=None,
            advisory_fired=False,
            path=self.path,
        )
        self.assertFalse(wrote)
        self.assertEqual(lrl_mod.read_log(self.path), [])

    def test_rate_limit_prevents_duplicate_rows(self) -> None:
        """Two invocations within MIN_MINUTES_BETWEEN must produce only
        ONE row. The advisor runs every 5 min via dashboard
        subprocesses; without this guard the log would balloon."""
        t0 = datetime(2026, 5, 19, 10, 0, 0)
        wrote_first = lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=7.0,
            solar_ah_so_far=1.0,
            irradiance_kwh_m2_so_far=0.15,
            solar_model_coefficient=8.15,
            drift_pct=-14.1,
            advisory_fired=False,
            now=t0, path=self.path,
        )
        # 10 min later → below the 25 min threshold
        wrote_second = lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=7.5,
            solar_ah_so_far=2.0,
            irradiance_kwh_m2_so_far=0.27,
            solar_model_coefficient=8.15,
            drift_pct=-8.0,
            advisory_fired=False,
            now=t0 + timedelta(minutes=10), path=self.path,
        )
        self.assertTrue(wrote_first)
        self.assertFalse(wrote_second)
        self.assertEqual(len(lrl_mod.read_log(self.path)), 1)

    def test_writes_again_after_interval_elapses(self) -> None:
        """30 min after a row → write another. Confirms the rate-
        limit gate ONLY kicks in within the window."""
        t0 = datetime(2026, 5, 19, 10, 0, 0)
        lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=7.0, solar_ah_so_far=1.0,
            irradiance_kwh_m2_so_far=0.15, solar_model_coefficient=8.15,
            drift_pct=-14.1, advisory_fired=False,
            now=t0, path=self.path,
        )
        wrote = lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=6.4, solar_ah_so_far=2.5,
            irradiance_kwh_m2_so_far=0.39, solar_model_coefficient=8.15,
            drift_pct=-21.5, advisory_fired=True,
            now=t0 + timedelta(minutes=30), path=self.path,
        )
        self.assertTrue(wrote)
        entries = lrl_mod.read_log(self.path)
        self.assertEqual(len(entries), 2)
        # Second row preserves advisory_fired=True (drift crossed)
        self.assertTrue(entries[-1].advisory_fired)

    def test_csv_round_trip_preserves_advisory_flag(self) -> None:
        """The advisory_fired bool is written as 'True'/'False' and
        round-trips through from_row() correctly. Edge case: pin down
        the string-to-bool decoder."""
        lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=4.2, solar_ah_so_far=3.0,
            irradiance_kwh_m2_so_far=0.7, solar_model_coefficient=8.15,
            drift_pct=-48.5, advisory_fired=True,
            now=datetime(2026, 5, 19, 12, 0, 0),
            path=self.path,
        )
        # Re-read from disk
        entries = lrl_mod.read_log(self.path)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[-1].advisory_fired)

    def test_csv_has_header_when_first_written(self) -> None:
        """Header row matches FIELDS so other tools can read the
        CSV without prior knowledge of column order."""
        lrl_mod.record_if_due(
            live_ratio_ah_per_kwh_m2=7.30, solar_ah_so_far=2.0,
            irradiance_kwh_m2_so_far=0.27, solar_model_coefficient=8.15,
            drift_pct=-10.4, advisory_fired=False,
            path=self.path,
        )
        with self.path.open() as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertEqual(header, lrl_mod.FIELDS)

    def test_default_rate_limit_constant(self) -> None:
        """Anchor the documented default so a tweak shows up as a
        deliberate change."""
        self.assertEqual(lrl_mod.MIN_MINUTES_BETWEEN, 25)


if __name__ == "__main__":
    unittest.main()
