# CP2 iteration 2 - agent-reviewer evidence

## Preconditions and mechanical gates

- The documented Windows rebuild command failed because `build.py` does not
  search the installed per-user KiCad root. With `KICAD_SHARE` pointed at that
  root, the build then failed in `kiutils.SymbolLib.from_file()` under the
  Windows default encoding. With both `KICAD_SHARE` and `PYTHONUTF8=1`, the
  final clean rebuild passed all eight sheet readability gates, the
  intent-vs-KiCad netlist gate, and root ERC with zero dangling/unconnected
  pins and zero power-pin-not-driven findings.
- `doc_consistency_check.py` and `check_requirements.py` both fail under the
  Windows default encoding. With `PYTHONUTF8=1`, the consistency checker
  reports clean and the requirements runner returns 29/29 PASS.
- `label_body_audit.py` reports zero geometry findings on all eight child
  sheets. Its same-net-label and free-crossing advisories were checked against
  the reviewer renders.
- An independent exported-netlist scan covered 98 R/C/L/D/Q/TVS/F references
  and found zero same-net pin pairs.

## Iteration-1 response re-verification

- F01/J5: the exported netlist reads J5 pins 1..6 as
  `MCU_EN/V3V3/DBG_TXD/GND/DBG_RXD/BOOT`. The on-file ESP-Prog schematic
  shows `FT_TXD -> R20 -> ESP_RXD0` and
  `FT_RXD -> R21 -> ESP_TXD0`; its Program headers put target `ESP_TXD0` on
  pin 3 and target `ESP_RXD0` on pin 5. The corrected target-perspective map
  is therefore sound. Both changed distributor cells reverse-resolved exactly
  to Wurth `61200621621` through the parts API.
- F02/D11: the designer iter-2 full-page set and changed-region crops exist.
  The final reviewer-owned set contains nine 300-DPI full pages and six
  overlapping zoom crops per page. No visible collision, clipping, ambiguous
  junction, or unreadable pin field was found.
- F03/D2: the netlist keeps D2 wired CANL/CANH/GND but the schematic and BOM
  mark it DNP. The on-file onsemi electrical table gives 24 V working
  voltage, 26.2..32 V breakdown, and 40/44 V maximum clamp at 5/8 A; the
  on-file TCAN332 absolute-maximum table gives +/-14 V on its bus pins. The
  no-coordination/DNP conclusion is correct.
- F04/rebuild portability: not resolved on this Windows installation; see
  the packet finding for the two independent failure modes.

## G8 wiring read-back

- Q5/Q10/Q11/Q_exp each read source pin 2 on `V3V3`, gate pin 1 on its
  distinct active-low control net, and drain pin 3 on its distinct gated
  load rail.
- J6 reads CANL=4/CANH=5; J10/J11 read A=7/B=8; J2 reads A=4/B=5 with
  12 V on 1..3 and GND on 6..8.
- J5 reads EN=1, VDD=2, target TXD=3, GND=4, target RXD=5, IO0=6.
- D2 reads its two cathodes on the distinct CANL/CANH nets and its anode on
  GND; its DNP state is visible in the final PDF.
- An in-memory false Q5 golden produced exactly one `[golden]` failure. An
  in-memory false R9 assertion produced 28 PASS/1 FAIL. The committed files
  were not modified, and a final clean build followed.

## Source and object checks

- Citation checks: ESP-Prog schematic page 1 (Program-header map and UART
  crossover), onsemi NUP2105L page 2 (electrical table), TCAN332 page 5
  (bus absolute maximum), TDK MPZ2012 pages 1-2 (S601A table and impedance
  curve), and Wurth 61200621621 page 1 (exact order code, six-pin numeric
  properties).
- Changed/new manifest objects were opened at their title/order pages:
  onsemi NUP2105L with the exact NUP2105LT1G ordering row, Espressif
  ESP32-PROG-BRD_V2 schematic, TDK MPZ2012 family with the exact S601A row,
  KEMET C1009 high-voltage C0G family with its ordering matrix, and Wurth
  exact order code 61200621621. Manufacturer and object level match the
  manifest rows.
- The Wurth page-1 illustration is generic-looking and visually shows more
  columns than its numeric six-pin property. The exact DigiKey and Mouser
  SKU resolutions, DigiKey's six-position/two-row parametrics, and the
  drawing's numeric properties all agree on six positions. CP3 should use
  the numeric hole-pattern dimensions, not count the illustrative pins.

## G9 and bring-up walk

1. Designer layer: all generator readability/glyph/title-block gates pass.
2. Independent layer: `label_body_audit.py` reports zero geometry findings
   on all eight child sheets.
3. Eyes layer: the nine final 300-DPI pages and 54 fixed-box zoom crops were
   inspected. The J5 and D2 changed regions are readable and collision-free.

The bring-up guide now uses J5.6-to-J5.4 for manual download mode and
J5.3/J5.5 for UART, matching the netlist. The requirements register still
names J5.3/J5.4 for R9, and its checker does not verify either J5 pin; this is
reported in the packet.

