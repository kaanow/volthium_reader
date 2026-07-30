"""Footprint resolution + dimension extraction for the CP3+ placement pass.

Shared by the dims inventory report and the placement generator/gates —
one resolver, one geometry model, no side-channel copies.

Every number here is measured from the parsed .kicad_mod (courtyard
graphics + pad geometry), never recalled from a datasheet or assumed
from the name.
"""
import math
import os
import re
import sys
from pathlib import Path

from kiutils.footprint import Footprint

KROOT = Path(__file__).resolve().parents[1]          # hardware/kicad
KICAD_SHARE = os.environ.get(
    "KICAD_SHARE", "/Applications/KiCad/KiCad.app/Contents/SharedSupport")
FP_DIRS = [os.environ.get("KICAD10_FOOTPRINT_DIR", f"{KICAD_SHARE}/footprints"),
           str(KROOT / "footprints")]                # repo-local volthium.pretty


def resolve(fpid: str) -> Path:
    """'Lib:Name' -> path to the .kicad_mod, or SystemExit. Same dir list
    as the schematic-side footprint gate (core._FP_DIRS)."""
    lib, _, name = fpid.partition(":")
    if not name:
        raise SystemExit(f"[fplib] bare footprint id {fpid!r} — schematic-side "
                         "normalization should have caught this")
    for d in FP_DIRS:
        p = Path(d) / f"{lib}.pretty" / f"{name}.kicad_mod"
        if p.exists():
            return p
    raise SystemExit(f"[fplib] {fpid}: not found in {FP_DIRS}")


_CACHE = {}


def load(fpid: str) -> Footprint:
    if fpid not in _CACHE:
        _CACHE[fpid] = Footprint.from_file(str(resolve(fpid)), encoding="utf-8")
    return _CACHE[fpid]


def _is_heatsink_via(pad):
    return getattr(pad, "property", None) == "pad_prop_heatsink" or \
        (pad.drill is not None and pad.drill.diameter and pad.drill.diameter < 0.5
         and pad.size.X <= 0.8)


def _pad_corners(pad):
    """Corners of a pad's bounding rectangle in footprint coords,
    honoring the pad's own rotation angle."""
    cx, cy = pad.position.X, pad.position.Y
    ang = getattr(pad.position, "angle", None) or 0.0
    hx, hy = pad.size.X / 2.0, pad.size.Y / 2.0
    # drill can exceed copper for npth
    if pad.drill is not None and pad.drill.diameter:
        hx = max(hx, pad.drill.diameter / 2.0)
        hy = max(hy, (pad.drill.width or pad.drill.diameter) / 2.0)
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    out = []
    for dx, dy in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
        out.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return out


def _graphic_points(item):
    """Extreme points of one graphic item (lines/rects/circles/arcs/polys)."""
    t = type(item).__name__
    pts = []
    if t == "FpLine":
        pts = [(item.start.X, item.start.Y), (item.end.X, item.end.Y)]
    elif t == "FpRect":
        pts = [(item.start.X, item.start.Y), (item.end.X, item.end.Y)]
    elif t == "FpCircle":
        cx, cy = item.center.X, item.center.Y
        r = math.dist((cx, cy), (item.end.X, item.end.Y))
        pts = [(cx - r, cy - r), (cx + r, cy + r)]
    elif t == "FpArc":
        # conservative: chord endpoints + midpoint
        pts = [(item.start.X, item.start.Y), (item.end.X, item.end.Y),
               (item.mid.X, item.mid.Y)]
    elif t == "FpPoly":
        pts = [(p.X, p.Y) for p in item.coordinates]
    return pts


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


