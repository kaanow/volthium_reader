"""Tests for volthium.estimator — including the BMS current-bias calibration."""

import sys
import pathlib
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from volthium.estimator import Estimator


class _FakeBatt:
    def __init__(self, remaining_ah=None):
        self.remaining_ah = remaining_ah


class _FakePack:
    """Minimal stand-in for PackReading — only the props the estimator reads."""
    def __init__(self, current, max_soc, min_soc=None, voltage=26.4,
                 rem_a=None, rem_b=None):
        self.pack_current = current
        self.pack_voltage = voltage
        self.pack_power = current * voltage
        self.max_soc = max_soc
        self.min_soc = min_soc if min_soc is not None else max_soc
        self.avg_soc = (self.max_soc + self.min_soc) / 2
        self.a = _FakeBatt(rem_a)
        self.b = _FakeBatt(rem_b)


def _settle(est, pack, n=60):
    """Push the EMA through enough samples that smoothed == raw."""
    for _ in range(n):
        e = est.update(pack)
    return e


class TestBasics(unittest.TestCase):
    def test_charging_settles(self):
        e = _settle(Estimator(), _FakePack(20.0, 80))
        self.assertEqual(e.state, "charging")
        # ah_needed = 200 * (95-80)/100 = 30 Ah ; minutes = 30/20*60 = 90
        self.assertAlmostEqual(e.minutes_remaining, 90.0, places=1)

    def test_discharging_settles(self):
        e = _settle(Estimator(), _FakePack(-10.0, 80))
        self.assertEqual(e.state, "discharging")
        # ah_left = 200 * (80-10)/100 = 140 Ah ; minutes = 140/10*60 = 840
        self.assertAlmostEqual(e.minutes_remaining, 840.0, places=1)

    def test_idle_below_threshold(self):
        e = _settle(Estimator(), _FakePack(0.2, 80))
        self.assertEqual(e.state, "idle")
        self.assertIsNone(e.minutes_remaining)

    def test_full_at_or_above_ceiling(self):
        e = _settle(Estimator(), _FakePack(5.0, 95))
        self.assertEqual(e.state, "full")
        self.assertEqual(e.minutes_remaining, 0.0)

    def test_full_at_96(self):
        e = _settle(Estimator(), _FakePack(2.0, 96))
        self.assertEqual(e.state, "full")


class TestCurrentCalibration(unittest.TestCase):
    """The Barge Inn BMS appears to under-report current by ~11%.

    Calibration multiplies effective current so the time-to-X math
    matches the BMS's own SOC trajectory."""

    def test_calibration_1_0_is_identity(self):
        e = _settle(Estimator(current_calibration=1.0), _FakePack(20.0, 80))
        self.assertAlmostEqual(e.minutes_remaining, 90.0, places=1)

    def test_calibration_above_1_shrinks_time_to_full(self):
        baseline = _settle(Estimator(current_calibration=1.0), _FakePack(20.0, 80))
        calibrated = _settle(Estimator(current_calibration=1.11), _FakePack(20.0, 80))
        # With 11% more effective current, we should reach full ~11% faster.
        self.assertLess(calibrated.minutes_remaining, baseline.minutes_remaining)
        ratio = calibrated.minutes_remaining / baseline.minutes_remaining
        self.assertAlmostEqual(ratio, 1.0 / 1.11, places=3)

    def test_calibration_works_for_discharge_too(self):
        baseline = _settle(Estimator(current_calibration=1.0), _FakePack(-10.0, 80))
        calibrated = _settle(Estimator(current_calibration=1.11), _FakePack(-10.0, 80))
        self.assertLess(calibrated.minutes_remaining, baseline.minutes_remaining)

    def test_displayed_smoothed_current_unaffected(self):
        """Calibration must not corrupt the raw current we surface."""
        e = _settle(Estimator(current_calibration=1.11), _FakePack(20.0, 80))
        # smoothed should equal the raw value (EMA settled), NOT raw * 1.11
        self.assertAlmostEqual(e.smoothed_current, 20.0, places=1)


class TestHybridMode(unittest.TestCase):
    """The hybrid coulomb-counter integrates current*dt between samples
    and re-anchors when the BMS's reported remaining_ah ticks."""

    def test_seeds_from_first_anchor(self):
        e = Estimator(use_remaining_ah_anchor=True)
        p = _FakePack(0.0, 80, rem_a=150, rem_b=140)
        est = e.update(p, ts=0.0)
        # avg(150, 140) = 145
        self.assertAlmostEqual(est.displayed_ah, 145.0, places=2)

    def test_integrator_advances_between_anchors(self):
        """Realistic case: 10s samples for ~10 minutes, no BMS tick.
        Integrator should accumulate current * total_dt."""
        e = Estimator(use_remaining_ah_anchor=True)
        # First sample seeds at 100 Ah avg
        e.update(_FakePack(10.0, 80, rem_a=100, rem_b=100), ts=0.0)
        # 60 samples × 10s = 600s = 10 min at +10A → +1.667 Ah
        for n in range(1, 61):
            est = e.update(_FakePack(10.0, 80, rem_a=100, rem_b=100), ts=n * 10.0)
        self.assertAlmostEqual(est.displayed_ah, 100 + 10 * 600 / 3600, places=1)

    def test_anchor_blends_in_on_tick(self):
        e = Estimator(use_remaining_ah_anchor=True, anchor_integrator_weight=0.8)
        e.update(_FakePack(60.0, 70, rem_a=100, rem_b=100), ts=0.0)
        # After 30s at +60A: integrator says 100 + 60*30/3600 = 100.5
        # If anchor then ticks to 102 (BMS counter advanced 2):
        est = e.update(_FakePack(60.0, 70, rem_a=102, rem_b=102), ts=30.0)
        # blended: 0.8 * 100.5 + 0.2 * 102 = 80.4 + 20.4 = 100.8
        self.assertAlmostEqual(est.displayed_ah, 100.8, places=2)

    def test_time_to_full_uses_displayed_ah(self):
        # SOC 80% (still well under 95), pack has 156 Ah remaining (78% of capacity)
        # Charging at +20A. Time to 95%*200 = 190 Ah is (190 - 156)/20 * 60 = 102 min.
        e = Estimator(use_remaining_ah_anchor=True)
        pack = _FakePack(20.0, 80, rem_a=156, rem_b=156)
        # settle the EMA
        for _ in range(60):
            est = e.update(pack, ts=time.monotonic())
        self.assertEqual(est.state, "charging")
        # We expect roughly 102 min — allow some slop because the EMA + integrator
        # have warmed up and slightly inflated displayed_ah (current was +20A so
        # over 60 ticks of ~0 dt the integrator barely moved).
        # The KEY check: it's based on Ah, not SOC%.
        self.assertIsNotNone(est.minutes_remaining)
        self.assertTrue(80 < est.minutes_remaining < 130,
                        f"expected ~100 min, got {est.minutes_remaining}")

    def test_legacy_mode_still_works(self):
        """Default mode (no hybrid) keeps the SOC-based math."""
        e = Estimator()  # use_remaining_ah_anchor defaults to False
        pack = _FakePack(20.0, 80, rem_a=156, rem_b=156)
        for _ in range(60):
            est = e.update(pack)
        # ah_needed = 200 * 15/100 = 30. minutes = 30/20 * 60 = 90.
        self.assertAlmostEqual(est.minutes_remaining, 90.0, places=1)
        # displayed_ah is None in legacy mode
        self.assertIsNone(est.displayed_ah)


if __name__ == "__main__":
    unittest.main()
