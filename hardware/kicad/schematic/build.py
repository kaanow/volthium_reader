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
OUT = HERE / "build"            # generated schematics + review renders (gitignored)
GRID = 1.27
CHARW = 0.85   # mm per char at 1.27 mm text height (approx, for box gate)
TXTH = 1.27

# ---- symbol sourcing -------------------------------------------------------
# Every symbol is embedded self-contained under the "volthium:" nickname (so
# the .kicad_sch needs no external lib table). Sources: the project lib for
# custom/generic parts, KiCad's stock libs for the ICs. Derived (extends)
# stock symbols are FLATTENED to their pin-bearing ancestor on embed.
STOCK = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
SYMBOLS = {
    # name -> (lib file, entry name in that lib)
    # -- project lib (generic passives + custom parts) --
    "R":       (str(LIB), "R"),      "C":     (str(LIB), "C"),
    "L":       (str(LIB), "L"),      "Fuse":  (str(LIB), "Fuse"),
    "D":       (str(LIB), "D"),      "D_TVS": (str(LIB), "D_TVS"),
    "LED":     (str(LIB), "LED"),    "Polyfuse": (str(LIB), "Polyfuse"),
    # -- KiCad stock ICs (exact entry names verified 2026-07) --
    "LM5166Y":          (f"{STOCK}/Regulator_Switching.kicad_sym", "LM5166Y"),
    "THVD1400D":        (f"{STOCK}/Interface_UART.kicad_sym",      "THVD1400D"),
    "TPS3808DBV":       (f"{STOCK}/Power_Supervisor.kicad_sym",    "TPS3808DBV"),
    "RV-3028-C7":       (f"{STOCK}/Timer_RTC.kicad_sym",           "RV-3028-C7"),
    "TPS2116DRL":       (f"{STOCK}/Power_Management.kicad_sym",    "TPS2116DRL"),
    "R-78HB12-0.5":     (f"{STOCK}/Converter_DCDC.kicad_sym",      "R-78HB12-0.5"),
    "ESP32-S3-WROOM-1": (f"{STOCK}/RF_Module.kicad_sym",           "ESP32-S3-WROOM-1"),
}

def _uuid(): return str(uuid.uuid4())
def snap(v): return round(v / GRID) * GRID
def _tw(s): return len(s) * CHARW + 0.4      # text width estimate

_SYMCACHE = {}
def resolve_symbol(name):
    """Return a self-contained kiutils Symbol for `name`, flattened to its
    pin-bearing ancestor (KiCad's schematic cache stores flattened symbols,
    never `extends`). Embedded/looked-up under nickname 'volthium'."""
    if name in _SYMCACHE:
        return _SYMCACHE[name]
    if name not in SYMBOLS:
        raise KeyError(f"symbol {name!r} not in SYMBOLS registry")
    libfile, entry = SYMBOLS[name]
    sl = SymbolLib.from_file(libfile)
    byname = {s.entryName: s for s in sl.symbols}
    cur, base = entry, None
    while cur:                                  # walk `extends` to the pins
        s = byname[cur]
        if any(getattr(u, "pins", []) for u in s.units):
            base = s; break
        cur = getattr(s, "extends", None)
    if base is None:
        raise ValueError(f"{name}: no pin-bearing symbol in extends chain")
    top = byname[entry]
    flat = _copy.deepcopy(base)
    flat.entryName = name; flat.libId = f"volthium:{name}"
    flat.libraryNickname = "volthium"; flat.extends = None
    for u in flat.units:
        u.entryName = name                      # -> unit ids name_0_1 / name_1_1
    flat.properties = _copy.deepcopy(top.properties)  # keep ref prefix / value
    _SYMCACHE[name] = flat
    return flat

def _xf(px, py, pos, angle):
    """lib coords -> sheet: rotateCCW(angle) then Y-flip, snapped to grid."""
    a = math.radians(angle); ca, sa = math.cos(a), math.sin(a)
    return (snap(pos[0] + px*ca - py*sa), snap(pos[1] - (px*sa + py*ca)))

