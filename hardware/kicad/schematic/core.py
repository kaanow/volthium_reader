#!/usr/bin/env python3
"""CP2 schematic generator CORE — shared by both board entry points
(build.py = battery side, build_display.py = display side).

Philosophy (opposite of the retired v1 graphical netlist):
  - WIRES are the intra-block connectivity; global labels only for real
    global nets. Every symbol placed + every wire routed explicitly, on the
    1.27 mm grid. The code renders MY layout; it never auto-places.
  - Readability is a HARD geometric gate that sees TEXT and LABELS, not just
    symbol bodies (a symbol-only box check is blind to the two defects that
    actually ship: ref/value text over the symbol, and a net line piercing a
    label chevron). US Letter. Inspect the rendered PDF/PNG per-region.
  - Every gate (readability/glyph/title-block, netlist intent==actual,
    GOLDEN contracts, exact-part variants, strict full ERC) lives HERE, in
    the same chokepoint as the writes, so no board can skip one.

An entry point supplies the per-project data: configure(...) then
run(SHEETS, GOLDEN, EXACT_PARTS, ERC_ACCEPTED). Everything geometric,
symbol-sourcing and verification stays board-agnostic and shared.
"""
from __future__ import annotations
import copy as _copy, math, os, re, shutil, subprocess, sys, uuid
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.schematic import Schematic
from kiutils.items.schitems import (SchematicSymbol, GlobalLabel, Connection,
    SymbolProjectPath, SymbolProjectInstance, HierarchicalSheet,
    HierarchicalSheetInstance, HierarchicalSheetProjectInstance,
    HierarchicalSheetProjectPath)
from kiutils.items.common import Position, Property, Effects, Stroke, Justify, TitleBlock, Fill

HERE = Path(__file__).resolve().parent
KROOT = HERE.parent
LIB = KROOT / "libraries" / "volthium.kicad_sym"

# Per-project config — an entry point MUST call configure() before run().
# Defaults match the original single-project generator (battery side) so the
# documented rebuild command's behavior is unchanged.
PROJECT = "volthium_reader"
OUT = HERE / "build"            # generated schematics + review renders (gitignored)
ROOT_TITLE = "Volthium reader — battery-side (root)"


def configure(project, out_dirname, root_title):
    """Bind the core to one project: netlist/instance-path project name, the
    output directory (sibling of this file), and the root sheet title."""
    global PROJECT, OUT, ROOT_TITLE
    PROJECT = project
    OUT = HERE / out_dirname
    ROOT_TITLE = root_title


GRID = 1.27
CHARW = 0.85   # mm per char at 1.27 mm text height (approx, for box gate)
TXTH = 1.27

# ---- symbol sourcing -------------------------------------------------------
# Every symbol is embedded self-contained under the "volthium:" nickname (so
# the .kicad_sch needs no external lib table). Sources: the project lib for
# custom/generic parts, KiCad's stock libs for the ICs. Derived (extends)
# stock symbols are FLATTENED to their pin-bearing ancestor on embed.
def _find_kicad_share():
    """KiCad data root, cross-platform (CP2 review F04). Override order:
    KICAD_SHARE env var, then the default install root per OS."""
    lad = os.environ.get("LOCALAPPDATA")
    cands = [os.environ.get("KICAD_SHARE"),
             "/Applications/KiCad/KiCad.app/Contents/SharedSupport",   # macOS
             "C:/Program Files/KiCad/10.0/share/kicad",                # Windows (all-users)
             f"{lad}/Programs/KiCad/10.0/share/kicad" if lad else None,  # Windows (per-user, F07)
             "/usr/share/kicad"]                                       # Linux
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "symbols")):
            return c
    raise SystemExit("[env] KiCad share dir not found - set KICAD_SHARE to the"
                     " directory that contains symbols/ and footprints/")

KICAD_SHARE = _find_kicad_share()
STOCK = os.environ.get("KICAD10_SYMBOL_DIR", f"{KICAD_SHARE}/symbols")


