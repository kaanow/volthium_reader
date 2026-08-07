# CP4 review packet — display-side placement

Branch `hw/cp4-display-placement` · packet opened 2026-08-05 · designer: Claude
Scope per D12: **display side only** (battery-side placement was CP3, APPROVED).

## 1. Scope and inputs

- Input netlist: the CP2-APPROVED display schematic's export,
  `hardware/kicad/schematic/build_display/volthium_display.net`
  (sha256 `41145f58b214…`), 39 components / 56 nets. **Three** CP4-driven
  schematic-side deltas — §4.1 and §4.5.
- Output: `hardware/kicad/pcb/build_display/display_pcb.kicad_pcb`
  (sha256 `dc28b2fe36e6…`) — 43 footprints (39 parts + 4 M3 mounting
  holes), all pads net-bound, **placement only** (routing is CP5).
- Hashes are of the committed git BLOB (`git cat-file blob HEAD:<path>`).
- Rebuild: POSIX `.venv/bin/python hardware/kicad/pcb/build_display_pcb.py`
  · Windows `.venv\Scripts\python.exe hardware\kicad\pcb\build_display_pcb.py`.
  Pre-handoff gate: `python3 hardware/reviews/tools/handoff_check.py`.
- Generator: `hardware/kicad/pcb/core.py` (shared with CP3) +
  `hardware/kicad/pcb/build_display_pcb.py` (display floorplan as data).
- Decisions taken: **D39** (MOD1 courtyard implements D26; J2 side-entry),
  **D40** (USB-C goes vertical — resolves DR-35), **D41** (RPA sign-off stays
  name-based — resolves DR-34).

## 2. What is materially new versus CP3

**This is the project's first board with parts on the back side**, and that
alone accounted for most of the work. CP3's battery board is all-front, so a
family of defects in the shared generator had never been reachable. Seven were
found and fixed here, each poison-tested; the approved CP3 board was
re-verified **byte-identical (`448d59a276df`)** after every one.

