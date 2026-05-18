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

from scripts.today_harvest import (  # noqa: E402
    compute_today_peaks,
    integrate_today,
    integrate_today_irradiance,
    weather_forecast_history,
)


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


def _write_pack(path: Path, samples: list[tuple[datetime, float]]) -> None:
    """Write a minimal pack.csv with just ts + pack_i — the only two
    columns integrate_today actually consumes. Real pack.csv has many
    more columns; the function should ignore them."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "pack_i"])
        for ts, pack_i in samples:
            w.writerow([ts.isoformat(), pack_i])


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


class TestIntegrateTodayPack(unittest.TestCase):
    """Tests for integrate_today — the pack-side trapezoidal integration
    that powers the harvest panel cumulative number, the sparkline, and
    the per-hour bar chart. Drives directly into the dashboard so any
    regression here is user-visible."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pack.csv"
        self.day = date(2026, 5, 18)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_returns_zero_dict_when_file_missing(self) -> None:
        bogus = Path(self.tmp.name) / "does_not_exist.csv"
        result = integrate_today(bogus, self.day)
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["solar_ah"], 0.0)
        self.assertEqual(result["series"], [])

    def test_returns_zero_dict_with_no_today_rows(self) -> None:
        _write_pack(self.path, [(datetime(2026, 5, 17, 12, 0), 5.0)])
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["samples"], 0)
        self.assertEqual(result["solar_ah"], 0.0)

    def test_single_sample_integrates_to_zero(self) -> None:
        """Need at least two samples to integrate — trapezoidal rule
        consumes adjacent pairs."""
        _write_pack(self.path, [(datetime(2026, 5, 18, 10, 0), 10.0)])
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["samples"], 1)
        self.assertEqual(result["charge_ah"], 0.0)

    def _make_run(self, start: datetime, n: int, pack_i: float,
                  step_s: int = 10) -> list[tuple[datetime, float]]:
        """Build a list of (ts, pack_i) at `step_s` cadence — matches
        the real 10-s logger spacing so the gap-skip rule (dt_s > 60)
        never trips."""
        out = []
        t = start
        for _ in range(n):
            out.append((t, pack_i))
            t = t + timedelta(seconds=step_s)
        return out

    def test_steady_charge_six_min(self) -> None:
        """+10 A held over 6 min at 10-s cadence → 10 A * 6/60 h = 1 Ah."""
        # 37 samples × 10 s = 360 s = 6 min
        _write_pack(self.path,
                    self._make_run(datetime(2026, 5, 18, 12, 0), 37, 10.0))
        result = integrate_today(self.path, self.day)
        self.assertAlmostEqual(result["charge_ah"], 1.0, places=2)
        self.assertAlmostEqual(result["solar_ah"], 1.0, places=2)
        self.assertEqual(result["generator_ah"], 0.0)
        self.assertEqual(result["discharge_ah"], 0.0)

    def test_generator_current_is_split_off_from_solar(self) -> None:
        """Current > +30 A is generator, not solar. solar_ah must NOT
        include the generator contribution."""
        # +60 A held over 6 min → 60 × 6/60 = 6 Ah, all generator
        _write_pack(self.path,
                    self._make_run(datetime(2026, 5, 18, 15, 0), 37, 60.0))
        result = integrate_today(self.path, self.day)
        self.assertAlmostEqual(result["charge_ah"], 6.0, places=1)
        self.assertAlmostEqual(result["generator_ah"], 6.0, places=1)
        # solar_ah = charge_ah − generator_ah → 0
        self.assertAlmostEqual(result["solar_ah"], 0.0, places=2)

    def test_threshold_exactly_30A_is_NOT_generator(self) -> None:
        """The generator threshold is strict `> 30 A` — exactly 30 A is
        solar. Catches off-by-one if someone refactors the comparison."""
        _write_pack(self.path,
                    self._make_run(datetime(2026, 5, 18, 14, 0), 37, 30.0))
        result = integrate_today(self.path, self.day)
        # 30 A × 6/60 h = 3 Ah, all classified as solar (not generator)
        self.assertAlmostEqual(result["charge_ah"], 3.0, places=1)
        self.assertEqual(result["generator_ah"], 0.0)
        self.assertAlmostEqual(result["solar_ah"], 3.0, places=1)

    def test_negative_current_counts_as_discharge(self) -> None:
        """Discharge current is recorded as positive Ah in discharge_ah."""
        # -5 A held over 6 min → 5 × 6/60 = 0.5 Ah discharge
        _write_pack(self.path,
                    self._make_run(datetime(2026, 5, 18, 22, 0), 37, -5.0))
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["charge_ah"], 0.0)
        self.assertAlmostEqual(result["discharge_ah"], 0.5, places=2)

    def test_gap_over_60s_is_skipped(self) -> None:
        """The trapezoidal step is skipped when adjacent samples are
        more than 60 s apart — prevents huge phantom Ah from logging
        gaps (BLE reconnect, app restart). Without this, a 1 h gap at
        +10 A would falsely book 10 Ah."""
        _write_pack(self.path, [
            (datetime(2026, 5, 18, 12,  0,  0), 10.0),
            # Adjacent sample 5 minutes later → skipped (gap > 60 s)
            (datetime(2026, 5, 18, 12,  5,  0), 10.0),
        ])
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["charge_ah"], 0.0)

    def test_series_bins_to_5_minute_resolution(self) -> None:
        """The series is downsampled to one (minute_of_day, cumulative_ah)
        point per `series_bin_minutes` bucket. With 10-s pack samples
        through a 15-minute span at 5-min bin → expect 3 points."""
        samples = []
        # 10:00 → 10:15, +10 A, every 10 s
        t = datetime(2026, 5, 18, 10, 0, 0)
        for _ in range(15 * 6 + 1):    # 15 min × 6 samples/min
            samples.append((t, 10.0))
            t = t + timedelta(seconds=10)
        _write_pack(self.path, samples)
        result = integrate_today(self.path, self.day, series_bin_minutes=5)
        # Expect 3 points: bins for 10:00, 10:05, 10:10 (the 10:15 sample
        # opens the 10:15 bin → 4 total). Series is non-decreasing.
        self.assertGreaterEqual(len(result["series"]), 3)
        self.assertLessEqual(len(result["series"]), 4)
        # First point at or after minute 600 (10:00 = 600 min)
        first_min, first_ah = result["series"][0]
        self.assertGreaterEqual(first_min, 600)
        # Last point's solar_ah must equal the final solar_ah total
        last_min, last_ah = result["series"][-1]
        self.assertAlmostEqual(last_ah, result["solar_ah"], places=2)
        # Series must be non-decreasing in cumulative_ah
        for i in range(1, len(result["series"])):
            self.assertGreaterEqual(result["series"][i][1],
                                    result["series"][i - 1][1])

    def test_only_today_samples_count(self) -> None:
        """Yesterday's pack samples must not pollute today's totals."""
        yest = self._make_run(datetime(2026, 5, 17, 15, 0), 7, 50.0)
        today = self._make_run(datetime(2026, 5, 18, 12, 0), 7, 10.0)
        _write_pack(self.path, yest + today)
        result = integrate_today(self.path, self.day)
        # 7 samples × 10 s = 60 s span on today; charge = 10 A × 60/3600 = 0.167 Ah
        self.assertEqual(result["samples"], 7)
        self.assertAlmostEqual(result["charge_ah"], 0.167, places=2)
        # Crucially, yesterday's 50 A samples did NOT bleed in
        self.assertNotAlmostEqual(result["charge_ah"], 50.0 * (60.0 / 3600.0))

    def test_none_pack_i_rows_are_skipped(self) -> None:
        """A pack.csv row with no pack_i value (e.g. BMS read failure)
        must not corrupt the integral. The function walks ADJACENT
        pairs, so both pairs that include the None row are dropped —
        a single missing sample creates a zero-Ah hole in the integral
        (a small underestimate, but not a phantom contribution)."""
        # Manual write to set an empty pack_i mid-stream
        with self.path.open("w") as f:
            f.write("ts,pack_i\n")
            f.write("2026-05-18T10:00:00,10.0\n")
            f.write("2026-05-18T10:00:30,\n")         # missing
            f.write("2026-05-18T10:01:00,10.0\n")
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["samples"], 3)
        # Both adjacent pairs involve the None row → both skipped.
        # Honest underestimate: charge_ah is 0, not a phantom contribution.
        self.assertEqual(result["charge_ah"], 0.0)

    def test_none_pack_i_does_not_corrupt_surrounding_segments(self) -> None:
        """When a None row sits BETWEEN two valid runs, the valid runs
        before and after still integrate cleanly. Only the pairs that
        touch the None row get skipped."""
        with self.path.open("w") as f:
            f.write("ts,pack_i\n")
            # Two valid samples 10 s apart (60 s apart from the None row)
            f.write("2026-05-18T10:00:00,10.0\n")
            f.write("2026-05-18T10:00:10,10.0\n")
            f.write("2026-05-18T10:00:40,\n")         # missing
            # Two more valid samples 10 s apart, AFTER the None
            f.write("2026-05-18T10:01:10,10.0\n")
            f.write("2026-05-18T10:01:20,10.0\n")
        result = integrate_today(self.path, self.day)
        self.assertEqual(result["samples"], 5)
        # Valid pairs: (00, 10) and (10, 40-None) [dropped],
        #              (40-None, 1:10) [dropped], (1:10, 1:20)
        # → 2 valid 10-s × 10 A segments = 2 × 10/360 ≈ 0.0556 Ah,
        # which integrate_today rounds to 2 decimals → 0.06.
        self.assertAlmostEqual(result["charge_ah"], 0.06, places=2)


