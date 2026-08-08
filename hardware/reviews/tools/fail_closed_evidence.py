"""Fail-closed proof: evidence, run through the REAL build chokepoint.

Six consecutive reviewer findings (F13, F15, F16, F17, F18, F19) were one
defect in different clothes: a gate answering "clean" having judged less
than it claimed. Each was fixed reactively and the next level up was found
by the reviewer, not by me. This inverts that: the invariant is stated over
the whole battery and proved on every build.
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
os.chdir(REPO)
sys.path.insert(0, str(REPO / "hardware/kicad/pcb"))
import core  # noqa: E402


def build(gen, name):
    spec = importlib.util.spec_from_file_location(name, gen)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    buf = io.StringIO()
    rc = 0
    with contextlib.redirect_stdout(buf):
        try:
            m.main()
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, buf.getvalue()


print("CP4 iteration 22 — the fail-closed proof")
print("=" * 70)
print("""
INVARIANT (stated over the SUITE, not any one gate):
  corrupt the emitted board in a way that changes its meaning, and AT LEAST
  ONE gate in the chokepoint must object.

An individual gate is allowed to be blind to a given mutation; the battery
is not. This is deliberately not "which gate should catch this?" — that
question is what produced six reactive fixes, because it stops at the
boundary of whatever file was just edited.

The proof runs inside write(), against the board actually being written, so
it cannot drift from what ships.
""")

print("-" * 70)
print("CONTROL — both production builds")
for gen, name in (("hardware/kicad/pcb/build.py", "battery"),
                  ("hardware/kicad/pcb/build_display_pcb.py", "display")):
    rc, out = build(gen, name)
    line = [x for x in out.splitlines() if "fail-closed" in x]
    print(f"  {name:8s} rc={rc}  {line[0].strip() if line else 'NO PROOF LINE'}")

print()
print("-" * 70)
print("THE MUTATIONS (each changes the board's meaning)")
print("""
   1  empty text                      8  a footprint moved 5 mm
   2  truncated to half               9  a footprint flipped to the other side
   3  first footprint deleted        10  a pad's net renamed
   4  a reference renamed (same n)   11  every reference hidden
   5  top-level anchor malformed     12  all body geometry stripped
   6  top-level layer removed        13  unmatched paren in a quoted string
   7  top-level layer non-copper
""")

print("-" * 70)
print("IS THE PROOF ITSELF ALIVE? — remove gates and watch it object")
print("""
A proof that always prints "all rejected" is worth nothing. Each gate is
removed in turn. Two outcomes are both legitimate, and they are reported as
what they are rather than as pass/fail:

  FAIL-OPEN DETECTED — that gate is the only one covering some mutation, and
                       the proof names it;
  REDUNDANT          — the battery still closes without it, because another
                       gate covers the same corruption. Defence in depth,
                       not a defect.

The liveness check is the last row: with the whole battery removed, the proof
MUST object. If it stays quiet there, it is measuring nothing.
""")
def _require_real(names):
    missing = [n for n in names if not hasattr(core, n)]
    if missing:
        raise SystemExit(
            f"[evidence] neuter list names attributes that do not exist: "
            f"{missing} — a rename would make the liveness case a silent "
            "no-op, which is the very failure this file exists to catch")


targets = [("assert_component_identity", lambda *a, **k: None),
           ("assert_board_parse_coverage", lambda *a, **k: None),
           ("assert_refdes_roundtrip", lambda *a, **k: None),
           ("refdes_over_body_findings", lambda *a, **k: [])]
_require_real([n for n, _ in targets])
ok = True
for nm, stub in targets:
    real = getattr(core, nm)
    setattr(core, nm, stub)
    try:
        rc, out = build("hardware/kicad/pcb/build_display_pcb.py", "disp_p")
        esc = [x for x in out.splitlines() if "passed EVERY gate" in x]
        print(f"  removed {nm:32s} -> "
              f"{'FAIL-OPEN DETECTED' if esc else 'REDUNDANT (battery still closed)'}")
        if esc:
            print(f"        {esc[0].strip()[:140]}")
    finally:
        setattr(core, nm, real)

saved = {nm: getattr(core, nm) for nm, _ in targets}
for nm, stub in targets:
    setattr(core, nm, stub)
try:
    rc, out = build("hardware/kicad/pcb/build_display_pcb.py", "disp_all")
    esc = [x for x in out.splitlines() if "passed EVERY gate" in x]
    ok &= bool(esc)
    print(f"\n  {'PASS' if esc else '*** PROOF IS VACUOUS ***'}  LIVENESS: "
          f"whole battery removed -> "
          f"{'proof objects' if esc else 'proof stayed quiet'}")
    if esc:
        print(f"        {esc[0].strip()[:160]}")
finally:
    for nm, v in saved.items():
        setattr(core, nm, v)

print()
rc, out = build("hardware/kicad/pcb/build_display_pcb.py", "disp_r")
line = [x for x in out.splitlines() if "fail-closed" in x]
restored = rc == 0 and line and "all rejected" in line[0]
ok &= bool(restored)
print(f"  {'PASS' if restored else '*** WRONG ***'}  gates restored: rc={rc} "
      f"{line[0].strip() if line else ''}")

print()
print("-" * 70)
print("WHAT THE PROOF FOUND ON ITS FIRST RUN (before any reviewer saw it)")
print("""
  assert_component_identity — NOTHING read the footprint ID back out of
  the written board (and, after F21, nothing read the Value either). Every gate took fpid from components[ref]["footprint"],
  our own model, and gate_readback compares only (ref, pad, net) triples.
  A board naming a different footprint than the netlist would have passed
  the entire battery. That is the "wrong physical part" class, and DRC does
  not cover it either: lib_footprint_mismatch findings are explicitly
  accepted here for the documented vendored variants.

  It also caught the proof's OWN under-scoping: two mutations looked like
  gate gaps until the battery was corrected to include the netlist-binding
  gate (which needs a file) and the KiCad-engine oracle. A proof assembled
  from a convenient subset measures the subset.
""")
print("=" * 70)
print("all checks behaved correctly" if ok else "SOME CHECKS WRONG")
sys.exit(0 if ok else 1)
