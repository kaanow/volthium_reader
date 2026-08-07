"""Independent attacks outside the iteration-22 mutation list."""

import importlib.util
import math
from pathlib import Path
import re
import sys
import tempfile


REPO = Path(__file__).resolve().parents[6]
PCB = REPO / "hardware" / "kicad" / "pcb"
sys.path.insert(0, str(PCB))

import core  # noqa: E402


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


display = load_module("review_display_iter23", PCB / "build_display_pcb.py")
board_path = PCB / "build_display" / "display_pcb.kicad_pcb"
text = board_path.read_text(encoding="utf-8")
mechanical = {f"H{i}" for i in range(1, len(display.MOUNT) + 1)}
visible = set(display.COMPS)
all_refs = visible | mechanical


def chunks(board_text):
    for match in re.finditer(r'\n  \(footprint "([^"]+)"', board_text):
        start = match.start() + 1
        end = core._balanced(board_text, start + 2)
        yield start, end, board_text[start:end]


def emitted_ref_points(board_text):
    points = {}
    for _, _, chunk in chunks(board_text):
        anchor = core.sexp_anchor(chunk)
        pm = re.search(r'\(property "Reference" "([^"]+)"', chunk)
        if anchor is None or not pm:
            continue
        block = chunk[pm.start():core._balanced(chunk, pm.start())]
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)', block)
        if not at:
            continue
        fx, fy, rotation = anchor
        dx, dy = float(at.group(1)), float(at.group(2))
        c = math.cos(math.radians(rotation))
        s = math.sin(math.radians(rotation))
        points[pm.group(1)] = (fx + dx * c + dy * s,
                              fy - dx * s + dy * c)
    return points


saved_selected = core._REFDES_SELECTED
saved_fallback = core._REFDES_FALLBACK
saved_intent = core._FPID_INTENT
core._REFDES_SELECTED = emitted_ref_points(text)
core._REFDES_FALLBACK = set()
core._FPID_INTENT = display.COMPS

builder = core.BoardBuilder(
    display.W,
    display.H,
    display.NETS,
    display.COMPS,
    display.P,
    overhang_ok=display.OVERHANG_OK,
    edge_marker_refs=display.EDGE_MARKER_REFS,
)
builder.mechanical_refs = mechanical
original_boxes = core.refdes_boxes_from_board(text)


def with_temp(board_text, fn):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".kicad_pcb", delete=False, encoding="utf-8", newline="\n"
    ) as handle:
        handle.write(board_text)
        path = Path(handle.name)
    try:
        return fn(path)
    finally:
        path.unlink(missing_ok=True)


def readback(board_text):
    def run(path):
        builder.findings = []
        builder.gate_readback(path)
        return list(builder.findings)
    return with_temp(board_text, run)


def escalate(board_text):
    def run(path):
        findings = []
        try:
            core.pcbnew_crosscheck(
                path,
                display.COMPS,
                display.P,
                original_boxes,
                findings,
                mechanical=mechanical,
            )
        except SystemExit as exc:
            findings.append(str(exc))
        return findings
    return with_temp(board_text, run)


def full_battery(board_text):
    findings = core._run_board_gates(
        board_text, visible, all_refs, readback=readback
    )
    if not findings:
        findings += escalate(board_text)
    return findings


first_start, first_end, first_chunk = next(chunks(text))
value_match = re.search(r'\(property "Value" "([^"]*)"', first_chunk)
if not value_match:
    raise RuntimeError("first footprint has no Value property")
value_poison_chunk = (
    first_chunk[:value_match.start(1)]
    + "ZZ_WRONG_VALUE"
    + first_chunk[value_match.end(1):]
)
value_poison = text[:first_start] + value_poison_chunk + text[first_end:]


def strip_edges(board_text):
    removals = []
    for match in re.finditer(r'\n  \(gr_(?:line|arc|rect|poly)', board_text):
        start = match.start() + 1
        end = core._balanced(board_text, start + 2)
        block = board_text[start:end]
        if '(layer "Edge.Cuts")' in block:
            removals.append((start, end))
    out = board_text
    for start, end in reversed(removals):
        out = out[:start] + out[end:]
    return out, len(removals)


outline_poison, removed_edges = strip_edges(text)


def strict_drc(board_text, tag):
    def run(path):
        report = path.with_name(path.stem + f"-{tag}.rpt")
        try:
            unaccounted, counts = core.run_drc(
                path, display.DRC_ACCEPTED, report
            )
            return {"unaccounted": unaccounted, "counts": counts}
        finally:
            report.unlink(missing_ok=True)
    return with_temp(board_text, run)


try:
    control = full_battery(text)
    value_findings = full_battery(value_poison)
    outline_findings = full_battery(outline_poison)
    control_drc = strict_drc(text, "control")
    value_drc = strict_drc(value_poison, "value")
    outline_drc = strict_drc(outline_poison, "outline")

    front = '(footprint "X" (layer "F.Cu") (at 1 2))'
    back = '(footprint "X" (layer "B.Cu") (at 1 2))'
    missing = '(footprint "X" (at 1 2))'
    malformed = '(footprint "X" (layer BAD) (at 1 2))'
    quoted = '(footprint "legal ) text" (layer "B.Cu") (at 1 2 90))'
    layer_results = {
        "front": core.footprint_layer(front),
        "back": core.footprint_layer(back),
        "missing": core.footprint_layer(missing),
        "malformed": core.footprint_layer(malformed),
        "quoted_anchor": core.sexp_anchor(quoted),
        "quoted_layer": core.footprint_layer(quoted),
    }
finally:
    core._REFDES_SELECTED = saved_selected
    core._REFDES_FALLBACK = saved_fallback
    core._FPID_INTENT = saved_intent


mutation_names = [name for name, _ in core._mutations(text, all_refs)]
checks = {
    "control_clean": control == [],
    "f19_direct_child_controls": layer_results == {
        "front": "F.Cu",
        "back": "B.Cu",
        "missing": None,
        "malformed": None,
        "quoted_anchor": (1.0, 2.0, 90.0),
        "quoted_layer": "B.Cu",
    },
    "value_mutation_is_outside_submitted_list": not any(
        "value" in name.lower() for name in mutation_names
    ),
    "outline_mutation_is_outside_submitted_list": not any(
        "outline" in name.lower() or "edge" in name.lower()
        for name in mutation_names
    ),
    "value_mutation_rejected": bool(value_findings),
    "outline_mutation_rejected": bool(outline_findings),
    "value_drc_unchanged_from_control": value_drc == control_drc,
    "outline_drc_adds_invalid_outline": (
        outline_drc["counts"].get("invalid_outline", 0)
        > control_drc["counts"].get("invalid_outline", 0)
    ),
}

print("submitted_mutations:", mutation_names)
print("f19_controls:", layer_results)
print("control_findings:", control)
print("value_mutation_findings:", value_findings)
print("outline_edges_removed:", removed_edges)
print("outline_mutation_findings:", outline_findings)
print("control_strict_drc:", control_drc)
print("value_strict_drc:", value_drc)
print("outline_strict_drc:", outline_drc)
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'} {name}")

failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("independent battery extension failed: " + ", ".join(failed))