def pin_points(name, pos, angle):
    """Absolute (x,y) of each pin: rotateCCW(px,py,angle) then Y-flip.
       Verified against KiCad ERC (passives + diode connect at these)."""
    sym = resolve_symbol(name)
    out = {}
    for u in sym.units:
        for p in getattr(u, "pins", []):
            out[p.number] = _xf(p.position.X, p.position.Y, pos, angle)
    return out

def body_box(name, pos, angle, margin=0.8):
    """Real body rectangle (from the symbol's graphics, transformed), so the
    readability gate reasons about the actual drawn body, not a guessed box."""
    sym = resolve_symbol(name); xs = []; ys = []
    for u in sym.units:
        for g in getattr(u, "graphicItems", []):
            pts = []
            for attr in ("start", "end", "center"):
                v = getattr(g, attr, None)
                if v is not None: pts.append((v.X, v.Y))
            for p in (getattr(g, "points", None) or []): pts.append((p.X, p.Y))
            for px, py in pts:
                X, Y = _xf(px, py, pos, angle); xs.append(X); ys.append(Y)
    if not xs:
        return (pos[0]-1.27, pos[1]-1.27, pos[0]+1.27, pos[1]+1.27)
    return (min(xs)-margin, min(ys)-margin, max(xs)+margin, max(ys)+margin)


