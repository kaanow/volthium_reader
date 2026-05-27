# CP4 review packet — display-side PCB placement

**Status**: ready for review (iteration 1 — approach)
**Opened**: 2026-05-26
**Branch**: `hw/cp4-display-placement`
**Goal of this CP**: produce `hardware/kicad/display_side/display_side.kicad_pcb`
with every display-side footprint placed (no routing yet), DRC clean
for "placement only" (track-not-routed warnings expected and suppressed
the same way as CP3), top + bottom PNG renders for visual review, and
a placement strategy that respects [`cp1_display_side.md`
§10](../layout/cp1_display_side.md#10-layout-strategy). Single-board
scope by design — battery-side is CP3-closed and unchanged here. See
[`decisions.md` D12](../layout/decisions.md#d12--cp-renumber-display-side-placement-inserted-as-cp4)
for why this is its own CP.

## 1. What CP3 + CP-schematic-cleanup handed us

- **Battery-side**: closed at CP3 iter 21 APPROVED.
  `hardware/kicad/battery_side/battery_side.kicad_pcb` has all
  footprints placed, DRC clean for placement, top + bottom renders
  committed. Out of scope for CP4.
- **Display-side schematic**: closed at CP2 + CP-schematic-cleanup
  iter 60 APPROVED. `hardware/kicad/display_side/display_side.kicad_sch`
  is ERC clean, PDF + netlist exported, D11-readable.
- **Display-side PCB**: does not exist yet.
  `hardware/kicad/display_side/` contains `.kicad_pro`, `.kicad_sch`,
  `.kicad_prl`, `sym-lib-table`, and the ERC report — no
  `.kicad_pcb`. Creating this file is the entire substance of CP4.
- **Footprint cache**: `hardware/kicad/libraries/volthium.pretty/`
  already contains every footprint referenced by display-side parts
  (the cache was populated during CP3 for both boards' shared
  symbol→footprint mappings, including the antenna respin
  `ESP32-S3-WROOM-1U` and the Hirose FH12-24S FFC).
- **`build_pcbs.py`**: has `build_battery_side()` and the supporting
  infrastructure (`_add_edge_cuts`, `_place_footprint`,
  `_add_mounting_holes`, `_write_fp_lib_table`, `resolve_footprint`,
  netlist parser). The CLI advertises `--all` as "smoke + battery +
  display" but `build_display_side()` is not yet implemented.

## 2. The approach for CP4

**Source of truth**: `hardware/kicad/display_side/display_side.kicad_pcb`,
generated programmatically from `display_side.net` via `build_pcbs.py`.
Per [`decisions.md` D1](../layout/decisions.md#d1) and the CP3 pattern.

**Generation method**: extend `build_pcbs.py` with a new
`build_display_side()` function that mirrors `build_battery_side()`,
using the same primitives:

1. **Board outline** on `Edge.Cuts`: 85 × 65 mm (per
   [`cp1_display_side.md`](../layout/cp1_display_side.md) §2 and the
   D8 double-gang form factor).
2. **Net definitions** populated from `hardware/outputs/display_side/display_side.net`
   (every net from the CP2 netlist ends up in the PCB `(net N "name")`
   table).
3. **Footprint instances**: for every component on the display-side
   schematic, resolve the libId from `volthium.pretty/`, instantiate
   it, set position/orientation/layer, tie pads to nets. Anchor
   coordinates live in a new `DISPLAY_PLACEMENT` dict in
   `build_pcbs.py`, structured identically to `BATTERY_PLACEMENT`.
4. **Net classes**: per
   [`cp1_display_side.md` §10.3](../layout/cp1_display_side.md#103-net-classes):
   Power-12V (0.5 mm / 0.25 mm), Power-3V3 (0.4 mm / 0.2 mm),
   Default-sig (0.2 mm / 0.2 mm), RS485-diff (0.25 mm / 0.2 mm).
5. **Mounting holes**: 4 corners, 3 mm margin, matching battery-side
   convention. Hole diameter = M2.5 clearance (2.7 mm) for standoffs.
6. **DRC** via `kicad-cli pcb drc --schematic-parity`. Expected
   violations: unrouted tracks (CP5's job). Suppress those for CP4;
   everything else should be clean.
7. **Render** via `kicad-cli pcb render --side top` and `--side
   bottom` → PNGs into `hardware/outputs/display_side/`.

No change to battery-side. No routing. No copper pours. Those are
explicitly CP5.

## 3. What carries over from CP3 — and what doesn't

**Carries over (no rework):**
- Footprint resolution from `volthium.pretty/` only; no host KiCad
  dependency at build time. `--rebuild-footprints` opt-in only.
- `fp-lib-table` written to `display_side/` pointing at the same
  shared `libraries/volthium.pretty/` (relative `${KIPRJMOD}/../libraries/...`).
- `_place_footprint`, `_add_edge_cuts`, `_add_mounting_holes`,
  `parse_netlist` reused verbatim.
- D11 visual inspection protocol: PNG renders + 100% zoom region
  screenshots, committed under
  `hardware/reviews/visual_inspections/cp4-display-placement/iterN/`.
- CP3's `--smoke` smoke-test PCB unchanged.
- The ESP32-S3-WROOM-1U variant + U.FL antenna decision from CP3
  iter 20. Display-side carries the same module and uses an external
  antenna with U.FL pigtail — keepout-free placement.

**Does not carry over (display-side specific):**
- Placement geometry: display-side is 85 × 65 mm vs battery-side's
  60 × 40 mm.
- Component set: J2 FFC (Hirose FH12-24S), 3 tactile buttons (BTN1/2/3),
  U1 (R-78E3.3) — only on this board.
- Layer assignment: U1 (R-78E3.3 SIP3, ~9 mm tall) lives on **B.Cu**
  per cp1_display_side.md §10.2 — first board to use B.Cu for an
  active component.
- Faceplate mechanical reference: button column at X = 24, 42, 60 mm
  is derived from the faceplate mounting-hole offset, not arbitrary.

## 4. Display-side placement strategy (per cp1_display_side.md §10)

Working draft — coordinates will be finalized in iter-2 against the
actual footprint bounding boxes. The constraints are:

### 4.1 Hard constraints (must-meet)

- **J2 FFC (Hirose FH12-24S, 24-pin 0.5 mm pitch, horizontal)** on the
  **top edge** (Y = 65 mm side of the board), centered laterally, ribbon
  exits toward +Y (toward the e-paper panel above). Anchor pads on
  F.Cu. The FFC ribbon makes a single 90° bend from panel back to PCB
  front — this is the lowest-stress geometry for the panel ribbon.
- **BTN1/BTN2/BTN3** on the **bottom edge** (Y ≈ 5 mm from board
  bottom), at X = 24, 42, 60 mm — the 18 mm spacing matched to
  faceplate mounting-hole offsets per cp1_display_side.md §10.2.
  Tactile switches mount F.Cu (caps push down through faceplate
  holes).
- **ESP32-S3-WROOM-1U module** with antenna direction pointing toward
  the **box back wall** (away from the e-paper panel). U.FL pigtail
  exits the module's antenna pad toward the back of the enclosure.
  This avoids the foil-backed e-paper detuning the antenna and the
  CP3 keepout-zone problem (already resolved at the module level by
  the -1U variant).
- **U1 (R-78E3.3, SIP3)** on the **B.Cu** layer — taller than 5 mm,
  must mount on the back of the PCB so the SIP body points into the
  open double-gang box, not into the e-paper panel.
- **J3 RJ45 + RS-485 transceiver U2** on the **left short edge**
  (X = 0 mm), accessible from the back of the box where the in-wall
  Cat5e cable arrives. Preference for left edge is so the cable
  doesn't push the box too far forward (mechanical clearance with
  the in-wall enclosure).

### 4.2 Soft preferences (optimize within constraints)

- Decoupling caps within 3 mm of their driven IC pin (D11-readable
  proximity).
- Power-rail components (U1 R-78E3.3 input, V12_CAT5E entry, TVS
  protection) clustered near the J3 entry, so V12_PROT → U1 → V3V3
  forms a short path along the left edge.
- Pull-ups and timing components (R for ESP32_EN, RTC crystal if
  present on this board) within 5 mm of the ESP32 module.
- FFC differential pairs (EPD SPI MOSI/MISO/SCK/CS) routed in tight
  bundles from MOD1 toward J2 — placement should keep those
  destinations within a single quadrant of the board.

### 4.3 Layer-stackup confirmation

Per cp1_display_side.md §10.1: 2-layer FR-4, F.Cu for signals,
B.Cu for ground pour (matches battery-side convention). No change.

## 5. D11 visual inspection plan

After iter-2 generates the PCB and renders, D11 inspection runs at
100 % zoom in a real PDF viewer (Preview / Acrobat, not KiCad GUI,
not PNG previews). Dense regions identified per the D11 §0 protocol
in DESIGNER.md:

- MOD1 (ESP32-S3 module): pads + nearby decoupling
- J2 FFC: all 24 pins legible
- J3 + U2 + V12_PROT cluster (left edge)
- Each BTN with its pullup
- U1 + L1 + C_BST cluster (B.Cu, viewed from bottom render)
- Mounting-hole vs nearest-track clearance, 4 corners

Snapshots saved under
`hardware/reviews/visual_inspections/cp4-display-placement/iter<N>/`
with the source PDFs frozen alongside under `snapshots/` per the
DESIGNER §0 protocol.

D11 criteria #0 (visual inspection passed) and #5 (every text element
readable at 100 % zoom) are the absolute gates. The packet's iter-N
sign-off may not claim PASS without the screenshots committed.

## 6. Verification commands (planned for iter-2)

```bash
# Generate the PCB
.venv/bin/python hardware/kicad/build_pcbs.py --display

# DRC (placement-mode, route violations suppressed)
kicad-cli pcb drc --schematic-parity \
  hardware/kicad/display_side/display_side.kicad_pcb \
  -o hardware/kicad/display_side/display_side-drc.rpt

# Render top + bottom
kicad-cli pcb render --side top  --output hardware/outputs/display_side/top.png  hardware/kicad/display_side/display_side.kicad_pcb
kicad-cli pcb render --side bottom --output hardware/outputs/display_side/bottom.png hardware/kicad/display_side/display_side.kicad_pcb

# Per-region 100 % zoom screenshots for D11 — manual, see DESIGNER §0
```

Acceptance: DRC report shows 0 errors, 0 unconnected items (since the
net topology comes from the ERC-clean schematic, this should hold),
and only unrouted-track warnings (counted, not zero).

## 7. Open items / known risks

- **R-78E3.3 (U1) on B.Cu**: first board where a tall active
  component lives on the back. Need to verify (a) the SIP3 footprint
  in `volthium.pretty/` has correct B.Cu-mountable geometry (pad
  layer assignments work bottom-side via `_place_footprint`'s layer
  arg), and (b) the 4-corner standoff height is enough to clear the
  9 mm component height plus solder.
- **FFC J2 mechanical**: 24-pin 0.5 mm pitch is small. Confirm the
  Hirose FH12-24S `.kicad_mod` in `volthium.pretty/` has horizontal
  contact orientation (latch on +Y side, contacts facing -Y so the
  ribbon enters from +Y).
- **Antenna pigtail routing**: U.FL connector orientation on the
  module affects pigtail bend radius. Place the module so the U.FL
  pad faces the back-of-box edge; verify that the closest board edge
  is ≥ 8 mm to allow the pigtail bend.
- **Differential pair length matching for EPD SPI**: e-paper panels
  generally don't need strict matching at typical EPD clock rates
  (MHz range), but if Codex flags it, can add length-matching as a
  CP5 routing constraint, not a placement constraint.

## 8. Reviewer findings (iteration 1)

_Reserved for Codex iter-1 review._

---

**Acceptance gate for CP4 close**:
- `display_side.kicad_pcb` exists and is byte-identical to a fresh
  `build_pcbs.py --display` build (modulo KiCad-regenerated UUIDs).
- DRC: 0 errors, 0 unconnected items, only unrouted-track warnings.
- Top + bottom PNG renders committed.
- D11 visual inspection complete: all dense regions PASS at 100 %
  zoom, screenshots committed under
  `visual_inspections/cp4-display-placement/iterN/`.
- No regression on battery-side: `battery_side.kicad_pcb` byte-
  identical to current main (excluding UUID/timestamp metadata),
  no changes to `battery_side/` directory.
