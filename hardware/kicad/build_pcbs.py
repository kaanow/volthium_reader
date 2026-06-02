#!/usr/bin/env python3
"""CP3 PCB build script — project-local footprint cache + smoke test.

By default this script resolves footprints from the committed
hardware/kicad/libraries/volthium.pretty/ directory. The host KiCad
install is only touched when invoked with --rebuild-footprints, which
re-extracts a curated set of .kicad_mod files from the host KiCad
footprint tree into the project-local cache.

This mirrors the CP2 symbol-library pattern (volthium.kicad_sym +
build_schematics.py --rebuild-library) and makes PCB generation
reproducible across machines: anyone with this repo + .venv can run
this script without any KiCad install at all (KiCad is still needed
for the GUI and for kicad-cli, but not for python-side generation).

Run from repo root:
  .venv/bin/python hardware/kicad/build_pcbs.py
  .venv/bin/python hardware/kicad/build_pcbs.py --rebuild-footprints
"""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJ_FP = REPO / "hardware/kicad/libraries/volthium.pretty"
SMOKE = REPO / "hardware/kicad/_smoke"

# Module-level flag set by main() — when True, build_battery_side() /
# build_display_side() run the Freerouting pipeline at the end. Default
# False so a plain `python build_pcbs.py --battery` regenerates the
# placement-only board (fast) without spending several minutes on
# routing. Pass `--autoroute` to enable.
AUTOROUTE = False

# Host KiCad footprint roots, tried in order. Only used when
# --rebuild-footprints is passed.
HOST_FP_ROOTS = [
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
    Path("/usr/share/kicad/footprints"),
    Path("/usr/local/share/kicad/footprints"),
    Path("/opt/homebrew/share/kicad/footprints"),
]

# Curated set of footprints the project needs. Each entry is
# (host_lib_name, footprint_name). Sourced from the CP2 netlists at
# CP3 iter 4 — 22 unique footprints across both boards, all present
# in KiCad 10 stock libraries (no hand-authoring required).
STOCK_FOOTPRINTS = [
    ("Battery",                 "BatteryHolder_Keystone_1057_1x2032"),
    ("Button_Switch_SMD",       "SW_SPST_B3S-1000"),
    ("Button_Switch_THT",       "SW_PUSH_6mm"),
    ("Capacitor_SMD",           "C_0402_1005Metric"),
    ("Capacitor_SMD",           "C_0603_1608Metric"),
    ("Capacitor_SMD",           "C_0805_2012Metric"),
    ("Capacitor_SMD",           "C_1210_3225Metric"),
    ("Connector_FFC-FPC",       "Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal"),
    ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical"),
    ("Connector_RJ",            "RJ45_Amphenol_RJHSE5380"),
    ("Converter_DCDC",          "Converter_DCDC_RECOM_R-78E-0.5_THT"),
    ("Diode_SMD",               "D_SMA"),
    ("Fuse",                    "Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal"),
    ("Inductor_SMD",            "L_0805_2012Metric"),
    ("Package_SO",              "SOIC-16W_7.5x10.3mm_P1.27mm"),
    ("Package_SO",              "SOIC-8_3.9x4.9mm_P1.27mm"),
    ("Package_TO_SOT_SMD",      "SOT-23"),
    ("Package_TO_SOT_SMD",      "SOT-23-6"),
    ("RF_Module",               "ESP32-S3-WROOM-1U"),  # external U.FL antenna; no keepout zone
    ("Resistor_SMD",            "R_0805_2012Metric"),
    ("Resistor_THT",            "R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"),
    ("TerminalBlock_Phoenix",   "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"),
    # Mounting hardware (CP3 iter 6+)
    ("MountingHole",            "MountingHole_3.2mm_M3_DIN965"),
]


def _find_host_root() -> Path:
    for root in HOST_FP_ROOTS:
        if root.is_dir():
            return root
    raise SystemExit(
        "ERROR: could not find a host KiCad footprint tree. Tried:\n  "
        + "\n  ".join(str(r) for r in HOST_FP_ROOTS)
        + "\nInstall KiCad 10 (or pass --skip-rebuild) to proceed."
    )


def rebuild_footprint_cache() -> None:
    """Re-extract STOCK_FOOTPRINTS from host KiCad into volthium.pretty/.

    This is the only function in this script that touches the host
    KiCad install. All other paths read from PROJ_FP only.
    """
    host = _find_host_root()
    PROJ_FP.mkdir(parents=True, exist_ok=True)
    n = 0
    for lib_name, fp_name in STOCK_FOOTPRINTS:
        src = host / f"{lib_name}.pretty" / f"{fp_name}.kicad_mod"
        if not src.is_file():
            raise SystemExit(f"ERROR: host footprint not found: {src}")
        dst = PROJ_FP / f"{fp_name}.kicad_mod"
        shutil.copy(src, dst)
        n += 1
    print(f"rebuilt {n} footprint(s) into {PROJ_FP.relative_to(REPO)}/")


def resolve_footprint(fp_name: str) -> Path:
    """Return path to a footprint .kicad_mod from the project-local cache.

    Never touches the host KiCad install. If the requested footprint is
    not cached, the error message tells the operator how to fix it.
    """
    p = PROJ_FP / f"{fp_name}.kicad_mod"
    if not p.is_file():
        raise SystemExit(
            f"ERROR: footprint '{fp_name}' not in {PROJ_FP.relative_to(REPO)}/.\n"
            f"Add it to STOCK_FOOTPRINTS in {Path(__file__).name} and re-run "
            f"with --rebuild-footprints to extract from host KiCad."
        )
    return p