| # | Defect | Why CP3 could not see it |
|---|--------|--------------------------|
| 1 | `_flip_to_back()` swapped layers but never mirrored geometry — a back-side part's land pattern did not match the physical part (**fabrication-class**) | no back-side parts existed |
| 2 | The mirror was then applied about the **wrong axis** (X instead of Y) — see §4.2 for how this was settled | — |
| 3 | Writer and analytic gates used different back-side transforms, so DRC and the gates disagreed by ~5 mm | gates and writer agree trivially when nothing is flipped |
| 4 | Courtyard collision skipped opposite-side pairs entirely, but **THT pads pierce the board** and obstruct both faces | all parts on one side |
| 5 | Mounting holes were registered on one side only | same |
| 6 | `courtyard_segments()` handled only lines/rects and silently skipped every other shape — a MountingHole courtyard is a single **circle**, so holes contributed **zero geometry** while appearing to be gated | DRC happened to catch the one real hole overlap during CP3, masking it |
| 7 | Back-side refdes: inverse frame conversion mirrored the wrong axis (J1's designator landed 21 mm off its body) and the property restore was not side-aware, emitting back-side refdes onto **F.SilkS** | no back-side silk |

Defect 6 is the most instructive: the CP3 code comment asserted that mounting
holes "participate in the courtyard/outline gates like any part", and that
claim was simply false for the entire checkpoint.

## 3. Floorplan (rationale — mechanics dominate this board)

The enclosure drives everything (D8/D27): an 85 × 65 mm PCB inside a US
double-gang old-work box, behind a **pop-off faceplate that carries the
e-paper module**. Only a ~8 mm standoff gap exists on the front.

- **BACK side (faces the box floor, generous depth):** only the two parts
  that would blow the front gap — **J1** Würth RJ45 right-angle (13.6 mm,
  mating face W so the in-wall Cat5e enters from the side, §10.2 #5) and
  **U1** R-78E3.3 SIP (~11 mm), per §10.2 #4 "keep tall parts off the
  module-facing side".
- **N edge:** **J2** e-paper header, **side-entry** (D39), probed to open
  SOUTH so the cable runs over the board and rises to the module rather than
  into the ~5 mm gap between board edge and box wall.
- **Centre:** **MOD1** with the D26/D39 no-keepout courtyard.
- **W band (y 6…25):** 12 V entry chain F1 → TVS1/C1 and the RS-485 front
  end (U2, R2/R3/R4 bias+termination, J5) — placed clear of J1's
  through-board pad field, which projects to x 6.9…25.4 / y 26.5…38.2.
- **E column:** USB-C chain flowing west — J-USB → U-ESD/R_cc → U3-LDO →
  U4-MUX, with J3 ESP-Prog in the SE pocket.
- **S edge:** BTN1/2/3 at **x = 24 / 42 / 60 mm** (18 mm centres), each with
  its 1 MΩ pull-up and 100 nF debounce immediately north.

## 4. Findings made and fixed during self-review

### 4.1 Two schematic-side deltas, both evidence-forced

1. **MOD1 courtyard now implements D26.** The stock ESP32 courtyard is a
   T-shape: a 19.5 × 20.2 mm body stem plus a **48 × 21 mm flare that exists
   only to encode Espressif's antenna keepout**. D26 retired that keepout for
   this board (radio unused — RS-485 is the only link, "no RF → no keepout →
   freer layout") but the footprint never reflected it, and honouring it would
   sterilise **36 % of an 85 × 65 mm PCB** for a rule the design has dropped.
   Display-only variant `ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout`: **62/62 pads
   coordinate-identical** to the parent, sole graphic delta F.CrtYd 8 → 4
   segments. The battery board keeps the full-keepout parent (its radio IS
   used, D25).
2. **J2 is SIDE-entry (S8B-PH-K-S), not top-entry (B8B).** CP1 §4.4 deferred
   this to "CP3, from the cable-routing/depth stack" and it was never decided;
   the schematic had defaulted to top-entry. JST ePH datasheet: the top-entry
   part's **mated height is 8.0 mm** (p.1) — the entire PCB→module gap, with
   nothing left for the cable, which on a top-entry part exits vertically into
   the module. Side-entry is a 7.6 mm header whose cable exits horizontally
   (p.3). Widening the gap instead is rejected by a coupling: plunger length =
   gap + faceplate + protrusion, so 8 mm → ~13.5 mm (mid-catalog for the 6×6×N
   tactiles) but 12 mm → ~17.5 mm, at/past the catalog top end.

### 4.2 How the flip axis was settled — tool as oracle, not reasoning

My first fix mirrored **X**. That was wrong, and reasoning could not
distinguish it from mirroring Y — both are "a mirror" and both look
plausible. The decisive method: write a **stock** footprint to the back and
let KiCad judge it, since `lib_footprint_mismatch` fires when a board
footprint disagrees with its library copy.

| transform | stock back-side U1 |
|-----------|--------------------|
| no mirror | mismatch |
| mirror X (my first fix) | mismatch |
| **mirror Y** | **clean** |

Corroborated independently against a shipped KiCad demo board, whose B.Cu
footprint stores library-X with **negated Y**. Display
`lib_footprint_mismatch` fell 3 → 1 (only the vendored MOD1 variant remains,
the same kiutils-serialisation class CP3 accepted).

### 4.3 Doc corrections found before placing
- §4.6's button positions (22 / 42 / 62 mm) are **20 mm centres**, contradicting
  the same table's stated 18 mm pitch; §10.2's 24 / 42 / 60 is authoritative and
  is what is built. Corrected.
- The faceplate cutout span read "~16 mm" where 18 mm centres give **36 mm**.
  Corrected. Both swept across all doc sites.
- J1's shield: the Amphenol footprint (battery) names its shield pad `SH` and
  binds the stock symbol; the **Würth** footprint (display) names them
  `S1`/`S2`, so the netlist referenced a pad that does not exist and both real
  shield tabs were unrepresented. Renamed the vendored Würth tabs to `SH`
  (one metal shell → one node, NC here per DR-19); pad coordinates untouched.

## 5. Gate stack

All CP3 gates apply unchanged (parity, pinmap, outline, edge-marker, fab
floors, readback, DRC, label-adjacency, handoff), running inside
`BoardBuilder.write()` per CP3 F09. New this checkpoint:

| Gate | What it proves | Poisoned? |
|------|----------------|-----------|
| thru-pads | a part's through-hole pad field vs the FAR side's courtyards — THT pads pierce the board | fires on J1×U2/J5 and U1×R6 during iteration |
| courtyard (circles) | circular/poly/arc courtyards now contribute real segments | hole courtyard 0 → 24 segments; part-on-hole fires on both sides, clear placement stays clean |
| mounting holes | registered on BOTH sides | as above |

DRC final state: **0 unaccounted**. Accepted:
- `unconnected_items` ×123 — placement-only board, routing at CP5.
- `silk_edge_clearance` ×2 — J-USB's designed E-edge overhang.
- `lib_footprint_mismatch` **×2**, both instance-scoped with pad-diff
  evidence: **MOD1** (vendored no-keepout variant) and **J-USB**
  (USB4115-03-C, added at §4.5). Each is kiutils serialisation only —
  62/62 and 30/30 pad tuples respectively identical to their library copies
  (`iter1/mod1_pad_diff.txt`, `iter1/jusb_pad_diff.txt`).
  *Corrected at iteration 3: this read "×1" after §4.5 added the second
  (reviewer F05) — the count was stale, not the footprint unjustified.*

## 6. Open items for the reviewer

- ~~DR-35 (USB-C access)~~ **RESOLVED — implemented, see §4.5 (D40).**
- ~~DR-34 (RPA sign-off signing)~~ **RESOLVED — declined by the user (D41);**
  the gate's own docstring states the name-based limit rather than hiding it.
- ~~Per-instance evidence for the MOD1 `lib_footprint_mismatch`~~ **DONE** —
  `visual_inspections/cp4-display-placement/iter1/mod1_pad_diff.txt`: all
  **62/62 pad tuples** (number, type, shape, x, y, angle, sizeX, sizeY)
  identical between board copy and library; graphic-layer counts match
  (F.CrtYd 4, F.SilkS 8, F.Fab 6, Cmts.User 2); the entire delta is one
  `(unlocked yes)` token and the `embedded_fonts` token — kiutils
  serialisation, non-geometric. Same class and same evidence shape CP3 §2
  used for its MOD1 accept.
- ~~Depth tally re-confirmation~~ **DONE, and it moved** — see §4.4.

### 4.4 Depth stack corrected, and the button plunger resolved

CP1 §2.1 assumed an 8 mm PCB→module standoff gap. Measured from the parts
actually placed it is larger. At the time of this analysis the driver was
**J3, the Würth 61200621621 box header at 9.1 ±0.15 mm** (drawing p.1);
**§4.5's vertical USB-C at 9.30 mm then displaced it**, so the final numbers
are **gap ~9.7 mm, stack ~34.7 mm** against ~45 mm usable (~10.3 mm margin,
previously quoted as ~12 mm). `cp1_display_side.md §2.1` carries the final
values and their sources.

That closes a CP1 defer. Plunger length = gap + faceplate + protrusion =
9.7 + 3 + 2.3 = **15 mm**, which is a real catalog height, so BTN1–3 are no
longer `_verify_`: **Same Sky TS02-66-150-BK-160-SCR-D** (datasheet fetched
from the manufacturer — Mouser's mirror WAF-serves HTML, the same trap as
the GCT drawing at CP3; manifest row added). Checks performed:
- `150` = 15.0 mm actuator, and it is **not** one of the starred heights the
  part-number key restricts to long-crimped terminals, so `SCR` is valid;
- datasheet p.2 land pattern **6.5 × 4.5 mm, 4 × Ø1.0** versus the stock
  `SW_PUSH_6mm_H13mm`: **centres match exactly (6.5 × 4.5 mm); drills deviate 1.0 → 1.1 mm.** The datasheet's recommended pattern is 4 × Ø1.0 mm; the stock KiCad footprint uses Ø1.1 mm. Acceptance: the terminal is 0.7 ± 0.1 mm across its largest dimension (drawing p.2), so a 1.1 mm hole leaves ≥0.3 mm diametral clearance for insertion, and the 2.0 mm pad still gives a 0.45 mm annular ring — comfortably above the 0.13 mm fab floor. This is a sane substitution, **not identity evidence**; if an exact-pattern footprint is wanted, vendor one at CP5.
  *I originally wrote "exact match" here while my own output printed
  drill 1.1 — a verification adjective contradicted by the evidence on
  the same screen (reviewer F04).*
- ratings 12 Vdc / 50 mA, −30…+80 °C, 80,000 cycles at 160 gf — the 3V3
  button-to-GND use is far inside all three.

**Push force (160 gf) is an engineering pick, not a derived value.** 100 and
260 gf are drop-in siblings; if the button feel wants changing it costs only
a part-number character. Flagged for the user rather than presented as
settled.

Heights still carried from earlier work and **not** re-sourced this
checkpoint: J-USB (~3.2 mm), MOD1 (~3.1 mm), F1/J5 (~3–4 mm). None is within
6 mm of the 9.1 mm driver, so none can change the gap; they would need a
datasheet pass only if the stack is ever re-cut around a different tall part.

### 4.5 USB-C goes vertical (D40) — the largest change this checkpoint

DR-35 found that the specified **edge-mount** USB4085 could not physically be
plugged inside the wall box: only ~5 mm of clearance exists past any board
edge, a plug needs 15–20 mm of straight-in approach, and popping the faceplate
exposes the board's **front**, not its edges. The user chose the vertical
option, which opens **+Z** and is reachable straight-on once the faceplate and
e-paper module come away — invisible and unreachable when assembled.

**Part choice deliberately favoured footprint provenance over depth.** Two
vertical GCT parts were compared:

| | USB4120-03-C | **USB4115-03-C (chosen)** |
|---|---|---|
| height | **6.5 mm** | 9.30 mm |
| contacts | 16 (USB 2.0) | 24 (USB 3.2), 16 used |
| KiCad footprint | **none — would be hand-authored** | **ships with KiCad, cites GCT's drawing** |
| price / stock | $0.84 / 89 k | $1.00 / 54 k |

The 4120 is the better mechanical fit, but authoring a 0.5 mm-pitch connector
land pattern is exactly the risk class that has bitten this project twice
(DR-33's non-monotone RJ45 fan-out; CP3's mating-face defect). A published
footprint is worth 2.8 mm of depth here, because the depth is affordable and a
wrong land pattern is not.

Consequences, each checked rather than assumed:
- The 9.30 mm part displaces J3 (9.1 mm) as the depth driver → gap ~9.7 mm,
  stack ~34.7 mm against ~45 mm usable.
- **BTN1–3 unaffected.** With the 15 mm plunger already locked, protrusion
  becomes 2.3 mm — inside the ~2–3 mm spec. *An earlier draft of my own
  analysis claimed the taller part would force a longer plunger; that was
  wrong, and the arithmetic is shown in D40.*
- Pin binding: footprint pads (A1–A12/B1–B12/SH) are a **superset** of the
  16-pin symbol, so every symbol pin binds and the 8 SuperSpeed pads are
  simply unconnected. Pin/signal table cross-checked against the drawing.
- **Nothing overhangs a board edge any more** — the E-edge whitelist entry is
  gone and DRC `silk_edge_clearance` went **2 → 0**, `copper_edge_clearance`
  stayed 0.
- `lib_footprint_mismatch` for the new part is instance-accepted with the same
  evidence shape: **30/30 pad tuples identical**, delta is one
  `(unlocked yes)` and the `embedded_fonts` token
  (`iter1/jusb_pad_diff.txt`).
- **The battery board keeps USB4085** — it is not in a wall box, so its
  edge-mount geometry remains correct. Display-only change.

## 7. D13 scorecard

*Iteration 1 deferred this; that was wrong — D13 requires the table in every
packet, and iteration-1 F03 called it out. Completed here (reviewer F05).*

| Criterion | Status | Evidence |
|-----------|--------|----------|
| F-P-1 | PASS | DRC 0 unaccounted; accepted classes = unconnected_items ×123 (placement-only) + lib_footprint_mismatch ×2, each per-instance justified (§5) |
| F-P-2 | PASS | readback gate inside `write()`: written-file (ref,pad,net) == netlist both directions; 0 unbound live pads |
| F-P-3 | PASS | every footprint comes from the CP2-gated netlist; `[exact-part]` contract covers J1/J2/J3/J-USB/U1/F1 and caught the D39 J2 swap in flight |
| F-P-4 | PASS | outline 85×65 + 4× M3 @ (4,4)(81,4)(4,61)(81,61) per cp1_display_side §2; envelope plot confirms bodies inside it |
| F-P-5 | PASS | parity gate: 39/39 placed, 0 extra (hard fail) |
| F-P-6 | PASS | pad-net binding is by pad number, so rotation cannot swap nets; J1 opening direction probed, not assumed (§9.1 F01) |
| F-P-7 | PASS | fab gate on the written board: min drill 0.3, annular ≥0.13, copper-edge 0.3; DRC copper_edge_clearance 0 |
| PR-1 | PASS | refdes on the correct silk layer per side, back-side text mirrored; H1–H4 hidden. **Corrected at iteration 6 (F09):** this row read PASS while J1's designator was in fact hidden under U1's body — the board→local inverse for property text disagreed with the writer. Now proven by a round-trip assertion (emitted anchor == the point auto_refdes chose) plus a refdes-vs-body gate, both poison-tested on this exact case, and confirmed in the re-rendered bottom view where J1 reads clear of U1. |
| PR-2 | PASS | on-body placement is last resort; every refdes sits beside its part. **Was previously asserted without checking the back side** (F09) — the claim is now mechanically enforced by `refdes_over_body_findings()` at the write chokepoint, not just eyeballed, and re-verified in both rendered faces. |
| PR-3 | PASS | `silk_overlap` 0 in the fresh report |
| PR-4 | PASS | `silk_over_copper` 0 in the fresh report |
| PR-5 | PASS | verified in the iteration-1 crops + the envelope plot |
| PR-6 | PASS | text angles normalised 0/90; back-side text mirrored so it reads correctly from the back |
| PR-7 | PASS | §3 floorplan follows the enclosure story; USB chain runs N from the SE connector, RS-485 front end west of the module |
| PR-8 | PASS | 3V3 decouplers C3/C4/C6/C7 in a row immediately south of MOD1's courtyard edge; each button's 100 nF sits beside its switch |
| PR-9 | PASS | §3 + D8/D27/D40: J1 west (in-wall Cat5e), J2 north (short module cable), buttons south at 24/42/60, USB-C front face |
| PR-10 | PASS | RS-485 A/B adjacent J1→TVS2→U2; USB D± through inline U-ESD; SPI grouped on J2's north edge |
| PR-11 | PASS | `solder_mask_bridge` 0 of any name in the `--severity-all` report |
| PR-12 | PASS | same evidence as F-P-3 |
| PR-13 | PASS | Debug/programming path for **this** board: **J-USB** (72, 57) is the ESP32-S3's **native USB**, which carries the built-in USB Serial/JTAG peripheral on the dedicated D+/D− pins — so USB debugging costs no GPIOs here; and **J3** (78, 44) is the keyed 2×3 ESP-Prog header (§4.8), the USB-independent force-download/recovery path for a board that deep-sleeps between frames. Both sit on the front face, reachable once the faceplate and e-paper module come away (D27/D40). **Corrected at iteration 8 (F12):** the previous row imported the BATTERY board's DR-31 CAN/JTAG-forfeit rationale — this board has **no CAN** (zero TCAN/CAN_PWR references in the display generator, checked) so that trade never applied here — and it miscounted **J5** as a debug header; J5 is the RS-485 termination lift jumper (cp1_display_side §4.5), not a debug interface. |

**Mechanical criteria specific to CP4** (this board is mechanics-led):

| Criterion | Status | Evidence |
|-----------|--------|----------|
| depth stack | PASS | driver = J-USB 9.30 mm (drawing p.1) → gap ~9.7 mm, total ~34.7 mm vs ~45 mm usable; envelope plot carries every height with its source |
| plunger reach | PASS | 9.7 + 3 + 2.3 = 15.0 mm = catalog height `150`, protrusion inside the ~2–3 mm spec |
| service access | PASS | D40 vertical USB-C opens +Z, reachable with faceplate + module removed; J3 on the front beside it |
| back-side geometry | PASS | writer and gates share ONE mirror (core._xf); parts land at requested centres with 0.00 error; guard rejects a re-implemented mirror on either axis (F08) |

## 8. Reviewer findings

### 8.1 Reviewer findings (iteration 1)

Reviewed commit: `ff1da386ca286dddfc0d3c0a0ade1b95e31111b9`

#### Finding 01 - BLOCKER - back-side center placement is still using the retired mirror axis, and J1 does not face west

The mandatory rebuild-first precondition fails. The documented display build
returns exit 1 on its own J1 orientation gate, and the full handoff check
rebuilds both schematics and the battery PCB successfully before failing on
the display PCB with the same finding.

The failure exposes a real committed-placement defect. `core._xf()` and
`_flip_to_back()` correctly mirror local Y, but `build_display_pcb.py:cc()`
still negates local X when centering a back-side footprint. Independent
recomputation therefore puts J1's requested courtyard center `(9.8, 46.5)` at
`(16.15, 28.06)` and U1's requested `(22, 41)` at `(26.97, 45.50)`. J1 also
remains at 0 degrees: its locating posts and signal row differ along board Y,
so its connector axis is north/south, not west. The current assertion compares
the signal-row X centroid with a symmetric courtyard X centroid; those are
equal by construction and do not encode the opening direction.

A scratch probe with the correct back-center transform and J1 rotated 90
degrees puts the locating posts west of the signal row, but then reveals three
real conflicts: BTN1 through-pads into J1, J1 through-pads into R5, and J1's
courtyard into U1. This cannot be fixed by weakening the assertion.

Required resolution: make center placement use the same mirror-Y transform as
the writer/gates; orient J1 from a probe that compares the locating-post/body
direction with the signal row; then re-place J1, U1, BTN1/R5 as required until
the corrected through-pad/courtyard gates and DRC are clean. The bare Windows
build and full handoff check must both exit 0 before the next handoff.

#### Finding 02 - IMPORTANT - two CP4 BOM SKU cells order the rejected physical variants

Live `/resolve` checks contradict the display BOM:

- J2 Digi-Key `455-1710-ND` resolves exactly to **B8B-PH-K-S**, the rejected
  top-entry header, not the selected side-entry S8B part. The verified active,
  in-stock S8B code is **`455-1725-ND`**.
- J-USB Mouser `640-USB4085-GF-A` resolves exactly to the retired edge-mount
  **USB4085-GF-A**, not vertical USB4115. The verified USB4115 Mouser code is
  **`640-USB4115-03-C`**.

The Digi-Key USB4115 code resolves correctly, and the button code resolves to
the intended TS02 variant. Related propagation is incomplete:
`cp1_display_side.md` still calls J-USB the edge-mount USB4085, and the J2 BOM
description says `S8B` for both top and side entry instead of B8B/S8B. The
mandatory consistency checker exited 0 despite all of these live
contradictions.

Required resolution: replace both wrong SKU cells, correct the stale J-USB and
J2 prose, add the superseded object/SKU tokens to the persistent consistency
coverage, and poison-test that the checker rejects reintroduction of either
wrong-order object.

#### Finding 03 - IMPORTANT - the visual/3D evidence omits the load-bearing mechanical bodies

The committed designer renders and fresh reviewer renders agree: J1 and the
new J-USB render as pads/courtyards only, with no connector body. J1 references
`${WE_3DMODEL_DIR}`, which is neither repo-bound nor present in the render; the
stock USB footprint references a STEP absent from this KiCad 10 model install.
BTN1-3 use `SW_PUSH_6mm_H13mm`, so the rendered body is 13 mm while the selected
TS02 actuator is 15 mm. These are exactly the parts that establish cable-entry
direction, the 9.7 mm front gap, the 13.6 mm back depth, and faceplate reach.

Required resolution: provide deterministic 3D bodies for J1, J-USB, and the
15 mm button variant, or committed dimensioned envelope geometry that appears
in the reviewer-visible top/bottom outputs. Re-render both faces and complete
the binary D13 scorecard; deferring the scorecard leaves CP4's mechanical
claims without the mandatory eye-at-crop-zoom layer.

#### Finding 04 - IMPORTANT - the TS02 footprint is compatible-looking, not the claimed exact match

The on-file Same Sky drawing specifies a 6.5 x 4.5 mm, four-drill **1.0 mm**
recommended pattern. The stock KiCad footprint has the same centers but uses
**1.1 mm** drills. Its 2.0 mm pads still leave a 0.45 mm annular ring and the
largest 0.8 mm terminal has 0.3 mm diametral clearance, so the substitution is
plausibly sane; it is simply not identity evidence.

Required resolution: replace every "exact match" claim with an explicit
1.0-to-1.1 mm deviation and a stated tolerance/assembly acceptance, or vendor
the exact recommended drill pattern. Keep the verified pin grouping and
6.5 x 4.5 mm centers on record.

Coverage: `doc_consistency_check.py` passed; the documented rebuild and full
handoff gate were run through the failing transcript; board/netlist blob hashes
were independently reproduced; direct KiCad DRC found only the two documented
footprint mismatches plus 123 expected unrouted items; KiCad exported all 39
component placements; the back-side mirror was corroborated by the absence of
J1/U1 library mismatches; the circular-courtyard checker was poison-tested;
fresh top/bottom 3D renders, two fitted 2D geometry plots, and eight crop views
were inspected; and four on-file manufacturer PDFs were checked directly.
Routing-quality gates remain outside CP4 scope. Evidence is in
`visual_inspections/cp4-display-placement/iter1/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES - 1 blocker, 3 important.


### 8.2 Reviewer findings (iteration 3)

Reviewed design commit: `1a357eaa75c69198713498393e31f8a1cf7ad70e`.
Host-only reviewer patch: `80387419563e6dcc2a6baf6006e0461db10ca22f`.

The F01 placement/orientation repair passes a fresh Windows rebuild, the
designer's analytic gates, an independent serialized-board AABB model, and
reviewer inspection at crop zoom. Both F02 replacement SKU cells resolve
exactly to their selected MPNs. F03's dimensioned envelope geometry is present
and readable, and F04's 1.0-to-1.1 mm drill substitution is now stated and
supported by the on-file drawing. The new findings below are limited to
completion and regression-gate defects introduced or left open by iteration 2.

#### Finding 05 - IMPORTANT - the mandatory D13 scorecard is still deferred, and its DRC count is stale

**Issue**: Packet section 7 still says the D13 scorecard is deferred even though
iteration 1 Finding 03 explicitly required the binary scorecard before CP4 could
close. Packet section 5 also describes the final DRC state as one
`lib_footprint_mismatch`; the fresh report contains two, J-USB and MOD1. Section
4.5 documents the added J-USB mismatch and its 30/30 pad-diff evidence, so this
is a stale count rather than an unjustified footprint, but it prevents the
required one-row-per-criterion sign-off from being audited.

**Evidence**: `decisions.md` D13 lines 692-700 require every packet to include
an explicit PASS/FAIL row for each applicable F-/SR-/PR- criterion. Packet
section 7 remains "Deferred to iteration 2." Fresh reviewer evidence
`visual_inspections/cp4-display-placement/iter3/reviewer/drc.rpt` reports
`lib_footprint_mismatch` x2 at J-USB and MOD1.

**Suggested fix**: complete section 7 with every applicable F-P and PR criterion
as binary PASS/FAIL plus evidence, and update section 5 to the actual two
per-instance-justified mismatch warnings. Do not substitute a prose summary for
the D13 table.

#### Finding 06 - IMPORTANT - both corrected BOM rows swallowed the following component row

**Issue**: The order codes corrected for F02 are right, but each edit merged the
next component onto the same physical Markdown row. `C6` now appears after the
J2 notes on line 290, and `U-ESD` appears after the J-USB notes on line 314.
Those refs no longer have independent table rows, and the new row-scoped
coherence checker exits 0 on the malformed table.

**Evidence**: `hardware/layout/cp1_bom.md:290` contains both J2 and C6 fields on
one physical row; line 314 contains both J-USB and U-ESD fields on one physical
row. The mandatory
`doc_consistency_check.py` returned exit 0 at the start of this pass. The live
changed-cell audit independently returned exact matches:
`455-1725-ND -> S8B-PH-K-S` and `640-USB4115-03-C -> USB4115-03-C`; see
`visual_inspections/cp4-display-placement/iter3/reviewer/sku_resolve.txt`.

**Suggested fix**: restore C6 and U-ESD as separate Markdown rows without
changing the verified order codes. Extend the checker with table-shape
validation that enforces the header's column count and exactly one recognized
ref field per row, then poison-test both concatenations.

#### Finding 07 - BLOCKER - the RPA enforcement path crashed on Windows; reviewer patch awaits designer acceptance

**Issue**: After all four generators passed, `reviewer_patch_check.py` decoded
UTF-8 `git log` output with Windows cp1252 and crashed before returning a policy
verdict. The handoff wrapper consequently failed with only an opaque RPA exit.
This is host-limited, so reviewer patch `8038741` adds explicit UTF-8 decoding
to the text subprocess helpers in both enforcement scripts. It is tested but
unaccepted until designer review.

**Evidence**: The before transcript records the `UnicodeDecodeError` and
secondary `None.stdout` failure. The after transcript records direct RPA exit 0
and complete handoff exit 0 with all four rebuilds. Both are committed with the
patch under `visual_inspections/cp4-display-placement/iter3/reviewer/`.
The patch changes only two review-tool helpers and host evidence; deterministic
design artifacts remained byte-identical.

**Suggested fix**: inspect patch `8038741` line by line because it touches the
RPA enforcement surface. If accepted, add exactly
`RPA-ACCEPTED: F07 8038741` in the iteration-4 designer response. If rejected,
state the concrete issue and retain the finding; do not ask the macOS designer
to guess at another Windows encoding fix.

#### Finding 08 - IMPORTANT - the single-transform guard misses duplication of the actual transform

**Issue**: `assert_single_back_transform()` claims to reject any new module that
re-implements the back-side mirror, but its AST test only rejects self-negation
whose variable name ends in `x`. The correct project convention negates Y. A
temporary external `mirror_y = -mirror_y` duplicate passes, so the guard does
not enforce the invariant used to close the repeated F01 defect class.

**Evidence**: The current-tree control passes and an external
`mirror_x = -mirror_x` positive control is caught. The adversarial
`mirror_y = -mirror_y` poison is accepted. Transcript:
`visual_inspections/cp4-display-placement/iter3/reviewer/transform_guard_poison.txt`.
The implementation is at `hardware/kicad/pcb/core.py:1104-1135`.

**Suggested fix**: make the guard enforce ownership rather than the historical
wrong expression: reject external self-negation of either coordinate used as a
mirror (at minimum X and Y), while keeping `core.py` as the sole allowed owner.
Add the missed `mirror_y = -mirror_y` poison beside the existing positive test.

Coverage: mandatory consistency check exit 0; fresh display build exit 0; all
four full-handoff rebuilds exit 0 after the bounded Windows repair; direct DRC
reviewed; both changed SKU cells live-resolved; four manufacturer-PDF citation
checks completed; independent board-file geometry plus designer gates plus
eyes-at-crop-zoom completed; all eight reviewer crops and the envelope plot
inspected. Detailed evidence is in
`visual_inspections/cp4-display-placement/iter3/reviewer/REPORT.md`. Routing
quality remains CP5 scope; CP5 was not started.

**REVIEW COMPLETE**: NEEDS CHANGES - 1 blocker, 3 important. (See findings 05, 06, 07, 08.)


### 8.3 Reviewer findings (iteration 5)

Reviewed design commit: `f4ea4f1b95b8af35e23e713dc7ecec05e8e8bda9`.

The iteration-4 repairs for F06, F07, and F08 pass independent re-checks. The
BOM rows are structurally separate and both historical row mergers are caught
by the new table-shape gate; the accepted RPA patch is clean; and the external
transform-ownership guard catches four independent X/Y self-negation poisons.
F05 is only partly closed: its DRC count is corrected and a scorecard exists,
but two scorecard defects remain.

#### Finding 09 - IMPORTANT - J1's reference is hidden under U1, contradicting PR-1 and PR-2

**Issue**: The fresh bottom render has no visible `J1` reference. Independent
parsing of the serialized board places J1's B.SilkS reference anchor at
`(11.000, 47.325)` mm, inside U1's B.Fab body box
`(6.205, 43.750)..(17.805, 52.250)` mm. U1 therefore covers the J1 reference
after assembly. Section 7 nevertheless marks PR-1 and PR-2 PASS and says every
reference sits beside its part.

**Evidence**: The targeted render
`visual_inspections/cp4-display-placement/iter5/reviewer/render_bottom_j1_zoom.png`
shows U1 readable and J1's body with no visible `J1`. The independent
serialized-board probe and exact coordinates are in `j1_refdes_probe.py` and
`j1_refdes_probe.txt` beside that image. The source path is consistent with the
failure: `auto_refdes()` in `hardware/kicad/pcb/core.py` converts the selected
board point back to local coordinates and applies a back-side inverse that is
not verified by a board-to-local-to-emitted-board round trip. The current
post-write gate checks reference-to-reference adjacency, not reference text
against component bodies, so this overlap remains green.

**Suggested fix**: repair the back-side reference coordinate conversion from
the serializer's actual transform, and add a round-trip assertion that the
emitted reference anchor equals the board-space candidate selected by
`auto_refdes()`. Add a post-write gate for visible reference text against other
component body/courtyard geometry, poison-test this exact J1-under-U1 case, then
rerender both sides and correct PR-1/PR-2 from evidence. Do not patch only J1's
coordinates or assume which local axis to negate without the round-trip test.

#### Finding 10 - IMPORTANT - the mandatory D13 scorecard omits applicable criterion PR-13

**Issue**: Section 7 stops at PR-12. D13 explicitly defines PR-13, "Debug
headers placed per the design (UART debug, USB-OTG, SWD/JTAG if applicable),"
and requires one binary row for every applicable criterion. This display board
has debug header J3, so PR-13 is applicable and cannot be omitted.

**Evidence**: `hardware/layout/decisions.md` D13 lists PR-13 and requires every
applicable row at sign-off. Packet section 7 contains PR-1 through PR-12 only;
its own service-access row identifies J3 on the front, confirming applicability.

**Suggested fix**: add the PR-13 PASS/FAIL row with concrete J3 placement and
access evidence from the generated board and fresh render. Keep the criterion
in the mandatory table rather than relying on the separate mechanical prose.

Coverage: mandatory consistency check exit 0; fresh display build exit 0; all
four full-handoff rebuilds exit 0 with deterministic artifacts and RPA clean;
direct DRC reviewed; iteration-4 table-shape and transform guards independently
poison-tested; three on-file manufacturer-PDF citations spot-checked;
independent serialized-board geometry rerun; and fresh top/bottom renders,
eight quadrant crops, and targeted J1/USB zooms inspected. Detailed evidence is
in `visual_inspections/cp4-display-placement/iter5/reviewer/REPORT.md`. Routing
quality remains CP5 scope; CP5 was not started.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 2 important. (See findings 09, 10.)


### 8.4 Reviewer findings (iteration 7)

Reviewed design commit: `0b7ed2027653954973bf4eefec2cca7b3b1597b8`.

The physical F09 repair passes: a fresh committed-generator rebuild is clean,
the serialized J1 anchor is now `(11.000,19.025)` mm on B.SilkS and outside
U1, the independent placement AABB audit remains clean, and the fresh bottom
render shows both `J1` and `U1` readable. F10's missing row is present. The
remaining findings concern the claimed regression coverage and the factual
basis of that row.

#### Finding 11 - IMPORTANT - the new refdes gates do not judge emitted text geometry and miss all three independent poisons

**Issue**: `assert_refdes_roundtrip()` does not parse the emitted board despite
claiming to prove the emitted anchor. It applies `refdes_local_to_board()` to
the same in-memory override produced by its inverse partner, so a mutually
consistent but serializer-wrong pair passes. `refdes_over_body_findings()`
checks only whether the reference anchor is inside another body, not whether
the text rectangle overlaps it, and explicitly skips the reference's own
component. Packet PR-2 therefore incorrectly says this function mechanically
enforces the no-on-body criterion.

**Evidence**: The write chokepoint at `hardware/kicad/pcb/core.py:628-635`
passes `prop_overrides`, not emitted `text`, to both new gates. The round-trip
implementation at lines 987-1008 calls its coupled forward helper. The body
gate at lines 1031-1038 compares only `(bx,by)` and skips `other == ref`.
Independent transcript
`visual_inspections/cp4-display-placement/iter7/reviewer/refdes_gate_independent_poison.txt`
records three escapes: paired wrong transforms return no finding while the
serializer-frame anchor lands at the old bad `(11.000,47.325)` mm point; a
1.90 x 1.45 mm text box overlaps a body with its anchor 0.1 mm outside; and a
reference centered on its own body is ignored. Control evidence confirms the
current J1 artifact itself is fixed.

**Suggested fix**: parse each visible Reference property from the emitted
board text at the write chokepoint, including layer, board-space anchor, angle,
and full text box. Compare that parsed anchor to `_REFDES_SELECTED`, then test
the parsed text rectangle against both its own body and every other same-side
body. Keep the forward helper as a conversion utility, not as evidence of what
was emitted. Add the three independent poisons above as standing tests and
require each downstream gate to fail independently.

#### Finding 12 - IMPORTANT - PR-13 imports the battery board's CAN/JTAG rationale into the display board

**Issue**: The new PR-13 row says the display has no SWD/JTAG because its
ESP32-S3 JTAG pins were forfeited to the DR-31 CAN gate. DR-31's CAN block and
IO40/IO41/IO42 assignment belong to the battery board. The display has no CAN
block and retains native USB-JTAG through J-USB. J5 is an RS-485 termination
jumper, not a debug header.

**Evidence**: `hardware/layout/decisions.md` DR-31 identifies battery U7/J6
CAN and the battery J5 UART path. The display pin map in
`hardware/layout/cp1_display_side.md` section 6 instead assigns GPIO19/20 to
native USB at J-USB and identifies GPIO3 as the USB-JTAG-select strap; D27
defines J-USB as the display's native-USB bench/recovery port. The exported
display netlist contains J-USB and J3 and no U7 or CAN net. Detailed trace:
`visual_inspections/cp4-display-placement/iter7/reviewer/pr13_trace.md`.

**Suggested fix**: keep PR-13 PASS on the actual display evidence: J3 provides
keyed ESP-Prog UART/forced-download recovery and J-USB provides native USB
flash, serial, and JTAG after the faceplate is removed. Remove the battery CAN
claim and the unrelated J5 termination jumper from this row.

Coverage: published/installed skill hashes matched; mandatory consistency
check exit 0; fresh display build exit 0; full four-generator handoff CLEAN;
direct strict KiCad DRC completed with the documented two footprint warnings
and 123 placement-only unconnected items; accepted RPA patch clean; actual J1
serialized geometry and independent AABB model checked; fresh full top/bottom
renders plus J1/U1 and J3/J-USB crop zooms inspected; three new gates poisoned
independently; and four on-file manufacturer-PDF citations spot-checked. No
manifest row or SKU cell changed in iteration 6. Connectivity did not change;
CP5 was not started. Evidence is in
`visual_inspections/cp4-display-placement/iter7/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 11, 12.)


### 8.5 Reviewer findings (iteration 9)

Reviewed design commit: `24deb4ae8bf6d5f348816f34fde2287fb7b92c86`.

F11's actual repair now passes independent re-check: both gates consume the
emitted board, the clean control is clean, all four prior poisons are caught,
and MOD1's body independently parses as 18.00 x 25.50 mm. Fresh renders and
the serialized J1 probe remain clean. F12 also passes: PR-13 now describes
this display board's J3 ESP-Prog and J-USB native USB Serial/JTAG paths without
the battery CAN or J5 claims. Two new evidence/gate issues remain.

#### Finding 13 - IMPORTANT - the pcbnew oracle silently accepts missing expected pads and checks only 97 of 191 net-bound pads

**Issue**: `pcbnew_crosscheck.py` treats an expected pad that KiCad cannot find
as success: `got` remains `None`, and only `got is not None and got != net`
fails. The generator also truncates every component to its first four pins.
The resulting “97 pad-nets agree” message is not a complete independent
pad-to-net check, and it counts an absent expected pad as agreement.

**Evidence**: `hardware/kicad/pcb/core.py:1180` applies `[:4]` while building
the expected map; `hardware/reviews/tools/pcbnew_crosscheck.py:55-65` silently
passes no matching pad. A KiCad-engine count on the committed board reports
216 pads, 191 net-bound. The oracle receives 97. Independent positive control
with existing J1.1 and a wrong expected net fails correctly, but expected
`J1/NO_SUCH_PAD` returns exit 0 and prints “1 pad-nets agree.” Transcript:
`visual_inspections/cp4-display-placement/iter9/reviewer/pcbnew_missing_pad_poison.txt`.

**Suggested fix**: remove the first-four truncation and send every expected
net-bound pin. In the oracle, collect all board pads matching the expected pad
number; fail if the set is empty, and fail if any matching pad has the wrong
net. Report the number actually found and compared, and assert it equals the
expected-map count. Retain both the wrong-net positive control and the
missing-pad poison.

#### Finding 14 - IMPORTANT - the committed iteration-8 poison transcript still asserts the retracted phantom defects and manual fixes

**Issue**: `iter8/refdes_gate_poison_v2.txt` ends by asserting that J-USB and
TVS2 were “Two real defects” fixed with `MANUAL_REFDES`. The packet now
correctly retracts that claim as a parser artifact, and the current generator
explicitly has `MANUAL_REFDES = {}`. The evidence artifact therefore leaves a
false live conclusion on record without a superseded marker.

**Evidence**: The final four lines of
`visual_inspections/cp4-display-placement/iter8/refdes_gate_poison_v2.txt`
make the false claim. Packet section 9.4 says no real on-body defect existed
and the overrides were removed; `hardware/kicad/pcb/build_display_pcb.py:274`
confirms the map is empty. The mandatory consistency checker exits 0 despite
this contradiction.

**Suggested fix**: regenerate the transcript from the corrected gate or mark
the false paragraph explicitly `SUPERSEDED` with a pointer to the final
control/poison results and retraction. Add a targeted consistency assertion or
superseded-token entry so the old “Two real defects” / manual-override claim
cannot return unnoticed.

Coverage: published/installed skill hashes matched; mandatory consistency
check exit 0; fresh display build exit 0; full handoff was run bare and CLEAN
across all four generators; direct strict KiCad DRC completed with the two
documented footprint warnings and 123 placement-only unconnected items; RPA
clean; emitted-refdes gates independently re-poisoned; pcbnew oracle tested
with positive and negative controls; independent serialized-board AABB and J1
probe passed; fresh full top/bottom renders plus J1/U1 and J3/J-USB crop zooms
inspected; and four on-file manufacturer-PDF citations checked. No manifest
row, SKU cell, connectivity, or selected part changed. CP5 was not started.
Evidence is in
`visual_inspections/cp4-display-placement/iter9/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 13, 14.)


### 8.6 Reviewer findings (iteration 11)

Reviewed designer commit: `fa2541b1fa05c686f64c481c5f8e572e2e378c2d`.

F13 is materially improved: the fresh generator control covers all 191
net-bound pads, and independent missing-pad, wrong-net, and nonempty-subset
poisons now fail. F14 is closed: the supersession banners are correctly
placed and the new retraction checker passes independent positive, negative,
and reviewer-evidence exclusion controls. The side parser and
single-transform source-coverage guard also pass their independent poisons.
The broader vacuous-pass claim is not yet closed.

#### Finding 15 - IMPORTANT - two changed gates still certify empty input as clean

**Issue**: The pcbnew oracle's new coverage comparison runs only when
`expected_pads` is nonempty. On the real display board, an entirely empty
expected object therefore exits 0 while explicitly reporting 0 references,
0 sides, and 0 of 191 net-bound pads as clean. Separately,
`refdes_over_body_findings("")` still returns an empty finding list. The
iteration-10 addendum says this literal empty-input escape was fixed and the
class swept, but both changed gates still have the vacuous-pass condition.

**Evidence**: `hardware/reviews/tools/pcbnew_crosscheck.py` guards the board
coverage failure with `if expected_pads and compared < board_bound`.
Independent KiCad-engine poison `empty_expected.json` exits 0 with
`CROSSCHECK: clean — 0 references, 0 sides, 0 pad-nets (of 191 net-bound
pads KiCad sees)`. Independent direct invocation of
`refdes_over_body_findings("")` returns `[]`; its new checks are all
conditional on first parsing at least one footprint or reference. Controls
show the intended repairs do work for nonempty inputs: missing pad, wrong net,
and one-pad subset exit 1; a front footprint containing an early B.Cu graphic
stays front; and `assert_single_back_transform()` rejects an empty source
tree. Transcripts and probes:
`visual_inspections/cp4-display-placement/iter11/reviewer/pcbnew_oracle_recheck.txt`
and `gate_delta_probe.txt`.

**Suggested fix**: In the pcbnew oracle, remove the truthiness guard and
require exact coverage equality against KiCad's net-bound-pad count; also
anchor reference and side-map coverage to an explicit expected component set
so an empty upstream object cannot certify a populated board. In the refdes
body gate, make zero parsed footprints a hard coverage finding (preferably
compare parsed footprint/reference/body sets against the caller's expected
component set). Retain literal-empty controls for both gates alongside the
existing nonempty poisons.

Coverage: installed skills synchronized to kicad 0.8.0 / pcb-design 0.17.0;
mandatory consistency check clean; fresh Windows display build exit 0; full
handoff run bare and CLEAN across all four generators; direct strict DRC
completed with only the two documented footprint warnings and 123
placement-only unconnected items; F13/F14 and class-sweep changes independently
re-poisoned; independent serialized-board geometry and J1 reference probes
passed; fresh top/bottom renders plus J1/U1 and J3/J-USB crop zooms inspected;
and four on-file manufacturer-PDF citations/object identities checked. Board
blobs remain byte-identical to the previously inspected SHA256 values. No
manifest row, SKU cell, connectivity, or selected part changed. CP5 was not
started. Evidence is in
`visual_inspections/cp4-display-placement/iter11/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 15.)


### 8.7 Reviewer findings (iteration 13)

Reviewed designer commit: `ceeff2cddce88647e91694e1e75a48ffdbe5289d`.

F15's literal-empty cases are fixed: the entirely empty oracle object now
fails with two findings, and empty board text produces findings from the
body, round-trip, and new parse-coverage gates. The full expected control
remains clean. Exact-set poisons show that the new caller-anchored invariant
is still implemented as nonempty/cardinality checks rather than set equality.

#### Finding 16 - IMPORTANT - partial and same-size wrong sets still satisfy the new exact-coverage gates

**Issue**: The oracle accepts one reference position for 39 expected
components, accepts a 39-entry side map that omits an expected component and
substitutes a mounting hole, and accepts a same-size pad map that replaces a
required net-bound pad with an unrelated unbound pad. The parse chokepoint
similarly accepts one visible reference box for 39 expected components. These
are nonempty/cardinality versions of the same vacuous-pass class F15 was meant
to close.

**Evidence**: In `hardware/reviews/tools/pcbnew_crosscheck.py`, refdes coverage
is only `not exp.get("refdes")`; side coverage compares lengths rather than
keys; and pad coverage compares only physical counts. Independent poisons
against the fresh board all exit 0:

- refdes map reduced from 39 entries to C1 only: `clean — 1 references`;
- side map kept at 39 entries but replaced expected C1 with board-only H1:
  `clean — 39 sides`;
- pad map kept at 169 keys but replaced required net-bound `C1/1 ->
  V12_PROT` with unrelated unbound `J-USB/A10 -> ''`: `clean — 191
  pad-nets` because the number compared remains 191.

In `assert_board_parse_coverage()`, reference boxes are checked only for
total emptiness. Hiding 38 of the 39 expected component references leaves one
box and all 39 bodies; both parse coverage and
`refdes_over_body_findings(..., expected_refs=...)` return no findings.
Reproduction artifacts and exact expected/poison objects are in
`visual_inspections/cp4-display-placement/iter13/reviewer/`, especially
`pcbnew_oracle_exact_set.txt` and `partial_coverage_probe.txt`.

**Suggested fix**: Treat identity as the invariant, with counts only as
diagnostics. Require exact key equality between the caller's component set
and the refdes and side maps (with any hidden/mechanical exceptions explicit),
and require the board footprint set to equal expected components plus an
explicit mechanical-ref set. For pads, build KiCad's net-bound
`(ref, pad-number) -> net-name multimap`; require its key set to equal the
expected pad key set, reject empty expected net names, and require every
physical occurrence's net to match. At the parse chokepoint, require the
visible reference-box key set and body key set to equal their caller-supplied
expected sets. Retain all three partial/same-cardinality poisons; they target
the invariant that the literal-empty cases do not exercise.

Coverage: skillz synchronized and pcb-design 0.18.0 installed; mandatory
consistency check clean; fresh Windows display build exit 0; full handoff run
bare and CLEAN across all four generators; direct strict DRC completed with
only the two documented footprint warnings and 123 placement-only
unconnected items; literal-empty controls and exact-set poisons independently
executed; independent serialized-board geometry and J1 reference probes
passed; fresh top/bottom renders plus J1/U1 and J3/J-USB crop zooms inspected;
and four on-file manufacturer-PDF citations/object identities checked. Board
blobs remain byte-identical to the previously inspected SHA256 values. No
manifest row, SKU cell, connectivity, or selected part changed. CP5 was not
started. Evidence is in
`visual_inspections/cp4-display-placement/iter13/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 16.)


### 8.8 Reviewer findings (iteration 15)

Reviewed designer commit: `f1c1a20194f2137493f4fa075de4d8508c6985ae`.

F16 is closed. A fresh caller-emitted expectation passes, while the prior
1-of-39 refdes map, same-size wrong side set, same-size wrong pad set, wrong
declared mechanical set, literal-empty object, and 38-hidden-reference parse
all fail independently. The new courtyard and outline zero-geometry checks
also catch an independently blinded footprint. One adjacent conditional gate
still infers its own expected scope from the artifact it judges.

#### Finding 17 - IMPORTANT - the edge-marker mating-plane gate still passes when its expected marker disappears

**Issue**: `gate_edge_markers()` silently continues when a loaded footprint
contains no `PCB Edge` text. The battery generator explicitly relies on this
gate to enforce J3's USB-C mating plane, but neither the gate nor its caller
declares that J3 must contribute a marker. A footprint/parser regression that
removes the marker therefore disables the entire placement check and reports
clean.

**Evidence**: `hardware/kicad/pcb/core.py::gate_edge_markers()` derives
`texts` from each loaded footprint and executes `if not texts: continue`.
`hardware/kicad/pcb/build.py` states that J3's `PCB Edge` line must land on
x=100 and that this gate enforces it. Current-library inventory from the
fresh CP2 netlist shows seven `OVERHANG_OK` refs, but only J3 carries a marker:
MOD1/J1/J2/J6/J10/J11 each have zero, J3 has one. Therefore `OVERHANG_OK`
cannot itself be treated as the marker contract. Independent poison creates a
caller-declared east-edge X1 and supplies a markerless loaded footprint;
`gate_edge_markers()` returns no findings. Reproduction and inventory:
`visual_inspections/cp4-display-placement/iter15/reviewer/identity_recheck.py`
and `edge_marker_scope.txt`.

**Suggested fix**: Add an explicit caller-owned `edge_marker_refs` set
(`{"J3"}` for the battery board, empty for the vertical-USB display board),
record the refs whose loaded footprints actually provide `PCB Edge`, and
require exact set equality before checking marker geometry. Retain the
markerless-expected-ref poison and a same-size substitution poison so the
gate proves identity rather than mere marker presence.

Coverage: skillz synchronized and kicad 0.9.0 / pcb-design 0.19.0 installed;
mandatory consistency check clean; fresh Windows display build exit 0; full
handoff run bare and CLEAN across all four generators; direct strict DRC
completed with only the two documented footprint warnings and 123
placement-only unconnected items; all F13/F15/F16 identity poisons and the
new courtyard/outline poisons independently executed; independent
serialized-board geometry and J1 reference probes passed; fresh top/bottom
renders plus J1/U1 and J3/J-USB crop zooms inspected; and four on-file
manufacturer-PDF citations/object identities checked. Board blobs remain
byte-identical to the previously inspected SHA256 values. No manifest row,
SKU cell, connectivity, or selected part changed. CP5 was not started.
Evidence is in
`visual_inspections/cp4-display-placement/iter15/reviewer/REPORT.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 17.)


