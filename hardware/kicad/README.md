# `hardware/kicad/` — KiCad design package

Both boards are generated **programmatically** from Python (kiutils +
`kicad-cli`) on **KiCad 10**. The `.kicad_sch` / `.kicad_pcb` files are
build artifacts — edit the generators, not the KiCad files.

## File map

| File / dir              | What                                                          |
|-------------------------|--------------------------------------------------------------|
| `build_schematics.py`   | **Source of truth.** Builds each board's `.kicad_sch`, runs `kicad-cli sch` upgrade/ERC, and exports the netlist + schematic PDF. Also runs the readability/geometry audits. |
| `build_pcbs.py`         | Builds each `.kicad_pcb` from the exported netlist: places footprints, routes, fills zones, exports Gerbers/drill/pos/STEP + renders. |
| `dedupe_pdf_text.py`    | Post-processes exported schematic PDFs (PyMuPDF).            |
| `libraries/`            | Custom symbols (`volthium.kicad_sym`) + footprints (`volthium.pretty/`). |
| `battery_side/`, `display_side/` | Per-board KiCad project dirs. Hold the human-maintained `.kicad_pro` + lib tables; the `.kicad_sch`/`.kicad_pcb` are regenerated into them. |
| `_smoke/`               | Minimal smoke-test board fixture.                            |
| `archive/`              | **Superseded** SKiDL / KiCad-8 toolchain (genesis). See `archive/README.md`. |

Outputs (netlists, PDFs, Gerbers, renders) land in
[`../outputs/`](../outputs/) and are regenerated — not hand-edited.

## Build flow

```
build_schematics.py ─► battery_side/battery_side.kicad_sch  ─┐ kicad-cli
                       display_side/display_side.kicad_sch  ─┘ ERC + export
                                                              │
                                                              ▼
                                  ../outputs/<board>/{<board>.net, schematic.pdf, erc.rpt}
                                                              │
build_pcbs.py  (reads the .net) ──────────────────────────────┘
       └─► <board>/<board>.kicad_pcb  +  ../outputs/<board>/{fab/, *.png, ...}
```

## Requirements

- **KiCad 10** with `kicad-cli` on `PATH`.
- A Python venv with the deps in [`../../requirements-hw.txt`](../../requirements-hw.txt) (kiutils, PyMuPDF). `build_pcbs.py` also shells out to KiCad's bundled `pcbnew` Python for zone fills / SES import.

## Run

```bash
cd hardware/kicad
python build_schematics.py        # schematics + ERC + netlist/PDF export  (see --help)
python build_pcbs.py              # placement + routing + fab outputs        (see --help)
```

The `.kicad_pro` project files are human-maintained and **preserved**
across regeneration (the generators snapshot and restore them). The old
SKiDL/KiCad-8 path lives in [`archive/`](archive/) for history.
