# Bill of Materials

> **⚠️ SUPPLIER PART NUMBERS UNVALIDATED — DO NOT ORDER AGAINST THIS FILE.**
>
> The `DigiKey` and `Mouser` columns throughout this document have not
> been verified against the distributors' live catalogs. Spot-checks
> have already turned up wrong/non-existent part numbers, and the rest
> are presumed to be the same quality until proven otherwise. Treat the
> manufacturer part name (the `Part` column) as the only authoritative
> identifier and re-derive the distributor part numbers yourself before
> placing any order.
>
> Validation is tracked as **D-OPEN-6** in `hardware/layout/decisions.md`.

Two columns where reasonable: "Proto" (build on a breadboard / dev board
for early bring-up) and "PCB" (custom board for permanent install). The
PCB column assumes Digi-Key / Mouser ordering and SMT parts where it
makes sense; through-hole stays for anything you'd realistically replace
in the field.

Prices are May 2026 (US, single quantity). Some prices ranged because
DigiKey/Mouser drift week-to-week — **and** because, as noted above,
some prices may not be tied to a real part number at all yet.

## Battery-side board

### Always-on / power

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| MOD1      | **ESP32-S3-WROOM-1-N16R8** (16 MB flash, 8 MB PSRAM) | SMD | 1 | both | 1965-ESP32-S3-WROOM-1-N16R8-ND | 356-ESP32S3WROOM1N16R8 | $6     | Use the dev kit for proto: 1965-ESP32-S3-DEVKITC-1-N16R8-ND ($15) |
| U1        | **TPS62933FDRLR** 3 A sync buck (24 V → 3.3 V) | SOT-563 | 1 | PCB | 296-50428-1-ND | 595-TPS62933FDRLR | $1.20 | 22 µA quiescent. EN pin lets the MOSFET kill the rail. |
|           | *or, for proto:* Pololu D24V5F3 module | TH | 1   | Proto       | —                 | —                        | $7     | If you'd rather not solder a TPS62933 |
| U2        | **Recom R-78E12-1.0** SIP3 buck (24 V → 12 V, 1 A) | SIP3 | 1 | both | 945-R-78E12-1.0  | 919-R-78E12-1.0           | $7     | Powers the Cat5e link |
| C1, C2    | 22 µF / 25 V ceramic                  | 1210           | 2   | PCB         | 1276-2920-1-ND     | 187-GRM32ER61E226KE15L    | $0.40  | Input/output bulk on TPS62933 |
| C3, C4    | 22 µF / 35 V ceramic                  | 1210           | 2   | PCB         | 1276-2885-1-ND     | 187-GRM32ER7YA226KA12L    | $0.50  | Input bulk on R-78E12 (24 V rail) |
| L1        | 2.2 µH 3 A inductor                   | 4×4 SMD        | 1   | PCB         | 587-3327-1-ND      | 875-DFE201610E-2R2M=P2    | $0.50  | TPS62933 inductor (see TI ref design) |
| F1        | 1 A fast-blow fuse + ATO holder       | TH             | 1   | both        | F4912-ND           | —                        | $3     | On the 24 V tap |
| D1        | SS24 Schottky (reverse-polarity)      | SMA            | 1   | PCB         | SS24FACT-ND        | 583-SS24                  | $0.30  | Inline on 24 V input |

### MCU support

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| RTC1      | **DS3231SN#** I²C RTC                 | SO-16W         | 1   | PCB         | DS3231SN#-ND       | 700-DS3231SN              | $7     | Has its own TCXO, ±2 ppm. Battery backed. |
| BAT1      | CR2032 coin-cell holder               | TH             | 1   | PCB         | BK-885-ND          | 534-1066                  | $0.80  | DS3231 backup |
| C5, C6    | 100 nF X7R                            | 0603           | 2   | PCB         | 311-1141-1-ND      | 81-GRM188R71H104KA93D     | $0.05  | RTC + ESP decoupling |
| C7        | 10 µF X7R                             | 0805           | 1   | PCB         | 1276-1023-1-ND     | 187-GRM21BR61C106KE15L    | $0.10  | ESP32 bulk |

### RS-485

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| U3        | **SN65HVD3082EDR** half-duplex, 3.3 V | SOIC-8         | 1   | both        | 296-21908-1-ND     | 595-SN65HVD3082EDR        | $1.20  | ESD-protected, low-EMI |
| R1        | 120 Ω 1% RS-485 termination           | 0805           | 1   | both        | RMCF0805FT120RCT-ND | 71-CRCW0805120RFKEA      | $0.10  | Slot-soldered so you can lift it if not at end of line |
| R2, R3    | 680 Ω bias                            | 0805           | 2   | PCB         | RMCF0805FT680RCT-ND | 71-CRCW0805680RFKEA      | $0.10  | Idle-state bias to A/B |
| TVS1      | SMAJ12CA bidirectional TVS            | SMA            | 1   | PCB         | SMAJ12CADICT-ND    | 78-SMAJ12CA-E3/61         | $0.30  | Surge protection on the A/B lines |
| TVS2      | SMAJ15A unidirectional TVS            | SMA            | 1   | PCB         | SMAJ15ADICT-ND     | 78-SMAJ15A-E3/61          | $0.30  | On the 12 V Cat5e feed (protects against cable transients) |

