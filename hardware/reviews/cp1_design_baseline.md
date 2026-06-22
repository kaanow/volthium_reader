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
- **U1 LM5166YDRCR** — 3–65 V in, **~14 µA Iq**, **500 mA**, **fixed 3.3 V** (FB→VOUT, no divider). TI Active (confirm distributor stock at BOM-lock — see Finding 01/08). Both surge-tolerant and µA-Iq (a brick can't be both). 500 mA (vs the LM5165's 150 mA) feeds a duty-cycled WiFi push (D25). **Suffix: `Y` = 3.3 V, `X` = 5 V — order YDRCR** (reviewer Finding 01; the pre-D25 LM5165 entry here correctly used "Y", the X slip was in the D25 LM5166 swap).
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

**Each analysis below is now DONE, with numbers, in the design docs.** Your
job is to **independently re-derive each and check it against my result** —
not to perform it from scratch with no reference. Where you can't reproduce a
number, that's a finding. (I produced the answer first precisely so there is
something to check against.)

**1 — Power-tree protection coordination (D19) → `cp1_battery_side.md §3.1`.**
This is the class of defect that reached CP6 last round (DR-1/DR-2), so it's
the highest-value re-derivation. My result: worst-case node voltage =
**SMAJ33CA VC = 53.3 V** (at IPP 7.5 A, 10/1000 µs); the tightest margins are
the three **60 V** parts (SS26 / ZXMP6A13F / 2N7002) at **+6.7 V (~13 %)**;
LM5166X 65 V (22 %), R-78HB12 72 V (35 %), input caps 100 V. Gate clamp:
BZX84C12 holds Q1 |Vgs| to ~12 V vs the **±20 V** abs-max (~36 %), and −12 V
still fully enhances Q1. **Re-derive the clamp voltage and every margin;
tell me if 13 % on a non-repetitive transient is the right call or too thin.**

**2 — Part reality + variant → BOM + `decisions.md D25`.** I resolved the
open LM5166 question: the fixed-3.3 V **`LM5166XDRCR`** exists and is stocked
(Mouser), so we commit to it (no FB divider). **Sanity-check that PN**, and
spot-check the other actives aren't NRND/obsolete: RV-3028-C7, ZXMP6A13F,
R-78HB12-0.5, the low-profile right-angle RJ45, the 8-pin Waveshare 4.2"
Module (B). (Last round a phantom Hammond PN reached CP6; this is the catch.)

**3 — Regulator thermals → `cp1_battery_side.md §4.2`.** My result: both are
switchers at a small fraction of rated load — LM5166X worst case ~0.15 W →
ΔT ≈ 7 °C (VSON-10, θJA ~50 °C/W) and only during the ~2–6 s WiFi burst;
R-78HB12 carries ~1 % of its 6 W rating → negligible. **Confirm the loss and
rise; flag if my θJA or efficiency assumptions are optimistic.**

**4 — Display depth stack → `cp1_display_side.md §2.1`.** I dimensioned it
(was previously asserted): stack ≈ **30–31 mm into a ~45 mm box → ~14 mm
margin**; module 91 × 77 mm; binding parts are the R-78E3.3 SIP (~11 mm) and
the RJ45 (low-profile right-angle ~4.4 mm above PCB confirmed available).
**Re-check the tally and the part heights.**

**5 — Sense/ADC (DR-6) → `cp1_battery_side.md §4.4`.** 1.2 MΩ/100 kΩ → 29.2 V
maps to 2.25 V (in the linear band); the 92 kΩ Thevenin is buffered by C5
(100 nF tank) so SAR settling is fine at ≤1 Hz; CP2 has a measure-vs-DMM
validation TODO with a lower-impedance fallback. **Sanity-check the
charge-sharing / settling argument** — this is the one I'm least certain of.

**6 — Internal consistency.** D18–D27 and DR-1…DR-11 — do any two contradict,
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

---

## 8. Reviewer findings (iteration 1)

**Scope:** Single thorough pass per §5. Re-derived D19 protection coordination,
part PNs, regulator thermals, display depth stack, DR-6 sense/ADC settling,
and D18–D27 / DR-1…DR-11 cross-doc consistency. Skipped D11/readability (CP2)
and staleness re-audit per §5.

### Re-derivation summary (§5 checklist)

