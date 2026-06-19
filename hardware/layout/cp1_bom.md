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

The **D19/D25 power-chain active parts (U1 LM5166, U2 R-78HB12-0.5,
Q1 ZXMP6A13F) WERE DigiKey stock/lifecycle-checked 2026-06-17** — all in
stock, Active. The remaining SKU columns were written from the prior
pass + working knowledge and are **not yet live-checked**. An earlier CP1
review (Finding 03) flagged several that appear stale:

| Part                          | CP1 SKU (this doc)         | Spotted alternate (verify) |
|-------------------------------|----------------------------|------------------------------------|
| ~~DS3231SN# RTC~~ → RV-3028-C7 | (DS3231 dropped, D23) | RV-3028-C7 — in stock, verified 2026-06-18 |
| SN65HVD3082EDR transceiver    | `296-21908-1-ND`           | `296-31719-1-ND` (~11,546) |

**Action**: At **CP5 procurement**, before clicking ORDER:
1. Visit DigiKey for each line, search the manufacturer part number, and
   capture the current SKU + stock count.
2. If the CP1 SKU here is EOL or out-of-stock, swap to a current SKU for
   the same MPN.
3. Stamp the BOM table with `last verified: YYYY-MM-DD` per line.

CP1 doesn't gate on SKU correctness — design rules and topology don't
depend on the exact reel/cut-tape variant. Procurement-time verification
is CP5's job. The CP1 BOM is "design intent": correct manufacturer
part numbers and packages.

## Order strategy

Two carts:

1. **DigiKey** — single-line vendor for most active parts and the
   Waveshare e-paper (DK carries it). One shipment.
2. **3D-printed bracket + faceplate** — user prints on their own
   printer; STL/STEP files come out of CP5.

JLCPCB order separately (the PCBs themselves; qty 5 each board, bare
PCB no PCBA). DHL shipping; ~$25–35 total for both boards' PCBs.

Total component spend across both boards: **~$110** in single-qty
parts. PCBs add ~$30. Bracket/faceplate are filament cost (~$2).
Grand total **~$145** for one complete monitor (including extras).

---

## Battery-side board

### Power input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes (Δ from prior BOM) |
|-----|------|-----|-----|-------------|------------|-------|--------------------------|
| J1  | Phoenix MSTB 2,5/2-G-5,08 pluggable terminal block (2-pin male header + female plug) | THT 5.08 mm | 1 | **277-1271-ND** + 277-1272-ND (plug) | 651-1755736 + 651-1755503 | $3.50 | **NEW** — replaces ring-terminal + external fuse |
| F1  | 5×20 mm cartridge fuse holder (PCB clip, ×2) | THT clip | 2 | **F1465-ND** | 530-31MJ005H | $0.70 ea | **NEW** — replaces ATO fuse holder. Holds the 1 A cartridge |
| F1_ELEM | 1 A 5×20 mm fast-blow ceramic cartridge fuse | TH 5×20 mm | 1 | **F2380-ND** | 504-0034.1519 | $0.95 | **NEW** — fuse element. Ceramic = safer in high-energy DC fault than glass |
| D1  | SS26 Schottky 60 V/2 A | SMA | 1 | _verify_ SS26FACT-ND | 583-SS26 | $0.30 | **Δ (D19/DR-3): SS24 (40 V) → SS26 (60 V)** to out-rate the ~53 V clamp |
| TVS1 | SMAJ33CA bidirectional TVS (Vrwm 33 V) | SMA | 1 | _verify_ SMAJ33CADICT-ND | 78-SMAJ33CA | $0.40 | **Δ (D19/DR-2): SMAJ30CA → SMAJ33CA** — 33 V clears the ~29 V full-charge bus with margin |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | LM5166 (24 V→3.3 V, **always-on** µA-Iq buck, **500 mA**) | VSON-10 | 1 | LM5166DRCR (adjustable) confirmed @ DigiKey 2026-06-18 | 595-LM5166DRCR | $4 | **Δ (D25): LM5165→LM5166** — 500 mA feeds a WiFi session; ~14 µA Iq keeps hard-cut ~1 mW. Use the **fixed-3.3 V variant if orderable (no divider), else adjustable + a high-impedance FB divider** (~6 µA). Confirm fixed PN at BOM-lock |
| L1  | 10–47 µH ≥0.3 A shielded SMD inductor (per LM5166 datasheet) | SMD | 1 | _verify_ | _verify_ | $0.50 | **Δ: LM5166 inductor** (low-Iq COT favors larger L than the old 2.2 µH) |
| C1, C2 | C1 22 µF / **100 V**, C2 22 µF / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.50 ea | **Δ: C1 →100 V** (LM5166 input on V24_FUSED, behind the ~53 V clamp) |
| U2  | Recom R-78HB12-0.5 buck (24 V→12 V, 0.5 A, 17–72 V in) | SIP3 THT | 1 | R-78HB12-0.5 (DK 2256237, **in stock, Active 2026-06-17**) | 919-R-78HB12-0.5 | $8.00 | **Δ (D19/DR-3): R-78E12 (34 V) → R-78HB12 (72 V)** to survive the clamp. Switched (behind Q1) |
| C3, C4 | C3 22 µF / **100 V**, C4 22 µF / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.55 ea | **Δ: C3 →100 V** (U2 input on V24_SW, behind the clamp) |

