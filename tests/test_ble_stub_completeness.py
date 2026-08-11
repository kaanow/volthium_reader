"""Every BLE stub in the tree must satisfy what volthium.pack reaches for.

The bug this guards: `volthium.pack._VolthiumBMSTapped` subclasses
`aiobmsble.bms.ej_bms.BMS`, which is not installed and is faked by the tests.
Three files grew their own copy of that fake and they drifted — one omitted
`_notification_handler`, which `_VolthiumBMSTapped` calls via `super()`. Each
copy self-guards with `if "aiobmsble" in sys.modules: return`, so the first
importer wins; `cloud/` sorts before `tests/`, so the INCOMPLETE copy won the
full-suite run and `tests/test_event_log_rotation.py` failed with
`AttributeError: 'super' object has no attribute '_notification_handler'`
while passing perfectly in isolation.

The required-method list is DERIVED FROM THE SOURCE here, not written down.
A hand-maintained list would be one more thing to drift — which is the failure
mode this whole file exists to catch. Add a new `super().foo()` call to the tap
and this test starts demanding `foo` of every stub, with no edit here.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conftest import install_ble_stubs   # noqa: E402

install_ble_stubs()

TAP_CLASS = "_VolthiumBMSTapped"


def _super_attrs(source: str, class_name: str) -> set[str]:
    """Names reached through `super().<name>` inside `class_name`."""
    tree = ast.parse(source)
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    assert cls is not None, f"{class_name} not found — did it get renamed?"
    found: set[str] = set()
    for node in ast.walk(cls):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "super"):
            found.add(node.attr)
    return found


def _stub_bms_classes() -> list[tuple[Path, ast.ClassDef]]:
    """Every locally-defined stand-in for the aiobmsble BMS base class.

    Identified structurally — a class whose name is bound to `<mod>.BMS` in the
    same file — so a fourth copy added later is picked up automatically.
    """
    out: list[tuple[Path, ast.ClassDef]] = []
    for path in sorted(ROOT.glob("**/test_*.py")) + [ROOT / "conftest.py"]:
        if ".venv" in path.parts:
            continue
        src = path.read_text()
        if "ej_bms" not in src:
            continue
        tree = ast.parse(src)
        bound = {
            node.value.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            for t in node.targets
            if isinstance(t, ast.Attribute) and t.attr == "BMS"
        }
        # The real stubs live inside module-level helpers (`_stub()`,
        # `_stub_ble_deps()`), so "module level only" is too strict. What must
        # be excluded is a stub built inside a TEST METHOD — a local fixture,
        # like the one further down this file, which cannot win an import race.
        # So: skip any class nested within a ClassDef.
        inside_class = {
            id(c) for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
            for c in ast.walk(cls) if isinstance(c, ast.ClassDef) and c is not cls
        }
        for node in ast.walk(tree):
            if (isinstance(node, ast.ClassDef) and node.name in bound
                    and id(node) not in inside_class):
                out.append((path, node))
    return out


class SuperAttrDerivationTests(unittest.TestCase):
    """The derivation itself must work, or every assertion below is vacuous."""

    def test_derivation_finds_the_known_call(self):
        attrs = _super_attrs((ROOT / "volthium" / "pack.py").read_text(),
                             TAP_CLASS)
        self.assertIn("_notification_handler", attrs,
                      "derivation returned nothing useful — the rest of this "
                      "file would pass vacuously")

    def test_derivation_ignores_super_calls_in_other_classes(self):
        attrs = _super_attrs(
            "class A:\n"
            "    def f(self): return super().only_in_a()\n"
            "class B:\n"
            "    def g(self): return super().only_in_b()\n", "A")
        self.assertEqual(attrs, {"only_in_a"})

    def test_finds_every_stub_copy(self):
        """If this stops finding them, drift goes unpoliced again."""
        found = _stub_bms_classes()
        self.assertGreaterEqual(
            len(found), 2,
            f"expected several stub copies, found {[str(p) for p, _ in found]}")


class StubCompletenessTests(unittest.TestCase):

    def test_installed_base_satisfies_the_tap(self):
        from aiobmsble.bms.ej_bms import BMS
        required = _super_attrs((ROOT / "volthium" / "pack.py").read_text(),
                                TAP_CLASS)
        missing = [a for a in sorted(required) if not hasattr(BMS, a)]
        self.assertEqual(missing, [],
                         f"installed BMS stub is missing {missing}")

    def test_the_tap_actually_runs_against_the_installed_base(self):
        """End-to-end, because hasattr() is not the same as callable."""
        from volthium.pack import _VolthiumBMSTapped
        bms = _VolthiumBMSTapped()
        bms._raw_addr = "AA:BB:CC:DD:EE:FF"
        bms._notification_handler(None, b":00~")   # must not raise

    def test_every_stub_copy_is_complete(self):
        """The real defence: conftest wins under pytest, but these files are
        also run standalone, and a thin copy is a landmine either way."""
        required = _super_attrs((ROOT / "volthium" / "pack.py").read_text(),
                                TAP_CLASS)
        bad: list[str] = []
        for path, cls in _stub_bms_classes():
            defined = {n.name for n in cls.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for attr in sorted(required):
                if attr not in defined:
                    bad.append(f"{path.relative_to(ROOT)}::{cls.name} "
                               f"missing {attr}")
        self.assertEqual(bad, [], "BLE stub copies have drifted: " + str(bad))

    def test_conftest_overwrites_rather_than_setdefaults(self):
        """A `setdefault` here would reintroduce the exact bug: a thinner stub
        installed first would survive and conftest would silently defer to it."""
        # Against the parsed CODE, not the text — the docstring above discusses
        # setdefault at length, and matching that would be a test with no teeth
        # dressed up as one.
        tree = ast.parse((ROOT / "conftest.py").read_text())
        calls = [n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertNotIn("setdefault", calls,
                         "conftest must overwrite sys.modules entries, not "
                         "defer to an already-installed (possibly thinner) stub")

    def test_stub_survives_a_thinner_one_installed_first(self):
        """Directly reproduces the original failure mode."""
        class _Thin:
            def __init__(self, *a, **kw): ...

        thin = type(sys)("aiobmsble.bms.ej_bms")
        thin.BMS = _Thin
        saved = sys.modules["aiobmsble.bms.ej_bms"]
        sys.modules["aiobmsble.bms.ej_bms"] = thin
        try:
            install_ble_stubs()
            from aiobmsble.bms.ej_bms import BMS
            self.assertTrue(hasattr(BMS, "_notification_handler"),
                            "a thinner stub installed first still wins")
        finally:
            sys.modules["aiobmsble.bms.ej_bms"] = saved


if __name__ == "__main__":
    unittest.main()
