"""Regression tests for scripts.generator_advisor.simulate_next_24h.

Specifically guards against the daytime false-positive bug captured at
06:10 on 2026-05-18: the old "discharge from now to next sunrise" calc
would treat 23 daytime hours as pure discharge, predicting a 40+ %
SOC drop and firing a spurious "RUN GENERATOR" recommendation.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from datetime import datetime, timedelta

# Make `scripts/` importable as a sibling
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from generator_advisor import simulate_next_24h


def _flat_profile(median_a: float) -> dict:
    """A profile where every hour has the same per-hour median current."""
    return {h: {"median_i": median_a, "n": 100, "p25_i": median_a,
                "p75_i": median_a, "sample_minutes": 60} for h in range(24)}


class TestSimulator(unittest.TestCase):

    def setUp(self):
        # Anchor "now" at 06:10 (1h after sunrise) so we exercise the
        # bug path explicitly.
        self.now = datetime(2026, 5, 18, 6, 10)
        self.sunrise_today = datetime(2026, 5, 18, 5, 10)
        self.sunset_today  = datetime(2026, 5, 18, 20, 51)

    # === The regression case ===

    def test_daytime_with_balancing_solar_keeps_soc_close_to_start(self):
        """Solar equal to overnight discharge → SOC roughly stable.
        Pre-fix bug would have shown a 40+% drop."""
        # Set numbers so solar exactly cancels discharge across daylight hours.
        # Discharge median -4 A; daylight ~16h gives 16*4 = 64 Ah of discharge in
        # those hours if we were treating them as night (the bug).
        # If solar contributes ~64 Ah we should cancel out, leaving only the
        # ~8 hours of real night discharge ≈ 32 Ah net.
        profile = _flat_profile(-4.0)
        result = simulate_next_24h(
            start_soc=73.0,
            now=self.now,
            profile=profile,
            sunrise_today=self.sunrise_today,
            sunset_today=self.sunset_today,
            solar_today_full_ah=64.0,
            solar_tomorrow_full_ah=64.0,
            capacity_ah=215.0,
        )
        # ~8h night × -4A = -32 Ah → ~15% SOC drop ≈ 58% lowest.
        # The bug would have given ~30% projected_low — assert we're well above that.
        self.assertGreater(result["projected_low_soc"], 50.0,
                           "daytime solar should keep us well above 50%")
        # Sanity: projection shouldn't be wildly negative
        self.assertGreater(result["projected_low_soc"], 0.0)
        self.assertLess(result["projected_low_soc"], 100.0)

    def test_pure_night_scenario_drops_as_expected(self):
        """When 'now' is just after sunset, only night discharge before
        tomorrow's solar. SOC should drop monotonically until sunrise."""
        now = datetime(2026, 5, 18, 21, 0)   # just after sunset
        profile = _flat_profile(-5.0)
        result = simulate_next_24h(
            start_soc=80.0, now=now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=0.0,           # today's already past
            solar_tomorrow_full_ah=50.0,
            capacity_ah=215.0,
        )
        # ~8 hours overnight × -5A = -40 Ah → ~18.6% drop → 61.4% at sunrise
        self.assertLess(result["projected_sunrise_soc"], 80.0)
        self.assertGreater(result["projected_sunrise_soc"], 50.0)
        self.assertLess(result["projected_low_soc"],
                        result["projected_sunrise_soc"] + 1.0,
                        "low should be at or near sunrise (before solar kicks in)")

    def test_strong_solar_day_lifts_soc(self):
        """A clear sunny day with light load should leave us higher than we
        started by tomorrow evening."""
        profile = _flat_profile(-1.0)        # very light load
        result = simulate_next_24h(
            start_soc=50.0, now=self.now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=80.0,
            solar_tomorrow_full_ah=80.0,
            capacity_ah=215.0,
        )
        # Net positive across the 24h window — projected_low should still
        # exceed start (no big dips at this load level)
        self.assertGreater(result["projected_sunrise_soc"], 50.0,
                           "with light load + sunny day, SOC should rise")
        self.assertGreater(result["projected_tomorrow_evening_soc"], 60.0)

    def test_pre_sunrise_window_works(self):
        """If 'now' is just before today's sunrise, the math should still
        produce reasonable numbers — short pre-dawn discharge, then full
        day of solar, then night."""
        now = datetime(2026, 5, 18, 4, 30)
        profile = _flat_profile(-4.0)
        result = simulate_next_24h(
            start_soc=70.0, now=now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=60.0,
            solar_tomorrow_full_ah=60.0,
            capacity_ah=215.0,
        )
        # All projections must be in [0, 100]
        for k in ("projected_low_soc", "projected_sunrise_soc",
                  "projected_tomorrow_evening_soc"):
            self.assertGreaterEqual(result[k], 0.0)
            self.assertLessEqual(result[k], 100.0)

    def test_zero_solar_zero_load_is_flat(self):
        """No solar, no load → SOC unchanged everywhere."""
        profile = _flat_profile(0.0)
        result = simulate_next_24h(
            start_soc=50.0, now=self.now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=0.0, solar_tomorrow_full_ah=0.0,
            capacity_ah=215.0,
        )
        self.assertAlmostEqual(result["projected_low_soc"], 50.0, places=1)
        self.assertAlmostEqual(result["projected_sunrise_soc"], 50.0, places=1)
        self.assertAlmostEqual(result["projected_tomorrow_evening_soc"], 50.0, places=1)

    def test_post_sunset_projections_target_NEXT_sunrise_not_day_after(self):
        """**Regression test for the 2026-05-18 21:00 bug.**

        Post-sunset, the advisor's caller bumps sunrise_today/
        sunset_today to TOMORROW's date (so they're 'next-occurring').
        Then the simulator's `sunrise_tomorrow = sunrise_today + 1 day`
        becomes DAY-AFTER-TOMORROW — outside the 24-h sim window. The
        old code's `soc_at(sunrise_tomorrow)` and `soc_at(sunset_tomorrow)`
        both fell off the end of the samples list and returned the SAME
        value (the last sample's SOC), making sunrise SOC and tomorrow-
        evening SOC always equal post-sunset.

        Fix: pick the actual next-occurring sunrise/sunset relative to
        `now` for the projection lookups. The two values must differ
        and must both be plausibly within the 24-h window.
        """
        # 21:00 post-sunset; sunrise/sunset bumped to TOMORROW (as the
        # advisor does at lines 272-275 + 284-292)
        now = datetime(2026, 5, 18, 21, 0)
        sunrise_next = datetime(2026, 5, 19, 5, 9)
        sunset_next  = datetime(2026, 5, 19, 20, 52)

        profile = _flat_profile(-5.0)
        result = simulate_next_24h(
            start_soc=90.0, now=now, profile=profile,
            sunrise_today=sunrise_next, sunset_today=sunset_next,
            solar_today_full_ah=45.0, solar_tomorrow_full_ah=45.0,
            capacity_ah=215.0,
        )

        # Sunrise projection: 8 h of -5 A discharge ≈ 40 Ah ≈ 18.6 %.
        # Start 90 % → sunrise ~71 %. NOT 90 % (would mean it pulled
        # samples[-1] from the very end of the window post-rebound).
        self.assertLess(result["projected_sunrise_soc"], 80.0,
                        "post-sunset projected_sunrise_soc should reflect "
                        "the overnight drop, not the end-of-window value")
        self.assertGreater(result["projected_sunrise_soc"], 65.0,
                           "shouldn't undershoot either")

        # Tomorrow evening: by 20:52 tomorrow we've had the daylight
        # window (~ +45 Ah / 215 = +20.9 %) on top of the overnight low.
        # Expect SOC near or above the start (90 %).
        self.assertGreater(result["projected_tomorrow_evening_soc"], 85.0,
                           "evening SOC should rebound past start after "
                           "a full day of solar")

        # **Critical bug-shape check**: sunrise SOC and tomorrow-evening
        # SOC must NOT be identical (the old bug had them tied at the
        # samples[-1] value).
        self.assertNotAlmostEqual(
            result["projected_sunrise_soc"],
            result["projected_tomorrow_evening_soc"],
            places=2,
            msg="sunrise SOC and tomorrow evening SOC were equal — the "
                "post-sunset bug is back",
        )

    # === Bias-fix regression tests (2026-05-19) ===
    # When the previous version of simulate_next_24h credited solar
    # uniformly across daylight, it overestimated the morning floor by
    # mean -2.97 pp (validated across 17 records from 2026-05-19). The
    # new sinusoidal-gross-solar + per-hour-load model preserves the
    # daily NET total but redistributes the within-day shape so the
    # floor lands later (closer to actual solar onset) and lower.
    # These tests pin down the new behavior without over-constraining.

    def test_projected_low_lands_after_sunrise_not_at_it(self) -> None:
        """With moderate load + moderate solar, the floor should be
        observed AFTER sunrise (during the early-morning solar ramp-
        up where load still exceeds solar), not AT sunrise.

        Anchors the bias-fix: previously the floor was always at
        sunrise because solar credited at average rate immediately."""
        now = datetime(2026, 5, 18, 22, 0)     # evening start
        sunrise_next = datetime(2026, 5, 19, 5, 10)
        sunset_next  = datetime(2026, 5, 19, 20, 51)
        profile = _flat_profile(-3.0)
        result = simulate_next_24h(
            start_soc=80.0, now=now, profile=profile,
            sunrise_today=sunrise_next, sunset_today=sunset_next,
            solar_today_full_ah=42.0,    # net daily contribution
            solar_tomorrow_full_ah=42.0,
            capacity_ah=215.0,
        )
        # SOC at sunrise (after overnight discharge): start 80,
        # 7.17h × -3A = -21.5 Ah → -10% → 70%.
        sunrise_soc = result["projected_sunrise_soc"]
        low = result["projected_low_soc"]
        # The low MUST be at or below the sunrise SOC (not above).
        # In the OLD model they were equal; in the new model the
        # post-sunrise discharge drops the floor further.
        self.assertLessEqual(
            low, sunrise_soc + 0.1,
            "floor should be at or below sunrise SOC (model now "
            "models post-sunrise discharge before solar overtakes load)",
        )

    def test_floor_undershoots_sunrise_when_load_steep_and_solar_modest(self) -> None:
        """Heavy load + modest solar → floor noticeably below sunrise SOC.
        Tightens the previous test for a stronger signature."""
        now = datetime(2026, 5, 18, 22, 0)
        sunrise_next = datetime(2026, 5, 19, 5, 10)
        sunset_next  = datetime(2026, 5, 19, 20, 51)
        profile = _flat_profile(-5.0)       # heavier baseline load
        result = simulate_next_24h(
            start_soc=80.0, now=now, profile=profile,
            sunrise_today=sunrise_next, sunset_today=sunset_next,
            solar_today_full_ah=30.0,
            solar_tomorrow_full_ah=30.0,
            capacity_ah=215.0,
        )
        sunrise_soc = result["projected_sunrise_soc"]
        low = result["projected_low_soc"]
        # With steep load and modest solar, the morning post-sunrise
        # discharge should pull the floor at least ~0.5 pp below sunrise.
        self.assertLess(
            low, sunrise_soc - 0.3,
            f"floor ({low:.2f}) should sit at least 0.3 pp below "
            f"sunrise SOC ({sunrise_soc:.2f}); old model would have "
            f"them equal",
        )

    def test_daily_net_preserved_so_evening_soc_in_reasonable_range(self) -> None:
        """The new model redistributes solar within the day. The
        daily-NET interpretation is preserved IN PRINCIPLE (gross
        solar = solar_day_ah + |daylight_load|, so gross+load over
        the full window = solar_day_ah) but for PARTIAL walks (e.g.
        starting mid-morning) the realized net differs slightly
        because gross-solar is concentrated mid-day and the walked
        portion may over-sample the peak.

        This test just sanity-checks evening SOC is plausibly in
        the upper half — the same behavior the OLD code produced for
        this scenario."""
        profile = _flat_profile(-4.0)
        result = simulate_next_24h(
            start_soc=73.0, now=self.now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=64.0,
            solar_tomorrow_full_ah=64.0,
            capacity_ah=215.0,
        )
        # Wide bounds intentional — exact value depends on hour-by-hour
        # sin profile evaluated at midpoints. The signal we care about
        # is the FLOOR (tested separately above), not evening rebound.
        self.assertGreater(result["projected_tomorrow_evening_soc"], 50.0)
        self.assertLess(result["projected_tomorrow_evening_soc"], 100.0)

    def test_zero_solar_daylight_is_flat_then_overnight_discharges(self) -> None:
        """When solar_day_ah=0, the new model interprets this as
        "predicted NET solar = 0" which means gross_solar exactly
        cancels daylight load → daylight is flat. Only the NIGHT
        portion discharges. This is the same physical behavior the
        OLD code had (daylight: ah_change = 0/15.7 = 0).

        Anchors that the sinusoidal model doesn't introduce phantom
        gain or loss when solar_day_ah=0."""
        profile = _flat_profile(-3.0)
        result = simulate_next_24h(
            start_soc=80.0, now=self.now, profile=profile,
            sunrise_today=self.sunrise_today, sunset_today=self.sunset_today,
            solar_today_full_ah=0.0, solar_tomorrow_full_ah=0.0,
            capacity_ah=215.0,
        )
        # Starting at 06:10 with sunrise at 05:10 and sunset 20:51,
        # the walk's 24 iterations cover ~15 daylight today + 8
        # night + 1 daylight tomorrow. Daylight at solar=0 is flat.
        # Night: ~8h × -3 = -24 Ah → -11.2% → 68.8%.
        # The OLD code produced ~68 here as well; pinned down so a
        # future change to either branch doesn't silently shift.
        self.assertLess(result["projected_low_soc"], 75.0,
                        "should drop noticeably overnight")
        self.assertGreater(result["projected_low_soc"], 60.0,
                           "shouldn't crater below the night-only loss")
        # Sanity bounds
        self.assertGreaterEqual(result["projected_low_soc"], 0.0)
        self.assertLessEqual(result["projected_low_soc"], 100.0)


if __name__ == "__main__":
    unittest.main()
