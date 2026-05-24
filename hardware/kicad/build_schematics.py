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
    # regulator
    ("Regulator_Switching", "TPS62933F", None),
    # RTC (DS3231M is electrically equivalent to DS3231SN#)
    ("Timer_RTC", "DS3231M", None),
    # MOSFETs
    ("Transistor_FET", "AO3401A", None),
    ("Transistor_FET", "AO3400A", None),
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

    # ===== Power flags (kept until real power-output pins land in iter 11+) =====
    # PWR_FLAG on V24_FUSED previously sourced this net. Now that D1's cathode
    # connects, the net has a real upstream connection (through F1, J1). But
    # KiCad's ERC requires a `power_output` pin for full validation, and D1's
    # cathode is `passive`. We keep PWR_FLAG on V24_FUSED until U1 (TPS62933F)
    # provides a real `power_output` pin in the next iter, then drop it.
    _place_power_flag(s, "V24_FUSED", (R5_X - 20 * G, R5_Y - 3 * G), lib)
    # Same logic for GND — J1.2 is a passive connector pin, not a power_input.
    # PWR_FLAG persists until a regulator's GND pin provides authoritative
    # net classification.
    _place_power_flag(s, "GND",       (R5_X - 20 * G, R6_Y + 3 * G), lib)

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
