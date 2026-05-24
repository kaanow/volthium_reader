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

**Project-local cache, mirroring the CP2 symbol-library pattern.**

Every CP2 schematic symbol has a `Footprint` field with a libId of
form `<lib>:<footprint>` (e.g. `Capacitor_SMD:C_0805_2012Metric`).
For PCB generation we resolve those names from a committed,
project-local directory — not from the host KiCad install — so
that anyone with this repo + `.venv` can re-generate the PCBs on
any machine.

Layout:

```
hardware/kicad/
├── libraries/
│   ├── volthium.kicad_sym         (CP2 — symbols, committed)
│   └── volthium.pretty/           (CP3 — footprint cache, committed)
│       ├── R_0805_2012Metric.kicad_mod
│       ├── C_0805_2012Metric.kicad_mod
│       └── …
└── <board>/
    ├── fp-lib-table               (per-project: points at volthium.pretty)
    └── <board>.kicad_pcb          (libId uses "volthium" nickname)
```

`build_pcbs.py` resolves footprints by name from `volthium.pretty/`
only. It refuses to fall back to the host KiCad tree, so a missing
footprint produces a clear error pointing at `--rebuild-footprints`.

Refreshing the cache (opt-in, runs against host KiCad):

```
.venv/bin/python hardware/kicad/build_pcbs.py --rebuild-footprints
```

That flag — and only that flag — touches
`/Applications/KiCad/.../footprints` (or the equivalent on Linux).
It copies each `.kicad_mod` from `STOCK_FOOTPRINTS` (a curated list
in `build_pcbs.py`) into `volthium.pretty/`. Committing the cache
means the next builder doesn't need KiCad at all to generate the
boards (KiCad is still required to run kicad-cli / GUI, just not for
python-side resolution).

Each board's project directory ships a small `fp-lib-table` so
KiCad's GUI and `kicad-cli pcb drc` know how to find the `volthium`
nickname:

```
(fp_lib_table
  (version 7)
  (lib (name "volthium")(type "KiCad")
       (uri "${KIPRJMOD}/../libraries/volthium.pretty")
       (options "")(descr "Project-local footprint cache (CP3+)"))
)
```

For each libId referenced in CP2:
1. Resolve `<fp>` to `hardware/kicad/libraries/volthium.pretty/<fp>.kicad_mod`.
2. Load via `kiutils.footprint.Footprint.from_file()`.
3. Set `libraryNickname="volthium"` and `libId="volthium:<fp>"` on
   the instance.
4. Set position, orientation, layer; tie pads to nets.
5. Append to the board.

**Audit task (still open at iter 3)**: walk every Footprint field
in CP2's `battery_side.net` + `display_side.net`, populate
`STOCK_FOOTPRINTS`, and run `--rebuild-footprints` once to seed
the cache. A handful (e.g.
`Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT`,
`Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal`)
may not exist in stock libs — those get hand-authored as new
`.kicad_mod` files committed straight into `volthium.pretty/`.

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

## 5. Smoke test (CP3 iter 1 + 2)

Toolchain validation — write a tiny `.kicad_pcb` programmatically:
- Empty board, 50×30 mm outline
- ONE 0805 resistor placed at (25, 15)
- Two pads, two nets ("RAW" and "GND")
- `kicad-cli pcb upgrade` to KiCad 10 format
- `kicad-cli pcb drc` — expect no errors / minor warnings
- `kicad-cli pcb render --side top` → PNG

**Iter 2 update**: smoke test now uses the project-local
`volthium.pretty/` cache (no host-path dependency). Generation:

```
.venv/bin/python hardware/kicad/build_pcbs.py            # builds from cache
kicad-cli pcb upgrade hardware/kicad/_smoke/smoke.kicad_pcb
kicad-cli pcb drc --severity-error --severity-warning hardware/kicad/_smoke/smoke.kicad_pcb
```

Output: 3 silk-overlap warnings (cosmetic; REF** placeholder will be
overridden in real placement), 0 errors, 0 unconnected pads, 0
footprint errors. The `lib_footprint_issues` warning that briefly
appeared after switching libIds to the `volthium` nickname was
resolved by adding `hardware/kicad/_smoke/fp-lib-table`.

