# Iteration 7 citation spot-checks

Checked directly against the committed PDFs with PyMuPDF text extraction.

1. `hardware/datasheets/USB4115_drawing.pdf`, page 1: the title block says
   `Vertical` and `H=9.30mm`. This supports the packet's J-USB orientation and
   depth-driver claim.
2. `hardware/datasheets/TS02_tactile.pdf`, page 1: the ordering key contains
   `150` = `15.0` mm and `SCR` = `SHORT CRIMPED`. This supports the packet's
   button-height and selected-terminal claims.
3. `hardware/datasheets/Wurth_61200621621.pdf`, page 1: the article number is
   `61200621621`, the drawing gives `9.1 +/-0.15` mm, and the pitch is
   `2.54 +/-0.05` mm. This supports the packet's J3 envelope claim.
4. `hardware/datasheets/615008145521.pdf`, page 1: the article number is
   `615008145521`, the body dimension is `13,60 +/-0.25` mm, and the product
   description says `Horizontal Shielded`. This supports the packet's J1
   envelope/orientation claim.

No manifest row or distributor-SKU cell changed in designer iteration 6, so
the object-identity and full changed-SKU sweeps were not re-triggered.
