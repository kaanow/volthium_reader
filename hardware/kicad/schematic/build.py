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
import copy as _copy, math, os, re, subprocess, sys, uuid
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.schematic import Schematic
from kiutils.items.schitems import (SchematicSymbol, GlobalLabel, Connection,
    SymbolProjectPath, SymbolProjectInstance, HierarchicalSheet,
    HierarchicalSheetInstance, HierarchicalSheetProjectInstance,
    HierarchicalSheetProjectPath)
from kiutils.items.common import Position, Property, Effects, Stroke, Justify, TitleBlock, Fill

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
    "AQY212EH": (str(LIB), "AQY212EH"),          # custom PhotoMOS SSR symbol
    "USB_C_16P": (str(LIB), "USB_C_16P"),        # custom USB-C (all pins one-per-row)
    "Q_PMOS_GSD": (str(LIB), "Q_PMOS_GSD"),      # NTR4171P (std SOT-23 GSD)
    # -- KiCad stock ICs (exact entry names verified 2026-07) --
    "LM5166Y":          (f"{STOCK}/Regulator_Switching.kicad_sym", "LM5166Y"),
    "THVD1400D":        (f"{STOCK}/Interface_UART.kicad_sym",      "THVD1400D"),
    "TPS3808DBV":       (f"{STOCK}/Power_Supervisor.kicad_sym",    "TPS3808DBV"),
    "RV-3028-C7":       (f"{STOCK}/Timer_RTC.kicad_sym",           "RV-3028-C7"),
    "TPS2116DRL":       (f"{STOCK}/Power_Management.kicad_sym",    "TPS2116DRL"),
    "R-78HB12-0.5":     (f"{STOCK}/Converter_DCDC.kicad_sym",      "R-78HB12-0.5"),
    "ESP32-S3-WROOM-1": (f"{STOCK}/RF_Module.kicad_sym",           "ESP32-S3-WROOM-1"),
    "AP2112K-3.3":      (f"{STOCK}/Regulator_Linear.kicad_sym",    "AP2112K-3.3"),
    "2N7002":           (f"{STOCK}/Transistor_FET.kicad_sym",      "2N7002"),
    "ADM2587E":         (f"{STOCK}/Interface_UART.kicad_sym",      "ADM2587E"),
    "SM712_SOT23":      (f"{STOCK}/Diode.kicad_sym",               "SM712_SOT23"),
    "FerriteBead":      (f"{STOCK}/Device.kicad_sym",              "FerriteBead"),
    "USBLC6-2SC6":      (f"{STOCK}/Power_Protection.kicad_sym",    "USBLC6-2SC6"),
    "Conn_01x04":       (f"{STOCK}/Connector_Generic.kicad_sym",   "Conn_01x04"),
    "Conn_01x02":       (f"{STOCK}/Connector_Generic.kicad_sym",   "Conn_01x02"),
    "Conn_01x08":       (f"{STOCK}/Connector_Generic.kicad_sym",   "Conn_01x08"),
    "RJ45_Shielded":    (f"{STOCK}/Connector.kicad_sym",           "RJ45_Shielded"),
    "SW_SPDT":          (f"{STOCK}/Switch.kicad_sym",              "SW_SPDT"),
    "USB_C_Receptacle_USB2.0_16P": (f"{STOCK}/Connector.kicad_sym", "USB_C_Receptacle_USB2.0_16P"),
    "PWR_FLAG":         (f"{STOCK}/power.kicad_sym",                "PWR_FLAG"),
}

def _uuid(): return str(uuid.uuid4())
def snap(v): return round(v / GRID) * GRID
def _tw(s): return len(s) * CHARW + 0.4      # text width estimate

_RAWHIDE_CACHE = {}
def _raw_pin_names_hidden(libfile, entry):
    """True if the RAW library marks `entry`'s pin names hidden — following the
    `extends` chain, since derived symbols inherit the parent's pin_names block.

    Why raw text: kiutils (KiCad-6 era) does not parse KiCad-10's NESTED
    `(pin_names (offset X) (hide yes))` — pinNamesHide stays False — so our
    flatten silently UN-hid names the library author explicitly hid. That was
    the root cause of the illegible USBLC6/SM712/Conn_01x0N bodies (DR-30) and
    of stray G/D/S / A/B/C letters on the FETs and BTN1."""
    key = (libfile, entry)
    if key in _RAWHIDE_CACHE:
        return _RAWHIDE_CACHE[key]
    txt = open(libfile, encoding="utf-8").read()
    cur = entry
    hidden = False
    for _ in range(6):                          # extends chains are short
        i = txt.find(f'(symbol "{cur}"')
        if i < 0: break
        head = txt[i:i + 400]                   # pin_names/extends live up top
        m = re.search(r'\(pin_names\s*(?:\(offset\s+[0-9.]+\)\s*)?(\(hide yes\))?\s*\)', head)
        if m:
            hidden = m.group(1) is not None
            break
        e = re.search(r'\(extends "([^"]+)"\)', head)
        if not e: break
        cur = e.group(1)
    _RAWHIDE_CACHE[key] = hidden
    return hidden


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
    # Stacked multi-pins (same net at one point) overprint their numbers
    # illegibly. Spread them out — the footprint maps by pin number, so pad
    # assignment is unaffected.
    allpins = [p for u in flat.units for p in getattr(u, "pins", [])]
    if name == "ESP32-S3-WROOM-1":
        gnd = sorted((p for p in allpins if p.number in ("1", "40", "41")), key=lambda p: int(p.number))
        for k, p in enumerate(gnd):
            p.position.X = (k - 1) * 5.08         # -5.08 / 0 / +5.08 along the bottom
    if name == "USB_C_Receptacle_USB2.0_16P":
        vbus = sorted((p for p in allpins if p.name == "VBUS"), key=lambda p: p.number)
        for k, p in enumerate(vbus):
            p.position.Y = 12.7 + k * 2.54        # 4 VBUS pins spread up the right edge
        gnd = sorted((p for p in allpins if p.name == "GND"), key=lambda p: p.number)
        for k, p in enumerate(gnd):
            p.position.X = -5.08 + k * 3.81       # 4 GND pins spread along the bottom (on-grid)
        for p in allpins:
            if p.name == "SHIELD": p.position.X = -12.7   # shield clear of the GND group
    if name == "LM5166Y":
        # stacked GND pin 10 + thermal pad pin 11 overprint their numbers
        # (caught by the glyph gate). Blocks must wire pin 11 explicitly.
        for p in allpins:
            if p.number == "11": p.position.X = 2.54
    if name == "TPS2116DRL":
        # stacked VOUT pins 2/7: the twin was no_connect'd ON the driven wire.
        # Spread pin 7 one grid below pin 2; blocks wire both to the output.
        for p in allpins:
            if p.number == "7": p.position.Y = 2.54
    # Restore the library author's pin-name visibility. kiutils drops KiCad-10's
    # nested `(hide yes)`, un-hiding names that were never meant to render (the
    # USBLC6/SM712/Conn_01x0N mush, stray G/D/S on FETs). Blanking to "~" is the
    # serialization-proof way to hide them: renders identically to stock KiCad,
    # and pin NUMBERS stay for the footprint map.
    if _raw_pin_names_hidden(libfile, entry):
        for p in allpins: p.name = "~"
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


# ---- symbol-OWN glyph modelling (pin names/numbers the symbol renders itself) ----
# The readability gate was structurally blind to this text: it modelled bodies,
# ref/value, labels and wires, but not the glyphs a symbol draws from its own
# definition — which is exactly what shipped three illegible symbols to the
# user's review (DR-30). These helpers give the gate that geometry.

_PIN_DIR = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}

def _xf_nosnap(px, py, pos, angle):
    """lib coords -> sheet, UNSNAPPED. Glyph/art boxes must not snap: TXTH/2 =
    0.635 is exactly half the 1.27 grid, so snapping collapses a text box to a
    degenerate line and shifts starts onto the outline (phantom flags)."""
    a = math.radians(angle); ca, sa = math.cos(a), math.sin(a)
    return (pos[0] + px*ca - py*sa, pos[1] - (px*sa + py*ca))

def _quad(pos, angle, corners):
    """lib-coord corner list -> sheet-coord axis-aligned bbox (unsnapped)."""
    pts = [_xf_nosnap(x, y, pos, angle) for x, y in corners]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))

def _twd(s):
    """display width: overline markup ~{...} renders as bare glyphs."""
    return _tw(re.sub(r"[~{}]", "", s))

def pin_glyph_boxes(name, pos, angle):
    """[(bbox, pin_number, kind, desc)] for every VISIBLE pin-name/number glyph.
    Geometry mirrors eeschema: offset>0 -> name runs inward from the pin's
    body-side end; offset==0 -> name rides alongside the stem (outside the
    body, opposite side from the number). Numbers ride ~1 mm off the stem."""
    sym = resolve_symbol(name)
    off = getattr(sym, "pinNamesOffset", None)
    off = 0.508 if off is None else off
    names_on = not getattr(sym, "pinNamesHide", False)
    nums_on = not getattr(sym, "hidePinNumbers", False)
    out = []
    for u in sym.units:
        for p in getattr(u, "pins", []):
            if getattr(p, "hide", False): continue
            d = _PIN_DIR[int(p.position.angle) % 360]
            nx, ny = -d[1], d[0]                      # stem-perpendicular
            ax, ay = p.position.X, p.position.Y       # connect point
            fx, fy = ax + p.length*d[0], ay + p.length*d[1]   # body-side end
            if names_on and p.name not in ("~", ""):
                w = _twd(p.name); h = TXTH/2
                if off > 0:      # name continues inward past the body edge
                    s0 = (fx + off*d[0], fy + off*d[1])
                else:            # offset 0: name above the stem, outside the body
                    m = (ax + p.length/2*d[0], ay + p.length/2*d[1])
                    s0 = (m[0] - w/2*d[0] + 1.0*nx, m[1] - w/2*d[1] + 1.0*ny)
                e0 = (s0[0] + w*d[0], s0[1] + w*d[1])
                out.append((_quad(pos, angle,
                                  [(s0[0]+nx*h, s0[1]+ny*h), (s0[0]-nx*h, s0[1]-ny*h),
                                   (e0[0]+nx*h, e0[1]+ny*h), (e0[0]-nx*h, e0[1]-ny*h)]),
                            p.number, "name", f"name'{p.name}'"))
            if nums_on and p.number:
                # KiCad offsets the number to one side of the stem; WHICH side
                # follows conventions not worth mis-modelling. Centre it ON the
                # stem midpoint instead — slightly conservative both ways, still
                # catches stacked-number overprint and number-vs-text collisions.
                w = _twd(p.number); h = TXTH/2
                c = (ax + p.length/2*d[0], ay + p.length/2*d[1])
                s0 = (c[0] - w/2*d[0], c[1] - w/2*d[1]); e0 = (c[0] + w/2*d[0], c[1] + w/2*d[1])
                out.append((_quad(pos, angle,
                                  [(s0[0]+nx*h, s0[1]+ny*h), (s0[0]-nx*h, s0[1]-ny*h),
                                   (e0[0]+nx*h, e0[1]+ny*h), (e0[0]-nx*h, e0[1]-ny*h)]),
                            p.number, "num", f"num{p.number}"))
    return out

