#!/usr/bin/env python3
"""Probe the serialized J1 refdes anchor against U1's physical body.

This reads only the emitted board text and applies KiCad's stored-local
rotation/translation. It does not call the generator's refdes placement or
readback helpers.
"""
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[6]
BOARD = ROOT / "hardware/kicad/pcb/build_display/display_pcb.kicad_pcb"


def balanced(text, start):
    depth = 0
    quoted = False
    escaped = False
    for pos in range(start, len(text)):
        char = text[pos]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
    raise ValueError("unbalanced board expression")


def footprint(text, wanted):
    for match in re.finditer(r'\n  \(footprint ', text):
        start = match.start() + 3
        chunk = text[start:balanced(text, start)]
        ref = re.search(r'\(property "Reference" "([^"]+)"', chunk)
        if ref and ref.group(1) == wanted:
            return chunk
    raise KeyError(wanted)


def placement(chunk):
    match = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', chunk)
    return tuple(float(v or 0) for v in match.groups())


def world(point, at):
    x, y = point
    fx, fy, angle = at
    angle = math.radians(angle)
    c, s = math.cos(angle), math.sin(angle)
    return fx + x * c + y * s, fy - x * s + y * c


def reference_anchor(chunk):
    start = chunk.index('(property "Reference"')
    block = chunk[start:balanced(chunk, start)]
    match = re.search(r'\(at ([-\d.]+) ([-\d.]+)', block)
    layer = re.search(r'\(layer "([^"]+)"\)', block).group(1)
    return (float(match.group(1)), float(match.group(2))), layer


def fab_box(chunk):
    points = []
    for match in re.finditer(
            r'\(fp_line \(start ([-\d.]+) ([-\d.]+)\) '
            r'\(end ([-\d.]+) ([-\d.]+)\) \(layer "B\.Fab"\)', chunk):
        points.extend(((float(match.group(1)), float(match.group(2))),
                       (float(match.group(3)), float(match.group(4)))))
    for match in re.finditer(
            r'\(fp_rect \(start ([-\d.]+) ([-\d.]+)\) '
            r'\(end ([-\d.]+) ([-\d.]+)\) \(layer "B\.Fab"\)', chunk):
        x0, y0, x1, y1 = map(float, match.groups())
        points.extend(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    if not points:
        raise ValueError("no B.Fab body geometry")
    placed = [world(point, placement(chunk)) for point in points]
    xs, ys = zip(*placed)
    return min(xs), min(ys), max(xs), max(ys)


def main():
    text = BOARD.read_text(encoding="utf-8")
    j1 = footprint(text, "J1")
    u1 = footprint(text, "U1")
    local, layer = reference_anchor(j1)
    anchor = world(local, placement(j1))
    body = fab_box(u1)
    inside = body[0] <= anchor[0] <= body[2] and body[1] <= anchor[1] <= body[3]
    print(f"board={BOARD.relative_to(ROOT).as_posix()}")
    print(f"J1 reference layer={layer}")
    print(f"J1 serialized local anchor=({local[0]:.3f},{local[1]:.3f})")
    print(f"J1 board anchor=({anchor[0]:.3f},{anchor[1]:.3f}) mm")
    print("U1 B.Fab body box="
          f"({body[0]:.3f},{body[1]:.3f})..({body[2]:.3f},{body[3]:.3f}) mm")
    print(f"J1 anchor inside U1 body={inside}")
    print("RESULT=FINDING" if inside else "RESULT=PASS")


if __name__ == "__main__":
    main()
