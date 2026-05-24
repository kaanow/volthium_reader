# CP3 review packet — PCB placement

**Status**: ready for review (iteration 1 — approach)
**Opened**: 2026-05-24
**Branch**: `hw/cp3-placement`
**Goal of this CP**: produce KiCad 10 `.kicad_pcb` files for both
boards with every footprint placed (no routing yet), DRC clean for
"placement only" (track-not-routed warnings expected and suppressed),
top + bottom PNG renders for visual review, and a placement strategy
that respects the constraints in
[`cp1_battery_side.md` §11`](../layout/cp1_battery_side.md#11-layout-strategy)
and [`cp1_display_side.md` §10](../layout/cp1_display_side.md#10-layout-strategy).

## 1. What CP2 handed us

71 components across two ERC-clean schematics + netlist exports
under `hardware/outputs/{battery,display}_side/`. Every symbol has a
`Footprint` field naming a KiCad library footprint (e.g.
`Resistor_SMD:R_0805_2012Metric`). The netlists are the wire-list
for the PCBs.

## 2. The approach for CP3

**Source of truth**: `hardware/kicad/<board>/<board>.kicad_pcb`
files. Per [`decisions.md` D1](../layout/decisions.md#d1).

**Generation method**: extend `hardware/kicad/build_schematics.py`
into `hardware/kicad/build_pcbs.py` (separate script for clarity)
using kiutils to construct each `.kicad_pcb` programmatically:

1. **Board outline** on `Edge.Cuts` layer (60×40 mm battery-side per
   CP1 §2, 85×65 mm display-side per CP1 §2).
2. **Net definitions** populated from the CP2 netlists (every net
   from `battery_side.net` and `display_side.net` ends up in the PCB
   `(net N "name")` table).
3. **Footprint instances**: for every component on the schematic,
   load the matching `.kicad_mod` from KiCad's stock libraries,
   clone it as a Footprint instance on the board, set position,
   orientation, layer (F.Cu / B.Cu), and tie its pads to the right
   nets.
4. **Net classes**: per CP1 §11.3 net-class table — track widths
   and clearances for Power-24V, Power-12V, Power-3V3,
   Default-sig, RS485-diff.
5. **DRC** via `kicad-cli pcb drc`. Expected violations: unrouted
   tracks (CP4's job). Suppress those for CP3; everything else
   should be clean.
6. **Render** via `kicad-cli pcb render --side top` and
   `--side bottom` → PNG outputs for visual review.

## 3. Footprint resolution strategy

Every CP2 schematic symbol has a `Footprint` field with a libId of
form `<lib>:<footprint>` (e.g. `Capacitor_SMD:C_0805_2012Metric`).
KiCad's stock footprint libraries live at
`/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/`.

For each libId in CP2:
1. Look up the `.kicad_mod` file at
   `<KiCad>/footprints/<lib>.pretty/<footprint>.kicad_mod`.
2. Load via `kiutils.footprint.Footprint.from_file()`.
3. Clone, set per-instance properties (Reference designator,
   position, orientation, layer), and append to the board.

**Risk**: a few footprints from CP2 may not exist in stock libs
(e.g. `Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT`,
`Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal`).
Sub-task at iter 3 start: audit footprint availability, hand-author
any missing ones into `hardware/kicad/libraries/volthium.pretty/`
(same project-local pattern as the symbol library).

## 4. Placement strategy (per CP1 §11)

### Battery-side (60×40 mm)

```
┌────────────────────────────────────────────────────────────┐
│ J1│F1│D1│TVS1│  U1 L1 C1 C2 C_BST  │  U2 C3 C4            │  power row
│   │  │  │    │                      │                       │
│  Q1 Q2 R3 R4 (hard-cut)             │                       │
│                                                              │
│       R5 R6 C5 (sense)                                       │
│                                                              │
│              MOD1 (ESP32-S3) — antenna keepout 15×6 mm      │
│              C6 C7 C8 R7                                     │
│                                                              │
│   RTC1 BAT1 R8 R9 C9   │   U3 R10 R11 R12 TVS2 C10 │  J2   │
│                         │                              │  RJ45 │
│   BTN1 R13 C11          │                              │       │
│                                                              │
│                                          J3 J5 (dev hdrs)   │
└────────────────────────────────────────────────────────────┘
              ↑ M3 hole         ↑ M3 hole
              (corners at (3,3), (57,3), (3,37), (57,37))
```

Per CP1 §11.2 priorities:
1. Antenna keepout — MOD1 corner at board edge, 15×6 mm no-copper
2. U1 / L1 / C1 / C2 switching loop ≤ 10 mm sides
3. Sense divider on bottom layer, opposite from L1
4. U3 + J2 (RJ45) at board edge with copper-pour shield drain
5. Hard-cut MOSFETs near regulators they control
6. RTC1 near MOD1, away from L1
7. High-current path V24_RAW → F1 → D1 → V24_FUSED continuous fat copper

### Display-side (85×65 mm)

```
┌──────────────────────────────────────────────────────────────┐
│ J1│F1│TVS1│C1│  U1 (R-78E3.3) C2 │ U2 (RS-485) + R/C +TVS2 │
│   │  │    │  │                    │                          │
│                                                                │
│    MOD1 (ESP32-S3) — antenna keepout 15×6 mm                  │
│    C3 C4 C5 R1                                                 │
│                                                                │
│    J2 (24-pin FFC) on long edge — e-paper folds over          │
│    (FFC oriented so panel ribbon bends only 90°)              │
│                                                                │
│    C6                                                           │
│                                                                │
│  J3 J4 (dev hdrs)               BTN1   BTN2   BTN3            │
│                                  ↑      ↑      ↑               │
│                                 18mm  18mm  18mm centers       │
│                              (bottom edge for faceplate access) │
└──────────────────────────────────────────────────────────────┘
              ↑ M3 corner mounting holes
```

Per CP1 display-side §10.2 priorities:
1. J2 FFC on long edge (top of board)
2. Buttons on bottom edge, 18 mm centers
3. ESP antenna away from e-paper (panel has metal back layer)
4. U1 (Recom SIP3) on B.Cu side (taller) — doesn't push into panel
5. RJ45 on a short edge (back of double-gang box)

## 5. Smoke test (CP3 iter 1)

Toolchain validation — write a tiny `.kicad_pcb` programmatically:
- Empty board, 50×30 mm outline
- ONE 0805 resistor placed at (25, 15)
- Two pads, two nets ("RAW" and "GND")
- `kicad-cli pcb upgrade` to KiCad 10 format
- `kicad-cli pcb drc` — expect no errors / minor warnings
- `kicad-cli pcb render --side top` → PNG

This proves end-to-end before committing to ~70 footprint placements.

## 6. Proposed iteration sequence

| Iter   | Scope                                                     | Deliverable |
|--------|-----------------------------------------------------------|-------------|
| 1 (this) | Approach review + scaffolding + smoke test            | This packet + empty `.kicad_pcb` files with outlines + smoke-test render |
| 3      | Footprint audit (validate every CP2 Footprint exists in KiCad libs or hand-author) | volthium.pretty/ with any missing footprints |
| 5      | Battery-side: power-input cluster placement (J1/F1/D1/TVS1, U1/L1/C1/C2/C_BST, U2/C3/C4, sense divider R5/R6/C5) | Partial PCB with ~13 footprints placed; top/bottom renders |
| 7      | Battery-side: hard-cut + MCU + support (Q1/Q2/R3/R4, MOD1/R7/C6/C7/C8) | More footprints; render |
| 9      | Battery-side: RTC + RS-485 + button + connectors (RTC1/BAT1/R8/R9/C9, U3/R10-12/TVS2/C10, BTN1/R13/C11, J2/J3/J5) | Battery-side placement complete |
| 11     | Display-side: full placement (smaller board, ~30 fps)    | Display-side placement complete |
| 13     | Net classes + final renders + DRC review                 | CP3 close |

Roughly 7 iters for CP3 (placement is much more visual + per-board than CP2's schematic capture).

## 7. Open questions for Codex

### Q-CP3-1: Programmatic vs GUI placement?

Same question as CP2 Q-CP2-1, but for PCB placement. Default:
**programmatic via kiutils** because (a) this session is GUI-less,
(b) reproducible Python beats manual drag-and-drop for diff review,
(c) we already proved kiutils works for schematics.

Tradeoff: visual placement aesthetics are worse (KiCad's GUI has
nice auto-placement and clearance checking; programmatic placement
is dumb). For a hand-soldered prototype this is acceptable; CP3
output is "valid floorplan" not "production-grade layout."

If Codex prefers GUI-driven placement (user opens KiCad, drags
footprints, saves, commits), I can switch — but the user has no
schedule to do that work, and they've delegated this.

### Q-CP3-2: Custom footprint authoring

A few CP2 footprints may not be in KiCad's stock libs. Plan: audit
at iter 3, hand-author the missing ones (most are simple — 3-pin
SIP for Recom, RJ45 modular jack with shield pads, 24-pin 0.5 mm
FFC). Put in `hardware/kicad/libraries/volthium.pretty/`.

If Codex disagrees with the project-local-library pattern for
footprints (different from symbols where I did this), say so.
Default: same pattern as symbols.

### Q-CP3-3: Net classes — committed at iter 1 or later?

CP1 §11.3 specifies net classes (Power-24V 1.0 mm, Power-12V 0.5 mm,
Power-3V3 0.4 mm, Default sig 0.20 mm, RS485-diff 0.25 mm pair).
Should net classes go into the `.kicad_pcb` now (during scaffolding)
or land at iter 13 (alongside final render)?

Default: scaffolding now. Net classes are static board-level config;
no reason to defer.

### Q-CP3-4: Antenna keepout — visual marker vs courtyard exclusion?

The ESP32-S3-WROOM-1 needs a 15×6 mm no-copper-no-track area.
Options:
- (a) Add a keepout zone (KiCad zone with "keep out copper" rule)
- (b) Just place the module so the antenna sticks off the board edge

Default: **(b) — place antenna over board edge**. Simpler, no zone
required, visually unambiguous. The MOD1 instance's RIGHT edge will
extend past the board's RIGHT edge by 6 mm.

### Q-CP3-5: M3 mounting holes — drill spec

CP1 specifies 4× M3 corner holes at (3, 3), (57, 3), (3, 37),
(57, 37) for battery-side; similar for display-side at (4, 4),
(81, 4), (4, 61), (81, 61). KiCad's `MountingHole_3.2mm` footprint
or just a drilled hole?

Default: `MountingHole_3.2mm` (standard 3.2 mm drill for M3
clearance fit) from the stock `MountingHole.pretty` library.

## 8. Success criteria (CP3 overall)

- [ ] `hardware/kicad/battery_side/battery_side.kicad_pcb` exists with
      all 41 footprints placed and board outline drawn
- [ ] `hardware/kicad/display_side/display_side.kicad_pcb` exists with
      all 30 footprints placed and board outline drawn
- [ ] `kicad-cli pcb drc` reports 0 errors (warnings limited to
      "unrouted tracks" which is CP4's job)
- [ ] Top + bottom PNG renders committed to
      `hardware/outputs/<board>/render_{top,bot}.png`
- [ ] Antenna keepout visible on top render for both boards
- [ ] Mounting holes present and dimensioned per CP1
- [ ] FFC pin assignments verified against Waveshare 4.2" e-Paper
      (B) v2 panel datasheet (Q-CP2-13 / Q-CP3-NEW)
- [ ] Net classes configured per CP1 §11.3

## 9. What this CP does NOT settle

- Routing (CP4)
- Copper pours / ground planes (CP4)
- Gerbers + drill + position files + assembly drawing (CP5)
- 3D model exports for the user's faceplate work (CP5)
- Final BOM SKU verification (CP5)

## 10. Reviewer findings (append-only)

*(append per the format in REVIEWER.md §5)*