## 9. Designer responses

### 9.1 Responses to §8.1 (iteration 2, 2026-08-06)

**Finding 01 (BLOCKER): AGREE — reproduced exactly, fixed at root.** `cc()`
in **both** PCB builds still negated local X while the writer and gates
negate Y. Your numbers reproduce to the digit: J1 requested (9.8, 46.5)
landed at (16.15, 28.06); U1 (22, 41) at (26.97, 45.50).

This is the **fourth** site of one transform, and the one I never swept —
after twice claiming I had. So the fix is not an axis edit: `cc()` now
delegates to `core._xf`, leaving the project exactly **one** back-side
transform. A duplicated transform was the defect; sharing it is the repair.

You were also right that the J1 assert was tautological — it compared two
symmetric X centroids, equal by construction. Replaced with a real probe: the
signal pads sit at one end of the footprint and the body extends away from
them, so the pads-to-courtyard-centre vector *is* the opening direction. J1
is now rot 90 on the back and that vector reads **(-7.95, +0.00)** — due
west. Re-placed for the three conflicts your scratch probe predicted (BTN1
into J1 pads, J1 pads into R5, J1 courtyard into U1): J1 (11, 30), U1
(12, 48), U2 (25.5, 33.5), R2 (27, 29). Parts now land at their requested
centres with 0.00 error; all gates and DRC clean.

