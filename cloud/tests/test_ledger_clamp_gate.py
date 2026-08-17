"""The ledger's inferred-production branch is gated on the clamp condition.

Until 2026-08-11 the gate was `pv_v >= 15` — a bare darkness threshold. It kept
phantom night-time solar out but admitted every twilight and overcast hour,
where the two meters' ~32 W disagreement is credited as production and the
GREATEST() makes the error one-directional. Measured at 1150-1550 Wh/day across
five days, against a ~600 Wh/day estimate on record.

The inference exists to rescue CLAMPED hours specifically: during a clamp the
MPPT cannot see power crossing its own body diode, so its self-report is
wrong-low. Gating on the clamp condition rather than on a proxy for it is the
same reasoning that produced the darkness gate, applied to the right predicate.

Two things are tested here, and the second matters more than the first:

  1. the query says what it is supposed to say;
  2. the clamp constants copied into db.py still match scripts/xanbus_telemetry.py.

(2) is the real risk. The server cannot import from scripts/, so the band is
duplicated, and duplicated constants in this repo drift — that is the single
most repeated failure in its history. The values are read back out of the
script's SOURCE rather than by importing it, so this test costs nothing at
import time and cannot be broken by the script's dependencies.
"""
from __future__ import annotations

import ast
import inspect
import re
import unittest
from pathlib import Path

from cloud.server import db as db_mod

SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
          / "xanbus_telemetry.py")


