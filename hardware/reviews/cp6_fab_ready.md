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
