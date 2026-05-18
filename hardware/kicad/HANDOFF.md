# HANDOFF — KiCad work on a different machine

> **You are a future Claude session.** The user has brought this repo over
> to a machine with KiCad installed (or about to install). Your job is to
> finish the PCB design by following this runbook. The user will do a
> final inspection but expects most/all work done autonomously. Don't
> guess; if something doesn't work, debug it the same way you'd debug
> code — with explicit checks, not assumptions.
>
> This document is the source of truth for the workflow. Update it as you
> learn things (e.g. "Recom didn't have a stock symbol; pulled from vendor
> lib at <url>") so the *next* iteration has more context than you did.

## TL;DR for the user (if they're reading)

Two boards are designed as SKiDL Python. Run `./run.sh` from
`hardware/kicad/` to regenerate KiCad netlists from Python. Open the
netlists in KiCad PCB Editor, lay out, route, export Gerbers. The
schematic-level docs (`docs/hardware/schematic_*_side.md`) and the
symbol/footprint map (`symbol_footprint_map.md`) are the engineering
intent — KiCad files are build output.

## Working environment (verify first)

```bash
# Verify KiCad is on the system
kicad-cli version    # expect 8.x or higher

# Verify the project venv exists and has skidl
cd <repo-root>
.venv/bin/python -c "import skidl; print(skidl.__version__)"   # expect 2.2.3+

# If venv is missing (fresh machine):
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-hw.txt
```

If `python3.13` isn't available, install python.org's Python 3.13 or 3.14
(per `memory/macos_bluetooth_tcc.md` notes on the original Mac).

## Stage 1 — Regenerate netlists

```bash
cd hardware/kicad
./run.sh
```

Expected outputs:
- `outputs/battery_side.net`
- `outputs/display_side.net`

Inspect the run output. SKiDL will emit warnings for any symbol/footprint
references it couldn't resolve. **Fix all such warnings before moving
on.** Reference `symbol_footprint_map.md` for the expected symbol names
and substitution strategies.

### If the run hangs or errors

- **Missing KiCad symbol library env vars**: `run.sh` autodetects on
  macOS at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols`.
  On Linux/Windows you may need to set `KICAD8_SYMBOL_DIR` manually.
- **"ERC violations"**: read SKiDL's complaint, find the offending net
  in the Python source, fix the connection logic.
- **Mismatched pin counts**: usually means the KiCad symbol on your
  machine has more/fewer pins than I expected when writing the SKiDL.
  Open the symbol in KiCad and edit the SKiDL to use the correct pin
  numbers/names.

## Stage 2 — Create KiCad projects

For each board, create a KiCad project that imports the netlist:

```bash
cd hardware/kicad/outputs
mkdir -p ../projects/battery_side ../projects/display_side

# KiCad 8 way: use the CLI to scaffold a project, then import netlist.
# Manual GUI steps below — the CLI doesn't fully support netlist import
# without an existing PCB.
```

**Manual KiCad GUI steps (first time only):**

1. Open KiCad → New → Project. Save at
   `hardware/kicad/projects/battery_side/battery_side.kicad_pro`.
2. Open the PCB Editor (Pcbnew).
3. File → Import → Netlist…
4. Browse to `../outputs/battery_side.net`. Use "Replace footprints with
   those specified in netlist" if asked. Confirm.
5. Pcbnew shows all the footprints stacked at origin — drag them into a
   rough layout (see "Layout hints" below).
6. Repeat for `display_side`.

After this first manual scaffold, future regenerations of the netlist
can be re-imported with File → Import → Netlist, choosing "Update PCB
from netlist" to apply changes.

## Stage 3 — Place footprints

Goals:
- **Battery side**: fit in a 60×38 mm board outline (Hammond 1556B2GY
  internal area is 64×42 mm; leave margin for the standoffs).
- **Display side**: fit in ~85×60 mm; the e-paper FFC (J3) on the long
  edge so the panel folds back over the PCB.

### Battery-side placement

```
       ┌──────────────────────────────────────────┐
       │   J2 [24V tap]    F1    D1   TVS3        │  <- left edge: power input
       │     ◯◯           [ ]   ▶│    ‖           │
       │                                            │
       │   U2 (R-78E12)     U1 (TPS62933+L1)       │  <- DC/DC regs
       │   ┌──────┐        ┌──┐  ⌃                 │
       │   │      │        │  │  L1                │
       │   └──────┘        └──┘                    │
       │                                            │
       │   Q1   Q2          RTC1 (DS3231)           │
       │  [P][N]            ┌────────┐              │
       │   sw                │ SOIC16 │              │
       │                    └────────┘              │
       │   BAT1                                     │
       │  [coin]              MOD1                  │
       │                     ┌──────────┐           │
       │                     │ ESP32-S3 │           │
       │                     │ WROOM-1  │           │
       │                     │   ANT--► │ <- antenna at edge, no copper behind
       │                     └──────────┘           │
       │                                            │
       │   BTN1   LED1   U3 (RS-485)    J1 [RJ45]   │  <- right edge: user/IO
       │  [butn] [LED] ┌──────┐         ◯◯◯◯◯◯◯◯    │
       │                │ SOIC8│         (8-pin)    │
       │                └──────┘                    │
       └──────────────────────────────────────────┘
```

Layout rules of thumb (in priority order):

1. **Antenna keepout**: ESP32-S3-WROOM-1 antenna corner needs 15 mm of
   no-copper, no-traces behind it. Place that corner at the board edge.
2. **Switching reg loops compact**: U1, L1, C_u1_in, C_u1_out should
   form a tight loop. Put them within ~10 mm of each other.
3. **Cap close to MCU**: C_esp_decoupling (100 nF) within 3 mm of the
   ESP module's VDD pin.
4. **High-current paths short**: V24_RAW → F1 → D1 → V24_FUSED → U1/U2
   should be a fat copper run, not a thin trace.
5. **ESD parts at IO edge**: TVS1 between J1 and U3 (RS-485 transceiver).
6. **RTC near MCU, not near switching reg**: minimize I²C trace length;
   minimize switching-noise coupling to the RTC crystal.

### Display-side placement

```
   ┌─────────────────────────────────────────────────┐
   │ J3 [24-pin FFC, e-paper]  ── on this long edge ──│
   │ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                        │
   │                                                  │
   │            MOD2                                  │
   │           ┌──────────┐                           │
   │           │ ESP32-S3 │                           │
   │           │ WROOM-1  │                           │
   │           │  ANT --► │ <- antenna at this edge   │
   │           └──────────┘                           │
   │                                                  │
   │ U10 (R-78E3.3)    U11 (RS-485)                  │
   │ ┌──────┐          ┌──────┐                       │
   │ │ SIP3 │          │ SOIC8│                       │
   │ └──────┘          └──────┘                       │
   │                                                  │
   │  F2 TVS3                  TVS4   J11 [RJ45]      │
   │ [PTC][▶│]                  [▶│]   ◯◯◯◯◯◯◯◯       │
   │                                                  │
   │   BTN10  BTN11  BTN12       LED1                 │
   │   [   ]  [   ]  [   ]        ☆                   │
   └─────────────────────────────────────────────────┘
       (bottom edge — buttons accessible behind wall plate)
```

Layout rules:

1. e-paper FFC on the long edge so the panel sits flat behind it.
2. Buttons on the opposite edge (bottom in the diagram), spaced ≥15 mm
   apart so the wall plate can have separate cap holes.
3. ESP antenna pointing away from the e-paper (the panel has a metal
   back layer that reflects RF).
4. RJ45 (J11) on a short edge, accessible from the side or back of the
   wall-mount cavity.

## Stage 4 — Route

Routing target: 2-layer board, both. We have low signal counts and low
currents — no need to go to 4 layers.

Net classes / track widths:

| Class       | Width | Clearance | Nets                                      |
|-------------|-------|-----------|-------------------------------------------|
| Power-24V   | 1.0 mm| 0.3 mm    | V24_RAW, V24_FUSED, V24_SW                 |
| Power-12V   | 0.5 mm| 0.25 mm   | V12_CAT5E (battery side), V12_PROT (display) |
| Power-3V3   | 0.4 mm| 0.2 mm    | V3V3_*, GND                               |
| Default sig | 0.2 mm| 0.15 mm   | UART, I²C, SPI, buttons, ADC, GPIO        |
| RS485-diff  | 0.25 mm| 0.2 mm   | RS485_A, RS485_B (route as a pair, equal-length) |

Notes:
- **GND pour both layers** with stitching vias every ~10 mm. The 24V
  switching regulator needs a contiguous ground reference under it.
- **RS-485 differential pair**: route A and B parallel, equal length,
  through the same vias if any. Keep the pair away from switching noise
  (i.e. not directly under L1).
- **ADC trace (V24_SENSE)**: short and away from switching. The 100 nF
  filter cap should sit right at the ESP32 GPIO1 pin.

## Stage 5 — DRC, then Gerbers

```bash
# After laying out + routing in KiCad GUI, run DRC. From the GUI:
#   Tools → DRC → Run DRC

# Then headless export of Gerbers:
cd hardware/kicad
mkdir -p outputs/battery_side_gerbers outputs/display_side_gerbers

kicad-cli pcb export gerbers \
    --output outputs/battery_side_gerbers \
    projects/battery_side/battery_side.kicad_pcb

kicad-cli pcb export drill \
    --output outputs/battery_side_gerbers \
    projects/battery_side/battery_side.kicad_pcb

# Same for display_side.
```

The resulting `outputs/*_gerbers/` directories are what you'd zip up
and send to JLCPCB / OSH Park / PCBWay.

## Stage 6 — Render previews

For human (and Claude) review without opening KiCad GUI:

```bash
# Render schematic to PDF
kicad-cli sch export pdf \
    --output outputs/battery_side_sch.pdf \
    projects/battery_side/battery_side.kicad_sch

# Render PCB to PNG (top + bottom)
kicad-cli pcb render \
    --output outputs/battery_side_top.png \
    --side top --background opaque \
    projects/battery_side/battery_side.kicad_pcb

kicad-cli pcb render \
    --output outputs/battery_side_bottom.png \
    --side bottom --background opaque \
    projects/battery_side/battery_side.kicad_pcb
```

A Claude session can `Read` these PNG/PDF outputs to verify the layout
visually and feed corrections back into the SKiDL source or the
PCB-editor session.

## Stage 7 — BOM cross-check

Before ordering, regenerate the BOM CSV from the schematic and
cross-check against `docs/hardware/bom.md`:

```bash
kicad-cli sch export bom \
    --output outputs/battery_side_bom.csv \
    projects/battery_side/battery_side.kicad_sch
```

Open the CSV; for each row verify:
- The Manufacturer Part Number matches `docs/hardware/bom.md`.
- The package matches the chosen footprint.
- Quantity matches.

Any mismatches → update either the SKiDL (if the part choice was wrong)
or the bom.md (if the choice is correct but the doc is stale).

## What to deliver back to the user

When done, the repo should have:

```
hardware/kicad/
├── HANDOFF.md                          (this file — updated with lessons learned)
├── battery_side.py                     (SKiDL source — only edit if design changes)
├── display_side.py
├── run.sh
├── symbol_footprint_map.md
├── projects/
│   ├── battery_side/
│   │   ├── battery_side.kicad_pro
│   │   ├── battery_side.kicad_sch
│   │   └── battery_side.kicad_pcb
│   └── display_side/
│       ├── display_side.kicad_pro
│       ├── display_side.kicad_sch
│       └── display_side.kicad_pcb
└── outputs/
    ├── battery_side.net               (regeneratable from .py)
    ├── battery_side_sch.pdf
    ├── battery_side_top.png
    ├── battery_side_bottom.png
    ├── battery_side_bom.csv
    ├── battery_side_gerbers/          (the deliverable to the PCB fab)
    │   ├── *.gbr
    │   └── *.drl
    └── (same set for display_side)
```

## Lessons learned / corrections (append-only)

*(future sessions: add a dated entry every time you find something this
HANDOFF doc was wrong about, so the next session has accurate guidance)*

- *(none yet)*

## Final inspection checklist for the user

Hand the user this list when work is "done":

- [ ] `kicad-cli pcb export gerbers` runs without errors for both boards
- [ ] `Tools → DRC` in KiCad PCB editor shows zero errors, zero warnings
       (or all warnings documented as accepted in this file)
- [ ] PDF rendering of each schematic is readable and matches
       `docs/hardware/schematic_*_side.md` net-for-net
- [ ] BOM CSV matches `docs/hardware/bom.md`
- [ ] Antenna keepouts visible on both boards' top render
- [ ] e-paper FFC connector pin numbering matches the panel's datasheet
       (verify pin 1 indication on both ends)
- [ ] Cat5e RJ45 pinout (J1, J11) matches `docs/hardware/cat5e_pinout.md`
- [ ] Board outlines fit the chosen enclosures (Hammond 1556B2GY,
       single-gang low-voltage box)
