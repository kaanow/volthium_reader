# CP4 review packet — display-side placement

Branch `hw/cp4-display-placement` · packet opened 2026-08-05 · designer: Claude
Scope per D12: **display side only** (battery-side placement was CP3, APPROVED).

## 1. Scope and inputs

- Input netlist: the CP2-APPROVED display schematic's export,
  `hardware/kicad/schematic/build_display/volthium_display.net`
  (sha256 `bdb817c16281…`), 39 components / 56 nets. Two CP4-driven
  schematic-side deltas, both in §4.1.
- Output: `hardware/kicad/pcb/build_display/display_pcb.kicad_pcb`
  (sha256 `cebadb942b4f…`) — 43 footprints (39 parts + 4 M3 mounting
  holes), all pads net-bound, **placement only** (routing is CP5).
- Hashes are of the committed git BLOB (`git cat-file blob HEAD:<path>`).
- Rebuild: POSIX `.venv/bin/python hardware/kicad/pcb/build_display_pcb.py`
  · Windows `.venv\Scripts\python.exe hardware\kicad\pcb\build_display_pcb.py`.
  Pre-handoff gate: `python3 hardware/reviews/tools/handoff_check.py`.
- Generator: `hardware/kicad/pcb/core.py` (shared with CP3) +
  `hardware/kicad/pcb/build_display_pcb.py` (display floorplan as data).
- Decisions taken: **D39** (MOD1 courtyard implements D26; J2 side-entry).

## 2. What is materially new versus CP3

**This is the project's first board with parts on the back side**, and that
alone accounted for most of the work. CP3's battery board is all-front, so a
family of defects in the shared generator had never been reachable. Seven were
found and fixed here, each poison-tested; the approved CP3 board was
re-verified **byte-identical (`448d59a276df`)** after every one.