class Sheet:
    def __init__(self, title):
        self.sch = Schematic.create_new()
        if not self.sch.uuid:
            self.sch.uuid = _uuid()          # root-sheet path for instances
        self.sch.paper.paperSize = "USLetter"
        self.sch.titleBlock = TitleBlock(title=title, company="Volthium reader")
        self.sym_boxes = []    # (x1,y1,x2,y2,ref)  symbol bodies
        self.sym_pins = []     # (frozenset{(x,y)}, ref)  each part's own pins
        self.txt_boxes = []    # (x1,y1,x2,y2,ref)  ref/value text
        self.lbl_boxes = []    # (x1,y1,x2,y2,text,anchor_xy)  label flag bodies
        self.wires = []        # ((x1,y1),(x2,y2))

    def _copy_lib_symbol(self, name):
        if self.sch.libSymbols is None: self.sch.libSymbols = []
        lid = f"volthium:{name}"
        if not any(getattr(s, "libId", None) == lid for s in self.sch.libSymbols):
            self.sch.libSymbols.append(_copy.deepcopy(resolve_symbol(name)))

    def place(self, name, ref, value, footprint, pos, angle=0.0,
              tanchor="r", bw=None, bh=None, tgap=0.0):
        """tanchor picks where ref/value sit relative to the real body:
             'ud' ref above / value below   'u' both stacked above
             'l'  both to the left          'r' both to the right
           bw/bh default to the true body half-extents (from the graphics).
           tgap adds vertical clearance for 'u'/'ud' — use it when a top pin's
           wire would otherwise run up through the ref/value text."""
        self._copy_lib_symbol(name)
        box = body_box(name, pos, angle)
        hw = max(bw, box[2]-box[0]) / 2 if bw else (box[2]-box[0]) / 2
        hh = max(bh, box[3]-box[1]) / 2 if bh else (box[3]-box[1]) / 2
        # ref/value anchors + boxes (left-justified so the box is predictable)
        if tanchor == "ud":
            rp = (snap(pos[0] - _tw(ref)/2), snap(pos[1] - (hh + 1.9 + tgap)))
            vp = (snap(pos[0] - _tw(value)/2), snap(pos[1] + (hh + 1.9 + tgap)))
        elif tanchor == "u":                     # both above (ICs)
            rp = (snap(pos[0] - _tw(ref)/2), snap(pos[1] - (hh + 4.2 + tgap)))
            vp = (snap(pos[0] - _tw(value)/2), snap(pos[1] - (hh + 1.9 + tgap)))
        elif tanchor == "l":                     # text to the LEFT (right-edge aligned)
            rp = (snap(pos[0] - hw - 1.3 - _tw(ref)), snap(pos[1] - 1.6))
            vp = (snap(pos[0] - hw - 1.3 - _tw(value)), snap(pos[1] + 1.6))
        else:                                    # 'r' text to the RIGHT
            rp = (snap(pos[0] + hw + 1.3), snap(pos[1] - 1.6))
            vp = (snap(pos[0] + hw + 1.3), snap(pos[1] + 1.6))
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
        self.sym_boxes.append((box[0], box[1], box[2], box[3], ref))
        pins = pin_points(name, pos, angle)
        self.sym_pins.append((frozenset(pins.values()), ref))
        return pins

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.sch.graphicalItems.append(Connection(type="wire",
                points=[Position(X=a[0], Y=a[1]), Position(X=b[0], Y=b[1])],
                stroke=Stroke(width=0.1524, type="default"), uuid=_uuid()))
            self.wires.append((tuple(a), tuple(b)))

    def add_junctions(self):
        """Place a junction dot wherever wires must merge but wouldn't on their
        own: (1) 3+ wire endpoints coincide, and (2) a wire endpoint lands on
        the INTERIOR of another wire (a T-tap onto a rail) — the second case is
        the one that silently dangles if missed."""
        from kiutils.items.schitems import Junction
        from collections import Counter
        pts = set()
        c = Counter()
        for a, b in self.wires:
            c[a] += 1; c[b] += 1
        for p, n in c.items():
            if n >= 3: pts.add(p)
        ends = {p for seg in self.wires for p in seg}
        for p in ends:                              # endpoint interior to a segment?
            for a, b in self.wires:
                if p == a or p == b: continue
                if self._interior(p, a, b): pts.add(p); break
        for (x, y) in pts:
            self.sch.junctions.append(Junction(position=Position(X=x, Y=y), uuid=_uuid()))

    @staticmethod
    def _interior(p, a, b):
        (px, py), (ax, ay), (bx, by) = p, a, b
        if ax == bx == px and min(ay, by) < py < max(ay, by): return True   # vertical
        if ay == by == py and min(ax, bx) < px < max(ax, bx): return True   # horizontal
        # general collinear-interior (diagonal) — cross product 0 + within bbox
        if abs((bx-ax)*(py-ay) - (by-ay)*(px-ax)) < 1e-6:
            return min(ax, bx)-1e-6 < px < max(ax, bx)+1e-6 and \
                   min(ay, by)-1e-6 < py < max(ay, by)+1e-6 and (px, py) not in (a, b)
        return False

    def no_connect(self, pos):
        """Mark an intentionally-unused pin so ERC stays clean (open-drain
        PGOOD, unused HYS/SS, etc.). Without this KiCad reports 'pin not
        connected' — which would mask a real dangle."""
        from kiutils.schematic import Schematic as _S
        from kiutils.items.schitems import NoConnect
        self.sch.noConnects.append(NoConnect(position=Position(X=pos[0], Y=pos[1]), uuid=_uuid()))

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
        # wire routed THROUGH a symbol body it does NOT connect to — unreadable
        # on a dense IC sheet. A part's OWN axis/stub wires (endpoint == one of
        # its pins) legitimately enter the body region, so exclude those.
        pinsets = dict((r, ps) for ps, r in self.sym_pins)
        for (sx1, sy1, sx2, sy2, ref) in self.sym_boxes:
            inner = (sx1+0.6, sy1+0.6, sx2-0.6, sy2-0.6)
            own = pinsets.get(ref, frozenset())
            for (p, q) in self.wires:
                if tuple(p) in own or tuple(q) in own:
                    continue
                for t in [i/24 for i in range(1, 24)]:
                    x = p[0] + (q[0]-p[0])*t; y = p[1] + (q[1]-p[1])*t
                    if inner[0] < x < inner[2] and inner[1] < y < inner[3]:
                        bad.append(f"[through] wire crosses body of {ref}"); break
                else:
                    continue
                break
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


