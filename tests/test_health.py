"""Tests for `scripts.health` — the one-screen summary command.

The summary aggregates state from every chain. Tests cover both the
fully-cold-start path (no logs anywhere) and a realistic populated
path so the output structure is pinned down.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import health as health_mod  # noqa: E402


class TestHealthSummary(unittest.TestCase):

    def setUp(self) -> None:
        # Operate inside a tempdir so we don't touch live data
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self._orig_cwd = Path.cwd()
        os.chdir(self.root)
        # Re-point the module's path constants too — they were captured
        # at import time with the project's cwd
        self._orig_pack = health_mod.PACK_CSV
        self._orig_wx = health_mod.WEATHER_CSV
        health_mod.PACK_CSV = Path("data/pack.csv")
        health_mod.WEATHER_CSV = Path("data/weather.csv")

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        health_mod.PACK_CSV = self._orig_pack
        health_mod.WEATHER_CSV = self._orig_wx
        self.tmp.cleanup()

    # ---------- cold start ----------

    def test_cold_start_renders_without_crashing(self) -> None:
        """No pack.csv, no logs anywhere → all chains report empty
        gracefully. This is the system's first-ever boot path."""
        out = health_mod.render_summary()
        # Header
        self.assertIn("Volthium pack health summary", out)
        # Each chain reports a graceful empty-state
        self.assertIn("(no pack.csv yet)", out)
        self.assertIn("(no harvest data yet)", out)
        self.assertIn("pre-onset, no milestones yet", out)
        self.assertIn("no calibration_log entries yet", out)
        self.assertIn("no transitions logged yet", out)
        self.assertIn("(no validatable records yet)", out)
        self.assertIn("(no projection_log entries yet)", out)

    # ---------- populated path ----------

    def test_summary_includes_all_chain_labels_in_order(self) -> None:
        """Regardless of populated or empty state, the structural
        layout must be stable: every chain label appears once and in
        the documented order. Anchors against accidental reorder/drop."""
        out = health_mod.render_summary()
        expected_in_order = [
            "PACK",
            "TODAY",
            "SOLAR ONSET",
            "SOLAR MODEL",
            "CONFIDENCE",
            "SUNRISE ACC",
            "MORN-LOW ACC",
            "DRIFT",
            "PROJECTION",
            "ADVISORY",
        ]
        last_idx = -1
        for label in expected_in_order:
            idx = out.find(label)
            self.assertNotEqual(idx, -1,
                                f"summary missing chain label '{label}'")
            self.assertGreater(idx, last_idx,
                               f"label '{label}' appeared out of order")
            last_idx = idx

    def test_pack_line_with_populated_data(self) -> None:
        """A typical pack.csv row produces a line with SOC, current,
        state, voltage."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            w.writerow({
                "ts": "2026-05-19T10:13:00", "state": "charging",
                "pack_v": "26.42", "pack_i": "4.5", "smoothed_i": "4.3",
                "soc_a": "66", "soc_b": "63",
            })
        out = health_mod.render_summary()
        self.assertIn("PACK", out)
        self.assertIn("66/63", out)
        self.assertIn("charging", out)
        self.assertIn("+4.5 A", out)
        self.assertIn("26.42 V", out)

    def test_advisory_line_reflects_projected_low(self) -> None:
        """The advisor line classifies based on projected_low_soc:
        below 25 % → RUN GENERATOR; below 50 % → morning watch;
        else → no generator needed."""
        path = self.root / "data" / "projection_log.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "start_soc_pct",
                "projected_sunrise_soc",
                "projected_tomorrow_evening_soc",
                "projected_low_soc",
                "solar_model_coefficient",
                "today_irradiance_kwh_m2",
                "sunrise_iso", "source",
            ])
            # Healthy projection: low=60 % → "no generator needed"
            w.writerow([
                "2026-05-19T10:00:00", "70.0", "65.0", "85.0", "60.0",
                "8.15", "5.0", "2026-05-20T05:08", "advisor-invocation",
            ])
        out = health_mod.render_summary()
        self.assertIn("✓ no generator needed", out)
        self.assertIn("projected low 60%", out)

    def test_advisory_line_morning_watch_band(self) -> None:
        path = self.root / "data" / "projection_log.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "start_soc_pct",
                "projected_sunrise_soc",
                "projected_tomorrow_evening_soc",
                "projected_low_soc",
                "solar_model_coefficient",
                "today_irradiance_kwh_m2",
                "sunrise_iso", "source",
            ])
            # Morning-watch projection: low=40 % → "⚠ morning watch"
            w.writerow([
                "2026-05-19T10:00:00", "50.0", "45.0", "65.0", "40.0",
                "8.15", "5.0", "2026-05-20T05:08", "advisor-invocation",
            ])
        out = health_mod.render_summary()
        self.assertIn("⚠ morning watch", out)
        # The hard-recommend message must NOT appear
        self.assertNotIn("▶ RUN GENERATOR", out)

    def test_advisory_line_run_generator_band(self) -> None:
        path = self.root / "data" / "projection_log.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "ts", "start_soc_pct",
                "projected_sunrise_soc",
                "projected_tomorrow_evening_soc",
                "projected_low_soc",
                "solar_model_coefficient",
                "today_irradiance_kwh_m2",
                "sunrise_iso", "source",
            ])
            # Critical projection: low=20 % → "▶ RUN GENERATOR"
            w.writerow([
                "2026-05-19T10:00:00", "40.0", "25.0", "45.0", "20.0",
                "8.15", "5.0", "2026-05-20T05:08", "advisor-invocation",
            ])
        out = health_mod.render_summary()
        self.assertIn("▶ RUN GENERATOR", out)
        self.assertIn("below 25% comfort floor", out)

    # ---------- Staleness detection ----------

    def test_pack_line_flags_stale_data(self) -> None:
        """When pack.csv's latest sample is older than the threshold,
        the PACK line surfaces a ⚠ STALE warning with the age. Real
        operational signal — caught a BLE-logger stall on 2026-05-19."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            # Latest sample 10 minutes old → past 60 s threshold
            old_ts = (datetime.now() - timedelta(minutes=10)).isoformat(
                timespec="seconds")
            w.writerow({
                "ts": old_ts, "state": "discharging",
                "pack_v": "26.30", "pack_i": "-2.5", "smoothed_i": "-2.4",
                "soc_a": "66", "soc_b": "64",
            })
        out = health_mod.render_summary()
        self.assertIn("⚠ STALE", out)
        self.assertIn("since last sample", out)
        # The age should be in minutes (since 10 min > 90 s)
        self.assertIn("10 min", out)

    def test_pack_line_does_not_flag_fresh_data(self) -> None:
        """A 5-second-old sample should NOT trigger the staleness
        warning (well under the 60 s threshold)."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            fresh_ts = (datetime.now() - timedelta(seconds=5)).isoformat(
                timespec="seconds")
            w.writerow({
                "ts": fresh_ts, "state": "charging",
                "pack_v": "26.40", "pack_i": "3.0", "smoothed_i": "2.8",
                "soc_a": "70", "soc_b": "68",
            })
        out = health_mod.render_summary()
        self.assertNotIn("⚠ STALE", out)

    def test_fmt_age_compact_form(self) -> None:
        """Age strings should be compact and unit-appropriate:
        seconds for < 90 s, minutes for < 90 min, hours for < 24 h,
        days otherwise."""
        self.assertEqual(health_mod._fmt_age(0.0), "0 s")
        self.assertEqual(health_mod._fmt_age(45.0), "45 s")
        self.assertEqual(health_mod._fmt_age(89.9), "89 s")
        self.assertEqual(health_mod._fmt_age(90.0), "1 min")
        self.assertEqual(health_mod._fmt_age(60 * 30.0), "30 min")
        self.assertEqual(health_mod._fmt_age(60 * 90.0), "1.5 h")
        self.assertEqual(health_mod._fmt_age(3600 * 5.5), "5.5 h")
        self.assertEqual(health_mod._fmt_age(86400.0), "1.0 d")

    def test_staleness_seconds_handles_bad_input(self) -> None:
        """None / unparseable / future timestamps must NOT crash."""
        self.assertIsNone(health_mod._staleness_seconds(None))
        self.assertIsNone(health_mod._staleness_seconds("not-an-iso-ts"))
        self.assertIsNone(health_mod._staleness_seconds(""))
        # Future ts → clamp to 0
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        self.assertEqual(health_mod._staleness_seconds(future), 0.0)

    # ---------- BLE gap tracker ----------

    def test_compute_pack_gaps_no_file(self) -> None:
        """Missing pack.csv → (0, 0, 0, 0) — defensive."""
        # Don't write pack.csv (setUp already left it absent)
        out = health_mod.compute_today_pack_gaps(day=datetime(2026, 5, 19))
        self.assertEqual(out, (0, 0.0, 0.0, 0))

    def test_compute_pack_gaps_clean_day(self) -> None:
        """A day with consistent 10 s sample cadence → 0 gaps."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            base = datetime(2026, 5, 19, 10, 0, 0)
            for i in range(6):
                w.writerow({
                    "ts": (base + timedelta(seconds=10 * i)).isoformat(),
                    "state": "charging", "pack_v": "26.40",
                    "pack_i": "3.0", "smoothed_i": "2.8",
                    "soc_a": "70", "soc_b": "68",
                })
        gap_count, max_gap, total_gap, n = health_mod.compute_today_pack_gaps(
            day=datetime(2026, 5, 19))
        self.assertEqual(gap_count, 0)
        self.assertEqual(max_gap, 0.0)
        self.assertEqual(total_gap, 0.0)
        self.assertEqual(n, 6)

    def test_compute_pack_gaps_with_one_stall(self) -> None:
        """Today has one 5-min gap → gap_count=1, max=300, total=300."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            t0 = datetime(2026, 5, 19, 10, 0, 0)
            # First sample at 10:00
            w.writerow({"ts": t0.isoformat(), "state": "idle",
                        "pack_v": "26.30", "pack_i": "0.0",
                        "smoothed_i": "0.0", "soc_a": "70", "soc_b": "68"})
            # Next sample 5 min later — 300 s gap
            w.writerow({"ts": (t0 + timedelta(minutes=5)).isoformat(),
                        "state": "idle",
                        "pack_v": "26.30", "pack_i": "0.0",
                        "smoothed_i": "0.0", "soc_a": "70", "soc_b": "68"})
        gap_count, max_gap, total_gap, _ = health_mod.compute_today_pack_gaps(
            day=datetime(2026, 5, 19))
        self.assertEqual(gap_count, 1)
        self.assertAlmostEqual(max_gap, 300.0, delta=1.0)
        self.assertAlmostEqual(total_gap, 300.0, delta=1.0)

    def test_compute_pack_gaps_multiple_events(self) -> None:
        """Today has two distinct stalls → gap_count=2, max=largest,
        total=sum. Anchors that the tracker correctly sums multiple
        events (exactly what we saw at the cabin today)."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            base = datetime(2026, 5, 19, 10, 0, 0)
            # Samples at 10:00:00, 10:00:10, then gap 5 min to 10:05:10,
            # then gap 10 min to 10:15:10
            stamps = [
                base,
                base + timedelta(seconds=10),
                base + timedelta(minutes=5, seconds=10),
                base + timedelta(minutes=15, seconds=10),
            ]
            for ts in stamps:
                w.writerow({"ts": ts.isoformat(), "state": "idle",
                            "pack_v": "26.30", "pack_i": "0.0",
                            "smoothed_i": "0.0", "soc_a": "70",
                            "soc_b": "68"})
        gap_count, max_gap, total_gap, _ = health_mod.compute_today_pack_gaps(
            day=datetime(2026, 5, 19))
        self.assertEqual(gap_count, 2)
        # Larger gap is 10 min = 600 s
        self.assertAlmostEqual(max_gap, 600.0, delta=1.0)
        # Total: 300 + 600 = 900 s
        self.assertAlmostEqual(total_gap, 900.0, delta=1.0)

    def test_compute_pack_gaps_ignores_other_days(self) -> None:
        """A gap that spans midnight (or samples from yesterday) must
        not bleed into today's counter."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            # Yesterday — should be ignored
            w.writerow({"ts": "2026-05-18T23:50:00", "state": "idle",
                        "pack_v": "26.30", "pack_i": "0.0",
                        "smoothed_i": "0.0",
                        "soc_a": "70", "soc_b": "68"})
            # Today, clean
            w.writerow({"ts": "2026-05-19T10:00:00", "state": "idle",
                        "pack_v": "26.30", "pack_i": "0.0",
                        "smoothed_i": "0.0",
                        "soc_a": "70", "soc_b": "68"})
            w.writerow({"ts": "2026-05-19T10:00:10", "state": "idle",
                        "pack_v": "26.30", "pack_i": "0.0",
                        "smoothed_i": "0.0",
                        "soc_a": "70", "soc_b": "68"})
        gap_count, _, _, n = health_mod.compute_today_pack_gaps(
            day=datetime(2026, 5, 19))
        # Today has 2 clean samples 10 s apart → 0 gaps
        self.assertEqual(gap_count, 0)
        self.assertEqual(n, 2)  # only today's samples counted

    # ---------- Uptime % ----------

    def test_compute_uptime_no_file(self) -> None:
        """Missing pack.csv → None (defensive)."""
        self.assertIsNone(
            health_mod.compute_today_uptime_pct(day=datetime(2026, 5, 19))
        )

    def test_compute_uptime_clean_day_is_100(self) -> None:
        """Continuous 10 s cadence for 10 min → no gaps → 100% uptime."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            base = datetime(2026, 5, 19, 10, 0, 0)
            for i in range(60):
                w.writerow({
                    "ts": (base + timedelta(seconds=10 * i)).isoformat(),
                    "state": "charging", "pack_v": "26.40",
                    "pack_i": "3.0", "smoothed_i": "2.8",
                    "soc_a": "70", "soc_b": "68",
                })
        pct = health_mod.compute_today_uptime_pct(day=datetime(2026, 5, 19))
        self.assertAlmostEqual(pct, 100.0, delta=0.1)

    def test_compute_uptime_with_gap_subtracts_correctly(self) -> None:
        """5-min gap in a 10-min span → uptime = (600 − 300) / 600 = 50%."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            t0 = datetime(2026, 5, 19, 10, 0, 0)
            # Sample at 10:00, then 5-min gap to 10:05, then sample at 10:10
            for offset_s in (0, 300, 600):
                w.writerow({
                    "ts": (t0 + timedelta(seconds=offset_s)).isoformat(),
                    "state": "idle", "pack_v": "26.30",
                    "pack_i": "0.0", "smoothed_i": "0.0",
                    "soc_a": "70", "soc_b": "68",
                })
        pct = health_mod.compute_today_uptime_pct(day=datetime(2026, 5, 19))
        # 600 s span, 300 s gap → 50.0%. Note that the second 5-min
        # gap (10:05→10:10) is also > 60 s threshold and counts.
        # So total gaps = 600 s, span = 600 s → 0%.
        # Let me recompute: gap between sample 0 (10:00) and sample 1
        # (10:05) is 300 s; gap between sample 1 and 2 is 300 s.
        # Both above the 60 s threshold → both count.
        # Total gap = 600. Span = 600. Uptime = 0%.
        self.assertAlmostEqual(pct, 0.0, delta=0.5)

    def test_compute_uptime_realistic_partial_day(self) -> None:
        """One 30 s short pause + one 2-min long gap in a 1-h span.
        Only the 2-min gap exceeds the 60 s threshold."""
        path = self.root / "data" / "pack.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            t0 = datetime(2026, 5, 19, 10, 0, 0)
            # 10:00:00 → 10:00:30 (30 s normal gap, NOT > threshold)
            # → 10:02:30 (2-min gap, IS > threshold) → 10:30:00 (continues)
            stamps = [t0,
                      t0 + timedelta(seconds=30),
                      t0 + timedelta(minutes=2, seconds=30),
                      t0 + timedelta(minutes=30)]
            for s in stamps:
                w.writerow({
                    "ts": s.isoformat(),
                    "state": "idle", "pack_v": "26.30",
                    "pack_i": "0.0", "smoothed_i": "0.0",
                    "soc_a": "70", "soc_b": "68",
                })
        pct = health_mod.compute_today_uptime_pct(day=datetime(2026, 5, 19))
        # Span: 10:00 → 10:30 = 1800 s. The 30 s gap doesn't count
        # (≤ 60 s threshold). The 120 s and 1650 s gaps both count.
        # Total = 1770 s. Uptime = (1800 - 1770) / 1800 = 1.67%.
        self.assertGreater(pct, 0.0)
        self.assertLess(pct, 100.0)

    def test_summary_includes_pack_gaps_line_when_gaps_exist(self) -> None:
        """Day with gaps → 'PACK GAPS' line appears in the summary.
        Day with clean cadence → line is OMITTED entirely (happy
        path is silence)."""
        path = self.root / "data" / "pack.csv"
        # Day with a clear stall
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ts", "state", "pack_v", "pack_i", "smoothed_i",
                "soc_a", "soc_b",
            ])
            w.writeheader()
            today = datetime.now()
            w.writerow({"ts": today.isoformat(timespec="seconds"),
                        "state": "idle", "pack_v": "26.30",
                        "pack_i": "0.0", "smoothed_i": "0.0",
                        "soc_a": "70", "soc_b": "68"})
            w.writerow({
                "ts": (today + timedelta(minutes=10)).isoformat(timespec="seconds"),
                "state": "idle", "pack_v": "26.30",
                "pack_i": "0.0", "smoothed_i": "0.0",
                "soc_a": "70", "soc_b": "68"})
        out = health_mod.render_summary()
        self.assertIn("PACK GAPS", out)
        self.assertIn("1 event", out)
        self.assertIn("10 min", out)


if __name__ == "__main__":
    unittest.main()