### Hard-cut, override, sensing

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| Q1        | **AO3401A** P-MOSFET (Vds 30 V, 4 A) | SOT-23         | 1   | PCB         | AO3401ADICT-ND     | 833-AO3401A               | $0.40  | Load switch — gate driven by ESP32 GPIO via Q2 |
| Q2        | **AO3400A** N-MOSFET                  | SOT-23         | 1   | PCB         | AO3400ADICT-ND     | 833-AO3400A               | $0.40  | Drives Q1's gate from 3.3 V |
| R4        | 10 kΩ pull-up (Q1 gate to source)     | 0603           | 1   | PCB         | RMCF0603FT10K0CT-ND | 71-CRCW060310K0FKEA      | $0.05  |  |
| R5, R6    | 100 kΩ / 11 kΩ — 24 V → 3.3 V divider | 0603 ×2        | 2   | PCB         | RMCF0603FT100KCT-ND, RMCF0603FT11K0CT-ND |  | $0.10  | 24 V sense on ADC1_CH0 (GPIO1). Top of divider stays alive in deep sleep. |
| BTN1      | Panel-mount override pushbutton       | TH             | 1   | both        | EG1218-ND          | 612-PVA1OAHNN             | $2     | On battery-side enclosure; jumps ULP to wake state |
| C8        | 100 nF debounce                       | 0603           | 1   | PCB         | 311-1141-1-ND      | (as C5)                   | $0.05  | |

### Interconnect / enclosure

| Ref       | Part                                  | Qty | DigiKey            | Mouser                   | Price | Notes |
|-----------|---------------------------------------|-----|--------------------|--------------------------|-------|-------|
| J1        | RJ45 keystone jack (Cat5e/6, T568B)   | 1   | 207-RJ45-T568B-ND  | —                        | $4    | Patch from this to in-wall Cat5e via short pre-made patch cable, or hardwire |
| J2        | 2-pin terminal block 5 mm pitch, 24 V tap | 1 | ED10564-ND          | 651-1715022               | $1    | Ring-terminal lugs land here from the battery |
| EN1       | IP65 enclosure ~80×60×40 mm           | 1   | HM5187-ND          | 546-1556B2GY              | $8    | Hammond 1556B2GY |
| —         | M3 standoffs + screws                 |     | —                  | —                        | $2    |  |
| —         | Cat5e patch cable, 30 cm              | 1   | (any)              | —                        | $3    | Inside the enclosure |

### Battery-side subtotal (PCB version, single qty): **~$45** in components, ~$60 with enclosure + connectors.

## Display-side board

### Power

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| U10       | **Recom R-78E3.3-0.5** SIP3 buck (12 V → 3.3 V, 0.5 A) | SIP3 | 1 | both | 945-R-78E3.3-0.5 | 919-R-78E3.3-0.5         | $5     | 80% eff. at 200 mA |
| F2        | PTC resettable fuse, 0.5 A hold       | TH             | 1   | both        | F1283CT-ND         | 650-MF-R050-2             | $1     | On the 12 V Cat5e feed |
| TVS3      | SMAJ15A on 12 V input                 | SMA            | 1   | PCB         | (as TVS2)          |                          | $0.30  |  |
| C11       | 22 µF / 25 V                          | 1210           | 1   | PCB         | (as C1)            |                          | $0.20  | Input bulk |
| C12       | 10 µF X7R                             | 0805           | 1   | PCB         | (as C7)            |                          | $0.10  | 3.3 V output bulk |

### MCU support

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| MOD2      | **ESP32-S3-WROOM-1-N16R8**            | SMD            | 1   | both        | (as MOD1)          |                          | $6     | Same module both ends — common firmware base |
| C13, C14  | 100 nF X7R                            | 0603           | 2   | PCB         | (as C5)            |                          | $0.05  | ESP decoupling |

### Display

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| LCD1      | **Waveshare 4.2" tri-color e-Paper (B) V2** + driver HAT | bare panel | 1 | both | 1738-1135-ND | 992-19094  | $35    | Black / red / white. 400×300. SPI |
| J3        | 24-pin 0.5 mm FFC connector (top-contact) | SMT | 1   | PCB         | 670-2719-1-ND      | 798-FH12-24S-0.5SH(55)    | $1     | Mating to panel ribbon |

### RS-485

| Ref       | Part                                  | Pkg            | Qty | Proto / PCB | DigiKey            | Mouser                   | Price  | Notes |
|-----------|---------------------------------------|----------------|-----|-------------|--------------------|--------------------------|--------|-------|
| U11       | **SN65HVD3082EDR**                    | SOIC-8         | 1   | both        | (as U3)            |                          | $1.20  |  |
| R10       | 120 Ω 1%                              | 0805           | 1   | both        | (as R1)            |                          | $0.10  | RS-485 term |
| R11, R12  | 680 Ω idle bias                       | 0805 ×2        | 2   | PCB         | (as R2)            |                          | $0.10  | |
| TVS4      | SMAJ12CA                              | SMA            | 1   | PCB         | (as TVS1)          |                          | $0.30  | RS-485 ESD |

### Buttons + interconnect

| Ref       | Part                                  | Qty | DigiKey            | Mouser                   | Price | Notes |
|-----------|---------------------------------------|-----|--------------------|--------------------------|-------|-------|
| BTN10–12  | 6×6×4.3 mm tactile switch             | 3   | 450-1641-ND        | 642-TL3300AF260QG         | $0.50 | Refresh / next-screen / release-BLE |
| J11       | RJ45 keystone jack                    | 1   | (as J1)            |                          | $4    |  |
| —         | Single-gang low-voltage mounting bracket | 1 | (HW store)         |                          | $4    |  |
| —         | Blank single-gang wall plate (to cut for panel + buttons) | 1 | (HW store) |              | $3    |  |
| —         | M2 mounting hardware for the e-paper  |     |                    |                          | $2    |  |

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
