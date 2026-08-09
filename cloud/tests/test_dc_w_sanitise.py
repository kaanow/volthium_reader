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


class DcWSanitiseTests(unittest.TestCase):

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
        for method in ("solar_energy_daily", "load_heatmap", "dc_load_profile"):
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
        self.assertEqual(seen, 4, "expected 4 sanitised interpolations")


if __name__ == "__main__":
    unittest.main()
