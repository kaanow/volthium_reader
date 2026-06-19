# `hardware/layout/` — design process docs

This folder holds the working documents Claude uses to drive the PCB design
through to a fab-ready package. The engineering *specification* lives in
[`docs/hardware/`](../../docs/hardware/) (block diagrams, BOM, schematic
intent); this folder is the *how-do-we-get-there*.

## Process

The work is gated by five checkpoints. Each checkpoint produces a review
packet in [`../reviews/`](../reviews/) and the work pauses for human / agent
review before continuing.

| CP | Phase                  | Outputs                                                          | Reviewer asks                                  |
|----|------------------------|------------------------------------------------------------------|-----------------------------------------------|
| 1  | **Design baseline**    | Per-board net + part lists, updated BOM, layout strategy         | Is this the right design before we draw it?    |
| 2  | **Schematic capture**  | `.kicad_sch`, ERC report, schematic PDFs, netlist                | Do schematics match the baseline?              |
| 3  | **Placement**          | Footprints placed, top/bottom PNG, dimensioned drawing           | Is the placement physically + electrically OK? |
| 4  | **Routing + DRC**      | Fully routed `.kicad_pcb`, DRC report, copper pours              | Is this routable to fab?                       |
| 5  | **Fab-ready**          | Gerbers, drill, position file, BOM CSV, fab checklist            | Would you click "order" on this?               |

## Layout

```
hardware/
├── layout/                      ← THIS FOLDER
│   ├── README.md                 — process index (this file)
│   ├── decisions.md              — every committed design decision + rationale
│   ├── cp1_battery_side.md       — CP1 baseline doc, battery-side
│   ├── cp1_display_side.md       — CP1 baseline doc, display-side
│   └── cp1_bom.md                — CP1 BOM (supersedes docs/hardware/bom.md
│                                    where they disagree)
├── kicad/
│   ├── battery_side/             — KiCad 10 project (CP2+ artifacts)
│   ├── display_side/             — KiCad 10 project (CP2+ artifacts)
│   ├── libraries/                — custom symbols/footprints we author
│   ├── battery_side.py           — legacy SKiDL (reference only; not source of truth)
│   ├── display_side.py           — legacy SKiDL (reference only)
│   └── HANDOFF.md                — original handoff (historical; superseded by this folder)
├── reviews/                     — checkpoint review packets
│   └── cpN_<phase>.md            — one per checkpoint
└── outputs/                     — build artifacts (Gerbers, BOMs, renders)
    ├── battery_side/
    └── display_side/
```

## Workflow notes

- **Source of truth = KiCad 10 native files** (`.kicad_pro`, `.kicad_sch`,
  `.kicad_pcb`). The existing SKiDL Python in `hardware/kicad/*.py` is
  preserved as a design-intent reference for the reviewer but is not the
  source we'll regenerate from.
- **Programmatic where possible** — schematic capture, footprint placement,
  ERC/DRC, exports are all scripted via `kiutils` + `kicad-cli` so design
  changes are reproducible and reviewable as diffs.
- **GUI where necessary** — interactive routing in CP4 may need human-driven
  KiCad PCB Editor work for the harder traces. Where that happens, the
  diff against the prior committed `.kicad_pcb` is the reviewable artifact.
- The autonomous loop in [`docs/STATUS.md`](../../docs/STATUS.md) is **not**
  driving this work — hardware progress is checkpoint-gated, not loop-driven.

## Cross-references

- [`decisions.md`](decisions.md) — the single source of "what did we commit to and why"
- [`../../docs/hardware/`](../../docs/hardware/) — engineering specification
- [`../kicad/README.md`](../kicad/README.md) — current build flow (kiutils / KiCad 10). The original SKiDL → KiCad 8 plan is archived at [`../kicad/archive/`](../kicad/archive/)
