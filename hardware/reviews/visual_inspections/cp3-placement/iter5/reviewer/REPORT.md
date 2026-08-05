# CP3 iteration 5 reviewer report

Reviewed commit: `035394a`

## Preconditions

- `doc_consistency_check.py`: exit 0; 34 manifest parts and 36 `_verify_`
  rows; no live superseded-token hits.
- Exact bare Windows PCB rebuild: exit 0; 127 footprints and 125 nets.
- Mandatory `handoff_check.py`: exit 1. See
  `handoff_check_transcript.txt`. This is Finding 08.

## Independent board checks

- Direct KiCad 10 DRC produced 12 `silk_edge_clearance`, one
  `lib_footprint_mismatch`, and 316 `unconnected_items` entries. These
  counts and instances match the packet's placement-stage acceptance
  registry; no additional DRC class appeared. See `reviewer_drc.rpt`.
- Independent netlist/board parsing found 123/123 component references
  and 431/431 connected `(reference, pad, net)` triples with no
  missing or extra live binding.
- The J3 PCB-edge marker transforms exactly to x=100.000 mm and its
  F.Fab shell extends 2.510 mm beyond the east edge. The pre-fix
  4.925 mm west poison is rejected at 4.93 mm.
- The four RJ45 F.Fab fronts independently transform to y=80.875 mm,
  0.875 mm proud of the south edge.
- The alternate reference-text model checked 123 visible component
  references and flagged zero pairs. Independent top/bottom renders and
  eight top-side crops show no new legibility, polarity-mark, component
  collision, antenna-overhang, or assembly-side defect.
- The edge-marker method has only one call site, in the battery build,
  despite changed documentation claiming automatic both-board coverage.
  This is Finding 09.

## Source-document checks

Four packet/BOM citations were independently checked against on-file PDFs:

1. `USB4085_drawing.pdf`, sha256 `39afb82c5104...`, pages 1-2:
   GCT USB4085 exact drawing and ordering grid; page 2 contains the
   recommended PCB layout and 2.10 mm mating-view dimension.
2. `1757242.pdf`, sha256 `7a342188f10c...`, page 3:
   Phoenix Contact 1757242; 5.08 mm pitch, 1 x 1 mm pins, and 1.4 mm
   PCB hole.
3. `R-78HB12-0.5.pdf`, sha256 `457ccbb2825f...`, page I-4:
   the external circuit gives 3.3 uF/100 V for Vin above 50 V and does
   not state a placement-distance limit. Packet section 4.4 now
   attributes only the value/rating to the PDF and labels 8 mm as an
   engineering judgment.
4. `ADM2582E_2587E.pdf`, sha256 `77a52a9e6036...`, Rev H Table 1,
   page 3: ADM2587E ICC is 90 mA at 3.3 V with a 100 ohm Y-Z load and
   72 mA at 5 V under the same load.

No manifest row or distributor-SKU cell changed in this delta, so no
object-identity or `/resolve` sweep was triggered. The changed USB placement
was checked against the existing exact-object drawing row.

## Coverage

Applied CP3 G4/G6/mechanical gates, G5 consistency, changed-object G2
checks, G8 netlist/layout parity and exact variants, and G9's three layers
(designer gate, independent geometry model, crop-zoom visual read).
Electrical topology is unchanged from approved CP2; routing quality remains
outside CP3 scope.

Verdict: NEEDS CHANGES. The placement delta itself passes, but the mandatory
handoff precondition is red on Windows and the cross-board gate claim is not
implemented at a shared chokepoint.
