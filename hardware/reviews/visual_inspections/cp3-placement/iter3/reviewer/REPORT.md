# CP3 placement reviewer evidence - iteration 3

Reviewed commit: `b4ada24`

## Gate results

- Installed skills synchronized to KiCad 0.3.1, PCB Design 0.10.0,
  and PCB Design Review 1.4.0.
- `doc_consistency_check.py`: exit 0. A live poison changing the
  1757242 hash to `000000000000` was rejected with exit 1; restoring
  the file returned exit 0.
- Exact bare Windows PCB rebuild before upstream regeneration: exit 1,
  12 MOD1 drill-floor findings from the stale ignored netlist.
- Fresh-clone simulation with the ignored netlist absent: exit 1,
  `FileNotFoundError`.
- Upstream schematic regeneration followed by the same bare PCB build:
  exit 0; 127 footprints, 125 nets.
- Exact `handoff_check.py`: exit 1. See `handoff_check_transcript.txt`.
- Direct KiCad 10.0.5 DRC of the committed board: completed with rc 5,
  10 expected silk-edge entries, one expected MOD1 library mismatch,
  and 316 placement-stage unconnected items. No new category.

The packet records hashes `40cfc2791487...` and `af64f93e2e2f...`.
After the gate's fresh rebuild, the local netlist and committed board
hashes were respectively `dabe7849c7e1...` and `5a44e30a6140...`.

## Placement and object checks

- Independent top/bottom KiCad renders plus eight reviewer crops:
  all parts remain on top; bottom is bare; polarity/pin-1 marks and
  reference labels remain readable.
- Independent text-box audit: 123 visible references, zero flagged
  pairs. The prior L10/R23 and L12/R33 defects are resolved.
- Independent isolation calculation reproduces 1.9400, 9.6787, and
  2.6999 mm. Packet section 3 and D38 are synchronized.
- Changed-island HF decouplers measure 0.775 to 1.383 mm pad-edge to
  the corresponding U10/U11 supply pin.
- MOD1 board/library comparison: 62/62 pad signatures identical,
  12 thermal vias at 0.3 mm.
- J1: 5.08 mm pitch and two 1.4 mm drills.
- U10/U11 probe: logic pin 2 is north of isolated pin 19 on both parts.

## Source-document checks

1. `1757242.pdf`, Phoenix Contact, page 3: exact order 1757242 header;
   5.08 mm pitch, 1 x 1 mm pins, and 1.4 mm PCB holes. The changed
   manifest row has one matching `7a342188f10c` hash and correct object.
2. `ADM2582E_2587E.pdf`, Rev H, page 8 Table 10 and page 22: pins 1-10
   are logic-side, pins 11-20 are isolated/bus-side, and RW-20 is a
   20-lead wide SOIC. The written orientations agree.
3. `ESP32-S3-WROOM-1-N16R8.pdf`, v1.8, page 45 Figure 11-1: WROOM-1
   pattern has 1.27 mm perimeter pitch and the thermal-pad via array.
4. `R-78HB12-0.5.pdf`, page I-4: recommends C1 = 3.3 uF/100 V when
   Vin > 50 V, but states no maximum capacitor-to-module distance.

No distributor SKU cell changed in this iteration, so the binding
full-SKU `/resolve` sweep was not triggered.