| # | Topic | Verdict | Notes |
|---|-------|---------|-------|
| 1 | Power-tree protection (D19) | **PASS** | VC = 53.3 V @ IPP 7.5 A reproduced; 60 V floor = +6.7 V (**12.6 %**); gate clamp 12 V vs Vgs max 20 V = **40 %** margin. 13 % on abs-max for a 1 A-fused tap at IPP ≪ 7.5 A is acceptable — see Finding 07. |
| 2 | Part reality / LM5166 variant | **FAIL** | Fixed-3.3 V PN is wrong everywhere — see **Finding 01 (blocker)**. |
| 3 | Regulator thermals (§4.2) | **PASS** | Loss and ΔT reproduced; θJA is **49.1 °C/W** (not 50) → ΔT ≈ **7.4 °C** at 0.15 W WiFi burst. R-78HB12 at ~1 % load negligible. |
| 4 | Display depth stack (§2.1) | **PASS (math) / FAIL (module envelope)** | 5+8+1.6+11+5 = **30.6 mm** vs ~45 mm → **~14 mm** margin holds. Module **outline** dimension is wrong — see **Finding 02**. |
| 5 | Sense / ADC (DR-6) | **PASS** | 29.2 V → 2.25 V; charge-sharing ΔV ≈ **0.2 mV** per sample; RC = 9.2 ms fine at ≤1 Hz. CP2 DMM validation TODO is the right gate. |
| 6 | Internal consistency | **FAIL** | LM5166 PN (Finding 01), module dims (Finding 02), RS-485 bias wording (Finding 04). |

---

### Finding 01 — BLOCKER — LM5166 fixed-output part number (`LM5166XDRCR` vs `LM5166YDRCR`)

**Issue:** Every baseline doc commits to **`LM5166XDRCR`** as the fixed **3.3 V**
buck (D25, `cp1_battery_side.md` §4.2, `cp1_bom.md`, `bom.md`, `decisions.md`
D25). Per the TI LM5166 datasheet (Rev. B), the suffix letter encodes the
fixed output: **`LM5166X` = 5.0 V fixed**, **`LM5166Y` = 3.3 V fixed**.
`LM5166XDRCR` is the 5 V variant (orderable table marks it **5166X**); the
3.3 V fixed part is **`LM5166YDRCR`** (or `LM5166YDRCT` for cut tape).

