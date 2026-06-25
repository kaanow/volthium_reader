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
| F1_ELEM | 1 A 5×20 mm **time-lag (T)** ceramic cartridge fuse | TH 5×20 mm | 1 | _verify_ | _verify_ | $0.95 | **NEW** — fuse element. **Time-lag (DR-12)**: rides the ~22 µF ceramic inrush; ceramic body = safer in a high-energy DC fault than glass |
| D1  | SS26 Schottky 60 V/2 A | SMA | 1 | _verify_ SS26FACT-ND | 583-SS26 | $0.30 | **Δ (D19/DR-3): SS24 (40 V) → SS26 (60 V)** to out-rate the ~53 V clamp |
| TVS1 | SMAJ33CA bidirectional TVS (Vrwm 33 V) | SMA | 1 | _verify_ SMAJ33CADICT-ND | 78-SMAJ33CA | $0.40 | **Δ (D19/DR-2): SMAJ30CA → SMAJ33CA** — 33 V clears the ~29 V full-charge bus with margin |
| TVS3 | SMAJ15A unidirectional TVS, V12_CAT5E↔GND | SMA | 1 | SMAJ15ADICT-ND | 78-SMAJ15A-E3/61 | $0.30 | **NEW (DR-15):** clamps cable surges on the 12 V Cat5e pair at the **battery** end (matches the display-end SMAJ15A → both ends protected). Zero static draw |

### Power conversion

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U1  | **LM5166YDRCR** (24 V→3.3 V, **always-on** µA-Iq buck, **500 mA**, **fixed 3.3 V**) | VSON-10 | 1 | LM5166**Y**DRCR = fixed 3.3 V (TI Active; YDRCR out-of-stock on TI.com 2026-06-21 — confirm distributor stock at BOM-lock) | 595-LM5166YDRCR | $4 | **Δ (D25): LM5165→LM5166**, fixed-3.3 V = **`LM5166YDRCR`** (reviewer Finding 01: `X`=5 V, `Y`=3.3 V — order **Y**). FB→VOUT, no divider. Fallback: YDRCT cut-tape, else adjustable + divider; **never XDRCR** (5 V) |
| L1  | 10–47 µH ≥0.3 A shielded SMD inductor (per LM5166 datasheet) | SMD | 1 | _verify_ | _verify_ | $0.50 | **Δ: LM5166 inductor** (low-Iq COT favors larger L than the old 2.2 µH) |
| C1, C2 | C1 22 µF / **100 V**, C2 22 µF / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.50 ea | **Δ: C1 →100 V** (LM5166 input on V24_FUSED, behind the ~53 V clamp) |
| U2  | Recom R-78HB12-0.5 buck (24 V→12 V, 0.5 A, 17–72 V in) | SIP3 THT | 1 | R-78HB12-0.5 (DK 2256237, **in stock, Active 2026-06-17**) | 919-R-78HB12-0.5 | $8.00 | **Δ (D19/DR-3): R-78E12 (34 V) → R-78HB12 (72 V)** to survive the clamp. Switched (behind Q1) |
| C3, C4 | C3 22 µF / **100 V**, C4 22 µF / 25 V X7R | 1210 | 2 | _verify_ | _verify_ | $0.55 ea | **Δ: C3 →100 V** (U2 input on V24_SW, behind the clamp) |

