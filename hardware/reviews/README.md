# `hardware/reviews/` — checkpoint review packets

Each PCB-design checkpoint produces a review packet here. Reviewers
(human or agent) start from the packet, follow links into the design
docs, and post findings as comments / commits / PR suggestions.

| File                            | Phase                | Status     |
|---------------------------------|----------------------|------------|
| `cp1_design_baseline.md`         | Design baseline      | pending    |
| `cp2_schematic_capture.md`       | Schematic capture    | not started |
| `cp3_placement.md`               | Footprint placement  | not started |
| `cp4_routing_drc.md`             | Routing + DRC        | not started |
| `cp5_fab_ready.md`               | Fab-ready package    | not started |

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
