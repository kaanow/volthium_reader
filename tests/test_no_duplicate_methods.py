"""No class may define the same method twice.

Found 2026-10-04: scripts/xanbus_telemetry.py's Decoder defined _chg_sts,
_inv_sts2 and _mppt_data TWICE each, byte-identical, 106 lines in total.
Python keeps the LAST definition and discards the first silently. So:

  * the first copies were unreachable — no test could exercise them,
  * and any edit to a first copy would have had zero effect while looking
    exactly like a fix.

That second failure mode is not hypothetical in this repo. Earlier in the same
session a fix was shipped to v2-history.html when /history serves
history.html, and the wrong page was then checked for the marker. Silent
shadowing is the same class of defect with no file path to notice.

This guard is cheap, covers every class in the reader and the server, and
fails loudly on the duplication rather than on its consequences.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCANNED = sorted(
    [p for p in (REPO / "scripts").glob("*.py")]
    + [p for p in (REPO / "cloud" / "server").glob("*.py")]
    + [p for p in (REPO / "cloud" / "uploader").glob("*.py")]
    + [p for p in (REPO / "volthium").glob("*.py")]
)
assert SCANNED, "found no source files to scan — the globs are wrong"


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(REPO)))
def test_no_class_redefines_a_method(path: Path):
    tree = ast.parse(path.read_text(), str(path))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: dict[str, list[int]] = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                seen.setdefault(item.name, []).append(item.lineno)
        for name, linenos in seen.items():
            if len(linenos) > 1:
                # A @property / @x.setter pair is a legitimate same-name
                # redefinition; exclude only that specific shape.
                decorated = [
                    item for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == name and item.decorator_list
                ]
                if len(decorated) == len(linenos):
                    continue
                offenders.append(f"{node.name}.{name} at lines {linenos}")
    try:
        shown = path.relative_to(REPO)
    except ValueError:
        shown = path          # the self-test feeds a tmp_path file
    assert not offenders, (
        f"{shown}: duplicate method definitions — Python "
        f"keeps only the LAST, so the earlier one is dead code and editing it "
        f"has no effect: {offenders}")


def test_the_guard_catches_a_planted_duplicate(tmp_path):
    """Mutation-proof the guard itself: a toothless structural test is worse
    than none, because it reads as coverage."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "class C:\n"
        "    def f(self):\n"
        "        return 1\n"
        "    def f(self):\n"
        "        return 2\n")
    with pytest.raises(AssertionError, match="duplicate method"):
        test_no_class_redefines_a_method(bad)


def test_the_guard_allows_a_property_setter_pair(tmp_path):
    ok = tmp_path / "ok.py"
    ok.write_text(
        "class C:\n"
        "    @property\n"
        "    def v(self):\n"
        "        return self._v\n"
        "    @v.setter\n"
        "    def v(self, x):\n"
        "        self._v = x\n")
    test_no_class_redefines_a_method(ok)   # must not raise
