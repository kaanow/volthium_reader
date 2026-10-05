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


def _code_only(js: str) -> str:
    """JS with comments stripped.

    Four separate assertions today matched their own EXPLANATION rather than
    the code: a docstring saying "strongly bimodal", a comment describing a
    removed flag, and here a comment naming `st.gen` while explaining why
    `st.gen` is gone. Source text includes the reasoning, so any assertion
    about what the code DOES has to drop the prose first.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)     # block comments
    js = re.sub(r"(?<![:\w])//[^\n]*", "", js)        # line comments, not URLs
    return js


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


class GeneratorIsNotHouseLoadAnywhereTests(unittest.TestCase):
    """The per-row treatment must cover every surface, not just the chart.

    Fixing the strip chart (4ab3517) left four other places reading the
    charger's DC draw as house load, found by the 2026-10-04 review:

      - the Loads tile and badge gated on the live `st.gen` global, refreshed
        at most every 120 s. Measured at 15:50:45Z the row had dc_a +44.93 /
        dc_w 1174, so the tile read "Loads 1174 W" with the badge "running on
        sun" while the chart directly beneath showed gen 1174 / loads 0 FOR
        THE SAME ROW.
      - the history ledger rendered load_wh, never subtracting charge_wh:
        2026-10-02 showed "loads out 6.03 kWh" against 3.96 true (+52%).
      - the heatmap was colour-scaled by the maximum, so one 1217 W generator
        hour pushed a typical 160 W cell from ~82% to 30% opacity.
      - the system table's `Math.abs(s.dc_a)` discarded the sign genAt()
        depends on, labelling 44.93 A of charge current "Inverter (AC loads)".
    """

    @classmethod
    def setUpClass(cls):
        cls.v2 = V2.read_text()
        cls.hist = (V2.parent / "v2-history.html").read_text()

    def test_the_loads_tile_asks_the_row_not_the_global(self):
        m = re.search(r"function loadW\(\)\s*\{(.*?)\n\}", self.v2, re.S)
        self.assertIsNotNone(m)
        body = _code_only(m.group(1))
        self.assertIn("genAt(", body,
                      "loadW still gates on the lagging st.gen global")
        self.assertNotIn("st.gen", body)

    def test_solar_inference_asks_the_row_too(self):
        m = re.search(r"function solarInfo\(\)\s*\{(.*?)\n\}", self.v2, re.S)
        self.assertIsNotNone(m)
        body = _code_only(m.group(1))
        self.assertIn("genAt(", body)
        self.assertNotIn("st.gen ?", body)

    def test_charge_current_is_not_labelled_inverter_load(self):
        """A source on the sink side also broke the balance gap by ~2.3 kW."""
        m = re.search(r"const invA = (.*?);", self.v2, re.S)
        self.assertIsNotNone(m)
        self.assertIn("dc_a > 0", m.group(1),
                      "invA still takes the magnitude, so charge current "
                      "renders as AC load")

    def test_EVERY_served_page_uses_the_corrected_total(self):
        """BOTH history pages, derived from main.py's FileResponse routes.

        I fixed v2-history.html on the reviewer's file:line and deployed it
        before noticing that /history serves history.html — the other one.
        The live page still rendered the uncorrected load_wh. Exactly the
        "two implementations, fix one and forget the other" trap the review
        flagged for scripts/dashboard.py, walked into by trusting a file
        reference without checking which file is served.

        So the scope is now the set of pages the server actually serves.
        """
        main_src = (Path(__file__).resolve().parents[1]
                    / "server" / "main.py").read_text()
        served = set(re.findall(r'STATIC_DIR / "([\w.-]+\.html)"', main_src))
        self.assertTrue(served, "could not derive the served pages")
        checked = 0
        for name in sorted(served):
            page = V2.parent / name
            if not page.exists():
                continue
            # STRIP COMMENTS. Checking raw text passed a mutation that
            # reverted the live page, because the explanatory comment left
            # behind still contained the string "load_wh_net". Fifth time
            # today an assertion was satisfied by its own explanation.
            txt = _code_only(page.read_text())
            if "load_wh" not in txt:
                continue          # page does not render the ledger
            checked += 1
            with self.subTest(page=name):
                self.assertIn(
                    "load_wh_net", txt,
                    f"{name} is served and renders load_wh without the "
                    f"charge correction")
        self.assertGreaterEqual(
            checked, 2, "expected both history pages to render the ledger")

    def test_the_history_ledger_uses_the_corrected_total(self):
        self.assertIn("load_wh_net", self.hist,
                      "the ledger chart still renders the uncorrected load_wh")
        self.assertRegex(self.hist, r"const loadOf = d =>",
                         "no single accessor, so the bars, tooltip and tile "
                         "can drift apart again")
        # every place that reads a day's load must go through it
        for frag in ("const sol = d.solar_wh || 0, load = loadOf(d);",
                     "loadOf(d)"):
            self.assertIn(frag, self.hist)

    def test_the_ledger_falls_back_for_rows_predating_the_field(self):
        """load_wh_net did not exist before 2026-10-04; those days must still
        render rather than collapsing to zero."""
        m = re.search(r"const loadOf = d => (.*?);", self.hist, re.S)
        self.assertIn("load_wh", m.group(1))
        self.assertIn("!= null", m.group(1))

    def test_the_heatmap_is_not_scaled_by_its_maximum(self):
        """One generator hour washed out 21 days of cells."""
        m = re.search(r"const max = (.*?);", self.hist, re.S)
        self.assertIsNotNone(m)
        self.assertNotRegex(
            m.group(1), r"\.\.\.cells\.map",
            "the heatmap still scales to the maximum cell")
        self.assertIn("p95", m.group(1))

    def test_the_heatmap_note_states_what_the_meter_cannot_see(self):
        """It said "average house draw", which is wrong twice: dc_w is blind
        to the bus-wired fridge, and it includes generator charging."""
        m = re.search(r'Average <b>inverter DC input</b>(.*?)</p>',
                      self.hist, re.S)
        self.assertIsNotNone(m, "the heatmap note still claims house draw")
        self.assertIn("fridge", m.group(1))
        self.assertIn("generator", m.group(1))


class ChargeStageNamesItsDeviceTests(unittest.TestCase):
    """"charging · not_charging" — both halves true, from different devices.

    Reported by the operator from a live screenshot: the battery was taking
    +639 W from 408 W of solar while the chip read not_charging. The BMS said
    charging; the newest chg_stage said not_charging — but that was the SW
    inverter/charger correctly reporting it had stopped when the generator was
    shut off at 19:11, while the MPPT had been in BULK since 17:38.

    There is no window that fixes this. The two devices interleave, so
    "the newest chg_stage" is just whichever spoke last.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _code_only(V2.read_text())

    def test_both_devices_are_queried_separately(self):
        self.assertIn('one("chg_stage", "mppt")', self.src)
        self.assertIn('one("chg_stage", "sw")', self.src)

    def test_the_query_filters_server_side(self):
        """Fetching a batch and picking client-side would reintroduce a
        window assumption — exactly what buried gen_start behind chg_stage
        churn."""
        self.assertIn("&node=", self.src)

    def test_there_is_no_single_stage_key_left(self):
        """One key cannot hold two devices' stages, and a stale one is how
        the wrong value got displayed."""
        self.assertNotIn("st.stage", self.src)
        self.assertIn("mpptStage", self.src)
        self.assertIn("swStage", self.src)

    def test_the_chip_names_the_source(self):
        """"bulk" means something different from the charger than from the
        array, so the label has to say which."""
        self.assertIn("(generator)", self.src)
        self.assertIn("(solar)", self.src)

    def test_the_generator_takes_precedence_when_both_charge(self):
        """During a run both can be in bulk; the generator is the notable
        one because it costs fuel."""
        i = self.src.index("swOn")
        j = self.src.index("mpptOn", i)
        self.assertLess(i, j, "the sw branch must be tested first")


