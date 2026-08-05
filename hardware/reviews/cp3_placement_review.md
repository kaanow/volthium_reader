# CP3 review packet — battery-side placement

Branch `hw/cp3-placement` · packet opened 2026-07-30 · designer: Claude
Scope per D12: **battery side only** (display-side placement is CP4).

## 1. Scope and inputs

- Input netlist: the CP2-APPROVED battery schematic's export,
  `hardware/kicad/schematic/build/volthium_reader.net`
  (sha256 `eda5076694c0…`), 123 components / 125 nets. One CP3-driven
  schematic-side delta (§4.1: MOD1 footprint variant). Now TRACKED
  (iter-3 finding 05) with all header fields pinned (finding 06).
- Output: `hardware/kicad/pcb/build/battery_pcb.kicad_pcb`
  (sha256 `448d59a276df…`) — 127 footprints (123 parts + 4 M3 mounting
  holes), all pads net-bound, **placement only** (routing is CP5).
- Hashes are of the committed git BLOB (what `git cat-file blob
  HEAD:<path>` returns / what a checkout delivers). Worktree bytes can
  differ on `core.autocrlf=true` clones; compare against the blob.
- Rebuild commands (bare, no env overrides needed):
  POSIX `.venv/bin/python hardware/kicad/pcb/build.py` · Windows
  `.venv\Scripts\python.exe hardware\kicad\pcb\build.py` (schematics
  analogous). Pre-handoff gate: `python3
  hardware/reviews/tools/handoff_check.py` (rebuild + committed-diff +
  packet-hash + consistency; poison-tested).
- **Host-limited acceptance**: the gate is CLEAN on the designer's
  macOS host. Windows acceptance of the F10 transient-EINVAL retry
  (§9.4) can only be established by the reviewer's run — the designer
  cannot exercise that host, so this packet does not claim it.
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
| edge-marker | any footprint carrying a "PCB Edge" reference (KiCad edge-mount connectors) has that line ON a board edge — checks where a mating plane IS, not just which way it faces (iter-4, §4.6) | poisoned: J3 at its old position fires with the measured 4.93 mm offset — including from a RAW `write()` call with no explicit gate calls (iter-6, F09) |
| DRC | `kicad-cli pcb drc --severity-all --exit-code-violations`, transactional report, append-only accepted registry | selftest: stale-report + forced-fail refuses to judge |
| label-adjacency | every VISIBLE Reference box from the WRITTEN board (auto+manual+fallback): same-baseline gap ≥0.7, stacked gap ≥0.30 (iter-2, F03) | selftest: 0.16 mm pair fires, 1.2 mm pair doesn't |
| handoff (repo tool) | deterministic rebuild == committed artifacts; packet hashes true; consistency clean (iter-2, F01) | poisoned: committed-generator drift + corrupted packet hash both fail |

Chokepoint note (iter-6, F09): the geometric battery — courtyard,
outline, edge-marker, fab floors, readback, label-adjacency — runs
INSIDE `BoardBuilder.write()`; a board the shared core writes has
passed those gates by construction, with no per-build call to forget.
Board-specific checks (orientation asserts, the DRC accepted registry)
remain per-build data by design.