def art_boxes(name, pos, angle):
    """(solids, outline_edges) in sheet coords — the same-symbol collision
    targets for glyphs. Non-rectangle graphics (diode/FET art, internal text)
    are solid bboxes; large rectangles are treated as hollow OUTLINES (a glyph
    fully inside an IC body is normal — straddling an edge is the defect), and
    small rectangles (connector pad stubs, internal detail) as solid."""
    sym = resolve_symbol(name)
    solids, edges = [], []
    T = 0.2                                        # edge-band half-thickness
    for u in sym.units:
        for g in getattr(u, "graphicItems", []):
            cls = type(g).__name__.lower()
            if "rect" in cls:
                x1, y1, x2, y2 = _quad(pos, angle,
                    [(g.start.X, g.start.Y), (g.end.X, g.start.Y),
                     (g.end.X, g.end.Y), (g.start.X, g.end.Y)])
                if (x2-x1) < 3.2 or (y2-y1) < 3.2:
                    solids.append((x1, y1, x2, y2))
                else:
                    edges += [(x1-T, y1-T, x2+T, y1+T), (x1-T, y2-T, x2+T, y2+T),
                              (x1-T, y1-T, x1+T, y2+T), (x2-T, y1-T, x2+T, y2+T)]
                continue
            if "circle" in cls:
                c, r = g.center, g.radius
                solids.append(_quad(pos, angle,
                    [(c.X-r, c.Y-r), (c.X+r, c.Y+r)]))
                continue
            if "text" in cls:
                v = getattr(g, "position", None)
                if v is not None:
                    t = getattr(g, "text", "") or ""
                    fh = TXTH          # internal art text often uses a smaller
                    try:               # font (ADM's ISOLATED DC-DC is 1.0 mm) —
                        fh = g.effects.font.height or TXTH   # scale by its real
                    except Exception:  # size or the box overhangs into pin names
                        pass
                    w = _tw(t) * (fh / TXTH)
                    solids.append(_quad(pos, angle,
                        [(v.X-w/2, v.Y-fh/2), (v.X+w/2, v.Y+fh/2)]))
                continue
            pts = []
            for attr in ("start", "mid", "end"):
                v = getattr(g, attr, None)
                if v is not None: pts.append((v.X, v.Y))
            for pt in (getattr(g, "points", None) or []): pts.append((pt.X, pt.Y))
            if pts:
                solids.append(_quad(pos, angle, pts))
    return solids, edges


_FP_DIRS = ["/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"]
_FP_SEEN = set()
_FP_BARE_PREFIX = (("R_", "Resistor_SMD"), ("C_", "Capacitor_SMD"),
                   ("L_", "Inductor_SMD"), ("D_", "Diode_SMD"))
def _normalize_footprint(fp):
    """Bare footprint names ('D_SMA', 'C_1210_3225Metric') don't resolve at
    PCB-update time — KiCad needs 'Lib:Name'. Prefix the standard SMD libs;
    anything else bare is an error (caught here, at CP2, not at CP3 layout)."""
    if not fp or ":" in fp: return fp
    for pre, lib in _FP_BARE_PREFIX:
        if fp.startswith(pre):
            return f"{lib}:{fp}"
    raise SystemExit(f"[footprint-gate] bare footprint {fp!r}: no known library prefix")
def _assert_footprint_exists(fp):
    """Hard build gate: a footprint string that doesn't resolve to a real
    .kicad_mod file kills the build. Added after 'footprint-existence: clean'
    was asserted while 4 phantoms shipped (DR-30): U6 nonexistent SOT-563,
    J1 name typo, RTC1 invented name, BTN1 fictional library. Enforcing at
    place() makes the check impossible to skip. Extend _FP_DIRS if a repo-local
    .pretty library is ever added."""
    if fp in _FP_SEEN: return
    lib, name = fp.split(":", 1)
    if not any(os.path.exists(f"{d}/{lib}.pretty/{name}.kicad_mod") for d in _FP_DIRS):
        raise SystemExit(f"[footprint-gate] {fp}: no {lib}.pretty/{name}.kicad_mod in {_FP_DIRS}")
    _FP_SEEN.add(fp)


class Sheet:
    def __init__(self, title, hier_uuid=None):
        self.sch = Schematic.create_new()
        if not self.sch.uuid:
            self.sch.uuid = _uuid()          # this sheet's own uuid
        # instance path: standalone = "/<own uuid>"; as a hierarchy child =
        # "/<sheet-symbol uuid in the root>" (KiCad's per-instance path).
        self.hier = hier_uuid or self.sch.uuid
        self.sch.paper.paperSize = "USLetter"
        self.sch.titleBlock = TitleBlock(title=title, company="Volthium reader")
        self.sym_boxes = []    # (x1,y1,x2,y2,ref)  symbol bodies
        self.sym_pins = []     # (frozenset{(x,y)}, ref)  each part's own pins
        self.txt_boxes = []    # (x1,y1,x2,y2,ref)  ref/value text
        self.lbl_boxes = []    # (x1,y1,x2,y2,text,anchor_xy)  label flag bodies
        self.wires = []        # ((x1,y1),(x2,y2))
        self.glyph_items = []  # (ref, [(bbox,pin,kind,desc)])  symbol-own pin glyphs
        self.art_items = {}    # ref -> (solid_boxes, outline_edge_bands)

    def _copy_lib_symbol(self, name):
        if self.sch.libSymbols is None: self.sch.libSymbols = []
        lid = f"volthium:{name}"
        if not any(getattr(s, "libId", None) == lid for s in self.sch.libSymbols):
            self.sch.libSymbols.append(_copy.deepcopy(resolve_symbol(name)))

    def place(self, name, ref, value, footprint, pos, angle=0.0,
              tanchor="r", bw=None, bh=None, tgap=0.0, dnp=False):
        """tanchor picks where ref/value sit relative to the real body:
             'ud' ref above / value below   'u' both stacked above
             'l'  both to the left          'r' both to the right
           bw/bh default to the true body half-extents (from the graphics).
           tgap adds vertical clearance for 'u'/'ud' — use it when a top pin's
           wire would otherwise run up through the ref/value text."""
        self._copy_lib_symbol(name)
        footprint = _normalize_footprint(footprint)
        if footprint:
            _assert_footprint_exists(footprint)
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
        elif tanchor == "d":                     # both below (small caps in tight spots)
            rp = (snap(pos[0] - _tw(ref)/2), snap(pos[1] + (hh + 1.9)))
            vp = (snap(pos[0] - _tw(value)/2), snap(pos[1] + (hh + 4.2)))
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
            unit=1, inBom=True, onBoard=True, dnp=(True if dnp else None),
            fieldsAutoplaced=False, uuid=_uuid())
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
            paths=[SymbolProjectPath(sheetInstancePath="/" + self.hier,
                                     reference=ref, unit=1)])]
        self.sch.schematicSymbols.append(inst)
        self.sym_boxes.append((box[0], box[1], box[2], box[3], ref))
        pins = pin_points(name, pos, angle)
        self.sym_pins.append((frozenset(pins.values()), ref))
        self.glyph_items.append((ref, pin_glyph_boxes(name, pos, angle)))
        self.art_items[ref] = art_boxes(name, pos, angle)
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
        # annotation symbols (PWR_FLAG etc., ref "#…") carry auto-refs over tiny
        # bodies — not a readability concern; skip them.
        def anon(box): return box[4].split(":")[0].startswith("#")
        allb = [("sym", x) for x in self.sym_boxes if not anon(x)] + \
               [("txt", x) for x in self.txt_boxes if not anon(x)]
        for i in range(len(allb)):
            for j in range(i+1, len(allb)):
                (ka, a), (kb, b) = allb[i], allb[j]
                if ka == kb == "txt" and a[4].split(":")[0] == b[4].split(":")[0]:
                    continue  # a part's own ref vs its own value: allowed adjacent
                if ov(a, b):
                    bad.append(f"[overlap] {ka}:{a[4]} × {kb}:{b[4]}")
        # a label flag body overlapping a symbol body or ref/value text — the
        # defect that slips past a pierce-only check (e.g. a decoupling cap's GND
        # label printed over an IC's pins).
        for i, (lx1, ly1, lx2, ly2, text, anch) in enumerate(self.lbl_boxes):
            lb = (lx1, ly1, lx2, ly2)
            for (sx1, sy1, sx2, sy2, ref) in self.sym_boxes:
                if ov(lb, (sx1, sy1, sx2, sy2)):
                    bad.append(f"[label-overlap] label '{text}' × body {ref}")
            for (tx1, ty1, tx2, ty2, tref) in self.txt_boxes:
                if tref.split(":")[0].startswith("#"): continue   # annotation symbol text
                if ov(lb, (tx1, ty1, tx2, ty2)):
                    bad.append(f"[label-overlap] label '{text}' × text {tref}")
            for j in range(i+1, len(self.lbl_boxes)):
                ob = self.lbl_boxes[j]
                if ov(lb, (ob[0], ob[1], ob[2], ob[3])):
                    bad.append(f"[label-overlap] label '{text}' × label '{ob[4]}'")
        # wire piercing a label flag body (crossing its interior, not just the anchor)
        for (lx1, ly1, lx2, ly2, text, anch) in self.lbl_boxes:
            for (p, q) in self.wires:
                if self._seg_crosses_box(p, q, (lx1, ly1, lx2, ly2), anch):
                    bad.append(f"[pierce] wire crosses label '{text}' body")
        # -------- symbol-OWN glyphs (pin names/numbers) --------
        # The gate used to be blind to text a symbol renders from its own
        # definition; that blindness shipped three illegible symbols to the
        # user's review (DR-30). Collide the modelled glyph boxes against
        # same-symbol art, outline edges, ref/value text, labels, and each
        # other. Thresholds are penetration depths (mm), calibrated so the
        # eye-verified-clean build passes and an un-hidden SM712 fails
        # (regression: comment out the _raw_pin_names_hidden blanking).
        def pen(a, b, t):
            return (min(a[2], b[2]) - max(a[0], b[0]) > t and
                    min(a[3], b[3]) - max(a[1], b[1]) > t)
        for ref, glyphs in self.glyph_items:
            if ref.startswith("#"): continue
            solids, edges = self.art_items.get(ref, ([], []))
            for (gb, pnum, kind, desc) in glyphs:
                if any(pen(gb, sb, 0.4) for sb in solids):
                    bad.append(f"[glyph-art] {ref} {desc} over body art")
                if kind == "name" and any(pen(gb, eb, 0.15) for eb in edges):
                    bad.append(f"[glyph-edge] {ref} {desc} straddles outline")
                for (tx1, ty1, tx2, ty2, tref) in self.txt_boxes:
                    if tref.split(":")[0].startswith("#"): continue
                    if pen(gb, (tx1, ty1, tx2, ty2), 0.3):
                        bad.append(f"[glyph-text] {ref} {desc} × text {tref}")
                for (lx1, ly1, lx2, ly2, ltext, anch) in self.lbl_boxes:
                    if pen(gb, (lx1, ly1, lx2, ly2), 0.3):
                        bad.append(f"[glyph-label] {ref} {desc} × label '{ltext}'")
        # glyph × glyph — also catches stacked-pin number overprint (the
        # ESP32/USB-C class that's currently handled by spreading in
        # resolve_symbol; this makes the gate enforce it).
        flat_g = [(r, g) for r, gs in self.glyph_items if not r.startswith("#")
                  for g in gs]
        for i in range(len(flat_g)):
            for j in range(i+1, len(flat_g)):
                (ra, (ba_, pa, ka, da)), (rb, (bb_, pb, kb, db)) = flat_g[i], flat_g[j]
                if ra == rb and pa == pb: continue     # a pin's own name+number
                if pen(ba_, bb_, 0.3):
                    bad.append(f"[glyph-glyph] {ra} {da} × {rb} {db}")
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


def blk_pwr_flags(s, cx, cy):
    """PWR_FLAGs: tell ERC these nets ARE driven, even though their local source
    is passive (V24_FUSED past D1, V24_SW past the SSR) or a board-input
    connector (VBUS from USB-C), plus the global GND reference."""
    for i, net in enumerate(("V24_FUSED", "V24_SW", "VBUS", "GND")):
        x = snap(cx + i*17.78)
        pf = s.place("PWR_FLAG", f"#FLG{i+1}", "PWR_FLAG", "", (x, cy), angle=0, tanchor="ud")
        pin = pf["1"]
        s.wire(pin, (pin[0], snap(pin[1] + 5.08)))
        s.label(net, (pin[0], snap(pin[1] + 5.08)), justify_h="left")


