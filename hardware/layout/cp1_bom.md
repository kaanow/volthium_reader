# CP1 — Bill of materials (consolidated)

**Status**: draft, ready for review
**Scope**: every part across both boards, with vendor SKUs, quantities,
and rationale. **This file supersedes [`docs/hardware/bom.md`](../../docs/hardware/bom.md)
where they disagree.**

Conventions:
- Prices = single-quantity from DigiKey US, May 2026, USD. Mouser as backup.
- Where the BOM line is unchanged from the prior pass, it's annotated
  "(unchanged)". Otherwise the delta is called out.
- Spare margin: order **qty 5 of each board's parts** (matches JLCPCB
  PCB minimum order) for hand-solder rework. Some passives (the common
  values) can be shared across boards and ordered in bulk.

## ⚠ SKU verification status

The SKU columns below were written based on the prior pass's `docs/hardware/bom.md`
plus Claude's working knowledge. **They have NOT been live-checked against
DigiKey/Mouser at CP1.** Codex's CP1 review (Finding 03, 2026-05-23) flagged
that several DigiKey SKUs appear stale relative to currently-orderable entries:

| Part                          | CP1 SKU (this doc)         | Codex's spotted alternate (verify) |
|-------------------------------|----------------------------|------------------------------------|
| Hirose FH12-24S-0.5SH(55) FFC | `670-2719-1-ND`            | `HFJ124CT-ND` (~7,533 in stock; please re-verify — `HFJ` prefix is unusual for this Hirose part) |
| DS3231SN# RTC                 | `DS3231SN#-ND`             | `DS3231SN#T&RCT-ND` (~6,609; reel vs cut-tape) |
| SN65HVD3082EDR transceiver    | `296-21908-1-ND`           | `296-31719-1-ND` (~11,546) |

**Action**: At **CP5 procurement**, before clicking ORDER:
1. Visit DigiKey for each line, search the manufacturer part number, and
   capture the current SKU + stock count.
2. If the CP1 SKU here is EOL or out-of-stock, swap to the Codex-flagged
   alternate (or another current SKU for the same MPN).
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
| D1  | SS24-E3/61T Schottky 40 V/2 A | SMA | 1 | (unchanged) SS24FACT-ND | 583-SS24 | $0.30 | (unchanged) |
| TVS1 | SMAJ30CA bidirectional TVS (Vrwm 30 V) | SMA | 1 | **SMAJ30CADICT-ND** | 78-SMAJ30CA-E3/61 | $0.40 | **NEW** — 24 V input transient suppressor. Renamed from prior TVS3 in SKiDL; Vrwm bumped 15→30 V to sit safely above the 28 V max charge voltage |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | TPS62933FDRLR (24 V→3.3 V, fixed, sync buck) | SOT-563 | 1 | (unchanged) 296-50428-1-ND | 595-TPS62933FDRLR | $1.20 | (unchanged) |
| L1  | Murata DFE201610E-2R2M= 2.2 µH 3 A SMD inductor | 2.0×1.6 mm | 1 | (unchanged) 587-3327-1-ND | 875-DFE201610E-2R2M=P2 | $0.50 | (unchanged) |
| C1, C2 | 22 µF / 25 V X7R ceramic | 1210 | 2 | (unchanged) 1276-2920-1-ND | 187-GRM32ER61E226KE15L | $0.40 ea | (unchanged) |
| U2  | Recom R-78E12-1.0 buck (24 V→12 V, 1 A) | SIP3 THT | 1 | (unchanged) 945-R-78E12-1.0 | 919-R-78E12-1.0 | $7.00 | (unchanged) |
| C3, C4 | 22 µF / 35 V X7R ceramic | 1210 | 2 | (unchanged) 1276-2885-1-ND | 187-GRM32ER7YA226KA12L | $0.50 ea | (unchanged) |

### Hard-cut load switch

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| Q1  | AO3401A P-MOSFET (Vds 30 V, 4 A) | SOT-23 | 1 | (unchanged) AO3401ADICT-ND | 833-AO3401A | $0.40 | (unchanged) |
| Q2  | AO3400A N-MOSFET | SOT-23 | 1 | (unchanged) AO3400ADICT-ND | 833-AO3400A | $0.40 | (unchanged) |
| R3  | 100 kΩ 0805 1 % (Q1 gate pull-up to V24_FUSED) | 0805 | 1 | RMCF0805FT100KCT-ND | 71-CRCW0805100KFKEA | $0.10 | **Δ: 10 kΩ → 100 kΩ** (10× idle current reduction) |
| R4  | 100 kΩ 0805 1 % (Q2 gate pull-down to GND) | 0805 | 1 | (same as R3) | (same) | $0.10 | (unchanged value, just renumbered) |

