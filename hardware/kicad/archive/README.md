# `hardware/kicad/archive/` — superseded SKiDL / KiCad-8 toolchain

Historical only. These files are the project's **original generation
path** and are no longer used.

## Why they're here

At project genesis the boards were authored *without* KiCad on the
machine, using **SKiDL** (Python → netlist, targeting **KiCad 8**), with
`HANDOFF.md` as a runbook for a future session that would bring the repo
to a KiCad machine and finish the PCB **by hand in the GUI**.

That era is over. The project now runs on **KiCad 10** with a
**programmatic kiutils flow** — `build_schematics.py` generates the
schematics and exports the netlist via `kicad-cli`, and `build_pcbs.py`
places footprints, routes, fills zones, and exports fab outputs in code.
The handoff it was written for already happened, and the manual KiCad-8
process it documents was replaced. See decisions.md **D1** (and the
re-open, **D18/D19**).

## Contents

| File | What it was |
|------|-------------|
| `battery_side.py` / `display_side.py` | SKiDL source (KiCad 8) — the original "source of truth"; superseded by `build_schematics.py` |
| `run.sh` | One-command SKiDL netlist regeneration |
| `HANDOFF.md` | Genesis runbook: finish the PCB by hand on a KiCad-8 machine |
| `symbol_footprint_map.md` | KiCad-8 symbol/footprint audit table (also pre-D19 part set) |

(`test_smoke.py`, the SKiDL environment check, was removed — it imported
`skidl` and would fail under the current toolchain; it's in git history.)

## Current build

See [`../README.md`](../README.md).

## build_schematics_v1_kiutils_SUPERSEDED.py (retired 2026-07-19, CP2 restart)

The first kiutils/KiCad-10 schematic generator. Retired because its
architecture produced a *graphical netlist*, not a readable schematic: it
auto-placed symbols and hung a net-label stub on every pin, treating wires
as "purely decorative" (see its own `_place_wire` docstring) and net labels
as the real connectivity — backwards. It also only ever built a partial
power-input slice of the pre-D19 design (TPS62933/DS3231/Q_PMOS).

**Kept for reference only** — salvage the kiutils primitives (symbol
placement, `kicad-cli` erc/export pipeline, the chevron/field-rotation
lessons in its comments), not the philosophy. The CP2 rebuild lives in
`hardware/kicad/schematic/` and is wires-first + hierarchical + block-
structured with a hard geometric readability gate.
