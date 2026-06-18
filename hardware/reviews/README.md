# `hardware/reviews/` — checkpoint review packets

Each PCB-design checkpoint produces a review packet here. Reviewers
(human or agent) start from the packet, follow links into the design
docs, and post findings as comments / commits / PR suggestions.

| File                            | Phase                | Status     |
|---------------------------------|----------------------|------------|
| `cp1_design_baseline.md`         | Design baseline      | **in review (re-opened, D18/D19)** |
| `cp2_schematic_capture.md`       | Schematic capture    | not started (next) |
| `cp3_placement.md`               | Footprint placement (battery) | not started |
| `cp4_display_placement.md`       | Footprint placement (display) | not started |
| `cp5_routing_drc.md`             | Routing + DRC        | not started |
| `cp6_fab_ready.md`               | Fab-ready package    | not started |

> **Note (2026-06-18):** CP1 was re-opened (decisions.md **D18**) after the
> engineering-correctness gate (D17) found CP1/CP2 architecture defects that
> had ridden to "CP6 fab-ready". The **prior CP2–CP6 review packets** (and
> the CP6 visual-inspection crops) describe board work built on the
> pre-D19 schematics and are **superseded** — they now live in
> [`archive/`](archive/) for history. New CP2+ packets will be written
> fresh against the corrected D19 design.

## What a review packet contains

Each packet is a single markdown file with:

1. **Status banner** — checkpoint name, date opened, current state
2. **What changed since the last checkpoint** — diff summary (commits, file list)
3. **What to look at** — pointers into the design docs + KiCad files,
   with the specific questions to evaluate
4. **Known unknowns / open decisions** — questions Claude is asking the
   reviewer to settle
5. **Success criteria** — what the reviewer needs to see to mark this
   checkpoint passed
6. **Reviewer findings** — appended by the reviewer; iterates until
   findings are resolved

## How to drive a review cycle

1. Claude commits the work and writes the packet
2. User triggers the reviewer (separate agent or human)
3. Reviewer appends findings to the packet
4. Claude addresses findings; updates packet with responses
5. Cycle continues until reviewer marks checkpoint passed
6. Next checkpoint begins

The reviewer is expected to read the packet only, not chase down design
decisions across the repo unless flagged. Claude's job is to make the
review packet self-contained.
