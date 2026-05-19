"""Tests for `scripts.low_soc_accuracy`.

Sister test of `test_projection_accuracy.py`. The module matches
projection_log entries to solar_onset rows by target date and
computes error = actual_low − projected_low_soc.

We pin down: matching rules, future-target skipping, projection-
made-AFTER-onset skipping (degenerate "prediction" of history),
horizon_min calculation, missing-onset-row handling.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import projection_log as projection_log_mod  # noqa: E402
import solar_onset as solar_onset_mod  # noqa: E402
from low_soc_accuracy import (  # noqa: E402
    compute_accuracy_records,
    summarize,
    summarize_by_horizon,
)


def _proj(ts: str, sunrise_iso: str, projected_low: float,
          coef: float = 8.15):
    """Compact constructor mapping to projection_log.LogEntry."""
    return projection_log_mod.LogEntry(
        ts=ts,
        start_soc_pct=80.0,
        projected_sunrise_soc=70.0,
        projected_tomorrow_evening_soc=88.0,
        projected_low_soc=projected_low,
        solar_model_coefficient=coef,
        today_irradiance_kwh_m2=5.0,
        sunrise_iso=sunrise_iso,
        source="advisor-invocation",
    )


def _onset(date_iso: str, first_net_positive_iso: str,
           soc_at_net: float, smoothed_at_net: float = 0.5):
    return solar_onset_mod.SolarOnsetRecord(
        date=date_iso,
        first_zero_iso=first_net_positive_iso,
        first_idle_iso=first_net_positive_iso,
        first_positive_iso=first_net_positive_iso,
        first_net_positive_iso=first_net_positive_iso,
        smoothed_i_at_net_positive=smoothed_at_net,
        soc_avg_at_net_positive=soc_at_net,
    )


class TestLowSocAccuracy(unittest.TestCase):

    def test_no_records_when_no_data(self) -> None:
        self.assertEqual(
            compute_accuracy_records([], [], now=datetime(2026, 5, 19, 12, 0)),
            [],
        )

    def test_basic_match_computes_signed_error(self) -> None:
        """Projection predicted floor=68, actual was 63.5 →
        error = 63.5 − 68 = −4.5 (advisor was optimistic)."""
        projs = [_proj("2026-05-18T22:14:46",
                       "2026-05-19T05:08", projected_low=68.0)]
        onsets = [_onset("2026-05-19",
                         "2026-05-19T07:45:40", soc_at_net=63.5)]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(len(recs), 1)
        self.assertAlmostEqual(recs[0].actual_low_soc, 63.5)
        self.assertAlmostEqual(recs[0].projected_low_soc, 68.0)
        self.assertAlmostEqual(recs[0].error_pct_points, -4.5, places=2)
        self.assertEqual(recs[0].target_date, "2026-05-19")

    def test_horizon_min_from_projection_to_net_positive(self) -> None:
        """horizon_min = net_positive_iso − projection_ts in minutes."""
        # Projection at 22:14, net_positive at 07:45 next day → 9h 31m = 571 min
        projs = [_proj("2026-05-18T22:14:00",
                       "2026-05-19T05:08", projected_low=68.0)]
        onsets = [_onset("2026-05-19",
                         "2026-05-19T07:45:00", soc_at_net=63.5)]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        # 22:14 → 07:45 = 9h 31m = 571 min
        self.assertAlmostEqual(recs[0].horizon_min, 571.0, delta=1.0)

    def test_skip_when_onset_missing_first_net_positive(self) -> None:
        """A solar_onset row with first_net_positive=None is still
        pre-resolved; we must NOT use it (no actual_low yet)."""
        projs = [_proj("2026-05-18T22:14:46",
                       "2026-05-19T05:08", projected_low=68.0)]
        # Onset row exists but only has first_zero — not yet resolved
        onsets = [solar_onset_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
            first_idle_iso="2026-05-19T06:44:10",
            first_positive_iso=None,
            first_net_positive_iso=None,
            smoothed_i_at_net_positive=None,
            soc_avg_at_net_positive=None,
        )]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(recs, [])

    def test_skip_when_no_onset_row_for_target_day(self) -> None:
        """Projection targets a day whose solar_onset row doesn't
        exist yet — must skip (e.g. future days, or days where no
        onset was logged)."""
        projs = [_proj("2026-05-19T22:14:46",
                       "2026-05-20T05:08", projected_low=65.0)]
        onsets = [_onset("2026-05-19",     # different day
                         "2026-05-19T07:45:00", soc_at_net=63.5)]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 23, 0),
        )
        self.assertEqual(recs, [])

    def test_skip_when_projection_made_after_onset(self) -> None:
        """A projection made AFTER first_net_positive is "predicting"
        history — degenerate, must be excluded. Otherwise the
        accuracy stat would be artificially perfect."""
        projs = [_proj("2026-05-19T10:00:00",      # AFTER 07:45 net+
                       "2026-05-20T05:08", projected_low=63.5)]
        onsets = [_onset("2026-05-19",
                         "2026-05-19T07:45:40", soc_at_net=63.5)]
        # The projection targets tomorrow's sunrise, so it'd match
        # via target_date in a buggy version — guard explicitly.
        # But our sunrise_iso is 2026-05-20, so it should match
        # the 2026-05-20 row, which doesn't exist → empty.
        # Edge case: same-day mismatch where projection targets
        # today's date AFTER onset.
        projs2 = [_proj("2026-05-19T10:00:00",
                        "2026-05-19T05:08", projected_low=63.5)]
        recs = compute_accuracy_records(
            projs2, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(recs, [],
                         "Projection made AFTER net_positive must be skipped")

    def test_multiple_records_with_different_lead_times(self) -> None:
        """Two projections at different horizons → both validated;
        per-horizon summary groups them correctly."""
        projs = [
            _proj("2026-05-18T22:14:00",     # ~9.5h ahead
                  "2026-05-19T05:08", projected_low=68.0),
            _proj("2026-05-19T06:43:00",     # ~1h ahead
                  "2026-05-19T05:08", projected_low=64.0),
        ]
        onsets = [_onset("2026-05-19",
                         "2026-05-19T07:45:00", soc_at_net=63.5)]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        self.assertEqual(len(recs), 2)
        # First: error = 63.5 − 68 = −4.5; horizon ~571 min → 7h+
        # Second: error = 63.5 − 64 = −0.5; horizon ~62 min → 1-2h
        s = summarize(recs)
        self.assertEqual(s["n"], 2)
        # mean = (−4.5 + −0.5)/2 = −2.5
        self.assertAlmostEqual(s["mean_error"], -2.5, places=2)
        self.assertAlmostEqual(s["mean_abs_error"], 2.5, places=2)

        by_h = summarize_by_horizon(recs)
        labels = [b["bucket"] for b in by_h]
        self.assertIn("7h+", labels)
        self.assertIn("1-2h", labels)

    def test_summarize_by_horizon_skips_empty_buckets(self) -> None:
        projs = [_proj("2026-05-19T06:43:00",
                       "2026-05-19T05:08", projected_low=64.0)]
        onsets = [_onset("2026-05-19",
                         "2026-05-19T07:45:00", soc_at_net=63.5)]
        recs = compute_accuracy_records(
            projs, onsets, now=datetime(2026, 5, 19, 12, 0),
        )
        by_h = summarize_by_horizon(recs)
        self.assertEqual(len(by_h), 1)
        self.assertEqual(by_h[0]["bucket"], "1-2h")

    def test_summarize_empty_records(self) -> None:
        self.assertEqual(summarize([]), {"n": 0})
        self.assertEqual(summarize_by_horizon([]), [])


if __name__ == "__main__":
    unittest.main()
