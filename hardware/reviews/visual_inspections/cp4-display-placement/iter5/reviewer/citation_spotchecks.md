# Citation spot-checks

Checked directly against the on-file manufacturer PDFs on 2026-08-06.

1. `USB4115_drawing.pdf`, SHA256 prefix `8e3448f72b96`, p.1: the GCT title
   block says USB4115 is a vertical SMT USB Type-C receptacle with H=9.30 mm.
   This supports the D13 depth-stack row.
2. `TS02_tactile.pdf`, SHA256 prefix `fe5026f60ec3`, p.1: the part key defines
   `150` as 15.0 mm actuator height and `SCR` as short-crimped terminals. Page
   2 was rendered and inspected because its drawing dimensions are vector
   geometry rather than extractable text; it shows the SCR recommended layout
   as 6.5 x 4.5 mm with four 1.0 mm holes and a 0.7 +/-0.1 mm terminal.
3. `615008145521.pdf`, SHA256 prefix `da03e4ed6257`, p.1: the Wurth drawing
   identifies order code 615008145521 as horizontal, shielded, tab-down 8P8C
   and dimensions its height at 13.60 +/-0.25 mm.

All three cited objects and values match the packet. No manifest row or SKU
cell changed in the iteration-4 response, so no new object-identity or
distributor-SKU sweep was triggered.