def _find_kicad_cli():
    """Resolve kicad-cli without requiring an installer-modified PATH."""
    override = os.environ.get("KICAD_CLI")
    if override:
        cli = Path(override).expanduser()
        if cli.is_file():
            return cli.resolve()
        raise SystemExit(f"[env] KICAD_CLI does not name a file: {cli}")

    exe = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    share = Path(KICAD_SHARE)
    # SAME-ROOT pairing first (kicad skill v0.2.0, Windows reviewer's rule:
    # never combine an executable from one KiCad install with share/ from
    # another). A PATH-resolved kicad-cli may belong to a DIFFERENT install
    # than the discovered share tree — prefer the discovered root's own
    # bin, then fall back to PATH and the standard locations.
    cands = []
    if len(share.parents) >= 2:
        cands.append(share.parents[1] / "bin" / exe)
    if sys.platform == "darwin":
        cands.append(share.parent / "MacOS" / exe)
    cands.append(shutil.which("kicad-cli"))

    lad = os.environ.get("LOCALAPPDATA")
    pf = os.environ.get("ProgramFiles")
    pfx86 = os.environ.get("ProgramFiles(x86)")
    cands.extend([
        Path(lad) / "Programs/KiCad/10.0/bin" / exe if lad else None,
        Path(pf) / "KiCad/10.0/bin" / exe if pf else None,
        Path(pfx86) / "KiCad/10.0/bin" / exe if pfx86 else None,
        Path("/Applications/KiCad/KiCad.app/Contents/MacOS") / exe,
        Path("/usr/bin") / exe,
    ])
    for candidate in cands:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit(
        "[env] kicad-cli executable not found - set KICAD_CLI to its full path"
    )


KICAD_CLI = _find_kicad_cli()
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
    "R-78E3.3-0.5":     (f"{STOCK}/Converter_DCDC.kicad_sym",      "R-78E3.3-0.5"),
    "SW_Push":          (f"{STOCK}/Switch.kicad_sym",               "SW_Push"),
    "ESP32-S3-WROOM-1": (f"{STOCK}/RF_Module.kicad_sym",           "ESP32-S3-WROOM-1"),
    "AP2112K-3.3":      (f"{STOCK}/Regulator_Linear.kicad_sym",    "AP2112K-3.3"),
    "2N7002":           (f"{STOCK}/Transistor_FET.kicad_sym",      "2N7002"),
    "ADM2587E":         (f"{STOCK}/Interface_UART.kicad_sym",      "ADM2587E"),
    "SM712_SOT23":      (f"{STOCK}/Diode.kicad_sym",               "SM712_SOT23"),
    "FerriteBead":      (f"{STOCK}/Device.kicad_sym",              "FerriteBead"),
    "USBLC6-2SC6":      (f"{STOCK}/Power_Protection.kicad_sym",    "USBLC6-2SC6"),
    "TCAN332":          (f"{STOCK}/Interface_CAN_LIN.kicad_sym",   "TCAN332"),
    "NUP2105L":         (f"{STOCK}/Power_Protection.kicad_sym",    "NUP2105L"),
    "Conn_01x04":       (f"{STOCK}/Connector_Generic.kicad_sym",   "Conn_01x04"),
    "Conn_02x03_Odd_Even": (f"{STOCK}/Connector_Generic.kicad_sym", "Conn_02x03_Odd_Even"),
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
    sl = SymbolLib.from_file(libfile, encoding="utf-8")   # F07: never locale-decode
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
        # F08: two tied power_output pins trip KiCad's [pin_to_pin] ERROR —
        # they are ONE physical rail split across two package pins. Retype
        # the twin (7) passive; pin 2 keeps power_output, so
        # power_pin_not_driven coverage of the rail is unchanged.
        for p in allpins:
            if p.number == "7":
                p.position.Y = 2.54
                p.electricalType = "passive"
    # Restore the library author's pin-name visibility. kiutils drops KiCad-10's
    # nested `(hide yes)`, un-hiding names that were never meant to render (the
    # USBLC6/SM712/Conn_01x0N mush, stray G/D/S on FETs). Blanking to "~" is the
    # serialization-proof way to hide them: renders identically to stock KiCad,
    # and pin NUMBERS stay for the footprint map.
    # Per-instance readability override: the 2N7002 NMOS pair (Q3/Q4 fail-safe
    # bypass) reads better WITH its S/G/D pin letters (user call 2026-07-23) —
    # the stock lib hides them; keep them visible for this symbol only. The
    # P-FETs (Q_PMOS_GSD) already show theirs.
    if _raw_pin_names_hidden(libfile, entry) and name not in ("2N7002",):
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


