"""Tests for `end_of_day_report.build_report`.

The report builder is consumed in two places: the CLI script writes
`data/reports/YYYY-MM-DD.md`, and `scripts/dashboard.py` inlines it
into the `/today-report` and `/report/YYYY-MM-DD` HTML responses.
Any regression here breaks both surfaces, so we exercise the
markdown sections directly on fixtured data.

Fixtured against tempdirs (no touching of real data/*.csv); tests
chdir into the tempdir so the report builder's relative-path
defaults (data/pack.csv, data/weather.csv, etc.) point at the
fixtures.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import end_of_day_report as end_of_day_report_mod  # noqa: E402


PACK_HEADER = ["ts", "state", "pack_v", "pack_i", "pack_p",
               "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
               "temp_a", "temp_b", "rem_a", "rem_b",
               "delta_v_a", "delta_v_b", "smoothed_i", "smoothed_p",
               "minutes_remaining", "name_a", "name_b"]

WEATHER_HEADER = ["ts", "lat", "lon", "temperature_c", "cloud_cover_pct",
                  "shortwave_radiation_wm2", "wind_speed_ms",
                  "wind_gusts_ms", "weather_code", "is_day",
                  "sunrise_iso", "sunset_iso",
                  "shortwave_radiation_sum_today_wh_m2",
                  "uv_index_max_today"]

DAILY_HEADER = ["date", "duration_h", "samples", "soc_min", "soc_max",
                "soc_start", "soc_end", "charge_ah", "discharge_ah",
                "net_ah", "generator_minutes", "generator_ah",
                "solar_ah_estimated", "weather_kwh_m2",
                "weather_cloud_pct_avg", "weather_temp_c_min",
                "weather_temp_c_max", "partial"]

CALIB_HEADER = ["ts", "coefficient", "n_observations", "confidence",
                "source", "notes"]

PROJ_HEADER = ["ts", "start_soc_pct",
               "projected_sunrise_soc", "projected_tomorrow_evening_soc",
               "projected_low_soc",
               "solar_model_coefficient", "today_irradiance_kwh_m2",
               "sunrise_iso", "source"]


class TestBuildReport(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "reports").mkdir(parents=True)
        self._orig_cwd = Path.cwd()
        os.chdir(self.root)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self.tmp.cleanup()

    # ---------- fixturing helpers ----------

    def _write_pack(self, samples: list[dict]) -> None:
        """Write a minimal pack.csv with samples list. Missing columns
        default to empty string (the production loader ignores them
        when not needed)."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=PACK_HEADER)
            w.writeheader()
            for s in samples:
                w.writerow({k: s.get(k, "") for k in PACK_HEADER})

    def _write_weather(self, samples: list[dict]) -> None:
        path = self.root / "data" / "weather.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=WEATHER_HEADER)
            w.writeheader()
            for s in samples:
                w.writerow({k: s.get(k, "") for k in WEATHER_HEADER})

    def _write_daily(self, rows: list[dict]) -> None:
        path = self.root / "data" / "daily_summary.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=DAILY_HEADER)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in DAILY_HEADER})

    def _write_calib(self, entries: list[dict]) -> None:
        path = self.root / "data" / "calibration_log.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CALIB_HEADER)
            w.writeheader()
            for e in entries:
                w.writerow({k: e.get(k, "") for k in CALIB_HEADER})

    def _write_proj(self, entries: list[dict]) -> None:
        path = self.root / "data" / "projection_log.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=PROJ_HEADER)
            w.writeheader()
            for e in entries:
                w.writerow({k: e.get(k, "") for k in PROJ_HEADER})

    def _pack_run(self, start: datetime, n: int, pack_i: float,
                  soc_a: float = 80.0, soc_b: float = 78.0,
                  pack_v: float = 26.5, step_s: int = 10) -> list[dict]:
        out = []
        t = start
        for _ in range(n):
            out.append({
                "ts": t.isoformat(),
                "pack_v": pack_v,
                "pack_i": pack_i,
                "smoothed_i": pack_i,
                "soc_a": soc_a,
                "soc_b": soc_b,
            })
            t = t + timedelta(seconds=step_s)
        return out

    # ---------- tests ----------

    def test_empty_day_produces_graceful_in_progress_summary(self) -> None:
        """No data anywhere → 'Day in progress.' summary, sections
        rendered with em-dashes instead of crashing."""
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("Day report — 2026-05-18", md)
        self.assertIn("Day in progress.", md)
        # The five major sections must all be present
        self.assertIn("## Pack", md)
        self.assertIn("## Solar harvest", md)
        self.assertIn("## Weather", md)
        self.assertIn("## SolarModel state", md)
        self.assertIn("## Cross-references", md)

    def test_partial_day_shows_partial_tag(self) -> None:
        """A daily_summary row with partial=True → '*(partial day so far)*'."""
        self._write_pack(
            self._pack_run(datetime(2026, 5, 18, 12, 0), 30, 10.0,
                           soc_a=80, soc_b=78))
        self._write_daily([{
            "date": "2026-05-18",
            "duration_h": "12.0", "samples": "30",
            "soc_min": "70", "soc_max": "85",
            "soc_start": "70", "soc_end": "85",
            "charge_ah": "20.0", "discharge_ah": "5.0", "net_ah": "15.0",
            "generator_minutes": "0", "generator_ah": "0.0",
            "solar_ah_estimated": "20.0",
            "weather_kwh_m2": "5.34",
            "weather_cloud_pct_avg": "80",
            "weather_temp_c_min": "5.0", "weather_temp_c_max": "15.0",
            "partial": "True",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("(partial day so far)", md)
        self.assertNotIn("**Complete day**", md)

    def test_complete_day_shows_complete_tag(self) -> None:
        self._write_pack(
            self._pack_run(datetime(2026, 5, 18, 0, 0), 30, 10.0))
        self._write_daily([{
            "date": "2026-05-18",
            "duration_h": "22.5", "samples": "5000",
            "soc_min": "70", "soc_max": "95",
            "soc_start": "85", "soc_end": "85",
            "charge_ah": "45.0", "discharge_ah": "44.0", "net_ah": "1.0",
            "generator_minutes": "0", "generator_ah": "0.0",
            "solar_ah_estimated": "45.0",
            "weather_kwh_m2": "5.34", "weather_cloud_pct_avg": "80",
            "weather_temp_c_min": "5.0", "weather_temp_c_max": "15.0",
            "partial": "False",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("**Complete day**", md)

    def test_strong_day_lede_when_pct_above_110(self) -> None:
        """Forecast overshoot → 'strong day' descriptor in the lede."""
        self._write_pack(
            self._pack_run(datetime(2026, 5, 18, 12, 0), 30, 10.0))
        # Manufacture a forecast such that snap.pct_of_forecast > 110.
        # SolarModel default is 7.0 Ah/(kWh/m²); with kwh=3.0 forecast Ah=21.
        # solar_ah_so_far needs to be > 23 (21 × 1.1) for "strong day".
        # The pack run above ≈ 0.83 Ah (30 × 10 × 10/3600), not enough.
        # Use a longer run that lands ~25 Ah charged:
        long_run = self._pack_run(
            datetime(2026, 5, 18, 12, 0),
            60 * 60 * 9 // 10,  # 9-h-equivalent at 10s cadence
            10.0,
        )
        self._write_pack(long_run)
        self._write_weather([{
            "ts": "2026-05-18T12:00:00", "lat": "51.07", "lon": "-121.2",
            "temperature_c": "10.0", "cloud_cover_pct": "50",
            "shortwave_radiation_wm2": "500.0",
            "wind_speed_ms": "1.0", "wind_gusts_ms": "2.0",
            "weather_code": "3", "is_day": "1",
            "sunrise_iso": "2026-05-18T05:09",
            "sunset_iso": "2026-05-18T20:52",
            "shortwave_radiation_sum_today_wh_m2": "3000.0",  # 3 kWh/m²
            "uv_index_max_today": "5.0",
        }, {
            "ts": "2026-05-18T18:00:00", "lat": "51.07", "lon": "-121.2",
            "temperature_c": "10.0", "cloud_cover_pct": "50",
            "shortwave_radiation_wm2": "500.0",
            "wind_speed_ms": "1.0", "wind_gusts_ms": "2.0",
            "weather_code": "3", "is_day": "1",
            "sunrise_iso": "2026-05-18T05:09",
            "sunset_iso": "2026-05-18T20:52",
            "shortwave_radiation_sum_today_wh_m2": "3000.0",
            "uv_index_max_today": "5.0",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        # ~9 h × 10 A ≈ 90 Ah harvested; forecast 7 × 3 = 21 Ah.
        # Raw pct = 428 % → snapshot clamps to 200 % (well above 110 %)
        # → strong day descriptor.
        self.assertIn("strong day", md)

    def test_soft_day_lede_when_pct_50_to_90(self) -> None:
        """Mid-range fraction of forecast → 'soft day' descriptor."""
        # 30 min × 10 A = 5 Ah. Forecast: 7 × 5 = 35 Ah → 14 % → "well below"
        # 6 min × 10 A = 1 Ah, forecast 7 × 2 = 14 → 7 % → also well below
        # Need ~17 Ah / 35 = 49 → 50-90 = soft. Use 5h × 10A then forecast 7 × 5.5 = 38.5
        # 50 Ah charged / 38.5 = 130 % strong
        # Tough geometry; pick 105 min × 10 = 17.5 Ah, forecast 7 × 3 = 21 → 83 % soft
        # 10 s × n = 105×60 → n = 630
        self._write_pack(
            self._pack_run(datetime(2026, 5, 18, 12, 0), 630, 10.0))
        self._write_weather([{
            "ts": "2026-05-18T12:00:00",
            "lat": "51.07", "lon": "-121.2",
            "temperature_c": "10.0", "cloud_cover_pct": "50",
            "shortwave_radiation_wm2": "500.0",
            "wind_speed_ms": "1.0", "wind_gusts_ms": "2.0",
            "weather_code": "3", "is_day": "1",
            "sunrise_iso": "2026-05-18T05:09",
            "sunset_iso": "2026-05-18T20:52",
            "shortwave_radiation_sum_today_wh_m2": "3000.0",
            "uv_index_max_today": "5.0",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        # 17.5 Ah / 21 Ah ≈ 83 % → soft day
        self.assertIn("soft day", md)

    def test_calibration_table_renders_today_entries(self) -> None:
        """When there are calibration_log entries dated to `day`, the
        table renders with one row per entry."""
        self._write_calib([
            {"ts": "2026-05-18T13:00:00", "coefficient": "7.000",
             "n_observations": "0", "confidence": "low",
             "source": "loop-iteration",
             "notes": "no usable observations yet"},
            {"ts": "2026-05-18T21:05:00", "coefficient": "8.230",
             "n_observations": "1", "confidence": "low",
             "source": "advisor-invocation",
             "notes": "fit from 1 observations"},
            # Yesterday — must NOT appear
            {"ts": "2026-05-17T19:00:00", "coefficient": "7.000",
             "n_observations": "0", "confidence": "low",
             "source": "old", "notes": ""},
        ])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("13:00", md)
        self.assertIn("21:05", md)
        self.assertIn("7.000", md)
        self.assertIn("8.230", md)
        # Yesterday's entry must be excluded
        self.assertNotIn("19:00", md)

    def test_no_calibration_entries_shows_helpful_text(self) -> None:
        """Empty calibration_log → 'No SolarModel coefficient changes
        logged today.' instead of an empty table."""
        # No calibration_log written
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("No SolarModel coefficient changes logged today",
                      md)

    def test_peaks_render_when_pack_data_present(self) -> None:
        """When pack samples exist for the day, the Peaks line lists
        peak_charge_a, peak_soc_pct, etc."""
        self._write_pack(
            self._pack_run(datetime(2026, 5, 18, 13, 0), 30, 21.4,
                           soc_a=92, soc_b=90, pack_v=27.0))
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("Peaks:", md)
        self.assertIn("21.4 A", md)
        self.assertIn("92%", md)
        # first_charge_time triggers on pack_i > 1.0 → 13:00 in our run
        self.assertIn("13:00", md)

    def test_generator_minutes_line_when_used(self) -> None:
        """If generator was run today, the report mentions it; else it
        says 'not run today'."""
        self._write_daily([{
            "date": "2026-05-18",
            "duration_h": "22.5", "samples": "5000",
            "soc_min": "60", "soc_max": "90",
            "soc_start": "65", "soc_end": "85",
            "charge_ah": "70.0", "discharge_ah": "44.0", "net_ah": "26.0",
            "generator_minutes": "45",
            "generator_ah": "40.0",
            "solar_ah_estimated": "30.0",
            "weather_kwh_m2": "5.0",
            "weather_cloud_pct_avg": "80",
            "weather_temp_c_min": "5.0", "weather_temp_c_max": "15.0",
            "partial": "False",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("Generator:", md)
        self.assertIn("45 min", md)
        self.assertIn("40.0", md)

    def test_no_generator_run_shows_not_run_today(self) -> None:
        self._write_daily([{
            "date": "2026-05-18",
            "duration_h": "22.5", "samples": "5000",
            "soc_min": "70", "soc_max": "95",
            "soc_start": "85", "soc_end": "85",
            "charge_ah": "45.0", "discharge_ah": "44.0", "net_ah": "1.0",
            "generator_minutes": "0", "generator_ah": "0.0",
            "solar_ah_estimated": "45.0",
            "weather_kwh_m2": "5.34", "weather_cloud_pct_avg": "80",
            "weather_temp_c_min": "5.0", "weather_temp_c_max": "15.0",
            "partial": "False",
        }])
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("Generator: not run today", md)

    def test_cross_references_section_always_present(self) -> None:
        """Even on an empty day the report tells the reader where to
        find the raw data."""
        md = end_of_day_report_mod.build_report(date(2026, 5, 18))
        self.assertIn("data/pack.csv", md)
        self.assertIn("data/weather.csv", md)
        self.assertIn("data/daily_summary.csv", md)
        self.assertIn("data/calibration_log.csv", md)
        self.assertIn("data/projection_log.csv", md)
        self.assertIn("docs/STATUS.md", md)

    # ---------- Projection accuracy section ----------

    def test_projection_accuracy_section_empty_when_no_records(self) -> None:
        """No projection_log + no pack samples → the 'Projection
        accuracy' section renders the friendly empty-state message."""
        md = end_of_day_report_mod.build_report(date(2026, 5, 19))
        self.assertIn("## Projection accuracy", md)
        self.assertIn("No validatable projections for this day yet", md)

    def test_projection_accuracy_section_renders_records_after_sunrise(self) -> None:
        """If projections targeting `day` sunrise have matching pack
        samples, the section renders a markdown table with one row
        per validated projection. Uses dates well in the past so the
        sunrise target is unambiguously a past time relative to test
        run-time (compute_accuracy_records uses datetime.now() by
        default to gate 'is the target valid yet')."""
        # Projection MADE on 2025-01-09 (year ago), targeting that
        # day's sunrise time. Definitely past relative to test now.
        self._write_proj([{
            "ts": "2025-01-09T22:14:46",
            "start_soc_pct": "84.0",
            "projected_sunrise_soc": "70.0",
            "projected_tomorrow_evening_soc": "90.0",
            "projected_low_soc": "69.0",
            "solar_model_coefficient": "8.15",
            "today_irradiance_kwh_m2": "5.62",
            "sunrise_iso": "2025-01-10T08:00",
            "source": "advisor-invocation",
        }])
        # Pack sample at the sunrise time with actual SOC = 72 % (avg
        # of 73 and 71)
        self._write_pack(
            self._pack_run(datetime(2025, 1, 10, 8, 0), 6, -5.0,
                           soc_a=73, soc_b=71))
        md = end_of_day_report_mod.build_report(date(2025, 1, 10))
        # Header + summary line
        self.assertIn("## Projection accuracy", md)
        self.assertIn("targeting **2025-01-10 sunrise**", md)
        # Table rendered with row for the projection
        self.assertIn("| made at | projected | actual | error (pp) |", md)
        self.assertIn("2025-01-09T22:14", md)        # made-at timestamp
        self.assertIn("70.0", md)                     # projected
        self.assertIn("72.0", md)                     # actual
        # Error = 72.0 - 70.0 = +2.0
        self.assertIn("+2.0", md)


if __name__ == "__main__":
    unittest.main()
