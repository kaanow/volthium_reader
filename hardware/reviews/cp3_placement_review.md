# CP3 review packet — battery-side placement

Branch `hw/cp3-placement` · packet opened 2026-07-30 · designer: Claude
Scope per D12: **battery side only** (display-side placement is CP4).

## 1. Scope and inputs

- Input netlist: the CP2-APPROVED battery schematic's export,
  `hardware/kicad/schematic/build/volthium_reader.net`
  (sha256 `485965cc2398…`), 123 components / 125 nets. One CP3-driven
  schematic-side delta (§4.1: MOD1 footprint variant).
- Output: `hardware/kicad/pcb/build/battery_pcb.kicad_pcb`
  (sha256 `b3d8030a1624…`) — 127 footprints (123 parts + 4 M3 mounting
  holes), all pads net-bound, **placement only** (routing is CP5).
- Generator: `hardware/kicad/pcb/core.py` (shared mechanics + gates) +
  `hardware/kicad/pcb/build.py` (battery floorplan as data). The pass-1
  PCB toolchain was retired to `hardware/kicad/archive/pass1_pcb/`.
- Decisions taken: **D38** (outline 100×80, antenna overhang, USB-E
  60 mm FS-USB run, iso column architecture) — see decisions.md.

## 2. Generator gate stack (all run in the build, rc≠0 on any finding)

