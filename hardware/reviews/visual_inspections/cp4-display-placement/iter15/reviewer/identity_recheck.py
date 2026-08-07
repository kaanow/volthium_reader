"""Independent recheck of the iteration-14 exact-identity repairs."""

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


def write_poison(name, data):
    (HERE / name).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


partial_refdes = copy.deepcopy(expected)
partial_refdes["refdes"] = {"C1": partial_refdes["refdes"]["C1"]}
write_poison("partial_refdes_expected.json", partial_refdes)

wrong_side = copy.deepcopy(expected)
wrong_side["side"].pop("C1")
wrong_side["side"]["H1"] = "F"
write_poison("wrong_side_set_expected.json", wrong_side)

wrong_pad = copy.deepcopy(expected)
wrong_pad["pads"].pop("C1/1")
wrong_pad["pads"]["J-USB/A10"] = ""
write_poison("wrong_pad_set_expected.json", wrong_pad)

wrong_mechanical = copy.deepcopy(expected)
wrong_mechanical["mechanical"].remove("H1")
wrong_mechanical["mechanical"].append("C1")
write_poison("wrong_mechanical_set_expected.json", wrong_mechanical)

text = BOARD.read_text(encoding="utf-8")
expected_visible = set(expected["components"])
expected_all = expected_visible | set(expected["mechanical"])

control = []
core.assert_board_parse_coverage(text, expected_visible, expected_all, control)

poison = text
for ref in sorted(expected_visible - {"C1"}):
    old = f'(property "Reference" "{ref}"'
    if old not in poison:
        raise RuntimeError(f"could not hide {ref}")
    poison = poison.replace(old, old + " (hide yes)", 1)
hidden = []
core.assert_board_parse_coverage(poison, expected_visible, expected_all, hidden)

builder = core.BoardBuilder(
    20, 20, [],
    {"X1": {"footprint": "Probe:NoCourtyard"}},
    {"X1": (10, 10, 0, "F")},
)
original_courtyard_segments = core.courtyard_segments
try:
    core.courtyard_segments = lambda *args, **kwargs: []
    builder.gate_courtyards()
    builder.gate_outline()
finally:
    core.courtyard_segments = original_courtyard_segments

print(f"control/components={len(expected_visible)} mechanical={len(expected['mechanical'])} "
      f"refdes={len(expected['refdes'])} sides={len(expected['side'])} "
      f"pad_keys={len(expected['pads'])}")
print(f"control/parse_coverage_findings={control}")
print(f"hidden/visible_boxes={len(core.refdes_boxes_from_board(poison))} "
      f"expected={len(expected_visible)}")
print(f"hidden/parse_coverage_findings={hidden}")
print(f"courtyard/empty_geometry_findings={builder.findings}")

edge_builder = core.BoardBuilder(
    20, 20, [],
    {"X1": {"footprint": "Probe:MissingEdgeMarker"}},
    {"X1": (20, 10, 0, "F")},
    overhang_ok=(("X1", "E"),),
)


class MarkerlessFootprint:
    graphicItems = []


original_load = core.fplib.load
try:
    core.fplib.load = lambda _fpid: MarkerlessFootprint()
    edge_builder.gate_edge_markers()
finally:
    core.fplib.load = original_load

print(f"edge-marker/declared_but_markerless_findings={edge_builder.findings}")
print("wrote four oracle poison JSON files")
