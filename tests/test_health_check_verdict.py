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
import ast
import importlib

import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import health_check as H   # noqa: E402

REPO = Path(__file__).resolve().parents[1]


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
    """Every tool that judges schema_version must DERIVE the expectation.

    This test existed and still missed the bug it was written for. It asserted
    about status_check only, while living in health_check's test file and
    importing health_check — so when the reader went to schema 3,
    status_check was correct and health_check went permanently red
    ("schema_version 3 != 2" on every run, making "all green" unreachable and
    camouflaging any real problem). One of two copies fixed, and a test
    scoped to the one that was.

    So the scope is now DERIVED: scan scripts/ for anything that reads
    schema_version and compares it, and require each to use a derived
    expectation. A fourth tool added later is covered without editing this.
    """

    @staticmethod
    def _tools_touching_schema():
        """Every script that CONSUMES schema_version. Scoped by consumption,
        not by how it compares — my first version of this scan looked for
        `schema_version` within 40 chars of `!=`, and missed status_check
        precisely because the fix had moved the comparison onto its own line
        (`sv != want`). A scan that only finds the unfixed form cannot tell
        you the fixed form stayed fixed.

        The reader is excluded: it EMITS the version and is the source of
        truth, not a judge of it.
        """
        return [f.stem for f in sorted((REPO / "scripts").glob("*.py"))
                if "schema_version" in f.read_text()
                and f.name != "xanbus_telemetry.py"]

    def test_the_scan_actually_finds_the_tools(self):
        """Otherwise every assertion below passes vacuously."""
        found = self._tools_touching_schema()
        self.assertIn("status_check", found)
        self.assertIn("health_check", found)

    def test_no_tool_pins_a_literal_expectation(self):
        """The bug class, stated directly: a literal goes stale on the next
        reader bump and the tool then reports a permanent false problem.
        health_check sat at EXPECT_SCHEMA = 2 against a reader emitting 3, so
        its "all green" was unreachable and any real problem was camouflaged.

        Walked as an AST, not grepped. A regex over the source matched the
        very DOCSTRING above that explains the bug ("schema_version 3 != 2"),
        which would have made this test unfixable without deleting its own
        explanation. Compare nodes are prose-immune.
        """
        for name in self._tools_touching_schema():
            with self.subTest(tool=name):
                src = (REPO / "scripts" / f"{name}.py").read_text()
                self.assertNotRegex(
                    src.replace('"""', "#"), r"EXPECT_SCHEMA\s*=\s*\d",
                    f"{name} pins a literal schema expectation")
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Compare):
                        continue
                    blob = ast.dump(node)
                    if "schema_version" not in blob:
                        continue
                    for comp in node.comparators:
                        self.assertNotIsInstance(
                            comp, ast.Constant,
                            f"{name} compares schema_version against the "
                            f"literal {getattr(comp, 'value', '?')!r}; derive "
                            f"it from the reader instead")

    def test_the_derived_helper_is_actually_CALLED(self):
        """Defining it is not using it.

        A mutation that put `want = 2` back in health_check passed every
        other assertion here: the comparison still read `!= want` (a Name,
        not a Constant), and `_reader_schema_version` still existed — it had
        simply stopped being called. The literal moved from the comparison to
        the assignment and the test could not see it.

        So require the call, by AST, outside the helper's own definition.
        """
        for name in self._tools_touching_schema():
            with self.subTest(tool=name):
                tree = ast.parse((REPO / "scripts" / f"{name}.py").read_text())
                # drop the helper's own body so its name there does not count
                for node in ast.walk(tree):
                    if (isinstance(node, ast.FunctionDef)
                            and node.name == "_reader_schema_version"):
                        node.body = []
                calls = [n for n in ast.walk(tree)
                         if isinstance(n, ast.Call)
                         and getattr(n.func, "id", None) == "_reader_schema_version"]
                self.assertTrue(
                    calls,
                    f"{name} defines _reader_schema_version but never calls "
                    f"it — the expectation is coming from somewhere else, "
                    f"which is how the stale literal survived")

    def test_every_such_tool_derives_the_version(self):
        for name in self._tools_touching_schema():
            with self.subTest(tool=name):
                mod = importlib.import_module(name)
                fn = getattr(mod, "_reader_schema_version", None)
                self.assertIsNotNone(
                    fn, f"{name} judges schema_version without deriving it — "
                        f"a literal here goes stale on the next reader bump "
                        f"and the tool reports a permanent false problem")
                src = (REPO / "scripts" / f"{name}.py").read_text()
                self.assertNotRegex(
                    src, r"EXPECT_SCHEMA\s*=\s*\d",
                    f"{name} still pins a literal expectation")

    def test_each_agrees_with_the_reader(self):
        want = int(re.search(
            r'"schema_version":\s*(\d+)',
            (REPO / "scripts" / "xanbus_telemetry.py").read_text()).group(1))
        for name in self._tools_touching_schema():
            with self.subTest(tool=name):
                mod = importlib.import_module(name)
                self.assertEqual(mod._reader_schema_version(), want)

    def test_unreadable_source_reports_UNCHECKED_rather_than_guessing(self):
        """A default would be a silent false all-clear."""
        for name in self._tools_touching_schema():
            with self.subTest(tool=name):
                mod = importlib.import_module(name)
                self.assertIn("return None",
                              inspect.getsource(mod._reader_schema_version))

    def test_no_literal_expectation_survives_in_the_solar_section(self):
        import scripts.status_check as sc
        src = inspect.getsource(sc.section_solar)
        self.assertNotRegex(
            src, r"sv\s*!=\s*\d",
            "schema expectation is hardcoded again — derive it from the reader")
        self.assertIn("_reader_schema_version", src)
        self.assertIn("UNCHECKED", src)
