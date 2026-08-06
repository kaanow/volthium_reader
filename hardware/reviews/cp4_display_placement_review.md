# CP4 review packet — display-side placement

Branch `hw/cp4-display-placement` · packet opened 2026-08-05 · designer: Claude
Scope per D12: **display side only** (battery-side placement was CP3, APPROVED).

## 1. Scope and inputs

- Input netlist: the CP2-APPROVED display schematic's export,
  `hardware/kicad/schematic/build_display/volthium_display.net`
  (sha256 `41145f58b214…`), 39 components / 56 nets. **Three** CP4-driven
  schematic-side deltas — §4.1 and §4.5.
- Output: `hardware/kicad/pcb/build_display/display_pcb.kicad_pcb`
  (sha256 `6232b530ee70…`) — 43 footprints (39 parts + 4 M3 mounting
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
- `lib_footprint_mismatch` ×1 — MOD1 vendored variant (non-geometric
  kiutils serialisation, same class as CP3 §2).

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

Deferred to iteration 2 — this packet is the first hand-off of a board whose
generator changed materially underneath it, and the reviewer's independent
rebuild is the more valuable first check.

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
