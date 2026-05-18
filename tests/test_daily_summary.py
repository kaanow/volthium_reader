"""Tests for daily_summary.summarize_day.

This function produces one row of data/daily_summary.csv per calendar
date — the input for `SolarModel.fit_from_daily_summary`, which drives
every advisor verdict. Any regression here cascades through every
downstream recommendation. Tested separately from
`integrate_today` because summarize_day adds the weather-join layer
and the partial-day flag that integrate_today doesn't carry.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_summary  # noqa: E402


def _pack_run(start: datetime, n: int, pack_i: float,
              soc_a: float = 80.0, soc_b: float = 78.0,
              step_s: int = 10) -> list[dict]:
    """Build a list of pack-side rows matching what daily_summary.load_pack
    produces: ts (datetime), date (iso), pack_i, soc_a, soc_b."""
    out = []
    t = start
    for _ in range(n):
        out.append({
            "ts": t,
            "date": t.date().isoformat(),
            "pack_i": pack_i,
            "soc_a": soc_a,
            "soc_b": soc_b,
        })
        t = t + timedelta(seconds=step_s)
    return out


def _weather_row(ts: datetime, cloud: float = 50.0, temp: float = 10.0,
                 kwh_today_wh_m2: float = 5000.0) -> dict:
    """Matching what daily_summary.load_weather produces per row."""
    return {
        "ts": ts,
        "cloud_pct": cloud,
        "temp_c": temp,
        "kwh_m2_today": kwh_today_wh_m2,
    }


class TestSummarizeDay(unittest.TestCase):

    def test_empty_rows_returns_none(self) -> None:
        self.assertIsNone(daily_summary.summarize_day([], []))

    def test_no_soc_pairs_returns_none(self) -> None:
        """If all rows are missing soc_a/soc_b, can't compute SOC stats."""
        rows = [
            {"ts": datetime(2026, 5, 18, 12, 0),
             "date": "2026-05-18", "pack_i": 5.0,
             "soc_a": None, "soc_b": None},
            {"ts": datetime(2026, 5, 18, 12, 0, 10),
             "date": "2026-05-18", "pack_i": 5.0,
             "soc_a": None, "soc_b": None},
        ]
        self.assertIsNone(daily_summary.summarize_day(rows, []))

    def test_steady_charge_produces_correct_charge_ah(self) -> None:
        """+10 A held 6 min at 10-s cadence → 1 Ah; no generator, no discharge."""
        rows = _pack_run(datetime(2026, 5, 18, 12, 0), 37, 10.0)
        r = daily_summary.summarize_day(rows, [])
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.charge_ah, 1.0, places=1)
        self.assertEqual(r.generator_ah, 0.0)
        self.assertEqual(r.discharge_ah, 0.0)
        self.assertAlmostEqual(r.solar_ah_estimated, 1.0, places=1)
        self.assertAlmostEqual(r.net_ah, 1.0, places=1)

    def test_generator_above_30A_routes_to_generator_ah(self) -> None:
        """Current > +30 A is generator. solar_ah_estimated = charge_ah - generator_ah."""
        rows = _pack_run(datetime(2026, 5, 18, 15, 0), 37, 60.0)
        r = daily_summary.summarize_day(rows, [])
        self.assertAlmostEqual(r.charge_ah, 6.0, places=1)
        self.assertAlmostEqual(r.generator_ah, 6.0, places=1)
        self.assertGreater(r.generator_minutes, 5.0)
        self.assertLess(r.generator_minutes, 7.0)
        # solar = charge - generator = 0
        self.assertAlmostEqual(r.solar_ah_estimated, 0.0, places=1)

    def test_30A_exactly_is_NOT_generator(self) -> None:
        """Strict > 30 A — exactly 30 A is solar. Off-by-one catch."""
        rows = _pack_run(datetime(2026, 5, 18, 14, 0), 37, 30.0)
        r = daily_summary.summarize_day(rows, [])
        self.assertEqual(r.generator_ah, 0.0)
        self.assertEqual(r.generator_minutes, 0.0)
        self.assertAlmostEqual(r.solar_ah_estimated, 3.0, places=1)

    def test_negative_current_counts_as_discharge(self) -> None:
        """Discharge stored as positive Ah in discharge_ah."""
        rows = _pack_run(datetime(2026, 5, 18, 22, 0), 37, -5.0)
        r = daily_summary.summarize_day(rows, [])
        self.assertEqual(r.charge_ah, 0.0)
        self.assertAlmostEqual(r.discharge_ah, 0.5, places=1)
        self.assertAlmostEqual(r.net_ah, -0.5, places=1)

    def test_gap_over_60s_is_skipped(self) -> None:
        """Adjacent samples > 60s apart drop the step (gap protection)."""
        # Two samples, 5 min apart: dt > 60 → both skipped
        rows = [
            {"ts": datetime(2026, 5, 18, 12, 0),
             "date": "2026-05-18", "pack_i": 10.0,
             "soc_a": 80, "soc_b": 78},
            {"ts": datetime(2026, 5, 18, 12, 5),
             "date": "2026-05-18", "pack_i": 10.0,
             "soc_a": 80, "soc_b": 78},
        ]
        r = daily_summary.summarize_day(rows, [])
        self.assertEqual(r.charge_ah, 0.0)
        self.assertEqual(r.samples, 2)

    def test_soc_stats_record_start_end_min_max(self) -> None:
        """SOC start/end/min/max come from the avg of soc_a and soc_b
        across the day's rows."""
        rows = []
        t = datetime(2026, 5, 18, 6, 0)
        # SOC walks 70 → 90 → 75
        for soc in [70, 75, 85, 90, 85, 80, 75]:
            rows.append({
                "ts": t, "date": t.date().isoformat(),
                "pack_i": 5.0,
                "soc_a": soc, "soc_b": soc,
            })
            t = t + timedelta(seconds=20)
        r = daily_summary.summarize_day(rows, [])
        self.assertAlmostEqual(r.soc_start, 70.0, places=1)
        self.assertAlmostEqual(r.soc_end, 75.0, places=1)
        self.assertAlmostEqual(r.soc_min, 70.0, places=1)
        self.assertAlmostEqual(r.soc_max, 90.0, places=1)

    def test_partial_flag_true_when_under_20h(self) -> None:
        """Default `partial=True` for short coverage; matches the 2026-05-18
        bug-fix where the old `duration_h > 12` rule wrongly admitted
        midnight-to-noon rows as complete."""
        # 12 h coverage with 10-s steps would be huge; use a 13-h start/end
        # pair with a single gap-skipped row in the middle for compactness.
        rows = _pack_run(datetime(2026, 5, 18, 0, 0), 2, 5.0, step_s=10)
        # Append a row 13 h later to push duration_h up but stay < 20 h
        rows.append({
            "ts": datetime(2026, 5, 18, 13, 0),
            "date": "2026-05-18", "pack_i": 5.0,
            "soc_a": 80, "soc_b": 78,
        })
        r = daily_summary.summarize_day(rows, [])
        # duration_h ≈ 13 → still partial under the 20h rule
        self.assertGreater(r.duration_h, 12.0)
        self.assertLess(r.duration_h, 14.0)
        self.assertTrue(r.partial)

    def test_partial_flag_false_when_at_least_20h(self) -> None:
        """duration_h >= 20 → complete day, partial=False, eligible for
        SolarModel fit."""
        rows = _pack_run(datetime(2026, 5, 18, 0, 0), 2, 5.0, step_s=10)
        rows.append({
            "ts": datetime(2026, 5, 18, 21, 0),
            "date": "2026-05-18", "pack_i": 5.0,
            "soc_a": 80, "soc_b": 78,
        })
        r = daily_summary.summarize_day(rows, [])
        self.assertGreaterEqual(r.duration_h, 20.0)
        self.assertFalse(r.partial)

    def test_weather_joins_use_max_irradiance_sum(self) -> None:
        """weather_kwh_m2 = max(weather rows' kwh_today_wh_m2) / 1000.
        Open-Meteo revises the day-total upward as the day progresses;
        we want the freshest (highest) reading."""
        rows = _pack_run(datetime(2026, 5, 18, 12, 0), 37, 10.0)
        weather_rows = [
            _weather_row(datetime(2026, 5, 18, 9, 0),
                         cloud=80.0, temp=8.0, kwh_today_wh_m2=4800.0),
            _weather_row(datetime(2026, 5, 18, 12, 0),
                         cloud=90.0, temp=11.0, kwh_today_wh_m2=5100.0),
            _weather_row(datetime(2026, 5, 18, 15, 0),
                         cloud=70.0, temp=14.0, kwh_today_wh_m2=5300.0),
        ]
        r = daily_summary.summarize_day(rows, weather_rows)
        # Picks the max → 5300 / 1000 = 5.30 kWh/m²
        self.assertAlmostEqual(r.weather_kwh_m2, 5.30, places=2)
        # Cloud mean of [80, 90, 70] = 80
        self.assertAlmostEqual(r.weather_cloud_pct_avg, 80.0, places=1)
        # Temp min / max
        self.assertAlmostEqual(r.weather_temp_c_min, 8.0, places=1)
        self.assertAlmostEqual(r.weather_temp_c_max, 14.0, places=1)

    def test_no_weather_rows_leaves_weather_fields_none(self) -> None:
        """A pack-only day still produces a row, just without weather columns."""
        rows = _pack_run(datetime(2026, 5, 18, 12, 0), 37, 10.0)
        r = daily_summary.summarize_day(rows, [])
        self.assertIsNone(r.weather_kwh_m2)
        self.assertIsNone(r.weather_cloud_pct_avg)
        self.assertIsNone(r.weather_temp_c_min)
        self.assertIsNone(r.weather_temp_c_max)

    def test_none_pack_i_rows_are_skipped(self) -> None:
        """A row missing pack_i must not corrupt the integral. Both
        adjacent pairs that touch the None row are dropped (same as
        integrate_today's behavior)."""
        rows = [
            {"ts": datetime(2026, 5, 18, 10, 0),
             "date": "2026-05-18", "pack_i": 10.0,
             "soc_a": 80, "soc_b": 78},
            {"ts": datetime(2026, 5, 18, 10, 0, 10),
             "date": "2026-05-18", "pack_i": None,
             "soc_a": 80, "soc_b": 78},
            {"ts": datetime(2026, 5, 18, 10, 0, 20),
             "date": "2026-05-18", "pack_i": 10.0,
             "soc_a": 80, "soc_b": 78},
        ]
        r = daily_summary.summarize_day(rows, [])
        self.assertEqual(r.samples, 3)
        # Both adjacent pairs touched the None row → no charge accumulated
        self.assertEqual(r.charge_ah, 0.0)


if __name__ == "__main__":
    unittest.main()
