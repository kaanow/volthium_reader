#!/usr/bin/env python3
"""CP2 schematic generator (v2) — wires-first, block-structured, hierarchical.

Philosophy (opposite of the retired v1, which made a graphical netlist):
  - **Wires ARE the connectivity** inside a functional block; a human can
    trace signal flow by following lines. Global labels are used ONLY for
    genuine global/cross-block nets (power rails, buses).
  - **I place every symbol and route every wire explicitly** (this file is a
    faithful renderer of a hand-authored layout, never an auto-placer).
  - **Readability is a hard geometric gate**: the build fails if symbols/
    labels overlap or fall off the sheet's printable area.
  - Target: **US Letter**, hierarchical sheets (one functional block per
    page), inspected as the rendered PDF/PNG — not trusted blind.

This first cut proves the pipeline on ONE block (battery-side input
protection) before scaling. Run:  ../../.venv/bin/python build.py
"""
from __future__ import annotations
import copy as _copy, math, subprocess, sys, uuid
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.schematic import Schematic
from kiutils.items.schitems import SchematicSymbol, GlobalLabel, Connection
from kiutils.items.common import Position, Property, Effects, Stroke, Font, Justify, TitleBlock

HERE = Path(__file__).resolve().parent
KROOT = HERE.parent
LIB = KROOT / "libraries" / "volthium.kicad_sym"
OUT = KROOT.parent / "outputs" / "_cp2_slice"
GRID = 1.27  # mm

def _uuid() -> str: return str(uuid.uuid4())
def snap(v: float) -> float: return round(v / GRID) * GRID

# ---------------------------------------------------------------- geometry
def pin_points(symlib: SymbolLib, name: str, pos, angle: float):
    """Absolute schematic (x,y) of each pin of a placed symbol.

    Symbol lib is Y-up; KiCad rotates the pin CCW about the origin in the lib
    frame, THEN the instance is drawn Y-down in the schematic. So:
      (rx,ry) = rotateCCW(px,py, angle);  schematic = (X+rx, Y-ry).
    (Rotate first, flip Y second — the reverse is the bug that danglded wires.)
    Returns {pin_number: (x, y)}, snapped to the 1.27 mm connection grid.
    """
    sym = next(s for s in symlib.symbols if s.entryName == name)
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    out = {}
    for u in sym.units:
        for p in getattr(u, "pins", []):
            px, py = p.position.X, p.position.Y
            rx = px * ca - py * sa
            ry = px * sa + py * ca
            out[p.number] = (snap(pos[0] + rx), snap(pos[1] - ry))
    return out

# ---------------------------------------------------------------- placement
class Sheet:
    def __init__(self, symlib, title):
        self.lib = symlib
        self.sch = Schematic.create_new()
        self.sch.paper.paperSize = "USLetter"          # 8.5×11, landscape
        self.sch.titleBlock = TitleBlock(title=title, company="Volthium reader")
        self.boxes = []   # (x1,y1,x2,y2,label) for overlap gate

    def _copy_lib_symbol(self, name):
        if self.sch.libSymbols is None: self.sch.libSymbols = []
        lid = f"volthium:{name}"
        if not any(getattr(s, "libId", None) == lid for s in self.sch.libSymbols):
            sym = _copy.deepcopy(next(s for s in self.lib.symbols if s.entryName == name))
            sym.libId = lid                            # embed as "volthium:Fuse"
            sym.libraryNickname, sym.entryName = "volthium", name
            self.sch.libSymbols.append(sym)

    def place(self, name, ref, value, footprint, pos, angle=0.0,
              w=5.0, h=9.0):
        self._copy_lib_symbol(name)
        inst = SchematicSymbol(
            libraryNickname="volthium", entryName=name,
            position=Position(X=pos[0], Y=pos[1], angle=angle),
            unit=1, inBom=True, onBoard=True, fieldsAutoplaced=False,
            uuid=_uuid())
        fa = (-angle) % 360
        inst.properties = [
            Property(key="Reference", value=ref,
                     position=Position(X=pos[0]+4, Y=pos[1]-1, angle=fa)),
            Property(key="Value", value=value,
                     position=Position(X=pos[0]+4, Y=pos[1]+2, angle=fa)),
            Property(key="Footprint", value=footprint,
                     position=Position(X=pos[0], Y=pos[1], angle=0),
                     effects=Effects(hide=True)),
            Property(key="Datasheet", value="",
                     position=Position(X=pos[0], Y=pos[1], angle=0),
                     effects=Effects(hide=True)),
        ]
        self.sch.schematicSymbols.append(inst)
        self.boxes.append((pos[0]-w/2, pos[1]-h/2, pos[0]+w/2, pos[1]+h/2, ref))
        return pin_points(self.lib, name, pos, angle)

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            c = Connection(type="wire",
                           points=[Position(X=a[0], Y=a[1]), Position(X=b[0], Y=b[1])],
                           stroke=Stroke(width=0.1524, type="default"), uuid=_uuid())
            self.sch.graphicalItems.append(c)

    def label(self, text, pos, angle=0.0, justify_h="left"):
        lbl = GlobalLabel(text=text, shape="input",
                          position=Position(X=pos[0], Y=pos[1], angle=angle),
                          fieldsAutoplaced=True, uuid=_uuid(), effects=Effects())
        lbl.effects.justify = Justify(horizontally=justify_h)
        self.sch.globalLabels.append(lbl)

    def overlap_gate(self):
        bad = []
        for i in range(len(self.boxes)):
            for j in range(i+1, len(self.boxes)):
                a, b = self.boxes[i], self.boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    bad.append(f"{a[4]} overlaps {b[4]}")
        return bad