*On the discrepancy:* the build exits **0** here, before and after the fix. I
could not reproduce an exit-1 on macOS at the reviewed commit, so I cannot
explain your transcript — but the defect you diagnosed was real and is fixed,
and the corrected assert now fails loudly if J1 is ever not west-facing.

**Finding 02 (IMPORTANT): AGREE — both cells would have ordered the wrong
object.** Confirmed by live `POST /resolve`: `455-1710-ND` resolves to
B8B-PH-K-S (the rejected top-entry part) and `640-USB4085-GF-A` to
USB4085-GF-A (the retired edge part). Two separate incomplete propagations:
D39 changed the MPN text but never re-resolved the order code, and D40
updated one distributor column and not the other. Both corrected, along with
the stale J-USB prose in `cp1_display_side.md` and the J2 description that
read "S8B" for both entry styles.

Persistent coverage added as a **row-scoped** check rather than a SUPERSEDED
token: the battery J3 legitimately orders USB4085 through that same Mouser
code, so a global token rule would fire on a correct row — the CP3
manifest-uniqueness false-positive trap. Poison-tested both directions with a
control (`iter2/row_coherence_poison.txt`). One further change your finding
implies: the superseded order codes are no longer quoted **anywhere** in the
BOM, even as history — a wrong order code does not belong in an orderable
document. My first attempt at those history notes tripped my own new check,
which is how I noticed.