| # | Defect | Why CP3 could not see it |
|---|--------|--------------------------|
| 1 | `_flip_to_back()` swapped layers but never mirrored geometry — a back-side part's land pattern did not match the physical part (**fabrication-class**) | no back-side parts existed |
| 2 | The mirror was then applied about the **wrong axis** (X instead of Y) — see §4.2 for how this was settled | — |
| 3 | Writer and analytic gates used different back-side transforms, so DRC and the gates disagreed by ~5 mm | gates and writer agree trivially when nothing is flipped |
| 4 | Courtyard collision skipped opposite-side pairs entirely, but **THT pads pierce the board** and obstruct both faces | all parts on one side |
| 5 | Mounting holes were registered on one side only | same |
| 6 | `courtyard_segments()` handled only lines/rects and silently skipped every other shape — a MountingHole courtyard is a single **circle**, so holes contributed **zero geometry** while appearing to be gated | DRC happened to catch the one real hole overlap during CP3, masking it |
| 7 | Back-side refdes: inverse frame conversion mirrored the wrong axis (J1's designator landed 21 mm off its body) and the property restore was not side-aware, emitting back-side refdes onto **F.SilkS** | no back-side silk |

Defect 6 is the most instructive: the CP3 code comment asserted that mounting
holes "participate in the courtyard/outline gates like any part", and that
claim was simply false for the entire checkpoint.

## 3. Floorplan (rationale — mechanics dominate this board)

The enclosure drives everything (D8/D27): an 85 × 65 mm PCB inside a US
double-gang old-work box, behind a **pop-off faceplate that carries the
e-paper module**. Only a ~8 mm standoff gap exists on the front.

- **BACK side (faces the box floor, generous depth):** only the two parts
  that would blow the front gap — **J1** Würth RJ45 right-angle (13.6 mm,
  mating face W so the in-wall Cat5e enters from the side, §10.2 #5) and
  **U1** R-78E3.3 SIP (~11 mm), per §10.2 #4 "keep tall parts off the
  module-facing side".
- **N edge:** **J2** e-paper header, **side-entry** (D39), probed to open
  SOUTH so the cable runs over the board and rises to the module rather than
  into the ~5 mm gap between board edge and box wall.
- **Centre:** **MOD1** with the D26/D39 no-keepout courtyard.
- **W band (y 6…25):** 12 V entry chain F1 → TVS1/C1 and the RS-485 front
  end (U2, R2/R3/R4 bias+termination, J5) — placed clear of J1's
  through-board pad field, which projects to x 6.9…25.4 / y 26.5…38.2.
- **E column:** USB-C chain flowing west — J-USB → U-ESD/R_cc → U3-LDO →
  U4-MUX, with J3 ESP-Prog in the SE pocket.
- **S edge:** BTN1/2/3 at **x = 24 / 42 / 60 mm** (18 mm centres), each with
  its 1 MΩ pull-up and 100 nF debounce immediately north.

## 4. Findings made and fixed during self-review

### 4.1 Two schematic-side deltas, both evidence-forced

1. **MOD1 courtyard now implements D26.** The stock ESP32 courtyard is a
   T-shape: a 19.5 × 20.2 mm body stem plus a **48 × 21 mm flare that exists
   only to encode Espressif's antenna keepout**. D26 retired that keepout for
   this board (radio unused — RS-485 is the only link, "no RF → no keepout →
   freer layout") but the footprint never reflected it, and honouring it would
   sterilise **36 % of an 85 × 65 mm PCB** for a rule the design has dropped.
   Display-only variant `ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout`: **62/62 pads
   coordinate-identical** to the parent, sole graphic delta F.CrtYd 8 → 4
   segments. The battery board keeps the full-keepout parent (its radio IS
   used, D25).
2. **J2 is SIDE-entry (S8B-PH-K-S), not top-entry (B8B).** CP1 §4.4 deferred
   this to "CP3, from the cable-routing/depth stack" and it was never decided;
   the schematic had defaulted to top-entry. JST ePH datasheet: the top-entry
   part's **mated height is 8.0 mm** (p.1) — the entire PCB→module gap, with
   nothing left for the cable, which on a top-entry part exits vertically into
   the module. Side-entry is a 7.6 mm header whose cable exits horizontally
   (p.3). Widening the gap instead is rejected by a coupling: plunger length =
   gap + faceplate + protrusion, so 8 mm → ~13.5 mm (mid-catalog for the 6×6×N
   tactiles) but 12 mm → ~17.5 mm, at/past the catalog top end.

### 4.2 How the flip axis was settled — tool as oracle, not reasoning

My first fix mirrored **X**. That was wrong, and reasoning could not
distinguish it from mirroring Y — both are "a mirror" and both look
plausible. The decisive method: write a **stock** footprint to the back and
let KiCad judge it, since `lib_footprint_mismatch` fires when a board
footprint disagrees with its library copy.

| transform | stock back-side U1 |
|-----------|--------------------|
| no mirror | mismatch |
| mirror X (my first fix) | mismatch |
| **mirror Y** | **clean** |

Corroborated independently against a shipped KiCad demo board, whose B.Cu
footprint stores library-X with **negated Y**. Display
`lib_footprint_mismatch` fell 3 → 1 (only the vendored MOD1 variant remains,
the same kiutils-serialisation class CP3 accepted).

### 4.3 Doc corrections found before placing
- §4.6's button positions (22 / 42 / 62 mm) are **20 mm centres**, contradicting
  the same table's stated 18 mm pitch; §10.2's 24 / 42 / 60 is authoritative and
  is what is built. Corrected.
- The faceplate cutout span read "~16 mm" where 18 mm centres give **36 mm**.
  Corrected. Both swept across all doc sites.
- J1's shield: the Amphenol footprint (battery) names its shield pad `SH` and
  binds the stock symbol; the **Würth** footprint (display) names them
  `S1`/`S2`, so the netlist referenced a pad that does not exist and both real
  shield tabs were unrepresented. Renamed the vendored Würth tabs to `SH`
  (one metal shell → one node, NC here per DR-19); pad coordinates untouched.

## 5. Gate stack

All CP3 gates apply unchanged (parity, pinmap, outline, edge-marker, fab
floors, readback, DRC, label-adjacency, handoff), running inside
`BoardBuilder.write()` per CP3 F09. New this checkpoint:

| Gate | What it proves | Poisoned? |
|------|----------------|-----------|
| thru-pads | a part's through-hole pad field vs the FAR side's courtyards — THT pads pierce the board | fires on J1×U2/J5 and U1×R6 during iteration |
| courtyard (circles) | circular/poly/arc courtyards now contribute real segments | hole courtyard 0 → 24 segments; part-on-hole fires on both sides, clear placement stays clean |
| mounting holes | registered on BOTH sides | as above |

DRC final state: **0 unaccounted**. Accepted:
- `unconnected_items` ×123 — placement-only board, routing at CP5.
- `silk_edge_clearance` ×2 — J-USB's designed E-edge overhang.
- `lib_footprint_mismatch` ×1 — MOD1 vendored variant (non-geometric
  kiutils serialisation, same class as CP3 §2).

## 6. Open items for the reviewer

- **DR-35 (USB-C access) is OPEN and affects this placement.** The specified
  GCT USB4085 is an **edge** connector, but the box leaves only ~5 mm past any
  board edge while a plug needs 15–20 mm, and popping the faceplate exposes
  the board's **front**, not its edges. The user proposed a **vertical** USB-C
  hidden under the faceplate; that is now the recommended option — GCT
  **USB4120-03-C is 6.5 mm tall** (product spec p.1, on file as
  `hardware/datasheets/candidates/USB4120.pdf`), below the ~8 mm gap and below the ~9.4 mm J3 header, so it
  costs **no depth**. Board is placed as the current (edge) part pending the
  user's call; if option B is taken, J-USB's footprint, pin map and the
  E-edge overhang whitelist all change.
- ~~Per-instance evidence for the MOD1 `lib_footprint_mismatch`~~ **DONE** —
  `visual_inspections/cp4-display-placement/iter1/mod1_pad_diff.txt`: all
  **62/62 pad tuples** (number, type, shape, x, y, angle, sizeX, sizeY)
  identical between board copy and library; graphic-layer counts match
  (F.CrtYd 4, F.SilkS 8, F.Fab 6, Cmts.User 2); the entire delta is one
  `(unlocked yes)` token and the `embedded_fonts` token — kiutils
  serialisation, non-geometric. Same class and same evidence shape CP3 §2
  used for its MOD1 accept.
- ~~Depth tally re-confirmation~~ **DONE, and it moved** — see §4.4.

### 4.4 Depth stack corrected, and the button plunger resolved

CP1 §2.1 assumed an 8 mm PCB→module standoff gap. Measured from the parts
actually placed, the tallest front-side component is **J3, the Würth
61200621621 box header at 9.1 ±0.15 mm** (drawing p.1, on file) — so the gap
must be **~9.5 mm**, and the total stack **~34.5 mm** against ~45 mm usable
(~10.5 mm margin, previously quoted as ~12 mm). `cp1_display_side.md §2.1`
updated with the correction and its source.

That closes a CP1 defer. Plunger length = gap + faceplate + protrusion =
9.5 + 3 + 2.5 = **15 mm**, which is a real catalog height, so BTN1–3 are no
longer `_verify_`: **Same Sky TS02-66-150-BK-160-SCR-D** (datasheet fetched
from the manufacturer — Mouser's mirror WAF-serves HTML, the same trap as
the GCT drawing at CP3; manifest row added). Checks performed:
- `150` = 15.0 mm actuator, and it is **not** one of the starred heights the
  part-number key restricts to long-crimped terminals, so `SCR` is valid;
- datasheet p.2 recommended land pattern **6.5 × 4.5 mm, 4 × drill 1.0**
  versus the stock `SW_PUSH_6mm_H13mm` footprint's pads — **exact match**
  (verified, not assumed — the DR-33 lesson);
- ratings 12 Vdc / 50 mA, −30…+80 °C, 80,000 cycles at 160 gf — the 3V3
  button-to-GND use is far inside all three.

**Push force (160 gf) is an engineering pick, not a derived value.** 100 and
260 gf are drop-in siblings; if the button feel wants changing it costs only
a part-number character. Flagged for the user rather than presented as
settled.

Heights still carried from earlier work and **not** re-sourced this
checkpoint: J-USB (~3.2 mm), MOD1 (~3.1 mm), F1/J5 (~3–4 mm). None is within
6 mm of the 9.1 mm driver, so none can change the gap; they would need a
datasheet pass only if the stack is ever re-cut around a different tall part.

## 7. D13 scorecard

Deferred to iteration 2 — this packet is the first hand-off of a board whose
generator changed materially underneath it, and the reviewer's independent
rebuild is the more valuable first check.
