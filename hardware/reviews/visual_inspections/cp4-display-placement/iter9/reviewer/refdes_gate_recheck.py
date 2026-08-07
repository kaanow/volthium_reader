"""Independent recheck of the CP4 iteration-8 emitted-refdes gates."""

from pathlib import Path
import math
import re
import sys


ROOT = Path(__file__).resolve().parents[6]
PCB_DIR = ROOT / "hardware" / "kicad" / "pcb"
BOARD = PCB_DIR / "build_display" / "display_pcb.kicad_pcb"
sys.path.insert(0, str(PCB_DIR))

import core  # noqa: E402


def balanced(text, start):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced board expression")


def footprint_span(text, ref):
    for m in re.finditer(r'\n  \(footprint "[^"]+"', text):
        start = m.start() + 1
        end = balanced(text, start)
        chunk = text[start:end]
        if re.search(rf'\(property "Reference" "{re.escape(ref)}"', chunk):
            return start, end, chunk
    raise KeyError(ref)


def set_reference_board_anchor(text, ref, bx, by):
    start, end, chunk = footprint_span(text, ref)
    fm = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', chunk)
    pm = re.search(rf'\(property "Reference" "{re.escape(ref)}"', chunk)
    prop_end = balanced(chunk, pm.start())
    prop = chunk[pm.start():prop_end]
    am = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', prop)
    fx, fy = float(fm.group(1)), float(fm.group(2))
    rot = float(fm.group(3)) if fm.group(3) else 0.0
    dx, dy = bx - fx, by - fy
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    lx, ly = dx * c - dy * s, dx * s + dy * c
    angle = am.group(3) or "0"
    new_prop = prop[:am.start()] + f"(at {lx:.3f} {ly:.3f} {angle})" + prop[am.end():]
    new_chunk = chunk[:pm.start()] + new_prop + chunk[prop_end:]
    return text[:start] + new_chunk + text[end:]


def report(label, findings, expected_fragment):
    caught = any(expected_fragment in item for item in findings)
    print(label)
    print(f"  findings={findings}")
    print(f"  RESULT={'CAUGHT' if caught else 'ESCAPED'}")
    return caught


def main():
    text = BOARD.read_text(encoding="utf-8")
    boxes = core.refdes_boxes_from_board(text)
    selected = {
        ref: ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        for ref, box in boxes
    }

    original_selected = dict(core._REFDES_SELECTED)
    original_fallback = set(core._REFDES_FALLBACK)
    try:
        core._REFDES_SELECTED.clear()
        core._REFDES_SELECTED.update(selected)
        core._REFDES_FALLBACK.clear()

        findings = []
        core.assert_refdes_roundtrip(text, findings)
        body = core.refdes_over_body_findings(text)
        print("CONTROL")
        print(f"  roundtrip_findings={findings}")
        print(f"  body_findings={body}")
        print(f"  RESULT={'PASS' if not findings and not body else 'FAIL'}")
        control = not findings and not body

        poison = set_reference_board_anchor(text, "J1", 11.0, 47.325)
        findings = []
        core.assert_refdes_roundtrip(poison, findings)
        p1 = report("POISON 1: emitted J1 anchor moved", findings,
                    "[refdes-roundtrip] J1")

        poison = set_reference_board_anchor(text, "BTN2", 38.0, 57.5)
        findings = core.refdes_over_body_findings(poison)
        p2 = report("POISON 2: anchor clears but text box overlaps",
                    findings, "[refdes-on-body] BTN2")

        bodies = {ref: box for ref, _side, box in core.bodies_from_board(text)}
        u2 = bodies["U2"]
        poison = set_reference_board_anchor(
            text, "U2", (u2[0] + u2[2]) / 2, (u2[1] + u2[3]) / 2
        )
        findings = core.refdes_over_body_findings(poison)
        p3 = report("POISON 3: reference centered on own body", findings,
                    "overlaps its own body")

        core._REFDES_SELECTED.clear()
        findings = []
        core.assert_refdes_roundtrip(text, findings)
        p4 = report("POISON 4: no placer selections", findings,
                    "no placement selections recorded")

        mod = bodies["MOD1"]
        print("INDEPENDENT EXTENT CHECK")
        print(f"  MOD1 body={mod}")
        print(f"  size=({mod[2] - mod[0]:.2f},{mod[3] - mod[1]:.2f}) mm")
        extent = abs((mod[2] - mod[0]) - 18.0) < 0.01 and \
            abs((mod[3] - mod[1]) - 25.5) < 0.01
        print(f"  RESULT={'PASS' if extent else 'FAIL'}")
    finally:
        core._REFDES_SELECTED.clear()
        core._REFDES_SELECTED.update(original_selected)
        core._REFDES_FALLBACK.clear()
        core._REFDES_FALLBACK.update(original_fallback)

    ok = control and p1 and p2 and p3 and p4 and extent
    print(f"SUMMARY: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
