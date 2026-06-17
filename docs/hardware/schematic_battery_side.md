# Battery-side board — schematic (netlist form)

> ⚠ **SUPERSEDED for the power architecture (decisions.md D18/D19).** This
> is the *original* pre-CP1 net intent. Its power tree (TPS62933 on the
> switched rail, R-78E12, AO340x load switch, both-end RS-485 bias) was
> re-architected in **D19** to fix the bootstrap/clamp/Vgs defects
> (DESIGN_REVIEW_ITEMS DR-3/DR-4). For the **authoritative** battery power
> tree, regulators, load switch, and bias, see:
> [`../../hardware/layout/cp1_battery_side.md`](../../hardware/layout/cp1_battery_side.md)
> §3–§4, [`block_diagrams.md`](block_diagrams.md), and [`bom.md`](bom.md).
> The GPIO/comms/sensing intent below is still valid; the **power-tree and
> Hard-cut sections are historical**.

This is structured to drop into KiCad as a schematic: each component is
listed with its reference designator and pin connections, organized by
net. See `bom.md` for part numbers; see `block_diagrams.md` for the
visual.

## ESP32-S3 GPIO assignment (battery-side)

Picked to (a) keep ADC1 free for the 24 V sense, (b) use RTC-capable pins
for anything that needs to survive deep sleep, (c) reserve USB pins so we
keep the dev-board USB-OTG option.

| GPIO     | Direction | Function                  | Notes                            |
|----------|-----------|---------------------------|----------------------------------|
| GPIO0    | input     | (strapping — leave open or weak-pull-up) | bootloader strap        |
| GPIO1    | analog in | **24 V sense ADC**        | ADC1_CH0 via 100 k / 11 k divider |
| GPIO2    | output    | RS-485 DE/RE (driver enable) | active high = transmit         |
| GPIO3    | (strap)   | leave NC                  | USB-JTAG select strap            |
| GPIO4    | out, ULP  | **P-MOSFET load-switch enable** | LOW = power off everything but ULP  |
| GPIO5    | I²C SDA   | DS3231                    |                                  |
| GPIO6    | I²C SCL   | DS3231                    |                                  |
| GPIO7    | input, ULP | **override pushbutton**  | wake from deep sleep             |
| GPIO15   | output    | onboard LED (debug)       | optional                         |
| GPIO17   | UART TX   | to SN65HVD3082 D pin      | UART1                            |
| GPIO18   | UART RX   | from SN65HVD3082 R pin    | UART1                            |
| GPIO19   | USB DM    | (USB-OTG, dev only)       | leave routed but optional        |
| GPIO20   | USB DP    | (USB-OTG, dev only)       |                                  |
| GPIO45   | (strap)   | leave NC                  | VDD_SPI voltage strap            |
| GPIO46   | (strap)   | leave NC                  | boot mode strap                  |

Unused GPIOs left as headers for expansion (temperature probe, etc.).

## Power tree

```
24V_RAW ──[F1: 1A]── 24V_FUSED ──[D1: SS24]── 24V
                                              │
                                              ├── R5/R6 divider → 24V_SENSE → ESP32 GPIO1 (ADC)
                                              │
                                              ├── U1 (TPS62933) ──── 3V3_SW
                                              │      │
                                              │      └── EN ◄── (3.3V LDO-style soft-start, see Q1 path)
                                              │
                                              └── U2 (R-78E12-1.0) ── +12V (to Cat5e)
                                                       │
                                                       └── TVS3 → GND
3V3_SW ──┐
         ├── ESP32-S3 (MOD1)
         ├── DS3231 (RTC1)
         ├── SN65HVD3082 (U3) VCC
         └── biased to RS-485 idle via R2/R3 to 3V3_SW

DS3231 V_BAT ── CR2032 (BAT1) — RTC keeps time across full power loss
```

## Hard-cut MOSFET path

```
                   ┌─────────────────────────────────────────┐
                   │                                          │
       24V ────────┤───────► Q1 (P-MOSFET AO3401A)            │
                   │      G                                    │
                   │      ├─[R4: 10k]──► 24V (default OFF)    │
                   │      │                                    │
                   │      └─────────► Q2 drain                 │
                   │                                            │
                   │   Q2 (N-FET AO3400A)                      │
                   │   G  ◄── ESP32 GPIO4 (PWR_EN_N — set LOW │
                   │              by ULP/main to enable rail) │
                   │   S  ◄── GND                              │
                   └────────────────────────────────────────────┘
                                  │
                                  ▼
                            (everything below
                            is on the switched
                            output of Q1)
```

