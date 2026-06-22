# CP1 review packet — Design baseline

**Status**: RE-OPENED 2026-06-17 (D18) — engineering-correctness pass ready for review
**Originally opened**: 2026-05-23
**Reviewer**: agent-reviewer (re-derive independently per ENGINEERING_REVIEW.md / D17)
**Branch**: `hw/cp1-architecture`
**Goal of this CP**: confirm the design is right *before* we draw it in
KiCad. Catch anything that's wrong, missing, or open-ended now — fixing
it later costs much more.

---

## 0. CP1 RE-OPEN (D18/D19) — engineering-correctness pass

**Why re-opened.** The project nominally reached "CP6 fab-ready," but
DR-1/DR-2 proved the input-protection defects were *CP1/CP2 architecture
decisions* that every automated gate (ERC/DRC/readability) passed. D17
added a first-principles **engineering-correctness gate**; D18 re-opened
CP1 to run it across the whole design with that gate now in place, and
superseded all board artifacts (placement/routing/fab) pending schematic
re-validation. This section is the result of that pass.

**Method.** Clean-sheet re-derivation per domain
([`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md)): power input, regulation,
comms, MCU, sensing, connectors — measuring the existing design against an
independently-derived textbook circuit as a *candidate*, not a baseline.

**Findings (logged in [`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md)):**

| # | Defect (every automated gate passed it) | Resolution |
|---|------------------------------------------|------------------|
| **DR-4** | **Board could not boot.** U1 (3V3 MCU regulator) sat on the hard-cut rail (V24_SW) downstream of a default-OFF load switch — the MCU that must close the switch was itself unpowered. Also: Q1 Vgs driven to −29 V (vs ±12 V rating); no wake path if MCU fully cut. | (D19) MCU + U1 move to an **always-on** rail. Q1 sheds **only the display feed**. Gate-source Zener clamp + 60 V FETs. ESP self-supervises (deep-sleep), ~1 mW at hard-cut. |
| **DR-3** | **Surge clamp only half-coordinated.** DR-2 raised U1 to 72 V but left U2 (R-78E12, ~34 V) and the load FET (30 V) behind the ~53 V TVS clamp. | (D19) U2 → R-78HB12 (72 V); Q1/Q2 → 60 V; D1 → 60 V Schottky. Whole protected rail now out-rates the clamp. |
| **DR-4b** | **RS-485 idle bias would become an always-on leak.** With the 3V3 rail now always-on, battery-side bias (~2.3 mA) draws continuously → ~8 mW, ~8× the hard-cut budget. | Fail-safe bias moves to the **display end only**, ~390 Ω (236 mV idle > 200 mV). Battery always-on rail draws **zero** RS-485 static current. |
| **DR-6** | **Sense divider in the ADC's nonlinear region.** 1 MΩ/110 kΩ put full charge at ~2.9 V — the ESP32-S3 ADC compresses above ~2.45 V, so SOC reads worst exactly at full charge. | Re-ratio **1.2 MΩ/100 kΩ** → full charge 2.25 V (linear band). Surge is current-limited by the 1.2 MΩ top to ~41 µA — no added clamp. |
| **DR-7** | **E-paper: wrong connector + missing driver support.** J2 was a 24-pin bare-panel FFC with a placeholder pinout and pins 11–24 "NC"; a bare panel needs an on-board booster network the schematic lacks — but the circuit (and BOM intent) is the 8-pin Waveshare Module (B). | Commit to the **Module (B)**; J2 → **8-pin 2.54 mm header** (VCC/GND/DIN/CLK/CS/DC/RST/BUSY). Drops the FFC, 16 NC pins, the missing-booster risk, and the open "verify FFC pinout" item. |
| **DR-5** | Baseline docs (BOM/power-budget/block-diagram + stale fab CSV) described the pre-DR design. | All reconciled to D19/DR-6/DR-7 in this pass. |

**Hard-cut behavior (user decision 2026-06-17): "Option 1 done right".**
At < 10 % SOC the ESP deep-sleeps on the always-on rail (~µA), periodically
reads V24_SENSE, and sheds the display via Q1. It is its own supervisor —
no separate supervisor IC. All-in trickle ≈ **~1 mW** (U1 Iq ~10.5 µA +
sense divider ~19 µA).