class TestWeatherForecastHistory(unittest.TestCase):
    """Tests for `weather_forecast_history` — the Open-Meteo forecast-
    revision tracker. Drives the dashboard's forecast-rev chip; needs
    to be robust to missing files, empty data, and single-sample edge
    cases so the chip degrades gracefully rather than crashing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "weather.csv"
        self.day = date(2026, 5, 18)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_forecast_series(
        self, ts_kwh_pairs: list[tuple[datetime, float]],
    ) -> None:
        """Write a weather.csv with the forecast column populated to
        the given (ts, kwh_today_Wh_m2) pairs."""
        with self.path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "lat", "lon", "temperature_c", "cloud_cover_pct",
                "shortwave_radiation_wm2", "wind_speed_ms", "wind_gusts_ms",
                "weather_code", "is_day", "sunrise_iso", "sunset_iso",
                "shortwave_radiation_sum_today_wh_m2", "uv_index_max_today",
            ])
            for ts, kwh in ts_kwh_pairs:
                w.writerow([ts.isoformat(), 51.07, -121.2, 10.0, 80,
                            500.0, 1.0, 2.0, 3, 1,
                            "2026-05-18T05:09", "2026-05-18T20:52",
                            kwh, 5.0])

    def test_missing_file_returns_empty_shape(self) -> None:
        bogus = Path(self.tmp.name) / "no_such.csv"
        r = weather_forecast_history(bogus, self.day)
        self.assertIsNone(r["first"])
        self.assertIsNone(r["latest"])
        self.assertIsNone(r["drift_pct"])
        self.assertEqual(r["n"], 0)

    def test_no_today_rows_returns_empty_shape(self) -> None:
        """Yesterday's rows shouldn't count toward today's history."""
        self._write_forecast_series([
            (datetime(2026, 5, 17, 12, 0), 4500.0),
            (datetime(2026, 5, 17, 18, 0), 4800.0),
        ])
        r = weather_forecast_history(self.path, self.day)
        self.assertEqual(r["n"], 0)
        self.assertIsNone(r["first"])

    def test_single_sample_has_zero_drift(self) -> None:
        """A single forecast value → first == latest, drift_pct == 0."""
        self._write_forecast_series([
            (datetime(2026, 5, 18, 10, 0), 5000.0),
        ])
        r = weather_forecast_history(self.path, self.day)
        self.assertEqual(r["n"], 1)
        self.assertAlmostEqual(r["first"], 5.0, places=3)
        self.assertAlmostEqual(r["latest"], 5.0, places=3)
        self.assertAlmostEqual(r["min"], 5.0, places=3)
        self.assertAlmostEqual(r["max"], 5.0, places=3)
        self.assertAlmostEqual(r["drift_pct"], 0.0, places=2)

    def test_upward_drift_is_positive(self) -> None:
        """Forecast revised UPWARD across the day → positive drift_pct.
        Mimics today's 4863.9 → 5202.8 path (real data from 2026-05-18)."""
        self._write_forecast_series([
            (datetime(2026, 5, 18, 0, 0),  4863.9),
            (datetime(2026, 5, 18, 6, 0),  4900.0),
            (datetime(2026, 5, 18, 12, 0), 5100.0),
            (datetime(2026, 5, 18, 18, 0), 5202.8),
        ])
        r = weather_forecast_history(self.path, self.day)
        self.assertEqual(r["n"], 4)
        self.assertAlmostEqual(r["first"], 4.864, places=3)
        self.assertAlmostEqual(r["latest"], 5.203, places=3)
        # (5.203 - 4.864) / 4.864 ≈ 6.97 %
        self.assertGreater(r["drift_pct"], 6.0)
        self.assertLess(r["drift_pct"], 8.0)

    def test_downward_drift_is_negative(self) -> None:
        """Forecast revised DOWNWARD → negative drift_pct."""
        self._write_forecast_series([
            (datetime(2026, 5, 18, 6, 0),  5500.0),
            (datetime(2026, 5, 18, 12, 0), 5200.0),
            (datetime(2026, 5, 18, 18, 0), 5000.0),
        ])
        r = weather_forecast_history(self.path, self.day)
        # (5.0 - 5.5) / 5.5 ≈ -9.09 %
        self.assertLess(r["drift_pct"], -8.0)
        self.assertGreater(r["drift_pct"], -10.0)

    def test_swing_captured_by_min_max(self) -> None:
        """The swing (max − min) is more meaningful than net drift on
        days where the forecast wobbled. 2026-05-18 had first=5.342,
        min=4.864, max=5.342, latest=5.203 → net drift small but swing
        large. The dashboard uses both numbers."""
        self._write_forecast_series([
            (datetime(2026, 5, 18, 0, 0),  5342.0),    # midnight, high
            (datetime(2026, 5, 18, 6, 0),  4864.0),    # morning, low
            (datetime(2026, 5, 18, 12, 0), 5000.0),
            (datetime(2026, 5, 18, 18, 0), 5203.0),    # afternoon, recovered
        ])
        r = weather_forecast_history(self.path, self.day)
        self.assertAlmostEqual(r["first"], 5.342, places=3)
        self.assertAlmostEqual(r["latest"], 5.203, places=3)
        self.assertAlmostEqual(r["min"], 4.864, places=3)
        self.assertAlmostEqual(r["max"], 5.342, places=3)
        # Net drift is small...
        self.assertLess(abs(r["drift_pct"]), 5.0)
        # ...but swing (max - min) / first should be ~9 %
        swing_pct = (r["max"] - r["min"]) / r["first"] * 100.0
        self.assertGreater(swing_pct, 8.0)
        self.assertLess(swing_pct, 10.0)

    def test_rows_with_missing_forecast_field_are_skipped(self) -> None:
        """If the weather row lacks a usable forecast value, skip it
        rather than erroring out."""
        with self.path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "lat", "lon", "temperature_c", "cloud_cover_pct",
                "shortwave_radiation_wm2", "wind_speed_ms", "wind_gusts_ms",
                "weather_code", "is_day", "sunrise_iso", "sunset_iso",
                "shortwave_radiation_sum_today_wh_m2", "uv_index_max_today",
            ])
            # Good row
            w.writerow(["2026-05-18T10:00:00", 51.07, -121.2, 10.0, 80,
                        500.0, 1.0, 2.0, 3, 1,
                        "2026-05-18T05:09", "2026-05-18T20:52",
                        5000.0, 5.0])
            # Missing forecast — should be skipped
            w.writerow(["2026-05-18T10:30:00", 51.07, -121.2, 10.0, 80,
                        500.0, 1.0, 2.0, 3, 1,
                        "2026-05-18T05:09", "2026-05-18T20:52",
                        "", 5.0])
            # Another good row
            w.writerow(["2026-05-18T11:00:00", 51.07, -121.2, 10.0, 80,
                        500.0, 1.0, 2.0, 3, 1,
                        "2026-05-18T05:09", "2026-05-18T20:52",
                        5100.0, 5.0])
        r = weather_forecast_history(self.path, self.day)
        self.assertEqual(r["n"], 2)
        self.assertAlmostEqual(r["first"], 5.0, places=3)
        self.assertAlmostEqual(r["latest"], 5.1, places=3)

    def test_zero_first_value_does_not_divide_by_zero(self) -> None:
        """Pathological case: if the first forecast value is 0 (e.g. an
        edge-of-night reading), drift_pct should be None rather than
        +inf or NaN. The dashboard hides the chip when drift_pct is null."""
        self._write_forecast_series([
            (datetime(2026, 5, 18, 0, 0),  0.0),
            (datetime(2026, 5, 18, 12, 0), 5000.0),
        ])
        r = weather_forecast_history(self.path, self.day)
        self.assertIsNone(r["drift_pct"])
        # ...but first / latest / min / max are still populated
        self.assertEqual(r["n"], 2)
        self.assertAlmostEqual(r["latest"], 5.0, places=3)