def build_smoke() -> None:
    """Build the CP3 smoke-test PCB using project-local footprint cache only."""
    from kiutils.board import Board
    from kiutils.footprint import Footprint
    from kiutils.items.common import Position, Net
    from kiutils.items.gritems import GrLine
    from kiutils.items.fpitems import FpText

    SMOKE.mkdir(parents=True, exist_ok=True)
    b = Board.create_new()

    def edge(x1, y1, x2, y2):
        return GrLine(
            start=Position(X=x1, Y=y1),
            end=Position(X=x2, Y=y2),
            layer="Edge.Cuts",
            width=0.05,
        )

    if b.graphicItems is None:
        b.graphicItems = []
    b.graphicItems.extend([
        edge(0, 0, 50, 0),
        edge(50, 0, 50, 30),
        edge(50, 30, 0, 30),
        edge(0, 30, 0, 0),
    ])

    b.nets = [
        Net(number=0, name=""),
        Net(number=1, name="RAW"),
        Net(number=2, name="GND"),
    ]

    fp = Footprint.from_file(str(resolve_footprint("R_0805_2012Metric")))
    fp.libraryNickname = "volthium"
    fp.entryName = "R_0805_2012Metric"
    fp.libId = "volthium:R_0805_2012Metric"
    fp.position = Position(X=25, Y=15, angle=0)
    fp.layer = "F.Cu"
    if fp.properties is None:
        fp.properties = {}
    fp.properties["Reference"] = "R1"
    fp.properties["Value"] = "10k"
    for txt in (fp.graphicItems or []):
        if isinstance(txt, FpText):
            if txt.type == "reference":
                txt.text = "R1"
            elif txt.type == "value":
                txt.text = "10k"
    if fp.pads:
        fp.pads[0].net = Net(number=1, name="RAW")
        fp.pads[1].net = Net(number=2, name="GND")

    if b.footprints is None:
        b.footprints = []
    b.footprints.append(fp)

    out = SMOKE / "smoke.kicad_pcb"
    b.to_file(str(out))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size} bytes)")


# ---------------------------------------------------------------------------
# Netlist parsing — read CP2 outputs and build {ref: pin -> net} + {ref: meta}.
# ---------------------------------------------------------------------------

import re
from collections import defaultdict


def parse_netlist(netlist_path: Path):
    """Return (nets, components) parsed from a KiCad .net file.

    nets:        list of (code:int, name:str)
    components:  dict[ref] -> {"value": str, "footprint": str, "pins": {pin: net}}
    """
    text = netlist_path.read_text()

    # Components section
    comp_pat = re.compile(
        r'\(comp\s+\(ref\s+"([^"]+)"\)\s+\(value\s+"([^"]+)"\).*?\(footprint\s+"([^"]+)"\)',
        re.DOTALL,
    )
    components = {
        ref: {"value": value, "footprint": fp, "pins": {}}
        for ref, value, fp in comp_pat.findall(text)
    }

    # Nets section
    net_pat = re.compile(
        r'\(net\s+\(code\s+"?(\d+)"?\)\s+\(name\s+"([^"]*)"\)(.*?)(?=\(net\s+\(code|\)\s*\)\s*\))',
        re.DOTALL,
    )
    node_pat = re.compile(r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)')
    nets = []
    for code, name, body in net_pat.findall(text):
        nets.append((int(code), name))
        for ref, pin in node_pat.findall(body):
            if ref in components:
                components[ref]["pins"][pin] = name

    return nets, components


# ---------------------------------------------------------------------------
# Battery-side placement — CP3 iter 6.
# ---------------------------------------------------------------------------

# Board outline (mm). Origin (0,0) at top-left.
# CP5 re-floorplan: D10 lifts the battery-side form-factor limit, so the
# board was enlarged from the cramped 60x40 (which forced sub-0.2mm pad
# clearances, ~88 silk-over-copper, ~28 courtyard overlaps and the BAT1->
# MOD1 GPIO short) to 95x75 — ~3x the area. Components are spread into
# functional zones with >=0.4mm courtyard gaps; BAT1's wide CR2032 clips
# now sit a full band below MOD1 so they cannot bridge MOD1's GPIO pads.
BATTERY_W, BATTERY_H = 95.0, 75.0

# Per-component placement on the battery-side board (CP5 re-floorplan).
# Each entry: ref -> (x_mm, y_mm, rotation_deg, layer), layer in {F.Cu,B.Cu}.
# Zones (top->bottom, signal flow left->right):
#   - top band: 24V input + protection (J1 -> F1 -> D1 / TVS1)
#   - upper-mid: hard-cut MOSFETs (Q1/Q2) + 3V3 buck U1 cluster + 12V U2
#   - center: MOD1 (ESP32-S3) with bypass caps on B.Cu beneath it
#   - right: RTC1, RS-485 (U3/TVS2/bias), RJ45 J2, dev headers J3/J5
#   - bottom: CR2032 BAT1 (its own band, clear of MOD1) + override button
# Verified courtyard-overlap-free with >=0.4mm gaps before generation.
BATTERY_PLACEMENT = {
    # ---- 24V input + reverse-polarity / TVS protection ----
    "J1":    (15.0, 13.0,   0, "F.Cu"),   # Phoenix 2-pin terminal block
    "F1":    (28.0, 12.0,   0, "F.Cu"),   # 5x20mm cartridge fuse
    "D1":    (54.0, 12.0,   0, "F.Cu"),   # SS24 reverse-polarity diode
    "TVS1":  (54.0, 18.0,   0, "F.Cu"),   # SMAJ30CA 24V clamp

    # ---- Hard-cut load switch ----
    "Q1":    (14.0, 27.0,   0, "F.Cu"),   # AO3401A P-FET
    "Q2":    (14.0, 32.0,   0, "F.Cu"),   # AO3400A N-FET gate driver
    "R4":    (20.0, 27.0,   0, "F.Cu"),   # Q1 gate pull-up
    "R3":    (20.0, 32.0,   0, "F.Cu"),   # Q2 gate pull-down

    # ---- 3V3 buck (TPS62933) cluster ----
    "U1":    (30.0, 27.0,   0, "F.Cu"),
    "C_BST": (30.0, 22.0,   0, "F.Cu"),   # bootstrap cap
    "L1":    (36.0, 27.0,   0, "F.Cu"),   # 2.2uH
    "C1":    (30.0, 33.0,   0, "F.Cu"),   # V24_SW input bulk
    "C2":    (41.0, 27.0,   0, "F.Cu"),   # 3V3 output bulk
    "C3":    (41.0, 33.0,   0, "F.Cu"),
    "C4":    (47.0, 33.0,   0, "F.Cu"),

    # ---- 12V Recom converter ----
    "U2":    (60.0, 30.0,   0, "F.Cu"),   # R-78E12-1.0 SIP3

    # ---- 24V sense divider (B.Cu) ----
    "R5":    (64.0, 12.0,   0, "B.Cu"),
    "R6":    (64.0, 15.0,   0, "B.Cu"),
    "C5":    (64.0, 18.0,   0, "B.Cu"),

    # ---- MCU module + bypass (caps on B.Cu under the module) ----
    "MOD1":  (30.0, 48.0,   0, "F.Cu"),   # ESP32-S3-WROOM-1U
    "C6":    (25.0, 43.0,   0, "B.Cu"),   # 10uF
    "C7":    (29.0, 43.0,   0, "B.Cu"),   # 100nF
    "C8":    (33.0, 43.0,   0, "B.Cu"),   # 1uF
    # R7 sits right of the bypass row, clear of MOD1's central PTH thermal
    # via array (pad 41 GND, ~x27-30 / y46-49) which a B.Cu part cannot overlap.
    "R7":    (37.0, 43.0,   0, "B.Cu"),   # EN pull-up

    # ---- RTC + CR2032 backup cell ----
    "RTC1":  (58.0, 48.0,   0, "F.Cu"),   # DS3231M SOIC-16W
    "R8":    (54.0, 57.0,   0, "B.Cu"),   # I2C pull-up
    "R9":    (58.0, 57.0,   0, "B.Cu"),   # I2C pull-up
    "C9":    (62.0, 57.0,   0, "B.Cu"),   # RTC VCC bypass
    # BAT1 (Keystone 1057, 34mm-wide clips) gets its own bottom band a full
    # 4mm below MOD1 so its GND clips cannot bridge MOD1's GPIO pads
    # (the D14 short on the old 60x40 layout).
    "BAT1":  (48.0, 67.0,   0, "F.Cu"),

    # ---- Override button + debounce ----
    "BTN1":  (10.0, 60.0,   0, "F.Cu"),
    "R13":   (22.0, 62.0,   0, "B.Cu"),
    "C11":   (22.0, 65.0,   0, "B.Cu"),

    # ---- RS-485 transceiver + line protection ----
    "U3":    (78.0, 45.0,   0, "F.Cu"),   # SN65HVD3082E
    "TVS2":  (78.0, 51.0,   0, "F.Cu"),   # SMAJ12CA differential clamp
    "R10":   (73.0, 52.0,   0, "B.Cu"),   # A bias
    "R11":   (77.0, 52.0,   0, "B.Cu"),   # 120R termination
    "R12":   (81.0, 52.0,   0, "B.Cu"),   # B bias
    "C10":   (84.0, 45.0,   0, "B.Cu"),   # U3 VCC bypass

    # ---- RJ45 (Cat5e) + dev headers (right edge) ----
    "J2":    (78.0, 18.0,   0, "F.Cu"),   # Amphenol RJHSE5380
    "J3":    (88.0, 36.0,   0, "F.Cu"),   # UART debug
    "J5":    (88.0, 56.0,   0, "F.Cu"),   # USB-OTG
}

