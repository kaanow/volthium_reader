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
export at CP6 (was CP5 pre-D12; see [D12](#d12--cp-renumber-display-side-placement-inserted-as-cp4)).

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
violations" below) but must satisfy this rule before the routing-drc
checkpoint begins (CP5 post-D12; was CP4 at the time this was written).

### Motivation

This workflow is intended to be transportable to future PCB projects.
Programmatic generation that produces machine-valid but
human-unreadable artifacts (e.g. ERC-clean schematics with overlapping
symbols and only net-label connections) creates documentation that no
engineer can review, hand off, or maintain. Future projects following
this template should not inherit that defect.

### Concrete acceptance criteria

A committed document passes D11 if **ALL** apply. Criteria #0 and #5
are absolute — failing either means the document is not finished
and may not ship. "Checklist-compliant but visually-unreadable" does
not pass.

0. **HARD STOP: No overlapping text or symbols, no text or symbols
   off the document.** Both designer and reviewer must open the
   rendered PDF, look at it, and confirm: (a) no two pieces of text
   overlap each other, (b) no text overlaps any symbol body,
   (c) no symbol body overlaps another symbol body, (d) every piece
   of text and every symbol fits entirely inside the sheet frame
   (none clipped at the page edge). If any of these fails, the
   document is not finished — fix it before any other gate is
   considered. **No "PARTIAL" rating is acceptable on this criterion.**
1. **No symbol/footprint coordinate collision.** Programmatically
   placed schematic symbols and PCB footprints must not share
   anchor coordinates. Verifiable by scripted check.
2. **Real wires within clusters.** Components electrically adjacent
   and visually adjacent are connected by wires, not labels. Net
   labels are reserved for power rails and cross-cluster signals.
3. **Functional grouping with visible signal flow.** Components
   forming a functional block are grouped with a clear primary flow
   direction (left → right or top → bottom).
4. **Populated title block.** Every committed PDF has non-empty
   Title, Rev, and Date.
5. **HARD STOP: Legible at 100 % zoom.** Net labels, ref designators,
   pin numbers, and any annotations are individually readable at 1:1
   scale, with clear whitespace between adjacent text. No "dense
   cluster of labels you can mentally parse if you squint" — if a
   reader at 100 % zoom can't read every piece of text without
   visual ambiguity, this fails. **No "PARTIAL" rating is acceptable
   on this criterion.**
6. **Power rails on consistent edges.** Supply rails near the top,
   GND near the bottom (or a single fixed sheet-wide pattern). Don't
   scatter the same rail across the sheet.
7. **Reference designators visible on PCB renders.** Top/bottom
   renders show each footprint's refdes, not `REF**`.

### Enforcement

- Each CP review packet's "Success criteria" section must include a
  "D11: docs pass engineer-readability bar" checkbox.
- **Both the designer and the reviewer must open and visually
  inspect the rendered PDFs before claiming a D11 criterion passes.**
  A grep-based audit alone is not sufficient — overlapping labels,
  off-page text, and unreadable clusters are visual defects that
  scripted checks can miss.
- Codex cites D11 when pushing back on documentation that fails any
  of the criteria above. Criteria #0 and #5 are non-negotiable.
- `DESIGNER.md` calls out D11 as a deliverable equal to correctness.

### Visual inspection protocol (mandatory before claiming #0 or #5 PASS)

A scripted audit can pass while the PDF is unreadable, because
scripts only check what they were written to check. Past project
history (see "Documented failure" below) shows this is a real
failure mode, not a hypothetical. To close it, every D11 sign-off
that touches a rendered document must include:

1. **Open the rendered PDF at 100 % zoom.** Not the KiCad editor,
   not a PNG export, not a screenshot taken at "fit-to-window" —
   the committed PDF, at 1:1, the artifact a downstream engineer
   would actually read.
2. **Screenshot every dense region.** A "dense region" is any IC,
   any connector with ≥4 pins, any cluster of ≥3 components within
   roughly 20 mm of each other, and any place a power/ground rail
   meets ≥3 component pins. For a typical two-IC schematic this is
   6–12 screenshots per sheet.
3. **Embed those screenshots in the active CP review packet** under
   a heading `## D11 visual inspection — iter <N>`. One screenshot
   per region, captioned with the region name (e.g. "U2
   SN65HVD3082E + RS-485 termination").
4. **For each screenshot, write one sentence**:
   `Read every piece of text in this region. Findings: <none> | <list>.`
   If `<list>` is non-empty, the document does not pass D11 and the
   iteration is not done — fix and re-render.
5. **The reviewer reads the screenshots, not the audit script
   output.** The reviewer may flag any text the designer claimed
   was readable; the reviewer's read of the rendered pixels is
   authoritative. A scripted-audit-only review is itself a D11
   enforcement failure.

A `## D11 visual inspection — iter <N>` section with screenshots is
a **hard prerequisite** for claiming criteria #0 or #5 PASS. Without
it, the designer has not performed the inspection and any "PASS"
claim is invalid on its face.

### What the scripted audit is good for

Scripted audits remain useful as a *first-pass filter*. They cheaply
catch symbol coordinate collisions, off-page text, duplicate
placements, and gross label spacing problems. They are **not** a
substitute for the visual inspection above. Treat them as
"necessary but not sufficient": if the script flags problems, fix
those first; once the script is clean, the visual inspection begins.

### Documented failure (teaching example — do not repeat)

CP-schematic-cleanup, iteration 36 (2026-05-25). The designer wrote
a label-coordinate distance audit that measured centroid-to-centroid
distance between net-label objects. The audit reported zero pairs
closer than 6 mm on either schematic and the designer declared the
CP done and asked for merge. The user opened the rendered PDF and
immediately saw, on the display-side schematic alone:

- FFC J2 pins 1–10: pin number + pin name (`Pin_N`) + net label
  (`GND`, `3V3`, `EPD_BUSY`, …) all occupying the same X coordinate
  — three pieces of text stacked at every used pin.
- U2 SN65HVD3082E: net labels (`UART_RX`, `UART_TX`, `DE_RE`, `3V3`,
  `GND`) placed directly on top of the chip's pin names (`RO`, `DI`,
  `RE`, `VCC`, pin 5).
- C7, R3, R4, TVS R2: net labels and component reference text
  overlapping the device body.

The audit didn't see any of this because it was written to check
label-vs-label centroid distance — not label-vs-pin-name,
label-vs-pin-number, or label-vs-symbol-body overlap. None of those
checks were ever in the script. The designer treated "script clean"
as equivalent to "criteria #0 and #5 satisfied." That equivalence is
what this section forbids.

Root cause was procedural, not technical: there was no mandatory
visual gate, so the cheapest thing (run a script) became the only
thing. The protocol above closes that gap by making screenshots-in-
packet a hard requirement of the sign-off itself.

### Portability for future PCB projects

D11, including the visual-inspection protocol and the documented
failure above, is intended to be **copied verbatim** into any future
PCB project that forks this template. A fresh Claude or Codex
instance starting a new board project should read D11 first,
internalize the failure mode, and never claim a documentation gate
PASS based on script output alone. The operational checklist in
`hardware/reviews/DESIGNER.md` §0 references this protocol and must
be carried forward together with it.

### Existing violations

The CP2-output schematic PDFs at
`hardware/outputs/{battery,display}_side/schematic.pdf` currently
fail criteria #1, #2, #3, #4, and #5. Fix planned as a separate
checkpoint (working name: "CP-schematic-cleanup") landed
**before the routing-drc checkpoint starts** (CP5 post-D12; was CP4
at the time this was written), on a branch off main that did not
perturb the CP3 placement work. Acceptance: ERC must stay 0/0 and
netlist topology must be byte-identical to current CP2 outputs
(modulo metadata strings).

## D12 — CP renumber: display-side placement inserted as CP4

**Date**: 2026-05-26
**Status**: committed
**Applies to**: project checkpoint roadmap from this date forward.

### Change

Original roadmap (D1–D11 era):

| CP | Phase                  |
|----|------------------------|
| 1  | Design baseline        |
| 2  | Schematic capture      |
| 3  | Placement (both boards)|
| 4  | Routing + DRC          |
| 5  | Fab-ready              |

CP3 in practice closed with battery-side placement only — display-side
was explicitly deferred at CP3 iter 18+ ("Display-side PCB — separate
scope (iter 18+ after CP3 close for battery-side)"). The CP-schematic-
cleanup side checkpoint then landed between CP3-battery-side and
routing-drc, leaving display-side placement as an undone prerequisite
for routing.

New roadmap:

| CP | Phase                       |
|----|-----------------------------|
| 1  | Design baseline             |
| 2  | Schematic capture           |
| 3  | Placement (battery-side)    |
| 4  | Placement (display-side) ←  new |
| 5  | Routing + DRC (was CP4)     |
| 6  | Fab-ready (was CP5)         |

The CP-schematic-cleanup side checkpoint between CP3 and CP5 remains
historically — it ran before this renumber and is already
closed/merged.

### Rationale

Three options were considered:

- **(A) CP3.5 standalone.** Single-concern packet preserved, but
  leaves a non-linear "3.5" wart in the project's permanent artifact
  trail.
- **(B) Fold display placement into the routing CP.** Preserves
  linear numbering but creates a mixed-concern packet (placement
  quality + routing quality evaluated in the same iteration), and
  breaks the single-concern pattern every prior CP followed.
- **(C) Renumber: display placement = CP4, routing = CP5, fab =
  CP6.** One-time doc-update cost in exchange for linear numbering
  AND single-concern packets, preserved across the project lifetime.

Option C chosen. Pursuit-of-excellence call: clean numbering and
clean concern boundaries are project-quality investments that
compound across every future reference (commits, PRs, BOM
revisions, any future PCB project that uses this as a template).

### Mechanics

- `hardware/reviews/DESIGNER.md` §2 table updated to six checkpoints;
  §5 advancement logic (`current_cp == 6` triggers fab-order gate);
  §5 branch-slug table; §6 per-CP work descriptions; §8a header.
- `hardware/layout/decisions.md` §145 (PCB STEP export), §183 (D11
  routing-drc precondition), §338–344 (CP-schematic-cleanup history)
  updated to reflect new numbering, with explicit "was CPN pre-D12"
  annotations where the prior number is historically informative.
- Existing CP-numbered branches and PRs (`hw/cp3-placement`,
  `hw/cp-schematic-cleanup`) are not renamed — their numbers reflect
  the roadmap at the time they were opened and are part of the
  historical record.
- New CP4 (display-side placement) opens on
  `hw/cp4-display-placement` with packet at
  `hardware/reviews/cp4_display_placement.md`.

### Out-of-scope for the renumber itself

The actual display-side placement design work (board outline,
footprint placement, DRC, renders) is the substantive content of
CP4, handled iteratively per the standard CP cycle. This decision
entry only documents the roadmap restructure.

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