### Hard-cut load switch

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| Q1  | ZXMP6A13F P-MOSFET (Vds −60 V, 0.9 A) | SOT-23 | 1 | ZXMP6A13FTA (DK 560639, **in stock, Active 2026-06-17**) | 522-ZXMP6A13F | $0.40 | **Δ (D19/DR-4): AO3401A (30 V) → ZXMP6A13F (60 V)** to survive the ~53 V clamp when open (~0.3 A load) |
| Q2  | 2N7002 N-MOSFET (Vds 60 V) | SOT-23 | 1 | _verify_ 2N7002 | 512-2N7002 | $0.10 | **Δ (D19/DR-4): AO3400A (30 V) → 2N7002 (60 V)** — drain follows the V24 rail when Q1 is off |
| DZ1 | BZX84C12 12 V Zener (Q1 gate–source clamp) | SOT-23 | 1 | _verify_ BZX84C12 | 512-BZX84C12LT1G | $0.10 | **NEW (D19/DR-4)** — holds Q1 Vgs ≤ 12 V (was driven to −29 V) |
| Rg  | ~1 kΩ 0805 1 % (series gate, Q2 drain → Q1 gate) | 0805 | 1 | _verify_ | _verify_ | $0.10 | **NEW (D19/DR-4)** — works with DZ1 to clamp the gate |
| R3  | 100 kΩ 0805 1 % (Q1 gate pull-up to V24_FUSED) | 0805 | 1 | RMCF0805FT100KCT-ND | 71-CRCW0805100KFKEA | $0.10 | Default-OFF load switch |
| R4  | 100 kΩ 0805 1 % (Q2 gate pull-down to GND) | 0805 | 1 | (same as R3) | (same) | $0.10 | Brown-out failsafe-off |

### 24 V sense (always-on)

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| R5  | 1.2 MΩ 0805 1 % (top of divider) | 0805 | 1 | RMCF0805FT1M20CT-ND | 71-CRCW08051M20FKEA | $0.10 | **Δ (DR-6): 1 MΩ → 1.2 MΩ** — full charge → 2.25 V, inside the ESP ADC linear band; also current-limits a surge to ~41 µA |
| R6  | 100 kΩ 0805 1 % (bottom of divider) | 0805 | 1 | RMCF0805FT100KCT-ND | 71-CRCW0805100KFKEA | $0.10 | **Δ (DR-6): 110 kΩ → 100 kΩ** (sets the ratio with R5) |
| C5  | 100 nF X7R | 0603 | 1 | (unchanged) 311-1141-1-ND | 81-GRM188R71H104KA93D | $0.05 | (unchanged) — ADC filter |

