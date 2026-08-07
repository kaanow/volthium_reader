# Iteration 9 citation spot-checks

Checked directly against the committed PDFs using PyMuPDF text extraction.

1. `hardware/datasheets/USB4115_drawing.pdf`, page 1: title block contains
   `Vertical` and `H=9.30mm`.
2. `hardware/datasheets/TS02_tactile.pdf`, page 1: ordering key contains
   `150` = `15.0` mm and `SCR` = `SHORT CRIMPED`.
3. `hardware/datasheets/Wurth_61200621621.pdf`, page 1: article number
   `61200621621`, height `9.1 +/-0.15` mm, pitch `2.54 +/-0.05` mm.
4. `hardware/datasheets/615008145521.pdf`, page 1: article number
   `615008145521`, dimension `13,60 +/-0.25` mm, description
   `Horizontal Shielded`.

All four checked claims pass. No manifest row or distributor-SKU cell changed
in designer iteration 8, so the changed-object and full changed-SKU sweeps were
not triggered.
