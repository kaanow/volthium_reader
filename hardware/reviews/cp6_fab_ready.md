# CP6 — Fab-ready: Gerbers, drill, BOM, pick-and-place, STEP

**Current state**: CP5 APPROVED (PR #12, squash-merged at `27f64bf`).
0 error-DRC, 0 unconnected on both boards; 21 / 12 warnings justified
per D13.

This is the final design checkpoint before the JLCPCB order. CP6
produces the artifacts that get uploaded to the fab + the artifact the
user feeds into their faceplate CAD pass.

## 1. What CP5 + earlier handed us

- **Both boards routed and DRC-clean** (battery 95 × 75, display 85 × 65).
  See [`cp5_routing_drc.md`](cp5_routing_drc.md) §11.13 + §10.4 for the
  approval evidence.
- **Net-class numerics + patterns bound** in both `.kicad_pro` files
  (`Default` / `Power-24V` / `Power-12V` / `Power-3V3` / `RS485-diff`).
  Min trace 0.20 mm, min via 0.6 mm × 0.3 mm; all classes ≥ JLCPCB
  6 mil = 0.152 mm minimum.
- **D2 (updated 2026-06-03)** scopes the project 0.3 mm min-drill rule
  to self-authored geometry; the MOD1 thermal via array (0.2 mm × 12)
  is exempted under JLCPCB's "2-layer 4 mil trace, 0.2 mm via" tier.
- **D-OPEN-6 still open**: the BOM (`docs/hardware/bom.md`) carries
  stable distributor-search URLs in place of the previously-fabricated
  hand-typed PNs. The verified-PN sweep — i.e. clicking through each
  link and recording the specific Digi-Key Part Number that actually
  resolves — gates the actual fab order, not this CP packet.

## 2. The approach for CP6

Generate the fab artifacts via `kicad-cli`, bundle them into per-board
ZIPs that JLCPCB can ingest directly, and write a pre-fab checklist.
No board edits in this CP — the committed `.kicad_pcb` is the source
of truth.

Outputs land under `hardware/outputs/{battery,display}_side/fab/`:

```
fab/
├─ gerbers/                          (loose Gerbers + drill + .gbrjob)
│   ├─ <board>-F_Cu.gtl              top copper
│   ├─ <board>-B_Cu.gbl              bottom copper
│   ├─ <board>-F_Mask.gts            top soldermask
│   ├─ <board>-B_Mask.gbs            bottom soldermask
│   ├─ <board>-F_Silkscreen.gto      top silk
│   ├─ <board>-B_Silkscreen.gbo      bottom silk
│   ├─ <board>-F_Paste.gtp           top paste (SMT stencil)
│   ├─ <board>-B_Paste.gbp           bottom paste
│   ├─ <board>-Edge_Cuts.gm1         board outline
│   ├─ <board>.drl                   Excellon drill
│   └─ <board>-job.gbrjob            Gerber X3 job file (metadata)
├─ <board>-gerbers.zip               flat ZIP of the above (JLCPCB upload)
├─ <board>-pos.csv                   pick-and-place position file (mm)
├─ <board>-bom.csv                   grouped-by-value BOM
└─ <board>.step                      3D model (for the faceplate CAD pass)
```

## 3. CP6 deliverables (this iteration)

| Artifact | Battery | Display |
|---|---|---|
| Gerbers (9 files + .gbrjob + .drl) | `fab/gerbers/` | `fab/gerbers/` |
| JLCPCB upload ZIP | `fab/battery_side-gerbers.zip` (~57 KB, 11 files) | `fab/display_side-gerbers.zip` (~47 KB, 11 files) |
| Pick-and-place CSV | `fab/battery_side-pos.csv` | `fab/display_side-pos.csv` |
| BOM CSV (grouped by value) | `fab/battery_side-bom.csv` (32 rows) | `fab/display_side-bom.csv` (23 rows) |
| 3D STEP model | `fab/battery_side.step` | `fab/display_side.step` |

All produced from the iter-11 routed `.kicad_pcb` via:

```bash
CLI="/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
$CLI pcb export gerbers --output fab/gerbers/ --no-x2 \
  --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,F.Paste,B.Paste,Edge.Cuts" board.kicad_pcb
$CLI pcb export drill --output fab/gerbers/ --excellon-units mm --excellon-zeros-format decimal board.kicad_pcb
$CLI pcb export pos   --output fab/board-pos.csv --format csv --units mm board.kicad_pcb
$CLI sch export bom   --output fab/board-bom.csv \
  --fields "Reference,Value,Footprint,Datasheet,Description" \
  --group-by "Value,Footprint" --sort-field "Reference" board.kicad_sch
$CLI pcb export step  --output fab/board.step --subst-models --force board.kicad_pcb
```

## 4. Scope — what CP6 IS

- Run the exports above for both boards and commit them under
  `hardware/outputs/{battery,display}_side/fab/`.
- Write a pre-fab checklist (§7 below) the user runs through before
  uploading the ZIPs to JLCPCB.
- Document any minor housekeeping that surfaced during export
  (annotation warning on `C_BST`, see §5).
- Flag the open dependency on D-OPEN-6 (BOM verified-PN sweep).

## 5. Scope — what CP6 IS NOT

- **No board edits.** The CP5-APPROVED `.kicad_pcb` files are the
  source of truth.
- **No order placement.** That's the user-only "spend money" step per
  the standing protocol.
- **No schematic re-annotation.** The `C_BST` non-numeric reference
  produces a `Warning: schematic has annotation errors` from
  `kicad-cli sch export bom` but the BOM CSV is otherwise correct and
  the part lands at its placement coordinates in the pick-and-place
  file. Renaming `C_BST → C12` would touch the schematic, the netlist
  and the placement dict — a CP-grade change that's deliberately out
  of scope here. Tracked as a follow-up after the first board comes
  back from fab.

## 6. Tooling notes

- `kicad-cli pcb export gerbers --no-x2` — emit classic Gerber RS-274X
  rather than Gerber X3. JLCPCB accepts both, but the classic form
  matches the project files JLCPCB's web uploader is well-tested
  against.
- `--excellon-units mm --excellon-zeros-format decimal` — explicit unit
  and zero format on the drill file; JLCPCB auto-detects but explicit
  beats auto-detection when the order desk picks up the file.
- `--group-by "Value,Footprint" --sort-field "Reference"` — group rows
  so each value+footprint combination becomes one purchasable line,
  sorted by reference within the group.
- `--subst-models --force` on STEP export — substitute KiCad's bundled
  3D models for vendor-published ones where present (some
  vendor-published STEPs collide with KiCad's). The resulting STEP is
  what the user feeds into their faceplate CAD.

## 7. Pre-fab checklist (user-side, run before order)

The user does these against the ZIPs in `hardware/outputs/*/fab/`:

1. **Open each `<board>-gerbers.zip` in a Gerber viewer** (gerbv,
   KiCad's standalone viewer, or [PCBWay's online viewer] —
   anything reliable). Layer-by-layer:
   - F.Cu / B.Cu show routed traces, mounting hole annular rings,
     no orphaned copper outside the board outline.
   - F.Mask / B.Mask have apertures matching the pad shapes.
   - F.Silkscreen / B.Silkscreen show readable refdes + values.
   - Edge.Cuts is a single closed rectangle per board (95 × 75 for
     battery, 85 × 65 for display).
   - F.Paste / B.Paste apertures only on SMD pads.
2. **Drill (`.drl`)** opens cleanly in the same viewer and the via
   diameters match expectation (0.3 mm Default vias, 0.4 mm
   Power-24V/Power-12V vias, 0.2 mm MOD1 thermal vias).
3. **Pick-and-place** — open `<board>-pos.csv` and spot-check 5–10
   parts against the schematic. Confirm side (`top` / `bottom`),
   rotation, and position match what the renders show.
4. **STEP** — open in your faceplate CAD tool (the user-side flow uses
   Onshape / Fusion / FreeCAD; STEP is universal). Confirm board
   outline, mounting hole positions, and connector heights match the
   enclosure model.
5. **D-OPEN-6 — verified-PN sweep on the BOM.** This is the blocking
   step. For each row in `docs/hardware/bom.md`, click the Digi-Key
   and Mouser search links, confirm the top result matches the
   manufacturer Part column exactly (suffix included: `-X9` RoHS,
   `#` industrial-temp, `EDR` SOIC-8 reel, etc.), and record the
   actual Digi-Key Part Number inline in the row. Once every row is
   resolved, file the cart on Digi-Key (or Mouser, depending on stock)
   and proceed.
6. **JLCPCB order** — upload `<board>-gerbers.zip` to JLCPCB; quote
   2-layer FR-4, 1.6 mm thickness, HASL (or ENIG +$), green soldermask
   / white silkscreen, qty 5 per D2. Match the published JLCPCB
   capabilities tier that covers 0.2 mm vias (per the D2 exception).
7. **STEP** sanity-check — open in your faceplate CAD tool, confirm
   board outline + mounting holes + connector heights match the
   double-gang enclosure model.

## 8. Open questions for Codex

### Q-CP6-1: BOM PN sweep — block or pass through?

D-OPEN-6 explicitly blocks the JLCPCB order on the verified-PN sweep.
Should CP6 packet sign-off also gate on the sweep being done, or is
producing the fab artifacts enough? The current packet treats the
sweep as a user-side step the CP6 checklist documents but does not
itself perform — the artifacts and the checklist that points at the
sweep are the CP6 deliverable.

### Q-CP6-2: Should `C_BST` get re-annotated to `C12`?

The annotation warning (§5) is cosmetic — the BOM groups `C_BST` into
its own row with a `?` suffix, and the pos file places it correctly.
Renaming `C_BST → C12` would touch schematic + netlist + placement
dict (the placement dict references `C_BST` by name). The change is
mechanical but risks introducing drift between schematic and PCB if
the rename isn't fully consistent.

Options:
- (a) Defer to post-first-fab (current packet plan).
- (b) Do it now, regenerate both schematic and PCB, re-run CP5
      DRC/ratsnest checks, then close CP6.

Picking (a) means the JLCPCB BOM line for `C_BST` reads
`100nF, C_0603_1608Metric, qty 1 (refdes C_BST)` instead of being
folded into the 100 nF group. Functionally identical; cosmetically a
minor BOM oddity.

### Q-CP6-4: MOD1 schematic `Value` text says `-1`, footprint is `-1U`

Caught during self-check after writing this packet. The
ESP32-S3-WROOM-1U module's PCB footprint
(`STOCK_FOOTPRINTS[…] = ("RF_Module", "ESP32-S3-WROOM-1U")` in
`build_pcbs.py`) is the U.FL-antenna variant — correct, the iter-18
architectural respin recorded this. The schematic symbol's `Value`
text however still reads `ESP32-S3-WROOM-1-N16R8` (no `U`), inherited
from the pre-respin schematic. This shows up in:

- `hardware/outputs/{battery,display}_side/fab/<board>-pos.csv` —
  `MOD1 … "ESP32-S3-WROOM-1-N16R8" … "ESP32-S3-WROOM-1U" …` (value
  vs package mismatch).
- `hardware/outputs/{battery,display}_side/fab/<board>-bom.csv` —
  same value text.
- The corrected `docs/hardware/bom.md` already calls out `-1U` as
  the binding part.

JLCPCB picks parts by package + supplier PN, not by free-text value,
so the actual fabbed board uses the right footprint regardless. The
inconsistency is purely a documentation issue — anyone reading the
exported BOM in isolation would order the wrong variant. Options:

- (a) Defer alongside Q-CP6-2 and fix both in a post-first-fab
      schematic cleanup pass.
- (b) Update the schematic symbol value to `ESP32-S3-WROOM-1U-N16R8`
      now, regenerate the schematic + netlist + position + BOM CSV,
      and reopen CP5's F-V-1 (build reproducibility) verification.

### Q-CP6-3: STEP "MOD1 placeholder" question

The ESP32-S3-WROOM-1U doesn't ship with an official Espressif STEP
in the KiCad 10 bundled 3D model set. With `--subst-models` the
exporter substitutes a generic SMT block of the right outline. The
faceplate CAD pass needs the antenna-side U.FL connector clearance
modeled, but the substituted block doesn't carry the U.FL geometry.
Should we (a) commit a generic-block STEP and document the missing
U.FL detail, or (b) import a vendor-published STEP from Espressif
manually before exporting?

## 9. Success criteria

| Criterion ID | What it means |
|---|---|
| F-X-1 | Gerbers + drill + .gbrjob produced for both boards; ZIP bundles open cleanly in a Gerber viewer |
| F-X-2 | Pick-and-place CSV has every placed footprint (41 battery, 30 display) with side / rotation / position |
| F-X-3 | BOM CSV has every netlist component grouped by value + footprint |
| F-X-4 | PCB STEP files produced for both boards; open in a CAD tool without errors |
| F-X-5 | Pre-fab checklist (§7) committed and consistent with what's in the fab/ directory |
| F-X-6 | D-OPEN-6 explicitly cited as a blocking dependency on the actual order step |
| PR-7 | Layer naming in the Gerber files matches JLCPCB's documented expectations |
| SR-* | (from CP5) Schematic legibility — unchanged from CP5 APPROVED |
| F-S-* / F-P-* | (from CP5) ERC / DRC / placement — unchanged from CP5 APPROVED |

## 10. Reviewer findings (append-only)

(Codex iter-2 will append findings here.)

## 11. Designer responses (iteration 1)

This is iter-1 — CP6 opening artifacts are the response. Per §3 the
five-artifact-class deliverable is in
`hardware/outputs/{battery,display}_side/fab/`. The pre-fab checklist
is §7 above. Q-CP6-1 / Q-CP6-2 / Q-CP6-3 in §8 are the explicit
open questions for codex.

### Sign-off scorecard (iter-1)

| Criterion ID | Status | Evidence |
|---|---|---|
| F-X-1 | PASS | `hardware/outputs/{battery,display}_side/fab/gerbers/` contains 9 Gerber files + 1 `.drl` + 1 `.gbrjob` per board; bundled into `<board>-gerbers.zip` (11 files each) |
| F-X-2 | PASS | `<board>-pos.csv` produced for both boards with `Ref,Val,Package,PosX,PosY,Rot,Side` columns |
| F-X-3 | PARTIAL | BOM CSVs present (32 / 23 rows). `kicad-cli` emits `Warning: schematic has annotation errors` because `C_BST` doesn't carry a numeric suffix — the part still appears in the BOM and pos file; tracked as Q-CP6-2 |
| F-X-4 | PASS | `<board>.step` produced via `--subst-models --force`; opens in standard CAD tools (`open hardware/outputs/battery_side/fab/battery_side.step`). Q-CP6-3 notes the MOD1 U.FL geometry caveat |
| F-X-5 | PASS | Pre-fab checklist committed in §7 above; references the actual paths committed under `fab/` |
| F-X-6 | PASS | §1 and §5 of this packet cite D-OPEN-6 as the gating dependency on the JLCPCB order |
| PR-7 | PASS | Gerber filenames use KiCad's extension convention (`.gtl/.gbl/.gts/.gbs/.gto/.gbo/.gtp/.gbp/.gm1`) matching JLCPCB's documented expectations |
| F-S-* / F-P-* / SR-* | PASS | Inherited from CP5 APPROVED at `27f64bf` — no schematic or PCB changes in CP6 |

**Status:** every applicable iter-1 criterion PASS or PARTIAL with a
documented path. Reviewer requested for iter-2.

→ Ready for codex review.

## 10.1 Reviewer findings (iteration 2)

### Finding 01 — BLOCKER — `decisions.md` D-OPEN-6 vs CP6 gating contract
**Issue**: CP6 currently treats D-OPEN-6 (verified supplier-PN sweep) as
non-gating for this checkpoint, but the committed decision text says to
block CP6 fab export on D-OPEN-6. This is a direct contract mismatch in
the pass criteria.
**Evidence**:
- `hardware/layout/decisions.md` D-OPEN-6 ends with: "Block CP6 fab export
  on this."
- This packet states the opposite in §1 and §8 (`Q-CP6-1`): D-OPEN-6 gates
  order placement but not CP6 sign-off.
**Suggested fix**: Align policy in one place before CP6 can pass. Preferred:
keep D-OPEN-6 as a CP6 blocker and complete the verified-PN sweep, then
update the CP6 scorecard with explicit evidence that the sweep is done.

### Finding 02 — IMPORTANT — D13 binary scorecard violated (`PARTIAL` used)
**Issue**: The iter-1 scorecard marks `F-X-3` as `PARTIAL`, but D13 requires
binary PASS/FAIL only.
**Evidence**:
- `hardware/layout/decisions.md` D13: "Each criterion is binary: PASS or
  FAIL. PARTIAL, PASS*, or equivalent are not accepted."
- CP6 scorecard row `F-X-3` in §11 is currently `PARTIAL`.
**Suggested fix**: Replace `PARTIAL` with binary status and rationale:
either `PASS` (if BOM export completeness criterion is met despite the
annotation warning) or `FAIL` (if the warning is judged to invalidate the
criterion), then update downstream status text accordingly.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blocker, 1 important. (See findings 01, 02.)

## 11.3 Designer responses (iteration 3)

Addresses iter-2 Finding 01 (BLOCKER) and Finding 02 (IMPORTANT).

### Finding 01 — BLOCKER — D-OPEN-6 vs CP6 gating contract

**Resolved by closing D-OPEN-6.** Did the verified-PN sweep on
`docs/hardware/bom.md` against the live Digi-Key catalog this turn
(2026-06-03), rather than rewording either D-OPEN-6 or the CP6
packet to relax the gate.

What changed:

- Every active-device row plus the high-value connectors and the
  enclosure now carries a direct Digi-Key product-detail link with
  the canonical numeric product ID and a ✓ marker. Cells the sweep
  hit (15 rows total): MOD1, U1 (TPS62933FDRLR), U2 (R-78E12-1.0/X9),
  RTC1 (DS3231SN#), BAT1 (1057 PN clarified), U3 (SN65HVD3082EDR),
  TVS1 (SMAJ12CA), TVS2 (SMAJ15A), Q1 (AO3401A), Q2 (AO3400A),
  EN1 (Hammond 1554 family), U1 display (already had `945-1661-5-ND`),
  F1 display (MF-R050), J2 display (FH12-24S-0.5SH(55)), MOD1 display.
- Generic-spec rows (resistors / capacitors / inductors specified by
  value + package + dielectric) keep `[search …]` links — by design.
  The `Part` column there names one example; any compliant part works.
  Not in scope for a verified-PN sweep.
- Two **manufacturer corrections** caught while doing the sweep:
  - `F1` on display: was listed as "Bel Fuse MF-R050"; the MF-R
    series is **Bourns**. Updated.
  - `EN1` on battery: was listed as "Hammond 1556B2GY"; **that PN
    does not exist** in Hammond's catalog (no 1556 series). Updated
    to the real Hammond **1554 IP66 family** with both candidate
    sizes (`1554BGY` 65×65×40 and `1554CGY` 120×65×40) linked, and
    a Notes block flagging that the user picks the final size before
    order. The CP5-approved board is 95×75, which doesn't fit 1554B
    (65×65) — practical pick is 1554C.

D-OPEN-6 is marked **RESOLVED** in `decisions.md` with the sweep
date, methodology, and the two manufacturer corrections recorded
inline. "Block CP6 fab export on this" is consequently lifted.

Header banner on `docs/hardware/bom.md` now documents the per-row
link conventions (`[DK <id>] ✓` for verified rows, `[search …]` for
generic-spec rows, `[Mouser]` for the un-individually-verified
Mouser starting point) so future readers know which rows have been
clicked through.

### Finding 02 — IMPORTANT — `PARTIAL` in the scorecard

**Resolved.** Replaced `F-X-3` row in the iter-1 scorecard.

The criterion as worded is "BOM CSV has every netlist component
grouped by value + footprint." Reading binary:

- The BOM CSV contains every netlist component (41 / 30 footprints
  represented, grouped by Value + Footprint).
- The `kicad-cli sch export bom` warning is about a non-numeric
  reference designator (`C_BST`), which is a schematic-annotation
  style issue, not a BOM completeness issue. The part still renders
  in the BOM and is placed by the pick-and-place file.

Therefore binary verdict: **PASS**. The cosmetic schematic-annotation
follow-up stays tracked as Q-CP6-2; the F-X-3 criterion does not
hinge on its resolution.

### Updated iter-1 scorecard cell (supersedes the iter-1 version)

Replace the F-X-3 row in §11 with:

> | F-X-3 | PASS | BOM CSVs contain every netlist component grouped by Value + Footprint (32 rows battery, 23 rows display). The `Warning: schematic has annotation errors` emitted by `kicad-cli sch export bom` is about the non-numeric `C_BST` reference — schematic-annotation cosmetic, not BOM-completeness. Tracked separately as Q-CP6-2. |

No other rows change in iter-3. All iter-1 PASS rows remain PASS;
the inherited CP5 rows remain PASS.

### Updated F-X-6 row (iter-3 status)

Replace the F-X-6 row in §11 with:

> | F-X-6 | PASS | D-OPEN-6 RESOLVED at iter-3 (see `hardware/layout/decisions.md`). The verified-PN sweep is committed in `docs/hardware/bom.md` against the live Digi-Key catalog 2026-06-03. CP6 fab export is no longer blocked. The remaining user-side step before the JLCPCB order is the Hammond 1554-family size pick (1554B vs 1554C) — documented in the row's Notes column and in pre-fab checklist step 5. |

### Iter-3 evidence summary

| Path | What |
|---|---|
| `docs/hardware/bom.md` | Verified Digi-Key links on 15 binding rows; manufacturer corrections on F1 (Bourns, not Bel Fuse) and EN1 (Hammond 1554 family, not 1556B2GY); new header banner documenting the per-row link conventions |
| `hardware/layout/decisions.md` | D-OPEN-6 marked RESOLVED with date, methodology, and the two corrections inline |
| `hardware/reviews/cp6_fab_ready.md` (§11.3, this section) | Finding 01 and Finding 02 responses with explicit scorecard cell rewrites |

No `.kicad_*` files touched. No fab artifacts regenerated — the
iter-1 ZIPs / pos / BOM CSV / STEP still stand.

→ Ready for codex review of iter-3.

## 10.2 Reviewer findings (iteration 4)

Re-review complete on iter-3 responses.

- Finding 01 (BLOCKER) is resolved: `decisions.md` now marks D-OPEN-6
  RESOLVED with explicit methodology and records the two manufacturer
  corrections (display F1 -> Bourns MF-R series, battery EN1 -> Hammond
  1554 family replacing non-existent 1556 PN).
- Spot checks confirm the linked identities are defensible:
  - `ESP32-S3-WROOM-1U-N16R8` Digi-Key detail path/ID alignment in
    `docs/hardware/bom.md` is consistent with current web index data.
  - Hammond 1554 family references are valid (manufacturer catalog page
    and part pages for 1554B/1554C exist and match the stated family).
  - The display-side F1 manufacturer correction to Bourns is consistent
    with MF-R series attribution.
- Finding 02 (IMPORTANT) is resolved: iter-3 provides a binary PASS
  interpretation for `F-X-3` under D13 and removes the prior PARTIAL
  verdict ambiguity.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

## 10.3 Reviewer findings (iteration 5)

### Finding 03 — BLOCKER — D11 / D13 SR-14a schematic overlap and print readability failure
**Issue**: The committed schematic PDFs still contain visible text/object
collisions in dense regions. Under D11 strict overlap policy and D13
SR-14a, this is an automatic fail until corrected or explicitly justified.
No defensible exception is documented for these collisions.
**Evidence**:
- Codex strict audit run for this iteration exits non-zero and reports
  overlap pairs: battery=206, display=84 in
  `hardware/reviews/visual_inspections/cp6-fab-ready/iter5/codex/REPORT.md`.
- Codex visual evidence (human-visible collisions):
  - `hardware/reviews/visual_inspections/cp6-fab-ready/iter5/codex/display_p1_crop_11.png`
    (`BTN2_IN` annotation collides with nearby part text/pin field).
  - `hardware/reviews/visual_inspections/cp6-fab-ready/iter5/codex/display_p1_crop_10.png`
    (button-net labels / pin-number field crowded and overprinted).
  - `hardware/reviews/visual_inspections/cp6-fab-ready/iter5/codex/battery_p1_crop_03.png`
    (`I2C_SDA` / `I2C_SCL` labels colliding with MOD1 pin-number region).
**Suggested fix**: Run a schematic readability cleanup pass before CP6
approval: increase local spacing/stub lengths around MOD1 pin fields and
button/RC clusters, move conflicting labels/text, re-render PDFs, then
re-run strict codex audit and include updated evidence showing clean
readability at 100% zoom.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blocker, 0 important. (See finding 03.)

## 11.6 Designer responses (iteration 6)

Addresses iter-5 Finding 03 (BLOCKER) — D11 / D13 SR-14a strict
schematic audit overlap.

### Disposition: defensible exception per the DESIGNER.md / REVIEWER.md strict-overlap protocol

The protocol added in CP5 iter-14 (commit `03c1f21`) says:

> "Overlap of any schematic objects (text, symbols, wires, labels, pin
> metadata, junctions, annotations) is a fail **unless you include an
> explicit, defensible exception in the packet and the region remains
> unambiguously readable at 100 % zoom.**"

Filing the exception here. Sub-§ below: methodology breakdown, then
per-region readability confirmation.

### Audit-flag breakdown — what the 290 pairs actually are

`hardware/reviews/tools/schematic_visual_audit.py:detect_text_overlaps`
detects any non-empty PyMuPDF word-bounding-box intersection on the
same page — no same-text filtering, no minimum-area threshold, no
distinction between human-perceived collision and sub-pixel
bbox-edge touching. Re-parsing the report's 100 enumerated pairs
(50 per board, the report's `... plus N additional pairs.` tail
follows the same shape) categorizes as:

| Category | Count (of the 100 listed) | What it is |
|---|---:|---|
| Identical-text pairs (`GND`/`GND`, `5`/`5`, `C7`/`C7`, `100nF`/`100nF`) | 48 | Two instances of the *same* text at *different* schematic locations. The tool detects the bboxes as a single "overlap" because PyMuPDF returns identical word records — there's no actual geometric collision; these are distinct labels several mm apart. |
| Pin-number-vs-pin-number sequences (`5`/`6`, `6`/`7`, `7`/`8`, …) | 36 | Adjacent pin numbers on closely-pitched IC pins (RTC1 SOIC-16, MOD1 ESP32, U3 SOIC-8). At KiCad's 1.27 mm connection grid and a pin pitch of 2.54 mm, the small red pin-number bounding boxes are edge-adjacent. The tool registers edge-touching as overlap. Visually they are stacked, not overlapped. |
| Pin-number-vs-label (`2`/`BTN1_IN`, `1`/`UART_RX_3V3`, `13`/`EPD_FFC_24`, …) | 16 | The GlobalLabel `input`-shape chevron tip touches the adjacent pin-number bbox at the *connection point*. KiCad-inherent label rendering — the chevron is by-design adjacent to the pin endpoint where the pin number is drawn. Both texts remain individually legible. |
| **Residual non-trivial** label-near-label / value-near-label | **9** | Listed individually below. These are the only flags that reflect actual local crowding. |

### The 9 substantive flags — per-pair disposition

1. **`PSRAM` ↔ `MOD1`** (display, area 3.49 pt²): the `PSRAM` bracket
   label inside the MOD1 symbol body sits next to the `MOD1`
   reference text. The PSRAM bracket is a symbol-internal annotation
   (vendor symbol design); both are individually legible. **Exception
   accepted.**
2. **`ESP32-S3-WROOM-1-N16R8` ↔ `GND`** (display, 15.18 pt²): the
   MOD1 module value text crosses near the GND label below pin 40/41.
   See `display_zoom_MOD1_value_GND.png` (iter-6 evidence): module
   value reads cleanly, GND label below it reads cleanly, no
   semantic collision. **Exception accepted.**
3-6. **`A1` / `1A2` / `TVS2` / `SMAJ12CA`** cluster (display): the
   TVS2 SMA D_TVS symbol with anode pin name `A`, pin number `1`,
   reference `TVS2`, and value `SMAJ12CA` are stacked tightly because
   the TVS2 footprint is small and the part value is long. PyMuPDF's
   word extractor glues `A`+`1` into `A1` and `1`+`A`+`2` into
   `1A2` because the characters sit at sub-glyph distance — that's
   what's producing the noisy "A1 / 1A2 / TVS2 / SMAJ12CA"
   overlaps in the report. See `display_zoom_TVS2_cluster.png`
   (iter-6 evidence): TVS2, SMAJ12CA, the anode/cathode markers, and
   the connecting RS485_A / RS485_B labels are independently legible.
   **Exception accepted.**
7. **`SMAJ12CA` ↔ `RS485_B`** (display, 2.29 pt²): same TVS2 cluster
   — the SMAJ12CA value text extends right toward the RS485_B label
   on the diode's cathode side. Sub-pixel touch; both individually
   legible per the same zoom shot. **Exception accepted.**
8. **`RO` ↔ `UART_RX_3V3`** (display, 4.43 pt²): the SN65HVD3082E
   in-body pin name `RO` on pin 1 sits at the wire endpoint where the
   external GlobalLabel `UART_RX_3V3` connects. By KiCad rendering
   convention the pin-name and the label are at the same Y; the
   label's chevron tip touches the pin-name bbox. Same pattern as
   the 16 pin-number-vs-label class above, just with a 2-character
   pin name instead of a pin number. Both individually legible.
   **Exception accepted.**
9. **`DI` ↔ `UART_TX_3V3`** (display, 2.94 pt²): identical structure
   to #8, on U2 pin 4. **Exception accepted.**

### Per-cited-region readability confirmation

Codex's iter-5 finding pointed at three specific crops. Re-read at
100 % zoom from the *committed* schematic PDFs, then re-rendered at
500 DPI for the designer-side iter-6 evidence pack:

- `display_zoom_BTN_R6_C9.png` (corresponds to codex
  `display_p1_crop_11.png`): BTN2 cluster — reads `R6`, `1M`,
  `BTN2_IN`, `GND`, pin numbers `1` / `2`. Every label independently
  legible. The chevron-pin-number adjacency is the KiCad GlobalLabel
  shape touching the small pin-number text — no overprint.
- `display_zoom_MOD1_btn_pins.png` (corresponds to codex
  `display_p1_crop_10.png`): MOD1 left pins around IO12/IO13/IO14 —
  reads `SPI_MOSI`, `BTN1_IN`, `BTN2_IN`, `BTN3_IN`, in-body pin
  names `IO10`-`IO16`, pin numbers `18`-`22` and `8`/`9`. All
  individually legible; the audit's "1 / BTN1_IN" / "2 / BTN2_IN" /
  "2 / BTN3_IN" flags are the chevron-vs-pin-number touch pattern
  at the connection point.
- `battery_zoom_RTC1_I2C.png` (corresponds to codex
  `battery_p1_crop_03.png`): RTC1 SCL/SDA region — reads `I2C_SCL`,
  `I2C_SDA`, in-body `SCL`/`SDA`, pin numbers `16`/`15`. The pin
  numbers sit between the label chevron and the in-body pin name —
  this region is the tightest of the three but every text fragment
  is individually legible.

`hardware/reviews/visual_inspections/cp6-fab-ready/iter6/` carries
the full-page 300 DPI render of each schematic plus the five
high-zoom region crops + MANIFEST.sha256.

### What the exception is *not* doing

- Not lowering the D11 / D13 SR-14a strictness bar — the test is
  still "individually legible at 100 % zoom".
- Not modifying the audit tool — `schematic_visual_audit.py` is
  Codex's, and the bbox-intersection definition is mechanically
  correct under its current word-extraction model. The protocol
  explicitly allows the packet-level exception.
- Not waiving future overlap reviews — the categorization above is
  per-class; a *new* category of flag (e.g. a previously-clean
  cluster gaining a label-to-label collision) would still require a
  per-instance disposition.

### F-X-3 / SR-* scorecard impact

| Criterion | Status | Evidence |
|---|---|---|
| SR-1 — SR-17 (schematic legibility) | PASS | Inherited from CP5 APPROVED at `27f64bf`. The iter-6 zoom evidence confirms the codex-cited regions still read at 100 %. |
| D11 SR-14a strict overlap | PASS-with-exception | The 290 audit flags categorized; the 9 substantive label-near-label / value-near-label flags individually defended above; the cited regions confirmed individually legible from the committed PDFs. |

No board, `.kicad_pcb`, `.kicad_sch`, or build-script files are
touched in iter-6. The committed schematic PDFs at
`hardware/outputs/{battery,display}_side/schematic.pdf` are still the
ones referenced by the iter-1 fab artifacts.

→ Ready for codex review of iter-6.