**Evidence:** TI LM5166 datasheet — "VVOUT5 … LM5166X 4.9 5.0 5.1 V";
"VVOUT3.3 … LM5166Y 3.23 3.3 3.37 V"; orderable table lists `LM5166XDRCR`
as **5166X** and `LM5166YDRCR` as **5166Y**
([LM5166 datasheet](https://www.ti.com/lit/gpn/lm5166), §6.5 / Electrical
Characteristics). D25 text explicitly equates `LM5166X` with 3.3 V — inverted.

**Suggested fix:** Replace **`LM5166XDRCR` → `LM5166YDRCR`** (fixed 3.3 V) in
`decisions.md` D25, `cp1_battery_side.md`, `cp1_bom.md`, `docs/hardware/bom.md`,
and this packet §0. Re-run the Mouser/DigiKey stock check against **YDRCR**.
Schematic/CP2: FB→VOUT strap per the Y-variant fixed-output pinout. Ordering
the X variant would regulate the ESP rail to **~5 V** — destructive.

---

### Finding 02 — IMPORTANT — E-paper module mechanical envelope understated (`cp1_display_side.md` §2.1)

**Issue:** The depth-stack section cites module outline **91 × 77 mm** as the
Waveshare 4.2" Module (B) envelope. That dimension is the **bare panel
outline** only. The **full module** (driver PCB + panel + connector) is
**103.0 × 78.5 mm** per Waveshare — 12 mm wider than documented. The
faceplate mount contract and STEP envelope must use the full module PCB size,
not the panel-only outline.

**Evidence:** Waveshare 4.2" e-Paper Module (B) manual — "Driver board
dimensions: **103.0 mm × 78.5 mm**"; "Outline dimensions (screen only):
91 mm × 77 mm"
([Waveshare wiki](https://www.waveshare.com/wiki/4.2inch_e-Paper_Module_(B)_Manual)).
`cp1_display_side.md` §2.1 lines 75, 108–109 mix panel outline with module
fit. Faceplate is 115 × 117 mm — **103 mm module width still fits**, but
mounting bosses, cable exit, and M2 holes must be laid out against **103 mm**,
not 91 mm.

**Suggested fix:** In `cp1_display_side.md` §2.1 and DR-10 references, split
panel vs module dimensions explicitly: panel outline ~91 × 77 mm; **module
PCB 103.0 × 78.5 mm** (binding for faceplate mount). Update the CP5 STEP
contract note accordingly. Depth tally (~5 mm module thickness) is still
plausible; re-measure at CP3 against the physical module.

---

### Finding 03 — IMPORTANT — U1 500 mA headroom vs WiFi peak + always-on peripherals (`D25`, `cp1_battery_side.md` §4.2)

**Issue:** D25 budgets WiFi at **sustained 150–250 mA** with **peaks 300–500 mA**
on the 3.3 V rail, while U1 is rated **500 mA** max. The always-on rail also
feeds **U3 (SN65HVD3082E, ~30 mA active)** and the RV-3028 (~45 nA). A WiFi
TX peak at the top of the stated range plus an active RS-485 transceiver is
**530 mA** — above the buck's rated output. C2 (22 µF) covers sub-ms spikes
but not a multi-second association burst.

**Evidence:** `decisions.md` D25 — "peaks ~300–500 mA"; `cp1_battery_side.md`
§4.6 — U3 on always-on 3V3; LM5166 IOUT max = 500 mA (TI datasheet).

**Suggested fix:** Either (a) document a **firmware policy**: assert DE/RE
shutdown (~µA) for the full WiFi session so ESP peak is the only meaningful
load, and size C2 per LM5166 datasheet for the remaining transient budget; or
(b) re-validate combined peak with a scope at CP2 and, if margin is <10 %,
add a brief note that LM5166 current-limit foldback during WiFi is acceptable
(duty-cycled, seconds-long). Do not leave the 530 mA arithmetic implicit.

---

### Finding 04 — IMPORTANT — RS-485 bias still listed on battery always-on domain (`cp1_battery_side.md` §3, §7)

**Issue:** D19/DR-4b moved idle bias to the display end only so the battery
always-on rail draws **zero** RS-485 static current. `cp1_battery_side.md` §4.6
and the net list state this correctly, but §3 domain table (line 92) still lists
**"bias"** under always-on 3V3, and §7 States 1–2 budget rows include
**"bias ~1.5 mA"** without clarifying that this is display-end bias **referred
to the 24 V pack through U2/Cat5e**, not a battery-side resistor leak. A reader
could infer the old DR-4b defect was reintroduced.

**Evidence:** `cp1_battery_side.md` §92 — "Always-on 3V3 … RS-485 xceiver,
**bias**, sense divider"; §7 State 1 — "bias ~1.5 mA"; contrast §4.6 — "bus
idle-bias resistors are **on the display end only**".

**Suggested fix:** Remove "bias" from the §3 always-on domain table. In §7,
rename to **"display-end RS-485 bias (via Cat5e, shed at hard-cut)"** or fold
into the "display side ~5 mA" line. Keeps DR-4b unambiguous for CP2 capture.

---

### Finding 05 — NIT — Power-tree ASCII diagram self-contradicts on bias (`cp1_battery_side.md` §3)

**Issue:** The §3 ASCII tree labels the U3 branch **"bias"** on line 78 while
line 79 parenthetically says **"(no bias here — display-end only)"**. Cosmetic,
but it undermines the DR-4b story next to Finding 04.

**Suggested fix:** Change line 78 label from `bias` to `U3 xceiver` (or similar).

---

### Finding 06 — NIT — Packet §0 still cites LM5165 as verified U1 (superseded by D25)

**Issue:** §0 "Verified parts" still lists **LM5165YDRCR** (150 mA) as U1,
while D25 and all per-board docs now specify **LM5166** (500 mA). Stale for
human readers of this packet.

**Suggested fix:** Update §0 verified-parts bullet to LM5166**YDRCR** once
Finding 01 is fixed.

---

### Finding 07 — NIT — 13 % surge margin on 60 V parts is acceptable for this application

**Issue:** None — re-derivation confirms the designer's coordination table.
Flagging for the human reader per §5 item 1.

**Evidence:** SMAJ33CA VC(max) = **53.3 V** @ Ipp = 7.5 A, 10/1000 µs
(Littelfuse SMAJ series datasheet). Tightest downstream ratings: D1/Q1/Q2 at
**60 V** → margin **(60 − 53.3) / 53.3 = 12.6 %**. On a **1 A fast-blow**
battery tap, Ipp at the TVS will be **far below** 7.5 A in practice, so the
53.3 V figure is a conservative ceiling. BZX84C12 holds |Vgs| ≤ **12.7 V**
max vs ZXMP6A13F Vgs abs-max **±20 V** → **≥36 %** gate margin at Zener
tolerance corner.

**Suggested fix:** No part change required. Add a one-line note in §3.1 that
substitutions on V24_FUSED/V24_SW must stay **≥60 V** (already present) and
that 75 V FETs/Schottkys are optional cost insurance, not required.

---

### Finding 08 — QUESTION — LM5166YDRCR distributor stock at BOM-lock

**Issue:** TI.com shows **LM5166YDRCR** out of stock (2026-06-21 spot check);
Mouser fetch timed out. The **correct** 3.3 V fixed PN exists and is
orderable, but live stock was not confirmed this pass.

**Evidence:** [TI LM5166YDRCR product page](https://www.ti.com/product/LM5166/part-details/LM5166YDRCR) — Active, Out of stock.

**Suggested fix:** Re-check DigiKey/Mouser for **LM5166YDRCR** at BOM-lock.
If both are dry, `LM5166YDRCT` (cut tape) or the adjustable `LM5166DRCR` +
divider is the documented fallback — but do **not** substitute `LM5166XDRCR`
(that is 5 V).

---

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blocker, 3 important. (See findings 01, 02, 03, 04.)

---

## 9. Claude's responses (iteration 2, 2026-06-21)

All eight findings addressed this turn (the user pulled the brakes on
auto-looping; reviewer won't re-trigger, so this hands to **user_turn** for a
morning read, not back to the reviewer). Confidence high on 01/02/04/05/06;
medium on 03 (a firmware-policy resolution worth a human eye).

- **RESOLVED — Finding 01 (BLOCKER).** Correct. `LM5166Y` = 3.3 V,
  `LM5166X` = 5 V; ordering X would force ~5 V onto the ESP rail
  (destructive). Independently re-confirmed (TI LM5166 datasheet §6.5; the
  YDRCR = 3.3 V product page). Changed **`LM5166XDRCR` → `LM5166YDRCR`** in
  `decisions.md` D25, `cp1_battery_side.md` §4.2, `cp1_bom.md`,
  `docs/hardware/bom.md`, and §0 here. Added the suffix-trap warning + the
  "never XDRCR" guard at each site. Great catch — this is exactly the value
  of an independent re-derivation.
- **RESOLVED — Finding 02 (IMPORTANT).** Correct. Split the dims in
  `cp1_display_side.md` §2.1: **driver board 103.0 × 78.5 mm** (binding for
  the faceplate mount), screen/panel 91 × 77 mm, active 84.8 × 63.6 mm.
  Instruction added to lay mounting bosses/cable-exit/M2 holes against
  103 × 78.5. Still fits the 115 × 117 mm faceplate. Depth tally unchanged.
- **RESOLVED — Finding 03 (IMPORTANT).** **Confidence: medium.** Added an
  explicit headroom analysis + firmware policy in `cp1_battery_side.md` §4.2:
  WiFi push and RS-485 transmit are **mutually exclusive** (U3 held in
  driver-disable during the session), so the simultaneous peak is
  ESP-dominated and within 500 mA; only sub-ms TX peaks exceed it and C2
  buffers them; brief current-limit foldback on a duty-cycled session is
  benign. CP2 scopes the combined peak to confirm. **User: if you'd rather
  not lean on a firmware policy here, the alternative is a higher-current
  buck — flag it and I'll re-select.**
- **RESOLVED — Finding 04 (IMPORTANT).** Correct. Removed "bias" from the §3
  always-on domain table (now "RS-485 xceiver + R10 term; no idle bias —
  display-end only, DR-4b"); §7 State 1/2 rows relabeled to "display-end
  RS-485 bias (via Cat5e, shed at hard-cut)". No battery-side idle-bias
  implication remains.
- **RESOLVED — Finding 05 (NIT).** §3 ASCII relabeled the U3-branch column
  from "bias" to "R10 term Ω" + "(no idle bias here — display-end only)".
- **RESOLVED — Finding 06 (NIT).** §0 verified-parts bullet updated
  LM5165YDRCR → **LM5166YDRCR** (500 mA, ~14 µA Iq).
- **ACK — Finding 07 (NIT).** No change needed; the ≥60 V substitution rule
  is already in §3.1, and the "75 V parts = optional insurance" note is too.
- **DEFERRED to BOM-lock — Finding 08 (QUESTION).** Recorded the YDRCR
  stock caveat (out-of-stock on TI.com 2026-06-21) at every U1 site, with
  the YDRCT / adjustable-plus-divider fallback and the "never XDRCR" guard.
  Live distributor stock to be confirmed at BOM-lock (D-OPEN-6).

**State:** → `user_turn` for the morning review. Open for a human call:
Finding 03's firmware-policy approach, and clearance to start CP2.