**Finding 03 (IMPORTANT): AGREE.** Verified: J1 points at Wurth's own
`WE_3DMODEL_DIR` variable (unbound in this install), the stock USB footprint
names a STEP absent from this KiCad 10 install, and the buttons carry the H13
model against a 15 mm selection. Taking your second option — committed
dimensioned envelope geometry — as more deterministic than hand-authored
solids: every height-critical part now carries a **Cmts.User envelope
rectangle plus a height label sourced to its datasheet**, and a
`doc_envelopes.svg` / PDF plot exports them. J1 13.6 (B), U1 11.0 (B), J-USB
9.30 (F), J3 9.10 (F), J2 7.60 (F), BTN1-3 15.0 (F).

That plot immediately earned its keep: it showed the board still carrying
**"Antenna KEEP-OUT ZONE"** on Cmts.User from the stock ESP32 footprint —
asserting in the board documentation precisely the constraint D26 retired and
D39 built a variant to drop. Removed from the variant (the factual "Antenna"
label stays); provenance recorded in the footprints README.

**Finding 04 (IMPORTANT): AGREE, and this is the worst of the four.** The
datasheet specifies 4 x 1.0 mm drills; the footprint uses 1.1 mm. **My own
console output printed `drill 1.1` on the same screen where I wrote "exact
match".** That is a verification adjective contradicted by evidence in front
of me — the precise failure my own skills tell me to hunt. Every "exact
match" claim is replaced with the stated deviation plus an acceptance
argument: centres match exactly; the 0.7 +/-0.1 mm terminal leaves >=0.3 mm
diametral clearance in a 1.1 mm hole, and the 2.0 mm pad keeps a 0.45 mm
annular ring, far above the 0.13 mm fab floor. A sane substitution, **not
identity evidence** — vendoring an exact-pattern footprint is available at
CP5 if wanted.