### Hard-cut load switch

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| Q1  | ZXMP6A13F P-MOSFET (Vds −60 V, 0.9 A) | SOT-23 | 1 | ZXMP6A13F**TA** (orderable tape&reel; Mouser stock ~75k, API-verified 2026-06-25 — bare ZXMP6A13F shows 0 stock) | 522-ZXMP6A13FTA | $0.40 | **Δ (D19/DR-4): AO3401A (30 V) → ZXMP6A13F (60 V)** to survive the ~53 V clamp when open (~0.3 A load) |
| Q2  | 2N7002 N-MOSFET (Vds 60 V) | SOT-23 | 1 | _verify_ 2N7002 | 512-2N7002 | $0.10 | **Δ (D19/DR-4): AO3400A (30 V) → 2N7002 (60 V)** — drain follows the V24 rail when Q1 is off |
| DZ1 | BZX84C12 12 V Zener (Q1 gate–source clamp) | SOT-23 | 1 | _verify_ BZX84C12 | 512-BZX84C12LT1G | $0.10 | **NEW (D19/DR-4)** — holds Q1 Vgs ≤ 12 V (was driven to −29 V) |
| Rg  | ~1 kΩ 0805 1 % (series gate, Q2 drain → Q1 gate) | 0805 | 1 | _verify_ | _verify_ | $0.10 | **NEW (D19/DR-4)** — works with DZ1 to clamp the gate |
| R3  | 100 kΩ 0805 1 % (Q1 gate pull-up to V24_FUSED) | 0805 | 1 | RMCF0805FT100KCT-ND | 71-CRCW0805100KFKEA | $0.10 | Default-OFF load switch |
| R4  | 100 kΩ 0805 1 % (Q2 gate pull-down to GND) | 0805 | 1 | (same as R3) | (same) | $0.10 | Brown-out failsafe-off |
| U4  | **TI TPS3890** voltage supervisor (~2.1 µA, adj. SENSE, OD RESET, CT delay) | SOT-23-6/SON | 1 | _verify_ TPS389030DSER-family | _verify_ | $0.80 | **NEW (D28/DR-16):** hardware UVLO backstop — asserts ESP EN low below ~20 V pack → reset MCU (~µA) + auto-shed display. Confirm SKU/threshold at BOM-lock |
| R_uv1, R_uv2 | UVLO pack divider → U4 SENSE (**R_total ≈ 2.0 MΩ**, ratio for ~20 V trip) | 0805 ×2 | 2 | _verify_ | _verify_ | $0.10 ea | **NEW (D28); ~2.0 MΩ not 10 MΩ (reviewer F02)** — TPS3890 needs ≥10 µA divider current (≥100× I_SENSE) for accuracy; 20 V/2.0 MΩ = 10 µA at trip |
| R_hys | UVLO external hysteresis, RESET→SENSE (~3.9–4.7 MΩ) | 0805 | 1 | _verify_ | _verify_ | $0.05 | **NEW (reviewer F01):** sets a deliberate ~1.5 V band (trip ~20 V / release ~21.5 V); chip's built-in ~0.12 V is too small (chatter) |
| C_ct | UVLO CT deglitch cap (~tens of ms) | 0603 | 1 | _verify_ | _verify_ | $0.05 | **NEW (D28):** rejects momentary sags |

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
| RTC1 | **Micro Crystal RV-3028-C7 32.768kHz 1ppm TA QA** I²C RTC (45 nA) | 4-pin SMD 3.2×1.5 | 1 | 2195-RV-3028-C732.768KHZ1PPM-TA-QATR-ND | _verify (Mouser)_ | $2.00 | **Δ (D23/DR-8): DS3231 → RV-3028-C7** — 45 nA. **Full orderable MPN corrected (API 2026-06-25):** plain "RV-3028-C7" is ambiguous (QA standard / QC AEC-Q200 / "ON BOARD" = a dev board — avoid). Using **QA**; QC if a wider-grade part is ever wanted |
| C-bk | Small backup cap (~10 mF–0.1 F) on RV-3028 VBACKUP | SMD | 1 | _verify_ | _verify_ | $0.50 | **Δ (D23): replaces CR2032 + holder** — trickle-charged, rides a full disconnect; no coin, no D14 short risk |
| U-ESD | USB ESD array (**USBLC6-2SC6Y**) | SOT-23-6 | 1 | 497-11882-2-ND | 511-USBLC6-2SC6Y | $0.30 | **NEW**: ESD clamp on the external USB-C D+/D−/VBUS (D22). **API-verified 2026-06-25: the original SC6 is out of stock at all sources → use the `-2SC6Y` variant** (DK ~30k, Mouser ~15k; pin-compatible) |
| U5  | 3.3 V LDO (AP2112K-3.3, ~600 mA) | SOT-23-5 | 1 | _verify_ AP2112K-3.3 | _verify_ | $0.20 | **NEW (D29):** VBUS→3V3_USB for USB maintenance power; VBUS-referenced (0 pack draw unplugged) |
| U6  | **TI TPS2116** priority power mux (~1.3 µA Iq, 2.5 A, reverse-blocking) | SOT-23-6 | 1 | _verify_ TPS2116DRLR | _verify_ | $0.70 | **NEW (D29):** VIN1=USB-LDO (priority), VIN2=U1 buck, OUT=V3V3. USB present → buck idles. Only ~1.3 µA always-on |
| Q3  | small signal N-FET, series in U4 RESET→EN (UVLO bypass) | SOT-23 | 1 | _verify_ 2N7002 | 512-2N7002 | $0.10 | **NEW (D29); default-ON via R_byp1→V3V3 (fail-safe, reviewer F03)** — conducts when VBUS absent (UVLO active); opened by Q4 when VBUS present |
| Q4  | small signal N-FET, VBUS-driven Q3-gate pulldown | SOT-23 | 1 | _verify_ 2N7002 | 512-2N7002 | $0.10 | **NEW (reviewer F03):** VBUS present → Q4 ON → Q3 gate to GND → bypass. VBUS-referenced |
| C_usb1, C_usb2 | LDO in/out 1 µF X7R | 0603 ×2 | 2 | _verify_ | _verify_ | $0.05 ea | **NEW (D29):** AP2112 in/out caps |
| C_mux | ~47 µF on TPS2116 OUT (V3V3) | 0805/1206 | 1 | _verify_ | _verify_ | $0.10 | **NEW (reviewer F11):** OUT bulk for reverse-current-blocking on USB hot-plug |
| R_byp1 | Q3 gate pull-up to **V3V3** (100 kΩ) | 0805 | 1 | _verify_ | _verify_ | $0.05 | **NEW (reviewer F03):** sets fail-safe default-ON |
| R_byp2 | VBUS → Q4 gate divider | 0805 | 1 | _verify_ | _verify_ | $0.05 | **NEW (D29):** VBUS-referenced |
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
| J1  | **Right-angle / low-profile RJ45**, shielded | THT shielded | 1 | _verify_ | | $4.00 | **Δ (DR-10): right-angle** — fits the shallow box, Cat5e enters side/bottom |
| F1  | PTC polyfuse, **~0.25 A hold** (e.g. Bourns MF-R025) | THT radial | 1 | _verify_ MF-R025 | 652-MF-R025 | $1.00 | **Δ (DR-11): 0.5 A → ~0.25 A** — matches the ~40–150 mA load, trips below U2 foldback |
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
| MOD1 | ESP32-S3-WROOM-1-N16R8 (`-1`) | SMD module | 1 | (unchanged) | | $6.00 | **D26: radio unused** (RS-485 link) — kept for commonality, RF disabled, antenna keepout dropped |
| C3  | 10 µF X7R | 0805 | 1 | (same as battery-side C6) | | $0.10 | ESP bulk |
| C4  | 100 nF X7R | 0402 or 0603 | 1 | (same as battery-side C7) | | $0.05 | ESP HF |
| C5  | 1 µF X7R | 0603 | 1 | (same as battery-side C8) | | $0.10 | ESP EN soft-start |
| R1  | 10 kΩ 0805 | 0805 | 1 | (same as battery-side R7) | | $0.05 | ESP EN pull-up |

