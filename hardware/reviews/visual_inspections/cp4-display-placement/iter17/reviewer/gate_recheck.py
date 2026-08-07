"""Independent probes for the CP4 iteration-16 gate-strength changes."""

import copy
import importlib.util
from pathlib import Path
import re
import sys


REPO = Path(__file__).resolve().parents[6]
PCB = REPO / "hardware" / "kicad" / "pcb"
sys.path.insert(0, str(PCB))

import core  # noqa: E402


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


battery = load_module("review_battery_build", PCB / "build.py")
display = load_module("review_display_build", PCB / "build_display_pcb.py")


def edge_findings(module, expected):
    builder = core.BoardBuilder(
        module.W,
        module.H,
        module.NETS,
        module.COMPS,
        module.P,
        overhang_ok=module.OVERHANG_OK,
        edge_marker_refs=expected,
    )
    builder.gate_edge_markers()
    return builder.findings


control_battery = edge_findings(battery, {"J3"})
wrong_identity = edge_findings(battery, {"J1"})
control_display = edge_findings(display, set())

original_load = core.fplib.load
j3_fpid = battery.COMPS["J3"]["footprint"]
display_usb_fpid = display.COMPS["J-USB"]["footprint"]
marker_template = next(
    item
    for item in original_load(j3_fpid).graphicItems
    if type(item).__name__ == "FpText"
    and getattr(item, "type", "") == "user"
    and getattr(item, "text", "") == "PCB Edge"
)


def markerless_load(fpid):
    fp = copy.deepcopy(original_load(fpid))
    if fpid == j3_fpid:
        fp.graphicItems = [
            item
            for item in fp.graphicItems
            if not (
                type(item).__name__ == "FpText"
                and getattr(item, "type", "") == "user"
                and getattr(item, "text", "") == "PCB Edge"
            )
        ]
    return fp


def unexpected_marker_load(fpid):
    fp = copy.deepcopy(original_load(fpid))
    if fpid == display_usb_fpid:
        fp.graphicItems.append(copy.deepcopy(marker_template))
    return fp


try:
    core.fplib.load = markerless_load
    marker_disappears = edge_findings(battery, {"J3"})
    core.fplib.load = unexpected_marker_load
    marker_appears = edge_findings(display, set())
finally:
    core.fplib.load = original_load


class ProbePad:
    def __init__(self, pad_type):
        self.type = pad_type
        self.number = "1"
        self.drill = None


class ProbeFootprint:
    def __init__(self, pad_type):
        self.properties = {"Reference": "XTEST"}
        self.pads = [ProbePad(pad_type)]


fab_builder = core.BoardBuilder(10, 10, [], {}, {})
fab_builder.b.footprints = [ProbeFootprint("thru_hole")]
fab_builder.gate_fab_rules()
missing_drill = list(fab_builder.findings)

fab_builder = core.BoardBuilder(10, 10, [], {}, {})
fab_builder.b.footprints = [ProbeFootprint("smd")]
fab_builder.gate_fab_rules()
smd_control = list(fab_builder.findings)


board_path = PCB / "build_display" / "display_pcb.kicad_pcb"
board_text = board_path.read_text(encoding="utf-8")
first = re.search(r'\n  \(footprint "([^"]+)"', board_text)
if not first:
    raise RuntimeError("fresh display board contains no footprint")
start = first.start() + 1
end = core._balanced(board_text, start + 2)
chunk = board_text[start:end]

bad_anchor_chunk = re.sub(
    r"\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)",
    "(at BAD BAD)",
    chunk,
    count=1,
)
bad_reference_chunk = chunk.replace(
    '(property "Reference"', '(property "BrokenReference"', 1
)


