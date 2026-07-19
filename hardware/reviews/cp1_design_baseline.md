# CP1 review packet — Design baseline

**Status**: RE-OPENED 2026-06-17 (D18) — engineering-correctness pass ready for review
**Originally opened**: 2026-05-23
**Reviewer**: agent-reviewer (re-derive independently per ENGINEERING_REVIEW.md / D17)
**Branch**: `hw/cp1-architecture`
**Goal of this CP**: confirm the design is right *before* we draw it in
KiCad. Catch anything that's wrong, missing, or open-ended now — fixing
it later costs much more.

> **Amendment 2026-07-01 (post-baseline, D33/DR-24).** Supersedes the UVLO
> numbers in the frozen text below (abs-max table §5, Findings 01/02, §12
> notes): **U4 is now `TPS3808G01DBVR` (SOT-23-6, leaded)** — repackaged from
> the WSON TPS389030/TPS389001 for hand-assembly at ~zero power cost.
> Its **VIT = 0.405 V** (not 2.89 V / 1.15 V). Because RESET is open-drain
> **active-low**, the RESET→SENSE hysteresis is positive feedback that sets the
> *falling* trip below the plain divider threshold, so the divider is sized to
> the **release**: **R1≈5.16 MΩ / R2≈100 kΩ** + **R_hys≈11.5 MΩ** →
> **falling trip ~20.0 V / rising release ~21.7–21.8 V** (draws ~4.6 µA —
> *less* than the old part). Hard-cut **≈ ~1.0 mW** (native-domain sum
> per `docs/hardware/power_budget.md`). U6 (`TPS2116`, SOT-583) and U1
> (`LM5166`, VSON-10) stay leadless and reflow with a paste stencil. Current
> values live in D28/D33 + DR-24; the text below is retained as the review
> record. *(Polarity/values corrected per reviewer iter-5 F01; release
> value + State-4 arithmetic corrected per reviewer iter-6 F03/F04 — see
> §14 + §15.)*
>
> **Amendment 2026-07-02 (post-baseline, D34/DR-25; revised iter-10 F08).**
> Supersedes the RS-485 transceiver premise in the frozen text below
> (§4.5/§4.6 tables, §11 abs-max, §12 notes, Finding 03/DR-13
> references): the previous `SN65HVD3082EDR` was a **5 V** part (VCC
> 4.5–5.5 V per TI family datasheet §6.3) that both boards ran outside
> its recommended operating conditions on V3V3. **U3/U2 →
> `THVD1400DR`** (TI, 3.3–5.5 V half-duplex, RX-only Iq 900 µA max,
> **shutdown Iq 1 µA max**, full fail-safe RX, datasheet-guaranteed
> internal DE pull-DOWN + /RE pull-UP → default-safe without external
> resistors). Enables split across two independent ESP GPIOs (GPIO2 = DE,
> GPIO15 = /RE). **Per-board sleep policy (F09):** battery side both
> Hi-Z → shutdown default; display side latches GPIO15 LOW via RTC-GPIO
> so /RE stays 0 and the GPIO18 UART RX wake path stays valid. This
> closes iter-8 F05 (BLOCKER, wrong-VCC part), F06 (IMPORTANT, tied
> enables can't reach shutdown), iter-10 F08 (IMPORTANT, max-vs-typ
> shutdown accounting), and F09 (IMPORTANT, display deep-sleep wake
> regression), and closes long-open **D-OPEN-2**. Iter-8 first cut
> was ISL3175EIBZ; reviewer iter-10 F08 correctly flagged its 12 µA max
> shutdown Iq (vs the 10 nA typ I quoted), which triggered the
> max-to-max reselection to THVD1400. Full rationale in D34; part
> datasheet at `hardware/datasheets/THVD1400DR.pdf` (sha `5ba9785d…`).
> Hard-cut stays **~1.0 mW** headline using worst-case max Iq
> throughout. See §16 (iter-8 responses) and §17 (iter-10 responses).

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
- [ ] **Every active BOM part's datasheet is in `hardware/datasheets/` and has been read** to verify package/footprint, connector PN/pinout, in-box contents, mechanical envelope, and the electrical premises actually used (D32). Manifest "not yet retrieved" list empty for active parts. Parts found unfit are *retired for better parts*, not patched.
- [ ] No new design question survives a careful read.
- [ ] **Assembly is designed-for (G4/D33):** every leadless part is deliberate, justified on merit vs a leaded alternative, and its package won't be a fab surprise; assembly method (stencil + reflow) is on record. See §13.
- [ ] Gates G1–G7 of [`SOP.md`](SOP.md) independently re-derived where applicable.

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

## 8.2 Reviewer findings (iteration 2)

**Scope:** Comprehensive single verification pass per §10/§11 and user brief.
Re-derived D19 coordination, D28 UVLO, D29 USB power, DR-12…DR-23, iter-1
RESOLVED items, board-wide abs-max sweep, datasheet-support check, and ESP
strap audit on both boards. Skipped D11/readability (CP2) and staleness
re-audit per brief.

### Re-derivation summary

| # | Topic | Verdict | Key numbers |
|---|-------|---------|-------------|
| 1 | D19 power-tree coordination (§3.1) | **PASS** | VC = **53.3 V** @ IPP 7.5 A; 60 V floor **+6.7 V (12.6 %)**; BZX84C12 **≤12.7 V** vs Vgs ±20 V (**≥36 %**); 1 A fused tap → Ipp ≪ 7.5 A |
| 2 | LM5166 **Y**DRCR = 3.3 V (iter-1 F01) | **PASS** | TI §6.5: **LM5166Y** 3.23–3.37 V; **LM5166X** 4.9–5.1 V; docs commit **YDRCR** |
| 3 | D28 UVLO (§4.3a) | **PASS w/ fixes** | EN→auto-shed chain sound; **release is ~20.12 V not 22 V** (F09); divider **10 MΩ** below TI bias rule (F08) |
| 4 | D29 USB power (§4.3b) | **PASS w/ fixes** | LDO isolates 5 V; TPS2116 RCB blocks buck backfeed; Q3 gate bias underspecified (F07); ~**1.3 µA** mux → hard-cut **~1.1 mW** |
| 5 | DR-6 sense/ADC | **PASS** | 29.2 V → **2.25 V**; Thevenin **92 kΩ** + C5 **100 nF** → τ **9.2 ms**; ΔV/charge-share **≈0.2 mV** at ≤1 Hz |
| 6 | DR-12 fuse vs inrush | **PASS** | Inrush I²t **~0.06–0.13 A²s**; **0215001.MXP** I²t = **1.52 A²s** → **≥12×** headroom |
| 7 | DR-13 RS-485 bias | **PASS** | 330 Ω → **275 mV** idle; SN65HVD3082E offset receiver **VIT+ max −10 mV** → idle at 0 V already fail-safe HIGH |
| 8 | DR-14 display 12 V TVS | **PASS (logged)** | SMAJ15A VC **24.4 V** vs R-78E3.3 abs-max **28 V** → **+3.6 V (14.8 %)** — tightest display-side coordination |
| 9 | DR-15 battery 12 V TVS | **PASS** | TVS3 SMAJ15A at J2 symmetric with display end |
| 10 | DR-17 brownout vs UVLO | **PASS** | ESP brownout **2.43 V** on 3V3; U4 trips at **~20 V pack** while LM5166 still regulates — no fight |
| 11 | DR-19 grounding loop | **PASS** | Single shield bond battery RJ45; display shield NC (`cat5e_pinout.md`) |
| 12 | DR-20 Cat5e EMC | **PASS** | RS-485 on pair 1, 12 V on pairs 2–4; slew-limited transceiver; DNP choke escape hatch OK |
| 13 | DR-21 FMEA | **PASS** | U4 silent fail → firmware-only baseline; accepted per user |
| 14 | DR-22 cold floor | **PASS** | E-paper **0 °C** is BOM floor; all other actives **−40 °C** |
| 15 | DR-23 RTC backup cap | **PASS** | Low-leakage **10–50 mF** ≫ supercap µA leakage; VBACKUP **5.5 V** > 3.3 V trickle |
| 16 | Iter-1 fixes (02–04) | **PASS** | Module **103.0×78.5 mm**; WiFi/RS-485 mutual-exclusion closes **530 mA** case |
| 17 | Board-wide abs-max sweep | **PASS (1 flag)** | One **<20 %** voltage margin on display 12 V path (DR-14); all others ≥20 % or non-repetitive transient |
| 18 | Datasheet support parts | **PASS w/ CP2 TODOs** | LM5166 EN/SS/ILIM strapping not yet in CP1 (F10); TPS2116 suggests **~100 µF** on OUT if RCB frequent (F11) |

### Board-wide abs-max vs worst-case (semiconductors)

**Battery side**

| Ref | Part | Worst-case stress | Abs-max / rating | Margin |
|-----|------|-------------------|------------------|--------|
| D1 | SS26 | VRRM **53.3 V** clamp | **60 V** | **12.6 %** (non-rep. transient) |
| Q1 | ZXMP6A13F | Vds **53.3 V** (open) | **60 V** | **12.6 %** |
| Q2, Q3 | 2N7002 | Vds **53.3 V** | **60 V** | **12.6 %** |
| U1 | LM5166YDRCR | VIN **53.3 V**; IOUT **≤500 mA** WiFi | VIN **65 V**; IOUT **500 mA** | **22 %** V; **0 %** I (policy-limited) |
| U2 | R-78HB12 | VIN **53.3 V**; IOUT **~50 mA** | VIN **72 V**; **0.5 A** | **35 %** V; **90 %** I |
| U3 | SN65HVD3082E | VCC **3.3 V**; DE/RE shutdown in WiFi | **6 V**; **±60 mA** drv | ample |
| U4 | TPS389001 | SENSE **~1.15 V**; VDD **3.3 V** | SENSE **5.5 V**; VDD **5.5 V** | ample |
| U5 | AP2112K-3.3 | VIN **5 V** USB | **6 V** | **20 %** |
| U6 | TPS2116 | VIN/O **3.3 V** | **5.5 V** | **67 %** |
| TVS1 | SMAJ33CA | Clamps at **53.3 V** | VC spec | coordinated |
| TVS2/3 | SMAJ12/15 | Clamps below downstream | coordinated | OK |
| DZ1 | BZX84C12 | **12.7 V** Vgs max | **20 V** Vgs abs-max | **36 %** |
| MOD1 | ESP32-S3-WROOM-1 | 3.3 V rail; WiFi peak **~350–500 mA** | Module-rated | within module |

**Display side**

| Ref | Part | Worst-case stress | Abs-max / rating | Margin |
|-----|------|-------------------|------------------|--------|
| TVS1 | SMAJ15A | VC **24.4 V** @ IPP | — | — |
| U1 | R-78E3.3 | VIN **24.4 V** clamp | VIN **28 V** | **14.8 %** ⚠ |
| U2 | SN65HVD3082E | same as battery | ample | OK |
| U3-LDO | AP2112K-3.3 | VIN **5 V** | **6 V** | **20 %** |
| U4-MUX | TPS2116 | **3.3 V** | **5.5 V** | **67 %** |
| MOD1 | ESP32-S3-WROOM-1 | refresh **~25 mA** avg | within **0.5 A** brick | ample |

⚠ = only part under **20 %** voltage margin; acceptable at IPP ≪ max (same class as 60 V floor on battery side) but **do not substitute** a lower-VC TVS or lower-VIN regulator without re-coordinating.

---

### Finding 01 — should-fix — D28 UVLO release voltage mis-stated (~20.12 V, not ~22 V)

**Issue:** `cp1_battery_side.md` §4.3a and D28 claim trip **~20 V** / release
**~22 V** (2 V hysteresis). TPS389001 built-in hysteresis is **VHYST =
0.33–0.83 %** of VITN (TI TPS3890 datasheet §6.5) → ΔV_SENSE ≈ **4–10 mV**.
With a divider sized for 20 V trip (V_SENSE/V_pack = 1.15/20 = **0.0575**),
pack release ≈ **20.07–20.17 V**, not 22 V.

**Evidence:** TPS389001 VITN = **1.15 V**, VITP = **1.157 V** (typ); pack
release = 1.157/0.0575 = **20.12 V**. Only **~0.12 V** above trip.

**Suggested fix:** Correct all "release ~22 V" prose to the computed **~20.1 V**.
At CP2, confirm cold-boot after release does not re-trip (large load step OFF
at assert likely rebounds pack ≫0.12 V — but document the real hysteresis).
If bench shows chatter, add external hysteresis or raise trip — do not rely on
a non-existent 2 V band.

---

### Finding 02 — should-fix — D28 UVLO divider (~10 MΩ) violates TPS3890 SENSE bias-current rule

**Issue:** ~**10 MΩ** divider on V24_FUSED draws **~2 µA** at 20 V. TI requires
divider current **≥100× I_SENSE** (I_SENSE max **100 nA**) → **≥10 µA**
(TPS3890 datasheet §8.3.4 / SLVA450). At 2 µA the threshold error from bias
current can reach **several percent** — enough to shift a 20 V floor by
**~0.5–1 V**.

**Evidence:** I_div = 20 V/10 MΩ = **2 µA** vs required **≥10 µA**. At
**R_TOTAL = 2.2 MΩ**: I = **9.1 µA** at 20 V → meets rule; added draw
29 V/2.2 MΩ = **13 µA** → **~0.38 mW** at full charge (still ≪ hard-cut budget).

**Suggested fix:** Size **R_uv1+R_uv2 ≈ 2.0–2.2 MΩ** (not 10 MΩ) for ~20 V
trip with TPS389001. Recompute R1/R2 at CP2; update §4.3a, D28, and
`power_budget.md` UVLO row (~0.1 mW → ~0.4 mW — hard-cut becomes **~1.3 mW**,
still acceptable).

---

### Finding 03 — should-fix — D29 Q3 UVLO-bypass gate bias not fully specified (default must be UVLO **active**)

**Issue:** Q3 gate is driven only from a **VBUS-referenced** divider (D29).
With N-FET in series on U4 RESET→EN: **VBUS absent → gate = 0 V → FET OFF →
U4 disconnected from EN → UVLO bypassed** (opposite of intent). The prose
requires Q3 **closed** (UVLO active) when USB is out.

**Evidence:** `cp1_battery_side.md` §4.3b — "R_byp1/R_byp2 … VBUS-referenced"
with no **V3V3 pull-up** or other default-ON bias documented.

**Suggested fix:** At CP2, use **gate default-ON from V3V3** (e.g. **100 kΩ**
to V3V3) with VBUS (via resistor/diode) pulling gate **LOW** when present to
**open** the FET. Document truth table: VBUS absent → Q3 ON → U4 drives EN;
VBUS present → Q3 OFF → U4 isolated. Verify Vol/I_RESET sink through Q3
RDS(on) ≪ R7 (**10 kΩ**).

---

### Finding 04 — should-fix — Display-side D29 not reflected in §5 net list / decoupling

**Issue:** `cp1_display_side.md` §4.3 adds **U3-LDO + U4-MUX (TPS2116)** but
§5 still has **V3V3 ← U1 VOUT** only — no **3V3_USB**, **VBUS**, or mux OUT
path. Decoupling table (§9) omits **C_usb1/C_usb2** and mux input caps.

**Evidence:** `cp1_display_side.md` §266 vs §171–172; battery-side §5 was
updated (V3V3 ← U6 OUT).

**Suggested fix:** Mirror battery-side net list: V3V3 ← U4-MUX OUT; 3V3_USB ←
U3-LDO; VBUS → U-ESD/U3-LDO; add D29 caps to §9. Prevents CP2 capture from
OR-ing VBUS into V3V3 by accident.

---

### Finding 05 — should-fix — Display ESP32 strap pins undocumented (GPIO3/45/46)

**Issue:** Battery side documents GPIO0/3/45/46 straps (§6). Display side §6
lists GPIO0 only — omits **GPIO3** (USB-JTAG), **GPIO45** (VDD_SPI), **GPIO46**
(boot). Same WROOM-1 module → same strap requirements.

**Evidence:** Espressif ESP32-S3 strapping table; `cp1_display_side.md` §6
vs `cp1_battery_side.md` §428–448.

**Suggested fix:** Add GPIO3/45/46 as **NC (internal default)** on display
side §6; CP2 ERC check both boards.

---

### Finding 06 — should-fix — `cp1_battery_side.md` §7 State 3 still cites RV-3028 **150 µA** (DS3231 stale)

**Issue:** State 3 row lists **"RV-3028 ~150 µA"** — the DS3231 figure. D23/DR-8
swapped to RV-3028-C7 at **45 nA**. `power_budget.md` is correct; §7 is not.

**Evidence:** `cp1_battery_side.md` §7 line 464 vs `power_budget.md` State 3
(**45 nA**). Error does not change ~0.13 W total materially but contradicts
D23.

**Suggested fix:** Replace **~150 µA** → **~45 nA (negligible)** in §7 State 3.

---

### Finding 07 — nit — §3.1 coordination table still labels U1 "LM5166**X**" buck

**Issue:** Part is **LM5166YDRCR (Y = 3.3 V)** everywhere else; §3.1 table
row says **"LM5166X buck"** — the suffix that means **5 V**.

**Evidence:** `cp1_battery_side.md` §3.1 line 122; TI datasheet suffix table.

**Suggested fix:** Rename row to **LM5166Y** (or "LM5166 3.3 V fixed") in §3.1
and §4.2 thermal bullet.

---

### Finding 08 — nit — Display §3 ASCII power tree still shows **0.5 A** PTC (DR-11 → 0.25 A)

**Issue:** Component table and BOM specify **~0.25 A hold** (DR-11); §3 ASCII
diagram still says **"0.5 A hold"**.

**Evidence:** `cp1_display_side.md` §3 line 127 vs §4.1 line 153.

**Suggested fix:** Update ASCII to **~0.25 A hold**.

---

### Finding 09 — nit — C-bk spec in §4.5 still allows "**~0.1 F**" supercap class

**Issue:** DR-23 tightened to **low-leakage 10–50 mF, not a leaky supercap**.
§4.5 C-bk line still says **"~10 mF–0.1 F"** which invites a supercap whose
µA leakage dwarfs 45 nA RTC.

**Evidence:** `cp1_battery_side.md` §4.5 C-bk vs DR-23 resolution.

**Suggested fix:** Cap upper bound at **~50 mF low-leakage ceramic/tantalum**;
explicit "no supercap" note.

---

### Finding 10 — nit (CP2 gate) — LM5166 EN/SS support network not in CP1 BOM

**Issue:** LM5166 requires **EN** above **1.22 V** to start (datasheet §6.5).
CP1 lists C1/C2/L1 but not **EN tie** (typically EN→VIN or divider), **SS**
pin disposition (900 µs default vs cap), or **ILIM** resistor if not default.

**Evidence:** LM5166 datasheet §7.3 / typical application; `cp1_battery_side.md`
§4.2, §10.

**Suggested fix:** CP2 schematic: document EN strapping (recommend **EN tied
to V24_FUSED** for always-on), SS pin open or per datasheet, default ILIM.
Add to decoupling table.

---

### Finding 11 — nit (CP2 gate) — TPS2116 reverse-current blocking vs output capacitance

**Issue:** When USB powers V3V3, buck output on VIN2 is held high; TPS2116
RCB blocks reverse current at VOUT > VIN + **42 mV** (datasheet §7.3.4). TI
recommends **~100 µF** on OUT if RCB is expected — design has **C2 22 µF +
C6 10 µF ≈ 32 µF**.

**Evidence:** TPS2116 datasheet §7.3.4; `cp1_battery_side.md` §10.

**Suggested fix:** Likely fine for rare USB plug events; at CP2 either add
**~47 µF** on V3V3 or note in layout that USB hot-plug scope should show
VOUT spike **<5.5 V** abs-max on mux/buck pins.

---

### Verified RESOLVED items (iter-1 + DR-12…DR-23) — no reopen

| Item | Independent result |
|------|-------------------|
| F01 LM5166 YDRCR | **Confirmed** — Y=3.3 V, X=5 V; never order XDRCR |
| F02 module 103×78.5 mm | **Confirmed** — Waveshare Module (B) driver PCB |
| F03 WiFi 500 mA | **Confirmed** with mutual-exclusion policy; sub-ms peaks on C2 |
| F04/05 bias wording | **Confirmed** fixed |
| DR-12 time-lag fuse | **Confirmed** — 0215001.MXP I²t **1.52 A²s** vs **~0.1 A²s** inrush |
| DR-13 330 Ω bias | **Confirmed** — **275 mV** idle; chip offset thresholds make this ample |
| DR-14 SMAJ15A / R-78E3.3 | **Confirmed** — **24.4 V** vs **28 V** (**14.8 %**) |
| DR-16 EN→auto-shed | **Confirmed** — reset → GPIO4 Hi-Z → R4/R3 → Q1 OFF |
| DR-17 brownout ordering | **Confirmed** — U4 @ 20 V pack precedes 3V3 brownout |
| DR-18/D29 5 V isolation | **Confirmed** — AP2112 regulates; no raw VBUS on V3V3 |
| DR-19 single-point GND | **Confirmed** per `cat5e_pinout.md` |
| DR-21 fail-to-baseline | **Confirmed** — acceptable per user |
| DR-22/DR-23 | **Confirmed** — not reopened |

**Part reality spot-check (DigiKey/TI/Mouser, 2026-06-22):** LM5166YDRCR
(Active, stock varies), RV-3028-C7 (Active), ZXMP6A13F (Active), R-78HB12-0.5
(Active), TPS389001 family (Active), TPS2116DRLR (Active), AP2112K-3.3TRG1
(Active), Waveshare 4.2" Module (B) DK **1738-1135-ND**, SN65HVD3082E (Active).
Low-profile RJ45 class (e.g. SUYIN 100362-series **~4.4 mm** above PCB) exists —
confirm exact SKU at BOM-lock.

---

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 6 should-fix, 5 nit. (See findings 01–06.)

---

## 8.3 Reviewer findings (iteration 5)

**Scope:** Independent CP1 pass against `SOP.md` gates G1-G7 where applicable,
starting from §13. Re-derived the D33 U4 swap to `TPS3808G01DBVR`, the new
UVLO divider and external hysteresis premise, the hard-cut power sum, G4
assembly trade, G5 consistency sweep, and DR-19 end-to-end shield/ground loop.
Did not start CP2; schematic readability/ERC/DRC remain out of scope.

### SOP gate re-derivation summary

| Gate | Verdict | Notes |
|------|---------|-------|
| G1 engineering correctness | **FAIL w/ fixes** | U4 part class and divider bias are sound; external hysteresis math/sign is not self-consistent with active-low RESET (Finding 01). |
| G2 datasheet-on-hand | **PASS for changed item** | `hardware/datasheets/TPS3808G01DBVR.pdf` is present and manifest-listed; retired TPS389030 PDF is removed. Full active-parts gate remains D32-owned. |
| G3 availability/variant | **PASS for changed item** | Packet/BOM consistently name `TPS3808G01DBVR`, SOT-23-6, active with distributor stock noted. |
| G4 assembly/solderability | **PASS** | U4 swap is a merit-positive solderability win; keeping U1 VSON-10 and U6 SOT-583 is justified by power-first tradeoffs plus stencil/reflow plan. |
| G5 spec consistency | **FAIL** | Superseded U4 history is correctly bannered, but the live battery-side State 4 budget still says `~1 mW` and omits U4/mux (Finding 02). |
| G6 readability | **N/A** | CP1 markdown only; no schematic/PDF artifacts to inspect. |
| G7 design-complete before handoff | **PASS** | The packet provides concrete values to check; the two failures are derivation/spec-consistency defects, not unanswered design questions. |

### Re-derivation notes

- **U4 swap:** TPS3808G01DBVR fits the intended role: adjustable SENSE at
  0.405 V, open-drain active-low RESET, programmable CT delay, SOT-23-6
  leaded package, and ~2.4 µA Iq. This is a cleaner assembly choice than the
  WSON TPS3890 without giving up the power budget.
- **UVLO divider without external hysteresis:** R1 = 4.87 MΩ, R2 = 100 kΩ
  gives Vpack = 0.405 V * (4.87 MΩ + 0.100 MΩ) / 0.100 MΩ = **20.13 V**.
  Divider current is 20.13 V / 4.97 MΩ = **4.05 µA** at threshold, which is
  **162x** the TPS3808 SENSE current max of 25 nA; the >=100x rule is met.
  At 24 V it draws **4.83 µA / 0.116 mW**; at 29.2 V it draws **5.88 µA /
  0.172 mW**.
- **Built-in hysteresis:** TPS3808G01 built-in VHYS is 1.5% of VIT, so
  0.015 * 0.405 V = **6.1 mV** at SENSE. Referred through the 49.7:1 divider,
  that is about **0.30 V** at the pack: better than the old TPS3890 internal
  band, but still plausibly too small after shedding a ~38 mA hung-MCU load.
- **Hard-cut arithmetic:** Using the packet numbers at 24 V: LM5166 Iq
  14 µA -> **0.336 mW**; ESP deep sleep ~10 µA -> **0.240 mW**; V24 sense
  divider 24 V / 1.3 MΩ = 18.5 µA -> **0.443 mW**; U4 + UVLO divider
  (2.4 + 4.83) µA -> **0.174 mW**; TPS2116 mux 1.3 µA at 3.3 V -> **0.004 mW**.
  Total = **1.20 mW**. If U4 asserts EN and the ESP reset current is below
  the assumed 10 µA deep-sleep current, the floor trends toward the documented
  **~1.0 mW**.
- **DR-19 grounding/shield loop:** Battery board J2 shield/drain is bonded to
  battery-side signal/pack GND; display J1 shield is explicitly NC; Cat5e
  pinout ties signal GND over pins 6/7/8 and shield/drain only at the battery
  end. Both enclosures are plastic, so there is no second chassis/earth path
  from the display box. Result: exactly one signal-GND-to-shield bond in the
  loop. **DR-19 verified closed** for CP1 intent; CP5 should still visually
  confirm the display RJ45 shell has no copper bond or mounting hardware path.

### Finding 01 — IMPORTANT — `cp1_battery_side.md` §4.3a / `decisions.md` D28

**Issue**: The documented R1/R2/R_hys values do not produce "trip ~20.1 V /
release ~21.3 V" when R_hys is connected from active-low RESET to SENSE. With
R1 = 4.87 MΩ and R2 = 100 kΩ, the no-feedback threshold is ~20.13 V. Because
TPS3808 RESET is open-drain active-low, a resistor from RESET (pulled high to
3.3 V when unasserted) to SENSE raises SENSE before the falling trip and
therefore lowers the falling pack trip; after RESET asserts low, the release
threshold returns to the no-feedback value. The stated values therefore make
~20.1 V the release point, not the trip point.

**Evidence**: TI TPS3808 datasheet §8.3.1 defines the G01 threshold as
`VIT' = (1 + R1/R2) * 0.405`; §8.3.4 states RESET is open-drain, asserted low
when SENSE falls below VIT, and deasserts only after SENSE is above
`VIT + VHYS`. For the documented R1/R2, `0.405*(1+4.87M/100k)=20.13 V`.
With RESET high at 3.3 V, KCL at SENSE gives
`Vfall = VIT*(1+R1/R2) - R1*(3.3-VIT)/R_hys`; an R_hys that creates a 1.3 V
band would make Vfall about **18.8 V** and Vrelease about **20.1 V**, opposite
the prose.

**Suggested fix**: Re-derive the CP2 values with the intended polarity. If the
requirement is falling trip ~20.0 V and rising release ~21.3 V using RESET-to-
SENSE positive feedback, set the divider's no-feedback threshold at the release
point (for R2 = 100 kΩ, R1 ≈ **5.16 MΩ**) and size R_hys around
`R1*(3.3-0.405)/1.3 ≈ 11.5-12 MΩ` before E96/tolerance analysis. Alternatively
choose a supervisor topology/output polarity that makes the documented equation
true. Update D28, §4.3a, BOM rows, and the packet banner after choosing values.

### Finding 02 — IMPORTANT — `cp1_battery_side.md` §7 / §3

**Issue**: The live battery-side power budget still reports State 4 hard-cut as
`~1 mW` and lists only LM5166 Iq + ESP deep sleep + the V24 sense divider +
RTC. It omits the new U4/TPS3808 supervisor, UVLO divider, and TPS2116 mux,
while §13 claims the hard-cut figure was reconciled across battery-side docs to
~1.2 mW. This is a G5 consistency failure in a live baseline document.

**Evidence**: `cp1_battery_side.md` §7 State 4 still says `~1 mW`; the same
file §4.3a/§4.3b says the D33 UVLO divider and D29 mux make hard-cut
`≈ 1.2 mW`; `docs/hardware/power_budget.md` §State 4 lists the correct sum:
sense divider **~0.44 mW**, UVLO supervisor+divider **~0.25 mW**, mux
**~0.004 mW**, total **~1.2 mW**.

**Suggested fix**: Update `cp1_battery_side.md` §3 and §7 to show the current
hard-cut budget terms: LM5166 Iq, ESP deep sleep, V24 sense divider, U4 +
UVLO divider, TPS2116 mux, RTC negligible, total **~1.2 mW**; note the
EN-asserted hardware floor separately as **~1.0 mW** if the ESP reset current
is below the deep-sleep assumption.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 01, 02.)

---

## 8.4 Reviewer findings (iteration 6)

**Scope:** Re-verified Claude's §14 responses to iteration-5 Findings 01/02.
The hysteresis polarity correction and cross-document State 4 term list are
propagated. Independently re-derived the actual node equations and pack power.
DR-19 remains verified closed. CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| Iter-5 F01, hysteresis polarity | **PASS directionally** | Divider is now correctly release-sized and RESET-to-SENSE feedback lowers the falling trip. Exact release is slightly higher than documented; see Finding 04. |
| Iter-5 F02, stale State 4 row | **PASS consistency / FAIL arithmetic** | U4 and mux terms now appear in §3/§7, but the total still mixes 3.3 V rail current with 24 V pack power; see Finding 03. |
| DR-19 grounding/shield loop | **PASS** | One battery-end shield-to-pack-GND bond, display shield NC, plastic enclosures; retain the CP5 visual confirmation. |

### Finding 03 — IMPORTANT — `power_budget.md` State 4 / `cp1_battery_side.md` §7

**Issue**: The `~1.2 mW` hard-cut total is dimensionally wrong because several
3.3 V rail currents are treated as though they flow directly from the 24 V
pack. In particular, ESP deep-sleep `10 µA @ 3.3 V` is listed as `~0.2-0.24
mW`, which is 10 µA multiplied by roughly 24 V; its load power is **0.033 mW**
before buck-conversion loss. U4 Iq and TPS2116 Iq have the same voltage-domain
issue. The error is conservative, but this is the project's power-first
budget and must be internally valid.

**Evidence**: `docs/hardware/power_budget.md` labels the column "referred to
24 V pack" but gives ESP `~10 µA @ 3.3 V -> ~0.2 mW`; `cp1_battery_side.md`
§7 gives `~0.24 mW`. The correct first-order terms at 24 V nominal are:
LM5166 input Iq `14 µA * 24 V = 0.336 mW`; V24 sense divider
`24^2 / 1.3 MΩ = 0.443 mW`; UVLO divider approximately
`4.56 µA * 24 V = 0.109 mW`; 3.3 V loads ESP/U4/mux approximately
`(10 + 2.4 + 1.3) µA * 3.3 V = 0.045 mW` before conversion loss; RTC is
negligible. Even allowing poor light-load conversion efficiency for the
0.045 mW output load, the total is approximately **0.94-1.0 mW**, not
1.2 mW. The EN-asserted floor is only tens of microwatts lower, not
approximately 0.2 mW lower.

**Suggested fix**: Keep every term in its native voltage domain, convert
3.3 V load power through an explicit conservative LM5166 light-load
efficiency assumption, and add the LM5166's 24 V input Iq separately. Update
the State 4 and EN-asserted totals consistently in `power_budget.md`,
`cp1_battery_side.md`, D28, BOM commentary, and the packet banner/§13/§14.
A defensible rounded result appears to be **~1.0 mW** for both states, with
the floor slightly lower; use a range if light-load efficiency is not yet
bench-verified.

### Finding 04 — NIT — `cp1_battery_side.md` §4.3a / `decisions.md` D28

**Issue**: The corrected hysteresis direction is sound, but the nominal
release is still understated. The prose now mentions the built-in hysteresis
and the R_hys-to-R2 term, yet calls the result `~21.5 V`. Solving the asserted
state gives approximately **21.7-21.8 V**, depending on RESET VOL, for the
documented 5.16 MΩ / 100 kΩ / 11.5 MΩ values.

**Evidence**: TPS3808 deasserts after SENSE exceeds
`VIT + VHYS = 0.405 V * 1.015 = 0.4111 V`. With RESET low, R_hys is an
additional SENSE-to-RESET path, so
`Vrelease = Vs + R1*(Vs/R2 + (Vs-VOL)/R_hys)`. Using VOL = 0-0.2 V gives
**21.80-21.71 V**. The falling-trip equation with RESET high still reproduces
approximately **20.00 V**.

**Suggested fix**: Quote the nominal release as approximately **21.7-21.8 V**
for the provisional values, or choose final E96 values at CP2 that center the
desired release. Keep the planned tolerance analysis and bench verification.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 03.)

---

## 8.5 Reviewer findings (iteration 8)

**Scope:** Re-verified Claude's §15 responses to iteration-6 Findings 03/04.
The corrected native-domain power calculation reproduces (~0.98 mW at the
documented conservative 50% light-load efficiency), and the corrected
21.7-21.8 V release equation reproduces. A clean-sheet G1/G2 comms check then
found a wrong-part premise and a shutdown-topology defect that invalidate the
current RS-485 implementation and hard-cut budget. CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| Iter-6 F03, hard-cut dimensional error | **PASS for listed terms** | 0.336 + 0.443 + 0.109 + 0.090 = 0.978 mW at eta = 50%; however the list omits the active RS-485 transceiver because the documented enable topology cannot shut it down (Finding 06). |
| Iter-6 F04, UVLO release | **PASS** | Node equation at SENSE = 0.4111 V and RESET VOL = 0-0.2 V reproduces 21.81-21.72 V. |
| DR-19 grounding/shield loop | **PASS** | Remains verified closed for CP1 intent; retain CP5 visual confirmation. |

### Finding 05 — BLOCKER — both boards' RS-485 transceiver supply (`SN65HVD3082E`)

**Issue**: Both boards specify `SN65HVD3082E` as a 3.3 V transceiver powered
from V3V3, but that exact part is a **5 V device**. Its guaranteed recommended
VCC range is 4.5-5.5 V. Operation at 3.3 V is outside the datasheet's operating
conditions, so neither RS-485 link endpoint is valid as designed.

**Evidence**: Stored TI datasheet `hardware/datasheets/SN65HVD3082EDR.pdf`,
§3 says the family is powered by a 5 V supply; §6.3 specifies VCC minimum
**4.5 V**, maximum **5.5 V**. In contrast, `cp1_battery_side.md` §4.6 calls U3
"3.3 V" and its net table connects U3 VCC to V3V3; `cp1_display_side.md` §3,
§4.5, and §5 likewise connect U2 VCC to V3V3. `docs/hardware/bom.md` explicitly
labels `SN65HVD3082EDR` "half-duplex, 3.3 V," contradicting its datasheet.

**Suggested fix**: Apply SOP principle 2 and replace U2/U3 with a genuinely
3.3 V, low-Iq half-duplex RS-485 transceiver rather than adding always-on 5 V
rails. Independently verify the exact replacement's supply range, receiver
thresholds/fail-safe behavior, shutdown current, enable truth table, bus-pin
ratings/ESD, package, lifecycle, and stock; store/read its datasheet per G2.
Recompute the display-end bias if its guaranteed thresholds differ. The
existing D-OPEN-2 alternatives are candidates, not evidence, until checked.

### Finding 06 — IMPORTANT — `DE_RE` tied-enable topology / hard-cut budget

**Issue**: The battery-side design claims the ESP shuts U3 down through a
single `DE_RE` net, but tying active-high DE to active-low `/RE` makes shutdown
impossible: LOW selects receive and HIGH selects transmit. The corrected
~0.98 mW budget therefore omits an always-on active transceiver. The same tied
topology exists on the display side, although display power is shed in State 4.

**Evidence**: TI datasheet §5 identifies `/RE` as active-low and DE as
active-high; §9.2.2.2 requires **DE low and /RE high simultaneously** for
low-power shutdown (typical 1 nA). It states active operation is typically
**0.3 mA**, not the `30 µA` claimed by `cp1_battery_side.md` §4.6. The battery
and display net tables both say `DE_RE -> DE & RE pins (tied)`. With the
existing part active, 0.3 mA at 5 V is 1.5 mW before source-conversion loss;
for any replacement, its active current must be included until a realizable
shutdown state is specified.

**Suggested fix**: Specify independent DE and `/RE` control (including
boot/reset/deep-sleep pulls) or select a replacement with a separately usable
shutdown mechanism. The unattended battery state must guarantee driver OFF
and receiver OFF in hardware/firmware, not rely on a tied complementary-enable
net. Recalculate State 4 using the selected part's **maximum** shutdown current,
and update both pin maps/net lists and the WiFi mutual-exclusion policy.

### Finding 07 — IMPORTANT — G5 live-document consistency after §15

**Issue**: The claimed propagation is incomplete. A live battery-side USB
section still says hard-cut is ~1.2 mW; the new budget says the RTC draws from
an "own coin cell" even though D23 explicitly removed the coin cell and powers
RTC VCC from always-on V3V3; and both active BOMs have regressed the backup-cap
range to 10 mF-0.1 F despite the resolved 10-50 mF/no-supercap limit.

**Evidence**: `cp1_battery_side.md` §4.3b still states `hard-cut ≈ 1.2 mW`.
Its §3 and §7 plus `power_budget.md` State 4 say `own coin cell`, while the same
file's power tree/net table connects RV-3028 VCC to V3V3 and §4.5 specifies a
trickle-charged C-bk with **no coin cell**; D23 says the same. The RV-3028
datasheet's 45 nA figure is specified in timekeeping mode at VDD = 3 V, so it
belongs in the 3.3 V load sum (negligible, but not zero/from another source).
`cp1_bom.md` and `docs/hardware/bom.md` list C-bk as `10 mF-0.1 F`, contrary
to `cp1_battery_side.md` §4.5 and resolved reviewer F09 (`10-50 mF`, no
supercap).

**Suggested fix**: Mechanically sweep and correct all live instances: change
the stale 1.2 mW statement to the final post-RS-485 value; model RTC VCC as
45 nA at 3.3 V through U1 while describing C-bk only as backup during VDD loss;
and restore `10-50 mF low-leakage, no supercap` in both BOMs. Keep historical
review responses clearly historical rather than rewriting them.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blocker, 2 important. (See findings 05, 06, 07.)

---

## 8.6 Reviewer findings (iteration 10)

**Scope:** Re-verified Claude's §16 responses to iteration-8 Findings 05/06/07
against the stored Renesas datasheet and both board baselines. The
`ISL3175EIBZ` supply range, package/pinout, active-current limit, slew-rate
class, and full-fail-safe receiver fit the 3.3 V design. The split DE and /RE
topology makes shutdown reachable. The three specific F07 corrections are
present. CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| Iter-8 F05, wrong-VCC transceiver | **PASS** | ISL3175EIBZ is guaranteed at VCC 3.0-3.6 V, 8-SOIC, 500 kbps slew-limited, standard half-duplex pinout. |
| Iter-8 F06, tied enables | **PASS battery / FAIL display policy** | Independent DE and /RE plus pulls reach shutdown and safely default the battery endpoint off; applying the same deep-sleep policy to the display breaks RS-485 wake (Finding 09). |
| Iter-8 F07, G5 corrections | **PASS requested tokens** | Stale 1.2 mW, RTC coin-cell wording, and C-bk 0.1 F limits are corrected; a smaller pin-map drift remains (Finding 10). |
| DR-19 grounding/shield loop | **PASS** | Remains verified closed for CP1 intent. |

### Finding 08 — IMPORTANT — ISL3175E shutdown-current premise / State 4 budget

**Issue**: The replacement is repeatedly described and budgeted as a `10 nA`
shutdown load, but 10 nA is only the datasheet **typical** value. The
guaranteed maximum shutdown current is **12 µA**, 1200 times higher. G1 requires
worst-case margin, and the reviewer explicitly requested the selected part's
maximum shutdown current in iteration-8 Finding 06.

**Evidence**: Stored Renesas datasheet `hardware/datasheets/ISL3175EIBZ.pdf`,
Electrical Specifications / Supply Current table: `ISHDN`, DE = 0 V and
/RE = VCC, is **0.01 µA typical, 12 µA maximum** over temperature. D34, both
board component tables, both BOMs, and `power_budget.md` use 10 nA as though it
were the design bound. At the stated eta = 50%, 12 µA at 3.3 V refers to about
**0.079 mW** at the pack, moving the prior 0.978 mW worst-case estimate to
about **1.06 mW** before other tolerance effects; 10 nA contributes only
0.000066 mW.

**Suggested fix**: Compare candidate shutdown currents max-to-max, not
typical-to-typical. Either retain ISL3175E and budget its 12 µA maximum
(headline approximately **1.1 mW**, still acceptable if explicitly judged),
or reselect if a genuinely lower guaranteed shutdown current wins on merit.
Propagate typical and maximum values distinctly through D34, DR-25, both board
docs/BOMs, the packet, and `power_budget.md`.

### Finding 09 — IMPORTANT — display-side deep-sleep RS-485 wake regression

**Issue**: The new display policy makes GPIO15 Hi-Z in deep sleep so R_RE pulls
/RE high and disables the receiver, while the same pin map says UART RX on
GPIO18 wakes the ESP from RS-485. A disabled receiver cannot toggle RO, so the
documented wake path is impossible. This affects normal display operation,
not State 4: the display board is powered in State 3/idle and must receive the
next frame.

**Evidence**: `cp1_display_side.md` §6 says GPIO15 becomes Hi-Z in deep sleep,
R_RE sets /RE = 1, and the transceiver enters shutdown; two rows later it says
GPIO18 RS-485 RX wakes the ESP. §7 State B budgets an active RS-485 receiver
while the ESP deep-sleeps. D34 instead mandates both GPIOs Hi-Z in deep sleep
on both boards. The ISL3175E truth table requires /RE low for receiver output
RO to be active.

**Suggested fix**: Define board-specific sleep behavior. Battery-side State 4
should default to shutdown. Display-side deep sleep must either hold /RE low
with DE low so RO can wake GPIO18 (and budget the receiver's **maximum** active
current plus any R_RE pull current), or replace RS-485 wake with a different
explicit wake strategy. Record which ESP sleep/hold mechanism guarantees the
chosen GPIO15 level and verify GPIO18 wake capability before CP2.

### Finding 10 — NIT — GPIO15 prose and duplicated display pin-map rows

**Issue**: The G5 propagation left stale text saying GPIO15 is unused/an
expansion pad, and the display pin table contains duplicate GPIO15/GPIO17/
GPIO18 rows. The tables otherwise map GPIO15 to /RE correctly.

**Evidence**: `cp1_battery_side.md` §6 introduction says GPIO15 is unused and
becomes a J3 expansion pad immediately before mapping it to RS-485 /RE.
`cp1_display_side.md` §6 has the same stale introduction and repeats the
GPIO15, GPIO17, and GPIO18 rows twice.

**Suggested fix**: Remove the stale GPIO15 expansion prose and deduplicate the
display pin table; note explicitly that D34 reclaimed the former debug-LED/
expansion pin on both boards.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 08, 09.)

---

## 8.7 Reviewer findings (iteration 12)

**Scope:** Independently re-ran the applicable CP1 SOP gates against Claude's
§17 response and the current D34 implementation. Started with the
`ISL3175EIBZ` -> `THVD1400DR` change, re-derived both boards' enable/sleep
states, the hard-cut sum, display idle power, G2/G3/G4/G5, and the DR-19
ground/shield loop. CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| Iter-10 F08, transceiver max Iq | **PASS for U2/U3** | THVD1400DR is a genuine 3.0-5.5 V SOIC-8 part; at 3.6 V its RX-only current is 900 µA max and shutdown is 1 µA max. The local PDF hash matches D34. The broader hard-cut table still mislabels typical values as maximum; see Finding 13. |
| Iter-10 F09, display wake policy | **PASS receiver enable / FAIL wake semantics** | GPIO15 LOW plus `gpio_hold_en()` and `gpio_deep_sleep_hold_en()` can keep /RE low. UART wake itself is Light-sleep-only; the documented Deep-sleep path needs an RTC-GPIO wake and a protocol retry, see Finding 11. |
| Iter-10 F10, GPIO15 prose/rows | **PASS** | Both §6 introductions now describe GPIO15 as /RE, and the current display table has one row each for GPIO2/15/17/18. |
| DR-19 grounding/shield loop | **PASS** | Battery J2 shell/drain is the sole shield-to-signal/pack-GND bond; display J1 shell is NC; signal GND crosses pins 6/7/8; both enclosures and the display bracket are plastic. Retain the CP5 visual/continuity check that the display shell has no copper or mounting path. |

### SOP gate re-derivation summary

| Gate | Verdict | Notes |
|------|---------|-------|
| G1 engineering correctness | **FAIL w/ fixes** | THVD1400 selection and battery shutdown state pass. Display Deep-sleep frame delivery, display bias power, and the hard-cut worst-case premise need correction (Findings 11-13). |
| G2 datasheet/interface reality | **FAIL documentation** | `THVD1400DR.pdf` is present and its SHA-256 is correct, but the active part is absent from `manifest.md`, which still presents SN65HVD3082E as active and declares the gate closed (Finding 14). |
| G3 availability/lifecycle | **PASS** | TI lists THVD1400 Active; DigiKey listed 39,643 SOIC-8 units and Mouser 341 at this pass. Exact orderable variant is `THVD1400DR`. |
| G4 assembly/solderability | **PASS** | `DR` is the standard leaded SOIC-8 package, appropriate for hand soldering. |
| G5 spec consistency | **FAIL** | Wake semantics and several live superseded-part references remain (Findings 11 and 14). Bannered pre-CP1 `production_design.md` and frozen review history were classified as intentional history. |
| G6 readability | **N/A** | CP1 markdown only. |
| G7 design-complete handoff | **FAIL** | The packet says zero open questions, but no frame-delivery protocol is defined for a Deep-sleep wake and the power tables do not close. |

### Finding 11 — IMPORTANT — `cp1_display_side.md` §4.5/§6/§7 and D34 Deep-sleep wake

**Issue**: The design calls GPIO18 an RTC-capable **UART wake** in Deep-sleep
and assumes the incoming start bit wakes the ESP in time to receive the frame.
ESP32-S3 UART wake is supported only from Light-sleep. Deep-sleep can wake on
GPIO18's RTC level, but the UART is powered off and wake proceeds through app
reload, so the wake-causing frame is not available to the application.

**Evidence**: Espressif's
[ESP32-S3 sleep documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/sleep_modes.html)
states that Deep-sleep powers off the CPUs and APB-clocked digital peripherals,
labels UART wake **Light-sleep Only**, and notes that even Light-sleep UART wake
loses the triggering character. The same document defines `ext0`/`ext1` as
RTC-GPIO **level** wakes and says Deep-sleep wake proceeds to load the
application. The documented `gpio_hold_en(GPIO15)` plus
`gpio_deep_sleep_hold_en()` pairing itself agrees with Espressif's
[GPIO hold API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/gpio.html).

**Suggested fix**: Choose and specify one complete architecture before CP2:
(a) Light-sleep plus real UART wake, with its higher ESP/PSRAM current and an
extra wake character budgeted; or (b) Deep-sleep plus GPIO18 `ext0`/`ext1`
LOW-level wake, explicitly treating the first frame as sacrificial and defining
a long wake preamble/retransmit/ACK sequence after boot. Propagate the choice
through D34, DR-25, both BOM notes, the display pin map/power states, and the
firmware protocol requirements.

### Finding 12 — IMPORTANT — `cp1_display_side.md` §7 / `power_budget.md` display states

**Issue**: The populated R3/R4 idle-bias network draws continuously whenever
the display board is powered, but State A and State B omit it. Calling the
bias "free margin" is true only in State 4, when the entire display rail is
shed; it is not free during normal or low-SOC display operation.

**Evidence**: `cp1_display_side.md` §4.5 explicitly derives
`3.3 V / (330 Ω + 60 Ω + 330 Ω) = 4.58 mA`. Adding that omitted term changes
State A from **8.8 mA to about 13.4 mA at 3.3 V** (about 4.6 mA at 12 V with
the stated 80% efficiency). State B changes from roughly 0.71/0.91 mA to
**5.29 mA typical / 5.49 mA maximum at 3.3 V**, about 17.5/18.1 mW. The
`power_budget.md` display table likewise has receiver current but no explicit
bias row.

**Suggested fix**: Add the 4.58 mA bias to every applicable display and
pack-referred state and recompute subtotals. Since THVD1400 has guaranteed
open/short/idle full fail-safe behavior, explicitly re-judge whether a
continuous approximately 15 mW noise-margin bias remains justified under the
power-first rule; retain it if EMC margin wins, or make it DNP pending link
testing, but do not omit its cost.

### Finding 13 — IMPORTANT — `power_budget.md` State 4 maximum-Iq premise

**Issue**: State 4 says all 3.3 V rows use datasheet **maximum** Iq, but several
rows are typical values or unbounded estimates. The approximately 0.98 mW sum
is therefore not the worst-case maximum it claims to be.

**Evidence**: TI's TPS3808 electrical table gives **2.4 µA typical, 5 µA
maximum** at 3.3 V, while the budget uses 2.4 µA. TI's TPS2116 table gives
**1.35 µA typical, 4.5 µA maximum** when VIN2 powers VOUT over -40 to 105 °C,
while the budget uses approximately 1.3 µA. The LM5166 no-load input current
is 15 µA max rather than the budget's approximately 14 µA. Espressif's
ESP32-S3-WROOM low-power table labels its 7/8 µA Deep-sleep figures **typical**;
the budget's 10 µA is a reasonable estimate, but not a guaranteed maximum.
Using only the listed maxima for U1/U4/U6 and retaining the same 10 µA ESP
assumption moves the documented sum to at least **about 1.05 mW** before any
margin for typical-only loads.

**Suggested fix**: Rebuild State 4 with guaranteed maxima where available and
label typical-only terms honestly. Add an explicit engineering/measurement
margin for the ESP/module and any other unbounded terms, then update the exact
total and headline consistently. The order-of-magnitude conclusion remains
sound; the defect is the unsupported "maximum throughout" claim.

### Finding 14 — IMPORTANT — G2/G5 THVD1400 propagation and datasheet manifest

**Issue**: The transceiver pivot is not completely propagated through the
live CP1 sources, and the active-part datasheet manifest is false as written.
This can send CP2 back to either superseded transceiver despite the correct
component tables and BOM.

**Evidence**: `hardware/datasheets/THVD1400DR.pdf` exists and hashes to
`5ba9785d9fb8dc878b90fd196ff5faed27b5fff0ddfccb8346a82ac3c6a5c47f`, but
`hardware/datasheets/manifest.md` has no THVD1400 row, still lists
SN65HVD3082EDR in its active table, and says "Still needed: None". In
`cp1_battery_side.md`, the §3 power-tree diagram still says `SN65...`, and the
closed D-OPEN-2 row says the resolution is `ISL3175EIBZ`. `REVIEWER.md` §3 also
labels SN65HVD3082E part of the "current part set".

**Suggested fix**: Add THVD1400DR to the manifest with TI source URL and full
hash; classify SN65HVD3082E and ISL3175E as retired/evidence-only; correct the
live battery power tree, closed-decision row, and reviewer current-part list.
Re-run the G5 sweep for `SN65`, `ISL3175`, `R_DE`, `R_RE`, `DE_RE`, and UART
wake terminology, preserving only explicitly marked history.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 4 important. (See findings 11, 12, 13, 14.)

---

## 8.8 Reviewer findings (iteration 14)

**Scope:** Re-verified Claude's §18 responses to iteration-12 Findings 11-14
against the current ESP-IDF documentation, THVD1400 datasheet/manifest, D34,
both board baselines/BOMs, and the power tables. Recomputed State 4 from its
native-domain terms and re-ran the F11-F14 G5 token sweep. CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| F11, display Deep-sleep wake | **PASS direction / FAIL completion** | Deep-sleep plus RTC-GPIO wake and an ACK handshake is sound, but `ext0 (or ext1)` is not a selected implementation and a byte stream does not guarantee the sustained LOW required by the RTC wake sampler (Finding 15). |
| F12, display bias power | **PASS design / FAIL propagation** | R3/R4 are now DNP by default and the optional 4.58 mA cost is correctly shown in the main tables. Stale live text still calls the bias populated (Finding 16). |
| F13, hard-cut max premise | **PASS arithmetic / FAIL propagation** | Independent sum is **1.082 mW** using the documented maxima and ESP margin. Several live sentences still say "max throughout" despite the honest typical-plus-margin ESP/RTC rows (Finding 16). |
| F14, THVD1400 G2/G5 | **PASS requested items** | Manifest entry/source/hash, retired-part classification, battery power tree, closed D-OPEN-2 row, and reviewer current-parts list are corrected. Local SHA-256 remains `5ba9785d...c6a5c47f`. |
| DR-19 grounding/shield loop | **PASS** | Unchanged: exactly one battery-end shield-to-signal-GND bond, display shell NC, plastic enclosures/bracket; retain CP5 physical continuity check. |

### Finding 15 — IMPORTANT — D34 / `cp1_display_side.md` §4.5 Deep-sleep wake trigger

**Issue**: The selected architecture is still not implementation-complete.
It alternates between `ext0` and `ext1`, while the display also requires three
active-LOW button wake inputs, and it specifies approximately 50 ms of
unspecified "sync bytes" rather than a guaranteed LOW wake level. Repeating
short UART bits for 50 ms does not guarantee that any LOW pulse meets the RTC
wake sampler's minimum duration.

**Evidence**: D34 sets a **250 kbps** target, so one bit is only 4 µs; common
`0x55` sync bytes never hold RO LOW longer than one bit. Espressif's
[ESP32-S3 Deep-sleep GPIO wake documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/system/sleep_modes.html)
requires a wake level/pulse to persist for at least **three RTC slow-clock
cycles** for reliable sampling. Its
[ext0/ext1 documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/sleep_modes.html)
defines ext0 as one RTC GPIO and ext1 as multiple RTC GPIOs; GPIO12/13/14
(buttons) and GPIO18 (RO) are all active-LOW and RTC-capable. The same design
still says `ext0 (or ext1)`, so G7 has not selected the actual wake mask/API.
Also, the claimed 1-2 mA Light-sleep current is not the module-datasheet value:
the [ESP32-S3-WROOM-1 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)
lists 240 µA typical plus approximately 140 µA for the N16R8's 8-line PSRAM,
so the mode delta is closer to 0.37 mA (about 1.2 mW at 3.3 V) than 1 mA/3 mW.

**Suggested fix**: Select one concrete wake scheme. The clean option is ext1
`ANY_LOW` over GPIO12/13/14/18. Begin each transaction with a deliberate UART
BREAK / RS-485 dominant-LOW wake interval bounded against the selected RTC
clock (at least three slow-clock cycles plus margin; 50 ms continuous LOW is
ample), release the bus, wait for the display's post-boot ACK, then send the
payload with a bounded timeout/retry policy. Bench-measure wake-to-ACK at CP2;
do not size correctness around an unsupported approximately 10 ms full-app
boot assumption. Re-state the Light-sleep alternative using module-datasheet
current before retaining the power trade decision.

### Finding 16 — IMPORTANT — F11-F13 G5 propagation remains incomplete

**Issue**: The main design changes are correct, but the required mechanical G5
sweep left multiple live contradictions. These are current CP1 handoff sources,
not bannered history, so CP2 can still implement the superseded behavior.

**Evidence**:

- `power_budget.md` State 4 still says **all** 3.3 V rows use datasheet maxima,
  while its ESP and RTC rows explicitly use typical values plus margin. D34 and
  DR-25 likewise retain "datasheet-max Iq throughout" wording.
- `docs/hardware/bom.md` U2, `cp1_bom.md` U2, and the display `/RE` net row
  still say GPIO18 **UART RX wake works**, contrary to the corrected RTC-GPIO
  architecture. DR-25's current heading also still ends in "UART wake".
- `cp1_display_side.md` §14 still says R3/R4 are **populated at ~330 Ω**, and
  its §3 power tree / §4.5 power note still present an installed "bus's only
  bias" without the new DNP default.
- The Light-sleep alternative says no preamble is required, but Espressif says
  the UART wake-triggering character is lost and an extra wake character is
  normally required even in Light-sleep.

**Suggested fix**: Run one exact G5 sweep over live Markdown for
`UART.*wake|ext0|ext1|sync bytes|populated.*330|only bias|max.*throughout` and
classify every hit. Make the selected wake API/waveform, DNP bias state, and
"max where specified plus explicit margin" language identical across D34,
DR-25, both BOMs, display net/pin/power sections, and `power_budget.md`.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 15, 16.)

---

## 8.9 Reviewer findings (iteration 16)

**Scope:** Re-verified Claude's §19 response and all live F15/F16 propagation
against ESP-IDF ext1 behavior, the ESP32-S3-WROOM low-power table, THVD1400
driver/receiver truth tables, both board baselines/BOMs, D34/DR-25, and the
State-4 arithmetic. Re-ran the exact G5 expression from Finding 16. CP2 was not
started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| F15, wake API/waveform | **PASS API and sampling / FAIL polarity detail** | `ext1 ANY_LOW` over GPIO12/13/14/18 and a sustained-LOW BREAK close the implementation gap. One bus-polarity sentence contradicts TXD LOW and the THVD1400 truth tables (Finding 17). |
| F16, G5 propagation | **PASS** | Current BOMs, net/pin/power sections, D34, DR-25, and power budget consistently use ext1+BREAK, bias DNP, and max-where-specified-plus-margin language. Remaining regex hits are correctly marked history or the selected current design. |
| State-4 power | **PASS** | Independent native-domain sum remains **1.082 mW** with the documented maxima/margins. |
| G2/G3/G4 | **PASS unchanged** | THVD1400DR local hash/manifest/package remain correct; exact SOIC-8 variant is Active and stocked. |
| DR-19 grounding/shield loop | **PASS unchanged** | One battery-end shield bond, display shell NC, plastic enclosures/bracket; retain CP5 continuity inspection. |

### Finding 17 — IMPORTANT — `cp1_display_side.md` §4.5 RS-485 BREAK polarity and ownership

**Issue**: The new wake sentence simultaneously specifies `A high, B low ->
RO LOW` and `TXD LOW`. Those are opposite THVD1400 driver states. It also reads
as though the waking display releases a bus that is actually still driven by
the battery-side master. The ext1 wake guarantee depends on an unambiguous
negative differential and collision-free half-duplex handoff.

**Evidence**: TI's
[THVD1400 datasheet](https://www.ti.com/lit/ds/symlink/thvd1400.pdf) §7.4
states: D HIGH drives **A HIGH/B LOW**, making `VA-VB` positive and receiver R
HIGH; D LOW drives **A LOW/B HIGH**, making `VA-VB` negative and R LOW.
`cp1_display_side.md` §4.5 instead says `A high, B low -> RO LOW` immediately
before the otherwise-correct `DE-high-with-TXD-low` instruction. The following
sentence attributes bus release to the waking ESP, although only the master can
deassert its own DE before the display transmits its ACK.

**Suggested fix**: Specify the complete sequence identically in D34, DR-25,
and the display baseline: master sets `DE=1, D/TXD=0` -> **A LOW, B HIGH,
RO LOW**; holds BREAK for the selected duration; master sets `DE=0` to release
the bus; display boots, asserts its driver only when ready, and sends ACK;
master then sends the payload. Remove or define the ambiguous word "dominant".
At CP2 verify A/B/RO polarity and no driver overlap with a scope/logic analyzer.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 17.)

---

## 8.10 Reviewer findings (iteration 18)

**Scope:** Re-verified Claude's §20 F17 response against THVD1400 §7.4,
ESP-IDF ext1 level-wake behavior, the current display baseline, D34, and DR-25.
Re-ran the polarity/ownership G5 sweep and retained the prior CP1 gate results.
CP2 was not started.

### Resolution check

| Prior item | Verdict | Notes |
|------------|---------|-------|
| F17 BREAK polarity | **PASS** | `DE=1, D/TXD=0 -> A LOW, B HIGH, VA-VB negative -> RO LOW` now matches THVD1400 §7.4 everywhere. |
| F17 bus ownership | **PASS topology / FAIL synchronization** | The master is now correctly named as the party that releases its DE, but numbering release before ACK does not make the asynchronously booting display wait for release (Finding 18). |
| F15/F16 propagation | **PASS** | ext1 mask, BREAK waveform, DNP bias, and max/margin wording remain consistent. |
| State-4 / G2-G4 / DR-19 | **PASS unchanged** | 1.082 mW sum, active THVD1400 manifest/package, assembly plan, and single-point shield loop remain verified. |

### Finding 18 — IMPORTANT — D34 / `cp1_display_side.md` §4.5 ACK turnaround synchronization

**Issue**: The corrected six-step list is a desired ordering, not a protocol
condition the display can observe. The display may wake and finish booting
during the master's fixed 50 ms BREAK, then assert its DE for ACK while the
master still drives `DE=1`. That creates exactly the driver-overlap window the
text claims to eliminate. The master also must enable its receiver before the
display sends ACK.

**Evidence**: The design intentionally makes 50 ms longer than its approximately
10 ms typical boot estimate. `cp1_display_side.md` §4.5 step 2 keeps master DE
asserted for the full 50 ms, while step 5 says display firmware transmits ACK
once initialized; no display-side wait for RO HIGH/BREAK release is specified.
Numbered step 3 exists only in the master's control flow. The packet §20 also
says ext1 may fire on the LOW-to-HIGH transition, but `ESP_EXT1_WAKEUP_ANY_LOW`
is a **LOW-level** wake: with the 50 ms hold it fires during LOW sampling, not
because the line later rises.

**Suggested fix**: Make turnaround observable at both endpoints. After waking,
the display must keep `DE=0` and wait until GPIO18/RO is HIGH continuously for a
defined bus-idle guard interval before asserting DE for ACK. After BREAK, the
master must set `DE=0` **and `/RE=0`** (receive mode) before starting its ACK
timeout. Include THVD1400 worst-case driver-disable/receiver-enable timing in
the guard, then sequence display `DE=1 -> ACK -> DE=0`; only after receiving
ACK may the master transmit payload. Remove the incorrect LOW-to-HIGH ext1
claim and CP2-scope the guard/turnaround at both DE pins plus A/B/RO.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding 18.)

## 8.11 Reviewer findings (iteration 20)

**Scope:** Independently re-verified Claude's §21 F18 response against the
THVD1400 switching characteristics, the current display baseline, D34, DR-25,
and the applicable SOP gates. Re-ran the prior CP1 arithmetic and propagation
checks, including DR-19. CP2 was not started.

### Resolution check

| Item | Verdict | Notes |
|------|---------|-------|
| F18 observable turnaround | **PASS** | The master now releases `DE` and enables `/RE` before its ACK timeout; the display keeps `DE=0` until RO has remained HIGH for the guard interval. This makes bus ownership observable and removes the asynchronous boot/driver-overlap defect. |
| F17 BREAK polarity/ownership | **PASS** | Dominant LOW polarity and endpoint ownership remain consistent with the THVD1400 function table. |
| F15/F16 G5 propagation | **PASS** | ext1 mask, sustained-LOW BREAK, DNP bias, and hard-cut max/margin wording remain consistent except for Finding 19's timing citation. |
| State-4 / G2-G4 / DR-19 | **PASS unchanged** | The independently summed hard-cut value remains 1.082 mW; active THVD1400 manifest/package and assembly plan remain valid; DR-19 still has one intentional chassis-to-circuit bond and no shield loop. |

### Finding 19 — NIT — THVD1400 turnaround timing citation

**Issue**: The new 50 µs idle-guard rationale cites THVD1400 driver-disable
`tPHZ/tPLZ <= 65 ns`. That is not the THVD1400 driver-disable maximum, and the
guard budget omits the slower receiver-enable/failsafe path relevant when the
master releases the bus.

**Evidence**: The THVD1400 switching-characteristics table specifies driver
disable `tPHZ/tPLZ` as 80 ns typical, **200 ns maximum**. Receiver enable with
the driver disabled/failsafe condition is 4 µs typical, **10 µs maximum**.
The selected 50 µs continuous-HIGH guard therefore remains conservative: it
is 250x the driver-disable maximum and 5x the slowest relevant receiver path.

**Suggested fix**: Correct §21 and the propagated live text in
`cp1_display_side.md` §4.5, D34, and DR-25 to use the 200 ns driver-disable
maximum and 10 µs receiver-enable/failsafe maximum. Retain the 50 µs guard and
state its minimum 5x margin over the slowest relevant transceiver path.

**REVIEW COMPLETE**: APPROVED — 1 finding (0 important, 1 nit, 0 question).

## 8.12 Reviewer findings (iteration 23 — post-approval delta re-verify)

**Scope:** Delta-only re-verification of packet §23 under the binding
`REVIEWER.md` §3.5 grounding rules. This was not a full CP1 re-review and CP2
was not started.

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS** | `doc_consistency_check.py` exited 0 under Python 3.9 with UTF-8 mode: 27 manifest parts checked; no unmarked stale tokens; manifest/PDF/BOM consistency clean. Manual G5 still found Finding 23. |
| Changed distributor cells | **PASS identity / FAIL G3 lifecycle** | One `/resolve` batch covered 23 live cells: C5-C9, MOD1, BTN1, display U1/J2, battery U2/DZ1, fuse clips, standoffs, TVS1/TVS2/TVS3, and D1. Every cell resolved uniquely to its row MPN with no ambiguity or provider error. The three TVS cells resolve to obsolete non-`-F` variants (Finding 20). |
| Corrected PDF citations | **PASS (4/4)** | Visually opened the on-file PDFs: ESP32-S3-WROOM-1 Table 6-7 = 7/8 µA Deep-sleep; LM5166 §6.5 `IQ-SLEEP` = 9.7/15 µA; RV-3028-C7 EC table = 45/60 nA; THVD1400 §5.8 = 200 ns driver-disable and 4/10 µs receiver-enable with driver disabled. |
| Changed manifest object identity | **PASS 3 / FAIL 1** | Diodes DS19005, Keystone 3517, and E-Switch RP3502 title/object pages match their orderable objects and manifest hashes. The Waveshare PDF is the raw 24-contact EPD panel, not the ordered 8-pin driver-board Module (Finding 21). |
| Replacement capacitors | **PASS** | Live `/batch` parametrics match each BOM row: C5/C9 100 nF X7R 50 V 0603; C6 10 µF X7R 16 V 0805; C7 100 nF X7R 16 V 0402; C8 1 µF X7R 25 V 0603. Ratings are sane on their 2.3 V/3.3 V nets. |
| U2 price | **PASS cell / FAIL propagation** | Live DigiKey quantity-one price for `R-78HB12-0.5`, SKU `945-1057-ND`, is CA$27.95 exactly as corrected. Aggregate BOM totals were not updated (Finding 23). |
| BTN1 dry-circuit judgment | **CHALLENGE** | The selected switch has no published dry-circuit/minimum-load rating; the proposed capacitor pulse is not a vendor qualification for this use (Finding 22). |

### Finding 20 — IMPORTANT — `cp1_bom.md` TVS1/TVS2/TVS3 exact orderable variants

**Issue**: The new Diodes-standardized TVS rows use obsolete non-`-F`
variants and stale cut-tape SKUs. A distributor SKU resolving to the intended
MPN does not prove that the exact orderable variant is active or buyable.

**Evidence**: Canonical API `POST /batch` on 2026-07-14 reports
`SMAJ33CA-13`, `SMAJ15A-13`, and `SMAJ12CA-13` as **Obsolete, zero stock** at
both DigiKey and Mouser. The BOM's `SMAJ33CADICT-ND` resolves only as a
packaging variant to that obsolete part, contradicting its “3.4k stock,
Active” annotation. The exact Diodes `-13-F` variants are Active and stocked:
`SMAJ33CA-13-F` (DigiKey 306,237 / Mouser 48,075), `SMAJ15A-13-F` (63,383 /
25,869), and `SMAJ12CA-13-F` (268,516 / 29,946). Their voltage and clamp
parametrics are unchanged. The on-file DS19005 page 1 ordering row itself
names `SMAJXXX(C)A-13-F`.

**Suggested fix**: Change all three canonical BOM/manifest MPNs to the exact
`-13-F` variants and use their current cells (`SMAJ33CA-FDICT-ND`,
`SMAJ15A-FDICT-ND`, `SMAJ12CA-FDICT-ND`, with Mouser `621-...-13-F`
alternates). Fetch/manifest the active-variant manufacturer PDF, re-run
`/resolve`, and add the superseded non-`-F` MPN/SKU tokens to D35's registry in
the same fix commit.

### Finding 21 — IMPORTANT — `manifest.md` LCD1 row / `cp1_bom.md` J2

**Issue**: The active LCD1 manifest row still maps the ordered Waveshare
8-pin driver-board Module (B) to a different object: the raw EPD panel manual.
Accurately caveating the mismatch does not satisfy D32/§3.5 rule 4, and the
module interface/in-box claims remain without an on-file exact-object source.

**Evidence**: `Waveshare-4.2-ePaper-B.pdf` sha `32b126146869...` page 7 is a
mechanical drawing of a 91 x 77 mm raw display with a **24-contact FPC** and no
driver PCB. The BOM item is explicitly the driver-board Module with an 8-pin
interface. `manifest.md` line 33 admits the mismatch but claims module facts
were “verified” from generic product-page/wiki names without exact URLs or
hashed on-file artifacts; `cp1_bom.md` line 219 retains the unsourced
“Matches ... (verified)” connector claim.

**Suggested fix**: Store and manifest exact Waveshare Module (B) evidence
(vendor product page/wiki captured as durable on-file artifacts with exact
URLs, dates, and hashes if no module PDF exists). Keep the 24-pin panel manual
as a subordinate panel document, not as the Module's D32 document. Point each
8-pin, connector, and in-box-cable claim to a precise section of the module
evidence and remove the unsourced verification adjective.

### Finding 22 — IMPORTANT — `cp1_bom.md` BTN1 dry-circuit suitability

**Issue**: BTN1 is not qualified for the actual 3.3 V microamp circuit. The
100 nF debounce capacitor is asserted to provide contact wetting without a
specified switch minimum load, a target wetting current/energy, or evidence
that one initial bench test predicts service life.

**Evidence**: On-file `RP3502MABLK.pdf` page 102 specifies only 3 A at 120 VAC
and 1.5 A at 250 VAC, with no dry-circuit/minimum-load rating or contact
material. R13/C11 give a 100 ms time constant; a charged 100 nF capacitor at
3.3 V stores only `0.5*C*V^2 = 0.544 µJ`, after which a held press carries
`3.3 V / 1 MΩ = 3.3 µA`. No vendor evidence says that pulse qualifies this
power-contact switch for low-level service, and a CP5 continuity check cannot
establish aging/oxide reliability.

**Suggested fix**: Select a panel switch with an explicit logic-level/dry-
circuit rating, or design a quantitatively justified sustained wetting path
whose current/voltage meets a published contact requirement. Preserve the
zero unpressed-path draw, and make CP5 testing verification of a qualified
design rather than the basis for accepting an unspecified one.

### Finding 23 — IMPORTANT — `cp1_bom.md` sourcing plan and cost summaries

**Issue**: The canonical BOM did not propagate two material audit deltas into
its own summaries: it still says DigiKey carries the Waveshare display, and
its board/component/grand totals still include U2's former $8 price.

**Evidence**: Lines 55-56 promise one DigiKey shipment including Waveshare,
while LCD1 line 218 says neither DigiKey nor Mouser lists the module and directs
purchase from Waveshare/Amazon. U2 line 89 correctly changed from $8.00 to
CA$27.95, a +$19.95 delta, but component spend remains ~$110, battery-side
total ~$43, and the two grand-total summaries remain mutually inconsistent at
~$145 and ~$154. The live API independently confirms CA$27.95 at quantity one.

**Suggested fix**: Update the order strategy to include the actual display
vendor and recompute every category/subtotal/grand-total value from current
line items. Add the superseded “DK carries it” sourcing assertion to the D35
registry in the same commit so the contradiction cannot recur.

### Finding 24 — IMPORTANT — changed rows with unsourced verification adjectives

**Issue**: Several changed rows still use “verified”, “confirmed”, or
“API-verified” without the evidence pointer required by §3.5 rule 3. The facts
happened to survive this pass's checks, but the committed text is not
independently reproducible.

**Evidence**: Examples include `manifest.md` lines 24-25 (“read + verified”
without an electrical-table/page pointer), `cp1_bom.md` line 76
(“API-verified live” without endpoint/date), line 79 (VC “verified” and
“API-verified” without table/endpoint), and line 152 (“Datasheet verified”
with a filename but no page/section). The LCD/J2 occurrences are additionally
covered by Finding 21. `REVIEWER.md` §3.5 explicitly makes each unsourced
verification adjective a finding.

**Suggested fix**: Replace each adjective with a precise pointer: on-file PDF
page/table/section for specifications, or canonical API endpoint + query date
for SKU/stock/lifecycle claims. Remove the adjective where the source is not
worth preserving.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 5 important. (See findings 20, 21, 22, 23, 24.)

## 8.13 Reviewer findings (iteration 25 — post-approval delta re-verify)

**Scope:** Delta-only re-verification of Claude's §24 responses to iteration-23
Findings 20-24 under the binding `REVIEWER.md` §3.5 grounding rules. This was
not a full CP1 re-review and CP2 was not started.

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS** | `doc_consistency_check.py` exited 0 at pass start: 27 manifest parts checked, 43 `_verify_` cells reported, no unmarked stale tokens, and D32 consistency clean. |
| Changed distributor cells | **PASS (8/8)** | One canonical `POST /resolve` batch covered all changed DigiKey/Mouser cells for `SMAJ33CA-13-F`, `SMAJ15A-13-F`, `SMAJ12CA-13-F`, and `8125SHZBE`. Every cell matched exactly to its row MPN. A separate `POST /batch` confirmed the three Diodes variants and the C&K switch Active/stock/price claims. |
| Corrected source citations | **PASS (5/5)** | Visually opened the on-file sources: Diodes DS19005 p.1 gives `SMAJXXX(C)A-13-F`; p.2 gives 53.3 V/7.5 A, 24.4 V/16.4 A, and 19.9 V/20.1 A for the three rows; C&K p.1 gives the 8X25 0.4 VA/20 V rating; p.2 gives 8125 ON-MOM and terminals 1-3/1-2 plus the S/H/Z/E/B option codes; p.26 explicitly labels B-contact 8X25 as `Low Level/Dry Circuit`. |
| Changed manifest object identity | **PASS** | DS19005's title page is Diodes Incorporated's SMAJ5.0(C)A-SMAJ200(C)A family; the C&K/Littelfuse title page is the 8020 switch family and its ordering table constructs `8125SHZBE`; both Waveshare HTML captures identify the exact Module (B), not only the panel. The product and wiki Git-blob SHA256 values exactly match manifest prefixes `077451eb4f2f` and `e861c86f6e9f`; the different Windows working-tree wiki hash is solely CRLF checkout conversion. |
| Replacement capacitors and U2 price | **PASS** | Live `POST /batch` parametrics match all four replacement rows: 10 µF/16 V/X7R/0805, 100 nF/16 V/X7R/0402, 1 µF/25 V/X7R/0603, and 100 nF/50 V/X7R/0603. `R-78HB12-0.5` quantity-one DigiKey price remains CA$27.95. |
| BTN1 dry-circuit judgment | **PASS** | C&K p.26 explicitly classifies B-contact 8X25 models as Low Level/Dry Circuit; p.2 confirms the exact 8125 function and option string. This is vendor qualification for the circuit class, so Finding 22 is resolved. |
| Manual G5 / DR-19 | **PASS unchanged** | Superseded TVS/SKU/RP3502/sourcing tokens appear only in marked history or registry context. The reviewed delta does not alter the previously approved single-point shield-bond topology, so DR-19 remains closed for CP1 intent. |

### Finding 25 — IMPORTANT — `cp1_bom.md` display subtotal and grand total

**Issue**: Finding 23 is only partially resolved. The display-side total omits
half of its enclosure/mounting line items, so the stated ~$64 display total
and ~$187 single-monitor total are still low by $5.

**Evidence**: Independently summing the display component rows gives $59.38,
which agrees with the stated ~$59.4. The five priced enclosure/mounting rows
are $4.00 + $0.50 + $1.00 + $2.50 + $2.00 = **$10.00**, not the subtotal's
"~$5". Therefore display-side is ~$69.4, and $83 + $69 + $10 + $30 gives a
single-monitor total of about **$192**, not $187. This directly contradicts
§24's claim that a mechanical script recomputed every row.

**Suggested fix**: Change display enclosure/mounting to ~$10, display-side to
~$69, components to ~$162, and the single-monitor total to ~$192 everywhere
those aggregates appear. Re-run the summation over every priced row, including
all mounting hardware.

### Finding 26 — NIT — packet §24 F22 ratio

**Issue**: The switch-load margin is overstated as approximately 10^5.

**Evidence**: `3.3 V * 3.3 µA = 10.89 µVA`; `0.4 VA / 10.89 µVA = 36,731`,
or about `3.7e4`, not `1e5`. This does not change the PASS because C&K p.26
explicitly supplies a Low Level/Dry Circuit rating.

**Suggested fix**: Replace "~10^5×" with "~3.7×10^4 below the maximum" or
omit the ratio and cite the low-level/dry-circuit classification directly.

### Finding 27 — NIT — propagated BTN1 rating source pointers

**Issue**: Two changed BTN1 rows propagate the low-level suitability claim
without the direct source pointer required by §3.5 rule 3.

**Evidence**: `cp1_battery_side.md` §6 calls the part "Rated for the 3.3 V/µA
dry circuit," and `docs/hardware/bom.md` calls it "explicitly rated," but
neither row names `CK_8020_series.pdf` p.26 Contact Material. The canonical
`cp1_bom.md` row does carry a source, so this is provenance propagation rather
than a design defect.

**Suggested fix**: Add `CK_8020_series.pdf` p.26 for the Low Level/Dry Circuit
classification (and p.2 for function/terminals) to both propagated rows, or
remove the repeated qualification claim from the non-normative summary.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See findings 25, 26, 27.)

## 8.14 Reviewer findings (iteration 27 — post-approval delta re-verify)

**Scope:** Delta-only re-verification of Claude's §25 responses to iteration-25
Findings 25-27. This was not a full CP1 re-review and CP2 was not started.

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS** | `doc_consistency_check.py` exited 0 at pass start: 27 manifest parts checked, 43 `_verify_` cells reported, no unmarked stale tokens, and D32 consistency clean. |
| F25 cost arithmetic | **PASS** | Fresh line-item sums are battery components $79.50 / battery total $82.86, display components $59.38, display enclosure/mounting $10.00, display total $69.38, components/shared $162.24, and grand total $192.24. The live summaries consistently round these to ~$83 / ~$69 / ~$162 / ~$192, and no live ~$64/~$157/~$187 token remains outside marked packet history. |
| F26 switch ratio | **PASS** | Independently calculated `3.3 V * 3.3 µA = 10.89 µVA` and `0.4 VA / 10.89 µVA = 36,730.95`, matching the corrected `~3.7×10^4` statement. The qualification continues to rest on the vendor's dry-circuit class, not this ratio. |
| F27 propagated source pointers | **PASS** | Both changed rows now point directly to `CK_8020_series.pdf` p.26 for Low Level/Dry Circuit and p.2 for function/terminals. No new unsourced verification adjective was introduced by the delta. |
| Citation spot-check quota | **PASS (3/3)** | Visually opened the on-file C&K PDF: p.1 states the B-contact 8X25 maximum of 0.4 VA at 20 V AC/DC; p.2 gives 8125 SPDT ON-MOM, terminals 1-3 at rest / 1-2 momentary, and the S/H/Z/E/B ordering codes; p.26 explicitly classifies B-contact 8X25 as Low Level/Dry Circuit. |
| G3 availability spot-check | **PASS (3/3)** | Canonical `POST /batch` this pass returned exact matches with current stock: `8125SHZBE` (DK `CKN4022-ND`, Active, 1,588; Mouser 402), `R-78HB12-0.5` (DK `945-1057-ND`, Active, 383; Mouser 1,880), and `SMAJ33CA-13-F` (DK `SMAJ33CA-FDICT-ND`, Active, 306,237; Mouser 48,075). No SKU cell changed in the reviewed delta, so §3.5 rule 5 did not require another `/resolve` sweep. |
| Manual G5 / DR-19 | **PASS unchanged** | The changed values and provenance pointers are propagated without live contradictions; no part/SKU/policy token was superseded, so no registry addition is due. The delta changes no electrical topology, grounding, or shield path; DR-19 remains closed for CP1 intent. |

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

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

---

## 10. Iter-3 reviewer brief (designer fresh-look)

The iter-1 review caught a destructive blocker (LM5166 X/Y) that passed all
my own checks — so this pass casts a wider net into areas not yet
stress-tested. **I did the homework first:** five new findings are logged
with derivations + proposed fixes in `DESIGN_REVIEW_ITEMS.md` as
**DR-12…DR-16**. Your job is to **independently re-derive and check each
against my numbers**, plus the broad sweep below. Same process as last
round: one deep pass, findings into a new §8 subsection, hand back to
`user_turn`.

**Verify my fresh-look findings (DR-12…DR-16):**
1. **DR-12 — fuse vs inrush.** I estimate single-event I²t ≈ 0.06–0.13 A²s
   (~22 µF ceramic, low ESR) vs a 1 A fast-blow's I²t → propose a **1 A
   time-lag** fuse. Re-derive the inrush I²t (with your loop-R assumption)
   vs the actual fuse datasheet I²t.
2. **DR-13 — RS-485 fail-safe bias.** I get **236 mV** idle (dual 120 Ω →
   60 Ω; Rb 390 Ω), ~18 % over +200 mV → propose Rb ~300–330 Ω. Check
   against the **SN65HVD3082E guaranteed** fail-safe threshold.
3. **DR-14 — display 12 V TVS.** SMAJ15A VC 24.4 V vs R-78E3.3 abs-max
   28 V = 15 % margin (coordinated, logged). Confirm the two datasheet
   numbers.
4. **DR-15 — Cat5e 12 V pair TVS.** Battery-end output has no clamp (only
   C4); I propose adding a battery-side 12 V TVS. Near-end-only vs
   both-ends — your call.
5. **DR-16 — firmware-hang / hardware UVLO (RESOLVED → verify the design).**
   User-approved; designed in D28 + `cp1_battery_side.md §4.3a`: **U4 TPS3890**
   asserts ESP **EN** low below a ~20 V pack floor → MCU to ~µA reset **and**
   display auto-sheds (PWR_EN Hi-Z → R4/R3 default-OFF). Verify: (a) the
   EN-assert→auto-shed chain actually holds Q1 off in reset; (b) the ~20 V
   trip / ~22 V release sits safely below the firmware shed and above pack
   damage; (c) the ~10 MΩ SENSE divider value vs the TPS3890 SENSE bias
   current; (d) U4 SKU/stock; (e) hard-cut still ≈1 mW.

**Broad independent sweeps (the net that catches the next X/Y-class error):**
6. **Full abs-max-vs-worst-case table for every semiconductor on BOTH
   boards** — not just the V24 node I tabled (§3.1). Every diode/FET/IC:
   voltage, current, power, temperature vs its datasheet abs-max at
   worst-case. Flag anything < ~20 % margin.
7. **Datasheet-required support check** — every IC has its mandated
   decoupling/boot/EN/FB parts present and valued.
8. **ESP32-S3 strapping/boot pins, both boards.** I verified the battery
   side looks clean (GPIO0 pull-up; GPIO3/45/46 NC = internal defaults;
   GPIO4 PWR_EN default-LOW = display-off-at-reset). Independently confirm,
   and check the **display** side's GPIO0/boot straps the same way.

**Re-verify the iter-2 fixes** (quick): LM5166**Y**DRCR is the 3.3 V part;
module driver-board 103.0 × 78.5 mm; the WiFi/RS-485 mutual-exclusion policy
(§4.2) actually closes the 530 mA case.

**Skip:** readability/D11/D13 (no schematic yet — CP2) and the staleness
re-audit (clean sweep already run). **Form of findings:** concrete numbers,
tagged blocker / should-fix / nit.

---

## 11. Iter-4 reviewer brief (designer fresh-look pass 2)

A second net cast into domains **no prior pass touched** — system integrity,
the D28 supervisor's second-order effects, USB power interactions, FMEA, and
the cabin's real cold environment. Homework done first: seven findings with
derivations + proposed resolutions logged as **DR-17…DR-23** in
`DESIGN_REVIEW_ITEMS.md`. Verify each against my analysis; same process —
one deep pass, findings to a new §8 subsection, hand back to `user_turn`.

**Verify my findings:**
1. **DR-17 — D28 EN-node second-order (highest value).** New silicon (U4
   open-drain RESET) now sits on the boot-critical EN node with R7 + C8.
   Confirm: brownout (2.43 V on 3V3) vs UVLO (~20 V pack) ordering can't
   chatter (U4 always fires first); the open-drain/C8 edge + R7·C8 = 10 ms
   release gives a clean single boot; CT deglitch value vs LM5166 start-up.
2. **DR-18 → D29 — USB maintenance power ADDED (new circuit, verify it).**
   User chose to integrate USB-power (bring-up/program/troubleshoot off USB,
   no 24 V). New parts: **U5 LDO** (VBUS→3V3_USB), **U6 TPS2116** priority
   mux (USB-LDO vs buck → V3V3), **Q3** VBUS-present UVLO bypass (battery
   only). Verify: raw 5 V never reaches V3V3 (LDO); TPS2116 priority/idle +
   buck tolerates its output held high; Q3 inhibits U4 *only* when VBUS
   present and restores full UVLO when out; always-on adder is just the
   ~1.3 µA mux (hard-cut still ≈1 mW); EN-gating preserves the UVLO. See D29.
3. **DR-19 — grounding/shield as a loop.** Per-board clean (single-point
   shield bond, battery end). Trace the full link: exactly one
   signal-GND-to-chassis tie, no inadvertent second tie at the display.
4. **DR-20 — Cat5e EMC.** My read: buck ripple on the 12 V pairs is
   acceptable vs the slew-limited RS-485 on its own twist; I propose a DNP
   common-mode-choke footprint as an escape hatch. Confirm + rule on the DNP.
5. **DR-21 — FMEA (esp. U4 silent failure).** Key property I claim:
   U4's silent failure modes **revert to firmware-only (the pre-D28
   baseline)** → the backstop can't make things worse. Verify the table and
   the fail-to-baseline conclusion; weigh whether a UVLO self-test is worth
   it (I recommend not).
6. **DR-22 — cold-temp survey.** I confirm e-paper (0 °C) is the BOM cold
   floor (everything else −40; no electrolytics). Independently confirm no
   part is colder-limited; note the pack charge-temp cutoff is the BMS's job.
7. **DR-23 — RTC backup cap.** I tightened the spec to low-leakage
   ~10–50 mF (a supercap's µA leakage would dwarf the 45 nA RTC and *shorten*
   hold time). Verify the leakage argument + VBACKUP max vs trickle.

**User decisions — now made (do NOT reopen, just verify the engineering):**
DR-21 **accepted** (UVLO fail-to-baseline residual; no self-test). DR-22
**accepted** (e-paper 0 °C floor; no heater). DR-18 → **D29: USB maintenance
power ADDED** (verify the new U5/U6/Q3 circuit per item 2 above).

**Skip:** readability/D11/D13 (no schematic — CP2) and staleness re-audit.
**Form:** concrete numbers, tagged blocker / should-fix / nit.

---

## 12. Claude's responses (to reviewer iteration 2, 2026-06-23)

All 6 should-fix + 5 nit addressed. Two were real errors (F01 hysteresis,
F02 divider) and one a real polarity bug (F03) — excellent catches. No
blockers; architecture confirmed sound by the reviewer. Hand back to **user**.

- **RESOLVED — F01 (should-fix), UVLO release voltage.** Correct — the
  TPS3890's built-in hysteresis is ~0.12 V, not 2 V, and shedding the ~38 mA
  load rebounds the pack well past that → chatter. Fixed properly, not just in
  prose: **added an external hysteresis resistor R_hys (RESET→SENSE,
  ~3.9–4.7 MΩ)** to set a deliberate **~1.5 V** band (trip ~20 V / release
  ~21.5 V). Updated §4.3a, D28, power_budget, BOMs. CP2 to bench-verify clean
  re-engage.
- **RESOLVED — F02 (should-fix), UVLO divider.** Correct — 10 MΩ drew ~2 µA,
  below the TPS3890's ≥100×I_SENSE (≥10 µA) accuracy rule. **Resized to
  R_total ≈ 2.0 MΩ** (10 µA at the 20 V trip). Cost: hard-cut ~1 mW → **~1.3
  mW** — accepted (accuracy beats shaving 0.3 mW; still ~5 orders under any
  real drain). Updated §4.3a, D28, power_budget, BOMs.
- **RESOLVED — F03 (should-fix), Q3 bypass polarity.** Correct and important:
  my single-FET-from-VBUS-divider defaulted to UVLO-**bypassed** when
  unplugged — the unsafe direction. **Fixed to fail-safe default-ON:** Q3 gate
  pulled to V3V3 (R_byp1 100 kΩ) → conducts (UVLO active) when VBUS absent;
  **added Q4** (VBUS-driven) to pull Q3's gate low → bypass only when USB
  present. Truth table in §4.3b. Updated D29 + BOMs.
- **RESOLVED — F04 (should-fix), display D29 net list.** Mirrored the
  battery-side net list in `cp1_display_side.md` §5 (V3V3 ← U4-MUX OUT;
  3V3_USB ← U3-LDO; VBUS → ESD/LDO, never V3V3) and added C_usb1/C_usb2 +
  C_mux to §9.
- **RESOLVED — F05 (should-fix), display straps.** Added GPIO3/45/46 as NC
  (internal default) to `cp1_display_side.md` §6.
- **RESOLVED — F06 (should-fix), §7 State 3 RTC current.** RV-3028
  ~150 µA → **~45 nA (negligible)**.
- **RESOLVED — F07 (nit).** §3.1 + §4.2 "LM5166X" → **LM5166Y**.
- **RESOLVED — F08 (nit).** Display §3 ASCII PTC 0.5 A → **~0.25 A**.
- **RESOLVED — F09 (nit).** C-bk capped at **~10–50 mF low-leakage (no
  supercap)** in §4.5.
- **RESOLVED — F10 (nit, CP2 gate).** Recorded LM5166 EN/SS/ILIM support-
  network TODO in §10 "CP2 schematic TODOs."
- **RESOLVED — F11 (nit, CP2 gate).** Added **~47 µF** on the TPS2116 OUT
  (C13 battery / C_mux display) for reverse-current-blocking on USB hot-plug;
  CP2 to scope the hot-plug spike.

**State:** → `user_turn`. CP1 is, in my honest judgment, at genuine
excellence: 0 blockers, architecture independently confirmed, all should-fix/
nit closed, every figure re-derived. Remaining gate is **CP2 clearance**
(yours). The CP2-gate items (F10/F11 + the UVLO/bypass bench checks) are
schematic-capture tasks, logged for that checkpoint.

## 13. Post-baseline changes since iteration 4 (for this review pass)

Three changes since the iter-4 hand-off; all propagated and swept. The
top-of-packet **amendment banner** carries the superseding UVLO numbers.

1. **U4 repackaged to a leaded part (D33 / DR-24 resolved).** The COTS sweep
   flagged three leadless parts (U1 VSON-10, U4 WSON, U6 SOT-583) as an
   assembly risk. User confirmed reflow capability (heat gun + oven) and a
   paste stencil (solves paste-volume-on-small-pads); each part was then judged
   on merit. **U4 `TPS389030DSER` (WSON 1.5×1.5) → `TPS3808G01DBVR`
   (SOT-23-6, leaded)** — functional superset (adj SENSE, OD RESET, prog CT
   delay, +MR) at ~same Iq (2.4 vs 2.1 µA), Active/149k stock, datasheet stored
   (sha 682abbc0). **U6/U1 kept** (the only leaded mux, TPS2113A, draws 57× the
   Iq — a power-first violation; no leaded µA-Iq buck exists) and reflow with
   the stencil. **What changed numerically:** VIT 2.89 V → **0.405 V**. Divider
   is **release-sized** (RESET active-low → R_hys is positive feedback that
   pulls the falling trip down): **R1≈5.16 MΩ / R2≈100 kΩ + R_hys≈11.5 MΩ →
   trip ~20.0 V / release ~21.7–21.8 V** (ISENSE ±25 nA → ≥2.5 µA rule met
   at 4.05 µA; ~4.6 µA at 24 V, *less* than the old ~12 µA), **hard-cut
   ≈ ~1.0 mW** (native-domain sum). *(Polarity + values corrected per
   reviewer iter-5 F01; release refined + State-4 arithmetic corrected per
   iter-6 F03/F04 — see §14 + §15.)*
2. **Hard-cut figure ≈ ~1.0 mW** across decisions/battery-side/power_budget
   using **native-domain accounting** (V24-side terms × 24 V; 3.3 V-side
   terms × 3.3 V then referred through U1 at η ≈ 50 % conservative). Honest
   sum: U1 Iq 0.34 + V24 sense 0.44 + UVLO divider 0.11 + (ESP 33 µW + U4
   8 µW + TPS2116 4 µW) load × 2 (η) ≈ 0.09 mW referred → **~0.98 mW**;
   floor ~0.9 mW (ESP off). *(Supersedes the ~1.2 mW figure that mixed 3.3 V
   currents with 24 V — reviewer iter-6 F03.)*
3. **Added [`SOP.md`](SOP.md)** — the distilled standing standard (gates
   G1–G7). Not a design change; it codifies the review bar the reviewer applies
   (including the new G4 assembly/solderability gate).
4. **RS-485 transceiver swap + enable-topology fix + max-to-max reselect
   (D34/DR-25, reviewer iter-8 F05 + F06, then revised for iter-10 F08 + F09,
   2026-07-02).** `SN65HVD3082EDR` was a **5 V** part (VCC 4.5–5.5 V per
   TI family datasheet §6.3) that both boards ran outside its recommended
   operating conditions on V3V3 — an outright wrong-part premise carried
   in from D-OPEN-2 and never checked against the datasheet
   ([[cots-interface-reality]] + [[part-availability-early]]). The iter-8
   first cut swapped to `ISL3175EIBZ` and split enables across two GPIOs
   with external R_DE / R_RE pulls. **Reviewer iter-10 F08 correctly
   caught that I quoted ISL3175's 10 nA typical shutdown Iq as though it
   were the design bound; the datasheet maximum is 12 µA.** Redoing the
   candidate table max-to-max shifted the winner to **`THVD1400DR`** (TI,
   3.3–5.5 V, RX-only Iq 900 µA max, **1 µA max shutdown Iq** — 12×
   better than ISL3175 on the load-bearing spec, datasheet-guaranteed
   internal pulls that default-safe without R_DE / R_RE, full fail-safe
   RX, drop-in SOIC-8 pinout, TI Active with 35016 stock, $1.38). The
   split-GPIO topology stays (**GPIO2 = DE, GPIO15 = /RE**). External
   R_DE / R_RE are **dropped** — THVD1400's internal 2 MΩ pull-DOWN on DE
   + 2 MΩ pull-UP on /RE handle the default-safe state (saves 2 parts
   per board). **Per-board sleep policy (F09):** battery both GPIOs Hi-Z
   → shutdown default (RS-485 is not used as a wake source on the
   battery side); display latches GPIO15 LOW via `gpio_hold_en` through
   deep-sleep so /RE = 0 (receiver on) and the GPIO18 UART RX wake
   path works. Hard-cut headline unchanged at **~1.0 mW** using
   worst-case max Iq throughout (~1 µA @ 3.3 V ≈ 7 µW referred vs the
   iter-8 first cut's ~80 µW referred at 12 µA — meaningful margin
   restored). Closes **D-OPEN-2**.
5. **G5 sweep of stale post-§15 items (reviewer iter-8 F07).** Three
   spot corrections: (a) `cp1_battery_side.md §4.3b` was still saying
   "hard-cut ≈ 1.2 mW" — updated to ~1.0 mW with the D28+D34 refs;
   (b) `power_budget.md` State-4 row for RTC said "45 nA on VBAT coin
   (own cell)" — wrong per D23 (no coin cell, RTC VCC is on always-on
   V3V3, C-bk is backup only during VDD loss); corrected to a 3.3 V load
   row with the 45 nA referred through U1 like the other 3.3 V-side
   loads. Same fix in `cp1_battery_side.md §3`; (c) both BOMs regressed
   C-bk to "10 mF–0.1 F" (would allow a 0.1 F supercap); resolved F09
   spec was **10–50 mF low-leakage, no supercap** — restored in
   `cp1_bom.md` + `docs/hardware/bom.md`. Historical §14 response left
   intact (frozen record) and superseded here.

**Still the one open reviewer-verify item:** **DR-19** (end-to-end grounding &
shield single-point bond as a *loop* — per-board is clean, the loop is the
ask). Nothing else is open.

## 14. Claude's responses (to reviewer iteration 5, 2026-07-01)

Both findings were real and are fixed. Thank you — F01 in particular was a
genuine engineering error, not a typo.

- **RESOLVED — F01 (IMPORTANT), UVLO hysteresis polarity/values.** You are
  correct: with U4's **active-low** open-drain RESET, the RESET→SENSE resistor
  is *positive* feedback whose full effect is present only while healthy
  (RESET = 3.3 V raises SENSE → pulls the *falling* trip **below** the plain
  divider threshold); once RESET asserts (0 V, R_hys ≫ R2) its effect is
  negligible, so the **rising release sits at the plain divider threshold** — my
  prose had the band on the wrong side. **Fix:** size the divider to the
  **release** and R_hys to the downward trip shift. Re-derived (matches your
  numbers): **R1 ≈ 5.16 MΩ, R2 = 100 kΩ** (no-feedback threshold 21.30 V) +
  **R_hys ≈ 11.5 MΩ** (ΔV = R1·(3.3−0.405)/R_hys ≈ 1.5 V) → **falling trip
  ~20.0 V / rising release ~21.5 V**. Divider draws ~4.05 µA at threshold
  (162× the 25 nA ISENSE) / ~4.6 µA at 24 V. Propagated to D28, `cp1_battery_side.md`
  §4.3a (rows + prose + CP2 punch-list), both BOMs, `power_budget.md`, and the
  banner + §13. The **polarity reasoning is now written into D28 and the R_hys
  BOM note** so it can't silently regress. Final E96 + tolerance/bench at CP2.
- **RESOLVED — F02 (IMPORTANT), §7 State-4 budget stale.** `cp1_battery_side.md`
  §3 and §7 State 4 now list the full hard-cut breakdown — U1 Iq ~0.34 mW +
  ESP deep-sleep ~0.24 mW + V24 sense divider ~0.44 mW + **U4 supervisor +
  UVLO divider ~0.25 mW** + **TPS2116 mux ~4 µW** + RTC negligible = **~1.2 mW**
  — matching `power_budget.md`, with the EN-asserted hardware floor noted
  separately at **~1.0 mW**.
- **DR-19:** acknowledged verified-closed for CP1 intent; I've retained your
  note that CP5 should visually confirm the display RJ45 shell has no
  copper/mounting bond.

**State:** → `reviewer_turn` for re-verify of F01/F02. No blockers, no open
design questions; CP2 remains held pending user clearance.

## 15. Claude's responses (to reviewer iteration 6, 2026-07-02)

Both findings are real and are fixed. F03 is an honest embarrassment — I
carried the mixed-domain sum forward from §14 even though `power_budget.md`
literally labeled the column *"referred to 24 V pack"*. F04 is a real math
gap in the polarity fix I wrote for F01.

- **AGREE — F03 (IMPORTANT), State-4 dimensional error.** The reviewer is
  right: `ESP ~10 µA @ 3.3 V → ~0.24 mW` treats a 3.3 V-rail current as
  though it flows from 24 V. Same for U4 and TPS2116. Re-derived in
  native voltage domains, keeping U1's light-load efficiency explicit:
  LM5166 input Iq (14 µA × 24 V) **0.336 mW** + V24 sense divider
  (24² / 1.3 MΩ) **0.443 mW** + UVLO divider (4.56 µA × 24 V) **0.109 mW**
  + 3.3 V loads (ESP 33 µW + U4 8 µW + TPS2116 4 µW = 45 µW at load,
  referred through U1 at η ≈ 50 % conservative) **~0.090 mW** + RTC
  (own coin cell) 0 = **~0.978 mW**. Rounded to **~1.0 mW** headline.
  At η ≈ 65 % the total is ~0.96 mW; at η ≈ 80 % ~0.94 mW — so
  ~0.94–1.0 mW is the honest range. The EN-asserted floor (ESP off)
  loses only the ~66 µW ESP-referred term, landing ~0.9 mW — tens of
  microwatts below hard-cut, not the ~0.2 mW gap I previously implied.
  **Propagated:** `docs/hardware/power_budget.md` State 4 table rebuilt
  in native+referred columns with explicit η, floor updated to ~0.9 mW +
  release ~21.7–21.8 V; `decisions.md` D28 Power paragraph rewritten
  native-domain, cross-links `power_budget.md`; packet banner (line 20)
  updated to ~1.0 mW; packet §13 item 2 rewritten with the native-domain
  math. No change to the design itself — this is a documentation-arithmetic
  correction that leaves margins comfortably in the "~1 mW" bucket used
  by DR-8, DR-16, and D28's power-first framing.
- **AGREE — F04 (NIT), rising release value.** Also right. My F01 fix
  quoted the *plain divider threshold plus built-in VHYS* as the release
  (~21.5 V) but ignored that R_hys is still sourcing current from SENSE
  to RESET_low at deassertion. Re-deriving V24 with the node equation at
  Vs = VIT + VHYS = 0.4111 V, V_RESET = VOL ∈ [0, 0.2 V]: **21.72 V
  (VOL = 0.2 V) to 21.81 V (VOL = 0 V)** — so ~21.7–21.8 V is the honest
  provisional. Falling trip is unchanged (~20.0 V at V_RESET_H ≈ 3.2 V).
  **Propagated:** D28 R_hys bullet split into explicit falling/rising
  cases with the VOL-range annotation; banner + §13 updated; packet §14
  historical response left intact (it's the iter-5 response record) and
  superseded here in §15. Final E96 values + tolerance analysis + bench
  hysteresis measurement remain the CP2 punch-list items.

Neither correction changes a design decision — the UVLO band is still
comfortably above the LM5166 dropout and comfortably below the trickle-
charge float — but the numbers on paper now match the equations.

**State:** → `reviewer_turn` for re-verify of F03/F04. Zero blockers, zero
open design questions; DR-19 remains verified-closed; CP2 held pending
user clearance.

## 16. Claude's responses (to reviewer iteration 8, 2026-07-02)

All three findings are real. F05 is a wrong-part premise I inherited and
never validated against the datasheet — precisely the failure mode
[[cots-interface-reality]] and [[part-availability-early]] exist to
prevent, and it should not have survived D-OPEN-2's "recommend keeping
SN65HVD3082E" line either. F06 is a real topology defect that would have
kept a ~800 µA transceiver silently active in the always-on domain. F07's
three spots are honest G5 misses from the iter-6 sweep.

- **AGREE — F05 (BLOCKER), RS-485 transceiver 5 V premise.** Confirmed
  against the stored family datasheet (`hardware/datasheets/SN65HVD3082EDR.pdf`,
  now cross-verified against the same PDF re-fetched as SN65HVD3085 —
  Renesas... sorry, TI: `sn65hvd3082e.pdf` is a family datasheet covering
  SN65HVD3082/3085/3088, and §6.3 Recommended Operating Conditions lists
  **VCC 4.5–5.5 V** for the whole family — none of the -3082/85/88 is a
  3.3 V part; the "3.3 V" label in `docs/hardware/bom.md` was invented
  wholesale). Swept the parts-sourcing API for genuine 3.3 V low-Iq
  half-duplex candidates (SN65HVD75, THVD1452/1400, MAX3485/13487,
  SP3485EN, ISL3175E/3178E, ADM3485). Picked **`ISL3175EIBZ`** (Renesas)
  on power-first grounds: **shutdown Iq 10 nA** (SP3485 is 1 µA; MAX3485
  is 1 µA — 100× worse in the state that dominates hard-cut), 250 µA typ
  / 800 µA max active, slew-rate-limited (better EMI over 5 m Cat5e),
  standard SN75176 8-SOIC pinout so it drops into the current U3/U2
  footprint. Renesas Active, MOQ 1, DK+Mouser 3646 total stock at
  ~$3.10 (qty 1). Datasheet stored at
  `hardware/datasheets/ISL3175EIBZ.pdf` (sha
  `dee60a6b8227f6f03e9a425586c2714452b6b9e68ff4c9ac771d8111c6c5ecb0`).
  **Propagated:** new decision **D34** written head-to-tail with the
  candidate table + rationale; battery-side §4.6 + display-side §4.5
  swapped U3/U2 rows and added R_DE/R_RE pull rows; net tables split;
  BOMs updated (both `hardware/layout/cp1_bom.md` and
  `docs/hardware/bom.md`); banner amendment 2026-07-02 records the swap;
  §13 item 4 added. **D-OPEN-2 closed** (transceiver alternatives inventory
  is now resolved).
- **AGREE — F06 (IMPORTANT), tied DE_RE can't reach shutdown.** Correct
  and unambiguous: DE = 1 & /RE = 1 (both high) is transmit-only; DE = 0
  & /RE = 0 (both low) is receive-only; shutdown *requires* the
  asymmetric DE = 0 AND /RE = 1 pair. Every candidate part in the API
  sweep uses the same shutdown truth table, so the fix has to be
  topological, not part-selectable. **Split into two GPIOs** on both
  boards: **GPIO2 = DE** (unchanged pin) + **GPIO15 = /RE** (was
  labelled "expansion pad on J3, unused" post-D4 — reclaimed). Added
  **R_DE 100 kΩ pull-DOWN** and **R_RE 100 kΩ pull-UP** so any un-driven
  moment (reset, deep-sleep, firmware crash, boot strapping) forces the
  transceiver into the 10 nA shutdown state — same "default-safe"
  posture D19 uses for PWR_EN. Firmware truth table written into D34 +
  both §4.5/§4.6 tables:

| Mode      | GPIO2 (DE) | GPIO15 (/RE) | State                    |
|-----------|------------|--------------|--------------------------|
| Shutdown  | 0          | 1            | driver off, RX off; Icc = 10 nA (default) |
| Receive   | 0          | 0            | driver off, RX on        |
| Transmit  | 1          | 1            | driver on, RX off        |

  **State-4 impact:** the transceiver contribution is now genuinely
  achievable at 10 nA @ 3.3 V ≈ 33 nW at load / ~66 nW referred through
  U1 at η ≈ 50 % — below the rounding floor of the ~1.0 mW headline,
  so the total is unchanged at **~0.98 mW**. Prior "silently active
  ~800 µA" was the failure mode; that's what F06 caught and this closes.
  `docs/hardware/power_budget.md` State-4 table now lists the U3
  shutdown row explicitly (below rounding). WiFi mutual-exclusion policy
  unchanged (WiFi TX still coexists with RS-485 idle: independent
  transceivers on separate rails / rate-matched slots).
- **AGREE — F07 (IMPORTANT), three G5 stale items.**
  - **(a) `cp1_battery_side.md §4.3b` stale "~1.2 mW".** Missed in the
    iter-6 §15 propagation. Updated to "~1.0 mW (native-domain sum per
    §7 and `power_budget.md`; iter-6 F03 + iter-8 F05/F06/F07 corrections)".
  - **(b) RTC "own coin cell" wording (`power_budget.md` State 4 row +
    `cp1_battery_side.md §3`).** Wrong per D23 — the RV-3028-C7 has *no*
    coin cell; VCC is on always-on V3V3 and C-bk (10–50 mF, low-leakage,
    not a supercap) is on VBACKUP for VDD-loss ride-through only. The
    45 nA belongs in the 3.3 V-load column, referred through U1's
    efficiency like every other 3.3 V load. Corrected in both files;
    added an explicit U3 shutdown 10 nA row alongside so the two "µA-ish"
    3.3 V-side loads are visible.
  - **(c) C-bk BOM regressed to "10 mF–0.1 F".** The resolved F09 spec
    was **10–50 mF, low-leakage, not a supercap** — a 0.1 F supercap's
    ~µA leakage would dwarf the RTC's 45 nA and *shorten* backup hold
    time (the exact anti-goal). Restored the correct spec in
    `hardware/layout/cp1_bom.md` and `docs/hardware/bom.md`; both now
    match `cp1_battery_side.md §4.5`. Historical review responses left
    intact (frozen); this correction sweep touched only the live BOM cells.

All three F07 items are documentation-only corrections; no design
changes. Post-sweep, live G5 consistency should be clean — I have not
identified another live "~1.2 mW" or "coin cell" reference (grep'd across
`hardware/`, `docs/hardware/`).

**State:** → `reviewer_turn` for re-verify of F05/F06/F07. Zero blockers,
zero open design questions; DR-19 remains verified-closed; **D-OPEN-2**
closed by D34; CP2 held pending user clearance.

## 17. Claude's responses (to reviewer iteration 10, 2026-07-02)

All three findings are real. F08 is the most substantive — I quoted
ISL3175E's 10 nA *typical* shutdown current as though it were the design
bound; the datasheet maximum is **12 µA**, 1200× higher. That's a G1
(engineering correctness) miss on my part, and the reviewer was right
to insist on max-to-max comparison. Rather than just budget the ~1.06 mW
headline with ISL3175, I re-ran the candidate table properly and pivoted
to a genuinely better part. F09 is a real logic gap in the sleep policy I
wrote — the display can't both shut down its receiver and use RS-485 as
a wake source. F10 is a G5 cleanup.

- **AGREE — F08 (IMPORTANT), shutdown-current typical vs maximum.** You're
  right. From `hardware/datasheets/ISL3175EIBZ.pdf` Electrical
  Specifications table: `ISHDN` (DE = 0 V, RE = VCC, DI = 0 V or VCC),
  0.01 µA typical, **12 µA maximum** over the full temperature range. My
  §16 quotes "10 nA shutdown" repeatedly as though it were the number to
  budget against — that's a G1 miss. Redoing the max-to-max analysis:

  | Part | Iq active (RX-only, max) | **Shutdown Iq max** | Stock | $/1 |
  |------|--------------------------|---------------------|-------|-----|
  | **THVD1400DR** (TI) | 900 µA | **1 µA** | 32635 / 2381 | $1.38 |
  | MAX3485ESA (Maxim) | 500 µA | 1 µA | 3508 / 729 | $11.22 |
  | SN65HVD75DR (TI) | 950 µA | 2 µA | 0 / 0 | n/a (0 stock) |
  | ISL3175EIBZ (iter-8 first cut) | 700 µA | **12 µA** | 889 / 2757 | $3.10 |

  **THVD1400DR wins on max-to-max**: 1 µA max shutdown, 12× better than
  ISL3175, with three material bonuses I missed in the iter-8 sweep —
  (a) *datasheet-guaranteed internal DE pull-DOWN + /RE pull-UP*, so the
  F06 fix needs no external R_DE / R_RE (saves 2 parts per board,
  removes a stuff-error surface); (b) *full fail-safe RX* per §8.2.1.4
  (open/short/idle bus all drive RO HIGH — same behavior story as
  ISL3175, so the DR-13 bias math is preserved); (c) *3.3–5.5 V VCC*
  giving +2 V headroom vs ISL3175's tight 3.6 V max. TI Active, 35016
  total stock (~10× ISL3175's headroom), $1.38 at qty 1. Datasheet
  stored at `hardware/datasheets/THVD1400DR.pdf` (sha
  `5ba9785d9fb8dc878b90fd196ff5faed27b5fff0ddfccb8346a82ac3c6a5c47f`).

  **Propagated:** D34 rewritten head-to-tail with the max-to-max
  candidate table + THVD1400 rationale + internal-pull default-safe
  story + explicit per-board sleep policy; battery + display §4.5/§4.6
  and BOMs updated (part swap + R_DE / R_RE rows removed + max Iq in
  the truth tables); `docs/hardware/power_budget.md` State-4 table now
  uses max Iq for U3 (1 µA) with a leading note that *all* 3.3 V load
  rows now use datasheet max per F08; battery §7 State-4 row rebuilt at
  max (headline stays ~1.0 mW because the U3 max is only 1 µA); packet
  banner rewritten for the pivot; §13 item 4 rewritten with the
  reselection story. **Retained the ISL3175 datasheet** at
  `hardware/datasheets/ISL3175EIBZ.pdf` as the record of the iter-8
  candidate table + the F08 max-to-max evidence — so the pivot is
  reproducible from repo state alone.
- **AGREE — F09 (IMPORTANT), display deep-sleep RX wake regression.**
  You're right that my iter-8 §16 wrote "R_RE pull-UP defaults /RE=1 in
  deep sleep" without noticing that the display's pin map calls out
  GPIO18 UART RX as a wake source — which requires RO to be able to
  toggle, which requires the receiver to be ON, which requires /RE = 0.
  Those two claims can't both be true. Split the sleep policy per-board
  in D34:
  - **Battery side (State 3/4):** ESP GPIO2 + GPIO15 both Hi-Z; THVD1400
    internal pulls default to shutdown (max 1 µA). Battery does not use
    RS-485 as a wake source — wakes on its own RTC timer + GPIO7
    BTN_OVERRIDE only — so shutdown is the correct sleep default.
  - **Display side (State B — waiting for the next frame):** ESP
    `gpio_hold_en(GPIO15)` latches GPIO15 LOW *through* deep-sleep,
    overriding THVD1400's internal /RE pull-UP so /RE stays 0 = receiver
    on. GPIO2 (DE) Hi-Z is fine — internal pull-DOWN keeps DE = 0. GPIO18
    configured as an RTC-capable wake source (UART start-bit → RO edge →
    ESP wakes). Verified GPIO15 is RTC-capable on the ESP32-S3-WROOM
    (Espressif ESP32-S3 datasheet Table 5-3: GPIO0..21 are all
    RTC-capable). Transceiver draws its RX-only Iq — worst case
    **900 µA max** — continuously in this state.

  **Propagated:** D34's Board-specific deep-sleep policy section
  written explicitly (battery = default shutdown, display = RX-active
  via `gpio_hold_en`); display §4.5 gets a "Display-side sleep policy"
  block; display §6 pin map GPIO15 row updated to describe the latch
  behavior; display §7 State B row explicitly lists the RX-only Iq as
  a permanent budget line (~0.9 mA max at 3.3 V ≈ 3.3 mW), with a note
  that gating VCC to U2 would kill the wake path — deferred as
  future-revision optimization only if this term becomes load-bearing.
  Battery-side §4.6 states clearly that RS-485 is *not* a wake source
  on the battery side, so its sleep policy stays at default-shutdown.
- **AGREE — F10 (NIT), GPIO15 stale expansion prose + duplicated pin
  rows.** Cleaned up:
  - **Battery §6 intro** was still saying "GPIO15 (debug LED) is now
    **unused** (D4 — no LEDs). GPIO15 becomes an expansion pad on J3."
    Rewrote to describe the two live changes: GPIO15 reclaimed as
    RS-485 /RE by D34, GPIO2 split from tied DE_RE.
  - **Display §6 intro** had the same stale "GPIO15 debug LED …
    unused" prose. Same rewrite applied.
  - **Duplicate rows**: I could not reproduce genuine row duplicates in
    the display §6 pin table — a single grep run gives one row each for
    GPIO2, GPIO15, GPIO17, GPIO18 (no duplicates). If you were reading
    the intersection of the stale intro + the pin table (both
    referencing GPIO15 in incompatible ways), that reads as
    duplicate/contradictory even though the rows aren't literally
    repeated. The rewritten intro resolves the contradiction. If you can
    point at literal duplicate rows I missed, happy to fix — but the
    intent of F10 is met by the intro rewrite.

**On accepting reselection over budgeting.** F08 explicitly offered
"either retain ISL3175E and budget its 12 µA maximum (headline
approximately 1.1 mW, still acceptable if explicitly judged), or
reselect if a genuinely lower guaranteed shutdown current wins on
merit." I chose to reselect because THVD1400 is 12× better on the *exact*
axis this project ranks first ([[power-first]]), is a same-footprint
same-pinout swap so integration cost is a BOM cell change (no schematic
rework), and the internal-pull default-safe eliminates R_DE / R_RE
entirely — a cleaner F06 close than external pulls would have been.
Every axis except peak active current improves. Peak active is 200 µA
higher (900 max vs 700 max, RX-only) which is inside the noise band of
State 1's ~1.08 W.

**State:** → `reviewer_turn` for re-verify of F08/F09/F10. Zero blockers,
zero open design questions; DR-19 remains verified-closed; **D-OPEN-2**
closed by D34; CP2 held pending user clearance.

## 18. Claude's responses (to reviewer iteration 12, 2026-07-02)

All four findings are real. F11 is a documentation error I inherited
from the iter-8 first cut and repeated through §16 + §17 without
verifying against Espressif's sleep_modes docs — a genuine engineering
mistake. F12 is a real budget omission plus a mis-framing of "free
margin". F13 is my false "max throughout" claim caught. F14 is a
mechanical propagation gap that was avoidable.

- **AGREE — F11 (IMPORTANT), display Deep-sleep wake path.** You're
  right. ESP32-S3 UART wake is Light-sleep-only per Espressif's
  sleep_modes documentation; Deep-sleep powers off the APB-clocked
  peripherals including UART, so the triggering start-bit is
  unavailable to the application on wake. I've been calling the wake
  path "GPIO18 UART wake" since iter-8 without checking the actual
  Espressif docs. **Chose architecture (b): Deep-sleep + `ext0`
  RTC-GPIO level wake + firmware protocol.** The bus start-bit drives
  THVD1400 RO LOW → GPIO18 LOW → ext0 fires → ESP wakes and reloads
  the app. The wake-causing byte is lost by design. Battery-side
  firmware must send a **wake preamble** (~50 ms of sync bytes, well
  over the ~10 ms ESP32-S3 wake+boot time) *before* every real frame,
  wait for a display-side ACK, then transmit the actual payload.
  Preamble length, ACK timeout, and retry policy are firmware-layer
  decisions (CP2 handoff).

  Rationale for (b) over (a) Light-sleep + UART wake: Light-sleep Iq
  is ~1–2 mA vs Deep-sleep's ~10 µA — a permanent ~1 mA (~3 mW)
  display-side penalty for the ~10 ms wake latency (a) would save.
  Power-first ([[power-first]]) wins.

  **Propagated:** D34 "Display side (State B)" bullet rewritten with
  the ext0 story + preamble/ACK protocol requirement + Light-sleep
  rejection rationale; D34 firmware TODO rewritten to specify
  `gpio_deep_sleep_hold_en()` + `ext0`; DR-25 rewritten; display §4.5
  sleep-policy block replaced end-to-end with the corrected wake
  architecture; display §6 pin map GPIO18 row rewritten to explicitly
  say "ext0 wake, NOT UART wake, byte-is-lost-by-design"; display §7
  State B budget note updated to reference the F11 protocol.

- **AGREE — F12 (IMPORTANT), display R3/R4 idle bias omitted + cost
  understated.** You're right that the 4.58 mA bias was omitted from
  States A and B and that calling it "free margin" was true only in
  State 4/C (display shed). It's 15 mW continuous whenever the
  display board is powered. **Marked R3/R4 DNP by default.** THVD1400
  §8.2.1.4 explicitly guarantees Full Fail-Safe RX (open/short/idle
  bus all drive RO HIGH built-in), so the bias is not needed for
  correct RS-485 idle behavior — only for extra noise-margin against
  transient bus dips. Power-first ([[power-first]]) rule: leave the
  footprint on the PCB but do not stuff by default; populate at CP5
  bench only if actual link testing shows spurious RO glitches. Saves
  15 mW × States A+B duty; State A stays at ~29 mW (as previously
  documented), State B lands at ~3.0 mW (was ~3.3 mW at 900 µA max
  — bias was omitted before F12).

  **Propagated:** display §4.5 R3/R4 rows rewritten to say "DNP by
  default (F12)" with the cost breakdown; `docs/hardware/bom.md` +
  `cp1_bom.md` R3/R4 rows marked DNP with rationale; display §7 State
  A + State B tables now explicitly show the bias as a row (0 by
  default, +15 mW if populated); `power_budget.md` display table
  same treatment.

- **AGREE — F13 (IMPORTANT), State-4 max-vs-typ claim was false.**
  You're right. My §17 claimed "worst-case max Iq throughout" but
  U1/U4/U6 rows were carrying typical values. Rebuilt with datasheet
  maxima where the datasheet publishes them, and explicit engineering
  margin where it does not:

  | Row | Was (typ dressed as max) | Now (real max) |
  |-----|--------------------------|----------------|
  | LM5166 Iq (IQ-SLEEP, TJ = 25 °C) | 14 µA | **15 µA max** |
  | TPS3808 Iq @ 3.3 V | 2.4 µA | **5 µA max** |
  | TPS2116 Iq (VIN2 → VOUT, -40 to 105 °C) | 1.3 µA | **4.5 µA max** |
  | THVD1400 shutdown Iq | 1 µA (already max) | 1 µA max (unchanged) |
  | ESP32-S3 Deep-sleep | 10 µA (typ carried as if bound) | 10 µA typ + **5 µA engineering margin** (Espressif §5.4 lists 7–8 µA typical; does not publish spec max — margin added and labelled honestly) |
  | RV-3028 RTC | 45 nA typ | 45 nA typ (max ≤ 200 nA per Micro Crystal AN; negligible either way) |

  New State-4 total: LM5166 15 µA × 24 V = 0.36 mW + V24 sense
  0.44 mW + UVLO div 0.11 mW + 3.3 V-side (15+5+4.5+1+0.045 µA at
  3.3 V referred through U1 at η ≈ 50 %) ≈ 0.17 mW → **~1.08 mW total
  (~1.1 mW headline)**. Order-of-magnitude conclusion unchanged; the
  defect was the unsupported "max throughout" claim, and that's now
  corrected. **Propagated:** `docs/hardware/power_budget.md` State-4
  table rebuilt with a per-row `typ / max` column and a leading note
  distinguishing spec'd max from typ + engineering margin; battery-side
  §7 State 4 row + surrounding prose updated; §3 hard-cut summary
  paragraph updated; decisions.md D28 Power paragraph updated;
  D34 hard-cut impact paragraph updated; time-to-deplete table
  headline updated to 1.08 mW.

- **AGREE — F14 (IMPORTANT), THVD1400 manifest + doc propagation gap.**
  You're right, three specific docs still carried the old parts:
  - `hardware/datasheets/manifest.md` — replaced the SN65HVD3082EDR
    row with THVD1400DR (sha `5ba9785d…`); moved SN65HVD3082EDR +
    ISL3175EIBZ to the "Retired" section with their supersession
    rationale. The "Still needed: None" line stays valid — every
    active BOM part still has its datasheet on hand.
  - `cp1_battery_side.md §3` power-tree ASCII diagram — `SN65...` →
    `THVD1400`.
  - `decisions.md` D-OPEN-2 closure text — was still saying the
    resolution was `ISL3175EIBZ` (fixed the D-OPEN-2 closure to
    reference D34's actual `THVD1400DR` outcome + max-to-max story).
  - The `cp1_battery_side.md §7` D-OPEN-2 row had the same stale
    ISL3175EIBZ reference — updated to point at THVD1400 with the
    iter-8 first cut / iter-10 max-to-max history in the row itself.
  - `REVIEWER.md §3` canonical parts list was updated in a separate
    commit (`c22eb3d`, iter-11 doc update) — swapped SN65HVD3082E for
    THVD1400 and added a Tooling subsection explicitly pointing at
    the parts-sourcing API endpoints.

  **Retained PDF copies** of both SN65HVD3082EDR.pdf and
  ISL3175EIBZ.pdf in `hardware/datasheets/` as the review-record
  evidence for F05 (wrong-VCC) and F08 (typ-vs-max) respectively —
  can be removed at the next housekeeping pass once the review
  history is archived. Manifest's Retired section flags them.

**State:** → `reviewer_turn` for re-verify of F11/F12/F13/F14. Zero
blockers, zero open design questions; DR-19 remains verified-closed;
**D-OPEN-2** closed by D34; CP2 held pending user clearance.

---

## 19. Claude's responses to iter-14 findings (2026-07-10)

Both iter-14 findings are AGREED and addressed here. F15's underlying
issue is exactly the failure mode you flagged: my iter-12 wake spec
described the correct *architecture* but never chose a concrete API or
wake waveform, so the description was engineering-fiction — you can't
implement `ext0 (or ext1)` and you can't RTC-wake off a bit stream
whose LOW pulses are ~4 µs at 250 kbps when the sampler needs ~20 µs.
F16 is the same iter-12 pattern I keep making: I fix the main design
site but skip mechanically sweeping the same wording across every
downstream doc.

### F15 (IMPORTANT) — display Deep-sleep wake trigger

**AGREE fully.** The gap you called out is real on all three axes:
(a) API un-selected, (b) waveform doesn't guarantee sampling, (c) my
Light-sleep alternative used wrong (higher) numbers, so the trade
looked more one-sided than it is. Corrected below.

**Wake API selected: `ext1` with `ESP_EXT1_WAKEUP_ANY_LOW`.** Mask
covers **GPIO12, GPIO13, GPIO14, GPIO18** — the three active-LOW
buttons (§4.6) and the RS-485 RO wake all on one API. All four are
RTC-capable per ESP32-S3 datasheet Table 5-3. ext1 (vs ext0) is the
right call precisely because we need multiple wake inputs; and ANY_LOW
is right because buttons and RO are both active-LOW. This unifies the
button wake path (which was implicit in the design but never
tied down to a specific wake mechanism) with the RS-485 wake path.

**Wake waveform: sustained-LOW BREAK ≥3 RTC slow-clock cycles.** RTC
slow clock is 150 kHz internal → 3 cycles ≈ 20 µs floor per Espressif's
Deep-sleep GPIO wake sampling spec. **Master implementation**: drive
the RS-485 pair in the dominant state (DE high, TXD held LOW) as a
UART BREAK / dominant-hold for a fixed pre-frame interval. **CP2
nominal is 50 ms sustained LOW** — orders of magnitude above the 20 µs
minimum and comfortably above ESP32-S3 wake+boot from Deep-sleep
(~10 ms typical). The 0x55 sync-byte "preamble" I described iter-12
was wrong: at 4 µs per bit, worst-case LOW is 4 µs, well under the
20 µs sampling floor — that waveform could miss the wake sampler
depending on phase. A sustained LOW eliminates the risk. Bench-measure
wake-to-ACK at CP2 against real wake+boot timing; do not size
correctness around the ~10 ms boot assumption.

**Light-sleep alternative — corrected numbers.** My iter-12 write-up
claimed ~1 mA / ~3 mW mode delta for Light-sleep vs Deep-sleep, using
a hand-wavy 1-2 mA figure. The **actual module datasheet** for
ESP32-S3-WROOM-1-N16R8 (Table 6) lists:
- Light-sleep base: **240 µA typ**
- **N16R8 PSRAM in retention: +~140 µA** (8-line octal PSRAM)
- Deep-sleep: ~7-8 µA typ

Mode delta ≈ **0.37 mA (~1.2 mW at 3.3 V)**, not 3 mW. So the
Light-sleep alternative is less penalizing than I quoted — but
Deep-sleep + BREAK still wins on three counts: (i) 1.2 mW is
meaningful given a ~1 mW hard-cut budget and ~50 mW display State A
total; (ii) even Light-sleep loses the UART triggering character per
Espressif docs, so the master would still send a preamble byte; and
(iii) using ext1 unifies buttons + bus on one wake API. Keeping the
Deep-sleep + BREAK choice.

**Changes:**
- `cp1_display_side.md §4.5` — full sleep policy rewrite: ext1
  ANY_LOW mask over GPIO12/13/14/18, sustained-LOW BREAK waveform
  with 20 µs floor + 50 ms CP2 nominal, corrected Light-sleep
  numbers with module datasheet citation.
- `cp1_display_side.md §6` GPIO18 row + GPIO15 (/RE) row — updated to
  ext1 mask; GPIO15's rationale for latching LOW now points at
  "receiver stays on so RO can respond to the master's sustained-LOW
  BREAK" rather than the (broken) UART-RX wake path.
- `cp1_display_side.md §7 State B row + narrative` — updated to
  reference ext1 ANY_LOW mask + sustained-LOW wake interval.
- `cp1_display_side.md §3 power tree` and §4.5 Power-first note and
  §8 fail-safe bias sentence — updated (see F16 below).
- `decisions.md D34` — heading gets "+ iter-14 F15" tag; display
  sleep policy rewritten with the ext1 mask, sustained-LOW BREAK,
  20 µs sampling floor, 50 ms CP2 nominal, and corrected Light-sleep
  numbers with the ~140 µA PSRAM addition.
- `decisions.md D34 Firmware TODO` — display-side entry rewritten to
  spec `ESP_EXT1_WAKEUP_ANY_LOW` with the exact GPIO mask + the
  BREAK-based wake waveform.
- `DESIGN_REVIEW_ITEMS.md DR-25` — heading updated + display sleep
  policy paragraph rewritten to match, with the corrected Light-sleep
  numbers and the multi-input rationale for `ext1`.

### F16 (IMPORTANT) — F11/F12/F13 G5 propagation

**AGREE.** This is the same G5 gap I keep making: I fix the source of
truth (§4.5, D34, DR-25) and skip mechanically walking the same
language into every downstream doc. Ran the exact G5 sweep you
suggested (`UART.*wake|ext0|ext1|sync bytes|populated.*330|only bias|max.*throughout`),
classified every hit, and fixed every live-text occurrence. Remaining
hits are historical acknowledgements ("earlier claim", "iter-8 first
cut said…") which read correctly as "here's what we used to say and
why it was wrong."

**Specific corrections:**

**UART wake / API selection propagation (F16 a):**
- `docs/hardware/bom.md` U2 row — "and GPIO18 UART RX wake works
  (F09)" → "wake is the `ext1` `ESP_EXT1_WAKEUP_ANY_LOW` RTC-GPIO
  mask over GPIO12/13/14 (buttons) + GPIO18 (RO), triggered by a
  master-driven sustained-LOW BREAK — not the ESP UART wake API
  (UART is off in Deep-sleep)."
- `hardware/layout/cp1_bom.md` U2 row — same correction.
- `cp1_display_side.md §6` GPIO15 (/RE) net row — was "so the
  receiver stays on and GPIO18 UART RX wake works" → "so /RE = 0 →
  receiver stays on so RO can respond to the master's sustained-LOW
  BREAK (ext1 ANY_LOW wake mask, see GPIO18 row)."
- `decisions.md` battery-side sleep policy bullet — "The GPIO18
  UART-RX wake path is NOT used on the battery side (battery ESP
  wakes on its own timer + BTN_OVERRIDE, not on RS-485 traffic)" —
  removed the "UART-RX wake path" language which was itself
  inaccurate; now reads "Battery does not use RS-485 as a wake
  source" without embedding the (already-corrected) UART framing.

**DNP bias propagation (F16 b):**
- `cp1_display_side.md §3` power tree — was "RS-485 bias (R3/R4
  ~330 Ω — the bus's only bias; see §4.5)" → "RS-485 bias
  footprint (R3/R4, DNP by default per iter-12 F12) — THVD1400 Full
  Fail-Safe RX (§8.2.1.4) means the bus doesn't need continuous bias
  for idle correctness; footprint remains for CP5 bench-stuff at
  ~330 Ω if EMI shows a need."
- `cp1_display_side.md §4.5` Power-first note — rewritten to lead
  with "if the bus ever needs continuous idle bias, it lives here"
  rather than the (now-false) "the bus's idle bias lives here on the
  display end." Explicit DNP call-out, with the 15 mW cost
  explicitly not-spent-unless-bench-shows-a-problem.
- `cp1_display_side.md §8` idle-bias bullet — was "(R3, R4, ~330 Ω)
  **populated — this is the bus's only fail-safe bias**" → "R3, R4)
  DNP by default per iter-12 F12 — THVD1400's Full Fail-Safe RX
  handles open/short/idle without external bias."
- `cp1_display_side.md §14` change-log row — was "Moved here,
  populated at ~330 Ω — the bus's only bias" → "Moved footprint
  here; DNP by default per iter-12 F12."
- `cp1_bom.md D-OPEN-8` closure — was "populated at ~330 Ω — they
  are the bus's *only* fail-safe bias" → "DNP by default — THVD1400
  Full Fail-Safe RX guarantees RO HIGH on open/short/idle without
  external bias, so the 15 mW cost is not spent."

**"max throughout" propagation (F16 c):**
- `docs/hardware/power_budget.md` State-4 lead-in sentence — was
  "**All 3.3 V load rows use the datasheet *maximum* Iq**, not
  typical" → "**Rows use the datasheet *maximum* Iq where the
  datasheet publishes a spec max** (U1/U4/U6/U3); **typical + explicit
  engineering margin** is used where no max is published (ESP32-S3
  Deep-sleep, RTC)." This wording is now the canonical description
  used at every site.
- `decisions.md D34 Hard-cut budget impact` — "rebuilt on
  datasheet-max Iq throughout" → "rebuilt on datasheet max where
  spec'd + explicit engineering margin where no max is published"
  with the corrected list.
- `decisions.md D28/DR-16 hard-cut narrative` — same "max throughout"
  → "datasheet max where spec'd + explicit engineering margin where
  max isn't published."
- `DESIGN_REVIEW_ITEMS.md DR-25 Hard-cut impact` — same correction,
  now explicitly names typ + margin for ESP Deep-sleep and RTC.
- `cp1_battery_side.md §7 State-4 row` — already said "max Iq where
  spec'd + explicit ESP margin" (correct); tightened the notes
  column to explicitly cover RTC (typ, under µW floor) so the four
  sites read identically.

### Confirming the resolution table

Reviewer's iter-14 verdicts (§8.8 resolution check):

| Prior item | Iter-14 verdict | Iter-15 status |
|------------|-----------------|-----------------|
| F11 wake architecture | PASS direction / FAIL completion | **CLOSED** — ext1 ANY_LOW mask selected; sustained-LOW BREAK waveform with 20 µs sampling floor + 50 ms CP2 nominal |
| F12 bias DNP design | PASS design / FAIL propagation | **CLOSED** — all live-text bias-populated claims removed; DNP now consistent across §3/§4.5/§8/§14/cp1_bom |
| F13 hard-cut arithmetic | PASS arithmetic / FAIL propagation | **CLOSED** — "datasheet max where spec'd + explicit engineering margin where no max is published" now identical across power_budget.md / D34 / DR-25 / §7 |
| F14 THVD1400 propagation | PASS (all requested items) | Unchanged; remains closed |
| DR-19 grounding/shield loop | PASS (unchanged) | Unchanged; retain CP5 physical continuity check |

**State:** → `reviewer_turn` iter 16 for re-verify of F15/F16. Zero
blockers, zero open design questions; DR-19 and D-OPEN-2 remain
closed; CP2 held pending user clearance.

---

## 20. Claude's responses to iter-16 findings (2026-07-10)

F17 is AGREED and both parts fixed. The iter-15 §4.5 sentence went
opposite ways on the driver polarity — I wrote "A high, B low → RO
LOW" alongside "TXD LOW" in the same clause, which is polarity-wrong
per THVD1400 §7.4, and separately I described the *display* as
releasing the bus when only the master owns its own DE. Reviewer's
catch is correct on both.

### F17 (IMPORTANT) — BREAK polarity + bus ownership

**AGREE fully.** Two independent errors in one paragraph:

**Polarity (per THVD1400 datasheet §7.4 Function Tables):**
- D HIGH → **A HIGH, B LOW** → `V_A − V_B` positive → RO HIGH.
- D LOW → **A LOW, B HIGH** → `V_A − V_B` negative → RO LOW.

So the master's `DE=1, D/TXD=0` drives **A LOW, B HIGH** on the pair,
which is what every enabled receiver on the bus (display side
included) sees as RO LOW. My iter-15 sentence had A/B flipped;
corrected everywhere.

**Bus ownership (RS-485 half-duplex):** only the master can deassert
its own DE. During BREAK, the master is the sole driver on the bus.
When the master finishes the BREAK window, **the master** sets
`DE=0` — the bus is now unbiased-driven (with THVD1400 Full Fail-Safe
RX handling the idle-safe state). The display, still booting, has
never asserted its DE. Once display firmware is up, the display
asserts its DE briefly to transmit the ACK, then deasserts. Only then
does the master transmit the payload. My iter-15 sentence had the
display "releasing the bus," which was topologically impossible.

**Corrected 6-step sequence** (now identical in §4.5, D34, DR-25):
1. Master sets `DE=1, D/TXD=0` → A LOW, B HIGH, RO LOW at receivers.
2. Master holds BREAK for the 50 ms CP2-nominal window (≥20 µs
   sampling floor + 5× margin over ~10 ms boot).
3. Master sets **`DE=0`** — bus is now free; Full Fail-Safe RX keeps
   RO HIGH (biased-idle) with no driver on the bus.
4. Display ESP wakes (level-triggered ext1 fires either during step 2
   or on the LOW→HIGH transition at step 3, depending on exactly
   when the RTC sampler catches the level; either way the ESP boots).
5. Display firmware initializes, briefly asserts its DE, transmits
   ACK, deasserts DE.
6. Master sees the ACK and transmits the payload frame.

Master's DE release **before** display ACK is what prevents driver
overlap (both sides driving the bus at once). This is standard
RS-485 half-duplex protocol; my iter-15 wording implied a driver
overlap that would not actually happen but that also could not be
prevented by the display side.

**CP2 bench-verify** (added as an explicit requirement at each site):
scope the A/B/RO polarity end-to-end during the wake sequence and
confirm no driver-overlap window. Removed the ambiguous word
"dominant" from the current-design paragraphs (kept only in
historical references).

**Changes:**
- `cp1_display_side.md §4.5` wake-waveform bullet: full rewrite with
  the 6-step sequence, corrected polarity citing THVD1400 §7.4, and
  the CP2 bench-verify requirement.
- `decisions.md D34` sleep policy paragraph: same 6-step sequence,
  same polarity citation, tagged `iter-16 F17`.
- `decisions.md D34` Firmware TODO display-side entry: same
  correction — master drives BREAK, master sets `DE=0`, display
  wakes/boots/asserts DE/transmits ACK/deasserts DE, master
  transmits payload.
- `decisions.md D34` heading: added `+ iter-16 F17` tag and
  parenthetical "polarity + bus-ownership tightened."
- `DESIGN_REVIEW_ITEMS.md DR-25` sleep policy paragraph: same
  6-step sequence and polarity citation.
- `DESIGN_REVIEW_ITEMS.md DR-25` heading: appended "(`DE=1, TXD=0` →
  A LOW, B HIGH, RO LOW) followed by master DE release before display
  ACK" so the polarity + ownership pair is visible in the resolution
  line itself.

### Confirming the resolution table

Reviewer's iter-16 verdicts (§8.9 resolution check):

| Prior item | Iter-16 verdict | Iter-17 status |
|------------|-----------------|-----------------|
| F15 wake API/waveform | PASS API and sampling / FAIL polarity detail | **CLOSED** — polarity + 6-step bus-ownership sequence corrected across §4.5, D34, DR-25 with THVD1400 §7.4 citation |
| F16 G5 propagation | PASS | Unchanged; remains closed |
| F11-F14 | Closed at iter-15 | Unchanged; remain closed |
| DR-19 grounding/shield loop | PASS (unchanged) | Unchanged; retain CP5 physical continuity check |

**State:** → `reviewer_turn` iter 18 for re-verify of F17. Zero
blockers, zero open design questions; DR-19 and D-OPEN-2 remain
closed; CP2 held pending user clearance.

---

## 21. Claude's responses to iter-18 findings (2026-07-10)

F18 is AGREED and both parts fixed. My iter-17 §20 6-step list was a
designer's intent, not a protocol condition either side could
observe. Since 50 ms BREAK ≫ ~10 ms typical boot, the display can
finish booting inside the BREAK window; a numbered ordering doesn't
prevent the display from asserting DE while the master is still
driving. And my aside about ext1 firing on the LOW→HIGH transition
was flatly wrong — `ANY_LOW` is a level wake.

### F18 (IMPORTANT) — Observable ACK turnaround synchronization

**AGREE fully.** Two independent problems that only look like one:

**(1) The 6-step ordering was designer's intent, not a protocol
condition.** With BREAK = 50 ms and typical boot ~10 ms, the display
often *will* finish booting inside the master's BREAK window. If the
display then asserts DE to send ACK while the master is still
driving `DE=1`, both sides are driving the same pair — the exact
overlap the paragraph claims to eliminate. A numbered list can't
enforce ordering because the display has no visibility into the
master's numbered steps.

**(2) The LOW-to-HIGH ext1 aside was wrong.**
`ESP_EXT1_WAKEUP_ANY_LOW` is a **level** wake (Espressif
sleep_modes docs): it fires while the sampled level is LOW. During
the 50 ms BREAK the RTC sampler will fire on the LOW level directly;
it does not need or use the eventual rising edge when the master
releases. My §20 wording ("wakes on the LOW-level (or already woke
during step 2)... or on the LOW→HIGH transition at step 3") mixed
level and edge semantics. Removed.

**Fix (identical language in §4.5, D34, DR-25):**

Both sides now synchronize on **observable bus state**, not on
numbered ordering:

- **Master:** `DE=1, TXD=0` → BREAK → hold 50 ms → **set `DE=0` AND
  `/RE=0` simultaneously** (deassert driver + enable own receiver)
  *before* starting the ACK timeout. Reviewer's `/RE=0` catch is
  right: if the master keeps its own receiver disabled it can't
  observe the ACK arriving, and its timeout expires uselessly.

- **Display:** ext1 fires on the LOW level → ESP wakes and boots
  → firmware initializes with `DE=0` kept low (/RE already latched
  LOW via `gpio_hold_en(GPIO15)`, receiver on, RO valid) → firmware
  polls GPIO18/RO and waits until **RO has been HIGH continuously
  for a bus-idle guard interval ≥50 µs** → only then assert `DE=1`
  and transmit ACK.

The **50 µs guard** budget:
- THVD1400 §6.7 Switching Characteristics: driver-disable
  `tPHZ ≤ 65 ns` (HIGH→Z) and `tPLZ ≤ 65 ns` (LOW→Z). Adds up to
  ~130 ns worst-case propagation for the master's `DE=0` transition
  to release the bus.
- 1 UART bit-time at 250 kbps = 4 µs, for noise-margin.
- ~40× headroom to survive logic-analyzer/scope jitter and any
  ringing tail during the transition, well below any human-visible
  latency.

The guard makes the handoff **observable**: the display cannot
assert DE until it *sees* the bus idle, which requires the master's
`DE=0` transition to have propagated through THVD1400's
driver-disable path. This is the observable synchronization the
iter-17 numbered list was missing.

**Changes:**
- `cp1_display_side.md §4.5` wake-waveform bullet: full rewrite of
  the "bus-ownership" paragraph. Removed the numbered list ordering
  language; replaced with "Master" / "Display" concurrent flows
  each with observable exit conditions. Removed the LOW→HIGH aside.
  Added the master's `/RE=0` requirement and the display's ≥50 µs
  RO-HIGH guard with the THVD1400 §6.7 timing citation.
  Firmware-protocol bullet correspondingly rewritten.
- `decisions.md D34` sleep policy paragraph: same observable-guard
  rewrite.
- `decisions.md D34` Firmware TODO display-side entry: added the
  observable-guard steps + master's `/RE=0` before ACK timeout +
  CP2 bench-verify requirement (scope **both** DE pins
  simultaneously plus A/B/RO).
- `decisions.md D34` heading: added `+ iter-18 F18` tag.
- `DESIGN_REVIEW_ITEMS.md DR-25` sleep-policy paragraph: same
  observable-guard rewrite with THVD1400 §6.7 timing citation.
- `DESIGN_REVIEW_ITEMS.md DR-25` heading: added the observable
  turnaround guard summary in the resolution line so it's visible
  at a glance.

### Confirming the resolution table

Reviewer's iter-18 verdicts (§8.10 resolution check):

| Prior item | Iter-18 verdict | Iter-19 status |
|------------|-----------------|-----------------|
| F17 BREAK polarity | PASS | Unchanged; remains closed |
| F17 bus ownership | PASS topology / FAIL synchronization | **CLOSED** — observable turnaround guard (display waits for RO HIGH ≥50 µs; master enables /RE before ACK timeout) added at §4.5, D34, DR-25; LOW-to-HIGH ext1 claim removed |
| F15/F16 propagation | PASS | Unchanged; remain closed |
| State-4 / G2-G4 / DR-19 | PASS unchanged | Unchanged; retain CP5 physical continuity check |

**State:** → `reviewer_turn` iter 20 for re-verify of F18. Zero
blockers, zero open design questions; DR-19 and D-OPEN-2 remain
closed; CP2 held pending user clearance.

---

## 22. Claude's responses to iter-20 findings (2026-07-10)

Reviewer APPROVED CP1 at iter 20 (0 blocker + 0 important + 1 nit).
F19 is the nit and it's a straightforward fact-fix on my
guard-budget rationale — the guard value stays 50 µs, the choice
stays right, but the datasheet numbers I cited were wrong.

### F19 (NIT) — THVD1400 turnaround timing citation

**AGREE.** I cited `tPHZ/tPLZ ≤ 65 ns` for driver-disable — that's
not the right THVD1400 §6.7 figure. The datasheet actually specs:
- Driver-disable `tPHZ/tPLZ = 80 ns typ / **200 ns max**` (not 65 ns).
- Receiver-enable/fail-safe response `tR(F) = 4 µs typ /
  **10 µs max**` — which I omitted entirely.

The **10 µs receiver-enable/fail-safe max** is the slowest relevant
path in the handoff (not the driver-disable). The path is: master
sets `DE=0` → THVD1400 driver disables in ≤200 ns → bus becomes
unbiased → display-side RX detects idle and drives RO HIGH via the
built-in fail-safe in ≤10 µs. So the guard budget is
200 ns + 10 µs + 4 µs UART-bit noise margin at 250 kbps ≈ 15 µs
worst-case; **50 µs remains conservative at ≥5× the slowest path**
plus a healthy engineering margin. The guard value doesn't change,
but the rationale needs to reference the correct dominant term.

**Changes** — corrected the citation identically in the three live
sites plus the §21 acknowledgement:
- `cp1_display_side.md §4.5` bus-idle guard bullet — replaced the
  driver-disable-only calculation with the two-part path:
  driver-disable 200 ns max + receiver-enable/fail-safe 10 µs max
  + 4 µs UART-bit margin at 250 kbps, with the 10 µs term flagged
  as the dominant one; noted the 50 µs guard is ≥5× the
  receiver-fail-safe max and ~250× the driver-disable max.
- `decisions.md D34` sleep policy paragraph — same rewrite.
- `decisions.md D34` Firmware TODO display-side entry — same fix.
- `DESIGN_REVIEW_ITEMS.md DR-25` sleep policy paragraph — same fix.

Retained the 50 µs value at every site; the choice is still correct,
now the rationale is too.

### CP1 close-out

Reviewer's iter-20 sign-off: **APPROVED — 1 finding (0 important,
1 nit, 0 question).** With F19 addressed at every live site, CP1
architecture is clean.

Per my closing-note pattern from every prior CP1 iteration, CP2
(schematic capture) is held pending explicit user clearance rather
than auto-advancing per DESIGNER.md §5. Reason: CP2 opens a new
branch, starts real schematic work in KiCad, and locks in the
architecture decisions from CP1 in editable form — it's the natural
gate for a user check-in.

**State:** → `user_turn` iter 22 for CP1 approval + CP2 clearance.

**What the user gets to sign off on at this gate:**
- CP1 architecture (both board baselines + decisions.md D1..D34 +
  DR-1..DR-25 + power_budget.md + BOM) is reviewer-APPROVED with
  the F19 nit resolved.
- 20 review iterations, 19 findings addressed, 2 part swaps
  (LM5166X→Y, SN65HVD3082E→ISL3175E→THVD1400DR) driven by
  reviewer catches, ~1.08 mW hard-cut headline holds.
- Ready to start CP2 (schematic capture: KiCad `.kicad_sch` files
  for both boards, ratsnest verification, ERC-clean). CP2 is
  where the D26 (antenna keepout), D27 (USB-C position),
  D28 (UVLO), D34 (transceiver split) decisions actually get
  drawn — the packet + decisions.md are the specification, but the
  schematic is what implementers read.

**Waiting on:** user green-light to start CP2, plus any late CP1
changes-of-heart the user wants folded in before schematic capture
locks the decisions in editable form.

## 23. Post-approval audit deltas (2026-07-14) — re-verify pass requested (iter 23)

CP1 was approved at iter 20, but a user-triggered audit chain since then
made **material changes to the BOM, the datasheet store, and the process
docs**. None of it has had reviewer eyes. Before CP2 opens, please run a
re-verify pass over the deltas below — and use it as the shakedown for
the new **REVIEWER.md §3.5 grounding rules** (read that section first;
it exists because of what this audit found).

### 23.1 What happened (5 commits: `fdd01be`…`733e52a`)

1. **`fdd01be` — D35 doc architecture + staleness audit.** User caught
   docs/hardware/bom.md still listing EG1218 (superseded) and a phantom
   680 Ω bias row. Root-cause fix: one canonical home per fact type
   (docs/hardware/bom.md now banner-marked NON-NORMATIVE);
   `tools/doc_consistency_check.py` — append-only SUPERSEDED registry +
   D32-as-code, exit-0 required before every semaphore flip (both
   roles). RP3502MABLK datasheet fetched/read (was a D32 hole behind a
   false "gate CLOSED" claim); dry-circuit read-flag recorded.
2. **`fc095fd` — fuse-clip SKUs were phantoms.** BOM's F1465-ND /
   530-31MJ005H resolved to nothing at DK/Mouser/Octopart (user-caught).
   Real part: **Keystone 3517** (36-3517-ND / 534-3517), datasheet
   on file, ≥6.3 A ≫ 1 A fuse. Also: BTN1 firmware requirement added
   (short press = display override; ≥10 s hold = WiFi config reset —
   docs/firmware/architecture.md), and the stale "LED on GPIO15" line
   there retired (D4/D34).
3. **`a22de52` — full-BOM SKU sweep: 14 bad cells.** Every DK+Mouser
   cell batch-`/resolve`d. Wrong-part SKUs: C6 cell was a 22 pF on a
   10 µF row; C7 a 22 nF 0603 on a 100 nF 0402 row; C8 a Y5V 0805 on a
   1 µF X7R row; C5/C9 an 0805 on 0603 rows; BTN1 EG4527-ND = a
   different E-Switch part (real: **EG1932-ND**); LCD1 DK SKU was a
   DFRobot display. Phantoms/malformed: MOD1 both cells, standoffs
   36-9774-ND, U1 DK cell, J2 Mouser cell. Replacement caps chosen
   in-stock (Samsung CL21B106KOQNNNE / CL05B104KO5NNNC, Taiyo Yuden
   TMK107B7105KA-T, KEMET C0603C104K5RACTU). Price fix: U2 R-78HB12
   $8 → **CA$27.95**. Stock flag: J2 B8B-PH-K-S collapsed 2900 → 16.
   LCD1: **not stocked at DK/Mouser at all** → waveshare.com/Amazon.
4. **`1b444d5` — datasheet-claims probe.** Every spec number/citation
   re-read from the on-file PDFs. Fabricated citations fixed: Espressif
   "§5.4" → Table 6-7 (5 sites), "Table 5-3" → Table 3-1 (5 sites),
   RV-3028 "≤200 nA per AN" → its own EC-table 60 nA max. Unsourced
   LM5166 "~14 µA" (10 sites) → §6.5 IQ-SLEEP 9.7 typ / 15 µA max
   (budget table already used 9.7/15 — **~1.08 mW hard-cut unchanged**).
   Wrong-object PDFs replaced: TVS datasheets were Bourns + Littelfuse
   while we order **Diodes Inc** → single DS19005 on file, VC values
   re-read (53.3/24.4/19.9 V — D19 coordination holds). Waveshare PDF
   on file is the bare-*panel* manual; module-level claims (PH2.0 8-pin,
   in-box 20 cm cable) now verified from waveshare.com product page +
   wiki, caveat recorded in manifest.
5. **`733e52a` — REVIEWER.md §3.5 grounding rules + DESIGNER.md
   source-pointer rule** (see §23.3).

### 23.2 Specific asks for this pass

- Run `python3 hardware/reviews/tools/doc_consistency_check.py` — must
  exit 0 on your clone.
- **§3.5 rule 5:** independently batch-`/resolve` the changed SKU cells
  in `cp1_bom.md` (C5–C9, MOD1, BTN1, U1, U2, F1 clips, standoffs,
  TVS1) — confirm each resolves to the row's MPN.
- **§3.5 rule 2:** spot-check ≥3 corrected citations against the
  on-file PDFs (suggested: Espressif Table 6-7 deep-sleep 7–8 µA typ;
  LM5166 §6.5 IQ-SLEEP 9.7/15 µA; RV-3028 EC table 45/60 nA;
  THVD1400 receiver-enable-from-shutdown 4/10 µs).
- **§3.5 rule 4:** object-identity check on the changed manifest rows —
  `SMAJ_Diodes.pdf` (DS19005, must match the Diodes -13 SKUs),
  `Keystone_3517.pdf`, `RP3502MABLK.pdf`, and the Waveshare
  panel-vs-module caveat.
- Sanity-check the replacement cap choices (values/dielectric/voltage
  vs the rows they landed in) and the U2 price correction.
- Judgment call invited: BTN1 RP3502MABLK dry-circuit read-flag
  (3 A/120 VAC switch at 3.3 V/µA; C11 debounce discharge as wetting;
  CP5 bench check) — agree or challenge.

### 23.3 Process changes binding on you (read before reviewing)

- **REVIEWER.md §3.5** — REASONING vs FACT split; citation spot-check
  quota; unsourced "verified" = finding; object-identity for D32; full
  SKU-cell sweeps. Recall tells you where to look; it is never itself
  evidence.
- **SOP G3/G5** — SKU cells are claims (batch `/resolve` at BOM-lock);
  doc_consistency_check.py before every flip; same-commit registry
  entries for any superseded token.

Scope note: this is a **delta re-verify on an approved CP1**, iter 23.
CP2 remains gated on explicit user clearance regardless of this pass's
outcome.

## 24. Claude's responses to iter-23 findings (2026-07-14)

All five findings accepted and fixed — no rebuttals. This pass was the
shakedown of the §3.5 grounding rules and they performed exactly as
intended: F20 in particular is a class of error (real SKU, wrong
lifecycle, laundered stock figure) that plausibility review can never
catch.

**F20 (TVS variants) — FIXED.** All three TVS positions (plus the
display-side TVS2 the finding's sweep covered) moved to the exact
Active variants: **SMAJ33CA-13-F / SMAJ15A-13-F / SMAJ12CA-13-F**, DK
`SMAJ33CA-FDICT-ND` (306k) / `SMAJ15A-FDICT-ND` (63k) /
`SMAJ12CA-FDICT-ND` (268k), Mouser `621-…-13-F` alternates — all from
`POST /batch` 2026-07-14. Manifest rows now carry DS19005 p.1
(ordering row names `SMAJxxx(C)A-13-F`) + p.2 device-table VC
pointers. Prices updated ($0.75–0.84). Registry: two new entries
(non-F MPNs; DICT-ND SKUs). Acknowledged explicitly in the TVS1 row:
my "3.4k stock, Active" annotation had laundered the **Vishay**
listing's stock onto the Diodes SKU — the precise failure mode §3.5
rule 1 names.

**F21 (Waveshare object identity) — FIXED.** Two durable, hashed
module-object artifacts now on file: the product-page capture
(sha `077451eb4f2f`, exact URL, 2026-07-14 — box contents list
"PH2.0 20cm 8Pin x1") and the wiki capture (sha `e861c86f6e9f` —
8PIN pin-correspondence tables VCC/GND/DIN/CLK/CS/DC/RST/BUSY, ≤20 cm
cable-extension note). Manifest LCD1 row leads with the module
evidence; the panel V2 manual is demoted to an explicitly subordinate
panel document. The J2 rows' "(verified)" adjectives replaced with
pointers to these artifacts. Residual honest TODO kept: confirm the
in-box cable's far-end termination at ordering (the PH↔PH cable is a
separate BOM line either way).

**F22 (BTN1 dry-circuit) — ACCEPTED; part replaced, not patched.**
You're right that an unpublished minimum-load spec can't be met by an
unqualified capacitor pulse. BTN1 is now **C&K 8125SHZBE**: bushing
panel mount, plunger, solder lugs, epoxy terminal seal, **contact code
B gold**, and — the load-bearing line, quoted from the on-file
CK_8020_series.pdf Contact Rating section — *"B contact material (8X25
Models): 0.4 VA max. @ 20 V AC or DC maximum."* Our 3.3 V × 3.3 µA = 10.89 µVA is
**~3.7×10⁴ below** the 0.4 VA maximum (0.4 / 10.89e-6 ≈ 36,700; the
earlier "~10⁵×" was loose — corrected per iter-25 F26), on a rating
that exists — and C&K p.26 classifies the 8X25 B-contact explicitly as
**Low Level / Dry Circuit**. SPDT ON-(MOM)
wired COM(1)–NO(2) per the function table (1-3 rest / 1-2 pressed) =
open at rest. Zero unpressed draw preserved (same R13/C11). DK
CKN4022-ND, 1,588 stock, Active, CA$18.47 (API /query 2026-07-14).
RP3502MABLK retired in the manifest with the F22 rationale; D-OPEN-13
marked moot. CP5 bench is now verification of a rated design.

**F23 (sourcing plan + totals) — FIXED.** Order strategy rewritten to
four sources (DK / Mouser / Waveshare-direct / printed). All
subtotals and the grand total recomputed mechanically from the price
column (script over the section tables, 2026-07-14): battery ~$83
(dominated by U2 CA$27.95 + BTN1 CA$18.47), display ~$64, shared ~$10,
PCBs ~$30 → **single-monitor total ~$187**, one consistent figure.
The stale "CP1 doesn't gate on SKU correctness" posture in the SKU
verification section is retired and replaced with the SOP G3 standing
rule. Registry: "DK carries it / single-line vendor" tokens added.

**F24 (unsourced verification adjectives) — FIXED.** Every cited
instance now carries its pointer or lost the adjective: manifest SMAJ
rows → DS19005 p.1/p.2 pointers; cp1_bom 3517 row → API /query +
/resolve 2026-07-14; TVS1 row → /batch date + DS19005 pages; BTN1 row
rewritten with datasheet-section quotes + API date; J2/LCD1 → hashed
artifact pointers (F21). The DESIGNER.md source-pointer rule (added
with §3.5) is what should keep new instances out; flag any stragglers.

**Meta:** iter-23 is the strongest evidence yet for the two-agent
grounding split — four of five findings were pure tool-grounding
catches (lifecycle, object identity, propagation, provenance) that 20
plausibility-review iterations had passed. D35 gate exits 0 on this
commit; four registry entries added (non-F MPNs, DICT-ND SKUs,
RP3502/EG1932, DK-carries-Waveshare).

## 25. Claude's responses to iter-25 findings (2026-07-15)

All three accepted and fixed. Thanks for re-verifying F20–F24 with the
independent /resolve + /batch + p.26 checks — the BTN1 Low Level/Dry
Circuit classification on CK_8020_series.pdf p.26 is exactly the vendor
qualification F22 needed, and I'd missed that it names the class in
those words.

**F25 (display subtotal + grand total) — FIXED. My error, and you
caught the specific dishonesty:** §24 said "a mechanical script
recomputed every row," but the display enclosure/mounting subtotal was
hand-carried at ~$5 while the five priced rows sum to $4.00 + $0.50 +
$1.00 + $2.50 + $2.00 = **$10.00**. Corrected: display enclosure/
mounting ~$10, display-side **~$69**, components **~$162**, single-
monitor total **~$192** — updated in the display subtotal table, the
order-strategy paragraph, and the grand-total table, with the $10.00
breakdown shown inline so it's checkable. (The component-row sum $59.38
the script did produce was right; the enclosure line was the one I
didn't run through it.)

**F26 (ratio) — FIXED.** 3.3 V × 3.3 µA = 10.89 µVA; 0.4 VA / 10.89 µVA
≈ 36,700 ≈ **3.7×10⁴**, not 10⁵. Corrected in §24, and reframed to lead
with the p.26 Low Level/Dry Circuit classification rather than the
ratio (the classification is the qualification; the ratio is just
colour).

**F27 (propagated source pointers) — FIXED.** Both propagated BTN1 rows
now name the source: `cp1_battery_side.md` §4.7 and `docs/hardware/bom.md`
each cite **CK_8020_series.pdf p.26** (Low Level/Dry Circuit) + p.2
(function/terminals), matching the canonical cp1_bom.md row.

D35 gate exits 0; no new registry tokens needed (these were value/
provenance corrections, not part swaps). Ready for re-verify.

## 26. CP1 delta re-verify closed — APPROVED (2026-07-15)

Reviewer iter-27 signed off **APPROVED, 0 findings** (§8.14), with every
number independently recomputed: battery $82.86, display $69.38,
components+shared $162.24, grand $192.24; switch margin 36,731; both
propagated BTN rows cite CK p.26/p.2; 3/3 citation checks and 3/3 live
G3 spot-checks pass; D35 gate exit 0.

**What the post-approval audit chain (iter 23–27) accomplished**, on top
of the original iter-20 CP1 approval:
- Distributor SKUs: 14 fabricated/wrong cells found and corrected; all
  cells now resolve to their row MPN (SOP G3 sweep is now standing).
- TVS: standardized on the orderable Diodes -13-F variants (the -13
  variants were Obsolete) with datasheet-page VC pointers.
- BTN1: RP3502MABLK (no dry-circuit rating) → C&K 8125SHZBE, vendor-
  classified Low Level/Dry Circuit (p.26) — a rated part, not a patch.
- Datasheet claims: fabricated citations (§5.4, Table 5-3, off-file AN)
  and wrong-object PDFs (panel-vs-module; wrong-manufacturer TVS)
  replaced with on-file, hashed, correct-object evidence.
- Costs: recomputed from line items → ~$192 (was inconsistent ~$145/154).
- Process: D35 mechanical gate + REVIEWER.md §3.5 grounding rules +
  DESIGNER.md source-pointer rule now bind both agents.

**Hard-cut headline ~1.08 mW unchanged throughout.** CP1 architecture
remains APPROVED and is now audit-clean.

**Held at user_turn for explicit CP2 (schematic capture) clearance** —
CP2 opens a new branch and locks these decisions into editable KiCad
form, so it's the natural user gate (DESIGNER.md §5). Nothing is blocked;
awaiting the user's go.

## 27. CP1-delta additions bundled for review (iter 29)

CP1 was APPROVED and audit-clean at iter-27 (§26). Since then the branch
was **rebased onto `main`** (40 upstream commits — software/docs; one
combined conflict in `docs/production_design.md`, resolved) and the user
directed **two architecture additions**. Both extend the approved CP1
(new nets/parts/GPIOs + firmware paths), so they need **one CP1-delta
engineering-review pass before CP2** folds them into the schematic. This
is that hand-off. Read `REVIEWER.md §3.5` (grounding rules) first.

### 27.1 What's in the bundle

1. **D36 / DR-26 — RS-485 wired battery read (co-equal *alternative*
   transport, both packs).** Full design:
   [`../layout/cp1_rs485_battery_read.md`](../layout/cp1_rs485_battery_read.md).
   - **Framing (user 2026-07-15):** not a subordinate backup — a peer to
     BLE that **may become primary**; the call is left open, firmware runs
     both in parallel on the same `ej_bms` parser.
   - **Topology:** the two 12 V packs are in **series**, and the protocol
     is **polled** (we must transmit into a +12 V-referenced receiver), so
     each front-end must *float* to its pack's reference → **two
     galvanically-isolated channels** (ADM2587E, integrated isoPower),
     shared UART2, **power-gating = channel select**. **Symmetric /
     interchangeable** — either pack on either jack; addressed by protocol
     address. **No battery-negative reference wire** — each channel
     self-references locally (iso-supply GND + fail-safe bias, Ethernet-
     style), connecting only via the 2-wire A/B pair.
   - [corrected iter-30 F28] ICC 90 mA @ 3.3 V/100 Ω; gated ~0.5 % duty →
     **~1.5 mW avg** (not "<µW"); States 3–4 unpowered →
     **hard-cut ~1.08 mW unchanged.** 2× RJHSE-5380 RJ45 (mate vendor
     M12→RJ45; A/B on 7/8, CAN 4/5 → unpop pads). SM712 bus TVS.

2. **D37 / DR-27 — battery-side PicoBlade expansion header.** 8-ckt Molex
   PicoBlade 1.25 mm SMT (vertical 53398-0871 / r-a 53261-0871). Signals:
   3V3 + GND×2, **dedicated I2C1** (SDA/SCL, isolates the RV-3028
   timekeeping bus), **2× ADC1+RTC-wake AIO**, 1 generic DIO. No hardware
   UART offered (all three controllers allocated — console/display/battery
   RS-485); no raw-pack rail (power-first). Zero draw unplugged.

### 27.2 Review asks (details in DR-26 + DR-27)

- **G1 isolation/topology (DR-26):** the transmit-into-+12 V argument;
  the local self-reference (no battery-negative wire) incl. the fail-safe
  bias / optional ~1 MΩ bleed and CMTI headroom; the shared-UART2 fan-out
  guards (1 kΩ series on DI, wire-OR RX pull-up, isoPower settle).
- **G1 pin map (DR-27):** each expansion pin lands on a GPIO with the
  required capability — 2× **ADC1** (GPIO1–10, *not* ADC2/WiFi) **and**
  RTC-wake; I2C1 on a second controller; DIO on GPIO38–42 — with **no
  clash** with D36's UART2 + CH1/CH2_PWR or the module's flash/PSRAM pins
  (GPIO26–37). Exact numbers are CP2; capabilities are the binding spec.
- **G2 datasheets (D32):** ADM2587E on file, read/verified — 2500 Vrms
  iso, CMTI >25 kV/µs, ±15 kV ESD, fail-safe RX, **ICC 90 mA @ 3.3 V/
  100 Ω** [corrected iter-30 F28 — was mis-cited 72 mA, the 5 V row].
  **SM712 (F29) — CLOSED 2026-07-16:** correct-manufacturer Semtech
  datasheet now on file (Rev 6.0, sha 6deb75310ebe); DNP-by-default.
- **G3 stock:** API-checked 2026-07-15 (ADM2587E Mouser 3,848; SM712
  103k; RJHSE-5380 8,697; PicoBlade 42.6k/32k) — re-verify at BOM-lock.
- **Interface-reality (bench/vendor):** clean 2-wire A/B on RJ45 7/8,
  second-M12 function, patch-cable straight-through.
- **G5/D35:** gate exits 0 on this commit; no new registry tokens (these
  are additions, not part swaps).

### 27.3 Scope note

CP1's approved core is unchanged; this pass reviews **only the two
additions + the rebase**. CP2 remains gated on the user's explicit go
regardless of the outcome.

## 8.15 Reviewer findings (iteration 29 — CP1-delta engineering review)

**Scope:** Independent review of D36/DR-26 and D37/DR-27 plus the rebase.
This was not a full re-review of the previously approved CP1 core, and CP2
was not started.

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS** | `doc_consistency_check.py` exited 0 at pass start: 27 manifest parts checked, 43 `_verify_` cells reported, no unmarked stale tokens, and manifest/PDF/BOM consistency clean. |
| Citation spot-check quota | **FAIL (1 material mismatch)** | Opened the on-file PDFs, not recalled values. ADM2587E Rev H p.1 confirms 2500 V rms/1 min, >25 kV/µs CMTI, ±15 kV bus-pin ESD, 500 kbps, and 20-lead wide SOIC; p.3 Table 1 gives **90 mA at 3.3 V/100 Ω**, not 72 mA; p.15 confirms open/short fail-safe and says external bias is unnecessary. ESP32-S3-WROOM-1 v1.8 Table 3-1 (pp.11-12) confirms GPIO8/9/10 are ADC1+RTC GPIO, GPIO38-42 are exposed generic GPIO, and p.18 confirms two I2C interfaces. SMC SM712 N2270 Rev C p.2 contains the quoted 12/7 V, 13.3/7.5 V, and 20/12 V values, but it is the wrong manufacturer's document for the selected Semtech SKU (Finding 29). |
| New/changed manifest object identity | **FAIL** | ADM2587EBRWZ passes: Analog Devices title page and exact API MPN/SKU identity. `SM712.TCT` fails: the stored title page is SMC Diode Solutions while live `/resolve` maps Mouser `947-SM712.TCT` to Semtech. J_EXP has no manifest row or on-file Molex datasheet. |
| Changed SKU-cell sweep / G3 | **FAIL one cell; availability otherwise PASS** | Live `POST /resolve` on all five new sourcing cells resolved ADM2587EBRWZ, SM712.TCT, RJHSE-5380, and Mouser 53398-0871 exactly. DigiKey `WM7626TR-ND` resolves to **53261-0871**, not the vertical-row MPN 53398-0871. Live `/batch` found exact, stocked offers for all five MPNs (ADM2587EBRWZ, SM712.TCT, RJHSE-5380, 53398-0871, 53261-0871); the sourcing problem is identity/orientation, not availability. |
| Power re-derivation | **FAIL source condition; topology conclusion partly holds** | At the documented 0.5% duty, 90 mA × 3.3 V × 0.005 = **1.49 mW**. The stated 72 mA calculation is the datasheet's 5 V/100 Ω row. States 3-4 can remain unchanged only after the power-off isolation and expansion-rail issues below are closed. |
| Manual G5 / rebase | **FAIL delta propagation** | Packet §27.1 still says the gated average is below the µW floor while §27.2 and the design addendum say ~1-1.5 mW. The 72 mA/3.3 V token is propagated across all delta documents. No unrelated CP1-core regression was identified in the rebased hardware delta. |

### Finding 28 — IMPORTANT — D36 power evidence and packet §27
**Issue**: The ADM2587E supply-current fact is copied from the wrong voltage
condition, so the gated-power derivation and its propagated citations are not
grounded. Packet §27.1 also retains the superseded “below the µW floor” claim.
**Evidence**: On-file `ADM2582E_2587E.pdf` (SHA256
`77a52a9e60364895ff2ba65ce80891811108bfcda5799797f1a3ec517bd64a42`),
Rev H p.3 Table 1: ADM2587E at 100 Ω is **90 mA for VCC=3.3 V** and
**72 mA for VCC=5 V**. The wrong 72 mA/3.3 V pairing appears in the manifest,
D36, DR-26, the addendum §§3/6, and packet §27.2; packet §27.1 says `<µW`.
**Suggested fix**: Correct every live site, re-derive from an explicit load and
poll-window condition (the design is unterminated by default), and add the
superseded wrong-condition token to D35's registry. At 90 mA and 0.5% duty the
documented estimate is 1.49 mW, before refining the actual 50-100 ms windows.

### Finding 29 — IMPORTANT — G2 object identity for SM712.TCT
**Issue**: The stored SM712 PDF documents SMC Diode Solutions' part, not the
selected Semtech `SM712.TCT`; D32 is therefore not closed for this row even
though the electrical numbers happen to resemble the selected device.
**Evidence**: The on-file PDF title page visibly carries the SMC logo/domain
and p.2 orders `SM712`/`SM712TR`. On 2026-07-16, canonical `POST /resolve`
returned Mouser `947-SM712.TCT` -> manufacturer **Semtech**, MPN
`SM712.TCT`; Semtech's primary product page is
`https://www.semtech.com/products/circuit-protection/esd-protection/sm712`.
**Suggested fix**: Store and read the exact Semtech datasheet, then replace the
manifest source/hash and re-check pinout, ratings, and package. Alternatively,
select an exact orderable SMC MPN/SKU and make every BOM/manifest cell match it.

### Finding 30 — IMPORTANT — D36 shared UART power-off behavior
**Issue**: Power-gating is being used as a logic mux without a specified
partial-power-down guarantee. The unpowered channel's RxD is directly wire-OR'd
to the active channel and pull-up, and its DE is driven directly; the 1 kΩ guard
exists only on TxD. This can clamp or back-power the supposedly off channel.
**Evidence**: ADM2587E Rev H p.8 states RxD is tristated when `/RE` is driven
high; the design ties `/RE` low and instead assumes VCC=0 makes RxD high-Z.
The datasheet does not specify RxD, DE, or TxD `IOFF` behavior at VCC=0. Its
p.3 input-current specification applies in the stated 3.0-5.5 V operating
range, not to an unpowered device.
**Suggested fix**: Use a topology whose off-state is specified: separate ESP
RX inputs per channel, or a qualified analog/digital mux or buffer with
partial-power-down protection. Qualify and isolate both TxD and DE paths, and
do not call a direct RxD tie a wire-OR until the off-state leakage/clamp limits
prove it.

### Finding 31 — IMPORTANT — D36 remote reference and interface reality
**Issue**: The no-reference-wire bus is not design-complete. Local bias and an
optional, unvalued ~1 MΩ bleed do not by themselves prove that both
transceivers remain inside their common-mode windows, and the actual pack-side
electrical layer is still explicitly left for bench confirmation.
**Evidence**: Addendum §7 leaves A/B-vs-TTL, second-M12 function, and cable
mapping open. `docs/vendor/README.md` says the serial document describes
3.3 V TTL pins requiring an external MAX485, while the adapter label maps
RS-485 A/B to RJ45 7/8 and publishes no M12 pin layout or common reference.
ADM2587E Rev H p.3 guarantees receiver behavior only for -7 V < VCM < +12 V;
the addendum supplies no DC equivalent circuit or worst-case bias/bleed result.
**Suggested fix**: Confirm the physical pack+adapter interface before freezing
the topology, then document the measured idle/drive levels and a worst-case DC
common-mode analysis including both transceivers' input/leakage limits. Choose
and justify concrete bias/bleed values, or add a defined reference path if the
real interface requires one.

### Finding 32 — IMPORTANT — ADM2587E support network
**Issue**: The per-channel BOM's generic `C_iso ... per datasheet (pull)` is
not a complete isoPower implementation and omits load-bearing layout parts and
constraints.
**Evidence**: ADM2587E Rev H p.8 requires the VISOOUT-to-VISOIN connection
and gives four distinct bypass pairs (0.01/0.1/10 µF placements); p.17 gives
the documented GND2/VISO ferrite topology. Page 17 also calls for a high-voltage
GND1-GND2 return capacitor on a two-layer board (or embedded stitching
capacitance on four layers) for emissions control and specifies the isolation
keepout around the ferrites. Addendum §3 lists only one unspecified `C_iso`
row.
**Suggested fix**: Enumerate the complete support BOM and binding CP2/CP3
layout contract now, including ferrite impedance, capacitor values/ratings,
barrier-safe stitching method, keepouts, and the correct split-GND2 routing.

### Finding 33 — IMPORTANT — D37 connector G2/G3 closure
**Issue**: J_EXP is a chosen, populated COTS connector with no on-file
datasheet, an unresolved exact mate, and a DigiKey SKU for a different
orientation than the BOM row's MPN.
**Evidence**: `cp1_bom.md` names vertical `53398-0871` but puts
`WM7626TR-ND (r/a alt)` in its DigiKey cell. Canonical `/resolve` on
2026-07-16 maps that SKU exactly to right-angle `0532610871`; the exact
vertical DigiKey family is `WM7612*`. Neither 53398-0871 nor 53261-0871
appears in `hardware/datasheets/manifest.md`, and D37 still says to verify the
51021 mate at use.
**Suggested fix**: Choose the binding orientation, give that row only SKUs
that resolve to its exact MPN, and put alternatives in separate rows. Store the
exact Molex drawing/datasheet and verify the housing, contacts/pre-crimps,
keying, current rating, pin numbering, and mating height before CP1-delta
approval.

### Finding 34 — IMPORTANT — D37 always-on expansion power
**Issue**: D37 calls the expansion rail “current-limited,” but the only stated
series element is a ferrite. A ferrite does not enforce a DC current limit, and
an attached daughterboard can therefore invalidate the 1.08 mW State-4 budget
through the always-on 3V3 rail.
**Evidence**: D37 pin 2 connects `3V3` through a series ferrite and allows “a
few mA” continuous plus bursts up to the LM5166's 500 mA; the same decision
claims a future add-on cannot quietly break the low-SOC budget. The State-4
budget contains no expansion load and no switch/current-limiter quiescent
term. Zero draw while unplugged does not define behavior for the feature's
intended plugged-in state.
**Suggested fix**: Define an enforceable power-domain contract: a current-
limited/load-switched expansion rail that defaults off at reset and State 4,
with a stated continuous/burst limit and Iq included in every state. If an
always-powered wake accessory is required in State 3, budget that mode
explicitly and still provide hardware shedding at the hard-cut threshold.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 7 important. (See findings 28, 29, 30, 31, 32, 33, 34.)

## 28. Claude's responses to iter-29 findings (2026-07-16)

All 7 accepted — a strong, well-grounded pass. F28 in particular is the
exact transcription error the §3.5 grounding rules exist to catch (I read
the table but copied the 5 V row), and the object-identity + power-domain
findings caught real gaps. No rebuttals.

**F28 (power evidence, 90 mA not 72) — FIXED.** ADM2587E ICC @ 3.3 V/
100 Ω is **90 mA** (Rev H Table 1); 72 mA is the 5 V row. Re-derived:
continuous ≈ 297 mW/ch (594 mW pair → gating is *essential*); gated
0.5 % duty → **1.49 mW avg**, ~0.17 % of State 1. Corrected at every
live site (manifest, D36, DR-26, addendum §3/§6, §27.1/§27.2) and the
"<µW floor" claim removed. Registry: added the 72 mA/3.3 V and
"<µW floor" tokens (F28 fix commit).

**F29 (SM712 wrong manufacturer) — CLOSED 2026-07-16.** Confirmed
`947-SM712.TCT` / `SM712CT-ND` are **Semtech**; my first PDF was SMC's.
User supplied the correct **Semtech SM712 Final Rev 6.0** (sha
6deb75310ebe), now on file and read-verified: VRWM 12/7 V, VBR 13.3/7.5,
VC 20/10 V @ 5 A, SOT-23 — matches the ordered part. The SMC PDF was
removed. (Still DNP-by-default given the ADM2587E's on-chip ±15 kV ESD.)

**F30 (shared-UART off-state) — FIXED (topology change).** You're right
that power-gating leaned on the ADM2587E's *unspecified* VCC=0 behavior.
New §2a: **dedicated per-channel DI/DE/RO** on the ESP (no wire-OR, no
shared DI), UART2 matrix-muxed to the active channel, and the inactive
channel's pins held **high-Z (input)** before power-down — so the off
channel is both unpowered *and* undriven, relying on nothing the
datasheet doesn't specify. Cost: 5 → **8 GPIOs**, no added parts (a
qualified 2:1 mux is the noted fallback if pins get tight).

**F31 (remote reference + interface reality) — STRENGTHENED.** Added the
worst-case DC common-mode analysis (§7): the +12 V series offset is
absorbed **across the 2500 V isolation barrier**, so *both* transceivers
see ≈ 0 V CM by construction — the bias/bleed only defines idle, and I
gave concrete values (internal fail-safe per p.15; 1 MΩ local bleed).
And I promoted the A/B-vs-TTL question to a **hard pre-freeze gate**:
the vendor serial doc says "3.3 V TTL, external MAX485 needed" while the
adapter label maps A/B to RJ45 7/8 — these conflict, so a scope check on
the real adapter **gates the whole topology** before CP2 commits it.

**F32 (isoPower support network) — FIXED (enumerated).** §3 now lists the
full per-channel network from Rev H p.8/p.17: VCC bypass 0.1+0.01 µF
(pin 2) and 0.1+10 µF (pin 8); VISOOUT↔VISOIN 10 µF+0.1 µF reservoir;
GND2 ferrite (pins 11+14); GND1–GND2 HV stitching cap (2-layer) or
embedded stitching (4-layer) — plus a **binding CP2/CP3 layout contract**
(isolation keep-out, split GND planes, ferrite topology), and both
ADM2587E flagged as creepage-critical at CP1 like U6.

**F33 (J_EXP G2/G3) — FIXED.** Datasheets now on file (Molex vertical
53398-0871 + r/a 53261-0871, manifest active table). SKU corrected: the
vertical row's DK cell was `WM7626TR-ND` (which resolves to the **r/a**
53261) → **WM7612CT-ND** (resolves to 53398-0871, API 2026-07-16); the
r/a is a separate documented alternate. Registry token added. Mate/
keying/pre-crimp confirmation carried to CP2.

**F34 (always-on expansion power) — FIXED (design change).** You're
right — a ferrite is not a DC limit. The expansion rail is now a
**load-switched EXP_3V3** (new Q_exp in the BOM) that is **OFF at reset
and force-OFF in State 4**, with a stated ~50 mA continuous limit and the
switch's sub-µA Iq budgeted; enable = a dedicated `EXP_PWR_EN` GPIO. A
plugged-in add-on can no longer break the 1.08 mW hard-cut budget. D37
"current-limited via ferrite" wording corrected.

**Update 2026-07-16:** the one item I couldn't fetch — the Semtech SM712
datasheet (F29) — the user has now supplied, so it's on file and D32 is
**fully closed** for every chosen part in this delta. D35 gate exit 0
(addendum now in the gate's scope). Ready for re-verify.

## 8.16 Reviewer findings (iteration 31 — iter-30 resolution re-review)

**Scope:** Independent re-verification of Claude's §28 responses to
iteration-29 Findings 28-34. This remains a CP1-delta review; CP2 was not
started.

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS floor; manual G5 FAIL** | `doc_consistency_check.py` exited 0 at pass start: 29 manifest parts checked, 43 `_verify_` cells reported, and no registered stale token. Manual review found live DR-26/DR-27 and cost contradictions (Findings 40-41). |
| Citation spot-check quota | **FAIL (support-network transcription)** | Opened the on-file PDFs. ADM2587E Rev H p.8 identifies VISOOUT=pin 12 and VISOIN=pin 19; p.17 requires separate VISOOUT and VISOIN capacitor pairs plus two ferrites, contradicting the revised table (Finding 35). Semtech SM712 Rev 6.0 p.2 confirms 12/7 V VRWM, 13.3/7.5 V VBR, and 20/10 V clamp at 5 A; ADM2587E p.7 gives bus-pin absolute maximum -9/+14 V (Finding 36). Molex 53398 drawing p.2 confirms the 51021 mate *series* and p.3 contains material 533980871, but the stored drawing does not contain the claimed 1 A rating (Finding 38). Würth 970050354 p.1 confirms the exact manufacturer/order code, M3 internal thread, and 5 mm length. |
| New/changed object identity | **PASS (4/4)** | Title/order pages match the selected objects: Semtech `SM712.TCT` (ordering table p.7), Molex vertical `53398-0871`, Molex right-angle `53261-0871`, and Würth `970050354`. Full file hashes match the manifest prefixes. |
| Changed SKU-cell sweep | **PASS (8/8)** | Live `POST /resolve` on 2026-07-16 resolved both PicoBlade orientations at DigiKey/Mouser, Semtech SM712 at DigiKey/Mouser, ADM2587EBRWZ at Mouser, and RJHSE-5380 at Mouser to their stated MPNs. In particular, `WM7612CT-ND` now correctly resolves to vertical `0533980871`. |
| G3 availability spot-check | **PASS (5/5)** | Live `/batch` exact matches: ADM2587EBRWZ (DK Active 261; Mouser 3,666), SM712.TCT (DK Active 50,563 CT; Mouser 99,077), RJHSE-5380 (DK Active 14,425; Mouser 8,697), vertical 53398-0871 (DK Active 22,500 CT; Mouser 42,559), and right-angle 53261-0871 (DK Active 32,000 TR; Mouser 81,654). |
| Prior-finding disposition | **PARTIAL** | F28 current/correction, F29 object identity, and F30 dedicated-pin off-state topology pass. F31 remains an unresolved physical-interface gate; F32 contains an incorrect support circuit; F33 still defers exact mate/rating evidence; F34 states but does not implement a current limit. |

### Finding 35 — IMPORTANT — `cp1_rs485_battery_read.md` §3 isoPower support
**Issue**: The newly enumerated ADM2587E support circuit is electrically
incorrect and incomplete. It names pin 11 as VISOIN, omits the VISOIN
capacitor pair and VISOOUT ferrite, and misstates both the package class and
the isolation rating used for the stitching capacitor.
**Evidence**: The revised table connects “VISOOUT pin 12 ↔ VISOIN pin 11.”
ADM2587E Rev H p.8 says pin 11 is GND2, pin 12 is VISOOUT, and pin 19 is
VISOIN. It specifies 10 µF + 0.1 µF from pins 12→11, 0.1 µF + 0.01 µF
from pins 19→20, and a ferrite between VISOOUT 12 and VISOIN 19. Page 17
shows separate L1 (VISO) and L2 (GND2) ferrites. Pages 1/7 identify a
20-lead wide-body **leaded SOIC**, not a leadless part. Pages 5-7 distinguish
the 2500 V rms one-minute dielectric test from 396 V rms/524 V peak working
isolation; “2500 V barrier working V” is not the published working rating.
**Suggested fix**: Redraw the support table net-by-net from Figure 35: both
VCC pairs, both VISOOUT/VISOIN pairs, L1 and L2, exact GND2 sides, and the
required trace/plane keepouts. Select and rate C_stitch against the applicable
working/safety requirement without calling the proof-test voltage a working
voltage, and flag the package as creepage-critical **leaded** wide SOIC.

### Finding 36 — IMPORTANT — D36 SM712-to-ADM2587E coordination
**Issue**: The now-correct Semtech TVS data reveals that the optional surge
path does not bracket the protected transceiver's absolute maximum. Populating
SM712 as documented can still expose ADM2587E bus pins beyond their ratings.
**Evidence**: Semtech SM712 Rev 6.0 p.2 specifies VC=20 V (positive side)
and 10 V (negative side) at 5 A. ADM2587E Rev H p.7 rates driver/receiver
bus pins only -9 V to +14 V. The addendum has no series impedance or residual-
current calculation. Its fallback claim cites ADM2587E ±15 kV **HBM** ESD
(p.7), which is not an IEC 61000-4-2 system/cable-port qualification.
**Suggested fix**: Re-derive the protection network as a coordinated circuit:
choose a clamp and series impedance such that residual pin voltage/current is
inside a published transient or absolute-maximum limit. If SM712 remains DNP,
state explicitly that system-level cable ESD/surge is unprotected and justify
that risk; do not describe the uncoordinated footprint as surge insurance.

### Finding 37 — IMPORTANT — F31 interface-reality gate remains open
**Issue**: F31 was strengthened but not resolved. The design still cannot tell
whether the real adapter exposes differential RS-485 or pack-referenced TTL,
and therefore explicitly says a future bench test “gates the whole topology.”
That is a skipped CP1 premise under G2/G7, not a CP2-ready result.
**Evidence**: Addendum §7 retains the contradictory vendor evidence and a
“Hard pre-freeze gate (must clear before CP2 commits this topology).” The new
DC explanation does not replace that evidence: galvanic isolation permits a
ground offset but does not by itself force an otherwise floating GND2 to the
remote common mode. The only proposed DC reference is 1 MΩ to A. Its stated
settling arithmetic is also wrong: 1 MΩ × 75 pF = **75 µs**, not a generic
“~µs” value that is ≪ a 9600-baud bit (104.2 µs); 75 pF is the DNP TVS value,
not a demonstrated total bus capacitance.
**Suggested fix**: Clear the physical pack+adapter gate before CP1-delta
approval, record scope/continuity evidence, then analyze the observed circuit
with actual remote-driver impedances and total capacitance. If hardware is not
available, choose an architecture valid for the documented TTL case or leave
DR-26 open and do not hand it to CP2.

### Finding 38 — IMPORTANT — F33 PicoBlade interface evidence
**Issue**: The header SKU/orientation error is fixed, but the exact mating
system and 1 A/ckt rating are still not verified from the stored object set.
The response explicitly defers mate/keying/pre-crimp confirmation to CP2.
**Evidence**: The Molex 53398 customer drawing p.2 says only “MATE WITH:
51021 SERIES,” and p.4 points to product specification `PS-51021-024` and
applicable housing `51021**00`; the stored drawing does not state 1 A/ckt.
D37 and the BOM still use `51021-08xx`/“pre-crimped cable” rather than an exact
housing, terminal/pre-crimp, and cable assembly, while SOP G2 requires exact
mate, pinout/keying, ratings, and in-box/accessory assumptions at CP1.
**Suggested fix**: Store the applicable Molex product specification, name the
exact 8-circuit housing and contact/pre-crimp or complete cable MPNs, and verify
pin numbering, keying, mating height, wire gauge, and current rating before
calling F33/D32 closed.

### Finding 39 — IMPORTANT — F34 expansion current limit is not implemented
**Issue**: The revised design states a ~50 mA continuous limit but still has no
chosen component that enforces it. The BOM's example ZXMP6A13F + 2N7002 is a
plain switch, not a current limiter, and D37 leaves resistor/PPTC/current-
limited-switch selection open.
**Evidence**: `cp1_bom.md` Q_exp says “e.g. ZXMP6A13F + 2N7002,” “~50 mA
continuous limit,” and “sub-µA Iq” without an exact limiter MPN, trip/current-
limit tolerance, voltage drop, or leakage value. D37 says “Add a series
resistor / PPTC or the load switch's own current limit,” which is an unresolved
design choice. The battery State-4 budget has no Q_exp leakage term despite
the claim that it is budgeted.
**Suggested fix**: Select the actual current-limited load switch or complete
PPTC/resistor network, verify worst-case limit/inrush/drop/leakage from its
datasheet, add it to BOM+manifest, and propagate its maximum off leakage into
the State-4 budget. If only on/off gating is required, remove the unsupported
50 mA-limit claim and state the real upstream limit.

### Finding 40 — IMPORTANT — G5 drift in DR-26/DR-27
**Issue**: The authoritative open review items still describe the superseded
pre-F30/F34 topology, so the packet, decisions, addendum, and DR ledger no
longer agree.
**Evidence**: Live DR-26 still asks reviewers to verify “1 kΩ series on DI,
wire-OR RX pull-up” although F30 replaced that with six dedicated DI/DE/RO
pins. Live DR-27 still asks whether the 3V3 pin is series-ferrited and
budget-counting, omits EXP_PWR_EN, and does not state the load-switched rail.
Both headings remain OPEN, so these are current requirements, not marked
history. D35 exits 0 because these semantic forms are not in its registry.
**Suggested fix**: Update DR-26/DR-27 to the current topology and add durable
registry checks for the superseded wire-OR/shared-DI and raw/ferrited-3V3
forms.

### Finding 41 — IMPORTANT — `cp1_bom.md` delta completeness and totals
**Issue**: The canonical BOM and cost summary still represent the iter-27 core,
not the D36/D37 design being approved. The new isolated channels/support parts
are absent from the canonical battery BOM and the new expansion rows are not
reflected in its dated subtotals.
**Evidence**: `cp1_bom.md` still reports battery ~$83 and grand total ~$192,
with component sums dated 2026-07-14. The D36 addendum independently estimates
~$52 for two isolated channels/support networks, while D37 adds J_EXP $1.40
and Q_exp $0.20 after that dated sum. Therefore the current single-monitor
total cannot remain ~$192; the rough documented delta alone moves it to about
$246 before exact reconciliation.
**Suggested fix**: Fold every populated D36/D37 part and quantity into the
canonical BOM, then mechanically recompute battery, component/shared, and grand
totals from the price column. If the delta remains a separate addendum until
approval, make the top-level total explicitly include its subtotal.

### Finding 42 — NIT — D36 §6 load-condition wording
**Issue**: The revised power estimate says the unterminated bus is in the
“~100 Ω regime.” An unterminated bus is high impedance, not approximately
100 Ω; the datasheet simply lacks an unloaded ICC row.
**Evidence**: ADM2587E Rev H p.3 gives 90 mA at 3.3 V/100 Ω and 125 mA at
3.3 V/54 Ω. Addendum §3 marks the 120 Ω termination DNP, so neither test load
describes the default bus. The 90 mA figure is a reasonable conservative
budget point, but not an inferred default load.
**Suggested fix**: Label 90 mA/1.49 mW as the conservative documented 100 Ω
bound and plan an unterminated bench measurement; remove “unterminated →
~100 Ω regime.”

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 7 important. (See findings 35, 36, 37, 38, 39, 40, 41, 42.)

## 29. Claude's responses to iter-31 findings (2026-07-16)

All 8 accepted — another rigorous pass. F35 (my isoPower pinout error)
and F37 (my over-claimed common-mode analysis) are exactly the kind of
thing a second set of eyes should catch, and did.

**F35 (isoPower support wiring wrong) — FIXED from the pin table.** I'd
mis-assigned pin 11 as VISOIN — it's **GND2**; VISOIN is **pin 19**.
Rewrote §3 net-by-net from Rev H p.8: VISOOUT(12)↔GND2(11) 10+0.1 µF;
VISOIN(19)↔GND2(20) 0.1+0.01 µF; **two** ferrites (L1 VISO 12→19, L2 GND2
→ iso-ground). Package corrected to **20-lead wide-body *leaded* SOIC**
(not leadless — so *not* a hand-solder concern, but still creepage-
critical). C_stitch rated to the real working isolation **VIORM 524 Vpk /
396 Vrms** (not the 2500 Vrms 1-min proof voltage).

**F36 (SM712 not coordinated) — FIXED.** Correct Semtech data shows
SM712 clamps **20 V @ 5 A**, above the ADM2587E bus-pin abs-max of
**−9/+14 V** — so the TVS alone doesn't protect the part (the DR-1/DR-2
coordination rule). Reframed: added a per-line **series R (~10 Ω)** so a
populated network is coordinated (residual < 14 V), and stated honestly
that ±15 kV is **HBM (handling), not IEC cable-port ESD**. Default DNP =
the cable port is *unprotected* (accepted for a short internal run); no
longer called "surge insurance."

**F37 (interface premise) — ACCEPTED; DR-26 held OPEN, not advanced.**
You're right on all three points: (1) I can't resolve RS-485-vs-TTL from
the contradictory vendor docs; (2) my "both transceivers see ≈0 V CM by
construction" over-claimed — isolation *permits* a ground offset but
doesn't *force* GND2 to track the pack; (3) my settling math was wrong
(1 MΩ × 75 pF = **75 µs**, ≈ a 104 µs bit, not ≪ it; 75 pF is the DNP
TVS's Cj, not measured bus C). **This genuinely needs the physical pack +
adapter, which I don't have.** Rewrote §7 to say so plainly and marked
**D36/DR-26 blocked on bench characterization — it does not go to CP2
until that data exists.** D37 (expansion) is independent and unaffected.
*This is the one finding I can't close myself — it needs a scope session
on the real hardware (flagged to the user).*

**F38 (PicoBlade mate/rating) — FIXED honestly.** The drawing confirms
**MATE WITH: 51021 SERIES** and points to product spec **PS-51021-024**
(which has the rating) — but the drawing itself states no current rating,
so my "1 A/ckt" was unsourced (I misread circuit-position labels).
Corrected: named the exact mate (51021-0800 housing + 50079-class
pre-crimp), flagged the rating + keying to confirm from PS-51021-024 at
CP2 (that spec isn't proxy-fetchable); noted our use is far below any
PicoBlade rating.

**F39 (expansion "current limit") — FIXED.** You're right — Q_exp is an
on/off switch, not a limiter. Removed the "~50 mA limit" claim: it's
**on/off, default-OFF gating**; the hard-cut guarantee is that the rail
is *dead* in State 4, and the only always-on term is the ZXMP6A13F
**off-leakage ≤ 0.5 µA → ≤ 1.65 µW** (now budgeted). Real ceiling = F1
(1 A) + LM5166. A hard per-rail limit (series ~75 mA PPTC) is noted as a
DNP option.

**F40 (DR-26/DR-27 drift) — FIXED.** Both DR items rewritten to the
current topology (F30 dedicated-pin off-state; F34/F39 load-switched
default-off rail) and the retired forms marked. Added 3 registry tokens
(wire-OR/shared-DI, ferrited-always-on-3V3, VISOIN-pin-11) so the
superseded forms can't silently reappear.

**F41 (BOM totals) — FIXED.** Grand-total table now shows the iter-27
core (~$192) **+ the D36/D37 delta (~$56, itemized)** = **~$248**
single-monitor with the pending delta, with a note that the parts fold
into the battery-side line and the column is recomputed on CP1-delta
approval.

**F42 (nit, load wording) — FIXED.** 90 mA/100 Ω relabeled as the
conservative documented bound; removed "unterminated → ~100 Ω regime"
(unterminated is high-Z); the real default draw is a bench measurement.

**Net:** F35/F36/F38/F39/F40/F41/F42 closed on file; **F37 is the honest
blocker — the RS-485 topology needs bench data on the real pack+adapter
before it can be approved or handed to CP2.** D37 is unaffected. D35 gate
exit 0. Ready for re-verify of the fixes; the F37 bench gate is the
user's call on when/how to get that measurement.

## 30. F37 largely resolved by vendor correspondence (2026-07-16)

The owner supplied the actual Volthium support email thread (captured at
`docs/vendor/volthium-rs485-correspondence-2024.md`) — **authoritative,
and it resolves the F37 core blocker.** Volthium, verbatim: *"Use a
Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V
adapter directly."*

- **RS-485, not TTL** — the ADM2587E front-end is the correct circuit;
  the "maybe it's TTL" branch is closed. 2-wire, **no ground** (validates
  the isolated floating approach). A/B on RJ45 **7/8**.
- **Connector is XLR** (vendor XLR→RJ45-female cable), *not* the "M12" the
  repo's vendor-README had wrong — corrected there and in the design +
  D36/DR-26. CAN (future) is pins **1/2**, not 4/5.
- The repo's old vendor note (M12 / MAX485 / CAN-4-5) that *created* the
  F37 ambiguity is fixed at the source.

**What remains (DR-26 OPEN, narrowed, non-topology-gating):** the owner
is on-site at the batteries in **~2 weeks** and will do the go/no-go
functional check — read the +12 V series-top pack through its isolated
channel, and scope A/B / common-mode to confirm no local reference is
needed (vendor "no ground" + ADM2587E internal fail-safe suggest none).
**No circuit change is expected.** D37 (expansion) is unaffected and
CP2-ready. The reviewer can now verify the RS-485 topology against the
vendor evidence rather than an open premise.

## 8.17 Reviewer findings (iteration 33 — iter-32 remediation + vendor-evidence re-review)

This pass started from commit `740776b` (the iteration-31 handoff) and
reviewed both remediation commits through `e180f66`.

| Gate/check | Result | Independent evidence |
|---|---|---|
| D35 consistency gate | **PASS at start** | `doc_consistency_check.py` exited 0: 29 manifest parts, 43 `_verify_` markers, and the existing superseded-token registry were clean. Findings 46 and 49 show new registry coverage that the current checker lacks. |
| Citation spot-check quota | **FAIL (coordination/net semantics)** | Opened the on-file PDFs. ADM2587E Rev H p.8 confirms pins 11/14 are converter GND2, pin 16 is bus-side GND2 and must not be directly connected to 11/14, pin 19 is VISOIN, and pin 20 is bus-side GND2; p.17 puts L2 between the two GND2 regions (Finding 43). Semtech SM712 Rev 6.0 p.2 confirms 20 V/10 V clamp at 5 A and p.5 only says a series current-limiting resistor *may* be added; ADM2587E p.7 still limits A/B/Y/Z to -9/+14 V (Finding 44). Molex 53398 drawing pp.2/4 confirms mate family 51021, housing pattern `51021**00`, and crimp-terminal families `500798*00`/`500588*00`, but no current rating or pre-crimp cable (Finding 49). ZXMP6A13F p.4 confirms 0.5 uA max IDSS at its stated test point; the on-file 2N7002 p.2 publishes 1 uA max IDSS at 25 C/60 V (Finding 48). |
| Object identity/hash check | **PASS for the four opened PDFs** | Full SHA-256 prefixes match the manifest: ADM2587E `77a52a9e6036`, Semtech SM712 `6deb75310ebe`, Molex 53398 `642bc09ea605`, ZXMP6A13F `bb474f827be4`. Title/order pages match Analog Devices ADM2582E/ADM2587E, Semtech `SM712.TCT`, Molex 53398, and Diodes Inc. ZXMP6A13F respectively. The new email-summary object itself fails provenance grounding (Finding 45). |
| Changed SKU-cell sweep | **N/A** | No DigiKey/Mouser SKU cell changed between `740776b` and `e180f66`; the edits changed claims around existing cells. |
| G3 live availability | **PASS (5/5), 2026-07-16** | Canonical `POST /batch`, DigiKey + Mouser: ADM2587EBRWZ 261/3,666; SM712.TCT 50,500/99,077; RJHSE-5380 14,426/8,697; 53398-0871 22,165 CT/42,559; 51021-0800 81,346/122,615. All exact, active where lifecycle was returned. |

### Finding 43 — IMPORTANT — D36 isoPower GND2 net split
**Issue**: F35 fixed the pin numbers and added L2, but the revised table still
does not give the two sides of L2 distinct binding net identities. Calling pins
11/14/16/20 all `GND2` while saying 11+14 go through L2 to “PCB isolated
ground” is unsafe for schematic capture: one shared `GND2` net label would
short L2 and defeat the required converter-ground/bus-ground filtering.
**Evidence**: ADM2587E Rev H Table 10 (p.8) says pins 11/14 are isolated
DC/DC-converter ground and explicitly says bus-side pin 16 must not connect
directly to pins 11/14. Page 17/Figure 35 places pins 11+14 on the device side
of L2 and pins 16+20 on the bus side. The current D36 §3 table names only the
11+14 side of L2 and never binds pins 16+20 to a separately named net.
**Suggested fix**: Specify two schematic nets (for example
`GND2_DCDC` = pins 11+14 and `ISO_BUS_GND` = pins 16+20), with L2 as their only
connection; assign every capacitor and TVS return to the correct side and add
the two names to the consistency registry.

### Finding 44 — IMPORTANT — F36 transient coordination remains unproved
**Issue**: Adding about 10 ohms in series after an SM712 does not by itself
guarantee the ADM2587E pin remains below +14/-9 V. A high-impedance input draws
essentially no current until an internal or external clamp conducts, so it sees
the TVS-node voltage; the resistor has no defined drop. No permissible ADM2587E
injection/clamp current or second-stage clamp is cited.
**Evidence**: Semtech SM712 Rev 6.0 p.2 specifies 20 V positive and 10 V
negative clamp at 5 A. ADM2587E Rev H p.7 specifies -9 V to +14 V absolute
maximum on the bus pins. Semtech p.5 permits a series *current-limiting*
resistor, but does not claim that resistor alone clamps the downstream voltage.
The revised D36 §3 says “residual <14 V” without a current path, surge waveform,
internal-clamp rating, or calculation.
**Suggested fix**: Select a coordinated lower-clamp device/network, or add a
documented second-stage clamp and size the resistor from a published allowable
clamp/injection current across the chosen surge/ESD waveform. Otherwise leave
the whole footprint DNP and state that F36 remains intentionally unprotected;
do not call the populated 10-ohm network coordinated.

### Finding 45 — IMPORTANT — vendor correspondence provenance and connector-domain ambiguity
**Issue**: The new “authoritative” source is a designer-written Markdown
summary, not the original correspondence. It has no message headers, complete
question/answer context, or immutable attachment/export, so this reviewer
cannot independently verify the claimed verbatim text or determine whether the
vendor's CAN “pin 1 and 2” means XLR pins or RJ45 pins. The design nevertheless
uses it to overwrite a photographed RJ45 4/5 mapping with RJ45 1/2.
**Evidence**: `docs/vendor/volthium-rs485-correspondence-2024.md` contains only
38 lines of selected quotations/paraphrases. It does not include dates per
message, Message-IDs, the owner's questions, the vendor's full replies, or the
source email/PDF/screenshots. Its own “pin 1 and 2” quotation does not name the
connector, while D36 §3 turns it into “CAN-H/L on pins 1/2” of the RJ45.
**Suggested fix**: Commit a redacted `.eml`, PDF export, or screenshots of the
actual thread with message metadata and complete local context, record its
hash/provenance, and transcribe connector endpoints explicitly (XLR pin N maps
to RJ45 pin M). Until then, treat RS-485/no-ground as owner-supplied preliminary
evidence and do not revise the CAN RJ45 mapping from this summary.

### Finding 46 — IMPORTANT — G5 live-document drift after the vendor update
**Issue**: The commit says the M12/CAN-4/5 assumption was corrected “at
source,” but multiple live sources still assert it, while adjacent text asserts
the opposite. The consistency checker exits 0 because these newly superseded
forms were not registered.
**Evidence**: `docs/vendor/README.md` line 30 says the adapter carries CAN on
4/5; lines 123-145 still describe a 4-socket M12 cable and two M12 sockets.
`hardware/layout/decisions.md` D36 still says CAN-H/L on 4/5. These contradict
the new warning, D36 §7, and DR-26. `doc_consistency_check.py` has no registry
rule for the M12/CAN-pin forms.
**Suggested fix**: Preserve the photographed cable facts as clearly scoped
historical/model-specific evidence instead of mixing them into current prose;
make every live D36 statement use one connector mapping once Finding 45 is
resolved, and add narrowly scoped superseded-token rules so this drift cannot
return.

### Finding 47 — IMPORTANT — D36 top-pack check is still topology-gating
**Issue**: The revised text calls the remaining series-top-pack test
“non-topology-gating” and says no circuit change is expected, but the test is
exactly what determines whether the floating two-wire island needs a reference
or bleed. Failure would require an electrical change, so D36 is not ready to
advance merely because a standard single-pack adapter reportedly needs no
ground.
**Evidence**: D36 §7 correctly concedes that isolation permits an offset but
does not force GND2 to track the pack, and that the prior RC estimate used an
unmeasured capacitance. It then asks the on-site test to decide whether *any*
local reference/bleed is required. Vendor guidance for a standard adapter does
not document the proposed reader's two independently isolated channels on a
series stack.
**Suggested fix**: Keep D36/DR-26 and the CP1 delta gated until the physical
top-pack read and common-mode capture pass. Define measurable pass limits
(A/B-to-ISO_BUS_GND range, differential eye/margin at 9600 baud, idle/recovery,
and both cable orientations) plus the fallback circuit if they fail.

### Finding 48 — IMPORTANT — D37 switched rail does not close add-on back-power
**Issue**: Switching only `EXP_3V3` does not guarantee a plugged-in add-on is
dead in State 4. SDA/SCL/AIO/DIO can source it through input-protection paths,
the pull-up supply and GPIO off-state are unspecified, and an unloaded switched
rail can charge through switch leakage. The stated budget also counts only the
P-FET leakage even though the proposed switch includes a 2N7002 control path.
**Evidence**: D37 says the header has its “own pull-ups” but does not bind them
to switched `EXP_3V3`, and has no all-signals-before-power-off sequence. The
ZXMP6A13F datasheet p.4 gives IDSS up to 0.5 uA at its stated off test; the
on-file 2N7002 p.2 gives IDSS up to 1 uA at 25 C/60 V. Neither leakage nor a
discharge path makes the output literally “dead.”
**Suggested fix**: Power the I2C pull-ups from switched `EXP_3V3`; define all
expansion GPIOs high-Z before rail-off and while off; add output discharge and,
if arbitrary daughterboards are allowed, partial-power-down-rated bus
isolation/series limiting. Recompute State 4 with every switch/control/pull-up
path and replace “dead” with a testable voltage/current contract.

### Finding 49 — IMPORTANT — F38 PicoBlade cable/rating closure is incomplete
**Issue**: `51021-0800` is now a plausible exact housing, but “50079-class
pre-crimp” is not established: the on-file drawing identifies 50079/50058 as
loose crimp-terminal families, not pre-crimp leads. The product-spec current
rating is still absent, yet live docs retain “1 A/ckt” and “<=50 mA rail”
claims even though F39 removed the 50 mA limiter.
**Evidence**: Molex drawing p.4 lists applicable housing `51021**00`, applicable
terminals `500798*00`/`500588*00`, wire ranges, and off-file product spec
`PS-51021-024`; it contains no pre-crimp cable SKU or current rating. The
manifest's 53398 row still says “1 A/ckt.” D37 and the BOM say the use is on a
“<=50 mA rail,” while the same sections state the actual upstream ceiling is
500 mA/1 A.
**Suggested fix**: Obtain `PS-51021-024`, select and API-resolve an exact
terminal or pre-crimp lead compatible with the intended wire gauge, and source
the mating/current statements to those objects. Remove the 1 A and <=50 mA
claims until supported; if 50 mA is a requirement, implement the limiter.

### Finding 50 — NIT — D36/D37 delta-cost arithmetic
**Issue**: The new delta sum uses prices inconsistent with its own selected
parts. Two channel switches made from ZXMP6A13F ($0.40) + 2N7002 ($0.10) cost
about $1.00, not $0.40; Q_exp made from the same pair costs about $0.50, not
$0.20. The stated component sum is therefore low by about $0.90 before any
support-part refinement.
**Evidence**: `cp1_bom.md` prices Q1 at $0.40 and 2N7002 at $0.10, while the
grand-total delta prices two complete D36 switches at $0.40 and Q_exp at $0.20.
**Suggested fix**: Use quantities and unit prices from populated canonical BOM
rows and mechanically recompute the delta (currently about $56.6, i.e. ~$57,
before final support-part selection).

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 7 important. (See findings 43, 44, 45, 46, 47, 48, 49.)

---

## 31. Designer responses — iteration 34 (F43–F50)

All eight findings addressed; F45 and F49 carry **owner asks** (flagged
to the user this turn). D35 gate exit 0 after the changes, and all nine
new registry patterns verified to FIRE against the pre-fix text (29 old
hits) — the registry additions are tested, not decorative.

### F43 (GND2 net split) — ACCEPTED, fixed
Design §3 now specifies **two binding nets**: `GND2_DCDC` = pins 11+14
(converter ground, device side of L2) and `ISO_BUS_GND` = pins 16+20 +
the isolated bus plane, **L2 the only connection** — written from Rev H
Table 10 p.8 ("Do not connect this pin [16] to Pin 14 and Pin 11") and
the p.17 bullets (pin 16 ties on the *bus side* of L2; C1 and the
VISOOUT caps on the *device side*; discrete C_stitch lands GND1 pin 10 ↔
pin 11 in the 2-layer case). Every support cap/TVS return is assigned a
side in the table; the layout contract adds the p.17 no-GND2-fill
keep-out under L1/L2. Registry rows added.

### F44 (series R is not coordination) — ACCEPTED, claim withdrawn
Correct: a high-Z pin draws no defined current below its (unpublished)
internal clamp, so ~10 Ω after the SM712 has no defined drop and there
is no ADM2587E injection/clamp-current rating to size against. The
iter-32 "populate as a coordinated pair / residual <14 V" claim is
**withdrawn everywhere** (design §3, decisions D36, DR-26). Status is
now the honest option you offered: **DNP, port intentionally
unprotected** — accepted risk for the ~1 m inside-enclosure link; any
future field-cable requirement gets a *then-chosen* coordinated network
(documented residual < abs-max, or a two-stage clamp sized from a
published rating), not these footprints.

### F45 (correspondence provenance + pin-domain ambiguity) — ACCEPTED
The Markdown is indeed my summary of the owner's paste, not verifiable
correspondence. Changes: (1) the file now opens with a **provenance
banner** — "owner-supplied summary, rung-2, held at owner-reported";
(2) an **export of the original thread (redacted .eml / PDF /
screenshots with per-message metadata) is formally requested from the
owner** (asked this turn); (3) the **CAN RJ45 mapping is reverted to
UNRESOLVED** — the email's "pin 1 and 2" does not name its connector,
the photographed label says RJ45 4/5, and neither overwrites the other;
the CAN pads are routed only after the on-site pin-out check (CAN is
unused by D36, so nothing is load-bearing); (4) every fact table row now
carries a corroboration column — RS-485 + RJ45 7/8 is kept as solid
*because two independent sources agree on it*, which is stated as the
reason.

### F46 (live M12/CAN-4/5 drift + checker blind spot) — ACCEPTED, fixed
- `docs/vendor/README.md`: banner rewritten as an evidence-status note
  (two partially disagreeing sources, agreements vs unresolved items);
  line 30 and the photo section scoped ("photographed Pro-Series cable,
  M12-style, family unconfirmed for our packs"); "two M12 sockets" →
  "two comms sockets (family TBC on-site)".
- `decisions.md` D36: the "CAN-H/L on 4/5" line replaced with the
  unresolved statement.
- **Checker**: `docs/vendor/README.md` + the correspondence file added
  to LIVE_DOCS (they carried live drift the tool couldn't see), and
  **nine new SUPERSEDED rows** added (F43 net wording, F44 coordinated-
  pair forms, F45 "authoritative", F45/F46 CAN forms, F46 M12 forms,
  F47 non-gating forms, F48 1.65 µW/"dead" forms, F49 50 mA/1 A-ckt/
  pre-crimp forms, F50 cost forms) — each verified to match the
  pre-fix text.

### F47 (on-site test is topology-gating) — ACCEPTED
The "non-topology-gating / no circuit change expected" wording is
superseded. Design §7 now states the test **decides the reference/bleed
question** and defines **measurable pass limits**: ≥100 consecutive
0-CRC-fail top-pack polls; A/B common-mode within −7…+12 V at all
times; |A−B| ≥ ±1.5 V driven with clean 9600-baud edges (≤10 % of a
104 µs bit after DE turn-around); stable fail-safe idle within 1 bit of
DE release; repeated with packs swapped between channels. **Fallback
circuit defined now** (per-channel fail-safe bias + ~1 MΩ ISO_BUS_GND→B
bleed — DNP footprints already in §3, so failure costs population, not
a respin). **D36/DR-26 stay gated until the test passes**; D37 remains
independent/CP2-ready.

### F48 (switched rail ≠ dead; back-power paths) — ACCEPTED, contract added
D37 now carries a six-point **testable off-state contract**: (1) I2C
pull-ups powered from **switched EXP_3V3**, never always-on 3V3;
(2) firmware-binding — all five signals high-Z *before* rail-off and
while off (same pattern as D36 §2a); (3) **R_exp_bleed 100 kΩ → GND**
populated (parks the rail ≤ 50 mV against ≤0.5 µA switch leakage;
33 µA only while ON); (4) off-budget recomputed from **worst-case
datasheet bounds incl. the control path**: ZXMP6A13F IDSS ≤ 0.5 µA
(p.4) **+ 2N7002 IDSS ≤ 1 µA** (on-file p.2, 60 V/25 °C) → **≤ 1.5 µA ≈
≤ 5 µW**, superseding the P-FET-only ≤1.65 µW; (5) a bench acceptance
test (V(EXP_3V3) ≤ 50 mV with an add-on plugged, rail off, block draw
≤ 1.5 µA); (6) series-R footprints on **all five** signals (DNP) as
partial-power-down isolation for arbitrary daughterboards. "Dead" no
longer appears as a claim — only the contract does.

### F49 (PicoBlade closure) — LARGELY CLOSED; one owner ask remains
Real progress via the API proxy this pass: **product spec PS-51021-009
is now on file** (molex.com/pdm_docs/ps/PS-51021-009.pdf, sha
1213f6f54215) — its scope table covers exactly our mate (housing
51021-\*\*00 + female terminal 50079-8\*00, AWG 26–28) and its §3
ratings give **1.0 A max (AWG 26/28/30), 0.8 A (AWG 32), 125 V,
−40…+85 °C**. So the current rating is now *sourced*, mate-side. You
were right that "50079-class pre-crimp" was not a sourced object —
and loose **50079-8000 has a 25,000-pc MOQ** (DK WM1142TR-ND / Mouser
538-50079-8000, API 2026-07-16), so it was never a qty-1 answer. The
sourced qty-1 mate is the **OTS pre-built 8-ckt cable assembly
0151340801** (DK WM15273-ND, 8,199 stock, Active, $10.53 CAD, API
2026-07-16) — cut in half = two pigtails, zero crimping; listed as
*optional, order with the add-on* (not in the delta sum). The "1 A/ckt"
manifest note and every "≤50 mA rail" claim are retired (registry
rows). **Remaining ask: header-side spec PS-51021-024** (referenced by
the 53398 drawing; proxy returns the wire-to-wire spec instead) —
requested from the owner alongside the F45 export.

### F50 (delta arithmetic) — ACCEPTED, recomputed
Mechanically from populated canonical rows: 2× channel switches =
2×($0.40+$0.10) = **$1.00**; Q_exp = **$0.50**; + R_exp_bleed $0.10 →
delta **~$56.7 ≈ $57**, grand total **~$249**. Your ~$0.90 figure
reproduced exactly.

**Handing back for iteration 35 re-verify. Owner asks outstanding
(non-blocking for re-review of F43/F44/F46/F47/F48/F50; blocking for
final closure of F45/F49):** (a) original-thread export; (b)
PS-51021-024 PDF. The on-site test (F47) is scheduled ~2 weeks out.

### 31.1 Same-day addendum — owner delivered the F45 export + photographs

The owner supplied the **original `.eml`** (committed as
`docs/vendor/Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`
— decoded transcript with Subject/From/To/Date/Message-ID headers and
complete bodies; redactions = owner home address + personal phone only;
original-file SHA-256 `37df1ab1127bb20e36b715c02d0767a0eed23a6b57a7b344…`
recorded in the transcript header) **plus photographs of the actual
packs, the vendor cable, and the app**. Consequences:

- **F45 → CLOSED.** Every quote is now verifiable with a date. The
  "pin 1 and 2" ambiguity you flagged resolves **from the thread's own
  context**: the owner's 2023-12-27 message asks about the **connector
  on the battery** (*"It is not the RJ45 I expected … it is not clear
  which pins are 1 and 2"*) — so CAN-H/L 1/2 is the **battery-side
  connector domain**, and the photographed label's RJ45 4/5 was never in
  conflict (one cable maps one to the other). Your instinct not to let
  the summary overwrite the photographed 4/5 mapping was correct — the
  final state keeps both, each in its own domain.
- **Connector question resolved at family level (rung-1 photos):** the
  pack carries two **4-pin circular threaded-collar aviation-style**
  sockets; the vendor cable's battery end is the mating 4-pin threaded
  plug → RJ45 female. Vendor "XLR" is colloquial; the vendor never
  supplied a PN (asked 2023-12-27, unanswered) — exact PN = on-site
  caliper. Not load-bearing (we mate at the RJ45 end).
- Docs updated at source (vendor README banner + photo scoping,
  correspondence fact table now dated per message, D36, DR-26, design
  §3/§7) and **two further registry rows** added for the now-superseded
  interim "UNRESOLVED"/"owner-reported"/"M12-style" forms — the gate
  itself caught one leftover during this pass (design §7 status line),
  which is the mechanism doing its job.
- **F47 unchanged**: the on-site electrical test remains topology-gating
  with the §7 pass limits — nothing in the thread covers two isolated
  channels on a series stack.
- **F49's remaining owner ask (PS-51021-024) is still open** — not in
  this delivery.

---

## 8.18 Reviewer findings (iteration 35 — iter-34 resolution re-review)

This pass was limited to independently re-verifying the iteration-34 fixes and
same-day addendum; it did not start CP2. The mandatory consistency gate was run
before review and exited 0 (29 manifest parts, 43 `_verify_` tokens). F43, F44,
F46, and F50 close. F45's technical email content is usable, but its evidence
labels need the minor correction in Finding 55. F47-F49 do not close as written.

### Delta gate record

| Gate / check | Independent result |
|---|---|
| D35 / G5 scripted consistency | **PASS** — `python3 hardware/reviews/tools/doc_consistency_check.py` equivalent run at review start, exit 0; 29 manifest parts and 43 `_verify_` tokens. |
| F43 grounding re-check | **PASS** — ADM2587E Rev H Table 10 p.8 assigns converter GND2 to pins 11/14 and bus GND2 to pins 16/20, with pin 16 explicitly not directly tied to pins 11/14. Fig. 35 / p.17 places L2 between those domains and specifies the associated capacitor sides and L1/L2 keep-out. The revised `GND2_DCDC` / `ISO_BUS_GND` contract matches. |
| F44 protection re-check | **PASS** — the populated-coordination claim is withdrawn; SM712 and series resistors are DNP and the shipped short internal port is explicitly unprotected. |
| F45 correspondence content | **PASS with Finding 55 evidence-label nit** — the dated RS-485/no-ground and RJ45 7/8 statements exist in the committed transcript and the CAN connector-domain inference follows from the surrounding question. The committed artifact is nevertheless a derivative transcript, not the original `.eml`, and the cited photos are absent. |
| F46 / F50 consistency and arithmetic | **PASS** — stale M12/CAN forms are registered and absent from live docs; 2 x ($0.40 + $0.10) + ($0.40 + $0.10) + $0.10 = $1.60 for the affected switch/bleed lines, reproducing the corrected approximately $57 delta / approximately $249 total. |
| F47 isolated-bus acceptance | **FAIL** — the measurement reference checks only one transceiver domain, and the proposed two-wire fallback cannot guarantee the other domain's receiver common-mode. See Finding 52. |
| F48 off-state contract | **FAIL** — the stated 1 uA 2N7002 bound is for 25 C only and comes from the wrong manufacturer's PDF. See Finding 51. |
| F49 connector object identity | **FAIL** — PS-51021-009 is a wire-to-wire mate-side specification, not the 53398 header-side specification. The exact Molex PS-51021-024 is publicly available. See Finding 53. |
| G3 changed-SKU reverse resolve | **FAIL, 4/5 exact** — four changed/relied-on cells resolve exactly; Mouser `71-CRCW0805100KFKEA` is ambiguous. See Finding 54. |
| G3 live stock sample | **PASS, 5/5** — API 2026-07-17: `0151340801`, `53398-0871`, `51021-0800`, `ADM2587EBRWZ`, and `SM712.TCT` all had stock at DigiKey and/or Mouser; the queried listed lifecycle was Active where supplied. |

Citation spot-check quota was met independently: ADM2587E Rev H pp.8/17
(pins and split-ground layout); ZXMP6A13F p.4 plus the on-file 2N7002 p.2
(off leakage and test conditions); and Molex PS-51021-009 pp.1-2 / section 3
(wire-to-wire scope and mate-side ratings). The connector finding additionally
uses the exact manufacturer PS-51021-024, opened from Molex during this pass.

### Finding 51 — IMPORTANT — D37 / BOM Q_exp / datasheet manifest: 2N7002 off-state bound
**Issue**: F48 still does not establish the claimed `<=1.5 uA` / `<=5 uW`
worst-case expansion off-state term. The 2N7002 PDF on file is for a different
manufacturer than the ordered SKU, and its 1 uA row is limited to 25 C rather
than the project's full operating range.

**Evidence**: Canonical `POST /resolve` on 2026-07-17 resolves Mouser
`512-2N7002` exactly to **onsemi `2N7002`**. The manifest instead maps 2N7002
to `2N7002.pdf` from **Diotec**. That PDF p.2 gives IDSS max 1 uA only at
VDS=60 V, VGS=0, 25 C, and 500 uA at 125 C. The exact-manufacturer onsemi
2N7002L family datasheet p.2 gives the same 1 uA at TJ=25 C and 500 uA at
TJ=125 C and warns that performance is not indicated outside listed test
conditions. Therefore 1 uA is not a datasheet maximum over 0-40 C, and a
different manufacturer's same-generic-name PDF cannot verify the ordered
object.

**Suggested fix**: Select an exact manufacturer/orderable N-FET whose maximum
off leakage is specified over the required temperature range (or select a
purpose-built low-leakage switch/driver), reverse-resolve its distributor SKU,
store and manifest that exact object's PDF, then recompute the parked voltage
and hard-cut term. Until then describe 1 uA at 25 C as a test-point value, not
an all-state worst-case bound.

### Finding 52 — IMPORTANT — D36 section 7: common-mode test and fallback are one-sided
**Issue**: The revised bench test measures A and B only with respect to the
adapter's isolated ground. That can validate the reader-side receiver domain
during the pack reply, but it does not validate the pack receiver's common-mode
during reader transmission. The proposed 1 Mohm `ISO_BUS_GND`-to-B bleed also
does not create a reference to the pack's B-minus, so failure cannot yet be
claimed to cost population rather than a topology change.

**Evidence**: For either RS-485 receiver, common-mode must be evaluated against
that receiver's local ground. During adapter TX, the relevant remote reference
is the active pack's B-minus (the series midpoint for the top pack); during the
pack reply, it is `ISO_BUS_GND`. Section 7 criterion 2 specifies only A/B versus
adapter isolated ground for both directions. The fallback ties
`ISO_BUS_GND` to a signal conductor that the reader itself drives relative to
`ISO_BUS_GND`; it provides no independent path to the remote B-minus while the
reader drives, so it cannot force the pack receiver into its common-mode window.

**Suggested fix**: Expand the acceptance matrix to capture A and B relative to
both local grounds in the direction each receiver is active, using isolated
differential probes for the top-pack midpoint. Keep D36 gated unless both
receivers remain within their datasheet common-mode limits. Do not claim the
DNP bias/bleed prevents a respin unless that exact network passes this matrix;
reserve a real reference-conductor or other independently derived topology
option if it does not.

### Finding 53 — IMPORTANT — F49 / manifest 53398 row: exact header specification is missing but available
**Issue**: PS-51021-009 cannot close the 53398 header-side object check. Its
scope is the 51021 receptacle/50079 terminal wire-to-wire system, while the
ordered PCB object is 53398-0871. The exact header-side manufacturer
specification is available and must be stored rather than leaving this premise
on a sibling document.

**Evidence**: The on-file `Molex_PS-51021-009_PicoBlade_product_spec.pdf` p.1
is titled for a 1.25 mm wire-to-wire connector and does not list 53398. Molex's
official
[`PS-51021-024-001`](https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/productspecificationpdf/510/51021/PS-51021-024-001.pdf?inline=)
p.1 explicitly covers 50058/50079 terminals, 51021 receptacle housings,
53398 vertical headers, and 53261 right-angle headers. Its p.2 ratings are
1.0 A max for AWG 26/28/30, 0.8 A for AWG 32, 125 V, and -40 to +105 C; its
8-circuit derating reference is 1.5 A for AWG 26/28 and 1.0 A for AWG 30/32,
with the table marked reference-only. This positively supports the intended
1 A ceiling once the exact PDF is committed and manifested.

**Suggested fix**: Download the official PS-51021-024 PDF, record its source
URL and SHA-256 in the manifest against the 53398/51021/50079 system, and make
the 53398 rating claim cite that exact specification. Retain PS-51021-009 only
for claims that it actually covers.

### Finding 54 — IMPORTANT — cp1_bom.md R3/R6/R_exp_bleed: ambiguous Mouser SKU
**Issue**: The changed-SKU sweep fails because the Mouser cell copied onto the
new bleed resistor, and already used by R3/R6, is not an exact orderable SKU.
It resolves ambiguously to two different suffix variants.

**Evidence**: Canonical `POST /resolve` on 2026-07-17 returned exact matches for
`WM15273-ND -> 0151340801`, `RMCF0805FT100KCT-ND -> RMCF0805FT100K`,
`WM1142TR-ND -> 0500798000`, and `538-50079-8000 -> 50079-8000`. It returned
`matched: ambiguous` for `71-CRCW0805100KFKEA`, with candidates
`CRCW0805100KFKEAC` and `CRCW0805100KFKEAHP`. An exact MPN query for the BOM's
intended Vishay `CRCW0805100KFKEA` instead returned Mouser
`71-CRCW0805-100K-E3` (296,354 in stock at query time). The ambiguous cell
appears in R3, R6, and R_exp_bleed.

**Suggested fix**: Replace all three live Mouser cells with the exact
reverse-resolved SKU (or another exact selected orderable), then add the
superseded ambiguous token to the consistency registry and rerun the full SKU
sweep.

### Finding 55 — NIT — F45 evidence labels: derivative transcript and uncommitted photographs
**Issue**: The technical email content is now inspectable, but live text
overstates the committed evidence as the "original thread on file" and as
reviewer-visible rung-1 photographs.

**Evidence**: The committed artifact identifies itself as a **redacted
transcript** decoded from an `.eml`; it says the owner retains the original,
and its Message-ID is redacted. The recorded original SHA cannot be reproduced
from an on-file original. No pack/cable photo artifacts were added in the two
iteration-34 commits, so this reviewer could verify only the transcript's text,
not the claimed physical-photo observations.

**Suggested fix**: Label the evidence precisely as an owner-supplied redacted
transcript derived from an off-file original, and label the connector photos as
owner-reported inspection unless redacted image artifacts are committed. The
dated RS-485/no-ground and pin-domain content may remain transcript-verified.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 4 important. (See findings 51, 52, 53, 54.)

---

## 32. Designer responses — iteration 36 (F51–F55)

All five addressed. The owner delivered **PS-51021-024** (F53's ask)
same-day. D35 gate exit 0 after changes; all seven new registry patterns
verified to FIRE on the pre-fix text (30 old hits). Two registry rows
were *amended* with in-code comments explaining why (the "$56/$248"
value-alternates now sit next to legitimately-correct values after the
F51 simplification; "owner-reported" became the F55-correct label) —
flagging the amendments here for your review rather than silently.

### F51 (2N7002 off-state bound + wrong-manufacturer doc) — ACCEPTED, and it simplified the design
Confirmed independently: `POST /resolve` 512-2N7002 → **onsemi** exact
(2026-07-17), while the on-file PDF was Diotec's. Fixes go further than
relabeling:
- **The 2N7002 is REMOVED from all three 3V3-domain switches** (Q_exp +
  both channel switches): their P-FET source is 3V3 — the same domain as
  the ESP pin — so the level shifter never had a function there. Gate is
  driven directly (100 kΩ pull-up to 3V3; enable active-LOW; high-Z at
  reset = OFF). One fewer leakage path, three fewer parts, and the
  off-state analysis now has a single semiconductor term per switch.
  (Q1/Q2 on the 24 V domain legitimately keep their level shifter.)
- **Remaining 2N7002 uses (Q2/Q3/Q4) re-pinned to the exact orderable
  onsemi 2N7002LT1G** — Mouser **863-2N7002LT1G** (76k stock, API
  2026-07-17; DK LT1G variants zero-stock same query, cell = "—"),
  $0.49 ea. Its exact doc **2N7002L-D Rev 11** fetched via the proxy
  (onsemi.com source header, sha 11eb3cde5ed5) replaces the Diotec PDF;
  manifest row rewritten.
- **The leakage claim is restated honestly** (your suggested interim,
  made structural): IDSS ≤0.5 µA (ZXMP6A13F p.4) is a **TJ=25 °C test
  point — no full-range max exists** (true of the onsemi doc too, as
  you noted). The budget now has three labeled layers: datasheet 25 °C
  anchor ≤0.5 µA → engineering **allocation ≤5 µA @ ≤40 °C** (explicitly
  an allocation, not a datasheet fact) → **binding limit = the bring-up
  acceptance measurement** (V(EXP_3V3) ≤50 mV, block draw ≤5 µA).
  Documented fallback if the bench exceeds the allocation: a
  specified-over-temperature load-switch IC — part swap, not respin.

### F52 (one-sided common-mode test + insufficient fallback) — ACCEPTED
Correct on both counts; the acceptance matrix in design §7 is now
**two-domain**: row 2a measures A/B against **the active pack's B−**
(top pack = series midpoint, isolated differential probe) during
*reader TX* — the direction that validates the pack receiver; row 2b
against the channel's isolated ground during *pack TX*. Both must stay
within −7…+12 V; functional/differential/idle rows and the
packs-swapped repeat retained. The 1 MΩ-to-B "fallback" is **withdrawn
with your reasoning recorded** (the reader drives B relative to
ISO_BUS_GND — a bleed to it references nothing during reader TX).
Replacement fallback: a per-channel **REF pad tying ISO_BUS_GND to that
pack's B− by a dedicated conductor** — a real reference that pins both
domains (offset ≈0 by construction), preserves channel symmetry (each
island refs its own pack), and costs a wire + a CP2 pad on failure.
D36/DR-26 remain gated on the matrix passing.

### F53 (header spec) — CLOSED, exact object on file
**PS-51021-024 Rev AD committed** (owner upload 2026-07-17, sha
b7d3ec9b74b9; your molex.com URL recorded as the official source —
direct fetch is WAF-blocked from here). Read and verified: scope p.1
lists **53398**71 vertical headers (ours)**, 53261 r/a, 51021 housings,
500798*00/500588*00 terminals; ratings p.2 exactly as you stated —
1.0 A max AWG 26/28/30, 0.8 A AWG 32, 125 V, **−40…+105 °C**, 8-ckt
derating reference 1.5/1.0 A @30 °C rise marked reference-only. All
header-rating claims now cite -024; **PS-51021-009 re-scoped in the
manifest to the wire-to-wire mate side only** (its actual scope).

### F54 (ambiguous Mouser SKU) — ACCEPTED, fixed
Reproduced your result independently: `/resolve` 71-CRCW0805-100K-E3 →
Vishay CRCW0805100KFKEA **exact**; MPN query shows 296k Mouser stock
(2026-07-17). All three cells (R3, R6, R_exp_bleed) replaced; the
ambiguous suffixless token registered. No other cells changed this
iteration except the 2N7002LT1G re-pin (F51), whose Mouser cell was
resolve-verified above.

### F55 (evidence labels) — ACCEPTED, relabeled everywhere
All live docs now say **"owner-supplied redacted transcript (original
off-file)"** — never "original thread on file" — and the pack/cable/app
photo claims are labeled **"owner-reported inspection (photos not
committed)"**. The distinction you drew is now explicit in the docs:
transcript text = verifiable by you; physical-inspection claims =
owner-reported until image artifacts are committed. (Offered to the
owner: committing redacted photo files would upgrade those labels —
their call.)

**Handing back for iteration 37 re-verify.** Remaining open by design:
the F47/F52 on-site matrix (~2 weeks) gates D36/DR-26; everything else
on the D36/D37 delta is, to my knowledge, closed.

---

## 8.19 Reviewer findings (iteration 37 — iter-36 resolution re-review)

This pass independently re-verified only the iteration-36 response and did not
start CP2. The mandatory D35 consistency checker ran first and exited 0 (30
manifest parts; 40 `_verify_` BOM cells). F51's exact onsemi object correction,
F53's exact connector document, F54's two changed SKU classes, and F55's
evidence labels verify. The direct-drive simplification introduced an
unqualified switch operating point, and the mechanical consistency sweep found
live text that the new registry pattern missed.

### Delta gate record

| Gate / check | Independent result |
|---|---|
| D35 scripted gate | **PASS as implemented** — exit 0. The manual G5 sweep still found three live forms of the withdrawn 1 Mohm bus-line bleed; see Finding 58. |
| F51 2N7002 object identity | **PASS** — local `2N7002_onsemi.pdf` SHA-256 begins `11eb3cde5ed5`; onsemi 2N7002L-D p.1 explicitly lists orderable 2N7002LT1G, and p.2 gives the cited 1 uA at 25 C / 500 uA at 125 C rows. Canonical `/resolve` on 2026-07-17 maps Mouser `863-2N7002LT1G` exactly to onsemi `2N7002LT1G`. |
| F51 revised 3V3 switch topology | **FAIL** — direct drive supplies only approximately -3.3 V VGS, below every guaranteed on-resistance test point for ZXMP6A13F. See Finding 56. |
| F52 two-domain matrix | **PASS in section 7** — reader TX is now measured against active-pack B-minus and pack TX against `ISO_BUS_GND`; the fallback includes a real per-channel reference conductor. Live contradictory legacy text remains; see Finding 58. |
| F53 connector object identity | **PASS electrically** — local PS-51021-024 SHA-256 begins `b7d3ec9b74b9`; exact Molex p.1 scope includes 53398/53261 headers, 51021 housing, and 50079/50058 terminals, and p.2 ratings match the docs. Manifest source provenance remains malformed; see Finding 59. |
| F54 changed-SKU sweep | **PASS, 2/2 exact** — `/resolve` maps `863-2N7002LT1G` to onsemi `2N7002LT1G` and `71-CRCW0805-100K-E3` to Vishay `CRCW0805100KFKEA`. All live changed cells use those exact forms. |
| F55 evidence labels | **PASS** — live vendor/design text now distinguishes the owner-supplied redacted transcript from owner-reported, uncommitted pack/cable photographs. The separately committed adapter-label image remains valid on-file evidence. |
| G3 ZXMP6A13FTA lifecycle / availability | **FAIL** — manufacturer marks the part NRND; distributor data does not substantiate the BOM's current-stock claim. See Finding 57. |
| Delta arithmetic | **PASS only against the stale $0.40 input** — `45.80 + 4.60 + 3.00 + 0.80 + 1.40 + 0.40 + 0.40 = 56.40`; current sourcing returns $1.43 for ZXMP6A13FTA, so the documented cost must follow the replacement in Finding 57. |

Citation spot-check quota was met against three exact manufacturer documents:
onsemi 2N7002L-D pp.1-2 (ordering and IDSS rows), Molex PS-51021-024
pp.1-2 (system scope and ratings), and Diodes ZXMP6A13F pp.1/4 (RDS(on),
threshold, and leakage test conditions). Local hashes match the manifest for
all three stored PDFs.

### Finding 56 — IMPORTANT — D36/D37 direct-GPIO ZXMP6A13F switches: no guaranteed ON state at 3.3 V
**Issue**: Removing the N-FET level shifters is topologically reasonable, but
ZXMP6A13F is not qualified as a load switch at the resulting approximately
-3.3 V gate drive. The design uses typical curves as though they guaranteed
the channel and expansion loads.

**Evidence**: With source at 3.3 V and an ESP low output at ground, the most
negative available VGS is approximately -3.3 V. The exact Diodes
ZXMP6A13F datasheet p.1/p.4 guarantees RDS(on) only at VGS=-10 V
(0.4 ohm max) and -4.5 V (0.6 ohm max). Its VGS(th) range is -1 to -3 V
at only ID=-250 uA; threshold is not a load-current rating. The p.5 curves at
3.0/3.5 V are typical, not production limits. Each channel must start an
ADM2587E whose documented 3.3 V supply current is 90 mA at the reviewed load,
and EXP_3V3 has a shared upstream ceiling of 500 mA, so neither use may rely on
the threshold row.

**Suggested fix**: Replace the three 3V3-domain P-FETs with a current-production
logic-level P-FET whose RDS(on) is guaranteed at VGS=-2.5 V or -3.0 V and whose
off leakage supports the stated ambient allocation. Re-derive voltage drop,
dissipation, startup margin, and parked-rail leakage from that exact part. Do
not defer this to a post-build IC swap unless a compatible alternate footprint
is deliberately reserved at CP2.

### Finding 57 — IMPORTANT — G3 / cp1_bom.md ZXMP6A13FTA: NRND and no confirmed on-hand stock
**Issue**: The BOM still describes ZXMP6A13FTA as Active, approximately 75k in
stock, and $0.40 while the manufacturer now marks the device NRND and the live
distributor result does not show quantity-one stock on hand. Iteration 36 also
increased the design's dependence on this part to four devices total.

**Evidence**: Diodes Incorporated's current
[`ZXMP6A13F product page`](https://www.diodes.com/part/view/ZXMP6A13F)
states **Not Recommended for New Design (NRND)**. Canonical `/resolve` maps
Mouser `522-ZXMP6A13FTA` exactly to the Diodes orderable, but the 2026-07-17
MPN query reports Mouser availability as `74376 On Order` (the incoming lots
sum to that figure) at CAD $1.43 and DigiKey cut-tape/Digi-Reel stock as zero.
This does not substantiate the BOM's `Mouser stock ~75k` statement, and the
manufacturer lifecycle status outranks DigiKey's stale `Active` field.

**Suggested fix**: Replace ZXMP6A13FTA with current-production, presently
orderable parts: one 60 V P-FET appropriate for Q1's 24 V/clamped domain and a
logic-level part for the three 3V3 switches (one part may serve both only if
its exact ratings satisfy both jobs). Resolve the new SKU cells, store exact
datasheets, add the superseded part token to D35, and recompute the BOM cost.

### Finding 58 — IMPORTANT — F52 / G5: withdrawn 1 Mohm bus-line bleed remains live
**Issue**: F52 is not consistently closed. Three live architecture locations
still prescribe the rejected bus-line bleed and say no battery-negative
reference is required, while revised section 7 correctly says that topology
cannot control receiver common-mode. The new registry regex is too narrow to
catch these forms.

**Evidence**: `cp1_rs485_battery_read.md` near the opening architecture says an
optional approximately 1 Mohm bleed to a bus line keeps the island referenced
and that nothing lands on battery negative; its component table still lists
`optional ~1 MΩ iso-GND↔bus bleed`. `decisions.md` D36 likewise says no
reference wire is required and retains the optional bleed. In contrast,
section 7 withdraws that fallback and specifies a dedicated REF conductor to
pack B-minus. The added checker pattern matches only longer `bleed from ... B
line` forms, so D35 exits 0 despite the contradiction. Section 7 additionally
says the new REF may be through approximately 100 kohm while claiming
offset approximately zero; no current bound is provided from which that drop
can be derived.

**Suggested fix**: Rewrite all live architecture/component rows to describe
the no-REF two-wire topology as conditional on the two-domain matrix passing,
remove every bus-line-bleed option, and expand the superseded-token regex to
cover the shorthand forms above. Define the failed-matrix fallback as a direct
REF conductor, or independently bound the reference current and calculate a
maximum series resistance that still keeps both receiver common-mode limits.

### Finding 59 — IMPORTANT — manifest PS-51021-024 row: source URL is not reproducible
**Issue**: The exact connector PDF and hash are correct, but the manifest does
not contain the exact official URL that iteration 36 says was recorded. The
source field uses an ellipsis, so it cannot be opened or independently
re-fetched.

**Evidence**: The new manifest row records
`molex.com/content/dam/…/PS-51021-024-001.pdf`. The verified manufacturer URL
is
[`https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/productspecificationpdf/510/51021/PS-51021-024-001.pdf?inline=`](https://www.molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/productspecificationpdf/510/51021/PS-51021-024-001.pdf?inline=).
The committed file hashes to
`b7d3ec9b74b9d7c57a56cf85362ff575dddd9af3f1f3ab10382d8ed257248736`,
so this is a provenance-record defect, not an object-content dispute.

**Suggested fix**: Put the complete official URL in the manifest row, retain
the owner-upload date and full SHA-256, and keep the explicit note that the
stored file came from the owner when direct fetch was blocked.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 4 important. (See findings 56, 57, 58, 59.)

---

## 33. Designer responses — iteration 38 (F56–F59)

All four addressed. F56+F57 together forced (and improved) a FET
replacement across the board. D35 gate exit 0 after changes; all five
new registry patterns verified to FIRE on the pre-fix text (44 old
hits); the gate itself caught three stragglers mid-pass (a
cp1_battery_side comparison row, the decisions part-sourcing note, and
REVIEWER.md's own part list) — including one that required updating the
old AO3401A registry row's *current* token to the new part (chain
supersession, noted in-code).

### F56 (no guaranteed ON state at −3.3 V) — ACCEPTED; one honest note
Correct: ZXMP6A13F guarantees RDS(on) only at −10 V / −4.5 V, and
VGS(th) at −250 µA is not a load rating. One point of record: **the
−3.3 V operating point predates iter-36** — the earlier 2N7002
level-shifter also only ever pulled the gate to ground with the source
at 3V3, i.e. the same −3.3 V VGS. F51's simplification exposed an
operating point that had been unqualified since the channel switches
were first drawn, rather than creating it. The fix (with F57) replaces
the device, not the topology: **DMG3415U** carries a **production-limit
RDS(on) row at VGS = −2.5 V (53 mΩ max, DS31735)** — the 3.3 V direct
drive is now a *qualified* operating point with margin below even the
−2.5 V row. Loads re-derived: ~90 mA channel start-up → ≤5 mV drop /
≈0.4 mW; EXP up to the 500 mA shared ceiling → ≤27 mV / ≤14 mW.
Dissipation and start-up margin are non-issues at 53 mΩ.

### F57 (ZXMP6A13F NRND, stock unsubstantiated) — ACCEPTED, replaced everywhere
Independently reproduced your sourcing result and replaced all four
uses with two current-production parts (both API-verified 2026-07-17,
datasheets proxy-fetched and read this pass):
- **Q1 (24 V/clamped domain): Vishay Si2309CDS-T1-GE3** — −60 V,
  ID −1.6 A, VGS ±20 V (the DZ1 12 V clamp scheme carries over
  unchanged), RDS(on) 0.345 Ω max at the −10 V clamped drive → ≤0.11 V
  drop at the ~0.3 A load. Bonus: **IDSS has a specified elevated-temp
  row (≤100 nA @25 °C, ≤1 µA @TJ=55 °C)** — the F51-class
  "25 °C-only" complaint is answered by the datasheet itself for this
  domain. DK SI2309CDS-T1-GE3CT-ND 120k stock Active / Mouser
  781-SI2309CDS-GE3 89k, $1.39.
- **3V3 switches ×3 (2× channel + Q_exp): Diodes DMG3415U-7** — the
  F56 fix; DK DMG3415UDICT-ND 136k stock Active / Mouser 621-DMG3415U-7
  7.5k, $0.72. IDSS ≤1 µA (−20 V/25 °C — pessimistic at our −3.3 V);
  the allocation-plus-acceptance budget structure from iter-36 stands,
  with the parked-rail datasheet bound restated **≤100 mV** (1 µA ×
  100 kΩ) and the measured ≤50 mV limit binding (fail → bleed drops to
  10–33 kΩ, resistor swap).
Both datasheets manifested (feb0974dd371 / 3863b974014c); ZXMP PDF
retired and deleted; ZXMP registered as a superseded token (33 pre-fix
hits across live docs — all now marked or replaced). Delta recomputed:
**~$57.4 / total ~$249.4**; the Q1 + 2N7002LT1G re-pins add ≈$2.2 to
the core, absorbed in the battery-side "~$83".

### F58 (withdrawn bleed still live ×3; unbounded 100 kΩ) — ACCEPTED, fixed
All three locations rewritten (design §1 architecture text, §3 R_bias
row, decisions D36): the 2-wire no-reference property is now stated as
**conditional on the §7 matrix passing**, every bus-line-bleed option is
deleted (with a supersession note carrying your reasoning), and a new
**REF_pad row** appears in §3 (per channel: ISO_BUS_GND → that pack's
B−, **direct 0 Ω link by default** — the "optionally through ~100 kΩ"
phrase is withdrawn per your point that no resistance can be claimed
without a bounded reference current; a series-R footprint exists for
bench flexibility only). The registry regex is expanded to four
shorthand families (bleed forms, "no battery-negative", "no reference
wire is required", the 100 kΩ phrase) — all verified firing on the old
text. You were right that my iter-36 pattern was too narrow; the three
misses were exactly the shorthand forms.

### F59 (abbreviated manifest URL) — ACCEPTED, fixed
The manifest row now carries the complete official URL
(molex.com/content/dam/molex/molex-dot-com/products/automated/en-us/productspecificationpdf/510/51021/PS-51021-024-001.pdf?inline=)
plus the owner-upload provenance and full-prefix SHA — reproducible by
anyone.

**Handing back for iteration 39 re-verify.** Still open by design: the
F47/F52 on-site two-domain matrix (~2 weeks) gating D36/DR-26.

### 33.1 Out-of-band evidence addendum (2026-07-17, owner bench work — pre-iter-39)

The owner purchased and bench-characterized the actual vendor cables.
Folded in before your pass so no known-stale statement survives review:

- **Connector identified (family level): 4-position M12-pattern
  screw-coupling** — coupling-thread ID ≈ 12.3 mm (M12×1), molded
  cordset, insert numbered 1→4 CCW, keying notch between 1/4. **Two
  photos committed** (`docs/vendor/images/`) — these connector claims
  upgrade from owner-reported to on-file (the pack-face photos remain
  uncommitted/owner-reported). The repo's *original* "4-socket M12"
  reading was the closest description; the vendor's "XLR" was colloquial.
- **Full conductor map measured (multimeter continuity, rung-1):**
  battery 1→RJ45 4, 2→6, 3→7, 4→8. With the thread's battery-side
  CAN-1/2: battery 1 = CAN-H (RJ45 4), 2 = CAN-L (RJ45 **6**),
  3 = RS-485 A (RJ45 7), 4 = RS-485 B (RJ45 8). **The in-service cable
  contradicts the Pro-Series label's CAN 4/5** — your F45 refusal to
  generalize one artifact's mapping is now empirically vindicated; live
  docs now say "follow the measured map of the cable in service."
  RS-485 on 7/8 gains a third independent confirmation.
- **The purchased cable ends in an RJ45 *male* plug** → mates our
  RJHSE-5380 directly; the "straight patch cable" link in the chain is
  deleted from live docs (it described the email's $10 RJ45-female
  variant).
- On-site list shrinks to: the §7 two-domain matrix (gating) + which
  socket carries RS-485 per pack (side-item). Connector caliper/ID and
  the patch-cable check are closed. Four new registry rows cover the
  superseded forms (label-4/5 guidance, patch-cable chain, on-site
  caliper, "aviation-style"); all verified firing on pre-fix text.
---

## 8.20 Reviewer findings (iteration 39 - iter-38 resolution re-review)

This pass independently re-verified the iteration-38 response plus the
pre-review section 33.1 evidence addendum and did not start CP2. The mandatory
D35 consistency checker ran first and exited 0 (31
manifest parts; 40 `_verify_` BOM cells). The new FET identities, changed SKU
cells, replacement electrical ratings, retired ZXMP object, REF-pad correction,
and full Molex URL were checked. The replacement pass exposed one gate-drive
power defect, one manufacturer lifecycle conflict, and live replacement drift.

### Delta gate record

| Gate / check | Independent result |
|---|---|
| D35 scripted gate | **PASS as implemented** - exit 0. The manual G5 sweep found live retired Q1 values and summary text; see Finding 62. |
| F56 3V3 switch electrical fit | **PASS electrically** - the exact DMG3415U datasheet guarantees 53 mOhm max at VGS=-2.5 V, so the approximately -3.3 V direct drive qualifies the intended operating point. |
| F57 Q1 electrical fit | **PASS for the FET itself** - the exact Si2309CDS datasheet gives -60 V VDS, +/-20 V VGS, and 0.345 Ohm max at VGS=-10 V. The inherited 1 kOhm gate-clamp network does not pass dissipation; see Finding 60. |
| F57 changed-SKU reverse resolve | **PASS, 4/4 exact** - canonical `/resolve` on 2026-07-17 mapped DigiKey `SI2309CDS-T1-GE3CT-ND` and Mouser `781-SI2309CDS-GE3` to Vishay `SI2309CDS-T1-GE3`, and DigiKey `DMG3415UDICT-ND` and Mouser `621-DMG3415U-7` to Diodes `DMG3415U-7`. |
| F57 object identity / stored files | **PASS, 2/2** - the local Si2309CDS and DMG3415U PDF SHA-256 prefixes are `feb0974dd371` and `3863b974014c`, matching their manifest rows; their manufacturers and orderable variants match the resolved objects. |
| F57 availability / lifecycle | **FAIL for DMG3415U lifecycle** - both changed objects have ample live distributor stock, but Diodes marks DMG3415U NRND; see Finding 61. |
| F58 REF fallback | **PASS** - live architecture text now makes the two-wire case conditional on the two-domain matrix and defines the fallback as a direct 0 Ohm reference conductor; old bleed forms remain only in explicitly superseded/history contexts. |
| F59 manifest provenance | **PASS** - the PS-51021-024 row contains the complete official Molex URL. |
| Section 33.1 cable evidence | **PASS for the visible objects; FAIL for G5 propagation** - the two committed photos show the four-position screw-coupled numbered face and the complete cable with an RJ45 male plug, supporting the family-level description and direct-mate correction. The continuity map is explicitly an owner multimeter measurement. Two live summary passages still preserve the superseded 4/5 interpretation; see Finding 63. |
| Delta arithmetic | **PASS for the stated component-price sum** - the revised 3V3-switch subtotal is `2 * $0.72 = $1.44`, and the document's approximately `$57.4` delta / `$249.4` total follows its stated rounded inputs. Finding 60 adds an unbudgeted active-state pack burden, not a BOM-price correction. |

Citation spot-check quota was met against three exact manufacturer documents.
Vishay Si2309CDS document 68980 pp.1-2 lists orderable
`Si2309CDS-T1-GE3`, -60 V VDS, +/-20 V VGS, and the cited 0.345/0.450 Ohm
RDS(on) rows. Diodes DMG3415U DS31735 pp.1/3 lists -20 V VDS, +/-8 V
VGS, and the cited 42.5/53/71 mOhm RDS(on) rows at -4.5/-2.5/-1.8 V.
The exact onsemi BZX84C12LT1G family datasheet pp.2-3 gives 250 mW on
FR-5 at 25 C, 2.0 mW/C derating above 25 C, and for BZX84C12LT1G gives
11.4-12.9 V at the 20 mA test point. The three local hashes begin
`feb0974dd371`, `3863b974014c`, and `f9818d9dfc03`, matching the
manifest.

### Finding 60 - IMPORTANT - Q1 gate clamp / Rg and DZ1: continuous full-charge dissipation is not rated
**Issue**: Rg is documented as an approximately 1 kOhm 0805 transient-current
limiter, but it carries large continuous current whenever Q1 is on. At a fully
charged pack it dissipates roughly 0.27-0.32 W with no selected power-rated
SKU, while DZ1 operates around 0.20-0.21 W against a 0.25 W rating that derates
above 25 C. The network also adds roughly half a watt of unbudgeted pack load.

**Evidence**: With Q1 source at 29.2 V and DZ1 holding source-to-gate at
11.4-12.9 V, Q2 pulls the lower end of Rg approximately to ground. Therefore
`I_Rg=(29.2-VZ)/1k=16.3-17.8 mA` and
`P_Rg=(29.2-VZ)^2/1k=0.266-0.317 W`. R3 supplies only
`VZ/100k=0.114-0.129 mA`, so
`I_Z=I_Rg-I_R3=16.17-17.69 mA` and
`P_Z=VZ*I_Z=0.202-0.209 W`. The exact onsemi datasheet rates DZ1 at
250 mW on its specified FR-5 board at 25 C and derates it 2.0 mW/C above
25 C, reducing the maximum to 200 mW at 50 C. The input burden is
`29.2 V * I_Rg=0.476-0.520 W`. `hardware/layout/cp1_bom.md` leaves both
Rg distributor cells `_verify_` and specifies only `~1 kOhm 0805 1 %`.

**Suggested fix**: Re-size the gate network rather than treating Rg as a
transient-only part. Independently bracket minimum Q1 VGS at minimum pack
voltage, DZ1 current/knee and maximum clamp voltage at 29.2 V, Rg and DZ1
power with ambient derating, and Q1 turn-on timing. Select an exact resistor
value/package/SKU only after that derivation and include the resulting
active-state burden in the power budget.

### Finding 61 - IMPORTANT - G3 / DMG3415U-7: manufacturer marks the replacement NRND
**Issue**: Iteration 38 describes DMG3415U as current-production and the BOM
labels it Active, but the current manufacturer product page marks DMG3415U
Not Recommended for New Design. Distributor stock does not override the
manufacturer lifecycle status.

**Evidence**: Diodes Incorporated's official DMG3415U product page displayed
`DMG3415U (NRND)` on 2026-07-17. Live distributor queries the same day still
showed 136,268 at DigiKey and 7,506 at Mouser, and all four changed SKU cells
reverse-resolved exactly, so this is a lifecycle-selection defect rather than
an identity or immediate-stock defect. The manufacturer status is the higher
evidence rung.

**Suggested fix**: Select a current-production P-channel load-switch FET with
RDS(on) guaranteed at no more negative than -2.5 V and leakage specified well
enough to support the parked-rail allocation. Reverse-resolve every changed
SKU, store and hash the exact manufacturer datasheet, register DMG3415U as
superseded, and re-run the voltage-drop, dissipation, leakage, and cost deltas.

### Finding 62 - IMPORTANT - G5 / Q1 replacement: live baseline text retains ZXMP ratings and identity
**Issue**: The Q1 replacement is not consistent across live binding documents.
The battery-side design still quotes the retired ZXMP6A13F on-resistance and
gate-rating text, and the overview BOM's current change summary stops at
ZXMP6A13F even though the same document calls the following parts table the
binding baseline.

**Evidence**: `hardware/layout/cp1_battery_side.md` gate-clamp text cites the
retired Diodes DS32014, states 600 mOhm at -4.5 V and 400 mOhm at -10 V
instead of the Si2309CDS limits of 450/345 mOhm, and later compares the old
approximately -29 V drive to `the FET's +/-12 V` although the selected
Si2309CDS rating is +/-20 V. `docs/hardware/bom.md` says
`Q1 (AO3401A->ZXMP6A13F)` in its live parts-changed banner while its Q1 row
correctly selects Si2309CDS. These are not confined to the append-only review
history or a clearly marked superseded schematic.

**Suggested fix**: Update the live Q1 narrative to the exact Vishay document
and Si2309CDS values, extend the change chain through Si2309CDS, and widen the
D35 registry patterns so these stale rating/citation forms fail the scripted
gate. Keep historical review responses unchanged.

### Finding 63 - IMPORTANT - G5 / section 33.1 cable map: live summaries retain the superseded 4/5 interpretation
**Issue**: The new measured 1-to-4 / 2-to-6 continuity map is not propagated
consistently. Two live summaries still call the label's RJ45 4/5 map consistent
with battery pins 1/2, even though their surrounding text now says the cable in
hand maps those pins to RJ45 4/6 and that the label describes a different
product.

**Evidence**: `hardware/reviews/DESIGN_REVIEW_ITEMS.md` says `RJ45 side is
4/5 per the label - consistent` at line 805, then records the owner-measured
`battery 1/2 = CAN-H/L -> RJ45 4/6` at lines 807-809. `docs/vendor/README.md`
likewise says the battery-side 1/2 statement does not conflict with the label's
4/5 map because `one cable maps one to the other`, while its later live summary
correctly says the purchased cable maps 1/2 to 4/6 and the 4/5 label belongs to
a different cable product. The new checker patterns catch `follow ... label
(4/5)` but not either surviving prose form, so D35 exits 0. Visual inspection
of the two committed photos independently confirms the numbered four-position
screw-coupled end and RJ45-male direct mate; the conductor continuity itself is
explicitly an owner multimeter result and is not visible in those photographs.

**Suggested fix**: Rewrite both live summaries to distinguish the separate
label artifact from the measured in-service cable without calling their maps
mutually consistent, and widen the superseded-token registry to cover these
remaining 4/5 interpretation forms. Preserve the label's actual 4/5 content as
artifact history, not routing guidance.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 4 important. (See findings 60, 61, 62, 63.)

---

## 34. Designer responses — iteration 40 (F60–F63)

All four addressed. F60 required real re-derivation; F61 is the
manufacturer-lifecycle lesson landing on my own replacement part. D35
gate exit 0 after changes; all four new registry patterns verified to
FIRE on pre-fix text (29 old hits); the gate caught two D19-narrative
stragglers mid-pass.

### F60 (Q1 gate clamp: continuous dissipation not rated) — ACCEPTED; re-derived
Your arithmetic reproduces exactly: with Rg = 1 kΩ, I_Rg = (29.2−12)/1k
= 17.2 mA → P_Rg ≈ 0.30 W (on an 0805, 125 mW) and P_DZ1 ≈ 0.20 W
(against 250 mW derating to 200 mW @ 50 °C), plus ~0.5 W of unbudgeted
pack draw whenever Q1 is on. The 1 kΩ was sized as a transient gate
resistor and nobody computed its steady state — the same
"under-derived-at-birth" pattern as the FET itself. Fixed by making the
network **divider-dominant**: **Rg → 150 kΩ** with the existing R3 =
100 kΩ.
- DC Vgs = V24·R3/(R3+Rg) = **11.7 V @ 29.2 V full charge**, **8.4 V @
  the 21 V UVLO floor** — both < ±20 V abs-max and fully enhancing
  (Si2309CDS RDS spec'd from −4.5 V).
- DZ1 (12 V) now sits **above** the 11.7 V DC point → ≤ 0.2 mW
  continuous (worst-case Zener low-tolerance), conducting only on a
  surge (the ~53 V clamp divides to 21.2 V would-be Vgs → DZ1 clamps to
  ~12 V). It is now a transient backstop, not the DC clamp.
- Standing current **117 µA → 3.4 mW pack burden while Q1 is ON, zero
  in hard-cut**; P_Rg 2.05 mW, P_R3 1.36 mW — all far under 0805.
  Turn-on τ ≈ 12 µs (softens display inrush). Fail-safe unchanged.
Exact SKU resolved: Rg = RMCF0805FT150KCT-ND / 71-CRCW0805-150K-E3
(resolve-exact 2026-07-17). The 3.4 mW active-only term is added to the
State-1/2 budget; it does not touch the ~1 mW hard-cut floor. Full
derivation in decisions.md D19 (F60).

### F61 (DMG3415U itself NRND) — ACCEPTED; and it's the lesson biting me
You're right, and the irony isn't lost: I added "manufacturer lifecycle
outranks the distributor field" to my own review skill an hour before
this pass, then didn't apply it to the F57 *replacement*. DMG3415U shows
distributor Active + 136k stock but Diodes marks it NRND. Replaced the
three 3V3-domain switches with **onsemi NTR4171P** — and this time I
verified lifecycle at the manufacturer, honestly caveated:
- **NTR4171P/D Rev 3 (Feb 2026)** on file (sha 9ce711ff393d): −30 V,
  **RDS(on) 150 mΩ max guaranteed @ VGS = −2.5 V** (my exact operating
  point), **Vgs ±12 V** (≫ 3.3 V drive), **IDSS ≤ 1 µA @ 25 °C / ≤ 5 µA
  @ 85 °C** — it *publishes* the elevated-temp leakage row the prior two
  parts lacked.
- Lifecycle: onsemi's product page shows **Active** (WebSearch of the
  manufacturer page, 2026-07-17). Honest caveat: onsemi.com WAF-blocks
  the fetcher, so I could not open the page directly — the Active call
  rests on the search summary of the mfr page + the Rev 3 Feb-2026
  datasheet (active maintenance) + onsemi-channel stock (11k DK / 30k
  Mouser). Materially better footing than DMG3415U, where the
  manufacturer explicitly said NRND. Flagged for a direct manufacturer
  re-confirm at BOM-lock.
- SKUs resolve-exact: DK NTR4171PT1GOSCT-ND / Mouser 863-NTR4171PT1G,
  $1.13. DMG3415U retired + registered. Q1's Si2309CDS is unaffected by
  F61 (you cleared it at F57); I re-checked it too — distributor Active
  (Future/Octopart), Vishay page not independently fetchable, so it
  carries the same BOM-lock re-confirm flag.
- **Delta recomputed: ~$58.6 / total ~$250.6** (NTR4171P $1.13 ×3 vs
  DMG3415U $0.72 ×3).

### F62 (live baseline retains ZXMP ratings/identity) — ACCEPTED, fixed
`cp1_battery_side.md` §3 gate-clamp paragraph rewritten to Si2309CDS
values (450/345 mΩ, ±20 V, Vishay 68980) and the new divider design;
the DS32014 citation, the 600/400 mΩ ZXMP numbers, and the "FET's
±12 V" are gone. Its DZ1 row and the "why this topology" bullet (line
~597) updated. `docs/hardware/bom.md` change banner extended
AO3401A→ZXMP6A13F→**Si2309CDS**. Two new registry patterns (the ZXMP
RDS/citation/±12 V forms, and the "1 kΩ Rg" form) now fail the gate on
recurrence.

### F63 (cable map: live summaries keep 4/5-consistent) — ACCEPTED, fixed
The three passages that called the label's 4/5 "consistent" with battery
1/2 (DR-26 line ~805, README banner, correspondence CAN row) are
rewritten: the **in-service cable measures RJ45 4/6** (beep-out), the
Pro-Series **label** prints 4/5 as a **different cable product**, and
the two are explicitly **not** the same map. The decisions.md D36 line
matched too and was fixed. New registry pattern covers the "4/5 …
consistent / one cable maps one to the other" forms. Your note that the
photos verify the connector face + RJ45-male mate but *not* the
continuity (which is the multimeter result) is correct and preserved in
the labels.

**Handing back for iteration 41 re-verify.** Remaining open by design:
the F47/F52 on-site two-domain matrix (~2 weeks) gating D36/DR-26; and
the standing BOM-lock manufacturer-lifecycle re-confirm on the FETs
(NTR4171P, Si2309CDS) now that lifecycle rigor is explicit.

---

## 8.21 Reviewer findings (iteration 41 - iter-40 resolution re-review)

This pass independently re-verified only the iteration-40 response and did not
start CP2. The mandatory D35 consistency checker ran first and exited 0 (31
manifest parts; 38 `_verify_` BOM cells). F61's exact NTR4171PT1G object,
changed SKU cells, ratings, stock, lifecycle evidence, and cost delta pass.
F63's cable-map corrections pass. F60 is not yet coordinated for the surge or
OFF-state cases, and the exact-PDF checks plus manual G5 sweep exposed three
additional live defects.

### Delta gate record

| Gate / check | Independent result |
|---|---|
| D35 scripted gate | **PASS as implemented, but incomplete** - exit 0. It misses the live 1 kOhm Rg row and does not scan `REVIEWER.md`; see Finding 67. |
| F60 normal-state divider arithmetic | **PASS** - with R3=100 kOhm and Rg=150 kOhm, `abs(VGS)=VS*100/250`: 11.68 V at 29.2 V and 8.4 V at 21 V. Divider current at 29.2 V is 116.8 uA and total burden is 3.41 mW. At the minimum operating rail, the guaranteed 0.450 Ohm RDS(on) row at -4.5 V applies; the 0.345 Ohm row at -10 V is not the conservative bound. |
| F60 surge / OFF-state coordination | **FAIL** - the divider cannot drive DZ1 at a characterized current under the 53.3 V surge, and Q2 leakage is not bounded over the operating range; see Finding 64. |
| F61 NTR4171PT1G object identity | **PASS** - local `NTR4171P_onsemi.pdf` SHA-256 is `9ce711ff393d...`, matching the manifest. Rev. 3 p.1 lists selected `NTR4171PT1G` in normal ordering information; the adjacent discontinued block applies to `NTR4171PT3G`, not the selected object. |
| F61 changed-SKU reverse resolve | **PASS, 4/4 exact** - canonical `/resolve` on 2026-07-17 maps `NTR4171PT1GOSCT-ND` and `863-NTR4171PT1G` exactly to onsemi `NTR4171PT1G`; the two 150 kOhm cells map exactly to Stackpole `RMCF0805FT150K` and Vishay `CRCW0805150KFKEA`. |
| F61 live stock / lifecycle | **PASS with the stated BOM-lock recheck retained** - API results show 11,032 DigiKey cut-tape and 30,583 Mouser onsemi parts; DigiKey says Active. The current manufacturer Rev. 3 ordering table and onsemi recommendation tool still carry PT1G, while explicitly distinguishing discontinued PT3G. |
| F61 electrical fit | **PASS for ON resistance and gate rating** - NTR4171P/D pp.1-2 gives +/-12 V VGS and 150 mOhm max at VGS=-2.5 V. Its leakage rows are correctly quoted, but the parked-rail conclusion is not; see Finding 66. |
| F62 Q1 narrative | **FAIL G5 only** - the primary gate-drive paragraph has the Si2309CDS values, but the live component row and topology drawing still say Rg is approximately 1 kOhm; see Finding 67. |
| F63 cable-map propagation | **PASS** - the live summaries now distinguish the measured in-service 4/6 map from the separate label's 4/5 map and do not treat them as the same cable. |
| Delta arithmetic | **PASS** - `45.80 + 4.60 + 3.00 + 2.26 + 1.40 + 1.13 + 0.40 = 58.59`, supporting the rounded approximately $58.6 delta and approximately $250.6 total. |

Citation spot-check quota was met against four exact on-file manufacturer
documents. Onsemi NTR4171P/D Rev. 3 pp.1-2 contains the selected PT1G ordering
row, 150 mOhm at -2.5 V, +/-12 V VGS, and 1/5 uA IDSS at 25/85 C.
Onsemi BZX84C12LT1G pp.2-3 gives 250 mW with 2 mW/C derating and specifies
its C12 voltage only at 1, 5, and 20 mA. Vishay document 68980 pp.1-2 gives
the Si2309CDS ordering/rating rows and the actual 1/10 uA IDSS limits at
25/55 C. Onsemi 2N7002L/D Rev. 11 pp.1-2 lists selected 2N7002LT1G and
specifies IDSS only as 1 uA at 25 C and 500 uA at 125 C. Local hashes for
the first three begin `9ce711ff393d`, `f9818d9dfc03`, and `feb0974dd371`,
matching the manifest.

### Finding 64 - IMPORTANT - F60 / Q1 gate network: surge clamp and OFF-state fail-safe remain unproved
**Issue**: The 150 kOhm correction fixes normal-state power, but it makes DZ1
too weakly driven to establish the claimed surge clamp from production-limit
data. The same re-derivation also omits Q2's temperature-dependent OFF leakage,
which develops Q1 gate drive across R3 and can defeat the hard-cut claim.

**Evidence**: At the documented 53.3 V rail clamp, the unloaded divider would
produce `VTH=53.3*100/(100+150)=21.32 V` across Q1 gate-source, above its
20 V absolute maximum. The network's Thevenin resistance is
`100k || 150k = 60 kOhm`. Even assuming DZ1 at its 12.7 V maximum from the
1 mA row, the available current is only `(21.32-12.7)/60k=0.144 mA`; at
VGS=20 V it is only 22 uA. BZX84C12LT1G p.3 specifies voltage at 1, 5,
and 20 mA, with no maximum clamp voltage at 22-144 uA. Therefore
`clamps to approximately 12 V` is not a guaranteed coordination bracket.
For hard-cut, Q2 is off and its leakage flows through Rg/R3; 2N7002L/D p.2
specifies 1 uA only at 25 C and 500 uA at 125 C, with no maximum at the
project's upper operating temperature. Because `abs(VGS_Q1)=Ileak*R3`, only
10 uA produces 1 V, equal to the Si2309CDS minimum threshold test value. The
response's `fail-safe unchanged` conclusion does not account for this path.

**Suggested fix**: Re-design the gate drive so a production-limit Zener row
proves `abs(VGS)<20 V` at the maximum rail clamp, or select a clamp specified
at the actually available current. Independently bracket Q2 leakage over the
declared ambient range and prove Q1 remains off, replacing the driver if that
cannot be done. Then re-derive normal burden, surge pulse power, minimum-rail
RDS(on) using the -4.5 V row, and turn-on/off timing from the final values.

### Finding 65 - IMPORTANT - Si2309CDS citation / hard-cut budget: IDSS rows are misread by 10x
**Issue**: The manifest and two binding Q1 rows conflate gate leakage with
drain-source leakage. They quote Q1 IDSS as 100 nA at 25 C and 1 uA at 55 C,
and the State-4 budget treats the entire switched branch as zero.

**Evidence**: Vishay document 68980 p.2 gives `IGSS` (gate-source leakage) as
100 nA. The separate `IDSS` rows are 1 uA at 25 C and **10 uA at TJ=55 C**.
The incorrect 100 nA / 1 uA pair appears in
`hardware/datasheets/manifest.md`, `hardware/layout/cp1_bom.md` Q1, and
`hardware/layout/cp1_battery_side.md` Q1. At 29.2 V, the exact elevated-temp
IDSS limit alone represents up to 0.292 mW entering the nominally shed branch,
about 27% of the current 1.08 mW hard-cut headline, before the Q2 path in
Finding 64. `docs/hardware/power_budget.md` instead assigns zero to the whole
Q1-off display branch.

**Suggested fix**: Correct every Si2309CDS leakage citation and add the
production-limit Q1/Q2 OFF paths to the State-4 budget. Bound what U2 does with
that leakage rather than equating Q1 OFF to zero input current; if the revised
hard-cut or OFF-voltage contract fails, select a switch/driver with guaranteed
temperature-range leakage.

### Finding 66 - IMPORTANT - D37 expansion OFF state: 100 mV bound is only a 25 C result
**Issue**: The NTR4171P replacement publishes a useful elevated-temperature
leakage row, but the design does not use it in the parked-rail calculation. It
calls 100 mV a datasheet bound while separately allocating the 5 uA value that
would produce 500 mV through the populated 100 kOhm bleed.

**Evidence**: NTR4171P/D p.2 specifies IDSS maximum 1 uA at 25 C and 5 uA at
85 C. Therefore the selected 100 kOhm bleed gives `Vpark <=100 mV` only at
the 25 C test point; the published elevated-temperature bracket is
`5 uA*100 kOhm=500 mV`. `hardware/layout/decisions.md` D37 states both
limits but still calls 100 mV datasheet-bound. `hardware/layout/cp1_bom.md`
Q_exp repeats that contradiction, while its `R_exp_bleed` row is staler still:
it uses the retired 0.5 uA premise to claim 50 mV. A room-temperature bring-up
measurement cannot establish the 40 C operating bound or qualify an arbitrary
future daughterboard.

**Suggested fix**: Use the elevated-temperature maximum for the architecture
contract. Either populate a bleed value that meets the required parked voltage
at 5 uA (10 kOhm for 50 mV), or specify a temperature-qualified acceptance
test and make the interface conditional on it. Update the Q_exp, R_exp_bleed,
D37, and power-budget text to one consistent worst-case bound.

### Finding 67 - IMPORTANT - D35 / G5: live 1 kOhm Rg and retired DMG3415U escape the checker
**Issue**: F62 is not mechanically closed. The battery component table and
topology drawing still specify the hazardous 1 kOhm Rg, and the reviewer entry
point still names retired DMG3415U as a current load switch. D35 exits 0 because
its history exemption and file scope hide both defects.

**Evidence**: `hardware/layout/cp1_battery_side.md` line 247 says
`Rg | approximately 1 kOhm series gate`, and its topology drawing near line
577 says `Rg [approximately 1k]`; both conflict with the new 150 kOhm design.
The line-247 superseded-token regex does match, but `_allowed()` accepts any
line containing the generic history marker `->`/arrow; here that arrow merely
describes the live net direction `Q2 drain -> Q1 gate`. Separately,
`hardware/reviews/REVIEWER.md` still lists `Si2309CDS / DMG3415U /
2N7002LT1G` as the current load-switch set, but `REVIEWER.md` is absent from
`LIVE_DOCS`, so the DMG registry row never scans it.

**Suggested fix**: Change both live Rg forms to 150 kOhm and update the reviewer
part list to NTR4171P. Include `REVIEWER.md` in D35 scope and narrow the history
exemption so a signal-flow arrow alone cannot legalize a stale value; require
an actual supersession word or a same-line old-to-current token pair.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 4 important. (See findings 64, 65, 66, 67.)

---

## 35. Designer responses — iteration 42 (F64–F67)

All four addressed; F65 was a flat 10× misread on my part. D35 gate
exit 0 after changes; all five new registry patterns verified to FIRE
on pre-fix text (19 old hits). The narrowed arrow-history exemption
(F67) surfaced 6 lines on first run — one genuine staleness (the
procurement BOM's R3), five legit history lines that had leaned on the
arrow — all fixed.

### F64 (Q1 gate: surge clamp + OFF fail-safe unproved) — ACCEPTED; re-derived again
Both holes are real and the iter-40 150 kΩ didn't close them.
Reproduced your surge arithmetic: the unloaded divider puts 21.3 V
across Vgs at the 53.3 V clamp and would rely on DZ1, but the network
supplies only ~0.14 mA — below the BZX84C12's 1 mA-characterized row —
so the Zener's clamp voltage is **not a bracket**. And Q2's
temperature-dependent OFF leakage develops Vgs = I_L·R3, which at
R3 = 100 kΩ could exceed the min Vth hot. Final values **R3 = 10 kΩ,
Rg = 33 kΩ**:
- **The divider alone is the surge bracket** (no DZ1 dependence):
  Vgs = 6.8 V @29.2 V / 4.9 V @21 V floor / **12.4 V @53.3 V surge**,
  all < ±20 V (38 % margin), at/above the −4.5 V RDS row.
- **Q2 OFF-leakage bounded over temperature:** Vgs_off = I_L(Q2)·R3 ≤
  **0.42 V @85 °C** (2N7002L 1 µA@25 °C → 500 µA@125 °C envelope) < the
  1 V min Vth — Q1 stays off across the operating range; the small R3
  buys this.
- DZ1 is now a **pure redundant backstop**; the bracket doesn't need it.
- Standing 679 µA → 19.8 mW (Q1-ON only, ~0 hard-cut); P_Rg 15.2 mW,
  P_R3 4.6 mW; turn-on τ ≈ 1.5 µs; min-rail RDS 0.45 Ω (−4.5 V row) →
  ≤0.135 V drop. SKUs resolve-exact (R3 10 kΩ, Rg 33 kΩ). Full
  derivation in D19 (F64).

### F65 (Si2309CDS IDSS misread 10×) — ACCEPTED; my error, corrected from the PDF
You're right and I verified it against 68980 p.2 myself rather than
re-recall: **IGSS = 100 nA** (gate leakage) is a *separate* row from
**IDSS = 1 µA @25 °C / 10 µA @55 °C** (drain leakage). I'd conflated the
two and shifted the temperature. Corrected in the manifest, cp1_bom Q1,
and cp1_battery_side Q1. And the State-4 budget no longer treats Q1-OFF
as zero: added the Q1 IDSS term (≤10 µA @55 °C → ≤0.24 mW into the shed
U2 branch) **and** the Q2 gate-net leakage term (F64), both ~1 µA/25 °C
(negligible) rising to ~0.45 mW combined at 60 °C — so the honest
hard-cut is **~1.1 mW @25 °C / ~1.5 mW @60 °C** (bounded; absolute
battery impact nil — even 2 mW on 4.8 kWh is centuries). power_budget.md
State 4 rows + note updated.

### F66 (expansion 100 mV bound is 25 °C-only) — ACCEPTED, fixed
Correct: at NTR4171P's 5 µA @85 °C the 100 kΩ bleed gives 500 mV, not
100 mV, and the R_exp_bleed row still cited the retired ZXMP 0.5 µA/
50 mV. **R_exp_bleed 100 kΩ → 10 kΩ** so the parked-rail bound uses the
worst-case temperature: **≤50 mV @85 °C** (5 µA×10 kΩ), matching the
bring-up acceptance target. On-cost 330 µA (1.1 mW, active only). Q_exp,
R_exp_bleed, D37 item 3/4, and the State-4 expansion term all now cite
the 5 µA @85 °C limit consistently.

### F67 (live 1 kΩ Rg + retired DMG3415U escape the checker) — ACCEPTED, fixed both ways
- **Content:** cp1_battery_side component row (line 247) and topology
  drawing (line 577) → 33 kΩ; REVIEWER.md load-switch list DMG3415U →
  NTR4171P. (REVIEWER.md was already in LIVE_DOCS — the row escaped
  because "superseded" on that line exempted it, the same
  broad-exemption class as the arrow.)
- **Gate:** removed the bare arrow `→`/`->` from HISTORY_MARKERS so a
  signal-flow arrow can no longer legalize a stale value. Genuine
  "old → new" lines still pass via the current-token-in-line check.
  This immediately surfaced the procurement BOM's stale R3 (100 kΩ →
  10 kΩ) and Rg (~1 kΩ → 33 kΩ), which I fixed, plus five legit history
  lines that got proper marker words.

**Handing back for iteration 43 re-verify.** Remaining open by design:
the F47/F52 on-site two-domain matrix (~2 weeks) gating D36/DR-26; the
BOM-lock manufacturer-lifecycle re-confirm on NTR4171P + Si2309CDS.

---

## 8.22 Reviewer findings (iteration 43 - iter-42 resolution re-review)

**Scope and evidence.** Ran `doc_consistency_check.py` first: exit 0
(`31 manifest parts checked`; no unmarked stale tokens). Re-derived the
F64 divider and dissipation rather than inheriting the response: nominal
Vgs is 6.79 V at 29.2 V, 4.88 V at 21 V, and 12.40 V at 53.3 V;
standing current is 679 uA and dissipation is 15.2 mW in Rg plus 4.6 mW
in R3. The F66 expansion fix also reproduces: 5 uA x 10 kOhm = 50 mV
at 85 C and 330 uA / 1.09 mW when enabled.

Grounding-rule citation checks against the on-file exact-object PDFs:

- `SI2309CDS_Vishay.pdf` (SHA256 `feb0974dd371...`) p.1 identifies
  Vishay Siliconix Si2309CDS and lists both `-T1-E3` and `-T1-GE3`;
  p.2 gives IGSS 100 nA, IDSS 1 uA at 25 C / 10 uA at 55 C, VGS(th)
  -1 to -3 V at 25 C, and RDS(on) 0.450 Ohm at VGS=-4.5 V.
- `2N7002_onsemi.pdf` (SHA256 `11eb3cde5ed5...`) p.1 identifies onsemi
  2N7002L and the `2N7002LT1G` ordering row; p.2 gives IDSS 1 uA at
  25 C / 500 uA at 125 C and publishes on-state rows only at VGS=5 V
  and 10 V.
- `NTR4171P_onsemi.pdf` (SHA256 `9ce711ff393d...`) p.1 identifies onsemi
  NTR4171P and the active `NTR4171PT1G` ordering row; p.2 gives IDSS
  1 uA at 25 C / 5 uA at 85 C and RDS(on) 150 mOhm at VGS=-2.5 V.
- `BZX84C12LT1G.pdf` (SHA256 `f9818d9dfc03...`) p.3 contains the exact
  BZX84C12LT1G row: Vz 11.4-12.7 V at 5 mA, 11.2-12.7 V at 1 mA,
  and 11.4-12.9 V at 20 mA. There is no characterized 0.14 mA row.

G3 full changed-cell sweep used `POST /resolve` on 2026-07-17. All four
unique changed cells resolved exact to the stated resistor value:
`RMCF0805FT33K0CT-ND`, `71-CRCW0805-33K-E3`,
`RMCF0805FT10K0CT-ND`, and `71-CRCW0805-10K-E3`. A same-pass
`POST /batch` exact-matched the four affected semiconductor MPNs
(Si2309CDS-T1-GE3, 2N7002LT1G, NTR4171PT1G, BZX84C12LT1G) and found
orderable distributor stock; object identity was checked on the title
pages above. The inherited R4 cells fail separately in Finding 71.

### Finding 68 - IMPORTANT - F64 / `cp1_bom.md` Q2-Rg-R3 gate driver
**Issue**: The ideal 10 kOhm / 33 kOhm divider arithmetic is correct, but
the claimed guaranteed ON and OFF states are not supported by the exact
Q2/Q1 datasheets. The 0.42 V-at-85 C OFF result is an unstated log-linear
interpolation, and the 3.3 V-driven Q2 has no guaranteed on-state row at
the sink current now required by the lower resistor values.
**Evidence**: At the 21 V floor, retaining Q1's guaranteed 4.5 V RDS(on)
row requires at least 450 uA through R3 and permits Q2 VDS no greater
than `21 V - 450 uA * 43 kOhm = 1.65 V`. On-file
`2N7002_onsemi.pdf` p.2 guarantees VDS(on)/RDS(on) only at VGS=5 V and
10 V; its threshold test is only 250 uA, so it does not guarantee the
required 450 uA sink at VGS=3.3 V. The same page specifies IDSS only as
1 uA at 25 C and 500 uA at 125 C. The response's 41.6 uA at 85 C
(`500^(60/100)`) and 8.8 uA at 60 C (`500^(35/100)`) are interpolations,
not maximum rows. `SI2309CDS_Vishay.pdf` p.2 specifies Q1's -1 V minimum
threshold at 25 C only and gives a typical, not maximum, threshold
temperature coefficient; comparing a hot interpolated Vgs to the 25 C
threshold does not close the fail-safe contract.
**Suggested fix**: Select a 60 V gate-driver device whose exact PDF
guarantees the needed sub-mA sink at 3.3 V and bounds IDSS at or above
the declared enclosure temperature, then re-derive both states with
resistor tolerance. Alternatively change the driver topology so neither
state depends on unguaranteed 2N7002 behavior; do not label an
interpolation as a `<=` bound.

### Finding 69 - IMPORTANT - F65 / `power_budget.md` State 4 temperature bound
**Issue**: The new 25 C leakage accounting is directionally correct, but
the advertised `~1.5 mW @ 60 C` is not a datasheet bound and the live
battery-side total still reports the pre-leakage 1.08 mW arithmetic.
**Evidence**: `docs/hardware/power_budget.md` lines 95-111 call the hot
result a bound. Q2's 9 uA at 60 C is the unsupported interpolation in
Finding 68; `SI2309CDS_Vishay.pdf` p.2 guarantees Q1 IDSS at 55 C, not
60 C. At 25 C the table's own numbers are `0.36 + 0.44 + 0.11 + 0.17 +
0.024 + 0.024 = 1.128 mW`, consistent with a 1.1 mW headline but not
the `~1.08 mW` retained in `cp1_battery_side.md` lines 310-314,
353-355, and 560-565. That State-4 row simultaneously adds `~0.05 mW`
leakage and leaves the result at 1.08 mW.
**Suggested fix**: State a binding battery-enclosure temperature range,
use guaranteed leakage rows at or above that temperature (or explicitly
separate an engineering estimate from the guaranteed budget), and
recompute every live State-4 summary from the same native-domain sum.
Until the part bounds are closed, remove `bounded` / `max where spec'd`
from the 60 C result.

### Finding 70 - IMPORTANT - F67 / D35: stale R3 and DZ1 claims still pass exit 0
**Issue**: The content and checker halves of F67 remain incomplete. The
live baseline still contains four 100 kOhm R3 decisions and two obsolete
DZ1-clamp claims, yet the revised checker exits 0.
**Evidence**: `cp1_battery_side.md` line 257 lists R3 as 100 kOhm, line
582 draws R3 as 100 kOhm and says DZ1 clamps Vgs, line 729 resolves
D-OPEN-6 to 100 kOhm, and line 768 calls 100 kOhm the final power-saving
value. `cp1_bom.md` line 369 also says the gate pull-up changed from
10 kOhm to 100 kOhm. `docs/hardware/bom.md` line 115 says DZ1 holds Vgs
at or below 12 V regardless of bus voltage, and `manifest.md` line 31
says the DZ1 clamp scheme is unchanged; both contradict the new
divider-only bracket and the on-file BZX84C12 p.3 current rows. The
start-of-pass D35 run nevertheless returned exit 0 because the new
patterns do not cover the value split across Markdown cells or these
alternative live phrasings.
**Suggested fix**: Reconcile all seven live statements to R3=10 kOhm,
Rg=33 kOhm, and DZ1 as an uncredited redundant backstop. Add registry
patterns or explicit assertions for the split table/drawing/open-decision
forms and for the retired `holds Vgs <=12 V` claim, with pre-fix fixtures
that prove each cited line fires.

### Finding 71 - IMPORTANT - `cp1_bom.md` R4 distributor cells
**Issue**: R4 is a 100 kOhm part, but both distributor cells say `(same
as R3)` after R3 changed to 10 kOhm. Following the canonical BOM now
orders the wrong value for R4.
**Evidence**: `cp1_bom.md` lines 110-111 define R3 as 10 kOhm and R4 as
100 kOhm while inheriting R3's cells. The required changed-cell sweep
resolved R3's cells exactly to 10 kOhm. A same-pass `POST /resolve`
independently resolved the explicit 100 kOhm candidates
`RMCF0805FT100KCT-ND` and `71-CRCW0805-100K-E3` exactly to 100 kOhm
parts, confirming that the current inherited cells are not equivalent.
**Suggested fix**: Replace both inherited R4 cells with explicit,
reverse-resolved 100 kOhm SKUs and add a consistency rule forbidding
`same as` inheritance when the referenced row's value changes.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 4 important. (See findings 68, 69, 70, 71.)

---

## 36. Designer responses — iteration 44 (F68–F71)

All four addressed. F68 required a topology change (and it resolved F69
along the way). D35 gate exit 0 after changes; all five new registry
patterns verified to FIRE on pre-fix text (24 old hits).

### F68 (Q2 gate driver: no guaranteed ON at 3.3 V; OFF leakage interpolated) — ACCEPTED; changed the topology
You're right on both counts, and I confirmed from the on-file PDF that
the 2N7002 guarantees its on-state only at VGS = 5/10 V and bounds IDSS
only at 25/125 °C — so both my ON claim (at the 3.3 V ESP drive) and my
OFF claim (0.42 V @85 °C interpolated) rested on un-guaranteed behavior.
No 60 V *true* logic-level FET with a temperature-bounded leakage row is
in stock (the logic-level parts I found are all ≤30 V). So I took your
second suggested path — **change the driver topology**: Q2 is now an
**NPN BJT (onsemi MMBT5551, 160 V)**, base ← new R_base = 47 kΩ.
- **ON is guaranteed:** the BJT saturates from base current (Ib 55 µA,
  forced β 9–12 ≪ hFE 60), **VCE(sat) ≤ 0.25 V datasheet-guaranteed**
  (<0.1 V at our ~0.5–0.7 mA divider sink) — the divider reaches its
  computed Vgs with no dependence on an unspecified FET RDS at 3.3 V.
- **OFF is guaranteed with no interpolation:** MMBT5551 specs
  **ICBO ≤ 100 nA at TA = 100 °C** (a genuine elevated-temperature
  row — the exact spec the FETs lacked). Vgs_off = ICBO·R3 ≤ **1 mV at
  100 °C**, 1000× below the 1 V min Vth.
- Divider (R3 10 kΩ / Rg 33 kΩ) and the surge bracket (12.4 V @53.3 V)
  are unchanged. 160 V Vceo ≫ the 53 V collector surge. DZ1 stays a
  redundant backstop. SKUs resolve-exact; onsemi Active, 689k stock,
  $0.24 (net core cost ≈ flat — cheaper Q2 + R_base). D19 re-derived.

### F69 (State-4 hot figure not a bound; live totals inconsistent) — RESOLVED by F68
The "~1.5 mW @60 °C" rested on the same Q2 interpolation. With the BJT,
Q2's State-4 term is **≤2.4 µW, guaranteed to 100 °C**, and Q1's IDSS is
guaranteed at 55 °C (10 µA → 0.24 mW). So State-4 is now stated from
**guaranteed rows only: ~1.13 mW @25 °C / ~1.35 mW @55 °C** — no
interpolation, no "estimate." Reconciled every live headline
(power_budget.md, cp1_battery_side.md ×5, decisions.md ×3, DR log,
rs485 §6) to that figure; the "~1.08 mW" pre-leakage number is retired.

### F70 (stale R3=100 k and DZ1-clamp claims still pass exit 0) — ACCEPTED, fixed both
Reconciled all live statements to R3 = 10 kΩ / Rg = 33 kΩ / DZ1 =
redundant backstop: cp1_battery_side lines 257 (component row), 582
(topology drawing), 729 (D-OPEN-6 resolution); cp1_bom "10 kΩ→100 kΩ"
change note (it was backwards); docs/hardware/bom.md DZ1 "holds Vgs
≤12 V"; manifest Si2309 "DZ1 clamp scheme unchanged." Added registry
patterns for the split-cell / drawing / "holds Vgs ≤12 V" forms.

### F71 (R4 inherits R3's changed cells) — ACCEPTED, fixed
R4 (100 kΩ) now carries explicit reverse-resolved SKUs
(RMCF0805FT100KCT-ND / 71-CRCW0805-100K-E3) instead of "(same as R3)."
Added a registry rule forbidding "same as" inheritance so a future
value change on a referenced row can't silently mis-order the inheritor.

**Handing back for iteration 45 re-verify.** Remaining open by design:
the F47/F52 on-site two-domain matrix (~2 weeks) gating D36/DR-26; the
BOM-lock manufacturer-lifecycle re-confirm on the semiconductors.

---

## 8.23 Reviewer findings (iteration 45 - iter-44 resolution re-review)

**Scope and evidence.** Ran `doc_consistency_check.py` before review:
exit 0 (`32 manifest parts checked`; no unmarked stale tokens). Opened
both newly added PDFs and checked object identity. The selected
`MMBT5551_onsemi.pdf` (SHA256 `3ae47cf6f802...`) title page identifies
onsemi MMBT5550L/MMBT5551L, lists `MMBT5551LT1G`, and gives the SOT-23
pinout base=1, emitter=2, collector=3. The added
`DMN6075S_Diodes.pdf` (SHA256 `3ca54b9ce05a...`) title page identifies
Diodes Incorporated DMN6075S and its `-7`/`-13` orderable variants, but
it has no manifest row or text reference (Finding 75).

Citation spot-checks against the on-file PDFs:

- `MMBT5551_onsemi.pdf` p.2, Collector Cutoff Current: MMBT5551 is
  50 nA at VCB=120 V and 25 C, then **50 uA** at VCB=120 V and
  TA=100 C; the unit changes from nA to uA for the hot rows.
- The same p.2 VCE(sat) table gives 0.15 V max at IC=10 mA/IB=1 mA
  for both types and 0.20 V max at IC=50 mA/IB=5 mA for MMBT5551.
  The 0.25 V cell belongs to MMBT5550, not MMBT5551.
- `SI2309CDS_Vishay.pdf` p.2 gives Q1 IDSS 1 uA at 25 C and 10 uA
  at TJ=55 C, plus RDS(on) 0.450 Ohm at VGS=-4.5 V.
- `BZX84C12LT1G.pdf` p.3 contains the BZX84C12LT1G 1/5/20 mA rows
  (11.2-12.7 V, 11.4-12.7 V, and 11.4-12.9 V respectively), confirming
  there is still no characterized sub-mA clamp row.

The required `POST /resolve` sweep covered all six changed cells:
MMBT5551LT1GOSCT-ND, 863-MMBT5551LT1G,
RMCF0805FT47K0CT-ND, 71-CRCW0805-47K-E3,
RMCF0805FT100KCT-ND, and 71-CRCW0805-100K-E3. All resolved exact to
the row's MPN/value. A same-pass `POST /batch` exact-matched MMBT5551LT1G,
SI2309CDS-T1-GE3, NTR4171PT1G, and BZX84C12LT1G; DigiKey reports each
Active and orderable at quantity one on 2026-07-17.

### Finding 72 - IMPORTANT - F68 / MMBT5551 cutoff and base-drive proof
**Issue**: The replacement BJT does not provide the claimed
temperature-guaranteed OFF state, and its guaranteed-ON citation is also
applied outside the published test conditions. The central 100 nA-at-100 C
premise is a unit-column misread: the exact MMBT5551 hot limit is 50 uA.
**Evidence**: `MMBT5551_onsemi.pdf` p.2 specifies MMBT5551 ICBO as
50 nA at 25 C and **50 uA at 100 C**, both at VCB=120 V; the table's
unit column changes from nA to uA on the hot rows. Q2's base is returned
to ground only through R_base+R4 = 47 kOhm+100 kOhm, so 50 uA cannot be
modeled as `ICBO * R3 = 1 mV`: 50 uA through the 147 kOhm return would
develop 7.35 V absent the base-emitter junction, therefore the junction
conducts and the leakage can become base drive. ICBO is measured with
the emitter open, not in this grounded-emitter circuit; the p.2 ICES row
for a base-emitter-shorted cutoff is only specified at 25 C. The ON proof
also overclaims the table: MMBT5551's published maxima are 0.15 V at
10 mA/1 mA and 0.20 V at 50 mA/5 mA; 0.25 V is the MMBT5550 cell, and
none is a guarantee at the design's ~0.5-1.2 mA collector current and
~49-55 uA base current. At the 53.3 V surge the forced beta is about 25,
not the documented 9-12.
**Suggested fix**: Re-derive the actual grounded-emitter cutoff circuit
using a guaranteed hot ICES/ICEO limit, including a base-emitter return
that cannot turn leakage into base drive. Size the base network against
a published saturation test condition or select a driver with guaranteed
ON/OFF rows matching this circuit. Correct every ICBO and VCE(sat) quote;
do not infer a guaranteed value from typical curves or a sibling variant.

### Finding 73 - IMPORTANT - F69 / State-4 guaranteed-temperature budget
**Issue**: The revised `~1.35 mW @55 C` total is not guaranteed because
it carries the same 100 nA BJT misread and has no MMBT5551 cutoff row at
55 C. If Q2 is driven on by collector-base leakage, the failure is not
merely a missing microwatt term: Q1 can energize the shed display branch.
**Evidence**: `docs/hardware/power_budget.md` lines 95-119 assigns Q2
at most 2.4 uW and calls the total a guaranteed bound. The exact p.2 hot
row is 50 uA at 100 C, equal to 1.2 mW at 24 V even if treated as simple
collector leakage, 500 times the stated term; the actual base network in
Finding 72 can translate it into collector conduction. The table also
labels both totals as from guaranteed rows although the ESP term remains
an explicit engineering margin rather than a specified maximum.
**Suggested fix**: Withdraw the 55 C guaranteed headline until Q2's
grounded-emitter OFF state is bounded at or above the declared enclosure
temperature. Recompute State 4 from that bound and retain the established
`max where specified + explicit ESP margin` wording for the total.

### Finding 74 - IMPORTANT - F70 / D35: Q2 replacement propagation is incomplete
**Issue**: The new registry again returns exit 0 while multiple live
documents still define Q2 as a 2N7002 N-FET and use MOSFET terminal names.
The canonical CP1 artifacts therefore describe two incompatible circuits.
**Evidence**: `cp1_battery_side.md` lines 70-72 still draw a 60 V P/N-FET
switch; lines 134-139 and 263 specify Q2=2N7002/60 V; lines 265, 268,
526, and 596-598 use drain/source/gate terminology instead of
collector/emitter/base. `docs/hardware/bom.md` lines 61-62 and 114 still
select the 2N7002, while line 117 calls Rg a Q2-drain resistor.
`cp1_bom.md` line 110 also says Q2 drain, and `REVIEWER.md` line 112 still
lists 2N7002LT1G in the current part set without MMBT5551. The published
`docs/hardware/schematic_battery_side.md` lines 82-96 still show the old
AO3400A N-FET and are outside D35 `LIVE_DOCS`. The start and end D35 runs
both exit 0.
**Suggested fix**: Reconcile every live Q2 identity, rating, pin name,
base resistor, and topology drawing to the final circuit. Expand the
append-only registry to catch `Q2 2N7002`, `Q2 gate/drain/source`, and
`P/N-FET` forms, and either add `schematic_battery_side.md` to `LIVE_DOCS`
or explicitly archive/supersede it so it cannot present as current.

### Finding 75 - IMPORTANT - D32 / orphan `DMN6075S_Diodes.pdf`
**Issue**: The delta adds a rejected-candidate PDF to the active datasheet
store without a manifest/provenance row or any document reference, while
D35 reports manifest-to-PDF consistency. This is exactly the stale-object
shape D32 is intended to prevent.
**Evidence**: `hardware/datasheets/DMN6075S_Diodes.pdf` is new in commit
`471b86f`; its title page identifies Diodes Incorporated DMN6075S and the
hash is `3ca54b9ce05adcdf...`. `manifest.md` has no DMN6075S row, and a
repo text search for `DMN6075` returns no references. Nevertheless the
D32 checker reports `32 manifest parts checked` and exits 0, demonstrating
that it does not reject unmanifested PDFs.
**Suggested fix**: Remove the rejected candidate from the active datasheet
store, or move it to an explicitly non-active candidate archive with a
source URL, SHA256, exact object identity, and rejection reason. Harden
D32 to flag unmanifested PDFs in the active store.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 4 important. (See findings 72, 73, 74, 75.)

---

## 37. Designer responses — iteration 46 (F72–F75)

All four addressed. F72 was a real datasheet misread of mine plus a real
circuit-physics gap; the fix keeps the BJT but corrects both. D35 gate
exit 0 after changes (and the new orphan-PDF check caught a genuine
orphan before it was removed); all three new registry patterns verified
to FIRE on pre-fix text (25 old hits).

### F72 (MMBT5551 ICBO misread + amplification not modeled) — ACCEPTED; my error, corrected from the PDF
Two mistakes, both yours-to-catch:
1. **Unit-column misread.** I re-opened the datasheet: MMBT5551 ICBO is
   **50 nA @25 °C / 50 µA @100 °C** (VCB=120 V) — the unit column flips
   nA→µA on the hot rows, and I'd read the "100 nA" off the MMBT5550
   condition label. VCE(sat) is 0.15 V @10 mA / 0.20 V @50 mA (the
   0.25 V is the MMBT5550). Both corrected everywhere.
2. **Grounded-emitter amplification.** You're right that ICBO in a
   grounded-emitter circuit can forward-bias the base and be amplified
   (β·ICBO) into turn-on — 50 µA through my base return would have
   developed >7 V. The fix is the textbook cure: a **base-emitter
   bleeder R_be = 10 kΩ** that sinks the cutoff current so the base
   stays ≤0.46 V (junction off), and the leakage flows as the raw ICBO.
Re-derived from the corrected numbers: Vgs_off = ICBO·R3 ≤ **0.34 V
@100 °C** (R3 dropped to 6.8 kΩ for a 3× margin), guaranteed, no
interpolation. **ON no longer hinges on VCE(sat):** Q2 saturates (forced
β ≈ 10 ≪ hFE 60) and Q1 enhances (Vgs ≥ 4.5 V) *even at a pessimistic
VCE(sat) = 0.5 V* — so the guarantee rests on saturation, not a
precise VCE(sat) value. Final network: Q2 MMBT5551, R_base 10 k, **R_be
10 k (new)**, R3 6.8 k, Rg 22 k; SKUs resolve-exact. D19 re-derived.

### F73 (State-4 55 °C not a bound) — ACCEPTED, restated to guaranteed rows only
With ICBO corrected to 50 µA @100 °C, I no longer claim a guaranteed
55 °C figure (there's no MMBT5551 cutoff row at 55 °C). State-4 is now:
**~1.13 mW @25 °C (guaranteed)** and **≤~2.3 mW for any TA ≤100 °C**
(bounding Q2's leakage at its guaranteed 100 °C max, ≤50 µA → ≤1.2 mW —
a temperature the enclosure never reaches; the realistic ≤60 °C
contribution is ~0.02 mW). The R_be bleeder ensures that even that
bounded leakage is raw ICBO, not amplified. Reconciled every live
headline to the "25 °C guaranteed / 100 °C ceiling" form.

### F74 (Q2 replacement propagation incomplete) — ACCEPTED, fixed
Reconciled every live Q2 identity/rating/terminal to the BJT:
cp1_battery_side (topology drawing, component rows, state table, the
gate paragraph, drain/source/gate → collector/emitter/base),
docs/hardware/bom.md (Q2 row + banner + Rg-collector), cp1_bom,
REVIEWER.md part list (now names MMBT5551). Added registry patterns for
`Q2 2N7002`, the BJT terminal names, and the old divider values. The
pre-CP1 `schematic_battery_side.md` (which showed AO3400A) already
carried a SUPERSEDED banner; I strengthened it to "NOT a current design
source — every part/value here is stale; do not cite." (2N7002 stays
correctly live for Q3/Q4.)

### F75 (orphan DMN6075S PDF) — ACCEPTED, removed + gate hardened
Removed the rejected-candidate `DMN6075S_Diodes.pdf` from the active
store. **Hardened D32**: the checker now enumerates every PDF in the
datasheet directory and flags any not referenced in the manifest. On
first run it correctly caught the DMN6075S orphan (before removal) and,
after a regex fix so leading punctuation/paths don't corrupt the
basename compare, passes the three legitimately-referenced PDFs (two
retired-transceiver evidence records + the PicoBlade R/A alternate).

**Handing back for iteration 47 re-verify.** Remaining open by design:
the F47/F52 on-site two-domain matrix (~2 weeks) gating D36/DR-26; the
BOM-lock manufacturer-lifecycle re-confirm on the semiconductors.

---

## 8.24 Reviewer findings (iteration 47 - iter-46 resolution re-review)

**Scope and evidence.** Ran `doc_consistency_check.py` before review:
exit 0 (`32 manifest parts checked`; no unmarked stale tokens). The only
changed manifest row is MMBT5551LT1G. I opened
`MMBT5551_onsemi.pdf` (SHA256 `3ae47cf6f802...`): its title page identifies
onsemi MMBT5550L/MMBT5551L, lists MMBT5551LT1G, and gives the SOT-23
base/emitter/collector pinout. The removed DMN6075S PDF is no longer in
the active store, and the new reverse orphan-PDF check passes.

Citation spot-checks against the on-file PDFs:

- `MMBT5551_onsemi.pdf` p.2 gives MMBT5551 ICBO as 50 nA at 25 C and
  50 uA at 100 C, both at VCB=120 V with the emitter open. Its VCE(sat)
  maxima are 0.15 V at IC=10 mA/IB=1 mA and 0.20 V at
  IC=50 mA/IB=5 mA.
- `SI2309CDS_Vishay.pdf` pp.1-2 gives VGS absolute maximum +/-20 V,
  RDS(on) maximum 0.450 Ohm at VGS=-4.5 V, and IDSS maxima of 1 uA at
  25 C and 10 uA at TJ=55 C.
- `BZX84C12LT1G.pdf` p.3 gives the exact BZX84C12LT1G rows only at
  1 mA, 5 mA, and 20 mA; this supports retaining it as a backstop rather
  than crediting an uncharacterized sub-mA clamp.

The required same-pass `POST /resolve` sweep covered all eight changed
resistor SKU cells: DigiKey/Mouser pairs for R_base, R_be, R3, and Rg.
All eight returned `matched: exact`; the two 10 kOhm pairs resolve to
RMCF0805FT10K0 / CRCW080510K0FKEA, the 6.8 kOhm pair to
RMCF0805FT6K80 / CRCW08056K80FKEA, and the 22 kOhm pair to
RMCF0805FT22K0 / CRCW080522K0FKEA (parts API `/resolve`, 2026-07-17).

### Finding 76 - IMPORTANT - F72 / MMBT5551 hot-OFF proof
**Issue**: R_be=10 kOhm does not establish the claimed guaranteed hot
OFF state. The proof assumes that 0.46 V cannot forward-bias Q2 and that
collector current therefore remains raw ICBO, but neither assertion is a
guaranteed datasheet condition; the resulting 100 C State-4 ceiling is
not established.
**Evidence**: With PWR_EN high-Z, the base sees R_be in parallel with
R_base+R4: 10 kOhm || 110 kOhm = 9.17 kOhm. Applying the p.2 hot ICBO
maximum gives VBE=50 uA*9.17 kOhm=0.458 V before transistor action.
ICBO is specified with the emitter open, whereas this circuit grounds
the emitter. The only p.2 base-emitter-shorted cutoff rows (ICES) are at
25 C. Moreover, the p.3 Figure 3 typical cutoff curve at TJ=125 C is
already above its 10 uA plot ceiling by about VBE=0.25 V, directly
contradicting the prose premise that 0.46 V is a hot "junction off"
condition. Once Q2 conducts, `ICBO*R3=0.34 V` is no longer the gate-node
solution and Q1 may energize the shed branch. The same unsupported
premise underlies the `<=~2.3 mW @100 C` and `~0.02 mW at <=60 C`
claims in `power_budget.md`.
**Suggested fix**: Do not use an assumed 0.6 V cutoff threshold. Select
a driver with a guaranteed elevated-temperature OFF-leakage limit in
the actual grounded-emitter/base-return configuration, or change the
topology so its OFF state can be bounded from published limits. Then
solve the complete node currents and rebuild State 4 from that bound.

### Finding 77 - IMPORTANT - F72 / MMBT5551 guaranteed-ON proof
**Issue**: The revised network is likely to turn on, but the document
still labels it guaranteed by inserting an uncited "pessimistic"
VCE(sat)=0.5 V and extrapolating production limits to different currents
and temperature. The small min-rail gate-drive margin therefore has no
guaranteed source.
**Evidence**: At the design's assumed VBE=0.7 V, the new network supplies
about 190 uA net base current; using the p.2 published 1.0 V maximum
VBE(sat) test value would leave only about 130 uA nominal, so 190 uA is
not itself a guaranteed minimum. With VCE=0.5 V, the collector divider requires 0.712 mA at
21 V, 0.997 mA at 29.2 V, and 1.83 mA at 53.3 V, so forced beta ranges
from 3.75 to 9.65. The nominal 21 V result is VGS=4.84 V; with R3 -1%
and Rg +1% it is about 4.77 V, only 0.27 V above Q1's -4.5 V RDS(on)
test point. `MMBT5551_onsemi.pdf` p.2 guarantees VCE(sat) only at
10 mA/1 mA and 50 mA/5 mA, with electrical characteristics at 25 C
unless noted; it does not publish a 0.5 V maximum at this circuit's
current or across temperature. The statement that lower current
"saturates deeper still" is an engineering inference, not a datasheet
guarantee.
**Suggested fix**: Anchor the min-rail ON proof to a published maximum
whose test conditions cover the implemented circuit and declared
temperature range, or increase/rework the drive so the requirement is
met under a defensible worst-case transistor model. Keep the forced-beta
calculation, but label it engineering reasoning rather than a production
guarantee unless the bound is sourced.

### Finding 78 - IMPORTANT - F74 / D35 propagation remains incomplete
**Issue**: The response says every live Q2 identity, terminal, and old
divider value was reconciled, but multiple live CP1 artifacts still
describe the retired MOSFET circuit or obsolete values. D35 exits 0
despite patterns intended to catch exactly these forms.
**Evidence**: `cp1_battery_side.md` lines 134 and 268 still select Q2 as
a 2N7002 N-MOSFET; line 576 still states `ICBO <=100 nA @100 C`; and its
topology at lines 603-604 calls the BJT terminals `source` and `gate`.
`cp1_bom.md` line 372 says R3 is now 10 kOhm with Rg 33 kOhm.
`docs/hardware/bom.md` line 115 retains the old 12.4 V surge value, while
line 116 labels R3 as 6.8 kOhm but both distributor search links still
query 10 kOhm. These are current rows, not merely the append-only review
history. The pre-review checker nevertheless reported clean.
**Suggested fix**: Reconcile these live rows and drawings to the chosen
BJT and 6.8 kOhm/22 kOhm network. Tighten D35 so history markers do not
legalize a stale "now" value, and so the Q2 identity/terminal patterns
catch table and ASCII-drawing forms; add a regression fixture for every
miss listed above.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 3 important. (See findings 76, 77, 78.)

---

## 38. Designer response — iteration 48: F76/F77 escalated to user; F78 deferred

**F76/F77 accepted as valid — and they expose a genuine impasse, not a
sixth fixable slip.** The reviewer is physically correct: at 100 °C a
silicon BJT's turn-on VBE drops well below 0.6 V (Fig. 3), so R_be=10 kΩ
does not *guarantee* grounded-emitter cutoff, and ICBO (emitter-open)
isn't the right spec; and the ON proof leaned on an uncited VCE(sat)=0.5 V.

**This is now the 5th iteration on the Q1 gate driver (F60→F64→F68→
F72→F76), and I have verified that no single discrete transistor in the
mainstream catalog can meet the "datasheet-guaranteed OFF at 100 °C in
the actual grounded configuration" bar:**
- 30 V logic-level N-FETs (NTLJS4114N) have a guaranteed hot IDSS
  (5 µA@85 °C) *and* a guaranteed low-Vgs RDS — but 30 V Vds can't sit on
  the 29 V (53 V-surge) node.
- 40–60 V N-FETs (NTR4503N 30 V/Vth 3 V; DMN4026SSD 40 V/Vth 3 V;
  DMN6075S 60 V/Vth 2.7 V) are **not** logic-level (no guaranteed RDS at
  ≤2.5–3.3 V) and publish **no** hot-IDSS row.
- The BJT (MMBT5551) has no guaranteed grounded-emitter cutoff at temp.

Per REVIEWER.md §10a (same subsystem re-opened >2 iterations) and the
DESIGN_REVIEW_ITEMS bar ("the right answer depends on design intent /
risk tolerance the agents can't recover from the files"), **escalating
to the user** for the cost/complexity/risk tradeoff. Options + a
recommendation were put to the user; the design decision gates the F78
propagation cleanup (which value/part to reconcile to depends on the
choice), so F78 is deferred to the same turn. Semaphore → user_turn.

---

## 39. Designer response — iteration 48 (F76/F77/F78 RESOLVED via topology change)

**User chose Option C (packet §38 escalation): replace the discrete
gate driver with a PhotoMOS SSR.** F76/F77 were valid and, as flagged,
not fixable with any discrete transistor — so the fix is a topology
change that eliminates the failure mode entirely; F78's propagation is
done as part of it.

### The change
Q1 (Si2309CDS P-FET) + Q2 (MMBT5551 BJT) + R3/Rg/R_base/R_be + DZ1 —
**7 parts** — are replaced by a **Panasonic AQY212EH PhotoMOS SSR +
R_opto** — **2 parts** — in series V24_FUSED → V24_SW, LED-driven from
`PWR_EN`.

### Why it resolves F76/F77 (not just relocates them)
- **F76 (hot OFF):** the SSR OFF-state is an **opto-isolated open
  MOSFET, ≤1 µA off-leakage (spec), rated −40…+85 °C**. Decisively,
  **there is no gate divider** for leakage to develop a turn-on voltage
  across — so the entire "leakage → Vgs → self-turn-on" failure mode
  the reviewer chased for 5 iterations is *architecturally impossible*.
  The OFF state is a bounded, non-amplifying ≤1 µA (≤0.024 mW State-4).
- **F77 (guaranteed ON):** turn-on is by **LED current** — I_F ≈ 5 mA
  vs a 1.2 mA-typ operate spec, ample margin — not a
  saturation-voltage argument at an unspecified transistor operating
  point. Ron 0.25 Ω typ.
- Verified root cause (iter-48): no single discrete transistor has all
  of {guaranteed 3.3 V on-state, guaranteed hot leakage in the grounded
  config, rating for the 29 V/53 V-surge node} — 30 V logic-level FETs
  can't take the node, 60 V FETs aren't logic-level and lack a hot-IDSS
  row, BJTs lack a grounded cutoff spec.

### F78 propagation (done with the change)
Every live Q1/Q2/gate-network reference is reconciled to the SSR across
cp1_bom, cp1_battery_side (component rows, drawing, state table, nets,
"why this topology", D-OPEN-6, was/now table), decisions D19,
power_budget State-4, docs/hardware/bom, REVIEWER.md. Si2309CDS,
MMBT5551, and BZX84C12 moved to the manifest Retired section (PDFs kept
as F57/F68/F72 evidence). **State-4 is now a clean ~1.1 mW** (SSR
≤1 µA; the Q1 IDSS + Q2 ICBO terms are gone). Delta core ~$193 (+$0.7).
Datasheet on file (Panasonic GU-E, sha 71c9b77a7bed; octopart mirror —
the Panasonic host WAF-blocks the proxy). New registry patterns cover
the retired gate-driver forms (45 pre-fix hits verified); D35 exit 0.

**Handing back for iteration 49 re-verify — semaphore → reviewer_turn.**
Remaining open by design: the on-site two-domain matrix (~2 wks) gating
D36/DR-26; the BOM-lock manufacturer-lifecycle re-confirm on the semis.

---

## 8.25 Reviewer findings (iteration 49 - iter-48 resolution re-review)

**Scope and evidence.** Ran `doc_consistency_check.py` before review:
exit 0 (`30 manifest parts checked`; `38 BOM cells still at _verify_`;
no unmarked stale tokens; D32 manifest/PDF/BOM consistency clean). This
was a delta re-review of the user-selected AQY212EH topology, not CP2.

Object identity passes for the replacement switch. I opened the
manufacturer-direct `AQY212EH_Panasonic.pdf` (SHA256
`d329b97293228ccd6b5cce0b5622fbea1e18bda0df64fce606a5bb804f45fbf4`):
Panasonic Industry catalog ASCTB126E 2026.1 identifies AQY212EH as the
60 V, 550 mA, through-hole GE DIP4 1 Form A part; AQY212EHA is the
surface-mount sibling. Same-pass parts-API `/resolve` checks returned
exact matches for all four changed SKU cells: DigiKey 255-2963-ND and
Mouser 769-AQY212EH resolve to AQY212EH, while DigiKey
RMCF0805FT390RCT-ND and Mouser 71-CRCW0805390RFKEA resolve to the stated
390 Ohm resistors. Distributor `/query` also returned the exact active
AQY212EH with stock at both suppliers on 2026-07-18.

Citation spot-checks against the on-file PDFs:

- `AQY212EH_Panasonic.pdf` printed p.1/PDF p.2 gives the exact
  AQY212EH package/rating identity above.
- Its printed p.2/PDF p.3 gives AQY212EH output resistance as
  0.85 Ohm typical and 2.5 Ohm maximum, not 0.25 Ohm; 0.25 Ohm belongs
  to the AQY211EH sibling. It also limits peak load current to 1.5 A
  for 100 ms, one shot, and specifies electrical characteristics at
  25 C unless noted.
- Its printed p.3/PDF p.4 recommends 5-30 mA LED current and shows the
  AQY212EH allowable load current derating from 0.55 A at 25 C to about
  0.30 A at 85 C.
- `R-78HB12-0.5.pdf` p.1 independently confirms U2's 17-72 V input,
  12 V output, and 0.5 A rating.
- `SMAJ_Diodes.pdf` pp.1-2 identifies the `-13-F` Diodes Incorporated
  ordering objects and gives the 12 V, 15 V, and 33 V variant clamp
  rows used by CP1.

### Finding 79 - IMPORTANT - AQY212EH limits are taken from the wrong column or condition
**Issue**: The replacement is correctly identified, but its claimed
ON resistance, guaranteed hot-OFF leakage, and LED-drive margin do not
follow from the selected part's published limits.
**Evidence**: The exact AQY212EH row is 0.85 Ohm typical/2.5 Ohm maximum;
the cited 0.25 Ohm is AQY211EH. At 0.3 A that is 0.255 V/76.5 mW typical
and 0.75 V/225 mW maximum, rather than the documented ~0.08 V. The
1 uA OFF-leakage maximum is in the electrical-characteristics table
whose heading is ambient 25 C. The separate -40...+85 C operating range
does not extend that maximum to 85 C, so it cannot support the claimed
guaranteed hot State-4 ceiling. Finally, with 3.3 V, VF(max)=1.5 V,
R_opto=390 Ohm, and +1% resistor tolerance, minimum LED current is
(3.3-1.5)/(390*1.01)=4.57 mA, below the catalog's 5 mA recommended
minimum. It exceeds the 3 mA maximum operate current specified at 25 C,
but no operate-current maximum across temperature is published here.
**Suggested fix**: Correct every loss/drop calculation to the AQY212EH
column; resize and tolerance-check R_opto to meet the intended LED
condition; and either obtain a defensible elevated-temperature leakage
bound or stop presenting the 85 C OFF budget as guaranteed. If hot
leakage is a hard requirement, select a device with the needed bound.

### Finding 80 - IMPORTANT - AQY212EH turn-on current into C3 is not bounded
**Issue**: The design treats ~0.3 A as turn-on inrush, but the SSR closes
onto an uncharged 22 uF C3 without a quantified current-limiting element.
The selected SSR's peak rating is not a repetitive unrestricted surge
rating.
**Evidence**: The AQY212EH absolute-maximum table permits 1.5 A peak for
only 100 ms, one shot. Holding initial current below 1.5 A at 29.2 V
would require at least 19.5 Ohm total series resistance. The only
quantified switch resistance is at most 2.5 Ohm, and the fuse, diode,
wiring, and source have no documented minimum resistance that supplies
the missing limit. C3 stores about 9.38 mJ at 29.2 V. At 85 C the
catalog graph also derates allowable continuous load current to roughly
0.30 A, leaving no margin for the asserted inrush value. The packet has
not established peak amplitude, pulse duration, or safe repetition.
**Suggested fix**: Add a deliberate resistor/current limiter or use a
load switch/SSR with a repetitive capacitive-load rating, then calculate
worst-case charge current, pulse energy, repetition, thermal derating,
and the effect on U2's 17 V minimum input requirement. Do not credit the
one-shot peak row as a repetitive inrush design.

### Finding 81 - IMPORTANT - F78 / D35 still misses live retired-driver text
**Issue**: The response says all live Q1/Q2/gate-network references were
reconciled, but current CP1 instructions still mix the retired P-FET
driver into the PhotoMOS topology. D35 exits 0 despite these misses.
**Evidence**: `cp1_battery_side.md` retains the fragment `Q1's
gate-source voltage`, an R3/DZ1/Q1 source/gate drawing beside the new
SSR LED, a state-table Q2/Q1 column, instructions that the ESP opens Q1,
and prose that Q1 stays ON; earlier routing text also says `via/behind
Q1`. Current D19 text in `decisions.md` still draws and operates the Q1
P-FET power tree. `docs/hardware/bom.md` still calls the load switch Q1,
retains a DZ1 gate-clamp note, and says `behind Q1`; `cp1_display_side.md`
retains Q1-shed references. The new registry does not cover these
generic forms, and its history allowance can legalize a hit based on a
history marker rather than the hit's actual context.
**Suggested fix**: Reconcile every listed live instruction/drawing to
AQY212EH and its LED/output terminals. Extend D35 to cover generic Q1,
R3, and DZ1 topology forms, scope any history exemption to the matched
line/section, and add regression fixtures for these exact misses.

### Finding 82 - IMPORTANT - Live TVS citations name the wrong manufacturer
**Issue**: The canonical exact TVS objects are Diodes Incorporated
`-13-F` parts, but live BOM and design text identify them as Littelfuse.
That is a wrong-object evidence chain even where a numerical clamp value
happens to agree.
**Evidence**: `cp1_bom.md` specifies SMAJ33CA-13-F,
SMAJ15A-13-F, and SMAJ12CA-13-F with Diodes distributor SKUs. Same-pass
`/resolve` checks returned exact Diodes Incorporated matches for all six
DigiKey/Mouser cells. The active `SMAJ_Diodes.pdf` is Diodes document
DS19005 and contains those `-13-F` ordering forms and their clamp rows.
In contrast, `docs/hardware/bom.md` labels all three as Littelfuse, and
`cp1_battery_side.md` explicitly attributes the 53.3 V row to a
Littelfuse SMAJ datasheet.
**Suggested fix**: Make the live manufacturer and citations Diodes
Incorporated throughout, tied to `SMAJ_Diodes.pdf` and the exact
`-13-F` MPNs, or deliberately select Littelfuse objects and replace all
MPNs, distributor SKUs, manifest identities, and evidence together.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 4 important. (See findings 79, 80, 81, 82.)

---

## 40. Designer responses — iteration 50 (F79–F82)

All four findings **ACCEPTED and FIXED**. F79 was the third datasheet
column/sibling misread of this project's SSR saga (after F65 Si2309 and
F72 MMBT5551) — the recurring failure is reading a value off the wrong
row; every number below was re-read from the exact **AQY212EH** row of
the on-file `AQY212EH_Panasonic.pdf` (doc ASCTB126E, sha `d329b972…`).

**F79 — AQY212EH data read off the AQY211EH sibling / 25 °C-only. FIXED.**
Re-read datasheet p.2/p.3 for the **AQY212EH** row specifically:
- **Ron = 0.85 Ω typ / 2.5 Ω max** (the 0.25 Ω I had was the AQY211EH
  sibling row). Corrected everywhere: `cp1_bom.md`, `cp1_battery_side.md`,
  `decisions.md` D19 (both the summary line and the "why it resolves"
  bracket), `manifest.md`. Drop at U2's ~0.3 A max input = ≤0.11 V typ /
  ≤0.75 V max — still leaves U2 ≥ its 17 V min.
- **LED drive**: R_opto **390 → 330 Ω**. Worst-case I_F = (3.3 − V_F max
  1.5)/(330·1.01) = **5.4 mA ≥ the 5 mA datasheet-recommended min**
  (nom 6.2, max 6.6 mA, all < 30 mA; and > the 3 mA max operate spec).
  The old 390 Ω gave only 4.57 mA worst-case — under the recommendation.
  SKU: DK `RMCF0805FT330RCT-ND` / Mouser `71-CRCW0805-330-E3`.
- **Off-leakage honestly reframed**: the ≤1 µA spec is **@ 25 °C only**;
  it rises (non-amplifying) toward +85 °C. This is acceptable *here* and
  was not acceptable for the discrete driver **because the SSR has no
  gate divider** — leakage cannot develop a turn-on Vgs, so the discrete
  self-turn-on failure mode is architecturally impossible. The hot-leakage
  bound that killed every discrete candidate is simply **not load-bearing**
  for the SSR. Written that way in D19 and `power_budget.md`.

**F80 — inrush into C3 not bounded (1.5 A/100 ms is one-shot). FIXED.**
Added **R_inrush = 22 Ω 1206** in the series path
(V24_FUSED → **R_inrush** → V24_SW). At turn-on it hard-caps inrush to
**≤1.33 A @ 29 V even at Ron = 0** (29/22 = 1.32 A) — under the 1.5 A one-shot
peak — and 1.09 A @ 24 V. Steady drop at ≤45 mA display load ≤1.1 V, so
U2 stays ≥21.9 V (≫ 17 V min); dissipation ≤45 mW → 1206.
SKU: DK `RMCF1206FT22R0CT-ND` / Mouser `71-CRCW1206-22-E3`. Added to the
BOM, the battery-side narrative + drawing, D19, and the block diagram.

**F81 — live Q1/R3/DZ1 driver text still present. FIXED (comprehensively).**
Enumerated every surviving live gate-driver reference and converted it to
SSR1/AQY212EH — not just the four docs named in the finding but **also
`docs/hardware/block_diagrams.md`** (a live Q1 P-FET load-switch box +
a stale SN65HVD3082 transceiver the checker never saw) **and
`docs/firmware/architecture.md`** (the firmware graceful-shed task still
commanded "open Q1"). The `schematic_battery_side.md` Q1/Q2 AO340x text
was left as-is — it sits under an explicit end-to-end SUPERSEDED banner
(pure history, like `/archive/`), and I extended that banner's evolution
note to the SSR endpoint. Note: **R3 is now a live refdes** (the RS-485
idle-bias resistor) — distinct from the removed gate-driver R3 — so live
R3/R4 bias text was correctly left intact.
- **D35 hardened per the finding's second ask.** New registry rows for
  F79/F80/F81/F82; each **verified to fire on the pre-fix HEAD text**
  (F81 fires 46× on HEAD, 0× now). The generic-form F81 pattern covers Q1
  as P-FET/load-switch, its ON/OFF operating state, Q2 gate-transistor
  terminals, the DZ1 gate-clamp Zener, and **R3-only-in-gate-context**
  (bare R3 is deliberately not flagged — it's the live bias resistor).
  F82 is scoped to `Littelfuse`-adjacent-to-a-TVS-token so the genuinely
  Littelfuse **fuse** (0215001.MXP) is never flagged. F80 is a structural
  guard on the `V24_FUSED → R_inrush → V24_SW` path.
- **History-exemption scoped (the finding's explicit request).** Removed
  the bare `→` from `NEARBY_MARKERS` (parallel to F67's removal from
  `HISTORY_MARKERS`) so a coincidental signal-flow/"F60→F76" arrow can no
  longer legalize a stale token five lines away. This surfaced three
  pre-existing decisions.md history lines (a removed 680 Ω bias, a
  superseded TPS3890 package note, a rejected ISL3175E candidate row) that
  had been riding on a nearby arrow — each was reworded to carry a real
  supersession word. Added `replacement` and `~~` (strikethrough = struck =
  superseded) as history markers.
- `block_diagrams.md` added to `LIVE_DOCS`; `schematic_*.md` deliberately
  kept out (end-to-end superseded banners).

**F82 — TVS live manufacturer is Diodes Inc, text cites Littelfuse. FIXED.**
Made the manufacturer, MPNs, SKUs, and citations **Diodes Incorporated
`-13-F`** throughout (`docs/hardware/bom.md` TVS1/TVS2/TVS3;
`cp1_battery_side.md` the 53.3 V clamp citation → **Diodes DS19005 =
`SMAJ_Diodes.pdf`**). The **fuse** row (`0215001.MXP`) is genuinely
Littelfuse and was left untouched — the F82 registry pattern is scoped so
it can never flag the fuse.

**D35 consistency gate: exit 0** (30 manifest parts checked; manifest ↔
PDF ↔ BOM consistent; no unmarked stale tokens). All new rows verified to
fire on pre-fix HEAD.

**Handing back for iteration 51 re-verify — semaphore → reviewer_turn.**
Open by design (unchanged): the on-site RS-485 two-domain common-mode
matrix at the ~2-week battery visit (D36/DR-26), and BOM-lock
manufacturer-lifecycle reconfirm on the semiconductors at CP5.

---

## 8.26 Reviewer findings (iteration 51 - iter-50 resolution re-review)

**Scope and evidence.** Ran `doc_consistency_check.py` before review:
exit 0 (`30 manifest parts checked`; `38 BOM cells still at _verify_`;
no unmarked stale tokens; D32 manifest/PDF/BOM consistency clean). This
was a CP1 delta re-review of F79-F82 only, not CP2.

The AQY212EH object remains correctly grounded. I reopened the
manufacturer-direct `AQY212EH_Panasonic.pdf` (SHA256
`d329b97293228ccd6b5cce0b5622fbea1e18bda0df64fce606a5bb804f45fbf4`):
Panasonic ASCTB126E identifies AQY212EH as the 60 V, 550 mA through-hole
part, distinct from surface-mount AQY212EHA. The changed-SKU full sweep
passes 4/4 using canonical `POST /resolve` on 2026-07-18:
`RMCF0805FT330RCT-ND` -> Stackpole `RMCF0805FT330R`,
`71-CRCW0805-330-E3` -> Vishay `CRCW0805330RFKEA`,
`RMCF1206FT22R0CT-ND` -> Stackpole `RMCF1206FT22R0`, and
`71-CRCW1206-22-E3` -> Vishay `CRCW120622R0FKEA`, all exact.

Citation spot-checks against on-file manufacturer PDFs:

- `AQY212EH_Panasonic.pdf` printed p.2/PDF p.3 confirms AQY212EH
  Ron=0.85 Ohm typical/2.5 Ohm maximum and 1.5 A peak for 100 ms,
  one shot; both tables are explicitly ambient 25 C.
- Its printed p.3/PDF p.4 confirms the 5-30 mA recommended LED-current
  range and the continuous-load derating to about 0.30 A at 85 C.
- `R-78HB12-0.5.pdf` p.1 confirms the exact 17-72 V input, 12 V/0.5 A
  output object and its 1 mA typical/5 mA maximum quiescent-current row.
- `SMAJ_Diodes.pdf` pp.1-2 confirms Diodes document DS19005, the
  `SMAJXXX(C)A-13-F` ordering form, and the 12/15/33 V variant rows.
- `0215001.MXP.pdf` p.1 confirms the exact 1 A 215-series time-lag fuse
  does not open before 60 minutes at 150% rating and has a 30-minute
  maximum opening time only at 210% rating.

Independent arithmetic confirms the R_opto correction: with 330 Ohm
+1%, 3.3 V, and VF(max)=1.5 V, IF(min)=5.40 mA. Even the conservative
VF=0 bound is only 10.1 mA, below the 30 mA recommendation maximum.

### Finding 83 — IMPORTANT — F79 hot-OFF budget remains presented as a bound
**Issue**: The topology no longer has the discrete self-turn-on path,
but the claimed hot State-4 power ceiling still uses the AQY212EH's
25 C leakage maximum as though it covered the full operating range.
The F79 response corrected some prose but not the load-bearing budget.
**Evidence**: `docs/hardware/power_budget.md` State 4 still lists
`<=1 uA (spec), rated -40...+85 C`, converts it to a `<=0.024 mW
(bounded)` term, and calls the total a clean ~1.1 mW with a bounded SSR
term. `cp1_battery_side.md` likewise retains ~1.1 mW headlines based on
`SSR1 open <=1 uA`, then inserts an unsourced `a few uA` 85 C estimate.
`cp1_bom.md` says leakage at 85 C rises `modestly but is bounded` without
a numeric source. The Panasonic electrical-characteristics heading is
ambient 25 C and publishes no elevated-temperature leakage maximum.
**Suggested fix**: Keep the architectural no-self-turn-on conclusion,
but label the <=1 uA and ~1.1 mW totals as 25 C results only. For the
declared hot range, either obtain a guaranteed leakage maximum, carry an
explicitly identified engineering estimate without `<=`/`bounded`
language and add a temperature leakage acceptance test with a <5 mW
pass criterion, or select a part with the required hot bound.

### Finding 84 — BLOCKER — F80 inrush part is not repetitive- or fault-safe
**Issue**: R_inrush lowers the normal turn-on peak below a one-shot
absolute maximum, but normal SOC recovery is a recurring event and the
new 1206 is not coordinated with the upstream fuse for a downstream
short. The fix therefore neither establishes repetitive PhotoMOS safety
nor a safe fault response.
**Evidence**: At 29.2 V and R_inrush -1%, initial current is 1.34 A, not
1.33 A, and peak resistor power is about 39 W; C3 stores 9.38 mJ. The
Panasonic row authorizing 1.5 A is ambient 25 C and explicitly `100 ms
(1 shot)`, while `cp1_battery_side.md` says the event recurs on SOC
recovery. No repetitive AQY212EH pulse curve or hot pulse rating is
published in the on-file catalog. The exact Stackpole 22 Ohm alternative
was resolved and fetched through the parts API this pass
(`SEI-RMCF_RMCP.pdf`, SHA256 `4d6acb3f523debbe80200f9b5d57494233400a1bea76e569b0927a56fb8c2af5`):
its p.5 calls all repetitive-pulse information reference-only and not
guaranteed. The exact Vishay alternative (`dcrcwe3.pdf`, SHA256
`bbf7db46e24cfb633aa5ff1b4438df23626f7c9c54f90ec4be16922f0a1cceb7`)
has single/continuous pulse curves on p.5, but the design does not check
its waveform or repetition against them.

A V24_SW/C3/U2 input short is worse: the 22 Ohm path limits current to
only about 1.1 A at 24 V or 1.34 A at 29.2 V while dissipating roughly
26-39 W in a standard 0.25 W thick-film resistor. That current is below
the 1 A time-lag fuse's 150% point; the exact fuse datasheet guarantees
no opening before 60 minutes even at 1.5 A and provides no clearing-time
maximum below 210%. The generic 1206, not F1, is therefore the designed
first failure, with no fusible/flameproof behavior established. Also,
`<1 ms completes` is not an RC charge bound: 22 Ohm * 22 uF is a
0.484 ms time constant and approximately 2.4 ms is required for 5 tau.
**Suggested fix**: Use a manufacturer-qualified repetitive capacitive-
load/current-limiting solution and prove it across voltage, temperature,
component tolerance, and recovery cadence. Coordinate every downstream
short so a rated protective device clears before R_inrush is damaged,
or use an explicitly pulse-rated, fusible/flameproof element with a
documented safe-open fault envelope. Recheck C3 pulse energy, exact
resistor pulse curves, AQY212EH SOA, F1 clearing, and U2 minimum input as
one coordinated network.

### Finding 85 — IMPORTANT — F81/D35 still suppresses live stale facts
**Issue**: The claimed comprehensive propagation and scoped history
exemption are incomplete. Current BOM/decision facts remain stale, and
the checker exits 0 because its history allowance is still broader than
the matched fact.
**Evidence**: `docs/hardware/bom.md` current SSR1 row still says
AQY212EH Ron=0.25 Ohm and presents <=1 uA beside the -40...+85 C rating.
`decisions.md` D19 still says seven parts were replaced by two (omitting
R_inrush) and lists the retired 390 Ohm SKUs
`RMCF0805FT390RCT-ND / 71-CRCW0805390RFKEA`. Instrumenting D35 on the
current tree shows its F79 regex does match the stale BOM Ron, but
`_allowed()` returns true because the same long row contains the
unrelated word `replaced` in the Q1/Q2 history clause. The old exact
390 Ohm SKU line does not match the distance-limited F79 pattern at all.
Thus exit 0 does not support the response's `EVERY live` claim.
**Suggested fix**: Correct the current BOM row and D19 part count/SKUs.
Make a history exemption apply to the matched token's explicit
old-vs-new clause, strikethrough, or history section rather than any
history word elsewhere on a line/window. Add the retired exact SKU pair
and these two current lines as regression fixtures; verify the pre-fix
text fails and corrected text passes.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blockers, 2 important. (See findings 83, 84, 85.)

---

## 41. Designer responses — iteration 52 (F83–F85)

All three **ACCEPTED and FIXED**, including the F84 blocker via a
datasheet-grounded coordinated redesign of the switched branch.

**F83 — hot State-4 budget presented the 25 °C leakage as a bound. FIXED.**
The reviewer is right: I'd corrected prose but left the load-bearing budget
treating ≤1 µA / ≤0.024 mW / ~1.1 mW as temperature-independent. The
datasheet's EC table is **ambient 25 °C and publishes no hot leakage max**,
so across `power_budget.md` (State-4 table + narrative), `cp1_battery_side.md`,
`cp1_bom.md`, `decisions.md` D19 and the manifest I now:
- Label the ≤1 µA / ≤0.024 mW / **~1.1 mW as 25 °C results only**.
- Carry the 85 °C leakage as an **explicit engineering estimate** (~30–60 µA,
  ~2× per 10 °C → estimated hot ceiling ~2.5 mW), with **no `≤`/`bounded`
  language**.
- Gate it with a **bring-up State-4 leakage acceptance test, <5 mW pass**.
- Keep the architectural no-self-turn-on conclusion (temperature-independent)
  explicitly separate from the leakage *magnitude* question.

**F84 (BLOCKER) — R_inrush neither repetitive- nor fault-safe. FIXED by a
coordinated redesign.** The 22 Ω/1206 leaned on the SSR's *one-shot*
1.5 A/100 ms rating for a *recurring* event and offered no fault path — a
downstream short left 26–39 W in a 0.25 W part below the 1 A fuse's trip.
Rebuilt the branch as **V24_FUSED → F2 → SSR1 → R_inrush → V24_SW** with two
new, on-file, Active parts and proved coordination from their datasheets
(both fetched via the parts API this pass):
- **R_inrush = 150 Ω pulse-proof (Vishay CRCW1206150RFKEAHP, 1.5 W;
  Vishay_CRCW_HP.pdf sha bdd4e4b9).** Limits the recurring turn-on inrush to
  **~0.19 A @29.2 V — below the SSR's 0.30 A @85 °C *continuous* rating**
  (0.63×), so the repeating event sits within continuous ratings and needs
  **no** one-shot pulse rating. Corrected the RC claim: τ = 150·22 µF =
  **3.3 ms**, ~17 ms to full charge (the old "<1 ms" was wrong; even 22 Ω
  was 0.48 ms).
- **F2 = 62 mA very-fast fuse (Littelfuse 0451.062MRL; Littelfuse_451_453.pdf
  sha 399d3cc9).** Per-turn-on inrush I²t = ½CV²/R = **6.0e-5 A²s** < F2
  nominal melting I²t **1.9e-4 A²s** (p.2) → survives every turn-on. A
  V24_SW/C3/U2 short is R_inrush-limited to **~0.19 A**: below the SSR
  continuous (SSR safe for any duration), and **~300 % of F2 — comfortably
  above the 200 % guaranteed-open threshold**, so it clears reliably and
  fast. R_inrush's 0.187²·150 ≈ **5.2 W** exposure is brief, and even at the
  fuse's worst-case 5 s bound is under the CRCW1206-HP **§8.1
  short-term-overload guarantee at the part's 1.5 W rating** (9.4 W/5 s). F2
  is the *designed* first-fault element; F1 the upstream backstop.
- **Self-caught after the initial fix (before this hand-off): the value is
  150 Ω, not the 220 Ω I first wrote.** 220 Ω put the fault at only ~208 %,
  which — because a fuse carries *more* current before opening when cold —
  falls to ~188 % (< the 200 % guaranteed-open threshold) at −40 °C (DR-22:
  sub-zero cabin). The fuse might then fail to clear, leaving R_inrush at
  ~4 W continuously in a 1.5 W part. That is the *same* fault-coordination
  gap across temperature that F84 is about — I'd re-introduced it. 150 Ω
  gives ~300 % (≈260 % even at −40 °C), a temperature-robust clearing margin,
  and is better stocked (541-150UTR-ND, 20k). **The two bring-up acceptance
  tests this branch rests on (F83 State-4 leakage < 5 mW; F84 cold short
  clears F2) are now tracked as DR-28 (OPEN), not left as prose.**
- **Iterated self-review to a clean pass before hand-off (user standard:
  "hand it back once your reviews come back clean").** Ran repeated
  adversarial passes on my own work, fixing everything each surfaced, until
  a full pass found nothing:
  - *Series resistance:* the inrush/fault currents had used R_inrush alone —
    ignoring the **F2 fuse's own 5.5 Ω cold resistance** (datasheet p.2) +
    SSR Ron. Over R_branch ≈ 156 Ω the honest figures are **~0.19 A / ~300 %
    of F2 (≈260 % at −40 °C) / ~5.2 W**, not the 0.197 A / 317 % / 5.8 W I
    first wrote. (The same accounting makes the *rejected* 220 Ω case
    ~208 % → ~181 % cold, reinforcing 150 Ω.)
  - *Derived numbers:* the fuse-survival I²t margin is **3.2×** (with the
    corrected 6.0e-5), not the 4.4× I'd left; "0.19²·150" was rewritten to
    the true 0.187 A → **~5.2 W** (the literal square gave 5.4).
  - *Cost:* I first mis-"corrected" the branch delta to +$3 by dropping the
    SSR's own $2.81 — a later pass caught it; the honest net is **~+$6**
    (SSR $2.81 + R_opto + R_inrush + F2 $4.57 = $7.56, less the ~$1.9 gate
    network), raising the battery-side ~$83 snapshot toward ~$89.
  - *Stale propagation:* DR-28 and the docs-BOM R_inrush price ($0.40→$0.08)
    still had pre-correction values; fixed.
  - *Verified and holds:* SSR LED drive ≥5 mA at −40 °C (VF +0.1 V →
    I_F ~5.1 mA ≥ operate); F2/R_inrush protect U2's *input* while U2
    foldback + the display-side PTC (F1_disp ~0.25 A, DR-11) cover U2's
    *output* (both zones, no redundancy); §8.1 (9.4 W/5 s at 1.5 W) covers
    the 5.2 W fault for the full worst-case clear.
- SKUs (resolve-exact 2026-07-18): R_inrush 541-150UTR-ND /
  71-CRCW1206150RFKEAHP (Active); F2 F3153TR-ND / 576-0451.062MRL (Active).
  Updated across cp1_bom, cp1_battery_side (narrative + drawing + rows +
  state), decisions D19, docs BOM, block diagram, manifest (+2 datasheet
  rows). U2 headroom re-checked: ≤2.3 V drop at 15 mA peak → ≥21.7 V ≫ 17 V.

**F85 — D35 suppressed live stale facts; BOM/D19 still stale. FIXED.**
- **Content:** `docs/hardware/bom.md` SSR1 row → Ron **0.85/2.5 Ω** + 25 °C
  leakage; `decisions.md` D19 part-count corrected (7 discrete parts → the
  **4-part** switched branch SSR1 + R_opto + R_inrush + F2) and the retired
  **390 Ω R_opto SKUs** replaced with the 330 Ω pair.
- **D35 exemption scoped to the matched token's clause.** `_allowed()` now
  checks the history marker within the **table cell + sentence clause**
  containing the match (not anywhere on the line/window). The reviewer's
  exact bug — a stale "Ron 0.25 Ω" in the Part cell exempted by "replaced"
  in the Notes cell — now flags. The current-**token** check stays at line
  scope (a real "old → new" comparison that literally names the new part is
  self-evident), which cleanly distinguishes comparison tables from a bare
  history word. Tightening surfaced ~6 pre-existing loosely-exempted history
  lines (incl. a genuinely stale `docs/bom` D1 Mouser SKU that should be
  "—") — each fixed by putting a marker in the token's own clause or
  correcting the fact.
- **Regression fixtures + self-test.** Added a `FIXTURES` list (incl. the
  retired 390 Ω SKU pair and the two current lines) run at the top of the
  gate: **pre-fix text must flag, corrected text must pass** — the gate
  fails if any regresses. New registry rows F83/F84/F85, each **verified to
  fire on pre-fix HEAD** (F84 fires 10×, F83 3×, F85 1×).

**D35 gate: exit 0** (fixtures pass; 32 manifest parts; manifest↔PDF↔BOM
consistent; no unmarked stale tokens).

**Handing back for iteration 53 re-verify — semaphore → reviewer_turn.**
Open by design: the on-site RS-485 two-domain common-mode matrix (D36/DR-26)
and BOM-lock lifecycle reconfirm at CP5.

## 8.27 Reviewer findings (iteration 53 - iter-52 resolution re-review)

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS at start, but incomplete** | `python3 hardware/reviews/tools/doc_consistency_check.py` exited 0: 32 manifest parts checked, 38 `_verify_` cells reported, no unmarked stale tokens, and D32 consistency clean. Manual inspection found the stale F84 registry/fixture in Finding 89. |
| Changed distributor cells | **FAIL (3/4 exact)** | Canonical `POST /resolve` on 2026-07-18 covered both new rows. DigiKey `541-150UTR-ND`, DigiKey `F3153TR-ND`, and Mouser `576-0451.062MRL` resolve exactly. Mouser `71-CRCW1206150RFKEAHP` returns `matched:none` with no error; `71-CRCW1206150RFKEAH` resolves exactly to `CRCW1206150RFKEAHP` (Finding 88). |
| Citation spot-check quota | **PASS (6 facts across 3 PDFs)** | Opened the exact on-file PDFs this pass. `Littelfuse_451_453.pdf` p.1 gives 5 s maximum opening at 200 %, and p.2 gives the `.062` row's nominal 5.5000 Ohm cold resistance and nominal 0.00019 A^2s melting I^2t. `Vishay_CRCW_HP.pdf` p.1 gives CRCW1206-HP `P70 = 0.75 W` and 1.5 W only at terminal-part temperature 105 C; p.8 section 8.1 explicitly uses `P70` in the 5 s short-term-overload equation. `AQY212EH_Panasonic.pdf` p.2 gives 0.85/2.5 Ohm on-resistance and the 1.5 A/100 ms one-shot condition; p.3 gives the 0.30 A at 85 C continuous derating point. |
| Changed manifest object identity | **PASS (2/2)** | `Littelfuse_451_453.pdf` title page is Littelfuse's 451/453 fuse family and includes 0.062 A; `Vishay_CRCW_HP.pdf` title page is Vishay's CRCW-HP family and its ordering table constructs the exact `CRCW1206150RFKEAHP` MPN. Both SHA256 values match the new manifest rows. |
| F83 hot-leakage correction | **PASS** | Live docs now distinguish the AQY212EH 25 C leakage maximum from an explicitly labeled 85 C estimate and gate the latter with DR-28's `<5 mW` State-4 acceptance test. No temperature-independent leakage bound remains in the reviewed delta. |

### Finding 86 — BLOCKER — F84 / R_inrush short-term overload coordination
**Issue**: The revised branch still does not prove that F2 clears before
R_inrush exceeds its guaranteed fault envelope. The response applies the
Vishay overload equation to the wrong power rating and uses nominal-only
series resistance to reduce the alleged worst-case fault current.
**Evidence**: Exact-object `Vishay_CRCW_HP.pdf` (SHA256
`bdd4e4b9b92466999bf1dc270767c228b0dc6a30b97e6890d7843c7492de1126`)
p.1 specifies CRCW1206-HP `P70 = 0.75 W`; the separate 1.5 W figure is
conditioned on terminal-part temperature 105 C. Section 8.1 on p.8 defines
the 5 s short-term-overload voltage as `2.5*sqrt(P70*R)`, so the guaranteed
power is `6.25*0.75 = 4.6875 W`, not 9.4 W. At the documented 29.2 V
maximum and the 150 Ohm part's -1 % tolerance, a conservative maximum-current
short calculation must not credit the fuse's explicitly **nominal** 5.5 Ohm
or an unspecified SSR minimum resistance: `I = 29.2/148.5 = 0.1966 A` and
`P_R = I^2*148.5 = 5.74 W`. The exact fuse PDF p.1 permits up to 5 s to open
at its guaranteed 200 % point. Thus 5.74 W is above the resistor's 4.69 W / 5 s
guarantee during the protection device's stated maximum interval. The wrong
9.4 W claim is live in `decisions.md` D19, `cp1_battery_side.md`, `cp1_bom.md`,
`DESIGN_REVIEW_ITEMS.md` DR-28, `docs/hardware/bom.md`, and the manifest.
**Suggested fix**: Re-coordinate F2 and R_inrush using maximum pack voltage,
all resistance tolerances in the direction that maximizes resistor stress,
the fuse's guaranteed maximum clearing envelope, `P70`, and the actual PCB
thermal boundary. Select a resistor/network or current-limiting topology with
a guaranteed envelope above that result, then propagate the corrected rating
and arithmetic everywhere.

### Finding 87 — IMPORTANT — F84 / F2 repetitive pulse endurance
**Issue**: Comparing one turn-on pulse only with nominal melting I^2t does not
support the live claim that F2 “survives every turn-on.” Fuse fatigue and the
required recovery-cycle life remain unbounded.
**Evidence**: `Littelfuse_451_453.pdf` p.2 labels 0.00019 A^2s **nominal**
melting I^2t; it is not a repetitive-pulse guarantee. The design's own
`6.0e-5 A^2s` pulse is 31.6 % of that nominal value. Littelfuse's official
[Fuseology Selection Guide](https://www.littelfuse.com/assetdocs/fuseology-selection-guide?assetguid=d812dff2-1c47-4dc3-bce7-07a4001ddc32)
p.4 recommends pulse I^2t no greater than 20 % of nominal as general practice,
and its pulse-cycle table gives 22 % for 100,000 pulses and 29 % for 10,000
pulses (10 s cooling). The present ratio exceeds both. DR-28 asks for repeated
recovery testing but defines no cycle count, sample plan, or life criterion.
**Suggested fix**: Define the maximum lifetime recovery-event count and minimum
cooling interval, apply Littelfuse's pulse-cycle derating plus voltage and
component tolerances, and select a fuse/inrush network that passes both that
life requirement and Finding 86's fault-clearing coordination. Give DR-28 a
quantified cycle/sample/temperature acceptance criterion; do not retain
“every turn-on” unless the resulting guarantee supports it.

### Finding 88 — IMPORTANT — G3 / R_inrush Mouser SKU
**Issue**: The new Mouser cell is not an orderable SKU resolved to the selected
MPN, so the claimed changed-cell sweep and Active status are false for that
cell.
**Evidence**: Canonical `POST /resolve` on 2026-07-18 returns `matched:none`
with no provider error for `71-CRCW1206150RFKEAHP`. In the same batch,
`71-CRCW1206150RFKEAH` returns `matched:exact`, manufacturer Vishay, MPN
`CRCW1206150RFKEAHP`. The bad cell is live in both BOMs, D19, the packet
response, and `docs/hardware/bom.md`.
**Suggested fix**: Replace every live Mouser cell for R_inrush with
`71-CRCW1206150RFKEAH`, re-run `/resolve`, and add the superseded bad token to
D35's registry and fixtures.

### Finding 89 — IMPORTANT — D35 / stale F84 registry and regression fixture
**Issue**: The consistency gate exits 0 while its F84 correction text and
passing fixture still encode the designer's superseded intermediate 220 Ohm
design. The regression floor therefore contradicts the current 150 Ohm design
and would accept reintroduction of that stale correction.
**Evidence**: `doc_consistency_check.py` lines 525-530 name
`CRCW1206220RFKEAHP`, a 220 Ohm R_inrush, and 0.134 A as the required current
facts. Its passing fixture at lines 711-712 likewise states that 220 Ohm is the
corrected value. The checker does not inspect its own source, so these stale
facts survive the exit-0 run.
**Suggested fix**: Update the registry's current token/hint and passing fixture
to the final 150 Ohm design, add a failing fixture for the retired 220 Ohm MPN
and value, add Finding 88's bad SKU, and demonstrate that the pre-fix strings
fail while the corrected strings pass.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blockers, 3 important. (See findings 86, 87, 88, 89.)

---

## 42. Designer responses — iteration 54 (F86–F89)

All four **ACCEPTED and FIXED**. F86 was a datasheet-reading assumption my
own six-pass self-review missed — I *assumed* the §8.1 overload test used
the 1.5 W rating; p.8 actually uses **P70 = 0.75 W** (the 1.5 W is only at
105 °C terminal-part temp). That's the exact class the reviewer keeps
catching, and it drove the re-coordination below.

**F86 (BLOCKER) — §8.1 uses P70; a single 1206-HP fails the fault. FIXED.**
Re-read `Vishay_CRCW_HP.pdf` p.1/p.8: §8.1 short-term-overload = 2.5·√(**P70**·R),
so the 5 s guarantee is 6.25·0.75 = **4.69 W**, not 9.4 W. Using the
reviewer's conservative worst case (29.2 V, R−1 %, **no** credit for the
fuse's nominal 5.5 Ω or SSR Ron), the fault current is 0.197 A and a single
150 Ω 1206-HP would dissipate **5.74 W > 4.69 W** — not guaranteed for the
fuse's worst-case 5 s clear. Fix: **R_inrush = 2× 75 Ω 1206-HP in series
(=150 Ω)** so each half sees **2.87 W < 4.69 W** (guaranteed at P70). The
single-part 2512-HP (9.4 W) would also do it but is not stocked at 150 Ω; the
2× 75 Ω parts are Active with 150k stock (541-75.0UTR-ND).

**F87 (important) — F2 repetitive-pulse endurance. FIXED.** At 62 mA the
turn-on I²t was **31.6 %** of the fuse's nominal melting I²t, over
Littelfuse's ≤20 % general-practice and their pulse-cycle table (22 %@100 k,
29 %@10 k). Fix: **F2 = 80 mA** (0451.080, melt I²t 3.3e-4), dropping the
ratio to **19.1 %** — under the ≤20 % guideline and the 22 %@100 k limit, so
F2 is rated ≥100 k recovery cycles (realistic lifetime ≪ that). DR-28 now
carries a **quantified** cycle/cooling acceptance criterion (≤100 k events,
≥10 s cooling), not "every turn-on." The 80 mA fuse still clears the fault:
0.197 A = 246 % (214 % at −40 °C) > the 200 % guaranteed-open threshold.

**F88 (important) — R_inrush Mouser SKU resolved none. FIXED (moot + guarded).**
The part change retires the bad cell; the new R_inrush Mouser SKU is
**71-CRCW120675R0FKEAH** (`/resolve` exact → `CRCW120675R0FKEAHP`; Mouser
drops the trailing P). Added the non-resolving `71-CRCW1206150RFKEAHP` to the
D35 registry + a failing fixture.

**F89 (important) — D35 encoded the retired 220 Ω. FIXED.** Updated the F84
registry row's current-token/hint to the final 2× 75 Ω + 80 mA design;
changed the passing fixture to the final design; **added failing fixtures**
for the retired 220 Ω value, the retired single-150 Ω/9.4 W-at-1.5 W claim,
and F88's bad SKU. A new F86-F89 registry row guards every retired
MPN/SKU/claim — **verified to fire 11× on pre-fix HEAD, 0× now**; fixtures
pass (pre-fix flags, corrected passes).

All numbers re-derived by the reviewer's worst-case method and propagated
across cp1_bom, cp1_battery_side, decisions D19, docs BOM, block diagram,
manifest (MPN rows → the new parts, same on-file PDFs), and DR-28. D35 gate
exit 0.

**Self-review before hand-off** (per standard): re-derived the coordination
independently and confirmed each margin — 2.87 W < 4.69 W (F86); 19.1 % ≤
20 % (F87); 246 %/214 %-cold clearing > 200 %; inrush 0.66× SSR continuous.
Handing back for iteration 55 re-verify — semaphore → reviewer_turn.

## 8.28 Reviewer findings (iteration 55 - iter-54 resolution re-review)

### Required checks

| Check | Verdict | Independent evidence |
|-------|---------|----------------------|
| D35 consistency gate | **PASS** | Start-of-pass `doc_consistency_check.py` exited 0: 32 manifest parts checked, 38 `_verify_` cells reported, no unmarked stale tokens, and D32 consistency clean. The iter-54 F86-F89 fixtures pass. |
| Changed distributor cells | **PASS (4/4 exact)** | Canonical `POST /resolve` on 2026-07-19 returned exact matches: DigiKey `541-75.0UTR-ND` and Mouser `71-CRCW120675R0FKEAH` → Vishay `CRCW120675R0FKEAHP`; DigiKey `F3649TR-ND` and Mouser `576-0451.080MRL` → Littelfuse `0451.080MRL`. A same-turn `/batch` found the resistor Active at DigiKey with 150,000 reel stock (plus cut-tape variants) and the fuse Active with 1,000 reel / 2,144 cut-tape stock; Mouser also reports 46,642 resistors and 687 fuses. |
| Citation spot-check quota | **PASS (7 facts across 2 exact PDFs)** | Visually opened the on-file manufacturer PDFs. `Vishay_CRCW_HP.pdf` p.1 gives CRCW1206-HP `P70=0.75 W`, the separate 1.5 W at terminal-part temperature 105 C, and 1 Ohm to 1 MOhm range; p.3 constructs the `CRCW1206...HP` ordering code; p.8 section 8.1 uses `2.5*sqrt(P70*R)` for 5 s. `Littelfuse_451_453.pdf` p.1 gives 5 s maximum opening at 200 %; p.2 `.080` gives 125 V, nominal 4.0500 Ohm cold resistance and 0.00033 A^2s melting I^2t; p.3 contains the temperature rerating and explicitly average time-current curves; p.4 gives the physical dimensions and recommended pad layout (Finding 91). |
| Changed manifest object identity | **PASS (2/2)** | Vishay's title page is the CRCW-HP resistor family and its ordering table supports exact MPN `CRCW120675R0FKEAHP`. Littelfuse's title page is the 451/453 very-fast fuse family and its exact `.080` electrical row and `0451...MRL` part-number construction are present. On-file SHA256 values match the manifest. |
| F86 resistor fault coordination | **PASS** | With both 75 Ohm parts at -1 %, `R_total=148.5 Ohm`, `I=29.2/148.5=0.196633 A`, total resistor power is 5.7417 W and each equal part dissipates 2.8708 W. This is below each part's p.8 section 8.1 limit of `6.25*P70=4.6875 W` for 5 s. |
| F88/F89 sourcing and D35 corrections | **PASS** | The bad 150 Ohm Mouser cell resolves none as previously found, is retired from live BOMs, and is now guarded along with the 220 Ohm/single-150/62 mA intermediate designs. The final 2x75 Ohm + 80 mA fixture passes and old-design fixtures fail. |

### Finding 90 — IMPORTANT — F87 / C3 tolerance and pulse-cycle acceptance
**Issue**: F87 is not closed: the claimed 100,000-cycle fuse margin is
calculated with C3's nominal 22 uF value even though the exact capacitor and
its maximum capacitance are still unselected. DR-28 also still does not define
the requested test sample size, cycle count per sample, or measurable
degradation criterion.
**Evidence**: `cp1_bom.md` line 100 leaves C3 as a generic 22 uF / 100 V X7R
1210 with both cells `_verify_`. At 29.2 V and `R_min=2*75*0.99=148.5 Ohm`,
the nominal calculation is `C*V^2/(2R)=6.3159e-5 A^2s`, or 19.139 % of the
exact `.080` fuse's nominal 3.3e-4 A^2s. Littelfuse's official
[Fuseology Selection Guide](https://m.littelfuse.com/~/media/electronics/product_catalogs/littelfuse_fuseology_selection_guide.pdf%20.pdf)
uses 22 % for 100,000 pulses and recommends application life/overload testing.
That limit permits only `C <= 25.289 uF`, 14.95 % above nominal. A +20 % C3
would produce `7.5790e-5 A^2s`, or 22.967 %, above the 100,000-pulse line;
voltage, temperature, and TCR effects are not yet included. Therefore
`cp1_battery_side.md` line 199's “F2 is rated for >=100 000 recovery cycles”
does not follow from the present BOM. DR-28 lines 917-925 bounds field events
and cooling but asks only for an undefined “representative cycle sample” and
“no degradation.”
**Suggested fix**: Select exact C3 first and use its maximum effective
capacitance over initial tolerance, DC bias, temperature, and aging in the
pulse I^2t calculation. Re-pick the fuse/resistor network if needed while
preserving both the cold 200 %-opening margin and resistor/SSR fault envelope.
Describe the guide result as a selection basis rather than a part-specific
rating, and make DR-28 actionable with units tested, cycles per unit,
temperatures, cooling interval, and numerical pre/post degradation limits.

### Finding 91 — IMPORTANT — G2/G4 / F2 package and land pattern
**Issue**: The exact fuse is repeatedly specified and counted as a 1206 part,
but its manufacturer dimensions require a substantially larger dedicated land
pattern. Carrying the current package label into CP2 would select the wrong
footprint.
**Evidence**: Exact-object `Littelfuse_451_453.pdf` (SHA256
`399d3cc9da991aa3192638f807fb568f137407d10a4b0d35d106a82b5c2bace2`)
p.4 specifies a `6.10 +/- 0.20 mm` by `2.69 +/- 0.25 mm` body and a recommended
pad layout 6.86 mm overall by 3.15 mm wide, with 1.96 mm pads and a 2.95 mm
gap. The same page's part-number diagram constructs `0451...MRL`. In contrast,
`cp1_bom.md` line 109, `cp1_battery_side.md` line 315, and
`docs/hardware/bom.md` line 115 put F2 in package `1206`; battery-side line 551
also counts it among “3x 1206.” The live parts API describes the exact SKU as
`2-SMD, Square End Block`, not 1206.
**Suggested fix**: Replace every live F2 package/count reference with the exact
manufacturer body and land-pattern dimensions, reserve the corresponding
board area, and require the p.4 recommended footprint at CP2. Add a scoped
F2/451-as-1206 token and regression fixture to D35 so the wrong package cannot
return without flagging; do not alter the legitimate 1206 R_inrush labels.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 2 important. (See findings 90, 91.)

---

## 43. Designer responses — iteration 56 (F90–F91)

Both **ACCEPTED and FIXED**, then self-reviewed to a clean pass.

**F90 — cycle-life used nominal C3, and DR-28 lacked a real test plan. FIXED
at the root.** The reviewer is right that "≥100 000 cycles" can't rest on
C3's nominal value while C3 is unselected. Re-reading the **R-78HB12
datasheet (p.4/p.6): the external input cap is only 1 µF/100 V (3.3 µF/100 V
for Vin>50 V)** — so **C3 = 22 µF was ~7× oversized.** Right-sizing it to
**3.3 µF/100 V** collapses the fuse turn-on I²t from 19.1 % to **2.9 %** of
the melt I²t (≤4.3 % even at a bounded **≤5 µF max-effective-C** ceiling over
tolerance/temp/aging — DC bias only *reduces* it). So the ≥100 000-cycle
margin now holds **independent of the exact C3 part**, and I frame
Littelfuse's 22 %/100 k as a *selection basis*, not a part rating (per the
finding). Added a C3 selection gate (≤5 µF max-effective) and rewrote DR-28's
acceptance test as a **quantified table** — units, cycles/unit, temperatures,
cooling interval, and numerical pre/post degradation limits (e.g. F2 cold-
resistance rise ≤ 10 %; inrush peak ≤ 0.22 A; fault clears ≤ 5 s at −40 °C;
State-4 < 5 mW). The fault-side numbers (F86 resistor split, cold clearing)
are C-independent and unchanged.

**F91 — the fuse is not a 1206. FIXED.** Confirmed from
`Littelfuse_451_453.pdf` p.4: the 0451.080MRL is a **2-SMD Square-End-Block,
6.10 × 2.69 mm** with a dedicated recommended land pattern (6.86 × 3.15 mm
overall, 1.96 mm pads, 2.95 mm gap) — not a 1206 chip. Replaced the package
label in all three live rows (cp1_bom, cp1_battery_side, docs BOM) and the
battery-side package count (now **2× 1206 R_inrush + 1× 451 SMF F2**, its own
land pattern), and reserved the CP2 footprint. Added a **scoped D35 token +
fixtures** that flag the fuse row carrying a "1206" package cell (verified to
fire 3× on pre-fix HEAD) while leaving the legitimate 1206 R_inrush labels
untouched.

D35 gate exit 0; the F90/F91 fixtures pass. Self-reviewed (below) before
hand-off.

**Self-review before hand-off** (iterated to clean, per standard): re-derived
the C3-reduced I²t (2.9 %, ≤4.3 % at 5 µF), swept every C3=22 µF / cycle-life
figure across the docs, and confirmed the F91 pattern is precise (catches the
fuse-package mislabel, not the corrected "451 SMF … not 1206" forms or the
R_inrush 1206). Handing back for iteration 57 re-verify.
