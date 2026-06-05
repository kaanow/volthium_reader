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

    # CP6 iter-7 strict-overlap cleanup: hide in-symbol pin name text on
    # multi-pin ICs and hide pin numbers on single-pin power flags.
    #
    # Why: every IC pin is labelled in the schematic with an explicit
    # GlobalLabel placed at the pin endpoint (V3V3_SW, GND, RS485_A,
    # UART_RX_3V3, ...). The library-symbol pin name text (rendered
    # inside the chip body) duplicates that info and, where the chip
    # has multiple pins sharing one library coord (DS3231M pins 5..13
    # all GND at lib (0,-10.16); ESP32-S3-WROOM-1 pins 1/40/41 GND at
    # lib (0,-27.94)), KiCad renders each pin name on top of the
    # previous — producing 9 "GND" texts at one pixel, which the
    # strict audit sees as C(9,2) = 36 overlap pairs from a single
    # symbol. Hiding pin names erases that whole category of pair
    # without losing information (the GlobalLabel at the pin already
    # carries the net name).
    #
    # PWR_FLAG is a single-pin marker; its pin number "1" is rendered
    # right on top of its Value text "PWR_FLAG". hidePinNumbers=True
    # cleans that up.
    _hide_pin_names_on = {
        # Multi-pin ICs — net labels at endpoints already carry the
        # functional name, so the in-body pin name text is duplicate
        # information that the strict-overlap audit flags every time.
        "ESP32-S3-WROOM-1", "DS3231M", "TPS62933", "LTC2850xS8",
        # Connectors — host KiCad ships these with `(hide yes)` in the
        # newer pin_names syntax, but kiutils' parser drops the value
        # form and reads pinNamesHide=False. Set explicitly so a
        # --rebuild-library run doesn't regress.
        "8P8C", "Conn_01x02", "Conn_01x03", "Conn_01x04", "Conn_01x24",
        # D_TVS has pins named A1/A2/K rendered very close to each other
        # (the two anode pins share a body) → "A1" overlaps "A2" every
        # placement. The diode triangle + cathode line already convey
        # the polarity.
        "D_TVS",
        # D, LED have pin names A/K; the symbol shape (triangle pointing
        # to cathode line) already conveys polarity unambiguously.
        "D", "LED",
        # Battery_Cell has pin names +/-; the symbol shape already shows
        # polarity (long terminal = +, short = -).
        "Battery_Cell",
        # SW_Push: lib symbol has pin NAMES = "1" / "2" (same characters
        # as the pin numbers). Hiding pin numbers leaves the pin names
        # still visible and indistinguishable from numbers; reader sees
        # "1" and "2" on the body anyway. Hide names so the body just
        # shows the button glyph with no annotations.
        "SW_Push",
    }
    # D16 / #40: hide duplicate stacked-power pins on the lib symbol so
    # only one pin renders at each library coordinate. The hidden pins
    # remain in the netlist (KiCad emits them for the footprint pad map)
    # but their pin number text no longer stacks on top of the visible
    # pin's number. Lets us re-enable pin numbers on the chips.
    _hide_stacked_power_pins_on = {
        # DS3231M: pins 5..13 all GND at lib (0, -10.16). Keep pin 5
        # visible; hide 6..13 so only "5" renders.
        "DS3231M": {"6", "7", "8", "9", "10", "11", "12", "13"},
        # ESP32-S3-WROOM-1: pins 1, 40, 41 all GND at lib (0, -27.94).
        # Keep pin 1 visible; hide 40 + 41.
        "ESP32-S3-WROOM-1": {"40", "41"},
    }
    for sym in out_lib.symbols:
        hide_nums = _hide_stacked_power_pins_on.get(sym.entryName)
        if not hide_nums:
            continue
        for u in sym.units:
            for p in u.pins:
                if p.number in hide_nums:
                    p.hide = True

    _hide_pin_numbers_on = {
        # PWR_FLAG is single-pin marker; "1" overlaps the Value text.
        "PWR_FLAG",
        # D16: stock power-port symbols (+3V3, +12V, +24V, GND) have a
        # single pin numbered "1" that the strict audit picks up as a
        # SAME-TEXT stroke-font duplicate at every placement. The glyph
        # is self-evident; the "1" adds nothing.
        "GND", "+3V3", "+12V", "+24V",
        # 2- and 3-pin discretes: pin numbers are redundant (polarity
        # is shown by the symbol shape — diode triangle, cap line,
        # etc.) and they pile onto the Value text every time. Hiding
        # eliminates several whole categories of strict-audit overlap
        # ('2'/'22uF/25V', '3'/'R-78E12-1.0', '2'/'1A', ...).
        "R", "L", "C", "Fuse", "Polyfuse",
        "D", "D_TVS", "LED", "Battery_Cell",
        # SW_Push is a 2-pin momentary switch — pin numbers are not
        # meaningful (both pins are the same logically when pressed),
        # and pin 1's "1" sits next to the GlobalLabel chevron tip.
        "SW_Push",
        # MOSFETs — G/D/S pin NAMES stay visible (set in _hide_pin_names_on
        # exclusion), but pin numbers 1/2/3 overlap the GlobalLabel
        # chevron tips on the gate/drain/source pins.
        "Q_PMOS_GSD", "Q_NMOS_GSD",
    }
    for sym in out_lib.symbols:
        if sym.entryName in _hide_pin_names_on:
            # kiutils only emits the (pin_names ...) block when pinNames
            # is truthy; pinNamesHide alone is silently dropped.
            sym.pinNames = True
            sym.pinNamesHide = True
        if sym.entryName in _hide_pin_numbers_on:
            sym.hidePinNumbers = True

    out_lib.to_file(str(LIB_FILE))
    print(f"\n[lib] wrote {LIB_FILE} ({LIB_FILE.stat().st_size} bytes)")


# -------------------------------------------------------------------- project files
def write_project_file(board_dir: Path, name: str) -> None:
    """Write the .kicad_pro JSON file — initial creation only.

    Includes the PCB DRC severity overrides + CP1 §11.3 net class
    definitions that CP3 established. Re-running this script must not
    wipe those — otherwise PCB DRC regresses from 0 errors to many.
    The numeric values for net classes live under `_intended_classes_cp4`
    as documented intent; CP4 routing binds them.

    CP6 iter-7: skip the write if the file already exists. Otherwise the
    CP5-committed netclass numerics (track_width, clearance, via_diameter,
    netclass_patterns) and KiCad-GUI-added DRC rules (e.g.
    min_resolved_spokes) get clobbered by the template every rebuild.
    """
    out = board_dir / f"{name}.kicad_pro"
    if out.exists():
        return
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