def chunk_for_ref(text, wanted):
    for match in re.finditer(r'\n  \(footprint "([^"]+)"', text):
        chunk_start = match.start() + 1
        chunk_end = core._balanced(text, chunk_start + 2)
        candidate = text[chunk_start:chunk_end]
        if f'(property "Reference" "{wanted}"' in candidate:
            return candidate
    raise RuntimeError(f"could not find footprint {wanted}")


battery_text = (PCB / "build" / "battery_pcb.kicad_pcb").read_text(
    encoding="utf-8"
)
fallback_chunk = chunk_for_ref(battery_text, "C_sense")
fallback_bad_anchor = re.sub(
    r"\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)",
    "(at BAD BAD)",
    fallback_chunk,
    count=1,
)

saved_selected = core._REFDES_SELECTED
saved_fallback = core._REFDES_FALLBACK
try:
    # Non-empty state reaches the written-footprint loop; this probe judges
    # only whether malformed footprints are surfaced, not placement points.
    core._REFDES_SELECTED = {"__review_probe__": (0.0, 0.0)}
    core._REFDES_FALLBACK = set()
    roundtrip_control = []
    core.assert_refdes_roundtrip(board_text, roundtrip_control)
    bad_anchor = []
    core.assert_refdes_roundtrip(
        board_text[:start] + bad_anchor_chunk + board_text[end:], bad_anchor
    )
    bad_reference = []
    core.assert_refdes_roundtrip(
        board_text[:start] + bad_reference_chunk + board_text[end:],
        bad_reference,
    )
    # This is a real consumer state: auto_refdes records no selected point
    # for a library fallback. A missing footprint anchor must still fail.
    core._REFDES_SELECTED = {"__review_probe__": (0.0, 0.0)}
    core._REFDES_FALLBACK = {"C_sense"}
    fallback_control = []
    core.assert_refdes_roundtrip("\n  " + fallback_chunk, fallback_control)
    fallback_anchor_missing = []
    core.assert_refdes_roundtrip(
        "\n  " + fallback_bad_anchor, fallback_anchor_missing
    )
finally:
    core._REFDES_SELECTED = saved_selected
    core._REFDES_FALLBACK = saved_fallback


def malformed(findings):
    return [f for f in findings if "no parseable anchor or reference" in f]


checks = {
    "battery_control_clean": control_battery == [],
    "display_control_clean": control_display == [],
    "same_size_scope_substitution_fails": any(
        "missing ['J1']" in f and "unexpected ['J3']" in f
        for f in wrong_identity
    ),
    "expected_marker_disappearance_fails": any(
        "missing ['J3']" in f for f in marker_disappears
    ),
    "unexpected_marker_appearance_fails": any(
        "unexpected ['J-USB']" in f for f in marker_appears
    ),
    "typed_through_hole_without_drill_fails": len(missing_drill) == 1,
    "drillless_smd_control_clean": smd_control == [],
    "roundtrip_control_has_no_malformed_footprint": malformed(roundtrip_control) == [],
    "malformed_anchor_fails": len(malformed(bad_anchor)) == 1,
    "malformed_reference_fails": len(malformed(bad_reference)) == 1,
    "fallback_control_clean": fallback_control == [],
    "fallback_malformed_anchor_rejected": len(
        malformed(fallback_anchor_missing)
    ) == 1,
}

print("edge/battery_control:", control_battery)
print("edge/display_control:", control_display)
print("edge/wrong_identity:", wrong_identity)
print("edge/marker_disappears:", marker_disappears)
print("edge/marker_appears:", marker_appears)
print("fab/missing_drill:", missing_drill)
print("fab/smd_control:", smd_control)
print("roundtrip/control_malformed:", malformed(roundtrip_control))
print("roundtrip/bad_anchor:", malformed(bad_anchor))
print("roundtrip/bad_reference:", malformed(bad_reference))
print("roundtrip/fallback_control:", fallback_control)
print("roundtrip/fallback_anchor_missing:", fallback_anchor_missing)
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'} {name}")

failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("independent gate recheck failed: " + ", ".join(failed))
