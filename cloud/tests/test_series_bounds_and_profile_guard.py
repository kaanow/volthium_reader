"""Two review findings, 2026-10-04: an unbounded endpoint and an unguarded model.

1. /api/history/series and /api/solar/series had NO row cap. hours <= 9600
   with bucket_s >= 10 permits 3.46 M buckets; measured 243 MB / 756,577 rows
   in 15.2 s, unauthenticated. command_timeout=10 does not bound it (per-query,
   and the aggregate finishes inside it) — the time is Python building dicts
   and gzipping in memory. Concurrent requests exhaust the container, and the
   restart runs apply_all() before serving: the 2026-10-04 outage shape,
   reachable with curl.

2. dc_load_profile computed the SAME modelled quantity as the ledger's
   dc_load_wh with NO premise guard — only `bimodal = draw_w > 20`, which no
   consumer read and which returned true anyway. Raw SIGNED pack_p let 71
   charging samples (0.43%) hijack Otsu, so the "fridge off" class became the
   generator run: draw 1404 W, duty 0.996, baseline -1230 W (impossible),
   33.56 kWh/day. The tile read ~1395 W for 26 h against a fridge of 80-120 W
   while the ledger returned NULL for the same day.
"""

from __future__ import annotations

import ast
import textwrap
import inspect
import unittest

from cloud.server import db as db_mod
from cloud.server import main as main_mod


class SeriesBucketBudgetTests(unittest.TestCase):

    def test_the_cap_is_near_what_a_chart_can_render(self):
        """A cap far above any real consumer is not a cap. history.html's
        bucketFor() targets ~450 buckets."""
        self.assertLessEqual(main_mod.MAX_SERIES_BUCKETS, 20000)
        self.assertGreaterEqual(main_mod.MAX_SERIES_BUCKETS, 1000)

    def test_the_243MB_request_is_rejected(self):
        """The exact parameters measured against production."""
        with self.assertRaises(Exception) as cm:
            main_mod._check_bucket_budget(9600, 10)
        self.assertEqual(getattr(cm.exception, "status_code", None), 422)

    def test_the_rejection_says_what_to_do_instead(self):
        """A 422 that does not tell the caller how to succeed just moves the
        problem to whoever is reading the logs."""
        try:
            main_mod._check_bucket_budget(9600, 10)
        except Exception as e:
            msg = str(getattr(e, "detail", e))
        self.assertIn("bucket_s", msg)
        self.assertRegex(msg, r"at least \d+ s")

    def test_every_request_the_pages_actually_make_is_allowed(self):
        """A guard that breaks the UI is worse than the leak. These are the
        real call shapes."""
        for hours, bucket_s in [(1, 15), (24, 300), (24, 60), (168, 900),
                                (336, 3600), (720, 3600), (9600, 86400),
                                (30 * 24, 3600)]:
            with self.subTest(hours=hours, bucket_s=bucket_s):
                main_mod._check_bucket_budget(hours, bucket_s)

    def test_both_series_endpoints_are_guarded(self):
        for fn in (main_mod.api_history_series, main_mod.api_solar_series):
            with self.subTest(endpoint=fn.__name__):
                self.assertIn("_check_bucket_budget", inspect.getsource(fn))

    def test_it_rejects_rather_than_truncates(self):
        """A truncated series is a LIE about the window the caller asked for.
        This repo has been bitten by silent truncation repeatedly."""
        src = inspect.getsource(main_mod._check_bucket_budget)
        self.assertIn("HTTPException", src)
        self.assertNotIn("LIMIT", src.upper())


class DcLoadProfileGuardTests(unittest.TestCase):

    def _src(self):
        return inspect.getsource(db_mod.AsyncpgReadingsDAO.dc_load_profile)

    def test_only_discharge_samples_are_used(self):
        """The premise is "whatever the battery SUPPLIES". A charging sample
        is not a load measurement, and 71 of them hijacked the Otsu split."""
        src = self._src()
        self.assertRegex(src, r"if v < 0",
                         "charging samples are not filtered out")

    def test_the_discard_count_is_reported(self):
        """A filter that drops without saying how much is how the generator
        run got in here unnoticed."""
        self.assertIn("charging_samples_excluded", self._src())

    def test_a_negative_baseline_is_refused(self):
        """baseline_w = -1230 W was the tell that the model had inverted."""
        self.assertRegex(self._src(), r"baseline <= 0")

    def test_the_duty_band_excludes_a_non_cycle(self):
        """duty 0.996 asserts the compressor never stops."""
        self.assertRegex(self._src(), r"0\.02 <= duty <= 0\.75")

    def test_the_split_must_sit_in_a_valley(self):
        """Same principle and the same shared constants as the ledger's
        _valley_sql, applied to this window's own Otsu point."""
        src = self._src()
        self.assertIn("VALLEY_BAND_W", src)
        self.assertIn("VALLEY_MAX_RATIO", src)

    def _emitted_keys(self):
        """Keys this function actually puts in its response, by AST.

        Scanning the source TEXT for "bimodal" failed twice: first on the
        docstring's legitimate "the signature is strongly bimodal", then on
        my own comment explaining the removed flag. That is the third time
        today a source-grep matched its own explanation. Parse the code.
        """
        tree = ast.parse(textwrap.dedent(self._src()))
        keys = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr == "update":
                    keys |= {k.arg for k in node.keywords if k.arg}
            if isinstance(node, ast.Dict):
                keys |= {k.value for k in node.keys
                         if isinstance(k, ast.Constant)
                         and isinstance(k.value, str)}
            if isinstance(node, ast.Subscript) and isinstance(
                    node.slice, ast.Constant):
                keys.add(node.slice.value)
        return keys

    def test_the_derivation_is_not_vacuous(self):
        keys = self._emitted_keys()
        self.assertIn("split_w", keys)
        self.assertIn("duty", keys)

    def test_the_unread_bimodal_flag_is_gone(self):
        """It was the only validity signal, no consumer read it, and it
        returned true anyway."""
        self.assertNotIn("bimodal", self._emitted_keys(),
                         "the unread bimodal flag is still emitted")
        self.assertIn("valid", self._emitted_keys(),
                      "there is no replacement validity flag")

    def test_an_invalid_profile_publishes_NO_modelled_NUMBER(self):
        """Refuse rather than publish. v2.html's dcLoadW() treats a falsy
        draw_w as "no profile" and renders an em dash, so nulling the fields
        is what makes the tile honest."""
        src = self._src()
        self.assertRegex(src, r"draw_w=None")
        self.assertRegex(src, r"baseline_w=None")
        self.assertRegex(src, r"kwh_per_day=None")

    def test_the_reason_is_returned_to_the_caller(self):
        """Two endpoints computing one quantity disagreed with no way to tell
        which was right. The invalid one now says why."""
        self.assertRegex(self._src(), r'note="; "\.join\(bad\)')


if __name__ == "__main__":
    unittest.main()