### E-paper

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| LCD1 | Waveshare 4.2inch e-Paper **Module (B)** — tri-color (B/W/R), onboard driver + 8-pin SPI | module | 1 | 1738-1135-ND | 992-19094 | $35.00 | **Δ (DR-7): use the module (8-pin SPI), not a bare panel.** Driver + booster on the module |
| J2  | **JST-PH 2.0 mm 8-pin** post header (B8B-PH-K-S top / S8B-PH-K-S side) — e-paper SPI: VCC/GND/DIN/CLK/CS/DC/RST/BUSY | THT 1×8 | 1 | B8B-PH-K-S → 455-1710-ND (API-verified 2026-06-25; stock ~2900) | 455-B8B-PH-K-S | $0.51 | **Matches the module's PH 2.0 connector (verified).** Same family both sides → pre-crimped PH↔PH cable (user: ASPHSPH24K102-class), no tool. Keyed by design. **Δ (DR-7):** was a 24-pin FH12-24S FFC (bare-panel) |
| C6  | 1 µF X7R panel VCC bulk | 0603 | 1 | (same as C5) | | $0.10 | NEW — reduces VCC dip during refresh |

### RS-485

| Ref | Part | Pkg | Qty | DigiKey SKU | Mouser SKU | Price | Notes |
|-----|------|-----|-----|-------------|------------|-------|-------|
| U2  | SN65HVD3082EDR | SOIC-8 | 1 | (unchanged) | | $1.20 | (unchanged) |
| R2  | 120 Ω 0805 1 % | 0805 | 1 | (same as battery R10) | | $0.10 | Bus terminus |
| R3, R4 | ~330 Ω 0805 1 % idle bias (A→3V3, B→GND) | 0805 | 2 | _verify_ | | $0.10 ea | **POPULATED — the bus's only fail-safe bias (D19/DR-4).** ~330 Ω gives **~275 mV** idle across the two 120 Ω terminators (~38 % over the 200 mV floor; DR-13, was 390 Ω/236 mV). Sourced from display 3V3 (shed with the display at low SOC) |
| TVS2 | SMAJ12CA bidirectional | SMA | 1 | (unchanged) | | $0.30 | |
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
| U4-MUX | **TI TPS2116** priority power mux | SOT-23-6 | 1 | _verify_ TPS2116DRLR | _verify_ | $0.70 | **NEW (D29):** VIN1=USB-LDO (priority), VIN2=R-78E3.3, OUT=V3V3. No UVLO bypass (display has no U4) |
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
- Display maintenance: J-USB = **USB-C** (native USB, D27) + USB ESD; J3 (UART) + J5 (term-lift) internal for bring-up