| Gate | What it proves | Poisoned? |
|------|----------------|-----------|
| parity | placement keys == netlist refs, both directions (pass-1's silent skip is impossible) | build-start selftest |
| pinmap | every netlist pin has a pad in the footprint | via readback |
| courtyard | pairwise courtyard collision (segment-intersection + containment), mounting holes included | selftest: overlap fires, clean spacing doesn't, rotated overlap fires, containment fires |
| outline | courtyards inside the board except whitelisted overhang edges per connector | gate findings during iteration |
| fab rules | drill ≥0.3, annular ≥0.13 on the WRITTEN board | caught the stock ESP32 0.2 mm heatsink vias (§4.1) |
| readback | (ref, pad, net) triples re-parsed from the written `.kicad_pcb` diffed against the netlist, both directions | caught its own regex bug during bring-up |
| orientation | probed (never hand-derived): RJ45 openings face S; J1 wire entry W; J3 opening E; MOD1 antenna N; **U10/U11 logic row north of iso row** | asserts fire on wrong rotation |
| DRC | `kicad-cli pcb drc --severity-all --exit-code-violations`, transactional report, append-only accepted registry | selftest: stale-report + forced-fail refuses to judge |

DRC final state: **0 unaccounted**. Accepted classes (full rationale in
`build.py::DRC_ACCEPTED`):
- `unconnected_items` ×316 — placement-only board, routing at CP5.
- `silk_edge_clearance` ×10 — enumerated per-instance: 8 = the four
  RJ45 mating-face silk boxes crossing the S edge (designed overhang),
  2 = MOD1 antenna silk crossing the N edge (D38). Nothing else clips.
- `lib_footprint_mismatch` ×1 (instance-scoped accept) — MOD1 board
  copy vs `volthium` lib: 62/62 pads coordinate-diffed identical, all
  graphic counts equal; the delta is kiutils serialization
  normalization only (dropped `(unlocked yes)`, stroke/fill order,
  `embedded_fonts` token). Non-geometric.

## 3. Floorplan (rationale)

South edge = cable edge (wall-box, cables from below): J2 display-link,
J6 Xanbus, J10/J11 pack-reads, each RJ45 with its transceiver directly
north of it. West edge: Phoenix 24 V entry above the display jack, then
F1 → D1/TVS1/C1 → the switched chain (F2 → SSR1 → R_inrush → U2) —
power flows S→N up the west side. Center: U1 buck triangle
(C1/U1/L1/C2 within ~10 mm, §11.2#2) below the module. North: MOD1
(antenna overhanging), RTC cluster, J_EXP + BTN1 harness headers NE.
East edge: USB-C → ESD → LDO → mux, flowing E→W toward the V3V3 rail.
NW: quiet sense divider + UVLO supervisor (§11.2#3 — far from L1).
J5 ESP-Prog flat mid-board (lid-off service access).

Isolated channels (D36/DR-26): vertical columns at x≈59.5/82 — logic
row, ADM2587E **rotated so the package isolation barrier runs
horizontally** (probed + asserted), iso island (supply π-filter under
its own pins, protection/term row), jack. Cross-domain pad separation
measured: logic↔iso1 ≥3.71 mm (J7.2→R22.1), iso1↔iso2 ≥4.73 mm,
logic↔iso2 ≥16.7 mm — vs ~0.6 mm IPC-2221 for <100 V functional
isolation. CP5 note: B.Cu pour must split along y≈47 under U10/U11
(barrier line), islands per channel.

## 4. Findings made and fixed during self-review (selection)

### 4.1 Fab-rule catch: stock ESP32 footprint violates the drill floor
`fplib.py`'s drill scan found the stock `RF_Module:ESP32-S3-WROOM-1`
carries 12 heatsink vias at **0.2 mm drill** — below JLCPCB's 0.3 mm
2-layer floor (cp1 §12). Fix: vendored variant
`volthium:ESP32-S3-WROOM-1_HSvia0.3` (single delta: 0.2→0.3 mm,
annular 0.15 ✓), both boards' schematics updated, CP2 gate stack
re-run green (see footprints README provenance row).

### 4.2 kiutils KiCad-10 repairs (board-writing layer)
1. **Pad/text angles**: KiCad stores TOTAL angles; kiutils leaves local
   angles — every rotated multi-pad footprint rendered with unrotated
   pad bodies (first DRC: L1's own pads 0.15 mm apart). Fixed by
   composing angles at place time.
2. **`(remove_unused_layers no)`** re-emitted as bare
   `(remove_unused_layers)` = YES — semantics inverted on every THT pad
   (masked 14 real clearance findings, 15 lib mismatches). Fixed
   textually at the write chokepoint.
3. **KiCad-10 `(property …)` blocks collapsed to bare strings** — every
   refdes lost its library position/layer/font/hide. Restored from the
   library text at the write chokepoint, with rotation-composed,
   readability-normalized angles.

### 4.3 Visual-pass catches (render, then fixed)
- U10/U11 barrier axis (→ rotation + standing assert, §3).
- C12 was 8 mm from U7's VCC on the wrong package side → moved to the
  VCC column; D2 (DNP clamp) swapped out of the tight pocket.
- On-body refdes deprioritized (invisible after soldering); mounting
  holes' H1–H4 refs hidden (rendered off-board at the corners).

### 4.4 Affinity/PR-8 instrument (review_affinity.py) catches
- C3 (U2 input bulk) was 14 mm from U2.1 → 8 mm (module input, not a
  high-di/dt node; datasheet placement satisfied).
- C7/C6 order swapped so the 100 nF HF cap is CLOSEST to MOD1 pin 2
  (1.5 mm pad-edge), 10 µF bulk behind.
- **U5 and U6 were rotated 180° from the power-flow direction** (VIN
  pins facing away from the incoming VBUS) → flipped; C_usb1/C_usb2
  now sit on their true VIN/VOUT sides.
- Iso supply caps re-ordered under their own pins (V_ISOOUT west /
  V_ISOIN east), beads to a second row.

## 5. PR-8 enumeration (decoupler pad-edge distances)

After fixes, every 0.1 µF/0.01 µF HF decoupler measures **< 3.0 mm**
pad-edge to its IC pin. Four 10 µF bulk caps measure 3.0–4.3 mm
(C23/C33 → VCC banks, C24/C34 → iso supplies, C6 → MOD1), each sitting
deliberately BEHIND its HF partner — moving bulk inside 3 mm would
displace the HF caps and worsen the actual high-frequency loop. C5
(36.6 mm to the ADC pin) is the §11.2#3 quiet-divider filter — the
long filtered-DC run is the design. C11 lives at the button header it
debounces. C_mux/C2/C4/C1/C3 are bulk/reservoir roles at their nodes.

## 6. D11 visual inspection — iter 1

Full-page renders + 8 region crops at
`visual_inspections/cp3-placement/iter1/`:
`nw_divider_uvlo, w_power_entry, buck_control, mod1_rtc, usb_east,
sw_comms_xanbus, iso_ch1, iso_ch2_ne` (+ `build/render_top.png`,
`render_bottom.png`, snapshot of the .kicad_pcb alongside).
Read in full at working zoom. Findings: **none open** — every refdes
legible, every polarity mark visible (SMA cathode bars, SOT-23 pin-1,
SOIC dots, RJ45 pin-1 triangles), bottom side bare (single-sided
assembly confirmed).

## 7. D13 scorecard

| Criterion | Status | Evidence |
|-----------|--------|----------|
| F-P-1 | PASS | DRC 0 unaccounted; 3 accepted classes each with rationale + per-instance enumeration (§2) |
| F-P-2 | PASS | readback gate: written-file (ref,pad,net) == netlist, both directions; 0 unbound live pads |
| F-P-3 | PASS | footprints from the CP2-gated netlist (exact-part contracts J2/J6/J10/J11/J5 + footprint-existence at place()); fplib dims table cross-checked |
| F-P-4 | PASS | outline 100×80 + 4× M3 @ (4,4)(96,4)(4,76)(96,76) recorded into cp1_battery_side §2 (was "TBD at CP3") |
| F-P-5 | PASS | parity gate: 123/123 placed, 0 extra (hard fail, not warning) |
| F-P-6 | PASS | pad-net binding is by pad number (orientation cannot swap nets); polarity marks verified visually §6 |
| F-P-7 | PASS | fab gate: min drill 0.3 (after §4.1), annular ≥0.15, copper-edge 0.3 in project rules, DRC clean |
| PR-1 | PASS | property restoration puts every refdes on F.SilkS at library/managed positions (H1–H4 deliberately hidden) |
| PR-2 | PASS | on-body candidates demoted to last resort; render shows every refdes beside its part |
| PR-3 | PASS | silk_overlap 0 unaccounted |
| PR-4 | PASS | silk_over_copper 0 unaccounted |
| PR-5 | PASS | verified in crops (§6) |
| PR-6 | PASS | text angles normalized to 0/90 (read L→R / bottom-up); no inverted text |
| PR-7 | PASS | §3 floorplan; net-spread MST review on record (worst nets are MCU-hub signals, inherent + slow) |
| PR-8 | PASS | §5 mechanical enumeration: all HF decouplers <3 mm; bulk exceptions listed per-instance with role rationale |
| PR-9 | PASS | §3 + D38; connector edges/holes per cp1 §2 (updated) |
| PR-10 | PASS | RS485 A/B adjacent (U3.6/7→J2.4/5 short); CANH/L adjacent + term/jumper inline; USB D± through inline ESD, common corridor |
| PR-11 | PASS | solder_mask_bridge count 0 in full-severity DRC |
| PR-12 | PASS | same as F-P-3 |

## 8. Reviewer findings

*(reviewer appends §8.N here)*

## 9. Designer responses

*(designer appends §9.N here)*
