"""Independent probes for the iteration-10 CP4 gate changes."""

from pathlib import Path
import sys
import tempfile


REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "hardware" / "kicad" / "pcb"))

import core  # noqa: E402


front_with_early_back_graphic = """(footprint "probe"
  (layer "F.Cu")
  (fp_line (start 0 0) (end 1 1) (stroke (width 0.1) (type default))
    (layer "B.Cu"))
)"""
back = """(footprint "probe"
  (layer "B.Cu")
  (fp_line (start 0 0) (end 1 1) (stroke (width 0.1) (type default))
    (layer "F.Cu"))
)"""

print("side/front-with-early-B.Cu:", core._footprint_is_back(front_with_early_back_graphic))
print("side/back-with-early-F.Cu:", core._footprint_is_back(back))

empty_findings = core.refdes_over_body_findings("")
print("refdes-empty/findings:", empty_findings)

core.assert_single_back_transform()
print("single-transform/real-tree: clean")

original_here = core.HERE
try:
    with tempfile.TemporaryDirectory() as tmp:
        core.HERE = Path(tmp)
        try:
            core.assert_single_back_transform()
        except SystemExit as exc:
            print("single-transform/empty-tree: FAIL as required:", exc)
        else:
            print("single-transform/empty-tree: CLEAN (unexpected)")
finally:
    core.HERE = original_here