_FP_DIRS = [os.environ.get("KICAD10_FOOTPRINT_DIR", f"{KICAD_SHARE}/footprints"),
            str(KROOT / "footprints")]   # repo-local volthium.pretty (see its README)
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
    def __init__(self, title, hier_uuid=None, root_uuid=None):
        self.sch = Schematic.create_new()
        if not self.sch.uuid:
            self.sch.uuid = _uuid()          # this sheet's own uuid
        # instance path: standalone = "/<own uuid>"; as a hierarchy child =
        # "/<ROOT FILE uuid>/<sheet-symbol uuid in the root>". The root prefix
        # is NOT optional: without it kicad-cli still resolves refs and LABELED
        # nets, but silently DROPS every unlabeled local net from the netlist
        # and flags their wires dangling — that was the entire 19-item
        # "dangling baseline" (19 real pin-to-pin nets missing from the
        # exported netlist, invisible in the render).
        if hier_uuid and root_uuid:
            self.hier = f"{root_uuid}/{hier_uuid}"
        else:
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
        self.pin_map = {}      # ref -> {pin_number: (x,y)}   for the netlist gate
        self.nc_pts = set()    # no_connect marker positions  for the netlist gate

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
        self.pin_map[ref] = dict(pins)
        return pins

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            if abs(a[0]-b[0]) < 1e-6 and abs(a[1]-b[1]) < 1e-6:
                continue                    # zero-length: KiCad noise, poisons the netlist gate
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
        # (3) a PIN landing on the interior of a wire (a cap tapped onto a bus
        # rail at a non-endpoint). KiCad does NOT connect that without a
        # junction — caught by the netlist gate (C_usb2 on the 3V3_USB bus).
        for ref, pins in self.pin_map.items():
            for num, p in pins.items():
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
        self.nc_pts.add((pos[0], pos[1]))

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
    def text(self, txt, pos, justify="left"):
        """Free annotation text (interpretability notes, region titles)."""
        from kiutils.items.schitems import Text as SchText
        t = SchText(text=txt, position=Position(X=pos[0], Y=pos[1], angle=0),
                    effects=Effects(justify=Justify(horizontally=justify)), uuid=_uuid())
        self.sch.texts.append(t)

    def dashed_line(self, a, b):
        """Sheet-level dashed line (isolation-barrier demarcation)."""
        from kiutils.items.schitems import PolyLine
        self.sch.shapes.append(PolyLine(
            points=[Position(X=a[0], Y=a[1]), Position(X=b[0], Y=b[1])],
            stroke=Stroke(width=0.254, type="dash"), uuid=_uuid()))

    def dashed_rect(self, a, b):
        """Sheet-level dashed rectangle (provisioning-region box)."""
        from kiutils.items.schitems import Rectangle as SchRect
        self.sch.shapes.append(SchRect(
            start=Position(X=a[0], Y=a[1]), end=Position(X=b[0], Y=b[1]),
            stroke=Stroke(width=0.254, type="dash"), uuid=_uuid()))

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
                # Annotation symbols (#FLG…): their auto REF text is page
                # furniture, but their VALUE text ("PWR_FLAG") renders just
                # like any other text and a net-label flag printed over it is
                # a real readability defect (display-iter1 F15) — so skip
                # only the ref text, keep the value in the check.
                pref, _, ptxt = tref.partition(":")
                if pref.startswith("#") and ptxt.startswith("#"):
                    continue                                  # "#FLG1:#FLG1"
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
        # -------- title-block keep-out --------
        # The page title block (bottom-right of USLetter landscape) is page
        # furniture no box list models — an annex drifted into it and every
        # gate passed while the sheet was unreadable. Nothing drawn may enter.
        TB = (144.8, 167.6, 260.0, 200.0)
        for kind, boxes in (("sym", self.sym_boxes), ("txt", self.txt_boxes)):
            for bx in boxes:
                if ov(bx[:4], TB) and not bx[4].split(":")[0].startswith("#"):
                    bad.append(f"[title-block] {kind}:{bx[4]} enters the title block")
        for (lx1, ly1, lx2, ly2, text, anch) in self.lbl_boxes:
            if ov((lx1, ly1, lx2, ly2), TB):
                bad.append(f"[title-block] label '{text}' enters the title block")
        for (p, q) in self.wires:
            for t in [i/24 for i in range(25)]:
                x = p[0] + (q[0]-p[0])*t; y = p[1] + (q[1]-p[1])*t
                if TB[0] < x < TB[2] and TB[1] < y < TB[3]:
                    bad.append(f"[title-block] wire {p}->{q} enters the title block"); break
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
                # a rail that TAPS one of this part's pins mid-segment (pin-
                # interior junction) legitimately grazes the body's top edge
                if any(_on_seg(op, p, q) for op in own):
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