### MCU & support

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 | SMD module | 1 | (unchanged) 1965-ESP32-S3-WROOM-1-N16R8-ND | 356-ESP32S3WROOM1N16R8 | $6.00 | (D-OPEN-1: consider -N8 alternative @ $4.50) |
| C6  | 10 µF X7R | 0805 | 1 | (unchanged) 1276-1023-1-ND | 187-GRM21BR61C106KE15L | $0.10 | ESP bulk |
| C7  | 100 nF X7R | 0402 | 1 | 311-1086-1-ND | 81-GRM155R71H104KE14D | $0.05 | **Δ: 0603 → 0402** for ESP HF decoupling close-in (or 0603 if 0402 hard to hand-place) |
| C8  | 1 µF X7R | 0603 | 1 | 311-1361-1-ND | 81-GRM188R71H105KA93D | $0.10 | **NEW** — ESP EN soft-start cap |
| R7  | 10 kΩ 0805 | 0805 | 1 | RMCF0805FT10K0CT-ND | 71-CRCW080510K0FKEA | $0.05 | **NEW** — ESP EN pull-up |
| RTC1 | **Micro Crystal RV-3028-C7** I²C RTC (45 nA) | 4-pin SMD 3.2×1.5 | 1 | RV-3028-C7 (in stock @ DigiKey 2026-06-18) | 727-RV-3028-C7 | $2.00 | **Δ (D23/DR-8): DS3231 → RV-3028-C7** — 45 nA vs ~0.2 mA; ±1 ppm; integrated crystal + backup switchover/trickle charger |
| C-bk | Small backup cap (~10 mF–0.1 F) on RV-3028 VBACKUP | SMD | 1 | _verify_ | _verify_ | $0.50 | **Δ (D23): replaces CR2032 + holder** — trickle-charged, rides a full disconnect; no coin, no D14 short risk |
| U-ESD | USB ESD array (USBLC6-2SC6) | SOT-23-6 | 1 | _verify_ USBLC6-2 | 511-USBLC6-2SC6 | $0.30 | **NEW**: ESD clamp on the external USB-C D+/D−/VBUS (D22) |
| C9  | 100 nF X7R | 0603 | 1 | (unchanged) 311-1141-1-ND | (as C5) | $0.05 | RTC decoupling |
| R8, R9 | 4.7 kΩ 0805 1 % I²C pull-ups | 0805 | 2 | RMCF0805FT4K70CT-ND | 71-CRCW08054K70FKEA | $0.05 ea | I²C bus pull-ups |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U3  | SN65HVD3082EDR | SOIC-8 | 1 | (unchanged) 296-21908-1-ND | 595-SN65HVD3082EDR | $1.20 | (unchanged) |
| R10 | 120 Ω 0805 1 % term resistor | 0805 | 1 | RMCF0805FT120RCT-ND | 71-CRCW0805120RFKEA | $0.10 | (unchanged) |
| — | _(no idle bias on the battery side — D19/DR-4)_ | — | 0 | — | — | — | **Δ: removed battery-side bias.** The always-on rail would otherwise leak ~2.3 mA continuously; bias is now display-end only |
| TVS2 | SMAJ12CA bidirectional TVS | SMA | 1 | (unchanged) SMAJ12CADICT-ND | 78-SMAJ12CA-E3/61 | $0.30 | Δ: renumbered from TVS1 in prior schematic |
| C10 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U3 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1 | E-Switch RP3502MABLK panel-mount SPST NO momentary | Panel-mount | 1 | EG4527-ND | 612-RP3502MABLK | $3.00 | (Δ: was EG1218; RP3502MA-series stocks better) |
| R13 | 1 MΩ 0805 1 % | 0805 | 1 | RMCF0805FT1M00CT-ND | 71-CRCW08051M00FKEA | $0.10 | BTN pull-up (Δ: was 10 kΩ → 1 MΩ for lower Iq) |
| C11 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | Button debounce |

### Connectivity

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J2  | Amphenol RJHSE-538X-MOD RJ45 keystone, shielded | THT shielded | 1 | (unchanged) 207-RJ45-T568B-ND | — | $4.00 | (unchanged) |
| J3  | **USB-C receptacle** (native ESP32-S3 USB) | SMD | 1 | _verify_ | | $0.50 | **Δ (D22): was a USB-OTG pin header** — now a board-edge maintenance port (flash/console/JTAG), accessible without opening. ESD-protected by U-ESD |
| J4  | 2-pin 2.54 mm header, RS-485 term lift jumper | THT | 1 | S1011EC-02-ND | 200-TSW10206TS | $0.20 | NEW |
| J5  | 4-pin 2.54 mm header, debug UART | THT | 1 | (same as J3) | (same) | $0.30 | NEW — dev only |

### Enclosure & mounting

| Ref | Part | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-------------|------------|-------|-------|
| EN1 | **User-3D-printed plastic enclosure, IP5x** (indoors) | 1 | — printed | — | (filament) | **Δ (D20): no commercial box** — wall-mount above the batteries (air gap), sized to the CP3 board outline, with a USB-C port + dust cap |
| —   | M3 standoffs + screws (4 sets, 5 mm board-to-base spacing) | 1 set | 36-9774-ND | — | $2.50 | |
| —   | 24 V hookup wire to pack, 30 cm of 18 AWG | 1 | — | — | $1.00 | User-supplied if they have it |