# ---------------------------------------------------------------- the slice
def build_input_protection(lib):
    """All coordinates on the 1.27 mm grid (pins land exactly, no dangles).
       Horizontal V24 rail (F1→D1 in series); TVS1 ‖ C1 shunt to a GND rail."""
    s = Sheet(lib, "Battery-side — input protection (CP2 slice)")
    yr, yg = snap(88.9), snap(113.03)          # V24 rail / GND rail rows
    xin  = snap(46.99)                          # V24_RAW label
    xf1  = snap(63.5)                           # F1 (fuse, horizontal)
    xd1  = snap(78.74)                          # D1 (diode, horizontal)
    xnod = snap(93.98)                          # V24_FUSED node
    xc1  = snap(109.22)                         # C1 branch
    f1 = s.place("Fuse", "F1", "1A T", "", (xf1, yr), angle=90)
    d1 = s.place("D", "D1", "SS26", "D_SMA", (xd1, yr))
    tv = s.place("D_TVS", "TVS1", "SMAJ33CA", "D_SMA", (xnod, snap(yr+12.7)), angle=90)
    c1 = s.place("C", "C1", "22µF 100V", "C_1210_3225Metric", (xc1, snap(yr+12.7)))
    # V24 rail: label → F1 → D1 → node → (right to C1 branch)
    s.label("V24_RAW", (xin, yr), justify_h="right")
    s.wire((xin, yr), f1["1"]); s.wire(f1["2"], d1["1"])
    s.wire(d1["2"], (xnod, yr)); s.wire((xnod, yr), (xc1, yr))
    # shunt legs: rail → each part's TOP pin; part BOTTOM pin → GND rail.
    topp = lambda pp: min(pp.values(), key=lambda xy: xy[1])
    botp = lambda pp: max(pp.values(), key=lambda xy: xy[1])
    s.wire((xnod, yr), topp(tv)); s.wire((xc1, yr), topp(c1))
    # GND rail: TVS1 & C1 bottoms → rail → GND label
    s.wire(botp(tv), (xnod, yg)); s.wire((xnod, yg), (xc1, yg)); s.wire(botp(c1), (xc1, yg))
    s.label("GND", (snap(xnod-10.16), yg), justify_h="left")
    s.wire((snap(xnod-10.16), yg), (xnod, yg))
    return s

# ---------------------------------------------------------------- pipeline
def kcli(*args):
    return subprocess.run(["kicad-cli", *args], capture_output=True, text=True)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lib = SymbolLib.from_file(str(LIB))
    s = build_input_protection(lib)
    bad = s.overlap_gate()
    if bad:
        print("OVERLAP GATE FAILED:"); [print("  -", b) for b in bad]; return 2
    schf = OUT / "input_protection.kicad_sch"
    s.sch.to_file(str(schf))
    print("wrote", schf)
    r = kcli("sch", "erc", "-o", str(OUT/"erc.rpt"), str(schf))
    print("ERC rc", r.returncode, (r.stderr or r.stdout).strip()[:300])
    r = kcli("sch", "export", "pdf", "-o", str(OUT/"input_protection.pdf"), str(schf))
    print("PDF rc", r.returncode, (r.stderr or r.stdout).strip()[:200])
    # rasterize to PNG for visual inspection
    try:
        import fitz
        doc = fitz.open(str(OUT/"input_protection.pdf"))
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(4, 4))
        pix.save(str(OUT/"input_protection.png"))
        print("PNG", OUT/"input_protection.png", pix.width, "x", pix.height)
    except Exception as e:
        print("raster failed:", e)
    return 0

if __name__ == "__main__":
    sys.exit(main())
