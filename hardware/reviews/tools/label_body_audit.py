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

    def shrunk(self, m: float) -> "Box":
        return Box(self.x0 + m, self.y0 + m, self.x1 - m, self.y1 - m)


def _seg_clip_len(p0, p1, box: "Box") -> float:
    """Length of the segment p0→p1 that lies inside `box` (Liang–Barsky).

    Used for wire-through-element detection: a wire that merely terminates
    at an element edge (a pin connection) clips to ~0 length; a wire that
    runs THROUGH an element clips to a meaningful length.
    """
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - box.x0), (dx, box.x1 - x0),
                 (-dy, y0 - box.y0), (dy, box.y1 - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return 0.0          # parallel and outside this edge
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return 0.0
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return 0.0
            if r < t1:
                t1 = r
    if t1 <= t0:
        return 0.0
    seg_len = (dx * dx + dy * dy) ** 0.5
    return (t1 - t0) * seg_len


def _seg_intersect(a0, a1, b0, b1):
    """Return (x, y) where segments a0a1 and b0b1 cross, else None.

    Endpoints touching count as an intersection (used to classify
    junction taps vs free crossings downstream).
    """
    (x1, y1), (x2, y2) = a0, a1
    (x3, y3), (x4, y4) = b0, b1
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return None                 # parallel / colinear
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


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
    # Thickness (perpendicular to the text) is just the cap height plus a
    # thin border. It must stay < the 2.54 mm pin pitch so that adjacent
    # connector/IC pin labels (stacked one pitch apart, which render with
    # a clear gap — verified on the J3/J4 dev headers) do NOT register as
    # a flag∩flag overlap. PAD only pads the text-direction length.
    half_t = TEXT_H / 2 + 0.25   # full thickness ≈ 2.05 mm < 2.54 pitch
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


def _label_core_box(text: str, x: float, y: float, angle: float,
                    justify: str | None) -> Box:
    """The flag's TEXT-BODY box, excluding the ~2.5 mm connection zone at
    the chevron tip. A wire reaching the chevron tip is a normal
    connection; only a wire crossing this core is a 'strike-through'.
    """
    length = len(text) * CHAR_W + CHEVRON + PAD
    half_t = TEXT_H / 2 + 0.25
    cz = 2.5    # connection-zone depth excluded from the chevron side
    a = int(round(angle)) % 360
    if a in (0, 180):
        if justify == "right":          # chevron right; body left
            return Box(x - length, y - half_t, x - cz, y + half_t)
        return Box(x + cz, y - half_t, x + length, y + half_t)
    else:                               # vertical
        if justify == "left":           # chevron down; body up
            return Box(x - half_t, y - length, x + half_t, y - cz)
        return Box(x - half_t, y + cz, x + half_t, y + length)


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

    bodies: list[tuple[str, Box, tuple[float, float]]] = []
    texts: list[tuple[str, Box]] = []
    for inst in s.schematicSymbols:
        name = inst.entryName
        ref = next((p.value for p in inst.properties if p.key == "Reference"), "?")
        c = (inst.position.X, inst.position.Y)
        if name in extents:
            bodies.append((ref, _instance_body_box(inst, extents[name]), c))
        for p in inst.properties:
            # Skip hidden text and the conventionally-hidden pseudo-refs
            # of power-port / power-flag symbols (#PWR*, #FLG*), which
            # never render and whose Value duplicates the net glyph.
            if p.key in ("Reference", "Value") and p.value and not (
                    p.effects and p.effects.hide) and not ref.startswith("#"):
                texts.append((f"{ref}.{p.key}={p.value}",
                              _text_box(p.value, p.position.X, p.position.Y)))

    labels = []
    label_cores = []
    for lbl in s.globalLabels:
        j = (lbl.effects.justify.horizontally
             if lbl.effects and lbl.effects.justify else None)
        box = _label_box(lbl.text, lbl.position.X, lbl.position.Y,
                         lbl.position.angle or 0, j)
        labels.append((lbl.text, box, lbl.position))
        label_cores.append(_label_core_box(lbl.text, lbl.position.X,
                                            lbl.position.Y,
                                            lbl.position.angle or 0, j))

    # Wire segments (each Connection of type "wire" is a polyline).
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for g in (s.graphicalItems or []):
        if type(g).__name__ == "Connection" and getattr(g, "type", None) == "wire":
            pts = [(p.X, p.Y) for p in g.points]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    segments.append((a, b))
    junctions = [(jn.position.X, jn.position.Y) for jn in (s.junctions or [])]

    # Thresholds (mm²). A label flag tip naturally sits one pin-pitch
    # (2.54 mm) from the power-port glyph on the *adjacent* pin of the
    # same connector — that grazes the generous power-port body box by
    # ~1.7 mm² but reads perfectly fine. Use a higher floor for power
    # ports so those adjacent-pin grazes drop out while a real flag-on-
    # glyph stack (≫ the original 9 mm² V3V3-on-GND case) still fires.
    # Component bodies (R/C/IC) and ref/value text use a tighter floor.
    # body∩body uses the lowest floor: NO two component glyphs should
    # share ink — they connect through pins/wires, never overlapping
    # bodies — so even a small overlap is a real bug.
    MIN_BODY = 2.0       # label-flag ∩ component body
    MIN_PWR = 4.0        # label-flag ∩ power-port glyph (adjacent-pin grazes ~1.7)
    MIN_TEXT = 2.0       # label-flag ∩ ref/value text
    MIN_BB = 0.5         # body ∩ body (any shared ink is wrong)
    MIN_FF = 2.0         # flag ∩ flag

    findings = []

    # (1) label flag ∩ component / power-port body
    # (2) label flag ∩ ref/value text
    for text, lbox, pos in labels:
        for ref, bbox, _c in bodies:
            a = lbox.inter(bbox)
            floor = MIN_PWR if ref == "#PWR" else MIN_BODY
            if a >= floor:
                findings.append((a, f"flag∩body : label {text!r} ∩ body {ref} "
                                    f"= {a:.1f} mm²  (at {pos.X:.1f},{pos.Y:.1f})"))
        for tref, tbox in texts:
            a = lbox.inter(tbox)
            if a >= MIN_TEXT:
                findings.append((a, f"flag∩text : label {text!r} ∩ {tref} "
                                    f"= {a:.1f} mm²  (at {pos.X:.1f},{pos.Y:.1f})"))

    # (3) body ∩ body  — NEW: catches a power-port glyph or any symbol
    #     overlapping another symbol's body (e.g. GND port on a resistor).
    for i in range(len(bodies)):
        ref_i, box_i, c_i = bodies[i]
        for k in range(i + 1, len(bodies)):
            ref_k, box_k, c_k = bodies[k]
            a = box_i.inter(box_k)
            if a >= MIN_BB:
                findings.append((a, f"body∩body : {ref_i} ∩ {ref_k} "
                                    f"= {a:.1f} mm²  (near {c_i[0]:.1f},{c_i[1]:.1f})"))

    # (4) flag ∩ flag  — NEW: two label flags whose bodies overlap.
    for i in range(len(labels)):
        t_i, box_i, p_i = labels[i]
        for k in range(i + 1, len(labels)):
            t_k, box_k, p_k = labels[k]
            a = box_i.inter(box_k)
            if a >= MIN_FF:
                findings.append((a, f"flag∩flag : {t_i!r} ∩ {t_k!r} "
                                    f"= {a:.1f} mm²  (at {p_i.X:.1f},{p_i.Y:.1f})"))

    # (5) wire ∩ element — a wire that runs THROUGH a body / flag / text.
    #     A wire that merely *terminates* at an element (a pin connection,
    #     or a wire ending at its own net flag) is fine; only a genuine
    #     pass-through is a finding. A pass-through has BOTH endpoints
    #     outside the element and a long interior clip.
    MIN_WIRE_THRU = 1.3   # mm of wire inside the element to count as "through"

    def _outside(pt, box):
        return not (box.x0 - 0.3 <= pt[0] <= box.x1 + 0.3 and
                    box.y0 - 0.3 <= pt[1] <= box.y1 + 0.3)

    def _end_in_interior(box):
        inner = box.shrunk(1.0)
        return (
            (inner.x0 <= s0[0] <= inner.x1 and inner.y0 <= s0[1] <= inner.y1) or
            (inner.x0 <= s1[0] <= inner.x1 and inner.y0 <= s1[1] <= inner.y1))

    for s0, s1 in segments:
        for ref, bbox, _c in bodies:
            # Power ports / power-flags (#…) are terminal glyphs: a wire
            # always legitimately ENDS at them, so only a true pass-through
            # (both endpoints outside, long interior clip) is a finding.
            # Real component bodies (R/C/L/IC) additionally flag a wire
            # that ENDS in their interior — a stub routed into the body
            # instead of stopping at a pin on the edge (e.g. the R2 case).
            clip = _seg_clip_len(s0, s1, bbox.shrunk(0.6))
            if clip < MIN_WIRE_THRU:
                continue
            passthru = _outside(s0, bbox) and _outside(s1, bbox)
            terminal = ref.startswith("#")
            if passthru or (not terminal and _end_in_interior(bbox)):
                findings.append((5.0, f"wire∩body : wire through/into {ref} body "
                                      f"(seg {s0[0]:.1f},{s0[1]:.1f}→{s1[0]:.1f},{s1[1]:.1f})"))
        for (text, lbox, pos), core in zip(labels, label_cores):
            # Check the flag's TEXT CORE (chevron/connection zone excluded)
            # so a wire reaching the chevron tip — a normal connection —
            # is not mistaken for a body strike-through.
            if _seg_clip_len(s0, s1, core) >= MIN_WIRE_THRU:
                findings.append((5.0, f"wire∩flag : wire through {text!r} flag body "
                                      f"(at {pos.X:.1f},{pos.Y:.1f})"))
        for tref, tbox in texts:
            if _outside(s0, tbox) and _outside(s1, tbox) and \
                    _seg_clip_len(s0, s1, tbox.shrunk(0.2)) >= MIN_WIRE_THRU:
                findings.append((5.0, f"wire∩text : wire through {tref}"))

    # (6) wire ∩ wire crossings — count free interior×interior crossings
    #     (guideline c: minimise these). T-taps (one wire's endpoint on
    #     another's interior) are electrical connections; KiCad renders a
    #     junction dot at them automatically, so they need no audit here
    #     — the dot-vs-no-dot distinction is enforced by KiCad's renderer.
    def _is_endpoint(pt, seg):
        return (abs(pt[0] - seg[0][0]) < 0.05 and abs(pt[1] - seg[0][1]) < 0.05) or \
               (abs(pt[0] - seg[1][0]) < 0.05 and abs(pt[1] - seg[1][1]) < 0.05)

    crossings = 0
    crossing_pts = []
    for i in range(len(segments)):
        for k in range(i + 1, len(segments)):
            pt = _seg_intersect(*segments[i], *segments[k])
            if pt is None:
                continue
            ep_i = _is_endpoint(pt, segments[i])
            ep_k = _is_endpoint(pt, segments[k])
            if not ep_i and not ep_k:
                crossings += 1      # interior×interior free crossing
                crossing_pts.append(pt)

    # (7) ADVISORY: two GlobalLabels carrying the SAME net name that sit
    #     close together should usually be replaced by a wire (guideline
    #     a) — flags are for genuinely far-apart connections.
    PROX = 20.0   # mm — "near" threshold
    advisories = []
    for i in range(len(labels)):
        t_i, _b_i, p_i = labels[i]
        for k in range(i + 1, len(labels)):
            t_k, _b_k, p_k = labels[k]
            if t_i != t_k:
                continue
            d = ((p_i.X - p_k.X) ** 2 + (p_i.Y - p_k.Y) ** 2) ** 0.5
            if d <= PROX:
                advisories.append((d, f"same-net labels {t_i!r} only "
                                      f"{d:.1f} mm apart "
                                      f"(({p_i.X:.0f},{p_i.Y:.0f})/"
                                      f"({p_k.X:.0f},{p_k.Y:.0f})) — "
                                      f"consider wiring instead of two flags"))

    findings.sort(reverse=True)
    if crossings:
        locs = ", ".join(f"({p[0]:.0f},{p[1]:.0f})" for p in crossing_pts)
        print(f"  [advisory] {crossings} free wire crossing(s) at {locs} "
              f"(no junction; minimise these per guideline c)")
    for _, line in sorted(advisories):
        print(f"  [advisory] {line}")
    print(f"=== {sch_path.name}: {len(findings)} geometry findings ===")
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
    # Non-zero exit on any finding so callers (build, CI) can gate on it.
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