def build_input_protection():
    s = Sheet("Battery-side — input protection (CP2 slice)")
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


def build_always_on_power():
    """Always-on 3V3 rail: U1 LM5166Y (24V->3V3 sync buck, PFM, ultra-low Iq).
    Design verified against LM5166 datasheet (Design 3, 24V/3.3V PFM):
      EN->VIN direct tie (rec-op 65V >= 53.3V clamp; 'connect EN directly to
      VIN', p.21); RT->GND selects PFM (lowest light-load Iq); R_ILIM 56.2k =>
      750mA peak / 300mA IOUT (Table 3); SS/HYS/PGOOD open; L1 4.7uH Isat>=2.2A;
      C1 22uF/100V (Vin, behind clamp); C2 47uF/25V (Eq 31 margin). Net in:
      V24_FUSED; net out: V3V3 (always-on); GND."""
    s = Sheet("Battery-side — always-on 3V3 rail (U1 LM5166Y buck)")
    cx, cy = snap(152.4), snap(104.14)
    y_gnd = snap(118.11)
    u1 = s.place("LM5166Y", "U1", "LM5166YDRCR", "Package_SON:Texas_S-PVSON-N10_ThermalVias",
                 (cx, cy), angle=0, tanchor="u")
    VIN, EN, PGOOD, HYS = u1["2"], u1["7"], u1["6"], u1["9"]
    RT, SW, VOUT, SS, ILIM, GND = u1["5"], u1["1"], u1["8"], u1["4"], u1["3"], u1["10"]
    y_in = VIN[1]

    # ---- input: V24_FUSED rail -> VIN, with C1 tap to GND ----
    xlbl_in = snap(cx - 38.1)
    xc1 = snap(cx - 25.4)
    c1 = s.place("C", "C1", "22µF 100V", "C_1210_3225Metric",
                 (xc1, snap(y_in + 3.81)), angle=0, tanchor="l")   # top pin on the rail
    s.label("V24_FUSED", (xlbl_in, y_in), justify_h="right")
    s.wire((xlbl_in, y_in), c1["1"])                   # label -> C1 top (rail split at pin)
    s.wire(c1["1"], VIN)                               # C1 top -> VIN pin
    s.wire(c1["2"], (xc1, y_gnd))                      # C1 bottom -> GND rail

    # ---- EN tied directly to VIN (self-start whenever pack present) ----
    s.wire(EN, VIN)

    # ---- output: SW -> L1 -> VOUT node -> V3V3, C2 tap, VOUT sense ----
    xL = snap(cx + 12.7)
    l1 = s.place("L", "L1", "4.7µH", "L_1210_3225Metric",
                 (xL, y_in), angle=90, tanchor="ud", bw=7.62)
    lL = min(l1.values(), key=lambda p: p[0]); lR = max(l1.values(), key=lambda p: p[0])
    s.wire(SW, lL)
    xsense = snap(cx + 17.78)                          # VOUT-sense tap node on rail
    xc2 = snap(cx + 24.13)
    xlbl_out = snap(cx + 33.02)
    s.wire(lR, (xsense, y_in))                         # L1 -> sense node
    s.wire((xsense, y_in), (xc2, y_in))                # -> C2 tap
    s.wire((xc2, y_in), (xlbl_out, y_in))              # -> V3V3 label
    s.label("V3V3", (xlbl_out, y_in), justify_h="left")
    c2 = s.place("C", "C2", "47µF 25V", "C_1210_3225Metric",
                 (xc2, snap(y_in + 3.81)), angle=0, tanchor="r")
    s.wire(c2["2"], (xc2, y_gnd))                      # C2 bottom -> GND rail
    # fixed-3.3V feedback: VOUT pin senses the output node
    s.wire(VOUT, (xsense, VOUT[1])); s.wire((xsense, VOUT[1]), (xsense, y_in))

    # ---- RT -> GND (PFM), ILIM -> R_ILIM -> GND (offset right, clear of U1) ----
    s.wire(RT, (RT[0], y_gnd))
    xr = snap(ILIM[0] + 6.35)
    rilim = s.place("R", "R_ILIM", "56.2k", "R_0805_2012Metric",
                    (xr, snap(ILIM[1] + 3.81)), angle=0, tanchor="r")
    s.wire(ILIM, rilim["1"]); s.wire(rilim["2"], (xr, y_gnd))   # ILIM->R->GND

    # ---- GND rail across the bottom + label ----
    xg_l = snap(cx - 29.21)
    s.wire((xg_l, y_gnd), (xc2, y_gnd))
    s.wire(GND, (GND[0], y_gnd))                       # U1 GND drop
    s.label("GND", (xg_l, y_gnd), justify_h="right")

    # ---- intentionally-open pins ----
    for p in (PGOOD, HYS, SS):
        s.no_connect(p)
    s.add_junctions()
    return s