def blk_input_protection(s, cx, cy):
    """V24_RAW (from J1) -> F1 (1A T) -> D1 (SS26 reverse-polarity) -> V24_FUSED;
    TVS1 (SMAJ33CA) clamp to GND. The input-bulk/buck-input cap is C1 in the
    buck block (same V24_FUSED net). Translated onto (cx,cy) = block centre."""
    ox, oy = cx - snap(78.1), cy - snap(100.97)      # translate the validated layout
    yr, yg = snap(88.9 + oy), snap(113.03 + oy)
    xin, xf1, xd1, xnod, xout = [snap(v + ox) for v in (46.99, 63.5, 78.74, 93.98, 111.76)]
    leftp  = lambda pp: min(pp.values(), key=lambda xy: xy[0])
    rightp = lambda pp: max(pp.values(), key=lambda xy: xy[0])
    topp   = lambda pp: min(pp.values(), key=lambda xy: xy[1])
    botp   = lambda pp: max(pp.values(), key=lambda xy: xy[1])
    # F1 = 5x20 cartridge (0215001.MXP) in Keystone 3517 clips — the clip
    # footprint IS the PCB land (BOM row F1).
    f1 = s.place("Fuse", "F1", "1A T",
                 "Fuse:Fuseholder_Clip-5x20mm_Keystone_3517_Inline_P23.11x6.76mm_D1.70mm_Horizontal",
                 (xf1, yr), angle=90, tanchor="ud")
    # D1 = SERIES reverse-polarity protector: anode toward the source (V24_RAW),
    # cathode toward the load. The `D` symbol is cathode(pin1)-left, so rotate 180°.
    d1 = s.place("D", "D1", "SS26", "D_SMA", (xd1, yr), angle=180, tanchor="ud")
    tv = s.place("D_TVS", "TVS1", "SMAJ33CA", "D_SMA", (xnod, snap(yr+12.7)), angle=90, tanchor="r")
    s.label("V24_RAW", (xin, yr), justify_h="right")     # input from J1
    s.wire((xin, yr), f1["1"]); s.wire(f1["2"], leftp(d1))       # F1 → D1 anode
    s.wire(rightp(d1), (xnod, yr))                                # D1 cathode = V24_FUSED node
    s.wire((xnod, yr), (xout, yr)); s.label("V24_FUSED", (xout, yr), justify_h="left")  # output
    s.wire((xnod, yr), topp(tv)); s.wire(botp(tv), (xnod, yg))    # TVS1 clamp to GND
    s.label("GND", (snap(xnod-10.16), yg), justify_h="right")
    s.wire((snap(xnod-10.16), yg), (xnod, yg))


def blk_always_on_power(s, cx, cy):
    """Always-on 3V3 rail: U1 LM5166Y (24V->3V3 sync buck, PFM, ultra-low Iq).
    Design verified against LM5166 datasheet (Design 3, 24V/3.3V PFM):
      EN->VIN direct tie (rec-op 65V >= 53.3V clamp; 'connect EN directly to
      VIN', p.21); RT->GND selects PFM (lowest light-load Iq); R_ILIM 56.2k =>
      750mA peak / 300mA IOUT (Table 3); SS/HYS/PGOOD open; L1 4.7uH Isat>=2.2A;
      C1 22uF/100V (Vin, behind clamp); C2 47uF/25V (Eq 31 margin). Net in:
      V24_FUSED; net out: V3V3_BUCK (-> USB mux U6 VIN2); GND. (cx,cy)=U1."""
    y_gnd = snap(cy + 13.97)
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
    s.wire((xc2, y_in), (xlbl_out, y_in))              # -> V3V3_BUCK (into the USB mux U6 VIN2)
    s.label("V3V3_BUCK", (xlbl_out, y_in), justify_h="left")
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
    s.wire(u1["11"], (u1["11"][0], y_gnd))             # thermal pad (pin 11) drop
    s.label("GND", (xg_l, y_gnd), justify_h="right")

    # ---- intentionally-open pins ----
    for p in (PGOOD, HYS, SS):
        s.no_connect(p)


