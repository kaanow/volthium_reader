# Display CP2 reviewer evidence - iteration 5

## Preconditions

- `doc_consistency_check.py`: PASS, 33 manifest parts, 36 verified BOM
  cells, no stale-token or D32 consistency findings.
- Bare Windows battery rebuild: PASS; KiCad 10.0.5 auto-discovered with
  KiCad removed from PATH and all KiCad/Python overrides unset. Strict ERC
  found the same two accepted battery warnings and zero unaccounted messages.
- Bare Windows display rebuild: PASS; four readability gates, netlist intent,
  golden contracts, exact-part contracts, and strict ERC all clean. Strict
  ERC returned zero messages with an empty accepted registry.
- Requirements runner: PASS, 42 checks and zero failures.

## G8 - exported-netlist read-back

`g8_netlist_audit.py` independently parsed the freshly exported display
netlist. It found 56 nets, passed all 110 golden contracts, found no exact-part
or discrete-short violations, and printed the complete pin-to-net maps for
the power input, power mux, USB, RS-485, display, buttons, ESP-Prog, and MCU
blocks. A deliberately false J1 net contract produced exactly one failure.
A deliberately wrong horizontal sibling footprint for J2 also produced
exactly one failure.

The exported wiring agrees with the documented design intent: J1 carries
12 V on pins 1-3, A/B on 4/5, ground on 6-8, and leaves the shield isolated;
F1/TVS1/U1 feed the 3.3 V regulator and mux; USB CC, D+/D-, ESD, LDO, and mux
priority wiring are correct; THVD1400 control and bus pins are correct; the
display connector has the canonical 8-pin order; R3/R4 are DNP; BTN1-3 use
the intended 1 Mohm/100 nF networks; and J3 uses the keyed ESP-Prog map.

## Source and object checks

Seven on-file source hashes match the manifest. The Wurth 615008145521
datasheet and the committed manufacturer footprint agree on the non-monotone
pad order `2,1,3,5,4,6,8,7`, hole diameters, and pad coordinates. Citation
checks covered ESP32 RTC-capable pins, THVD1400 pins and bus limits, R-78E
input/output/capacitance limits, SMAJ clamp values, and MF-R025 lead geometry.

All eleven changed DigiKey/Mouser cells independently resolve as `exact` to
the expected manufacturer part numbers; the raw request and response are
preserved beside this report.

The on-file USB4085 PDF is a family specification and does not identify the
`GF-A` ordering suffix. The same-turn official GCT drawing proves `GF` is
Gold Flash, `A` is Tape and Reel, and the connector is through-hole. The
installed KiCad footprint has 20 through-hole pads and no SMD pads.

## G9 - independent geometry

All three layers were exercised:

1. The generator's four display readability gates passed.
2. `label_body_audit.py`, an independent label/body box model, found zero
   geometry defects on the four child sheets.
3. Reviewer eyes inspected all five fresh 300-DPI pages and 30 deterministic
   zoom crops.

The generic G9 tool requires both a battery and display PDF argument. For
this display-only pass, `display_five_sheet_snapshot.pdf` was supplied to
both slots. Consequently, the nested `battery_*` files are byte-equivalent
aliases of the corresponding `display_*` files and were not treated as
battery-review evidence. The separate bare battery rebuild transcript is the
battery regression evidence for this turn.

The sheets are readable except that four `PWR_FLAG` value strings on the
power sheet are obscured by net-label boxes. The clearest evidence is
`eye_p2_grid_06.png`; the complete page is under
`g9/display/iter1/reviewer/display_p2_full_300dpi.png`.

## Bring-up guide walk

Stage 6 does not explicitly require fitting the display-end J5 termination,
although R18 says that jumper is fitted by default at the display terminus.
The recovery appendix documents only battery J5 and does not provide a
display J3/USB recovery procedure despite R21 adding the display header for
that purpose.

## Result

NEEDS CHANGES: three important findings and one nit. See F12-F15 in the
review packet.
