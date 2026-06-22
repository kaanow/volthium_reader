# Bill of Materials

> This is the **procurement / shopping** view (distributor methodology +
> substitution notes). For the **complete per-reference-designator
> engineering BOM**, see [`hardware/layout/cp1_bom.md`](../../hardware/layout/cp1_bom.md).
> Both are reconciled to D19/DR-6/DR-7; a single merged BOM lands at CP2
> when the schematic regen sets final reference designators.

> **How to read the distributor columns:**
>
> - `[DK <id>](...)` ✓ — verified against the live Digi-Key catalog
>   2026-06-03. The bracketed identifier is the Digi-Key product
>   detail page numeric ID, which is a stable internal reference.
>   Click the link, confirm stock, copy the manufacturer PN into your
>   cart. Where an older `<digit>-<part>-ND` PN is still in use, it's
>   noted in the cell.
> - `[search …](...)` — manufacturer-part-keyed search URL for rows
>   where the canonical orderable PN is one of many compatible parts
>   (e.g. any 0805 0.1 µF X7R 16 V ceramic works; the `Part` column
>   names one example).
> - `[Mouser](...)` — search URL into Mouser's catalog, keyed on the
>   manufacturer PN. Not individually verified; treat as starting point.
>
> The verified-PN sweep (D-OPEN-6) was completed for this revision on
> 2026-06-03 — every active-device row plus the high-value connectors
> and the enclosure was clicked through. Two manufacturer corrections
> caught in the process:
>
> - **F1 (display)** — was listed as "Bel Fuse MF-R050"; the MF-R
>   series is actually **Bourns**.
> - **EN1 (battery)** — was listed as "Hammond 1556B2GY"; that PN
>   does not exist in Hammond's catalog (no 1556 series). Updated to
>   reference the real **1554 IP66 family** with both candidate sizes
>   linked, pending the user's final pick (see the row's Notes).
>
> Generic-spec rows (resistors, capacitors, inductors meeting a value
> + package spec) keep search URLs because the `Part` column names
> one example, not a binding choice — any compliant part works.

Two columns where reasonable: "Proto" (build on a breadboard / dev board
for early bring-up) and "PCB" (custom board for permanent install). The
PCB column assumes Digi-Key / Mouser ordering and SMT parts where it
makes sense; through-hole stays for anything you'd realistically replace
in the field.

Prices are May 2026 (US, single quantity, indicative). Distributor
catalogs drift week-to-week — both the price and the specific
distributor PN behind a search URL may change.

## Battery-side board

> **Battery-side reflects decisions.md D19–D25** (CP1 re-architecture +
> design-discussion calls, 2026-06). The MCU is on an always-on µA-Iq rail
> (U1 LM5166); the load switch (Q1) sheds only the 12 V/display feed (U2).
> Parts changed from the pre-D19 design: U1 (TPS62933→LM5165→**LM5166** 500 mA,
> for WiFi — D25), U2 (R-78E12→R-78HB12), Q1 (AO3401A→ZXMP6A13F), Q2
> (AO3400A→2N7002), D1 (SS24→SS26), input bulk caps →100 V, sense divider
> →1.2 M/100 k (DR-6), gate-clamp Zener (DZ1), **RTC DS3231→RV-3028-C7 +
> backup cap** (D23/DR-8), **MOD1 −1U→−1 PCB antenna** (D21), **USB-OTG
> header→USB-C** (D22), **enclosure→3D-printed IP5x** (D20).
> **Reference designators here track the pre-regen schematic and are
> finalized when the CP2 schematic is regenerated against D19** (DR-5); the
> *parts* are the binding CP1 baseline.

### Always-on / power