### Battery-side subtotal

| Category | Cost |
|----------|------|
| Active components | ~$22 |
| Passives | ~$5 |
| Connectors / headers | ~$8 |
| Enclosure | ~$5 |
| Hardware (standoffs, screws) | ~$3 |
| **Battery-side total** | **~$43** |

---

## Display-side board

### Power input + protection

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J1  | Amphenol RJHSE-538X-MOD RJ45 keystone, shielded | THT shielded | 1 | (unchanged) | | $4.00 | Same as battery-side J2 |
| F1  | Bel Fuse 0ZCG0050FF2C PTC polyfuse 0.5 A hold | THT radial | 1 | F1283CT-ND | 650-MF-R050-2 | $1.00 | (unchanged) |
| TVS1 | SMAJ15A unidirectional TVS | SMA | 1 | SMAJ15ADICT-ND | 78-SMAJ15A-E3/61 | $0.30 | (unchanged) |
| C1  | 22 µF / 25 V X7R | 1210 | 1 | (unchanged) | | $0.20 | V12 input bulk |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | Recom R-78E3.3-0.5 (12 V→3.3 V, 0.5 A) | SIP3 THT | 1 | 945-R-78E3.3-0.5 | 919-R-78E3.3-0.5 | $5.00 | (unchanged) |
| C2  | 10 µF X7R | 0805 | 1 | (unchanged) | | $0.10 | V3V3 output bulk |

### MCU & support

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 | SMD module | 1 | (unchanged) | | $6.00 | Same as battery-side; common BOM line |
| C3  | 10 µF X7R | 0805 | 1 | (same as battery-side C6) | | $0.10 | ESP bulk |
| C4  | 100 nF X7R | 0402 or 0603 | 1 | (same as battery-side C7) | | $0.05 | ESP HF |
| C5  | 1 µF X7R | 0603 | 1 | (same as battery-side C8) | | $0.10 | ESP EN soft-start |
| R1  | 10 kΩ 0805 | 0805 | 1 | (same as battery-side R7) | | $0.05 | ESP EN pull-up |

### E-paper

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| LCD1 | Waveshare 4.2inch e-Paper **Module (B)** — tri-color (B/W/R), onboard driver + 8-pin SPI | module | 1 | 1738-1135-ND | 992-19094 | $35.00 | **Δ (DR-7): use the module (8-pin SPI), not a bare panel.** Driver + booster on the module |
| J2  | **8-pin 2.54 mm header** (e-paper SPI: VCC/GND/DIN/CLK/CS/DC/RST/BUSY) | THT 1×8 | 1 | _verify_ 1x8 2.54mm | _verify_ | $0.30 | **Δ (DR-7): was a 24-pin Hirose FH12-24S FFC** (the bare-panel connector). Match pin order to module silk at assembly |
| C6  | 1 µF X7R panel VCC bulk | 0603 | 1 | (same as C5) | | $0.10 | NEW — reduces VCC dip during refresh |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U2  | SN65HVD3082EDR | SOIC-8 | 1 | (unchanged) | | $1.20 | (unchanged) |
| R2  | 120 Ω 0805 1 % | 0805 | 1 | (same as battery R10) | | $0.10 | Bus terminus |
| R3, R4 | ~390 Ω 0805 1 % idle bias (A→3V3, B→GND) | 0805 | 2 | _verify_ | | $0.10 ea | **POPULATED — the bus's only fail-safe bias (D19/DR-4).** ~390 Ω gives 236 mV idle across the two 120 Ω terminators (> 200 mV). Sourced from display 3V3 (shed with the display at low SOC) |
| TVS2 | SMAJ12CA bidirectional | SMA | 1 | (unchanged) | | $0.30 | |
| C7  | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U2 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1, BTN2, BTN3 | C&K PTS525 6×6×4.3 mm tactile SMT | SMT | 3 | 450-1641-ND | 642-TL3300AF260QG | $0.50 ea | (unchanged) |
| R5, R6, R7 | 1 MΩ 0805 1 % BTN pull-ups | 0805 | 3 | RMCF0805FT1M00CT-ND | 71-CRCW08051M00FKEA | $0.10 ea | **Δ: 10 kΩ → 1 MΩ** (display BTN pull-ups; 1 MΩ, distinct from battery R5 = 1.2 MΩ) |
| C8, C9, C10 | 100 nF X7R debounce caps | 0603 | 3 | (unchanged) | | $0.05 ea | |

