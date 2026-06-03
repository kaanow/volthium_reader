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
- Min drill: 0.3 mm (project rule for our own routing — see exception below)
- Min annular ring: 0.13 mm
- Edge clearance: 0.3 mm
- Hole-to-trace: 0.2 mm

**Exception (added 2026-06-03 in response to CP5 iter-12 Finding 09):**
*Vendor-supplied footprints* — specifically the thermal-via array inside
a manufacturer-published module footprint — are exempt from the project
0.3 mm min-drill rule when the vendor specifies a smaller drill and the
fab process supports it. Concretely: the
`ESP32-S3-WROOM-1U` Espressif footprint includes a 12-via 0.2 mm array
under pad 41 (GND thermal pad), required by the module's thermal spec.
JLCPCB's published minimum **via** drill is 0.2 mm (their "2-layer 4 mil
trace, 0.2 mm via" tier), so these vias are fab-acceptable. The 0.3 mm
rule applies only to vias we author ourselves; vendor-module thermal
arrays are accepted as-shipped.

KiCad will emit `drill_out_of_range` warnings for the 0.2 mm vias because
the project DRC's `min_through_hole_diameter` rule stays at 0.3 mm for
self-authored geometry. Those warnings are documented per-instance in
the active CP packet's D13 scorecard under the F-S-2 / F-P-7 evidence
column and accepted as expected vendor-footprint output.

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
0a. **HARD STOP: No schematic-object overlap, full stop, unless an
   explicit defensible exception is documented.** "Schematic object"
   includes symbol bodies, wires, labels, refdes/value text, pin names,
   pin numbers, junctions, and graphical annotations. Default rule is
   zero overlap of any object with any other object. The only allowed
   exception path is:
   - overlap is intentional and functionally required,
   - a concrete rationale is written in the active CP packet, and
   - readability at 100 % zoom remains unambiguous.
   If any overlap is present without that written justification, D11
   fails.
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

## D13 — Explicit acceptance criteria operationalizing D11

**Date**: 2026-05-26
**Status**: committed
**Applies to**: every review packet from the date this decision merges
forward. Existing closed checkpoints may be re-audited against these
criteria if the user or a downstream reviewer identifies a likely
defect; see "Re-audit obligations" below.

### Motivation

