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


class ClampGateSqlTests(unittest.TestCase):

    def _sql(self) -> str:
        src = inspect.getsource(db_mod.AsyncpgReadingsDAO.solar_energy_daily)
        body = [b for b in re.findall(r'f?"""(.*?)"""', src, re.S)
                if "SELECT" in b.upper()]
        self.assertEqual(len(body), 1, "expected exactly one SQL literal")
        return (body[0]
                .replace("{sane_s}", db_mod._dc_w_sane("s.dc_w"))
                .replace("{_clamped_sql()}", db_mod._clamped_sql())
                .replace("{_dc_w_sane()}", db_mod._dc_w_sane()))

    def test_dc_v_is_selected_into_the_cte(self):
        """The gate reads s.dc_v; the CTE did not select it before this change,
        which would have been a runtime-only 'column does not exist'."""
        self.assertRegex(self._sql(),
                         r"SELECT ts AS b,[^\n]*\bdc_v\b")

    def test_the_bare_voltage_gate_is_gone(self):
        """The specific defect. `pv_v < 15` must no longer decide this."""
        self.assertNotIn("s.pv_v, 0) < 15", self._sql())

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


if __name__ == "__main__":
    unittest.main()
