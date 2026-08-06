# CP4 iteration 1 - independent reviewer evidence

Reviewed commit: `ff1da386ca286dddfc0d3c0a0ade1b95e31111b9`

## Preconditions

- `doc_consistency_check.py`: exit 0, 36 manifest parts checked.
- Display PCB rebuild: exit 1 with
  `[orient] J1: signal pads not west of body - RJ45 opening does not face the W edge`.
- Full `handoff_check.py`: battery/display schematic builds and battery PCB build
  exit 0; display PCB build exits 1 on the same J1 finding; overall FAIL.
- Packet blob hashes independently reproduced: display board
  `1bf74eea4fc005c51ad257fdb2604515b9a4263b8d4b617acaa7115b7c81dcad`;
  display netlist
  `41145f58b214cd3b07f2c973946949c386e233a1fdf7c10c8b716b7e52c781a8`.

## Independent geometry

`cc()` negates the local courtyard X center for a back-side part, while the
writer and analytic transform correctly negate local Y. Recomputing from the
generator data gives:

| Ref | requested center | actual generated center | delta |
|---|---:|---:|---:|
| J1 | (9.8, 46.5) | (16.15, 28.06) | (+6.35, -18.44) mm |
| U1 | (22.0, 41.0) | (26.97, 45.50) | (+4.97, +4.50) mm |

J1 remains at 0 degrees, with its signal-row centroid at `(16.15, 36.01)`
and its two locating posts at `(10.435, 28.39)` and `(21.865, 28.39)`. That
is a north/south connector axis, not a west-facing axis. A scratch geometry
probe using the corrected center transform and a 90-degree J1 rotation puts
the locating posts west of the signal row, but then correctly reports three
layout conflicts: BTN1 through-pads into J1, J1 through-pads into R5, and
J1 courtyard into U1. This needs a real re-placement, not an assertion bypass.

The new circular-courtyard path was independently poisoned: an M3 mounting
hole produces 24 segments, collides with a resistor at the same center, and
does not collide at a clean offset.

KiCad's fresh placement export is `positions.csv`. Fresh DRC is
`independent_drc.rpt`: two accounted `lib_footprint_mismatch` warnings
(J-USB and MOD1) plus 123 expected unrouted items, and no additional geometry
violations. In particular, J1/U1 do not report library mismatch, corroborating
that the writer's mirror-Y transform is correct; the stale center helper and
J1 rotation are the defects.

## SKU resolution

Live `/resolve` checks on 2026-08-06:

| BOM cell | resolved object | verdict |
|---|---|---|
| DK `2073-USB4115-03-CTR-ND` | `USB4115-03-C` | correct |
| Mouser `640-USB4085-GF-A` | `USB4085-GF-A` | wrong retired edge part |
| DK `179-TS0266150BK160SC` | `TS02-66-150-BK-160-SCR-D` | packaging-variant match |
| DK `455-1710-ND` | `B8B-PH-K-S` | wrong rejected top-entry part |

Focused live lookups return `455-1725-ND` for active/in-stock
`S8B-PH-K-S` and `640-USB4115-03-C` for in-stock `USB4115-03-C`.

## Source-document spot checks

- Wurth `615008145521.pdf` p.1 identifies exact order code 615008145521,
  horizontal/tab-down construction, 13.60 mm body height, and the non-monotone
  recommended hole pattern used by the vendored footprint.
- GCT `USB4115_drawing.pdf` pp.1-2 identifies exact `USB4115-03-C`, vertical
  SMT construction, 9.30 mm height, and the 24-contact plus shell land pattern.
- Same Sky `TS02_tactile.pdf` pp.1-2 decodes the exact 15.0 mm/160 gf/SCR
  variant and specifies a 6.5 x 4.5 mm pattern with four 1.0 mm drills.
  The stock KiCad footprint uses 1.1 mm drills and a 13 mm 3D model, so the
  packet's "exact match" statement is false even though the larger drill is
  plausibly acceptable (0.45 mm annular ring; 0.8 mm maximum terminal width).
- JST `B8B-PH-K-S.pdf` pp.1,3 confirms 8.0 mm top-entry mounting height and
  the 7.6 mm side-entry `S8B-PH-K-S` construction.

Rendered source pages are under `datasheets/`.

## Visual inspection

Fresh reviewer-owned top/bottom 3D renders, eight quadrant crops, fitted
front/back geometry SVG/PNG plots, placement CSV, and DRC report are in this
directory. The committed designer renders and fresh Windows renders agree:
J1 and J-USB have no visible 3D bodies. J1 references an unresolved
`${WE_3DMODEL_DIR}` model; the USB footprint references a STEP absent from the
installed KiCad 10 model set. BTN1-3 render the stock H13 body, not the selected
15 mm actuator. Therefore the current visual set cannot verify the three
load-bearing mechanical envelopes.
