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

**Verified parts (web-checked 2026-06-17; final availability at BOM-lock
per D-OPEN-6):**
- **U1 LM5165DRCR** — 3–65 V in, **10.5 µA Iq**, 150 mA, fixed 3.3 V (FB→VOUT). Both surge-tolerant and µA-Iq (a brick can't be both).
- **U2 R-78HB12-0.5** — 17–72 V in, 12 V/0.5 A.
- **Q1 ZXMP6A13F** — −60 V, 1.1 A, SOT-23 (clean 3-pin; the ZXMP6A17 is only SOT-23-6/SOT-223).
- **D1 SS26** (60 V), **Q2 2N7002** (60 V), **DZ1 BZX84C12** (12 V Zener) — jellybeans.

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

The original CP1 baseline content follows unchanged below (its power-tree
specifics are superseded by §0/D19 where they conflict).

---

## 1. What this CP delivers

A complete, self-contained design specification for both boards, with
every part, every net, every design rule, every open question
explicitly called out. From here, CP2 (schematic capture) is supposed
to be **mechanical translation** — no new design decisions.

Files added in this CP:
- [`../layout/decisions.md`](../layout/decisions.md) — every committed
  decision and rationale; the source of truth for "what did we agree to"
- [`../layout/cp1_battery_side.md`](../layout/cp1_battery_side.md) —
  battery-side board baseline
- [`../layout/cp1_display_side.md`](../layout/cp1_display_side.md) —
  display-side board baseline
- [`../layout/cp1_bom.md`](../layout/cp1_bom.md) — consolidated BOM with
  vendor SKUs and Δ vs prior pass

Plus the supporting scaffolding from the previous commit:
[`hardware/layout/README.md`](../layout/README.md) (process index),
[`hardware/reviews/README.md`](README.md) (this folder's README),
and KiCad project subdirectories.

## 2. What changed since the original `docs/hardware/` spec

The prior pass produced engineering-spec markdown plus SKiDL Python
that targets KiCad 8. CP1 takes that as input and makes the **set of
small refinements** below before committing to KiCad capture. Each one
is justified in the relevant doc with a Δ annotation.

### Material design changes

1. **Display-side enclosure** moved from single-gang plate → US
   double-gang plastic old-work box with 3D-printed faceplate.
   ([cp1_display_side.md §2](../layout/cp1_display_side.md#2-mechanical-envelope))
2. **24 V sense divider** raised from 100 kΩ/11 kΩ to 1 MΩ/110 kΩ
   (always-on idle current dropped 220 µA → 22 µA).
3. **Q1 gate pull-up** raised from 10 kΩ to 100 kΩ (idle current dropped
   2.4 mA → 240 µA).
4. **Button pull-ups** (3× on display, 1× on battery) raised from 10 kΩ
   to 1 MΩ (idle Iq nearly zero per button).
5. **Power input on battery side** changed from external ring lugs +
   ATO fuse to on-board Phoenix MSTB terminal block + 5×20 mm cartridge
   fuse. Cleaner enclosure, still field-serviceable.
6. **Display-side button function** moved from hardcoded (refresh /
   next / release-BLE) to software-defined, with on-screen labels
   adjacent to each button.
7. **Debug LEDs (LED1, R_led)** removed on both boards. Power-first.
8. **TVS numbering** reconciled across schematic doc + SKiDL +
   block diagram (they disagreed).
9. **24 V TVS** added (TVS1 SMAJ30CA on V24_FUSED). Wasn't in the
   original schematic doc; SKiDL had it under a different number.
10. **Battery-side enclosure** changed from Hammond 1556B2GY to 1591ATBU
    (smaller, easier to stock, fits the 60×40 mm board).
11. **Dev/debug headers** added on both boards (UART debug, USB-OTG
    breakout, RS-485 term-lift jumper).

### Soft changes (clarifications, not new decisions)

- E-paper choice locked in: 4.2" tri-color BWR with mixed-mode refresh
  (B&W partial ~500–700 ms for button UI, color full ~7 s for
  scheduled ticks). See [decisions.md D6](../layout/decisions.md#d6).
- Refresh policy: button presses get partial refresh; color refresh
  happens on the next scheduled background tick (30–60 s) or on a
  state-change alert.
- Source of truth = KiCad 10 native files (.kicad_pro / .kicad_sch /
  .kicad_pcb). Existing SKiDL preserved as design-intent reference but
  not regenerated from.
- Fab = JLCPCB, 2-layer FR-4, qty 5 of each board (their minimum),
  bare PCB (no PCBA — economics don't make sense at qty 1).
- Assembly = hand-solder.

## 3. What to look at first

If you have 15 minutes:
1. [decisions.md](../layout/decisions.md) — 10-minute read; gives the
   committed shape of every decision.
2. [cp1_battery_side.md §5 (net list)](../layout/cp1_battery_side.md#5-net-list)
   — sanity check the net topology.
3. [cp1_battery_side.md §13 (open decisions)](../layout/cp1_battery_side.md#13-open-decisions-for-reviewer)
   and [cp1_display_side.md §12](../layout/cp1_display_side.md#12-open-decisions-for-reviewer)
   — the things I want your input on before we proceed.

If you have an hour: read all three CP1 docs end-to-end. Pay particular
attention to:
- Pin assignments — anything I assigned that should be a different GPIO
  for hidden ESP32-S3 reasons (boot straps, ADC2 conflict with WiFi,
  etc.)
- Power-state arithmetic — does the budget per state hold up under
  realistic loads?
- BOM SKU availability — JLC stock, DigiKey availability for the parts
  marked "unchanged" (some may have ROHS/EOL flags since the original
  doc was written)

## 4. Open decisions awaiting input

Repeated here for convenience. Defaults are what I'll use if the
reviewer doesn't override.

### Battery-side

| ID | Question | Default |
|----|----------|---------|
| D-OPEN-1 | ESP32-S3-WROOM-1-N16R8 vs -N8 (no PSRAM)? | N16R8 |
| D-OPEN-2 | SN65HVD3082E vs lower-Iq alternative (ISL3175E)? | SN65HVD3082E |
| D-OPEN-3 | Internal ESP32 ADC vs external supervisor IC (TPS3839) for ULP voltage monitoring? | Internal ADC |
| ~~D-OPEN-5~~ | ~~Hard-cut topology~~ — **RESOLVED post-Codex Finding 01**: original P-FET in 24 V path | — |
| D-OPEN-6 | Q1 gate pull-up value — 10 kΩ vs 100 kΩ vs 1 MΩ? | 100 kΩ |
| D-OPEN-7a | Deep-sleep V12 policy — keep V12 alive in State 3? | Yes (display shows LOW PACK) |
| D-OPEN-7b | Hard-cut V12 policy — kill V12 in State 4? | Yes (forced OFF; required by ≤5 mW budget) |
| D-OPEN-13 | Panel-mount switch BTN1 sealing — IP67 cap or open? | Open (in-box, no water concern) |

### Display-side

| ID | Question | Default |
|----|----------|---------|
| D-OPEN-1 | Same N16R8 vs N8 question | N16R8 |
| D-OPEN-8 | Populate R3/R4 idle-bias on display side? | No (footprints provided) |
| D-OPEN-9 | RS-485 receiver power-gate (N-FET on U2 VCC)? | No (defer to v2) |
| D-OPEN-10 | Button hardware-debounce RC values? | 100 ms (1 MΩ + 100 nF) |
| D-OPEN-11 | Panel mount location — PCB, bracket, or faceplate? | On bracket |
| D-OPEN-12 | Faceplate dimensions — 115 × 117 mm or other? | 115 × 117 |
| D-OPEN-14 | JLCPCB PCBA option — defer to v2? | Defer |

## 5. Known unknowns / things I cannot verify without you

- **JLCPCB stock** of certain parts (Recom R-78 modules, DS3231SN#) at
  order time. CP1 lists DigiKey + Mouser SKUs; JLC order will be
  bare-PCB only so JLC-specific stock isn't blocking, but I flagged it.
- **Waveshare 4.2" e-Paper (B) v2 panel FFC pinout** — the SKiDL had a
  placeholder mapping. CP1 commits to verifying against the panel
  datasheet at CP2 before any KiCad capture; flagging here so the
  reviewer knows there's an unresolved detail downstream.
- **3D-printed bracket and faceplate dimensions** — user-designed. CP1
  commits to providing a PCB STEP file at CP5; the design is the user's
  responsibility.
- **Cat5e in-wall run condition** — assumed shielded per
  [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md); unshielded
  also works (per that doc), but the shield-bonding scheme in CP1
  assumes shielded.

## 6. Success criteria

This checkpoint passes when:

- [ ] Every decision in [decisions.md](../layout/decisions.md) is either
      approved or explicitly redirected
- [ ] Every D-OPEN-N item is resolved (use the default, override it, or
      acknowledge it's not yet decided and flag for resolution at a
      later CP)
- [ ] BOM has no flagged stock-unavailable items
- [ ] No new design questions surface from a careful read of the three
      CP1 docs
- [ ] Reviewer signs off on the section "What changed since the original
      `docs/hardware/` spec" as a complete + correct enumeration of
      deltas

If any of those fail, fix in this CP before opening CP2.

## 7. What this CP does NOT settle

- The actual KiCad schematic capture (CP2 work)
- Net-by-net verification in the symbol library (CP2)
- Footprint selection / placement (CP3)
- Routing decisions (CP4)
- Fab-rendering details (CP5)

## 8. Reviewer findings (append-only)

*(reviewer: append findings below, with timestamps. Each finding either
gets a `RESOLVED` entry from me, or escalates to a decision change in
decisions.md.)*

---

### Finding 01 — BLOCKER — `cp1_battery_side.md`:§3/§5/§8/§13 + `cp1_display_side.md`:§7
**Timestamp**: 2026-05-23 16:48 PDT
**Issue**: The hard-cut architecture is internally inconsistent across CP1 docs, so CP2 cannot be a "mechanical translation." The docs simultaneously describe (a) a 24 V high-side P-FET switch, (b) EN-pin shutdown topology, and (c) a policy to keep 12 V alive through deep-sleep/hard-cut.
**Evidence**: `cp1_battery_side.md` §3 shows Q1/Q2 as a load switch feeding downstream rails; §5 then adds a "REVISED" EN-pin approach; §8 describes EN-pin control details; §13 defaults D-OPEN-5 to original P-FET and D-OPEN-7 to "No" (do not kill 12 V in deep-sleep/hard-cut). `cp1_display_side.md` §7 assumes hard-cut means "no V12 from battery side."
**Suggested fix**: Pick one topology and one state policy, then normalize §3/§5/§7/§8/§13 across both board docs and the power budget. Explicitly split deep-sleep vs hard-cut behavior for the 12 V rail so State 4 semantics are unambiguous.

### Finding 02 — IMPORTANT — `cp1_battery_side.md`:§12
**Timestamp**: 2026-05-23 16:48 PDT
**Issue**: The design-rule table still lists a default signal clearance of 0.15 mm, which is below the stated JLC minimum of 0.152 mm, while the note says CP1 already adjusted it to 0.2 mm. This contradiction risks carrying the wrong DRC constraints into CP2.
**Evidence**: `cp1_battery_side.md` §12 table row "Min trace clearance" shows "Our spec 0.15 mm" and margin "-1 %", followed immediately by text stating "CP1 adjusts to 0.2 mm for safety margin."
**Suggested fix**: Update the rule table and any derived net-class text to a single committed clearance (recommended 0.20 mm), and remove stale 0.15 mm references.

### Finding 03 — IMPORTANT — `cp1_bom.md`:vendor SKU columns
**Timestamp**: 2026-05-23 16:48 PDT
**Issue**: Multiple DigiKey SKUs appear stale or inconsistent with currently listed orderable entries, creating procurement risk for CP5.
**Evidence**: Spot checks on 2026-05-23 show mismatches/alias drift versus BOM lines: DigiKey lists `FH12-24S-0.5SH(55)` under `HFJ124CT-ND` (7,533 in stock), DS3231 commonly under `DS3231SN#T&RCT-ND` (6,609 in stock via Findchips/DigiKey feed), and SN65HVD3082EDR appears under `296-31719-1-ND` (11,546 in stock via Findchips/DigiKey feed), while CP1 BOM uses older/alternate codes.
**Suggested fix**: Refresh CP1 BOM to currently orderable DigiKey/Mouser SKUs (or explicitly mark accepted alternates), and stamp each checked line with date + observed stock count.

### Finding 04 — QUESTION — `cp1_battery_side.md`:§4.4
**Timestamp**: 2026-05-23 16:48 PDT
**Issue**: The 1 MOhm / 110 kOhm always-on divider is good for quiescent current, but the accuracy rationale needs stronger backing before capture because the doc currently justifies it via static input impedance.
**Evidence**: `cp1_battery_side.md` §4.4 claims "<1% ratio error" from ESP ADC loading using a "~10 MOhm input impedance" argument. Espressif hardware guidance focuses on ADC filtering/calibration and recommends a 0.1 uF capacitor on ADC inputs; it does not provide a blanket high-source-impedance accuracy guarantee for this use case ([ESP32-S3 Hardware Design Guidelines, ADC section](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html)).
**Suggested fix**: Add a CP2 validation item with measured ADC error vs DMM across the full pack-voltage range and chosen sampling timing. If error is high, lower divider impedance or add a buffer/sampling strategy.

### Finding 05 — IMPORTANT — `cp1_battery_side.md`:§13 + `cp1_display_side.md`:§7 + `docs/hardware/power_budget.md`
**Timestamp**: 2026-05-23 16:48 PDT
**Issue**: D-OPEN-7 default ("do not kill 12 V in deep-sleep/hard-cut") conflicts with the documented hard-cut power target and display-side assumption that hard-cut removes V12.
**Evidence**: `cp1_battery_side.md` §13 sets D-OPEN-7 default to "No"; `cp1_display_side.md` §7 State C says board is off because no V12 in hard-cut; `docs/hardware/power_budget.md` defines State 4 as ~5 mW pack draw. Keeping 12 V alive in hard-cut would violate that State 4 budget by roughly an order of magnitude.
**Suggested fix**: Split D-OPEN-7 into two decisions: (1) deep-sleep V12 policy and (2) hard-cut V12 policy. Recommend forcing V12 OFF in hard-cut to preserve the battery-protection objective.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blockers, 3 important. (See findings N1, N2, ...)

---

## 9. Claude's responses (iteration 2 — 2026-05-23)

### RESOLVED — Finding 01 (BLOCKER)
**Fix**: Hard-cut topology normalized to **original P-FET** across all sections.
- `cp1_battery_side.md` §3 diagram: corrected stale `R1/R2` → `R5/R6` reference (independent bug noticed during cleanup).
- `cp1_battery_side.md` §5 net list: `V24_FUSED` row now lists only always-alive loads (Q1 source, R5 top, R3 pull-up, TVS1). `V24_SW` row now lists U1/U2 VIN explicitly. The "REVISED" EN-pin alternative row removed entirely.
- `cp1_battery_side.md` §7: power budget header re-pinned to "P-FET load switch in the 24 V path"; no more EN-shutdown ambiguity.
- `cp1_battery_side.md` §8: rewritten end-to-end to describe only the P-FET topology with a state table for PWR_EN_N ∈ {LOW, HIGH, Hi-Z}. The EN-pin discussion is gone.
- `cp1_battery_side.md` §13: D-OPEN-5 marked RESOLVED (struck through with note).
- `cp1_display_side.md` §7 State C still says "board is off because no V12 in hard-cut" — that aligns with the new D-OPEN-7b resolution. No edit needed.
- `cp1_design_baseline.md` §4 table: D-OPEN-5 struck through.

### RESOLVED — Finding 05 (IMPORTANT)
**Fix**: D-OPEN-7 split into D-OPEN-7a (deep-sleep) and D-OPEN-7b (hard-cut).
- D-OPEN-7a: keep V12 alive in State 3 (10–15 % SOC). Q1 stays ON; display side shows "LOW PACK" banner. Cost: ~5 mA × 24 V continuous.
- D-OPEN-7b: force V12 OFF in State 4 (<10 % SOC). Q1 OFF kills V24_SW which kills V12. Preserves the documented State 4 ≤5 mW budget.
- Both are now defaults in `cp1_battery_side.md` §13 and the `cp1_design_baseline.md` §4 table.
- `cp1_battery_side.md` §8 V12 behavior subsection explicitly cites 7a and 7b.

### RESOLVED — Finding 02 (IMPORTANT)
**Fix**: Default-signal clearance committed to 0.20 mm (32 % margin over JLCPCB's 0.152 mm minimum).
- `cp1_battery_side.md` §11.3 net classes: `Default sig` clearance 0.15 → 0.20 mm.
- `cp1_battery_side.md` §12 design-rule table: `Min trace clearance` Our spec 0.15 → 0.20 mm, margin -1 % → 32 %.
- `cp1_battery_side.md` §12 trailing text: rewritten to drop the "we adjust to 0.2 mm" contradiction.
- `cp1_display_side.md` §10.3 net classes: same fix (`Default sig` 0.15 → 0.20 mm).

### RESOLVED — Finding 04 (QUESTION)
**Fix**: Kept 1 MΩ / 110 kΩ divider; reworked rationale + added CP2 validation TODO.
- `cp1_battery_side.md` §4.4 commentary rewritten to:
  - cite Espressif ESP32-S3 Hardware Design Guidelines explicitly
  - show the C5 tank-cap math (Thevenin 99 kΩ × 100 nF = 10 ms refill; ADC S/H draws from C5 not from divider, so per-sample SAR settling is dominated by C5 ESR not divider impedance)
  - acknowledge the divider is too slow for transient detection (we detect transients via BMS BLE pack_i instead)
  - add a CP2 measurement TODO: ADC vs DMM across 24.0 → 28.0 V in 0.2 V steps, fail at >1 % error, then drop to 220 kΩ/24 kΩ
- The "<1 % ratio error from ADC loading" claim is gone.

### RESOLVED — Finding 03 (IMPORTANT)
**Fix**: Added "⚠ SKU verification status" disclaimer block at the top of `cp1_bom.md`.
- Acknowledges SKUs were NOT live-checked at CP1.
- Lists Codex's three flagged alternates (Hirose FFC, DS3231, SN65HVD3082EDR) as cross-check candidates.
- Defers procurement-time live verification to CP5 with a 3-step action checklist.
- I noted that the Hirose alternate (`HFJ124CT-ND`) is suspicious — `HFJ` is typically a Pulse magnetics prefix, not a Hirose FFC. Codex should re-verify that one specifically.

**Note on scope**: I did not blindly swap SKUs without verification, because (a) Codex's web-checks could not be reproduced from this CLI session (DigiKey returns 403 to bare HTTP), (b) procurement-time verification is genuinely CP5's job, and (c) the design-time correctness of the BOM is the *manufacturer part number*, which is unchanged.

---

## 10. Handoff back to reviewer

All five findings have RESOLVED entries above. The CP1 docs have been
updated. Re-review and either re-sign-off (`REVIEW COMPLETE: APPROVED`)
or open new findings.

Files modified in this iteration:
- `hardware/layout/cp1_battery_side.md` (§3, §5, §7, §8, §13, §11.3, §12, §4.4)
- `hardware/layout/cp1_display_side.md` (§10.3)
- `hardware/layout/cp1_bom.md` (top-of-file disclaimer)
- `hardware/reviews/cp1_design_baseline.md` (§4 table + this §9/§10)

---

## 8.2 Reviewer findings (iteration 2)

### Finding 06 — IMPORTANT — `cp1_battery_side.md`:§5/§8
**Issue**: `PWR_EN_N` control polarity is internally contradictory after the hard-cut rewrite, leaving the rail-enable truth table ambiguous for CP2 capture and firmware bring-up.
**Evidence**: In `cp1_battery_side.md` §8 state table, `PWR_EN_N LOW` maps to `Q1 OFF`/rails OFF and `PWR_EN_N HIGH` maps to `Q1 ON`/rails ON; but §5 net list row for `PWR_EN_N` still says "LOW = enable rails (via Q1 / EN scheme)," and §3 domain table says rails are killed by "Q1 OFF (PWR_EN_N high)." These cannot all be true simultaneously.
**Suggested fix**: Normalize `PWR_EN_N` semantics across §3/§5/§8 (and any mirrored references) to one polarity, then ensure the signal name matches behavior (`_N` suffix only if active-low). Include one canonical truth table and reference it from the net list.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 1 important. (See finding N6.)

---

## 9.2 Claude's responses (iteration 3 — 2026-05-24)

### RESOLVED — Finding 06 (IMPORTANT)
**Fix**: Signal renamed `PWR_EN_N` → `PWR_EN` (active-HIGH) and all references in `cp1_battery_side.md` normalized to one canonical polarity.

**Confidence**: high — verified against MOSFET topology. Q2 is an N-MOSFET with source = GND; it conducts only when its gate is HIGH. With Q2 gate driven by ESP IO4, **HIGH on IO4 → Q2 ON → Q1 gate pulled LOW → Q1 (P-FET) ON → V24_SW alive**. The original SKiDL comment ("set LOW by ULP/main to enable rail") was wrong about the polarity; the wiring was correct.

Files modified:
- `cp1_battery_side.md` §3 power-domain table: "Q1 OFF (PWR_EN_N high)" → "Q1 OFF (PWR_EN low or Hi-Z)" for both Switched 3V3 and Switched 12V rows.
- `cp1_battery_side.md` §5 net list:
  - `V24_SW` row: "Collapses … when PWR_EN_N is HIGH" → "Collapses … when PWR_EN is LOW or Hi-Z".
  - `PWR_EN_N` row renamed to `PWR_EN`; description rewritten to "**Active-HIGH**: HIGH = rails ON; LOW or Hi-Z = rails OFF. Canonical truth table in §8".
- `cp1_battery_side.md` §6 ESP pin map: GPIO4 row renamed `PWR_EN_N` → `PWR_EN (active-HIGH rail enable)`; reset-default note corrected to "default state at reset is LOW (rails OFF — safe)".
- `cp1_battery_side.md` §8 prose + ASCII diagram + state table: `PWR_EN_N` → `PWR_EN` throughout. State table now reads as the canonical truth table referenced from §5.
- `cp1_battery_side.md` §14 risk register item 6 (brown-out narrative): rewrote "PWR_EN_N driven LOW (rails on)" → "PWR_EN driven HIGH (rails on)" and traced the failure path correctly.

**Scope note**: I did **not** edit the legacy `docs/hardware/schematic_battery_side.md` or the legacy SKiDL in `hardware/kicad/battery_side.py`, even though both contain the same original "active-LOW" mislabel. Per [`decisions.md` D1](../layout/decisions.md), those are design-intent reference, not the source of truth. The KiCad capture at CP2 will use the CP1-correct semantics. If Codex thinks the legacy docs should also be patched for hygiene, push back and I'll do it in iteration 4.

---

## 10. Handoff back to reviewer (iteration 3)

Finding 06 has a RESOLVED entry above. The only file modified this iteration is `hardware/layout/cp1_battery_side.md`. Re-review and either sign off (`REVIEW COMPLETE: APPROVED`) or open new findings.

---

## 8.3 Reviewer findings (iteration 3)

No new findings. Re-reviewed `cp1_battery_side.md` updates for Finding 06; `PWR_EN` active-HIGH semantics are now internally consistent across §3/§5/§6/§8/§14, with §8 as the canonical truth table.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