# ---- sheet composition: several functional blocks per US-Letter sheet --------
def sheet(title, placements, hier_uuid=None, page="1", root_uuid=None):
    """Compose blocks onto one sheet: each placement is (blk_fn, cx, cy).
    hier_uuid + root_uuid tie this sheet into the root hierarchy (else it's
    standalone). Both the symbol instance paths and the sheet_instances entry
    must carry the FULL "/<root uuid>/<sheet-symbol uuid>" path — see
    Sheet.__init__ for what silently breaks otherwise."""
    s = Sheet(title, hier_uuid=hier_uuid, root_uuid=root_uuid)
    for fn, cx, cy in placements:
        fn(s, snap(cx), snap(cy))
    s.add_junctions()
    if hier_uuid:
        s.sch.sheetInstances = [HierarchicalSheetInstance(
            instancePath="/" + s.hier, page=page)]
    return s



def build_root(defs, root_uuid):
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
            f'\t(generator_version "10.0")\n\t(uuid "{root_uuid}")\n\t(paper "USLetter")\n'
            f'\t(title_block (title "{ROOT_TITLE}") '
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
    }, indent=2), encoding="utf-8")
    # F08: the old table pointed at the PROJECT lib with a BARE relative URI —
    # resolved against process CWD (not the project dir), and the project lib
    # anyway lacks the stock-derived symbols we embed (138 [lib_symbol_issues]
    # of the 141 strict-ERC messages, in two layers). Deterministic fix:
    # write a GENERATED library of exactly the flattened symbols this build
    # embedded (_SYMCACHE) next to the project, referenced via ${KIPRJMOD}.
    # Self-contained in build/, host-independent, always complete and always
    # identical to the embedded cache.
    gen = SymbolLib()
    gen.generator = "volthium_build"
    gen.symbols = [_SYMCACHE[k] for k in sorted(_SYMCACHE)]
    gen.filePath = str(OUT / "volthium.kicad_sym")
    gen.to_file(encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        '(sym_lib_table\n  (version 7)\n  (lib (name "volthium")(type "KiCad")'
        '(uri "${KIPRJMOD}/volthium.kicad_sym")(options "")(descr ""))\n)\n',
        encoding="utf-8")
    # Repo-local footprint library (vendored/authored parts absent from the
    # stock libs — see hardware/kicad/footprints/README.md). Declared per
    # project so kicad-cli ERC can resolve `volthium:` footprint links.
    (OUT / "fp-lib-table").write_text(
        '(fp_lib_table\n  (version 7)\n  (lib (name "volthium")(type "KiCad")'
        '(uri "${KIPRJMOD}/../../footprints/volthium.pretty")(options "")(descr ""))\n)\n',
        encoding="utf-8")


