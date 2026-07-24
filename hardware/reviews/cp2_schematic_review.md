# CP2 review packet — battery-side schematic (hw/cp2-schematic)

> **For agent-reviewer.** Skill: `pcb-design-review` **v1.2.0** (the user
> hands it to you — note the NEW §3 rebuild-first precondition and gates
> **G8** (wiring read-back) / **G9** (independent-geometry second opinion);
> they were written from this CP's failure history and are expected to be
> exercised here). Scope: the **battery-side** 9-sheet schematic at CP2.
> Display-side CP2 has not started.

## 1. What you are reviewing

- Branch: `hw/cp2-schematic` (pull first — you run from a separate clone).
- Source of truth: `hardware/kicad/schematic/build.py` (code-generated
  KiCad 10). **Rebuild before reviewing anything**:
  `cd hardware/kicad/schematic && <repo>/.venv/bin/python build.py`
  — gate-failed sheets are never written, so unbuilt artifacts can be stale.
- Artifacts (after rebuild): `build/volthium_reader.pdf` (9 pages),
  `build/volthium_reader.net` (exported netlist = connectivity ground truth),
  per-sheet `.kicad_sch/.png`.
- Canonical BOM: `hardware/layout/cp1_bom.md`. Requirements:
  `hardware/layout/requirements.md` (R1–R16). Decisions: `decisions.md`;
  review items: `DESIGN_REVIEW_ITEMS.md` (DR-26, DR-30, DR-31, DR-32 are
  this CP's core). Bring-up: `docs/hardware/bringup_guide.md`.

## 2. Scope delta since the CP1 sign-off

1. Full battery-side schematic captured: power path, supervisor, USB
   maintenance, MCU, peripherals (display RS-485 + RTC + **Xanbus CAN**),
   2× isolated RS-485 battery-read channels, connectors.
2. **DR-31 Xanbus CAN read** (user-approved requirements change): TCAN332DR,
   power-gated (CAN_PWR), termination through J7 jumper, CAN_L=4/CAN_H=5 per
   LYNK II 805-0052 §4.2.1, NET-power pins NC. Datasheet on file.
3. **DR-32 programming/bring-up**: J5 grew to 6-pin exact ESP-Prog order
   (EN/VDD/TXD/RXD/IO0/GND); IO0 strap wired as BOOT.
4. Iso sheets redrawn as signal flow (wires-first, drawn isolation barrier,
   boxed DNP annex) — connectivity held identical through the redraw.
5. Requirements register + mechanical compliance runner
   (`hardware/tools/check_requirements.py`, 29/29 PASS, poison-tested).

## 3. Evidence on record (verify, don't inherit)

- Build gate suite green: readability/glyph/title-block gates ×8 sheets;
  netlist intent==actual; **GOLDEN table** (~150 doc-derived connectivity
  contracts in build.py) clean; `[part-short]` rule clean; footprint
  existence+normalization enforced in `place()`; ERC dangling 0 /
  power-pin 0.
- Independent audits clean: `hardware/reviews/tools/label_body_audit.py`
  (0 findings ×8), `doc_consistency_check.py` (clean),
  `check_requirements.py` (29/29).
- Known gate-history this CP (why G8/G9 exist): a consistent-but-wrong
  power gate (Q5 S/D swap) passed every mechanical diff and was caught only
  by wiring read-back; the "dangling=19 ERC baseline" turned out to be real
  broken nets from missing root-uuid instance paths; six phantom footprints
  shipped past a claimed footprint check. All fixed + regression-proven —
  but treat every green gate as a claim to spot-audit, not a fact.

## 4. Reviewer asks (beyond your standard gates)

1. **G8 read-back on the four power gates** (Q10/Q11/Q5/Q_exp) and both
   comms polarities (Xanbus 4/5, battery RJ45 7/8, Cat5e 4/5) — from the
   exported netlist, against decisions/DR/vendor docs.
2. **Poison-test one golden and one requirements check** yourself.
3. Engineering pass per ENGINEERING_REVIEW.md (D17) on the NEW blocks:
   CAN (TCAN332 bias/termination/CM budget), J5/boot strapping (IO0 net
   effects at boot), the iso-sheet redraw (fig-35 fidelity: bead placement,
   cap-on-which-side-of-bead, C_stitch return).
4. Challenge premises, not just math: LYNK-II-derived Xanbus pinout
   (third-party doc — is the inference sound?), C_stitch functional-vs-
   safety call (DR-30, user-decided), bead impedance open item (DS p.17
   ~2 kΩ vs 600 Ω pick — DR-30).

## 5. Open items already known (don't re-find them)

- DR-26 §7 two-domain bench test — gates iso population (CP5).
- Bead impedance verification at BOM-lock (DR-30, logged 2026-07-23).
- 40 BOM cells at `_verify_` — pre-BOM-lock by process (D32 applies when
  MPNs are chosen).
- Bench-class requirement rows (R1/R5/R7/R10/R12 [B] parts) — CP5, staged
  in the bring-up guide.

## 6. Findings protocol

Per SOP/REVIEWER.md: numbered findings (continue the F-series), each with
severity, evidence, and the exact artifact+line; flip the semaphore to
`claude_turn` when your pass is written.
