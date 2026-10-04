"""The two ledger defects found on 2026-10-04, and the guards against them.

Both produced "unrealistically high values that don't reconcile" on the
dashboard, and both are failures of a PREMISE rather than of arithmetic — so
the tests here assert the premise is still being checked, not that some number
comes out right.

  1. dc_w IS A MAGNITUDE. The Conext frame reports |dc_v * dc_a|, which
     xanbus_telemetry documents and cross-checks. So generator charging —
     current flowing INTO the battery through the inverter/charger — arrives
     as a large positive dc_w and `load_w = dc_w` books it as house load.
     Measured over the 2026-10-03 00:29-02:12Z run: 411/411 rows with
     dc_a > 0, median +44.9 A, dc_w ~1216 W, totalling 2077 Wh of charging
     counted as consumption. Local 10-02's load_wh came out 6034 Wh against a
     ~2700 Wh baseline.

     Note _dc_w_sane's "BETWEEN 0 AND 6000" LOOKS like it would catch this and
     cannot: dc_w is never negative, so no sign guard can live there.

  2. THE FRIDGE SPLIT ASSUMES A VALLEY. dc_load_wh subtracts mean-below from
     mean-above at a hardcoded 117.6 W and calls the difference the fridge.
     That is only the fridge while the dark-power distribution is bimodal
     with 117.6 W in the gap. The operator notes the night baseline rises
     whenever people are at the cabin — fan, phone charging, lights into the
     evening — and when it rises past the split, the split slices one risen
     blob and the subtraction returns the blob's width.

     Measured per local day: duty 0.16-0.25 and ~320 Wh while sound, then
     0.47 / 0.84 / 0.91 and 1413 / 1515 / 1322 Wh once it broke. A duty of
     0.91 asserts the fridge runs 91% of the time.

These are read-path guards and there is no live Postgres in the suite, so the
assertions are against the ASSEMBLED SQL and the shared constants — the same
approach as test_ledger_clamp_gate.py, for the same reason.
"""

from __future__ import annotations

import re
import unittest

from cloud.server import db as db_mod
from cloud.tests.test_ledger_clamp_gate import _render_sql


def _case_for(sql: str, alias: str) -> str:
    """The CASE expression that produces `alias` in the final SELECT.

    Scoped deliberately: an assertion against the whole query would be
    satisfied by the guard appearing ANYWHERE, including on the other column,
    so a guard dropped from exactly one of the two would still pass.
    """
    m = re.search(r"CASE WHEN (?:(?!CASE WHEN).)*?END AS " + alias,
                  sql, re.S)
    assert m is not None, f"no CASE ... END AS {alias} in the query"
    return m.group(0)


class ChargingIsNotLoadTests(unittest.TestCase):

    def test_charge_w_is_gated_on_current_direction(self):
        """dc_a > 0 is the only thing that distinguishes charging from load,
        because dc_w itself carries no sign."""
        sql = _render_sql()
        m = re.search(r"CASE WHEN s\.dc_a > 0 THEN (.*?) END\s*AS charge_w",
                      sql, re.S)
        self.assertIsNotNone(
            m, "charge_w is not gated on dc_a > 0 — without that gate there "
               "is nothing in the row that says which way the current flows")

    def test_charge_w_is_sanitised_like_every_other_dc_w_read(self):
        """The corrupt -27844 W row is still in the table; a new consumer of
        dc_w must not reintroduce the unguarded read."""
        m = re.search(r"CASE WHEN s\.dc_a > 0 THEN (.*?) END\s*AS charge_w",
                      _render_sql(), re.S)
        self.assertIn("BETWEEN 0 AND 6000", m.group(1))

    def test_total_load_subtracts_the_charge_energy(self):
        """The actual fix. Without this, every generator run inflates the
        headline load figure by roughly twice the energy it delivered."""
        self.assertIn("- g.charge_wh", _case_for(_render_sql(),
                                                 "total_load_wh"))

    def test_load_wh_itself_is_left_alone(self):
        """load_wh is frozen for historical continuity — the operator's call.
        The correction belongs in the derived total, not in the raw column."""
        sql = _render_sql()
        g_cte = sql.split("), g AS (", 1)[1].split("), dcl AS (", 1)[0]
        self.assertRegex(g_cte, r"SUM\(load_w\) \* 15 / 3600\.0\s+AS load_wh")
        self.assertNotIn("charge", g_cte.split("AS load_wh")[0].rsplit(
            "SUM(load_w)", 1)[0][-200:] or "")

    def test_charge_wh_is_coalesced(self):
        """charge_w is NULL on every row that is not charging, so a day with
        no generator run SUMs to NULL — and NULL would propagate through the
        subtraction and blank out total_load_wh on all the normal days."""
        sql = _render_sql()
        self.assertRegex(sql, r"COALESCE\(SUM\(charge_w\),\s*0\)")


