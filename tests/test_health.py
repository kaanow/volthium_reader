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


if __name__ == "__main__":
    unittest.main()