def _place_wire(sch: Schematic, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Add a (wire ...) graphical item between two pin endpoints.

    D11 criterion #2: real wires within clusters. Use sparingly — wires
    are visually redundant with net labels but visually reinforce that
    two adjacent components share a net. Add a wire only when both
    endpoints are already on the same labeled net (so ERC topology is
    unchanged and the wire is purely decorative).
    """
    from kiutils.items.schitems import Connection
    from kiutils.items.common import Position, Stroke
    w = Connection()
    w.type = "wire"
    w.points = [Position(X=start[0], Y=start[1]), Position(X=end[0], Y=end[1])]
    w.stroke = Stroke(width=0.0, type="default")
    w.uuid = _uuid()
    if sch.graphicalItems is None:
        sch.graphicalItems = []
    sch.graphicalItems.append(w)


def _add_rail_convention_note(sch: Schematic, x: float = 25.0, y: float = 20.0) -> None:
    """Add a sheet-level text annotation documenting the power-rail convention.

    D11 criterion #6: power rails on consistent edges. Since most power
    labels are placed at component pin endpoints (driven by chip pinout,
    not stylistic choice), strictly enforcing "GND at bottom, supplies
    at top" would require re-orienting every component — out of scope
    for this CP. Instead, this annotation makes the convention explicit
    so any reader knows which side to look at for each rail.

    Uses left-aligned justification so the text starts at the anchor
    (KiCad's default centers text on the anchor, which pushed the
    leading portion off the page on long strings).
    """
    from kiutils.items.schitems import Text
    from kiutils.items.common import Position, Effects, Font, Justify
    note = Text()
    # Short enough to fit comfortably on a left-justified A3 sheet
    # without clipping (D11 #0: nothing off-page).
    note.text = "Convention: power rails above components; GND below."
    note.position = Position(X=x, Y=y, angle=0)
    note.uuid = _uuid()
    note.effects = Effects(
        font=Font(height=2.0, width=2.0),
        justify=Justify(horizontally="left"),
    )
    if sch.texts is None:
        sch.texts = []
    sch.texts.append(note)


def _copy_symbol_to_schematic(lib: SymbolLib, sym_name: str, sch: Schematic) -> Symbol:
    """Find a symbol in the project lib and copy it into the schematic's libSymbols.

    Idempotent — if the symbol is already present, return the existing instance.

    CP6 iter-7 strict-overlap cleanup: each placed symbol instance carries
    its own Reference/Value properties (e.g. Reference="C10", Value="100nF").
    The libSymbol embed also carries Reference and Value template properties
    (e.g. Reference="C", Value="C") for use during auto-annotation. KiCad's
    PDF exporter renders BOTH template and instance text at their respective
    `at` positions; for vertically-symmetric symbols (R, C, L, D) the
    template's `at (0.635, 2.54)` lands on top of the instance's `at (0,
    5.08)` after the symbol's bounding-box-relative positioning, producing
    two identical "C10" word boxes at the same pixel. The strict audit
    flags this as a SAME-TEXT overlap. Hide the libSymbol Reference and
    Value properties so only the instance text renders.
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
    # Mark Reference + Value template properties on the embedded libSymbol
    # as hidden — the instance properties (set in _place_symbol) carry the
    # real Reference="C10" / Value="100nF" and are the ones the user reads.
    for prop in clone.properties:
        if prop.key in ("Reference", "Value"):
            if prop.effects is None:
                prop.effects = Effects()
            prop.effects.hide = True
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
    value_pos: tuple[float, float] | None = None,
    ref_pos: tuple[float, float] | None = None,
) -> SchematicSymbol:
    """Place a SchematicSymbol instance referencing volthium:<sym_name>.

    iter 51 (fix C): added `value_pos` kwarg so multi-pin IC call sites
    can override where the Value property text lands. Default position
    (pos.x + 2.54, pos.y + 1.27) sits inside the chip body for large
    ICs (MOD1, SOIC-16, SOT-23, etc.); callers pass an explicit
    out-of-body position when that matters.
    """
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
    val_pos = value_pos if value_pos is not None else (pos[0] + 2.54, pos[1] + 1.27)
    rf_pos = ref_pos if ref_pos is not None else (pos[0] + 2.54, pos[1] - 1.27)
    # Properties: Reference, Value, Footprint, Datasheet (the standard 4)
    inst.properties = [
        Property(key="Reference", value=reference,
                 position=Position(X=rf_pos[0], Y=rf_pos[1], angle=0),
                 effects=Effects()),
        Property(key="Value", value=value,
                 position=Position(X=val_pos[0], Y=val_pos[1], angle=0),
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


def _set_active_lib(lib: SymbolLib) -> None:
    """Set the library every `_pin_label` invocation in this run uses to
    resolve stock power-port symbol names. Called once per schematic
    build so call sites don't have to thread `lib=` through every
    `_pin_label` invocation.
    """
    global _ACTIVE_LIB
    _ACTIVE_LIB = lib


_ACTIVE_LIB: SymbolLib | None = None


def _pin_label(sch: Schematic, net: str, endpoint: tuple[float, float],
               outdir: str, *, stub: float = 3 * 1.27, angle: float | None = None,
               lib: SymbolLib | None = None) -> None:
    """Connect a net label to a pin endpoint via a stub wire, placing the
    label out in clear space so its text never lands on pin numbers, pin
    names, or the part's own Reference/Value text.

    `outdir` is the direction the pin faces AWAY from the part body:
      'L' left, 'R' right, 'U' up, 'D' down.
    The stub extends the pin endpoint by `stub` mm in that direction and the
    GlobalLabel is anchored at the stub's far end, oriented so its text reads
    outward (left-side labels extend left, top labels read upward, etc.).

    This is the single chokepoint for "label a pin" — every 2-pin passive,
    connector, and flag should route through here rather than dropping a bare
    label on the endpoint (which is what made earlier sheets unreadable).

    D16 / CP6 iter-8: for nets that map to a stock KiCad power port symbol
    (GND, +3V3, +12V, +24V), route through `_place_power_port` instead of
    dropping a GlobalLabel. The standard power-port glyphs (downward
    triangle for GND, upward arrow for supplies) are visually distinct from
    signal-label flags and from each other, which is what makes "this pin
    goes to GND" readable at a glance.
    """
    _lib = lib if lib is not None else _ACTIVE_LIB
    if net in _STOCK_POWER_PORTS and _lib is not None:
        _place_power_port(sch, net, endpoint, outdir, stub=stub, lib=_lib)
        return
    dirs = {'L': (-1, 0), 'R': (1, 0), 'U': (0, -1), 'D': (0, 1)}
    dx, dy = dirs[outdir]
    far = (endpoint[0] + dx * stub, endpoint[1] + dy * stub)
    _place_wire(sch, endpoint, far)
    if angle is None:
        angle = {'L': 180, 'R': 0, 'U': 90, 'D': 270}[outdir]
    _place_label(sch, net, far, angle=angle)


# D16 / CP6 iter-8: nets that have a stock KiCad power port glyph in our
# `volthium` library. _pin_label routes these to _place_power_port so the
# rendered schematic shows the standard ground-triangle / supply-arrow
# instead of an indistinguishable flag-shaped GlobalLabel.
_STOCK_POWER_PORTS = {"GND", "+3V3", "+12V", "+24V"}


def _place_power_port(sch: Schematic, net: str, endpoint: tuple[float, float],
                      outdir: str, *, stub: float, lib: SymbolLib) -> None:
    """Place a stock KiCad power port symbol at the outer end of a stub.

    The power port symbol has a single pin labelled with the net name.
    KiCad ERC treats this as a power-net connection automatically — no
    separate GlobalLabel needed. The visible glyph (ground triangle for
    GND, upward arrow for supplies) is the standard schematic notation
    a reader recognizes instantly.

    Pin geometry for the stock symbols (lib coords): pin 1 is at (0, 0)
    for all of them, with pin angle 90 (extends downward in lib =
    upward in schematic after Y-flip) for the supply symbols and
    angle 270 for GND (extends upward in lib = downward in schematic).
    The symbol body sits ABOVE the pin for supplies, BELOW for GND.

    We orient the symbol so its pin lands at the outer end of the stub,
    pointing back toward the endpoint:
      outdir 'D' (pin faces down → port goes below): angle 0
      outdir 'U' (pin faces up   → port goes above): angle 180
      outdir 'L' (pin faces left → port goes left):  angle 90
      outdir 'R' (pin faces right→ port goes right): angle 270
    """
    dirs = {'L': (-1, 0), 'R': (1, 0), 'U': (0, -1), 'D': (0, 1)}
    dx, dy = dirs[outdir]
    far = (endpoint[0] + dx * stub, endpoint[1] + dy * stub)
    _place_wire(sch, endpoint, far)

    _copy_symbol_to_schematic(lib, net, sch)
    inst = SchematicSymbol()
    inst.libraryNickname = "volthium"
    inst.entryName = net
    inst.position = Position(X=far[0], Y=far[1],
                             angle={'D': 0, 'U': 180, 'L': 90, 'R': 270}[outdir])
    inst.unit = 1
    inst.inBom = False
    inst.onBoard = False
    inst.fieldsAutoplaced = True
    inst.uuid = _uuid()
    # Power port instance properties: Reference="#PWR" auto-annotation
    # placeholder (KiCad fills it in on save); Value=net name (hidden,
    # since the symbol glyph already conveys which rail).
    ref_hide = Effects()
    ref_hide.hide = True
    val_hide = Effects()
    val_hide.hide = True
    inst.properties = [
        Property(key="Reference", value="#PWR",
                 position=Position(X=far[0], Y=far[1], angle=0),
                 effects=ref_hide),
        Property(key="Value", value=net,
                 position=Position(X=far[0], Y=far[1], angle=0),
                 effects=val_hide),
        Property(key="Footprint", value="",
                 position=Position(X=far[0], Y=far[1], angle=0),
                 effects=Effects(hide=True)),
        Property(key="Datasheet", value="",
                 position=Position(X=far[0], Y=far[1], angle=0),
                 effects=Effects(hide=True)),
    ]
    sch.schematicSymbols.append(inst)


def _place_noconnect(sch: Schematic, pos: tuple[float, float]) -> None:
    """Place a NoConnect marker at the given pin endpoint."""
    nc = NoConnect()
    nc.position = Position(X=pos[0], Y=pos[1], angle=0)
    nc.uuid = _uuid()
    sch.noConnects.append(nc)


def _outward_for_angle(lib_angle: float) -> tuple[int, int]:
    """Return outward unit vector (dx, dy) in schematic mm-multiples per
    library pin angle.

    Library angle indicates pin extension direction INTO the chip body.
    Outward (away from chip) is the opposite direction in schematic
    coordinates. KiCad flips Y between library and schematic, so:
      angle 0   → lib +X into chip → sch outward (-1,  0)  left-side pin
      angle 90  → lib +Y into chip → sch outward ( 0, +1)  bottom-side pin
      angle 180 → lib -X into chip → sch outward (+1,  0)  right-side pin
      angle 270 → lib -Y into chip → sch outward ( 0, -1)  top-side pin
    """
    a = int(round(lib_angle)) % 360
    return {0: (-1, 0), 90: (0, 1), 180: (1, 0), 270: (0, -1)}.get(a, (0, 0))


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
    # Tie PWR_FLAG to its net via a label dropped a few grid units BELOW the
    # flag — clear of the flag graphic (above the pin) and the #FLG/PWR_FLAG
    # property text (to the right) — so the net name reads in open space.
    below = (pos[0], pos[1] + 4 * 1.27)
    _place_wire(sch, pos, below)
    _place_label(sch, net, below, angle=0)


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
    _add_rail_convention_note(s)
    lib = _load_project_lib()
    _set_active_lib(lib)

    # KiCad connection grid is 1.27 mm. All positions are expressed as n×G
    # so endpoints land on the grid (resistor pins are at ±3*G from center,
    # so symbol-center alignment propagates to pin alignment).
    G = 1.27

    # ===== Iter 10: V24 input path (J1 → F1 → D1 → V24_FUSED), TVS1 clamp =====

    # J1 — 2-pin terminal block (Phoenix MSTB-2,5/2-G-5,08). Pins at:
    #   pin 1 (V24_RAW): symbol-relative (-5.08, 0) → endpoint (X-5.08, Y)
    #   pin 2 (GND):     symbol-relative (-5.08, -2.54) → endpoint (X-5.08, Y-2.54)
    J1_X, J1_Y = 28 * G, 30 * G   # power-input chain, top row
    _place_symbol(s, "Conn_01x02", "J1", "Conn_01x02",
                  "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                  (J1_X, J1_Y), lib=lib)
    # Note: KiCad flips Y between symbol library and schematic. Lib pin Y
    # becomes -lib_Y on the schematic (relative to symbol center). For
    # Conn_01x02: pin 1 lib (-5.08, 0) → schematic (X-5.08, Y); pin 2 lib
    # (-5.08, -2.54) → schematic (X-5.08, Y+2.54).
    _pin_label(s, "V24_RAW", (J1_X - 4 * G, J1_Y), 'L')            # pin 1
    _pin_label(s, "GND",     (J1_X - 4 * G, J1_Y + 2 * G), 'L')    # pin 2

    # F1 — 5×20 mm cartridge fuse holder, 2-pin vertical (like R).
    # Spread iter 20: power row stretched across the page width to give
    # each component's V24_* labels clear horizontal space (D11 #5).
    F1_X, F1_Y = 54 * G, 30 * G
    _place_symbol(s, "Fuse", "F1", "1A 5x20",
                  "Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal",
                  (F1_X, F1_Y), lib=lib,
                  value_pos=(F1_X + 5 * G, F1_Y + 1.27))  # CP6 iter-7: shift right of V24_AFTER_FUSE label
    _pin_label(s, "V24_RAW",        (F1_X, F1_Y - 3 * G), 'U')     # pin 1 (top)
    _pin_label(s, "V24_AFTER_FUSE", (F1_X, F1_Y + 3 * G), 'D')     # pin 2 (bottom)

    # D1 — SS24 Schottky reverse-polarity diode (Device:D generic, Value
    # overridden to BOM MPN). Horizontal: pin 1 (K) on left, pin 2 (A) on
    # right; pins at ±3.81 = ±3*G from center.
    D1_X, D1_Y = 80 * G, 30 * G
    _place_symbol(s, "D", "D1", "SS24",
                  "Diode_SMD:D_SMA",
                  (D1_X, D1_Y), lib=lib,
                  ref_pos=(D1_X, D1_Y - 3 * G),   # D16: ref above body, clear of V24_AFTER_FUSE label area
                  value_pos=(D1_X, D1_Y + 3 * G)) # D16: value below body
    _pin_label(s, "V24_FUSED",      (D1_X - 3 * G, D1_Y), 'L')     # pin 1 (K)
    _pin_label(s, "V24_AFTER_FUSE", (D1_X + 3 * G, D1_Y), 'R')     # pin 2 (A)

    # TVS1 — SMAJ30CA bidirectional 24V TVS (Device:D_TVS generic, Value
    # overridden). Pins same geometry as D.
    TVS1_X, TVS1_Y = 104 * G, 30 * G
    _place_symbol(s, "D_TVS", "TVS1", "SMAJ30CA",
                  "Diode_SMD:D_SMA",
                  (TVS1_X, TVS1_Y), lib=lib)
    _pin_label(s, "V24_FUSED", (TVS1_X - 3 * G, TVS1_Y), 'L')      # pin 1
    _pin_label(s, "GND",       (TVS1_X + 3 * G, TVS1_Y), 'R')      # pin 2

    # ===== Iter 8 (existing): V24 sense divider + filter cap =====
    # CP-cleanup iter 22 (Finding 07): the three components share the
    # V24_SENSE net at adjacent pin endpoints. Previously each got its
    # own V24_SENSE label → 3 labels stacked in a 13mm-tall box →
    # unreadable. Replaced with 1 label + 2 wires that visually
    # connect the pin endpoints (criterion #2). Net topology
    # preserved by the single remaining label.

    # R5 — 1 MΩ, top of sense divider
    R5_X, R5_Y = 74 * G, 64 * G   # sense divider; R6/C5 derive
    _place_symbol(s, "R", "R5", "1M",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R5_X, R5_Y), lib=lib)
    _pin_label(s, "V24_FUSED", (R5_X, R5_Y - 3 * G), 'U')   # pin 1
    # No V24_SENSE label on R5 pin 2 — wire connects to R6 pin 1 below
    # (which has the V24_SENSE label).

    # R6 — 110 kΩ, bottom of sense divider
    R6_X, R6_Y = R5_X, R5_Y + 10 * G   # (101.6, 63.5)
    _place_symbol(s, "R", "R6", "110k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R6_X, R6_Y), lib=lib)
    _pin_label(s, "V24_SENSE", (R6_X, R6_Y - 3 * G), 'L')   # SINGLE V24_SENSE label (left, clear of R5/C5 wires above/right)
    _pin_label(s, "GND",       (R6_X, R6_Y + 3 * G), 'D')

    # C5 — 100 nF filter cap on V24_SENSE
    C5_X, C5_Y = R6_X + 10 * G, R6_Y   # (114.3, 63.5)
    _place_symbol(s, "C", "C5", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C5_X, C5_Y), lib=lib)
    # No V24_SENSE label on C5 — wire connects to R6 pin 1 (above).
    _pin_label(s, "GND",       (C5_X, C5_Y + 3 * G), 'D')

    # Wires materialising the V24_SENSE node:
    #   R5 pin 2 ─┐
    #             ├── V24_SENSE (label)
    #   C5 pin 1 ─┘
    #             │
    #   R6 pin 1 ─┘
    _place_wire(s, (R5_X, R5_Y + 3 * G), (R6_X, R6_Y - 3 * G))  # R5↓ → R6↑
    _place_wire(s, (R6_X, R6_Y - 3 * G), (C5_X, C5_Y - 3 * G))  # R6↑ → C5↑

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
    U1_X, U1_Y = 150 * G, 72 * G   # buck cluster; L1/C1/C2/C_BST derive
    _place_symbol(s, "TPS62933", "U1", "TPS62933FDRLR",
                  "Package_TO_SOT_SMD:SOT-23-6",
                  (U1_X, U1_Y), lib=lib,
                  value_pos=(U1_X, U1_Y + 14 * G))  # iter 51 fix C: out of body, below GND label
    # Pin connections per CP1 §5 net list:
    #   VIN ← V24_FUSED
    #   GND ← GND
    #   EN  ← V24_FUSED (always-on; firmware kills U1 via the Q1 path)
    #   SW  → U1_SW (internal to U1+L1)
    #   FB  ← V3V3_SW (fixed-3.3 variant pin is tied to VOUT)
    #   BST → 100nF bootstrap cap (placeholder NoConnect for now; cap added
    #         in iter 14 when MOSFET cluster lands — they share decoupling)
    #   SS, RT → NoConnect (use internal defaults)
    # CP-cleanup iter 24: U1.VIN (pin 3) and U1.EN (pin 2) are both
    # tied to V24_SW (always-on regulator). Wire pin 3 → pin 2 → label.
    # iter 47 (fix B2): extend the pickoff 2G outward so the label
    # sits clear of the chip's "EN"/"VIN" pin name text.
    _place_wire(s, (U1_X - 6 * G, U1_Y - 6 * G), (U1_X - 6 * G, U1_Y - 4 * G))   # pin 3 ↔ pin 2
    _place_wire(s, (U1_X - 6 * G, U1_Y - 4 * G), (U1_X - 12 * G, U1_Y - 4 * G))  # D16: 6G stub so the V24_SW chevron clears pin 2 number "2"
    _place_label(s, "V24_SW",  (U1_X - 12 * G, U1_Y - 4 * G), angle=180)
    # D16: route U1 pin 4 GND through the stock power port.
    _place_power_port(s, "GND", (U1_X, U1_Y + 10 * G), 'D', stub=1 * G, lib=lib)
    _place_wire(s,  (U1_X + 6 * G, U1_Y),         (U1_X + 8 * G, U1_Y))            # pin 5 stub
    _place_label(s, "U1_SW",   (U1_X + 8 * G, U1_Y))             # pin 5 SW
    _place_wire(s,  (U1_X + 6 * G, U1_Y + 6 * G), (U1_X + 8 * G, U1_Y + 6 * G))   # pin 8 stub
    _place_label(s, "V3V3_SW", (U1_X + 8 * G, U1_Y + 6 * G))     # pin 8 FB
    _place_noconnect(s, (U1_X - 6 * G, U1_Y + 4 * G))            # pin 1 RT
    _place_noconnect(s, (U1_X - 6 * G, U1_Y + 2 * G))            # pin 7 SS
    # BST: 100 nF bootstrap cap between U1.BST (pin 6) and U1.SW (pin 5).
    # Per Codex iter-13 guidance Q-CP2-10 — required for the high-side MOSFET
    # gate drive to function on real hardware.
    _place_wire(s,  (U1_X + 6 * G, U1_Y - 6 * G), (U1_X + 8 * G, U1_Y - 6 * G))  # pin 6 stub
    _place_label(s, "U1_BST",  (U1_X + 8 * G, U1_Y - 6 * G))     # pin 6 BST → cap

    # L1 — 2.2 µH inductor (2-pin, same geometry as R: ±3.81 from center).
    L1_X, L1_Y = U1_X + 20 * G, U1_Y   # (177.8, 38.1)
    _place_symbol(s, "L", "L1", "2.2uH",
                  "Inductor_SMD:L_0805_2012Metric",  # placeholder
                  (L1_X, L1_Y), lib=lib,
                  value_pos=(L1_X + 4 * G, L1_Y + 1.27))  # D16: clear of pin 2 number
    # L1.pin1 U1_SW label deduped — wire to U1.SW directly (iter 32).
    _place_wire(s, (U1_X + 6 * G, U1_Y),  (L1_X, U1_Y))             # U1.SW → corner
    _place_wire(s, (L1_X, U1_Y),          (L1_X, L1_Y - 3 * G))     # corner → L1.pin1
    _pin_label(s, "V3V3_SW", (L1_X, L1_Y + 3 * G), 'D')     # pin 2 (bottom)

    # C1 — 22 µF bulk on V24_SW (U1 VIN decoupling)
    C1_X, C1_Y = U1_X - 14 * G, U1_Y + 4 * G   # (134.62, 43.18)
    _place_symbol(s, "C", "C1", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C1_X, C1_Y), lib=lib)
    # D16: V24_SW label deduped — wire C1.pin1 up + over to the U1 V24_SW
    # pickoff at (U1_X - 12G, U1_Y - 4G) where U1 keeps the single label.
    _place_wire(s, (C1_X, C1_Y - 3 * G), (C1_X, U1_Y - 4 * G))
    _place_wire(s, (C1_X, U1_Y - 4 * G), (U1_X - 12 * G, U1_Y - 4 * G))
    _pin_label(s, "GND",    (C1_X, C1_Y + 3 * G), 'D')   # pin 2

    # C2 — 22 µF bulk on V3V3_SW (U1 VOUT decoupling)
    C2_X, C2_Y = L1_X + 8 * G, L1_Y + 4 * G   # (188.4, 43.18)
    _place_symbol(s, "C", "C2", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C2_X, C2_Y), lib=lib)
    # D16: V3V3_SW label deduped — wire C2.pin1 up + over to L1.pin2 (also V3V3_SW).
    _place_wire(s, (C2_X, C2_Y - 3 * G), (C2_X, L1_Y + 3 * G))
    _place_wire(s, (C2_X, L1_Y + 3 * G), (L1_X, L1_Y + 3 * G))
    # No GND label here — see the C2↔C3 GND wire after C3 placement.

    # C_BST — 100 nF bootstrap cap between U1.BST and U1.SW. Required for
    # TPS62933 high-side MOSFET gate drive. Per Codex iter-13 Q-CP2-10.
    CBST_X, CBST_Y = U1_X + 10 * G, U1_Y - 4 * G   # (165.1, 33.02)
    _place_symbol(s, "C", "C_BST", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (CBST_X, CBST_Y), lib=lib,
                  ref_pos=(CBST_X + 3 * G, CBST_Y - 1.27),    # D16: ref right, clear of U1_BST label
                  value_pos=(CBST_X + 3 * G, CBST_Y + 1.27))
    # CP-cleanup iter 32 (Finding 09): drop the C_BST end labels and
    # wire C_BST directly to U1.BST + U1.SW pins. U1 keeps both labels.
    # C_BST pin 1 (U1_BST node) at (CBST_X, CBST_Y - 3*G) = (CBST_X, 29.21)
    # U1.BST at (U1_X + 6*G, U1_Y - 6*G) = (204.47, 30.48)
    _place_wire(s, (U1_X + 6 * G, U1_Y - 6 * G), (CBST_X, U1_Y - 6 * G))   # U1.BST → corner
    _place_wire(s, (CBST_X, U1_Y - 6 * G), (CBST_X, CBST_Y - 3 * G))       # corner → C_BST.pin1
    # C_BST pin 2 (U1_SW node) at (CBST_X, CBST_Y + 3*G) = (CBST_X, 36.83)
    # U1.SW at (U1_X + 6*G, U1_Y) = (204.47, 38.10)
    _place_wire(s, (U1_X + 6 * G, U1_Y),       (CBST_X, U1_Y))             # U1.SW → corner
    _place_wire(s, (CBST_X, U1_Y),             (CBST_X, CBST_Y + 3 * G))   # corner → C_BST.pin2

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
    U2_X, U2_Y = 214 * G, 72 * G   # V12 cluster level w/ buck; C3/C4 derive
    _place_symbol(s, "Conn_01x03", "U2", "R-78E12-1.0",
                  "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                  (U2_X, U2_Y), lib=lib,
                  value_pos=(U2_X, U2_Y + 6 * G))  # CP6 iter-7: out of body, clear of pin 3 number bbox
    _pin_label(s, "V24_SW",     (U2_X - 4 * G, U2_Y - 2 * G), 'L')   # pin 1 VIN (top)
    _pin_label(s, "GND",        (U2_X - 4 * G, U2_Y),         'L')   # pin 2 GND (mid)
    _pin_label(s, "V12_CAT5E",  (U2_X - 4 * G, U2_Y + 2 * G), 'L')   # pin 3 VOUT (bot)

    # C3 — 22 µF bulk on V24_SW (U2 VIN decoupling)
    C3_X, C3_Y = U2_X - 14 * G, U2_Y + 4 * G   # (185.42, 43.18)
    _place_symbol(s, "C", "C3", "22uF/35V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C3_X, C3_Y), lib=lib)
    _pin_label(s, "V24_SW", (C3_X, C3_Y - 3 * G), 'U')
    _pin_label(s, "GND",    (C3_X, C3_Y + 3 * G), 'D')

    # CP-cleanup iter 28: C2 (V3V3 bulk) and C3 (V12 bulk) both have
    # GND at the bottom pin, only 3.81mm apart at y=46.99. Wire them;
    # C3 keeps the GND label, C2's was dropped above.
    _place_wire(s, (C2_X, C2_Y + 3 * G), (C3_X, C3_Y + 3 * G))

    # C4 — 22 µF bulk on V12_CAT5E (U2 VOUT decoupling)
    C4_X, C4_Y = U2_X + 8 * G, U2_Y + 4 * G   # (213.36, 43.18)
    _place_symbol(s, "C", "C4", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C4_X, C4_Y), lib=lib)
    _pin_label(s, "V12_CAT5E", (C4_X, C4_Y - 3 * G), 'U')
    _pin_label(s, "GND",       (C4_X, C4_Y + 3 * G), 'D')

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
    Q1_X, Q1_Y = 52 * G, 72 * G   # hard-cut switch (rigid-translated cluster, ERC-clean geometry)
    _place_symbol(s, "Q_PMOS_GSD", "Q1", "AO3401A",
                  "Package_TO_SOT_SMD:SOT-23", (Q1_X, Q1_Y), lib=lib)
    # iter 55 fix F1: pull each Q1 net label 2G off the pin endpoint
    # with a stub wire so the label doesn't sit on the in-symbol pin
    # name letter (G/S/D).
    _place_wire(s,  (Q1_X - 4 * G, Q1_Y),         (Q1_X - 8 * G, Q1_Y))           # D16: 4G stub clears the "G" pin name
    _place_label(s, "Q1_GATE",   (Q1_X - 8 * G, Q1_Y), angle=180)                 # pin 1 G (left → reads left)
    _place_wire(s,  (Q1_X + 2 * G, Q1_Y + 4 * G), (Q1_X + 2 * G, Q1_Y + 6 * G))  # pin 2 S stub (down)
    _place_label(s, "V24_FUSED", (Q1_X + 2 * G, Q1_Y + 6 * G))                    # pin 2 S
    _place_wire(s,  (Q1_X + 2 * G, Q1_Y - 4 * G), (Q1_X + 2 * G, Q1_Y - 6 * G))  # pin 3 D stub (up)
    _place_label(s, "V24_SW",    (Q1_X + 2 * G, Q1_Y - 6 * G))                    # pin 3 D

    # Q2 — AO3400A N-MOSFET, drives Q1's gate from PWR_EN
    Q2_X, Q2_Y = 42 * G, 82 * G   # Q1 + (-10,+10)
    _place_symbol(s, "Q_NMOS_GSD", "Q2", "AO3400A",
                  "Package_TO_SOT_SMD:SOT-23", (Q2_X, Q2_Y), lib=lib)
    # iter 55 fix F1: same stub-out pattern.
    _place_wire(s,  (Q2_X - 4 * G, Q2_Y),         (Q2_X - 8 * G, Q2_Y))           # D16: 4G stub clears the "G" pin name
    _place_label(s, "PWR_EN",  (Q2_X - 8 * G, Q2_Y), angle=180)                   # pin 1 G (left → reads left)
    # D16: Q2 pin 2 S → GND via stock power port.
    _place_power_port(s, "GND", (Q2_X + 2 * G, Q2_Y + 4 * G), 'D', stub=2 * G, lib=lib)
    # Q1_GATE label deduped at Q2.D — wire up to Q1.G (which keeps the label).
    _place_wire(s, (Q2_X + 2 * G, Q2_Y - 4 * G), (Q2_X + 2 * G, Q1_Y))   # Q2.D → corner
    _place_wire(s, (Q2_X + 2 * G, Q1_Y),         (Q1_X - 4 * G, Q1_Y))   # corner → Q1.G

    # R3 — 100 kΩ Q1 gate pull-up to V24_FUSED (default-OFF)
    R3_X, R3_Y = 42 * G, 66 * G   # Q1 + (-10,-6)
    _place_symbol(s, "R", "R3", "100k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R3_X, R3_Y), lib=lib)
    _pin_label(s, "V24_FUSED", (R3_X, R3_Y - 3 * G), 'U')   # pin 1
    # Q1_GATE label deduped at R3.pin2 — wire down to Q1.G.
    _place_wire(s, (R3_X, R3_Y + 3 * G), (R3_X, Q1_Y))               # R3.pin2 → corner
    _place_wire(s, (R3_X, Q1_Y),         (Q1_X - 4 * G, Q1_Y))       # corner → Q1.G

    # R4 — 100 kΩ Q2 gate pull-down to GND (failsafe on MCU brown-out)
    R4_X, R4_Y = 30 * G, 82 * G   # Q1 + (-22,+10)
    _place_symbol(s, "R", "R4", "100k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R4_X, R4_Y), lib=lib,
                  ref_pos=(R4_X - 4 * G, R4_Y - 1.27),    # D16: ref left, opposite from PWR_EN labels which extend left from Q2/R4
                  value_pos=(R4_X - 4 * G, R4_Y + 1.27))
    _pin_label(s, "PWR_EN", (R4_X, R4_Y - 3 * G), 'U')   # pin 1
    _pin_label(s, "GND",    (R4_X, R4_Y + 3 * G), 'D')   # pin 2

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
    MOD1_X, MOD1_Y = 150 * G, 150 * G   # MCU center-bottom, own region

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
    _esp_pin_info = {
        int(p.number): (p.position.X, p.position.Y, p.position.angle)
        for u in _esp_sym.units for p in u.pins
    }

    _place_symbol(s, "ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "RF_Module:ESP32-S3-WROOM-1U",  # -1U variant: external U.FL antenna, no keepout zone
                  (MOD1_X, MOD1_Y), lib=lib,
                  ref_pos=(MOD1_X + 16 * G, MOD1_Y - 24 * G),  # D16: above-right, clear of V3V3_SW top label
                  value_pos=(MOD1_X, MOD1_Y + 30 * G))  # value below body
    # Pins 1, 40, 41 (all GND) share the same library position in the
    # ESP32-S3-WROOM-1 symbol (0, -27.94). Placing one label per pin
    # creates 3 stacked GND labels at the same coordinate — fails D11
    # #0 (overlapping text). Dedupe by endpoint: place each label once
    # per unique (x, y).
    # CP-cleanup iter 47 (fix B2): for each labelled pin, drop a 2G
    # stub from the pin endpoint and place the net label at the stub's
    # outer end so the label no longer overlaps the chip's in-symbol
    # pin name text (IO0/IO1/.../EN/USB_D±/TXD0/RXD0/etc).
    _placed = set()
    for pin_num, net in esp_pins.items():
        lib_x, lib_y, lib_a = _esp_pin_info[pin_num]
        # KiCad Y-flip: schematic_Y = symbol_Y - lib_pin_Y
        endpoint = (MOD1_X + lib_x, MOD1_Y - lib_y)
        if endpoint in _placed:
            continue
        _placed.add(endpoint)
        if net == "NC":
            _place_noconnect(s, endpoint)
        else:
            dx, dy = _outward_for_angle(lib_a)
            outer = (endpoint[0] + dx * 6 * G, endpoint[1] + dy * 6 * G)  # D16: 6G stub so chevron tip clears the newly-visible MOD1 pin number
            _place_wire(s, endpoint, outer)
            # Orient the label so its text reads AWAY from the symbol body
            # (left-side pins must extend left, not back over the pin name).
            lbl_angle = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}.get((dx, dy), 0)
            _place_label(s, net, outer, angle=lbl_angle)

    # ===== Iter 18: ESP support — R7 EN pull-up + C8 EN soft-start cap +
    #               C6 ESP bulk decoupling + C7 ESP HF decoupling =====

    # Place ESP support caps + R7 to the LEFT of MOD1 (free area above the
    # existing power cluster). Y at MOD1_Y - 30*G so the support cluster
    # is above ESP horizontally.
    SUP_Y = MOD1_Y - 38 * G   # ESP support row above MCU

    # R7 — 10 kΩ pull-up from ESP_EN to V3V3_SW. Vertical (R pins ±3*G).
    R7_X, R7_Y = MOD1_X - 24 * G, SUP_Y
    _place_symbol(s, "R", "R7", "10k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R7_X, R7_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (R7_X, R7_Y - 3 * G), 'U')   # pin 1 top
    _pin_label(s, "ESP_EN",  (R7_X, R7_Y + 3 * G), 'D')   # pin 2 bottom

    # C8 — 1 µF EN soft-start cap. EN to GND.
    C8_X, C8_Y = MOD1_X - 16 * G, SUP_Y
    _place_symbol(s, "C", "C8", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C8_X, C8_Y), lib=lib)
    _pin_label(s, "ESP_EN", (C8_X, C8_Y - 3 * G), 'U')
    _pin_label(s, "GND",    (C8_X, C8_Y + 3 * G), 'D')

    # C6 — 10 µF ESP bulk on V3V3_SW
    C6_X, C6_Y = MOD1_X - 8 * G, SUP_Y
    _place_symbol(s, "C", "C6", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C6_X, C6_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (C6_X, C6_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (C6_X, C6_Y + 3 * G), 'D')

    # C7 — 100 nF ESP HF decoupling
    C7_X, C7_Y = MOD1_X, SUP_Y
    _place_symbol(s, "C", "C7", "100nF",
                  "Capacitor_SMD:C_0402_1005Metric",
                  (C7_X, C7_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (C7_X, C7_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (C7_X, C7_Y + 3 * G), 'D')

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
    RTC1_X, RTC1_Y = 60 * G, 150 * G   # RTC cluster left of MCU
    _place_symbol(s, "DS3231M", "RTC1", "DS3231SN#",
                  "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
                  (RTC1_X, RTC1_Y), lib=lib,
                  value_pos=(RTC1_X - 10 * G, RTC1_Y + 13 * G))  # iter 51 fix C: out of body, left of BTN1 cluster
    # CP-cleanup iter 47 (fix B2): pull each RTC1 net label 2G off the
    # pin endpoint with a stub wire so labels read clear of the chip
    # pin name text (VCC/VBAT/GND/SDA/SCL). Pin 2 VCC and pin 14 VBAT
    # are both top-side pins 2G apart in X — VBAT gets an L-shape stub
    # 4G to the right so the two labels don't pile up horizontally.
    _place_wire(s,  (RTC1_X - 2 * G, RTC1_Y -  8 * G), (RTC1_X - 2 * G, RTC1_Y - 10 * G))   # pin 2 stub
    _place_label(s, "V3V3_SW",  (RTC1_X - 2 * G, RTC1_Y - 10 * G), angle=90)                 # pin 2 VCC (top → up)
    # iter 49 (Finding 15): pin 14 VBAT now routed up 4G + right 6G so
    # the V_BAT_RTC label is offset BOTH vertically and horizontally from
    # the pin 2 V3V3_SW label — clear visual gap in iter-47 evidence the
    # 4G horizontal offset alone wasn't enough.
    _place_wire(s,  (RTC1_X,         RTC1_Y -  8 * G), (RTC1_X,         RTC1_Y - 12 * G))   # pin 14 up 4G
    _place_wire(s,  (RTC1_X,         RTC1_Y - 12 * G), (RTC1_X + 6 * G, RTC1_Y - 12 * G))   # pin 14 right 6G
    _place_label(s, "V_BAT_RTC",(RTC1_X + 6 * G, RTC1_Y - 12 * G), angle=90)                 # pin 14 VBAT (top → up)
    # D16: RTC1 pins 5..13 GND → stock power port.
    _place_power_port(s, "GND", (RTC1_X, RTC1_Y + 8 * G), 'D', stub=2 * G, lib=lib)
    _place_wire(s,  (RTC1_X - 10 * G, RTC1_Y - 2 * G), (RTC1_X - 14 * G, RTC1_Y - 2 * G))  # D16: 4G stub so chevron clears pin 15 number
    _place_label(s, "I2C_SDA",  (RTC1_X - 14 * G, RTC1_Y - 2 * G), angle=180)
    _place_wire(s,  (RTC1_X - 10 * G, RTC1_Y - 4 * G), (RTC1_X - 14 * G, RTC1_Y - 4 * G))  # D16: 4G stub
    _place_label(s, "I2C_SCL",  (RTC1_X - 14 * G, RTC1_Y - 4 * G), angle=180)
    _place_noconnect(s, (RTC1_X - 10 * G, RTC1_Y + 4 * G))          # pin 4 RST
    _place_noconnect(s, (RTC1_X + 10 * G, RTC1_Y - 4 * G))          # pin 1 32KHZ
    _place_noconnect(s, (RTC1_X + 10 * G, RTC1_Y + 2 * G))          # pin 3 INT/SQW

    # BAT1 — CR2032 holder, 2-pin (+, -)
    #   pin 1 + lib (0,  5.08), 270 → sch (X, Y-5.08)
    #   pin 2 - lib (0, -2.54),  90 → sch (X, Y+2.54)
    BAT1_X, BAT1_Y = 30 * G, 140 * G
    _place_symbol(s, "Battery_Cell", "BAT1", "CR2032",
                  "Battery:BatteryHolder_Keystone_1057_1x2032",
                  (BAT1_X, BAT1_Y), lib=lib)
    _pin_label(s, "V_BAT_RTC", (BAT1_X, BAT1_Y - 4 * G), 'U')   # pin 1 + (lib_Y=5.08)
    _pin_label(s, "GND",       (BAT1_X, BAT1_Y + 2 * G), 'D')   # pin 2 - (lib_Y=-2.54)

    # C9 — 100 nF RTC VCC decoupling. Moved well away from RTC1's left-edge
    # pins (SCL/SDA/RST at X=63.5) to avoid endpoint collisions with the
    # I2C labels — C9 pin 2 used to land at (63.5, 115.57) right on top of
    # RTC1.SCL's endpoint, forcing GND and I2C_SCL onto the same net.
    # Moved from x=16*G (20.32mm — barely inside left edge) to x=22*G
    # so labels at this anchor stay clear of the page boundary.
    C9_X, C9_Y = 30 * G, 170 * G
    _place_symbol(s, "C", "C9", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C9_X, C9_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (C9_X, C9_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (C9_X, C9_Y + 3 * G), 'D')

    # R8/R9 — I²C pull-ups (SDA/SCL → V3V3_SW)
    R8_X, R8_Y = 48 * G, 128 * G
    _place_symbol(s, "R", "R8", "4.7k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R8_X, R8_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (R8_X, R8_Y - 3 * G), 'U')
    _pin_label(s, "I2C_SDA", (R8_X, R8_Y + 3 * G), 'D')
    R9_X, R9_Y = 42 * G, 128 * G
    # D11 #2 demo: horizontal wire linking R8/R9 V3V3_SW endpoints visually.
    # Both endpoints already have V3V3_SW labels; the wire is decorative
    # reinforcement that these I2C pullups share the same rail. ERC
    # topology unchanged (labels are the topological source-of-truth).
    _place_wire(s, (R9_X, R9_Y - 3 * G), (R8_X, R8_Y - 3 * G))
    _place_symbol(s, "R", "R9", "4.7k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R9_X, R9_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (R9_X, R9_Y - 3 * G), 'U')
    _pin_label(s, "I2C_SCL", (R9_X, R9_Y + 3 * G), 'D')

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
    U3_X, U3_Y = 280 * G, 60 * G   # RS485 far right; cluster derives
    _place_symbol(s, "LTC2850xS8", "U3", "SN65HVD3082E",
                  "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                  (U3_X, U3_Y), lib=lib,
                  value_pos=(U3_X, U3_Y + 18 * G))  # CP6 iter-7: below the GND label stub at Y+16G, with margin
    # CP6 iter-7 strict-overlap fix: GlobalLabel's hexagonal chevron is
    # ~1.5 G wide either side of its anchor; with the previous 2 G horizontal
    # stub the chevron's pointed tip protruded back into the chip body and
    # landed right on top of the pin number ("1", "4", etc.). Bumped to 4 G
    # horizontal stubs and 3 G vertical stubs so the chevron tip sits a
    # full grid step clear of the pin endpoint.
    _STUB_H = 8 * G   # horizontal stub for left/right pins — enough that even the longest label (UART_RX_3V3, ~28 pt = ~10 mm) clears the pin number bbox
    _STUB_V = 4 * G   # vertical stub for top/bottom pins
    _place_wire(s,  (U3_X -  8 * G, U3_Y - 4 * G), (U3_X -  8 * G - _STUB_H, U3_Y - 4 * G))  # pin 1 stub
    _place_label(s, "UART_RX_3V3", (U3_X - 8 * G - _STUB_H, U3_Y - 4 * G), angle=180)         # pin 1 RO (left)
    # CP-cleanup iter 24: U3 ~RE (pin 2) and DE (pin 3) are tied so the
    # MCU drives both with a single DE_RE signal.
    _place_wire(s,  (U3_X -  8 * G, U3_Y - 2 * G), (U3_X -  8 * G, U3_Y))                     # pin 2 ↔ pin 3
    _place_wire(s,  (U3_X -  8 * G, U3_Y - 2 * G), (U3_X -  8 * G - _STUB_H, U3_Y - 2 * G))  # tied-pair stub
    _place_label(s, "DE_RE",       (U3_X - 8 * G - _STUB_H, U3_Y - 2 * G), angle=180)         # pin 2/3 (tied, left)
    _place_wire(s,  (U3_X -  8 * G, U3_Y + 4 * G), (U3_X -  8 * G - _STUB_H, U3_Y + 4 * G))  # pin 4 stub
    _place_label(s, "UART_TX_3V3", (U3_X - 8 * G - _STUB_H, U3_Y + 4 * G), angle=180)         # pin 4 DI (left)
    # D16: U3 pin 5 GND → stock power port.
    _place_power_port(s, "GND", (U3_X, U3_Y + 12 * G), 'D', stub=_STUB_V, lib=lib)
    _place_wire(s,  (U3_X +  8 * G, U3_Y - 6 * G), (U3_X +  8 * G + _STUB_H, U3_Y - 6 * G))  # pin 6 stub
    _place_label(s, "RS485_A",     (U3_X + 8 * G + _STUB_H, U3_Y - 6 * G))                    # pin 6 A
    _place_wire(s,  (U3_X +  8 * G, U3_Y - 2 * G), (U3_X +  8 * G + _STUB_H, U3_Y - 2 * G))  # pin 7 stub
    _place_label(s, "RS485_B",     (U3_X + 8 * G + _STUB_H, U3_Y - 2 * G))                    # pin 7 B
    _place_wire(s,  (U3_X,          U3_Y - 12 * G), (U3_X,          U3_Y - 12 * G - _STUB_V)) # pin 8 stub
    _place_label(s, "V3V3_SW",     (U3_X,          U3_Y - 12 * G - _STUB_V), angle=90)        # pin 8 VCC (top → up)

    # C10 — 100 nF U3 VCC decoupling
    C10_X, C10_Y = U3_X + 6 * G, U3_Y - 10 * G   # (287.02, 50.8)
    _place_symbol(s, "C", "C10", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C10_X, C10_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (C10_X, C10_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (C10_X, C10_Y + 3 * G), 'D')

    # R10 — 120 Ω RS-485 termination (A ↔ B). Horizontal so both pins
    # land on the A/B nets without rotating the symbol.
    R10_X, R10_Y = U3_X + 16 * G, U3_Y - 4 * G   # (299.72, 58.42)
    _place_symbol(s, "R", "R10", "120",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R10_X, R10_Y), lib=lib,
                  ref_pos=(R10_X + 6 * G, R10_Y - 1.27),   # D16: ref far right, clear of RS485_A label bbox
                  value_pos=(R10_X + 6 * G, R10_Y + 1.27)) # D16: value far right, clear of RS485_B label bbox
    _pin_label(s, "RS485_A", (R10_X, R10_Y - 3 * G), 'U')   # pin 1
    # D16: R10.pin2 RS485_B label deduped — wire-out to R12.pin1
    # placed below; corner at the trunk Y. Wire emitted after R12
    # is positioned (see RS485_B trunk block below).

    # R11 — 680 Ω idle bias A → V3V3_SW
    R11_X, R11_Y = U3_X + 12 * G, U3_Y - 12 * G   # (294.64, 47.62)
    _place_symbol(s, "R", "R11", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R11_X, R11_Y), lib=lib)
    _pin_label(s, "V3V3_SW", (R11_X, R11_Y - 3 * G), 'U')
    # RS485_A label deduped — wire down to R10.pin1 (also RS485_A);
    # R10 keeps the label.

    # R12 — 680 Ω idle bias B → GND
    R12_X, R12_Y = U3_X + 12 * G, U3_Y + 8 * G   # (294.64, 73.66)
    _place_symbol(s, "R", "R12", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R12_X, R12_Y), lib=lib,
                  ref_pos=(R12_X + 6 * G, R12_Y - 1.27),   # D16: ref far right
                  value_pos=(R12_X + 6 * G, R12_Y + 1.27)) # D16: value far right
    _pin_label(s, "RS485_B", (R12_X, R12_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (R12_X, R12_Y + 3 * G), 'D')
    # D16: RS485_B trunk — wire R10.pin2 down + over to R12.pin1
    # (both RS485_B). R12.pin1 keeps the single label.
    _place_wire(s, (R10_X, R10_Y + 3 * G), (R10_X, R12_Y - 3 * G))
    _place_wire(s, (R10_X, R12_Y - 3 * G), (R12_X, R12_Y - 3 * G))

    # TVS2 — SMAJ12CA differential clamp across A/B. Device:D_TVS with
    # Value override. Horizontal (pins ±3.81 X from center).
    TVS2_X, TVS2_Y = U3_X + 24 * G, U3_Y - 4 * G   # right of R10 (8G gap) so values don't collide; same row keeps A-dedup wire clear of R10.pin2
    _place_symbol(s, "D_TVS", "TVS2", "SMAJ12CA",
                  "Diode_SMD:D_SMA",
                  (TVS2_X, TVS2_Y), lib=lib,
                  ref_pos=(TVS2_X, TVS2_Y - 3 * G),    # D16: ref above, clear of RS485_B label
                  value_pos=(TVS2_X, TVS2_Y + 3 * G))
    # TVS2.pin1 RS485_A label deduped — wire to R10.pin1.
    _pin_label(s, "RS485_B", (TVS2_X + 3 * G, TVS2_Y), 'R')   # pin 2
    # CP-cleanup iter 30: cluster the 4 RS485_A endpoints (U3.A,
    # R10.pin1, R11.pin2, TVS2.pin1) — wire R11 and TVS2 to R10;
    # U3.A keeps its own RS485_A label (name connects across the
    # schematic). Two labels eliminated.
    _place_wire(s, (R10_X, R10_Y - 3 * G), (R10_X, R11_Y + 3 * G))  # R10.pin1 → corner
    _place_wire(s, (R10_X, R11_Y + 3 * G), (R11_X, R11_Y + 3 * G))  # corner → R11.pin2
    _place_wire(s, (R10_X, R10_Y - 3 * G), (R10_X, TVS2_Y))         # R10.pin1 → corner
    _place_wire(s, (R10_X, TVS2_Y),         (TVS2_X - 3 * G, TVS2_Y))  # corner → TVS2.pin1

    # D16: BTN1 + R13 + C11 debounce cluster — single horizontal
    # BTN_OVERRIDE trunk at Y=192G connects BTN1 pin 1 (left) to
    # R13.pin 2 (bottom) to C11.pin 1 (top). R13 sits above the
    # trunk pulling BTN_OVERRIDE up to V3V3_SW; C11 sits below the
    # trunk debouncing BTN_OVERRIDE to GND. One BTN_OVERRIDE
    # GlobalLabel on the trunk carries the net to MOD1. The label-
    # at-each-pin pattern used through iter-7 forced the reader to
    # mentally splice three separate "BTN_OVERRIDE" labels.
    #
    # BTN1 SW_Push pin geometry: pin 1 left (X-5.08, Y), pin 2 right
    # (X+5.08, Y). Net mapping: pin 1 → BTN_OVERRIDE (trunk-going-
    # right), pin 2 → GND (port to the right). Trunk runs right from
    # BTN1.pin1 anchor + 2G clearance to R13.pin2 and on to C11.pin1.
    # BTN1 override pushbutton cluster: SW_Push horizontal, R13 1MΩ
    # pull-up vertical to its right, C11 100nF debounce vertical further
    # right. Per-pin labels (BTN_OVERRIDE on each side of the net) carry
    # the connection; in-cluster wire restructuring deferred (ERC
    # tractability — the trunk-through-SW_Push-body topology trips
    # `wire_dangling`, requires lib-symbol body geometry inspection).
    BTN1_X, BTN1_Y = 45 * G, 192 * G   # override button, bottom-left
    _place_symbol(s, "SW_Push", "BTN1", "OVERRIDE",
                  "Button_Switch_THT:SW_PUSH_6mm",
                  (BTN1_X, BTN1_Y), lib=lib,
                  ref_pos=(BTN1_X - 2 * G, BTN1_Y - 5 * G),
                  value_pos=(BTN1_X - 2 * G, BTN1_Y + 5 * G))
    _place_wire(s,  (BTN1_X - 4 * G, BTN1_Y), (BTN1_X - 6 * G, BTN1_Y))
    _place_label(s, "BTN_OVERRIDE", (BTN1_X - 6 * G, BTN1_Y), angle=180)
    _place_power_port(s, "GND", (BTN1_X + 4 * G, BTN1_Y), 'R', stub=2 * G, lib=lib)

    R13_X, R13_Y = 62 * G, 192 * G
    _place_symbol(s, "R", "R13", "1M",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R13_X, R13_Y), lib=lib)
    _pin_label(s, "V3V3_SW",      (R13_X, R13_Y - 3 * G), 'U')
    _pin_label(s, "BTN_OVERRIDE", (R13_X, R13_Y + 3 * G), 'D')

    C11_X, C11_Y = 78 * G, 192 * G
    _place_symbol(s, "C", "C11", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C11_X, C11_Y), lib=lib)
    _pin_label(s, "BTN_OVERRIDE", (C11_X, C11_Y - 3 * G), 'U')
    _pin_label(s, "GND",          (C11_X, C11_Y + 3 * G), 'D')

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
    J2_X, J2_Y = 225 * G, 135 * G   # connectors right of MCU, clear of title block
    _place_symbol(s, "8P8C", "J2", "RJ45",
                  "Connector_RJ:RJ45_Amphenol_RJHSE5380",
                  (J2_X, J2_Y), lib=lib)
    # Pin Y offsets from symbol center (after Y-flip): pin 1=+7.62 below,
    # pin 8=-10.16 above. Use 3*G grid alignment (lib_Y values are
    # multiples of 2.54 = 2*G, so Y-flip gives multiples of 2*G).
    # CP-cleanup iter 24: pins 1/2/3 share V12_CAT5E, pins 6/7/8 share
    # GND. Previously each pin got its own label → 3 stacked labels per
    # rail at 2.54mm pitch (unreadable). Replaced with one label + a
    # vertical wire that spans the three same-net pin endpoints
    # (criterion #2 pattern).
    _PIN_X = J2_X + 8 * G
    # V12_CAT5E: 2 wire segments (pin 1↔2 and pin 2↔3) so each wire
    # endpoint coincides with an actual pin endpoint (ERC requirement
    # — KiCad doesn't auto-connect at wire midpoint without junctions).
    _place_wire(s, (_PIN_X, J2_Y + 6 * G), (_PIN_X, J2_Y + 4 * G))   # pin 1 → pin 2
    _place_wire(s, (_PIN_X, J2_Y + 4 * G), (_PIN_X, J2_Y + 2 * G))   # pin 2 → pin 3
    _pin_label(s, "V12_CAT5E", (_PIN_X, J2_Y + 4 * G), 'R')          # at pin 2 (middle)
    _pin_label(s, "RS485_A",   (_PIN_X, J2_Y),         'R')          # pin 4
    _pin_label(s, "RS485_B",   (_PIN_X, J2_Y - 2 * G), 'R')          # pin 5
    # GND: 2 wire segments (pin 6↔7 and pin 7↔8)
    _place_wire(s, (_PIN_X, J2_Y - 4 * G), (_PIN_X, J2_Y - 6 * G))   # pin 6 → pin 7
    _place_wire(s, (_PIN_X, J2_Y - 6 * G), (_PIN_X, J2_Y - 8 * G))   # pin 7 → pin 8
    _pin_label(s, "GND",       (_PIN_X, J2_Y - 6 * G), 'R')          # at pin 7 (middle)

    # J3 — 4-pin USB-OTG dev header (D+/D-/EN/GND)
    # Conn_01x04 pin lib: pin 1 (-5.08, 2.54), pin 2 (-5.08, 0),
    # pin 3 (-5.08, -2.54), pin 4 (-5.08, -5.08).
    # Sch endpoints: (X-5.08, Y - lib_Y).
    J3_X, J3_Y = 225 * G, 165 * G
    _place_symbol(s, "Conn_01x04", "J3", "USB-OTG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J3_X, J3_Y), lib=lib)
    _pin_label(s, "USB_DP",  (J3_X - 4 * G, J3_Y - 2 * G), 'L')   # pin 1 (lib_Y=+2.54)
    _pin_label(s, "USB_DM",  (J3_X - 4 * G, J3_Y),         'L')   # pin 2 (lib_Y= 0)
    _pin_label(s, "ESP_EN",  (J3_X - 4 * G, J3_Y + 2 * G), 'L')   # pin 3 (lib_Y=-2.54)
    _pin_label(s, "GND",     (J3_X - 4 * G, J3_Y + 4 * G), 'L')   # pin 4 (lib_Y=-5.08)

    # J5 — 4-pin UART debug header (TX/RX/GND/RESET#).
    # Reset (ESP_EN) reuses J3.3; J5 just exposes UART RX/TX + GND + EN.
    J5_X, J5_Y = 225 * G, 182 * G
    _place_symbol(s, "Conn_01x04", "J5", "UART-DBG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J5_X, J5_Y), lib=lib)
    # CP6 iter-7: longer label stub (8G ≈ 10 mm) so the 11-char
    # DBG_UART_* labels don't reach back into the connector body.
    _LONG = 8 * G
    _pin_label(s, "DBG_UART_TX", (J5_X - 4 * G, J5_Y - 2 * G), 'L', stub=_LONG)   # pin 1
    _pin_label(s, "DBG_UART_RX", (J5_X - 4 * G, J5_Y),         'L', stub=_LONG)   # pin 2
    _pin_label(s, "GND",         (J5_X - 4 * G, J5_Y + 2 * G), 'L', stub=_LONG)   # pin 3
    _pin_label(s, "ESP_EN",      (J5_X - 4 * G, J5_Y + 4 * G), 'L', stub=_LONG)   # pin 4 RESET#

    # ===== Power flags =====
    # In KiCad's ERC model, a `power_in` pin (like U1.VIN, U1.GND) needs a
    # matching `power_out` pin OR a PWR_FLAG on the same net. Our V24 source
    # is the battery itself (external to the schematic) and arrives via
    # passive connector pins — those don't satisfy ERC. PWR_FLAG is the
    # standard pattern for nets sourced from outside the schematic. We
    # keep these for the lifetime of the design.
    # CP-cleanup iter 20 (Finding 06): moved PWR_FLAG column from
    # x=R5_X-20*G=60*G — which clashed with F1's column (76.2 mm) and
    # produced the dense V24_* label cluster — to a dedicated
    # horizontal strip at y=180*G=228.6mm (bottom of the A3 sheet,
    # well below all other components). Spaced 20*G=25.4mm apart so
    # adjacent flag labels have plenty of horizontal breathing room.
    _PF_Y = 206 * G   # power-flag strip along the bottom
    _place_power_flag(s, "V24_FUSED", (40 * G,  _PF_Y), lib)
    _place_power_flag(s, "GND",       (70 * G,  _PF_Y), lib)
    _place_power_flag(s, "V24_SW",    (100 * G, _PF_Y), lib)
    _place_power_flag(s, "V3V3_SW",   (130 * G, _PF_Y), lib)
    _place_power_flag(s, "V_BAT_RTC", (160 * G, _PF_Y), lib)
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
    _add_rail_convention_note(s)
    lib = _load_project_lib()
    _set_active_lib(lib)
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
    # CP-cleanup iter 24: same RJ45 dedup as battery-side J2 — pins
    # 1/2/3 share V12_CAT5E, pins 6/7/8 share GND. Replace stacked
    # labels with a vertical wire + single label per rail.
    _PIN_X = J1_X + 8 * G
    # Same per-segment wire pattern as battery-side J2 (so each wire
    # endpoint coincides with an actual pin endpoint for ERC).
    _place_wire(s, (_PIN_X, J1_Y + 6 * G), (_PIN_X, J1_Y + 4 * G))
    _place_wire(s, (_PIN_X, J1_Y + 4 * G), (_PIN_X, J1_Y + 2 * G))
    _pin_label(s, "V12_CAT5E", (_PIN_X, J1_Y + 4 * G), 'R')
    _pin_label(s, "RS485_A",   (_PIN_X, J1_Y),         'R')   # pin 4
    _pin_label(s, "RS485_B",   (_PIN_X, J1_Y - 2 * G), 'R')   # pin 5
    _place_wire(s, (_PIN_X, J1_Y - 4 * G), (_PIN_X, J1_Y - 6 * G))
    _place_wire(s, (_PIN_X, J1_Y - 6 * G), (_PIN_X, J1_Y - 8 * G))
    _pin_label(s, "GND",       (_PIN_X, J1_Y - 6 * G), 'R')

    # F1 — PTC polyfuse (0.5A hold) on V12_CAT5E
    F1_X, F1_Y = 55 * G, 50 * G   # (69.85, 63.5)
    _place_symbol(s, "Polyfuse", "F1", "MF-R050",
                  "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
                  (F1_X, F1_Y), lib=lib,
                  ref_pos=(F1_X - 4 * G, F1_Y - 1.27),    # D16: ref left, opposite from V12_PROT labels (which go right of F1.pin2)
                  value_pos=(F1_X - 4 * G, F1_Y + 1.27))
    # Polyfuse pin geometry mirrors Fuse/R (lib Y ±3.81 → sch Y ∓3.81).
    _pin_label(s, "V12_CAT5E", (F1_X, F1_Y - 3 * G), 'U')   # pin 1
    _pin_label(s, "V12_PROT",  (F1_X, F1_Y + 3 * G), 'D')   # pin 2

    # TVS1 — SMAJ15A unidirectional TVS on V12_PROT ↔ GND
    TVS1_X, TVS1_Y = 70 * G, 50 * G   # (88.9, 63.5)
    _place_symbol(s, "D", "TVS1", "SMAJ15A",
                  "Diode_SMD:D_SMA",
                  (TVS1_X, TVS1_Y), lib=lib,
                  ref_pos=(TVS1_X, TVS1_Y - 3 * G),    # D16: ref above body, clear of V12_PROT label
                  value_pos=(TVS1_X, TVS1_Y + 3 * G))
    _pin_label(s, "GND",      (TVS1_X - 3 * G, TVS1_Y), 'L')   # pin 1 K
    _pin_label(s, "V12_PROT", (TVS1_X + 3 * G, TVS1_Y), 'R')   # pin 2 A

    # C1 — 22µF/25V input bulk on V12_PROT
    C1_X, C1_Y = 60 * G, 60 * G   # (76.2, 76.2)
    _place_symbol(s, "C", "C1", "22uF/25V",
                  "Capacitor_SMD:C_1210_3225Metric",
                  (C1_X, C1_Y), lib=lib)
    _pin_label(s, "V12_PROT", (C1_X, C1_Y - 3 * G), 'U')
    _pin_label(s, "GND",      (C1_X, C1_Y + 3 * G), 'D')

    # ===== Power conversion: U1 Recom R-78E3.3-0.5 + C2 output bulk =====

    # U1 — Recom R-78E3.3-0.5 (12V → 3V3, 0.5A). Conn_01x03 stand-in:
    # pin 1 lib (-5.08, +2.54) → sch (X-5.08, Y-2.54) — VIN
    # pin 2 lib (-5.08, 0)     → sch (X-5.08, Y)        — GND
    # pin 3 lib (-5.08, -2.54) → sch (X-5.08, Y+2.54)   — VOUT
    U1_X, U1_Y = 85 * G, 50 * G   # (107.95, 63.5)
    _place_symbol(s, "Conn_01x03", "U1", "R-78E3.3-0.5",
                  "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                  (U1_X, U1_Y), lib=lib,
                  value_pos=(U1_X, U1_Y + 6 * G))  # CP6 iter-7: out of body, clear of pin 3 number bbox
    _pin_label(s, "V12_PROT", (U1_X - 4 * G, U1_Y - 2 * G), 'L')   # pin 1 VIN
    _pin_label(s, "GND",      (U1_X - 4 * G, U1_Y),         'L')   # pin 2 GND
    _pin_label(s, "V3V3",     (U1_X - 4 * G, U1_Y + 2 * G), 'L')   # pin 3 VOUT

    # C2 — 10µF output bulk on V3V3
    C2_X, C2_Y = 95 * G, 60 * G   # (120.65, 76.2)
    _place_symbol(s, "C", "C2", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C2_X, C2_Y), lib=lib)
    _pin_label(s, "V3V3", (C2_X, C2_Y - 3 * G), 'U')
    _pin_label(s, "GND",  (C2_X, C2_Y + 3 * G), 'D')

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
    _esp_pin_info = {
        int(p.number): (p.position.X, p.position.Y, p.position.angle)
        for u in _esp_sym.units for p in u.pins
    }

    _place_symbol(s, "ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "RF_Module:ESP32-S3-WROOM-1U",  # -1U variant: external U.FL antenna, no keepout zone
                  (MOD1_X, MOD1_Y), lib=lib,
                  ref_pos=(MOD1_X, MOD1_Y - 24 * G),    # CP6 iter-7: above body, clear of in-symbol "PSRAM" text
                  value_pos=(MOD1_X, MOD1_Y + 30 * G))  # CP6 iter-7: below GND label stub at Y+26G
    # Dedupe shared symbol pins (1/40/41 GND) — see battery-side comment.
    # CP-cleanup iter 47 (fix B2): same 2G stub-out treatment as
    # battery-side MOD1 so net labels read clear of the chip's
    # in-symbol pin name text.
    _placed = set()
    for pin_num, net in esp_pins.items():
        lib_x, lib_y, lib_a = _esp_pin_info[pin_num]
        endpoint = (MOD1_X + lib_x, MOD1_Y - lib_y)
        if endpoint in _placed:
            continue
        _placed.add(endpoint)
        if net == "NC":
            _place_noconnect(s, endpoint)
        else:
            dx, dy = _outward_for_angle(lib_a)
            outer = (endpoint[0] + dx * 6 * G, endpoint[1] + dy * 6 * G)  # D16: 6G stub so chevron tip clears the newly-visible MOD1 pin number
            _place_wire(s, endpoint, outer)
            # Orient the label so its text reads AWAY from the symbol body
            # (left-side pins must extend left, not back over the pin name).
            lbl_angle = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}.get((dx, dy), 0)
            _place_label(s, net, outer, angle=lbl_angle)

    # ===== ESP support: R1 EN pull-up + C5 EN soft-start + C3 bulk + C4 HF =====
    # SUP_Y kept ≥38G above MOD1 so the caps' downward GND stubs clear MOD1's
    # top-pin label stubs (4G) — at 32G they collided, shorting GND↔V3V3.
    SUP_Y = MOD1_Y - 40 * G
    # R1 — 10kΩ EN pull-up
    R1_X, R1_Y = MOD1_X - 24 * G, SUP_Y
    _place_symbol(s, "R", "R1", "10k",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R1_X, R1_Y), lib=lib)
    _pin_label(s, "V3V3",   (R1_X, R1_Y - 3 * G), 'U')
    _pin_label(s, "ESP_EN", (R1_X, R1_Y + 3 * G), 'D')
    # C5 — 1µF EN soft-start
    C5_X, C5_Y = MOD1_X - 16 * G, SUP_Y
    _place_symbol(s, "C", "C5", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C5_X, C5_Y), lib=lib)
    _pin_label(s, "ESP_EN", (C5_X, C5_Y - 3 * G), 'U')
    _pin_label(s, "GND",    (C5_X, C5_Y + 3 * G), 'D')
    # C3 — 10µF ESP bulk
    C3_X, C3_Y = MOD1_X - 8 * G, SUP_Y
    _place_symbol(s, "C", "C3", "10uF",
                  "Capacitor_SMD:C_0805_2012Metric",
                  (C3_X, C3_Y), lib=lib)
    _pin_label(s, "V3V3", (C3_X, C3_Y - 3 * G), 'U')
    _pin_label(s, "GND",  (C3_X, C3_Y + 3 * G), 'D')
    # C4 — 100nF ESP HF decoupling
    C4_X, C4_Y = MOD1_X, SUP_Y
    _place_symbol(s, "C", "C4", "100nF",
                  "Capacitor_SMD:C_0402_1005Metric",
                  (C4_X, C4_Y), lib=lib)
    _pin_label(s, "V3V3", (C4_X, C4_Y - 3 * G), 'U')
    _pin_label(s, "GND",  (C4_X, C4_Y + 3 * G), 'D')

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
    # Moved right of MOD1 (CP-schematic-cleanup iter 10, criterion #3):
    # the e-paper FFC visually represents the panel that sits to the
    # right of the MCU in the physical layout. Putting it on the right
    # side of the sheet aligns schematic geometry with signal flow.
    # 24-pin column extends 23*G = 29.2 mm down from anchor; anchor at
    # y=70*G means pins span y=70-99*G, clear of MOD1's body at y=78-122*G.
    J2_X, J2_Y = 200 * G, 70 * G   # (254.0, 88.9)
    _place_symbol(s, "Conn_01x24", "J2", "EPD_FFC_24",
                  "Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal",
                  (J2_X, J2_Y), lib=lib,
                  ref_pos=(J2_X, J2_Y - 4 * G),    # D16: ref above body, clear of pin labels
                  value_pos=(J2_X, J2_Y + 33 * G)) # D16: value below 24-pin stack
    # CP-cleanup iter 26 (Finding 08): pins 2/3 share V3V3 (adjacent on
    # the FFC). Dedupe with a wire + single label so the 24-pin stack
    # at x=248.92 has one fewer redundant label. Pins 1/4 also share
    # GND but they're separated by V3V3 pins, so the wire would need
    # to route around — keep two GND labels there.
    epd_pins = {
        1: "GND",
        # pin 2/3 V3V3 — single label below; wire connects pin 2 to pin 3
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
            _pin_label(s, epd_pins[pin], endpoint, 'L')
        elif pin in (2, 3):
            continue  # handled below as shared V3V3 with wire
        else:
            _place_noconnect(s, endpoint)

    # V3V3 dedup: pin 2 at lib_y=25.4 → schematic y = 88.9-25.4 = 63.5
    #             pin 3 at lib_y=22.86 → schematic y = 88.9-22.86 = 66.04
    _v3v3_x = J2_X - 5.08
    _place_wire(s, (_v3v3_x, J2_Y - 25.4), (_v3v3_x, J2_Y - 22.86))   # pin 2 → pin 3
    _pin_label(s, "V3V3", (_v3v3_x, J2_Y - 22.86), 'L')               # at pin 3

    # C6 — 1µF panel VCC bulk (reduces VCC dip during refresh)
    C6_X, C6_Y = 60 * G, 90 * G   # (76.2, 114.3)
    _place_symbol(s, "C", "C6", "1uF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C6_X, C6_Y), lib=lib)
    _pin_label(s, "V3V3", (C6_X, C6_Y - 3 * G), 'U')
    _pin_label(s, "GND",  (C6_X, C6_Y + 3 * G), 'D')

    # ===== RS-485: U2 (LTC2850xS8 stand-in for SN65HVD3082E) + passives =====
    # Same topology as battery-side U3. This end is the bus terminus (R2
    # populated). Idle bias R3/R4 footprints provided but treated as
    # populated for ERC simplicity (CP1 D-OPEN-8 default says "don't
    # populate by default" but ERC-wise we still place them since the
    # bias defines the idle state of the differential pair).
    U2_X, U2_Y = 220 * G, 80 * G   # (279.4, 101.6)
    _place_symbol(s, "LTC2850xS8", "U2", "SN65HVD3082E",
                  "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                  (U2_X, U2_Y), lib=lib,
                  value_pos=(U2_X, U2_Y + 18 * G))  # CP6 iter-7: below the GND label stub at Y+16G, with margin
    # CP6 iter-7 strict-overlap fix: same as battery U3 — 4 G horizontal
    # and 3 G vertical stubs so the GlobalLabel chevron tip stays clear
    # of pin numbers.
    _STUB_H = 8 * G
    _STUB_V = 4 * G
    _place_wire(s,  (U2_X -  8 * G, U2_Y - 4 * G), (U2_X -  8 * G - _STUB_H, U2_Y - 4 * G))  # pin 1 stub
    _place_label(s, "UART_RX_3V3", (U2_X - 8 * G - _STUB_H, U2_Y - 4 * G), angle=180)         # pin 1 RO (left)
    _place_wire(s,  (U2_X -  8 * G, U2_Y - 2 * G), (U2_X -  8 * G, U2_Y))                     # pin 2 ↔ pin 3
    _place_wire(s,  (U2_X -  8 * G, U2_Y - 2 * G), (U2_X -  8 * G - _STUB_H, U2_Y - 2 * G))  # tied-pair stub
    _place_label(s, "DE_RE",       (U2_X - 8 * G - _STUB_H, U2_Y - 2 * G), angle=180)         # pin 2/3 (tied, left)
    _place_wire(s,  (U2_X -  8 * G, U2_Y + 4 * G), (U2_X -  8 * G - _STUB_H, U2_Y + 4 * G))  # pin 4 stub
    _place_label(s, "UART_TX_3V3", (U2_X - 8 * G - _STUB_H, U2_Y + 4 * G), angle=180)         # pin 4 DI (left)
    # D16: U2 pin 5 GND → stock power port.
    _place_power_port(s, "GND", (U2_X, U2_Y + 12 * G), 'D', stub=_STUB_V, lib=lib)
    _place_wire(s,  (U2_X +  8 * G, U2_Y - 6 * G), (U2_X +  8 * G + _STUB_H, U2_Y - 6 * G))  # pin 6 stub
    _place_label(s, "RS485_A",     (U2_X + 8 * G + _STUB_H, U2_Y - 6 * G))                    # pin 6 A
    _place_wire(s,  (U2_X +  8 * G, U2_Y - 2 * G), (U2_X +  8 * G + _STUB_H, U2_Y - 2 * G))  # pin 7 stub
    _place_label(s, "RS485_B",     (U2_X + 8 * G + _STUB_H, U2_Y - 2 * G))                    # pin 7 B
    _place_wire(s,  (U2_X,          U2_Y - 12 * G), (U2_X,          U2_Y - 12 * G - _STUB_V)) # pin 8 stub
    _place_label(s, "V3V3",        (U2_X,          U2_Y - 12 * G - _STUB_V), angle=90)        # pin 8 VCC (top → up)

    # C7 — 100nF U2 VCC decoupling
    C7_X, C7_Y = U2_X + 6 * G, U2_Y - 10 * G   # (286.94, 88.9)
    _place_symbol(s, "C", "C7", "100nF",
                  "Capacitor_SMD:C_0603_1608Metric",
                  (C7_X, C7_Y), lib=lib)
    _pin_label(s, "V3V3", (C7_X, C7_Y - 3 * G), 'U')
    _pin_label(s, "GND",  (C7_X, C7_Y + 3 * G), 'D')

    # R2 — 120Ω termination (A ↔ B), bus terminus
    R2_X, R2_Y = U2_X + 16 * G, U2_Y - 4 * G   # (299.72, 96.52)
    _place_symbol(s, "R", "R2", "120",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R2_X, R2_Y), lib=lib,
                  ref_pos=(R2_X + 6 * G, R2_Y - 1.27),   # D16: ref far right, clear of RS485_A label bbox
                  value_pos=(R2_X + 6 * G, R2_Y + 1.27)) # D16: value far right
    _pin_label(s, "RS485_A", (R2_X, R2_Y - 3 * G), 'U')
    # D16: R2.pin2 RS485_B label deduped — wire emitted after R4
    # is placed below (same pattern as battery U3 R10→R12).

    # R3 — 680Ω idle bias A → V3V3
    R3_X, R3_Y = U2_X + 12 * G, U2_Y - 12 * G   # (294.64, 85.72)
    _place_symbol(s, "R", "R3", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R3_X, R3_Y), lib=lib)
    _pin_label(s, "V3V3",    (R3_X, R3_Y - 3 * G), 'U')
    # RS485_A label deduped — wire to R2.pin1 (same pattern as battery U3).

    # R4 — 680Ω idle bias B → GND
    R4_X, R4_Y = U2_X + 12 * G, U2_Y + 8 * G   # (294.64, 111.76)
    _place_symbol(s, "R", "R4", "680",
                  "Resistor_SMD:R_0805_2012Metric",
                  (R4_X, R4_Y), lib=lib)
    _pin_label(s, "RS485_B", (R4_X, R4_Y - 3 * G), 'U')
    _pin_label(s, "GND",     (R4_X, R4_Y + 3 * G), 'D')
    # D16: RS485_B trunk — wire R2.pin2 → R4.pin1 (both RS485_B).
    _place_wire(s, (R2_X, R2_Y + 3 * G), (R2_X, R4_Y - 3 * G))
    _place_wire(s, (R2_X, R4_Y - 3 * G), (R4_X, R4_Y - 3 * G))

    # TVS2 — SMAJ12CA differential clamp across A/B
    TVS2_X, TVS2_Y = U2_X + 24 * G, U2_Y - 4 * G   # right of R2 (8G gap) so values don't collide; same row keeps A-dedup wire clear of R2.pin2
    _place_symbol(s, "D_TVS", "TVS2", "SMAJ12CA",
                  "Diode_SMD:D_SMA",
                  (TVS2_X, TVS2_Y), lib=lib,
                  ref_pos=(TVS2_X, TVS2_Y - 3 * G),    # D16: ref above, clear of RS485_B label
                  value_pos=(TVS2_X, TVS2_Y + 3 * G))
    # TVS2.pin1 RS485_A label deduped — wire to R2.pin1.
    _pin_label(s, "RS485_B", (TVS2_X + 3 * G, TVS2_Y), 'R')
    # Same RS485_A cluster dedup as battery-side U3 area:
    _place_wire(s, (R2_X, R2_Y - 3 * G), (R2_X, R3_Y + 3 * G))   # R2.pin1 → corner
    _place_wire(s, (R2_X, R3_Y + 3 * G), (R3_X, R3_Y + 3 * G))   # corner → R3.pin2
    _place_wire(s, (R2_X, R2_Y - 3 * G), (R2_X, TVS2_Y))         # R2.pin1 → corner
    _place_wire(s, (R2_X, TVS2_Y),         (TVS2_X - 3 * G, TVS2_Y))  # corner → TVS2.pin1

    # ===== Buttons: BTN1/2/3 + R5/R6/R7 (1MΩ pull-ups) + C8/C9/C10 (debounce) =====
    # Per-pin labels (BTN<N>_IN on each side of the net). In-cluster
    # wire restructure deferred — same trunk-through-SW_Push-body ERC
    # issue as battery BTN1.
    for i, (btn_ref, r_ref, c_ref, btn_net) in enumerate([
        ("BTN1", "R5", "C8",  "BTN1_IN"),
        ("BTN2", "R6", "C9",  "BTN2_IN"),
        ("BTN3", "R7", "C10", "BTN3_IN"),
    ]):
        BTN_X = (200 + i * 30) * G
        BTN_Y = 150 * G
        _place_symbol(s, "SW_Push", btn_ref, btn_ref,
                      "Button_Switch_SMD:SW_SPST_B3S-1000",
                      (BTN_X, BTN_Y), lib=lib,
                      ref_pos=(BTN_X - 2 * G, BTN_Y - 5 * G),
                      value_pos=(BTN_X - 2 * G, BTN_Y + 5 * G))
        _place_wire(s,  (BTN_X - 4 * G, BTN_Y), (BTN_X - 6 * G, BTN_Y))
        _place_label(s, btn_net, (BTN_X - 6 * G, BTN_Y), angle=180)
        _place_power_port(s, "GND", (BTN_X + 4 * G, BTN_Y), 'R', stub=2 * G, lib=lib)
        R_X = BTN_X + 8 * G
        _place_symbol(s, "R", r_ref, "1M",
                      "Resistor_SMD:R_0805_2012Metric",
                      (R_X, BTN_Y), lib=lib)
        _pin_label(s, "V3V3",  (R_X, BTN_Y - 3 * G), 'U')
        _pin_label(s, btn_net, (R_X, BTN_Y + 3 * G), 'D')
        C_X = BTN_X + 16 * G
        _place_symbol(s, "C", c_ref, "100nF",
                      "Capacitor_SMD:C_0603_1608Metric",
                      (C_X, BTN_Y), lib=lib)
        _pin_label(s, btn_net, (C_X, BTN_Y - 3 * G), 'U')
        _pin_label(s, "GND",   (C_X, BTN_Y + 3 * G), 'D')

    # ===== Dev headers: J3 (UART debug) + J4 (USB-OTG) =====

    # CP6 iter-7: longer label stub (8G ≈ 10 mm) so the 11-char
    # DBG_UART_* / USB_* labels don't reach back into the connector body.
    _LONG = 8 * G

    # J3 — UART debug: TX/RX/GND/RESET#
    J3_X, J3_Y = 30 * G, 120 * G   # (38.1, 152.4)
    _place_symbol(s, "Conn_01x04", "J3", "UART-DBG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J3_X, J3_Y), lib=lib)
    _pin_label(s, "DBG_UART_TX", (J3_X - 4 * G, J3_Y - 2 * G), 'L', stub=_LONG)   # pin 1
    _pin_label(s, "DBG_UART_RX", (J3_X - 4 * G, J3_Y),         'L', stub=_LONG)   # pin 2
    _pin_label(s, "GND",         (J3_X - 4 * G, J3_Y + 2 * G), 'L', stub=_LONG)   # pin 3
    _pin_label(s, "ESP_EN",      (J3_X - 4 * G, J3_Y + 4 * G), 'L', stub=_LONG)   # pin 4

    # J4 — USB-OTG: D+/D-/GND/V3V3
    J4_X, J4_Y = 30 * G, 130 * G   # (38.1, 165.1)
    _place_symbol(s, "Conn_01x04", "J4", "USB-OTG",
                  "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
                  (J4_X, J4_Y), lib=lib)
    _pin_label(s, "USB_DP", (J4_X - 4 * G, J4_Y - 2 * G), 'L', stub=_LONG)
    _pin_label(s, "USB_DM", (J4_X - 4 * G, J4_Y),         'L', stub=_LONG)
    _pin_label(s, "GND",    (J4_X - 4 * G, J4_Y + 2 * G), 'L', stub=_LONG)
    _pin_label(s, "V3V3",   (J4_X - 4 * G, J4_Y + 4 * G), 'L', stub=_LONG)

    # ===== Power flags =====
    # CP-schematic-cleanup iter 51 (fix E): moved PWR_FLAGs from the
    # X=20*G column (which sat on the J1 RJ45 body at Y=50*G…80*G — see
    # iter-37 finding for display 02) to the same bottom-row pattern
    # the battery side uses (_PF_Y=180*G, spread horizontally). Clears
    # the J1 body completely.
    _PF_Y = 180 * G
    # V12_CAT5E sourced externally (from Cat5e battery side) via J1's
    # `passive` connector pins. Same pattern as V24_FUSED on battery side.
    _place_power_flag(s, "V12_CAT5E", (40 * G,  _PF_Y), lib)
    # GND sourced externally via J1; passive pins don't drive ERC.
    _place_power_flag(s, "GND",       (60 * G,  _PF_Y), lib)
    # V12_PROT: post-PTC, post-TVS. F1.2 is passive, TVS1.A is passive,
    # U1.VIN (Conn_01x03) is passive. PWR_FLAG bridges.
    _place_power_flag(s, "V12_PROT",  (80 * G,  _PF_Y), lib)
    # V3V3: U1.VOUT is passive. MOD1.3V3 is power_input. PWR_FLAG bridges.
    _place_power_flag(s, "V3V3",      (100 * G, _PF_Y), lib)

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
    # D16: --exclude-pdf-property-popups / --exclude-pdf-hierarchical-
    # links / --exclude-pdf-metadata strip the PDF accessibility / link
    # overlays. The property-popups overlay normally double-emits every
    # Reference / Value / pin-name string, which would surface as
    # SAME-TEXT identical-bbox pairs in the strict audit. None of those
    # overlays are useful in committed fab-ready PDFs.
    rc, _, err = run_kicad_cli("sch", "export", "pdf",
                               "--exclude-pdf-property-popups",
                               "--exclude-pdf-hierarchical-links",
                               "--exclude-pdf-metadata",
                               "-o", str(pdf), str(sch))
    print(f"  [pdf] rc={rc} → {pdf}")

    # D16 follow-on: even with the three --exclude-pdf-* flags above,
    # KiCad's PDF content stream still emits ~30 Reference / Value /
    # pin-name strings twice as byte-identical `q … Tj … Q` blocks at
    # identical positions. PyMuPDF (and therefore
    # schematic_visual_audit.py) sees each duplicate as a SAME-TEXT
    # identical-bbox overlap pair, even though the text is pixel-
    # perfect overlapping and the human reads it once. Run the
    # `dedupe_pdf_text` post-processor in place to strip the
    # duplicates from the content stream. Visual rendering is
    # unaffected (<0.1 % pixel delta from anti-aliasing on the over-
    # drawn strokes); PyMuPDF then sees each text span once and the
    # strict audit drops by ~30 pairs per sheet.
    import subprocess
    rc_dedupe = subprocess.run(
        [sys.executable,
         str(Path(__file__).parent / "dedupe_pdf_text.py"),
         str(pdf)],
        capture_output=True, text=True
    )
    print(f"  [dedupe] {rc_dedupe.stdout.strip()}")

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
