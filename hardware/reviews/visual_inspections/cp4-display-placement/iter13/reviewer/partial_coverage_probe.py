"""Independent exact-coverage poisons for the iteration-12 F15 repair."""

import copy
import json
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[6]
HERE = Path(__file__).resolve().parent
BOARD = REPO / "hardware" / "kicad" / "pcb" / "build_display" / "display_pcb.kicad_pcb"
sys.path.insert(0, str(REPO / "hardware" / "kicad" / "pcb"))

import core  # noqa: E402


expected = json.loads((HERE / "full_expected.json").read_text(encoding="utf-8"))

partial_refdes = copy.deepcopy(expected)
keep = sorted(partial_refdes["refdes"])[0]
partial_refdes["refdes"] = {keep: partial_refdes["refdes"][keep]}
(HERE / "partial_refdes_expected.json").write_text(
    json.dumps(partial_refdes, indent=2) + "\n", encoding="utf-8", newline="\n")

wrong_side_set = copy.deepcopy(expected)
wrong_side_set["side"].pop("C1")
wrong_side_set["side"]["H1"] = "F"
(HERE / "wrong_side_set_expected.json").write_text(
    json.dumps(wrong_side_set, indent=2) + "\n", encoding="utf-8", newline="\n")

text = BOARD.read_text(encoding="utf-8")
expected_refs = set(expected["components"])
control_findings = []
core.assert_board_parse_coverage(text, expected_refs, control_findings)

empty_body_findings = core.refdes_over_body_findings("", expected_refs=expected_refs)
empty_roundtrip_findings = []
core.assert_refdes_roundtrip("", empty_roundtrip_findings)
empty_parse_findings = []
core.assert_board_parse_coverage("", expected_refs, empty_parse_findings)

# Leave exactly one expected component's Reference visible. Bodies and
# footprint references still parse, so this isolates reference-box coverage.
poison = text
for ref in sorted(expected_refs - {"C1"}):
    old = f'(property "Reference" "{ref}"'
    new = old + " (hide yes)"
    if old not in poison:
        raise RuntimeError(f"could not poison {ref}")
    poison = poison.replace(old, new, 1)

boxes = core.refdes_boxes_from_board(poison)
bodies = core.bodies_from_board(poison)
poison_findings = []
core.assert_board_parse_coverage(poison, expected_refs, poison_findings)
body_findings = core.refdes_over_body_findings(poison, expected_refs=expected_refs)

print(f"control/components={len(expected_refs)} refdes={len(expected['refdes'])} "
      f"sides={len(expected['side'])} pad_keys={len(expected['pads'])}")
print(f"control/parse_coverage_findings={control_findings}")
print(f"empty/refdes_over_body_findings={empty_body_findings}")
print(f"empty/refdes_roundtrip_findings={empty_roundtrip_findings}")
print(f"empty/parse_coverage_findings={empty_parse_findings}")
print(f"poison/partial_refdes_map={len(partial_refdes['refdes'])} of "
      f"{len(expected_refs)} (written partial_refdes_expected.json)")
print("poison/side_keys=39 but C1 replaced by H1 "
      "(written wrong_side_set_expected.json)")
print(f"poison/visible_boxes={len(boxes)} expected={len(expected_refs)}")
print(f"poison/bodies={len({r for r, _, _ in bodies} & expected_refs)} "
      f"expected={len(expected_refs)}")
print(f"poison/parse_coverage_findings={poison_findings}")
print(f"poison/refdes_over_body_findings={body_findings}")
