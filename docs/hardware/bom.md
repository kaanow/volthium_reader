# Bill of Materials

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

### Always-on / power

| Ref       | Part                                                  | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| MOD1      | **Espressif ESP32-S3-WROOM-1U-N16R8** (16 MB flash, 8 MB PSRAM) | SMD     | 1   | both        | [DK 16162641](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-S3-WROOM-1U-N16R8/16162641) ✓ | [Mouser](https://www.mouser.com/c/?q=ESP32-S3-WROOM-1U-N16R8) | $6     | PCB footprint is **-1U** (external U.FL antenna) per `STOCK_FOOTPRINTS` in `build_pcbs.py`. Use the dev kit for proto: search "ESP32-S3-DevKitC-1U-N16R8". |
| U1        | **TI TPS62933FDRLR** 3 A sync buck (24 V → 3.3 V)     | SOT-563 | 1   | PCB         | [DK 16669312](https://www.digikey.com/en/products/detail/texas-instruments/TPS62933FDRLR/16669312) ✓ | [Mouser](https://www.mouser.com/c/?q=TPS62933FDRLR) | $1.20 | 22 µA quiescent. EN pin lets the MOSFET kill the rail. |
|           | *or, for proto:* Pololu D24V5F3 module                | TH      | 1   | Proto       | [Pololu 2842](https://www.pololu.com/product/2842) | —      | $7     | If you'd rather not solder a TPS62933 |
| U2        | **Recom R-78E12-1.0/X9** SIP3 buck (24 V → 12 V, 1 A) | SIP3    | 1   | both        | [DK 13401697](https://www.digikey.com/en/products/detail/recom-power/R-78E12-1-0-X9/13401697) ✓ | [Mouser](https://www.mouser.com/c/?q=R-78E12-1.0/X9) | $7     | Powers the Cat5e link. `/X9` is the RoHS-compliant variant. |
| C1, C2    | 22 µF / 25 V X5R/X7R ceramic                          | 1210    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=22uF+25V+1210+X7R) | [search](https://www.mouser.com/c/?q=22uF%2025V%201210%20X7R) | $0.40  | Input/output bulk on TPS62933. Any compliant Murata GRM32 / TDK CGA6 / Samsung CL32 works. |
| C3, C4    | 22 µF / 35 V X5R/X7R ceramic                          | 1210    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=22uF+35V+1210+X7R) | [search](https://www.mouser.com/c/?q=22uF%2035V%201210%20X7R) | $0.50  | Input bulk on R-78E12 (24 V rail). |
| L1        | 2.2 µH ≥3 A inductor                                  | 4×4 SMD | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=2.2uH+inductor+3A+shielded) | [search](https://www.mouser.com/c/?q=2.2uH%20inductor%203A%20shielded) | $0.50  | TPS62933 inductor (see TI ref design 14-PN range). |
| F1        | 1 A fast-blow 5×20 mm fuse + holder                   | TH      | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=5x20mm+fuse+holder+1A+fast) | [search](https://www.mouser.com/c/?q=5x20mm%20fuse%20holder%201A%20fast) | $3     | On the 24 V tap. |
| D1        | **Vishay SS24** 40 V / 2 A Schottky                   | SMA     | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=SS24+Schottky+SMA) | [search](https://www.mouser.com/c/?q=SS24%20Schottky%20SMA) | $0.30  | Reverse-polarity inline on 24 V input. |

### MCU support

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| RTC1      | **Analog Devices DS3231SN#** I²C RTC            | SO-16W  | 1   | PCB         | [DK 1197576](https://www.digikey.com/en/products/detail/analog-devices-inc-maxim-integrated/DS3231SN/1197576) ✓ | [Mouser](https://www.mouser.com/c/?q=DS3231SN%23) | $7     | Onboard TCXO, ±2 ppm. Battery backed. `#` suffix = industrial-temp grade. Tape-and-reel variant is `DS3231SN#T&R` (DK 1197577). |
| BAT1      | **Keystone 1057** through-hole CR2032 holder (PCB) | THT     | 1   | PCB         | [DK 36-1057-ND](https://www.digikey.com/en/products/result?keywords=Keystone+1057) | [Mouser](https://www.mouser.com/c/?q=Keystone%201057) | $0.80  | DS3231 backup. The PCB footprint targets the Keystone 1057. **D-OPEN-5** in `decisions.md` tracks the open question of swapping to a non-cutout SMD alternative (Keystone 3000 / 3034) — not closed yet. The earlier BOM said "SMD" + cited Keystone 1066; both wrong — 1066 is also THT, and the current PCB targets 1057 specifically. |
| C5, C6    | 100 nF X7R                                      | 0603    | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=100nF+0603+X7R+25V) | [search](https://www.mouser.com/c/?q=100nF%200603%20X7R%2025V) | $0.05  | RTC + ESP decoupling. |
| C7        | 10 µF X7R                                       | 0805    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=10uF+0805+X7R+16V) | [search](https://www.mouser.com/c/?q=10uF%200805%20X7R%2016V) | $0.10  | ESP32 bulk. |

### RS-485

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| U3        | **TI SN65HVD3082EDR** half-duplex, 3.3 V        | SOIC-8  | 1   | both        | [DK 1574525](https://www.digikey.com/en/products/detail/texas-instruments/SN65HVD3082EDR/1574525) ✓ | [Mouser](https://www.mouser.com/c/?q=SN65HVD3082EDR) | $1.20  | ESD-protected, slew-rate-limited. |
| R1        | 120 Ω 1 % RS-485 termination (e.g. Vishay CRCW0805120RFKEA) | 0805    | 1   | both        | [search CRCW0805120RFKEA](https://www.digikey.com/en/products/result?keywords=CRCW0805120RFKEA) | [Mouser](https://www.mouser.com/c/?q=CRCW0805120RFKEA) | $0.10  | Bus terminator. Generic spec — any compliant 0805 120 Ω 1 % works. |
| R2, R3    | 680 Ω 1 % bias (e.g. Vishay CRCW0805680RFKEA)   | 0805    | 2   | PCB         | [search CRCW0805680RFKEA](https://www.digikey.com/en/products/result?keywords=CRCW0805680RFKEA) | [Mouser](https://www.mouser.com/c/?q=CRCW0805680RFKEA) | $0.10  | Idle-state bias to A/B. |
| TVS1      | **Littelfuse SMAJ12CA** bidirectional TVS       | SMA     | 1   | PCB         | [DK 762271](https://www.digikey.com/en/products/detail/littelfuse-inc/SMAJ12CA/762271) ✓ | [Mouser](https://www.mouser.com/c/?q=SMAJ12CA) | $0.30  | Surge protection on A/B. |
| TVS2      | **Littelfuse SMAJ15A** unidirectional TVS       | SMA     | 1   | PCB         | [DK 762276](https://www.digikey.com/en/products/detail/littelfuse-inc/SMAJ15A/762276) ✓ | [Mouser](https://www.mouser.com/c/?q=SMAJ15A) | $0.30  | On the 12 V Cat5e feed. |

### Hard-cut, override, sensing

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| Q1        | **Alpha & Omega AO3401A** P-MOSFET (Vds 30 V, 4 A) | SOT-23  | 1   | PCB         | [DK 1855773](https://www.digikey.com/en/products/detail/alpha-omega-semiconductor-inc/AO3401A/1855773) ✓ | [Mouser](https://www.mouser.com/c/?q=AO3401A) | $0.40  | Load switch — gate driven by ESP32 GPIO via Q2. |
| Q2        | **Alpha & Omega AO3400A** N-MOSFET              | SOT-23  | 1   | PCB         | [DK 1855942](https://www.digikey.com/en/products/detail/alpha-omega-semiconductor-inc/AO3400A/1855942) ✓ (legacy PN `785-1000-1-ND`) | [Mouser](https://www.mouser.com/c/?q=AO3400A) | $0.40  | Drives Q1's gate from 3.3 V. |
| R4        | 10 kΩ 1 % pull-up (Q1 gate)                     | 0603    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=CRCW060310K0FKEA) | [search](https://www.mouser.com/c/?q=CRCW060310K0FKEA) | $0.05  |  |
| R5, R6    | 100 kΩ / 11 kΩ — 24 V → 3.3 V divider           | 0603 ×2 | 2   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=CRCW0603+100k+11k+1%25) | [search](https://www.mouser.com/c/?q=CRCW0603%20100k%2011k%201%25) | $0.10  | 24 V sense on ADC1_CH0 (GPIO1). Top of divider stays alive in deep sleep. |
| BTN1      | Panel-mount override pushbutton (e.g. E-Switch EG1218) | TH      | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=EG1218) | [search](https://www.mouser.com/c/?q=EG1218) | $2     | On battery-side enclosure; jumps ULP to wake state. |
| C8        | 100 nF debounce                                 | 0603    | 1   | PCB         | (as C5) | (as C5) | $0.05  |  |

### Interconnect / enclosure

| Ref       | Part                                            | Qty | DigiKey | Mouser | Price | Notes |
|-----------|-------------------------------------------------|-----|---------|--------|-------|-------|
| J1        | **Amphenol RJHSE5380** RJ45 jack (Cat5e, T568B) | 1   | [search](https://www.digikey.com/en/products/result?keywords=RJHSE5380) | [search](https://www.mouser.com/c/?q=RJHSE5380) | $4    | Patch from this to in-wall Cat5e, or hardwire. This is the footprint the PCB targets. |
| J2        | 2-pin terminal block 5.08 mm pitch (24 V)       | 1   | [search](https://www.digikey.com/en/products/result?keywords=Phoenix+MKDS+5.08+2+pin) | [search](https://www.mouser.com/c/?q=Phoenix%20MKDS%205.08%202%20pin) | $1    | Ring-terminal lugs land here from the battery. PCB uses Phoenix MKDS-1,5-2 family. |
| EN1       | **Hammond 1554-series IP66 enclosure** — TBD on exact PN | 1   | [Hammond 1554 series](https://www.hammfg.com/electronics/small-case/plastic/1554) ; [DK 1554BGY 65×65×40](https://www.digikey.com/product-detail/en/1554BGY/HM918-ND/1090730) ; [DK 1554CGY 120×65×40](https://www.digikey.com/en/products/detail/hammond-manufacturing/1554CGY/655303) | [Mouser](https://www.mouser.com/c/?q=Hammond%201554) | $8–14 | Earlier BOM said `Hammond 1556B2GY` — **that PN does not exist in Hammond's catalog** (1556 isn't a series). The intended ~80×60×40 mm IP65 grey ABS box lives in the 1554 family; closest standard sizes are 1554B (65×65×40) and 1554C (120×65×40). Pick the size that fits the assembled PCB (95×75 board → 1554C is the realistic fit, even though it overshoots the original 80mm target). User to confirm before order. |
| —         | M3 standoffs + screws                           |     | (any)   | (any)  | $2    |  |
| —         | Cat5e patch cable, 30 cm                        | 1   | (any)   | (any)  | $3    | Inside the enclosure |

### Battery-side subtotal (PCB version, single qty): **~$45** in components, ~$60 with enclosure + connectors.

## Display-side board

### Power

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| U1        | **Recom R-78E3.3-0.5** SIP3 buck (12 V → 3.3 V, 0.5 A) | SIP3    | 1   | both        | [945-1661-5-ND](https://www.digikey.com/en/products/detail/recom-power/R-78E3.3-0.5/3593412) | [search](https://www.mouser.com/c/?q=R-78E3.3-0.5) | $5     | 80 % eff. at 200 mA. Digi-Key PN verified. |
| F1        | **Bourns MF-R050** PTC resettable fuse, 0.5 A hold | TH      | 1   | both        | [DK 259965](https://www.digikey.com/en/products/detail/bourns-inc/MF-R050/259965) ✓ | [Mouser](https://www.mouser.com/c/?q=MF-R050) | $1     | On the 12 V Cat5e feed. (Earlier BOM said "Bel Fuse"; the MF-R series is **Bourns**.) |
| TVS1      | SMAJ15A on 12 V input                           | SMA     | 1   | PCB         | (as battery TVS2) | (as battery TVS2) | $0.30  |  |
| C1        | 22 µF / 25 V X7R                                | 1210    | 1   | PCB         | (as battery C1) | (as battery C1) | $0.20  | Input bulk |
| C2        | 10 µF X7R                                       | 0805    | 1   | PCB         | (as battery C7) | (as battery C7) | $0.10  | 3.3 V output bulk |

### MCU support

| Ref       | Part                                            | Pkg     | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-------------------------------------------------|---------|-----|-------------|---------|--------|--------|-------|
| MOD1      | **Espressif ESP32-S3-WROOM-1U-N16R8**           | SMD     | 1   | both        | [DK 16162641](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-S3-WROOM-1U-N16R8/16162641) ✓ | [Mouser](https://www.mouser.com/c/?q=ESP32-S3-WROOM-1U-N16R8) | $6     | **Both boards** use the -1U variant (external U.FL antenna) — the PCB footprint matches on both sides. Earlier BOM said battery uses -1, display uses -1U; that was a documentation error. Common firmware base. |
| R1        | 10 kΩ ESP32 EN pull-up                          | 0805    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=10k+0805+1%25) | [search](https://www.mouser.com/c/?q=10k%200805%201%25) | $0.05  |  |
| C3        | 10 µF X7R MOD1 V3V3 bulk                        | 0805    | 1   | PCB         | (as C2) | (as C2) | $0.10  | Close to the ESP32 module 3V3 pin |
| C4        | 100 nF X7R MOD1 V3V3 HF                         | 0402    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=100nF+0402+X7R+16V) | [search](https://www.mouser.com/c/?q=100nF%200402%20X7R%2016V) | $0.05  | The 0402 close-in cap — smaller package fits inside MOD1's pad row |
| C5        | 1 µF ESP_EN soft-start                          | 0603    | 1   | PCB         | [search](https://www.digikey.com/en/products/result?keywords=1uF+0603+X7R) | [search](https://www.mouser.com/c/?q=1uF%200603%20X7R) | $0.05  | Paired with R1 forms the EN power-on delay. |
| C6        | 1 µF panel VCC bulk                             | 0603    | 1   | PCB         | (as C5) | (as C5) | $0.05  | Reduces VCC dip during EPD refresh |
| C7        | 100 nF U2 V3V3 decoupling                       | 0603    | 1   | PCB         | (as battery C5) | (as battery C5) | $0.05  | At the RS-485 transceiver |

### Display

| Ref       | Part                                                | Pkg        | Qty | Proto / PCB | DigiKey | Mouser | Price  | Notes |
|-----------|-----------------------------------------------------|------------|-----|-------------|---------|--------|--------|-------|
| LCD1      | **Waveshare 4.2" tri-color e-Paper (B) V2** module (`WFT0420CZ15`) + driver HAT | bare panel | 1   | both        | [search](https://www.digikey.com/en/products/result?keywords=Waveshare+4.2+e-Paper+B+V2) | [search](https://www.mouser.com/c/?q=Waveshare%204.2%20e-Paper%20B%20V2) | $35    | Black / red / white, 400×300, SPI. **Primary source:** [waveshare.com/4.2inch-e-paper-module-b.htm](https://www.waveshare.com/4.2inch-e-paper-module-b.htm) — distributors carry it inconsistently; direct-from-Waveshare or Amazon may be more reliable. |
| J2        | **Hirose FH12-24S-0.5SH(55)** 24-pin 0.5 mm FFC, top-contact, RoHS variant | SMT        | 1   | PCB         | [DK 1110322](https://www.digikey.com/en/products/detail/hirose-electric-co-ltd/FH12-24S-0-5SH-55/1110322) ✓ (legacy PN `HFJ124CT-ND`) | [Mouser](https://www.mouser.com/c/?q=FH12-24S-0.5SH%2855%29) | $1     | Mates the panel ribbon. The `(55)` suffix is the RoHS-compliant variant — explicit suffix is what the PCB footprint expects. |

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
| BTN1–3    | 6×6×4.3 mm tactile switch (e.g. E-Switch TL3300 series) | 3   | [search](https://www.digikey.com/en/products/result?keywords=TL3300+tactile+switch) | [search](https://www.mouser.com/c/?q=TL3300%20tactile%20switch) | $0.50 | Refresh / next-screen / release-BLE |
| J1        | RJ45 keystone jack (same as battery J1)         | 1   | (as battery J1) | (as battery J1) | $4    |  |
| —         | Single-gang low-voltage mounting bracket        | 1   | (HW store) |     | $4    |  |
| —         | Blank single-gang wall plate (cut for panel + buttons) | 1 | (HW store) |  | $3    |  |
| —         | M2 mounting hardware for the e-paper            |     |         |     | $2    |  |

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

- **Buck regulator family**: anything with ~20 µA Iq and ≥3 V minimum input
  works. The TPS62933 was chosen because the family is broadly stocked and
  the EN pin gives us the hard-cut control we want. Alternatives: TPS62A01,
  MP2451, AP63203.
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