| Ref       | Part                                                  | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| MOD1      | **Espressif ESP32-S3-WROOM-1-N16R8** (16 MB flash, 8 MB PSRAM) | SMD     | 1   | both        | [search ESP32-S3-WROOM-1-N16R8](https://www.digikey.com/en/products/result?keywords=ESP32-S3-WROOM-1-N16R8) | [Mouser](https://www.mouser.com/c/?q=ESP32-S3-WROOM-1-N16R8) | $6     | **`-1` (PCB antenna)** per D21 — plastic batteries + plastic box → no need for the external `-1U`. Needs the 15×6 mm antenna keepout. Serves BLE + WiFi (D25). |
| U1        | **TI LM5166XDRCR** ultra-low-Iq sync buck (24 → 3.3 V, **always-on**, **fixed 3.3 V**) | VSON-10 | 1   | PCB         | [search LM5166X](https://www.digikey.com/en/products/result?keywords=LM5166X) | [Mouser](https://www.mouser.com/c/?q=LM5166XDRCR) | $4 | 3–65 V in, **~14 µA Iq**, **500 mA** — feeds a duty-cycled WiFi session (D25); 65 V out-rates the 53.3 V clamp (D19/DR-4). **Resolved 2026-06-21:** the **fixed-3.3 V `LM5166XDRCR`** exists and is stocked @ Mouser → FB→VOUT, **no divider**. Confirm stock + price at BOM-lock. |
|           | *or, for proto:* Pololu D24V5F3 module                | TH      | 1   | Proto       | [Pololu 2842](https://www.pololu.com/product/2842) | —      | $7     | Convenient 3.3 V buck for bring-up (does not match the low-Iq budget) |
| U2        | **Recom R-78HB12-0.5** SIP3 buck (24 → 12 V, 0.5 A, 17–72 V in) | SIP3    | 1   | both        | [search R-78HB12-0.5](https://www.digikey.com/en/products/result?keywords=R-78HB12-0.5) | [Mouser](https://www.mouser.com/c/?q=R-78HB12-0.5) | $8     | Cat5e/display feed, **switched** (behind Q1). 72 V in tolerates the ~53 V TVS clamp (D19/DR-3). Was R-78E12 (34 V) — under-rated. |
| C1, C2    | C1 22 µF / **100 V**, C2 22 µF / 25 V X7R ceramic     | 1210    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=22uF+100V+1210+X7R) | [search](https://www.mouser.com/c/?q=22uF%20100V%201210%20X7R) | $0.80  | LM5166 input (C1, on V24_FUSED behind the ~53 V clamp → 100 V) / output (C2, 3.3 V). A bulk cap on 3V3 also buffers WiFi TX peaks (D25). |
| C3, C4    | C3 22 µF / **100 V**, C4 22 µF / 25 V X7R ceramic     | 1210    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=22uF+100V+1210+X7R) | [search](https://www.mouser.com/c/?q=22uF%20100V%201210%20X7R) | $0.90  | U2 (R-78HB12) input (C3, on V24_SW behind the clamp → 100 V) / 12 V output (C4). |
| L1        | inductor per LM5166 datasheet (≥0.6 A for 500 mA out) | SMD     | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=22uH+inductor+shielded) | [search](https://www.mouser.com/c/?q=22uH%20inductor%20shielded) | $0.50  | LM5166 buck inductor (sized for 500 mA / WiFi). |
| F1        | 1 A fast-blow 5×20 mm fuse + holder                   | TH      | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=5x20mm+fuse+holder+1A+fast) | [search](https://www.mouser.com/c/?q=5x20mm%20fuse%20holder%201A%20fast) | $3     | On the 24 V tap. |
| TVS1      | **Littelfuse SMAJ33CA** bidirectional TVS (33 V Vrwm) | SMA     | 1   | PCB         | [search SMAJ33CA](https://www.digikey.com/en/products/result?keywords=SMAJ33CA) | [search](https://www.mouser.com/c/?q=SMAJ33CA) | $0.30  | Surge clamp on V24_FUSED (~53 V clamp). 33 V clears the ~29 V full-charge bus (D19/DR-2). |
| D1        | **Vishay SS26** 60 V / 2 A Schottky                   | SMA     | 1   | PCB         | [search SS26](https://www.digikey.com/en/products/result?keywords=SS26+Schottky+SMA) | [search](https://www.mouser.com/c/?q=SS26%20Schottky%20SMA) | $0.30  | Series reverse-polarity on 24 V input. 60 V (was SS24/40 V) to out-rate the ~53 V clamp (D19/DR-3). |

### MCU support

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| RTC1      | **Micro Crystal RV-3028-C7** I²C RTC (e.g. `…1ppm TA-QC`) | 4-pin SMD 3.2×1.5 | 1 | PCB         | [search RV-3028-C7](https://www.digikey.com/en/products/result?keywords=RV-3028-C7) | [Mouser](https://www.mouser.com/c/?q=RV-3028-C7) | $2     | **D23:** 45 nA ultra-low-power, ±1 ppm RT / ±3 ppm, integrated crystal, built-in backup switchover + trickle charger. Replaces the DS3231 (~0.2 mA TCXO was the dominant idle load — DR-8). −40…+85 °C. **In stock @ DigiKey/Mouser (checked 2026-06-18).** |
| U-ESD     | **USB ESD array** (e.g. USBLC6-2SC6) on the USB-C D+/D−/VBUS | SOT-23-6 | 1 | PCB         | [search USBLC6-2](https://www.digikey.com/en/products/result?keywords=USBLC6-2) | [Mouser](https://www.mouser.com/c/?q=USBLC6-2) | $0.30  | Protects the *externally-accessible* USB-C port (D22) — the exposed connector should have a dedicated ESD clamp, not just the ESP's internal protection. Jellybean. |
| C-bk      | Small backup cap (~10 mF–0.1 F) on RV-3028 VBACKUP | SMD  | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=0.1F+supercap) | [Mouser](https://www.mouser.com/c/?q=0.1F%20supercap) | $0.50  | **D23:** trickle-charged by the RTC; rides a full pack disconnect (45 nA → weeks). Replaces the CR2032 + Keystone holder — no coin, no D14 short risk. |
| C5, C6    | 100 nF X7R                                      | 0603    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=100nF+0603+X7R+25V) | [search](https://www.mouser.com/c/?q=100nF%200603%20X7R%2025V) | $0.05  | RTC + ESP decoupling. |
| C7        | 10 µF X7R                                       | 0805    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=10uF+0805+X7R+16V) | [search](https://www.mouser.com/c/?q=10uF%200805%20X7R%2016V) | $0.10  | ESP32 bulk. |

### RS-485

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| U3        | **TI SN65HVD3082EDR** half-duplex, 3.3 V        | SOIC-8  | 1   | both        | [DK 1574525](https://www.digikey.com/en/products/detail/texas-instruments/SN65HVD3082EDR/1574525) ✓ | [Mouser](https://www.mouser.com/c/?q=SN65HVD3082EDR) | $1.20  | ESD-protected, slew-rate-limited. |
| R1        | 120 Ω 1 % RS-485 termination (e.g. Vishay CRCW0805120RFKEA) | 0805    | 1   | both        | [search CRCW0805120RFKEA](https://www.digikey.com/en/products/result?keywords=CRCW0805120RFKEA) | [Mouser](https://www.mouser.com/c/?q=CRCW0805120RFKEA) | $0.10  | Bus terminator. Generic spec — any compliant 0805 120 Ω 1 % works. |
| R2, R3    | 680 Ω 1 % bias (e.g. Vishay CRCW0805680RFKEA)   | 0805    | 2   | PCB         | [search CRCW0805680RFKEA](https://www.digikey.com/en/products/result?keywords=CRCW0805680RFKEA) | [Mouser](https://www.mouser.com/c/?q=CRCW0805680RFKEA) | $0.10  | Idle-state bias to A/B. |
| TVS (A/B) | **Littelfuse SMAJ12CA** bidirectional TVS       | SMA     | 1   | PCB         | [DK 762271](https://www.digikey.com/en/products/detail/littelfuse-inc/SMAJ12CA/762271) ✓ | [Mouser](https://www.mouser.com/c/?q=SMAJ12CA) | $0.30  | Surge/ESD on the RS-485 A/B pair (schematic refdes TVS2). |
| —         | *(24 V input surge TVS is SMAJ33CA — see the power table above. The 12 V Cat5e feed is surge-clamped at the **display** end, where it arrives over 5 m of cable — see display-side TVS1.)* | — | — | — | — | — | No separate SMAJ15A on the battery side. |

### Hard-cut, override, sensing

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| Q1        | **Diodes ZXMP6A13F** P-MOSFET (Vds −60 V, 0.9 A) | SOT-23  | 1   | PCB         | [search ZXMP6A13F](https://www.digikey.com/en/products/result?keywords=ZXMP6A13F) | [Mouser](https://www.mouser.com/c/?q=ZXMP6A13F) | $0.40  | Load switch for the 12 V/display feed (~0.3 A). 60 V out-rates the ~53 V clamp (D19/DR-4). Was AO3401A (30 V). **In stock @ DigiKey, Active (checked 2026-06-17).** |
| Q2        | **2N7002** N-MOSFET (Vds 60 V)                  | SOT-23  | 1   | PCB         | [search 2N7002](https://www.digikey.com/en/products/result?keywords=2N7002) | [Mouser](https://www.mouser.com/c/?q=2N7002) | $0.10  | Drives Q1's gate from 3.3 V. 60 V because its drain follows the V24 rail (D19/DR-4). Was AO3400A (30 V). |
| DZ1       | **BZX84C12** 12 V Zener (Q1 gate–source clamp)  | SOT-23  | 1   | PCB         | [search BZX84C12](https://www.digikey.com/en/products/result?keywords=BZX84C12) | [Mouser](https://www.mouser.com/c/?q=BZX84C12) | $0.10  | Holds Q1 Vgs ≤ 12 V regardless of bus voltage (D19/DR-4). New part. |
| R3, R4    | 100 kΩ 1 % — Q1 gate pull-up (R3, gate→source) + PWR_EN pull-down (R4) | 0805 ×2 | 2 | PCB | [search](https://www.digikey.com/en/products/result?keywords=100k+0805+1%25) | [search](https://www.mouser.com/c/?q=100k%200805%201%25) | $0.10  | Default-OFF load switch + brown-out failsafe-off. A ~1 kΩ series gate resistor (Rg) sits between Q2 drain and Q1 gate (works with DZ1). |
| R5, R6    | 1.2 MΩ / 100 kΩ — 24 V → ~2.25 V sense divider  | 0805 ×2 | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=1.2M+100k+0805+1%25) | [search](https://www.mouser.com/c/?q=1.2M%20100k%200805%201%25) | $0.10  | 24 V sense on ADC1_CH0 (GPIO1). Full charge (29.2 V) → **2.25 V**, inside the ESP ADC linear band (DR-6). High-impedance (~19 µA) for power-first; the 1.2 MΩ top also current-limits a ~53 V surge to ~41 µA. C5 (100 nF) tank. Always-on. |
| BTN1      | Panel-mount override pushbutton (e.g. E-Switch EG1218) | TH      | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=EG1218) | [search](https://www.mouser.com/c/?q=EG1218) | $2     | On battery-side enclosure; jumps ULP to wake state. |
| C8        | 100 nF debounce                                 | 0603    | 1   | PCB         | (as C5) | (as C5) | $0.05  |  |

### Interconnect / enclosure

| Ref       | Part                                            | Qty | DigiKey | Mouser | Price | Notes |
|-----------|-------------------------------------------------|-----|---------|--------|-------|-------|
| J1        | **Amphenol RJHSE5380** RJ45 jack (Cat5e, T568B) | 1   | [search](https://www.digikey.com/en/products/result?keywords=RJHSE5380) | [search](https://www.mouser.com/c/?q=RJHSE5380) | $4    | Patch from this to in-wall Cat5e, or hardwire. This is the footprint the PCB targets. |
| J2        | 2-pin terminal block 5.08 mm pitch (24 V)       | 1   | [search](https://www.digikey.com/en/products/result?keywords=Phoenix+MKDS+5.08+2+pin) | [search](https://www.mouser.com/c/?q=Phoenix%20MKDS%205.08%202%20pin) | $1    | Ring-terminal lugs land here from the battery. PCB uses Phoenix MKDS-1,5-2 family. |
| EN1       | **User-3D-printed plastic enclosure**, IP5x (indoors) | 1   | — (printed) | — | — | (filament) | **D20:** wall-mount above the batteries with an air gap; sized to the final board outline (set at CP3). Has a board-edge port for the USB-C maintenance connector (dust cap). No commercial box / no IP65–66. |
| —         | M3 standoffs + screws                           |     | (any)   | (any)  | $2    |  |
| —         | Cat5e patch cable, 30 cm                        | 1   | (any)   | (any)  | $3    | Inside the enclosure |

### Battery-side subtotal (PCB version, single qty): **~$45** in components, ~$60 with enclosure + connectors.

## Display-side board

### Power

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| U1        | **Recom R-78E3.3-0.5** SIP3 buck (12 V → 3.3 V, 0.5 A) | SIP3    | 1   | both        | [945-1661-5-ND](https://www.digikey.com/en/products/detail/recom-power/R-78E3.3-0.5/3593412) | [search](https://www.mouser.com/c/?q=R-78E3.3-0.5) | $5     | 80 % eff. at 200 mA. Digi-Key PN verified. |
| F1        | **Bourns MF-R025** PTC resettable fuse, **~0.25 A hold** (DR-11) | TH      | 1   | both        | [search MF-R025](https://www.digikey.com/en/products/result?keywords=MF-R025) | [Mouser](https://www.mouser.com/c/?q=MF-R025) | $1     | On the 12 V Cat5e feed. **Δ (DR-11): 0.5 A → ~0.25 A** — matches the ~40–150 mA display load and trips below the battery-side U2 ~0.5 A foldback (the 0.5 A part was too loose for real cable protection). |
| TVS1      | SMAJ15A on 12 V input                           | SMA     | 1   | PCB         | (as battery TVS2) | (as battery TVS2) | $0.30  |  |
| C1        | 22 µF / 25 V X7R                                | 1210    | 1   | PCB         | (as battery C1) | (as battery C1) | $0.20  | Input bulk |
| C2        | 10 µF X7R                                       | 0805    | 1   | PCB         | (as battery C7) | (as battery C7) | $0.10  | 3.3 V output bulk |

### MCU support

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| MOD1      | **Espressif ESP32-S3-WROOM-1-N16R8** (`-1`, display side) | SMD     | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=ESP32-S3-WROOM-1-N16R8) | [Mouser](https://www.mouser.com/c/?q=ESP32-S3-WROOM-1-N16R8) | $6     | **D26: radio unused** — RS-485 is the only link; kept for firmware/footprint commonality, RF disabled, **antenna keepout dropped**. Common firmware base. |
| J-USB     | **USB-C receptacle** (native ESP32-S3 USB, board edge) | SMD | 1 | PCB | [search USB-C receptacle](https://www.digikey.com/en/products/result?keywords=USB-C+receptacle+16pin) | [Mouser](https://www.mouser.com/c/?q=USB-C%20receptacle) | $0.60 | **D27:** bench/recovery port — reached by popping the faceplate (no front cutout). Routine updates are OTA over RS-485. |
| U-ESD     | **USB ESD array** (USBLC6-2SC6)                 | SOT-23-6 | 1   | PCB         | [search USBLC6-2](https://www.digikey.com/en/products/result?keywords=USBLC6-2) | [Mouser](https://www.mouser.com/c/?q=USBLC6-2) | $0.30  | ESD clamp on the USB-C D+/D−/VBUS (D27). Jellybean. |
| R1        | 10 kΩ ESP32 EN pull-up                          | 0805    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=10k+0805+1%25) | [search](https://www.mouser.com/c/?q=10k%200805%201%25) | $0.05  |  |
| C3        | 10 µF X7R MOD1 V3V3 bulk                        | 0805    | 1   | PCB         | (as C2) | (as C2) | $0.10  | Close to the ESP32 module 3V3 pin |
| C4        | 100 nF X7R MOD1 V3V3 HF                         | 0402    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=100nF+0402+X7R+16V) | [search](https://www.mouser.com/c/?q=100nF%200402%20X7R%2016V) | $0.05  | The 0402 close-in cap — smaller package fits inside MOD1's pad row |
| C5        | 1 µF ESP_EN soft-start                          | 0603    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=1uF+0603+X7R) | [search](https://www.mouser.com/c/?q=1uF%200603%20X7R) | $0.05  | Paired with R1 forms the EN power-on delay. |
| C6        | 1 µF panel VCC bulk                             | 0603    | 1   | PCB         | (as C5) | (as C5) | $0.05  | Reduces VCC dip during EPD refresh |
| C7        | 100 nF U2 V3V3 decoupling                       | 0603    | 1   | PCB         | (as battery C5) | (as battery C5) | $0.05  | At the RS-485 transceiver |

### Display

| Ref       | Part                                                | Pkg        | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-----------------------------------------------------|------------|-----|-------------|---------|--------|--------|-------|
| LCD1      | **Waveshare 4.2inch e-Paper Module (B)** — tri-color B/W/R, 400×300, **onboard driver PCB + 8-pin SPI** header | module | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=Waveshare+4.2+e-Paper+B+V2) | [search](https://www.mouser.com/c/?q=Waveshare%204.2%20e-Paper%20B%20V2) | $35    | Connects to **J2 (8-pin)** via its included cable: VCC/GND/DIN/CLK/CS/DC/RST/BUSY (DR-7). **Primary source:** [waveshare.com/4.2inch-e-paper-module-b.htm](https://www.waveshare.com/4.2inch-e-paper-module-b.htm). **Not** the bare `WFT0420CZ15` panel — that's a raw 24-pin-FPC display needing an on-board booster network. |
| J2        | **8-pin 2.54 mm header** (e-paper SPI: VCC/GND/DIN/CLK/CS/DC/RST/BUSY) | THT 1×8 | 1   | PCB         | [search 1x8 2.54mm header](https://www.digikey.com/en/products/result?keywords=1x8+header+2.54mm) | [Mouser](https://www.mouser.com/c/?q=1x8%20header%202.54mm) | $0.30  | Mates the Module (B) 8-pin cable. **Δ (DR-7): was a 24-pin Hirose FH12-24S FFC** — that's the *bare-panel* connector and would need a booster network we don't carry. Match physical pin order to the module silk at assembly. |

### RS-485

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| U2        | **TI SN65HVD3082EDR**                           | SOIC-8  | 1   | both        | (as battery U3) | (as battery U3) | $1.20  |  |
| R2        | 120 Ω 1 % termination                           | 0805    | 1   | both        | (as battery R1) | (as battery R1) | $0.10  | RS-485 term |
| R3, R4    | 680 Ω idle bias                                 | 0805 ×2 | 2   | PCB         | (as battery R2) | (as battery R2) | $0.10  |  |
| TVS2      | SMAJ12CA                                        | SMA     | 1   | PCB         | (as battery TVS1) | (as battery TVS1) | $0.30  | RS-485 ESD |

### Buttons + interconnect

| Ref       | Part                                            | Qty | DigiKey | Mouser | Price | Notes |
|-----------|-------------------------------------------------|-----|---------|--------|-------|-------|
| BTN1–3    | 6×6 mm tactile switch, **tall actuator / printed cap extension** (e.g. E-Switch TL3300) | 3   | [search](https://www.digikey.com/en/products/result?keywords=TL3300+tactile+switch) | [search](https://www.mouser.com/c/?q=TL3300%20tactile%20switch) | $0.50 | Software-defined (on-screen labels, D7). Cap height spans the PCB→faceplate gap (DR-10). |
| J1        | **Right-angle / low-profile RJ45** jack (T568B, shielded) | 1   | [search RJ45 right angle shielded](https://www.digikey.com/en/products/result?keywords=RJ45+right+angle+shielded) | (Mouser) | $4    | **Δ (DR-10):** right-angle so it doesn't eat the shallow-box depth; in-wall Cat5e enters from the side/bottom. |
| —         | **3D-printed bracket + faceplate** (user-printed, D8/D20/D27) — **double-gang** | 1   | (printed) |     | (filament) | Replaces the single-gang plate (stale). E-paper module mounts to the faceplate back; main PCB to the bracket; designed against the PCB STEP. |

### Display-side subtotal (PCB version): **~$55** in components, ~$65 with the mounting bits.

## Grand totals

| Build                          | Battery-side | Display-side | Cable / connectors | Total |
|--------------------------------|--------------|--------------|--------------------|-------|
| Proto (dev boards + breakouts) | ~$55         | ~$65         | ~$10               | **~$130** |
| Custom PCB (qty 1 of each)     | ~$60         | ~$65         | ~$10               | **~$135** |
| Custom PCB w/ a spare e-paper  | "            | +$35         | "                  | **~$170** |

Add ~$50–80 for PCB fab (e.g. JLCPCB qty 5 of each board, 2-layer, HASL,
ENIG slightly more).

## Substitutions worth noting

- **Always-on buck (U1)**: must be **both** ≥60 V input (to survive the
  ~53 V TVS clamp on V24_FUSED) **and** µA-class Iq (so the always-on rail
  costs ~nothing at low SOC). The LM5166 (3–65 V, ~14 µA Iq, 500 mA) hits both;
  that combination is rare. Alternatives: LM5166, MAX17552 (60 V, ~28 µA).
  A plain brick (R-78 family) is *not* suitable here — bricks idle at
  milliamps, which would make the always-on trickle tens of mW (D19/DR-4).
- **Switched 12 V buck (U2)**: a wide-input (≥60 V) module to survive the
  clamp; R-78HB12 chosen for stock + footprint continuity with the
  display's R-78E3.3. Iq doesn't matter here — it's off at low SOC.
- **RS-485 transceiver**: any 3.3 V half-duplex, slew-rate-limited part is
  fine. MAX3485 is the obvious other choice; slightly higher current draw.
- **E-paper**: if 4.2" tri-color goes out of stock, the same Waveshare 4.2"
  monochrome (B/W) is more available — the FW abstracts panel color depth.
  The Pervasive Displays EXT3-1 panels are nicer but harder to source.
- **MCU**: ESP32-S3 was chosen for BLE 5 + USB-OTG + low deep-sleep. An
  nRF52840 module would work too but the Bluedroid/NimBLE story is more
  established on ESP-IDF.

## Procurement methodology

Treat this file as a **shopping starting point**, not a binding cart. The
distributor-search links are deterministic given the manufacturer PN; the
specific product they resolve to may vary as distributor catalogs churn.

Before placing a JLCPCB order or pulling distributor carts:

1. Click each distributor link, scan the live result, and confirm:
   - The first hit (or one of the top hits) matches the manufacturer PN
     exactly — including suffix (`-X9` RoHS variant, `#` industrial-temp
     grade, `EDR` SOIC-8 reel suffix, etc.).
   - Stock and lead time are acceptable.
2. For passives (R, C, L), any compliant part meeting the spec works —
   the PN in the `Part` column is one validated example, not a binding
   choice.
3. For active devices, modules, connectors, and the e-paper panel, the
   `Part` column **is** binding; substitutions there change the PCB
   footprint or firmware behavior.

D-OPEN-6 in `hardware/layout/decisions.md` tracks closing the
procurement loop with a fully-verified PN list before CP6 fab export.
