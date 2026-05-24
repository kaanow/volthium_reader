"""CP2 schematic generation script — placeholder.

This file will be populated in successive CP2 iterations after the
approach in `hardware/reviews/cp2_schematic_capture.md` is approved.

Plan:
  - iter 2: power-input section, battery-side
  - iter 3: MCU + RS-485, battery-side
  - iter 4: remaining battery-side + display-side
  - end of CP2: both .kicad_sch files complete, ERC clean,
    PDF + netlist exported into ../outputs/<board>/.

Run:
    .venv/bin/python hardware/kicad/build_schematics.py

Uses kiutils to author .kicad_sch files in KiCad 7 format, then
kicad-cli sch upgrade to bring them to KiCad 10. ERC + PDF +
netlist exports are run by the same script via subprocess calls
to kicad-cli.
"""

# Placeholder — real implementation lands in CP2 iter 2.
if __name__ == "__main__":
    print("CP2 schematic generation — not yet implemented.")
    print("See hardware/reviews/cp2_schematic_capture.md for the plan.")