def blk_rs485(s, cx, cy):
    """RS-485 half-duplex transceiver to the display side (U3 THVD1400, D34).
    Control (RO/nRE/DE/DI) -> MCU; differential A/B -> Cat5e, with the 120 Ohm
    terminator R10 and differential TVS2 across A-B; C10 decoupling. No idle
    bias (THVD1400 full fail-safe RX; DR-4b/F12). VCC = V3V3. (cx,cy)=U3 centre."""
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

    # ---- A/B bus (right): term (R10 in series with J4 term-lift jumper) + TVS2
    #      bridge A-B, then to Cat5e. J4 open = 120R termination lifted. ----
    yA, yB = A[1], snap(A[1] + 15.24)                 # wide bridge for R10 + J4 in series
    xstep = snap(cx + 12.7)
    xbr1, xbr2, xlblB = snap(cx + 17.78), snap(cx + 33.02), snap(cx + 45.72)
    s.wire(A, (xbr1, yA))                             # A rail
    s.wire(B, (xstep, B[1]))                          # B out, then step down to yB
    s.wire((xstep, B[1]), (xstep, yB)); s.wire((xstep, yB), (xbr1, yB))
    nT = snap(yA + 7.62)                              # R10 <-> J4 term node
    r10 = s.place("R", "R10", "120", "R_0805_2012Metric",
                  (xbr1, snap(yA + 3.81)), angle=0, tanchor="r", bw=2.0)   # top=yA rail, bot=nT
    j4 = s.place("Conn_01x02", "J4", "TERM",
                 "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                 (snap(xbr1 + 5.08), snap(yA + 10.16)), angle=0, tanchor="r")
    j4t = min(j4.values(), key=lambda p: p[1]); j4b = max(j4.values(), key=lambda p: p[1])
    s.wire((xbr1, nT), j4t); s.wire(j4b, (xbr1, yB))             # R10 bot -> J4 -> B rail
    tvs = s.place("D_TVS", "TVS2", "SMAJ12CA", "D_SMA", (xbr2, snap((yA + yB) / 2)), angle=90, tanchor="r")
    tvT = min(tvs.values(), key=lambda p: p[1]); tvB = max(tvs.values(), key=lambda p: p[1])
    s.wire((xbr1, yA), (xbr2, yA)); s.wire((xbr2, yA), (xlblB, yA))   # A -> label
    s.wire((xbr1, yB), (xbr2, yB)); s.wire((xbr2, yB), (xlblB, yB))   # B -> label
    s.wire((xbr2, yA), tvT); s.wire((xbr2, yB), tvB)                  # TVS2 across A-B
    s.label("RS485_A", (xlblB, yA), justify_h="left")
    s.label("RS485_B", (xlblB, yB), justify_h="left")


def blk_iso_ch(s, cx, cy, n):
    """Isolated RS-485 battery-read channel n (D36/DR-26) — one channel per sheet.
    U_iso ADM2587E = isolated transceiver + integrated isoPower. VCC power-gated
    by Q_ls (NTR4171P P-FET, gate=CHn_PWR active-LOW + 100k pull-up to 3V3 =
    default-OFF). isoPower per Rev H Fig 35 / p.17: L1 in the VISOOUT->VISOIN
    line; the four GND2 pins are NOT one net — 11/14 = GND2_DCDC{n} (converter,
    device side of L2), 16/20 = ISO_BUS_GND{n} (bus side); L2 is the ONLY tie;
    C_stitch (HV Y-cap) is the only GND1<->GND2_DCDC bridge. Bus A+Y / B+Z ->
    J_bat RJ45 pins 7/8. TVS(SM712)+R_ser+R_bias+term+REF are DNP provisioning
    (F36/F44: intentionally unprotected short in-box link). Both isolated grounds
    are per-channel-unique nets so the two packs never share a floating ground.
    Dense isoPower network -> connected by short labelled stubs (wires here would
    be excessive clutter); (cx,cy) = U_iso centre."""
    dnp = True
    # short conventional refdes (per-channel bands: ch1 20s, ch2 30s) — keeps the
    # dense network readable; functional names live in the spec + net labels.
    U, Q, Dt, Jr = f"U{9+n}", f"Q{9+n}", f"D{9+n}", f"J{9+n}"    # ch1->U10.. ch2->U11..
    La, Lb = f"L{8+2*n}", f"L{9+2*n}"                            # ch1->L10/L11 ch2->L12/L13
    rb = 20 + (n-1)*10; cb = 20 + (n-1)*10                       # R/C bands
    u = s.place("ADM2587E", U, "ADM2587EBRWZ", "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
                (cx, cy), angle=0, tanchor="u", tgap=8.0)
    VCC, GDC, GBUS = f"VCC{n}", f"GND2_DCDC{n}", f"ISO_BUS_GND{n}"
    VOUT, VIN, BA, BB = f"V_ISOOUT{n}", f"V_ISOIN{n}", f"BUS_A{n}", f"BUS_B{n}"

    def stub(pin, net, dx, dy=0.0):
        """route a pin out by (dx,dy) to a global label; horizontal exit."""
        end = (snap(pin[0] + dx), snap(pin[1] + dy))
        if dy: s.wire(pin, (pin[0], end[1]), end)
        else:  s.wire(pin, end)
        s.label(net, end, justify_h=("right" if dx < 0 else "left"))

    def hpart(name, ref, val, fp, x, y, netL, netR, _dnp=False):
        """2-terminal part placed horizontal; each pin -> a labelled stub."""
        p = s.place(name, ref, val, fp, (x, y), angle=90, tanchor="ud", bw=7.62, dnp=_dnp)
        L = min(p.values(), key=lambda q: q[0]); R = max(p.values(), key=lambda q: q[0])
        s.wire(L, (snap(L[0] - 3.81), y)); s.label(netL, (snap(L[0] - 3.81), y), justify_h="right")
        s.wire(R, (snap(R[0] + 3.81), y)); s.label(netR, (snap(R[0] + 3.81), y), justify_h="left")
        return p

    def bank(items, x0, ytop, ybot, netTop, netBot, pitch=15.24):
        """Cap/part bank: vertical parts in a row between a top rail (netTop) and
        bottom rail (netBot). One label per rail (not per part) -> compact +
        readable for shared-net decoupling groups. Text left of each part."""
        ymid = snap((ytop + ybot) / 2)
        xs = [snap(x0 + i * pitch) for i in range(len(items))]
        for (name, ref, val, fp, d), x in zip(items, xs):
            p = s.place(name, ref, val, fp, (x, ymid), angle=0, tanchor="l", dnp=d)
            top = min(p.values(), key=lambda q: q[1]); bot = max(p.values(), key=lambda q: q[1])
            s.wire(top, (x, ytop)); s.wire(bot, (x, ybot))
        s.wire((snap(x0 - 3.81), ytop), (xs[-1], ytop))
        s.wire((snap(x0 - 3.81), ybot), (xs[-1], ybot))
        s.label(netTop, (snap(x0 - 3.81), ytop), justify_h="right")
        s.label(netBot, (snap(x0 - 3.81), ybot), justify_h="right")

    # ---- ADM2587E pin stubs ------------------------------------------------
    # logic side (left): VCC (2/8 joined), control, GND1 (1/3/9/10 joined)
    s.wire(u["2"], u["8"])                                       # VCC2 & VCC8 (same x)
    stub(u["8"], VCC, -6.35)
    stub(u["4"], f"RS485B_RO{n}", -6.35)                         # RxD
    stub(u["5"], "GND", -6.35)                                   # /RE tied low
    stub(u["6"], f"RS485B_DE{n}", -6.35)                         # DE
    stub(u["7"], f"TXD{n}", -6.35)                               # TxD -> local net (R_di below)
    s.wire(u["1"], u["3"]); s.wire(u["3"], u["9"]); s.wire(u["9"], u["10"])  # GND1 rail
    stub(u["10"], "GND", -6.35)
    # isolated side (right): VISO, bus (A+Y / B+Z), GND2 split (11/14 vs 16/20)
    stub(u["12"], VOUT, 5.08)                                    # VISOOUT
    stub(u["19"], VIN, 5.08)                                     # VISOIN
    stub(u["18"], BA, 5.08); stub(u["13"], BA, 5.08)            # A + Y  -> BUS_A
    stub(u["17"], BB, 5.08); stub(u["15"], BB, 5.08)           # B + Z  -> BUS_B
    s.wire(u["11"], u["14"]); stub(u["14"], GDC, 5.08)          # GND2_DCDC (11/14)
    s.wire(u["16"], u["20"]); stub(u["20"], GBUS, 5.08)         # ISO_BUS_GND (16/20)

    # ---- power gate (upper-left) : 3V3 -[Q_ls]-> VCC, gate = CHn_PWR + pull-up
    fx, fy = snap(cx - 44.45), snap(cy - 27.94)
    q = s.place("Q_PMOS_GSD", Q, "NTR4171P", "Package_TO_SOT_SMD:SOT-23",
                (fx, fy), angle=0, tanchor="l")
    stub(q["1"], f"CH{n}_PWR", -7.62)                            # gate
    stub(q["2"], "V3V3", 7.62)                                   # source (main 3V3 rail)
    stub(q["3"], VCC, 7.62)                                      # drain -> VCC
    hpart("R", f"R{rb}", "100k", "R_0805_2012Metric", fx, snap(fy - 12.7), f"CH{n}_PWR", "V3V3")

    # ---- DI series R (below IC, out of the crowded control column) ------------
    hpart("R", f"R{rb+1}", "1k", "R_0805_2012Metric", snap(cx - 33.02), snap(cy + 22.86), f"RS485B_DI{n}", f"TXD{n}")

    # ---- VCC decoupling bank (4) : C_vcc1a/b (0.1u/0.01u), C_vcc2a/b (0.1u/10u)
    bank([("C", f"C{cb}", "0.1µF", "C_0603_1608Metric", False),
          ("C", f"C{cb+1}", "0.01µF", "C_0603_1608Metric", False),
          ("C", f"C{cb+2}", "0.1µF", "C_0603_1608Metric", False),
          ("C", f"C{cb+3}", "10µF", "C_0805_2012Metric", False)],
         snap(cx - 67.31), snap(cy + 27.94), snap(cy + 40.64), VCC, "GND")

    # ---- isoPower support (right) : C_vout/C_vin banks + L1/L2 + C_stitch -----
    bank([("C", f"C{cb+4}", "10µF", "C_0805_2012Metric", False),
          ("C", f"C{cb+5}", "0.1µF", "C_0603_1608Metric", False)],
         snap(cx + 46.99), snap(cy - 27.94), snap(cy - 15.24), VOUT, GDC)
    bank([("C", f"C{cb+6}", "0.1µF", "C_0603_1608Metric", False),
          ("C", f"C{cb+7}", "0.01µF", "C_0603_1608Metric", False)],
         snap(cx + 46.99), snap(cy + 15.24), snap(cy + 27.94), VIN, GBUS)
    hpart("FerriteBead", La, "600Ω 2A", "Inductor_SMD:L_0805_2012Metric", snap(cx + 85.09), snap(cy - 22.86), VOUT, VIN)
    hpart("C", f"C{cb+8}", "1nF 1kV", "C_1206_3216Metric", snap(cx + 85.09), cy, "GND", GDC)
    hpart("FerriteBead", Lb, "600Ω 2A", "Inductor_SMD:L_0805_2012Metric", snap(cx + 85.09), snap(cy + 22.86), GDC, GBUS)

    # ---- battery jack : RJ45 (A=pin7, B=pin8, shield=ISO_BUS_GND). Pins face
    #      right -> stub A/B/shield rightward into their labels (clear of body).
    j = s.place("RJ45_Shielded", Jr, "Amphenol_RJHSE-5380", "Connector_RJ:RJ45_Amphenol_RJHSE5380",
                (snap(cx + 116.84), cy), angle=0, tanchor="u", tgap=6.35)
    stub(j["7"], BA, 7.62); stub(j["8"], BB, 7.62)
    stub(j["SH"], GBUS, 0, 5.08)
    for pn in ("1", "2", "3", "4", "5", "6"): s.no_connect(j[pn])

    # ---- bus protection provisioning (DNP), 2-col grid below IC : TVS + R_ser
    #      + R_bias + term + REF. All label-connected (F36/F44 unpopulated).
    #      col1 = R_ser1/R_ser2/TVS (TVS last, room below for its GND stub).
    c1, c2 = snap(cx + 2.54), snap(cx + 40.64)
    yv = [snap(cy + 35.56 + k * 12.7) for k in range(4)]
    hpart("R", f"R{rb+2}", "10", "R_0603_1608Metric", c1, yv[0], BA, f"TVA{n}", dnp)
    hpart("R", f"R{rb+3}", "10", "R_0603_1608Metric", c1, yv[1], BB, f"TVB{n}", dnp)
    tv = s.place("SM712_SOT23", Dt, "SM712", "Package_TO_SOT_SMD:SOT-23",
                 (c1, yv[2]), angle=0, tanchor="u", dnp=dnp)
    stub(tv["1"], f"TVA{n}", -6.35); stub(tv["2"], f"TVB{n}", 6.35); stub(tv["3"], GBUS, 0, 6.35)
    # col2 rows offset by half-pitch so no col1/col2 part shares a Y (inward
    # labels of adjacent columns then never collide across the gap).
    yw = [snap(y + 6.35) for y in yv]
    hpart("R", f"R{rb+5}", "560", "R_0603_1608Metric", c2, yw[0], BA, VIN, dnp)
    hpart("R", f"R{rb+6}", "560", "R_0603_1608Metric", c2, yw[1], BB, GBUS, dnp)
    hpart("R", f"R{rb+7}", "0", "R_0805_2012Metric", c2, yw[2], GBUS, f"PACK{n}_Bminus", dnp)
    hpart("R", f"R{rb+4}", "120", "R_0805_2012Metric", c2, yw[3], BA, BB, dnp)

    # ---- PWR_FLAGs: passively-driven isolated nets. VCC via the power-gate FET;
    #      V_ISOIN fed through L1; the two floating grounds have no "driver". ----
    for i, net in enumerate((VCC, VIN, GDC, GBUS)):
        pf = s.place("PWR_FLAG", f"#FLG{n}{i}", "PWR_FLAG", "",
                     (snap(cx - 7.62 + i * 17.78), snap(cy - 46.99)), angle=0, tanchor="ud")
        s.wire(pf["1"], (pf["1"][0], snap(pf["1"][1] + 5.08)))
        s.label(net, (pf["1"][0], snap(pf["1"][1] + 5.08)), justify_h="left")


def blk_j5_dbg(s, cx, cy):
    """J5 debug/console UART header — ESP U0TXD/U0RXD + V3V3 + GND for a
    USB-serial adapter (flash fallback / console). (cx,cy) = J5 centre."""
    j = s.place("Conn_01x04", "J5", "debug-UART",
                "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                (cx, cy), angle=0, tanchor="r")
    for pn, net in (("1", "GND"), ("2", "V3V3"), ("3", "DBG_TXD"), ("4", "DBG_RXD")):
        pin = j[pn]; e = (snap(pin[0] - 10.16), pin[1])
        s.wire(pin, e); s.label(net, e, justify_h="right")


def blk_usbc(s, cx, cy):
    """USB-C maintenance port (D22/D29). Custom one-pin-per-row symbol (no
    stacked pins). VBUS/GND are 4 pads each; D± -> native ESP USB; CC1/CC2 5.1k
    pull-downs (UFP/device mode); SBU unused; shield -> GND. (cx,cy)=J3."""
    yg = snap(cy + 30.48)
    j = s.place("USB_C_16P", "J3", "USB-C 2.0",
                "Connector_USB:USB_C_Receptacle_GCT_USB4085", (cx, cy), angle=0, tanchor="u", tgap=3.0)

    def bus(pins, net, dx=10.16):        # tie N same-net pins, one label
        xb = snap(max(p[0] for p in pins) + dx)
        for p in pins: s.wire(p, (xb, p[1]))
        y0, y1 = min(p[1] for p in pins), max(p[1] for p in pins)
        s.wire((xb, y0), (xb, y1))
        s.wire((xb, y0), (snap(xb + 7.62), y0)); s.label(net, (snap(xb + 7.62), y0), justify_h="left")
    bus([j[n] for n in ("A4", "A9", "B4", "B9")], "VBUS")
    bus([j["A7"], j["B7"]], "USB_DM", 7.62)
    bus([j["A6"], j["B6"]], "USB_DP", 7.62)
    # CC1/CC2 -> 5.1k -> GND (far right, clear of the D± labels; CC1 higher ->
    # farther column so no wire crosses another)
    for pin, ref, dx in (("A5", "R_cc1", 40.64), ("B5", "R_cc2", 27.94)):
        p = j[pin]; xr = snap(p[0] + dx); s.wire(p, (xr, p[1]))
        r = s.place("R", ref, "5.1k", "R_0805_2012Metric", (xr, snap(p[1] + 6.35)), tanchor="r")
        s.wire((xr, p[1]), r["1"]); s.wire(r["2"], (xr, snap(r["2"][1] + 2.54)))
        s.label("GND", (xr, snap(r["2"][1] + 2.54)), justify_h="left")
    s.no_connect(j["A8"]); s.no_connect(j["B8"])         # SBU unused
    # U-ESD USBLC6-2SC6: ESD array on D+/D- (internal clamp diodes to VBUS/GND),
    # placed near J3 (D22/D29 note). I/O1(1,6)=D+, I/O2(3,4)=D-, 5=VBUS, 2=GND.
    ux, uy = snap(cx + 50.8), snap(cy - 40.64)
    ue = s.place("USBLC6-2SC6", "U-ESD", "USBLC6-2SC6Y", "Package_TO_SOT_SMD:SOT-23-6",
                 (ux, uy), angle=0, tanchor="r")
    s.wire(ue["1"], (snap(ue["1"][0] - 7.62), ue["1"][1]))
    s.label("USB_DP", (snap(ue["1"][0] - 7.62), ue["1"][1]), justify_h="right")
    s.wire(ue["3"], (snap(ue["3"][0] - 7.62), ue["3"][1]))
    s.label("USB_DM", (snap(ue["3"][0] - 7.62), ue["3"][1]), justify_h="right")
    s.wire(ue["5"], (ue["5"][0], snap(ue["5"][1] - 5.08)))
    s.label("VBUS", (ue["5"][0], snap(ue["5"][1] - 5.08)), justify_h="left")
    s.wire(ue["2"], (ue["2"][0], snap(ue["2"][1] + 5.08)))
    s.label("GND", (ue["2"][0], snap(ue["2"][1] + 5.08)), justify_h="left")
    s.no_connect(ue["6"]); s.no_connect(ue["4"])         # I/O duplicate pins
    # GND x4 (bottom) -> GND rail ; shield -> GND (left)
    gp = [j[n] for n in ("A1", "A12", "B1", "B12")]
    for p in gp: s.wire(p, (p[0], yg))
    gxs = sorted(p[0] for p in gp)
    s.wire((snap(gxs[0] - 7.62), yg), (gxs[-1], yg))
    s.label("GND", (snap(gxs[0] - 7.62), yg), justify_h="right")
    sh = j["SH"]; s.wire(sh, (snap(sh[0] - 7.62), sh[1]))
    s.label("GND", (snap(sh[0] - 7.62), sh[1]), justify_h="right")


def blk_exp(s, cx, cy):
    """Expansion header J_EXP (Molex PicoBlade 53398-0871) on the switched
    EXP_3V3 rail. Q_exp NTR4171P high-side P-FET (default-OFF: gate pulled to
    V3V3 via R_exp_pu 100k; EXP_PWR_EN low = ON). R_exp_bleed 10k parks the rail
    (F66). D37 pinout: 1/8=GND, 2=EXP_3V3, 3=SDA, 4=SCL, 5=AIO1, 6=AIO2, 7=DIO3."""
    # Q_exp high-side switch: S=V3V3, D=EXP_3V3, G=EXP_PWR_EN + R_exp_pu->V3V3
    q = s.place("Q_PMOS_GSD", "Q_exp", "NTR4171P", "Package_TO_SOT_SMD:SOT-23",
                (cx, cy), angle=0, tanchor="r")
    G, S, D = q["1"], q["2"], q["3"]
    s.wire(S, (S[0], snap(S[1] + 3.81))); s.label("V3V3", (snap(S[0] + 10.16), snap(S[1] + 3.81)), justify_h="left")
    s.wire((S[0], snap(S[1] + 3.81)), (snap(S[0] + 10.16), snap(S[1] + 3.81)))
    s.wire(D, (D[0], snap(D[1] - 3.81)))
    xe = snap(D[0] + 15.24)
    s.wire((D[0], snap(D[1] - 3.81)), (xe, snap(D[1] - 3.81))); s.label("EXP_3V3", (xe, snap(D[1] - 3.81)), justify_h="left")
    # gate: EXP_PWR_EN + R_exp_pu pull-up to V3V3
    xg = snap(G[0] - 10.16)
    s.wire(G, (xg, G[1])); s.label("EXP_PWR_EN", (snap(xg - 12.7), G[1]), justify_h="right")
    s.wire((snap(xg - 12.7), G[1]), (xg, G[1]))
    rpu = s.place("R", "R_exp_pu", "100k", "R_0805_2012Metric", (xg, snap(G[1] - 6.35)), tanchor="l")
    s.wire(rpu["2"], (xg, G[1])); s.wire(rpu["1"], (xg, snap(rpu["1"][1] - 2.54)))
    s.label("V3V3", (xg, snap(rpu["1"][1] - 2.54)), justify_h="right")
    # R_exp_bleed 10k: EXP_3V3 -> GND
    rb = s.place("R", "R_exp_bleed", "10k", "R_0805_2012Metric", (xe, snap(D[1] - 3.81 + 6.35)), tanchor="l")
    s.wire((xe, snap(D[1] - 3.81)), rb["1"]); s.wire(rb["2"], (xe, snap(rb["2"][1] + 2.54)))
    s.label("GND", (xe, snap(rb["2"][1] + 2.54)), justify_h="right")
    # EXP I2C pull-ups (DNP, footprint-only): SDA/SCL -> switched EXP_3V3.
    # Populate here OR on the expansion daughterboard if/when one is built
    # (user call 2026-07-20). 4.7k to match R8/R9.
    for i, (ref, net) in enumerate((("R_exp_sda", "EXP_SDA"), ("R_exp_scl", "EXP_SCL"))):
        yp = snap(cy - 20.32 - i * 10.16)
        rp = s.place("R", ref, "4.7k", "R_0805_2012Metric", (snap(cx + 7.62), yp),
                     angle=90, tanchor="ud", bw=7.62, dnp=True)
        L = min(rp.values(), key=lambda p: p[0]); R = max(rp.values(), key=lambda p: p[0])
        s.wire(L, (snap(L[0] - 3.81), yp)); s.label("EXP_3V3", (snap(L[0] - 3.81), yp), justify_h="right")
        s.wire(R, (snap(R[0] + 3.81), yp)); s.label(net, (snap(R[0] + 3.81), yp), justify_h="left")

    # J_EXP header
    jy = snap(cy + 3.81)
    j = s.place("Conn_01x08", "J_EXP", "Molex_PicoBlade_53398-0871",
                "Connector_Molex:Molex_PicoBlade_53398-0871_1x08-1MP_P1.25mm_Vertical",
                (snap(cx + 45.72), jy), angle=0, tanchor="u")
    NET = {"1": "GND", "2": "EXP_3V3", "3": "EXP_SDA", "4": "EXP_SCL", "5": "EXP_AIO1",
           "6": "EXP_AIO2", "7": "EXP_DIO3", "8": "GND"}
    for num, net in NET.items():
        p = j[num]; s.wire(p, (snap(p[0] - 10.16), p[1])); s.label(net, (snap(p[0] - 10.16), p[1]), justify_h="right")


def blk_j1_btn(s, cx, cy):
    """Pack input J1 (Phoenix MSTBA 2,5/2-G-5,08) + override button BTN1 (C&K
    8125SHZBE SPDT wired COM-NO, R13 1M pull-up + C11 debounce). (cx,cy)=J1."""
    j1 = s.place("Conn_01x02", "J1", "Phoenix_MSTBA_2,5-2-G-5,08",
                 "Connector_Phoenix_MSTB:PhoenixContact_MSTBA_2,5_2-G-5,08_1x02_P5.08mm_Horizontal",
                 (cx, cy), angle=0, tanchor="u")
    for num, net in (("1", "V24_RAW"), ("2", "GND")):
        p = j1[num]; s.wire(p, (snap(p[0] - 10.16), p[1]))
        s.label(net, (snap(p[0] - 10.16), p[1]), justify_h="right")
    # BTN1 below J1
    by = snap(cy + 25.4)
    # BTN1 is PANEL-mounted (solder lugs, flying leads — see its BOM row); the
    # PCB side is a 1x03 THT hole pattern the leads solder into (pads 1..3
    # match the SW_SPDT pin numbers; only 1=NO and 2=COM are actually wired).
    bt = s.place("SW_SPDT", "BTN1", "C&K_8125SHZBE",
                 "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                 (cx, by), angle=0, tanchor="u")
    COM, NO, NC = bt["2"], bt["1"], bt["3"]
    s.no_connect(NC)
    s.wire(NO, (snap(NO[0] + 7.62), NO[1])); s.label("GND", (snap(NO[0] + 7.62), NO[1]), justify_h="left")
    s.wire((NO[0], NO[1]), (snap(NO[0] + 7.62), NO[1]))
    # COM = BTN_OVERRIDE node: R13 pull-up to V3V3, C11 debounce to GND, label to MCU
    xn = snap(COM[0] - 10.16)
    s.wire(COM, (xn, COM[1])); s.label("BTN_OVERRIDE", (snap(xn - 10.16), COM[1]), justify_h="right")
    s.wire((snap(xn - 10.16), COM[1]), (xn, COM[1]))
    r13 = s.place("R", "R13", "1M", "R_0805_2012Metric", (xn, snap(COM[1] - 6.35)), tanchor="l")
    s.wire(r13["2"], (xn, COM[1])); s.wire(r13["1"], (xn, snap(r13["1"][1] - 2.54)))
    s.label("V3V3", (xn, snap(r13["1"][1] - 2.54)), justify_h="right")
    c11 = s.place("C", "C11", "100nF", "C_0603_1608Metric", (xn, snap(COM[1] + 6.35)), tanchor="l")
    s.wire((xn, COM[1]), c11["1"]); s.wire(c11["2"], (xn, snap(c11["2"][1] + 2.54)))
    s.label("GND", (xn, snap(c11["2"][1] + 2.54)), justify_h="right")


def blk_j2_rj45(s, cx, cy):
    """J2 RJ45 to the display side (Amphenol RJHSE-538X, shielded). T568B per
    cat5e_pinout: 1-3=V12_CAT5E, 4=RS485_A, 5=RS485_B, 6-8=GND, shield->GND at
    this (battery) end only (DR-19). (cx,cy)=J2 centre."""
    j2 = s.place("RJ45_Shielded", "J2", "Amphenol_RJHSE-538X",
                 "Connector_RJ:RJ45_Amphenol_RJHSE538X", (cx, cy), angle=0, tanchor="u", tgap=6.35)
    NET = {"1": "V12_CAT5E", "2": "V12_CAT5E", "3": "V12_CAT5E", "4": "RS485_A",
           "5": "RS485_B", "6": "GND", "7": "GND", "8": "GND", "SH": "GND"}
    for num, net in NET.items():
        p = j2[num]; s.wire(p, (snap(p[0] + 10.16), p[1]))
        s.label(net, (snap(p[0] + 10.16), p[1]), justify_h="left")


def blk_usb_power(s, cx, cy):
    """USB maintenance power (D29). U5 AP2112 LDO (VBUS->3V3_USB) wired DIRECTLY
    into U6 TPS2116 priority mux — 3V3_USB is local to this sheet so it's a wire,
    not a label. MODE->VIN1 (priority mode, USB preferred); PR1->VIN1; VIN2 =
    V3V3_BUCK (from the buck); OUT = V3V3 rail. (cx,cy) = U5 centre."""
    yg = snap(cy + 20.32)
    # ---- U5 AP2112 LDO ----
    u5 = s.place("AP2112K-3.3", "U5", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
                 (cx, cy), angle=0, tanchor="u", tgap=3.0)
    VIN, GND5, EN5, VOUT5 = u5["1"], u5["2"], u5["3"], u5["5"]
    s.no_connect(u5["4"])
    xcu1, xvbus = snap(cx - 15.24), snap(cx - 25.4)
    cu1 = s.place("C", "C_usb1", "1µF", "C_0603_1608Metric", (xcu1, snap(VIN[1] + 3.81)), tanchor="l")
    s.label("VBUS", (xvbus, VIN[1]), justify_h="right")
    s.wire((xvbus, VIN[1]), cu1["1"]); s.wire(cu1["1"], VIN); s.wire(cu1["2"], (xcu1, yg))
    s.wire(EN5, VIN); s.wire(GND5, (GND5[0], yg))
    # ---- U6 mux to the right ----
    # footprint: SOT-583-8 (8-pin DRL) — stock symbol's own suggestion; the
    # previous "Package_SON:Texas_SOT-563" was a 6-pin package that doesn't
    # exist in that library (caught while fixing the stacked VOUT pins).
    u6 = s.place("TPS2116DRL", "U6", "TPS2116DRLR", "Package_TO_SOT_SMD:SOT-583-8",
                 (snap(cx + 40.64), cy), angle=0, tanchor="u", tgap=3.0)
    GND6, VOUT6, VIN1, PR1, MODE, VIN2, ST = u6["1"], u6["2"], u6["3"], u6["4"], u6["5"], u6["6"], u6["8"]
    s.no_connect(ST)
    # 3V3_USB bus: U5 VOUT + C_usb2 -> U6 VIN1/PR1/MODE (all wired, local net)
    xb = snap(cx + 17.78)
    s.wire(VOUT5, (xb, VOUT5[1]))
    s.wire((xb, VIN1[1]), (xb, MODE[1]))              # vertical bus
    s.wire((xb, VIN1[1]), VIN1); s.wire((xb, PR1[1]), PR1); s.wire((xb, MODE[1]), MODE)
    cu2 = s.place("C", "C_usb2", "1µF", "C_0603_1608Metric", (snap(cx + 10.16), snap(VOUT5[1] + 3.81)), tanchor="r")
    s.wire(cu2["1"], (cu2["1"][0], VOUT5[1])); s.wire(cu2["2"], (cu2["1"][0], yg))
    # VIN2 <- V3V3_BUCK (down to a label, clear of the bus) ; OUT -> V3V3
    s.wire(VIN2, (VIN2[0], snap(VIN2[1] + 6.35))); s.label("V3V3_BUCK", (VIN2[0], snap(VIN2[1] + 6.35)), justify_h="left")
    s.wire(VOUT6, (snap(VOUT6[0] + 8.89), VOUT6[1])); s.label("V3V3", (snap(VOUT6[0] + 15.24), VOUT6[1]), justify_h="left")
    s.wire((snap(VOUT6[0] + 8.89), VOUT6[1]), (snap(VOUT6[0] + 15.24), VOUT6[1]))
    # C_mux: 47µF bulk on the mux OUT (V3V3) — reverse-current-blocking on USB
    # hot-plug (reviewer F11). Hangs off the V3V3 node down to the GND rail.
    xcm = snap(VOUT6[0] + 8.89)
    cm = s.place("C", "C_mux", "47µF", "C_0805_2012Metric", (xcm, snap(VOUT6[1] + 6.35)), tanchor="l")
    s.wire(cm["1"], (xcm, VOUT6[1])); s.wire(cm["2"], (xcm, yg))
    s.wire(u6["7"], (xcm, u6["7"][1]))   # VOUT twin (pin 7) joins the output node
    s.wire(GND6, (GND6[0], yg))
    # shared GND rail (extends to xcm so C_mux's bottom pin lands on it)
    s.wire((snap(xcu1 - 5.08), yg), (xcm, yg))
    s.label("GND", (snap(xcu1 - 5.08), yg), justify_h="right")


def blk_usb_failsafe(s, cx, cy):
    """Fail-safe USB bypass (F03): Q3 (series UVLO_RESET->MCU_EN) default-ON via
    R_byp1(100k->V3V3); Q4 (VBUS-driven via R_byp2/R_byp2b divider) pulls Q3 gate
    low when USB is present, so the MCU boots off USB even on a dead pack.
    (cx,cy) = Q3 centre."""
    # Q3: series UVLO_RESET(S) -> MCU_EN(D); gate default-ON via R_byp1->V3V3.
    qx, qy = cx, cy
    q3 = s.place("2N7002", "Q3", "2N7002", "Package_TO_SOT_SMD:SOT-23", (qx, qy), tanchor="r")
    q3G, q3S, q3D = q3["1"], q3["2"], q3["3"]
    s.wire(q3D, (q3D[0], snap(q3D[1] - 5.08)))
    s.label("MCU_EN", (snap(q3D[0] + 7.62), snap(q3D[1] - 5.08)), justify_h="left")
    s.wire((q3D[0], snap(q3D[1] - 5.08)), (snap(q3D[0] + 7.62), snap(q3D[1] - 5.08)))
    s.wire(q3S, (q3S[0], snap(q3S[1] + 5.08)))
    s.label("UVLO_RESET", (snap(q3S[0] + 7.62), snap(q3S[1] + 5.08)), justify_h="left")
    s.wire((q3S[0], snap(q3S[1] + 5.08)), (snap(q3S[0] + 7.62), snap(q3S[1] + 5.08)))
    # R_byp1: Q3 gate -> V3V3 (pull-up = default ON)
    xg = snap(q3G[0] - 10.16)
    rb1 = s.place("R", "R_byp1", "100k", "R_0805_2012Metric", (xg, snap(q3G[1] - 6.35)), tanchor="l")
    s.wire(q3G, (xg, q3G[1])); s.wire((xg, q3G[1]), rb1["2"])
    s.wire(rb1["1"], (xg, snap(rb1["1"][1] - 2.54)))
    s.label("V3V3", (xg, snap(rb1["1"][1] - 2.54)), justify_h="right")
    # Q4: gate <- VBUS divider (R_byp2 / R_byp2b); D -> Q3 gate node; S -> GND
    q4 = s.place("2N7002", "Q4", "2N7002", "Package_TO_SOT_SMD:SOT-23", (qx, snap(qy + 25.4)), tanchor="r")
    q4G, q4S, q4D = q4["1"], q4["2"], q4["3"]
    s.wire(q4D, (q4D[0], snap(q4D[1] - 5.08))); s.wire((q4D[0], snap(q4D[1] - 5.08)), (xg, snap(q4D[1] - 5.08)))
    s.wire((xg, snap(q4D[1] - 5.08)), (xg, q3G[1]))    # Q4 drain -> Q3 gate node (xg column)
    s.wire(q4S, (q4S[0], snap(q4S[1] + 5.08)))
    s.label("GND", (snap(q4S[0] + 7.62), snap(q4S[1] + 5.08)), justify_h="left")
    s.wire((q4S[0], snap(q4S[1] + 5.08)), (snap(q4S[0] + 7.62), snap(q4S[1] + 5.08)))
    # R_byp2 (VBUS -> Q4 gate) + R_byp2b (Q4 gate -> GND) divider — its own column,
    # kept clear of the Q3-gate column (xg) so VBUS never touches the reset net.
    xg4 = snap(q4G[0] - 20.32)
    rb2 = s.place("R", "R_byp2", "100k", "R_0805_2012Metric", (xg4, snap(q4G[1] - 6.35)), tanchor="l")
    s.wire(q4G, (xg4, q4G[1])); s.wire((xg4, q4G[1]), rb2["2"])
    s.wire(rb2["1"], (xg4, snap(rb2["1"][1] - 2.54)))
    s.label("VBUS", (xg4, snap(rb2["1"][1] - 2.54)), justify_h="right")
    rb2b = s.place("R", "R_byp2b", "1M", "R_0805_2012Metric", (xg4, snap(q4G[1] + 6.35)), tanchor="l")
    s.wire((xg4, q4G[1]), rb2b["1"]); s.wire(rb2b["2"], (xg4, snap(rb2b["2"][1] + 2.54)))
    s.label("GND", (xg4, snap(rb2b["2"][1] + 2.54)), justify_h="right")


def blk_ssr(s, cx, cy):
    """Display-feed load switch (F76): V24_FUSED -> F2 (80mA) -> SSR1 (AQY212EH
    PhotoMOS) -> R_inrush (2x75R = 150R) -> V24_SW. SSR LED driven by PWR_EN via
    R_opto (330R); R4 100k pull-down holds the LED OFF when PWR_EN floats
    (reset/brown-out). (cx,cy)=SSR1 centre."""
    yg = snap(cy + 13.97)
    # AQY212EH = standard DIP-4 THT, 7.62 mm row (datasheet); the previous
    # "Relay_SolidState:Panasonic_DIP-4_LongPin" library doesn't exist.
    ssr = s.place("AQY212EH", "SSR1", "AQY212EH", "Package_DIP:DIP-4_W7.62mm",
                  (cx, cy), angle=0, tanchor="u")
    A, K, OUT3, OUT4 = ssr["1"], ssr["2"], ssr["3"], ssr["4"]

    # ---- input LED: PWR_EN -> R_opto -> A(anode); K(cathode) -> GND; R4 pulldown ----
    ropto = s.place("R", "R_opto", "330", "R_0805_2012Metric", (snap(cx - 17.78), A[1]),
                    angle=90, tanchor="ud", bw=7.62)
    roL = min(ropto.values(), key=lambda p: p[0]); roR = max(ropto.values(), key=lambda p: p[0])
    s.wire(roR, A)
    xen, xn = snap(cx - 40.64), snap(cx - 27.94)      # PWR_EN label, R4 tap node
    s.label("PWR_EN", (xen, A[1]), justify_h="right")
    s.wire((xen, A[1]), (xn, A[1])); s.wire((xn, A[1]), roL)
    r4 = s.place("R", "R4", "100k", "R_0805_2012Metric", (xn, snap(A[1] + 3.81)), tanchor="l")
    s.wire(r4["2"], (xn, yg))                          # R4 top sits on the PWR_EN node
    s.wire(K, (K[0], yg))                             # cathode -> GND rail

    # ---- output: OUT4/OUT3 fanned to separated rows for label room ----
    yF, yR = snap(cy - 8.89), snap(cy + 8.89)         # F2 row / R_inrush row
    xf = snap(cx + 13.97)
    s.wire(OUT4, (xf, OUT4[1])); s.wire((xf, OUT4[1]), (xf, yF))
    s.wire(OUT3, (xf, OUT3[1])); s.wire((xf, OUT3[1]), (xf, yR))
    # V24_FUSED -> F2 -> OUT4 (top row)
    f2 = s.place("Fuse", "F2", "80mA", "Fuse:Fuse_Littelfuse-NANO2-451_453", (snap(cx + 22.86), yF),
                 angle=90, tanchor="ud", bw=7.62)
    f2L = min(f2.values(), key=lambda p: p[0]); f2R = max(f2.values(), key=lambda p: p[0])
    s.wire((xf, yF), f2L); s.wire(f2R, (snap(cx + 38.1), yF))
    s.label("V24_FUSED", (snap(cx + 38.1), yF), justify_h="left")
    # OUT3 -> R_inrush x2 -> V24_SW (bottom row)
    ri1 = s.place("R", "R_inrush1", "75", "R_1206_3216Metric", (snap(cx + 22.86), yR),
                  angle=90, tanchor="ud", bw=7.62)
    ri2 = s.place("R", "R_inrush2", "75", "R_1206_3216Metric", (snap(cx + 35.56), yR),
                  angle=90, tanchor="ud", bw=7.62)
    r1L = min(ri1.values(), key=lambda p: p[0]); r1R = max(ri1.values(), key=lambda p: p[0])
    r2L = min(ri2.values(), key=lambda p: p[0]); r2R = max(ri2.values(), key=lambda p: p[0])
    s.wire((xf, yR), r1L); s.wire(r1R, r2L); s.wire(r2R, (snap(cx + 48.26), yR))
    s.label("V24_SW", (snap(cx + 48.26), yR), justify_h="left")

    # ---- GND rail ----
    s.wire((snap(xn - 7.62), yg), (K[0], yg))
    s.label("GND", (snap(xn - 7.62), yg), justify_h="right")


def blk_u2(s, cx, cy):
    """Switched 12V converter (behind SSR1): V24_SW -> U2 R-78HB12 -> V12_CAT5E.
    C3 in (3.3µF/100V, behind the clamp; F90), C4 out (22µF/25V), TVS3 SMAJ15A
    on the Cat5e 12V pair at this end (DR-15). (cx,cy)=U2 centre."""
    yg = snap(cy + 13.97)
    u2 = s.place("R-78HB12-0.5", "U2", "R-78HB12-0.5",
                 "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                 (cx, cy), angle=0, tanchor="u", tgap=2.0)
    IN, GND, OUT = u2["1"], u2["2"], u2["3"]
    # input: V24_SW -> IN, C3 tap to GND
    xin, xc3 = snap(cx - 27.94), snap(cx - 15.24)
    c3 = s.place("C", "C3", "3.3µF 100V", "C_1210_3225Metric",
                 (xc3, snap(IN[1] + 3.81)), tanchor="l")
    s.label("V24_SW", (xin, IN[1]), justify_h="right")
    s.wire((xin, IN[1]), c3["1"]); s.wire(c3["1"], IN); s.wire(c3["2"], (xc3, yg))
    # output: OUT -> node -> V12_CAT5E; C4 + TVS3 taps to GND
    xc4, xtv, xout = snap(cx + 15.24), snap(cx + 33.02), snap(cx + 43.18)
    s.wire(OUT, (xc4, OUT[1]))
    c4 = s.place("C", "C4", "22µF 25V", "C_1210_3225Metric",
                 (xc4, snap(OUT[1] + 3.81)), tanchor="r")
    tv3 = s.place("D_TVS", "TVS3", "SMAJ15A", "D_SMA",
                  (xtv, snap(OUT[1] + 6.35)), angle=90, tanchor="r")
    t3T = min(tv3.values(), key=lambda p: p[1]); t3B = max(tv3.values(), key=lambda p: p[1])
    s.wire((xc4, OUT[1]), (xtv, OUT[1])); s.wire((xtv, OUT[1]), (xout, OUT[1]))
    s.label("V12_CAT5E", (xout, OUT[1]), justify_h="left")
    s.wire(c4["2"], (xc4, yg)); s.wire(t3T, (xtv, OUT[1])); s.wire(t3B, (xtv, yg))
    # GND rail
    xgl = snap(cx - 20.32)
    s.wire((xgl, yg), (xtv, yg)); s.wire(GND, (GND[0], yg))
    s.label("GND", (xgl, yg), justify_h="right")


def blk_mcu(s, cx, cy):
    """MOD1 ESP32-S3-WROOM-1-N16R8 — the hub. 3V3 (C6/C7 decoupling), EN network
    (R7 pull-up + C8 + MCU_EN from the UVLO/Q3 gate), I2C pull-ups R8/R9. GPIO
    map per cp1: IO1=V24_SENSE(ADC), IO2=RS485_DE, IO15=RS485_nRE, IO4=PWR_EN,
    IO7=BTN, IO8/9=I2C, IO17/18=RS485 DI/RO, USB_D±. Unused GPIOs no-connected.
    (cx,cy)=module centre."""
    mod = s.place("ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "RF_Module:ESP32-S3-WROOM-1", (cx, cy), angle=0, tanchor="u", tgap=9.0)
    # pin number -> global net (side inferred from pin x)
    NETS = {"3": "MCU_EN", "39": "V24_SENSE", "38": "RS485_DE", "4": "PWR_EN",
            "7": "BTN_OVERRIDE", "12": "I2C_SDA", "17": "I2C_SCL", "8": "RS485_nRE",
            "10": "RS485_DI", "11": "RS485_RO", "13": "USB_DM", "14": "USB_DP",
            # expansion header (D37): dedicated I2C1 + 2x ADC1/RTC-wake AIO + DIO + PWR_EN
            "15": "EXP_AIO1", "5": "EXP_AIO2", "18": "EXP_SDA", "19": "EXP_SCL",
            "20": "EXP_PWR_EN", "31": "EXP_DIO3",
            # isolated RS-485 battery read (D36): 2 ch x (DI/RO/DE) on the shared
            # matrix-mapped UART2 + per-ch power-gate. All plain GPIO; strapping
            # (IO0/45/46), octal-PSRAM (IO35/36/37) and console UART0 avoided.
            "6": "RS485B_DI1", "9": "RS485B_RO1", "21": "RS485B_DE1", "22": "CH1_PWR",
            "23": "RS485B_DI2", "24": "RS485B_RO2", "25": "RS485B_DE2", "32": "CH2_PWR",
            # console UART0 -> J5 debug header
            "37": "DBG_TXD", "36": "DBG_RXD"}
    for num, net in NETS.items():
        pin = mod[num]
        if pin[0] < cx:
            lbl = (snap(pin[0] - 16.51), pin[1]); s.label(net, lbl, justify_h="right")
        else:
            lbl = (snap(pin[0] + 16.51), pin[1]); s.label(net, lbl, justify_h="left")
        s.wire(lbl, pin)
    # 3V3 (top-centre) -> up -> V3V3 rail routed LEFT; C6/C7 decoupling hang off
    # it (keeps the top-centre clear of the ref/value text).
    v3 = mod["2"]; yv = snap(v3[1] - 7.62)
    s.wire(v3, (v3[0], yv))
    xc6, xc7, xv3 = snap(cx - 15.24), snap(cx - 27.94), snap(cx - 38.1)
    s.wire((v3[0], yv), (xc6, yv)); s.wire((xc6, yv), (xc7, yv)); s.wire((xc7, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="right")
    for xc, ref, val in ((xc6, "C6", "10µF"), (xc7, "C7", "100nF")):
        c = s.place("C", ref, val, "C_0805_2012Metric", (xc, snap(yv - 3.81)), tanchor="l")
        s.wire(c["1"], (xc, snap(c["1"][1] - 2.54)))
        s.label("GND", (xc, snap(c["1"][1] - 2.54)), justify_h="right")
    # GND: the 3 bottom pins (1/40/41, spread in the symbol) -> a short GND rail
    yg = snap(mod["1"][1] + 6.35)
    gxs = sorted(mod[n][0] for n in ("1", "40", "41"))
    for n in ("1", "40", "41"):
        s.wire(mod[n], (mod[n][0], yg))
    s.wire((snap(gxs[0] - 7.62), yg), (gxs[-1], yg))
    s.label("GND", (snap(gxs[0] - 7.62), yg), justify_h="right")
    # ---- support cluster below the module: EN + I2C pull-ups to V3V3, C8 ----
    yrail = snap(cy + 43.18); ylbl = snap(yrail + 11.43)
    xs = [snap(cx - 22.86), snap(cx - 7.62), snap(cx + 7.62)]
    s.label("V3V3", (snap(xs[0] - 8.89), yrail), justify_h="right")
    s.wire((snap(xs[0] - 8.89), yrail), (xs[-1], yrail))
    for x, (ref, val, net) in zip(xs, (("R7", "10k", "MCU_EN"), ("R8", "4.7k", "I2C_SDA"),
                                       ("R9", "4.7k", "I2C_SCL"))):
        r = s.place("R", ref, val, "R_0805_2012Metric", (x, snap((yrail + ylbl) / 2)), tanchor="l")
        s.wire(r["1"], (x, yrail))
        s.wire(r["2"], (x, ylbl)); s.label(net, (x, ylbl), justify_h="left")
    # C8: EN filter, MCU_EN -> GND (own column, right of the pull-ups)
    xc8 = snap(cx + 22.86)
    c8 = s.place("C", "C8", "1µF", "C_0603_1608Metric", (xc8, snap((yrail + ylbl) / 2)), tanchor="l")
    s.wire(c8["1"], (xc8, yrail)); s.label("MCU_EN", (xc8, yrail), justify_h="left")
    s.wire(c8["2"], (xc8, ylbl)); s.label("GND", (xc8, ylbl), justify_h="left")
    # unused GPIOs -> no-connect
    used = set(NETS) | {"2", "1", "40", "41"}
    for num, pin in mod.items():
        if num not in used:
            s.no_connect(pin)


def blk_uvlo(s, cx, cy):
    """Hardware UVLO backstop (U4 TPS3808G01, D28/DR-16). Pack divider R_uv1/R_uv2
    -> SENSE (VIT 0.405V); R_hys (RESET->SENSE) = positive-feedback hysteresis;
    C_sense filter; C_ct deglitch; C_uvdd bypass. RESET (open-drain, active-low)
    -> UVLO_RESET -> ESP EN gating. MR floats (internal 90k pull-up). Falling
    trip ~20.0V / release ~21.7V. (cx,cy)=U4 centre."""
    yg = snap(cy + 15.24)
    u4 = s.place("TPS3808DBV", "U4", "TPS3808G01DBVR", "Package_TO_SOT_SMD:SOT-23-6",
                 (cx, cy), angle=0, tanchor="u", tgap=15.24)
    SENSE, MR, CT = u4["5"], u4["3"], u4["4"]
    RESET, VDD, GND = u4["1"], u4["6"], u4["2"]
    s.no_connect(MR)                                  # internal 90k pull-up to VDD
    ys = SENSE[1]                                     # SENSE rail y (cy-2.54)

    # ---- pack divider: V24_FUSED -> R_uv1 -> SENSE -> R_uv2 -> GND ----
    xd = snap(cx - 33.02)
    r1 = s.place("R", "R_uv1", "5.16M", "R_0805_2012Metric", (xd, snap(ys - 3.81)), tanchor="l")
    r2 = s.place("R", "R_uv2", "100k", "R_0805_2012Metric", (xd, snap(ys + 3.81)), tanchor="l")
    yvf = snap(r1["1"][1] - 2.54)
    s.wire(r1["1"], (xd, yvf)); s.wire((xd, yvf), (snap(xd - 10.16), yvf))
    s.label("V24_FUSED", (snap(xd - 10.16), yvf), justify_h="right")
    s.wire(r2["2"], (xd, yg))
    xcs = snap(xd + 11.43)                            # C_sense column
    cse = s.place("C", "C_sense", "1nF", "C_0603_1608Metric", (xcs, snap(ys + 3.81)), tanchor="r")
    s.wire(cse["2"], (xcs, yg))
    s.wire((xd, ys), (xcs, ys)); s.wire((xcs, ys), SENSE)          # SENSE rail

    # ---- R_hys wrap: SENSE-rail -> up -> over the top -> down to RESET ----
    yh = snap(cy - 16.51)
    rh = s.place("R", "R_hys", "11.5M", "R_0805_2012Metric", (snap(cx - 16.51), yh),
                 angle=90, tanchor="ud", bw=7.62)
    hL = min(rh.values(), key=lambda p: p[0]); hR = max(rh.values(), key=lambda p: p[0])
    s.wire(hL, (hL[0], ys))                                        # left leg down onto SENSE rail
    s.wire(hR, (RESET[0], hR[1])); s.wire((RESET[0], hR[1]), RESET)  # right leg over to RESET

    # ---- RESET -> UVLO_RESET label (right) ----
    xr = snap(cx + 22.86)
    s.wire(RESET, (xr, RESET[1])); s.label("UVLO_RESET", (xr, RESET[1]), justify_h="left")

    # ---- CT -> C_ct -> GND (routed out left, clear of the body) ----
    xct = snap(cx - 13.97)
    s.wire(CT, (xct, CT[1]))
    cct = s.place("C", "C_ct", "10nF", "C_0603_1608Metric", (xct, snap(CT[1] + 3.81)), tanchor="l")
    s.wire(cct["2"], (xct, yg))

    # ---- VDD -> V3V3 + C_uvdd bypass (kept off the RESET column) ----
    yv = snap(VDD[1] - 3.81)
    s.wire(VDD, (VDD[0], yv))
    xcu, xv3 = snap(cx + 16.51), snap(cx + 26.67)
    s.wire((VDD[0], yv), (xcu, yv)); s.wire((xcu, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="left")
    cuv = s.place("C", "C_uvdd", "100nF", "C_0603_1608Metric", (xcu, snap(yv - 3.81)), tanchor="r")
    s.wire(cuv["1"], (xcu, snap(cuv["1"][1] - 2.54)))
    s.label("GND", (xcu, snap(cuv["1"][1] - 2.54)), justify_h="right")

    # ---- GND rail (R_uv2, C_sense, C_ct, U4 GND) ----
    s.wire((snap(xd - 7.62), yg), (cx, yg)); s.wire(GND, (cx, yg))
    s.label("GND", (snap(xd - 7.62), yg), justify_h="right")


def blk_sense(s, cx, cy):
    """24V sense divider (always-on): V24_FUSED -> R5 1.2M -> V24_SENSE -> R6
    100k -> GND; C5 100nF ADC tank. Full charge 29.2V -> ~2.25V (DR-6).
    V24_SENSE -> ESP GPIO1/ADC1_CH0. (cx,cy)=divider node."""
    yg = snap(cy + 13.97)
    r5 = s.place("R", "R5", "1.2M", "R_0805_2012Metric", (cx, snap(cy - 6.35)), tanchor="l")
    r6 = s.place("R", "R6", "100k", "R_0805_2012Metric", (cx, snap(cy + 6.35)), tanchor="l")
    node = (cx, cy)
    s.wire(r5["2"], node); s.wire(node, r6["1"])
    yt = r5["1"][1]
    s.wire(r5["1"], (cx, snap(yt - 2.54)))
    s.wire((cx, snap(yt - 2.54)), (snap(cx - 12.7), snap(yt - 2.54)))
    s.label("V24_FUSED", (snap(cx - 12.7), snap(yt - 2.54)), justify_h="right")
    s.wire(r6["2"], (cx, yg))
    xc, xlbl = snap(cx + 10.16), snap(cx + 20.32)
    s.wire(node, (xc, cy)); s.wire((xc, cy), (xlbl, cy))
    s.label("V24_SENSE", (xlbl, cy), justify_h="left")
    c5 = s.place("C", "C5", "100nF", "C_0603_1608Metric", (xc, snap(cy + 3.81)), tanchor="r")
    s.wire(c5["2"], (xc, yg))
    s.wire((snap(cx - 7.62), yg), (xc, yg)); s.wire((cx, yg), (cx, yg))
    s.label("GND", (snap(cx - 7.62), yg), justify_h="right")


def blk_rtc(s, cx, cy):
    """RV-3028-C7 ultra-low-power I2C RTC (45 nA, D23). VDD on always-on V3V3;
    C-bk backup cap on VBACKUP (rides a pack disconnect); C9 decoupling; I2C to
    MCU (R8/R9 pull-ups live on the MCU sheet). EVI->GND (unused), CLKOUT/INT
    unused. (cx,cy)=RTC centre."""
    yg = snap(cy + 16.51)
    rtc = s.place("RV-3028-C7", "RTC1", "RV-3028-C7", "Package_SON:MicroCrystal_C7_SON-8_1.5x3.2mm_P0.9mm",
                  (cx, cy), angle=0, tanchor="u", tgap=6.35)
    CLK, INT, SCL, SDA = rtc["1"], rtc["2"], rtc["3"], rtc["4"]
    VSS, VBK, VDD, EVI = rtc["5"], rtc["6"], rtc["7"], rtc["8"]
    # VDD (top-left) -> V3V3 rail + C9 decoupling
    yv = snap(VDD[1] - 3.81)
    s.wire(VDD, (VDD[0], yv))
    xc9, xv3 = snap(cx - 22.86), snap(cx - 33.02)
    s.wire((VDD[0], yv), (xc9, yv)); s.wire((xc9, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="right")
    # C9 hangs UP off the V3V3 rail (SCL/SDA are just below VDD — keep clear)
    c9 = s.place("C", "C9", "100nF", "C_0603_1608Metric", (xc9, snap(yv - 3.81)), tanchor="r")
    yc = snap(c9["1"][1] - 2.54)
    s.wire(c9["1"], (xc9, yc)); s.label("GND", (xc9, yc), justify_h="right")
    # VBACKUP (top) -> C-bk to GND (backup-only cap)
    yb = snap(VBK[1] - 6.35)
    s.wire(VBK, (VBK[0], yb))
    cbk = s.place("C", "C-bk", "22mF", "C_1210_3225Metric", (snap(cx + 12.7), snap(yb)), angle=90, tanchor="ud", bw=7.62)
    cbkL = min(cbk.values(), key=lambda p: p[0]); cbkR = max(cbk.values(), key=lambda p: p[0])
    s.wire((VBK[0], yb), cbkL)
    s.wire(cbkR, (cbkR[0], yb)); s.wire((cbkR[0], yb), (cbkR[0], snap(yb + 4.0)))
    s.label("GND", (cbkR[0], snap(yb + 4.0)), justify_h="left")
    # VSS -> GND
    s.wire(VSS, (VSS[0], yg)); s.label("GND", (VSS[0], yg), justify_h="left")
    # I2C left; EVI -> GND
    s.label("I2C_SCL", (snap(SCL[0] - 12.7), SCL[1]), justify_h="right"); s.wire((snap(SCL[0] - 12.7), SCL[1]), SCL)
    s.label("I2C_SDA", (snap(SDA[0] - 12.7), SDA[1]), justify_h="right"); s.wire((snap(SDA[0] - 12.7), SDA[1]), SDA)
    s.wire(EVI, (snap(EVI[0] - 10.16), EVI[1])); s.label("GND", (snap(EVI[0] - 10.16), EVI[1]), justify_h="right")
    # unused outputs
    s.no_connect(CLK); s.no_connect(INT)


# ---- sheet composition: several functional blocks per US-Letter sheet --------
def sheet(title, placements, hier_uuid=None, page="1"):
    """Compose blocks onto one sheet: each placement is (blk_fn, cx, cy).
    hier_uuid ties this sheet into the root hierarchy (else it's standalone)."""
    s = Sheet(title, hier_uuid=hier_uuid)
    for fn, cx, cy in placements:
        fn(s, snap(cx), snap(cy))
    s.add_junctions()
    if hier_uuid:
        s.sch.sheetInstances = [HierarchicalSheetInstance(instancePath="/" + hier_uuid, page=page)]
    return s


# ---- the battery-side hierarchy: one child .kicad_sch per functional sheet ----
SHEETS = [
    ("sheet_power", "Battery — Power path", [
        (blk_input_protection, 78, 62), (blk_always_on_power, 205, 62),
        (blk_ssr, 78, 140), (blk_u2, 205, 140), (blk_pwr_flags, 120, 105)]),
    ("sheet_periph", "Battery — Peripherals & comms", [
        (blk_rs485, 90, 62), (blk_rtc, 95, 140)]),
    ("sheet_super", "Battery — Supervisor", [
        (blk_uvlo, 82, 82), (blk_sense, 210, 68)]),
    ("sheet_usb", "Battery — USB maintenance power", [
        (blk_usb_power, 75, 62), (blk_usb_failsafe, 190, 62)]),
    ("sheet_isors485_1", "Battery — Isolated RS-485 read (ch.1)",
        [(lambda s, cx, cy: blk_iso_ch(s, cx, cy, 1), 95, 115)]),
    ("sheet_isors485_2", "Battery — Isolated RS-485 read (ch.2)",
        [(lambda s, cx, cy: blk_iso_ch(s, cx, cy, 2), 95, 115)]),
    ("sheet_mcu", "Battery — MCU (ESP32-S3)", [(blk_mcu, 145, 105)]),
    ("sheet_conn", "Battery — Connectors & I/O", [
        (blk_j1_btn, 55, 52), (blk_j2_rj45, 210, 52),
        (blk_usbc, 60, 120), (blk_exp, 150, 145), (blk_j5_dbg, 175, 60)]),
]


def build_root(defs):
    """Root sheet text (KiCad-10 format — kiutils' KiCad-6 sheet serialization
    won't load in KiCad 10). One hierarchical-sheet box per child; shared nets
    (V3V3, GND, V24_*, RS485_*, I2C_*, EXP_*, …) connect across the hierarchy via
    their GLOBAL labels, so no sheet pins are needed."""
    # 2 cols x 4 rows, kept entirely above the bottom-right title block
    # (title block ~ x159+, y185+ on USLetter landscape). Boxes end by y170.
    x0, y0, dx, dy, w, h = 38, 20, 120, 40, 92, 30
    blocks = []
    for i, (name, title, hu) in enumerate(defs):
        r, c = divmod(i, 2); px, py = x0 + c*dx, y0 + r*dy
        blocks.append(
            f'\t(sheet\n\t\t(at {px} {py}) (size {w} {h})\n'
            f'\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)\n'
            f'\t\t(fields_autoplaced yes)\n'
            f'\t\t(stroke (width 0.1524) (type solid))\n\t\t(fill (color 0 0 0 0.0000))\n'
            f'\t\t(uuid "{hu}")\n'
            f'\t\t(property "Sheetname" "{title}" (at {px+3} {py+h/2-2} 0)\n'
            f'\t\t\t(effects (font (size 3.0 3.0) (bold yes)) (justify left)))\n'
            f'\t\t(property "Sheetfile" "{name}.kicad_sch" (at {px+3} {py+h/2+3} 0)\n'
            f'\t\t\t(effects (font (size 2.0 2.0)) (justify left)))\n'
            f'\t\t(instances (project "{PROJECT}" (path "/" (page "{i+2}"))))\n\t)')
    return (f'(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n'
            f'\t(generator_version "10.0")\n\t(uuid "{_uuid()}")\n\t(paper "USLetter")\n'
            f'\t(title_block (title "Volthium reader — battery-side (root)") '
            f'(company "Volthium reader"))\n\t(lib_symbols)\n'
            + "\n".join(blocks)
            + '\n\t(sheet_instances (path "/" (page "1")))\n)\n')


def write_project():
    """Minimal .kicad_pro + sym-lib-table so KiCad opens the hierarchy cleanly."""
    import json
    (OUT / f"{PROJECT}.kicad_pro").write_text(json.dumps({
        "board": {}, "boards": [], "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 1},
        "schematic": {"legacy_lib_list": [], "legacy_lib_dir": ""},
        "sheets": [], "text_variables": {},
    }, indent=2))
    rel = os.path.relpath(str(LIB), str(OUT))
    (OUT / "sym-lib-table").write_text(
        f'(sym_lib_table\n  (version 7)\n  (lib (name "volthium")(type "KiCad")(uri "{rel}")(options "")(descr ""))\n)\n')


def kcli(*a): return subprocess.run(["kicad-cli", *a], capture_output=True, text=True)

MM = 2.8346   # schematic mm -> PDF points

def render(s, name, crops=()):
    """Per-child: readability gate -> write .kicad_sch -> PDF -> PNG (+ crops).
    ERC is run once on the ROOT (children are hierarchy members; their instance
    paths only resolve through the root, so a standalone child ERC is moot)."""
    bad = s.gate()
    if bad:
        print(f"[{name}] READABILITY GATE FAILED:"); [print("  "+b) for b in bad]
        return False
    print(f"[{name}] readability gate: clean")
    schf = OUT / f"{name}.kicad_sch"; s.sch.to_file(str(schf))
    kcli("sch", "export", "pdf", "-o", str(OUT/f"{name}.pdf"), str(schf))
    import fitz
    doc = fitz.open(str(OUT/f"{name}.pdf"))
    doc[0].get_pixmap(matrix=fitz.Matrix(7, 7)).save(str(OUT/f"{name}.png"))
    for i, (x1, y1, x2, y2) in enumerate(crops):
        clip = fitz.Rect(x1*MM, y1*MM, x2*MM, y2*MM)
        doc[0].get_pixmap(matrix=fitz.Matrix(11, 11), clip=clip).save(str(OUT/f"{name}.crop{i}.png"))
    print(f"[{name}] PNG{' + '+str(len(crops))+' crops' if crops else ''} written")
    return True

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    defs = [(name, title, _uuid()) for (name, title, _) in SHEETS]
    ok = True
    for i, ((name, title, placements), (_, _, hu)) in enumerate(zip(SHEETS, defs)):
        s = sheet(title, placements, hier_uuid=hu, page=str(i + 2))
        ok &= render(s, name)
    # root + project
    rootf = OUT / f"{PROJECT}.kicad_sch"; rootf.write_text(build_root(defs))
    write_project()
    r = kcli("sch", "erc", "-o", str(OUT / "root.erc.rpt"), str(rootf))
    rpt = open(OUT / "root.erc.rpt").read() if (OUT / "root.erc.rpt").exists() else ""
    nd = rpt.count("dangling") + rpt.count("[pin_not_connected]")
    npd = rpt.count("power_pin_not_driven")
    print(f"[ROOT hierarchy] ERC rc={r.returncode}; dangling/unconn={nd}; power_pin_not_driven={npd}")
    kcli("sch", "export", "pdf", "-o", str(OUT / f"{PROJECT}.pdf"), str(rootf))
    print(f"[ROOT] wrote {PROJECT}.kicad_sch + .kicad_pro + full {PROJECT}.pdf")
    return 0 if ok else 2

if __name__ == "__main__":
    sys.exit(main())
