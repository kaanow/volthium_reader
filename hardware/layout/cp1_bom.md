# CP1 — Bill of materials (consolidated)

**Status**: CP1 snapshot (reconciled to D19)
**Scope**: the **complete** part list — every reference designator across
both boards, with vendor SKUs, quantities, and rationale. This is the
authoritative *engineering* BOM for CP1;
[`docs/hardware/bom.md`](../../docs/hardware/bom.md) is the curated
*procurement / shopping* view (distributor methodology + substitution
notes). Both are reconciled to D19.

> **Reference designators here track the pre-regen schematic and are
> finalized when the CP2 schematic regenerates.** A single fully-merged
> BOM (one refdes scheme, one file) is deferred to CP2 — unifying refdes
> now would just be redone then.

Conventions:
- Prices = single-quantity from DigiKey US, May 2026, USD. Mouser as backup.
- Where the BOM line is unchanged from the prior pass, it's annotated
  "(unchanged)". Otherwise the delta is called out.
- Spare margin: order **qty 5 of each board's parts** (matches JLCPCB
  PCB minimum order) for hand-solder rework. Some passives (the common
  values) can be shared across boards and ordered in bulk.

## ⚠ SKU verification status

**All distributor SKU cells in this BOM were batch-resolved against the
parts API on 2026-07-14** (SOP G3 sweep; independently re-run by the
reviewer at iter 23) — every cell resolves uniquely to its row's MPN.
That sweep replaced the earlier posture where only the D19/D25
power-chain actives had been checked (2026-06-17) and the rest were
written from working knowledge — which produced 14 fabricated or
wrong-part cells (see per-row correction notes). Historical stale-SKU
flags from the earlier review:

| Part                          | CP1 SKU (this doc)         | Spotted alternate (verify) |
|-------------------------------|----------------------------|------------------------------------|
| ~~DS3231SN# RTC~~ → RV-3028-C7 | (DS3231 dropped, D23) | RV-3028-C7 — in stock, verified 2026-06-18 |
| ~~SN65HVD3082EDR transceiver~~ (superseded D34, iter-8 F05) | ~~`296-21908-1-ND`~~ | ~~`296-31719-1-ND`~~ |
| ~~ISL3175EIBZ~~ (iter-8 first cut; superseded iter-10 F08 max-to-max) | ~~`ISL3175EIBZ-ND`~~ | ~~`968-ISL3175EIBZ`~~ |
| **THVD1400DR** transceiver (D34, current) | `296-THVD1400DRTR-ND` (32635) | `595-THVD1400DR` (2381) |

**Standing rule (SOP G3, revised 2026-07-14):** batch-`POST /resolve`
every SKU cell after any SKU edit and again at BOM-lock — a SKU cell is
a claim, never a recollection. At **CP5 procurement**, re-run the sweep
and re-check stock/lifecycle before clicking ORDER (stock moves: J2
B8B-PH-K-S collapsed 2900 → 16 in three weeks). The earlier posture
("CP1 doesn't gate on SKU correctness; verification is CP5's job") is
retired — it's how wrong-part cells survived 20 review iterations.

## Order strategy

Four sources (corrected 2026-07-14, iter-23 F23 — the prior "DigiKey
carries the Waveshare, one shipment" plan was wrong; neither DigiKey nor
Mouser lists the module):

1. **DigiKey** — primary cart for most active parts (all SKUs in this
   BOM resolved via the parts API, 2026-07-14).
2. **Mouser** — the Mouser-only lines: M3×5 standoffs (710-970050354);
   also stocks most other lines as second source.
3. **Waveshare direct (waveshare.com) or Amazon** — LCD1 e-paper
   Module (B); not stocked at DK/Mouser (API keyword sweep 2026-07-14).
4. **3D-printed bracket + faceplate** — user prints on their own
   printer; STL/STEP files come out of CP5.

JLCPCB order separately (the PCBs themselves; qty 5 each board, bare
PCB no PCBA). DHL shipping; ~$25–35 total for both boards' PCBs.

Component spend recomputed 2026-07-14 from the line items below (prior
"~$110 components / ~$145 grand" predated the U2 price correction
$8 → CA$27.95, the BTN1 dry-circuit upgrade $3 → CA$18.47, and the
TVS -13-F price updates; display enclosure/mounting corrected to $10
per iter-25 F25): battery-side **~$83**, display-side **~$69**,
cable/shared **~$10** → components **~$162**. PCBs add ~$30;
bracket/faceplate are filament cost (~$2). Grand total **~$192** for
one complete monitor.

---

## Battery-side board

### Power input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes (Δ from prior BOM) |
|-----|------|-----|-----|-------------|------------|-------|--------------------------|
| J1  | Phoenix **MSTBA 2,5/2-G-5,08** header (1757242, right-angle, 2-pos) + **MSTB 2,5/2-ST-5,08** plug (1757019, 2-pos screw-clamp) | THT 5.08 mm | 1 | 277-1106-ND (hdr) + 277-1011-ND (plug) | 651-1757242 + 651-1757019 | $3.50 | **NEW** pluggable input — user lands pack wires on the plug, plugs into the board (disconnect w/o unscrewing, D19). **PLUG CORRECTED 2026-07-01 (user caught via datasheet, D32): was 1727010 = MKDS 1/2-3,81 — a 3.81 mm board-mount screw terminal, wrong series/pitch, doesn't mate the header. 1757019 = the real MSTB 2,5/2-ST-5,08 2-pos plug (parametrics-verified: 2 pos, 5.08 mm, screw rising-cage; stock ~15k).** |
| F1  | 5×20 mm fuse clip, Keystone **3517** (×2, w/ end stops, UL E354010) | THT clip | 2 | **36-3517-ND** | 534-3517 | $0.48 ea | **NEW** — replaces ATO fuse holder. Holds the 1 A cartridge. **SKUs corrected 2026-07-14 (user-caught): prior F1465-ND / 530-31MJ005H were phantoms — zero hits at DK/Mouser/Octopart** (API /query + /resolve, 2026-07-14: DK 85.7k / Mouser 54.3k, Active). Datasheet Keystone_3517.pdf (5 mm/3AG clip table) |
| F1_ELEM | **Littelfuse 0215001.MXP** — 1 A 5×20 mm **time-lag (T)** ceramic cartridge fuse | TH 5×20 mm | 1 | F1696-ND | 576-0215001.MXP | $0.95 | **NEW** — fuse element. **Time-lag (DR-12)**: rides the ~22 µF ceramic inrush; ceramic = safer in a high-energy DC fault than glass. **API-verified 2026-06-25** (DK ~3.8k stock) |
| D1  | SS26 Schottky 60 V/2 A (SS26-E3/52T) | **DO-214AA (SMB)** | 1 | SS26-E3/52TGITR-ND | — | $0.30 | **Δ (D19/DR-3): SS24 (40 V) → SS26 (60 V)** to out-rate the ~53 V clamp. **Package corrected SMA → SMB (API 2026-06-25)** — SS26-E3/52T is DO-214AA; SMB is also easier to hand-solder |
| TVS1 | **SMAJ33CA-13-F** bidirectional TVS (Vrwm 33 V, VC 53.3 V @ 7.5 A per DS19005 p.2 device table; Diodes Inc) | SMA | 1 | SMAJ33CA-FDICT-ND (306k stock, Active; API /batch 2026-07-14) | 621-SMAJ33CA-13-F (48k) | $0.83 | **Iter-23 F20: non-F variant is Obsolete/zero-stock — and my prior "3.4k stock, Active" cell had laundered the Vishay listing's stock onto the Diodes SKU.** DS19005 p.1 ordering row names SMAJxxx(C)A-13-F. **Δ (D19/DR-2): SMAJ30CA → SMAJ33CA** — 33 V clears the ~29 V full-charge bus with margin |
| TVS3 | **SMAJ15A-13-F** unidirectional TVS, V12_CAT5E↔GND (VC 24.4 V @ 16.4 A per DS19005 p.2) | SMA | 1 | SMAJ15A-FDICT-ND (63k stock, Active; API /batch 2026-07-14) | 621-SMAJ15A-13-F (26k) | $0.75 | **NEW (DR-15):** clamps cable surges on the 12 V Cat5e pair at the **battery** end (matches the display-end SMAJ15A → both ends protected). Zero static draw |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | **LM5166YDRCR** (24 V→3.3 V, **always-on** µA-Iq buck, **500 mA**, **fixed 3.3 V**) | VSON-10 | 1 | LM5166**Y**DRCR = fixed 3.3 V (TI Active; YDRCR out-of-stock on TI.com 2026-06-21 — confirm distributor stock at BOM-lock) | 595-LM5166YDRCR | $4 | **Δ (D25): LM5165→LM5166**, fixed-3.3 V = **`LM5166YDRCR`** (reviewer Finding 01: `X`=5 V, `Y`=3.3 V — order **Y**). FB→VOUT, no divider. **CP2 (DR-29):** RT→GND = **PFM**; EN→VIN direct; HYS/SS/PGOOD open. Fallback: YDRCT cut-tape, else adjustable + divider; **never XDRCR** (5 V) |
| L1  | **4.7 µH**, Isat ≥ 2.2 A, low DCR shielded SMD | 1210 | 1 | _verify_ | _verify_ | $0.50 | **Δ: LM5166 inductor** — 4.7 µH for **PFM** (CP2/DR-29; TI Design 3, 24 V→3.3 V). Was "10–47 µH" assuming COT |
| C1, C2 | C1 22 µF / **100 V**, C2 **47 µF** / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.50 ea | **Δ: C1 →100 V** (LM5166 input, behind the ~53 V clamp); **C2 →47 µF** (CP2/DR-29: Eq-31 margin at peak-current overshoot; Design 3 value) |
| R_ILIM | **56.2 kΩ 1 %**, ILIM → GND | 0805 | 1 | _verify_ | _verify_ | $0.02 | **NEW (CP2/DR-29):** PFM current-limit select 750 mA peak / 300 mA IOUT (LM5166 Table 3) |
| U2  | Recom R-78HB12-0.5 buck (24 V→12 V, 0.5 A, 17–72 V in) | SIP3 THT | 1 | 945-1057-ND (383 stock, Active) | 919-R-78HB12-0.5 (1.9k) | **$27.95** (CAD; BOM had $8.00 — price corrected 2026-07-14) | **Δ (D19/DR-3): R-78E12 (34 V) → R-78HB12 (72 V)** to survive the clamp. Switched behind SSR1 + R_inrush |
| C3, C4 | C3 **3.3 µF** / **100 V** (R-78HB12 p.4; was 22 µF, ~7× oversized — F90), C4 22 µF / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.55 ea | **Δ: C3 22 µF→3.3 µF/100 V (F90)** — the R-78HB12 p.4 external-input value for Vin>50 V; shrinks the F2 turn-on I²t to 2.9 %. **Constrain the CP5 pick to ≤5 µF max-effective** (tol+temp+aging; DC bias reduces it) to keep ≤4.3 %. |

