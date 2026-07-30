# `hardware/kicad/` — KiCad design package

Both boards are generated **programmatically** from Python (kiutils +
`kicad-cli`) on **KiCad 10**. The `.kicad_sch` / `.kicad_pcb` files are
build artifacts — edit the generators, not the KiCad files.

## File map

| File / dir      | What                                                          |
|-----------------|---------------------------------------------------------------|
| `schematic/`    | **Schematic source of truth.** `core.py` (shared generator core + full gate stack), `build.py` (battery board), `build_display.py` (display board), `testdata/` (standing poison fixtures for the build-start self-test). Outputs land in `schematic/build/` (battery) and `schematic/build_display/` (display): `.kicad_sch` hierarchy, `.kicad_pro`, netlist, PDF, per-sheet PNGs. |
| `pcb/`          | **Placement/routing source of truth** (CP3+). Same pattern: shared core + per-board build scripts; outputs in `pcb/build/` / `pcb/build_display/`. |
| `libraries/`    | Custom symbols (`volthium.kicad_sym`).                        |
| `footprints/`   | Custom footprints (`volthium.pretty/`) with provenance README. |
| `archive/`      | **Superseded** toolchains: SKiDL/KiCad-8 genesis, plus `pass1_pcb/` (the first design pass's placement/routing generator + board projects + outputs, retired when the design was re-baselined at CP1). See `archive/README.md`. |

## Requirements

- **KiCad 10** with `kicad-cli` discoverable (see the generator's startup
  print for the resolved share/CLI pairing).
- The repo venv (`.venv/`) with kiutils + PyMuPDF.

## Run

```bash
# battery-side schematic (gates + ERC + netlist + PDF/PNG export)
.venv/bin/python hardware/kicad/schematic/build.py
# display-side schematic
.venv/bin/python hardware/kicad/schematic/build_display.py
# battery-side placement (CP3)
.venv/bin/python hardware/kicad/pcb/build.py
```

Every generator carries its own gate stack (readability, glyph, pdf-text
ground truth, netlist intent==actual, exact-part contracts, strict full
ERC/DRC, build-start poison self-tests) and fails the build on any gate.