def kcli(*a):
    return subprocess.run([str(KICAD_CLI), *a], capture_output=True, text=True)

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
    schf = OUT / f"{name}.kicad_sch"; s.sch.to_file(str(schf), encoding="utf-8")
    kcli("sch", "export", "pdf", "-o", str(OUT/f"{name}.pdf"), str(schf))
    import fitz
    doc = fitz.open(str(OUT/f"{name}.pdf"))
    doc[0].get_pixmap(matrix=fitz.Matrix(7, 7)).save(str(OUT/f"{name}.png"))
    for i, (x1, y1, x2, y2) in enumerate(crops):
        clip = fitz.Rect(x1*MM, y1*MM, x2*MM, y2*MM)
        doc[0].get_pixmap(matrix=fitz.Matrix(11, 11), clip=clip).save(str(OUT/f"{name}.crop{i}.png"))
    print(f"[{name}] PNG{' + '+str(len(crops))+' crops' if crops else ''} written")
    return True
# ---------------- netlist gate: generator intent vs KiCad ground truth -------
# The readability/glyph gates judge the DRAWING; nothing verified that KiCad's
# CONNECTIVITY matches what the generator meant — a wire missing a pin by one
# grid step renders as "basically touching", ships past every visual pass, and
# was being absorbed into an accepted "dangling baseline". This gate derives
# the intended netlist from the generator's own wire graph (union-find over
# wire endpoints, T-junctions, pins and labels — X-crossings do NOT join) and
# diffs it against `kicad-cli sch export netlist` on the assembled hierarchy.

def _uf_make():
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        parent[find(a)] = find(b)
    return find, union

def _on_seg(p, a, b, eps=0.01):
    """p strictly on segment ab (incl. endpoints). Degenerate (zero-length)
    segments match NOTHING — one such wire would otherwise union every point
    on the sheet into a single blob (found the hard way)."""
    ax, ay = a; bx, by = b; px, py = p
    L2 = (bx-ax)**2 + (by-ay)**2
    if L2 < eps*eps: return False
    cross = (bx-ax)*(py-ay) - (by-ay)*(px-ax)
    if abs(cross) > eps * max(1.0, abs(bx-ax)+abs(by-ay)): return False
    dot = (px-ax)*(bx-ax) + (py-ay)*(by-ay)
    return -eps <= dot <= L2 + eps

def _key(p): return (round(p[0]*100), round(p[1]*100))

