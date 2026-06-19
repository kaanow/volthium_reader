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