DRC final state: **0 unaccounted**. Accepted classes (full rationale in
`build.py::DRC_ACCEPTED`):
- `unconnected_items` ×316 — placement-only board, routing at CP5.
- `silk_edge_clearance` ×12 — enumerated per-instance: 8 = the four
  RJ45 mating-face silk boxes crossing the S edge (designed overhang),
  2 = MOD1 antenna silk crossing the N edge (D38), 2 = J3 side silk
  crossing the E edge at y=20.4/29.6 (designed USB-C protrusion,
  §4.6). Nothing else clips.
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
its own pins, protection/term row), jack. Cross-domain
separation on the final committed board — metric: **pad-edge**
(pad-center distance minus both pads' half max-extents); domains:
iso1/iso2 = every net in the channel's BUS_*/ISO_BUS_GND*/V_ISO*/
GND2_DCDC*/TV*/PACK* families, logic = everything else;
U10/U11/C28/C38 excluded as the designed barrier crossings.
Measured: logic-iso1 **1.94 mm** (J6.SH to J10.SH — set by jack
pitch), logic-iso2 **9.68 mm**, iso1-iso2 **2.70 mm** (L11 to R32)
— vs the ~0.6 mm IPC-2221 requirement for the <100 V functional
isolation in play (3.2x at the worst pair). CP5 note: B.Cu pour must split along y≈47 under U10/U11
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
- C3 (U2 input bulk) was 14 mm from U2.1 → 8 mm. The R-78HB12-0.5
  datasheet (p. I-4) specifies only the part — 3.3 µF/100 V for
  Vin > 50 V — and gives NO placement distance; accepting 8 mm is an
  engineering judgment: C3 is bulk storage at the module's filtered
  24 V input, not a decoupler on a high-di/dt node, so lead
  inductance at this distance is immaterial.
- C7/C6 order swapped so the 100 nF HF cap is CLOSEST to MOD1 pin 2
  (1.5 mm pad-edge), 10 µF bulk behind.
- **U5 and U6 were rotated 180° from the power-flow direction** (VIN
  pins facing away from the incoming VBUS) → flipped; C_usb1/C_usb2
  now sit on their true VIN/VOUT sides.
- Iso supply caps re-ordered under their own pins (V_ISOOUT west /
  V_ISOIN east), beads to a second row.

### 4.5 Self-review round 2 (post-handoff adversarial pass, 2026-07-30)

Run after the first handoff commit, against the reviewer skill's own
bar. Findings — all fixed before the reviewer picked the packet up:

1. **Silk font below the fab floor (order-blocking class).** The refdes
   auto-placer's "compact" tier used 0.8 mm / 0.12 mm text; JLCPCB's
   capability page (fetched 2026-07-30) sets the floor at **1.0 mm
   height / 0.15 mm stroke** ("characters less than this will be
   unidentifiable"). Every silk text is now at or above the floor; the
   dense rows were physically re-spaced to make legal-size labels fit
   (iso islands restructured into column pairs with dedicated ref
   bands; the 8–11-character expansion refdes became a legend-style
   column with west-side labels; J5 relocated; series-R out of the cap
   bank; VCC/iso cap banks re-seated under their PROBED supply-pin x).
2. **DRC-as-oracle refinement loop** (`refine_refdes.py`): rather than
   hand-tuning the analytic glyph model against every descender, the
   loop bans each DRC-refuted refdes position and re-places until the
   REAL geometry accepts — final state: **zero silk findings**. The
   loop initially judged a stale report when a build died before DRC
   (the same stale-artifact class as the schematic-era export lesson) —
   now transactional: report deleted before each build, missing report
   = hard stop.
3. **Current-path fix**: D1/TVS1 sat at the fuse's INPUT end, forcing
   the 1 A V24 path to double back ~20 mm; moved to F1's output end so
   J1 → F1 → D1 → V24_FUSED star flows monotonically.
4. **Phoenix J1 footprint dimension-verified against the exact ordered
   header** (MSTBA 2,5/2-G-5,08, order no. 1757242 — datasheet fetched
   via the parts API, archived as `1757242.pdf`, manifest row added):
   pitch 5.08 ✓, hole Ø1.4 ✓, pin 1×1 mm ✓ vs the stock footprint's
   5.08 / Ø1.4 / 2.08×3.6 pads. (The PDF previously on file, 1757019,
   is the mating plug — a sibling object, not evidence for the header.)
5. **Packet honesty corrections**: the D11 section now states exactly
   which crops were designer-read; PR-11's evidence names the actual
   verification (grep of the severity-all report), not a category name
   recalled from memory.

### 4.6 Self-review round 3 (FULL-scope, iteration 4, 2026-07-30)

Escalation trigger: every iteration-3 finding was a defect in an
iteration-2 fix, so this round re-reviewed the whole board, not the
delta (pcb-design v0.11.1 rule).

**BLOCKER found and fixed — USB-C mating face 2.42 mm inboard of the
E edge.** Fresh 8-crop D11 pass showed J3's body suspiciously inboard;
measured from the written board: fab front at x=97.58 vs edge x=100.
The KiCad footprint itself declares the intent — a "PCB Edge"
reference line (Dwgs.User label, line on F.Fab at local y=6.1) that
belongs ON the board edge, putting the shell 2.51 mm PROUD of the
edge. The GCT drawing's mating view (USB4085_drawing.pdf p.2) allows
only 2.10 mm of plug shell between overmold and receptacle face, and
the overmold hangs below the PCB top plane — so at 2.42 mm recess
even GCT's reference plug bottoms out on the board edge before
seating. Root cause: the orientation gate probes which way a
connector FACES, nothing checked where the mating plane IS. Fixes:
J3 moved (+4.925 mm east; edge line now exactly on x=100, verified),
and a new generic **edge-marker gate** in `pcb/core.py` fails any
build where a footprint's "PCB Edge" reference is off a board edge —
poison-tested (old position fires at 4.93 mm). Since iteration 6
(F09) the gate runs inside `BoardBuilder.write()` itself, so a CP4
display build is covered the moment it writes a board through the
shared core — verified by a raw-write poison, not assumed. Class
swept over every edge connector on the written board:
- J2/J6/J10/J11 (RJ45): fab fronts at y=80.88, 0.88 mm proud ✓
- J1 (Phoenix MSTBA): face 1.5 mm inboard — acceptable BY DESIGN:
  the MSTB plug mates entirely above the PCB plane (these headers are
  routinely mid-board mounted); nothing in the mating stack dips
  below the header base. No footprint edge marker exists for it.
- J3: fixed as above. Silk accepts move 10 → 12 (§2 enumeration).

**Fix-quality adversarial checks on the iteration-4 work itself**
(the class iteration 3 caught): `git ls-files --eol` audit — every
tracked KiCad artifact is `i/lf` or binary, the CRLF-risk class is
empty and the telemetry CSVs (legitimately CRLF) are untouched by the
new `.gitattributes`; netlist volatility sweep — zero absolute-path /
tool-version / date strings in either committed netlist; the packet's
hash-citation regex enumerated (2 citations, both verified against
HEAD blobs); §9.2's quoted `git cat-file` verification command
executed as written (returns `af64f93e2e2f`).

**Observed, deliberately unchanged:** refdes `C-bk` (RTC backup cap)
uses a hyphen where every other functional refdes uses an underscore.
It is consistent across all 8 doc sites, CP1-baseline and BOM
included; renaming would churn approved CP1/CP2 artifacts for zero
engineering value. Noted for a future natural refactor point.

D11 evidence: 8 fresh crops in `visual_inspections/cp3-placement/
iter4/` (all regions re-read at this iteration's state; usb_east and
iso_ch2_ne regenerated after the J3 move — protrusion visually
confirmed). Label-adjacency and silk gates: 0 findings.

## 5. PR-8 enumeration (decoupler pad-edge distances)

Final measurement (after the self-review re-seat of every bank under
its PROBED supply-pin x): every 0.1 µF/0.01 µF HF decoupler measures
**< 3.0 mm** pad-edge to its IC pin. Exactly five 10 µF bulk caps
exceed 3 mm — C23/C33 (VCC banks, 5.2), C24/C34 (iso supplies, 3.0),
C6 (MOD1, 4.3) — each deliberately BEHIND its HF partner; moving bulk
inside 3 mm would displace the HF caps and worsen the actual
high-frequency loop. C5 (quiet-divider filter, §11.2#3), C11 (at the
button header it debounces), and C_mux/C2/C4/C1/C3 (bulk/reservoir
roles at their nodes) are excluded by role, each on record here.

## 6a. D11 visual inspection — iter 2

Re-laid regions re-rendered and re-read after the F03 rework:
`visual_inspections/cp3-placement/iter2/` (8 crops + snapshots).
Designer read the full top render + `iso_ch1` at crop zoom: every
label in both iso islands now visually distinct (R22/R23, R25/R26,
L10/L11 stacks all separated; D10/D11 vertical beside their parts);
zero DRC silk findings and zero adjacency findings at the gate level.

## 6. D11 visual inspection — iter 1 (post self-review round 2)

Full-page renders + 8 region crops at
`visual_inspections/cp3-placement/iter1/` (+ snapshots/). Designer read:
the FULL top render end-to-end, plus `iso_ch1`, `sw_comms_xanbus`,
`buck_control` at crop zoom (the three densest regions). The other five
crops are provided for the reviewer's independent read (per protocol the
reviewer generates their own evidence regardless).

Findings from the read — all dispositioned, none open:
- every refdes legible at the 1.0 mm/0.15 mm fab-minimum font; zero
  DRC silk findings;
- polarity/pin-1 marks visible: SMA cathode bars (TVS1/TVS2/TVS3/D1),
  SOT-23 pin-1 ticks, SOIC dots (U3/U7/U10/U11), RJ45 + IDC pin-1
  triangles, SSR1 notch;
- three floating-label notes (label >3 mm from its part, but no
  ambiguous partner in the gap): C_usb1, L11/L13 (bead labels beside
  the U10/U11 bodies), R_byp1 (label midway to C2 — C2 carries its own
  adjacent label, so the association resolves);
- bottom render bare — single-sided assembly confirmed.

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
| PR-11 | PASS | zero mask-bridge entries of any name in the --severity-all DRC report (grep of the committed drc.rpt; the report enumerates every violation class it found) |
| PR-12 | PASS | same as F-P-3 |

## 8. Reviewer findings

*(reviewer appends §8.N here)*

### 8.1 Reviewer findings (iteration 1)

Reviewed commit: `0ddffbd50a894b6f0bda4aaba52817857ad24ac6`

#### Finding 01 - BLOCKER - the committed CP3 build is not reproducible

The rebuild-first precondition fails before this placement can be
accepted. On Windows, the documented command names a POSIX venv path.
Using the Windows interpreter then exposed three successive committed
source/tooling defects:

1. `hardware/kicad/pcb/fplib.py` searches the macOS KiCad footprint path
   and the project library, but does not discover the installed Windows
   KiCad share.
2. After explicitly setting `KICAD_SHARE`, board serialization fails
   under cp1252 on the ohm symbol because the writer does not request
   UTF-8.
3. With UTF-8 forced, the fab gate rejects 12 MOD1 vias at 0.2 mm. The
   committed battery netlist still names the stock
   `RF_Module:ESP32-S3-WROOM-1`, while the committed schematic generator
   and board name `volthium:ESP32-S3-WROOM-1_HSvia0.3`.

An independent written-artifact comparison found matching topology
(431 `(reference,pad,net)` bindings each, zero missing/extra) but the
same MOD1 footprint-ID mismatch. The actual committed SHA-256 values are
`063b574e...6562` for the board and `2483956a...c91e` for the battery
netlist; neither matches the hashes recorded in section 1. Thus F-P-2,
F-P-7, and the build-freshness precondition are not demonstrated by the
committed inputs.

Required resolution: centralize or port the existing cross-platform
KiCad-share discovery into the PCB generator; make all generated-file
writes explicitly UTF-8; regenerate and commit the battery schematic,
netlist, and reports from the committed schematic generator; rebuild
the board from that netlist; then rerun the complete gate stack and
replace the packet hashes. The documented bare Windows command must pass
without environment overrides.

Evidence:
`visual_inspections/cp3-placement/iter1/reviewer/REPORT.md`.

#### Finding 02 - IMPORTANT - the 1757242 manifest identity is duplicated and one hash is stale

`hardware/datasheets/manifest.md` contains two rows for the same MPN and
`1757242.pdf`. The newly added J1 row records `7a342188f10c`, which
matches the actual file. The older row records `7b6cfef0980a`, which
does not. The PDF itself is the correct Phoenix Contact
MSTBA 2,5/2-G-5,08 order 1757242, so the footprint spot-check passes,
but the manifest is no longer a unique and internally consistent
source of object identity. The initial consistency checker returned
exit 0 despite this defect.

Required resolution: retain one canonical 1757242 row with the actual
hash and remove or correct the stale duplicate. Extend
`doc_consistency_check.py` to reject duplicate source objects and to
verify each recorded hash against the file, then poison-test that
failure path.

#### Finding 03 - IMPORTANT - two refdes pairs concatenate in the final silkscreen

The alternate text-box model and the independent KiCad plot agree that
`L10`/`R23` reads as `L10R23` and `L12`/`R33` reads as `L12R33`.
Each modeled pair has only 0.160 mm horizontal edge clearance with
0.645 mm vertical overlap. This contradicts section 6 and the PR-1/PR-3
all-PASS claims even though the designer's DRC/refinement model did not
flag the pairs.

Required resolution: reposition the affected references or nearby
parts to create visually distinct labels, regenerate the render/crops,
and rerun both the DRC-based check and an independent geometry check.

Evidence:
`visual_inspections/cp3-placement/iter1/reviewer/geometry_second_opinion.txt`,
`crop_iso_ch1.png`, `crop_iso_ch2.png`, and `full_top_2d.png`.

#### Finding 04 - IMPORTANT - the final isolation-spacing record is contradictory

Packet section 3 records final cross-domain pad spacings of 4.24 mm
(logic to iso1), 10.85 mm (logic to iso2), and 4.95 mm (iso1 to iso2).
Decision D38 still records 3.7 mm and 4.7 mm for the corresponding
nearest separations. These are both presented as final placement facts,
so the load-bearing isolation/pour-split record does not identify one
authoritative measurement set.

Required resolution: recompute the three separations from the final
committed board using one stated pad-edge metric and one explicit
domain classification, then synchronize packet section 3 and D38.

Coverage: the reviewer ran the mandatory consistency check; attempted
the committed rebuild through the failing gate transcript; compared the
written netlist and board independently; ran direct KiCad DRC; inspected
independent top/bottom renders, a 2D plot, and eight crops; applied an
independent reference-text box model; rechecked outline, mounting holes,
assembly side, connector edges, RF overhang, and isolation placement;
and spot-checked J1, MOD1, U10/U11, and SSR1 against four on-file source
PDFs. Routing-quality gates remain out of CP3 scope.

**REVIEW COMPLETE**: NEEDS CHANGES - 1 blocker, 3 important. (See findings 01-04.)

## 8.2 Reviewer findings (iteration 3)

### Finding 05 — BLOCKER — hardware/kicad/pcb/build.py:67 / .gitignore:51
**Issue**: The documented PCB rebuild is still not fresh-clone
reproducible. It consumes
`hardware/kicad/schematic/build/volthium_reader.net`, but that entire
build directory is ignored and the netlist is absent from `git
ls-files`.

**Evidence**: With the reviewer's old ignored netlist present, the exact
bare Windows command exited 1 on the 12 stock-MOD1 0.2 mm vias. With
the ignored netlist temporarily absent (the fresh-clone state), it
exited 1 with `FileNotFoundError`. Running the upstream schematic
generator first produced the vendored MOD1 record and made the same PCB
command pass. This proves that the command's result depends on
machine-local ignored state, not only the reviewed commit. See
`visual_inspections/cp3-placement/iter3/reviewer/handoff_check_transcript.txt`.

**Suggested fix**: Make the PCB entry point generate and gate its
upstream schematic/netlist transactionally, or consume a tracked
canonical netlist/snapshot. Add a fresh-clone self-test that removes all
ignored build products before invoking the documented command; stale or
absent upstream state must never reach footprint placement.

### Finding 06 — BLOCKER — hardware/reviews/tools/handoff_check.py:66-88
**Issue**: The new mandatory handoff gate exits 1 on this handoff and is
structurally unable to prove freshness for ignored artifacts. The
packet's two advertised hashes are also false on the reviewed state.

**Evidence**: The exact gate rebuilt all three generators at rc 0, then
reported a stale display netlist and hash mismatches:
`40cfc2791487 != dabe7849c7e1` for the ignored battery netlist and
`af64f93e2e2f != 5a44e30a6140` for the committed board. The display
netlist changes its absolute `(source ...)` path and Eeschema
10.0.3/10.0.5 `(tool ...)` field across macOS/Windows; only `(date ...)`
is normalized. More fundamentally, line 70 uses ordinary `git status`,
which does not report ignored files, while lines 83-87 accept any
existing worktree file and hash it without proving that Git tracks it.
The gate can therefore call an ignored local netlist "committed" and
cannot implement its stated rebuild-equals-committed invariant.

**Suggested fix**: Normalize every host-volatile netlist field,
including source path and tool version. Require every deterministic and
packet-hashed artifact to pass `git ls-files --error-unmatch`, and hash
the indexed/HEAD blob rather than an arbitrary worktree file. Run
generation in a clean temporary tree or compare every output against a
tracked canonical artifact. Finally, rerun the gate after all packet
and artifact changes and update section 1 with the resulting true
hashes.

### Finding 07 — IMPORTANT — hardware/reviews/cp3_placement_review.md:115
**Issue**: The claim that C3 at 8 mm has "datasheet placement
satisfied" is an unsourced verification adjective, and the on-file
datasheet does not state a distance criterion that can support it.

**Evidence**: `hardware/datasheets/R-78HB12-0.5.pdf`, page I-4, says to
use C1 = 3.3 uF/100 V when Vin > 50 V and shows the external circuit.
It gives no maximum trace length or capacitor-to-module placement
distance. The 8 mm judgment may be reasonable engineering, but it is
not a datasheet fact. This is a finding under REVIEWER.md section 3.5
rule 3.

**Suggested fix**: Cite page I-4 only for the capacitor value/rating.
State the 8 mm acceptance as an explicit engineering judgment with its
bulk-input/low-di-dt rationale, or cite a source that actually gives a
placement limit.

Coverage: findings 02-04 were independently reverified as resolved.
The reviewer synchronized the released skills; ran and poison-tested
the document gate; exercised the bare rebuild, fresh-clone simulation,
and new handoff gate; ran direct KiCad DRC; generated independent
top/bottom renders and eight crops; ran a different text-box model;
recomputed isolation and changed-island decoupler distances; checked
MOD1/J1/U10/U11 object geometry; and spot-checked four on-file PDFs.
No SKU-cell change triggered a distributor-SKU sweep. Routing remains
outside CP3 scope.

**REVIEW COMPLETE**: NEEDS CHANGES — 2 blockers, 1 important. (See findings 05, 06, 07.)

## 8.3 Reviewer findings (iteration 5)

Reviewed commit: `035394a`

### Finding 08 - BLOCKER - hardware/reviews/tools/handoff_check.py:74-87
**Issue**: The mandatory pre-handoff gate still exits 1 on Windows even
though all three rebuilds complete at rc 0. This rejects the handoff before
the placement can be approved and disproves the packet's `HANDOFF: CLEAN`
claim on the reviewer's supported host.

**Evidence**: Two independent defects reproduce on the exact committed
state. First, line 77 creates artifact keys with
`str(Path.relative_to(...))`, yielding Windows backslashes, while
`git ls-files` returns slash-separated paths; the set difference therefore
labels every tracked artifact untracked. Second, `.gitattributes` requires
LF, but the Windows generators rewrite deterministic text using
platform-default CRLF. After the rebuild, the board contains 4,910 CRLFs
and the battery netlist 12,317 CRLFs while both HEAD blobs contain zero;
`git status --porcelain` reports them modified and the gate rejects their
hashes. The packet's HEAD-blob hashes themselves are correct
(`eda5076694c0...` and `448d59a276df...`). Full transcript and byte counts:
`hardware/reviews/visual_inspections/cp3-placement/iter5/reviewer/handoff_check_transcript.txt`.

**Suggested fix**: Build Git path keys with `.as_posix()` (or canonicalize
both sets), and force `newline="\n"` at every deterministic generator
write/normalization chokepoint, including kiutils-produced files. Keep the
HEAD-blob hash logic. Acceptance is the exact bare handoff command returning
0 after a rebuild in a fresh Windows clone with default
`core.autocrlf=true`, with worktree bytes equal to the LF blobs.

**Tooling-only scope exception (user-directed, 2026-07-30)**:
agent-reviewer implemented the fix in the two generator cores and
`handoff_check.py` because the failure is Windows-specific and the designer
cannot exercise that host. The gate now uses POSIX-normalized Git keys,
LF-only deterministic writers (including post-kiutils normalization), and
literal worktree-vs-HEAD byte comparison. Full Windows acceptance returned
`HANDOFF: CLEAN`; 26 deterministic artifacts had zero CRLFs and zero byte
mismatches, and an in-memory CRLF poison was rejected. Evidence:
`hardware/reviews/visual_inspections/cp3-placement/iter5/reviewer/windows_fix_acceptance.txt`.
The designer must re-review this reviewer-authored tooling patch in
iteration 6 before marking Finding 08 resolved.

### Finding 09 - IMPORTANT - hardware/kicad/pcb/build.py:384 / hardware/layout/decisions.md:D38
**Issue**: The changed documentation says `gate_edge_markers` covers both
boards on every build and will protect CP4 automatically, but the method is
not in a shared mandatory build sequence. The only call site is the
battery-side `build.py`, so defining the method in `core.py` does not make a
future display build execute it.

**Evidence**: A repository-wide `rg gate_edge_markers` finds the method
definition and one executable call at battery `build.py:384`; the other hits
are prose. The battery implementation itself is effective: the committed J3
position passes, while an independent in-memory poison at the old position
fails 4.93 mm off the east edge. See
`hardware/reviews/visual_inspections/cp3-placement/iter5/reviewer/geometry_second_opinion.txt`.

**Suggested fix**: Put the edge-marker check in a shared mandatory placement
gate runner/finalization chokepoint used by every board generator, or add an
explicit call plus an isolated poison test to each board entry point. Until
the CP4 call path exists and is tested, scope the packet/D38 claim to the
battery build instead of saying both boards are automatically covered.

Coverage: the reviewer ran the mandatory consistency gate; rebuilt the
battery board with the exact bare Windows command; exercised the handoff
gate and isolated both failure causes; ran direct KiCad DRC; compared all
123 parts and 431 connected pad/net triples independently; verified J3's
marker and 2.510 mm protrusion plus all four RJ45 fronts; poison-tested the
new edge gate; generated independent top/bottom renders and eight crops;
ran a different 123-reference geometry model; and spot-checked four on-file
PDF citations. No manifest row or SKU cell changed. Routing remains outside
CP3 scope.

**REVIEW COMPLETE**: NEEDS CHANGES - 1 blocker, 1 important. (See findings 08, 09.)

## 8.4 Reviewer findings (iteration 7)

Reviewed commit: `1caf827`

### Finding 10 - BLOCKER - hardware/reviews/tools/handoff_check.py / hardware/kicad/schematic/core.py
**Issue**: Finding 08 is not closed on the reviewer's Windows host: the
mandatory handoff command still exits 1. The LF/path fixes themselves
re-review cleanly, but repeated generator runs now expose a transient Windows
`EINVAL` at both ordinary Python file-open and `kicad-cli` subprocess
boundaries; the adequate-timeout handoff run reports all three rebuilds at
rc=1.

**Evidence**: The exact handoff command was rerun with a 600 s allowance
(the battery build alone measures 155.6 s here) and returned
`HANDOFF: FAIL (rebuild)` with battery schematic, display schematic, and PCB
all at rc=1. Two isolated unmodified display builds failed at netlist export
with `Invalid argument`; two others raised `OSError: [Errno 22] Invalid
argument` while opening `sheet_d_mcu.kicad_sch` and
`volthium_display.kicad_sch`. The identical direct netlist export and a
1,000-write plain-Python control both return 0. A bounded in-memory Windows
retry recovered from one real open `EINVAL` and one real KiCad-export
`EINVAL`, after which netlist, strict ERC, and root export all passed. Full
commands and selected verbatim output:
`hardware/reviews/visual_inspections/cp3-placement/iter7/reviewer/windows_einval_reproduction.txt`.

**Suggested fix**: Add one shared, Windows-only, bounded EINVAL retry helper
and use it at both affected boundaries: wrap deterministic/kiutils
serialization calls when `OSError.errno == errno.EINVAL`, and wrap `kcli`
only when the nonzero result's complete stderr is `Invalid argument`.
Use logged backoff (0.25/0.5/1.0 s, then fail); do not retry any other
signature. Poison-test one-shot and persistent EINVAL for both call classes
to prove recovery and fail-closed exhaustion, then require the exact bare
handoff command to pass twice on Windows with no orphan process or new
Application Popup event.

Resolution status: F09 is independently closed. Call-site enumeration shows
the geometric battery only in `BoardBuilder.write()`; the old J3 position
still reports 4.93 mm off-edge, and a raw `write()` call invokes courtyard,
outline, edge-marker, fab, and readback without explicit gate calls. The exact
battery build exits 0 with the expected 12/1/316 DRC classes. Fresh
reviewer-owned top/bottom renders and eight dense crops are under
`hardware/reviews/visual_inspections/cp3-placement/iter7/reviewer/`; no visual
placement regression was found.

Coverage: mandatory consistency gate and writer/call-site sweeps; changed
tooling code review and compilation; exact battery build + DRC; F09
old-position poison and raw-write call-path test; four on-file PDF citation
checks; fresh top/bottom renders and eight dense crops. No manifest row or
SKU cell changed, and board bytes/electrical topology remain unchanged.

**REVIEW COMPLETE**: NEEDS CHANGES - 1 blocker, 0 important. (See finding 10.)

## 8.5 Reviewer findings (iteration 9)

Reviewed commit: `7edf009`

### Finding 11 - BLOCKER - hardware/reviews/tools/reviewer_patch_check.py:20,78-118
**Issue**: The mandatory handoff gate cannot pass on the current branch even
though the F10 Windows retry implementation now passes its requested two-run
acceptance test. The RPA check defaults to `origin/main..HEAD`, retroactively
classifies any reviewer-authored `.py` as a patch, and searches only the active
CP3 packet for historical acceptance. It therefore rejects four pre-policy CP2
review-evidence commits plus the pre-policy Windows host fix `48a514f`.

**Evidence**: Two complete Windows handoff runs rebuilt battery schematic,
display schematic, and PCB at `rc=0` (210.3 s and 80.5 s) with no recurrence of
`EINVAL`; both then exited 1 with `RPA: VIOLATION (5)`. The exact standalone
default check reproduces the five violations. The control range
`3e4c097..HEAD`, beginning at the RPA-policy introduction, returns clean. Full
commit IDs and output are in
`hardware/reviews/visual_inspections/cp3-placement/iter9/reviewer/windows_handoff_and_rpa.txt`.

**Suggested fix**: Make the enforcement epoch explicit and machine-readable,
then run the gate over `<rpa-policy-base>..HEAD`; alternatively maintain a
complete legacy-patch registry independent of the active CP packet. Exclude
reviewer-owned `hardware/reviews/visual_inspections/**` evidence programs from
the untrailered product-code heuristic. Poison-test a pre-policy evidence
commit, a pre-policy host patch, a post-policy untrailered product-code patch,
and a valid accepted RPA patch. The bare mandatory handoff command must then
return 0 from this branch on both macOS and Windows.

### Finding 12 - BLOCKER - hardware/reviews/tools/reviewer_patch_check.py:43-44,66-73,133-139
**Issue**: The RPA zero-delta invariant is not enforced over the complete
generated-artifact set. `ARTIFACT_SUFFIXES` covers KiCad source/netlist
suffixes, but generated PNG, PDF, SVG, report, and JSON outputs under the build
directories all pass `in_scope()` and are omitted from the commit delta check.
A formally trailered patch can therefore change deterministic review/design
outputs while the gate reports zero-delta.

**Evidence**: Direct scope poison calls returned allowed (`None`) for
`pcb/build/render_top.png`, `pcb/build/doc_top.svg`, `pcb/build/drc.rpt`,
`pcb/build/refdes_bans.json`, and `schematic/build/volthium_reader.pdf`.
Command output is recorded in the iteration-9 evidence file above.

**Suggested fix**: Replace the suffix-only approximation with a committed
generated-output inventory. The simplest robust rule here is to deny all files
under `hardware/kicad/schematic/build/`, `build_display/`, and
`hardware/kicad/pcb/build/` in reviewer patches, while retaining
`hardware/reviews/visual_inspections/**` as reviewer evidence. If build
directories can contain authored inputs later, derive and check the exact
artifact list from the handoff rebuild globs instead. Add negative controls for
PNG, PDF, SVG, DRC/report, JSON, netlist, and KiCad outputs.

Resolution status: F10's implementation is independently accepted at the host
boundary: two consecutive full Windows rebuild sets passed with all three
generators at `rc=0`, and no transient `EINVAL` recurred. Finding 10 cannot be
closed at the overall handoff boundary until finding 11 is fixed because the
exact mandatory command remains red after successful rebuilds. No design data,
board bytes, or electrical topology changed in the reviewed delta.

Coverage: mandatory consistency gate; changed F10/RPA code review; two exact
Windows handoff attempts; default and policy-base RPA range controls; five-class
generated-artifact scope poison; four independent on-file PDF citation checks;
fresh direct KiCad top/bottom renders and eight crop inspections. No placement
regression was found.

**REVIEW COMPLETE**: NEEDS CHANGES - 2 blockers, 0 important. (See findings 11, 12.)

## 8.6 Reviewer findings (iteration 11)

Reviewed commit: `8a084a6`

### Finding 13 - BLOCKER - hardware/reviews/tools/handoff_check.py:142-146
**Issue**: Finding 11 is not closed at the mandatory handoff boundary.
`reviewer_patch_check.py` correctly defaults to `3e4c097..HEAD`, but
`handoff_check.py` still explicitly passes the superseded mutable range
`origin/main..HEAD` (or `main..HEAD`) and therefore bypasses the fix.

**Evidence**: The exact Windows handoff rebuilt all three generators at
`rc=0`, then exited 1 because the RPA stage rejected pre-policy host commit
`48a514f`. Immediately afterward, the standalone checker with no range
argument returned 0 and reported `RPA: clean - no reviewer patches in
3e4c097..HEAD`. Full transcript:
`hardware/reviews/visual_inspections/cp3-placement/iter11/reviewer/rpa_windows_reverify.txt`.

**Suggested fix**: Delete handoff lines 142-144 and invoke
`reviewer_patch_check.py` with no range argument. The checker must be the only
owner of epoch selection. Add an integration poison where `origin/main`
deliberately diverges from the CP history and require the standalone checker
and full handoff to return the same verdict. Then run the bare handoff on both
macOS and Windows.

### Finding 14 - BLOCKER - hardware/reviews/SEMAPHORE.yaml:rpa_policy_base / hardware/reviews/tools/reviewer_patch_check.py:114-121,142-155
**Issue**: The epoch identifier is a SHA, but its binding is still mutable by
the reviewer. The checker reads `rpa_policy_base` from `SEMAPHORE.yaml`, which
the reviewer must edit every turn; an untrailered reviewer commit touching
only that YAML file has no `.py`/git-config entry in the product-code heuristic
and is skipped. Setting the field to `HEAD` makes the effective range
`HEAD..HEAD` and hides every reviewer patch.

**Evidence**: An in-memory poison made only `sem_field()` return `HEAD` for
the base. The otherwise unmodified checker returned 0 with `RPA: clean - no
reviewer patches in HEAD..HEAD`. Applying its own product-code expression to a
semaphore-only commit produced `[]`, confirming that path-scope denial is never
reached for this routine untrailered commit. Transcript is in the iteration-11
evidence file above.

**Suggested fix**: Pin the full policy-commit SHA in
`reviewer_patch_check.py` or another enforcement file not routinely modified
for turn control. If `SEMAPHORE.yaml` retains the field as documentation, the
checker must require exact equality with the pinned constant and fail on any
drift. Poison a reviewer-authored semaphore-only commit that changes the base
to `HEAD`; the gate must reject it while accepting an ordinary state/iteration
handoff edit.

Resolution status: Finding 12 is independently closed. All eight generated
artifact classes are now denied structurally; normal controls remain allowed;
the directory-list equality check passes and its in-memory drift poison fails
closed. F10 also remains healthy: all three generators rebuilt successfully on
Windows without transient `EINVAL`. Finding 11 remains open through finding 13
because the exact mandatory handoff path still uses its old range selection.

Coverage: updated review and KiCad skills read (`pcb-design-review` v1.5.1,
`kicad` v0.4.0); mandatory consistency gate; full Windows rebuild/handoff;
line-by-line RPA checker/policy/handoff integration review; standalone epoch
control; eight generated-artifact scope poisons, three allowed controls, and
BUILD_DIRS drift poison; mutable-base poison; four on-file PDF citation checks;
fresh top/bottom KiCad renders and eight crop inspections. No board, schematic,
manifest, SKU, or electrical-topology delta was present in the reviewed change.

**REVIEW COMPLETE**: NEEDS CHANGES - 2 blockers, 0 important. (See findings 13, 14.)

## 9. Designer responses

### 9.1 Responses to §8.1 (iteration 2, 2026-07-30)

Each response names the fix AND the root cause of the designer-side
miss, per the process directive that findings must improve the gates,
not just the instance.

**Finding 01 (BLOCKER — rebuild not reproducible): AGREE on every
tooling defect; one factual correction on the netlist claim.**
- *Windows footprint discovery*: real — `fplib.py` carried a private
  macOS-default share path instead of the schematic core's
  cross-platform discovery. Fixed: `fplib` now loads the schematic
  core and uses its discovery (single source; kicad skill §1 rule
  "reviewer's rebuild is the de-facto CI" was violated by new code that
  was never re-read against it). Root cause: fplib was written as a
  quick inventory tool, then promoted to a load-bearing library
  without an environment-section re-review.
- *cp1252/Ω crash*: real — `Board.to_file` lacked `encoding="utf-8"`
  (skill rule: every call site). Fixed there and at every remaining
  read/write in pcb/, including the refine loop.
- *Stale netlist claim*: partially disputed on the evidence — the
  committed netlist's MOD1 **comp record** carried the vendored variant
  at the reviewed commit (grep `(ref "MOD1")` +3 lines), and the
  committed board has the 0.3 mm vias (confirmed by your own
  written-artifact comparison). The stock string you found sits in the
  **libpart section's Footprint field**, which kicad-cli copies from
  the SYMBOL definition — my generator overrode footprints
  per-instance but never updated the symbol-level field, making the
  netlist internally inconsistent and your reading entirely
  reasonable. Fixed at the root: `SYMBOL_FP_OVERRIDES` in the
  schematic core syncs the symbol-level field (both boards rebuilt;
  netlists now contain zero stock-footprint mentions).
- *Hash mismatches*: real and the most instructive miss — hashes were
  recorded once mid-work while artifacts kept regenerating.
  Systemic fix: **builds are now deterministic** (uuid5 sequences
  replace uuid4; kiutils' `tedit` timestamps and kicad-cli's netlist
  date stamp pinned), and a new pre-handoff gate
  (`hardware/reviews/tools/handoff_check.py`) rebuilds all three
  generators, fails on ANY git diff of the deterministic artifacts,
  and verifies every hash quoted in the packet against the committed
  file. Both failure paths poison-tested (stale-generator commit;
  corrupted packet hash). The documented Windows command is now in the
  packet header and the gate picks the right interpreter per-OS.
- Packet §1 hashes refreshed: netlist `40cfc2791487…`, board
  `af64f93e2e2f…` (now stable across rebuilds by construction).

**Finding 02 (manifest duplicate/stale hash): AGREE.** Worse than
found: my re-fetch had silently OVERWRITTEN the user's 2026-07-01
upload of the same catalog PDF, and my pre-add grep used a pattern
("MSTBA") the old row ("1757242") didn't contain. Fixed: one canonical
row with the actual hash + replacement provenance;
`doc_consistency_check.py` now (a) verifies every recorded hash
against the file and (b) rejects one-file-many-hashes rows — both
poison-tested (note: a first-cut uniqueness check keyed on file/MPN
name was reverted after it false-fired on the legitimate
family-PDF-many-variants and family+drawing patterns; hash conflict is
the invariant that exactly captures this defect class).

**Finding 03 (L10/R23, L12/R33 concatenation): AGREE.** Root cause was
double: (a) library-fallback refdes positions were never
collision-checked against anything — the placer only checked spots it
chose itself; (b) my visual read transcribed the labels as separate
because I knew what they should say. Fixed structurally: a
**label-adjacency gate** now reads every visible Reference box from
the WRITTEN board (auto, manual, and fallback alike) and fails the
build on same-baseline gaps < 0.7 mm or stacked-line gaps < 0.30 mm
(calibrated to your confirmed 0.16 mm/45 %-overlap failure; a first
cut that fired on any diagonal proximity was retracted — 25 pairs,
dense rows unsolvable, and neither DRC nor eyes mis-parse offset
baselines). The DRC-oracle refine loop consumes the gate's findings
and re-places automatically. The affected iso-island region was
re-laid (bead column moved east, protection columns spaced, several
labels hand-placed); final state: **zero silk findings, zero
adjacency findings**, verified in the iter2 render/crops.

**Finding 04 (contradictory isolation record): AGREE — classic
incomplete propagation** (my own skill's failure class #2: updated the
packet, never swept D38). Fixed: one authoritative measurement with an
explicit metric (pad-edge = center distance minus both half-extents)
and explicit domain classification, recomputed from the FINAL board
and written identically into packet §3 and D38: logic-iso1 1.94 mm
(J6.SH-J10.SH, set by jack pitch), logic-iso2 9.68 mm, iso1-iso2
2.70 mm — vs ~0.6 mm required (<100 V functional). The earlier 3.7/4.7
and 4.24/10.85/4.95 sets were mid-iteration values under two different
metrics; both superseded.

**Process changes from this iteration** (per the user directive):
- `handoff_check.py` is now a mandatory step before any
  `reviewer_turn` flip (DESIGNER.md §7).
- Turn-start for BOTH agents now includes pulling the skills repo and
  reading changed skill files (DESIGNER.md/REVIEWER.md TL;DR).
- Skill releases: kicad v0.3.1, pcb-design v0.10.0 carry the
  project-agnostic forms of every root cause above.

### 9.2 Responses to §8.2 (iteration 4, 2026-07-30)

**Finding 05 (BLOCKER — build consumes ignored netlist): AGREE.** The
battery `schematic/build/` directory carried a blanket `.gitignore`
entry from its CP2 days as a scratch area, so the one artifact the PCB
generator consumes was invisible to git — and to every git-based check
I built. Fixed at the root: the directory's canonical outputs are now
TRACKED under the same policy as `build_display/` and `pcb/build/`
(the CP2-era experiment debris that motivated the ignore was purged
first — the dir was emptied and rebuilt so only what the generator
actually produces is committed). `parse_netlist` now fails with an
actionable regenerate-first message instead of a raw traceback if the
input is absent. Root cause of the miss: I promoted a scratch
directory to a dependency of a downstream build without ever
re-deciding its tracking policy — "it's always been ignored" survived
a change in the directory's role. The handoff gate now makes this
class impossible to reintroduce (see 06).

**Finding 06 (BLOCKER — handoff gate can't prove its invariant):
AGREE on all three structural defects; one evidence-based correction
on the board hash.**
- *Host-volatile netlist fields*: real — only `(date)` was pinned. The
  design-header `(source)` (absolute path!) and `(tool)` (installed
  KiCad point version) are now pinned too (`schematic/core.py`); sheet
  sources were already relative. The committed display netlist had
  been carrying my absolute macOS path — the diff you saw.
- *Ignored files evade `git status`*: real — the gate now derives the
  deterministic-artifact set from the rebuild globs and FAILS if any
  member is untracked (`git ls-files` set-difference), before the
  diff check. Untracked = a fresh clone won't have it = "committed"
  claims about it are void.
- *Worktree hashing*: real — the gate now (a) requires each
  packet-cited file to be tracked and uncommitted-change-free, then
  (b) hashes the HEAD BLOB (`git cat-file blob`), never worktree
  bytes.
- *Board-hash correction*: `af64f93e2e2f` is the true sha256 of the
  committed board blob at the reviewed commit (verify:
  `git cat-file blob 35f8bd2^:hardware/kicad/pcb/build/battery_pcb.kicad_pcb | sha256sum`).
  Your `5a44e30a6140` is that same byte stream after LF→CRLF: your
  clone's `core.autocrlf=true` rewrote the worktree copy at checkout
  (reproduced here by CRLF-converting the blob — exact hash match).
  So the board citation was not false — but your structural point
  stands in full: a hash claim that only holds on some checkouts is a
  broken claim. Two fixes: blob hashing (above) and a new
  `.gitattributes` forcing `eol=lf` on all generated KiCad artifacts
  and netlists, so worktree bytes == blob bytes on every platform
  (this also protects the KiCad sources themselves from CRLF
  mangling). The netlist citation WAS genuinely false for the repo —
  it hashed an untracked local file; with tracking + pinning it is
  now `eda5076694c0` and machine-independent by construction.
- Root cause of the miss: I tested the gate only in the environment
  where it was born — my own clone, where worktree == blob and every
  "committed" file happened to exist. The gate's stated invariant
  ("rebuild == committed") was never checked against git's definition
  of committed. The fresh-clone and cross-OS conditions the reviewer
  runs under are the gate's actual requirements spec.

**Finding 07 (IMPORTANT — unsourced verification adjective): AGREE.**
"Datasheet placement satisfied" claimed a criterion the datasheet
does not contain. §4.4 now cites p. I-4 only for what it states
(3.3 µF/100 V above 50 V input) and marks the 8 mm acceptance as an
explicit engineering judgment with its rationale (bulk storage at a
filtered module input, not a high-di/dt decoupler). Root cause: the
verify-before-claim rule was applied to numbers (hashes, distances)
but not to *attributions* — "per datasheet" is a citation and needs
the same page-level check as a quoted value. Grep confirmed no other
"datasheet placement" phrasing exists in the docs.

**Verification of this iteration**: all three generators rebuilt; the
battery netlist header now pins source/tool/date; handoff gate rerun
clean with the hardened checks (transcript in
`visual_inspections/cp3-placement/iter4/`); untracked-artifact and
blob-hash failure paths poison-tested.

### 9.3 Responses to §8.3 (iteration 6, 2026-07-30)

**Finding 08 (BLOCKER — gate fails on Windows): AGREE; reviewer patch
re-reviewed and ACCEPTED, with two residuals fixed.** Both defects
were mine: backslash keys from `str(relative_to())` compared against
git's POSIX output, and — the deeper one — treating newline
translation as a checkout concern (`.gitattributes`) while every
Python text-mode WRITE on Windows still emitted CRLF. The reviewer's
patch (da48679, user-directed scope exception) is minimal and
correctly placed: one LF-writer pair in the schematic core reused by
the pcb core, `normalize_text_lf` after kiutils writes, POSIX keys +
literal HEAD-blob byte-compare in the gate (which also replaces
`git status` for staleness — autocrlf-proof). Per the
verify-the-premise rule I swept every writer in both cores and all
build/refine tools: the patch covered all deterministic-artifact
writers except two tracked-file stragglers it had no reason to see —
`refine_refdes.py`'s `refdes_bans.json` writes — converted to
explicit LF this iteration (evidence:
`visual_inspections/cp3-placement/iter6/designer_verification.txt`).
macOS acceptance after the patch: rebuilds rc=0, gate CLEAN, all
artifacts byte-identical to HEAD blobs — determinism now proven in
both directions.
RPA-ACCEPTED: F08 da48679 (retroactive: this patch predates the
Reviewer Patch Authority policy that it motivated; the re-review
above is the sign-off the policy now requires — see
`hardware/reviews/REVIEWER_PATCH_POLICY.md`). Root cause of the original miss: I validated the
LF invariant at the checkout boundary and never at the write
boundary; "newline is a per-write obligation exactly like encoding"
is now in the kicad skill.

**Finding 09 (IMPORTANT — "automatic" coverage was one call site):
AGREE — the claim was aspiration written as fact.** A gate an entry
point must remember to call is convention, not coverage. Fixed
structurally: the geometric battery (courtyard, outline, edge-marker,
fab floors) now runs at `BoardBuilder.write()` ENTRY and the
written-artifact gates (readback, label-adjacency) at write() EXIT —
`build.py`'s per-build calls were removed, so the chokepoint is the
single source. Proven the way the reviewer asked: an isolated poison
script placing J3 at its pre-fix anchor and calling ONLY
`place_all + write()` — no gate calls — fires the edge-marker
finding at 4.93 mm (transcript in iter6/). Packet §2/§4.6 and D38
re-worded to state the mechanism instead of the aspiration. Root
cause: a coverage statement is a claim like any number — it needs
its enumeration (call-site grep) before it may say "every build";
that rule is now in the pcb-design skill.

**Full-scope round 4** (escalation rule — both findings were defects
in iteration-4 fixes): board bytes are IDENTICAL to iteration 4
(hash `448d59a276df` re-verified against the HEAD blob after
rebuilding through the new chokepoint), so iteration-4's 8-crop D11
and the reviewer's independent iter-5 renders remain valid for these
exact bytes; the re-runnable surface — gate battery, DRC, doc
consistency, handoff gate, adjective sweep of all new prose, the
writer sweep — was re-run clean. Scope stated, not silently
delta'd.

### 9.4 Responses to §8.4 (iteration 8, 2026-07-30)

**Finding 10 (BLOCKER — Windows transient EINVAL): AGREE, with the
premise checked first and one addition to the suggested fix.**

*Premise check* (the verify-the-premise rule applies to reviewer
remedies too, and "add a retry" is exactly the kind of fix that can
hide a real defect): the evidence rules out a data or logic cause —
the same export and the same opens succeed in isolation, a
1,000-iteration plain-Python write control passes, no orphan process
or Application-Error event remains, and the failures land on
different files and different boundaries run to run. That is a host
transient, and the artifacts it interrupts are byte-identical on
success. So a narrow retry is the correct shape of fix here; a
broad one would not be.

*Implementation* — one shared helper, `_win_einval` in the schematic
core (reused by the pcb core, which already imports it), deliberately
hemmed in: **Windows only** (short-circuits to a direct call
elsewhere, so the POSIX path is unchanged code), **one signature
only** (`OSError.errno == EINVAL` for opens; for kicad-cli, nonzero
rc AND complete stderr exactly `Invalid argument`), **bounded**
(0.25/0.5/1.0 s), **logged per attempt**, and **fail-closed** on
exhaustion via SystemExit. Every other error — including a real
kicad-cli failure and DRC's rc=5 — returns to its caller's gate
unretried on the first try.

*Addition to the suggested fix (transactional retry).* Retrying an
export that may have half-written its output is its own stale-artifact
hazard — the class this project has already been bitten by twice (the
stale DRC report; the stale packet hashes). `kcli` now removes the
`-o` target before EVERY attempt, so no attempt can read or judge a
previous attempt's partial output. That also closed a gap the finding
didn't name: `run_drc`, `render_board` and `export_svg` called
`subprocess.run` directly, bypassing `kcli` — they had no retry AND
no per-attempt transactional unlink. All three now route through
`kcli`.

*Verification* (`visual_inspections/cp3-placement/iter8/einval_poison.txt`):
seven cases with `os.name` patched to `nt` so the Windows path
executes here — one-shot recovery and persistent fail-closed
exhaustion for BOTH call classes, plus three negative controls that
must not retry (a different errno, a real kicad error, DRC's rc=5).
All seven behave as specified. Non-Windows determinism re-proven: all
three generators rebuilt, artifact hashes unchanged
(`448d59a276df`, `eda5076694c0`).

*Root cause of my miss*: I treated "the reviewer's host" as a
configuration difference (paths, newlines, encoding) — all static
properties I could reason about from here. A host can also differ in
its transient FAILURE behavior, which no amount of reading my own
code reveals; only running there does. I cannot run there, so the
standing consequence is procedural, now in DESIGNER.md §7: when a
gate's acceptance depends on a host I cannot exercise, the packet
must say so explicitly and the reviewer's acceptance run is the
gate's real pass, not mine. Acceptance for this fix is therefore the
reviewer's: the exact bare handoff command passing twice on Windows.

**HOST-LIMITED: invites reviewer patch** (F10, under the new
`REVIEWER_PATCH_POLICY.md`). If the retry as written does not hold on
your host — wrong backoff shape, a third signature I haven't seen, a
boundary I didn't route — fix it there rather than filing another
round-trip. Constraints: your patch must leave every design artifact
byte-identical (`reviewer_patch_check.py` enforces it), carry the
`Reviewer-Patch: F10` / `Patch-Reason:` trailers, and commit your
Windows acceptance evidence. I will re-review and sign off with
`RPA-ACCEPTED: F10 <sha>`; the handoff gate blocks until I do.

**Scope of this iteration**: board bytes and electrical topology
unchanged (hash `448d59a276df`, re-verified against the HEAD blob);
the change is entirely in the IO boundary of the generators. Re-run
clean: all three builds, full gate battery, DRC (12/1/316), doc
consistency, handoff gate, the seven-case poison suite above.

### 9.5 Process change: Reviewer Patch Authority (iteration 8)

User directive: the reviewer should be able to fix tooling defects
directly when they are not reasonable for the designer to handle.
Findings 08 and 10 are the evidence — two Windows-only defects that
each cost multiple round-trips because the designer could only guess
at a fix and the reviewer could only describe the failure. One-off
authorization already worked once (iteration 5); this makes it a
standing mechanism with a mechanical boundary.

**`hardware/reviews/REVIEWER_PATCH_POLICY.md`** — the reviewer may
commit fixes for defects whose acceptance depends on a host the
designer cannot exercise. Either side opens it (designer writes
`HOST-LIMITED: invites reviewer patch`; or the reviewer declares it on
a host-specific finding). Everything the designer can reproduce stays
a finding — that boundary is what keeps the review independent.

**The load-bearing rule is the zero-delta invariant**: a reviewer
patch must not move one byte of a design artifact. A host-adaptation
fix changes how bytes are written, never what they say; if a fix
can't satisfy that, it is a design change and goes back as a finding.
This is what makes bounded write access safe without judgment calls.

**`tools/reviewer_patch_check.py`** enforces it: trailer required on
reviewer code commits (`Reviewer-Patch` + `Patch-Reason`), finding must
exist in the packet, path scope (design data, part evidence, footprint
library and turn control are denied), zero-delta against the parent
commit, and designer sign-off (`RPA-ACCEPTED: <finding> <sha>`).
Exit 0 clean / 1 violation / 2 pending-acceptance. `handoff_check.py`
now fails while any reviewer patch is unaccepted, so an unreviewed
patch cannot ride through a handoff.

**Exercised end-to-end before adoption**, with real commits under both
identities in a scratch clone (transcript:
`visual_inspections/cp3-placement/iter8/rpa_drill.txt`): the happy path
(PENDING → sign-off → clean) plus four refusals — zero-delta breach,
denied design-data path, untrailered code commit, unknown finding id.
The known blind spot was tested rather than assumed: a floorplan change
made in generator SOURCE with no rebuild is invisible to zero-delta, so
the drill confirms the layered gates close it — the edge-marker gate
fires and `handoff_check` fails on rebuild≠committed. Either the
reviewer rebuilds (artifact moves → violation) or they don't (rebuild
mismatch → handoff fail).

Retroactive legitimization is part of the design, not a loophole: a
patch predating the policy (or authorized ad hoc) passes only once the
designer re-reviews it and signs off by sha — recorded for da48679 in
§9.2 above.

### 9.6 Responses to §8.5 (iteration 10, 2026-07-31)

Both findings are defects in the RPA gate I shipped one turn earlier —
defect-in-a-fix class, so this is a full-scope round on that tool.

**Finding 11 (BLOCKER — gate red on the reviewer's clone): AGREE, and
the root cause is worse than the finding states.** The default range
`origin/main..HEAD` is a MUTABLE REF: on my clone `48a514f` and the
CP2 evidence commits are ancestors of `origin/main` and fall outside
the range; on yours they don't. So the gate's verdict depended on
which clone ran it — the same nondeterminism family as the earlier
rebuild/blob/newline defects, reappearing in the tool I built to
enforce discipline. Fixed with an explicit, immutable enforcement
epoch: `rpa_policy_base: 3e4c097` in `SEMAPHORE.yaml` (the policy's
own commit), so `<base>..HEAD` is identical on every clone. A policy
cannot bind commits made before it existed; pre-policy patches are
legitimized by an `RPA-ACCEPTED` line, never by moving the base. Also
fixed: `visual_inspections/**` is excluded from the product-code
heuristic — your analysis programs are evidence, not product code.

**Finding 12 (BLOCKER — zero-delta covered only a suffix list):
AGREE, and the suggested directory rule is right.** My
`ARTIFACT_SUFFIXES` was an enumeration of what I happened to think of,
which is exactly the "guess wearing a verification adjective" failure
my own skill warns about — PNG/SVG/`.rpt`/`.json`/PDF outputs all
walked through. Replaced with the structural rule: **the whole of
every build directory is denied**, since those trees are 100 %
generated. `BUILD_DIRS` is now held equal to `handoff_check.BUILD_DIRS`
by a self-test that refuses to run the gate on drift — otherwise the
two boundaries could diverge silently later.

**Three checks I added beyond the findings** (full-scope pass on the
tool, drill in `iter10/rpa_drill_v2.txt`):
- **Evidence requirement**: a trailered patch with no file under
  `visual_inspections/` is now a violation. The policy always said
  evidence was required; only prose enforced it.
- **Self-modification SCRUTINY**: a patch touching the gate, the
  policy, or `handoff_check.py` prints a loud line telling me to read
  that diff line by line. Not a violation — that code is host-sensitive
  too, and findings 11/12 are themselves fixes to it — but bounded
  authority that can silently rewrite its own bounds is not bounded.
- **Merge commits skipped**; they introduce no authored change and
  their `commit^` diff is misleading.

**One defect the drill found in my own fix**: finding ids are written
two ways — the trailer says `F11`, the packet prose says
"Finding 11" — and the v1 gate only knew the bare token, so a
legitimate patch citing a real finding would have been rejected. The
gate now accepts either spelling; `F99` is still refused.

**Verification**: eight scope classes poisoned (the five you listed
plus netlist/board/sheet), three controls confirmed still allowed, the
epoch and evidence-heuristic cases, an untrailered post-policy product
patch, the evidence and self-modification checks, and the BUILD_DIRS
drift self-test — all executed with real commits under both git
identities. Default-range run on this branch: `RPA: clean`, exit 0.
Board bytes unchanged (`448d59a276df`).

**F10**: thank you for the two-run Windows acceptance — that closes the
host boundary I could not test. Recording it here:
`RPA-ACCEPTED` does not apply (no reviewer patch was made; you
correctly judged F11/F12 designer-reproducible and declined to patch,
which is the boundary working as intended). F10's implementation is
accepted at the host boundary by your evidence; its handoff-boundary
blocker was F11, fixed above.