**Verified parts (specs + DigiKey stock/lifecycle checked 2026-06-17;
final confirmation still at BOM-lock per D-OPEN-6):**
- **U1 LM5165YDRCR** — 3–65 V in, **10.5 µA Iq**, 150 mA, **fixed 3.3 V** (FB→VOUT, no divider). In stock @ DigiKey, Active. Both surge-tolerant and µA-Iq (a brick can't be both). *The stock check first flagged that the adjustable DRCR I'd picked would need an FB divider — resolved by switching to the fixed-3.3 V "Y" variant (same package), not by adding the divider.*
- **U2 R-78HB12-0.5** — 17–72 V in, 12 V/0.5 A. In stock @ DigiKey, Active.
- **Q1 ZXMP6A13F** — −60 V, **0.9 A**, SOT-23-3 (clean 3-pin; the ZXMP6A17 is only SOT-23-6/SOT-223). In stock @ DigiKey, Active. 0.9 A ≫ the ~0.3 A display feed.
- **D1 SS26** (60 V), **Q2 2N7002** (60 V), **DZ1 BZX84C12** (12 V Zener) — ubiquitous jellybeans.

Availability was checked *at selection time* (not deferred to BOM-lock) per
the principle now in ENGINEERING_REVIEW.md step 3 — and the right response
to the adjustable-vs-fixed mismatch was to **pick the fixed-output variant**
(LM5165YDRCR), not to bolt an FB divider onto the adjustable one. Replace
the misfit part; don't patch around it.

**Pre-handoff excellence pass (2026-06-18).** Before review, the sensing
path and the display side got a second, deeper look — which surfaced
**DR-6** (sense divider) and **DR-7** (e-paper), both now resolved above.
The display board was given the same first-principles rigor as the battery
side: PTC vs e-paper load (0.5 A hold ≫ ~40 mA — fine), R-78E3.3
coordination (SMAJ15A ~24 V clamp < R-78E3.3 ~28–30 V max — sound, DR-1),
RS-485 ESD on the cabled lines (TVS2/TVS1 — fine), decoupling, buttons.

**Domains that cleared** with only minor notes: comms (term + single
display-end bias, coordinated), MCU (decoupling, EN RC soft-start, straps
on internal defaults — fine for flash boot), connectors (Phoenix + RJ45
ratings ample). The remaining open items are human-decision, not defects:
the ESP module variant (-N16R8 vs -N8) and final BOM-lock SKU checks.

**Design-discussion decisions (D20–D25, + DR-8), 2026-06-18.** A working
session added/changed, all captured in [`decisions.md`](../layout/decisions.md)
and reflected in the per-board docs + BOM: **D20** enclosure → user-3D-printed
plastic IP5x, board outline deferred to placement; **D21** battery antenna →
WROOM-1 `-1` PCB antenna (batteries verified ABS-plastic — no metal-detune
concern); **D22** maintenance port → board-edge USB-C on native USB (+ a USB
ESD array); **D23** RTC → RV-3028-C7 (45 nA) + small trickle-charged backup
cap, replacing the DS3231 (**DR-8**: the DS3231 was a ~0.5 mW always-on load
the budget had missed); **D24** e-paper tri-color retained, cold limit
(0–40 °C) accepted; **D25** battery-side duty-cycled **WiFi** log-push, with
**U1 LM5165→LM5166** (500 mA, same µA-Iq family) to feed a WiFi session
(a cap can't bridge a multi-second connect/upload). Hard-cut stays ~1 mW.

**Display-side clean-sheet review (D26/D27 + DR-9/10/11), 2026-06-18.** The
display board got the same domain-complete pass, now exercising mechanical/
serviceability: **D26** radio unused (RS-485 link) → keep the WROOM-1 for
commonality, RF disabled, antenna keepout dropped; **D27 / DR-9** add a
bottom-edge USB-C maintenance port (+ USB ESD) since it's wall-mounted;
**DR-10** (mechanical) the shallow double-gang box drives a right-angle
RJ45, the e-paper module mounting to the oversized custom faceplate (it
won't fit inside the box), a depth-stack budget, and the PCB-STEP-as-
contract; **DR-11** PTC tightened 0.5 A → ~0.25 A. Electrical otherwise
clean. (Also caught + fixed a stale single-gang-plate BOM row — the
display is double-gang.)

**Acceptance for this pass.** Architecture re-derived and corrected
(D19); all baseline docs reconciled; candidate parts verified. The CP2
schematic implementation (the D19 power tree in `build_schematics.py` +
ERC + readability audits) is the next checkpoint, **not** part of CP1.

---

## 1. CP1 deliverables (work products)

- **This packet** — `cp1_design_baseline.md` (§0 above is the live review content).
- **Decisions** — [`decisions.md`](../layout/decisions.md): D18 (re-open), D19 (battery power re-architecture).
- **Per-board baselines** — [`cp1_battery_side.md`](../layout/cp1_battery_side.md), [`cp1_display_side.md`](../layout/cp1_display_side.md).
- **BOM** — [`cp1_bom.md`](../layout/cp1_bom.md) (CP1 snapshot) / [`bom.md`](../../docs/hardware/bom.md) (published).
- **Engineering review** — [`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md) (method), [`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md) (DR-1…DR-5).
- **Supporting architecture** — [`block_diagrams.md`](../../docs/hardware/block_diagrams.md), [`power_budget.md`](../../docs/hardware/power_budget.md) (reconciled to D19).

## 2. How to review

1. [`decisions.md`](../layout/decisions.md) D18/D19 — the re-open and the corrected power architecture.
2. [`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md) DR-3/DR-4/DR-5 — re-derive each independently (D17); a designer "PASS" is not evidence.
3. [`cp1_battery_side.md`](../layout/cp1_battery_side.md) §3 (power tree), §5 (nets), §8 (load switch) — confirm the bootstrap/clamp/Vgs fixes and that nothing else on the protected rail under-rates the ~53 V clamp.
4. [`cp1_display_side.md`](../layout/cp1_display_side.md) §4.5 — the relocated RS-485 bias.

## 3. Success criteria (this pass)

- [ ] D18/D19 sound; DR-3/4/5 independently re-derived and agreed.
- [ ] No part on V24_FUSED/V24_SW under-rates the ~53 V clamp; no continuous draw violates the ~1 mW hard-cut budget.
- [ ] Baseline docs internally consistent (one part set, no stale refs).
- [ ] No new design question survives a careful read.

## 4. Out of scope (later checkpoints)

KiCad schematic capture + ERC + readability audits (CP2); placement (CP3/CP4); routing + DRC (CP5); fab (CP6). Final distributor-SKU verification at BOM-lock (D-OPEN-6).

## 5. Designer's request to the reviewer — single thorough pass

> **Scope note:** §2–§3 above were written at the D18/D19 re-open and name
> only those decisions. The actual CP1 scope is **D18–D27** and
> **DR-1…DR-11** (all DR currently RESOLVED). Treat this §5 as the priority
> steer; re-derive, don't trust the RESOLVED tags.

**Process this round.** Make **one** pass, as deep as you can — we're
deliberately slowing the automation down. When done, write findings into a
new §8 here and hand back to the **user** (`state: user_turn`), *not* to me.
A human reads your pass before I respond; no auto ping-pong this round.

**1 — The thing I most want: independently re-derive the power-tree
protection coordination (D19).** Don't audit my conclusion — redo the
arithmetic from the part datasheets. The defect that reached CP6 last round
(DR-1/DR-2) was exactly this class: ERC-clean and readable, but a protective
part out-rated by what it protects. I re-architected it, but I'm the same
eyes that missed it the first time, so a from-scratch derivation by a second
agent is the highest-value check here.
Take the worst-case voltage V24_FUSED reaches when the **SMAJ33CA** conducts
at the surge current a 1 A-fused 24 V input can deliver (use the TVS
clamp-V-vs-current curve, not the nominal standoff), and confirm **every**
part on that node survives with margin: D1 **SS26** (60 V), Q1 **ZXMP6A13F**
(Vds −60 V), Q2 **2N7002** (60 V), U1 **LM5166** VIN abs-max, U2 **R-78HB12**
(72 V), and the bulk caps (rated ≥ clamp?). Then the gate-clamp path:
**BZX84C12** holding Q1 |Vgs| inside rating across the **full** bus range
(cold-charge ~29 V up through the clamp), not just nominal. Flag any thin
margin or any place my assumed clamp voltage isn't supported by the curve at
the real fault current.

**2 — Are the parts real and the right variant?** Independently confirm
(datasheet + a quick stock/lifecycle check) each active part exists in the
named package/variant and isn't NRND/obsolete: LM5166 — and **resolve the
open question**: is a fixed-3.3 V variant actually orderable, or are we
committed to adjustable + FB divider? — RV-3028-C7, ZXMP6A13F, R-78HB12-0.5,
the right-angle RJ45, and the 8-pin Waveshare 4.2" Module (B). Last round I
carried a phantom Hammond PN to CP6; a second sourcing pass catches that
early.

**3 — Find the domain I skipped.** Don't just confirm my
electrical/mechanical/thermal/serviceability bullets — actively hunt for the
domain or failure mode I missed. Two I'd specifically value:
- **Thermal:** both regulators at worst case, no heatsink — LM5166 (24→3.3 V)
  and R-78HB12 (24→12 V into the display load) — against package θJA. Either
  marginal?
- **Display mechanical depth:** does the real stack (e-paper module +
  right-angle RJ45 + PCB + standoffs) fit the shallow recessed double-gang
  box (~45 mm)? I asserted the fit; I never dimensioned it.

**4 — The sense/ADC subtlety (DR-6).** Re-derive 1.2 MΩ/100 kΩ: 29.2 V →
2.25 V. Confirm that lands in the ESP32-S3 ADC's actual usable linear band,
**and** that a 1.2 MΩ source impedance is acceptable for the S3's
sample-and-hold (high divider impedance can cause settling/gain error unless
buffered or the sample window is widened). That second part is what I'm least
sure of.

**5 — Internal consistency.** D18–D27 and DR-1…DR-11 — do any two contradict,
and does the BOM match the decisions?

**Please skip:** readability / D11 / D13 schematic-geometry audits (no
schematic yet — that's CP2), and re-auditing staleness (I just ran a clean
mechanical sweep; only flag a *new* contradiction).

**Form of findings.** For anything you'd block on, give the concrete number
or calculation — the datasheet value, the computed margin — not just the
concern, so a human can act in one pass without a clarification round. Tag
each finding **blocker / should-fix / nit**.

---

*The original May-2026 CP1 packet (its "what changed" enumeration, open-decision tables, and the agent-reviewer Finding 01–05 review) is preserved in git history. It was superseded by the D18/D19 re-open: its headline blocker — the hard-cut topology inconsistency — is exactly what D19 resolves.*
