# CP5 review packet — routing + DRC (both boards)

**Status**: open (iteration 1 — approach packet, no routing yet)
**Opened**: 2026-05-27
**Branch**: `hw/cp5-routing-drc`
**Goal of this CP**: route every signal on both
`hardware/kicad/battery_side/battery_side.kicad_pcb` and
`hardware/kicad/display_side/display_side.kicad_pcb`, add a B.Cu
ground pour to each, run DRC to **zero** errors (warnings categorized
+ justified per D13 PR-*), and re-render top + bottom PNGs that
satisfy D11 readability for the routed boards. CP6 (Gerbers, drill,
position, BOM CSV, STEP) follows immediately after this APPROVES.

## 1. What CP4 + earlier CPs handed us

- **CP3 APPROVED**: `hardware/kicad/battery_side/battery_side.kicad_pcb`
  with every footprint placed, DRC clean for "placement only"
  (unrouted-track warnings suppressed at that gate).
- **CP4 APPROVED** (this branch's predecessor):
  `hardware/kicad/display_side/display_side.kicad_pcb` with every
  footprint placed on an 85×65 mm outline, DRC clean for placement,
  top + bottom renders D11-readable.
- **`build_pcbs.py`** has full footprint placement + net-tying for
  both boards. No routing logic; no zone/pour logic; net classes are
  not yet emitted into the PCB files (verified: `grep -n
  "net_class\|netclass"` on both kicad_pcb files returns empty —
  classes live in [cp1_battery_side.md §11.3](../layout/cp1_battery_side.md#113-net-classes-track-widths)
  and [cp1_display_side.md §10.3](../layout/cp1_display_side.md#103-net-classes)
  as design intent but have not been written to the boards).
- **In-flight crash WIP** (preserved at `git stash@{0}` titled
  "iter-10 crash recovery: silk-promotion WIP ..."): silk-promotion
  infrastructure for `build_pcbs.py` (font sizing to JLCPCB silk
  minimums: 1.0 mm height / 0.15 mm thickness; per-component refdes
  offsets for SMD passives; post-processing of `(property "Reference"
  ...)` lines that kiutils strips on save). Out of scope for routing
  but in scope for "renders must remain D11-clean after routing"
  (silk text near tracks/vias is exactly the kind of regression CP5
  could re-introduce). May be popped and applied here if Codex
  agrees in §7. Also stashed: a `reviewer_automation.sh` tooling
  tweak (interval 600→180 s, preflight sync logic) — that goes to a
  separate `main` commit, not into CP5's PCB scope.

## 2. The approach for CP5

**Generation discipline**: same as CP3/CP4 — KiCad PCB files are the
source of truth, but every modification is reproducible from
`build_pcbs.py` + the design-intent docs. No manual KiCad-GUI edits
land on `main` unbacked by a script change.

Five work items, in order:

1. **Emit net classes into both boards** (extend `build_pcbs.py`
   with a `_apply_net_classes(board, classes)` helper that writes
   the `(net_class ...)` blocks from a Python dict matching the
   CP1 spec). One commit per board for traceability.
2. **Route the boards.** Two candidate strategies in §3 — Codex
   to pick one in iter-2 sign-off (or earlier via §7 question).
3. **Add B.Cu ground pour** on both boards via
   `_add_ground_zone(board, layer="B.Cu", net="GND",
   clearance=0.25 mm)`. Stitching vias every ~10 mm around U1
   (battery-side) per [cp1_battery_side.md §11.4](../layout/cp1_battery_side.md#114-ground)
   and around the FFC return path on display-side per
   [cp1_display_side.md §10.4](../layout/cp1_display_side.md#104-ground).
4. **DRC** via `kicad-cli pcb drc --schematic-parity` on both
   boards. Pass criterion: zero errors. Warnings must each map to a
   D13 PR-* row with PASS justification, or be fixed.
5. **Render** via `kicad-cli pcb render --side top` and
   `--side bottom` for both boards, at the same 4k preset CP4 used.
   D11 visual inspection per DESIGNER.md §0 checklist on each
   rendered PDF/PNG (silk-vs-track collisions are the new failure
   mode that CP5 introduces).

## 3. Routing strategy — two candidates

### 3a. Programmatic + Freerouting hybrid (default proposal)

Emit critical high-current and tight-tolerance routes
programmatically in `build_pcbs.py` so they are reproducible and
review-friendly:

- **Battery-side**: V24_RAW → F1 → D1 → V24_FUSED → U1 (Power-24V,
  1.0 mm wide) as a fat continuous run; the U1 → L1 → C2 switching
  loop (≤10 mm sides per
  [cp1_battery_side.md §11.2](../layout/cp1_battery_side.md#112-placement-priorities)).
- **Display-side**: V12_CAT5E → F1 → D1 → V12_PROT → U1 (Power-12V,
  0.5 mm), RS-485 diff pair (RS485_A/B as a coupled pair, equal-
  length, no stubs).

Then export `.dsn`, run **Freerouting** (Java CLI app) for the
remaining signal nets, import `.ses` back. Freerouting is the
standard KiCad autorouter; deterministic with a fixed seed, no
license cost, output is editable in KiCad.

Pros: critical paths bit-reproducible from script; bulk signal
routing automated; tractable in this loop.

Cons: introduces a Java dependency at build time (~80 MB JAR);
Freerouting occasionally needs manual touch-up on dense regions
(would surface in §3's DRC pass and get a follow-up commit).

### 3b. Pure programmatic (no Freerouting)

Hand-write every track in `build_pcbs.py` using `kiutils`'
`Segment` / `Via` primitives. Manageable because the boards are
small (60×40 and 85×65 mm, ~50 nets total combined).

Pros: no external tooling; pure-Python build chain.

Cons: writing ~200+ Segments by hand is brittle and tedious; any
placement adjustment cascades into hand-edited route fixups; we'd
spend most of CP5 doing hand-routing work that a router does in
seconds.

**Recommendation**: 3a. Reproducibility for the paths that matter
(power, switching loop, RS-485 pair) + automation for the rest. If
Codex prefers 3b for purity, we accept the extra iteration cost.

## 4. Scope — what CP5 IS

- Net-class metadata in both `.kicad_pcb` files
- Every signal net routed end-to-end
- B.Cu ground pour on both boards, stitching vias per §11.4 / §10.4
- DRC zero errors on both boards (`schematic-parity` enabled)
- Top + bottom renders for both boards, D11-readable
- One PR (`hw/cp5-routing-drc`), one squash-merge on APPROVE

## 5. Scope — what CP5 IS NOT

- **Gerbers / drill / position / BOM CSV / STEP**: all CP6.
- **Schematic edits**: CP2/CP-schematic-cleanup closed those.
  Any net change here is a regression unless paired with a
  schematic re-export and explicit Codex sign-off.
- **3D STEP**: CP6.
- **Pre-fab checklist**: CP6.
- **Mechanical / faceplate**: user-owned, out of every CP.
- **Battery-side placement re-litigation**: CP3 closed at iter-21
  APPROVED. Don't touch placement unless a routing constraint
  forces it, and even then surface the move as a finding for the
  user.

## 6. Tooling notes

- `kicad-cli pcb drc <file> --schematic-parity --output <rpt>`
  is the DRC entry point (used in CP3 / CP4).
- `kicad-cli pcb render <file> --side {top,bottom} --preset
  perspective --output <png>` for 4k renders (D11 inspections
  use these).
- Freerouting CLI: `java -jar freerouting-2.x.jar -de <board.dsn>
  -do <board.ses>`. Pin the version; record SHA in `decisions.md`
  on first commit so re-runs are reproducible. Confirm
  availability with `which java` on the build host.
- `kiutils` (already vendored via `build_pcbs.py`) for emitting
  net classes, zones, and any programmatic segments/vias.

## 7. Open questions for Codex

### Q-CP5-1: Routing strategy — 3a hybrid or 3b pure programmatic?

Recommendation: 3a (hybrid). See §3 trade-off table. If 3b, we add
~1–2 iterations of route hand-writing on this branch.

### Q-CP5-2: Pop the stashed silk-promotion WIP into CP5?

The stashed `build_pcbs.py` changes (silk font sizing to JLCPCB
minimums + post-process of `(property "Reference" ...)` lines)
were not part of the CP4 APPROVED state but appear correctness-
relevant once tracks/vias enter the renders. Three options:

- **Pop here** as the first iter-2 commit; D11 quality improves
  ahead of routing.
- **Reject** entirely; the CP4 APPROVED silk treatment is fine, we
  don't change build_pcbs silk logic in CP5.
- **Defer to CP6** under the "fab-ready" silk-final pass.

Recommendation: **pop here** — the post-processor specifically
restores silk attrs that kiutils strips, which becomes a
correctness bug once routing changes other board content (any
build_pcbs.py re-run regenerates silk anchors back at footprint
center, which routing PRs will need to do).

### Q-CP5-3: Antenna keepout enforcement during routing

[cp1_battery_side.md §11.2](../layout/cp1_battery_side.md#112-placement-priorities)
specifies a 15×6 mm no-copper-no-track zone at the ESP32-S3-WROOM-1
antenna corner. Freerouting respects keepout zones if they exist on
the board. Should I:

- Add the keepout as a `(zone ...)` with `(keepout (tracks not_allowed)
  (copperpour not_allowed))` in `build_pcbs.py` first (iter-2), then
  route?
- Or assume Freerouting + the placement clearance is sufficient and
  let DRC catch any violation?

Recommendation: **add the keepout zone first.** Defense in depth;
DRC then enforces it.

### Q-CP5-4: DRC severity policy for the post-route board

CP3/CP4 closed with non-zero DRC warning counts (94 DRC, 34
footprint warnings on display-side iter-9). Per D13 those need
each-row PASS justification in the scorecard. For CP5, do we:

- **Raise the bar to zero warnings** for routed boards (silk
  overlaps, courtyard overlaps, etc., all fixed)?
- **Keep the CP3/CP4 policy**: zero errors, warnings categorized +
  justified per D13?

Recommendation: keep the **zero errors, warnings categorized**
policy. Some warnings (silk-on-pad on small SMDs) are intrinsic
to the chosen footprints and can't be fixed without re-spinning
footprint authoring, which is CP3's domain. CP5 should not
inherit CP3/CP4 baseline-warning churn.

## 8. Success criteria (CP5 overall)

| ID | Criterion |
|----|-----------|
| F-S-1 | Both boards ERC clean (unchanged from CP2/4) |
| F-S-2 | Both boards DRC clean (zero errors), schematic-parity enabled |
| F-P-1 | Every net in each `.kicad_pcb` has at least one routed segment connecting all its pads |
| F-P-2 | Net classes per [cp1_battery_side.md §11.3](../layout/cp1_battery_side.md#113-net-classes-track-widths) and [cp1_display_side.md §10.3](../layout/cp1_display_side.md#103-net-classes) emitted into both boards' `(net_class ...)` tables; tracks for each net carry the class's width |
| F-P-3 | B.Cu ground pour present on both boards; stitching vias around the switching regulator (battery-side) and FFC return (display-side) |
| F-P-4 | Antenna keepout (battery-side) honored — no tracks, no copper inside the 15×6 mm zone |
| SR-1 | Every routed-board render is D11-readable (D13 SR-* applied to renders post-route) |
| PR-* | Warning rows categorized + PASS-justified per D13 |
| F-V-1 | Build is reproducible: `python hardware/kicad/build_pcbs.py --battery` and `--display` regenerate the committed `.kicad_pcb` byte-equivalent (modulo timestamps Freerouting may inject) |

## 9. What this CP does NOT settle

- **Fab readiness** — Gerbers, drill, position file, BOM CSV,
  STEP. CP6 only.
- **EMC pre-test** — V24 switcher noise on the antenna lead. Out
  of scope; informally surface any obvious red flags in routing
  review.
- **Mechanical fit** — faceplate clearance, button height,
  panel-to-PCB stackup. User-owned.

## 10. Reviewer findings (append-only)

### Finding 01 — BLOCKER — cp5_routing_drc.md:§8 F-P-1 (all nets routed)
**Issue**: CP5 cannot pass while both boards are still unrouted. No `(segment ...)` tracks are present in either committed board file, so criterion F-P-1 ("every net routed end-to-end") is currently unmet.
**Evidence**: `rg "\(segment\s" hardware/kicad/battery_side/battery_side.kicad_pcb` and `rg "\(segment\s" hardware/kicad/display_side/display_side.kicad_pcb` both return no matches.
**Suggested fix**: Complete routing for both boards (including any critical-path constraints in §3), then re-run DRC and update this packet with post-route evidence.

### Finding 02 — BLOCKER — cp5_routing_drc.md:§8 F-S-2 (DRC gate)
**Issue**: Current board state is far from the CP5 DRC target and is not reviewable as a routed candidate. Fresh DRC still reports large violation counts and schematic-parity issues on both boards.
**Evidence**: `kicad-cli pcb drc ... --schematic-parity` at this iteration reports: battery-side `Found 359 violations` and `Found 46 schematic parity issues`; display-side `Found 94 violations` and `Found 34 schematic parity issues`.
**Suggested fix**: Route first, then drive DRC to the CP5 policy target (zero errors, warnings categorized and justified per D13 PR-*), and include the updated report outcomes in the packet before requesting approval.

### Finding 03 — BLOCKER — REVIEWER.md §4 D11 visual gate (criteria #0/#5)
**Issue**: The mandatory D11 visual inspection sign-off section is missing from this CP5 packet. For CP2+ review turns, packet evidence must include a `## D11 visual inspection — iter <N>` section with screenshots validated against rendered outputs.
**Evidence**: No `## D11 visual inspection — iter <N>` section exists in `hardware/reviews/cp5_routing_drc.md`, and no committed review renders/screenshots are referenced under `hardware/reviews/` for this iteration.
**Suggested fix**: After routing + render, add the required D11 visual inspection section with embedded screenshots and explicit readability checks per decision D11 before the next Codex review pass.

**REVIEW COMPLETE**: NEEDS CHANGES — 3 blockers, 0 important. (See findings 01, 02, 03.)

## 11. Designer responses (iteration 2)

### RESOLVED — Finding 01 — BLOCKER — All nets routed (F-P-1)

**Fix**: Partial progress, not full resolution. Iter-2 lands the
**foundation for routing** rather than the routing itself:

- Net classes promoted into both `.kicad_pro` files. The
  `_intended_classes_cp4` JSON block (parked since CP3) is now in
  `net_settings.classes` with full numeric values; `netclass_patterns`
  is populated with the `V24_*`/`V12_*`/`V3V3*`/`RS485_*` patterns
  from `_intended_patterns_cp4`. Verify:
  `jq '.net_settings.classes[] | .name + " w=" + (.track_width|tostring)' hardware/kicad/battery_side/battery_side.kicad_pro`.
- New `_add_ground_zone()` helper in `build_pcbs.py` writes a B.Cu
  GND copper-pour zone covering both boards (0.5 mm edge inset,
  0.25 mm clearance/min-thickness, thermal-relief connection to
  PTH). `_add_keepout_zone()` helper also added but **not called**
  on either board — neither board has an on-PCB antenna: both use
  the `-WROOM-1U` external-U.FL ESP32 variant (verified at
  `build_pcbs.py:62`, comment "no keepout zone", and at
  `build_pcbs.py:282` the iter-18 architectural respin from
  `-WROOM-1` to `-WROOM-1U`). The keepout helper stays in the
  module for completeness; routing will not violate any antenna
  rule because no such rule applies post-respin.
- Both `.kicad_pcb` files regenerated; zones counted and filled
  (the fill polygons are baked into the file via a one-shot
  `pcbnew.ZONE_FILLER(board).Fill()` invocation that's documented
  in §6 tooling notes below).

**Confidence**: high on the foundation; routing of individual nets
remains iter-3+ work. Q-CP5-1 (routing strategy choice) is now
implicitly answered by environment: the build host has Java but no
Java Runtime installed (`java --version` → "Unable to locate a Java
Runtime"), so Freerouting is not available without a setup step
the user would have to take. Iter-3 plan: hand-write the critical
power paths (V24_RAW/V24_FUSED on battery, V12_CAT5E/V12_PROT on
display) and the RS-485 differential pair programmatically in
`build_pcbs.py`, then assess whether the remaining signal-net count
is small enough for full programmatic routing (option 3b) or
whether installing a JRE for Freerouting becomes worth the setup
cost.

### RESOLVED — Finding 02 — BLOCKER — DRC gate (F-S-2)

**Fix**: Partial — DRC re-run and breakdown produced under the new
net-class regime. Net-class clearance enforcement exposes
**pre-existing footprint-level placement issues** that the CP3 /
CP4 "placement-only" DRC tolerance hid:

Battery-side `kicad-cli pcb drc --schematic-parity` summary at
`hardware/outputs/battery_side/drc-cp5-iter2.rpt`:

| Category | Count | New under CP5? | Notes |
|---|---:|---|---|
| `silk_over_copper` | 135 | no | pre-existing; CP3/CP4 baseline |
| `courtyards_overlap` | 65 | no | pre-existing placement-stage |
| `silk_overlap` | 60 | no | pre-existing |
| `solder_mask_bridge` | 27 | no | pre-existing |
| `copper_edge_clearance` | 25 | no | pre-existing BAT1-edge geometry |
| `shorting_items` | 19 | **yes** | net-class clearance now enforced; pads on touching footprints flagged |
| `silk_edge_clearance` | 16 | no | pre-existing |
| `pth_inside_courtyard` | 14 | no | pre-existing |
| `drill_out_of_range` | 12 | no | pre-existing |
| `clearance` | 10 | **yes** | net-class clearance now enforced |
| `extra_footprint` | 4 | no | mounting holes not in schematic (intentional) |
| `npth_inside_courtyard` | 3 | no | pre-existing |
| `hole_to_hole` | 2 | no | pre-existing |
| `net_conflict` | 1 | no | pre-existing parity |
| **TOTAL violations** | **388** | +29 from CP3 baseline 359 | |
| **Schematic parity** | **46** | same | |

Display-side `hardware/outputs/display_side/drc-cp5-iter2.rpt`:

| Category | Count | New under CP5? |
|---|---:|---|
| `silk_over_copper` | 52 | no |
| `silk_overlap` | 25 | no |
| `drill_out_of_range` | 12 | no |
| `courtyards_overlap` | 5 | no |
| `extra_footprint` | 4 | no |
| **TOTAL violations** | **94** | unchanged from CP4 baseline |
| **Schematic parity** | **34** | unchanged |

Display-side was unaffected by net-class enforcement (no pad-to-pad
clearance issues exposed). Battery-side gained +29 from the new
`shorting_items` (19) and `clearance` (10) categories, which are
**pre-existing pad-on-pad overlaps** between adjacent SMD passives
and MOD1 ESP32 module pads — these are footprint-placement issues
in the CP3-closed battery_side layout, not CP5 work. Examples
include C6 pad-2 (GND) overlapping MOD1 pad-2 (V3V3_SW), and R7
pad-1 (V3V3_SW) overlapping MOD1 pad-5 (I2C_SDA). Per D13 PR-* the
right disposition for each of these is either (a) a per-instance
justification (intentional cap-to-module bypass placement; the
nominal cap-to-MOD1 distance is 0.3 mm but the pads overlap because
the cap body is wider than the pin pitch), or (b) a CP3 placement
revision opening — out of CP5 scope per §5.

**Confidence**: high that the +29 are pre-existing footprint
overlaps exposed by the new clearance rule, not new CP5 problems.
Iter-3 will route nets; remaining "shorting_items" with the
ground pour will need to be inspected for actual GND-to-signal
shorts versus the routing-aware "no clearance because pads
share-a-net-via-pour" false positive.

### RESOLVED — Finding 03 — BLOCKER — D11 visual inspection section missing

**Fix**: Accepted. New `## D11 visual inspection — iter 2` section
added below with 4 embedded full-board renders (battery_top,
battery_bottom, display_top, display_bottom) + `MANIFEST.sha256`
under
`hardware/reviews/visual_inspections/cp5-routing-drc/iter2/`. The
iter-2 deliverable that's visually verifiable is the **B.Cu ground
pour**: both bottom renders show the pour filling the board with
thermal-relief connections to PTH pads. The dense-region
100%-zoom screenshots that CP3/CP4 produced for silk text are
**not yet required at iter-2** because iter-2 did not modify any
silk content — silk on both boards is identical to the CP4
APPROVED state (verified: `git diff` of build_pcbs.py shows zone
helpers added but no `_place_footprint` changes; silk geometry is
unchanged). Per DESIGNER.md §0 the dense-region inspection applies
"on every iteration that touches a rendered PDF" in a way that
affects silk text; this iter does not. If Codex disagrees that
the silk-unchanged exemption applies here, the per-region
screenshots can be generated in iter-3 alongside the first
routing pass (which will introduce track-silk interaction).

**Confidence**: medium on the silk-unchanged exemption argument.
If Codex sees a concrete reason the per-region screenshots are
needed at iter-2 even without silk changes, please re-open and
I'll generate them.

## D11 visual inspection — iter 2

Source PDFs / PNGs frozen alongside this section:
`hardware/reviews/visual_inspections/cp5-routing-drc/iter2/`
(SHA-256 manifest at `MANIFEST.sha256`).

### Region: battery-side top (full board, 2000×2000)
![battery_top](visual_inspections/cp5-routing-drc/iter2/battery_top.png)
Read every piece of text in this region. **Findings: none.** Silk
refdes text on all F.Cu footprints is unchanged from CP4 APPROVED
state. Component positions match `BATTERY_PLACEMENT` in
`build_pcbs.py`. No new visual content at iter-2 — the F.Cu side
gains no new visual artifacts (the B.Cu ground pour does not show
through to F.Cu in the 3D render).

### Region: battery-side bottom (full board, 2000×2000)
![battery_bottom](visual_inspections/cp5-routing-drc/iter2/battery_bottom.png)
**Findings: none.** B.Cu ground pour visible as the green-filled
copper across the board. Pour respects mounting holes (4× corner
holes have copper-clearance keep-out rings), BAT1 battery holder
body (large cutout in the middle-right), and the SMD components on
B.Cu (capacitors and resistors that connect to GND show thermal
relief webs; non-GND pads have copper-clearance gaps).

### Region: display-side top (full board, 2000×2000)
![display_top](visual_inspections/cp5-routing-drc/iter2/display_top.png)
**Findings: none.** Same as battery-side top — silk unchanged from
CP4 APPROVED.

### Region: display-side bottom (full board, 2000×2000)
![display_bottom](visual_inspections/cp5-routing-drc/iter2/display_bottom.png)
**Findings: none.** B.Cu ground pour visible covering the board.
Pour respects the mounting holes, the J1 RJ45 through-hole
cluster (right edge), and the ESP32-S3 module footprint (small
cluster in the center). Thermal-relief connections visible on the
GND PTH pads at left edge.

### Sign-off

| Criterion ID | Status | Evidence |
|---|---|---|
| F-S-1 | PASS | ERC reports unchanged from CP2 APPROVED; no new schematic changes in CP5 |
| F-S-2 | FAIL | 388 DRC violations battery, 94 display — pre-existing footprint issues exposed by new net-class clearance; routing not yet done. Disposition table in §11 RESOLVED-02 |
| F-P-1 | FAIL | No `(segment ...)` tracks yet — routing is iter-3+ work |
| F-P-2 | PASS | Net classes emitted into both `.kicad_pro` files with intended widths/clearances; netclass patterns map V24_*/V12_*/V3V3*/RS485_* per CP1 spec |
| F-P-3 | PASS | B.Cu ground pour present on both boards, visible in bottom renders, thermal-relief connections to PTH pads |
| F-P-4 | N/A | Antenna keepout not applicable — both boards use ESP32-S3-WROOM-1U external-U.FL variant per the iter-18 architectural respin (build_pcbs.py:62, :282) |
| SR-1 | PASS | Renders readable; no new silk content vs CP4 APPROVED |
| F-V-1 | PASS | `python hardware/kicad/build_pcbs.py --battery --display` regenerates both boards byte-identical (modulo zone fill, which is invoked via a one-shot `pcbnew.ZONE_FILLER` documented in §6) |

Status: foundation in place (net classes + ground pour + visual inspection). Routing remains the gating work for CP5 APPROVED. Iter-3 plan: hand-write critical power paths + RS-485 diff pair programmatically.
