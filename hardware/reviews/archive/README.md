# `hardware/reviews/archive/` — superseded review artifacts

These files are **historical** — kept for traceability, not current.

## Why they're here

The project reached a nominal "CP6 fab-ready" state, then the
engineering-correctness gate (decisions.md **D17**) found CP1/CP2
architecture defects (input-protection mis-coordination, a load switch
that couldn't boot the board) that every automated gate had passed. So
**CP1 was re-opened** (decisions.md **D18**) and the battery-side power
architecture re-derived (**D19**). All board work below CP1 — placement,
routing, fab, and their reviews — was built on the **pre-D19 schematics**
and is therefore **superseded**. It will be regenerated from the corrected
design at the new CP2+.

## Contents

| File | What it was |
|------|-------------|
| `cp2_schematic_capture.md` | CP2 review packet (pre-D19 schematic) |
| `cp3_placement.md` | CP3 battery-side placement review |
| `cp4_display_placement.md` | CP4 display-side placement review |
| `cp5_routing_drc.md` | CP5 routing + DRC review |
| `cp6_fab_ready.md` | CP6 fab-ready review (the pass that "passed" with the defects) |
| `cp_schematic_cleanup.md` | Interim schematic-readability cleanup review |
| `visual_inspections/` | CP6 per-region render crops used during readability review |

## Where the current truth lives

- **Decisions:** [`../../layout/decisions.md`](../../layout/decisions.md) (D17/D18/D19)
- **Live CP1 packet:** [`../cp1_design_baseline.md`](../cp1_design_baseline.md)
- **Per-board baselines:** [`../../layout/cp1_battery_side.md`](../../layout/cp1_battery_side.md), [`../../layout/cp1_display_side.md`](../../layout/cp1_display_side.md)
- **Design-review log:** [`../DESIGN_REVIEW_ITEMS.md`](../DESIGN_REVIEW_ITEMS.md)

Links inside the archived files may point to paths as they existed before
archiving; that's expected for frozen history.