### Hard-cut load switch

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| SSR1 | **Panasonic AQY212EH** PhotoMOS SSR (1-Form-A, 60 V / 550 mA, **Ron 0.85 Ω typ / 2.5 Ω max**) — display-feed load switch **replacing the whole P-FET + gate-driver network** | DIP-4 (THT) | 1 | **255-2963-ND** (2471 stock, Active, API 2026-07-17) | 769-AQY212EH (4195) | $2.81 | **Δ iter-48 (F76 resolution, user-approved):** the discrete P-FET gate driver could not be *datasheet-guaranteed* OFF at temperature (5 iters, F60→F76). A PhotoMOS SSR is LED-controlled and opto-isolated: **OFF = open MOSFET, off-leakage ≤1 µA @25 °C (spec), and cannot self-turn-on** (no gate divider — the failure mode is *architecturally* eliminated). The datasheet publishes **no elevated-temperature leakage maximum** (its EC table is ambient 25 °C); at 85 °C the leakage is an *engineering estimate* of ~tens of µA (leakage ≈ doubles per ~10 °C) — carried explicitly as an estimate, **not** a bound, and gated by a bring-up State-4 leakage acceptance test (<5 mW pass; F83). It is non-amplifying, so it cannot cascade. Rated −40…+85 °C; continuous load derates 0.55 A@25 °C → 0.30 A@85 °C (≫ the ~5 mA display draw). In series V24_FUSED→**F2**→SSR1→**R_inrush**→V24_SW; blocks the 53 V surge open (<60 V), passes it to the 72 V U2 closed. Values corrected iter-50 (F79): the 0.25 Ω/100 °C-leakage figures were the AQY211EH sibling / 25 °C-only. Datasheet on file (Panasonic GE DIP4, sha d329b9729322) |
| R_opto | **330 Ω** 0805 1 % (ESP PWR_EN → SSR1 LED anode; cathode → GND) | 0805 | 1 | RMCF0805FT330RCT-ND | 71-CRCW0805-330-E3 | $0.10 | **NEW (F76); value F79:** SSR LED current limit. Worst-case I_F = (3.3−V_F max 1.5)/(330·1.01) = **5.4 mA ≥ the 5 mA recommended min** (nom 6.2 mA; max 6.6 mA < 30 mA); >the 3 mA operate spec with margin. ~6 mA GPIO load, **active only, 0 in hard-cut**. (390 Ω was only 4.57 mA worst-case — F79.) |
| R_inrush1, R_inrush2 | **2× 75 Ω 1206 pulse-proof (Vishay CRCW-HP, `CRCW120675R0FKEAHP`) in series = 150 Ω**, switched branch V24_FUSED→F2→SSR1→R_inrush→V24_SW/C3 | 1206 | 2 | 541-75.0UTR-ND (150k stock, Active) | 71-CRCW120675R0FKEAH (46k; Mouser drops the trailing P) | $0.06 ea | **NEW (F80); re-coordinated iter-54 (F86/F89).** Two 75 Ω in series (=150 Ω) so each survives a fault: worst case (V=29.2 V, R−1 %, **no fuse/SSR series credit** — reviewer's method) I=196.6 mA, total 5.74 W → **2.87 W each < the CRCW1206-HP §8.1 short-term-overload guarantee 6.25·P70 = 4.69 W/5 s at P70=0.75 W** (a *single* 1206-HP fails: 5.74 W > 4.69 W — F86). Recurring turn-on inrush **0.197 A — below the SSR 0.30 A @85 °C *continuous* (0.66×)**, no one-shot reliance. τ=150 Ω·3.3 µF=0.5 ms; ~2.5 ms to full charge. Per-turn-on I²t=½C·V²/R=**9.5e-6 A²s** = 2.9 % of F2's 80 mA melting I²t at the right-sized C3 = 3.3 µF (≤4.3 % at a 5 µF max-effective ceiling; the old 22 µF gave 19.1 % — F90) — far under Littelfuse's ≤20 %/100 k-pulse selection basis (F87). Datasheet Vishay_CRCW_HP.pdf (bdd4e4b9); §8.1 uses **P70**, not the 105 °C 1.5 W figure. |
| F2 | **80 mA** very-fast-acting SMD fuse (Littelfuse 451 Nano2 SMF), switched branch | **451 SMF, 6.10×2.69 mm** (dedicated land pattern p.4 — NOT 1206) | 1 | F3649TR-ND (1k stock, Active) | 576-0451.080MRL (687) | $4.57 | **NEW (F84); re-picked 62→80 mA iter-54 (F87).** Coordinated fault clear. Normal ~5 mA (≤~15 mA refresh) ≪ 80 mA. Worst-case short 0.197 A = **246 % of 80 mA (214 % at −40 °C** with the ~15 % cold fuse re-rating**)** → above the 200 % guaranteed-open threshold, clears within **200 %→5 s**; the 2× R_inrush (2.87 W each, §8.1) and SSR (<continuous) survive to the clear. **80 mA not 62 mA:** the fuse must survive the turn-on pulse for the product life. At the right-sized C3 = 3.3 µF (F90) the 80 mA fuse's I²t ratio is 2.9 % (≤4.3 % at the 5 µF max-effective ceiling), far under Littelfuse's ≤20 %/100 k-pulse selection basis; the 62 mA fuse and the old 22 µF C3 gave much higher ratios (F87/F90). 125 V/50 A@125 VDC interrupt; melting I²t 3.3e-4 A²s (datasheet p.2 .080 row). Datasheet Littelfuse_451_453.pdf (399d3cc9). |
| R4  | 100 kΩ 0805 1 % (PWR_EN pull-down to GND) | 0805 | 1 | **RMCF0805FT100KCT-ND** | 71-CRCW0805-100K-E3 | $0.10 | Brown-out failsafe-off: holds PWR_EN low (SSR LED off → open) when the ESP GPIO is high-Z/off |
| U4  | **TI TPS3808G01DBVR** voltage supervisor (~2.4 µA, adj SENSE, OD RESET, prog CT delay, +MR) | **SOT-23-6 (leaded ✓)** | 1 | 296-17188-2-ND | 595-TPS3808G01DBVR | $0.90 | **D28/DR-16; repackaged D33/DR-24 (2026-07-01): WSON→SOT-23-6 for solderability at ~zero power cost (Iq 2.4 µA vs the old part's 2.1 µA).** Adjustable **VIT = 0.405 V**; ISENSE ±25 nA max; built-in VHYS 1.5 %. Divider **release-sized** R1≈5.16 MΩ/R2≈100 kΩ + R_hys≈11.5 MΩ → trip ~20.0 V / release ~21.7–21.8 V (RESET active-low → positive feedback; F01 polarity + F04 release value; see R_uv/R_hys rows; final E96 at CP2). Active, DK 149k. Datasheet: hardware/datasheets/TPS3808G01DBVR.pdf |
| R_uv1 (top), R_uv2 (bottom) | UVLO pack divider → U4 SENSE. **VIT = 0.405 V** (TPS3808G01). Plain divider threshold is the *lower bound* on the release (see R_hys for the R_hys-leg + VHYS lift): sizing to ~21.3 V → **R1 ≈ 5.16 MΩ, R2 ≈ 100 kΩ** (E96) → actual release ~21.7–21.8 V, trip ~20.0 V | 0805 ×2 | 2 | _verify_ | _verify_ | $0.10 ea | **D28; re-derived for 0.405 V + polarity fix (D33/F01) + release refinement (F04).** ISENSE ±25 nA max → I_div ≥ 2.5 µA; 0.405 V/100 kΩ = 4.05 µA at threshold ✓ (~4.6 µA at 24 V, lower than the old 2.89 V part). Add small SENSE filter cap; final E96 at CP2 |
| R_hys | UVLO external hysteresis, U4 RESET → SENSE (**~11.5 MΩ**) | 0805 | 1 | _verify_ | _verify_ | $0.05 | **F01 (iter-5) + F04 (iter-6)/D28.** RESET is open-drain **active-low** → R_hys is *positive* feedback: healthy (RESET≈3.3 V) pulls SENSE up → drops the falling trip; asserted (VOL = 0–0.2 V) still sources a small current from SENSE → RESET, so release lands ~0.4–0.5 V *above* the plain divider threshold. ΔV = R1·(V_RESET_H−VIT)/R_hys ≈ **1.5 V** → trip ~20.0 / release ~21.7–21.8 V. Built-in VHYS (~6 mV) too small alone. Final E96 at CP2 |
| C_uvdd | 100 nF X7R — U4 VDD decoupling | 0603 | 1 | generic | generic | $0.05 | **BOM-diff catch 2026-07-23** (was drawn, never itemized) |
| C_sense | 1 nF C0G — U4 SENSE filter (the "small SENSE filter cap" from the R_uv row) | 0603 | 1 | generic | generic | $0.05 | **BOM-diff catch 2026-07-23** |
| C_ct | UVLO CT deglitch cap (~tens of ms) | 0603 | 1 | _verify_ | _verify_ | $0.05 | **NEW (D28):** rejects momentary sags |

### 24 V sense (always-on)

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| R5  | 1.2 MΩ 0805 1 % (top of divider) | 0805 | 1 | RMCF0805FT1M20CT-ND | 71-CRCW08051M20FKEA | $0.10 | **Δ (DR-6): 1 MΩ → 1.2 MΩ** — full charge → 2.25 V, inside the ESP ADC linear band; also current-limits a surge to ~41 µA |
| R6  | 100 kΩ 0805 1 % (bottom of divider) | 0805 | 1 | RMCF0805FT100KCT-ND | 71-CRCW0805-100K-E3 | $0.10 | **Δ (DR-6): 110 kΩ → 100 kΩ** (sets the ratio with R5) |
| C5  | 100 nF X7R 50 V (KEMET C0603C104K5RACTU) | 0603 | 1 | 399-C0603C104K5RACTUCT-ND (7.3M stock) | — | $0.05 | ADC filter. **SKUs corrected 2026-07-14 (SKU sweep): prior DK 311-1141-1-ND was an 0805 part on this 0603 row; prior Mouser Murata GRM188R71H104KA93D is Obsolete** |

### MCU & support

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 | SMD module | 1 | 5407-ESP32-S3-WROOM-1-N16R8CT-ND (3.2k stock, Active) | 356-ESP32S3WRM1N16R8 (66k) | $6.00 | **SKUs corrected 2026-07-14 (SKU sweep): prior DK "1965-…-ND" and Mouser "356-ESP32S3WROOM1N16R8" were malformed — resolved to nothing at either distributor.** (D-OPEN-1: consider -N8 alternative @ $4.50) |
| C6  | 10 µF X7R 16 V (Samsung CL21B106KOQNNNE) | 0805 | 1 | 1276-2872-1-ND (18 in stock — order early) | 187-CL21B106KOQNNNE (80k) | $0.32 | ESP bulk. **Corrected 2026-07-14 (SKU sweep): prior DK 1276-1023-1-ND was a 22 pF C0G — wrong part entirely; prior Mouser Murata cell was a wrong-prefix SKU and the part is OOS everywhere** |
| C7  | 100 nF X7R 16 V (Samsung CL05B104KO5NNNC) | 0402 | 1 | 1276-1001-1-ND (15.6M stock) | — | $0.05 | **Δ: 0603 → 0402** for ESP HF decoupling close-in (or 0603 if 0402 hard to hand-place). **Corrected 2026-07-14 (SKU sweep): prior DK 311-1086-1-ND was a 22 nF 0603 — wrong value AND size; prior Mouser Murata cell OOS** |
| C8  | 1 µF X7R 25 V (Taiyo Yuden TMK107B7105KA-T) | 0603 | 1 | 587-2984-1-ND (785k stock) | — | $0.15 | **NEW** — ESP EN soft-start cap. **Corrected 2026-07-14 (SKU sweep): prior DK 311-1361-1-ND was a Y5V 0805 100 nF — wrong dielectric, size and value; prior Mouser Murata cell is unlisted at both distributors** |
| R7  | 10 kΩ 0805 | 0805 | 1 | RMCF0805FT10K0CT-ND | 71-CRCW080510K0FKEA | $0.05 | **NEW** — ESP EN pull-up |
| RTC1 | **Micro Crystal RV-3028-C7 32.768kHz 1ppm TA QA** I²C RTC (45 nA) | 4-pin SMD 3.2×1.5 | 1 | 2195-RV-3028-C732.768KHZ1PPM-TA-QATR-ND | _verify (Mouser)_ | $2.00 | **Δ (D23/DR-8): DS3231 → RV-3028-C7** — 45 nA. **Full orderable MPN corrected (API 2026-06-25):** plain "RV-3028-C7" is ambiguous (QA standard / QC AEC-Q200 / "ON BOARD" = a dev board — avoid). Using **QA**; QC if a wider-grade part is ever wanted |
| C-bk | **Low-leakage backup cap ~10–50 mF (not a supercap)** on RV-3028 VBACKUP | SMD | 1 | _verify_ | _verify_ | $0.50 | **Δ (D23) + reviewer F09 / iter-8 F07:** trickle-charged by the RTC, rides a full disconnect. Supercap-class (0.1 F) leakage would dwarf the RTC's 45 nA and *shorten* hold time — the ≤50 mF, low-leakage constraint is the point. No coin, no D14 short risk. |
| U-ESD | USB ESD array (**USBLC6-2SC6Y**) | SOT-23-6 | 1 | 497-11882-2-ND | 511-USBLC6-2SC6Y | $0.30 | **NEW**: ESD clamp on the external USB-C D+/D−/VBUS (D22). **API-verified 2026-06-25: the original SC6 is out of stock at all sources → use the `-2SC6Y` variant** (DK ~30k, Mouser ~15k; pin-compatible) |
| U5  | 3.3 V LDO (AP2112K-3.3, ~600 mA) | SOT-23-5 | 1 | _verify_ AP2112K-3.3 | _verify_ | $0.20 | **NEW (D29):** VBUS→3V3_USB for USB maintenance power; VBUS-referenced (0 pack draw unplugged) |
| U6  | **TI TPS2116DRLR** priority power mux (~1.3 µA Iq, 2.5 A, reverse-blocking) | **SOT-583 (leadless ⚠)** | 1 | _verify_ TPS2116DRLR | 595-TPS2116DRLR | $0.70 | **NEW (D29):** VIN1=USB-LDO (priority), VIN2=U1 buck, OUT=V3V3. USB present → buck idles. Only ~1.3 µA always-on. **Package SOT-23-6 → SOT-583 (API 2026-06-25)** |
| Q3  | small signal N-FET **2N7002LT1G** (onsemi), series in U4 RESET→EN (UVLO bypass) | SOT-23 | 1 | — | **863-2N7002LT1G** | $0.49 | **NEW (D29); default-ON via R_byp1→V3V3 (fail-safe, reviewer F03)** — conducts when VBUS absent (UVLO active); opened by Q4 when VBUS present |
| Q4  | small signal N-FET **2N7002LT1G** (onsemi), VBUS-driven Q3-gate pulldown | SOT-23 | 1 | — | **863-2N7002LT1G** | $0.49 | **NEW (reviewer F03):** VBUS present → Q4 ON → Q3 gate to GND → bypass. VBUS-referenced |
| C_usb1, C_usb2 | LDO in/out 1 µF X7R | 0603 ×2 | 2 | _verify_ | _verify_ | $0.05 ea | **NEW (D29):** AP2112 in/out caps |
| C_mux | ~47 µF on TPS2116 OUT (V3V3) | 0805/1206 | 1 | _verify_ | _verify_ | $0.10 | **NEW (reviewer F11):** OUT bulk for reverse-current-blocking on USB hot-plug |
| R_byp1 | Q3 gate pull-up to **V3V3** (100 kΩ) | 0805 | 1 | _verify_ | _verify_ | $0.05 | **NEW (reviewer F03):** sets fail-safe default-ON |
| R_byp2 | VBUS → Q4 gate divider | 0805 | 1 | _verify_ | _verify_ | $0.05 | **NEW (D29):** VBUS-referenced |
| R_byp2b | 1 MΩ — VBUS divider bottom leg (Q4 gate) | 0805 | 1 | generic | generic | $0.05 | **BOM-diff catch 2026-07-23** (drawn with R_byp2, never itemized) |
| C9  | 100 nF X7R 50 V (KEMET C0603C104K5RACTU, as C5) | 0603 | 1 | 399-C0603C104K5RACTUCT-ND | — | $0.05 | RTC decoupling. **Corrected 2026-07-14 (SKU sweep): prior DK 311-1141-1-ND was an 0805 part on this 0603 row** |
| R8, R9 | 4.7 kΩ 0805 1 % I²C pull-ups | 0805 | 2 | RMCF0805FT4K70CT-ND | 71-CRCW08054K70FKEA | $0.05 ea | I²C bus pull-ups |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U3  | **THVD1400DR** (TI, 3.3–5.5 V half-duplex, 500 kbps, full fail-safe RX) | SOIC-8 | 1 | 296-THVD1400DRTR-ND | 595-THVD1400DR | $1.38 | **D34 (revised iter-10 F08)**: pivot from ISL3175EIBZ (12 µA max shutdown, iter-8 first cut) to THVD1400 (**1 µA max shutdown**, 12× better on the load-bearing hard-cut spec). VCC 3.0–5.5 V, RX-only Iq 900 µA max/700 µA typ; **datasheet-guaranteed internal DE pull-DOWN + /RE pull-UP** → default-safe without external R_DE/R_RE. Standard SN75176 8-SOIC pinout (drop-in). TI Active, DK+Mouser **35016** stock. Datasheet: `hardware/datasheets/THVD1400DR.pdf` (sha `5ba9785d…`). |
| R10 | 120 Ω 0805 1 % term resistor | 0805 | 1 | RMCF0805FT120RCT-ND | 71-CRCW0805120RFKEA | $0.10 | (unchanged) |
| — | _(no idle bias on the battery side — D19/DR-4)_ | — | 0 | — | — | — | **Δ: removed battery-side bias.** The always-on rail would otherwise leak ~2.3 mA continuously; bias is now display-end only |
| TVS2 | **SMAJ12CA-13-F** bidirectional TVS (VC 19.9 V @ 20.1 A per DS19005 p.2) | SMA | 1 | SMAJ12CA-FDICT-ND (268k stock, Active; API /batch 2026-07-14) | 621-SMAJ12CA-13-F (30k) | $0.84 | **Iter-23 F20: -13 → -13-F (non-F Obsolete)** | Δ: renumbered from TVS1 in prior schematic |
| C10 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U3 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1 | **C&K 8125SHZBE** — SPDT ON-(MOM) snap-acting pushbutton, plunger actuator, 0.250" flat bushing panel mount, solder lugs, **contact code B = gold, epoxy terminal seal**. Wire COM(1)–NO(2): open at rest, closed pressed (function table, CK_8020_series.pdf) | Panel-mount bushing | 1 | CKN4022-ND (1,588 stock, Active, CA$18.47; API /query 2026-07-14) | 611-8125-241 (402) | $18.47 | **Iter-23 F22 (reviewer): RP3502MABLK superseded — an AC power switch with no published dry-circuit/minimum-load rating can't be qualified for 3.3 V/µA service, and the C11 100 nF pulse (0.54 µJ) is not a vendor wetting qualification.** 8125+B is *rated for this circuit class*: "B contact material (8X25 Models): 0.4 VA max. @ 20 V AC or DC maximum" (CK_8020_series.pdf, Contact Rating). Our 3.3 V × 3.3 µA ≪ 0.4 VA ✓. Zero unpressed draw preserved (same R13/C11 network). Smaller bushing than the RP3502 (1/4"-40 class vs 12.7 mm) — lid hole sized at enclosure design. CP5 bench = verification of a rated design, not qualification of an unrated one |
| R13 | 1 MΩ 0805 1 % | 0805 | 1 | RMCF0805FT1M00CT-ND | 71-CRCW08051M00FKEA | $0.10 | BTN pull-up (Δ: was 10 kΩ → 1 MΩ for lower Iq) |
| C11 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | Button debounce |

### Connectivity

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J2  | **Amphenol RJHSE-5380** RJ45 jack, shielded, THT | THT shielded | 1 | 664-RJHSE5380-ND | 523-RJHSE-5380 | $2.50 | **MPN/SKU API-verified 2026-06-25** (DK ~18k; was the placeholder "RJHSE-538X" + wrong SKU). **✅ MAGNETICS-FREE confirmed from datasheet (P-RJHSE-X380): "8P8C, shielded, without LEDs", phosphor-bronze contacts straight to 8 PCB pins, no transformer** — safe for 12 V DC + RS-485. Vertical jack (battery enclosure not depth-limited). Datasheet: hardware/datasheets/RJHSE-5380.pdf |
| J3  | **USB-C receptacle** (native ESP32-S3 USB) | SMD | 1 | _verify_ | | $0.50 | **Δ (D22): was a USB-OTG pin header** — now a board-edge maintenance port (flash/console/JTAG), accessible without opening. ESD-protected by U-ESD |
| R_cc1, R_cc2 | 5.1 kΩ — USB-C CC1/CC2 UFP advertisement | 0603 | 2 | generic | generic | $0.02 ea | **BOM-diff catch 2026-07-23** (required for a 5 V source to enable VBUS) |
| J4  | 2-pin 2.54 mm header, RS-485 term lift jumper | THT | 1 | S1011EC-02-ND | 200-TSW10206TS | $0.20 | NEW |
| J5  | **6-pin 2.54 mm header — programming/debug, exact ESP-Prog "Program" order (EN/VDD/TXD/RXD/IO0/GND)** | THT | 1 | (same as J4 family) | (same) | $0.30 | **Δ 2026-07-23 (DR-32): 4→6 pin.** Adds EN + IO0 so a standard ESP-Prog (or jumper wire) can FORCE download mode — the recovery path native USB-Serial/JTAG can't provide when firmware deep-sleeps immediately or kills USB |
| J_EXP | **Molex PicoBlade 1.25 mm, 8-ckt, SMT** expansion header, **vertical 53398-0871** | SMT | 1 | **WM7612CT-ND** | 538-53398-0871 (42.6k) | $1.40 | **NEW (D37):** future-expansion — dedicated I2C1 (SDA/SCL, pull-ups on **switched EXP_3V3**, F48) + 2× ADC1/RTC-wake AIO + 1 generic DIO + **load-switched EXP_3V3** + GND×2. Datasheet on file (customer drawing). **F33 fix:** DK SKU corrected WM7626 (=r/a 53261) → WM7612CT-ND (=53398-0871). **F38/F49/F53 (mate/rating — CLOSED iter-36):** drawing = **MATE WITH: 51021 SERIES**; exact header-system spec **PS-51021-024 Rev AD now on file** (owner upload 2026-07-17, sha b7d3ec9b74b9) — its scope lists **53398\*\*71 vertical headers (ours)**, and ratings give **1.0 A max (AWG 26/28/30), 125 V, −40…+105 °C** (8-ckt derating ref 1.5 A @ AWG 26/28, 30 °C rise, reference-only) — our loads (logic + one power pin whose upstream ceiling is the shared LM5166 500 mA) are within it. PS-51021-009 stays scoped to the wire-to-wire mate side (F53). Qty-1 mate = **OTS pre-built cable assembly 0151340801** (DK **WM15273-ND**, 8,199 stock, Active, $10.53, API 2026-07-16 — optional, order with the add-on; loose 50079-8000 terminals have a 25k MOQ, not a qty-1 path). R/A alt 53261-0871. Pinout/power: decisions.md **D37** |
| Q_exp | Expansion-rail **on/off** load switch — **direct-GPIO-driven NTR4171P** P-FET high-side, **default-OFF** (F51: source = 3V3 = the GPIO domain, no level shifter; **F61 iter-40: FET = onsemi NTR4171P — RDS(on) guaranteed 150 mΩ max @ VGS=−2.5 V**, Vgs ±12 V ≫ the 3.3 V drive; replaced DMG3415U, which was NRND at the manufacturer despite distributor stock; gate ← 100 kΩ pull-up to 3V3 + ESP `EXP_PWR_EN`: high-Z/high = OFF, low = ON) — **F34/F39/F48/F51/F56/F61** | SOT-23 | 1 | **NTR4171PT1GOSCT-ND** (11k stock, Active, API 2026-07-17) | 863-NTR4171PT1G (30k) | $1.13 | **NEW:** gates EXP_3V3; **OFF at reset + force-OFF in State 4**. **F48/F51 off-state contract (decisions.md D37):** I2C pull-ups on the switched rail; all 5 signals high-Z before/while rail-off; R_exp_bleed (**10 kΩ**, F66) parks the rail **≤50 mV @85 °C datasheet-bound** (NTR4171P IDSS ≤5 µA @85 °C × 10 kΩ; ≤10 mV @25 °C); **binding limit = bring-up acceptance ≤50 mV measured**. State-4 off-leakage from 3V3 = IDSS ≤5 µA @85 °C (≈16 µW). **F39: a switch, not a current limiter** — upstream limit is F1 (1 A) + LM5166 (500 mA). Optional series PPTC (~75 mA hold) — noted, DNP |
| R_exp_pu | 100 kΩ — Q_exp gate pull-up to V3V3 (default-OFF) | 0805 | 1 | generic | generic | $0.05 | **BOM-diff catch 2026-07-23** (named in the Q_exp row, never itemized) |
| R_exp_sda, R_exp_scl | **4.7 kΩ** expansion-I2C pull-ups (EXP_SDA/EXP_SCL → switched **EXP_3V3**) | 0805 | 2 (**DNP**) | generic | generic | — (DNP) | **DNP, footprint-only (user call 2026-07-20):** the D37/F48 pull-ups live on the switched rail; footprints on-board so they can be stuffed **here OR on the expansion daughterboard** if/when one is ever built. Value matches R8/R9 |
| R_exp_bleed | **10 kΩ** 0805, EXP_3V3 → GND discharge | 0805 | 1 | **RMCF0805FT10K0CT-ND** | 71-CRCW0805-10K-E3 | $0.10 | **Δ (F66): 100 kΩ → 10 kΩ.** Parks the switched rail against the **NTR4171P elevated-temp leakage**: ≤5 µA IDSS @85 °C × 10 kΩ = **≤50 mV @85 °C** (the earlier 0.5 µA/50 mV cited the retired ZXMP6A13F; at 100 kΩ the NTR4171P bound would have been 500 mV @85 °C). Draws 330 µA (~1.1 mW) only while EXP is ON |

### Xanbus CAN read (DR-31 — user-approved 2026-07-22; population default-yes, J7 shunt only at chain end)

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U7 | **TI TCAN332DR** — 3.3 V CAN transceiver, ±12 V CM, ±14 V bus fault, 12 kV IEC ESD, **bus high-Z when unpowered** | SOIC-8 (leaded) | 1 | 296-43711-1-ND (6.3k stock, Active; API 2026-07-22) | 595-TCAN332DR | CA$3.69 | Listens to the Schneider **Xanbus** (CAN 250 kbps) via the ESP32-S3 native TWAI (IO40/41). Unpowered-high-Z + power gate ⇒ the parked reader never loads the live network. Datasheet on file (TCAN332.pdf, SLLSEQ7F) |
| Q5 | **onsemi NTR4171P** P-FET high-side gate, CAN_PWR (IO42) active-LOW, 100k default-OFF pull-up (R14) | SOT-23 | 1 | NTR4171PT1GOSCT-ND | 863-NTR4171PT1G | $1.13 | Same part/pattern as Q10/Q11/Q_exp — zero draw parked (power-first) |
| D2 | **onsemi NUP2105L** dual-line CAN TVS (24 V standoff) | SOT-23 | 1 | NUP2105LT1GOSCT-ND (132k stock, Active; API 2026-07-22) | 863-NUP2105LT1G | CA$0.66 | Belt-and-braces on the field cable (U7 already has 12 kV IEC) |
| J6 | **Amphenol RJHSE-5380** RJ45, shielded (3rd instance — same SKU/line as J2/J10/J11) | THT shielded | 1 | 664-RJHSE5380-ND | 523-RJHSE-5380 | $2.50 | **Xanbus: CAN_L = pin 4, CAN_H = pin 5, no ground pin** (LYNK II 805-0052 §4.2.1 — same battery-side topology). Xanbus NET-power pins left unconnected |
| J7 | 2-pin 2.54 mm header + shunt, **CAN termination lift** (fitted = 120 Ω in circuit) | THT | 1 | (same as J4) | (same) | $0.20 | User call: easy on/off termination — the reader terminates only when it's a chain END |
| R14 | 100 kΩ gate pull-up (default-OFF) | 0805 | 1 | generic | generic | $0.02 | |
| R15 | 120 Ω CAN termination (in series with J7) | 0805 | 1 | generic | generic | $0.02 | |
| C12 | 100 nF X7R decoupling on the gated VCC | 0603 | 1 | generic | generic | $0.05 | |

**Subtotal ≈ CA$8.3.** GPIO note: IO40/41/42 were the last free safe pins — **MCU GPIO budget now exhausted** (JTAG forfeited; debug = J5 UART).

### Isolated RS-485 battery read (D36 — PENDING DR-26)

> **Status: PENDING — CP1-delta / DR-26 gated.** This whole subsection is
> the itemization of the `cp1_rs485_battery_read.md` addendum and is **not
> yet folded into the battery-side subtotal**. It stays gated on the §7
> on-site two-domain acceptance matrix (F47/F52). Nets/refdes freeze only
> after that pass; SKUs below were API-resolved 2026-07-20. Schematic drawn
> in CP2 (2× ADM2587E channels, one sheet each); net-name + footprint
> reconciled against the generator 2026-07-20.
> **Two identical, interchangeable channels** (ch1 = refdes 2x, ch2 = 3x);
> Qty columns already reflect the ×2 (or ×4). Prices are single-qty; the
> ADM2587E line is CAD from Mouser (matches the D36 grand-total delta),
> the rest track the BOM's USD/DigiKey convention — reconcile currency at
> BOM-lock.

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U10, U11 | **Analog Devices ADM2587EBRWZ** — isolated RS-485 + integrated isolated DC-DC (isoPower), 3.3 V, 500 kbps slew-limited, ±15 kV ESD bus pins, 2500 Vrms iso | SOIC-20W (wide-body, **leaded**) | 2 | 505-ADM2587EBRWZ-ND (200 stock — straight tube; or -REEL7 505-ADM2587EBRWZ-REEL7CT-ND, 11k) | 584-ADM2587EBRWZ (3.7k stock) | $22.90 ea (CAD, Mouser) | One-chip isolation+xcvr+iso-supply → fewest joints for a hand build. ICC 90 mA @3.3 V/100 Ω (Rev H Table 1) → **power-gated per channel** (see Q10/Q11). Creepage-critical: CP3 barrier keep-out. DK non-reel stock thin (200) — order the REEL7 cut-tape. Datasheet on file (Rev H, sha 77a52a9e6036) |
| Q10, Q11 | **onsemi NTR4171P** P-FET high-side load switch (RDS(on) 150 mΩ max @ VGS=−2.5 V, Vgs ±12 V) — power-gates each ADM2587E VCC; **active-LOW** CHx_PWR, default-OFF | SOT-23 | 2 | NTR4171PT1GOSCT-ND (11k stock, Active) | 863-NTR4171PT1G (30k) | $1.13 ea | Same P-FET class as Q_exp (already in BOM). 100 kΩ gate pull-up to **V3V3** → OFF while GPIO high-Z. ~90 mA channel load → ≤14 mV drop. Off-leakage IDSS ≤1 µA @25 °C / ≤5 µA @85 °C (F51/F61) |
| J10, J11 | **Amphenol RJHSE-5380** RJ45 jack, shielded, magnetics-free — mates the vendor M12→RJ45-male cable directly (A/B on pins 7/8, measured 2026-07-17) | THT shielded | 2 | 664-RJHSE5380-ND | 523-RJHSE-5380 | $2.50 ea | **Reuses J2's SKU/line** (identical part). Footprint `Connector_RJ:RJ45_Amphenol_RJHSE5380` (no hyphen). Identical/interchangeable — either pack on either jack. Datasheet on file (RJHSE-5380.pdf) |
| L10, L11, L12, L13 | **TDK MPZ2012S601AT000** ferrite bead, 600 Ω @100 MHz, 2 A, 100 mΩ DCR — L1 on VISOOUT→VISOIN, L2 between `GND2_DCDC` and `ISO_BUS_GND` (one per net, ×2 ch) | 0805 | 4 | 445-MPZ2012S601AT000CT-ND (896k stock) | 810-MPZ2012S601AT000 (660k) | $0.18 ea | **Two beads per channel** (Rev H Fig 35): L1 on the VISO rail, L2 the *only* GND2_DCDC↔ISO_BUS_GND tie. p.17 keep-out under both (no GND2 fill). Generic 600 Ω/0805 — dual-sourced, high stock. **⚠ Verify at BOM-lock (user Q 2026-07-23):** DS p.17 sizes the bead "about 2 kΩ between 100 MHz and 1 GHz" (180 MHz primary / 360 MHz rectifying + harmonics); a 600 Ω@100 MHz bead may sit below that — check the MPZ2012S601 |Z| curve at 180/360 MHz or pick from AN-1349's recommended parts. Emissions-only concern (no EN55022 target for this one-off; in-enclosure links) → functional either way |
| C20, C30 · C22, C32 · C25, C35 · C26, C36 | **0.1 µF** X7R decoupling — VCC pin2 (C20/C30), VCC pin8 (C22/C32), VISOOUT (C25/C35), VISOIN (C26/C36) | 0603 | 8 | generic | generic | $0.05 ea | Per-channel isoPower bypass network (Rev H pp.8/17 — required, not optional). VISOOUT caps land on `GND2_DCDC`; VISOIN caps on `ISO_BUS_GND` |
| C21, C31 · C27, C37 | **0.01 µF** X7R decoupling — VCC pin2 (C21/C31, on GND1), VISOIN (C27/C37, on `ISO_BUS_GND`) | 0402 | 4 | generic | generic | $0.05 ea | HF bypass pair with the 0.1 µF caps above |
| C23, C33 · C24, C34 | **10 µF** X7R bulk — VCC pin8 logic bulk (C23/C33, GND1), VISOOUT bulk (C24/C34, `GND2_DCDC`) | 0805 | 4 | generic | generic | $0.10 ea | isoPower input/output bulk (Rev H p.17: device side of L1/L2) |
| C28, C38 | **KEMET C1206C102KDGACTU** — 1 nF, **1 kV**, C0G/NP0 ceramic (C_stitch) — GND1 pin10 ↔ pin11 (`GND2_DCDC`) across the isolation barrier | 1206 | 2 | 399-C1206C102KDGACTUCT-ND (13k stock, Active, MOQ 1) | 80-C1206C102KDGACTU (22k stock) | $0.20 ea | **1 kV C0G, NOT a mains Y-cap** (resolved 2026-07-20): this is a **24 V battery system — functional isolation, not mains-safety**, so no safety-agency certification is required. 1 kV rating >> the ADM2587E barrier's own **524 Vpk VIORM** and >> the ≤~60 V bank-stack common-mode it actually sees. A "safety" Y2 cap would be worse here — typically only ~250–300 VAC rated, *below* the 524 Vpk number. Only cap allowed to bridge GND1↔GND2. C0G = stable/low-loss for the HF common-mode return |
| R20, R30 | **100 kΩ** gate pull-up (Q10/Q11 gate → V3V3, default-OFF) | 0805 | 2 | generic | generic | $0.02 ea | Sets fail-safe default-OFF while CHx_PWR is high-Z |
| R21, R31 | **1 kΩ** series on each DIx (power-up-settle guard, §2a) | 0603 | 2 | generic | generic | $0.02 ea | Belt-and-braces limit during the ~1 ms isoPower settle |
| R22, R32 · R23, R33 | **10 Ω** R_ser1 / R_ser2 — series between the TVS node and ADM2587E A/B | 0603 | 4 (**DNP**) | generic | generic | — (DNP) | **DNP, footprint-only.** Part of the intentionally-unprotected in-box link (F36/F44): no published ADM injection rating to size an R against. Populate only with a *properly coordinated* TVS if field-cable surge ever becomes a requirement |
| R24, R34 | **120 Ω** RS-485 termination across A/B (via J4-style lift is not used here — hard-DNP) | 0805 | 2 (**DNP**) | generic | generic | — (DNP) | **DNP, footprint-only.** 9600 baud over ~1–2 m point-to-point → reflections settle ≪ 1 bit; term just loads the driver. Stuff only if a bench capture shows ringing |
| R25, R35 · R26, R36 | **560 Ω** fail-safe idle bias1 / bias2 (A→iso-rail, B→iso-GND) | 0805 | 4 (**DNP**) | generic | generic | — (DNP) | **DNP, footprint-only.** ADM2587E has internal fail-safe (Rev H p.15); **idle-noise margin only, NOT a common-mode fix** (F52/F58). Stuff only if §7 bench shows idle chatter |
| R27, R37 | **0 Ω** REF jumper — ISO_BUS_GND → pack B− (fallback reference pad) | 0805 | 2 (**DNP**) | generic | generic | — (DNP) | **DNP, footprint-only.** §7 fallback if the two-domain matrix fails: 0 Ω link pins each island to its own pack's B−, preserving symmetry. Default unwired |
| D10, D11 | **Semtech SM712** asymmetric RS-485 TVS (VRWM 12/7 V, VC 20/10 V @5 A) | SOT-23 | 2 (**DNP**) | SM712CT-ND | 947-SM712.TCT | — (DNP) | **DNP, footprint-only — port intentionally unprotected** (F36/F44). SM712 VC 20 V > ADM bus abs-max −9/+14 V and a bare series-R can't coordinate it. Accepted risk: short in-enclosure link |

**Subtotal (populated parts only), recomputed from the canonical rows above (2026-07-23):** 2× ADM2587E $45.80 + 2× NTR4171P $2.26 + 2× RJHSE-5380 $5.00 + 4× bead $0.72 + isoPower passives (8× 0.1 µF $0.40, 4× 0.01 µF $0.20, 4× 10 µF $0.40, 2× R100k $0.04, 2× R1k $0.04) + 2× C_stitch (KEMET 1 nF/1 kV) $0.40 ≈ **$55.3** (mixed CAD/USD per the column convention — reconcile at BOM-lock). All DNP protection/bias/term/ref parts add $0 (footprint-only: R22–R27/R32–R37 ×12 + D10/D11).

### Enclosure & mounting

| Ref | Part | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-------------|------------|-------|-------|
| EN1 | **User-3D-printed plastic enclosure, IP5x** (indoors) | 1 | — printed | — | (filament) | **Δ (D20): no commercial box** — wall-mount above the batteries (air gap), sized to the CP3 board outline, with a USB-C port + dust cap |
| —   | M3×5 mm brass standoffs (Würth 970050354 WA-SBRII, ×4) + generic M3 screws | ×4 | — | 710-970050354 (4.5k stock) | $0.59 ea | **Corrected 2026-07-14 (SKU sweep): prior DK 36-9774-ND was a phantom — no such SKU.** Würth WA-SBRII M3×5 mm matches the 5 mm board-to-base spacing |
| —   | 24 V hookup wire to pack, 30 cm of 18 AWG | 1 | — | — | $1.00 | User-supplied if they have it |

### Battery-side subtotal

| Category | Cost |
|----------|------|
| Component + connector line items (mechanical sum of this section's price column, 2026-07-14) | ~$79.6 |
| Hardware (standoffs ×4 @ $0.59, hookup wire) | ~$3.4 |
| Enclosure | (printed — filament) |
| **Battery-side total** | **~$83** |

*(Recomputed at iter-23 F23. The dominant deltas vs the stale ~$43:
U2 R-78HB12-0.5 = CA$27.95 (was $8) and BTN1 8125SHZBE = CA$18.47
(was $3).)*

---

## Display-side board

### Power input + protection

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J1  | **Würth 615008145521** WR-MJ RJ45 jack, right-angle (horizontal, tab-down), shielded, THT | THT shielded | 1 | 732-615008145521-ND | 710-615008145521 | $4.00 | **Δ (DR-10): right-angle** for the shallow box (the earlier SUYIN 100362 is NOT distributor-stocked). **✅ Datasheet-verified 2026-06-25: horizontal/right-angle + shielded (EMI panel finger) + 8P8C + MAGNETICS-FREE** (plain CAT5e jack, 20 mΩ contacts, no magjack) + ~13.6 mm height → fits the ~45 mm depth (~33 mm stack). −40…+85 °C, UL E324776. **Tab-down** → confirm cable-entry orientation at CP3. Datasheet: hardware/datasheets/615008145521.pdf |
| F1  | **Bourns MF-R025** PTC polyfuse, **~0.25 A hold** | THT radial | 1 | MF-R025-ND | 652-MFR025 | $1.00 | **Δ (DR-11): 0.5 A → ~0.25 A** — matches the ~40–150 mA load, trips below U2 foldback. **API-verified 2026-06-25** (DK ~4.2k, Mouser ~7k) |
| TVS1 | **SMAJ15A-13-F** unidirectional TVS (VC 24.4 V per DS19005 p.2) | SMA | 1 | SMAJ15A-FDICT-ND (63k, Active; API /batch 2026-07-14) | 621-SMAJ15A-13-F (26k) | $0.75 | **Iter-23 F20: -13 → -13-F** |
| C1  | 22 µF / 25 V X7R | 1210 | 1 | (unchanged) | | $0.20 | V12 input bulk |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | Recom R-78E3.3-0.5 (12 V→3.3 V, 0.5 A) | SIP3 THT | 1 | 945-1661-5-ND (7.0k stock, Active) | 919-R-78E3.3-0.5 (18k) | $5.00 | **DK cell corrected 2026-07-14 (SKU sweep): prior "945-R-78E3.3-0.5" was malformed (not a DK SKU)** |
| C2  | 10 µF X7R | 0805 | 1 | (unchanged) | | $0.10 | V3V3 output bulk |

### MCU & support

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 (`-1`) | SMD module | 1 | (unchanged) | | $6.00 | **D26: radio unused** (RS-485 link) — kept for commonality, RF disabled, antenna keepout dropped |
| C3  | 10 µF X7R | 0805 | 1 | (same as battery-side C6) | | $0.10 | ESP bulk |
| C4  | 100 nF X7R | 0402 or 0603 | 1 | (same as battery-side C7) | | $0.05 | ESP HF |
| C5  | 1 µF X7R | 0603 | 1 | (same as battery-side C8) | | $0.10 | ESP EN soft-start |
| R1  | 10 kΩ 0805 | 0805 | 1 | (same as battery-side R7) | | $0.05 | ESP EN pull-up |

### E-paper

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| LCD1 | Waveshare 4.2inch e-Paper **Module (B)** — tri-color (B/W/R), onboard driver + 8-pin SPI | module | 1 | — | — | ~$35.00 | **Δ (DR-7): use the module (8-pin SPI), not a bare panel.** Driver + booster on the module. **Sourcing corrected 2026-07-14 (SKU sweep): prior DK 1738-1135-ND resolves to DFRobot DFR0290 (different manufacturer's display) and Mouser 992-19094 is a phantom; keyword sweep confirms neither distributor lists this Waveshare module → order from waveshare.com or Amazon** |
| J2  | **JST-PH 2.0 mm 8-pin** post header (B8B-PH-K-S top / S8B-PH-K-S side) — e-paper SPI: VCC/GND/DIN/CLK/CS/DC/RST/BUSY | THT 1×8 | 1 | B8B-PH-K-S → 455-1710-ND (**stock collapsed ~2900 → 16 between 2026-06-25 and 07-14 — order early**; still Active) | — (Mouser doesn't list; prior 455- cell used the DK prefix) | $0.51 | **Matches the module's PH 2.0 connector — evidence: hashed Waveshare product-page + wiki captures 2026-07-14 (manifest LCD1 row; box lists "PH2.0 20cm 8Pin x1"; iter-23 F21).** Same family both sides → pre-crimped PH↔PH cable (user: ASPHSPH24K102-class), no tool. Keyed by design. **Δ (DR-7):** was a 24-pin FH12-24S FFC (bare-panel) |
| C6  | 1 µF X7R panel VCC bulk | 0603 | 1 | (same as C5) | | $0.10 | NEW — reduces VCC dip during refresh |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U2  | **THVD1400DR** (TI, 3.3–5.5 V half-duplex, 500 kbps, full fail-safe RX) | SOIC-8 | 1 | 296-THVD1400DRTR-ND | 595-THVD1400DR | $1.38 | **D34 (revised iter-10 F08 + iter-14 F15)** — same swap as battery-side U3, drop-in SOIC-8. Internal DE pull-DOWN + /RE pull-UP → no external R_DE/R_RE needed. Display firmware latches GPIO15 LOW via `gpio_hold_en` in deep sleep so /RE = 0 (receiver on); wake is the **`ext1` `ESP_EXT1_WAKEUP_ANY_LOW` RTC-GPIO mask** over GPIO12/13/14 (buttons) + GPIO18 (RO), triggered by a master-driven sustained-LOW BREAK — **not** the ESP UART wake (UART off in Deep-sleep). |
| R2  | 120 Ω 0805 1 % | 0805 | 1 | (same as battery R10) | | $0.10 | Bus terminus |
| R3, R4 | ~330 Ω 0805 1 % idle bias footprints (A→3V3, B→GND) | 0805 | 2 (**DNP by default**) | _verify_ | | $0.10 ea | **DNP by default (iter-12 F12).** THVD1400 datasheet §8.2.1.4 guarantees Full Fail-Safe RX (open/short/idle bus → RO HIGH built-in), so a static bias is not required for correct RS-485 idle behavior. If populated, it draws **4.58 mA at 3.3 V ≈ 15 mW continuously** whenever the display board is powered — that's the reviewer's F12 catch; prior text called this "free margin at hard-cut" but it's a real 15 mW cost in State A + State B (only free in State C hard-cut). Footprint stays on the PCB so it can be stuffed at CP5 bench if actual link EMI ever shows spurious RO glitches. |
| TVS2 | **SMAJ12CA-13-F** bidirectional (VC 19.9 V @ 20.1 A per DS19005 p.2) | SMA | 1 | SMAJ12CA-FDICT-ND (268k, Active; API /batch 2026-07-14) | 621-SMAJ12CA-13-F (30k) | $0.84 | **Iter-23 F20: -13 → -13-F (non-F Obsolete)** |
| C7  | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U2 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1, BTN2, BTN3 | **THT tall-actuator tactile** (6×6 mm body, long plunger ~13–17 mm class) | THT | 3 | _verify (height from CP3 stack)_ | _verify_ | $0.30 ea | **Δ (2026-06-23 user call):** real button protruding through the faceplate (no printed caps). Pick the catalog plunger height nearest (PCB-front→faceplate gap + ~2–3 mm) at CP3/CP5 |
| R5, R6, R7 | 1 MΩ 0805 1 % BTN pull-ups | 0805 | 3 | RMCF0805FT1M00CT-ND | 71-CRCW08051M00FKEA | $0.10 ea | **Δ: 10 kΩ → 1 MΩ** (display BTN pull-ups; 1 MΩ, distinct from battery R5 = 1.2 MΩ) |
| C8, C9, C10 | 100 nF X7R debounce caps | 0603 | 3 | (unchanged) | | $0.05 ea | |

### Dev headers

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J-USB | **USB-C receptacle** (native ESP32-S3 USB, board edge) | SMD | 1 | _verify_ | | $0.60 | **Δ (D27): bench/recovery port** — reached by popping the faceplate (no front cutout); routine updates OTA over RS-485. Replaces the USB-OTG pin header |
| U-ESD | USB ESD array (**USBLC6-2SC6Y**) | SOT-23-6 | 1 | 497-11882-2-ND | 511-USBLC6-2SC6Y | $0.30 | **NEW (D27):** ESD clamp on USB-C D+/D−/VBUS. **API-verified 2026-06-25: use `-2SC6Y` (the SC6 is out of stock everywhere)** |
| U3-LDO | 3.3 V LDO (AP2112K-3.3, ~600 mA) | SOT-23-5 | 1 | _verify_ | _verify_ | $0.20 | **NEW (D29):** VBUS→3V3_USB; VBUS-referenced |
| U4-MUX | **TI TPS2116DRLR** priority power mux | **SOT-583 (leadless ⚠)** | 1 | _verify_ TPS2116DRLR | 595-TPS2116DRLR | $0.70 | **NEW (D29):** VIN1=USB-LDO (priority), VIN2=R-78E3.3, OUT=V3V3. No UVLO bypass (display has no U4). **Package SOT-23-6 → SOT-583 (API 2026-06-25)** |
| C_usb1, C_usb2 | LDO in/out 1 µF X7R | 0603 ×2 | 2 | _verify_ | _verify_ | $0.05 ea | **NEW (D29):** LDO caps |
| C_mux | ~47 µF on TPS2116 OUT (V3V3) | 0805/1206 | 1 | _verify_ | _verify_ | $0.10 | **NEW (reviewer F11):** OUT bulk for reverse-current-blocking on USB hot-plug |
| J3  | 4-pin 2.54 mm header (UART debug) | THT | 1 | (same as battery-side J5) | | $0.30 | Internal bench bring-up only |
| J5  | 2-pin 2.54 mm jumper (term lift) | THT | 1 | (same as battery-side J4) | | $0.20 | |

### Mounting / enclosure

| Ref | Part | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-------------|------------|-------|-------|
| —   | US double-gang plastic old-work box | 1 | hardware store | — | $4.00 | User-supplied (Carlon B232ADJ or equivalent) |
| —   | 3D-printed PCB bracket | 1 | — | — | $0.50 (PLA) | User-printed from STEP at CP5 |
| —   | 3D-printed faceplate | 1 | — | — | $1.00 (PLA) | User-printed; user-designed against PCB STEP |
| —   | M3 standoffs + screws | 1 set | — | — | $2.50 | PCB to bracket |
| —   | M2 mounting hardware for e-paper module | 1 | — | — | $2.00 | **Module mounts to the faceplate back** (D27/DR-10) — the ~90–103 mm module doesn't fit inside the ~95 mm box; main PCB sits behind, 8-pin cable between |
| —   | _(button cap extensions removed — using tall-actuator THT tactiles that protrude through the faceplate directly; 2026-06-23 user call)_ | — | — | — | — | See BTN1–3 |

### Display-side subtotal

| Category | Cost |
|----------|------|
| Component + connector line items incl. LCD1 $35 (mechanical sum of this section's price column, 2026-07-14) | ~$59.4 |
| Enclosure + mounting ($4.00 box + $0.50 bracket + $1.00 faceplate + $2.50 M3 + $2.00 M2 = $10.00; corrected iter-25 F25 — was hand-carried at ~$5) | ~$10 |
| **Display-side total** | **~$69** |

---

## Cable & shared

| Item | Qty | Price | Notes |
|------|-----|-------|-------|
| Cat5e patch cable, 30 cm | 1 | $3.00 | Inside enclosures (battery side to in-wall Cat5e) |
| Cat5e patch cable, 30 cm | 1 | $3.00 | Display side to in-wall Cat5e |
| In-wall Cat5e (5 m) | 1 | (user-supplied / already pulled) | $— |
| Cat5e keystone jacks for in-wall termination (×2) | 2 | $4.00 | If not already terminated |

**Shared subtotal: ~$10**

---

## Grand total

| Item | Cost |
|------|------|
| Battery-side board — iter-27 core + iter-48 SSR swap (qty 1, hand-assembled) | ~$84 |
| Display-side board (qty 1, hand-assembled) | ~$69 |
| Cable & shared connectors | ~$10 |
| Bare PCBs from JLCPCB (qty 5 of each board, 2-layer FR-4 HASL, DHL shipping) | ~$30 |
| **core total** | **~$193** |
| **+ D36/D37 delta (pending CP1-delta review)** — see below | **+ ~$58.6** |
| **Single-monitor total (with pending delta)** | **~$251.6** |

**D36/D37 delta (recomputed iter-36 after the F51 switch simplification;
iter-34 F50 fixed the earlier mis-sums $0.40/$0.20):** 2× ADM2587E @
$22.90 = $45.80; 2× RJHSE-5380 battery-read jacks @ $2.30 = $4.60; 2×
isoPower support networks ~$3.00; 2× channel load-switches — now
**direct-GPIO-driven NTR4171P, no 2N7002 (F51; FET re-pinned F56/F57→F61)** — @ $1.13 = **$2.26**;
J_EXP $1.40; Q_exp (same NTR4171P class) **$1.13**; expansion passives
incl. R_exp_bleed + gate pull-ups ~$0.40 → **~$58.6** (recomputed iter-40 after the F61 NTR4171P swap;
iter-38 after the F56/F57 FET replacement; SM712 ×2 +
series-R + PPTC all DNP = $0). *Optional, not in the sum:* PicoBlade
mate cable assembly 0151340801 (**$10.53**, DK WM15273-ND) — order
if/when an add-on is actually built. The core sums above are dated
2026-07-14 (plus the 2N7002LT1G re-pin iter-36 and the **iter-48
gate-driver replacement: Q1 P-FET + Q2 BJT + 5 gate resistors + DZ1 →
one AQY212EH PhotoMOS SSR + R_opto + R_inrush + F2 fuse** — net ≈ **+$6** (added SSR $2.81 + R_opto $0.10 + R_inrush 2×$0.06 = $0.12 + F2 fuse $4.57 ≈ $7.60, less the ~$1.9 discrete gate network removed — the Si2309CDS P-FET alone was ~$1.39; F2 + the SSR dominate), which raises the 2026-07-14
battery-side "~$83" snapshot toward ~$89) and do **not** yet include the
delta; when the CP1-delta is approved it folds into the battery-side
line and the whole column is mechanically recomputed. *(F25: display enclosure/mounting was $5→$10.
Prior ~$145/~$154 predated the U2/BTN1/TVS corrections.)*

Spares for the 4× extra PCBs are essentially free at JLC's minimum-order
pricing. Hand-solder rework on the first build is essentially guaranteed,
so the extras are not wasted.

## Δ summary against the prior `docs/hardware/bom.md`

**Removed** (battery side):
- 1 A ATO fuse + holder (replaced by 5×20 mm cartridge fuse + clips)
- Ring terminals (replaced by Phoenix terminal block)
- LED1 + R_led debug LED (per D4)
- Hammond 1556B2GY enclosure (replaced by Hammond 1591ATBU, smaller and easier to stock)

**Removed** (display side):
- Single-gang low-voltage mounting bracket (replaced by 3D-printed bracket)
- Blank single-gang wall plate (replaced by 3D-printed faceplate)
- LED1 + R_led debug LED (per D4)

**Added** (battery side):
- Phoenix MSTB pluggable terminal block + plug
- 5×20 mm cartridge fuse + 2× PCB-mount fuse clips
- TVS1 = SMAJ33CA on V24_FUSED (D19/DR-2)
- Display-feed load switch: **Panasonic AQY212EH PhotoMOS SSR** (Ron 0.85 Ω typ/2.5 Ω max) in the switched branch V24_FUSED→**F2 (80 mA fuse)**→SSR1→**R_inrush (2× 75 Ω 1206-HP = 150 Ω)**→V24_SW, driven by ESP `PWR_EN` through **R_opto 330 Ω** (~6 mA LED, ≥5 mA worst-case). Replaced the discrete P-FET + gate-driver network (Q1/Q2/R3/Rg/R_base/R_be/DZ1) at iter-48 (F76 resolution) because no discrete driver could be datasheet-guaranteed OFF at temperature. SSR OFF-leakage ≤1 µA @25 °C (spec; hot leakage is an estimate + acceptance test, F83), rated −40…+85 °C, opto-isolated → cannot self-turn-on. **Coordinated switched-branch protection (F84/F86/F87):** R_inrush = 2× 75 Ω 1206-HP series limits the recurring inrush to 0.197 A (below the SSR 0.30 A@85 °C continuous — no one-shot reliance); a V24_SW short (0.197 A worst case) dissipates 2.87 W in each half (< the §8.1 4.69 W/5 s guarantee at P70) and F2 (80 mA) clears it at 246 % — SSR + both R_inrush halves survive to the clear. LED ~20 mW active, 0 in hard-cut.
- ESP EN cap (C8) + pull-up (R7)
- Maintenance: J3 = **USB-C** (native USB, D22) + USB ESD array; J5 (UART) for bring-up
- **Removed** battery-side RS-485 idle bias (now display-end only, D19/DR-4)

**Added** (display side):
- Panel VCC bulk cap (C6)
- ESP EN cap + pull-up
- Display maintenance: J-USB = **USB-C** (native USB, D27) + USB ESD; J3 (UART) + J5 (term-lift) internal for bring-up

**Changed parts/values** (D19 power re-architecture, both sides):
- U1 (3V3): TPS62933 → **LM5166** (always-on, µA-Iq, 65 V) — DR-4
- U2 (12V): R-78E12 → **R-78HB12** (72 V) — DR-3
- Q1/Q2: AO3401A/AO3400A (30 V) → **ZXMP6A13F/2N7002** (60 V) — DR-4, all later superseded; iter-38 F57: ZXMP NRND, superseded by **Si2309CDS** (itself retired at iter-48 → the AQY212EH SSR)
- D1: SS24 (40 V) → **SS26** (60 V) — DR-3
- Input bulk C1/C3 → **100 V** (behind the ~53 V clamp)
- RS-485 bias → **display-end only, ~330 Ω** (battery rail draws 0) — DR-4
- Display-feed switch: discrete P-FET gate network → **AQY212EH PhotoMOS SSR** (iter-48, F76). LED drive **R_opto 330 Ω** (worst-case I_F ≥ 5 mA); switched branch **V24_FUSED→F2 (80 mA fuse)→SSR1→R_inrush (2× 75 Ω = 150 Ω pulse-proof)→V24_SW** — R_inrush limits recurring inrush to 0.197 A (below SSR continuous), the series pair splits the fault power (2.87 W each < §8.1 4.69 W at P70), and the 80 mA F2 clears a downstream short at 246 % (F80/F84/F86/F87). OFF immunity is architectural (no gate divider), not a resistor value (F79).
- 24 V sense divider: 100 kΩ/11 kΩ → 1.2 MΩ/100 kΩ (10× lower idle current; full charge in ADC linear band — DR-6)
- E-paper: 8-pin Waveshare Module (B), J2 → 8-pin header (was 24-pin FFC) — DR-7
- BTN pull-ups: 10 kΩ → 1 MΩ (both sides — Iq reduction)

## Open questions surfaced by this BOM

- **D-OPEN-1** ESP module variant — would standardizing on -N8 save
  $1.50 per board and reduce ESP power slightly? Reviewer to weigh.
- ~~**D-OPEN-8** Display-side bias resistors populated or not?~~
  **RESOLVED (D19/DR-4, revised iter-12 F12):** DNP by default —
  THVD1400 Full Fail-Safe RX (datasheet §8.2.1.4) guarantees RO HIGH on
  open/short/idle bus without external bias, so the 15 mW cost of the
  ~330 Ω bias is not spent. Footprint stays on the PCB; CP5 stuff at
  ~330 Ω if bench testing reveals a specific noise-margin need
  (battery-side bias remains removed regardless to keep the always-on
  rail at zero static draw).
- ~~**D-OPEN-13** Panel-mount switch BTN1 on battery side — does the
  since-retired RP3502MA-series exist in stock with sealed cap (IP67) options?~~
  **RESOLVED then superseded:** the retired RP3502 series page
  offered no sealed/IP67 option; the question is **moot since iter-23
  F22 replaced BTN1 with the C&K 8125SHZBE** (also unsealed — accepted:
  the button lives on the battery-side enclosure lid inside the cabin,
  IP5x indoor per D20). If sealing is ever wanted, change series at
  ordering (e.g. an IP67 vandal-style momentary), not a cap add-on.
- **D-OPEN-14** JLCPCB PCBA option deferred for now (qty 1 → expensive).
  Re-evaluate before a v2 spin if user wants more boards.
