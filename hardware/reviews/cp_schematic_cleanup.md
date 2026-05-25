# CP-schematic-cleanup review packet — D11 readability pass

**Status**: ready for review (iteration 1 — approach)
**Opened**: 2026-05-24
**Branch**: `hw/cp-schematic-cleanup`
**Goal**: bring the CP2-generated schematic PDFs up to the D11
engineer-readable bar (see [`decisions.md` §D11](../layout/decisions.md#d11)),
on a branch off main, **without** changing netlist topology.

## 1. The trigger

At CP3 iter 14, the user reviewed the CP2 schematic PDFs and
flagged them as functionally correct but unreadable as engineering
documents: overlapping symbols, only net-label connections (no
wires), blank title block, no functional grouping, smeared labels.

Project rule D11 was added with seven concrete acceptance criteria.
The CP2 PDFs currently fail criteria #1-#5. This CP fixes them.

## 2. Non-goals (hard guardrails)

- **Netlist topology MUST NOT change.** Every component, every pin
  assignment, every net membership stays identical. Verifiable by
  byte-comparing the regenerated `.net` files modulo cosmetic
  metadata (date, tstamps, Footprint strings if any).
- **ERC must remain 0/0** on both schematics throughout.
- **CP3 PCB work must not be invalidated.** The PCB consumes nets
  by name + component by ref; both stay stable.

If at any point during this CP either guardrail breaks, abort and
re-plan — don't ship a working-but-different-topology schematic.

## 3. The seven D11 criteria mapped to fix-work

| # | Criterion | CP2 status | Fix |
|---|-----------|-----------|-----|
| 1 | No symbol overlap | FAIL — multiple components at duplicate (x, y) | Audit `build_schematics.py` for duplicate placements; assign unique coords to every `_place_symbol` call |
| 2 | Real wires within clusters | FAIL — pure net-label graph | Add `Wire` graphic elements for short within-cluster connections (bypass cap to chip pin, divider middle, decoupling-to-power). Keep net labels for cross-cluster nets (GND, V3V3, named buses) |
| 3 | Functional grouping with signal flow | FAIL — components scattered | Reorganize coordinate layout so functional blocks (power input chain, regulator + bypass, MCU + decoupling, RTC + backup, RS-485, button, headers) occupy contiguous rectangles with left-to-right signal flow |
| 4 | Populated title block | FAIL — empty | Set Title, Rev, Date, Company in `.kicad_sch` via the title-block fields KiCad reads from the project's metadata |
| 5 | Legible at 100% zoom | FAIL — labels smear | After fixes #1-#3, audit label position collisions by viewing PDFs at 100% — fix any remaining overlaps |
| 6 | Power rails on consistent edges | PARTIAL — GND/V3V3 scattered | Reflow so power rails are net-labeled at the top edge of each sheet, GND at the bottom |
| 7 | Reference designators visible on renders | PASS — already done at CP3 iter 8 for the PCB | N/A — schematic-side this means refdes is visible (already is via symbol property) |

## 4. Approach

**Source of truth stays `build_schematics.py`.** All edits are to the
Python that generates the schematics. The .kicad_sch files are
re-emitted, not hand-edited. This keeps the workflow transportable
to future projects: regenerate, ERC-check, render PDF, all in one
script run.

**Iteration plan** (~6 iters):

| Iter | Scope |
|------|-------|
| 1 (this) | Approach packet + audit duplicate placements (criterion #1) |
| 3 | Add title block to both sheets (criterion #4) — small, isolated change |
| 5 | Reflow placements into functional groups + signal flow (criterion #3, #6) |
| 7 | Replace within-cluster net labels with wires (criterion #2) |
| 9 | Audit label legibility at 100% zoom (criterion #5) |
| 11 | Render PDFs, compare to D11 acceptance criteria, close CP |

## 5. Audit method for criterion #1

Programmatic check: extract every `_place_symbol` call's coordinates
from build_schematics.py, group by (x, y), report any tuple with
>1 component.

```
grep "_place_symbol" build_schematics.py | python tool/dedupe_audit.py
```

Or simpler: dump symbol Position blocks from regenerated .kicad_sch
files and report duplicate (X, Y).

## 6. Verification gates per iter

Each iter must satisfy ALL of the following before handoff. Per-board
results are reported separately (battery-side and display-side
explicitly listed in the iter handoff note) so regressions can't
hide behind aggregate language.

1. `python build_schematics.py` exits 0.
2. `kicad-cli sch erc` returns 0/0 on each board independently.
3. `git diff hardware/outputs/<board>/<board>.net` for each board
   shows only:
   - `(date ...)` differences
   - `(tstamps ...)` UUIDs
   - (Maybe `(at X Y angle)` lines for component positions —
     these are metadata, not topology, but flag if any other diffs)
4. Lines with `(pin ...)` net membership: byte-identical per board.
5. Lines with `(comp (ref X) (value Y) (footprint Z))`: stable per
   board (refs + values must not change; Footprint string may
   change if intentional).
6. **PCB DRC regression gate** (added per Finding 01): for each
   board, run
   ```
   cd hardware/kicad/<board>
   kicad-cli pcb drc --severity-error <board>.kicad_pcb
   ```
   from the project directory so the project's `.kicad_pro`
   severity overrides apply. Expected: **0 errors** for
   battery-side at every iter (matches CP3-close baseline);
   display-side is N/A until a PCB exists for it. If error count
   rises above 0, the iter aborts.

## 7. Open questions for Codex

### Q-SCH-1: Wire emission — kiutils API vs direct S-expression?

**Resolved per Codex Finding 02**: the pinned kiutils does not
expose a `Wire` class in `kiutils.items.schitems` (verified by
runtime inspection). Available related classes: `PolyLine`,
`BusEntry`, `BusAlias`. Plan: **direct S-expression emission of
`(wire (pts (xy X1 Y1) (xy X2 Y2)) (stroke ...) (uuid ...))`** as
the primary implementation path for criterion #2. Wrap in a small
helper in `build_schematics.py` that takes (start, end) and emits
the wire S-expr. Keep a serialization test that confirms KiCad
re-opens the schematic and ERC stays 0/0 after each wire is added.

### Q-SCH-2: Title block fields — kiutils attribute name?

**Resolved per Codex Finding 03**: the kiutils attribute is
`Schematic.titleBlock` (camelCase), not `title_block`. Verified by
runtime inspection. Plan: set `s.titleBlock.title`,
`s.titleBlock.revision`, `s.titleBlock.date`, `s.titleBlock.company`
explicitly. Verify by asserting `(title_block` appears in both
emitted `.kicad_sch` files and in exported PDFs.

### Q-SCH-3: How aggressive should "wire-replacement" be?

Replacing ALL net labels with wires would be unreadable too (giant
spaghetti). Proposal: net labels stay for any net that connects
>2 pins OR connects pins >50mm apart. Wires replace short adjacent
connections only. Codex: agree?

### Q-SCH-4: Single CP vs split battery + display?

**Resolved per Codex Finding 04**: one CP, both boards, but **each
iter handoff note reports criterion pass/fail per board** —
battery-side vs display-side — so regressions cannot hide behind
aggregate language. Aggregate "both boards" statements only appear
in the final closeout, not in per-iter notes.

## 8. Success criteria (CP overall)

- [ ] Both schematics regenerate from build_schematics.py
- [ ] ERC 0/0 on both
- [ ] Netlist topology byte-identical (modulo cosmetic metadata)
- [ ] Every D11 criterion (1-6) verifiably passing on both PDFs
- [ ] PDFs visually reviewed by user before merge to main
- [ ] No regression in CP3 PCB DRC (refs + nets unchanged)

## 9. Iter-1 audit results — criterion #1 (symbol coord collisions)

Programmatic check across both regenerated `.kicad_sch` files:

```
battery_side: 46 symbols, 45 unique positions, 1 collision
  (76.20, 76.20) → ['#FLG1', 'Q2']
display_side: 34 symbols, 34 unique positions, 0 collisions
```

**Net:** 1 raw coordinate collision (PWR_FLAG sitting on top of Q2).
Fix is a 1-line coordinate change in `build_schematics.py`.

The wider PDF readability problem (visible "stacked components" in
the rendered output) is **not** primarily from raw coordinate
collisions — it's from:
- Symbol bodies whose bounding boxes extend across each other even
  when their `(at X Y)` anchors differ
- Dense net-label placement at boundaries
- A 280 × 200 mm A4 sheet where ~70 components are packed into the
  upper-left ~150 × 100 mm quadrant

So the iter-3+ work is primarily **bounding-box-aware reflow**
(criterion #3, signal-flow grouping) and **wire replacement**
(criterion #2), not just dedup. Criterion #1 is essentially a
one-line fix.

## 10. Reviewer findings (append-only)

*(append per the format in REVIEWER.md §5)*

### Finding 01 — IMPORTANT — cp_schematic_cleanup.md:§6 Verification gates
**Issue**: The per-iteration verification gates do not check PCB DRC stability, even though this CP's guardrail says CP3 PCB work must not be invalidated and REVIEWER protocol for CP2+ requires running `kicad-cli pcb drc`.
**Evidence**: Running `kicad-cli pcb drc hardware/kicad/battery_side/battery_side.kicad_pcb` on this branch reports `Found 359 violations` (report: `battery_side-drc.rpt`). Current §6 gates only mention schematic ERC + netlist checks.
**Suggested fix**: Add a DRC regression gate that compares against a checked-in baseline report/count (or at minimum violation count + classes), and fail the iteration if new violations appear.

### Finding 02 — IMPORTANT — cp_schematic_cleanup.md:§7 Q-SCH-1
**Issue**: The plan assumes kiutils may expose a direct `Wire` API, but the currently pinned environment does not expose a `Wire` class in `kiutils.items.schitems`; treating that path as likely can block criterion #2 implementation.
**Evidence**: Runtime inspection in project venv: `hasattr(kiutils.items.schitems, "Wire") == False`; available related classes include `PolyLine`, `BusEntry`, and `BusAlias`.
**Suggested fix**: Treat direct S-expression emission of `(wire ...)` segments as the primary plan for criterion #2 (not fallback), and keep a small serialization test that confirms KiCad re-opens + ERC stays 0/0 after emission.

### Finding 03 — QUESTION — cp_schematic_cleanup.md:§7 Q-SCH-2
**Issue**: Confirmed naming detail: in current kiutils the schematic-level title block field is `Schematic.titleBlock` (camelCase), not `title_block`; this should be explicit in the plan to avoid no-op writes.
**Evidence**: Runtime inspection in project venv: `hasattr(Schematic(), "titleBlock") == True`, `hasattr(Schematic(), "title_block") == False`. Current generated schematic also has no `(title_block ...)` node.
**Suggested fix**: Update the implementation note to set `s.titleBlock` explicitly, then verify by asserting `(title_block` appears in both emitted `.kicad_sch` files and in exported PDFs.

### Finding 04 — QUESTION — cp_schematic_cleanup.md:§7 Q-SCH-4
**Issue**: One CP for both boards is acceptable if each iteration keeps objective acceptance checks board-scoped; otherwise regressions can hide behind aggregate "both boards" statements.
**Evidence**: This CP already has board-specific artifacts (`hardware/outputs/battery_side/*` and `hardware/outputs/display_side/*`) and independent ERC runs.
**Suggested fix**: Keep a single CP, but report criterion pass/fail per board in each iteration note (battery-side vs display-side), then aggregate only in the final closeout.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 01, 02.)

---

## 11. Designer response (iteration 2)

### Response to Finding 01 — DRC regression gate — ACCEPTED

Updated §6 to add gate #6: PCB DRC must be re-run from the project
directory (`hardware/kicad/<board>/`) so the project's `.kicad_pro`
severity overrides apply, and must report **0 errors** at every
iter handoff.

Note on Codex's 359-violation evidence: that count came from
invoking `kicad-cli pcb drc` without `cd`ing into the project
directory, so the `.kicad_pro` rule_severities overrides (in place
since CP3 iter 6) didn't apply. From the project directory at this
branch's tip:

```
cd hardware/kicad/battery_side
kicad-cli pcb drc --severity-error battery_side.kicad_pcb
→ Found 0 violations, 0 unconnected items, 0 footprint errors
```

This is the baseline for the gate. Every iter on this branch must
keep it at 0 errors for the battery-side. (Display-side has no PCB
yet; gate is N/A there.)

### Response to Finding 02 — Wire emission via S-expr — ACCEPTED

Updated §7 Q-SCH-1 to make direct `(wire ...)` S-expression
emission the primary implementation path, not the fallback. Added
a serialization-test requirement: every iter that adds wires must
verify `kicad-cli sch erc` still returns 0/0 on each board.

### Response to Finding 03 — `titleBlock` attribute — ACCEPTED

Updated §7 Q-SCH-2 with the correct kiutils attribute name
(`Schematic.titleBlock`, camelCase). Will assert `(title_block`
appears in both emitted `.kicad_sch` files and the rendered PDFs
as part of the iter-3 verification.

### Response to Finding 04 — per-board reporting — ACCEPTED

Updated §6 to require per-board reporting in each iter handoff
note. Updated §7 Q-SCH-4 with the resolved policy. Aggregate
"both boards" language only appears in the final closeout.

### Handing back

State → `codex_turn`, iter 3. Codex: please re-verify:
- §6 now lists 6 verification gates including the DRC regression
  gate run from project dir.
- §7 Q-SCH-1 commits to S-expression wire emission as the primary
  path, with a serialization test requirement.
- §7 Q-SCH-2 names the kiutils attribute correctly as
  `Schematic.titleBlock` (camelCase).
- §7 Q-SCH-4 commits to per-board reporting per iter.

If clean, mark Findings 01-04 resolved and APPROVE so iter 4 starts
the smallest concrete fix: PWR_FLAG/Q2 coordinate dedup +
populated title block on both schematics.

## 12. Reviewer findings (iteration 3)

Re-review completed for Findings 01-04 and verification gates:
- Confirmed §6 now includes the PCB DRC regression gate with
  project-directory invocation and expected zero battery-side errors.
- Confirmed §7 Q-SCH-1 names direct `(wire ...)` S-expression emission
  as the primary path with serialization/ERC verification.
- Confirmed §7 Q-SCH-2 uses `Schematic.titleBlock` (camelCase).
- Confirmed §7 Q-SCH-4 requires per-board pass/fail reporting each
  iteration.
- Re-ran gates this iteration:
  - `kicad-cli sch erc` (battery_side): 0 violations.
  - `kicad-cli sch erc` (display_side): 0 violations.
  - `kicad-cli pcb drc --severity-error` (battery_side): 0 violations,
    0 unconnected items.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

---

## 12. Designer iter 4 — D11 criterion #1 + #4

### Changes

**Criterion #1: PWR_FLAG/Q2 dedup**

`build_schematics.py` line 994: V_BAT_RTC PWR_FLAG y offset changed
from `R5_Y + 20*G` to `R5_Y + 26*G`. The +20*G value computed to
y=76.2 which exactly collided with Q2 at (60*G=76.2, 60*G=76.2).
New y=83.82 places the PWR_FLAG 7.62 mm below Q2 with no other
nearby symbol.

**Criterion #4: Title block on both sheets**

Added `_set_title_block(sch, title)` helper that sets
`Schematic.titleBlock` (kiutils camelCase, per Finding 03) with:

```
title:    "Volthium reader — battery side"  / "...display side"
revision: "CP-schematic-cleanup"
date:     "2026-05-24"
company:  "Volthium"
```

Verified `(title_block ...)` block appears in both `.kicad_sch`
files and renders correctly in the PDF title-block corner.

### Side fix — `.kicad_pro` regression on schematic regen

While verifying gate #6 (PCB DRC from project dir), discovered that
the PCB DRC errors had jumped from 0 to 146. Root cause:
`write_project_file` in `build_schematics.py` overwrites the
`.kicad_pro` on every regen, stripping CP3's rule_severities
overrides and named net classes.

Fix: `write_project_file` now writes the full CP3-required project
config (rule_severities + 5 named classes + intent comments). Every
future schematic regen preserves the PCB design settings. Verified
DRC back to 0 errors after rebuild.

This is a workflow-transportability win — future runs of
`build_schematics.py` won't silently regress PCB DRC. Worth a
short note for any future PCB project that pairs schematic +
PCB generation.

### Per-board verification (per Codex Finding 04 protocol)

| Gate | battery_side | display_side |
|------|--------------|--------------|
| 1. `build_schematics.py` exit 0 | PASS | PASS |
| 2. ERC 0/0 | PASS (0 errors, 0 warnings) | PASS (0 errors, 0 warnings) |
| 3. Netlist diff = title_block only | PASS (only `(title)`, `(company)`, `(rev)` strings differ) | PASS (same) |
| 4. `(pin ...)` byte-identical | PASS | PASS |
| 5. `(comp (ref X) (value Y) (footprint Z))` stable | PASS | PASS |
| 6. PCB DRC 0 errors from project dir | PASS (0 violations, 0 unconnected) | N/A (no PCB) |

### Coord collision audit (criterion #1 re-check)

```
battery_side: 46 symbols, 46 unique positions, 0 collisions
display_side: 34 symbols, 34 unique positions, 0 collisions
```

Both boards: criterion #1 PASS.

### D11 status

| Criterion | battery_side | display_side |
|-----------|--------------|--------------|
| #1 no symbol overlap (coord) | PASS | PASS |
| #4 populated title block | PASS | PASS |
| #2 real wires within clusters | pending iter 8 | pending iter 8 |
| #3 functional grouping + flow | pending iter 6 | pending iter 6 |
| #5 legible at 100% zoom | pending iter 10 | pending iter 10 |
| #6 power rails on consistent edges | pending iter 6 | pending iter 6 |
| #7 refdes visible | PASS (PCB; sch always shown) | PASS |

### Handing back

State → `codex_turn`, iter 5. Codex: please re-verify all 6 gates
per board (battery + display) and the D11 status table. Specifically:
- PWR_FLAG/Q2 collision at (76.2, 76.2) gone — V_BAT_RTC PWR_FLAG
  now at (76.2, 83.82).
- `(title_block ...)` block present in both `.kicad_sch` and
  renders in the PDF corner.
- Netlist topology preserved: only `(title)`/`(company)`/`(rev)`
  strings change; refs/pins/nets identical.
- PCB DRC from `hardware/kicad/battery_side/`: still 0 errors.
- `write_project_file` fix prevents future regression of
  rule_severities + named classes.

If clean, APPROVE so iter 6 starts on criterion #3 + #6 (functional
grouping + power rails on consistent edges) — the largest scope of
this CP.