# Silkscreen reference-designator offsets (dx, dy mm from anchor). Auto-placed
# refdes text otherwise lands on each part's own body outline / pads
# (silk_over_copper, silk_overlap). These push each refdes into the cardinal
# direction with the most free space, computed against the courtyard floorplan.
BATTERY_REFDES_OFFSETS = {
    "BAT1":  ( 0.00,  5.55),
    "BTN1":  (-3.40,  2.25),
    "C1":    ( 4.20,  0.00),
    "C10":   ( 0.00,  1.63),
    "C11":   ( 0.00,  1.63),
    "C2":    ( 4.20,  0.00),
    "C3":    (-4.20,  0.00),
    "C4":    ( 4.20,  0.00),
    "C5":    ( 0.00,  1.63),
    "C6":    ( 0.00, -2.48),
    "C7":    ( 0.00, -1.96),
    "C8":    ( 0.00, -2.23),
    "C9":    ( 3.38,  0.00),
    "C_BST": ( 3.38,  0.00),
    "D1":    ( 0.00, -2.65),
    "F1":    ( 8.90, -2.25),
    "J1":    (-4.94, -0.30),
    "J2":    ( 3.56, -9.40),
    "J3":    ( 0.00, -2.67),
    "J5":    ( 0.00, 10.29),
    "L1":    ( 0.00, -1.75),
    "MOD1":  (11.65,  0.22),
    "Q1":    ( 0.00, -2.60),
    "Q2":    ( 0.00,  2.60),
    "R10":   (-3.58,  0.00),
    "R11":   ( 0.00,  1.85),
    "R12":   ( 3.58,  0.00),
    "R13":   ( 3.58,  0.00),
    "R3":    ( 3.58,  0.00),
    "R4":    ( 3.58,  0.00),
    "R5":    ( 0.00, -1.85),
    "R6":    ( 3.58,  0.00),
    "R7":    ( 0.00, -2.45),
    "R8":    (-3.58,  0.00),
    "R9":    ( 0.00, -1.85),
    "RTC1":  ( 0.00, -6.30),
    "TVS1":  ( 0.00,  2.65),
    "TVS2":  ( 0.00,  2.65),
    "U1":    (-3.95,  0.00),
    "U2":    ( 2.48,  3.15),
    "U3":    ( 0.00, -3.60),
}


def _add_edge_cuts(b, w, h):
    """Draw board outline rectangle on Edge.Cuts."""
    from kiutils.items.gritems import GrLine
    from kiutils.items.common import Position
    def edge(x1, y1, x2, y2):
        return GrLine(
            start=Position(X=x1, Y=y1),
            end=Position(X=x2, Y=y2),
            layer="Edge.Cuts",
            width=0.05,
        )
    if b.graphicItems is None:
        b.graphicItems = []
    b.graphicItems.extend([
        edge(0, 0, w, 0),
        edge(w, 0, w, h),
        edge(w, h, 0, h),
        edge(0, h, 0, 0),
    ])


_F_TO_B_LAYER = {
    "F.Cu": "B.Cu", "F.Mask": "B.Mask", "F.Paste": "B.Paste",
    "F.SilkS": "B.SilkS", "F.Fab": "B.Fab", "F.Adhes": "B.Adhes",
    "F.CrtYd": "B.CrtYd",
}


def _flip_layer(layer_name: str) -> str:
    """Return the back-side equivalent for a front-side layer name; same name
    for other layers (Edge.Cuts, etc.)."""
    return _F_TO_B_LAYER.get(layer_name, layer_name)


