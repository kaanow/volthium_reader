# Design decisions log

Every committed design decision lives here with date + rationale. If you
think you remember a decision but it's not in this file, treat it as not
yet decided. New decisions get appended chronologically.

## D1 — Source of truth = KiCad 10 native files

**Date**: 2026-05-23
**Status**: committed

The repository's existing SKiDL Python (`hardware/kicad/{battery,display}_side.py`)
targets KiCad 7/8 symbol/footprint libraries. KiCad 10's S-expression format
has evolved, and `skidl==2.2.3` does not target it cleanly.

**Decision**: `.kicad_pro` / `.kicad_sch` / `.kicad_pcb` are the source of
truth. The SKiDL files are preserved as design-intent reference for
reviewers but are not regenerated from.

**Reason**: avoids spending time wrestling SKiDL into KiCad 10 compatibility
on a project where the design is already specified at schematic-net level
in `docs/hardware/`. Direct authoring via `kiutils` + KiCad GUI is the
shortest path.

## D2 — Fab choice = JLCPCB, qty 5 of each (bare PCB)

**Date**: 2026-05-23
**Status**: committed

User builds 1 of each board; JLCPCB minimum order is 5. Excess units are
spares (handy for prototype rework).

**Decision**: target JLCPCB design rules:
- 2-layer FR-4, 1.6 mm thickness
- HASL or ENIG (HASL default; cheaper)
- Green soldermask, white silkscreen
- Min trace/space: 6 mil (0.152 mm)
- Min drill: 0.3 mm
- Min annular ring: 0.13 mm
- Edge clearance: 0.3 mm
- Hole-to-trace: 0.2 mm

PCB-only ($25–35 incl. DHL); no PCBA service. PCBA setup for qty 1 isn't
economical (~$200/board).

## D3 — Assembly = hand-solder

**Date**: 2026-05-23
**Status**: committed

User-confirmed. Drives part choices toward solderable packages:

- ESP32 module (ESP32-S3-WROOM-1) — not a bare QFN
- SOIC for ICs, not QFN where possible
- 0805 minimum for passives (no 0603/0402)
- Through-hole for connectors and high-current parts
- Pluggable terminal blocks for field-serviceable connections

## D4 — No always-on indicator LEDs

**Date**: 2026-05-23
**Status**: committed

User-explicit: "I don't want the extra draw of an LED at the time the
batteries are low."

**Decision**: no power-on / status LEDs that draw continuously. Indicator
LEDs are permitted ONLY if they draw nothing in idle (e.g. driven from a
GPIO that pulses briefly on demand and is otherwise tri-stated).

**Implication**: alert visibility is delivered via the e-paper (red color
for low-SOC / fault states) and on-screen messaging, not via LEDs.

## D5 — Power-first design ethic

**Date**: 2026-05-23
**Status**: committed

The monitor must trickle the absolute minimum power it can get away with.
This extends D4 to a general rule:

- Touch overlays add ~70–200 µA continuous → rejected (see D6)
- Pull-ups on idle GPIOs bias toward higher resistance (MΩ where the MCU
  input can handle it)
- Regulators: pick parts with sub-µA quiescent current for always-on rails
- The 4-tier SOC self-shutdown (NORMAL / LOW / DEEPSLEEP / HARDCUT) in
  [`docs/production_design.md`](../../docs/production_design.md) is the
  spec, not aspirational — every state must shed every non-essential
  current path
- If "more vibrant" and "lower draw" disagree, lower draw wins

## D6 — Display = 4.2" tri-color BWR e-paper

**Date**: 2026-05-23
**Status**: committed

Considered:
- 4.2" tri-color BWR (Waveshare 4.2 B v2) — chosen
- 4.2" 4-color BWRY (Waveshare 4.2 G) — rejected (~15 s full refresh, no
  partial refresh — broken for button-driven UI)
- 5.83" tri-color — rejected (needs non-standard faceplate, panel doesn't
  fit double-gang outline cleanly)
- Monochrome + RGB LED for alerts — rejected (LED draws power even at LOW
  SOC; conflicts with D4/D5)
- Touch overlay variants — rejected (continuous touch-controller draw)

**Decision**: 4.2" tri-color BWR with **mixed-mode refresh**:
- B&W **partial refresh (~500–700 ms)** for button-press responses and
  countdown updates
- **Color full refresh (~7 s)** on scheduled background tick (30–60 s)
  and on state-change alerts

Refresh policy makes button presses feel responsive while preserving red
for alerts and keeping idle current at zero (e-paper is bistable).

## D7 — User input = 3 tactile buttons on PCB bottom edge

**Date**: 2026-05-23
**Status**: committed

Buttons sit on the PCB along the bottom edge near the display so their
on-screen labels can be rendered directly adjacent (software-defined
function). Originally: dedicated functions ("refresh", "switch screen",
"release BLE"). New model: variable function via on-screen labels.

Power: tactile buttons draw zero in idle, transient only when pressed.

## D8 — Display-side form factor = US double-gang old-work box

**Date**: 2026-05-23
**Status**: committed

The display-side enclosure changed from single-gang to double-gang. PCB
must fit within typical interior dimensions:

| Dimension | Approx                         |
|-----------|--------------------------------|
| Width     | 90 mm usable (≤ 85 mm preferred) |
| Height    | 70 mm usable                   |
| Depth     | 50 mm usable                   |

Faceplate is 3D-printed (custom) to user-supplied dimensions; default
target is a standard double-gang outline (~115 × 117 mm). Cutouts for
display window + button caps designed against the PCB STEP file we
export at CP5.

## D9 — Battery-side power input = on-board screw terminal + 5×20 mm fuse

**Date**: 2026-05-23
**Status**: committed

