# CP3 iteration 7 reviewer report

Reviewed commit: `1caf827`

## Preconditions

- `doc_consistency_check.py`: exit 0; 34 manifest parts checked, 36
  `_verify_` rows, and no live stale-token or manifest inconsistency.
- Python compilation: the changed PCB core/build/refine files, schematic
  core, and handoff checker compile cleanly.
- Mandatory Windows `handoff_check.py`: exit 1 because all three child
  rebuilds return 1. See `windows_einval_reproduction.txt`.

## Delta re-verification

- F08 writer sweep: the reviewer-authored LF helper remains correctly placed;
  kiutils outputs are normalized after serialization; Git set-comparison keys
  use `.as_posix()`; both tracked `refdes_bans.json` writers now specify
  `newline="\n"`. No other tracked/deterministic bare writer was found.
- F08 remains open for a different Windows-host failure. Repeated unmodified
  display builds hit transient `OSError: [Errno 22] Invalid argument` both in
  ordinary Python file opens and in a KiCad netlist export. The exact direct
  export succeeds. A bounded fail-closed wrapper recovered from one instance
  at each boundary and completed the full display pipeline.
- F09 is resolved. Repository call-site enumeration leaves the geometric
  gates inside `BoardBuilder.write()` and removes the battery entry point's
  duplicate calls. An independent old-J3 poison reports 4.93 mm off-edge; a
  raw `write()` call invokes courtyard, outline, edge-marker, fab, and
  readback without explicit gate calls. The exact battery build exits 0 with
  the expected 12/1/316 DRC classes.

## Visual evidence

Fresh reviewer-owned KiCad renders are `full_top_3d.png` and
`full_bottom_3d.png`; eight dense top-side crops are
`crop_region_00.png` through `crop_region_07.png`, with
`crop_contact_sheet.png` for quick review. The unchanged board remains
visually clean: labels are distinct, polarity/pin-1 marks are visible,
connector overhangs remain coherent, and the bottom remains component-free.

## Citation checks

Four on-file PDF claims were independently opened this pass:

1. `USB4085_drawing.pdf`, sha256 `39afb82c5104...`, sheet 2/3: the
   plug/receptacle mating view contains the 2.10 mm face-to-overmold
   dimension used in packet section 4.6.
2. `R-78HB12-0.5.pdf`, sha256 `457ccbb2825f...`, page I-4: the protection
   circuit states 3.3 uF / 100 V when Vin is above 50 V; it gives no
   placement-distance requirement.
3. `LM5166YDRCR.pdf`, sha256 `1817a5b4f779...`, section 6.5: the fixed
   variants are independently tabulated as LM5166X = 5.0 V and LM5166Y =
   3.3 V.
4. `THVD1400DR.pdf`, sha256 `5ba9785d9fb8...`, Table 4-1: the pin-functions
   table identifies receiver-enable pin 2 with a 2 Mohm internal pull-up and
   driver-enable pin 3 with a 2 Mohm internal pull-down.

No manifest row or distributor-SKU cell changed in the iteration-6 delta, so
no object-identity or `/resolve` sweep was triggered.

## Coverage

Applied CP3 G4/G6/mechanical re-verification, G5 consistency, changed-tooling
portability, G8 artifact/readback behavior, and G9's three layers (designer
gate, independent old-position poison/call-path model, and fresh crop-zoom
visual read). Electrical topology and board bytes are unchanged; routing
remains outside CP3 scope.

Verdict: NEEDS CHANGES. F09 is closed, but the mandatory handoff
precondition is red on the reviewer's supported Windows host.