def build_rs485():
    """RS-485 half-duplex transceiver to the display side (U3 THVD1400, D34).
    Control (RO/nRE/DE/DI) -> MCU; differential A/B -> Cat5e, with the 120 Ohm
    terminator R10 and differential TVS2 across A-B; C10 decoupling. No idle
    bias (THVD1400 full fail-safe RX; DR-4b/F12). VCC = V3V3."""
    s = Sheet("Battery-side — RS-485 transceiver (U3 THVD1400)")
    cx, cy = snap(152.4), snap(104.14)
    u3 = s.place("THVD1400D", "U3", "THVD1400DR", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                 (cx, cy), angle=0, tanchor="u", tgap=5.08)
    RO, nRE, DE, DI = u3["1"], u3["2"], u3["3"], u3["4"]
    GND, A, B, VCC = u3["5"], u3["6"], u3["7"], u3["8"]

    # ---- control signals -> MCU (left) ----
    xlbl = snap(cx - 25.4)
    for pin, net in ((RO, "RS485_RO"), (nRE, "RS485_nRE"), (DE, "RS485_DE"), (DI, "RS485_DI")):
        s.label(net, (xlbl, pin[1]), justify_h="right")
        s.wire((xlbl, pin[1]), pin)

    # ---- VCC (top) -> V3V3 rail; C10 decoupling hangs off it, clear of the body ----
    yv = snap(VCC[1] - 3.81)                          # VCC rail just above the pin
    xc10 = snap(cx - 20.32)                           # left of the body (clear)
    xv3 = snap(cx - 27.94)
    s.wire(VCC, (VCC[0], yv))
    s.wire((VCC[0], yv), (xc10, yv)); s.wire((xc10, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="right")
    c10 = s.place("C", "C10", "100nF", "C_0603_1608Metric",
                  (xc10, snap(yv + 3.81)), angle=0, tanchor="l")   # top pin on VCC rail
    ygc = snap(c10["2"][1] + 2.54)
    s.wire(c10["2"], (xc10, ygc)); s.label("GND", (xc10, ygc), justify_h="right")

    # ---- GND (bottom) -> local GND ----
    ygp = snap(GND[1] + 2.54)
    s.wire(GND, (GND[0], ygp)); s.label("GND", (GND[0], ygp), justify_h="left")

    # ---- A/B bus (right): term R10 + TVS2 bridge A-B, then to Cat5e ----
    yA, yB = A[1], snap(A[1] + 7.62)                  # spread B down to a 7.62 bridge span
    xstep = snap(cx + 12.7)
    xbr1, xbr2, xlblB = snap(cx + 17.78), snap(cx + 30.48), snap(cx + 43.18)
    s.wire(A, (xbr1, yA))                             # A rail
    s.wire(B, (xstep, B[1]))                          # B out, then step down to yB
    s.wire((xstep, B[1]), (xstep, yB)); s.wire((xstep, yB), (xbr1, yB))
    ymid = snap((yA + yB) / 2)
    r10 = s.place("R", "R10", "120", "R_0805_2012Metric",
                  (xbr1, ymid), angle=0, tanchor="r", bw=2.0)
    tvs = s.place("D_TVS", "TVS2", "SMAJ12CA", "D_SMA", (xbr2, ymid), angle=90, tanchor="r")
    tvT = min(tvs.values(), key=lambda p: p[1]); tvB = max(tvs.values(), key=lambda p: p[1])
    s.wire((xbr1, yA), (xbr2, yA)); s.wire((xbr2, yA), (xlblB, yA))   # A -> label
    s.wire((xbr1, yB), (xbr2, yB)); s.wire((xbr2, yB), (xlblB, yB))   # B -> label
    s.wire((xbr2, yA), tvT); s.wire((xbr2, yB), tvB)                  # TVS2 across A-B
    s.label("RS485_A", (xlblB, yA), justify_h="left")
    s.label("RS485_B", (xlblB, yB), justify_h="left")

    s.add_junctions()
    return s


def kcli(*a): return subprocess.run(["kicad-cli", *a], capture_output=True, text=True)

MM = 2.8346   # schematic mm -> PDF points

def render(s, name, clip_mm):
    """gate -> ERC -> PDF -> full PNG + high-zoom crop. clip_mm=(x1,y1,x2,y2)."""
    bad = s.gate()
    if bad:
        print(f"[{name}] READABILITY GATE FAILED:"); [print("  "+b) for b in bad]
        return False
    print(f"[{name}] readability gate: clean")
    schf = OUT / f"{name}.kicad_sch"; s.sch.to_file(str(schf))
    kcli("sch", "erc", "-o", str(OUT/f"{name}.erc.rpt"), str(schf))
    rpt = open(OUT/f"{name}.erc.rpt").read() if (OUT/f"{name}.erc.rpt").exists() else ""
    # Classify ERC: real defects vs standalone-expected. power_pin_not_driven is
    # expected for a block whose supply/ground enter from an adjacent sheet
    # (a PWR_FLAG is added once at hierarchical assembly, not per block).
    real = [ln for ln in ("dangling", "pin_not_connected", "endpoint_off_grid",
                          "no_connect_connected") if ln in rpt]
    nd = rpt.count("dangling") + rpt.count("[pin_not_connected]")
    exp = rpt.count("power_pin_not_driven")
    print(f"[{name}] ERC real-defects={nd} (standalone-expected power-flag={exp})")
    if nd:
        for ln in rpt.splitlines():
            if any(k in ln for k in ("dangling", "pin_not_connected")): print("   "+ln.strip())
    kcli("sch", "export", "pdf", "-o", str(OUT/f"{name}.pdf"), str(schf))
    import fitz
    doc = fitz.open(str(OUT/f"{name}.pdf"))
    doc[0].get_pixmap(matrix=fitz.Matrix(6, 6)).save(str(OUT/f"{name}.png"))
    x1, y1, x2, y2 = clip_mm
    clip = fitz.Rect(x1*MM, y1*MM, x2*MM, y2*MM)
    doc[0].get_pixmap(matrix=fitz.Matrix(11, 11), clip=clip).save(str(OUT/f"{name}.crop.png"))
    print(f"[{name}] PNG + crop written")
    return nd == 0

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    ok &= render(build_input_protection(), "input_protection", (40, 80, 122, 120))
    ok &= render(build_always_on_power(), "always_on_power", (108, 82, 192, 126))
    ok &= render(build_rs485(), "rs485", (120, 82, 208, 126))
    return 0 if ok else 2

if __name__ == "__main__":
    sys.exit(main())