Original spec: ring terminals → external inline ATO fuse → board. New:
on-board 2-pin pluggable terminal block (Phoenix MSTB-type) + on-board
5×20 mm cartridge fuse in clip.

**Rationale**: cleaner enclosure, no external fuse holder, still
field-serviceable (cartridge fuses pop out of clips). User builds 1; the
small loss in fuse-rating flexibility doesn't matter.

**BOM delta from `docs/hardware/bom.md`**:
- Remove: 1 A ATO fast-blow fuse + inline holder; ring terminals
- Add: 2-pin 5.08 mm pitch pluggable terminal block (Phoenix MSTB 2,5/2-G-5,08
  or equivalent); 5×20 mm cartridge fuse (1 A fast-blow); PCB-mount fuse clip
  (2× for the two ends of the cartridge)

## D10 — Battery-side form factor = unconstrained

**Date**: 2026-05-23
**Status**: committed

The battery-side board mounts to the wall near the batteries with no fixed
enclosure constraint. We target a small board (~60 × 40 mm) sized to fit a
generic IP65 project box (e.g. Hammond 1591ATBU or similar) and mount with
4 corner standoffs. User can swap enclosures freely.

## D11 — All committed documentation must be engineer-readable

**Date**: 2026-05-24
**Status**: committed
**Applies to**: all PDFs, schematics, board renders, BOMs, and assembly
drawings committed to this repo from this point forward. Existing CP2
schematic PDFs are out of scope for immediate fix (see "Existing
violations" below) but must satisfy this rule before CP4 begins.

### Motivation

This workflow is intended to be transportable to future PCB projects.
Programmatic generation that produces machine-valid but
human-unreadable artifacts (e.g. ERC-clean schematics with overlapping
symbols and only net-label connections) creates documentation that no
engineer can review, hand off, or maintain. Future projects following
this template should not inherit that defect.

### Concrete acceptance criteria

A committed document passes D11 if all apply:

1. **No symbol/footprint overlap.** Programmatically-placed schematic
   symbols and PCB footprints must not share coordinates. Verifiable
   by scripted check (`grep` for duplicate `(at x y)` positions in
   .kicad_sch / .kicad_pcb).
2. **Real wires within clusters.** In schematics, components that are
   electrically adjacent and visually adjacent must be connected by
   wires, not labels. Net labels are reserved for power rails (GND,
   V3V3, etc.) and for cross-cluster signals that genuinely span the
   sheet.
3. **Functional grouping with visible signal flow.** Components that
   form a functional block (power input chain, regulator + caps,
   MCU + bypass, etc.) must be grouped together with a clear primary
   flow direction (left → right or top → bottom).
4. **Populated title block.** Every committed PDF must have a non-empty
   Title, Rev, and Date.
5. **Legible at 100 % zoom.** Net labels, ref designators, and pin
   numbers must not overlap each other when the PDF is viewed at
   1:1 scale. (Subjective but the reviewer must confirm.)
6. **Power rails on consistent edges.** Within a sheet, supply rails
   stay near the top, GND near the bottom (or a single fixed pattern).
   Don't scatter the same rail across the sheet.
7. **Reference designators visible on PCB renders.** Top/bottom
   renders committed for review must show each footprint's refdes,
   not the KiCad `REF**` placeholder.

### Enforcement

- Each CP review packet's "Success criteria" section must include a
  "D11: docs pass engineer-readability bar" checkbox. The reviewer
  (Codex) cites D11 when pushing back on documentation that fails any
  of the criteria above.
- `DESIGNER.md` is updated to call out D11 as a deliverable, not a
  side effect: when generating any document, treat readability as a
  first-class requirement equal to correctness.

### Existing violations

The CP2-output schematic PDFs at
`hardware/outputs/{battery,display}_side/schematic.pdf` currently
fail criteria #1, #2, #3, #4, and #5. Fix planned as a separate
checkpoint (working name: "CP-schematic-cleanup") landed
**before CP4 starts**, on a branch off main that does not perturb
the CP3 placement work. Acceptance: ERC must stay 0/0 and netlist
topology must be byte-identical to current CP2 outputs (modulo
metadata strings).

---

## Open decisions (not yet committed)

- **D-OPEN-1: ESP32-S3 module specifics.** Existing BOM says
  `ESP32-S3-DevKitC-1-N8R2`. For a custom PCB we'd use the bare module
  (`ESP32-S3-WROOM-1-N8` or `-N16R8`). Need to pick:
  - flash size (4 / 8 / 16 MB) → 8 MB sufficient for firmware
  - PSRAM yes/no → no PSRAM needed
  - antenna onboard vs U.FL connector → onboard (lower BoM, fewer SKUs)
  - revision (WROOM-1 vs WROOM-2) → WROOM-1, ubiquitous in stock
- **D-OPEN-2: RS-485 transceiver part.** Original BOM:
  `SN65HVD3082EDR`. Alternative `THVD1452`, `MAX3485ESA`. Need to pick
  based on stock + low quiescent (THVD1452 is the lowest-Iq).
- **D-OPEN-3: ULP voltage monitor IC vs ESP32-S3 internal ADC.** The
  4-tier shutdown needs sub-100 µA monitoring of pack voltage in
  HARDCUT. Options:
  - ESP32-S3 ULP-RISC-V wakes on RTC tick, samples internal ADC → cheap,
    but needs the 3V3 rail alive (~50 µA quiescent on the regulator).
  - Dedicated supervisor IC with comparator (e.g. TPS3839) → ~150 nA
    typical, sub-µA total path. More $, lower draw.
  - Resolve at CP1.
- **D-OPEN-4: Fab-house-specific design rule choice.** Confirm JLCPCB
  vs PCBWay vs OSHPark at CP1 (default JLCPCB; user input welcome).