def _flip_footprint_to_back(fp) -> None:
    """In-place: swap every F.* layer reference inside a footprint to B.*,
    and set `mirror` on any text being moved to a B.* layer so it reads
    correctly when viewed from the back.

    KiCad's "flip footprint" GUI command does all of this. kiutils'
    Footprint.layer setter only changes the footprint's own layer
    property and does NOT cascade into pads, graphics, or properties —
    so a B.Cu-placed footprint loaded by kiutils ends up with F.Cu pads
    and F.SilkS refdes (not mirrored), breaking the layer assignment we
    intended and tripping DRC `nonmirrored_text_on_back_layer`.
    """
    from kiutils.items.common import Justify, Effects
    # Pads
    for pad in (fp.pads or []):
        pad.layers = [_flip_layer(l) for l in (pad.layers or [])]
    # All graphic items (FpText, FpLine, FpCircle, FpArc, FpPoly, etc.)
    for gi in (fp.graphicItems or []):
        if hasattr(gi, "layer") and gi.layer:
            new_layer = _flip_layer(gi.layer)
            # Mirror text that moved to a back layer.
            if (new_layer.startswith("B.") and gi.layer.startswith("F.")
                    and hasattr(gi, "effects") and gi.effects is not None):
                if gi.effects.justify is None:
                    gi.effects.justify = Justify(mirror=True)
                else:
                    gi.effects.justify.mirror = True
            gi.layer = new_layer
    # Properties (Reference, Value, Datasheet, Description, …) — these
    # also carry a (layer …) field that controls where the corresponding
    # silk/Fab text actually shows up on the manufactured board.
    # kiutils 1.4+ stores them in fp.properties as a list of Property
    # dataclasses with `.layer`; older or newer versions may store as a
    # dict-of-strings (value only, no layer). Guard against both.
    try:
        props = fp.properties
        if isinstance(props, list):
            for p in props:
                if hasattr(p, "layer") and p.layer:
                    p.layer = _flip_layer(p.layer)
    except AttributeError:
        pass


def _place_footprint(b, ref, comp_meta, placement, nets_by_name, refdes_offset=None):
    """Load a footprint from cache, set instance properties, tie pads to nets.

    refdes_offset: optional (dx_mm, dy_mm) tuple. When set, relocates the
    silkscreen reference designator FpText to that position relative to
    the footprint anchor. Used to move refdes outside body silk where the
    footprint's auto-placed text sits under the component body (D11 #5).
    """
    from kiutils.footprint import Footprint
    from kiutils.items.common import Position, Net
    from kiutils.items.fpitems import FpText

    # Strip lib prefix: "Resistor_SMD:R_0805_2012Metric" -> "R_0805_2012Metric"
    libId_full = comp_meta["footprint"]
    fp_name = libId_full.split(":", 1)[1]

    fp = Footprint.from_file(str(resolve_footprint(fp_name)))
    fp.libraryNickname = "volthium"
    fp.entryName = fp_name
    fp.libId = f"volthium:{fp_name}"

    x, y, rot, layer = placement
    fp.position = Position(X=x, Y=y, angle=rot)
    fp.layer = layer

    # When placing on B.Cu, kiutils-loaded footprints retain F.* layer
    # references for pads and silk — setting fp.layer alone does NOT
    # flip them. KiCad's GUI "flip footprint" operation swaps every
    # F.* layer to B.* (and vice versa) on the footprint's children.
    # CP3 generated boards without this flip, silently leaving "B.Cu"
    # passives physically on F.Cu — visible as DRC `shorting_items`
    # errors where pads of B.Cu-intended caps/resistors overlap MOD1
    # ESP32 pads on F.Cu. CP5 iter-6 fixes that here for any future
    # regeneration; the already-committed `.kicad_pcb` files were
    # similarly mis-flipped at CP3 and would need rebuild to repair.
    if layer == "B.Cu":
        _flip_footprint_to_back(fp)

    # Relocate any footprint-drawn Edge.Cuts geometry to F.Fab. The board
    # outline is the single rectangle drawn by _add_edge_cuts(); a component
    # that ships mechanical outline on Edge.Cuts (BAT1 Keystone_1057 draws
    # the coin-cell body there) would otherwise be interpreted by KiCad as a
    # board cutout — self-intersecting the outline (invalid_outline) and
    # tripping copper/silk edge-clearance on nearby parts. The Keystone 1057
    # is a surface-mount retainer that sits on top of the board, so no cutout
    # is wanted; keep the outline as F.Fab documentation instead.
    for gi in (fp.graphicItems or []):
        if getattr(gi, "layer", None) == "Edge.Cuts":
            gi.layer = "F.Fab"

    # KiCad 10 stores Reference/Value as footprint properties; silkscreen
    # text references them via ${REFERENCE} / ${VALUE} substitution.
    if fp.properties is None:
        fp.properties = {}
    fp.properties["Reference"] = ref
    fp.properties["Value"] = comp_meta["value"]

    # Reference + Value text handling — covers both KiCad 6/7 (typed
    # FpText: type="reference") and KiCad 8/10 (untyped user-mode
    # FpText with text "${REFERENCE}", typically on F.Fab not F.SilkS
    # because the modern convention puts assembly-only text on Fab).
    #
    # When refdes_offset is provided we also force the silk position
    # AND promote the layer to F.SilkS so the text actually appears
    # on the manufactured board (D11 #5 — engineer-readable silk).
    silk_layer = "B.SilkS" if layer == "B.Cu" else "F.SilkS"
    for txt in (fp.graphicItems or []):
        if not isinstance(txt, FpText):
            continue
        is_reference = (
            txt.type == "reference"
            or (txt.type == "user" and txt.text == "${REFERENCE}")
        )
        is_value = (
            txt.type == "value"
            or (txt.type == "user" and txt.text == "${VALUE}")
        )
        if is_reference:
            txt.text = ref
            if refdes_offset is not None:
                dx, dy = refdes_offset
                txt.position = Position(X=dx, Y=dy, angle=0)
                # Promote to silkscreen so the designator renders on
                # the printed board, not just the F.Fab assembly layer.
                txt.layer = silk_layer
        elif is_value:
            txt.text = comp_meta["value"]

    # Assign pads to nets
    pin_to_net = comp_meta["pins"]
    for pad in (fp.pads or []):
        net_name = pin_to_net.get(pad.number)
        if net_name and net_name in nets_by_name:
            code = nets_by_name[net_name]
            pad.net = Net(number=code, name=net_name)
        else:
            pad.net = Net(number=0, name="")

    if b.footprints is None:
        b.footprints = []
    b.footprints.append(fp)