class TestComputeTodayPeaks(unittest.TestCase):
    """Tests for `compute_today_peaks` — the single-pass running-max
    scan that powers the dashboard's "TODAY'S PEAKS" subrow. Tested
    separately from `integrate_today` because it tracks max values
    instead of integrating, and reads more pack.csv columns (pack_v,
    soc_a, soc_b, smoothed_i)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pack.csv"
        self.day = date(2026, 5, 18)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_rows(self, rows: list[dict]) -> None:
        """Write pack.csv with the columns compute_today_peaks reads.
        Anything else can be empty strings — the function ignores them."""
        headers = ["ts", "state", "pack_v", "pack_i", "pack_p",
                   "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
                   "temp_a", "temp_b", "rem_a", "rem_b",
                   "delta_v_a", "delta_v_b", "smoothed_i", "smoothed_p",
                   "minutes_remaining", "name_a", "name_b"]
        with self.path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow([r.get(c, "") for c in headers])

    def test_returns_all_none_when_file_missing(self) -> None:
        bogus = Path(self.tmp.name) / "no_such.csv"
        r = compute_today_peaks(bogus, self.day)
        self.assertIsNone(r["peak_charge_a"])
        self.assertIsNone(r["peak_soc_pct"])
        self.assertIsNone(r["peak_pack_voltage_v"])
        self.assertIsNone(r["first_charge_time"])

    def test_yesterday_rows_do_not_count(self) -> None:
        """Cross-day filter: only today's rows contribute to peaks."""
        self._write_rows([
            # Yesterday — must be ignored:
            {"ts": "2026-05-17T15:00:00", "pack_v": 27.5,
             "pack_i": 60.0, "smoothed_i": 50.0,
             "soc_a": 95, "soc_b": 95},
            # Today — these are what should count:
            {"ts": "2026-05-18T12:00:00", "pack_v": 26.5,
             "pack_i": 10.0, "smoothed_i": 9.5,
             "soc_a": 75, "soc_b": 73},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertAlmostEqual(r["peak_charge_a"], 10.0, places=2)
        self.assertAlmostEqual(r["peak_pack_voltage_v"], 26.5, places=2)
        self.assertAlmostEqual(r["peak_soc_pct"], 75.0, places=1)

    def test_peak_charge_is_max_of_all_today_samples(self) -> None:
        """peak_charge_a tracks the running max of pack_i across all
        today's rows, not just the latest."""
        self._write_rows([
            {"ts": "2026-05-18T10:00:00", "pack_i": 5.0,
             "soc_a": 70, "soc_b": 68, "pack_v": 26.2},
            {"ts": "2026-05-18T13:00:00", "pack_i": 21.4,
             "soc_a": 85, "soc_b": 84, "pack_v": 26.9},  # peak
            {"ts": "2026-05-18T16:00:00", "pack_i": 2.5,
             "soc_a": 93, "soc_b": 93, "pack_v": 26.75},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertAlmostEqual(r["peak_charge_a"], 21.4, places=2)

    def test_peak_smoothed_tracks_smoothed_column(self) -> None:
        """peak_smoothed_a is independent of peak_charge_a — comes
        from the smoothed_i column, which may peak at a different
        sample due to EMA lag."""
        self._write_rows([
            {"ts": "2026-05-18T12:00:00", "pack_i": 22.0, "smoothed_i": 10.0,
             "soc_a": 70, "soc_b": 68, "pack_v": 26.5},
            {"ts": "2026-05-18T12:10:00", "pack_i": 15.0, "smoothed_i": 17.8,  # peak
             "soc_a": 72, "soc_b": 70, "pack_v": 26.6},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertAlmostEqual(r["peak_charge_a"], 22.0, places=2)
        self.assertAlmostEqual(r["peak_smoothed_a"], 17.8, places=2)

    def test_peak_soc_considers_both_batteries(self) -> None:
        """peak_soc_pct is max across BOTH soc_a and soc_b, so an
        asymmetric pair where one battery is ahead still surfaces."""
        self._write_rows([
            # A leads B
            {"ts": "2026-05-18T10:00:00", "pack_i": 5.0,
             "soc_a": 92, "soc_b": 85, "pack_v": 26.5},
            # B leads A — peak should still pick the higher one
            {"ts": "2026-05-18T14:00:00", "pack_i": 5.0,
             "soc_a": 90, "soc_b": 94, "pack_v": 26.7},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertAlmostEqual(r["peak_soc_pct"], 94.0, places=1)

    def test_first_charge_time_is_first_sample_above_1A(self) -> None:
        """first_charge_time triggers on the first sample where
        pack_i > 1.0 A, ignoring earlier sub-1A trickle/idle/discharge."""
        self._write_rows([
            {"ts": "2026-05-18T06:30:00", "pack_i": -3.0,
             "soc_a": 75, "soc_b": 73, "pack_v": 26.2},   # discharging
            {"ts": "2026-05-18T08:30:00", "pack_i": 0.5,
             "soc_a": 75, "soc_b": 73, "pack_v": 26.3},   # below threshold
            {"ts": "2026-05-18T09:11:00", "pack_i": 1.5,
             "soc_a": 76, "soc_b": 74, "pack_v": 26.4},   # first > 1 A
            {"ts": "2026-05-18T10:00:00", "pack_i": 8.0,
             "soc_a": 80, "soc_b": 78, "pack_v": 26.6},   # later, stronger
        ])
        r = compute_today_peaks(self.path, self.day)
        # Must record the FIRST > 1 A sample, not the strongest one
        self.assertEqual(r["first_charge_time"], "09:11")

    def test_exactly_1A_is_NOT_first_charging(self) -> None:
        """Strict > 1.0 A — exactly 1.0 A is not enough. The dashboard
        labels "first net charging" as a meaningful event, not noise."""
        self._write_rows([
            {"ts": "2026-05-18T09:00:00", "pack_i": 1.0,
             "soc_a": 75, "soc_b": 73, "pack_v": 26.3},
            {"ts": "2026-05-18T09:30:00", "pack_i": 1.1,
             "soc_a": 76, "soc_b": 74, "pack_v": 26.4},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertEqual(r["first_charge_time"], "09:30")

    def test_no_charging_samples_leaves_first_charge_time_none(self) -> None:
        """If the pack never crosses +1 A today, first_charge_time
        stays None (graceful for overnight-only / generator-only days)."""
        self._write_rows([
            {"ts": "2026-05-18T00:00:00", "pack_i": -5.0,
             "soc_a": 80, "soc_b": 78, "pack_v": 26.2},
            {"ts": "2026-05-18T06:00:00", "pack_i": 0.2,
             "soc_a": 70, "soc_b": 68, "pack_v": 26.1},
        ])
        r = compute_today_peaks(self.path, self.day)
        self.assertIsNone(r["first_charge_time"])
        # peak_charge_a still captures the max we saw, even if < 1 A
        self.assertAlmostEqual(r["peak_charge_a"], 0.2, places=2)


if __name__ == "__main__":
    unittest.main()