class DisplayHonestyTests(unittest.TestCase):
    """Text and windows that claimed more than they delivered."""

    @classmethod
    def setUpClass(cls):
        cls.v2 = V2.read_text()
        cls.hist = (V2.parent / "v2-history.html").read_text()

    def test_the_latch_banner_does_not_promise_a_bound_the_guard_breaks(self):
        """"clears within ~20 min" rested on a figure from a truncated run
        (regenerated: 14.1 min median, n=2) AND is contradicted by the
        guard's own constants: a 45 min cooldown and a 6/day cap."""
        self.assertNotIn("automatically within", self.v2)
        self.assertIn("45 min", self.v2, "the cooldown must be stated")
        self.assertIn("6 attempts", self.v2, "the daily cap must be stated")

    def test_the_events_heading_does_not_claim_a_fixed_window(self):
        """It said "last 14 days" and rendered 2 h 25 min."""
        self.assertNotIn("last 14 days", self.hist)
        self.assertIn("evspan", self.hist,
                      "the rendered span must be computed and shown")

    def test_an_api_failure_is_not_rendered_as_an_empty_system(self):
        """jget returned r.json() unconditionally, so every section fell back
        to `|| []` and printed "no data yet" — cannot-look reported as
        looked-and-fine."""
        m = re.search(r"async function jget\(u\)\s*\{(.*?)\n\}",
                      self.hist, re.S)
        self.assertIsNotNone(m)
        self.assertIn("r.ok", m.group(1))

    def test_solar_staleness_is_surfaced_separately_from_the_bms(self):
        """The chip aged only /api/latest, so a dead xanbus reader left every
        solar tile hours old and unflagged while it read "discharging"."""
        code = _code_only(self.v2)
        self.assertIn("solarStale", code)
        self.assertIn("SOLAR STALE", self.v2)

    def test_the_solar_threshold_clears_the_upload_batch(self):
        """Solar uploads in 300 s batches, so a tighter threshold would fire
        on the normal sawtooth every cycle."""
        m = re.search(r"solarAgeS > (\d+)", _code_only(self.v2))
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 900)