def _add_mounting_holes(b, w, h, margin=3.0):
    """Add 4× M3 corner mounting holes (3.2mm drill, NPTH)."""
    from kiutils.footprint import Footprint
    from kiutils.items.common import Position

    hole_name = "MountingHole_3.2mm_M3_DIN965"
    hole_fp = resolve_footprint_optional(hole_name)
    if hole_fp is None:
        return

    corners = [
        (margin, margin),
        (w - margin, margin),
        (margin, h - margin),
        (w - margin, h - margin),
    ]
    for i, (x, y) in enumerate(corners, start=1):
        fp = Footprint.from_file(str(hole_fp))
        fp.libraryNickname = "volthium"
        fp.entryName = hole_name
        fp.libId = f"volthium:{hole_name}"
        fp.position = Position(X=x, Y=y, angle=0)
        fp.layer = "F.Cu"
        if fp.properties is None:
            fp.properties = {}
        fp.properties["Reference"] = f"H{i}"
        fp.properties["Value"] = "MountingHole_3.2mm"
        if b.footprints is None:
            b.footprints = []
        b.footprints.append(fp)


def _add_ground_zone(b, w, h, gnd_net_code: int, layer: str = "B.Cu",
                     margin: float = 0.5, clearance: float = 0.25,
                     min_thickness: float = 0.25):
    """Add a copper-pour zone tied to GND covering the whole board minus a
    `margin`-mm edge inset. Used on both boards to give every GND pin a
    contiguous return path on B.Cu per cp1_battery_side.md §11.4 /
    cp1_display_side.md §10.4.
    """
    from kiutils.items.zones import Zone, Hatch, FillSettings, ZonePolygon
    from kiutils.items.common import Position

    zone = Zone(
        net=gnd_net_code,
        netName="GND",
        layers=[layer],
        hatch=Hatch(style="edge", pitch=0.508),
        clearance=clearance,
        minThickness=min_thickness,
        # Default (thermal reliefs) connect_pads so SMD GND pads also
        # auto-connect to the pour. Was "thru_hole_only", which left ~5 SMD
        # GND pads requiring manual routing that freerouting reliably missed.
        # NOTE: kiutils-written "thermal_reliefs" string is invalid KiCad
        # syntax (it's the default — must be implicit). Omit connectPads.
        fillSettings=FillSettings(
            yes=True,
            thermalGap=0.5,
            thermalBridgeWidth=0.5,
            # mode 2 = "remove islands smaller than islandAreaMin (mm²)".
            # 10 mm² strips the dozens of tiny pour fragments that
            # autorouting creates without removing legitimate
            # functional ground islands (the smallest legitimate
            # island around a routed via is well under 10 mm²; this
            # value is calibrated for the autorouted boards' fragment
            # distribution and may need tuning if routing changes).
            islandRemovalMode=2,
            islandAreaMin=10,
        ),
        polygons=[ZonePolygon(coordinates=[
            Position(X=margin, Y=margin),
            Position(X=w - margin, Y=margin),
            Position(X=w - margin, Y=h - margin),
            Position(X=margin, Y=h - margin),
        ])],
    )
    if b.zones is None:
        b.zones = []
    b.zones.append(zone)


def _add_keepout_zone(b, x: float, y: float, w: float, h: float,
                      layers=("F.Cu", "B.Cu"), name: str = "keepout"):
    """Add a no-track no-copper keepout rectangle. Used for the ESP32-S3
    antenna corner on battery-side per cp1_battery_side.md §11.2.
    """
    from kiutils.items.zones import Zone, Hatch, KeepoutSettings, ZonePolygon
    from kiutils.items.common import Position

    zone = Zone(
        net=0,
        netName="",
        layers=list(layers),
        name=name,
        hatch=Hatch(style="edge", pitch=0.508),
        keepoutSettings=KeepoutSettings(
            tracks="not_allowed",
            vias="not_allowed",
            pads="allowed",
            copperpour="not_allowed",
            footprints="allowed",
        ),
        polygons=[ZonePolygon(coordinates=[
            Position(X=x, Y=y),
            Position(X=x + w, Y=y),
            Position(X=x + w, Y=y + h),
            Position(X=x, Y=y + h),
        ])],
    )
    if b.zones is None:
        b.zones = []
    b.zones.append(zone)


