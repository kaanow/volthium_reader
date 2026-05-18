"""Tests for volthium.solar_model.SolarModel."""

import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from volthium.solar_model import (
    SolarModel,
    DEFAULT_AH_PER_KWH_PER_M2,
    MIN_REASONABLE_COEFFICIENT,
    MAX_REASONABLE_COEFFICIENT,
)


class TestPredict(unittest.TestCase):
    def test_default_predicts_with_default_coefficient(self):
        m = SolarModel.default()
        ah = m.predict_ah(kwh_per_m2=5.0)
        self.assertAlmostEqual(ah, 5.0 * DEFAULT_AH_PER_KWH_PER_M2, places=3)

    def test_zero_irradiance_gives_zero(self):
        m = SolarModel.default()
        self.assertEqual(m.predict_ah(0.0), 0.0)
        self.assertEqual(m.predict_ah(-1.0), 0.0)


class TestConfidence(unittest.TestCase):
    def test_no_observations_is_low(self):
        self.assertEqual(SolarModel.default().confidence, "low")

    def test_three_observations_is_medium(self):
        m = SolarModel.fit_from_pairs([(5, 35), (6, 42), (7, 49)])
        self.assertEqual(m.confidence, "medium")

    def test_seven_observations_is_high(self):
        m = SolarModel.fit_from_pairs([(5, 35)] * 7)
        self.assertEqual(m.confidence, "high")


class TestFit(unittest.TestCase):
    def test_fits_through_origin(self):
        # ratios are 7.0 each → coefficient should be 7.0
        m = SolarModel.fit_from_pairs([(5, 35), (6, 42), (7, 49)])
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)
        self.assertEqual(m.n_observations, 3)

    def test_median_is_robust_to_outlier(self):
        # 4 ratios of ~7, plus one outlier of 14 — median still picks 7
        m = SolarModel.fit_from_pairs([
            (5, 35), (6, 42), (7, 49), (5, 70), (8, 56),
        ])
        # ratios: 7, 7, 7, 14, 7 — median = 7
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)

    def test_clamp_high(self):
        m = SolarModel.fit_from_pairs([(5, 500), (6, 600), (7, 700)])
        # ratios all 100 → clamp to MAX_REASONABLE_COEFFICIENT (15)
        self.assertEqual(m.coefficient_ah_per_kwh_m2, MAX_REASONABLE_COEFFICIENT)
        self.assertIn("clamped", m.notes)

    def test_clamp_low(self):
        m = SolarModel.fit_from_pairs([(5, 1), (6, 1.2)])
        # ratios ~0.2 → clamp to MIN_REASONABLE_COEFFICIENT (2)
        self.assertEqual(m.coefficient_ah_per_kwh_m2, MIN_REASONABLE_COEFFICIENT)

    def test_empty_pairs_returns_default(self):
        m = SolarModel.fit_from_pairs([])
        self.assertEqual(m.coefficient_ah_per_kwh_m2, DEFAULT_AH_PER_KWH_PER_M2)
        self.assertEqual(m.n_observations, 0)

    def test_skip_zero_or_negative_inputs(self):
        m = SolarModel.fit_from_pairs([(5, 35), (0, 50), (6, -20), (7, 49)])
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)
        self.assertEqual(m.n_observations, 2)


class TestFitFromDailySummary(unittest.TestCase):
    def test_excludes_short_days(self):
        rows = [
            # explicit partial flag — preferred new behavior
            {"partial": "True",  "duration_h": 6,  "weather_kwh_m2": 5.0, "solar_ah_estimated": 30.0},
            {"partial": "False", "duration_h": 23, "weather_kwh_m2": 6.0, "solar_ah_estimated": 42.0},
            {"partial": "False", "duration_h": 24, "weather_kwh_m2": 7.0, "solar_ah_estimated": 49.0},
        ]
        m = SolarModel.fit_from_daily_summary(rows)
        self.assertEqual(m.n_observations, 2)
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)

    def test_excludes_noon_partial_via_partial_flag(self):
        """Regression test for the 2026-05-18 12:02 bug. A midnight-
        rolling logger has duration_h = 12.1 by noon; the old `> 12`
        rule wrongly admitted it as a complete day and corrupted the
        SolarModel fit (16.4 Ah / 5.34 kWh/m² ≈ 3.1 — way below any
        real coefficient). The `partial=True` flag must veto.
        """
        rows = [
            {"partial": "True",  "duration_h": 12.1, "weather_kwh_m2": 5.34, "solar_ah_estimated": 16.4},
            {"partial": "False", "duration_h": 24.0, "weather_kwh_m2": 5.0,  "solar_ah_estimated": 35.0},  # 7.0
        ]
        m = SolarModel.fit_from_daily_summary(rows)
        self.assertEqual(m.n_observations, 1)
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)

    def test_backcompat_uses_duration_when_partial_absent(self):
        """Older daily_summary.csv files don't have a `partial` column.
        Fall back to a duration check of >= 20 h. The bug-trip case
        (duration_h = 12.1) must still be excluded under fallback."""
        rows = [
            {"duration_h": 12.1, "weather_kwh_m2": 5.34, "solar_ah_estimated": 16.4},   # excluded
            {"duration_h": 19.9, "weather_kwh_m2": 5.0,  "solar_ah_estimated": 35.0},   # also excluded
            {"duration_h": 20.5, "weather_kwh_m2": 6.0,  "solar_ah_estimated": 42.0},   # 7.0
        ]
        m = SolarModel.fit_from_daily_summary(rows)
        self.assertEqual(m.n_observations, 1)
        self.assertAlmostEqual(m.coefficient_ah_per_kwh_m2, 7.0, places=2)

    def test_handles_missing_fields(self):
        rows = [
            {"partial": "False", "duration_h": 24, "weather_kwh_m2": None, "solar_ah_estimated": 42.0},
            {"partial": "False", "duration_h": 24, "weather_kwh_m2": 6.0,  "solar_ah_estimated": None},
            {"partial": "False", "duration_h": 24, "weather_kwh_m2": 7.0,  "solar_ah_estimated": 49.0},
        ]
        m = SolarModel.fit_from_daily_summary(rows)
        self.assertEqual(m.n_observations, 1)


if __name__ == "__main__":
    unittest.main()
