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
    ("RF_Module",               "ESP32-S3-WROOM-1"),
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
    # TPS62933 buck (SOT-23-6, 3x3mm).
    "U1":    (42.0,   7.5,    0,   "F.Cu"),
    # 0805 input bulk cap, below U1.
    "C1":    (42.0,  11.5,    0,   "F.Cu"),
    # Bootstrap cap (0603, between pins 5/6 of U1).
    "C_BST": (43.5,   4.0,    0,   "F.Cu"),
    # 0805 inductor — close to U1 pin 5 (SW).
    "L1":    (46.5,   7.5,    0,   "F.Cu"),
    # 1210 output bulk cap on 3V3 rail.
    "C2":    (46.5,  11.5,    0,   "F.Cu"),
    # Additional 3V3 bulk caps separated to right.
    "C3":    (51.0,   7.5,    0,   "F.Cu"),
    "C4":    (51.0,  11.5,    0,   "F.Cu"),
    # Recom R-78E12 SIP3 (V12 rail for CAT5e PoE-style output). 11.5x6mm body.
    "U2":    (54.0,  18.0,   90,   "F.Cu"),
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

    # ===== ESP32-S3 module (iter 10) =====
    # MOD1 = ESP32-S3-WROOM-1-N16R8. Footprint body ~18x25.5mm.
    # KiCad's ESP32-S3-WROOM-1 footprint origin is at pin 1 corner with
    # the body extending +x and +y from there; antenna is on the +y end.
    # Placing pin-1 origin at (24, 13.5) puts the module body x=24-42,
    # y=13.5-39 — antenna sticks off the bottom of the 40 mm board
    # by 1 mm (acceptable per Q-CP3-4 default; refine in iter 12).
    "MOD1":  (28.0,  16.5,    0,   "F.Cu"),

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

    # ===== Parked off-board (iter 12 will move these) =====
    # X >= 70 keeps them out of the 60mm board area. Stack in rows.
}

# Parked off-board positions for the remaining components (iter 12).
# Placed on a 15mm-step grid starting at x=75 so courtyards stay clear.
_PARKED = [
    "RTC1", "BAT1", "R8", "R9", "C9",                    # RTC + backup cell
    "BTN1", "R13",                                       # override button
    "U3", "R10", "R11", "R12", "TVS2", "C10",            # RS-485
    "C11", "C12", "C13", "C14",                          # misc decoupling
    "J2", "J3", "J5",                                    # RJ45 + headers
]
# Park each on a 30mm row stride / 15mm column stride to keep courtyards clear.
for i, ref in enumerate(_PARKED):
    row, col = divmod(i, 4)
    BATTERY_PLACEMENT[ref] = (75.0 + col * 15.0, 10.0 + row * 15.0, 0, "F.Cu")


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


def _place_footprint(b, ref, comp_meta, placement, nets_by_name):
    """Load a footprint from cache, set instance properties, tie pads to nets."""
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

    # KiCad 10 stores Reference/Value as footprint properties; silkscreen
    # text references them via ${REFERENCE} / ${VALUE} substitution.
    if fp.properties is None:
        fp.properties = {}
    fp.properties["Reference"] = ref
    fp.properties["Value"] = comp_meta["value"]

    # Legacy KiCad 6/7 footprints still use typed FpText; keep both paths
    # in sync so older library files behave too.
    for txt in (fp.graphicItems or []):
        if isinstance(txt, FpText):
            if txt.type == "reference":
                txt.text = ref
            elif txt.type == "value":
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
    _write_fp_lib_table(project_dir)

    out = project_dir / "battery_side.kicad_pcb"
    b.to_file(str(out))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size} bytes)")
    print(f"  components placed: {len([r for r in components if r in BATTERY_PLACEMENT])}")
    print(f"  nets: {len(b.nets)}")


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
        "--all",
        action="store_true",
        help="Build all PCBs (smoke + battery + display).",
    )
    args = ap.parse_args()

    if args.rebuild_footprints:
        rebuild_footprint_cache()

    if args.smoke or args.all:
        build_smoke()
    if args.battery or args.all:
        build_battery_side()

    if not any([args.rebuild_footprints, args.smoke, args.battery, args.all]):
        # Default: build everything
        build_smoke()
        build_battery_side()

    return 0


if __name__ == "__main__":
    sys.exit(main())