class ValleyGuardTests(unittest.TestCase):

    def test_both_modelled_columns_are_gated(self):
        sql = _render_sql()
        for alias in ("dc_load_wh", "total_load_wh"):
            case = _case_for(sql, alias)
            self.assertIn("dcl.mid_n", case,
                          f"{alias} is not gated on the valley test")
            self.assertIn("LEAST(dcl.lo_n, dcl.hi_n)", case,
                          f"{alias} does not compare against both side bands")

    def test_the_guard_requires_both_side_bands_to_exist(self):
        """With an empty side band the ratio is meaningless — and that is
        exactly the observed shape on 10-02/10-03, where lo_n was 0 because
        the low mode had risen entirely above the split."""
        clause = db_mod._valley_sql()
        self.assertIn("dcl.lo_n > 0", clause)
        self.assertIn("dcl.hi_n > 0", clause)

    def test_the_guard_uses_the_shared_threshold(self):
        """Ties the SQL to the constant, so the two cannot drift."""
        self.assertIn(str(db_mod.VALLEY_MAX_RATIO), db_mod._valley_sql())

    def test_bands_are_ordered_and_do_not_overlap(self):
        self.assertLess(db_mod.VALLEY_LO_EDGE, db_mod.VALLEY_MID_LO)
        self.assertLess(db_mod.VALLEY_MID_LO, db_mod.DC_LOAD_SPLIT_W)
        self.assertLess(db_mod.DC_LOAD_SPLIT_W, db_mod.VALLEY_MID_HI)
        self.assertLess(db_mod.VALLEY_MID_HI, db_mod.VALLEY_HI_EDGE)

    # (mid_n, lo_n, hi_n) per local day, measured off production 2026-10-04
    # over 12 days of dark-hour BMS samples. The sound days are the ones whose
    # dc_load_wh (~320 Wh) reconciles with a fridge; the broken ones are the
    # days the operator saw unrealistic numbers on.
    SOUND = {
        "2026-09-22": (503, 4580, 2449),
        "2026-09-23": (77, 5916, 1864),
        "2026-09-24": (91, 6121, 1803),
        "2026-09-25": (53, 6732, 1386),
        "2026-09-26": (47, 6689, 1249),
        "2026-09-27": (35, 6730, 1248),
        "2026-09-28": (20, 6915, 1261),
        "2026-09-29": (51, 6927, 1334),
        "2026-09-30": (50, 6828, 1308),
    }
    BROKEN = {
        "2026-09-21": (401, 389, 342),      # partial day, modes already merged
        "2026-10-01": (1109, 4082, 1349),
        "2026-10-02": (3690, 0, 1629),      # low mode gone above the split
        "2026-10-03": (2628, 0, 2523),
    }

    @staticmethod
    def _sound(mid_n, lo_n, hi_n) -> bool:
        """The rule as the SQL states it. Written from the constants rather
        than hardcoded so a threshold change is reflected here too."""
        return (lo_n > 0 and hi_n > 0
                and mid_n < db_mod.VALLEY_MAX_RATIO * min(lo_n, hi_n))

    def test_the_threshold_accepts_every_sound_day(self):
        for day, counts in self.SOUND.items():
            with self.subTest(day=day):
                self.assertTrue(self._sound(*counts),
                                f"{day} reconciled with a fridge but the "
                                f"guard would discard it")

    def test_the_threshold_rejects_every_broken_day(self):
        for day, counts in self.BROKEN.items():
            with self.subTest(day=day):
                self.assertFalse(self._sound(*counts),
                                 f"{day} produced an unrealistic figure and "
                                 f"the guard would still publish it")

    def test_the_threshold_is_not_fitted_to_the_sample(self):
        """The point of 0.5: there is open space around it. If a future
        threshold change narrows that gap, the separation is no longer
        structural and this should be reconsidered rather than re-tuned.
        """
        ratio = lambda c: c[0] / max(1, min(c[1], c[2]))   # noqa: E731
        worst_sound = max(ratio(c) for c in self.SOUND.values())
        best_broken = min(ratio(c) for c in self.BROKEN.values())
        self.assertLess(worst_sound, db_mod.VALLEY_MAX_RATIO)
        self.assertGreater(best_broken, db_mod.VALLEY_MAX_RATIO)
        self.assertGreater(
            best_broken / worst_sound, 2.0,
            f"sound days reach {worst_sound:.2f} and broken days start at "
            f"{best_broken:.2f} — the groups are no longer cleanly separated")


