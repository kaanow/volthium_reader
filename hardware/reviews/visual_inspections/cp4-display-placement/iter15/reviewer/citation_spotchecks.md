# Citation spot-checks - iteration 15

Extracted directly from the on-file manufacturer PDFs with PyMuPDF during this review turn.

1. `USB4115_drawing.pdf`, page 1, SHA256 `8e3448f72b96e77b0952160bfa76d54c034a7c7ce783411cfc70492e8d1b90dc`: title block says `USB3.2 Gen2 Type C Receptacle, Vertical, SMT, H=9.30mm`; ordering grid identifies USB4115.
2. `TS02_tactile.pdf`, pages 1-2, SHA256 `fe5026f60ec364c89a2fe4e09833742055a35c12a10b00215723f9171d6913f8`: key says `150 = 15.0 mm`, `160 = 160 gf`, and `SCR = Short Crimped`; only starred heights require LCR, and 150 is not starred. Page 1 gives 12 Vdc, 50 mA, -30 to 80 C, and 80,000 cycles for 160 gf.
3. `Wurth_61200621621.pdf`, page 1, SHA256 `6474a7ec48fc7046b5628f232646e82035021567fee8b6b8f7af2f02879af7a2`: title identifies order code 61200621621 and `WR-BHD Male Box Header`; drawing gives 6 pins, 2.54 mm pitch, and 9.1 +/-0.15 mm height.
4. `615008145521.pdf`, page 1, SHA256 `da03e4ed62572d59ba76a685b70fbcf613dd5a1fa37405537724dd34dd253c6e`: title identifies order code 615008145521 and `Horizontal Shielded with EMI Panel Finger 8P8C`; drawing gives 13.60 +/-0.25 mm.

Object identity passes for all four title/manufacturer/order-code checks.
