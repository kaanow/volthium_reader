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

# Board outline (mm). 60x40 per CP1 §2. Origin (0,0) at top-left.
BATTERY_W, BATTERY_H = 60.0, 40.0

# Per-component placement on the battery-side board.
# Iter 6 scope: power-input cluster placed with intent. All other
# components parked off-board (x>=70) until iters 8/10 refine them.
#
# Each entry: ref -> (x_mm, y_mm, rotation_deg, layer)
# layer in {"F.Cu", "B.Cu"}.
BATTERY_PLACEMENT = {
    # ===== Power-input cluster (iter 6 — placed with intent) =====
    # Input terminal block on the left edge, 5.08mm 2-pin Phoenix horizontal.
    # Body ~12.8x9.5mm so center near (8.5, 9.0) keeps body within 3-15mm.
    "J1":    ( 9.0,   8.5,    0,   "F.Cu"),
    # Cartridge fuse holder. Pads at 17.8mm pitch, body ~21mm wide, ~6mm tall.
    # Center at (24.5, 8.5) → pads at ~15.6 and ~33.4.
    "F1":    (24.5,   8.5,    0,   "F.Cu"),
    # Schottky reverse-polarity diode (D_SMA, 4.3x2.6mm). Right of fuse output.
    "D1":    (37.0,   7.5,    0,   "F.Cu"),
    # 24V TVS — bottom row below D1 (parallel diode to GND on V24_FUSED rail).
    "TVS1":  (37.0,  10.5,    0,   "F.Cu"),
    # TPS62933 buck cluster — moved past F1's right edge (x=42.9 max)
    # to clear hole-clearance from F1's 1.17mm THT pads (iter 12,
    # Finding 03). F1 spans x=24.5-42.3 with pads in a 2x2 grid.
    "U1":    (45.0,   7.5,    0,   "F.Cu"),
    # 0805 input bulk cap, below U1.
    "C1":    (45.0,  11.5,    0,   "F.Cu"),
    # Bootstrap cap (0603, between pins 5/6 of U1).
    "C_BST": (46.5,   4.0,    0,   "F.Cu"),
    # 0805 inductor — close to U1 pin 5 (SW).
    "L1":    (49.0,   7.5,    0,   "F.Cu"),
    # 1210 output bulk cap on 3V3 rail.
    "C2":    (49.0,  11.5,    0,   "F.Cu"),
    # Additional 3V3 bulk caps separated further right (1210 needs ≥3.5mm pitch).
    "C3":    (54.0,   7.5,    0,   "F.Cu"),
    "C4":    (54.0,  11.5,    0,   "F.Cu"),
    # Recom R-78E12 SIP3 (V12 rail for CAT5e PoE-style output). 11.5x6mm body.
    # Moved down at iter 12 to clear U1-cluster output caps (C3/C4).
    "U2":    (54.0,  25.0,   90,   "F.Cu"),
    # Sense divider on bottom layer per CP1 §11.2 (5,6 + 0603 cap).
    "R5":    (10.0,  16.0,    0,   "B.Cu"),
    "R6":    (10.0,  18.5,    0,   "B.Cu"),
    "C5":    (10.0,  21.0,    0,   "B.Cu"),

    # ===== Hard-cut MOSFET pair + gate net (iter 10) =====
    # Q1 = AO3401A P-MOSFET (high-side, SOT-23 G/S/D), V24 load switch.
    # Q2 = AO3400A N-MOSFET, gate driver pulling Q1 gate low when ESP
    # asserts PWR_EN. R3 = Q2 gate pulldown, R4 = Q1 gate pullup to source.
    # Per CP1 §11.2 priority 5: hard-cut MOSFETs near the regulators they
    # control. Placed below the power-cluster row, x≈15-23 (left of MOD1).
    "Q1":    (16.0,  17.0,    0,   "F.Cu"),
    "Q2":    (16.0,  21.5,    0,   "F.Cu"),
    "R3":    (20.0,  21.5,    0,   "F.Cu"),
    "R4":    (20.0,  17.0,    0,   "F.Cu"),

    # ===== ESP32-S3 module — -1U variant (iter 18 architectural respin) =====
    # Swapped from ESP32-S3-WROOM-1 (PCB antenna + 48x21mm keepout zone)
    # to ESP32-S3-WROOM-1U (external U.FL antenna, no keepout). Same
    # pinout, but the -1U footprint anchor is offset by +3.15mm in y
    # relative to its pad bbox center vs the -1 footprint. Anchor was
    # (28, 16.5) → now (28, 19.65) so pin positions stay at the same
    # absolute board coords as before the swap, preserving the bypass
    # row + RTC + hard-cut placements that depend on pin 2/3/4 location.
    "MOD1":  (28.0,  19.65,   0,   "F.Cu"),

    # ===== MCU bypass caps + EN pullup (iter 10) =====
    # 10uF + 100nF + 1uF in parallel close to pin 2 (3V3). Pin 2 at
    # absolute (19.25, 12.51); the module body occupies the F.Cu real
    # estate around pin 2, so bypass caps go on B.Cu directly under
    # pin 2 with short via stitches up to it. Loop area stays small.
    "C6":    (18.0,  13.5,    0,   "B.Cu"),  # 10µF X7R, 0805
    "C7":    (20.0,  13.5,    0,   "B.Cu"),  # 100nF, 0603 — closest to pin 2
    "C8":    (22.0,  13.5,    0,   "B.Cu"),  # 1µF, 0603
    # R7 = 10kΩ EN-pullup. Pin 3 (EN) at (-8.75, -2.72) → (19.25, 13.78).
    # Place R7 on B.Cu just below the bypass row.
    "R7":    (20.0,  15.5,    0,   "B.Cu"),

    # ===== RTC + CR2032 backup cell (iter 14) =====
    # Per CP1 §11.2: RTC1 near MOD1, away from L1. MOD1 occupies
    # y=3.75-29.25, so place RTC cluster in the strip y=30-37.
    # RTC1 = DS3231M, SOIC-16W (10.3x7.5mm). Anchor at x=30 keeps the
    # right edge (x=35.15) clear of J2's shield pad at x=39.43
    # (Finding 05). Anchor at y=35 keeps the top edge (y=31.25) clear
    # of MOD1's bottom pad row (y=29.0) — was overlapping at y=33.5.
    "RTC1":  (30.0,  35.0,    0,   "F.Cu"),
    # Keystone_1057 CR2032 holder. Pads at ±15.15mm in x; Edge.Cuts
    # extends ±11.5mm in y (footprint draws the cell outline on the
    # board edge layer). Anchor at (17, 28) keeps Edge.Cuts y range
    # 16.5-39.5, inside the 40mm board.
    "BAT1":  (17.0,  28.0,    0,   "F.Cu"),
    # I2C pullups + RTC bypass — on B.Cu near RTC1 to save F.Cu space.
    "R8":    (35.0,  37.5,    0,   "B.Cu"),   # SCL pullup
    "R9":    (37.5,  37.5,    0,   "B.Cu"),   # SDA pullup
    "C9":    (42.5,  37.5,    0,   "B.Cu"),   # RTC VCC bypass 100nF

    # ===== Override button + debounce (iter 14) =====
    # BTN1 = SW_PUSH_6mm THT, 6.5x4.5mm body. Place left of BAT1 in
    # the leftmost column. BAT1 anchor at (17, 28), pad 1 at (1.85, 28).
    # BTN1 below BAT1's pad-1 column.
    "BTN1":  ( 8.0,  37.0,    0,   "F.Cu"),
    "R13":   (12.0,  37.0,    0,   "B.Cu"),   # 1M pullup, B.Cu
    "C11":   (12.0,  35.5,    0,   "B.Cu"),   # debounce cap, B.Cu

    # ===== RS-485 transceiver + protection (iter 14) =====
    # U3 = SN65HVD3082E SOIC-8 (3.9x4.9mm). Per CP1 §11.2 priority 4:
    # near board edge with shield drain to J2 RJ45. Place top-right
    # area below the U1 cluster.
    "U3":    (50.0,  16.0,    0,   "F.Cu"),
    "R10":   (54.0,  14.0,    0,   "B.Cu"),   # RS-485 A bias (B.Cu)
    "R11":   (54.0,  16.0,    0,   "B.Cu"),   # 120Ω termination (B.Cu)
    "R12":   (54.0,  18.0,    0,   "B.Cu"),   # RS-485 B bias (B.Cu)
    "TVS2":  (54.0,  20.5,    0,   "F.Cu"),   # RS-485 line TVS (D_SMA)
    "C10":   (50.0,  19.0,    0,   "B.Cu"),   # U3 VCC bypass 100nF (B.Cu)

    # ===== Misc decoupling (iter 14) — all on B.Cu =====
    # Additional bypass for U2 (V12 rail) and digital section.
    "C12":   (51.0,  29.5,    0,   "B.Cu"),   # near U2 input
    "C13":   (53.0,  29.5,    0,   "B.Cu"),   # near U2 output
    "C14":   (50.0,  31.5,    0,   "B.Cu"),   # general 3V3 bypass

    # ===== RJ45 + dev headers (iter 14) =====
    # J2 = RJ45 Amphenol RJHSE5380 (~14x16mm body, 12 pads x∈[-4.57,
    # +11.69], y∈[-2.54, +1.78] from anchor). Anchor at (44, 33) puts
    # pads x=39.43-55.69, y=30.46-34.78. Body occupies that footprint
    # area; the receptacle face exits the board (south). Conflict
    # with nothing on F.Cu — BTN cluster is now left, RTC1 above,
    # decoupling/R8-9/C9 all moved to B.Cu.
    "J2":    (44.0,  33.0,    0,   "F.Cu"),
    # Dev headers J3 (UART debug) + J5 (USB OTG). Place rot 0° (pads
    # vertical) on right edge below sense divider.
    "J3":    (57.0,  10.5,    0,   "F.Cu"),
    "J5":    (57.0,  33.0,    0,   "F.Cu"),
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
        connectPads="thru_hole_only",
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
    # ===== EPD FFC connector on top edge (cp1 §10.2 priority 1) =====
    # Hirose FH12-24S-0.5SH 24-pin 0.5mm pitch horizontal FFC. Body
    # ~16.8x4.5mm. Anchor at (42.5, 8) centers the connector on X and
    # gives 4mm clearance from the top edge. Contacts face -Y (into the
    # board); ribbon enters from +Y above (toward the e-paper panel).
    "J2":    (42.5,   8.0,    0,   "F.Cu"),

    # ===== Left-edge power-input column (cp1 §10.2 priority 5) =====
    # J1 RJ45 Amphenol RJHSE5380 on the LEFT short edge. Rotated 90°
    # so the receptacle face exits toward -X (the wall where the
    # in-wall Cat5e arrives). Body ~14x16mm; anchor at (10, 32) with
    # rot=90 keeps the connector body left of MOD1.
    "J1":    (10.0,  32.0,   90,   "F.Cu"),
    # F1 axial PTC (10.16mm pad pitch, horizontal). Between top edge
    # and J1 RJ45. Anchor at (18, 14) horizontal so pads sit at X=13
    # and X=23. Y=14 keeps F1 clear of J1's body (J1 at (10,32,90)
    # rotated body Y=25-39, X=2-18) and gives 3mm courtyard gap to
    # U2 at X=28.
    "F1":    (18.0,  14.0,    0,   "F.Cu"),
    # TVS1 SMAJ15A — 15V unidirectional clamp on V12 line. D_SMA body
    # 4.3x2.6mm, pads at anchor X±2.15. Placed above U1 in the
    # left-column V12 path.
    "TVS1":  ( 8.0,  44.0,    0,   "F.Cu"),
    # C1 22µF/25V 1210 V12 bulk cap. Body 3.2x2.5mm, pads at anchor
    # X±1.5. Placed between TVS1 and U1 in the V12 column.
    "C1":    ( 8.0,  48.0,    0,   "F.Cu"),
    # U1 R-78E3.3 SIP3 — on B.Cu per §10.2 priority 4 (tall, lives on
    # back of board, body points into open double-gang space).
    # Converter_DCDC_RECOM_R-78E-0.5_THT footprint: SIP3, 5.08mm pad
    # pitch (pads at X-5.08, X, X+5.08 from anchor). Anchor at
    # (12, 52, 0, B.Cu) places pads at X=6.92/12/17.08, Y=52 — below
    # the V12 column (TVS1 Y=44, C1 Y=48) with 4mm pad-to-pad clearance,
    # and above the BTN row at Y=55 (horizontal clear: U1 right pad
    # X=17.08 vs BTN1 anchor X=24).
    "U1":    (12.0,  52.0,    0,   "B.Cu"),

    # ===== RS-485 column (between J1 and MOD1) =====
    # U2 SN65HVD3082E SOIC-8 (3.9x4.9mm body, pads on 1.27mm pitch
    # extending X±2.45 from anchor, Y±1.27 for the inner pin row).
    # Anchor at (28, 18) puts pad row 1 (pins 1-4) at Y≈16.4 and pad
    # row 2 (pins 5-8) at Y≈19.6.
    "U2":    (28.0,  18.0,    0,   "F.Cu"),
    # TVS2 SMAJ12CA bidirectional — RS-485 line protection. Between
    # U2 and J1 receptacle.
    "TVS2":  (22.0,  25.0,    0,   "F.Cu"),
    # R2 = 120Ω RS-485 termination across A/B lines. B.Cu, below U2.
    "R2":    (28.0,  22.5,    0,   "B.Cu"),
    # R3 = 680Ω V3V3-A fail-safe bias. B.Cu, 6mm right of U2 anchor
    # (was 4mm in iter-2, which put R3 pad inside the solder-mask
    # web of U2 pads 6/7 — Finding 05).
    "R3":    (34.0,  17.0,    0,   "B.Cu"),
    # R4 = 680Ω B-GND fail-safe bias. B.Cu, 6mm right of U2 anchor.
    "R4":    (34.0,  19.0,    0,   "B.Cu"),

    # ===== ESP32-S3-WROOM-1U module (cp1 §10.2 priority 3) =====
    # Body ~25.5×18mm (-1U variant). Anchor at (50, 30) puts the body
    # roughly X=37-63, Y=20-40. U.FL pad on +X short edge → pigtail
    # exits toward the right edge of the board (toward box back wall).
    "MOD1":  (50.0,  30.0,    0,   "F.Cu"),
    # R1 = 10kΩ ESP32 EN pullup. B.Cu, in the strip below MOD1.
    "R1":    (33.0,  42.0,    0,   "B.Cu"),
    # MOD1 V3V3 decoupling row on B.Cu, below MOD1 body (MOD1 body
    # extents Y=21-39 at anchor (50,30); 3mm clearance to Y=42 row).
    # Spaced 4mm apart to clear courtyards.
    #
    # Net-correctness audit (iter 4 fix): C8/C9/C10 are NOT MOD1
    # decoupling — they are BTN1/BTN2/BTN3 debounce caps per the
    # netlist (each connects BTN<N>_IN to GND). C5 is the ESP_EN
    # debounce cap, not a bulk V3V3 bypass. C2/C3/C4/C6/C7 are the
    # actual MOD1 V3V3 bypass caps. Iter-2 misidentified these. The
    # decoupling row below now holds only the real V3V3 bypass caps;
    # C5 sits next to MOD1 EN pin; C8/C9/C10 are paired with their
    # respective buttons.
    "C2":    (37.0,  42.0,    0,   "B.Cu"),   # 10µF 0805 V3V3 bulk
    "C3":    (41.0,  42.0,    0,   "B.Cu"),   # 10µF 0805 V3V3 bulk
    "C4":    (45.0,  42.0,    0,   "B.Cu"),   # 100nF 0402 close-in
    "C6":    (49.0,  42.0,    0,   "B.Cu"),   # 1µF 0603 V3V3 bulk
    "C7":    (53.0,  42.0,    0,   "B.Cu"),   # 100nF 0603 V3V3 bypass
    # C5 = ESP_EN debounce cap (100nF + R1 10kΩ pullup form the
    # power-on EN debounce). B.Cu next to R1 EN-pullup so the cap
    # sits between MOD1 EN pin and GND with R1 as the pullup branch.
    "C5":    (33.0,  39.5,    0,   "B.Cu"),

    # ===== Bottom-edge button row (cp1 §10.2 priority 2) =====
    # BTN1/2/3 at X=24/42/60 per §10.2 reconciled spec. Y=55 chosen to
    # give 4mm clearance from the bottom mounting-hole row at Y=61
    # (M3 footprint spans ~Y=59.4-62.6, button body B3S-1000 ~6x6mm
    # → button bottom edge at Y=58, clear by 1.4mm).
    "BTN1":  (24.0,  55.0,    0,   "F.Cu"),
    "BTN2":  (42.0,  55.0,    0,   "F.Cu"),
    "BTN3":  (60.0,  55.0,    0,   "F.Cu"),
    # R5/R6/R7 = 1MΩ button pullups, on B.Cu above each BTN. Each
    # pullup paired with the button's debounce cap (C8/C9/C10 — these
    # are 100nF caps on BTN<N>_IN to GND per the netlist; iter-2
    # misplaced them on the MOD1 decoupling row).
    "R5":    (22.0,  50.0,    0,   "B.Cu"),
    "R6":    (40.0,  50.0,    0,   "B.Cu"),
    "R7":    (58.0,  50.0,    0,   "B.Cu"),
    # C8/C9/C10 = button debounce caps (100nF each). B.Cu paired with
    # the pullup, 2mm to the right of each pullup so R + C form a
    # tidy unit above the corresponding button.
    "C8":    (26.0,  50.0,    0,   "B.Cu"),
    "C9":    (44.0,  50.0,    0,   "B.Cu"),
    "C10":   (62.0,  50.0,    0,   "B.Cu"),

    # ===== Dev headers (right edge) =====
    # J3 UART debug (1x4 pinheader), J4 USB-OTG (1x4 pinheader).
    # Right edge below MOD1. Each 1x4 vertical pinheader body spans
    # ±5.1mm in Y at rot 0; place J3 at Y=12 and J4 at Y=42 to give
    # ~30mm clearance — keeps J4 clear of the bottom mounting hole
    # at (81, 61).
    "J3":    (72.0,  12.0,    0,   "F.Cu"),
    "J4":    (72.0,  42.0,    0,   "F.Cu"),
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
    # BTN1/2/3: silk text auto-placed at body center (under the tactile
    # switch cap). Above the body collides with the R+C pullup/debounce
    # silk at Y=50 (R5/R6/R7 + C8/C9/C10 are on B.Cu but their silk
    # shows through). Move to the RIGHT of each body instead:
    # offset (+5, 0) puts text at anchor + 5mm in +X. BTN1 (24,55) →
    # text at (29, 55), well clear of BTN2 (body starts X=39). BTN3
    # (60, 55) → text at (65, 55), clear of J4 at X=72.
    "BTN1":  ( 5.0,   0.0),
    "BTN2":  ( 5.0,   0.0),
    "BTN3":  ( 5.0,   0.0),
    # J1 RJ45 (anchor (10, 32), rot 90). Auto-placed silk is inside the
    # 14x16mm body. Move text 5mm to the right in footprint-local
    # coords; with rot 90 that puts the text below the body in absolute
    # board coords (away from the J1 body to the +Y side, visible
    # between J1 and U1).
    "J1":    ( 0.0,  10.0),
    # J2 FFC (anchor (42.5, 8), rot 0). Body 16.8x4.5mm. Move text 5mm
    # below the body (absolute Y=13) — interior of board, between J2
    # and MOD1, clear of mounting hole at (4,4)/(81,4).
    "J2":    ( 0.0,   5.0),
    # J3, J4 pinheaders (1x4 vertical). Body 2.54x10.16. Move text 4mm
    # to the left of the body (absolute X=68) — interior of board,
    # between dev headers and MOD1.
    "J3":    (-4.0,   0.0),
    "J4":    (-4.0,   0.0),
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
            refdes_offset=DISPLAY_REFDES_OFFSETS.get(ref),
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
    _fill_zones(out)
    if AUTOROUTE:
        _autoroute(out, "display_side")


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
    _fill_zones(out)
    if AUTOROUTE:
        _autoroute(out, "battery_side")


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
