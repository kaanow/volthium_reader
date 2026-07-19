#!/usr/bin/env python3
"""CP2 schematic generator (v2) — wires-first, block-structured, hierarchical.

Philosophy (opposite of the retired v1 graphical netlist):
  - WIRES are the intra-block connectivity; global labels only for real
    global nets. Every symbol placed + every wire routed explicitly, on the
    1.27 mm grid. The code renders MY layout; it never auto-places.
  - Readability is a HARD geometric gate that sees TEXT and LABELS, not just
    symbol bodies (a symbol-only box check is blind to the two defects that
    actually ship: ref/value text over the symbol, and a net line piercing a
    label chevron). US Letter. Inspect the rendered PDF/PNG per-region.

First slice: battery-side input protection. Run: ../../.venv/bin/python build.py
"""
from __future__ import annotations
import copy as _copy, math, subprocess, sys, uuid
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.schematic import Schematic
from kiutils.items.schitems import (SchematicSymbol, GlobalLabel, Connection,
    SymbolProjectPath, SymbolProjectInstance)
from kiutils.items.common import Position, Property, Effects, Stroke, Justify, TitleBlock

PROJECT = "volthium_reader"

HERE = Path(__file__).resolve().parent
KROOT = HERE.parent
LIB = KROOT / "libraries" / "volthium.kicad_sym"
OUT = KROOT.parent / "outputs" / "_cp2_slice"
GRID = 1.27
CHARW = 0.85   # mm per char at 1.27 mm text height (approx, for box gate)
TXTH = 1.27

def _uuid(): return str(uuid.uuid4())
def snap(v): return round(v / GRID) * GRID
def _tw(s): return len(s) * CHARW + 0.4      # text width estimate

def pin_points(symlib, name, pos, angle):
    """Absolute (x,y) of each pin: rotateCCW(px,py,angle) then Y-flip.
       Verified against KiCad ERC (passives + diode connect at these)."""
    sym = next(s for s in symlib.symbols if s.entryName == name)
    a = math.radians(angle); ca, sa = math.cos(a), math.sin(a)
    out = {}
    for u in sym.units:
        for p in getattr(u, "pins", []):
            px, py = p.position.X, p.position.Y
            out[p.number] = (snap(pos[0] + px*ca - py*sa), snap(pos[1] - (px*sa + py*ca)))
    return out


