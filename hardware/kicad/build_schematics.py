"""CP2 schematic generation — battery-side + display-side.

Run:
    .venv/bin/python hardware/kicad/build_schematics.py

This script does three things:

  1. Builds `hardware/kicad/libraries/volthium.kicad_sym` by extracting
     every symbol the design uses from KiCad 10's stock libraries
     (at HOST_LIB_DIR below) and hand-authoring custom symbols where
     stock parts aren't available (the Recom R-78E modules).
  2. Generates the `.kicad_sch` files for each board with all
     components placed and connected via global labels (no manual
     wires — matches the CP2-approved approach).
  3. Runs `kicad-cli sch upgrade` → `sch erc` → `sch export pdf/netlist`
     on each generated schematic.

The host KiCad install is read **only to seed the project library**.
Once `volthium.kicad_sym` is committed, regeneration runs entirely
from repo + venv with no host-machine dependency.

This iteration (CP2 iter 2 implementation) lands:
  - libraries/volthium.kicad_sym (seeded with everything both boards
    will need across all of CP2)
  - battery_side/battery_side.kicad_pro (project file)
  - battery_side/battery_side.kicad_sch (POWER-INPUT slice only)
  - display_side/display_side.kicad_pro (project file; empty schematic
    for now — display-side schematic comes in iter 4)
  - per-project sym-lib-tables
  - hardware/outputs/battery_side/{schematic.pdf, battery_side.net}

Iter 3 fills out the rest of the battery-side schematic (MCU, RS-485,
support). Iter 4 generates the display-side schematic.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from kiutils.symbol import SymbolLib, Symbol
from kiutils.schematic import Schematic
from kiutils.items.schitems import (
    SchematicSymbol,
    GlobalLabel,
    NoConnect,
)
from kiutils.items.common import Position, Property, Effects

# -------------------------------------------------------------------- paths
REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware"
KICAD_DIR = HW / "kicad"
LIB_DIR = KICAD_DIR / "libraries"
LIB_FILE = LIB_DIR / "volthium.kicad_sym"
BATT_DIR = KICAD_DIR / "battery_side"
DISP_DIR = KICAD_DIR / "display_side"
OUT_BATT = HW / "outputs" / "battery_side"
OUT_DISP = HW / "outputs" / "display_side"

HOST_LIB_DIR = Path(
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
)

# Stock symbols we need. (host_lib, symbol_name) → optional rename
STOCK_SYMBOLS: list[tuple[str, str, Optional[str]]] = [
    # passives
    ("Device", "R", None),
    ("Device", "C", None),
    ("Device", "L", None),
    ("Device", "Fuse", None),
    ("Device", "Polyfuse", None),
    ("Device", "LED", None),
    ("Device", "Battery_Cell", None),
    # diodes / TVS — use Device:D and Device:D_TVS generics (Value field
    # overridden per-instance to the BOM MPN). Avoids pulling in the long
    # chain of derived-symbol parents that lives in Diode.kicad_sym.
    ("Device", "D", None),
    ("Device", "D_TVS", None),
    # MCU + module
    ("RF_Module", "ESP32-S3-WROOM-1", None),
    # regulator (TPS62933F extends TPS62933; using the parent directly
    # avoids the missing-extends-parent issue we hit with the diode family.
    # Value field is overridden to "TPS62933FDRLR" per instance.)
    ("Regulator_Switching", "TPS62933", None),
    # RTC (DS3231M is electrically equivalent to DS3231SN#)
    ("Timer_RTC", "DS3231M", None),
    # MOSFETs: AO3401A extends TP0610T (P-FET), AO3400A extends Q_NMOS_GSD.
    # Use the Q_PMOS_GSD / Q_NMOS_GSD generics directly to avoid the same
    # missing-extends-parent issue we hit with diodes; Value field carries
    # the BOM MPN per instance.
    ("Transistor_FET", "Q_PMOS_GSD", None),
    ("Transistor_FET", "Q_NMOS_GSD", None),
    # RS-485 transceiver — LTC2850xS8 is the parent of MAX3485 (and many
    # other 8-pin RS-485 parts). Same SOIC-8 pinout as SN65HVD3082E:
    # 1=RO, 2=RE, 3=DE, 4=DI, 5=GND, 6=A, 7=B, 8=VCC. Value field
    # overrides per-instance to SN65HVD3082E (BOM MPN).
    ("Interface_UART", "LTC2850xS8", None),
    # switches
    ("Switch", "SW_Push", None),
    # connectors — RJ45 extends 8P8C; use the 8P8C parent directly
    ("Connector", "8P8C", None),
    ("Connector_Generic", "Conn_01x02", None),
    ("Connector_Generic", "Conn_01x03", None),
    ("Connector_Generic", "Conn_01x04", None),
    ("Connector_Generic", "Conn_01x24", None),  # for display-side FFC
    # power symbols
    ("power", "+3V3", None),
    ("power", "+12V", None),
    ("power", "+24V", None),
    ("power", "GND", None),
    ("power", "PWR_FLAG", None),
]


def build_library() -> None:
    """Extract stock symbols from host KiCad libs + add custom Recom symbols.

    Writes hardware/kicad/libraries/volthium.kicad_sym.
    """
    LIB_DIR.mkdir(parents=True, exist_ok=True)

    # Cache: stock-lib path → SymbolLib (loaded lazily)
    loaded: dict[str, SymbolLib] = {}

    out_lib = SymbolLib()
    out_lib.version = "20251024"
    out_lib.generator = "volthium-build-schematics"

    for lib_name, sym_name, rename in STOCK_SYMBOLS:
        path = HOST_LIB_DIR / f"{lib_name}.kicad_sym"
        if str(path) not in loaded:
            loaded[str(path)] = SymbolLib.from_file(str(path))
        lib = loaded[str(path)]
        found = [s for s in lib.symbols if s.entryName == sym_name]
        if not found:
            raise SystemExit(f"FAIL: {lib_name}:{sym_name} not in {path}")
        sym = found[0]
        # If kiutils has a deepcopy-able representation, copy it; otherwise
        # serialize and re-parse (safe for our purposes).
        out_lib.symbols.append(sym)
        print(f"  + {lib_name}:{sym_name}")

    # Custom: Recom R-78E12-1.0 (3-pin VIN/GND/VOUT module)
    # We hand-author by cloning the structure of an existing 3-pin
    # regulator symbol; for now use the TPS62933F symbol's structure as
    # a template is overkill — kiutils makes it easy to spawn a generic
    # 3-pin module. Defer the actual authoring to iter 3 when we
    # actually need it for the schematic; for now flag as TODO.
    print("  TODO: Recom R-78E12-1.0 + R-78E3.3-0.5 custom symbols")
    print("        (deferred to iter 3 when their nets are wired in)")

    out_lib.to_file(str(LIB_FILE))
    print(f"\n[lib] wrote {LIB_FILE} ({LIB_FILE.stat().st_size} bytes)")


# -------------------------------------------------------------------- project files
def write_project_file(board_dir: Path, name: str) -> None:
    """Write the .kicad_pro JSON file.

    Includes the PCB DRC severity overrides + CP1 §11.3 net class
    definitions that CP3 established. Re-running this script must not
    wipe those — otherwise PCB DRC regresses from 0 errors to many.
    The numeric values for net classes live under `_intended_classes_cp4`
    as documented intent; CP4 routing binds them.
    """
    pro = {
        "board": {
            "design_settings": {
                "defaults": {},
                "rule_severities": {
                    "unconnected_items": "ignore",
                    "courtyards_overlap": "warning",
                    "solder_mask_bridge": "warning",
                    "drill_out_of_range": "warning",
                    "copper_edge_clearance": "warning",
                    "lib_footprint_issues": "ignore",
                    "lib_footprint_mismatch": "ignore",
                    "footprint_type_mismatch": "ignore",
                    "pth_inside_courtyard": "warning",
                    "npth_inside_courtyard": "warning",
                },
            },
            "layer_presets": [],
            "viewports": [],
        },
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "erc": {
            "erc_exclusions": [],
            "meta": {"version": 0},
            "pin_map": [],
            "rule_severities": {
                # kicad-cli's library-resolution complaint is non-functional —
                # the schematic's embedded libSymbols section is authoritative
                # for ERC and netlist correctness. Suppress to keep the
                # report focused on real design issues.
                "lib_symbol_issues": "ignore",
                # Footprints aren't finalized at CP2 (schematic capture).
                # CP3 (placement) is where footprint links are resolved.
                # Until then, suppress the linkage warning.
                "footprint_link_issues": "ignore",
                # `isolated_pin_label`: was suppressed during mid-CP2
                # build-out (many labels landed on MOD1 before counterpart
                # components). Re-enabled at CP2 close (iter 22) per
                # Q-CP2-NEW. If this fires, a real wiring gap exists.
            },
        },
        "libraries": {
            "pinned_footprint_libs": [],
            "pinned_symbol_libs": ["volthium"],
        },
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {
            "_comment_cp3": (
                "Class definitions per CP1 §11.3. Numeric track/clearance"
                " values are stored in _intended_classes_cp4 — not yet bound"
                " to KiCad's clearance checker (would trigger placement-phase"
                " clearance churn). CP4 routing reinstates the numerics +"
                " netclass_patterns."
            ),
            "_intended_classes_cp4": {
                "Default":    {"clearance": 0.2,  "track_width": 0.2,  "via_diameter": 0.6, "via_drill": 0.3},
                "Power-24V":  {"clearance": 0.3,  "track_width": 1.0,  "via_diameter": 0.8, "via_drill": 0.4},
                "Power-12V":  {"clearance": 0.25, "track_width": 0.5,  "via_diameter": 0.7, "via_drill": 0.4},
                "Power-3V3":  {"clearance": 0.2,  "track_width": 0.4,  "via_diameter": 0.6, "via_drill": 0.3},
                "RS485-diff": {"clearance": 0.25, "track_width": 0.25, "diff_pair_width": 0.25, "diff_pair_gap": 0.2},
            },
            "_intended_patterns_cp4": [
                {"netclass": "Power-24V",  "pattern": "V24_*"},
                {"netclass": "Power-12V",  "pattern": "V12_*"},
                {"netclass": "Power-3V3",  "pattern": "V3V3*"},
                {"netclass": "RS485-diff", "pattern": "RS485_*"},
            ],
            "classes": [
                {"name": "Default"},
                {"name": "Power-24V"},
                {"name": "Power-12V"},
                {"name": "Power-3V3"},
                {"name": "RS485-diff"},
            ],
            "meta": {"version": 4},
            "net_colors": None,
            "netclass_assignments": None,
            "netclass_patterns": [],
        },
        "pcbnew": {"last_paths": {}, "page_layout_descr_file": ""},
        "schematic": {
            "annotate_start_num": 0,
            "bom_settings": [],
            "drawing": {},
            "legacy_lib_dir": "",
            "legacy_lib_list": [],
            "meta": {"version": 1},
            "net_format_name": "",
            "page_layout_descr_file": "",
            "plot_directory": "",
            "spice_external_command": "spice \"%I\"",
            "subpart_first_id": 65,
            "subpart_id_separator": 0,
        },
        "sheets": [],
        "text_variables": {},
    }
    out = board_dir / f"{name}.kicad_pro"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pro, indent=2))
    print(f"  + {out}")


def write_sym_lib_table(board_dir: Path) -> None:
    """Write per-project sym-lib-table referencing our project library.

    Uses an absolute-ish path expanded from ${KIPRJMOD}. Verified to match
    KiCad 10's expected format.
    """
    content = (
        "(sym_lib_table\n"
        "\t(version 7)\n"
        "\t(lib\n"
        '\t\t(name "volthium")\n'
        '\t\t(type "KiCad")\n'
        '\t\t(uri "${KIPRJMOD}/../libraries/volthium.kicad_sym")\n'
        '\t\t(options "")\n'
        '\t\t(descr "Project-local symbol library")\n'
        "\t)\n"
        ")\n"
    )
    out = board_dir / "sym-lib-table"
    out.write_text(content)
    print(f"  + {out}")


# -------------------------------------------------------------------- schematic gen
@dataclass
class Placed:
    """A symbol placement with its property overrides and pin labels."""
    lib_id: str            # e.g. "volthium:R"
    ref: str               # e.g. "R5"
    value: str             # e.g. "1M"
    footprint: str         # e.g. "Resistor_SMD:R_0805_2012Metric"
    pos: tuple[float, float]  # (x, y) in mm
    pin_labels: dict[str, str] = field(default_factory=dict)
    # map pin_number → net_name; placed as GlobalLabel adjacent to the pin


def _make_property(key: str, value: str, x: float, y: float, hide: bool = False) -> Property:
    """kiutils Property helper."""
    p = Property(key=key, value=value, position=Position(X=x, Y=y, angle=0), effects=Effects())
    if hide:
        p.effects.hide = True
    return p


def _load_project_lib() -> SymbolLib:
    """Load the committed project library."""
    return SymbolLib.from_file(str(LIB_FILE))


def _set_title_block(sch: Schematic, title: str) -> None:
    """Populate the schematic title block + set A3 paper size.

    D11 criterion #4: title block must be populated.
    D11 criterion #3 + #5: A4 landscape is too small for ~40-component
    schematics — components and labels cram into the upper-left
    quadrant. A3 landscape (420×297 mm vs 297×210 mm) gives ~2× area
    at the same aspect ratio so functional blocks can occupy
    visually-distinct regions with breathing room.
    """
    from kiutils.items.common import TitleBlock
    tb = TitleBlock()
    tb.title = title
    tb.revision = "CP-schematic-cleanup"
    tb.date = "2026-05-24"
    tb.company = "Volthium"
    sch.titleBlock = tb
    sch.paper.paperSize = "A3"


def _copy_symbol_to_schematic(lib: SymbolLib, sym_name: str, sch: Schematic) -> Symbol:
    """Find a symbol in the project lib and copy it into the schematic's libSymbols.

    Idempotent — if the symbol is already present, return the existing instance.
    """
    import copy as _copy
    # Check if already present (full id "volthium:<name>")
    full_id = f"volthium:{sym_name}"
    for existing in sch.libSymbols:
        existing_full = f"{existing.libraryNickname or ''}:{existing.entryName}"
        if existing_full == full_id or existing.entryName == full_id:
            return existing
    src = next((s for s in lib.symbols if s.entryName == sym_name), None)
    if src is None:
        raise ValueError(f"symbol {sym_name!r} not in project library {LIB_FILE}")
    clone = _copy.deepcopy(src)
    # KiCad's schematic libSymbols stores symbols with libraryNickname:entryName
    # as the full id; we set libraryNickname so the serializer prefixes it.
    clone.libraryNickname = "volthium"
    sch.libSymbols.append(clone)
    return clone


def _uuid() -> str:
    """Generate a UUID v4 string for KiCad."""
    import uuid as _uuid_mod
    return str(_uuid_mod.uuid4())


def _place_symbol(
    sch: Schematic,
    sym_name: str,
    reference: str,
    value: str,
    footprint: str,
    pos: tuple[float, float],
    *,
    lib: SymbolLib,
    angle: float = 0.0,
) -> SchematicSymbol:
    """Place a SchematicSymbol instance referencing volthium:<sym_name>."""
    # Ensure the symbol definition is in libSymbols
    _copy_symbol_to_schematic(lib, sym_name, sch)
    inst = SchematicSymbol()
    inst.libraryNickname = "volthium"
    inst.entryName = sym_name
    inst.libName = None
    inst.position = Position(X=pos[0], Y=pos[1], angle=angle)
    inst.unit = 1
    inst.inBom = True
    inst.onBoard = True
    inst.fieldsAutoplaced = True
    inst.uuid = _uuid()
    # Properties: Reference, Value, Footprint, Datasheet (the standard 4)
    inst.properties = [
        Property(key="Reference", value=reference,
                 position=Position(X=pos[0] + 2.54, Y=pos[1] - 1.27, angle=0),
                 effects=Effects()),
        Property(key="Value", value=value,
                 position=Position(X=pos[0] + 2.54, Y=pos[1] + 1.27, angle=0),
                 effects=Effects()),
        Property(key="Footprint", value=footprint,
                 position=Position(X=pos[0], Y=pos[1], angle=0),
                 effects=Effects(hide=True)),
        Property(key="Datasheet", value="",
                 position=Position(X=pos[0], Y=pos[1], angle=0),
                 effects=Effects(hide=True)),
    ]
    sch.schematicSymbols.append(inst)
    return inst


def _place_label(sch: Schematic, text: str, pos: tuple[float, float], *, angle: float = 0.0) -> None:
    """Place a GlobalLabel at the given absolute schematic coordinates."""
    lbl = GlobalLabel()
    lbl.text = text
    lbl.shape = "input"
    lbl.position = Position(X=pos[0], Y=pos[1], angle=angle)
    lbl.fieldsAutoplaced = True
    lbl.uuid = _uuid()
    lbl.effects = Effects()
    sch.globalLabels.append(lbl)


def _place_noconnect(sch: Schematic, pos: tuple[float, float]) -> None:
    """Place a NoConnect marker at the given pin endpoint."""
    nc = NoConnect()
    nc.position = Position(X=pos[0], Y=pos[1], angle=0)
    nc.uuid = _uuid()
    sch.noConnects.append(nc)


def _place_power_flag(sch: Schematic, net: str, pos: tuple[float, float], lib: SymbolLib) -> None:
    """Place a PWR_FLAG symbol at pos, anchoring it to a global label `net`.

    PWR_FLAG is a stock KiCad power symbol used to assert "this net is driven"
    so ERC doesn't complain about a power input with no source.
    """
    # First place the PWR_FLAG symbol (it has a single pin)
    _copy_symbol_to_schematic(lib, "PWR_FLAG", sch)
    inst = SchematicSymbol()
    inst.libraryNickname = "volthium"
    inst.entryName = "PWR_FLAG"
    inst.position = Position(X=pos[0], Y=pos[1], angle=0)
    inst.unit = 1
    inst.inBom = False
    inst.onBoard = False
    inst.fieldsAutoplaced = True
    inst.uuid = _uuid()
    inst.properties = [
        Property(key="Reference", value="#FLG1",
                 position=Position(X=pos[0] + 2.54, Y=pos[1] - 1.27, angle=0),
                 effects=Effects()),
        Property(key="Value", value="PWR_FLAG",
                 position=Position(X=pos[0] + 2.54, Y=pos[1] + 1.27, angle=0),
                 effects=Effects()),
        Property(key="Footprint", value="",
                 position=Position(X=pos[0], Y=pos[1], angle=0),
                 effects=Effects(hide=True)),
        Property(key="Datasheet", value="",
                 position=Position(X=pos[0], Y=pos[1], angle=0),
                 effects=Effects(hide=True)),
    ]
    sch.schematicSymbols.append(inst)
    # Add the label that ties PWR_FLAG to the net
    _place_label(sch, net, pos)


def build_battery_side_schematic() -> None:
    """Generate battery-side schematic — symbol-instancing harness proof (CP2 iter 8).

    Iteration 8 (the symbol-instancing harness): places a small fragment of
    the real design — the 24 V sense divider (R5 + R6 + C5) — to validate
    end-to-end SchematicSymbol creation, libSymbols caching, GlobalLabel
    placement at pin endpoints, and PWR_FLAG-based net sourcing for ERC.

    Subsequent iterations fill in the rest of battery-side and display-side.
    """
    s = Schematic.create_new()
    s.generator = "volthium-build-schematics"
    _set_title_block(s, "Volthium reader — battery side")
    lib = _load_project_lib()

    # KiCad connection grid is 1.27 mm. All positions are expressed as n×G
    # so endpoints land on the grid (resistor pins are at ±3*G from center,
    # so symbol-center alignment propagates to pin alignment).
    G = 1.27

    # ===== Iter 10: V24 input path (J1 → F1 → D1 → V24_FUSED), TVS1 clamp =====

    # J1 — 2-pin terminal block (Phoenix MSTB-2,5/2-G-5,08). Pins at:
    #   pin 1 (V24_RAW): symbol-relative (-5.08, 0) → endpoint (X-5.08, Y)
    #   pin 2 (GND):     symbol-relative (-5.08, -2.54) → endpoint (X-5.08, Y-2.54)
    J1_X, J1_Y = 40 * G, 30 * G   # (50.8, 38.1)
    _place_symbol(s, "Conn_01x02", "J1", "Conn_01x02",
                  "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                  (J1_X, J1_Y), lib=lib)
    # Note: KiCad flips Y between symbol library and schematic. Lib pin Y
    # becomes -lib_Y on the schematic (relative to symbol center). For
    # Conn_01x02: pin 1 lib (-5.08, 0) → schematic (X-5.08, Y); pin 2 lib
    # (-5.08, -2.54) → schematic (X-5.08, Y+2.54).
    _place_label(s, "V24_RAW", (J1_X - 4 * G, J1_Y))            # pin 1 endpoint
    _place_label(s, "GND",     (J1_X - 4 * G, J1_Y + 2 * G))    # pin 2 endpoint

    # F1 — 5×20 mm cartridge fuse holder, 2-pin vertical (like R).
    F1_X, F1_Y = 60 * G, 30 * G   # (76.2, 38.1)
    _place_symbol(s, "Fuse", "F1", "1A 5x20",
                  "Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal",
                  (F1_X, F1_Y), lib=lib)
    _place_label(s, "V24_RAW",        (F1_X, F1_Y - 3 * G))     # pin 1 (top)
    _place_label(s, "V24_AFTER_FUSE", (F1_X, F1_Y + 3 * G))     # pin 2 (bottom)

    # D1 — SS24 Schottky reverse-polarity diode (Device:D generic, Value
    # overridden to BOM MPN). Horizontal: pin 1 (K) on left, pin 2 (A) on
    # right; pins at ±3.81 = ±3*G from center.
    D1_X, D1_Y = 80 * G, 30 * G   # (101.6, 38.1)
    _place_symbol(s, "D", "D1", "SS24",
                  "Diode_SMD:D_SMA",
                  (D1_X, D1_Y), lib=lib)
    _place_label(s, "V24_FUSED",      (D1_X - 3 * G, D1_Y))     # pin 1 (K) endpoint
    _place_label(s, "V24_AFTER_FUSE", (D1_X + 3 * G, D1_Y))     # pin 2 (A) endpoint

    # TVS1 — SMAJ30CA bidirectional 24V TVS (Device:D_TVS generic, Value
    # overridden). Pins same geometry as D.
    TVS1_X, TVS1_Y = 95 * G, 30 * G   # (120.65, 38.1)
    _place_symbol(s, "D_TVS", "TVS1", "SMAJ30CA",
                  "Diode_SMD:D_SMA",
                  (TVS1_X, TVS1_Y), lib=lib)
    _place_label(s, "V24_FUSED", (TVS1_X - 3 * G, TVS1_Y))      # pin 1 endpoint
    _place_label(s, "GND",       (TVS1_X + 3 * G, TVS1_Y))      # pin 2 endpoint

    # ===== Iter 8 (existing): V24 sense divider + filter cap =====

    # R5 — 1 MΩ, top of sense divider
    R5_X, R5_Y = 80 * G, 40 * G   # (101.6, 50.8)
    _place_symbol(s, "R", "R5", "1M",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R5_X, R5_Y), lib=lib)
    _place_label(s, "V24_FUSED", (R5_X, R5_Y - 3 * G))   # pin 1 endpoint
    _place_label(s, "V24_SENSE", (R5_X, R5_Y + 3 * G))   # pin 2 endpoint

    # R6 — 110 kΩ, bottom of sense divider
    R6_X, R6_Y = R5_X, R5_Y + 10 * G   # (101.6, 63.5)
    _place_symbol(s, "R", "R6", "110k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R6_X, R6_Y), lib=lib)
    _place_label(s, "V24_SENSE", (R6_X, R6_Y - 3 * G))
    _place_label(s, "GND",       (R6_X, R6_Y + 3 * G))

    # C5 — 100 nF filter cap on V24_SENSE
    C5_X, C5_Y = R6_X + 10 * G, R6_Y   # (114.3, 63.5)
    _place_symbol(s, "C", "C5", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C5_X, C5_Y), lib=lib)
    _place_label(s, "V24_SENSE", (C5_X, C5_Y - 3 * G))
    _place_label(s, "GND",       (C5_X, C5_Y + 3 * G))

    # ===== Iter 12: 3V3 converter — U1 (TPS62933F) + L1 + bulk caps =====

    # U1 — TPS62933 buck regulator, 8-pin SOT-563. Pin geometry (lib coords;
    # schematic Y-flip applies):
    #   pin 1 RT  (-7.62, -5.08) passive → sch (X-7.62, Y+5.08)
    #   pin 2 EN  (-7.62,  5.08) input   → sch (X-7.62, Y-5.08)
    #   pin 3 VIN (-7.62,  7.62) power_in→ sch (X-7.62, Y-7.62)
    #   pin 4 GND ( 0,   -12.7)  power_in→ sch (X,      Y+12.7) — bottom of body
    #   pin 5 SW  ( 7.62,  0)    output  → sch (X+7.62, Y)
    #   pin 6 BST ( 7.62,  7.62) passive → sch (X+7.62, Y-7.62)
    #   pin 7 SS  (-7.62, -2.54) passive → sch (X-7.62, Y+2.54)
    #   pin 8 FB  ( 7.62, -7.62) input   → sch (X+7.62, Y+7.62)
    U1_X, U1_Y = 120 * G, 30 * G   # (152.4, 38.1)
    _place_symbol(s, "TPS62933", "U1", "TPS62933FDRLR",
                  "Package_TO_SOT_SMD:SOT-23-6",
                  (U1_X, U1_Y), lib=lib)
    # Pin connections per CP1 §5 net list:
    #   VIN ← V24_FUSED
    #   GND ← GND
    #   EN  ← V24_FUSED (always-on; firmware kills U1 via the Q1 path)
    #   SW  → U1_SW (internal to U1+L1)
    #   FB  ← V3V3_SW (fixed-3.3 variant pin is tied to VOUT)
    #   BST → 100nF bootstrap cap (placeholder NoConnect for now; cap added
    #         in iter 14 when MOSFET cluster lands — they share decoupling)
    #   SS, RT → NoConnect (use internal defaults)
    _place_label(s, "V24_SW", (U1_X - 6 * G, U1_Y - 6 * G))      # pin 3 VIN
    _place_label(s, "V24_SW", (U1_X - 6 * G, U1_Y - 4 * G))      # pin 2 EN
    _place_label(s, "GND",       (U1_X,         U1_Y + 10 * G))  # pin 4 GND
    _place_label(s, "U1_SW",     (U1_X + 6 * G, U1_Y))           # pin 5 SW
    _place_label(s, "V3V3_SW",   (U1_X + 6 * G, U1_Y + 6 * G))   # pin 8 FB
    _place_noconnect(s, (U1_X - 6 * G, U1_Y + 4 * G))            # pin 1 RT
    _place_noconnect(s, (U1_X - 6 * G, U1_Y + 2 * G))            # pin 7 SS
    # BST: 100 nF bootstrap cap between U1.BST (pin 6) and U1.SW (pin 5).
    # Per Codex iter-13 guidance Q-CP2-10 — required for the high-side MOSFET
    # gate drive to function on real hardware.
    _place_label(s, "U1_BST", (U1_X + 6 * G, U1_Y - 6 * G))      # pin 6 BST → cap

    # L1 — 2.2 µH inductor (2-pin, same geometry as R: ±3.81 from center).
    L1_X, L1_Y = U1_X + 20 * G, U1_Y   # (177.8, 38.1)
    _place_symbol(s, "L", "L1", "2.2uH",
                  "Inductor_SMD:L_0805_2012Metric",  # placeholder
                  (L1_X, L1_Y), lib=lib)
    _place_label(s, "U1_SW",   (L1_X, L1_Y - 3 * G))     # pin 1 (top, lib Y+3.81)
    _place_label(s, "V3V3_SW", (L1_X, L1_Y + 3 * G))     # pin 2 (bottom)

    # C1 — 22 µF bulk on V24_SW (U1 VIN decoupling)
    C1_X, C1_Y = U1_X - 14 * G, U1_Y + 4 * G   # (134.62, 43.18)
    _place_symbol(s, "C", "C1", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C1_X, C1_Y), lib=lib)
    _place_label(s, "V24_SW", (C1_X, C1_Y - 3 * G))   # pin 1
    _place_label(s, "GND",    (C1_X, C1_Y + 3 * G))   # pin 2

    # C2 — 22 µF bulk on V3V3_SW (U1 VOUT decoupling)
    C2_X, C2_Y = L1_X + 8 * G, L1_Y + 4 * G   # (188.4, 43.18)
    _place_symbol(s, "C", "C2", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C2_X, C2_Y), lib=lib)
    _place_label(s, "V3V3_SW", (C2_X, C2_Y - 3 * G))
    _place_label(s, "GND",     (C2_X, C2_Y + 3 * G))

    # C_BST — 100 nF bootstrap cap between U1.BST and U1.SW. Required for
    # TPS62933 high-side MOSFET gate drive. Per Codex iter-13 Q-CP2-10.
    CBST_X, CBST_Y = U1_X + 10 * G, U1_Y - 4 * G   # (165.1, 33.02)
    _place_symbol(s, "C", "C_BST", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (CBST_X, CBST_Y), lib=lib)
    _place_label(s, "U1_BST", (CBST_X, CBST_Y - 3 * G))   # pin 1 → BST
    _place_label(s, "U1_SW",  (CBST_X, CBST_Y + 3 * G))   # pin 2 → SW

    # ===== Iter 14: 12V converter — U2 (Recom R-78E12-1.0) + C3 + C4 =====
    #
    # U2 is a Recom R-78E12-1.0 SIP3 buck module: 3-pin VIN/GND/VOUT. The
    # stock KiCad library doesn't have this part, so we instance the generic
    # Connector_Generic:Conn_01x03 with Value="R-78E12-1.0" + the proper
    # Footprint per CP1 BOM. Conn_01x03 pin geometry (in lib coords; KiCad
    # Y-flip applies on schematic placement):
    #   pin 1 lib (-5.08,  2.54) → schematic (X-5.08, Y-2.54)  [TOP pin]
    #   pin 2 lib (-5.08,  0)    → schematic (X-5.08, Y)
    #   pin 3 lib (-5.08, -2.54) → schematic (X-5.08, Y+2.54)  [BOTTOM pin]
    # Mapping (per Recom datasheet): pin 1 = VIN, pin 2 = GND, pin 3 = VOUT.
    U2_X, U2_Y = 160 * G, 30 * G   # (203.2, 38.1)
    _place_symbol(s, "Conn_01x03", "U2", "R-78E12-1.0",
                  "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                  (U2_X, U2_Y), lib=lib)
    _place_label(s, "V24_SW",     (U2_X - 4 * G, U2_Y - 2 * G))   # pin 1 VIN (top)
    _place_label(s, "GND",        (U2_X - 4 * G, U2_Y))           # pin 2 GND (mid)
    _place_label(s, "V12_CAT5E",  (U2_X - 4 * G, U2_Y + 2 * G))   # pin 3 VOUT (bot)

    # C3 — 22 µF bulk on V24_SW (U2 VIN decoupling)
    C3_X, C3_Y = U2_X - 14 * G, U2_Y + 4 * G   # (185.42, 43.18)
    _place_symbol(s, "C", "C3", "22uF/35V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C3_X, C3_Y), lib=lib)
    _place_label(s, "V24_SW", (C3_X, C3_Y - 3 * G))
    _place_label(s, "GND",    (C3_X, C3_Y + 3 * G))

    # C4 — 22 µF bulk on V12_CAT5E (U2 VOUT decoupling)
    C4_X, C4_Y = U2_X + 8 * G, U2_Y + 4 * G   # (213.36, 43.18)
    _place_symbol(s, "C", "C4", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C4_X, C4_Y), lib=lib)
    _place_label(s, "V12_CAT5E", (C4_X, C4_Y - 3 * G))
    _place_label(s, "GND",       (C4_X, C4_Y + 3 * G))

    # ===== Iter 16: hard-cut MOSFET cluster (Q1, Q2, R3, R4) =====
    #
    # Per cp1_battery_side.md §8 — the P-FET load switch that kills V24_SW
    # when the MCU drives PWR_EN low (or boots / faults / browns-out).
    # MOSFET pin geometry (Q_PMOS_GSD / Q_NMOS_GSD, identical):
    #   pin 1 G lib (-5.08, 0)    → schematic (X-5.08, Y)        [left]
    #   pin 2 S lib ( 2.54, -5.08)→ schematic (X+2.54, Y+5.08)   [bottom]
    #   pin 3 D lib ( 2.54,  5.08)→ schematic (X+2.54, Y-5.08)   [top]
    #
    # V24_SW connects Q1.drain → U1.VIN/EN + U2.VIN + C1, C3 (input
    # bulk caps on the regulators), per CP1 §3 power-architecture
    # diagram. Routing the regulators to V24_SW means they collapse
    # cleanly when Q1 is OFF — the whole point of the hard-cut.

    # Q1 — AO3401A P-MOSFET, hard-cut load switch
    Q1_X, Q1_Y = 70 * G, 50 * G   # (88.9, 63.5)
    _place_symbol(s, "Q_PMOS_GSD", "Q1", "AO3401A",
                  "Package_TO_SOT_SMD:SOT-23", (Q1_X, Q1_Y), lib=lib)
    _place_label(s, "Q1_GATE",   (Q1_X - 4 * G, Q1_Y))             # pin 1 G
    _place_label(s, "V24_FUSED", (Q1_X + 2 * G, Q1_Y + 4 * G))     # pin 2 S
    _place_label(s, "V24_SW",    (Q1_X + 2 * G, Q1_Y - 4 * G))     # pin 3 D

    # Q2 — AO3400A N-MOSFET, drives Q1's gate from PWR_EN
    Q2_X, Q2_Y = 60 * G, 60 * G   # (76.2, 76.2)
    _place_symbol(s, "Q_NMOS_GSD", "Q2", "AO3400A",
                  "Package_TO_SOT_SMD:SOT-23", (Q2_X, Q2_Y), lib=lib)
    _place_label(s, "PWR_EN",  (Q2_X - 4 * G, Q2_Y))               # pin 1 G
    _place_label(s, "GND",     (Q2_X + 2 * G, Q2_Y + 4 * G))       # pin 2 S
    _place_label(s, "Q1_GATE", (Q2_X + 2 * G, Q2_Y - 4 * G))       # pin 3 D

    # R3 — 100 kΩ Q1 gate pull-up to V24_FUSED (default-OFF)
    R3_X, R3_Y = 60 * G, 44 * G   # (76.2, 55.88)
    _place_symbol(s, "R", "R3", "100k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R3_X, R3_Y), lib=lib)
    _place_label(s, "V24_FUSED", (R3_X, R3_Y - 3 * G))   # pin 1
    _place_label(s, "Q1_GATE",   (R3_X, R3_Y + 3 * G))   # pin 2

    # R4 — 100 kΩ Q2 gate pull-down to GND (failsafe on MCU brown-out)
    R4_X, R4_Y = 48 * G, 60 * G   # (60.96, 76.2)
    _place_symbol(s, "R", "R4", "100k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R4_X, R4_Y), lib=lib)
    _place_label(s, "PWR_EN", (R4_X, R4_Y - 3 * G))   # pin 1
    _place_label(s, "GND",    (R4_X, R4_Y + 3 * G))   # pin 2

    # ===== Iter 18: MCU — MOD1 (ESP32-S3-WROOM-1-N16R8) + ESP support =====
    #
    # ESP32-S3-WROOM-1 has 41 pins. CP1 §6 (battery-side pin assignment)
    # uses 11 of them; the rest get NoConnect markers. Pin geometry from
    # the library (lib coords; KiCad Y-flip applies on schematic
    # placement → schematic_endpoint_Y = ESP_Y - lib_pin_Y).
    #
    # Module dimensions are large: 30 mm wide (±15.24 mm pins on left/right)
    # × 56 mm tall (±27.94 mm pins on top/bottom). Placed below the
    # existing power cluster so everything fits on one A4 landscape page.

    # Moved to its own right-side column on A3 (CP-schematic-cleanup
    # iter 6, criterion #3): keeps MOD1's ~30×56mm body from
    # overlapping the regulator row above it, and gives left-side
    # space for the bypass + RTC clusters that hang off MOD1's pins.
    MOD1_X, MOD1_Y = 180 * G, 110 * G   # (228.6, 139.7)

    # Pin number → (net_name or "NC"). NC pins get a NoConnect marker.
    # Per CP1 §6 ESP32-S3 pin assignment table (battery-side).
    esp_pins: dict[int, str] = {
        # Power
        1:  "GND",
        2:  "V3V3_SW",
        40: "GND",
        41: "GND",
        # EN + ADC + control
        3:  "ESP_EN",        # to R7 pull-up + C8 soft-start cap
        4:  "PWR_EN",        # IO4 → Q2 gate (real driver, drops the synthetic PWR_FLAG)
        39: "V24_SENSE",     # IO1, ADC1_CH0
        # I²C (RTC DS3231M)
        5:  "I2C_SDA",       # IO5
        6:  "I2C_SCL",       # IO6
        # Override button
        7:  "BTN_OVERRIDE",  # IO7 (RTC-wake)
        # UART1 to RS-485
        10: "UART_TX_3V3",   # IO17
        11: "UART_RX_3V3",   # IO18
        # RS-485 DE/RE
        38: "DE_RE",         # IO2
        # USB-OTG (J3 dev header — defer cluster to iter 20)
        13: "USB_DM",        # USB_D-
        14: "USB_D+ → USB_DP",  # USB_D+ — see below; using USB_DP net
        # Strap pins — leave NC per CP1 §6
        27: "NC",            # IO0 (bootloader strap)
        15: "NC",            # IO3 (USB-JTAG strap)
        # Unused expansion GPIOs — all NC per CP1 §6
        8:  "NC",            # IO15 (was debug LED — D4 removed)
        9:  "NC",            # IO16
        12: "NC",            # IO8
        16: "NC",            # IO46 (boot strap)
        17: "NC",            # IO9
        18: "NC",            # IO10
        19: "NC",            # IO11
        20: "NC",            # IO12
        21: "NC",            # IO13
        22: "NC",            # IO14
        23: "NC",            # IO21
        24: "NC",            # IO47
        25: "NC",            # IO48
        26: "NC",            # IO45 (VDD_SPI strap)
        28: "NC",            # IO35
        29: "NC",            # IO36
        30: "NC",            # IO37
        31: "NC",            # IO38
        32: "NC",            # IO39
        33: "NC",            # IO40
        34: "NC",            # IO41
        35: "NC",            # IO42
        # Debug UART (J5 dev header — defer cluster to iter 20)
        36: "DBG_UART_RX",   # RXD0
        37: "DBG_UART_TX",   # TXD0
    }
    # Fix the USB_D+ entry — that was a typo above. Should be USB_DP.
    esp_pins[14] = "USB_DP"

    # Pin lookup: build the (lib_x, lib_y) per pin number from the symbol
    # definition. This avoids hardcoding pin positions (which can change
    # if KiCad updates the symbol library).
    _esp_sym = next(s for s in lib.symbols if s.entryName == "ESP32-S3-WROOM-1")
    _esp_pin_pos = {
        int(p.number): (p.position.X, p.position.Y)
        for u in _esp_sym.units for p in u.pins
    }

    _place_symbol(s, "ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "RF_Module:ESP32-S3-WROOM-1U",  # -1U variant: external U.FL antenna, no keepout zone
                  (MOD1_X, MOD1_Y), lib=lib)
    for pin_num, net in esp_pins.items():
        lib_x, lib_y = _esp_pin_pos[pin_num]
        # KiCad Y-flip: schematic_Y = symbol_Y - lib_pin_Y
        endpoint = (MOD1_X + lib_x, MOD1_Y - lib_y)
        if net == "NC":
            _place_noconnect(s, endpoint)
        else:
            _place_label(s, net, endpoint)

    # ===== Iter 18: ESP support — R7 EN pull-up + C8 EN soft-start cap +
    #               C6 ESP bulk decoupling + C7 ESP HF decoupling =====

    # Place ESP support caps + R7 to the LEFT of MOD1 (free area above the
    # existing power cluster). Y at MOD1_Y - 30*G so the support cluster
    # is above ESP horizontally.
    SUP_Y = MOD1_Y - 30 * G

    # R7 — 10 kΩ pull-up from ESP_EN to V3V3_SW. Vertical (R pins ±3*G).
    R7_X, R7_Y = MOD1_X - 24 * G, SUP_Y
    _place_symbol(s, "R", "R7", "10k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R7_X, R7_Y), lib=lib)
    _place_label(s, "V3V3_SW", (R7_X, R7_Y - 3 * G))   # pin 1 top
    _place_label(s, "ESP_EN",  (R7_X, R7_Y + 3 * G))   # pin 2 bottom

    # C8 — 1 µF EN soft-start cap. EN to GND.
    C8_X, C8_Y = MOD1_X - 16 * G, SUP_Y
    _place_symbol(s, "C", "C8", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C8_X, C8_Y), lib=lib)
    _place_label(s, "ESP_EN", (C8_X, C8_Y - 3 * G))
    _place_label(s, "GND",    (C8_X, C8_Y + 3 * G))

    # C6 — 10 µF ESP bulk on V3V3_SW
    C6_X, C6_Y = MOD1_X - 8 * G, SUP_Y
    _place_symbol(s, "C", "C6", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C6_X, C6_Y), lib=lib)
    _place_label(s, "V3V3_SW", (C6_X, C6_Y - 3 * G))
    _place_label(s, "GND",     (C6_X, C6_Y + 3 * G))

    # C7 — 100 nF ESP HF decoupling
    C7_X, C7_Y = MOD1_X, SUP_Y
    _place_symbol(s, "C", "C7", "100nF",
                  "Capacitor_SMD:C_0402_1005Metric",
                  (C7_X, C7_Y), lib=lib)
    _place_label(s, "V3V3_SW", (C7_X, C7_Y - 3 * G))
    _place_label(s, "GND",     (C7_X, C7_Y + 3 * G))

    # ===== Iter 20: RTC + RS-485 + button + connectors + dev headers =====
    # Last sub-iter on the battery-side schematic. Completes the design.

    # RTC1 — DS3231M (SOIC-16). Pin geometry from inspection:
    #   pin 2  VCC          lib (-2.54, 10.16), 270  → sch (X-2.54, Y-10.16)
    #   pin 13 GND (pwr_in) lib ( 0,   -10.16), 90   → sch (X, Y+10.16)
    #   pin 14 VBAT         lib ( 0,    10.16), 270  → sch (X, Y-10.16)
    #   pin 15 SDA          lib (-12.7, 2.54),  0    → sch (X-12.7, Y-2.54)
    #   pin 16 SCL          lib (-12.7, 5.08),  0    → sch (X-12.7, Y-5.08)
    #   pin 4  RST (bidir)  lib (-12.7,-5.08),  0    → sch (X-12.7, Y+5.08)
    #   pin 1  32KHZ (oc)   lib ( 12.7, 5.08),  180  → sch (X+12.7, Y-5.08)
    #   pin 3  INT/SQW (oc) lib ( 12.7,-2.54),  180  → sch (X+12.7, Y+2.54)
    #   pins 5-12 GND all map to (X, Y+10.16) — same endpoint as pin 13
    RTC1_X, RTC1_Y = 60 * G, 95 * G   # (76.2, 120.65)
    _place_symbol(s, "DS3231M", "RTC1", "DS3231SN#",
                  "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
                  (RTC1_X, RTC1_Y), lib=lib)
    _place_label(s, "V3V3_SW",  (RTC1_X - 2 * G, RTC1_Y - 8 * G))   # pin 2 VCC
    _place_label(s, "V_BAT_RTC",(RTC1_X,         RTC1_Y - 8 * G))   # pin 14 VBAT
    _place_label(s, "GND",      (RTC1_X,         RTC1_Y + 8 * G))   # pins 5-13 GND (shared endpoint)
    _place_label(s, "I2C_SDA",  (RTC1_X - 10 * G, RTC1_Y - 2 * G))  # pin 15 SDA
    _place_label(s, "I2C_SCL",  (RTC1_X - 10 * G, RTC1_Y - 4 * G))  # pin 16 SCL
    _place_noconnect(s, (RTC1_X - 10 * G, RTC1_Y + 4 * G))          # pin 4 RST
    _place_noconnect(s, (RTC1_X + 10 * G, RTC1_Y - 4 * G))          # pin 1 32KHZ
    _place_noconnect(s, (RTC1_X + 10 * G, RTC1_Y + 2 * G))          # pin 3 INT/SQW

    # BAT1 — CR2032 holder, 2-pin (+, -)
    #   pin 1 + lib (0,  5.08), 270 → sch (X, Y-5.08)
    #   pin 2 - lib (0, -2.54),  90 → sch (X, Y+2.54)
    BAT1_X, BAT1_Y = 40 * G, 85 * G   # (50.8, 107.95)
    _place_symbol(s, "Battery_Cell", "BAT1", "CR2032",
                  "Battery:BatteryHolder_Keystone_1057_1x2032",
                  (BAT1_X, BAT1_Y), lib=lib)
    _place_label(s, "V_BAT_RTC", (BAT1_X, BAT1_Y - 4 * G))   # pin 1 + (4*G = -5.08 rounded; lib_Y=5.08)
    _place_label(s, "GND",       (BAT1_X, BAT1_Y + 2 * G))   # pin 2 - (lib_Y=-2.54)

    # C9 — 100 nF RTC VCC decoupling. Moved well away from RTC1's left-edge
    # pins (SCL/SDA/RST at X=63.5) to avoid endpoint collisions with the
    # I2C labels — C9 pin 2 used to land at (63.5, 115.57) right on top of
    # RTC1.SCL's endpoint, forcing GND and I2C_SCL onto the same net.
    C9_X, C9_Y = 16 * G, 95 * G   # (20.32, 120.65)
    _place_symbol(s, "C", "C9", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C9_X, C9_Y), lib=lib)
    _place_label(s, "V3V3_SW", (C9_X, C9_Y - 3 * G))
    _place_label(s, "GND",     (C9_X, C9_Y + 3 * G))

    # R8/R9 — I²C pull-ups (SDA/SCL → V3V3_SW)
    R8_X, R8_Y = 36 * G, 90 * G   # (45.72, 114.3)
    _place_symbol(s, "R", "R8", "4.7k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R8_X, R8_Y), lib=lib)
    _place_label(s, "V3V3_SW", (R8_X, R8_Y - 3 * G))
    _place_label(s, "I2C_SDA", (R8_X, R8_Y + 3 * G))
    R9_X, R9_Y = 30 * G, 90 * G   # (38.1, 114.3)
    _place_symbol(s, "R", "R9", "4.7k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R9_X, R9_Y), lib=lib)
    _place_label(s, "V3V3_SW", (R9_X, R9_Y - 3 * G))
    _place_label(s, "I2C_SCL", (R9_X, R9_Y + 3 * G))

    # U3 — RS-485 transceiver (LTC2850xS8 stand-in for SN65HVD3082E).
    # Pin geometry from inspection:
    #   pin 1 RO     lib (-10.16,  5.08), 0    → sch (X-10.16, Y-5.08)
    #   pin 2 ~RE    lib (-10.16,  2.54), 0    → sch (X-10.16, Y-2.54)
    #   pin 3 DE     lib (-10.16,  0),    0    → sch (X-10.16, Y)
    #   pin 4 DI     lib (-10.16, -5.08), 0    → sch (X-10.16, Y+5.08)
    #   pin 5 GND    lib (0,     -15.24), 90   → sch (X,       Y+15.24)
    #   pin 6 A      lib (10.16,  7.62),  180  → sch (X+10.16, Y-7.62)
    #   pin 7 B      lib (10.16,  2.54),  180  → sch (X+10.16, Y-2.54)
    #   pin 8 VCC    lib (0,      15.24), 270  → sch (X,       Y-15.24)
    U3_X, U3_Y = 220 * G, 50 * G   # (279.4, 63.5)
    _place_symbol(s, "LTC2850xS8", "U3", "SN65HVD3082E",
                  "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                  (U3_X, U3_Y), lib=lib)
    _place_label(s, "UART_RX_3V3", (U3_X - 8 * G,  U3_Y - 4 * G))   # pin 1 RO
    _place_label(s, "DE_RE",       (U3_X - 8 * G,  U3_Y - 2 * G))   # pin 2 ~RE (tied to DE)
    _place_label(s, "DE_RE",       (U3_X - 8 * G,  U3_Y))            # pin 3 DE
    _place_label(s, "UART_TX_3V3", (U3_X - 8 * G,  U3_Y + 4 * G))   # pin 4 DI
    _place_label(s, "GND",         (U3_X,          U3_Y + 12 * G))   # pin 5 GND
    _place_label(s, "RS485_A",     (U3_X + 8 * G,  U3_Y - 6 * G))   # pin 6 A
    _place_label(s, "RS485_B",     (U3_X + 8 * G,  U3_Y - 2 * G))   # pin 7 B
    _place_label(s, "V3V3_SW",     (U3_X,          U3_Y - 12 * G))   # pin 8 VCC

    # C10 — 100 nF U3 VCC decoupling
    C10_X, C10_Y = U3_X + 6 * G, U3_Y - 10 * G   # (287.02, 50.8)
    _place_symbol(s, "C", "C10", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C10_X, C10_Y), lib=lib)
    _place_label(s, "V3V3_SW", (C10_X, C10_Y - 3 * G))
    _place_label(s, "GND",     (C10_X, C10_Y + 3 * G))

    # R10 — 120 Ω RS-485 termination (A ↔ B). Horizontal so both pins
    # land on the A/B nets without rotating the symbol.
    R10_X, R10_Y = U3_X + 16 * G, U3_Y - 4 * G   # (299.72, 58.42)
    _place_symbol(s, "R", "R10", "120",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R10_X, R10_Y), lib=lib)
    _place_label(s, "RS485_A", (R10_X, R10_Y - 3 * G))   # pin 1
    _place_label(s, "RS485_B", (R10_X, R10_Y + 3 * G))   # pin 2

    # R11 — 680 Ω idle bias A → V3V3_SW
    R11_X, R11_Y = U3_X + 12 * G, U3_Y - 12 * G   # (294.64, 47.62)
    _place_symbol(s, "R", "R11", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R11_X, R11_Y), lib=lib)
    _place_label(s, "V3V3_SW", (R11_X, R11_Y - 3 * G))
    _place_label(s, "RS485_A", (R11_X, R11_Y + 3 * G))

    # R12 — 680 Ω idle bias B → GND
    R12_X, R12_Y = U3_X + 12 * G, U3_Y + 8 * G   # (294.64, 73.66)
    _place_symbol(s, "R", "R12", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R12_X, R12_Y), lib=lib)
    _place_label(s, "RS485_B", (R12_X, R12_Y - 3 * G))
    _place_label(s, "GND",     (R12_X, R12_Y + 3 * G))

    # TVS2 — SMAJ12CA differential clamp across A/B. Device:D_TVS with
    # Value override. Horizontal (pins ±3.81 X from center).
    TVS2_X, TVS2_Y = U3_X + 20 * G, U3_Y - 4 * G   # (304.8, 58.42)
    _place_symbol(s, "D_TVS", "TVS2", "SMAJ12CA",
                  "Diode_SMD:D_SMA",
                  (TVS2_X, TVS2_Y), lib=lib)
    _place_label(s, "RS485_A", (TVS2_X - 3 * G, TVS2_Y))   # pin 1
    _place_label(s, "RS485_B", (TVS2_X + 3 * G, TVS2_Y))   # pin 2

    # BTN1 — Override pushbutton, SW_Push (2-pin horizontal).
    # Pin geometry: pin 1 lib (-5.08, 0) angle 0 → sch (X-5.08, Y);
    #               pin 2 lib (5.08, 0)  angle 180 → sch (X+5.08, Y).
    BTN1_X, BTN1_Y = 60 * G, 110 * G   # (76.2, 139.7)
    _place_symbol(s, "SW_Push", "BTN1", "OVERRIDE",
                  "Button_Switch_THT:SW_PUSH_6mm",
                  (BTN1_X, BTN1_Y), lib=lib)
    _place_label(s, "BTN_OVERRIDE", (BTN1_X - 4 * G, BTN1_Y))   # pin 1
    _place_label(s, "GND",          (BTN1_X + 4 * G, BTN1_Y))   # pin 2

    # R13 — 1 MΩ pull-up BTN_OVERRIDE → V3V3_SW
    R13_X, R13_Y = 70 * G, 110 * G   # (88.9, 139.7)
    _place_symbol(s, "R", "R13", "1M",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R13_X, R13_Y), lib=lib)
    _place_label(s, "V3V3_SW",      (R13_X, R13_Y - 3 * G))
    _place_label(s, "BTN_OVERRIDE", (R13_X, R13_Y + 3 * G))

    # C11 — 100 nF button debounce
    C11_X, C11_Y = 80 * G, 110 * G   # (101.6, 139.7)
    _place_symbol(s, "C", "C11", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C11_X, C11_Y), lib=lib)
    _place_label(s, "BTN_OVERRIDE", (C11_X, C11_Y - 3 * G))
    _place_label(s, "GND",          (C11_X, C11_Y + 3 * G))

    # J2 — RJ45 (8P8C parent). Cat5e to display side. T568B pinout
    # per docs/hardware/cat5e_pinout.md:
    #   pin 1 white-orange  → +12V (V12_CAT5E)
    #   pin 2 orange        → +12V
    #   pin 3 white-green   → +12V
    #   pin 4 blue          → RS485_A
    #   pin 5 white-blue    → RS485_B
    #   pin 6 green         → GND
    #   pin 7 white-brown   → GND
    #   pin 8 brown         → GND
    # 8P8C pin lib coords: all at X=+10.16, Y from -7.62 (pin 1) to
    # +10.16 (pin 8) in 2.54mm steps → sch (X+10.16, Y - lib_Y).
    J2_X, J2_Y = 240 * G, 90 * G   # (304.8, 114.3)
    _place_symbol(s, "8P8C", "J2", "RJ45",
                  "Connector_RJ:RJ45_Amphenol_RJHSE5380",
                  (J2_X, J2_Y), lib=lib)
    # Pin Y offsets from symbol center (after Y-flip): pin 1=+7.62 below,
    # pin 8=-10.16 above. Use 3*G grid alignment (lib_Y values are
    # multiples of 2.54 = 2*G, so Y-flip gives multiples of 2*G).
    _place_label(s, "V12_CAT5E", (J2_X + 8 * G, J2_Y + 6 * G))   # pin 1 (lib_Y=-7.62)
    _place_label(s, "V12_CAT5E", (J2_X + 8 * G, J2_Y + 4 * G))   # pin 2 (lib_Y=-5.08)
    _place_label(s, "V12_CAT5E", (J2_X + 8 * G, J2_Y + 2 * G))   # pin 3 (lib_Y=-2.54)
    _place_label(s, "RS485_A",   (J2_X + 8 * G, J2_Y))            # pin 4 (lib_Y= 0)
    _place_label(s, "RS485_B",   (J2_X + 8 * G, J2_Y - 2 * G))   # pin 5 (lib_Y=+2.54)
    _place_label(s, "GND",       (J2_X + 8 * G, J2_Y - 4 * G))   # pin 6 (lib_Y=+5.08)
    _place_label(s, "GND",       (J2_X + 8 * G, J2_Y - 6 * G))   # pin 7 (lib_Y=+7.62)
    _place_label(s, "GND",       (J2_X + 8 * G, J2_Y - 8 * G))   # pin 8 (lib_Y=+10.16)

    # J3 — 4-pin USB-OTG dev header (D+/D-/EN/GND)
    # Conn_01x04 pin lib: pin 1 (-5.08, 2.54), pin 2 (-5.08, 0),
    # pin 3 (-5.08, -2.54), pin 4 (-5.08, -5.08).
    # Sch endpoints: (X-5.08, Y - lib_Y).
    J3_X, J3_Y = 270 * G, 110 * G   # (342.9, 139.7)
    _place_symbol(s, "Conn_01x04", "J3", "USB-OTG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J3_X, J3_Y), lib=lib)
    _place_label(s, "USB_DP",  (J3_X - 4 * G, J3_Y - 2 * G))   # pin 1 (lib_Y=+2.54)
    _place_label(s, "USB_DM",  (J3_X - 4 * G, J3_Y))           # pin 2 (lib_Y= 0)
    _place_label(s, "ESP_EN",  (J3_X - 4 * G, J3_Y + 2 * G))   # pin 3 (lib_Y=-2.54)
    _place_label(s, "GND",     (J3_X - 4 * G, J3_Y + 4 * G))   # pin 4 (lib_Y=-5.08)

    # J5 — 4-pin UART debug header (TX/RX/GND/RESET#).
    # Reset (ESP_EN) reuses J3.3; J5 just exposes UART RX/TX + GND + EN.
    J5_X, J5_Y = 270 * G, 120 * G   # (342.9, 152.4)
    _place_symbol(s, "Conn_01x04", "J5", "UART-DBG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J5_X, J5_Y), lib=lib)
    _place_label(s, "DBG_UART_TX", (J5_X - 4 * G, J5_Y - 2 * G))   # pin 1
    _place_label(s, "DBG_UART_RX", (J5_X - 4 * G, J5_Y))           # pin 2
    _place_label(s, "GND",         (J5_X - 4 * G, J5_Y + 2 * G))   # pin 3
    _place_label(s, "ESP_EN",      (J5_X - 4 * G, J5_Y + 4 * G))   # pin 4 RESET#

    # ===== Power flags =====
    # In KiCad's ERC model, a `power_in` pin (like U1.VIN, U1.GND) needs a
    # matching `power_out` pin OR a PWR_FLAG on the same net. Our V24 source
    # is the battery itself (external to the schematic) and arrives via
    # passive connector pins — those don't satisfy ERC. PWR_FLAG is the
    # standard pattern for nets sourced from outside the schematic. We
    # keep these for the lifetime of the design.
    _place_power_flag(s, "V24_FUSED", (R5_X - 20 * G, R5_Y - 3 * G), lib)
    _place_power_flag(s, "GND",       (R5_X - 20 * G, R6_Y + 3 * G), lib)
    # V24_SW gets a PWR_FLAG too. ERC-wise, Q1.drain is `passive`, so it
    # doesn't drive the net even though Q1 physically passes V24_FUSED → V24_SW
    # when ON. U1.VIN and U2.VIN are `power_in` pins that need a source.
    _place_power_flag(s, "V24_SW",    (R5_X - 20 * G, (R5_Y + R6_Y) / 2), lib)
    # V3V3_SW: MOD1.3V3 is `power_input`. U1's SW pin is `output`, not
    # `power_output`, so ERC needs a flag here. The regulator output IS
    # really the source — flag is just ERC bookkeeping.
    _place_power_flag(s, "V3V3_SW",   (R5_X - 20 * G, R5_Y + 16 * G), lib)
    # V_BAT_RTC: RTC1.VBAT is `power_input`. BAT1.+ (CR2032 holder) is
    # `passive` per KiCad — the cell IS the source but ERC needs a flag.
    # Y offset moved from +20*G to +26*G to clear Q2 at (60*G, 60*G);
    # the +20*G value collided exactly with Q2 (D11 criterion #1 fix).
    _place_power_flag(s, "V_BAT_RTC", (R5_X - 20 * G, R5_Y + 26 * G), lib)
    # PWR_EN is now driven by MOD1.IO4 (bidirectional). MOD1 landed in
    # iter 18, so the synthetic PWR_EN PWR_FLAG is no longer needed —
    # dropped.
    # V3V3_SW (U1 output) and V12_CAT5E (U2 output): regulator outputs are
    # `output` type which ERC accepts as drivers. No PWR_FLAG needed.

    out = BATT_DIR / "battery_side.kicad_sch"
    out.parent.mkdir(parents=True, exist_ok=True)
    s.to_file(str(out))
    print(f"  + {out} ({out.stat().st_size} bytes; {len(s.schematicSymbols)} symbols, {len(s.globalLabels)} labels)")


def build_display_side_schematic() -> None:
    """Generate the display-side schematic (CP2 iter 22).

    Per cp1_display_side.md. Simpler than battery-side: no hard-cut MOSFETs,
    no V24 rail, no RTC. Just a Cat5e-fed 12V→3V3 buck, the same ESP32-S3
    module, the e-paper FFC, an RS-485 transceiver, three software-defined
    buttons, and dev headers.
    """
    s = Schematic.create_new()
    s.generator = "volthium-build-schematics"
    _set_title_block(s, "Volthium reader — display side")
    lib = _load_project_lib()
    G = 1.27

    # ===== Power input: J1 RJ45 → F1 PTC → TVS1 → C1 input bulk =====

    # J1 — RJ45 Cat5e in (T568B). Pin mapping per docs/hardware/cat5e_pinout.md:
    # pins 1/2/3 = V12_CAT5E, pin 4 = RS485_A, pin 5 = RS485_B,
    # pins 6/7/8 = GND. Symbol 8P8C with Value=RJ45 override.
    J1_X, J1_Y = 30 * G, 50 * G   # (38.1, 63.5)
    _place_symbol(s, "8P8C", "J1", "RJ45",
                  "Connector_RJ:RJ45_Amphenol_RJHSE5380",
                  (J1_X, J1_Y), lib=lib)
    # 8P8C pins at X=+10.16, lib_Y from -7.62 (pin 1) to +10.16 (pin 8)
    # in 2.54 mm steps → schematic endpoint (X+10.16, Y - lib_Y).
    _place_label(s, "V12_CAT5E", (J1_X + 8 * G, J1_Y + 6 * G))   # pin 1
    _place_label(s, "V12_CAT5E", (J1_X + 8 * G, J1_Y + 4 * G))   # pin 2
    _place_label(s, "V12_CAT5E", (J1_X + 8 * G, J1_Y + 2 * G))   # pin 3
    _place_label(s, "RS485_A",   (J1_X + 8 * G, J1_Y))            # pin 4
    _place_label(s, "RS485_B",   (J1_X + 8 * G, J1_Y - 2 * G))   # pin 5
    _place_label(s, "GND",       (J1_X + 8 * G, J1_Y - 4 * G))   # pin 6
    _place_label(s, "GND",       (J1_X + 8 * G, J1_Y - 6 * G))   # pin 7
    _place_label(s, "GND",       (J1_X + 8 * G, J1_Y - 8 * G))   # pin 8

    # F1 — PTC polyfuse (0.5A hold) on V12_CAT5E
    F1_X, F1_Y = 55 * G, 50 * G   # (69.85, 63.5)
    _place_symbol(s, "Polyfuse", "F1", "MF-R050",
                  "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
                  (F1_X, F1_Y), lib=lib)
    # Polyfuse pin geometry mirrors Fuse/R (lib Y ±3.81 → sch Y ∓3.81).
    _place_label(s, "V12_CAT5E", (F1_X, F1_Y - 3 * G))   # pin 1
    _place_label(s, "V12_PROT",  (F1_X, F1_Y + 3 * G))   # pin 2

    # TVS1 — SMAJ15A unidirectional TVS on V12_PROT ↔ GND
    TVS1_X, TVS1_Y = 70 * G, 50 * G   # (88.9, 63.5)
    _place_symbol(s, "D", "TVS1", "SMAJ15A",
                  "Diode_SMD:D_SMA",
                  (TVS1_X, TVS1_Y), lib=lib)
    _place_label(s, "GND",      (TVS1_X - 3 * G, TVS1_Y))   # pin 1 K
    _place_label(s, "V12_PROT", (TVS1_X + 3 * G, TVS1_Y))   # pin 2 A

    # C1 — 22µF/25V input bulk on V12_PROT
    C1_X, C1_Y = 60 * G, 60 * G   # (76.2, 76.2)
    _place_symbol(s, "C", "C1", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C1_X, C1_Y), lib=lib)
    _place_label(s, "V12_PROT", (C1_X, C1_Y - 3 * G))
    _place_label(s, "GND",      (C1_X, C1_Y + 3 * G))

    # ===== Power conversion: U1 Recom R-78E3.3-0.5 + C2 output bulk =====

    # U1 — Recom R-78E3.3-0.5 (12V → 3V3, 0.5A). Conn_01x03 stand-in:
    # pin 1 lib (-5.08, +2.54) → sch (X-5.08, Y-2.54) — VIN
    # pin 2 lib (-5.08, 0)     → sch (X-5.08, Y)        — GND
    # pin 3 lib (-5.08, -2.54) → sch (X-5.08, Y+2.54)   — VOUT
    U1_X, U1_Y = 85 * G, 50 * G   # (107.95, 63.5)
    _place_symbol(s, "Conn_01x03", "U1", "R-78E3.3-0.5",
                  "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                  (U1_X, U1_Y), lib=lib)
    _place_label(s, "V12_PROT", (U1_X - 4 * G, U1_Y - 2 * G))   # pin 1 VIN
    _place_label(s, "GND",      (U1_X - 4 * G, U1_Y))            # pin 2 GND
    _place_label(s, "V3V3",     (U1_X - 4 * G, U1_Y + 2 * G))   # pin 3 VOUT

    # C2 — 10µF output bulk on V3V3
    C2_X, C2_Y = 95 * G, 60 * G   # (120.65, 76.2)
    _place_symbol(s, "C", "C2", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C2_X, C2_Y), lib=lib)
    _place_label(s, "V3V3", (C2_X, C2_Y - 3 * G))
    _place_label(s, "GND",  (C2_X, C2_Y + 3 * G))

    # ===== MCU: MOD1 ESP32-S3-WROOM-1-N16R8 (different pin map vs battery side) =====

    MOD1_X, MOD1_Y = 140 * G, 100 * G   # (177.8, 127.0)

    # Pin map per cp1_display_side.md §6. Different from battery side:
    # no PWR_EN/V24_SENSE/BTN_OVERRIDE/I2C; instead SPI to e-paper +
    # 3 buttons + dev headers.
    esp_pins: dict[int, str] = {
        # Power
        1:  "GND",
        2:  "V3V3",
        40: "GND",
        41: "GND",
        # EN
        3:  "ESP_EN",
        # RS-485 control + UART1
        38: "DE_RE",         # IO2
        10: "UART_TX_3V3",   # IO17
        11: "UART_RX_3V3",   # IO18
        # E-paper SPI
        5:  "EPD_CS",        # IO5
        6:  "EPD_DC",        # IO6
        7:  "EPD_RST",       # IO7
        12: "EPD_BUSY",      # IO8
        17: "SPI_SCK",       # IO9
        18: "SPI_MOSI",      # IO10
        # Buttons
        20: "BTN1_IN",       # IO12
        21: "BTN2_IN",       # IO13
        22: "BTN3_IN",       # IO14
        # USB-OTG (dev)
        13: "USB_DM",        # USB_D-
        14: "USB_DP",        # USB_D+
        # Debug UART (dev)
        36: "DBG_UART_RX",   # RXD0
        37: "DBG_UART_TX",   # TXD0
        # Strap pins — leave NC per CP1 §6
        27: "NC",            # IO0
        15: "NC",            # IO3
        16: "NC",            # IO46 (boot)
        26: "NC",            # IO45 (VDD_SPI)
        # Unused expansion
        4:  "NC",            # IO4 (no PWR_EN on display side)
        8:  "NC",            # IO15
        9:  "NC",            # IO16
        19: "NC",            # IO11
        23: "NC",            # IO21
        24: "NC",            # IO47
        25: "NC",            # IO48
        28: "NC",            # IO35
        29: "NC",            # IO36
        30: "NC",            # IO37
        31: "NC",            # IO38
        32: "NC",            # IO39
        33: "NC",            # IO40
        34: "NC",            # IO41
        35: "NC",            # IO42
        # Pins 38, 39 = IO2/IO1 — IO2 used (DE_RE), IO1 unused
        39: "NC",            # IO1
    }

    # Pin position lookup from symbol definition
    _esp_sym = next(s for s in lib.symbols if s.entryName == "ESP32-S3-WROOM-1")
    _esp_pin_pos = {
        int(p.number): (p.position.X, p.position.Y)
        for u in _esp_sym.units for p in u.pins
    }

    _place_symbol(s, "ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "RF_Module:ESP32-S3-WROOM-1U",  # -1U variant: external U.FL antenna, no keepout zone
                  (MOD1_X, MOD1_Y), lib=lib)
    for pin_num, net in esp_pins.items():
        lib_x, lib_y = _esp_pin_pos[pin_num]
        endpoint = (MOD1_X + lib_x, MOD1_Y - lib_y)
        if net == "NC":
            _place_noconnect(s, endpoint)
        else:
            _place_label(s, net, endpoint)

    # ===== ESP support: R1 EN pull-up + C5 EN soft-start + C3 bulk + C4 HF =====
    SUP_Y = MOD1_Y - 32 * G
    # R1 — 10kΩ EN pull-up
    R1_X, R1_Y = MOD1_X - 24 * G, SUP_Y
    _place_symbol(s, "R", "R1", "10k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R1_X, R1_Y), lib=lib)
    _place_label(s, "V3V3",   (R1_X, R1_Y - 3 * G))
    _place_label(s, "ESP_EN", (R1_X, R1_Y + 3 * G))
    # C5 — 1µF EN soft-start
    C5_X, C5_Y = MOD1_X - 16 * G, SUP_Y
    _place_symbol(s, "C", "C5", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C5_X, C5_Y), lib=lib)
    _place_label(s, "ESP_EN", (C5_X, C5_Y - 3 * G))
    _place_label(s, "GND",    (C5_X, C5_Y + 3 * G))
    # C3 — 10µF ESP bulk
    C3_X, C3_Y = MOD1_X - 8 * G, SUP_Y
    _place_symbol(s, "C", "C3", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C3_X, C3_Y), lib=lib)
    _place_label(s, "V3V3", (C3_X, C3_Y - 3 * G))
    _place_label(s, "GND",  (C3_X, C3_Y + 3 * G))
    # C4 — 100nF ESP HF decoupling
    C4_X, C4_Y = MOD1_X, SUP_Y
    _place_symbol(s, "C", "C4", "100nF",
                  "Capacitor_SMD:C_0402_1005Metric",
                  (C4_X, C4_Y), lib=lib)
    _place_label(s, "V3V3", (C4_X, C4_Y - 3 * G))
    _place_label(s, "GND",  (C4_X, C4_Y + 3 * G))

    # ===== E-paper FFC: J2 Hirose FH12-24S + C6 panel VCC bulk =====
    #
    # Tentative pin mapping per legacy SKiDL — Waveshare 4.2" e-Paper (B) v2.
    # CP1 §4.4 calls out that this must be verified against the panel
    # datasheet before fab. Placeholder mapping:
    #   pin 1 GND, pin 2 VCC (V3V3), pin 3 V3V3 logic, pin 4 GND,
    #   pin 5 BUSY, pin 6 RST, pin 7 DC, pin 8 CS,
    #   pin 9 SCK, pin 10 MOSI, pins 11-24 unused (NC).
    # Conn_01x24 pin geometry: pin N at lib (-5.08, 27.94 - 2.54*(N-1)),
    # angle 0 → sch (X-5.08, Y - lib_Y).
    J2_X, J2_Y = 50 * G, 130 * G   # (63.5, 165.1)
    _place_symbol(s, "Conn_01x24", "J2", "EPD_FFC_24",
                  "Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal",
                  (J2_X, J2_Y), lib=lib)
    epd_pins = {
        1: "GND",
        2: "V3V3",
        3: "V3V3",
        4: "GND",
        5: "EPD_BUSY",
        6: "EPD_RST",
        7: "EPD_DC",
        8: "EPD_CS",
        9: "SPI_SCK",
        10: "SPI_MOSI",
        # pins 11-24 reserved / unused — NoConnect
    }
    for pin in range(1, 25):
        # lib_Y = 27.94 - 2.54*(pin-1) → schematic Y = J2_Y - lib_Y
        lib_y = 27.94 - 2.54 * (pin - 1)
        endpoint = (J2_X - 5.08, J2_Y - lib_y)
        if pin in epd_pins:
            _place_label(s, epd_pins[pin], endpoint)
        else:
            _place_noconnect(s, endpoint)

    # C6 — 1µF panel VCC bulk (reduces VCC dip during refresh)
    C6_X, C6_Y = 60 * G, 90 * G   # (76.2, 114.3)
    _place_symbol(s, "C", "C6", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C6_X, C6_Y), lib=lib)
    _place_label(s, "V3V3", (C6_X, C6_Y - 3 * G))
    _place_label(s, "GND",  (C6_X, C6_Y + 3 * G))

    # ===== RS-485: U2 (LTC2850xS8 stand-in for SN65HVD3082E) + passives =====
    # Same topology as battery-side U3. This end is the bus terminus (R2
    # populated). Idle bias R3/R4 footprints provided but treated as
    # populated for ERC simplicity (CP1 D-OPEN-8 default says "don't
    # populate by default" but ERC-wise we still place them since the
    # bias defines the idle state of the differential pair).
    U2_X, U2_Y = 220 * G, 80 * G   # (279.4, 101.6)
    _place_symbol(s, "LTC2850xS8", "U2", "SN65HVD3082E",
                  "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                  (U2_X, U2_Y), lib=lib)
    _place_label(s, "UART_RX_3V3", (U2_X - 8 * G, U2_Y - 4 * G))   # pin 1 RO
    _place_label(s, "DE_RE",       (U2_X - 8 * G, U2_Y - 2 * G))   # pin 2 ~RE
    _place_label(s, "DE_RE",       (U2_X - 8 * G, U2_Y))            # pin 3 DE
    _place_label(s, "UART_TX_3V3", (U2_X - 8 * G, U2_Y + 4 * G))   # pin 4 DI
    _place_label(s, "GND",         (U2_X,         U2_Y + 12 * G))   # pin 5 GND
    _place_label(s, "RS485_A",     (U2_X + 8 * G, U2_Y - 6 * G))   # pin 6 A
    _place_label(s, "RS485_B",     (U2_X + 8 * G, U2_Y - 2 * G))   # pin 7 B
    _place_label(s, "V3V3",        (U2_X,         U2_Y - 12 * G))   # pin 8 VCC

    # C7 — 100nF U2 VCC decoupling
    C7_X, C7_Y = U2_X + 6 * G, U2_Y - 10 * G   # (286.94, 88.9)
    _place_symbol(s, "C", "C7", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C7_X, C7_Y), lib=lib)
    _place_label(s, "V3V3", (C7_X, C7_Y - 3 * G))
    _place_label(s, "GND",  (C7_X, C7_Y + 3 * G))

    # R2 — 120Ω termination (A ↔ B), bus terminus
    R2_X, R2_Y = U2_X + 16 * G, U2_Y - 4 * G   # (299.72, 96.52)
    _place_symbol(s, "R", "R2", "120",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R2_X, R2_Y), lib=lib)
    _place_label(s, "RS485_A", (R2_X, R2_Y - 3 * G))
    _place_label(s, "RS485_B", (R2_X, R2_Y + 3 * G))

    # R3 — 680Ω idle bias A → V3V3
    R3_X, R3_Y = U2_X + 12 * G, U2_Y - 12 * G   # (294.64, 85.72)
    _place_symbol(s, "R", "R3", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R3_X, R3_Y), lib=lib)
    _place_label(s, "V3V3",    (R3_X, R3_Y - 3 * G))
    _place_label(s, "RS485_A", (R3_X, R3_Y + 3 * G))

    # R4 — 680Ω idle bias B → GND
    R4_X, R4_Y = U2_X + 12 * G, U2_Y + 8 * G   # (294.64, 111.76)
    _place_symbol(s, "R", "R4", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R4_X, R4_Y), lib=lib)
    _place_label(s, "RS485_B", (R4_X, R4_Y - 3 * G))
    _place_label(s, "GND",     (R4_X, R4_Y + 3 * G))

    # TVS2 — SMAJ12CA differential clamp across A/B
    TVS2_X, TVS2_Y = U2_X + 20 * G, U2_Y - 4 * G   # (304.8, 96.52)
    _place_symbol(s, "D_TVS", "TVS2", "SMAJ12CA",
                  "Diode_SMD:D_SMA",
                  (TVS2_X, TVS2_Y), lib=lib)
    _place_label(s, "RS485_A", (TVS2_X - 3 * G, TVS2_Y))
    _place_label(s, "RS485_B", (TVS2_X + 3 * G, TVS2_Y))

    # ===== Buttons: BTN1/2/3 + R5/R6/R7 (1MΩ pull-ups) + C8/C9/C10 (debounce) =====

    # Place 3 button clusters horizontally, evenly spaced.
    for i, (btn_ref, r_ref, c_ref, btn_net) in enumerate([
        ("BTN1", "R5", "C8",  "BTN1_IN"),
        ("BTN2", "R6", "C9",  "BTN2_IN"),
        ("BTN3", "R7", "C10", "BTN3_IN"),
    ]):
        BTN_X = (200 + i * 30) * G   # 254, 292.1, 330.2
        BTN_Y = 150 * G              # 190.5
        _place_symbol(s, "SW_Push", btn_ref, btn_ref,
                      "Button_Switch_SMD:SW_SPST_B3S-1000",
                      (BTN_X, BTN_Y), lib=lib)
        _place_label(s, btn_net, (BTN_X - 4 * G, BTN_Y))   # pin 1
        _place_label(s, "GND",   (BTN_X + 4 * G, BTN_Y))   # pin 2
        # R — 1MΩ pull-up
        R_X = BTN_X + 8 * G
        _place_symbol(s, "R", r_ref, "1M",
                      "Resistor_SMD:R_0805_2012Metric",
                      (R_X, BTN_Y), lib=lib)
        _place_label(s, "V3V3",  (R_X, BTN_Y - 3 * G))
        _place_label(s, btn_net, (R_X, BTN_Y + 3 * G))
        # C — 100nF debounce
        C_X = BTN_X + 16 * G
        _place_symbol(s, "C", c_ref, "100nF",
                      "Capacitor_SMD:C_0603_1608Metric",
                      (C_X, BTN_Y), lib=lib)
        _place_label(s, btn_net, (C_X, BTN_Y - 3 * G))
        _place_label(s, "GND",   (C_X, BTN_Y + 3 * G))

    # ===== Dev headers: J3 (UART debug) + J4 (USB-OTG) =====

    # J3 — UART debug: TX/RX/GND/RESET#
    J3_X, J3_Y = 30 * G, 120 * G   # (38.1, 152.4)
    _place_symbol(s, "Conn_01x04", "J3", "UART-DBG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J3_X, J3_Y), lib=lib)
    _place_label(s, "DBG_UART_TX", (J3_X - 4 * G, J3_Y - 2 * G))   # pin 1
    _place_label(s, "DBG_UART_RX", (J3_X - 4 * G, J3_Y))            # pin 2
    _place_label(s, "GND",         (J3_X - 4 * G, J3_Y + 2 * G))   # pin 3
    _place_label(s, "ESP_EN",      (J3_X - 4 * G, J3_Y + 4 * G))   # pin 4

    # J4 — USB-OTG: D+/D-/GND/V3V3
    J4_X, J4_Y = 30 * G, 130 * G   # (38.1, 165.1)
    _place_symbol(s, "Conn_01x04", "J4", "USB-OTG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J4_X, J4_Y), lib=lib)
    _place_label(s, "USB_DP", (J4_X - 4 * G, J4_Y - 2 * G))
    _place_label(s, "USB_DM", (J4_X - 4 * G, J4_Y))
    _place_label(s, "GND",    (J4_X - 4 * G, J4_Y + 2 * G))
    _place_label(s, "V3V3",   (J4_X - 4 * G, J4_Y + 4 * G))

    # ===== Power flags =====
    # V12_CAT5E sourced externally (from Cat5e battery side) via J1's
    # `passive` connector pins. Same pattern as V24_FUSED on battery side.
    _place_power_flag(s, "V12_CAT5E", (8 * G, 50 * G), lib)
    # GND sourced externally via J1; passive pins don't drive ERC.
    _place_power_flag(s, "GND",       (8 * G, 60 * G), lib)
    # V12_PROT: post-PTC, post-TVS. F1.2 is passive, TVS1.A is passive,
    # U1.VIN (Conn_01x03) is passive. PWR_FLAG bridges.
    _place_power_flag(s, "V12_PROT",  (8 * G, 70 * G), lib)
    # V3V3: U1.VOUT is passive. MOD1.3V3 is power_input. PWR_FLAG bridges.
    _place_power_flag(s, "V3V3",      (8 * G, 80 * G), lib)

    out = DISP_DIR / "display_side.kicad_sch"
    out.parent.mkdir(parents=True, exist_ok=True)
    s.to_file(str(out))
    print(f"  + {out} ({out.stat().st_size} bytes; "
          f"{len(s.schematicSymbols)} symbols, {len(s.globalLabels)} labels, "
          f"{len(s.noConnects)} NCs)")


# -------------------------------------------------------------------- kicad-cli
def run_kicad_cli(*args: str) -> tuple[int, str, str]:
    """Run kicad-cli; return (rc, stdout, stderr)."""
    p = subprocess.run(["kicad-cli", *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def post_process(board_dir: Path, board_name: str, out_dir: Path) -> None:
    """Upgrade .kicad_sch to v10 format; run ERC; export PDF + netlist."""
    sch = board_dir / f"{board_name}.kicad_sch"
    out_dir.mkdir(parents=True, exist_ok=True)

    rc, _, err = run_kicad_cli("sch", "upgrade", str(sch))
    print(f"  [upgrade] rc={rc}")
    if rc != 0:
        print(f"    stderr: {err.strip()}", file=sys.stderr)

    erc_rpt = out_dir / "erc.rpt"
    rc, out, err = run_kicad_cli("sch", "erc", "-o", str(erc_rpt), str(sch))
    print(f"  [erc] rc={rc}")
    # ERC output goes to stdout; report file has details
    if erc_rpt.exists():
        with erc_rpt.open() as f:
            for line in f:
                line = line.rstrip()
                if line.startswith(" ** ERC messages") or line.startswith("***** Sheet"):
                    print(f"    {line}")

    pdf = out_dir / "schematic.pdf"
    rc, _, err = run_kicad_cli("sch", "export", "pdf", "-o", str(pdf), str(sch))
    print(f"  [pdf] rc={rc} → {pdf}")

    net = out_dir / f"{board_name}.net"
    rc, _, err = run_kicad_cli("sch", "export", "netlist", "-o", str(net), "--format", "kicadsexpr", str(sch))
    print(f"  [netlist] rc={rc} → {net}")


# -------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate KiCad 10 schematic artifacts. Default path uses the "
            "committed project library at hardware/kicad/libraries/volthium.kicad_sym "
            "and does NOT touch the host KiCad install. Use --rebuild-library "
            "to re-extract symbols from the host install (e.g. when adding a new part)."
        )
    )
    parser.add_argument(
        "--rebuild-library",
        action="store_true",
        help=(
            "Re-extract stock symbols from the host KiCad install at "
            f"{HOST_LIB_DIR} and re-author custom symbols. Writes "
            "hardware/kicad/libraries/volthium.kicad_sym. Requires the host "
            "KiCad install to be present at the expected path."
        ),
    )
    args = parser.parse_args()

    if args.rebuild_library:
        if not HOST_LIB_DIR.exists():
            raise SystemExit(
                f"FATAL: --rebuild-library requested but host KiCad libraries "
                f"not found at {HOST_LIB_DIR}. Install KiCad 10 or adjust "
                f"HOST_LIB_DIR in this script."
            )
        print("=== Rebuilding project library from host KiCad install ===")
        build_library()
    else:
        if not LIB_FILE.exists():
            raise SystemExit(
                f"FATAL: project library not found at {LIB_FILE}. "
                f"Re-run with --rebuild-library to extract from host KiCad install."
            )
        print(f"=== Using committed project library at {LIB_FILE.relative_to(REPO)} ===")
        print(f"    ({LIB_FILE.stat().st_size} bytes; no host KiCad access this run)")

    print("\n=== Write project files ===")
    write_project_file(BATT_DIR, "battery_side")
    write_sym_lib_table(BATT_DIR)
    write_project_file(DISP_DIR, "display_side")
    write_sym_lib_table(DISP_DIR)

    print("\n=== Generate schematics ===")
    build_battery_side_schematic()
    build_display_side_schematic()

    print("\n=== Post-process: upgrade, ERC, export ===")
    print("--- battery_side ---")
    post_process(BATT_DIR, "battery_side", OUT_BATT)
    print("--- display_side ---")
    post_process(DISP_DIR, "display_side", OUT_DISP)

    print("\nDone.")


if __name__ == "__main__":
    main()
