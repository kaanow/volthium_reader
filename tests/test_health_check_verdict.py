"""health_check must not discard status_check's verdict.

`check_rs485` shells out to status_check, parses its "bottom line" into
out["verdict"], and until 2026-08-15 did nothing else with it. status_check
exits 1 on anything notable and emits an explicit INCOMPLETE verdict precisely
so a partial run cannot read as a clean one — and neither the string nor the
exit code reached `problems`.

So health_check printed the verdict on one line and "all green" on the next,
and exited 0. A wrapper that swallows its own subordinate's alarm is worse
than not calling it at all.
"""
from __future__ import annotations

import subprocess
import sys
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import health_check as H   # noqa: E402


def _run(stdout: str, rc: int):
    return mock.patch.object(
        H.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout, ""))


class VerdictPropagationTests(unittest.TestCase):

    QUIET = ("Readings ...\n  time gaps > 60s: none\n"
             "  battery-silent stretches: none\n  read_fail: none\n"
             "=== bottom line: quiet window ===\n")

    def test_a_quiet_verdict_is_not_a_problem(self):
        with _run(self.QUIET, 0):
            out = H.check_rs485(2.0)
        self.assertEqual(out["problems"], [])

    def test_a_NOTABLE_verdict_becomes_a_problem(self):
        """The regression. Must not be recorded-and-forgotten."""
        txt = self.QUIET.replace("quiet window",
                                 "NOTABLE — investigate above")
        with _run(txt, 1):
            out = H.check_rs485(2.0)
        self.assertTrue(out["problems"], "a NOTABLE verdict must surface")
        self.assertIn("NOTABLE", " ".join(out["problems"]))

    def test_an_INCOMPLETE_verdict_becomes_a_problem(self):
        """status_check emits INCOMPLETE so a partial run cannot read clean.
        That is the whole reason the verdict exists."""
        txt = self.QUIET.replace("quiet window", "INCOMPLETE — could not check")
        with _run(txt, 1):
            out = H.check_rs485(2.0)
        self.assertTrue(out["problems"])
        self.assertIn("INCOMPLETE", " ".join(out["problems"]))

    def test_a_nonzero_exit_is_a_problem_even_if_the_text_looks_quiet(self):
        """Belt and braces: if the text says quiet but the process failed,
        believe the exit code."""
        with _run(self.QUIET, 1):
            out = H.check_rs485(2.0)
        self.assertTrue(out["problems"])

    def test_an_unparseable_verdict_is_a_problem(self):
        """'unknown' must not pass as clean."""
        with _run("garbage with no bottom line\n", 0):
            out = H.check_rs485(2.0)
        self.assertTrue(out["problems"])


if __name__ == "__main__":
    unittest.main()


class SchemaSkewIsDerivedTests(unittest.TestCase):
    """The skew check must track the reader, not a hardcoded number.

    It was pinned to 2 and started crying "reader/server skew" the moment
    schema 3 shipped correctly — a monitoring check firing on an intended
    change, which is how an operator learns to ignore it and a real skew
    slips through. Same failure family as the RS485 section that returned an
    error instead of a verdict.
    """

    def test_it_reads_the_version_out_of_the_reader(self):
        import scripts.status_check as sc
        src = (Path(__file__).resolve().parents[1]
               / "scripts" / "xanbus_telemetry.py").read_text()
        want = int(re.search(r'"schema_version":\s*(\d+)', src).group(1))
        self.assertEqual(
            sc._reader_schema_version(), want,
            "the health check's expected schema version must come from the "
            "reader's source, not a literal")

    def test_no_literal_expectation_survives_in_the_section(self):
        import inspect
        import scripts.status_check as sc
        src = inspect.getsource(sc.section_solar)
        self.assertNotRegex(
            src, r"sv\s*!=\s*\d",
            "schema expectation is hardcoded again — derive it from the reader")
        self.assertIn("_reader_schema_version", src)

    def test_unreadable_source_reports_UNCHECKED_rather_than_guessing(self):
        """A default would be a silent false all-clear."""
        import scripts.status_check as sc
        src = inspect.getsource(sc._reader_schema_version)
        self.assertIn("return None", src)
        self.assertIn("UNCHECKED", inspect.getsource(sc.section_solar))