This proves end-to-end before committing to ~70 footprint placements,
**and** validates that the project-local resolution path works end
to end with no fallback to the host KiCad tree.

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

---

## 10.1 Reviewer findings (iteration 1)

### Finding 01 — IMPORTANT — `cp3_placement.md`:§3 footprint resolution strategy
**Issue**: The proposed footprint-loading flow is still host-install dependent via a hardcoded macOS KiCad footprint path, which breaks cross-machine reproducibility just as in early CP2.
**Evidence**: §3 points footprint lookup at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/` and describes loading `.kicad_mod` files directly from that tree on each run.
**Suggested fix**: Mirror the CP2 symbol-library pattern for footprints: resolve from project-local `volthium.pretty` + committed KiCad footprint-table entries by default, and gate host-library extraction behind an explicit opt-in rebuild mode (with clear failure messaging when host libs are absent).

Re-review notes:
- Smoke-test evidence is valid: DRC on `hardware/kicad/_smoke/smoke.kicad_pcb` reports only the documented three silkscreen warnings and no unconnected items.
- Q-CP3-1: programmatic placement is acceptable for CP3 in this workflow.
- Q-CP3-3: net classes should land in scaffolding early (iter 1/3), not deferred to CP3 close.
- Q-CP3-4 and Q-CP3-5 defaults are acceptable (antenna over-edge placement and `MountingHole_3.2mm`).

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See findings N1, N2, ...)

---

## 10.2 Designer response (iteration 2)

### Response to Finding 01 — IMPORTANT — Footprint resolution: ACCEPTED, implemented

Agreed in full. The host-path lookup in §3 was a sloppy carryover
from initial exploration; it should have been a project-local cache
from the start (matching what we did for symbols in CP2). Fixed in
this iter:

- New script `hardware/kicad/build_pcbs.py` resolves footprints
  exclusively from `hardware/kicad/libraries/volthium.pretty/`.
  Never reads host KiCad paths during normal builds.
- `--rebuild-footprints` flag is the **only** code path that touches
  the host KiCad footprint tree. It extracts a curated
  `STOCK_FOOTPRINTS` list into the project cache; safe to commit the
  resulting `.kicad_mod` files.
- Cache seeded with `R_0805_2012Metric.kicad_mod` (smoke test's only
  footprint). Full audit + cache population of all CP2 footprints is
  the planned start-of-iter-3 work.
- Smoke `.kicad_pcb` now uses `libId = volthium:R_0805_2012Metric`.
- Added `hardware/kicad/_smoke/fp-lib-table` declaring the
  `volthium` nickname → `${KIPRJMOD}/../libraries/volthium.pretty`.
  This pattern will repeat in each real board's project directory
  at iter 3.
- §3 of this packet rewritten to describe the project-local cache
  + opt-in rebuild flow.

Verification: re-ran `.venv/bin/python hardware/kicad/build_pcbs.py`
without any --rebuild flag, then `kicad-cli pcb drc`. Result:

```
Found 3 violations          ← 3 silk-overlap warnings (cosmetic)
Found 0 unconnected items
Found 0 Footprint errors
```

The transient `lib_footprint_issues` warning that appeared
immediately after the libId rename was resolved by the new
fp-lib-table.

### Re-review acks (no action needed)

- Q-CP3-1 (programmatic placement): acknowledged accepted.
- Q-CP3-3 (net classes in scaffolding): acknowledged accepted; will
  land in the scaffolding step at iter 3 (battery_side / display_side
  project directories) — net-class definitions per CP1 §11.3 go into
  the `.kicad_pro` `boards.design_settings.rules.classes` block at
  the same time the `.kicad_pcb` files are first written.
- Q-CP3-4 (antenna over-edge): acknowledged accepted, will document
  MOD1 position in iter 7 placement.
- Q-CP3-5 (MountingHole_3.2mm): acknowledged accepted, will be on
  the iter-3 footprint audit list.

### Handing back

State → `codex_turn`, iter 3. Recommend Codex re-verify:
- `hardware/kicad/build_pcbs.py` does not read any
  `/Applications/KiCad` / `/usr/share/kicad` path during a default
  build (it should only do so under `--rebuild-footprints`).
- `hardware/kicad/_smoke/smoke.kicad_pcb` libId is
  `volthium:R_0805_2012Metric`, not the original `Resistor_SMD:...`.
- DRC re-runs cleanly with no `lib_footprint_issues`.

If satisfied, mark Finding 01 resolved and APPROVE the CP3 approach
so iter-3 can start the real footprint audit + battery-side power
cluster placement.

---

## 10.3 Reviewer findings (iteration 3)

*(Codex re-review of iter 2 — APPROVED, see SEMAPHORE note. Inlining
here for completeness.)*

- Finding 01 verified resolved: `build_pcbs.py` default path reads
  only from `volthium.pretty/`; host extraction gated on
  `--rebuild-footprints`.
- Smoke PCB libId is `volthium:R_0805_2012Metric`; fp-lib-table
  resolves the `volthium` nickname.
- DRC: 3 silk warnings, 0 unconnected pads, 0 footprint errors.

**REVIEW COMPLETE**: APPROVED.

---

## 10.4 Designer iter 4 — footprint audit + cache population

**Scope**: walk CP2 netlists, enumerate every Footprint field, audit
against KiCad 10 stock libraries, fix mismatches at the schematic
source, populate the project-local `volthium.pretty/` cache.

### Audit results

23 unique Footprint references across both boards. 17 matched
KiCad stock directly. 6 did not match — diagnosis below.

| # | Original libId | Diagnosis | Resolution |
|---|----------------|-----------|------------|
| 1 | `Package_SO:SOT-23-6` | Wrong library namespace | Moved to `Package_TO_SOT_SMD:SOT-23-6` |
| 2 | `RF_Module:ESP32-S2-WROOM-1` | Typo (S2 vs S3) | Changed to `RF_Module:ESP32-S3-WROOM-1` |
| 3 | `Battery:BatteryHolder_Keystone_1066_1x12mm` | 1066 not in KiCad libs | Switched to `Battery:BatteryHolder_Keystone_1057_1x2032` (same Keystone CR2032 holder family) |
| 4 | `Button_Switch_SMD:SW_SPST_TL3300` | TL3300 not in KiCad libs | Switched to `Button_Switch_SMD:SW_SPST_B3S-1000` (Omron B3S — common 6×6mm tactile, hand-solderable) |
| 5 | `Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT` | KiCad ships only the 0.5A variant footprint; R-78E body is mechanically identical across current ratings | Switched to `Converter_DCDC_RECOM_R-78E-0.5_THT` (BOM MPN R-78E12-1.0 still carried in Value field) |
| 6 | `Fuse:Fuse_Bel_5MF` | Bel "5MF" series name not in KiCad; KiCad has the canonical Bel FC-203-22 clip | Switched to `Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal` |

All 6 fixes were applied at the source — `STOCK_SYMBOLS` Footprint
fields in `build_schematics.py`. Schematics regenerated, ERC still
0 / 0 / 0 on both boards.

### After fixes

After re-running the schematic build pass, the audit shows 22
unique footprints (one libId collapsed because R-78E-0.5_THT is now
shared by both Recom modules). **22 / 22 hit KiCad stock libraries.
Zero hand-authored footprints needed.**

### Cache population

```
.venv/bin/python hardware/kicad/build_pcbs.py --rebuild-footprints
→ rebuilt 22 footprint(s) into hardware/kicad/libraries/volthium.pretty/
```

The cache now contains every `.kicad_mod` referenced by either
board. Committed to the branch.

### Per-component disposition

```
battery-side (41 components → 13 distinct footprints used):
  J1   TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal
  F1   Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral
  D1   D_SMA
  TVS1 D_SMA
  U1   SOT-23-6        (TPS62933)
  L1   L_0805_2012Metric
  C1/C2/C3/C4   C_1210_3225Metric  (10µF X7R 50V)
  C_BST (not in netlist — bootstrap of U1, integrated in TPS62933 schematic)
  U2   Converter_DCDC_RECOM_R-78E-0.5_THT  (R-78E12-1.0)
  Q1/Q2 SOT-23          (AO3401A / AO3400A — both 3-pin)
  MOD1 ESP32-S3-WROOM-1
  R*   R_0805_2012Metric  (×13 instances)
  C5/C8/C9/C10/C11/C12/C13/C14   C_0603_1608Metric
  C6   C_0805_2012Metric
  C7   C_0402_1005Metric
  RTC1 SOIC-16W_7.5x10.3mm_P1.27mm  (DS3231M)
  BAT1 BatteryHolder_Keystone_1057_1x2032
  BTN1 SW_PUSH_6mm      (THT 6mm momentary)
  U3   SOIC-8_3.9x4.9mm_P1.27mm  (RS-485 transceiver)
  TVS2 D_SMA
  J2   RJ45_Amphenol_RJHSE5380
  J3/J5 PinHeader_1x04_P2.54mm_Vertical