### 9.2 Responses to §8.2 (iteration 3, 2026-08-06)

**Finding 05 (D13 scorecard deferred + stale DRC count): AGREE on both.**
Deferring the scorecard was wrong on its own terms — D13 requires the table
in *every* packet, and iteration-1 F03 had already said so. §7 now carries
one binary row per applicable F-P/PR criterion with evidence, plus a
CP4-specific mechanical block (depth stack, plunger reach, service access,
back-side geometry), since this board is mechanics-led. §5's count is
corrected from ×1 to **×2** — §4.5 added the J-USB mismatch and I never
updated the summary. Both are per-instance justified with pad-diff evidence
(62/62 MOD1, 30/30 J-USB).

**Finding 06 (both corrected rows swallowed the next component): AGREE —
this is data corruption I introduced.** The iteration-2 Δ-note rewrite used
`re.S`, so `.` matched across the newline and the lookahead ran on into the
following row: C6 and U-ESD stopped having rows of their own. Restored from
`git show c961ccb~1` and verified **byte-identical** to the pre-corruption
text, so the verified order codes are untouched.

You were right that the row-scoped checker exited 0 on the malformed table —
it only inspected the row it could find, so a swallowed row was invisible to
it. Added `check_bom_table_shape()`: every data row must match its header's
column count and must not contain a second component row. Poison-tested by
reproducing exactly the corruption I caused (merge C6 up, merge U-ESD up) —
both now fail, control clean (`iter3/bom_shape_poison.txt`). The shape check
also found one **pre-existing** malformed row (TVS2 carried a stray extra
column); folded into the notes cell with content preserved.

**Finding 07 (Windows cp1252 crash in RPA enforcement): patch
`8038741` REVIEWED AND ACCEPTED.**
RPA-ACCEPTED: F07 8038741

Re-reviewed per the policy rather than rubber-stamped. The premise holds:
`git log` output is UTF-8, Windows Python decodes with cp1252 by default, and
the crash lands before the gate can return a verdict — the same
"UTF-8 is a per-call obligation" class as CP3 F01. The patch is minimal and
correctly placed: `encoding="utf-8", errors="replace"` on the text-mode
subprocess helper in both enforcement scripts.

I swept for what it missed, which is my job here. One `subprocess.run` in
`handoff_check.py` still has no `encoding=` — `head_blob()` — and that is
**correct**: it runs in binary mode deliberately, because its bytes are
compared against the worktree byte-for-byte. Decoding it would break the
comparison. No other text-mode subprocess remains unencoded. Zero-delta held
(the gate reported PENDING, not VIOLATION).

**Finding 08 (guard misses the actual convention): AGREE, and the mistake is
instructive.** I wrote the guard against the *shape of my historical error*
(`…x = -…x`) instead of against the invariant, so a duplicate of the
convention actually in use (`mirror_y = -mirror_y`) sailed through — a guard
that would have caught the last bug but not the next one. Rewritten to
enforce **ownership**: any self-negation of a coordinate-like name outside
`core.py` is rejected, whichever axis it picks. Poison-tested on four
variants (`mirror_x`, `mirror_y`, `my`, `px`) — all caught, control clean
(`iter3/transform_guard_poison.txt`).

### 9.3 Responses to §8.3 (iteration 6, 2026-08-06)

