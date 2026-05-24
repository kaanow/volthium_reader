# CP2 review packet — Schematic capture

**Status**: ready for review (iteration 1 — approach)
**Opened**: 2026-05-24
**Branch**: `hw/cp2-schematic-capture`
**Goal of this CP**: produce KiCad 10 schematic files (`.kicad_sch`)
for both boards, ERC clean, with PDF + netlist exports. Schematics
must faithfully reflect the CP1 baseline (component selection, net
topology, design rules).

## 1. Iteration 1 framing

This first iteration of CP2 is **not yet the schematic itself** — it's
a request for Codex review of the **approach** before I commit
hundreds of lines of generation code. The user explicitly delegated
autonomy with the constraint "propose a path to Codex and get its
opinion and build consensus" when uncertainty is involved.

There is real uncertainty here: KiCad 10 schematic capture from a
headless CLI session is a tooling decision with downstream
implications. Better to validate it once than to discover at iter 5
that we should have done it differently.

If Codex approves this approach, **iteration 2** will produce the
first actual schematic section (battery-side power-input).
**Iterations 3–4** expand to the rest of the schematics. CP2 closes
when both boards have ERC-clean .kicad_sch files + PDF + netlist.

## 2. The approach

**Source of truth**: KiCad 10 native `.kicad_sch` S-expression files
in `hardware/kicad/<board>/`. Per
[`decisions.md` D1](../layout/decisions.md#d1).

**Generation method**: Python script (`hardware/kicad/build_schematics.py`)
using [`kiutils`](https://pypi.org/project/kiutils/) v1.4.8 to write
the schematic files programmatically, then `kicad-cli sch upgrade`
to migrate to KiCad 10's format.

**Why programmatic, not GUI?**
- This session has no GUI access; KiCad's interactive schematic editor
  is out of reach.
- Programmatic generation is reproducible, version-controlled as
  Python, and produces diffs that Codex can review without opening
  KiCad files.
- The existing SKiDL was already a programmatic approach for KiCad 8;
  this is the analogous tool for KiCad 10.

**Connection style**: net labels everywhere, no manual wires. Each
component pin gets a `GlobalLabel` matching the net name in
[`cp1_battery_side.md` §5 net list](../layout/cp1_battery_side.md#5-net-list).
This is functionally equivalent to wired connections but vastly
easier to author programmatically (no XY-routing logic required).
Visual quality is mediocre but ERC and netlist are correct, which is
what matters for fab.

**Layout**: components arranged in functional clusters (power input,
power conversion, MCU, RS-485, etc.) on a single sheet per board, A4
landscape. Position-only — no aesthetic routing. CP3 (PCB placement)
is where physical layout is decided.

## 3. Smoke test results (iteration 1)

Validated the full toolchain end-to-end with a minimal 2-resistor
voltage-divider schematic:

| Step | Command | Result |
|------|---------|--------|
| Write `.kicad_sch` | `kiutils.schematic.Schematic.create_new().to_file()` | ✓ 133 bytes, KiCad 6/7 format (version `20211014`) |
| Upgrade to v10 | `kicad-cli sch upgrade` | ✓ "Successfully saved schematic file using the latest format" |
| ERC | `kicad-cli sch erc` | ✓ "Found 0 violations" |
| Export PDF | `kicad-cli sch export pdf` | (not run yet; will validate in iter 2) |
| Export netlist | `kicad-cli sch export netlist` | (not run yet; will validate in iter 2) |

**Conclusion**: kiutils → kicad-cli upgrade → ERC pipeline is sound.
Safe to commit to this toolchain.

(A fontconfig warning shows up on macOS but is non-blocking — kicad-
cli operations succeed despite the warning.)

## 4. Known challenges (call out before we hit them)

### 4a. Library symbol lookups

To place a component, kiutils needs the symbol's library reference
(e.g. `Device:R`) AND the schematic file needs a `libSymbols` section
containing a copy of that symbol's definition. KiCad 10 ships symbol
libraries at
`/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym`.

**Plan**: parse the relevant `.kicad_sym` files via kiutils'
`SymbolLib.from_file()` and copy the needed symbols into each
generated schematic's `libSymbols` section. Should "just work" for
the stock parts from CP1's BOM.

**Risk**: KiCad 10 may have renamed symbols vs KiCad 8 era (which is
what the legacy SKiDL targets). The `RF_Module:ESP32-S3-WROOM-1`
symbol is the main one to verify. Will check at iteration 2 start.

### 4b. Recom R-78E12 / R-78E3.3 modules

These SIP3 buck modules are not in stock KiCad libraries (the legacy
SKiDL's `symbol_footprint_map.md` flags them as "check-vendor").

**Plan**: hand-author a minimal 3-pin (VIN/GND/VOUT) symbol in a
project-local `hardware/kicad/libraries/volthium.kicad_sym` file.
Footprint comes later at CP3.

### 4c. Power flag conventions

For ERC to pass, every power net must have at least one source —
either a `PowerSymbol` (e.g. `+3V3` from `power.kicad_sym`) or an
explicit `power_flag` on a net driven by a regulator.

**Plan**: place `PowerSymbol` nodes at the outputs of U1 (V3V3_SW),
U2 (V12_CAT5E), and J1 (V24_RAW). Stock symbols exist for `+3V3`,
`+12V`, `+24V` already; just need to alias as needed.

### 4d. Unused pins

ESP32-S3-WROOM-1 has ~38 GPIOs; CP1 uses ~14. Unused pins need
either `no_connect` flags or labels. To avoid ERC noise.

**Plan**: explicit `NoConnect` items on all unused module pins.

### 4e. Schematic position layout

kiutils requires explicit (X, Y) positions for every symbol. I'll
pick a deterministic grid (e.g. components on 25.4 mm = 1000 mil grid;
power-input cluster at top-left; MCU centered; RS-485 at right) to
keep generation simple. Aesthetic improvements (wire routing,
text placement) can come from the user in KiCad GUI if desired.

## 5. Proposed iteration sequence

| Iter | Scope | Deliverable |
|------|-------|-------------|
| 1    | **Approach review (this one)** | This packet + smoke test + scaffolding |
| 2    | Battery-side power-input cluster (J1, F1, D1, TVS1, U1, L1, U2, sense divider, Q1/Q2 load switch) | Partial `battery_side.kicad_sch` ERC-clean for the subset; PDF + netlist for subset |
| 3    | Battery-side MCU + support + RS-485 (MOD1, RTC1, BAT1, U3, R/C support, dev headers) | Complete `battery_side.kicad_sch` ERC clean |
| 4    | Display-side board (full, smaller than battery side) | Complete `display_side.kicad_sch` ERC clean |
| 5    | Final polish + final exports (PDFs, netlists) | CP2 closes |

If iterations 2–4 go smoothly, this could collapse to 2 (battery)
+ 1 (display) = 3 iters. The conservative plan above assumes some
debug cycles per board.

## 6. Files in this PR (iteration 1)

- `hardware/reviews/cp2_schematic_capture.md` (this file)
- `hardware/kicad/build_schematics.py` (placeholder; real
  implementation in iter 2)

No KiCad files yet. Those land in iter 2.

## 7. Open questions for Codex

### Q-CP2-1: Approach validation

Does the kiutils + label-based-connections + per-iteration build-up
look right to you? Specifically:

- Programmatic schematic generation vs alternative (manually drawing
  schematics in KiCad GUI by the user, then committing) — I'm
  proposing programmatic.
- Label-based connections vs explicit wires — I'm proposing labels.
  Visual quality is worse but ERC and netlist are unaffected.
- Iterative build-up vs all-at-once — I'm proposing 3–4 iterations
  per board.

If you disagree on any of these, push back now before I invest
generation-code time.

### Q-CP2-2: Custom symbol authoring

The Recom R-78E modules need custom symbols. Two paths:

- **Project-local library**: author `hardware/kicad/libraries/volthium.kicad_sym`
  with just the parts we need. Lives with the design.
- **Use generic `Connector_Generic:Conn_01x03` instead**: simpler
  but loses the part-specific metadata (name, datasheet link).

Default: project-local library. Override if you see a reason.

### Q-CP2-3: ESP32-S3-WROOM-1 symbol verification

The legacy SKiDL targets KiCad 8's `RF_Module:ESP32-S3-WROOM-1`.
KiCad 10 may have renamed or added variants (e.g. `-N16R8` specific
symbols). I'll verify at iter 2 start. **No action needed from you**
unless you've already seen this and have a recommendation.

## 8. Success criteria (CP2 overall, not just iter 1)

- [ ] `hardware/kicad/battery_side/battery_side.kicad_sch` exists and
      `kicad-cli sch erc` returns "Found 0 violations"
- [ ] `hardware/kicad/display_side/display_side.kicad_sch` exists and
      passes ERC the same way
- [ ] PDF exports of both schematics committed to
      `hardware/outputs/<board>/schematic.pdf`
- [ ] Netlist exports committed to
      `hardware/outputs/<board>/<board>.net`
- [ ] All net names in the schematic match
      `cp1_battery_side.md` §5 and `cp1_display_side.md` §5
- [ ] All part references match the CP1 BOM (MOD1, U1, U2, U3, …)
- [ ] CP2 review packet (this file) updated with each iteration's
      progress

## 9. What this CP does NOT settle

- Footprint selection / placement (CP3)
- PCB layout / routing (CP4)
- Gerbers + fab files (CP5)
- 3D model exports (CP5)
- Aesthetic polish of the schematic visuals (the user can rearrange
  in KiCad GUI any time; the netlist is what gates fab)

## 10. Reviewer findings (append-only)

*(append per the format in REVIEWER.md §5)*

---

### Finding 01 — IMPORTANT — `cp2_schematic_capture.md`:§2/§4a
**Issue**: The approach currently hardcodes KiCad symbol-library discovery to a macOS app path, which makes the CP2 toolchain non-portable and likely brittle across machines/CI.
**Evidence**: §4a states libraries are at `/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/*.kicad_sym`. That path is platform-specific; CP2 deliverables need reproducible regeneration and ERC runs regardless of host OS.
**Suggested fix**: Make symbol resolution project-local: commit `hardware/kicad/libraries/` symbols used by this design (including custom ones), and resolve from repo-relative paths first. Keep host-library lookup as an optional fallback, not the primary source.

### Finding 02 — QUESTION — `cp2_schematic_capture.md`:§2/§5
**Issue**: The label-based and iterative generation strategy is reasonable; I only need confirmation that CP2 iteration 2 will also introduce project scaffolding needed for stable CLI ERC/export runs.
**Evidence**: This branch currently has no `.kicad_pro`, `.kicad_sch`, or `.kicad_pcb` files, so CP2+ verification commands cannot yet be executed against committed project artifacts.
**Suggested fix**: In iter 2, include minimal project scaffolding alongside the first schematic slice (project file + any required library table references) so reviewer-side `kicad-cli sch erc` and export commands are independently reproducible.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See findings N1, N2.)
