# Citation and object spot-checks

Opened and read the rendered on-file PDFs during reviewer iteration 7.

1. `THVD1400DR.pdf`, page 4, TI document SLLSE78B: section 5.1 gives
   A/B absolute maximum as -16 V to +16 V. The full SHA-256 starts
   `5ba9785d9fb8`, matching `hardware/datasheets/manifest.md`.
2. `THVD1400DR.pdf`, page 5: section 5.4 gives the recommended input
   voltage at any bus terminal as -7 V to +12 V. This confirms that the
   operating range and absolute maximum are distinct claims.
3. `USB4085_drawing.pdf`, page 1, GCT drawing revision B: the title block
   identifies USB4085 as "Dip Type, PCB Top Mount"; the ordering grid
   decodes `GF` as Gold Flash (Standard) and `A` as Tape & Reel.
4. `USB4085_drawing.pdf`, page 2: the recommended component-side PCB
   layout calls out 16 contact holes at 0.65 mm. The installed KiCad
   `USB_C_Receptacle_GCT_USB4085` footprint independently contains
   20 through-hole pads and zero SMD pads. The drawing's full SHA-256
   starts `39afb82c5104`, matching the exact-object manifest row.

No distributor SKU cell or manifest row changed in the F16 geometry/gate
delta, so no new `/resolve` sweep or changed-row identity audit was
applicable.
