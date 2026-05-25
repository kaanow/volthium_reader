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

Each iter must satisfy before handoff:
1. `python build_schematics.py` exits 0
2. `kicad-cli sch erc` returns 0/0 on both boards
3. `git diff hardware/outputs/*/[board].net` shows only:
   - `(date ...)` differences
   - `(tstamps ...)` UUIDs
   - (Maybe `(at X Y angle)` lines for component positions —
     these are metadata, not topology, but flag if any other diffs)
4. Lines with `(pin ...)` net membership: byte-identical
5. Lines with `(comp (ref X) (value Y) (footprint Z))`: stable
   (only Footprint may change if we tweak it; refs and values stay)

## 7. Open questions for Codex

### Q-SCH-1: Does the kiutils-based approach support wires?

kiutils' Schematic class includes a `graphicalItems` list that
holds Wire objects. Need to verify the API for creating Wire(start,
end, stroke). If kiutils doesn't expose it cleanly, fall back to
emitting the S-expression directly.

### Q-SCH-2: Title block fields — KiCad property or schematic-level?

KiCad 10 stores Title/Rev/Date on the .kicad_sch root via
`(title_block ...)`. Need to set via kiutils Schematic.title_block
or equivalent.

### Q-SCH-3: How aggressive should "wire-replacement" be?

Replacing ALL net labels with wires would be unreadable too (giant
spaghetti). Proposal: net labels stay for any net that connects
>2 pins OR connects pins >50mm apart. Wires replace short adjacent
connections only. Codex: agree?

### Q-SCH-4: Single CP vs split battery + display?

Both schematics have the same issues. Plan above does both in one
CP. Alternative: do battery-side first, get APPROVED, then display.

Default: one CP, both schematics, ~6 iters total.

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