class Sheet:
    def __init__(self, symlib, title):
        self.lib = symlib
        self.sch = Schematic.create_new()
        if not self.sch.uuid:
            self.sch.uuid = _uuid()          # root-sheet path for instances
        self.sch.paper.paperSize = "USLetter"
        self.sch.titleBlock = TitleBlock(title=title, company="Volthium reader")
        self.sym_boxes = []    # (x1,y1,x2,y2,ref)  symbol bodies
        self.txt_boxes = []    # (x1,y1,x2,y2,ref)  ref/value text
        self.lbl_boxes = []    # (x1,y1,x2,y2,text,anchor_xy)  label flag bodies
        self.wires = []        # ((x1,y1),(x2,y2))

    def _copy_lib_symbol(self, name):
        if self.sch.libSymbols is None: self.sch.libSymbols = []
        lid = f"volthium:{name}"
        if not any(getattr(s, "libId", None) == lid for s in self.sch.libSymbols):
            sym = _copy.deepcopy(next(s for s in self.lib.symbols if s.entryName == name))
            sym.libId = lid; sym.libraryNickname, sym.entryName = "volthium", name
            self.sch.libSymbols.append(sym)

    def place(self, name, ref, value, footprint, pos, angle=0.0,
              tanchor="r", bw=5.0, bh=8.0):
        """tanchor: 'ud' = ref above / value below (horizontal parts);
                    'r'  = ref+value stacked to the right (vertical parts)."""
        self._copy_lib_symbol(name)
        # ref/value anchors + boxes (left-justified so the box is predictable)
        if tanchor == "ud":
            rp = (snap(pos[0] - _tw(ref)/2), snap(pos[1] - (bh/2 + 1.9)))
            vp = (snap(pos[0] - _tw(value)/2), snap(pos[1] + (bh/2 + 1.9)))
        else:
            rp = (snap(pos[0] + bw/2 + 1.3), snap(pos[1] - 1.6))
            vp = (snap(pos[0] + bw/2 + 1.3), snap(pos[1] + 1.6))
        for txt, (tx, ty) in ((ref, rp), (value, vp)):
            self.txt_boxes.append((tx, ty-TXTH/2, tx+_tw(txt), ty+TXTH/2, f"{ref}:{txt}"))
        inst = SchematicSymbol(libraryNickname="volthium", entryName=name,
            position=Position(X=pos[0], Y=pos[1], angle=angle),
            unit=1, inBom=True, onBoard=True, fieldsAutoplaced=False, uuid=_uuid())
        le = lambda: Effects(justify=Justify(horizontally="left"))
        # Field angle to keep ref/value HORIZONTAL + upright regardless of the
        # symbol's rotation. KiCad's readable-text handling is non-obvious
        # (not a simple counter-rotate — 180° needs 0, not 180); values below
        # are empirically verified against the render.
        fa = {0: 0, 90: 270, 180: 0, 270: 90}[int(round(angle)) % 360]
        inst.properties = [
            Property(key="Reference", value=ref, position=Position(X=rp[0], Y=rp[1], angle=fa), effects=le()),
            Property(key="Value", value=value, position=Position(X=vp[0], Y=vp[1], angle=fa), effects=le()),
            Property(key="Footprint", value=footprint, position=Position(X=pos[0], Y=pos[1], angle=0), effects=Effects(hide=True)),
            Property(key="Datasheet", value="", position=Position(X=pos[0], Y=pos[1], angle=0), effects=Effects(hide=True)),
        ]
        # The (instances …) block is REQUIRED for pin-to-pin connectivity —
        # without it KiCad marks wires between two component pins dangling.
        inst.instances = [SymbolProjectInstance(name=PROJECT,
            paths=[SymbolProjectPath(sheetInstancePath="/" + self.sch.uuid,
                                     reference=ref, unit=1)])]
        self.sch.schematicSymbols.append(inst)
        self.sym_boxes.append((pos[0]-bw/2, pos[1]-bh/2, pos[0]+bw/2, pos[1]+bh/2, ref))
        return pin_points(self.lib, name, pos, angle)

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.sch.graphicalItems.append(Connection(type="wire",
                points=[Position(X=a[0], Y=a[1]), Position(X=b[0], Y=b[1])],
                stroke=Stroke(width=0.1524, type="default"), uuid=_uuid()))
            self.wires.append((tuple(a), tuple(b)))

    def add_junctions(self):
        """A tee of 3+ wires needs a junction dot or KiCad won't merge them
        (and marks the adjoining wires dangling). Place one wherever ≥3 wire
        endpoints coincide."""
        from kiutils.items.schitems import Junction
        from collections import Counter
        c = Counter()
        for a, b in self.wires:
            c[a] += 1; c[b] += 1
        for (x, y), n in c.items():
            if n >= 3:
                self.sch.junctions.append(Junction(position=Position(X=x, Y=y), uuid=_uuid()))

    def label(self, text, pos, justify_h="right"):
        """justify_h='right' → chevron on the right, flag body to the LEFT of
           the anchor (use when the wire exits to the right, so it can't pierce
           the body). 'left' → mirror. Records the flag body box for the gate."""
        lbl = GlobalLabel(text=text, shape="input",
            position=Position(X=pos[0], Y=pos[1], angle=0),
            fieldsAutoplaced=True, uuid=_uuid(), effects=Effects())
        lbl.effects.justify = Justify(horizontally=justify_h)
        self.sch.globalLabels.append(lbl)
        w = _tw(text) + 2.0                      # text + chevron
        if justify_h == "right":                 # body extends LEFT of anchor
            box = (pos[0]-w, pos[1]-1.1, pos[0]-0.4, pos[1]+1.1)
        else:                                    # body extends RIGHT of anchor
            box = (pos[0]+0.4, pos[1]-1.1, pos[0]+w, pos[1]+1.1)
        self.lbl_boxes.append((*box, text, tuple(pos)))

    # -------- readability gate (sees symbols, TEXT, and label-pierce) --------
    def gate(self):
        bad = []
        def ov(a, b):  # rectangle overlap (strict interiors)
            return a[0] < b[2]-1e-6 and b[0] < a[2]-1e-6 and a[1] < b[3]-1e-6 and b[1] < a[3]-1e-6
        allb = [("sym", x) for x in self.sym_boxes] + [("txt", x) for x in self.txt_boxes]
        for i in range(len(allb)):
            for j in range(i+1, len(allb)):
                (ka, a), (kb, b) = allb[i], allb[j]
                if ka == kb == "txt" and a[4].split(":")[0] == b[4].split(":")[0]:
                    continue  # a part's own ref vs its own value: allowed adjacent
                if ov(a, b):
                    bad.append(f"[overlap] {ka}:{a[4]} × {kb}:{b[4]}")
        # wire piercing a label flag body (crossing its interior, not just the anchor)
        for (lx1, ly1, lx2, ly2, text, anch) in self.lbl_boxes:
            for (p, q) in self.wires:
                if self._seg_crosses_box(p, q, (lx1, ly1, lx2, ly2), anch):
                    bad.append(f"[pierce] wire crosses label '{text}' body")
        return bad

    @staticmethod
    def _seg_crosses_box(p, q, box, anchor):
        x1, y1, x2, y2 = box
        # sample the segment; if an interior point (not near the anchor) is
        # inside the box, the wire pierces the flag body.
        for t in [i/20 for i in range(1, 20)]:
            x = p[0] + (q[0]-p[0])*t; y = p[1] + (q[1]-p[1])*t
            if x1+1e-6 < x < x2-1e-6 and y1+1e-6 < y < y2-1e-6:
                if math.hypot(x-anchor[0], y-anchor[1]) > 0.6:  # not the anchor itself
                    return True
        return False


