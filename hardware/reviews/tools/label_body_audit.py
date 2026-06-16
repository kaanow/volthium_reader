#!/usr/bin/env python3
"""Detect GlobalLabel flags that land on top of component symbols.

The strict text-overlap audit (`schematic_visual_audit.py`) only sees
text-vs-text bbox overlap. It is blind to a label whose *flag body*
(the hexagon outline + its rotated text) sweeps across a component
symbol's body, pins, reference, or value — which is exactly what the
justify-based label reorientation can cause (a long net name on a
vertical flag extends many grid units and can cross an adjacent
vertical resistor / its value text).

This tool reads the generated `.kicad_sch` directly and, for every
`global_label`, computes the analytic bounding box of the rendered
flag (text length × calibrated char width, oriented by angle +
justify). It then intersects that box against:

  (a) every component body bbox (from the library symbol's graphic
      items, oriented by the instance angle and centered on the
      instance position), and
  (b) every component Reference / Value property text bbox.

Anything that intersects is reported. A label is allowed to touch the
component it actually connects to ONLY at the pin stub; a flag body
sitting *on* a body rectangle is always clutter.

Usage:
    .venv/bin/python hardware/reviews/tools/label_body_audit.py \
        hardware/kicad/display_side/display_side.kicad_sch
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.schematic import Schematic

REPO = Path(__file__).resolve().parents[3]
LIB_FILE = REPO / "hardware/kicad/libraries/volthium.kicad_sym"

# Calibrated from rendered KiCad PDFs (stroke font, 1.27 mm text size).
CHAR_W = 0.92          # mm per character (horizontal advance)
TEXT_H = 1.55          # mm text cap height
CHEVRON = 1.6          # mm chevron + internal padding on the tip side
PAD = 0.9              # mm body padding around the text


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def inter(self, o: "Box") -> float:
        ix = min(self.x1, o.x1) - max(self.x0, o.x0)
        iy = min(self.y1, o.y1) - max(self.y0, o.y0)
        if ix <= 0 or iy <= 0:
            return 0.0
        return ix * iy


def _label_box(text: str, x: float, y: float, angle: float,
               justify: str | None) -> Box:
    """Analytic bbox of a rendered GlobalLabel flag (mm, schematic Y-down).

    The anchor (x, y) is the chevron tip (the wire connection point).
    `justify=right` puts the chevron on the right (body extends left)
    at angle 0; `justify=left` puts it on the left (body extends right).
    At angle 90 the same rotates: justify=left → chevron-down (body up),
    justify=right → chevron-up (body down).
    """
    length = len(text) * CHAR_W + CHEVRON + PAD
    half_t = TEXT_H / 2 + PAD
    a = int(round(angle)) % 360
    if a in (0, 180):
        if justify == "right":          # chevron right → body extends left
            return Box(x - length, y - half_t, x + CHEVRON, y + half_t)
        else:                           # chevron left → body extends right
            return Box(x - CHEVRON, y - half_t, x + length, y + half_t)
    else:                               # 90 / 270 : vertical
        if justify == "left":           # chevron down → body extends up
            return Box(x - half_t, y - length, x + half_t, y + CHEVRON)
        else:                           # chevron up → body extends down
            return Box(x - half_t, y - CHEVRON, x + half_t, y + length)


def _lib_body_extent(sym) -> tuple[float, float] | None:
    """Half-width / half-height (mm) of the symbol body graphics in lib
    coords (origin at pin-grid centre). Returns None if no body graphics.
    """
    xs: list[float] = []
    ys: list[float] = []
    for u in sym.units:
        for g in (u.graphicItems or []):
            cls = type(g).__name__
            if cls == "SyRect":
                xs += [g.start.X, g.end.X]
                ys += [g.start.Y, g.end.Y]
            elif cls == "SyPolyLine":
                for p in g.points:
                    xs.append(p.X)
                    ys.append(p.Y)
            elif cls == "SyCircle":
                xs += [g.center.X - g.radius, g.center.X + g.radius]
                ys += [g.center.Y - g.radius, g.center.Y + g.radius]
            elif cls == "SyArc":
                for p in (g.start, g.mid, g.end):
                    xs.append(p.X)
                    ys.append(p.Y)
    if not xs:
        return None
    return (max(abs(min(xs)), abs(max(xs))),
            max(abs(min(ys)), abs(max(ys))))


def _instance_body_box(inst, extent: tuple[float, float]) -> Box:
    """Body bbox centred on the instance, w/h swapped for 90/270."""
    hw, hh = extent
    a = int(round(inst.position.angle or 0)) % 360
    if a in (90, 270):
        hw, hh = hh, hw
    cx, cy = inst.position.X, inst.position.Y
    return Box(cx - hw, cy - hh, cx + hw, cy + hh)


def _text_box(text: str, x: float, y: float) -> Box:
    w = len(text) * CHAR_W
    return Box(x - w / 2, y - TEXT_H / 2, x + w / 2, y + TEXT_H / 2)


def audit(sch_path: Path) -> int:
    lib = SymbolLib.from_file(str(LIB_FILE))
    extents = {}
    for sym in lib.symbols:
        e = _lib_body_extent(sym)
        if e:
            extents[sym.entryName] = e

    s = Schematic.from_file(str(sch_path))

    bodies: list[tuple[str, Box]] = []
    texts: list[tuple[str, Box]] = []
    for inst in s.schematicSymbols:
        name = inst.entryName
        ref = next((p.value for p in inst.properties if p.key == "Reference"), "?")
        if name in extents:
            bodies.append((ref, _instance_body_box(inst, extents[name])))
        for p in inst.properties:
            if p.key in ("Reference", "Value") and p.value and not (
                    p.effects and p.effects.hide):
                texts.append((f"{ref}.{p.key}={p.value}",
                              _text_box(p.value, p.position.X, p.position.Y)))

    labels = []
    for lbl in s.globalLabels:
        j = (lbl.effects.justify.horizontally
             if lbl.effects and lbl.effects.justify else None)
        box = _label_box(lbl.text, lbl.position.X, lbl.position.Y,
                         lbl.position.angle or 0, j)
        labels.append((lbl.text, box, lbl.position))

    # Thresholds (mm²). A label flag tip naturally sits one pin-pitch
    # (2.54 mm) from the power-port glyph on the *adjacent* pin of the
    # same connector — that grazes the generous power-port body box by
    # ~1.7 mm² but reads perfectly fine. Use a higher floor for power
    # ports so those adjacent-pin grazes drop out while a real flag-on-
    # glyph stack (≫ the original 9 mm² V3V3-on-GND case) still fires.
    # Component bodies (R/C/IC) and ref/value text use a tighter floor.
    MIN_BODY = 2.0
    MIN_PWR = 4.0
    MIN_TEXT = 2.0

    findings = []
    for text, lbox, pos in labels:
        for ref, bbox in bodies:
            a = lbox.inter(bbox)
            floor = MIN_PWR if ref == "#PWR" else MIN_BODY
            if a >= floor:
                findings.append((a, f"label {text!r} flag ∩ body {ref} "
                                    f"= {a:.1f} mm²  (label at "
                                    f"{pos.X:.1f},{pos.Y:.1f})"))
        for tref, tbox in texts:
            a = lbox.inter(tbox)
            if a >= MIN_TEXT:
                findings.append((a, f"label {text!r} flag ∩ text {tref} "
                                    f"= {a:.1f} mm²  (label at "
                                    f"{pos.X:.1f},{pos.Y:.1f})"))

    findings.sort(reverse=True)
    print(f"=== {sch_path.name}: {len(findings)} label-on-component findings ===")
    for _, line in findings:
        print("  " + line)
    return len(findings)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("schematic", type=Path, nargs="+")
    args = ap.parse_args()
    total = 0
    for p in args.schematic:
        total += audit(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
