"""dc_w must not be able to render a physically impossible number.

On 2026-08-09 a single 10:10 bucket stored dc_w = -27844 W — the inverter's
own DC draw, decoded wrong, while dc_v (27.00) and dc_a (-4.4) in the same
frame were both fine. `load_w` is a straight passthrough of dc_w, so the day's
ledger reported load_wh = -758: a house that generated power by consuming it.

Fixed in two places, deliberately. The decoder now cross-checks dc_w against
|dc_v*dc_a| so bad frames never land (tests/test_xanbus_telemetry.py), but that
only protects rows written from now on — the bad row is already in the table
and will stay in every historical window for as long as it is queried. A read
path that can print a negative load is a defect on its own terms.
"""
from __future__ import annotations

import ast
import inspect
import re
import unittest

from cloud.server import db as db_mod


class DaoStructureTests(unittest.TestCase):
    """The DAO must actually expose its methods.

    Fixing the dc_w bug above, the helper was inserted at column 0 *inside*
    the class body. That ends the class, and the indented `async def`s after
    it become nested functions inside the helper. Three endpoints started
    returning 500 in production.

    The whole 108-test cloud suite passed against that broken file, because
    every test either used a fake DAO or — like the sanitise tests below —
    inspected source text with a regex. Source text was still perfectly
    correct; it was the resulting object that was wrong. Assert on the object.
    """

    EXPECTED = (
        "solar_series", "solar_energy_daily", "load_heatmap",
        "dc_load_profile", "recent_xanbus_events", "recent_events",
        "history_alarms", "sources",
    )

    def test_dao_exposes_every_method_the_api_calls(self):
        missing = [m for m in self.EXPECTED
                   if not callable(getattr(db_mod.AsyncpgReadingsDAO, m, None))]
        self.assertEqual(missing, [], f"not methods on the DAO: {missing}")

    def test_no_module_level_def_inside_the_dao_class(self):
        """Catches the shape of the mistake directly, not just this instance."""
        tree = ast.parse(inspect.getsource(db_mod))
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef)
                   and n.name == "AsyncpgReadingsDAO")
        nested = [n.name for n in cls.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  for inner in ast.walk(n)
                  if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and inner is not n
                  and inner.name.startswith(("solar_", "load_", "dc_"))]
        self.assertEqual(nested, [], f"DAO methods nested inside another def: {nested}")


def _methods_reading_dc_w() -> list[str]:
    """Every DAO method whose SQL mentions dc_w at all.

    Derived from the source so a new consumer is in scope the moment it is
    written, which is the whole point: the hand-maintained list of three was
    what allowed solar_series to read dc_w unsanitised for eight days.
    """
    tree = ast.parse(inspect.getsource(db_mod))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "AsyncpgReadingsDAO")
    out = []
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.get_source_segment(inspect.getsource(db_mod), node) or ""
        if "dc_w" not in body:
            continue
        # READ paths only. insert_solar names dc_w too, but sanitising on the
        # way IN is the decoder's job (xanbus_telemetry cross-checks dc_w
        # against |dc_v*dc_a| so bad frames never land); this guard is about
        # what reaches the API from rows already stored.
        if re.search(r"\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b", body, re.I):
            continue
        out.append(node.name)
    assert out, "derivation found nothing — the rest of this test is vacuous"
    return out


