"""Tests for `scripts.projection_accuracy.compute_accuracy_records`.

Fixture pack samples + projection_log entries, anchor `now` at a
known point, verify which projections become validatable and what
errors come out. Especially important to lock down BEFORE the first
real-data validation lands tomorrow morning — once this code is
running on live data, regressions would be silent.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import projection_log as projection_log_mod  # noqa: E402
from projection_accuracy import (  # noqa: E402
    compute_accuracy_records,
    summarize,
)


def _entry(ts: str, sunrise: str, projected: float, coef: float = 8.15):
    """Compact constructor matching projection_log.LogEntry fields."""
    return projection_log_mod.LogEntry(
        ts=ts,
        start_soc_pct=80.0,
        projected_sunrise_soc=projected,
        projected_tomorrow_evening_soc=88.0,
        projected_low_soc=68.0,
        solar_model_coefficient=coef,
        today_irradiance_kwh_m2=5.0,
        sunrise_iso=sunrise,
        source="advisor-invocation",
    )


def _pack_samples(*pairs):
    """[(iso_ts, soc_a, soc_b), ...] → list[(datetime, soc_avg)]"""
    return [
        (datetime.fromisoformat(ts), (sa + sb) / 2.0)
        for ts, sa, sb in pairs
    ]


class TestProjectionAccuracy(unittest.TestCase):

    def test_returns_empty_when_no_entries(self) -> None:
        result = compute_accuracy_records(
            [], _pack_samples(),
            now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(result, [])

    def test_future_targets_are_skipped(self) -> None:
        """A projection whose sunrise_iso is still in the future
        can't be validated yet — skip rather than crash."""
        entries = [_entry("2026-05-18T22:00:00",
                          "2026-05-19T05:09", projected=70.0)]
        result = compute_accuracy_records(
            entries, _pack_samples(),
            now=datetime(2026, 5, 19, 0, 0),    # before sunrise
        )
        self.assertEqual(result, [])

    def test_matches_passed_target_to_closest_pack_sample(self) -> None:
        """sunrise at 05:09; pack samples at 05:00, 05:09, 05:20 →
        the 05:09 sample wins (closest)."""
        entries = [_entry("2026-05-18T22:00:00",
                          "2026-05-19T05:09", projected=70.0)]
        samples = _pack_samples(
            ("2026-05-19T05:00:00", 71.0, 70.0),   # 71/70 avg = 70.5
            ("2026-05-19T05:09:00", 72.0, 71.0),   # 72/71 avg = 71.5  ← match
            ("2026-05-19T05:20:00", 73.0, 72.0),
        )
        result = compute_accuracy_records(
            entries, samples,
            now=datetime(2026, 5, 19, 8, 0),
        )
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertAlmostEqual(r.actual_sunrise_soc, 71.5, places=2)
        # error = actual − projected = 71.5 − 70.0 = +1.5
        self.assertAlmostEqual(r.error_pct_points, +1.5, places=2)
        self.assertEqual(r.sample_offset_min, 0.0)

    def test_match_within_tolerance_only(self) -> None:
        """If no pack sample lies within ±tolerance_min of the target,
        the projection is unmatched and silently dropped."""
        entries = [_entry("2026-05-18T22:00:00",
                          "2026-05-19T05:09", projected=70.0)]
        # Closest sample is 45 min away → outside default 30-min tolerance
        samples = _pack_samples(
            ("2026-05-19T04:24:00", 70.0, 69.0),
        )
        result = compute_accuracy_records(
            entries, samples,
            now=datetime(2026, 5, 19, 8, 0),
            tolerance_min=30.0,
        )
        self.assertEqual(result, [])

    def test_negative_error_means_pack_undershot(self) -> None:
        """If the projection said 75 % and reality landed at 70 %,
        error = actual − projected = −5 (pack did worse than predicted)."""
        entries = [_entry("2026-05-18T22:00:00",
                          "2026-05-19T05:09", projected=75.0)]
        samples = _pack_samples(
            ("2026-05-19T05:09:00", 70.0, 70.0),    # 70/70 avg = 70
        )
        result = compute_accuracy_records(
            entries, samples,
            now=datetime(2026, 5, 19, 8, 0),
        )
        self.assertAlmostEqual(result[0].error_pct_points, -5.0, places=2)

    def test_mixed_past_and_future_targets(self) -> None:
        """Pack of projections — some valid, some still-future. Result
        should only contain the past ones."""
        entries = [
            _entry("2026-05-17T22:00:00",
                   "2026-05-18T05:10", projected=70.0),   # past
            _entry("2026-05-18T22:00:00",
                   "2026-05-19T05:09", projected=68.0),   # past
            _entry("2026-05-19T22:00:00",
                   "2026-05-20T05:08", projected=66.0),   # future
        ]
        samples = _pack_samples(
            ("2026-05-18T05:10:00", 72.0, 72.0),
            ("2026-05-19T05:09:00", 70.0, 69.0),
        )
        result = compute_accuracy_records(
            entries, samples,
            now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(len(result), 2)
        # First: 72 actual - 70 projected = +2.0
        self.assertAlmostEqual(result[0].error_pct_points, +2.0, places=2)
        # Second: 69.5 actual - 68 projected = +1.5
        self.assertAlmostEqual(result[1].error_pct_points, +1.5, places=2)

    def test_summarize_empty_records(self) -> None:
        self.assertEqual(summarize([]), {"n": 0})

    def test_summarize_aggregates_correctly(self) -> None:
        """Mean / RMS / mean-abs over a small set of records."""
        entries = [
            _entry("2026-05-18T22:00:00",
                   "2026-05-19T05:09", projected=70.0),
            _entry("2026-05-17T22:00:00",
                   "2026-05-18T05:10", projected=72.0),
            _entry("2026-05-16T22:00:00",
                   "2026-05-17T05:11", projected=74.0),
        ]
        # Actuals: 72, 70, 75 → errors +2, -2, +1
        samples = _pack_samples(
            ("2026-05-17T05:11:00", 75.0, 75.0),
            ("2026-05-18T05:10:00", 70.0, 70.0),
            ("2026-05-19T05:09:00", 72.0, 72.0),
        )
        result = compute_accuracy_records(
            entries, samples,
            now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(len(result), 3)
        s = summarize(result)
        self.assertEqual(s["n"], 3)
        # errors are +1, -2, +2  (sorted by projection ts):
        #   2026-05-16 -> +1
        #   2026-05-17 -> -2
        #   2026-05-18 -> +2
        # mean = (1 - 2 + 2) / 3 = 0.33; abs mean = 5/3 = 1.67;
        # RMS = sqrt((1+4+4)/3) = sqrt(3) ≈ 1.73
        self.assertAlmostEqual(s["mean_error"], 0.33, places=2)
        self.assertAlmostEqual(s["mean_abs_error"], 1.67, places=2)
        self.assertAlmostEqual(s["rms_error"], 1.73, places=2)
        self.assertAlmostEqual(s["min_error"], -2.0, places=2)
        self.assertAlmostEqual(s["max_error"], +2.0, places=2)


if __name__ == "__main__":
    unittest.main()
