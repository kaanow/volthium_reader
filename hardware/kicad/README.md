# `hardware/kicad/` — KiCad design package

This directory holds the SKiDL Python that describes the two boards
plus the runbook for finishing the PCB on a machine with KiCad
installed.

## File map

| File / dir                  | What                                              |
|-----------------------------|---------------------------------------------------|
| `HANDOFF.md`                | **The runbook.** Start here on a fresh machine.  |
| `battery_side.py`           | SKiDL source for the battery-side board           |
| `display_side.py`           | SKiDL source for the display-side board           |
| `symbol_footprint_map.md`   | Auditable table of every component → KiCad symbol + footprint |
| `test_smoke.py`             | Environment check — run first on any new machine |
| `run.sh`                    | One-command netlist regeneration                  |
| `projects/`                 | KiCad projects (created during PCB layout)        |
| `outputs/`                  | Generated netlists, Gerbers, renders (gitignored) |

## Workflow at a glance

```
   battery_side.py ─► run.sh ─► outputs/battery_side.net ─► KiCad PCB editor
   display_side.py ─►          outputs/display_side.net   (layout + route)
                                                          │
                                                          ▼
                                                   outputs/*_gerbers/
                                                   outputs/*.pdf
                                                   outputs/*.png
                                                          │
                                                          ▼
                                                   send to JLCPCB / OSH Park
```

`.py` files are the source of truth. The `.kicad_sch` files are
generated downstream and should be treated as build artifacts.

## If you're on a fresh machine

```bash
cd hardware/kicad
../../.venv/bin/python test_smoke.py    # verifies env
./run.sh                                # regenerates netlists
```

Then follow `HANDOFF.md` step by step for the PCB layout work.