When `PWR_EN_N` is LOW, Q2 pulls Q1's gate to GND → Q1 conducts → 24V passes
through to the downstream regulators. When `PWR_EN_N` floats / goes HIGH,
R4 pulls Q1's gate to its source → Q1 off → downstream rails collapse.

Note: the 24 V sense divider (R5/R6) is connected to the *un-switched*
24 V rail. That way the ULP can wake every minute, read SOC-proxy voltage
through GPIO1, and decide whether to re-enable the rail — even when the
rest of the system is off.

## RS-485 transceiver (U3 — SN65HVD3082)

| U3 pin | Net           | Connects to                                      |
|--------|---------------|--------------------------------------------------|
| 1 (R)  | UART_RX_3V3   | ESP32 GPIO18                                     |
| 2 (RE/) | DE_3V3       | ESP32 GPIO2 (tied together with DE)              |
| 3 (DE) | DE_3V3        | ESP32 GPIO2                                      |
| 4 (D)  | UART_TX_3V3   | ESP32 GPIO17                                     |
| 5 (GND)| GND           |                                                  |
| 6 (A)  | RS485_A       | RJ45 pin 4 (blue), R1 to RS485_B, TVS1, R2 bias  |
| 7 (B)  | RS485_B       | RJ45 pin 5 (white-blue), R1 to RS485_A, TVS1, R3 bias |
| 8 (VCC)| 3V3_SW        |                                                  |

R2 (680 Ω) idles A high to 3V3_SW; R3 (680 Ω) idles B low to GND. TVS1
(SMAJ12CA) between A and B clamps differential transients.

R1 (120 Ω) terminates **only if this end is the bus terminus**. Place it
on a 2-pin header so it can be jumped or removed. The battery-side will
be one end of the bus (display-side is the other).

## Decoupling

| Cap     | Value     | Location                                     |
|---------|-----------|----------------------------------------------|
| C1      | 22 µF     | TPS62933 VIN (24 V rail input bulk)          |
| C2      | 22 µF     | TPS62933 VOUT (3V3_SW bulk)                  |
| C3      | 22 µF     | R-78E12 VIN                                  |
| C4      | 22 µF     | R-78E12 VOUT (12 V to Cat5e)                 |
| C5      | 100 nF    | DS3231 VCC                                   |
| C6      | 100 nF    | ESP32 module VCC pin                         |
| C7      | 10 µF     | ESP32 bulk on 3V3_SW                         |
| C8      | 100 nF    | Override-button RC debounce                  |
| (BTNs)  | 100 nF    | one per tactile switch, parallel to switch   |

## Override-button RC debounce

```
3V3_SW ──[R7: 10k]──┬── ESP32 GPIO7 (ULP wake input, pull-up enabled)
                    │
                   ─┴─ (Switch BTN1 — closes to GND)
                    │
                   ─┴─ C8 (100 nF — RC time ~1 ms)
                    │
                   GND
```

When pressed, GPIO7 goes LOW. ULP firmware can configure this as a
wake-up source from deep sleep via `esp_deep_sleep_enable_gpio_wakeup()`.

## Connector pinout (RJ45 J1 — T568B)

| RJ45 pin | T568B color    | Net      |
|----------|----------------|----------|
| 1        | white-orange   | +12V     |
| 2        | orange         | +12V     |
| 3        | white-green    | +12V     |
| 4        | blue           | RS485_A  |
| 5        | white-blue     | RS485_B  |
| 6        | green          | GND      |
| 7        | white-brown    | GND      |
| 8        | brown          | GND      |

Shield drain wire → chassis ground stud near J1 (bonded at this end only).

## PCB layout hints

- Keep the 24 V → 3.3 V switching path tight (TPS62933 + L1 + C1/C2 in a
  compact loop). Put a small ground plane under it.
- The RS-485 transceiver and RJ45 should be on the board edge. Use copper
  pour from the GND pins of the SN65HVD3082 to the J1 shell.
- Keep the ADC sense divider (R5/R6) away from switching noise — ideally
  on the opposite side of the board from L1.
- Mount the override button (BTN1) so its actuator pokes through the
  enclosure lid. A panel-mount version (EG1218 or similar) is easier than
  routing a board-mount switch to the panel.
- Add 4× M3 mounting holes near corners. Hammond 1556B2GY has a 64×42 mm
  internal area; design to a 60×38 mm board outline.