display-side (30 components → ~12 distinct footprints):
  J1   RJ45_Amphenol_RJHSE5380
  F1   R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal  (resettable polyfuse THT)
  TVS1/TVS2 D_SMA
  C1   C_1210_3225Metric
  U1   Converter_DCDC_RECOM_R-78E-0.5_THT  (3V3 0.5A)
  C2/C3 C_0805_2012Metric
  U2   SOIC-8_3.9x4.9mm_P1.27mm  (RS-485)
  C4   C_0402_1005Metric
  R*   R_0805_2012Metric  (×5 instances)
  C5/C6   C_0603_1608Metric  (×4 instances)
  MOD1 ESP32-S3-WROOM-1
  J2   Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal  (FFC)
  BTN1/2/3 SW_SPST_B3S-1000  (SMD tactile)
  J3/J4 PinHeader_1x04_P2.54mm_Vertical
```

### Verification commands

```
.venv/bin/python hardware/kicad/build_schematics.py        # regen schematics + nets (ERC 0/0)
.venv/bin/python hardware/kicad/build_pcbs.py --rebuild-footprints  # repopulate cache
ls hardware/kicad/libraries/volthium.pretty/ | wc -l       # → 22
```

### Handing back

State → `codex_turn`, iter 5. Recommend Codex re-verify:
- All 22 cached `.kicad_mod` files match the names in
  `STOCK_FOOTPRINTS`.
- Netlist footprints now reference only names that exist in the
  cache (no orphan refs).
- Schematic regen still produces 0 / 0 / 0 ERC on both boards.
- The 6 footprint corrections in this iter don't change net
  topology (they're metadata strings only, not pin connections) —
  spot-check by diffing battery_side.net + display_side.net
  before/after this commit's `.net` files (only the
  `(footprint ...)` strings should differ; refs/pins/nets stable).

Next deliverable (iter 6 if Codex approves): begin actual PCB
generation for battery-side power-input cluster
(J1 / F1 / D1 / TVS1 / U1 / L1 / Cs / U2 / sense divider) with
real (x, y) coordinates from §4 ASCII floorplan.

---

## 10.3 Reviewer findings (iteration 2)

No new findings.

Re-review results:
- Finding 01 is resolved: `build_pcbs.py` default flow resolves footprints only from project-local `hardware/kicad/libraries/volthium.pretty/`, and host KiCad path access is gated behind explicit `--rebuild-footprints`.
- `hardware/kicad/_smoke/smoke.kicad_pcb` now uses project-local libId `volthium:R_0805_2012Metric`, with matching `_smoke/fp-lib-table` entry.
- Independent smoke DRC re-run remains consistent with the packet claims: 3 silkscreen-only warnings, 0 unconnected pads, and 0 footprint errors (no `lib_footprint_issues`).
- Q-CP3-2 project-local footprint library pattern is accepted; proceed with iter-3 full footprint audit/cache population and battery-side power-cluster placement.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

---

## 10.5 Reviewer findings (iteration 3)

No new findings.

Re-review results:
- Footprint cache is coherent: `STOCK_FOOTPRINTS` enumerates 22 entries and `hardware/kicad/libraries/volthium.pretty/` contains exactly those 22 `.kicad_mod` files (no missing or extra cache files).
- Regenerated netlists reference only cached footprint names (no orphan footprint refs) for both `hardware/outputs/battery_side/battery_side.net` and `hardware/outputs/display_side/display_side.net`.
- Independent ERC rerun remains clean (`0 errors, 0 warnings`) on both schematics after the footprint metadata corrections.
- Net topology is unchanged versus the prior Codex-approved baseline (`e8d45d0`): no added/removed/changed nets in either board netlist, confirming the iter-4 edits are metadata-only as intended.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).
