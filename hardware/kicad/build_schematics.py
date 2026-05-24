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
    # RS-485 transceiver (MAX3485 used as electrically-equivalent stand-in
    # for SN65HVD3082E — same SOIC-8 pinout: 1=R, 2=RE, 3=DE, 4=D,
    # 5=GND, 6=A, 7=B, 8=VCC. The schematic's Value field overrides
    # the visible part number to SN65HVD3082E.)
    ("Interface_UART", "MAX3485", None),
    # switches
    ("Switch", "SW_Push", None),
    # connectors
    ("Connector", "RJ45", None),
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
    """Write a minimal .kicad_pro JSON file."""
    pro = {
        "board": {
            "design_settings": {"defaults": {}},
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
            },
        },
        "libraries": {
            "pinned_footprint_libs": [],
            "pinned_symbol_libs": ["volthium"],
        },
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": [{"name": "Default"}], "meta": {"version": 4}, "net_colors": None, "netclass_assignments": None, "netclass_patterns": []},
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
                  "Fuse:Fuse_Bel_5MF",   # cartridge clip footprint family
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
                  "Package_SO:SOT-23-6",   # SOT-563, placeholder; finalize at CP3
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
                  "Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT",
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
    # PWR_EN net also needs a flag — it's driven by ESP IO4 (which will land
    # in iter 18). Until then, Q2.G ("input" type) is dangling without a
    # source. PWR_FLAG bridges that until the MCU is wired in.
    _place_power_flag(s, "PWR_EN",    (R5_X - 20 * G, R5_Y + 8 * G), lib)
    # V3V3_SW (U1 output) and V12_CAT5E (U2 output): regulator outputs are
    # `output` type which ERC accepts as drivers. No PWR_FLAG needed.

    out = BATT_DIR / "battery_side.kicad_sch"
    out.parent.mkdir(parents=True, exist_ok=True)
    s.to_file(str(out))
    print(f"  + {out} ({out.stat().st_size} bytes; {len(s.schematicSymbols)} symbols, {len(s.globalLabels)} labels)")


def build_display_side_schematic() -> None:
    """Generate display-side schematic — empty placeholder for iter 4."""
    s = Schematic.create_new()
    s.generator = "volthium-build-schematics"
    out = DISP_DIR / "display_side.kicad_sch"
    out.parent.mkdir(parents=True, exist_ok=True)
    s.to_file(str(out))
    print(f"  + {out} ({out.stat().st_size} bytes)")


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