### 24 V sense (always-on)

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| R5  | 1 MΩ 0805 1 % (top of divider) | 0805 | 1 | **RMCF0805FT1M00CT-ND** | 71-CRCW08051M00FKEA | $0.10 | **Δ: 100 kΩ → 1 MΩ** (10× idle current reduction; this is the biggest single power optimization) |
| R6  | 110 kΩ 0805 1 % (bottom of divider) | 0805 | 1 | RMCF0805FT110KCT-ND | 71-CRCW0805110KFKEA | $0.10 | **Δ: 11 kΩ → 110 kΩ** (same ratio, scaled with R5) |
| C5  | 100 nF X7R | 0603 | 1 | (unchanged) 311-1141-1-ND | 81-GRM188R71H104KA93D | $0.05 | (unchanged) — ADC filter |

### MCU & support

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 | SMD module | 1 | (unchanged) 1965-ESP32-S3-WROOM-1-N16R8-ND | 356-ESP32S3WROOM1N16R8 | $6.00 | (D-OPEN-1: consider -N8 alternative @ $4.50) |
| C6  | 10 µF X7R | 0805 | 1 | (unchanged) 1276-1023-1-ND | 187-GRM21BR61C106KE15L | $0.10 | ESP bulk |
| C7  | 100 nF X7R | 0402 | 1 | 311-1086-1-ND | 81-GRM155R71H104KE14D | $0.05 | **Δ: 0603 → 0402** for ESP HF decoupling close-in (or 0603 if 0402 hard to hand-place) |
| C8  | 1 µF X7R | 0603 | 1 | 311-1361-1-ND | 81-GRM188R71H105KA93D | $0.10 | **NEW** — ESP EN soft-start cap |
| R7  | 10 kΩ 0805 | 0805 | 1 | RMCF0805FT10K0CT-ND | 71-CRCW080510K0FKEA | $0.05 | **NEW** — ESP EN pull-up |
| RTC1 | DS3231SN# I²C RTC, TCXO-locked | SOIC-16W | 1 | (unchanged) DS3231SN#-ND | 700-DS3231SN | $7.00 | (unchanged) |
| BAT1 | CR2032 holder (Keystone 1066) | THT | 1 | (unchanged) BK-885-ND | 534-1066 | $0.80 | (unchanged) |
| C9  | 100 nF X7R | 0603 | 1 | (unchanged) 311-1141-1-ND | (as C5) | $0.05 | RTC decoupling |
| R8, R9 | 4.7 kΩ 0805 1 % I²C pull-ups | 0805 | 2 | RMCF0805FT4K70CT-ND | 71-CRCW08054K70FKEA | $0.05 ea | I²C bus pull-ups |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U3  | SN65HVD3082EDR | SOIC-8 | 1 | (unchanged) 296-21908-1-ND | 595-SN65HVD3082EDR | $1.20 | (unchanged) |
| R10 | 120 Ω 0805 1 % term resistor | 0805 | 1 | RMCF0805FT120RCT-ND | 71-CRCW0805120RFKEA | $0.10 | (unchanged) |
| R11, R12 | 680 Ω 0805 1 % idle bias | 0805 | 2 | RMCF0805FT680RCT-ND | 71-CRCW0805680RFKEA | $0.10 ea | (unchanged) |
| TVS2 | SMAJ12CA bidirectional TVS | SMA | 1 | (unchanged) SMAJ12CADICT-ND | 78-SMAJ12CA-E3/61 | $0.30 | Δ: renumbered from TVS1 in prior schematic |
| C10 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U3 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1 | E-Switch RP3502MABLK panel-mount SPST NO momentary | Panel-mount | 1 | EG4527-ND | 612-RP3502MABLK | $3.00 | (Δ: was EG1218; RP3502MA-series stocks better) |
| R13 | 1 MΩ 0805 1 % | 0805 | 1 | (same as R5) | (same) | $0.10 | (Δ: was 10 kΩ → 1 MΩ for lower Iq) |
| C11 | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | Button debounce |