class FpDims:
    """Measured extents of one footprint, in its own coordinate frame
    (origin = footprint anchor, +y down as KiCad draws it)."""

    def __init__(self, fpid):
        fp = load(fpid)
        self.fpid = fpid
        self.pad_count = sum(1 for p in fp.pads if p.type != "np_thru_hole")
        self.npth_count = sum(1 for p in fp.pads if p.type == "np_thru_hole")
        # Assembly class: thermal/heatsink vias (pad_prop_heatsink, tiny
        # drills) don't make a package hand-solder-THT — only real solder
        # holes do.
        self.tht = any(p.type == "thru_hole" and not _is_heatsink_via(p)
                       for p in fp.pads)
        self.smd = any(p.type == "smd" for p in fp.pads)
        self.max_drill = max((p.drill.diameter for p in fp.pads
                              if p.drill is not None and p.drill.diameter), default=0.0)
        self.min_drill = min((p.drill.diameter for p in fp.pads
                              if p.drill is not None and p.drill.diameter), default=None)

        pad_pts = [pt for p in fp.pads for pt in _pad_corners(p)]
        self.pads_bbox = _bbox(pad_pts) if pad_pts else None

        crt_pts = [pt for g in fp.graphicItems
                   if getattr(g, "layer", "") in ("F.CrtYd", "B.CrtYd")
                   for pt in _graphic_points(g)]
        self.courtyard = _bbox(crt_pts) if crt_pts else None

        fab_pts = [pt for g in fp.graphicItems
                   if getattr(g, "layer", "") in ("F.Fab", "B.Fab")
                   for pt in _graphic_points(g)]
        self.fab_bbox = _bbox(fab_pts) if fab_pts else None

        boxes = [b for b in (self.pads_bbox, self.courtyard) if b]
        self.overall = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[2] for b in boxes), max(b[3] for b in boxes))

    @property
    def size(self):
        x0, y0, x1, y1 = self.overall
        return (x1 - x0, y1 - y0)

    def courtyard_size(self):
        if not self.courtyard:
            return None
        x0, y0, x1, y1 = self.courtyard
        return (x1 - x0, y1 - y0)


def parse_netlist_comps(net_path: Path):
    """(ref, value, footprint) triplets from an exported netlist —
    the same ground-truth source the CP2 exact-part gate reads."""
    net = Path(net_path).read_text(encoding="utf-8")
    pat = re.compile(
        r'\(comp\s*\(ref "([^"]+)"\)\s*\(value "([^"]+)"\)\s*\(footprint "([^"]+)"\)',
        re.S)
    comps = pat.findall(net)
    if not comps:
        raise SystemExit(f"[fplib] no components parsed from {net_path}")
    return comps


def main():
    net = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        KROOT / "schematic/build/volthium_reader.net"
    comps = parse_netlist_comps(net)
    byfp = {}
    for ref, val, fpid in comps:
        byfp.setdefault(fpid, []).append(ref)
    print(f"{len(comps)} components, {len(byfp)} unique footprints\n")
    rows = []
    for fpid, refs in sorted(byfp.items()):
        d = FpDims(fpid)
        cw = d.courtyard_size()
        rows.append((fpid, len(refs), d))
        kind = ("THT" if d.tht else "SMD") + ("+npth" if d.npth_count else "")
        print(f"{fpid:70s} x{len(refs):<3d} {kind:8s} "
              f"court {cw[0]:6.2f}x{cw[1]:6.2f}  " if cw else
              f"{fpid:70s} x{len(refs):<3d} {kind:8s} court   --  ",
              end="")
        print(f"overall {d.size[0]:6.2f}x{d.size[1]:6.2f}  pads {d.pad_count}"
              + (f"  drill<= {d.max_drill:.2f}" if d.max_drill else ""))
    nocrt = [fpid for fpid, n, d in rows if not d.courtyard]
    if nocrt:
        print(f"\nWARNING: no courtyard layer in: {nocrt}")
    # JLCPCB 2-layer fab floor: 0.3 mm min drill (cp1_battery_side §12)
    small = [(fpid, d.min_drill) for fpid, n, d in rows
             if d.min_drill is not None and d.min_drill < 0.3]
    if small:
        print("\nFAB-RULE: drills below JLCPCB 0.3 mm minimum "
              "(needs a project-local footprint variant):")
        for fpid, md in small:
            print(f"  {fpid}: min drill {md} mm")


if __name__ == "__main__":
    main()