def intended_nets(built):
    """[(frozenset{(ref,pin)}, {label texts}, [nc-violations])] across sheets,
    with same-text labels merging nets globally (global-label semantics)."""
    find, union = _uf_make()
    pin_at = []           # ((ref,pin), key)
    lbl_at = []           # (text, key)
    ncs = []
    for name, s in built:
        P = lambda p: ("pt", name, _key(p))     # coordinates are PER-SHEET —
        wires = [(("w", name, i, 0), ("w", name, i, 1), a, b)
                 for i, (a, b) in enumerate(s.wires)]
        # wire endpoints by coordinate + T-junctions
        for wid0, wid1, a, b in wires:
            union(wid0, P(a)); union(wid1, P(b))
            union(wid0, wid1)
        for _, _, a, b in wires:
            for wid0, wid1, c, d in wires:
                if (a, b) == (c, d): continue
                for p in (a, b):
                    if _key(p) not in (_key(c), _key(d)) and _on_seg(p, c, d):
                        union(P(p), wid0)
        # pins + labels join at their exact point or on a wire segment
        for ref, pins in s.pin_map.items():
            for num, pt in pins.items():
                node = ("pin", ref, num)
                pin_at.append(((ref, num), node))
                union(node, P(pt))
                for wid0, _, a, b in wires:
                    if _on_seg(pt, a, b): union(node, wid0)
        for (lx1, ly1, lx2, ly2, text, anch) in s.lbl_boxes:
            node = ("lbl", name, _key(anch), text)
            lbl_at.append((text, node))
            union(node, P(anch))
            for wid0, _, a, b in wires:
                if _on_seg(anch, a, b): union(node, wid0)
        for pt in s.nc_pts:
            ncs.append((name, _key(pt)))
    # per-sheet alias check BEFORE the global merge — a false wire-graph merge
    # shows up here with the sheet named, instead of as one design-wide blob
    per_sheet = {}
    for text, node in lbl_at:
        sheetname = node[1]
        per_sheet.setdefault((sheetname, find(node)), set()).add(text)
    alias_errs = [f"[net-alias] {sn}: one net carries labels {sorted(ts)}"
                  for (sn, _), ts in per_sheet.items() if len(ts) > 1]
    # merge same-text labels across the hierarchy (global labels)
    first_of = {}
    for text, node in lbl_at:
        if text in first_of: union(node, first_of[text])
        else: first_of[text] = node
    groups = {}
    for (refpin, node) in pin_at:
        groups.setdefault(find(node), {"pins": set(), "labels": set()})["pins"].add(refpin)
    for (text, node) in lbl_at:
        groups.setdefault(find(node), {"pins": set(), "labels": set()})["labels"].add(text)
    return [(frozenset(g["pins"]), g["labels"]) for g in groups.values()], alias_errs