class DcWSanitiseTests(unittest.TestCase):

    def test_the_derivation_finds_the_known_consumers(self):
        found = _methods_reading_dc_w()
        for m in ("solar_energy_daily", "load_heatmap", "dc_load_profile",
                  "solar_series"):
            self.assertIn(m, found, f"{m} reads dc_w but was not derived")


    def test_helper_renders_null_outside_the_plausible_range(self):
        sql = db_mod._dc_w_sane()
        self.assertIn("BETWEEN 0 AND 6000", sql)
        # NULL, not a clamp: a corrupt sample is missing data, and clamping to
        # a bound would invent a measurement that was never taken.
        self.assertNotIn("ELSE", sql)

    def test_helper_qualifies_the_column(self):
        """The ledger joins two tables, so an unqualified dc_w is ambiguous."""
        self.assertIn("s.dc_w BETWEEN", db_mod._dc_w_sane("s.dc_w"))

    def test_every_dc_w_read_path_is_sanitised(self):
        """The regression is not 'the ledger was wrong', it is 'three separate
        endpoints read this column and nothing guarded any of them'. A fourth
        added later must not silently reintroduce it."""
        src = inspect.getsource(db_mod)
        # DERIVED, not hand-listed. The previous version named three methods,
        # so it was structurally blind to a FOURTH consumer — and solar_series
        # was exactly that: it aggregated dc_w raw and fed the history explorer
        # from 2026-08-07 until this was found on 08-15. A guard whose scope is
        # a hardcoded list cannot catch the case it was written to prevent.
        for method in _methods_reading_dc_w():
            body = re.search(
                rf"async def {method}\(.*?(?=\n    async def |\Z)", src, re.S)
            self.assertIsNotNone(body, f"{method} not found")
            text = body.group(0)
            # Selecting the raw column into a CTE is fine — the consumer
            # sanitises it. What must never appear is a raw dc_w inside an
            # aggregate or an output expression, which is what reaches the API.
            raw = re.findall(
                r"(?:AVG|SUM|MIN|MAX|COALESCE)\(\s*(?:\w+\.)?dc_w\b"
                r"|(?:\w+\.)?dc_w\s+AS\s+load_w",
                text)
            self.assertEqual(
                raw, [], f"{method} aggregates dc_w unsanitised: {raw}")
            self.assertRegex(
                text, r"_dc_w_sane|sane_s",
                f"{method} never sanitises dc_w at all")

    def test_queries_still_parse_and_interpolate(self):
        """These SQL strings became f-strings; a stray brace or an undefined
        name would only surface on a live request, which the suite never makes."""
        tree = ast.parse(inspect.getsource(db_mod))
        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    names = {x.id for x in ast.walk(v.value)
                             if isinstance(x, ast.Name)}
                    if names & {"_dc_w_sane", "sane_s"}:
                        seen += 1
        self.assertEqual(seen, 5, "expected 5 sanitised interpolations")


class SqlWellFormednessTests(unittest.TestCase):
    """These queries are f-strings assembled by hand and only ever executed
    against a live Postgres, which no test has. Both times db.py has broken in
    production it was structural and invisible to the suite: once a helper at
    column 0 that ended the class body, once an unbalanced paren from an
    inserted CTE. Neither was a logic error — both would have been caught by
    looking at the assembled string.
    """

    def _sql(self, method):
        src = inspect.getsource(getattr(db_mod.AsyncpgReadingsDAO, method))
        out = []
        for m in re.finditer(r'f?"""(.*?)"""', src, re.S):
            body = m.group(1)
            if "SELECT" in body.upper():
                out.append(body.replace("{sane_s}", db_mod._dc_w_sane("s.dc_w"))
                               .replace("{_dc_w_sane()}", db_mod._dc_w_sane()))
        return out

    def test_every_query_has_balanced_parens(self):
        bad = []
        for name in ("solar_energy_daily", "load_heatmap", "dc_load_profile",
                     "solar_series"):
            for sql in self._sql(name):
                d = sql.count("(") - sql.count(")")
                if d:
                    bad.append((name, d))
        self.assertEqual(bad, [], f"unbalanced parens: {bad}")

    def test_no_doubled_cte_close(self):
        """The exact shape of the second outage: an inserted CTE left `)`
        immediately followed by `), name AS (`."""
        for name in ("solar_energy_daily",):
            for sql in self._sql(name):
                # Anchored to a line that is ONLY a paren. An unanchored
                # version also matches the legitimate `USING (b)` on the line
                # above a CTE boundary, which made it fail on correct SQL.
                self.assertNotRegex(
                    sql, r"(?m)^[ \t]*\)[ \t]*$\n[ \t]*\)[ \t]*,\s*\w+\s+AS\s*\(",
                    f"{name} closes a CTE twice")

    def test_placeholders_are_contiguous_from_one(self):
        """A dropped $n is a runtime-only failure."""
        for name in ("solar_energy_daily", "load_heatmap", "dc_load_profile"):
            for sql in self._sql(name):
                ns = sorted({int(x) for x in re.findall(r"\$(\d+)", sql)})
                if ns:
                    self.assertEqual(ns, list(range(1, max(ns) + 1)),
                                     f"{name} has gaps in $n: {ns}")


if __name__ == "__main__":
    unittest.main()