def _fill_zones(pcb_path: Path) -> None:
    """Compute zone fill polygons and save them into the .kicad_pcb file.

    kiutils writes the zone definition but does not compute the actual fill
    geometry — KiCad's GUI normally does that on first open, and `kicad-cli
    pcb render` shows the board without fill until then. This helper uses
    KiCad's own Python pcbnew binding (under wx-app context) to fill all
    zones and persist them, so the next render shows the filled pour.
    """
    import subprocess

    kicad_py = (
        "/Applications/KiCad/KiCad.app/Contents/Frameworks/"
        "Python.framework/Versions/3.9/bin/python3.9"
    )
    if not Path(kicad_py).exists():
        print(f"  fill_zones: skipped (kicad python not found at {kicad_py})")
        return

    script = (
        "import wx; wx.App(); import pcbnew; "
        f"b = pcbnew.LoadBoard({str(pcb_path)!r}); "
        "pcbnew.ZONE_FILLER(b).Fill(b.Zones()); "
        f"pcbnew.SaveBoard({str(pcb_path)!r}, b)"
    )
    result = subprocess.run(
        [kicad_py, "-c", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  fill_zones: WARN exit={result.returncode}: {result.stderr[-200:]}")
    else:
        print(f"  fill_zones: ok")


def _apply_refdes_offsets(pcb_path: Path, offsets: dict) -> None:
    """Reposition each footprint's silkscreen reference designator via pcbnew.

    kiutils represents footprint properties as a plain dict of strings, so it
    drops the Reference property's (at)/(layer)/(effects) on write — every
    refdes lands at the footprint origin (0,0), printing on top of the part
    body and pads (silk_over_copper / silk_overlap). pcbnew handles the board
    and back-layer transforms correctly, so we set the absolute board position
    (anchor + offset), force the correct silk layer, and give the text a
    fab-legal size/thickness here as a post-process.
    """
    import subprocess, json, tempfile

    kicad_py = (
        "/Applications/KiCad/KiCad.app/Contents/Frameworks/"
        "Python.framework/Versions/3.9/bin/python3.9"
    )
    if not Path(kicad_py).exists():
        print("  refdes: skipped (kicad python not found)")
        return

    off_json = Path(tempfile.gettempdir()) / "refdes_offsets.json"
    off_json.write_text(json.dumps(offsets))

    script = f"""
import json, pcbnew
offs = json.load(open({str(off_json)!r}))
b = pcbnew.LoadBoard({str(pcb_path)!r})
for fp in b.GetFootprints():
    ref = fp.GetReference()
    if ref.startswith("H") and ref[1:].isdigit():
        fp.Reference().SetVisible(False)  # mounting-hole refdes prints on its own hole
        continue
    if ref not in offs:
        continue
    dx, dy = offs[ref]
    a = fp.GetPosition()
    t = fp.Reference()
    t.SetPosition(pcbnew.VECTOR2I(a.x + pcbnew.FromMM(dx), a.y + pcbnew.FromMM(dy)))
    t.SetLayer(pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS)
    t.SetMirrored(fp.IsFlipped())
    t.SetVisible(True)
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.0), pcbnew.FromMM(1.0)))
    t.SetTextThickness(pcbnew.FromMM(0.15))
pcbnew.SaveBoard({str(pcb_path)!r}, b)
"""
    result = subprocess.run([kicad_py, "-c", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  refdes: WARN exit={result.returncode}: {result.stderr[-200:]}")
    else:
        print(f"  refdes: repositioned {len(offsets)} designators")


def _autoroute(pcb_path: Path, board_name: str, *, freerouting_jar: Path = None,
               java_bin: str = None, timeout_s: int = 900) -> bool:
    """Export DSN → run Freerouting → import SES → fill zones → save.

    Reproducible routing pipeline. Returns True on success, False otherwise.

    The build host needs:
    - KiCad 10 (for pcbnew.ExportSpecctraDSN / ImportSpecctraSES)
    - OpenJDK 21+ (Freerouting v1.9.0 was built with JDK 17 but runs on 21)
    - Freerouting v1.9.0 JAR at hardware/tools/freerouting-1.9.0.jar
      (NOT v2.x — v2 hangs on save after multi-threaded optimization,
      reproducibly. v1.9.0's single-threaded optimizer exits cleanly.)

    Skipped quietly if any dependency is missing — the function returns
    False and the caller proceeds with an unrouted .kicad_pcb.
    """
    import subprocess

    if freerouting_jar is None:
        freerouting_jar = REPO / "hardware/tools/freerouting-1.9.0.jar"
    if java_bin is None:
        java_bin = "/opt/homebrew/opt/openjdk@21/bin/java"

    kicad_py = (
        "/Applications/KiCad/KiCad.app/Contents/Frameworks/"
        "Python.framework/Versions/3.9/bin/python3.9"
    )

    if not Path(kicad_py).exists():
        print(f"  autoroute: skipped (kicad python not found)")
        return False
    if not freerouting_jar.exists():
        print(f"  autoroute: skipped (freerouting jar not at {freerouting_jar})")
        return False
    if not Path(java_bin).exists():
        print(f"  autoroute: skipped (java not at {java_bin})")
        return False

    outputs_dir = REPO / "hardware/outputs" / board_name
    outputs_dir.mkdir(parents=True, exist_ok=True)
    dsn_path = outputs_dir / f"{board_name}.dsn"
    ses_path = outputs_dir / f"{board_name}.ses"

    # 1. Export DSN via pcbnew Python.
    script = (
        "import wx; wx.App(); import pcbnew; "
        f"b = pcbnew.LoadBoard({str(pcb_path)!r}); "
        f"pcbnew.ExportSpecctraDSN(b, {str(dsn_path)!r})"
    )
    result = subprocess.run([kicad_py, "-c", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  autoroute: DSN export FAIL: {result.stderr[-300:]}")
        return False
    if not dsn_path.exists():
        print(f"  autoroute: DSN export produced no file")
        return False
    print(f"  autoroute: DSN exported ({dsn_path.stat().st_size} bytes)")

    # 2. Run Freerouting v1.9.0. Stdin redirected from /dev/null so the
    # process doesn't block waiting for keyboard input; v1.9.0 saves the
    # SES file and exits naturally on its own.
    if ses_path.exists():
        ses_path.unlink()
    print(f"  autoroute: running Freerouting (up to {timeout_s}s)...")
    try:
        result = subprocess.run(
            [java_bin, "-jar", str(freerouting_jar),
             "-de", str(dsn_path), "-do", str(ses_path)],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        print(f"  autoroute: TIMEOUT after {timeout_s}s")
        return False
    if not ses_path.exists():
        print(f"  autoroute: SES not produced; freerouting stderr tail:\n{result.stderr[-500:]}")
        return False
    print(f"  autoroute: SES produced ({ses_path.stat().st_size} bytes)")

    # 3. Import SES + fill zones + save via pcbnew Python.
    script = (
        "import wx; wx.App(); import pcbnew; "
        f"b = pcbnew.LoadBoard({str(pcb_path)!r}); "
        f"ok = pcbnew.ImportSpecctraSES(b, {str(ses_path)!r}); "
        "print(f'ImportSpecctraSES={ok} tracks=' + str(len(list(b.GetTracks())))); "
        "pcbnew.ZONE_FILLER(b).Fill(b.Zones()); "
        f"pcbnew.SaveBoard({str(pcb_path)!r}, b)"
    )
    result = subprocess.run([kicad_py, "-c", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  autoroute: SES import FAIL: {result.stderr[-300:]}")
        return False
    print(f"  autoroute: SES import ok ({result.stdout.strip().splitlines()[-1] if result.stdout.strip() else 'no msg'})")
    return True


def resolve_footprint_optional(fp_name: str):
    """Like resolve_footprint but returns None instead of raising."""
    p = PROJ_FP / f"{fp_name}.kicad_mod"
    return p if p.is_file() else None


def _write_fp_lib_table(project_dir: Path) -> None:
    """Write a project-local fp-lib-table mapping 'volthium' to the cache."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "fp-lib-table").write_text(
        '(fp_lib_table\n'
        '  (version 7)\n'
        '  (lib (name "volthium")(type "KiCad")'
        '(uri "${KIPRJMOD}/../libraries/volthium.pretty")'
        '(options "")(descr "Project-local footprint cache (CP3+)"))\n'
        ')\n'
    )


# ---------------------------------------------------------------------------
# Display-side placement — CP4 iter 2 (after D12 renumber).
# ---------------------------------------------------------------------------

# Board outline (mm). 85x65 per CP1 §2 (double-gang form factor). Origin
# (0,0) at top-left. Mounting holes per CP1 §2: (4,4), (81,4), (4,61),
# (81,61) — 4× M3, handled by _add_mounting_holes with margin=4.0.
DISPLAY_W, DISPLAY_H = 85.0, 65.0
DISPLAY_MARGIN = 4.0  # mounting-hole inset from corners

# Per-component placement on the display-side board.
# Each entry: ref -> (x_mm, y_mm, rotation_deg, layer)
# layer in {"F.Cu", "B.Cu"}.
#
# Strategy per cp1_display_side.md §10:
#   - J2 FFC (Hirose FH12-24S) on top edge, centered laterally, contacts
#     facing into the board so the EPD ribbon enters from +Y (above).
#   - BTN1/BTN2/BTN3 in a row on bottom edge at X=24/42/60 (faceplate
#     mounting-hole reconcile per §10.2), Y=55 — chosen to clear the
#     bottom mounting-hole row at Y=61 (M3 footprint spans ±1.6mm).
#   - MOD1 ESP32-S3-WROOM-1U centered on X, biased upward to allow room
#     for the button row below. U.FL pad faces the +X edge so the
#     pigtail exits toward the box-back side.
#   - J1 RJ45 on the LEFT short edge, anchored so the connector body
#     hangs flush with X=0; cable exits toward -X.
#   - U1 R-78E3.3 SIP3 on B.Cu, in the left-edge power column below the
#     RJ45 entry — first board where a tall active lives on B.Cu, per
#     cp1_display_side.md §10.2 priority 4.
#   - U2 SN65HVD3082E SOIC-8 in the RS-485 column between J1 and MOD1.
#   - F1 axial PTC and TVS1 V12-line protection in the power column.
#   - TVS2 SMAJ12CA bidirectional on the RS-485 lines between U2 and J1.
#   - Decoupling caps clustered on B.Cu under their driven IC pin where
#     the F.Cu real estate is occupied by the IC body (mirrors CP3's
#     battery-side MOD1 bypass strategy).
DISPLAY_PLACEMENT = {
    # ---- Top band: EPD FFC, V12 input fuse/clamp, UART dev header ----
    "J2":    (42.5,  9.0,    0,   "F.Cu"),   # Hirose EPD FFC, top-center
    "F1":    (10.0,  9.0,    0,   "F.Cu"),   # axial fuse on V12_CAT5E (clear of J1 NPTH at y~11)
    "TVS1":  (28.0, 13.0,    0,   "F.Cu"),   # V12 clamp after F1
    "J3":    (75.0, 14.0,    0,   "F.Cu"),   # UART debug header

    # ---- Left column: RJ45 + V12 bulk + 3V3 Recom (rot 90, B.Cu) ----
    "J1":    (10.0, 30.0,   90,   "F.Cu"),   # Cat5e RJ45 (KiCad rot 90 CW body y=16.7-36.2)
    "C1":    (15.0, 39.0,    0,   "F.Cu"),   # V12 bulk between J1 and U1
    "U1":    (15.0, 50.0,   90,   "B.Cu"),   # R-78E3.3 SIP3 (rot 90 horizontal)

    # ---- RS-485 transceiver + protection between J1 and MOD1 ----
    "U2":    (40.0, 22.0,    0,   "F.Cu"),   # SN65HVD3082E
    "TVS2":  (40.0, 17.0,    0,   "F.Cu"),   # SMAJ12CA differential clamp
    "R2":    (45.0, 18.0,    0,   "B.Cu"),   # 120R termination
    "R3":    (45.0, 22.0,    0,   "B.Cu"),   # 680R A bias
    "R4":    (45.0, 26.0,    0,   "B.Cu"),   # 680R B bias

    # ---- MCU + bypass on B.Cu below MOD1 (clear of pad-41 thermal vias) ----
    "MOD1":  (60.0, 30.0,    0,   "F.Cu"),   # ESP32-S3-WROOM-1U
    "R1":    (50.0, 44.0,    0,   "B.Cu"),   # EN pull-up
    "C2":    (54.0, 44.0,    0,   "B.Cu"),   # 10uF V3V3 bulk
    "C3":    (58.0, 44.0,    0,   "B.Cu"),   # 10uF V3V3 bulk
    "C4":    (62.0, 44.0,    0,   "B.Cu"),   # 100nF close-in
    "C5":    (66.0, 44.0,    0,   "B.Cu"),   # ESP_EN debounce 100nF
    "C6":    (50.0, 47.0,    0,   "B.Cu"),   # 1uF V3V3 bulk
    "C7":    (54.0, 47.0,    0,   "B.Cu"),   # 100nF V3V3 HF

    # ---- Bottom: 3 buttons + pull-ups + debounce caps ----
    "BTN1":  (28.0, 58.0,    0,   "F.Cu"),
    "BTN2":  (46.0, 58.0,    0,   "F.Cu"),
    "BTN3":  (64.0, 58.0,    0,   "F.Cu"),
    "R5":    (26.0, 52.0,    0,   "B.Cu"),   # BTN1 pull-up
    "R6":    (44.0, 52.0,    0,   "B.Cu"),   # BTN2 pull-up
    "R7":    (62.0, 52.0,    0,   "B.Cu"),   # BTN3 pull-up
    "C8":    (30.0, 52.0,    0,   "B.Cu"),   # BTN1 debounce
    "C9":    (48.0, 52.0,    0,   "B.Cu"),   # BTN2 debounce
    "C10":   (66.0, 52.0,    0,   "B.Cu"),   # BTN3 debounce

    # ---- Right edge: USB-OTG dev header ----
    "J4":    (75.0, 38.0,    0,   "F.Cu"),
}


# Per-ref silkscreen-reference-text offsets for display-side. Each entry
# overrides the footprint's auto-placed `Reference` FpText, moving it to
# (anchor + offset) so the silk designator is visible at 100% zoom (D11
# criterion #5). Only components whose auto-placed silk falls inside the
# body footprint (where it's covered at assembly time) need an override.
#
# Offset is in footprint-local coordinates: (dx_mm, dy_mm). For a
# footprint at rotation 0, +X is right and +Y is down (KiCad convention).
DISPLAY_REFDES_OFFSETS = {
    "BTN1":  ( 0.00,  4.60),
    "BTN2":  ( 0.00,  4.60),
    "BTN3":  ( 0.00,  4.60),
    "C1":    ( 4.20,  0.00),
    "C10":   ( 3.38,  0.00),
    "C2":    ( 0.00, -1.88),
    "C3":    ( 0.00, -1.88),
    "C4":    ( 0.00, -1.36),
    "C5":    ( 3.38,  0.00),
    "C6":    (-3.38,  0.00),
    "C7":    ( 3.38,  0.00),
    "C8":    ( 3.38,  0.00),
    "C9":    ( 3.38,  0.00),
    "F1":    ( 5.08, -2.40),
    "J1":    (10.15, -3.56),
    "J2":    ( 0.00, -3.90),
    "J3":    ( 0.00, -2.67),
    "J4":    ( 3.67,  3.81),
    "MOD1":  ( 0.00,-10.75),
    "R1":    (-3.58,  0.00),
    "R2":    ( 3.58,  0.00),
    "R3":    ( 3.58,  0.00),
    "R4":    ( 0.00,  1.85),
    "R5":    (-3.58,  0.00),
    "R6":    (-3.58,  0.00),
    "R7":    (-3.58,  0.00),
    "TVS1":  ( 0.00,  2.65),
    "TVS2":  (-5.40,  0.00),
    "U1":    (-2.25,  4.47),
    "U2":    (-5.60,  0.00),
}


def build_display_side() -> None:
    """Build hardware/kicad/display_side/display_side.kicad_pcb from CP2 netlist."""
    from kiutils.board import Board
    from kiutils.items.common import Net

    project_dir = REPO / "hardware/kicad/display_side"
    netlist = REPO / "hardware/outputs/display_side/display_side.net"
    nets, components = parse_netlist(netlist)

    b = Board.create_new()
    _add_edge_cuts(b, DISPLAY_W, DISPLAY_H)

    # Nets table — code 0 is reserved "no connection"
    b.nets = [Net(number=0, name="")]
    nets_by_name = {"": 0}
    for code, name in nets:
        b.nets.append(Net(number=code, name=name))
        nets_by_name[name] = code

    # Place every footprint
    for ref, meta in sorted(components.items()):
        if ref not in DISPLAY_PLACEMENT:
            print(f"  WARNING: no placement for {ref}, skipping")
            continue
        _place_footprint(
            b, ref, meta, DISPLAY_PLACEMENT[ref], nets_by_name,
        )

    _add_mounting_holes(b, DISPLAY_W, DISPLAY_H, margin=DISPLAY_MARGIN)
    gnd_code = nets_by_name.get("GND", 0)
    if gnd_code:
        _add_ground_zone(b, DISPLAY_W, DISPLAY_H, gnd_net_code=gnd_code)
    _write_fp_lib_table(project_dir)

    out = project_dir / "display_side.kicad_pcb"
    b.to_file(str(out))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size} bytes)")
    print(f"  components placed: {len([r for r in components if r in DISPLAY_PLACEMENT])}")
    print(f"  nets: {len(b.nets)}")
    print(f"  zones: {len(b.zones or [])}")
    # Preserve the human-maintained .kicad_pro (pcbnew SaveBoard rewrites it).
    pro = project_dir / "display_side.kicad_pro"
    pro_snapshot = pro.read_bytes() if pro.exists() else None
    _fill_zones(out)
    _apply_refdes_offsets(out, DISPLAY_REFDES_OFFSETS)
    if AUTOROUTE:
        _autoroute(out, "display_side")
    if pro_snapshot is not None:
        pro.write_bytes(pro_snapshot)


def build_battery_side() -> None:
    """Build hardware/kicad/battery_side/battery_side.kicad_pcb from CP2 netlist."""
    from kiutils.board import Board
    from kiutils.items.common import Net

    project_dir = REPO / "hardware/kicad/battery_side"
    netlist = REPO / "hardware/outputs/battery_side/battery_side.net"
    nets, components = parse_netlist(netlist)

    b = Board.create_new()
    _add_edge_cuts(b, BATTERY_W, BATTERY_H)

    # Nets table — code 0 is reserved "no connection"
    b.nets = [Net(number=0, name="")]
    nets_by_name = {"": 0}
    for code, name in nets:
        b.nets.append(Net(number=code, name=name))
        nets_by_name[name] = code

    # Place every footprint
    for ref, meta in sorted(components.items()):
        if ref not in BATTERY_PLACEMENT:
            print(f"  WARNING: no placement for {ref}, skipping")
            continue
        _place_footprint(b, ref, meta, BATTERY_PLACEMENT[ref], nets_by_name)

    _add_mounting_holes(b, BATTERY_W, BATTERY_H)
    gnd_code = nets_by_name.get("GND", 0)
    if gnd_code:
        _add_ground_zone(b, BATTERY_W, BATTERY_H, gnd_net_code=gnd_code)
    _write_fp_lib_table(project_dir)

    out = project_dir / "battery_side.kicad_pcb"
    b.to_file(str(out))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size} bytes)")
    print(f"  components placed: {len([r for r in components if r in BATTERY_PLACEMENT])}")
    print(f"  nets: {len(b.nets)}")
    print(f"  zones: {len(b.zones or [])}")
    # pcbnew's SaveBoard (in the steps below) rewrites the sibling .kicad_pro
    # design_settings, clobbering the human-maintained net classes and DRC
    # severity overrides. Snapshot and restore it so the build never mutates
    # that file.
    pro = project_dir / "battery_side.kicad_pro"
    pro_snapshot = pro.read_bytes() if pro.exists() else None
    _fill_zones(out)
    _apply_refdes_offsets(out, BATTERY_REFDES_OFFSETS)
    if AUTOROUTE:
        _autoroute(out, "battery_side")
    if pro_snapshot is not None:
        pro.write_bytes(pro_snapshot)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rebuild-footprints",
        action="store_true",
        help="Re-extract STOCK_FOOTPRINTS from host KiCad into volthium.pretty/. "
        "Only needed when adding new footprints or refreshing the cache.",
    )
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="Build the CP3 smoke-test PCB.",
    )
    ap.add_argument(
        "--battery",
        action="store_true",
        help="Build the battery-side PCB from CP2 netlist.",
    )
    ap.add_argument(
        "--display",
        action="store_true",
        help="Build the display-side PCB from CP2 netlist.",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Build all PCBs (smoke + battery + display).",
    )
    ap.add_argument(
        "--autoroute",
        action="store_true",
        help="After building each board, export DSN, run Freerouting v1.9.0, "
        "import SES, fill zones. Adds several minutes per board. Requires "
        "hardware/tools/freerouting-1.9.0.jar and OpenJDK 21+.",
    )
    args = ap.parse_args()

    global AUTOROUTE
    AUTOROUTE = args.autoroute

    if args.rebuild_footprints:
        rebuild_footprint_cache()

    if args.smoke or args.all:
        build_smoke()
    if args.battery or args.all:
        build_battery_side()
    if args.display or args.all:
        build_display_side()

    if not any([args.rebuild_footprints, args.smoke, args.battery, args.display, args.all]):
        # Default: build everything
        build_smoke()
        build_battery_side()
        build_display_side()

    return 0


if __name__ == "__main__":
    sys.exit(main())