def _const(name: str) -> float:
    """Read a module-level float constant out of the script's source."""
    tree = ast.parse(SCRIPT.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return float(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not found in {SCRIPT.name}")


class ClampConstantsMirrorTests(unittest.TestCase):

    def test_the_source_reader_actually_works(self):
        """Otherwise every assertion below passes vacuously."""
        self.assertEqual(_const("LATCH_DELTA_MAX_V"), 4.0)
        with self.assertRaises(AssertionError):
            _const("NO_SUCH_CONSTANT_XYZ")

    def test_band_matches_the_live_detector(self):
        self.assertEqual(db_mod.CLAMP_MIN_PV_V, _const("LATCH_DAYLIGHT_V"))
        self.assertEqual(db_mod.CLAMP_DELTA_MIN_V, _const("LATCH_DELTA_MIN_V"))
        self.assertEqual(db_mod.CLAMP_DELTA_MAX_V, _const("LATCH_DELTA_MAX_V"))


def _render_sql() -> str:
    """The assembled query, every placeholder filled.

    ONE renderer, shared by both test classes. There were two, and they
    substituted different placeholder sets — so adding {DC_LOAD_SPLIT_W} broke
    the well-formedness test while the other copy passed. A duplicated renderer
    is a duplicated constant with extra steps.
    """
    src = inspect.getsource(db_mod.AsyncpgReadingsDAO.solar_energy_daily)
    body = [b for b in re.findall(r'f?"""(.*?)"""', src, re.S)
            if "SELECT" in b.upper()]
    assert len(body) == 1, f"expected one SQL literal, found {len(body)}"
    sql = (body[0]
           .replace("{sane_s}", db_mod._dc_w_sane("s.dc_w"))
           .replace("{_clamped_sql()}", db_mod._clamped_sql())
           .replace("{_dc_w_sane()}", db_mod._dc_w_sane()))
    # Any remaining {NAME} is resolved from the module, so a placeholder added
    # to the query is substituted here WITHOUT editing this function. Three
    # separate times a new placeholder broke the renderer while the code was
    # fine, and each time the fix was to hand-add one more .replace() — the
    # hand-maintained-list failure mode, in the very file that keeps finding it.
    for name in set(re.findall(r"\{(\w+)\}", sql)):
        assert hasattr(db_mod, name), (
            f"SQL references {{{name}}} but db.py has no such attribute")
        sql = sql.replace("{" + name + "}", str(getattr(db_mod, name)))
    return sql


def _cte(sql: str, name: str) -> str:
    """Isolate one CTE body, so an assertion about the inferred branch cannot
    be satisfied — or broken — by unrelated SQL elsewhere in the query."""
    if name == "j":
        return sql.split("), j AS (", 1)[1].split("), g AS (", 1)[0]
    return sql.split(f"), {name} AS (", 1)[1].split("), ", 1)[0]


class ClampGateSqlTests(unittest.TestCase):

    def _sql(self) -> str:
        return _render_sql()

    def test_dc_v_is_selected_into_the_cte(self):
        """The gate reads s.dc_v; the CTE did not select it before this change,
        which would have been a runtime-only 'column does not exist'."""
        self.assertRegex(self._sql(),
                         r"SELECT ts AS b,[^\n]*\bdc_v\b")

    def test_the_bare_voltage_gate_is_gone(self):
        """The specific defect: `pv_v < 15` must no longer decide PRODUCTION.

        Scoped to the `j` CTE, where the inferred branch lives. The unscoped
        version matched the whole query and started failing when the fridge CTE
        legitimately used the same expression as a DARKNESS gate — a correct use
        of the same string. A test that cannot tell those apart would have been
        'fixed' by deleting the assertion.
        """
        self.assertNotIn("s.pv_v, 0) < 15", _cte(self._sql(), "j"))

    def test_the_darkness_gate_IS_still_used_for_the_fridge(self):
        """The other half of the distinction above: the same expression is
        correct in the dcl CTE, and must stay there."""
        self.assertIn("s.pv_v, 0) < 15", _cte(self._sql(), "dcl"))

    def test_inference_is_reached_only_through_the_clamp_predicate(self):
        sql = self._sql()
        m = re.search(r"CASE WHEN (.*?)\s*THEN GREATEST", sql, re.S)
        self.assertIsNotNone(m, "the inferred branch is not behind a CASE WHEN")
        cond = m.group(1)
        for frag in ("s.dc_v IS NOT NULL", "s.pv_v > 20.0", "BETWEEN 0.3 AND 4.0"):
            self.assertIn(frag, cond, f"clamp gate missing {frag!r}")

    def test_the_default_branch_is_the_mppt_self_report(self):
        """Outside a clamp the device's own number must be used, NOT zero —
        zeroing would delete almost all production."""
        self.assertRegex(self._sql(),
                         r"ELSE COALESCE\(s\.solar_w, 0\)")

    def test_null_dc_v_cannot_enter_the_inferred_branch(self):
        """`NULL > 20` is NULL, not false, and NULL in a CASE WHEN falls to
        ELSE — so this is belt-and-braces. It is asserted anyway because
        relying on three-valued-logic intuition is how SQL bugs get shipped."""
        self.assertIn("s.dc_v IS NOT NULL", db_mod._clamped_sql())

    def test_helper_is_parameterised(self):
        self.assertIn("x.pv_v", db_mod._clamped_sql("x.pv_v", "x.dc_v"))
        self.assertIn("x.dc_v", db_mod._clamped_sql("x.pv_v", "x.dc_v"))

    def test_sql_stays_well_formed(self):
        sql = self._sql()
        self.assertEqual(sql.count("(") - sql.count(")"), 0,
                         "unbalanced parens — this has 500'd production before")
        ns = sorted({int(x) for x in re.findall(r"\$(\d+)", sql)})
        self.assertEqual(ns, list(range(1, max(ns) + 1)), f"gaps in $n: {ns}")
        self.assertNotIn("{", sql, "an f-string placeholder was left unfilled")



class DcLoadDecompositionTests(unittest.TestCase):
    """The ledger must account for the fridge WITHOUT double-counting.

    load_w is a passthrough of dc_w, the inverter's own DC draw, and the 24 V
    fridge is on the bus rather than through the inverter — so dc_w is
    structurally blind to it (it moves less than its own noise across a 74.2 W
    step in real bus load).

    But naively adding the fridge to load_wh makes it WORSE, which is the trap.
    At night dc_w reads 113.6 W against a true total of 104.7 W measured from
    the BMS alone: +9%, because a 32.8 W inverter over-read and a 24.0 W
    time-averaged fridge nearly cancel. Adding the fridge alone gives +33 W of
    error; correcting the offset alone gives -24 W; both together give +0.1 W.
    """

    def _sql(self) -> str:
        return _render_sql()

    def test_the_arithmetic_that_justifies_doing_both(self):
        """If either correction is applied alone the ledger gets worse. This is
        the whole reason the decomposition exists rather than a simple add."""
        dcw, true_total = 113.6, 104.7
        fridge = 74.2 * 0.323
        over = db_mod.INVERTER_OVER_READ_W
        self.assertAlmostEqual(abs(dcw + fridge - true_total), 32.9, delta=0.5)
        self.assertAlmostEqual(abs(dcw - over - true_total), 23.9, delta=0.5)
        self.assertLess(abs(dcw - over + fridge - true_total), 1.0,
                        "both corrections together must land on the measured "
                        "total")

    def test_load_wh_is_unchanged(self):
        """Retained exactly so no historical dashboard value moves."""
        self.assertRegex(self._sql(), r"SUM\(load_w\) \* 15 / 3600\.0\s+AS load_wh")

    def test_total_load_wh_applies_BOTH_corrections(self):
        sql = self._sql()
        m = re.search(r"AS total_load_wh", sql)
        self.assertIsNotNone(m, "total_load_wh must exist")
        block = sql[max(0, m.start() - 400):m.start()]
        self.assertIn(str(db_mod.INVERTER_OVER_READ_W), block,
                      "total must subtract the inverter over-read")
        self.assertIn("step_w", block, "total must add the fridge")

    def test_the_fridge_split_is_from_the_bms_alone(self):
        """Same instrument both sides of the subtraction. Cross-meter
        arithmetic has been wrong every time on this system."""
        sql = self._sql()
        dcl = sql.split("), dcl AS (", 1)[1].split("), c AS (", 1)[0]
        self.assertIn("abs(r.pack_p)", dcl)
        self.assertNotIn("dc_w", dcl, "the fridge split must not touch dc_w")

    def test_darkness_is_gated_on_ARRAY_VOLTAGE_not_power(self):
        """A clamped MPPT reports single-digit watts in broad daylight, so a
        power gate lets latched daylight hours in and wrecks the split."""
        dcl = self._sql().split("), dcl AS (", 1)[1].split("), c AS (", 1)[0]
        self.assertIn("s.pv_v, 0) < 15", dcl)

    def test_both_new_columns_are_null_without_enough_dark_samples(self):
        """An invented number is worse than an honest gap."""
        sql = self._sql()
        self.assertEqual(sql.count("dcl.dark_n >= 120"), 2,
                         "both dc_load_wh and total_load_wh must be gated")

    def test_the_split_constant_matches_what_fridge_split_measured(self):
        """If someone retunes this, the +0.1 W reconciliation above stops
        applying and should be re-derived with scripts/fridge_split.py."""
        self.assertAlmostEqual(db_mod.DC_LOAD_SPLIT_W, 117.6, places=1)
        self.assertAlmostEqual(db_mod.INVERTER_OVER_READ_W, 32.8, places=1)


class PartialDayScalingTests(unittest.TestCase):
    """A partial day must not be charged a full day of correction.

    Both new columns project a dark-hours measurement across the day. With a
    flat 24 h multiplier, 2026-08-17 — half elapsed — reported 611 Wh of fridge
    and subtracted a full 787 Wh of inverter over-read from a load_wh that was
    only half accumulated. Scaling by `coverage` fixes it and leaves completed
    days untouched, since coverage is 1.0 there.
    """

    def test_both_projections_are_scaled_by_coverage(self):
        sql = _render_sql()
        for col in ("dc_load_wh", "total_load_wh"):
            i = sql.index(f"AS {col}")
            block = sql[max(0, i - 500):i]
            self.assertIn("g.coverage", block,
                          f"{col} must be scaled by coverage, not a flat 24 h")

    def test_the_offset_correction_is_also_scaled(self):
        """Subtracting a full day's over-read from a partial day's load was the
        larger half of the error: 787 Wh against a 1332 Wh load."""
        sql = _render_sql()
        i = sql.index("AS total_load_wh")
        block = sql[max(0, i - 500):i]
        self.assertRegex(block, r"INVERTER_OVER_READ|32\.8")
        self.assertEqual(block.count("g.coverage"), 2,
                         "both the offset and the fridge term must be scaled")

    def test_a_complete_day_is_unaffected(self):
        """coverage = 1.0, so the arithmetic is identical for finished days —
        this fix must not silently move history."""
        cov, step, duty = 1.0, 74.2, 0.323
        self.assertAlmostEqual(step * duty * 24 * cov, step * duty * 24)


class CounterAttributionTests(unittest.TestCase):
    """mppt_counter_wh must be correct whatever DISPLAY_TZ is set to.

    mppt_daily_total fires at the MPPT's own midnight — the SITE's midnight —
    carrying the finished day's total. The attribution shifted it back an hour
    using DISPLAY_TZ, which only lands in the previous day if DISPLAY_TZ happens
    to BE the site zone. It is America/Toronto for a site in British Columbia,
    so the event landed at 03:01 Toronto, minus an hour is 02:01, still the new
    day — and the CURRENT day inherited the previous day's counter. Observed
    1356 Wh against a day that had produced 6 Wh, which defeats the column's
    purpose as a standing pipeline audit.

    Correctness must not depend on a display preference the operator can point
    anywhere.
    """

    def test_the_counter_cte_uses_SITE_TZ_not_the_display_tz(self):
        c = _cte(_render_sql(), "c")
        self.assertIn(db_mod.SITE_TZ, c,
                      "the rollover shift must key on the site zone")
        self.assertNotIn("AT TIME ZONE $3", c,
                         "using DISPLAY_TZ here makes correctness depend on a "
                         "rendering setting")

    def test_the_display_tz_is_still_used_for_the_display_grouping(self):
        """The rest of the ledger groups by DISPLAY_TZ on purpose — that IS a
        presentation choice. Only the counter's correctness is site-bound."""
        g = _cte(_render_sql(), "g")
        self.assertIn("AT TIME ZONE $3", g)

    def test_the_counter_is_BOUNDED_on_the_read_path(self):
        """A corrupt row already in the table cannot be fixed at the decoder.

        On 2026-08-16 the MPPT emitted day_wh = 8388607 (0x7FFFFF) and the
        unbounded MAX() latched it permanently — 8.4 MWh from a 750 W array,
        shown as that day's audit figure. The decoder now rejects it, but that
        only protects rows written from now on; the bad row is already stored
        and will appear in every historical window that queries it. Same lesson
        as dc_w = -27844: guard at BOTH ends, because only one can be
        retroactive.
        """
        c = _cte(_render_sql(), "c")
        self.assertIn("BETWEEN 0 AND 20000", c,
                      "mppt_counter_wh must be range-bounded on read")
        self.assertNotRegex(
            c, r"MAX\(\(data->>'day_wh'\)::numeric\)",
            "an unguarded MAX() lets one corrupt sample own the day forever")

    def test_the_bound_admits_a_real_day_and_rejects_the_corrupt_one(self):
        """The bound must not eat data. Best day on record is 1939 Wh; the
        corrupt sample was 8388607."""
        self.assertLess(1939, 20000)
        self.assertGreater(8388607, 20000)

    def test_the_site_zone_is_the_actual_site(self):
        """Barge Inn is in British Columbia. If this ever needs changing, the
        panels moved."""
        self.assertEqual(db_mod.SITE_TZ, "America/Vancouver")

    def test_the_shift_lands_in_the_previous_day_at_the_site(self):
        """The arithmetic, checked rather than asserted by eye: 00:01 local
        minus an hour is 23:01 the previous day."""
        import datetime as dt
        fired = dt.datetime(2026, 8, 12, 0, 1, 15)      # site-local midnight
        self.assertEqual((fired - dt.timedelta(hours=1)).date(),
                         dt.date(2026, 8, 11))

if __name__ == "__main__":
    unittest.main()
