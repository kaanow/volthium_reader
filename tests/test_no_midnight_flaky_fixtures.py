"""No test may build a multi-row time span starting at an unanchored now().

This flake class has now appeared twice:

  * PACK GAPS (tests/test_health.py) — its own comment records that it "failed
    for ten minutes out of every twenty-four hours and passed every other
    time, which reads as flakiness rather than as a broken fixture."
  * LOAD SURGES (same file) — 7 rows at 10 s cadence span 60 s, so within a
    minute of midnight they straddle the date boundary. The helpers filter on
    today's ISO date prefix, so the run is truncated and the assertion fails.
    It fired during a suite run at local midnight on 2026-10-04.

Reproduced directly for the second one: with base at 23:59:30 the helper
returns 0 surges; at 15:00 and at noon it returns 1.

The fix both times is `.replace(hour=..., minute=0, second=0, microsecond=0)`
— keep today's DATE (so the live "today" path is exercised end to end) while
pinning the time of day away from both boundaries. This guard exists so there
is not a third occurrence.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEST_DIRS = [REPO / "tests", REPO / "cloud" / "tests"]
FILES = sorted(p for d in TEST_DIRS for p in d.glob("test_*.py"))
assert FILES, "found no test files to scan — the glob is wrong"

# `base = datetime.now()` / `t0 = datetime.now()` with no .replace(hour=...)
# on the same line. A bare now() is fine for single relative timestamps
# (staleness tests want "10 minutes ago"); the hazard is using it as the
# ORIGIN of a span that is then stepped forward with timedelta.
ASSIGN = re.compile(
    r"^\s*(?:base|t0|start|origin)\s*=\s*(?:dt\.)?datetime\.now\(\)"
    r"(?!.*replace\s*\(\s*hour)", re.M)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_span_origin_from_an_unanchored_now(path: Path):
    src = path.read_text()
    if path.name == Path(__file__).name:
        pytest.skip("this file documents the pattern it forbids")
    offenders = []
    for m in ASSIGN.finditer(src):
        line_no = src[:m.start()].count("\n") + 1
        # Only flag it if a timedelta step follows within the same function-ish
        # neighbourhood — that is what turns a timestamp into a span.
        window = src[m.end():m.end() + 1200]
        if "timedelta(" in window:
            offenders.append(f"line {line_no}: {m.group(0).strip()}")
    assert not offenders, (
        f"{path.name} builds a multi-row time span from an unanchored "
        f"datetime.now(); within a minute of midnight the rows straddle the "
        f"date boundary and date-prefix filtering truncates the run. Anchor "
        f"with .replace(hour=12, minute=0, second=0, microsecond=0): "
        f"{offenders}")


def test_the_guard_catches_the_pattern_it_forbids(tmp_path):
    """A structural guard that cannot fail reads as coverage and gives none."""
    bad = tmp_path / "test_bad.py"
    bad.write_text(
        "from datetime import datetime, timedelta\n"
        "def test_x():\n"
        "    base = datetime.now()\n"
        "    rows = [base + timedelta(seconds=10 * i) for i in range(7)]\n")
    with pytest.raises(AssertionError, match="unanchored"):
        test_no_span_origin_from_an_unanchored_now(bad)


def test_the_guard_accepts_the_anchored_form(tmp_path):
    ok = tmp_path / "test_ok.py"
    ok.write_text(
        "from datetime import datetime, timedelta\n"
        "def test_x():\n"
        "    base = datetime.now().replace(hour=12, minute=0, second=0)\n"
        "    rows = [base + timedelta(seconds=10 * i) for i in range(7)]\n")
    test_no_span_origin_from_an_unanchored_now(ok)   # must not raise