def build_input_protection(lib):
    s = Sheet(lib, "Battery-side — input protection (CP2 slice)")
    yr, yg = snap(88.9), snap(113.03)
    xin, xf1, xd1, xnod, xc1 = map(snap, (46.99, 63.5, 78.74, 93.98, 109.22))
    # pin selectors by geometry (orientation-independent wiring)
    leftp  = lambda pp: min(pp.values(), key=lambda xy: xy[0])
    rightp = lambda pp: max(pp.values(), key=lambda xy: xy[0])
    topp   = lambda pp: min(pp.values(), key=lambda xy: xy[1])
    botp   = lambda pp: max(pp.values(), key=lambda xy: xy[1])
    f1 = s.place("Fuse", "F1", "1A T", "", (xf1, yr), angle=90, tanchor="ud")
    # D1 = SERIES reverse-polarity protector: anode toward the source
    # (V24_RAW), cathode toward the load — forward-biased in normal operation.
    # The `D` symbol is cathode(pin1)-left by default, so rotate 180°.
    d1 = s.place("D", "D1", "SS26", "D_SMA", (xd1, yr), angle=180, tanchor="ud")
    tv = s.place("D_TVS", "TVS1", "SMAJ33CA", "D_SMA", (xnod, snap(yr+12.7)), angle=90, tanchor="r")
    c1 = s.place("C", "C1", "22µF 100V", "C_1210_3225Metric", (xc1, snap(yr+12.7)), tanchor="r")
    s.label("V24_RAW", (xin, yr), justify_h="right")     # wire exits right
    s.wire((xin, yr), f1["1"]); s.wire(f1["2"], leftp(d1))       # F1 → D1 anode
    s.wire(rightp(d1), (xnod, yr)); s.wire((xnod, yr), (xc1, yr))  # D1 cathode → V24_FUSED
    s.wire((xnod, yr), topp(tv)); s.wire((xc1, yr), topp(c1))
    s.wire(botp(tv), (xnod, yg)); s.wire((xnod, yg), (xc1, yg)); s.wire(botp(c1), (xc1, yg))
    s.label("GND", (snap(xnod-10.16), yg), justify_h="right")  # wire exits right → body left
    s.wire((snap(xnod-10.16), yg), (xnod, yg))
    s.add_junctions()
    return s


def kcli(*a): return subprocess.run(["kicad-cli", *a], capture_output=True, text=True)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lib = SymbolLib.from_file(str(LIB))
    s = build_input_protection(lib)
    bad = s.gate()
    if bad:
        print("READABILITY GATE FAILED:"); [print("  "+b) for b in bad]; return 2
    print("readability gate: clean")
    schf = OUT / "input_protection.kicad_sch"; s.sch.to_file(str(schf))
    r = kcli("sch", "erc", "-o", str(OUT/"erc.rpt"), str(schf))
    nd = open(OUT/"erc.rpt").read().count("dangling") if (OUT/"erc.rpt").exists() else -1
    print(f"ERC rc {r.returncode}; dangling={nd}")
    kcli("sch", "export", "pdf", "-o", str(OUT/"input_protection.pdf"), str(schf))
    import fitz
    doc = fitz.open(str(OUT/"input_protection.pdf"))
    doc[0].get_pixmap(matrix=fitz.Matrix(6, 6)).save(str(OUT/"input_protection.png"))
    # per-region crop for high-zoom inspection (schematic mm → PDF pt ×2.8346)
    MM = 2.8346
    pg = doc[0]; clip = fitz.Rect(40*MM, 80*MM, 122*MM, 120*MM)
    pg.get_pixmap(matrix=fitz.Matrix(10, 10), clip=clip).save(str(OUT/"crop_circuit.png"))
    print("PNG + crop_circuit.png written")
    return 0

if __name__ == "__main__":
    sys.exit(main())