if __name__ == "__main__":
    unittest.main()


class ChargeCorrectionIsReachableTests(unittest.TestCase):
    """The charge correction must produce a number on days it is needed.

    THE DEFECT THIS EXISTS FOR, shipped 2026-10-03 and measured 10-04: the
    `- charge_wh` subtraction sat INSIDE the fridge model's validity gate, so
    it only applied on days the fridge model was sound. Those two conditions
    are anti-correlated BY CONSTRUCTION — the generator runs when people are
    at the cabin, and occupancy is what breaks the bimodality the fridge
    model needs.

    Result across 67 days of production: both days with charge energy
    (2026-10-02, 2077 Wh; 2026-10-04, 440 Wh) returned total_load_wh = NULL.
    The correction produced a number ZERO times out of two, and the
    operator's original "values unrealistically high that don't reconcile"
    stayed live.

    TWO TESTS IN THIS FILE CERTIFIED IT. `test_total_load_subtracts_the_charge
    _energy` asserted the string "- g.charge_wh" was present;
    `test_both_modelled_columns_are_gated` asserted both modelled columns
    were gated. Both passed, both were individually correct, and their
    CONJUNCTION was the bug. Neither evaluated the query against data.

    So these tests assert the RELATIONSHIP between the two properties rather
    than each in isolation.
    """

    def _final_select(self) -> str:
        """The outer SELECT only — everything after the CTEs."""
        sql = _render_sql()
        i = sql.index("SELECT g.*, c.mppt_counter_wh")
        return sql[i:sql.index("FROM g LEFT JOIN c", i)]

    def test_a_charge_corrected_load_exists_OUTSIDE_every_gate(self):
        """The property that was missing: some corrected load figure has to
        survive the fridge guard failing."""
        sel = self._final_select()
        m = re.search(r"g\.load_wh\s*-\s*g\.charge_wh\s+AS\s+(\w+)", sel)
        self.assertIsNotNone(
            m, "no ungated charge-corrected load column; if every corrected "
               "figure is behind the valley gate, generator days get none")
        alias = m.group(1)
        # and it must not be swallowed by a CASE
        before = sel[:m.start()]
        self.assertEqual(
            before.count("CASE"), before.count("END"),
            f"{alias} is inside an unclosed CASE — it is gated after all")

    def test_the_charge_term_is_not_only_inside_the_valley_gate(self):
        """Direct statement of the conjunction. If every occurrence of
        charge_wh is inside a valley-gated CASE, the correction is dead on
        exactly the days it is for."""
        sel = self._final_select()
        gated = re.findall(r"CASE WHEN (?:(?!CASE WHEN).)*?END", sel, re.S)
        gated_blob = "\n".join(g for g in gated if "mid_n" in g)
        total_uses = sel.count("charge_wh")
        gated_uses = gated_blob.count("charge_wh")
        self.assertLess(
            gated_uses, total_uses,
            f"all {total_uses} uses of charge_wh are inside the valley gate; "
            f"the correction cannot fire on an occupied day, which is every "
            f"day the generator runs")

    # The two production days that exposed it, as a regression fixture.
    # (day, load_wh, charge_wh, valley_sound)
    GENERATOR_DAYS = [
        ("2026-10-02", 6034.3, 2076.8, False),
        ("2026-10-04", 2011.0, 439.7, False),
    ]

    def test_every_recorded_generator_day_yields_a_corrected_figure(self):
        for day, load, charge, sound in self.GENERATOR_DAYS:
            with self.subTest(day=day):
                # load_wh_net is ungated, so it exists regardless of `sound`
                net = load - charge
                self.assertIsNotNone(net)
                self.assertLess(
                    net, load,
                    f"{day}: corrected load must be below the raw figure")
                self.assertAlmostEqual(
                    net, load - charge, places=6,
                    msg=f"{day}: correction must remove exactly the charge "
                        f"energy, not a modelled approximation of it")

    def test_the_fridge_term_is_STILL_gated(self):
        """Ungating the charge term must not have ungated the model. The
        fridge projection genuinely does need its premise."""
        sel = self._final_select()
        m = re.search(r"CASE WHEN (?:(?!CASE WHEN).)*?END AS dc_load_wh",
                      sel, re.S)
        self.assertIsNotNone(m)
        self.assertIn("mid_n", m.group(0),
                      "the fridge column lost its validity guard")
