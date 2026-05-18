"""Tests for the SolarModel calibration log."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.calibration_log import (  # noqa: E402
    LogEntry,
    append_entry,
    is_meaningful_change,
    last_entry,
    read_log,
    record_if_changed,
)
from volthium.solar_model import SolarModel  # noqa: E402


def _mk_model(coef: float, n: int = 0, notes: str = "") -> SolarModel:
    """SolarModel(...) takes only the data fields; `confidence` is
    derived from n_observations inside the class."""
    return SolarModel(
        coefficient_ah_per_kwh_m2=coef,
        n_observations=n,
        notes=notes,
    )


class TestCalibrationLog(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "calibration_log.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_read_log_returns_empty_when_file_missing(self) -> None:
        self.assertEqual(read_log(self.path), [])

    def test_last_entry_returns_none_when_empty(self) -> None:
        self.assertIsNone(last_entry(self.path))

    def test_first_record_always_writes(self) -> None:
        """No previous entry → always meaningful → must write."""
        m = _mk_model(7.0)
        wrote = record_if_changed(m, source="init", path=self.path,
                                  now=datetime(2026, 5, 18, 12, 0))
        self.assertTrue(wrote)
        log = read_log(self.path)
        self.assertEqual(len(log), 1)
        self.assertAlmostEqual(log[0].coefficient, 7.0, places=4)
        self.assertEqual(log[0].source, "init")

    def test_tiny_change_does_not_write(self) -> None:
        """0.005 Ah/(kWh/m²) shift is below the 0.01 threshold → no
        new entry. Prevents log spam from sample-count jitter."""
        record_if_changed(_mk_model(7.0), source="a", path=self.path,
                          now=datetime(2026, 5, 18, 12, 0))
        wrote = record_if_changed(_mk_model(7.005), source="b",
                                  path=self.path,
                                  now=datetime(2026, 5, 18, 12, 1))
        self.assertFalse(wrote)
        self.assertEqual(len(read_log(self.path)), 1)

    def test_significant_change_writes_new_entry(self) -> None:
        record_if_changed(_mk_model(7.0), source="a", path=self.path,
                          now=datetime(2026, 5, 18, 12, 0))
        wrote = record_if_changed(_mk_model(6.5), source="b",
                                  path=self.path,
                                  now=datetime(2026, 5, 18, 21, 0))
        self.assertTrue(wrote)
        log = read_log(self.path)
        self.assertEqual(len(log), 2)
        self.assertAlmostEqual(log[1].coefficient, 6.5, places=4)
        self.assertEqual(log[1].source, "b")

    def test_n_observations_change_writes_entry(self) -> None:
        """Same coefficient, but n_obs changed (e.g. the first day of
        real data lands) → must log. The user wants to see the
        transition from default-stub to actual fit."""
        record_if_changed(_mk_model(7.0, n=0),
                          source="default", path=self.path,
                          now=datetime(2026, 5, 18, 12, 0))
        wrote = record_if_changed(_mk_model(7.0, n=1),
                                  source="first-day-fit",
                                  path=self.path,
                                  now=datetime(2026, 5, 18, 21, 0))
        self.assertTrue(wrote)
        self.assertEqual(len(read_log(self.path)), 2)

    def test_confidence_tier_change_writes_entry(self) -> None:
        """Same coef, n_obs ticks across the medium threshold (>=3)
        → confidence flips low → medium → log."""
        record_if_changed(_mk_model(7.0, n=2),
                          source="day2", path=self.path,
                          now=datetime(2026, 5, 19, 21, 0))
        wrote = record_if_changed(_mk_model(7.0, n=3),
                                  source="day3", path=self.path,
                                  now=datetime(2026, 5, 20, 21, 0))
        self.assertTrue(wrote)
        log = read_log(self.path)
        self.assertEqual(len(log), 2)
        self.assertEqual(log[1].confidence, "medium")

    def test_is_meaningful_change_thresholds(self) -> None:
        prev = LogEntry(ts="", coefficient=7.0, n_observations=1,
                        confidence="low", source="", notes="")
        # Comfortably above the 0.01 threshold → meaningful.
        # (Using 7.011 instead of exactly 7.01 to dodge IEEE float
        # rounding — 7.01 − 7.0 ≈ 0.00999... which trips a strict >=.)
        self.assertTrue(is_meaningful_change(prev,
                                             _mk_model(7.011, n=1)))
        # Below threshold + same n & confidence → not meaningful
        self.assertFalse(is_meaningful_change(prev,
                                              _mk_model(7.005, n=1)))

    def test_idempotent_on_repeated_no_change_calls(self) -> None:
        """Calling record_if_changed many times with the same model
        produces exactly one row — protects against the dashboard
        subprocess-cached advisor pinging this on every refresh."""
        m = _mk_model(7.0)
        for _ in range(5):
            record_if_changed(m, source="repeat", path=self.path,
                              now=datetime(2026, 5, 18, 12, 0))
        self.assertEqual(len(read_log(self.path)), 1)


if __name__ == "__main__":
    unittest.main()