### Connectivity

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| J2  | Amphenol RJHSE-538X-MOD RJ45 keystone, shielded | THT shielded | 1 | (unchanged) 207-RJ45-T568B-ND | — | $4.00 | (unchanged) |
| J3  | 4-pin 2.54 mm header, USB-OTG dev breakout | THT | 1 | S1011EC-04-ND | 200-TSW10406TS | $0.30 | NEW — dev only |
| J4  | 2-pin 2.54 mm header, RS-485 term lift jumper | THT | 1 | S1011EC-02-ND | 200-TSW10206TS | $0.20 | NEW |
| J5  | 4-pin 2.54 mm header, debug UART | THT | 1 | (same as J3) | (same) | $0.30 | NEW — dev only |

### Enclosure & mounting

| Ref | Part | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-------------|------------|-------|-------|
| EN1 | Hammond 1591ATBU plastic enclosure 62×35×17 mm | 1 | HM5189-ND | 546-1591ATBU | $5.00 | Δ: 1556B2GY → 1591ATBU (smaller, cheaper, easier to stock) |
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
| LCD1 | Waveshare 4.2" e-Paper Module (B) v2, tri-color (B+W+R) | bare panel + ribbon | 1 | 1738-1135-ND | 992-19094 | $35.00 | (unchanged display, but we no longer use the HAT — only the panel) |
| J2  | Hirose FH12-24S-0.5SH(55) FFC connector | SMT top-contact | 1 | 670-2719-1-ND | 798-FH12-24S-0.5SH(55) | $1.00 | (unchanged) |
| C6  | 1 µF X7R panel VCC bulk | 0603 | 1 | (same as C5) | | $0.10 | NEW — reduces VCC dip during refresh |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U2  | SN65HVD3082EDR | SOIC-8 | 1 | (unchanged) | | $1.20 | (unchanged) |
| R2  | 120 Ω 0805 1 % | 0805 | 1 | (same as battery R10) | | $0.10 | Bus terminus |
| R3, R4 | 680 Ω 0805 1 % idle bias | 0805 | 2 | (same as battery R11/R12) | | $0.10 ea | **CP1: footprints provided, depopulated by default** (see D-OPEN-8) |
| TVS2 | SMAJ12CA bidirectional | SMA | 1 | (unchanged) | | $0.30 | |
| C7  | 100 nF X7R | 0603 | 1 | (unchanged) | | $0.05 | U2 decoupling |

### User input

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| BTN1, BTN2, BTN3 | C&K PTS525 6×6×4.3 mm tactile SMT | SMT | 3 | 450-1641-ND | 642-TL3300AF260QG | $0.50 ea | (unchanged) |
| R5, R6, R7 | 1 MΩ 0805 1 % BTN pull-ups | 0805 | 3 | (same as R5 on battery side) | | $0.10 ea | **Δ: 10 kΩ → 1 MΩ** |
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
- TVS1 = SMAJ30CA on V24_FUSED
- ESP EN cap (C8) + pull-up (R7)
- Dev/debug headers J3 (USB-OTG), J4 (term-lift), J5 (UART)

**Added** (display side):
- Panel VCC bulk cap (C6)
- ESP EN cap + pull-up
- Dev/debug headers J3 (UART), J4 (USB-OTG), J5 (term-lift)

**Changed values** (both sides):
- Q1 gate pull-up: 10 kΩ → 100 kΩ (battery side, 10× lower idle current)
- 24 V sense divider: 100 kΩ/11 kΩ → 1 MΩ/110 kΩ (10× lower idle current)
- BTN pull-ups: 10 kΩ → 1 MΩ (both sides — Iq reduction)

## Open questions surfaced by this BOM

- **D-OPEN-1** ESP module variant — would standardizing on -N8 save
  $1.50 per board and reduce ESP power slightly? Reviewer to weigh.
- **D-OPEN-8** Display-side bias resistors populated or not?
- **D-OPEN-13** Panel-mount switch BTN1 on battery side — does the
  RP3502MA-series exist in stock with sealed cap (IP67) options? Confirm
  during ordering.
- **D-OPEN-14** JLCPCB PCBA option deferred for now (qty 1 → expensive).
  Re-evaluate before a v2 spin if user wants more boards.