D11 set the right principle and the right hard-stops (#0 no overlapping
text/symbols, #5 legible at 100 % zoom). In practice, those criteria
were APPROVED on documents that visibly violate them. A user audit on
2026-05-26 walked the display-side schematic PDF and the CP4 PCB
renders against an explicit checklist: the schematic had overlapping
labels around the MCU pin region and the BTN cluster; the PCB had
`silk_over_copper` (52) and `silk_overlap` (25) DRC warnings that
prior CPs dismissed as "footprint-internal noise."

The fix is not to weaken or strengthen D11 but to operationalize it:
enumerate the specific criteria that count as PASS, treat each as
binary (no PARTIAL / no PASS\*), require an explicit per-criterion
scorecard in every review packet, and put **functional correctness as
the prerequisite** that must pass before any readability claim is
even evaluated.

### Scope and order of evaluation

Every CP review packet is judged in this order:

1. **D13.A — Functional correctness gates.** If any applicable gate
   fails, the packet is REJECTED. Readability is not evaluated.
2. **D13.B — Schematic readability** (when the packet touches a
   schematic or schematic-derived artifact).
3. **D13.C — PCB readability** (when the packet touches a board or
   board-derived artifact).

Each criterion is binary: PASS or FAIL. **PARTIAL, PASS\*, or
"PASS with caveat" are forbidden.** A criterion is either met or it
isn't.

### D13.A — Functional correctness gates (must pass first)

These are not new requirements — they restate the existing functional
expectations as an explicit gate so the readability evaluation can
assume functional correctness.

**Schematic gates:**

| ID    | Criterion |
|-------|-----------|
| F-S-1 | ERC: 0 errors. Every ERC warning is categorized and per-instance justified in the packet. |
| F-S-2 | Every IC pin connected per the relevant `cp1_*.md` design spec, or explicitly marked NC. |
| F-S-3 | `PWR_FLAG` on every power net (V3V3, GND, V12_*, etc.). |
| F-S-4 | No floating nodes / no unconnected wire ends. |
| F-S-5 | BOM is 1:1 with schematic refs and values. Every ref in the committed schematic has a BOM row; every BOM row has a schematic ref. |
| F-S-6 | Net names are meaningful. No `Net-(X1-Pad1)` autogen names in the committed netlist. |

**PCB gates:**

| ID    | Criterion |
|-------|-----------|
| F-P-1 | DRC errors = 0. Warnings categorized + each category justified. `silk_over_copper` and `silk_overlap` warnings are **not** "noise" — they are evaluated under D13.C, not waived here. |
| F-P-2 | PCB net topology matches the ERC-clean schematic exactly. 0 unconnected pads. Schematic-parity issues limited to the documented `volthium:` vs `Lib:` libId-prefix mismatch (from the project-local footprint cache pattern); any other parity issue is a fail. |
| F-P-3 | Every footprint matches the BOM part number's package and pinout. No SOT-23 footprint for a SOT-23-5 part, etc. |
| F-P-4 | Board outline and mounting holes match the relevant `cp1_*.md` mechanical spec. |
| F-P-5 | Every component from the netlist is placed (0 missing-placement warnings). |
| F-P-6 | Polarized components (diodes, electrolytic caps, TVS, MOSFETs) have correct orientation, verifiable by the silk pin-1 / cathode / polarity mark. |
| F-P-7 | JLCPCB fab rules met per [D2](#d2--fab-choice--jlcpcb-qty-5-of-each-bare-pcb): 0.152 mm trace/space, 0.3 mm drill, 0.13 mm annular ring, 0.3 mm edge clearance, 0.2 mm hole-to-trace. |

### D13.B — Schematic readability criteria (binary)

Apply when the packet touches a schematic or its rendered PDF.

**Layout and flow:**

| ID    | Criterion |
|-------|-----------|
| SR-1  | Functional blocks visually separated. Power input, regulator, MCU + decoupling, peripheral interfaces, user IO each occupy a distinct region of the sheet with clear whitespace between them. Reviewer can name each block when shown the rendered PDF. |
| SR-2  | Signal flow consistent: left → right OR top → bottom, declared once per sheet (e.g. in a top-of-sheet comment), followed throughout. |
| SR-3  | Power rails on consistent edges (top or one fixed side); GND on the opposite or one fixed side. No same-rail scatter across the sheet. |
| SR-4  | No densely packed cluster: no more than 6 distinct labels (refs + values + net names, combined) within any 20 × 20 mm region of the sheet. |

**Identification:**

| ID    | Criterion |
|-------|-----------|
| SR-5  | Every component has a visible refdes (R1, U2, …) and a visible value (10k, ESP32-S3-WROOM-1U, …). Both legible at 100 % zoom. |
| SR-6  | Refdes and value do not overlap each other, do not overlap pins, do not overlap the component body, do not overlap any wire. |

**Nets:**

| ID    | Criterion |
|-------|-----------|
| SR-7  | Net labels appear only at wire ENDS, not mid-wire and not on a component body. |
| SR-8  | Power nets use `PWR_FLAG` symbols; bare text-labels for power are forbidden. |
| SR-9  | Bus / repeated bundles use bus syntax, not parallel net-label spaghetti. |
| SR-10 | Wire stubs at IC pins are long enough that the net label is at least 2 mm clear of the IC body silk. |

**Pin and IC clarity:**

| ID    | Criterion |
|-------|-----------|
| SR-11 | IC pin numbers visible and not occluded by net labels or other text. |
| SR-12 | IC pin names (functional, e.g. `MOSI`, `TX`, `EN`) visible near the wire stub leaving the pin. |

**Typography:**

| ID    | Criterion |
|-------|-----------|
| SR-13 | The smallest text on the sheet is legible at 100 % PDF zoom in a real PDF viewer (Preview / Acrobat), without squinting. Net labels ≥ 1.0 mm in schematic units (≈ 10 pt rendered). |
| SR-14 | No overlapping text anywhere on the sheet (subsumes D11 #0; applies to every label, ref, value, and pin name). |
| SR-14a | No overlap among **any** schematic objects (text, symbols, wires, pin metadata, junctions, graphics). Any intentional overlap must be explicitly justified in the active review packet with a defensible rationale and confirmed legible at 100 % zoom. |

**Polarity, safety, metadata:**

| ID    | Criterion |
|-------|-----------|
| SR-15 | Polarity indicators on every electrolytic cap, every diode, every TVS, every MOSFET (S/D distinguished by silk or schematic-symbol convention). |
| SR-16 | DNI / DNP marks where applicable; test points labeled. |
| SR-17 | Title, Sheet, Rev, Date populated. Multi-sheet: sheet number visible. |

### D13.C — PCB readability criteria (binary)

Apply when the packet touches a board or its rendered top/bottom PNG.

**Silk text (subsumes D11 #7):**

| ID    | Criterion |
|-------|-----------|
| PR-1  | Every component has a refdes on the appropriate silk layer (F.SilkS for F.Cu components, B.SilkS for B.Cu components). Verified visible in the committed render. |
| PR-2  | No refdes sits under its own component body where assembly will cover it. The text must be visible after the part is soldered down. |
| PR-3  | No silk text overlaps another component's body or pads. DRC `silk_overlap` = 0, OR each remaining warning is documented per-instance as a footprint-internal artifact that does not impact the readability of any refdes. |
| PR-4  | No silk printed on bare copper. DRC `silk_over_copper` = 0, OR each remaining warning is documented per-instance as a footprint-internal artifact AND the clipped portion is not the refdes. |
| PR-5  | Pin-1 / polarity indicators visible on every polarized footprint (silk dot, arrow, or cathode mark). |
| PR-6  | All silk text reads in a consistent orientation (bottom-up or left-to-right). No upside-down text. |

**Placement:**

| ID    | Criterion |
|-------|-----------|
| PR-7  | Components grouped by function. Power-input → regulator → IC chains visually compact. |
| PR-8  | Decoupling caps placed within 3 mm of their driven IC pin (pad-edge to pad-edge). |
| PR-9  | Mechanical constraints (mounting holes, board outline, connector edges, tall-component layer) honored per the relevant `cp1_*.md`. |
| PR-10 | Differential pairs (RS-485, USB) placed close together so they can be routed as pairs at the routing checkpoint. |

**DFM and reliability:**

| ID    | Criterion |
|-------|-----------|
| PR-11 | DRC `solder_mask_bridge` = 0 (assembly-risk hard fail). |
| PR-12 | Footprint matches the BOM part number's package and pin pitch (also covered by F-P-3; restated here because mismatches show up as silk/placement defects too). |
| PR-13 | Debug headers placed per the design (UART debug, USB-OTG, SWD/JTAG if applicable). |

### Enforcement — packet scorecard

Every CP review packet from this decision onward must include, at
the SIGN-OFF section, an explicit table with one row per applicable
F-*, SR-*, PR-* criterion. Columns:

- **Criterion ID** (e.g. F-S-1, SR-7, PR-3)
- **Status** (PASS or FAIL, no other values)
- **Evidence / justification** (one sentence; for FAIL, what specifically failed; for any PR-3 / PR-4 PASS that has a non-zero raw DRC count, the per-instance justification)

The reviewer (Codex) verifies each row independently. APPROVED requires
**every applicable row = PASS**. Any FAIL → NEEDS CHANGES.

CPs select the criteria that apply to their phase:

- Schematic CPs (CP2, CP-schematic-cleanup, any schematic touch):
  F-S-\* + SR-\*.
- Placement CPs (CP3, the display-side placement CP, any placement
  touch): F-P-\* + PR-1..PR-9 + PR-11..PR-12. PR-10 deferred to the
  routing CP if at placement-only. PR-13 evaluated at placement
  (location only) and again at routing (connection).
- Routing CPs: F-P-\* + PR-\* (full set including PR-10).
- Fab-ready CPs: F-P-\* + PR-\* + Gerber-specific gates added when
  written.

### Re-audit obligations

D13's criteria apply to:

1. All new CP packets from this decision's merge date forward.
2. The CP currently in flight when this decision merges
   (display-side placement): the packet must be amended with an
   explicit D13.A/B/C scorecard before any merge to main, regardless
   of any prior APPROVED verdict reached under the pre-D13
   (permissive) standard.
3. CP-schematic-cleanup (closed; the schematic PDFs failed the user
   audit): re-audit required. The schematic is reopened on a side
   checkpoint of the form `CP-schematic-cleanup-2` if downstream
   work depends on schematic readability per D13.B.
4. CP3 (battery-side placement, closed): re-audit deferred. If the
   routing-drc CP encounters a placement-readability blocker per
   D13.C, CP3 reopens on a side checkpoint.

### Out of scope for this decision

D13 does not introduce new electrical requirements, new BOM parts,
or new fab-process targets. It enumerates the acceptance bar for
review packets — the bar that D11 declared in principle but did not
enumerate concretely enough to prevent permissive APPROVED verdicts.

---

## D14 — Battery-side BAT1↔MOD1 clearance was a real GPIO short, not an inert NC overlap

### Finding

Through CP5 iter-9 the battery board carried 3 `[clearance]` DRC
errors, documented in the packet as "functionally inert" because the
involved MOD1 pads 23/24/25 were believed to be no-connect. They are
not. In `RF_Module.kicad_sym`, ESP32-S3-WROOM-1 pads 22–26 are
**IO14 / IO21 / IO47 / IO48 / IO45** — general-purpose IO that this
design leaves unused (hence `<no net>` in the netlist). BAT1's GND
spring-clip copper (pad 2, bbox x30.65–33.86, y26.18–29.81) overlapped
pads 23/24/25 (y28.25–29.75) at **0.000 mm** — a physical short of
GPIO21/47/48 to GND on the finished board. `<no net>` means "unused in
this schematic," not "not bonded to silicon." The inert-NC rationale
was false and must not be reused.

### Constraints discovered

- **BAT1 (Keystone_1057) is immovable by translation.** The footprint
  draws the round CR2032 profile on Edge.Cuts, which KiCad treats as a
  ~11.6 mm-radius milled cutout about the anchor. Left → cutout off the
  board edge; down → off the bottom edge; right → the cutout swallows
  MOD1's pads. Confirmed empirically (invalid-outline / new errors).
- **MOD1 is boxed on all four sides** — Q1/R3/R4 immediately left, J2
  immediately right, F1 fuse above, RTC1 immediately below. A 2 mm
  downward shift collides MOD1's bottom pads with RTC1's top pads
  (8 new errors). MOD1 cannot move either.

### Fix path investigated — and why it's bundled into the re-floorplan

The minimal placement fix is verified: raising BAT1's anchor 1.8 mm,
(17, 28) → (17, 26.2), drops the GND clip's bottom edge to y28.01,
clearing MOD1's bottom GPIO row (top edge y28.25) by 0.24 mm — over the
0.20 mm Default rule. Placement-only DRC with that move: **0 errors**
(total violations 242 → 232; silk improved, +4 inherent cutout-edge
warnings).

But the board could not be brought to a clean **routed** state by
point-fixes — the cramped 60×40 board hits a wall:
- With BAT1 raised, the autorouter (v2.1.0) routes 105–89 tracks but
  bridges U2 pad 3 (V12_CAT5E) onto TVS2's RS-485 pads — a 12 V↔RS-485
  short — because TVS2 sits 2 mm off U2's pad on the packed right edge.
- Relocating TVS2 clear of U2 (tried (44, 23)) makes the RS-485 zone
  unroutable: Freerouting v2.1.0 churns past a 900 s timeout and never
  emits an SES, at any optimizer-pass count.
- Freerouting **v1.9.0** (the build's default) is unusable here at all
  — its route optimizer throws a `NullPointerException`
  (`FloatPoint.rotate`, p_point==null) and pops a modal dialog that
  never saves. v2.1.0 routes the *original* placement but is flaky on
  perturbed geometry.

Conclusion: the GPIO short, the U2↔TVS2 short, and the ~88 silk /
~28 courtyard warnings the user flagged are all symptoms of the same
over-packed board. They are **not** independently fixable by nudging
(every nudge relocates a conflict or breaks routing — the same lesson
the schematic re-floorplan taught). The board is **unconstrained per
D10**, so the correct fix is to enlarge it and re-floorplan with
generous spacing — and/or swap BAT1 to a non-cutout B.Cu SMD holder
(D-OPEN-5). The committed PCB is therefore left at the prior routed
state; the BAT1/TVS2 fixes are folded into that re-floorplan task so
the board is fixed and cleanly routed in one coherent pass, not left
in a half-routed/2-error intermediate.

### Recommended follow-up (BOM/mechanical — needs owner sign-off)

The Keystone_1057 cutout footprint is the source of ~25 inherent
`copper_edge_clearance` warnings: its clips sit at the milled cutout
edge amid dense copper, and the cutout cannot be placed clear of MOD1
on a 60×40 board. A genuinely clean battery side would replace it with
a **non-cutout SMD coin holder (e.g. Keystone 3000 / 3034) mounted on
B.Cu, opposite MOD1** — eliminating the cutout, its edge warnings, and
any F.Cu pad conflict in one move. This is deferred here because it is
a BOM change (new Keystone PN, procurement) plus a mechanical/enclosure
decision (holder on the board bottom) that the hardware owner must
approve — out of scope for a DRC-correctness iteration. Tracked as
D-OPEN-5 below.

### Lesson encoded elsewhere

The process failure (justifying a real defect on an unverified premise)
and the tooling path (regenerate DRC from the board; kiutils can't read
the routed file; verify pin function before "NC") are recorded in
`hardware/reviews/DESIGNER.md` §12.

---

## D15 — Battery-side PCB enlarged to 95×75 and re-floorplanned

Operationalizing **D10** (battery-side form factor unconstrained), the
battery board was enlarged from the cramped **60×40** to **95×75 mm**
(~3× the area) and fully re-floorplanned. The 60×40 layout had forced
sub-0.2 mm pad clearances, ~88 silk-over-copper, ~28 courtyard overlaps,
and the **D14** BAT1→MOD1 GPIO short — none independently nudge-fixable.

Floorplan: functional zones, signal flow left→right — 24 V input +
protection across the top (J1→F1→D1/TVS1), hard-cut MOSFETs + the 3V3
buck (U1) cluster + 12 V Recom (U2) in the upper-mid band, MOD1 (ESP32)
center with bypass caps on B.Cu beneath it, RTC1 / RS-485 / RJ45 / dev
headers down the right, and the CR2032 **BAT1 in its own bottom band a
full 4 mm below MOD1** so its 34 mm-wide clips cannot bridge MOD1's GPIO
pads. Verified courtyard-overlap-free (0, was ~28) before generation
with an offline floorplan checker, then **0 error-severity DRC**.

Resolved along the way:
- **BAT1 Edge.Cuts → F.Fab.** The `Keystone_1057` footprint draws the
  coin-cell body outline on `Edge.Cuts`; KiCad reads that as a board
  cutout, self-intersecting the rectangular outline (`invalid_outline`)
  and tripping copper/silk edge-clearance on neighbours. The 1057 is a
  surface-mount retainer that sits *on top* of the board — no cutout is
  wanted — so the build relocates any component Edge.Cuts geometry to
  `F.Fab` documentation. This fixes the corruption **without** the BOM
  swap of D-OPEN-5 (now optional, not required for DRC correctness).
- **Refdes positioning.** kiutils stores footprint properties as a plain
  string dict and drops the Reference `(at)`/`(layer)`, so every refdes
  was written at the part origin (silk-over-copper / silk-overlap). A
  pcbnew post-process sets each designator's absolute board position
  (anchor + a clearance-maximizing offset), correct silk layer + mirror,
  and a fab-legal size/thickness. Mounting-hole (`H*`) refdes are hidden.
- **MOD1 thermal vias.** The stock `ESP32-S3-WROOM-1U` pad 41 (GND) is a
  PTH thermal pad with a 12-via 0.2 mm array. These trip
  `drill_out_of_range` against the 0.3 mm default rule; kept as accepted
  **warnings** (0.2 mm is within JLCPCB/PCBWay capability and the module
  vendor specifies them) per the D13 warning-justification convention. A
  B.Cu part cannot overlap that array, so R7 was placed clear of it.
- **Build no longer mutates `.kicad_pro`.** pcbnew `SaveBoard` rewrites
  the sibling project's `design_settings`, clobbering the hand-maintained
  net classes / DRC severities; the build now snapshots and restores it.

State: placement complete and DRC-clean. **Routing:** all 92 ratsnest
connections routed by Freerouting v2.1.0 in 2.7 s on the roomier board.
Three follow-ups bound at routing time, all per the project plan
(`_intended_classes_cp4`):

- **Net-class numerics bound.** `_intended_classes_cp4` /
  `_intended_patterns_cp4` in `.kicad_pro` was a deliberate placeholder
  ("CP4 routing reinstates the numerics + netclass_patterns" per the
  CP3 comment). Without those numerics pcbnew exports a degenerate
  Specctra DSN with `width -0.001` vias — Freerouting's "enlarge as a
  workaround" then exploded the maze search and OOMed even at 6 GB heap.
  Activated all classes (Default / Power-24V / Power-12V / Power-3V3 /
  RS485-diff) with their planned numerics and bound the V24_*/V12_*/
  V3V3*/RS485_* patterns.
- **Zone connect_pads switched from `thru_hole_only` to the default
  (thermal reliefs)** so SMD GND pads auto-connect to the pour. The
  previous `thru_hole_only` setting left several SMD GND pads requiring
  manual routing that Freerouting reliably missed. (kiutils writing an
  explicit `"thermal_reliefs"` string produces invalid KiCad syntax — it
  must be implicit; the constructor argument is now omitted.)
- **`min_resolved_spokes` relaxed from 2 to 1** to allow small bypass
  caps whose neighbourhood only fits one thermal spoke (C8 1 µF on B.Cu).
  Electrically one spoke is a valid connection; the rule trades a
  thermal-robustness preference for routing compatibility on a roomy
  but layered board.

Result: **0 error-DRC, 0 unconnected.** 21 warnings remain (12
`drill_out_of_range` for MOD1's thermal vias, 5 `track_dangling` from
Freerouting v2.1.0's known-broken multi-thread optimizer leaving ~0.5 mm
GND stubs, 4 `isolated_copper` GND zone islands ≥ 10 mm²) — all
warning-severity per the D13 convention.

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
- **D-OPEN-5: Battery-side coin-cell holder — cutout vs SMD (see D14).**
  Current part `BatteryHolder_Keystone_1057_1x2032` requires a milled
  board cutout that cannot be placed clear of MOD1 on the 60×40 board,
  generating ~25 inherent `copper_edge_clearance` warnings. Candidate
  replacement: a non-cutout SMD holder (Keystone 3000 / 3034) on B.Cu
  opposite MOD1. Decision needs the hardware owner: (a) BOM/procurement
  for the new PN, (b) enclosure clearance for a bottom-mounted holder,
  (c) whether ~25 cosmetic edge warnings justify the change vs the
  iter-10 geometry that already clears all DRC *errors*. Resolve before
  CP6 fab export, or accept the warnings explicitly in the CP6 packet.
- **D-OPEN-6: BOM supplier part numbers require validation.** The
  `DigiKey` and `Mouser` columns in `docs/hardware/bom.md` have not
  been verified against the distributors' live catalogs. Spot-checks
  (e.g. the LCD1 entry) have already returned fabricated / non-existent
  part numbers, and the rest are presumed equally suspect until proven
  otherwise. Every row needs to be re-derived from the authoritative
  `Part` column before any procurement happens. A header banner now
  warns against ordering directly from the file; this open decision
  tracks closing the loop with verified PNs (and a methodology — most
  likely a scripted lookup against the DigiKey / Mouser search APIs
  rather than hand-typed entries). Block CP6 fab export on this.