def kicad_netlist(rootf):
    """{netname: frozenset{(ref,pin)}} from kicad-cli (ground truth)."""
    out = OUT / (Path(rootf).stem + ".net")
    r = kcli("sch", "export", "netlist", "-o", str(out), str(rootf))
    if r.returncode != 0:
        raise SystemExit(f"[netlist-gate] export failed: {r.stderr[:300]}")
    txt = out.read_text(encoding="utf-8")
    nets = {}
    # paren-balanced scan (a regex-to-blank-line parse drops one-line nets)
    i = 0
    while True:
        i = txt.find("(net", i)
        if i < 0: break
        if txt[i+4] not in " \n\t":      # skip "(nets" / "(netclass"
            i += 4; continue
        depth = 0; j = i
        while j < len(txt):
            if txt[j] == "(": depth += 1
            elif txt[j] == ")":
                depth -= 1
                if depth == 0: break
            j += 1
        blk = txt[i:j+1]; i = j + 1
        nm = re.search(r'\(name "([^"]*)"\)', blk)
        if not nm: continue
        nodes = frozenset(re.findall(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', blk))
        nets[nm.group(1)] = nodes
    return nets


def check_golden(knets, golden):
    """Read-back check: every GOLDEN contract against kicad's netlist."""
    bad = []
    net_of = {}
    for kname, nodes in knets.items():
        for rp in nodes: net_of[rp] = kname
    for entry in golden:
        kind, a = entry[0], entry[1]
        if kind == "on":
            netname, why = entry[2], entry[3]
            got = net_of.get(a)
            if got != netname:
                bad.append(f"[golden] {a} expected on '{netname}' but on '{got}' — {why}")
        elif kind == "same":
            b, why = entry[2], entry[3]
            na, nb = net_of.get(a), net_of.get(b)
            if na is None or na != nb:
                bad.append(f"[golden] {a} ({na}) should share a net with {b} ({nb}) — {why}")
        elif kind == "diff":
            b, why = entry[2], entry[3]
            na, nb = net_of.get(a), net_of.get(b)
            if na is not None and na == nb:
                bad.append(f"[golden] {a} and {b} both on '{na}' but must differ — {why}")
    return bad


def verify_netlist(built, rootf, golden, exact_parts):
    """Every intended multi-pin net must be EXACTLY a KiCad net (and carry its
    label's name); every multi-pin KiCad net must be intended. Returns issues."""
    intent, bad = intended_nets(built)
    knets = kicad_netlist(rootf)
    real = lambda pins: frozenset(rp for rp in pins if not rp[0].startswith("#"))
    kicad_by_member = {}
    for kname, nodes in knets.items():
        for rp in nodes: kicad_by_member[rp] = (kname, nodes)
    for pins, labels in intent:
        rp_pins = real(pins)
        if len(rp_pins) < 2 and not labels:
            continue                      # single-pin unlabeled: ERC's domain
        if not rp_pins:
            continue                      # power-flag-only nets
        probe = sorted(rp_pins)[0]
        hit = kicad_by_member.get(probe)
        if hit is None:
            bad.append(f"[net-missing] {probe} not in any KiCad net (intended {sorted(labels) or sorted(rp_pins)})")
            continue
        kname, nodes = hit
        if nodes != rp_pins:
            bad.append(f"[net-mismatch] intended {sorted(labels) or [probe]}: "
                       f"kicad '{kname}' has {sorted(set(nodes) ^ set(rp_pins))} extra/missing")
        if labels and kname.lstrip("/") not in labels:
            bad.append(f"[net-name] intended label {sorted(labels)} but kicad named it '{kname}'")
    intents = {real(p) for p, _ in intent}
    for kname, nodes in knets.items():
        if len(nodes) >= 2 and not kname.startswith("unconnected-") and nodes not in intents:
            bad.append(f"[net-extra] kicad net '{kname}' {sorted(nodes)} not intended")
    # [part-short]: a 2-3 pin discrete (R/C/L/D/Q) with two pins on the SAME
    # net is a drawing error, not a circuit. This is the spec-level rule the
    # intent==actual diff cannot express: it caught nothing until Q5's S/D
    # were fused to V3V3 by a swapped-pin-side wire pattern (user-caught).
    # Multi-unit ICs (U/MOD refs) legitimately stack same-named pins - exempt.
    net_of = {}
    for kname, nodes in knets.items():
        for rp in nodes: net_of[rp] = kname
    for name_, s in built:
        for ref, pins in s.pin_map.items():
            if not re.match(r"^(R|C|L|D|Q|TVS|F)[0-9_]", ref) and                not re.match(r"^(R|C|L|D|Q|TVS|F)_", ref): continue
            seen = {}
            for num in pins:
                kn = net_of.get((ref, num))
                if kn is None or kn.startswith("unconnected-"): continue
                if kn in seen:
                    bad.append(f"[part-short] {ref} pins {seen[kn]}+{num} both on net '{kn}'")
                seen[kn] = num
    bad += check_golden(knets, golden)
    bad += check_exact_parts(rootf, exact_parts)
    return bad


def check_exact_parts(rootf, exact_parts):
    """Read (ref, value, footprint) from the exported netlist and require the
    EXACT_PARTS variants. Returns issues."""
    txt = (OUT / (Path(rootf).stem + ".net")).read_text(encoding="utf-8")
    comps = dict()
    for m in re.finditer(r'\(ref "([^"]+)"\)\s*\(value "([^"]*)"\)\s*'
                         r'\(footprint "([^"]*)"\)', txt):
        comps.setdefault(m.group(1), (m.group(2), m.group(3)))
    bad = []
    for ref, (val, fp) in exact_parts.items():
        got = comps.get(ref)
        if got is None:
            bad.append(f"[exact-part] {ref}: not found in exported netlist")
        elif got != (val, fp):
            bad.append(f"[exact-part] {ref}: netlist has value/footprint "
                       f"{got}, contract requires ({val!r}, {fp!r})")
    return bad



def _parse_erc(rptfile):
    """[(class, severity, object-text)] from a kicad-cli ERC report."""
    out, cur = [], None
    for line in open(rptfile, encoding="utf-8"):
        m = re.match(r"\[(\w+)\]: (.*)", line.strip())
        if m:
            cur = [m.group(1), "?", m.group(2)]
            out.append(cur)
        elif cur is not None:
            s = line.strip()
            if s.startswith(";"):
                cur[1] = s.lstrip("; ").strip()
            elif s.startswith("@"):
                cur[2] += " | " + s
    return out


def run_strict_erc(rootf, erc_accepted):
    """Full-severity ERC; returns count of UNACCOUNTED messages (0 = pass)."""
    r = kcli("sch", "erc", "--severity-all", "--exit-code-violations",
             "-o", str(OUT / "root.erc.rpt"), str(rootf))
    if not (OUT / "root.erc.rpt").exists():
        print(f"[ROOT ERC strict] report missing (rc={r.returncode}) — FAIL")
        return 1
    viol = _parse_erc(OUT / "root.erc.rpt")
    unacc, used = [], set()
    for cls, sev, obj in viol:
        for (acls, tok), _why in erc_accepted.items():
            if cls == acls and tok in obj:
                used.add((acls, tok))
                break
        else:
            unacc.append((cls, sev, obj))
    print(f"[ROOT ERC strict] rc={r.returncode}; {len(viol)} message(s), "
          f"{len(viol) - len(unacc)} accepted (ERC_ACCEPTED), "
          f"{len(unacc)} unaccounted")
    for cls, sev, obj in unacc[:25]:
        print(f"  [{cls}] {sev}: {obj[:120]}")
    for key in erc_accepted.keys() - used:
        print(f"  note: ERC_ACCEPTED entry {key} matched nothing (stale?)")
    return len(unacc)


def run(sheets_def, golden, exact_parts, erc_accepted):
    """The whole pipeline for one project (the old main()): build every child
    sheet behind the readability gate, assemble root + project files, then the
    netlist / GOLDEN / exact-part / strict-ERC gates. Returns the exit code."""
    print(f"[env] KiCad share: {KICAD_SHARE}")
    print(f"[env] KiCad CLI: {KICAD_CLI}")
    OUT.mkdir(parents=True, exist_ok=True)
    root_uuid = _uuid()                     # generated FIRST: children need it
    defs = [(name, title, _uuid()) for (name, title, _) in sheets_def]
    ok = True
    built = []
    for i, ((name, title, placements), (_, _, hu)) in enumerate(zip(sheets_def, defs)):
        s = sheet(title, placements, hier_uuid=hu, page=str(i + 2), root_uuid=root_uuid)
        ok &= render(s, name)
        built.append((name, s))
    # root + project
    rootf = OUT / f"{PROJECT}.kicad_sch"
    rootf.write_text(build_root(defs, root_uuid), encoding="utf-8")
    write_project()
    if not ok:
        print("[NETLIST gate] SKIPPED — a sheet failed its readability gate, so"
              " the files on disk are STALE (render() refuses to write a failed"
              " sheet); netlist comparison would judge the OLD drawing.")
        return 2
    nbad = verify_netlist(built, rootf, golden, exact_parts)
    if nbad:
        print(f"[NETLIST GATE FAILED] {len(nbad)} issue(s):")
        for b in nbad: print("  " + b)
        ok = False
    else:
        print("[NETLIST gate] generator intent == kicad-cli netlist: clean")
    nerc = run_strict_erc(rootf, erc_accepted)
    if nerc:
        ok = False
    kcli("sch", "export", "pdf", "-o", str(OUT / f"{PROJECT}.pdf"), str(rootf))
    print(f"[ROOT] wrote {PROJECT}.kicad_sch + .kicad_pro + full {PROJECT}.pdf")
    return 0 if ok else 2

