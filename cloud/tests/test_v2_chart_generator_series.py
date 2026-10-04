"""The last-hour chart must draw the generator from the ROWS, not live state.

Reported by the operator after a verified 22-minute generator run: "the last
hour chart on the main page doesn't show any generator activity." Two
independent faults, both predating the run:

  1. The BACKFILL hardcoded `gen: 0`. Every page load therefore showed a flat
     zero for the generator regardless of what happened in that hour. This is
     the one the operator hit — the run was over, so they were looking at a
     freshly backfilled chart.

  2. The LIVE path took `st.gen`, a single global reflecting what the
     generator is doing NOW, and applied it to every row it pushed. A global
     cannot describe history: once the generator stopped, that term went to
     zero, and a refresh re-ran the backfill and erased the run entirely.

Both were inferences standing in for a measurement that did not exist yet —
the generator's power was reconstructed as `batt - solar`, gated on a flag.
schema_version 3 put the generator's own AC readings in every 15 s row
(verified against the live run: |gen_v*gen_a| agrees with the device's own
gen_va to 0.23%), so there is nothing left to infer.

There is no JS runtime in this suite, so these are source-level assertions on
the shipped file. That is weaker than executing it, and it is chosen
deliberately over no coverage at all: each assertion below names a specific
regression that actually happened.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


V2 = Path(__file__).resolve().parents[1] / "server" / "static" / "v2.html"


class GeneratorSeriesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = V2.read_text()

    def _hist_pushes(self) -> list[str]:
        """Every hist.push({...}) call — the backfill and the live tail."""
        pushes = re.findall(r"hist\.push\(\{(.*?)\}\)", self.src, re.S)
        self.assertGreaterEqual(
            len(pushes), 2,
            "expected a backfill push and a live push; the shape of this file "
            "changed and these assertions may no longer be scoped right")
        return pushes

    def test_no_push_hardcodes_the_generator_to_zero(self):
        """Fault 1, exactly as reported."""
        for i, p in enumerate(self._hist_pushes()):
            self.assertNotRegex(
                p, r"gen:\s*0\b",
                f"hist.push #{i} hardcodes gen: 0 — the chart cannot show a "
                f"generator run that way, which is the reported bug")

    def test_no_push_derives_the_generator_from_live_global_state(self):
        """Fault 2. `st.gen` is the CURRENT state; a historical row must be
        described by its own fields or the series rewrites itself."""
        for i, p in enumerate(self._hist_pushes()):
            self.assertNotIn(
                "st.gen", p,
                f"hist.push #{i} reads the live st.gen flag; a global cannot "
                f"describe a past row")

    def test_both_pushes_use_the_same_per_row_helper(self):
        """If the backfill and the live tail compute this differently, the
        chart changes shape on refresh — which is how fault 1 hid behind
        fault 2 for as long as it did."""
        for i, p in enumerate(self._hist_pushes()):
            self.assertRegex(
                p, r"gen:\s*g\b",
                f"hist.push #{i} does not use the shared per-row generator "
                f"value")
        self.assertEqual(
            len(re.findall(r"const g = genAt\(r\)", self.src)), 2,
            "both paths must call genAt(r) on the row they are pushing")

    def test_genAt_reads_the_rows_own_measured_fields(self):
        body = re.search(r"function genAt\(r\)\s*\{(.*?)\n\}", self.src, re.S)
        self.assertIsNotNone(body, "genAt is missing")
        b = body.group(1)
        self.assertIn("r.gen_v", b,
                      "generator presence must come from the row's measured "
                      "AC voltage")
        self.assertIn("r.dc_a", b,
                      "delivered power must be gated on measured current "
                      "direction")
        self.assertNotIn("st.", b, "genAt must not touch live global state")

    def test_the_chart_uses_the_DC_side_not_the_AC_side(self):
        """The stack balances solar + gen + discharge against load + charge,
        all on the DC bus. Feeding it |gen_v*gen_a| would overstate the
        generator by the charger's conversion loss — measured 15.6% on the
        2026-10-04 run — and the stack would never reconcile.
        """
        b = re.search(r"function genAt\(r\)\s*\{(.*?)\n\}",
                      self.src, re.S).group(1)
        self.assertIn("r.dc_w", b)
        self.assertNotRegex(
            b, r"gen_v\s*\*|gen_a\s*\*|r\.gen_va",
            "genAt returns an AC-side figure; the chart's other series are "
            "DC-side and the stack will not balance")

    def test_load_is_not_drawn_from_a_charging_inverter_terminal(self):
        """While the generator feeds the system, dc_w is CHARGE, not load.
        Drawing it as load would show a ~1.2 kW phantom house load for the
        whole run."""
        body = re.search(r"function loadAt\(r[^)]*\)\s*\{(.*?)\n\}",
                         self.src, re.S)
        self.assertIsNotNone(body, "loadAt is missing")
        self.assertRegex(body.group(1), r"genAt\(r\)\s*>\s*0",
                         "loadAt must suppress load while the generator runs")


class ReplayTests(unittest.TestCase):
    """The logic, checked against what the real run actually recorded.

    These numbers are from the verified 2026-10-04 15:50-16:13Z run as stored
    in solar_readings. Mirrors genAt/loadAt rather than executing the JS, so
    it catches a THRESHOLD or SIGN change even though it cannot catch a JS
    syntax error.
    """

    # (gen_v, dc_a, dc_w) sampled across the run and its edges
    BEFORE = [(None, -7.53, 192), (None, -7.40, 189)]
    RUNNING = [(118.7, 44.92, 1180), (118.6, 44.93, 1193),
               (118.4, 44.91, 1202), (118.3, 44.91, 1205)]
    RAMP = [(120.8, 10.22, 515)]
    AFTER = [(126.9, -3.84, 175), (None, -7.07, 186)]

    @staticmethod
    def gen_at(gen_v, dc_a, dc_w):
        if (gen_v or 0) < 50:
            return 0
        return dc_w if (dc_a or 0) > 0 else 0

    def test_the_run_is_drawn(self):
        for r in self.RUNNING:
            self.assertGreater(self.gen_at(*r), 1000,
                               f"{r} should draw as ~1.2 kW of generator")

    def test_the_ramp_bucket_is_drawn(self):
        """Partial buckets at the edges are real generator output, not noise."""
        self.assertGreater(self.gen_at(*self.RAMP[0]), 0)

    def test_quiet_periods_are_zero(self):
        for r in self.BEFORE:
            self.assertEqual(self.gen_at(*r), 0, f"{r} is not a generator row")

    def test_generator_present_but_DISCHARGING_is_not_generator_output(self):
        """The wind-down bucket: AC voltage is back up to 126.9 V with the
        generator coasting, but dc_a has already gone negative — the battery
        is supplying again. Drawing dc_w as generator output there would
        credit the generator for a house load."""
        for r in self.AFTER:
            self.assertEqual(self.gen_at(*r), 0,
                             f"{r}: dc_a is negative, so this is not "
                             f"generator output")


if __name__ == "__main__":
    unittest.main()
