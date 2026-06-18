# CP1 review packet — Design baseline

**Status**: RE-OPENED 2026-06-17 (D18) — engineering-correctness pass ready for review
**Originally opened**: 2026-05-23
**Reviewer**: codex (re-derive independently per ENGINEERING_REVIEW.md / D17)
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

**Findings (all in the battery-side power domain; logged in
[`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md)):**

| # | Defect (every automated gate passed it) | Resolution (D19) |
|---|------------------------------------------|------------------|
| **DR-4** | **Board could not boot.** U1 (3V3 MCU regulator) sat on the hard-cut rail (V24_SW) downstream of a default-OFF load switch — the MCU that must close the switch was itself unpowered. Also: Q1 Vgs driven to −29 V (vs ±12 V rating); no wake path if MCU fully cut. | MCU + U1 move to an **always-on** rail. Q1 sheds **only the display feed**. Gate-source Zener clamp + 60 V FETs. ESP self-supervises (deep-sleep), ~1 mW at hard-cut. |
| **DR-3** | **Surge clamp only half-coordinated.** DR-2 raised U1 to 72 V but left U2 (R-78E12, ~34 V) and the load FET (30 V) behind the ~53 V TVS clamp. | U2 → R-78HB12 (72 V); Q1/Q2 → 60 V; D1 → 60 V Schottky. Whole protected rail now out-rates the clamp. |
| **DR-4b** | **RS-485 idle bias would become an always-on leak.** With the 3V3 rail now always-on, battery-side bias (~2.3 mA) draws continuously → ~8 mW, ~8× the hard-cut budget. | Move fail-safe bias to the **display end only**, resized ~390 Ω (236 mV idle > 200 mV). Battery always-on rail draws **zero** RS-485 static current. |
| **DR-5** | Baseline docs (BOM/power-budget/block-diagram + stale fab CSV) described the pre-DR design. | All reconciled to D19 in this pass. |

**Hard-cut behavior (user decision 2026-06-17): "Option 1 done right".**
At < 10 % SOC the ESP deep-sleeps on the always-on rail (~µA), periodically
reads V24_SENSE, and sheds the display via Q1. It is its own supervisor —
no separate supervisor IC. All-in trickle ≈ **~1 mW** (U1 Iq ~10.5 µA +
sense divider ~22 µA).

**Verified parts (specs + DigiKey stock/lifecycle checked 2026-06-17;
final confirmation still at BOM-lock per D-OPEN-6):**
- **U1 LM5165YDRCR** — 3–65 V in, **10.5 µA Iq**, 150 mA, **fixed 3.3 V** (FB→VOUT, no divider). In stock @ DigiKey, Active. Both surge-tolerant and µA-Iq (a brick can't be both). *The stock check first flagged that the adjustable DRCR I'd picked would need an FB divider — resolved by switching to the fixed-3.3 V "Y" variant (same package), not by adding the divider.*
- **U2 R-78HB12-0.5** — 17–72 V in, 12 V/0.5 A. In stock @ DigiKey, Active.
- **Q1 ZXMP6A13F** — −60 V, **0.9 A**, SOT-23-3 (clean 3-pin; the ZXMP6A17 is only SOT-23-6/SOT-223). In stock @ DigiKey, Active. 0.9 A ≫ the ~0.3 A display feed.
- **D1 SS26** (60 V), **Q2 2N7002** (60 V), **DZ1 BZX84C12** (12 V Zener), FB-divider resistors — ubiquitous jellybeans.

Availability was checked *at selection time* (not deferred to BOM-lock) per
the principle now in ENGINEERING_REVIEW.md step 3 — and the right response
to the adjustable-vs-fixed mismatch was to **pick the fixed-output variant**
(LM5165YDRCR), not to bolt an FB divider onto the adjustable one. Replace
the misfit part; don't patch around it.

**Domains that cleared** with only minor notes: comms (term/bias now
coordinated; dual→single bias point), MCU (decoupling, EN RC soft-start,
straps on internal defaults — fine for flash boot), sensing (1 MΩ/110 kΩ
divider ~22 µA; ~2.9 V at full charge sits near the ADC ceiling — handled
by calibration), connectors (Phoenix + RJ45 ratings ample). Display side:
its one defect (DR-1) was already fixed; regulator coordination sound
(SMAJ15A ~24 V clamp < R-78E3.3 ~28–30 V max).

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

---

*The original May-2026 CP1 packet (its "what changed" enumeration, open-decision tables, and the codex Finding 01–05 review) is preserved in git history. It was superseded by the D18/D19 re-open: its headline blocker — the hard-cut topology inconsistency — is exactly what D19 resolves.*
