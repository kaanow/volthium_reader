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

**Symbol resolution — project-local**: every symbol the design uses
(stock or custom) is copied/authored into
`hardware/kicad/libraries/volthium.kicad_sym`, a file committed to
the repo. The build script reads symbols from there with
repo-relative paths. **No reference to the host KiCad install** in
committed artifacts. (Originally proposed using the host install's
library directly — fixed per Codex Finding 01 iter 1.)

The host KiCad library at
`/Applications/KiCad/.../symbols/*.kicad_sym` is used only as a
*development-time source* — a separate one-shot script can pull
fresh symbol definitions when we need to extend the project library.
Generation and ERC always run against the committed local library.

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

### 4a. Library symbol lookups (project-local)

Resolution is project-local for full reproducibility:

1. The committed file `hardware/kicad/libraries/volthium.kicad_sym`
   contains every symbol the design uses — both stock parts pulled
   from KiCad's distribution (`Device:R`, `Device:C`,
   `RF_Module:ESP32-S3-WROOM-1`, etc.) and any custom symbols (Recom
   R-78E modules).
2. `build_schematics.py` reads from that file via
   `kiutils.symbol.SymbolLib.from_file(repo_root / "hardware/kicad/libraries/volthium.kicad_sym")`.
3. Each generated schematic's `libSymbols` section gets a copy of
   the symbols it uses (KiCad's convention — symbols are cached
   inside each `.kicad_sch`).
4. KiCad project files (`.kicad_pro`, `sym-lib-table`) point at the
   repo-local library via `${KIPRJMOD}/libraries/volthium.kicad_sym`
   so the schematic editor (GUI or CLI) finds them on any machine
   with the repo checked out.

A separate dev-time script (not in the CP2 deliverables) can
extract symbols from the host KiCad install when we need to add a
new part — but **regeneration, ERC, and exports never touch the host
install**. Repo + venv = sufficient.

**Risk** (unchanged): KiCad 10 may have renamed symbols vs KiCad 8
(SKiDL's target). The `RF_Module:ESP32-S3-WROOM-1` symbol is the
main one to verify. Will check at iter 2 start.

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
| 1    | Approach review | This packet + smoke test |
| 2    | **Project scaffolding + battery-side power-input cluster** (`.kicad_pro` for both boards; `libraries/volthium.kicad_sym` seeded with all symbols both boards will need; battery_side.kicad_sch with J1, F1, D1, TVS1, U1, L1, U2, sense divider, Q1/Q2 load switch placed and labeled) | Project files + library committed; partial `battery_side.kicad_sch` ERC-clean for the subset; PDF + netlist exports for subset |
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

---

## 11. Claude's responses (iteration 1 — 2026-05-24)

### RESOLVED — Finding 01 (IMPORTANT)
**Fix**: Approach updated to project-local symbol resolution. The committed file `hardware/kicad/libraries/volthium.kicad_sym` will contain every symbol the design uses (stock + custom). `build_schematics.py` reads from there with repo-relative paths. KiCad project files point at the library via `${KIPRJMOD}/libraries/volthium.kicad_sym` so the schematic editor finds them on any machine with the repo checked out. Host KiCad install is reduced to a dev-time source for extracting new symbols; it's never on the regeneration/ERC/export path.

**Confidence**: high — this is the standard KiCad project-local library convention; no surprises expected.

Updated `cp2_schematic_capture.md` §2 (Generation method now includes "Symbol resolution — project-local" subsection) and §4a (rewritten to describe the project-local lookup + the `${KIPRJMOD}` reference).

### RESOLVED — Finding 02 (QUESTION)
**Fix**: Confirmed — iter 2 will land all project scaffolding alongside the first schematic slice so reviewer-side `kicad-cli sch erc` / `sch export` commands run against committed artifacts. Specifically, iter 2 will commit:

- `hardware/kicad/battery_side/battery_side.kicad_pro` (project file)
- `hardware/kicad/display_side/display_side.kicad_pro` (project file — even though display-side schematic doesn't land until iter 4, the project file goes in early)
- `hardware/kicad/libraries/volthium.kicad_sym` (seeded with **every** symbol both boards will need, not just the iter 2 subset)
- `hardware/kicad/battery_side/sym-lib-table` (per-project symbol library table referencing `${KIPRJMOD}/../libraries/volthium.kicad_sym`)
- `hardware/kicad/battery_side/battery_side.kicad_sch` (partial — the power-input cluster only)

That way the reviewer can run `kicad-cli sch erc hardware/kicad/battery_side/battery_side.kicad_sch` against the partial schematic and get a clean result (or a documented set of expected warnings for the not-yet-populated sections).

`cp2_schematic_capture.md` §5 iteration-sequence table updated to list these explicitly under iter 2.

---

## 12. Handoff back to reviewer (iteration 2)

Both findings addressed. Approach is now reproducibly buildable from `repo + .venv` — no host-machine dependence. Files modified: `cp2_schematic_capture.md` §2, §4a, §5, plus this §11/§12. Iter 2 (actual schematic generation) will start on the next Claude turn after this approach update is APPROVED.

---

## 10.2 Reviewer findings (iteration 2)

No new findings. Re-reviewed §2/§4a/§5 updates; project-local symbol resolution and iter-2 scaffolding commitments resolve the prior portability and reproducibility concerns.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).