### Dev headers

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J3  | 4-pin 2.54 mm header (UART debug) | THT | 1 | (same as battery-side J5) | | $0.30 | |
| J4  | 4-pin 2.54 mm header (USB-OTG breakout) | THT | 1 | (same as battery-side J3) | | $0.30 | |
| J5  | 2-pin 2.54 mm jumper (term lift) | THT | 1 | (same as battery-side J4) | | $0.20 | |

### Mounting / enclosure

| Ref | Part | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-------------|------------|-------|-------|
| —   | US double-gang plastic old-work box | 1 | hardware store | — | $4.00 | User-supplied (Carlon B232ADJ or equivalent) |
| —   | 3D-printed PCB bracket | 1 | — | — | $0.50 (PLA) | User-printed from STEP at CP5 |
| —   | 3D-printed faceplate | 1 | — | — | $1.00 (PLA) | User-printed; user-designed against PCB STEP |
| —   | M3 standoffs + screws | 1 set | — | — | $2.50 | PCB to bracket |
| —   | M2 mounting hardware for e-paper | 1 | — | — | $2.00 | Panel to bracket |
| —   | Tactile button cap extensions (3D-printed, optional, ~5 mm tall) | 3 | — | — | $0.10 (PLA) | If standard caps don't reach the faceplate |

### Display-side subtotal

| Category | Cost |
|----------|------|
| Active components | ~$13 |
| Passives | ~$5 |
| E-paper panel | ~$35 |
| Connectors / headers | ~$8 |
| Enclosure + mounting | ~$10 |
| **Display-side total** | **~$71** |

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
| Battery-side board (qty 1, hand-assembled) | $43 |
| Display-side board (qty 1, hand-assembled) | $71 |
| Cable & shared connectors | $10 |
| Bare PCBs from JLCPCB (qty 5 of each board, 2-layer FR-4 HASL, DHL shipping) | $30 |
| **Single-monitor total** | **~$154** |

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
- Q1 gate-source Zener clamp DZ1 (BZX84C12) + series gate Rg (D19/DR-4)
- ESP EN cap (C8) + pull-up (R7)
- Maintenance: J3 = **USB-C** (native USB, D22) + USB ESD array; J5 (UART) for bring-up
- **Removed** battery-side RS-485 idle bias (now display-end only, D19/DR-4)

**Added** (display side):
- Panel VCC bulk cap (C6)
- ESP EN cap + pull-up
- Dev/debug headers J3 (UART), J4 (USB-OTG), J5 (term-lift)

**Changed parts/values** (D19 power re-architecture, both sides):
- U1 (3V3): TPS62933 → **LM5166** (always-on, µA-Iq, 65 V) — DR-4
- U2 (12V): R-78E12 → **R-78HB12** (72 V) — DR-3
- Q1/Q2: AO3401A/AO3400A (30 V) → **ZXMP6A13F/2N7002** (60 V) — DR-4
- D1: SS24 (40 V) → **SS26** (60 V) — DR-3
- Input bulk C1/C3 → **100 V** (behind the ~53 V clamp)
- RS-485 bias → **display-end only, ~390 Ω** (battery rail draws 0) — DR-4
- Q1 gate pull-up: 10 kΩ → 100 kΩ (10× lower idle current)
- 24 V sense divider: 100 kΩ/11 kΩ → 1.2 MΩ/100 kΩ (10× lower idle current; full charge in ADC linear band — DR-6)
- E-paper: 8-pin Waveshare Module (B), J2 → 8-pin header (was 24-pin FFC) — DR-7
- BTN pull-ups: 10 kΩ → 1 MΩ (both sides — Iq reduction)

## Open questions surfaced by this BOM

- **D-OPEN-1** ESP module variant — would standardizing on -N8 save
  $1.50 per board and reduce ESP power slightly? Reviewer to weigh.
- ~~**D-OPEN-8** Display-side bias resistors populated or not?~~
  **RESOLVED (D19/DR-4):** populated at ~390 Ω — they are the bus's *only*
  fail-safe bias (battery-side bias removed to keep the always-on rail at
  zero static draw).
- **D-OPEN-13** Panel-mount switch BTN1 on battery side — does the
  RP3502MA-series exist in stock with sealed cap (IP67) options? Confirm
  during ordering.
- **D-OPEN-14** JLCPCB PCBA option deferred for now (qty 1 → expensive).
  Re-evaluate before a v2 spin if user wants more boards.
