# CP3 placement reviewer evidence - iteration 1

Reviewed commit: `0ddffbd50a894b6f0bda4aaba52817857ad24ac6`

## Preconditions

- `python3 hardware/reviews/tools/doc_consistency_check.py`: exit 0,
  35 manifest parts checked, 36 BOM `_verify_` cells reported.
- The packet's POSIX venv command does not name the Windows interpreter.
- Bare Windows rebuild with
  `.venv\Scripts\python.exe hardware\kicad\pcb\build.py` failed because
  `hardware/kicad/pcb/fplib.py` selected only the macOS KiCad footprint
  path plus the project library.
- Supplying the installed KiCad share path exposed a second failure:
  Python's cp1252 writer could not encode the ohm symbol.
- Supplying the share path and `PYTHONUTF8=1` reached the fab gate, which
  rejected all 12 MOD1 thermal vias as 0.2 mm drills.

The committed schematic generator names
`volthium:ESP32-S3-WROOM-1_HSvia0.3`, but the committed battery netlist
still names `RF_Module:ESP32-S3-WROOM-1`. The committed board names the
vendored footprint and contains 12 0.3 mm thermal vias.

## Written-artifact checks

SHA-256 values independently calculated from the committed files:

| Artifact | Actual SHA-256 |
|---|---|
| `battery_pcb.kicad_pcb` | `063b574ea908797069c669863f966f8215a567ca63298f23aab5204242096562` |
| `volthium_reader.net` | `2483956a85ae37ed5489a6f3a15b34b5ec8f84e654f78e6573aa3530dd8fc91e` |

Neither value matches the hashes recorded in packet section 1.

An independent written-board/netlist comparison found:

- 123 netlist references and 127 board references (the four extras are
  the expected mounting holes);
- 431 bound `(reference, pad, net)` triples in each artifact;
- zero missing or extra triples;
- one footprint-ID mismatch: MOD1 is stock in the netlist and vendored
  in the board.

Direct KiCad 10.0.5 DRC of the committed board is in
`reviewer_drc.rpt`: 11 violation entries (10 enumerated silk/edge accepts
and the one enumerated MOD1 library mismatch) plus 316 placement-stage
unconnected items. No additional category was found.

## Independent geometry and visual checks

- `full_top.png` and `full_bottom.png`: independent KiCad 3D renders;
  all components are on the top and the bottom is bare.
- `full_top_2d.png`: rasterized independent KiCad plot of
  `F.Cu,F.Silkscreen,Edge.Cuts`.
- Eight reviewer crops cover the board at inspection zoom.
- `geometry_second_opinion.txt` records an alternate text-box model.

The independent model and crop-level eye check agree that `L10`/`R23`
and `L12`/`R33` visually concatenate.

Mechanical checks against the written board:

- closed rectangular Edge.Cuts from `(0,0)` to `(100,80)` mm;
- M3 holes at `(4,4)`, `(96,4)`, `(4,76)`, `(96,76)` mm;
- MOD1 antenna overhang is north-facing while its pads remain on-board;
- J1 west, J3 east, RJ45 connectors south, and J5 inboard.

## Source-document spot checks

All checks used the PDFs already committed under `hardware/datasheets/`.

1. `1757242.pdf`, Phoenix Contact: title identifies order 1757242,
   MSTBA 2,5/2-G-5,08; page 3 gives 5.08 mm pitch, 1.0 mm square pin,
   and 1.4 mm hole. Written J1 has two pads at 5.08 mm and 1.4 mm drills.
2. `ESP32-S3-WROOM-1-N16R8.pdf`, Espressif v1.8: Figure 11-1 specifies
   the WROOM-1 land pattern with 1.27 mm perimeter pitch and thermal-pad
   via array. The vendored footprint preserves the stock geometry while
   changing the 12 via drills from 0.2 to 0.3 mm.
3. `ADM2582E_2587E.pdf`, Analog Devices Rev H: Figure 2/Table 10 and the
   package section specify the 20-lead wide SOIC and logic/isolated pin
   partition. Written U10/U11 use SOIC-20W at 1.27 mm pitch with the
   logic row north and isolated/bus row south.
4. `AQY212EH_Panasonic.pdf`: package drawing specifies DIP-4 with
   2.54 mm lead pitch, 7.62 mm row span, and 0.8 mm holes. Written SSR1
   uses `DIP-4_W7.62mm` with four 0.8 mm drills.

Object-identity audit also found two manifest rows for the same
`1757242.pdf`. The newer row's prefix `7a342188f10c` matches the actual
file; the older row's `7b6cfef0980a` does not.
