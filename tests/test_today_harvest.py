"""Tests for the today_harvest snapshot.

Focus: the irradiance integrator's flat-extrapolation tail, which fixes
the live-ratio jump artifact at weather-sample boundaries. Without
extrapolation, when weather.csv lags pack.csv (30-min vs 10-s cadence),
the live ratio = harvest/kWh shoots up because the denominator goes
stale while the numerator keeps growing. With extrapolation, the
denominator advances with the most-recent wm2 held flat up to `now`.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.today_harvest import integrate_today_irradiance  # noqa: E402


def _write_weather(path: Path, samples: list[tuple[datetime, float]]) -> None:
    """Write a minimal weather.csv with the columns today_harvest reads."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ts", "lat", "lon", "temperature_c", "cloud_cover_pct",
            "shortwave_radiation_wm2", "wind_speed_ms", "wind_gusts_ms",
            "weather_code", "is_day", "sunrise_iso", "sunset_iso",
            "shortwave_radiation_sum_today_wh_m2", "uv_index_max_today",
        ])
        for ts, wm2 in samples:
            w.writerow([ts.isoformat(), 51.07, -121.2, 10.0, 50,
                        wm2, 1.0, 2.0, 3, 1, "2026-05-18T05:09",
                        "2026-05-18T20:52", 4000.0, 5.0])


class TestIrradianceIntegrator(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "weather.csv"
        self.day = date(2026, 5, 18)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_returns_none_with_no_data(self) -> None:
        _write_weather(self.path, [])
        self.assertIsNone(integrate_today_irradiance(self.path, self.day))

    def test_returns_none_with_one_sample(self) -> None:
        _write_weather(self.path, [(datetime(2026, 5, 18, 10, 0), 500.0)])
        self.assertIsNone(integrate_today_irradiance(self.path, self.day))

    def test_trapezoidal_integration_basic(self) -> None:
        """Two samples at 500 W/m² over 1 hour ⇒ 0.5 kWh/m²."""
        _write_weather(self.path, [
            (datetime(2026, 5, 18, 10, 0), 500.0),
            (datetime(2026, 5, 18, 11, 0), 500.0),
        ])
        # `now` exactly at the last sample → no extrapolation tail.
        result = integrate_today_irradiance(
            self.path, self.day,
            now=datetime(2026, 5, 18, 11, 0),
        )
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_extrapolation_tail_advances_past_last_sample(self) -> None:
        """The artifact fix: between weather samples the integral must
        keep advancing using the last-known wm2, so the live ratio
        doesn't jump at sample boundaries.

        Setup: two samples 500 W/m² apart by 30 min (= 0.25 kWh/m² ).
        Query 'now' 20 min after the last sample. The tail adds
        500 W/m² × 20/60 = 167 Wh/m² = 0.167 kWh/m². Total ≈ 0.417.
        """
        _write_weather(self.path, [
            (datetime(2026, 5, 18, 10, 0), 500.0),
            (datetime(2026, 5, 18, 10, 30), 500.0),
        ])
        result = integrate_today_irradiance(
            self.path, self.day,
            now=datetime(2026, 5, 18, 10, 50),
        )
        # 0.25 (trapezoidal main) + 0.1667 (extrapolation) ≈ 0.4167
        self.assertAlmostEqual(result, 0.4167, places=3)

    def test_extrapolation_capped_at_max_seconds(self) -> None:
        """If the gap is huge (laptop sleeps overnight, weather logger
        stalls), the extrapolation must NOT keep growing forever. Cap
        at max_extrap_seconds (default 2400 s = 40 min) so a missed
        sample doesn't silently inflate the integral.
        """
        _write_weather(self.path, [
            (datetime(2026, 5, 18, 10, 0),  500.0),
            (datetime(2026, 5, 18, 10, 30), 500.0),
        ])
        # 'now' is 6 HOURS later — the tail should be capped to 40 min.
        result = integrate_today_irradiance(
            self.path, self.day,
            now=datetime(2026, 5, 18, 16, 30),
        )
        # 0.25 main + 500 W/m² × (2400/3600) / 1000 = 0.25 + 0.333 ≈ 0.583
        self.assertAlmostEqual(result, 0.5833, places=3)

    def test_only_today_samples_count(self) -> None:
        """A weather row for yesterday should not contribute to today's
        integral."""
        _write_weather(self.path, [
            # Yesterday — must be ignored:
            (datetime(2026, 5, 17, 12, 0), 800.0),
            (datetime(2026, 5, 17, 13, 0), 800.0),
            # Today:
            (datetime(2026, 5, 18, 10, 0), 500.0),
            (datetime(2026, 5, 18, 11, 0), 500.0),
        ])
        result = integrate_today_irradiance(
            self.path, self.day,
            now=datetime(2026, 5, 18, 11, 0),
        )
        self.assertAlmostEqual(result, 0.5, places=4)

    def test_zero_wm2_samples_zero_integral(self) -> None:
        """Overnight samples (wm2 = 0) integrate to 0 — sanity."""
        _write_weather(self.path, [
            (datetime(2026, 5, 18, 2, 0), 0.0),
            (datetime(2026, 5, 18, 3, 0), 0.0),
            (datetime(2026, 5, 18, 4, 0), 0.0),
        ])
        result = integrate_today_irradiance(
            self.path, self.day,
            now=datetime(2026, 5, 18, 4, 0),
        )
        self.assertAlmostEqual(result, 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