**Changed parts/values** (D19 power re-architecture, both sides):
- U1 (3V3): TPS62933 → **LM5166** (always-on, µA-Iq, 65 V) — DR-4
- U2 (12V): R-78E12 → **R-78HB12** (72 V) — DR-3
- Q1/Q2: AO3401A/AO3400A (30 V) → **ZXMP6A13F/2N7002** (60 V) — DR-4
- D1: SS24 (40 V) → **SS26** (60 V) — DR-3
- Input bulk C1/C3 → **100 V** (behind the ~53 V clamp)
- RS-485 bias → **display-end only, ~330 Ω** (battery rail draws 0) — DR-4
- Q1 gate pull-up: 10 kΩ → 100 kΩ (10× lower idle current)
- 24 V sense divider: 100 kΩ/11 kΩ → 1.2 MΩ/100 kΩ (10× lower idle current; full charge in ADC linear band — DR-6)
- E-paper: 8-pin Waveshare Module (B), J2 → 8-pin header (was 24-pin FFC) — DR-7
- BTN pull-ups: 10 kΩ → 1 MΩ (both sides — Iq reduction)

## Open questions surfaced by this BOM

- **D-OPEN-1** ESP module variant — would standardizing on -N8 save
  $1.50 per board and reduce ESP power slightly? Reviewer to weigh.
- ~~**D-OPEN-8** Display-side bias resistors populated or not?~~
  **RESOLVED (D19/DR-4):** populated at ~330 Ω — they are the bus's *only*
  fail-safe bias (battery-side bias removed to keep the always-on rail at
  zero static draw).
- **D-OPEN-13** Panel-mount switch BTN1 on battery side — does the
  RP3502MA-series exist in stock with sealed cap (IP67) options? Confirm
  during ordering.
- **D-OPEN-14** JLCPCB PCBA option deferred for now (qty 1 → expensive).
  Re-evaluate before a v2 spin if user wants more boards.