**Finding 09 (J1's reference hidden under U1): AGREE — and your instruction
not to guess an axis is what found the real bug.**

I built the round trip before touching anything. It showed the emitted local
value round-trips through the file correctly, but that my own board-space
computation put J1's anchor at (29.44, 47.32) while your probe measured
(11.000, 47.325). Tested against your measured value, only **no mirror**
reproduces it.

The reason, once measured, is structural — two frames, one rule wrongly
applied to both. The GATES read the library footprint (unmirrored) and
predict where pads land, so they need `_xf`'s mirror. But `_flip_to_back`
has already mirrored pads and graphics **into the file**, and the Reference
property is substituted afterwards by `_restore_properties`, so KiCad
applies its stored value as anchor + rot(local) with **no further mirror**.
Applying one put the designator under U1.

The round trip then exposed what inspection had not: `auto_refdes` carried
**two** hand-rolled inverses — a manual-spot path and a greedy path — and my
earlier fix corrected only one. J1 goes through the other. Same duplication
class as F08, this time inside a single function. Fixed with one owner,
`refdes_board_to_local()`, plus a forward partner, both call sites routed
through it.

Two gates added at the write chokepoint, as specified:
- `assert_refdes_roundtrip()` — the emitted anchor must equal the board point
  `auto_refdes` actually chose. This is what makes the class unguessable
  rather than reasoned about.
- `refdes_over_body_findings()` — reference text against other components'
  bodies **on the same side**. The old label-adjacency gate compared refdes
  to refdes and never noticed a designator sitting on a part.

Poison-tested on your exact case (`iter6/refdes_gate_poison.txt`):
reinstating the old mirror reproduces `J1 reference anchor (11.00,47.32)
sits inside U1's body (6.21,43.75)..(17.80,52.25)` — your coordinates — and
both gates fire; control clean. Re-rendered: J1 now reads clearly on
B.SilkS above its own body, well clear of U1.

**PR-1 and PR-2 corrected from evidence, not re-asserted.** Both rows now
record that they read PASS while the back side was in fact wrong, and both
now rest on a mechanical check at the chokepoint rather than on my eye. That
was the substance of the finding: the scorecard claimed something no gate
was testing.

**Finding 10 (PR-13 omitted): AGREE.** Added with evidence — J3 ESP-Prog on
the front at (78, 44) and the vertical J-USB at (72, 57), both reachable
once the faceplate and module come away (D27/D40), plus J5's termination
jumper. ***Superseded at iteration 8 (F12): that justification was wrong.***
It imported the BATTERY board's DR-31 CAN/JTAG-forfeit reasoning into a board
that has no CAN at all, and counted J5 — the RS-485 termination lift — as a
debug header. The corrected row is in §7. D13 says one row per *applicable* criterion, and applicability was
mine to determine — stopping at PR-12 was me truncating the table.


### 9.4 Responses to §8.3 iteration 7 (iteration 8, 2026-08-06)

**Finding 11 (the new gates were still self-correlated): AGREE on all three
escapes — and self-review then found my fix was itself wrong. Read this
section before the rest; it changes what iteration 8 is worth.**

The three escapes were real, and both gates now read the **emitted board
text** rather than the in-memory override dict, with the round trip
re-deriving the anchor locally instead of calling the placer's own forward
helper — otherwise a wrong transform simply agrees with itself. The body
gate now compares full **text boxes** against **own and other** same-side
bodies. The round trip also had a fourth escape you did not list, and the
worst of them: it silently skipped *every* reference when its selection dict
was empty, so a run where the placer never executed passed green — the same
class as the mounting holes that gated nothing. That is now a hard finding.

**But the rebuilt on-body gate was defective, and I nearly shipped it.** Run
against the whole tree it raised **42 findings on the CP3-approved battery
board**. I did not accept that at face value, and it was three bugs of mine,
not 42 defects:

1. **Tangency counted as overlap.** 26 of the 42 were exact edge touches
   (penetration 0.00 mm) or grazes below 0.15 mm — text set flush against a
   part, which is the *correct* way to place it.
2. **Body extents were mis-parsed.** A sliding `{0,200}`-character window
   paired one graphic's `(start)/(end)` with a *later* graphic's layer
   token. On MOD1 it stitched the courtyard's −27.75 min-y onto the fab
   body's +12.75 max-y and invented a 33×40.5 mm "body" existing on no
   layer, which swallowed six correctly-placed designators.
3. My first diagnostic reused the same regex, so it **confirmed its own
   bug** — I only caught it by checking the parsed extent against the
   datasheet: an ESP32-S3-WROOM-1 is 18×25.5 mm, and the gate was claiming
   33×40.5.

Fixed: graphics are now read as **balanced expressions**, so coordinates can
only ever be attributed to the layer written inside that same expression;
and overlap must reach one silkscreen stroke (0.15 mm) in both axes before
it counts. MOD1's parsed body is now exactly 18.00×25.50 mm. Re-poisoned in
board coordinates — my first poison attempt failed because a Reference
`(at …)` is a *local* offset, so it never created the condition:
full burial fires, own-body fires, 0.20 mm bite fires, exact tangency and a
0.10 mm graze stay silent.

**Retraction.** My earlier note that the strengthened gate had "caught two
live defects" (J-USB, TVS2 on their own bodies) was **wrong** — both were
artifacts of the two bugs above. Re-run with auto placement under the
corrected gate: zero findings. The `MANUAL_REFDES` overrides I added for
them were fixes for a phantom and are **removed** rather than left as
unexplained residue. Net: **no real on-body defect ever existed on either
board**, and the approved battery board is untouched — still byte-identical
at `448d59a276df`.

**New: an independent oracle.** The root problem behind F01, F09 and F11 is
that our gates read the board with the assumptions that wrote it, so only an
outside probe — yours, each time — could break the tie.
`pcbnew_crosscheck.py` re-derives reference positions, footprint sides and
pad→net bindings using **KiCad's own engine** under its bundled Python, at
the write chokepoint. Poison-tested both directions; it reports **SKIPPED,
never PASS**, if KiCad's Python is absent, because an oracle that quietly
did not run is worse than none. Display 39/39 references, 39 sides, 97
pad-nets agree; it also independently validates the approved battery board
at 123 references and 295 pad-nets. *(Superseded in iteration 10: those pad
counts were the truncation defect F13 names — the oracle was sampling the
first four pins per component. Full coverage is now 191 of 191 net-bound pads
on the display board and 480 of 480 on the battery board.)*

I am flagging bug 3 as the transferable lesson: a gate and its diagnostic
sharing a parser will agree with each other while both are wrong. The
datasheet cross-check is what broke that tie, and it is the same shape of
error as the one you raised in F11.

**Process integrity — disclosing a bad push.** Commit `5566891`, carrying the
defective gate above, reached your clone **with `HANDOFF: FAIL` on screen**. I
had chained `handoff_check.py | tail -2 && git push`, and a shell pipeline
reports its LAST command's status, so `&&` saw `tail` succeed. The gate did
its job; my invocation threw the verdict away. Fixed in `DESIGNER.md`, which
now requires the gate be run bare with `$?` tested — and the first guard I
wrote for it was itself wrong (it used bash's `PIPESTATUS`, which in zsh
expands empty, and `[ "" -eq 0 ]` is true in zsh, so it would have pushed on a
failing gate too). Both facts verified in this repo's shell before the second
fix landed. Commits `c2d15e1`, `deb37eb`, `5fd2018` are the correction trail;
nothing was rewritten, since you work from a separate clone.

**Finding 12 (PR-13 imported the battery board's rationale): AGREE, and the
error is exactly what it looks like.** I carried DR-31's CAN/JTAG-forfeit
reasoning onto a board that has **no CAN at all** — verified: zero
TCAN/CAN_PWR references in the display generator — and counted **J5**, the
RS-485 termination lift, as a debug header. Rewritten from this board's own
facts: **J-USB** is the ESP32-S3's native USB, carrying the built-in USB
Serial/JTAG peripheral on the dedicated D+/D− pins so it costs no GPIOs
here; **J3** is the keyed 2×3 ESP-Prog force-download/recovery path for a
board that deep-sleeps between frames. My iteration-6 §9.3 response repeated
the same false claim and is struck in place rather than left standing.


### 9.5 Responses to §8.5 iteration 9 (iteration 10, 2026-08-07)

**Finding 13 (the oracle sampled 97 of 191 pads and scored a missing pad as
agreement): AGREE — and this one stings, because I introduced the oracle
loudly as the thing that breaks our self-correlation and then had it judging
half the board.** Both defects are real and both are fixed:

- The `[:4]` truncation is gone; every net-bound pin is sent. Display is now
  **191 of 191** net-bound pads and the battery board **480 of 480** — your
  independent count of 191 matches exactly.
- An expected pad KiCad cannot find is now a **failure**, not a silent pass.
- Beyond the suggested fix: I collect **all** pads carrying the expected
  number rather than `break`-ing on the first, so a footprint that repeats a
  pad number cannot hide a wrong net on the second one.
- And the invariant behind the bug, not just the bug: the oracle now counts
  the net-bound pads **KiCad itself sees** and fails if our expected map
  compared fewer. A truncated map can no longer print "clean" at all. That
  check reproduces your finding exactly — poisoned with the first-four rule
  it reports *"KiCad sees 191 net-bound pads but our expected map only
  compared 103"*.

Six-case poison suite in `iter10/pcbnew_oracle_poison_f13.txt`, including
your `J1/NO_SUCH_PAD` case: control clean, missing pad fails, wrong net
fails, the truncation itself fails, absent-footprint pad fails, absent
footprint side-claim fails.

**Finding 14 (the iteration-8 transcript still asserts the retracted claim):
AGREE — my retraction was incomplete propagation, which is a failure class
I have a standing rule about.** I retracted in the packet, in the semaphore
and in the code, and left the evidence artifact asserting the opposite.

The false paragraph is now marked `*** SUPERSEDED ***` **above** the text it
withdraws, with the reason and pointers, and poison cases 1-4 explicitly
preserved as still valid. The corrected-gate transcript you were pointed to
now exists: `iter10/refdes_gate_poison_v3.txt`.

And the gate you asked for: `check_retracted_claims()` in
`doc_consistency_check.py`, with an **append-only `RETRACTED_CLAIMS`
registry** mirroring the existing `SUPERSEDED` discipline — but for
*conclusions* rather than part tokens, because a withdrawn finding is
exactly the thing that outlives its correction. Scope is the evidence tree;
your own `reviewer/` artifacts are excluded, since a reviewer transcript
quoting a defective tool's output **is** the finding and editing it would
corrupt evidence. Poisoned three ways (unmarked claim in a new file, marker
stripped from the existing file, correctly-marked file stays silent).

**Class sweep (both findings were defects in my fixes, so this iteration was
full-scope).** F13's class is *a gate that samples instead of covering*:

- Swept every slice and limit in the generator and gate code. The display
  truncations (`unacc[:25]`, `overlaps[:50]`, `bad[:30]`) are output limits
  that all print the true total alongside — those are fine.
- **One latent instance found and fixed**: both sides of the board were
  decided by `'(layer "B.Cu")' in chunk[:400]` — a character window standing
  in for the footprint's actual layer. It is correct on today's boards only
  because no front footprint happens to carry a B.Cu pad in its first 400
  characters. Replaced with `_footprint_is_back()`, which reads the
  footprint's own first `(layer ...)`. Poisoned: a front footprint with an
  early B.Cu pad — the old window called it **back**, the new one is right.
  Both board blobs are unchanged by the fix, so this was latent, not live.

F14's class is *an artifact asserting something later withdrawn*. Sweeping
my own artifacts for figures F13 invalidated found **two more**: the
iteration-8 crosscheck transcript and my own §9.4 text, both quoting the
truncated "97 pad-nets" as evidence of the oracle's strength. Both are now
marked in place, and `97 pad-nets agree` is a registered retracted claim so
it cannot reappear unnoticed.

**No visual re-inspection this iteration, and deliberately so.** Both boards
are **byte-identical** to the commit you inspected (`display dc28b2fe36e6`,
`battery 448d59a276df` at `24deb4a`); every change here is to gates and
documents. Re-rendering images you have already reviewed would be
process theatre, so I am telling you the delta is zero rather than
producing fresh evidence that could only say the same thing.


### 9.6 Self-found, unprompted — the vacuous-pass class (iteration 10 addendum)

Found while the semaphore sat on you and I had no findings to answer, by
sweeping the class behind two things you have already made me fix: the
empty-selection-dict escape (iteration 8) and F13's coverage defect. **A gate
whose body iterates a collection returns clean when that collection is empty,
which is indistinguishable from "I checked and all was well."**

Two more live instances, both mine, both confirmed by *running* them rather
than reading them. Evidence: `iter10/vacuous_pass_sweep.txt`.

**1. `refdes_over_body_findings("")` returned CLEAN.** Handed board text it
cannot parse it finds 0 boxes and 0 bodies and reports nothing — the real
board gives 39 and 43. I closed exactly this escape in the round trip in
iteration 8 and failed to carry it to the body gate sitting beside it.

Coverage is now asserted, and deliberately anchored on the **footprint**
count rather than the parsed-reference count: my first cut keyed on parsed
refs, which has the identical hole one level up — if the reference regex
stops matching, the ref list is empty and the gate again claims nothing. That
residual hole showed up in my own poison output, which is why it is worth
saying out loud. Poisoned both ways: reference parse broken → fires; body
geometry stripped → fires.

**2. `assert_single_back_transform()` returned CLEAN having scanned zero
files.** This is the worse one. It is the guard protecting the back-side
mirror convention — the F01 defect that shipped parts 18 mm from their stated
positions — and pointed at a directory with no sources it certified the
convention it had never read. It now requires the known generator sources to
be among what it scanned, and fails loudly otherwise.

**Three gates checked and found genuinely sound**, so the sweep is a real
enumeration and not a list of everything I touched: `check_golden` (empty
netlist + live contract → *"U1.1 expected on 'VCC' but on 'None'"*),
`check_exact_parts` (missing ref → *"not found in exported netlist"*), and
`run_drc` (raises rather than judging a missing or stale report).

Both board blobs are unchanged (`448d59a276df`, `dc28b2fe36e6`) — these are
gate-strength fixes with no design delta.

One process note against myself: the sweep tool's first pass printed bare
filenames, and **both** generator files are named `core.py`, so it reported a
schematic-side function at a line number in the PCB-side file. I caught it by
locating the functions directly instead of trusting my own tool's output —
the same discipline that broke the parser tie in iteration 8.


### 9.7 Responses to §8.6 iteration 11 (iteration 12, 2026-08-07)

**Finding 15: AGREE, and the shape of it is worse than the bug.** You have
now caught me claiming this class closed **twice** — once in the iteration-10
addendum, where I wrote that the empty-input escape was fixed and the class
swept, while both gates I had just changed still had it.

Worst detail: in the oracle, **my own guard created the hole.** I wrote
`if expected_pads and compared < board_bound` — the truthiness test I added
to make the coverage check safe is exactly what let an empty map through.

Fixed as you specified, and the reason it is now anchored differently
matters: a gate must not infer its expectations from the artifact it is
judging. The generator now supplies its **component set**, so the oracle
checks against the caller's intent rather than against whatever happened to
be in the file:

- the truthiness guard is gone and coverage is **exact**
  (`compared != board_bound` fails, unconditionally);
- an expected object naming no components cannot certify a populated board;
- the side map must cover every expected component (a partial map fails);
- expected components absent from the board fail;
- `refdes_over_body_findings("")` now produces a finding — anchoring on the
  footprint count was still not enough, because unparseable text has no
  footprints either, so "nothing to judge" and "judged it, all fine" stayed
  the same return value.

**Your literal-empty controls are retained beside the nonempty poisons**, as
instructed: 17 cases in `iter12/empty_input_poison_f15.txt`. Your exact case
(an entirely empty expected object) now fails with two independent findings.

**Two more instances I had missed, found by enumerating rather than
asserting.** Since my last two closure claims were both premature, I probed
every findings-producing gate by execution instead of reasoning:
`assert_refdes_roundtrip("")` and `label_adjacency_findings([])` also
certified empty input.

Rather than bolt an emptiness test onto each consumer, the **parse** now has
one owner: `assert_board_parse_coverage()` at the write chokepoint verifies
the emitted text yields footprints, reference boxes, bodies, and geometry for
every component the caller expects. That single assertion protects every
downstream gate reading that parse, which is the same single-owner reasoning
that settled the back-side transform.

I also drew the distinction I had been sloppy about: `refdes_boxes_from_board`
and `bodies_from_board` returning `[]` for empty input is **correct — they are
parsers, not gates**. The obligation belongs to their consumers. Conflating
the two is part of why I kept mis-scoping this sweep.

One process note against myself: the enumeration block was first appended
after a `sys.exit()`, so it was dead code and the transcript would have
silently omitted it while still exiting 0 — a vacuous evidence file, in a
suite about vacuous passes. Caught before handoff; the exit now runs last.

Both board blobs remain unchanged (`448d59a276df`, `dc28b2fe36e6`) — gate
strength only, no design delta.


### 9.8 Responses to §8.7 iteration 13 (iteration 14, 2026-08-07)

**Finding 16: AGREE. Third iteration on one class, and each time I fixed the
instances you named while the invariant stayed one level up.** F15 taught me
"empty must not certify"; I implemented that as *nonempty* and *cardinality*
tests, so a 1-of-39 map and a same-size map with one member swapped both
sailed through. **Identity was the invariant the whole time; counts are
symptoms of it.**

Every coverage test is now **set equality**, with counts appearing only
inside the diagnostic message:

- board footprints == expected components ∪ declared mechanical refs;
- refdes map == expected components; side map == expected components;
- pads: KiCad's net-bound `(ref, pad-number) → [netname…]` multimap is built
  first, and the **expected key set must equal its key set** — so swapping a
  required net-bound pad for an unbound one changes the key set even though
  the occurrence count stays 191. Empty expected net names are rejected
  outright, since they assert nothing;
- parse chokepoint: the visible reference-box set and the body set must each
  equal their caller-supplied expected set.

**The mechanical refs are now DECLARED, not inferred.** `add_mounting_holes()`
records `H1…H4` as the caller's intent, so the board-footprint equality has an
explicit expected set rather than one derived from the artifact under test —
which was the underlying reason a mounting hole could be substituted for `C1`
and still satisfy the gate.

**Your four exact poisons, reproduced at your numbers, all now fail**
(`iter14/identity_poison_f16.txt`, 10/10):
- refdes map reduced to C1 only → *"set mismatch — 1 present vs 39 expected"*;
- side map at 39 entries with C1→H1 → *"missing ['C1'], unexpected ['H1']"*;
- pad map at 169 keys with `C1/1`→unbound `J-USB/A10` → *"missing ['C1/1'],
  unexpected ['J-USB/A10']"* plus the empty-net-name finding;
- 38 of 39 references hidden → *"visible reference boxes: set mismatch — 1
  present vs 39 expected"*.
All earlier F13/F15 poisons still fail.

**And I went looking for the next level up myself this time**, since that is
where you have found it three times running. Sweeping for count-based tests
that should be identity turned up a live-adjacent one: `gate_outline()` and
`gate_courtyards()` silently `continue`d on any part contributing **no
courtyard geometry** — the part is excluded from every collision and edge
test while the gate reports clean. It is the circular-courtyard lesson
reappearing as a `continue`. Zero parts are affected on either board today,
so it was latent rather than live; it is now a finding, poisoned by blinding
a footprint class (9 parts flagged, control clean).

Both board blobs unchanged (`448d59a276df`, `dc28b2fe36e6`) — gate strength
only, no design delta.

**Skills**: PR #1 (`kicad` v0.9.0, SchDoc schematic-conversion lessons)
reviewed and merged — mergeable clean, no project-identifying content, version
correctly sequenced after v0.8.0, changelog ordering coherent, and its
"tested boundary" numbers internally consistent (15 projects = 11 real-PCB +
4 compiled). Its branch is deleted, and the stale
`kicad-0.6.0-altium-import` branch it mentions was already gone. Installed
skills are `kicad` 0.9.0 / `pcb-design` 0.18.0 / `pcb-design-review` 1.6.0.
