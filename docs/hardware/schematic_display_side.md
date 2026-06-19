# Display-side board — schematic (netlist form)

> ⚠ **SUPERSEDED — historical pre-CP1 net intent (decisions.md D18–D27).**
> This entire document predates the CP1 re-architecture and is retained only
> for historical reference and as a starting point for the GPIO pin map.
> **Do not treat any part number, connector, or enclosure here as current.**
> Re-architected since: the e-paper interface (bare-panel 24-pin Hirose
> FH12-24S FFC → 8-pin Waveshare 4.2" Module (B) header — DR-7), the dev port
> (USB-OTG header → native USB-C, board-edge + pop-faceplate — D27), the
> enclosure (single-gang → recessed **double-gang** box with a custom
> 3D-printed faceplate the e-paper module mounts to — D27/DR-10), RS-485 bias
> (now the bus's only fail-safe bias, ~390 Ω display-end; TVS1 corrected —
> DR-1), and field update (OTA over RS-485 — D27). Even the GPIO *assignments*
> below should be re-verified, not trusted. **Authoritative:**
> [`../../hardware/layout/cp1_display_side.md`](../../hardware/layout/cp1_display_side.md),
> [`../../hardware/layout/decisions.md`](../../hardware/layout/decisions.md),
> [`block_diagrams.md`](block_diagrams.md).

Simpler than the battery-side: no 24 V rail, no MOSFET load-switch, no
RTC chip. Most of the BoM is the e-paper FFC and the connector.

## ESP32-S3 GPIO assignment (display-side)

| GPIO  | Direction | Function                  | Notes                       |
|-------|-----------|---------------------------|-----------------------------|
| GPIO0 | (strap)   | leave open                | bootloader strap            |
| GPIO2 | output    | RS-485 DE/RE              | active high = transmit      |
| GPIO5 | output    | E-paper CS                | SPI chip select             |
| GPIO6 | output    | E-paper DC                | data/command select         |
| GPIO7 | output    | E-paper RST               | hardware reset (active low) |
| GPIO8 | input     | E-paper BUSY              | high while updating         |
| GPIO9 | output    | SPI SCK                   |                             |
| GPIO10 | output   | SPI MOSI                  | (e-paper is write-only over SPI) |
| GPIO12 | input    | BTN10 — refresh now       | pulled-up, RC-debounced     |
| GPIO13 | input    | BTN11 — next screen       | "                           |
| GPIO14 | input    | BTN12 — release BLE       | "                           |
| GPIO15 | output   | onboard LED (debug)       | optional                    |
| GPIO17 | UART TX  | to SN65HVD3082            |                             |
| GPIO18 | UART RX  | from SN65HVD3082          |                             |
| GPIO19 | USB DM   | (USB-OTG, dev only)       |                             |
| GPIO20 | USB DP   | (USB-OTG, dev only)       |                             |

## Power tree

```
+12V (from Cat5e) ──[F2: PTC 0.5A]──[TVS3: SMAJ15A]──┬── U10 (R-78E3.3-0.5) ─── 3V3_RAIL
                                                     │
                                                    C11 (22 µF, input bulk)

3V3_RAIL ──┬── ESP32-S3 (MOD2)
           ├── SN65HVD3082 (U11) VCC
           ├── E-paper VCC
           ├── RS-485 idle-bias via R11/R12
           └── C12, C13, C14 (decoupling)
```

The PTC fuse (F2) protects against cable shorts. The TVS clamps any
inductive kick from the Cat5e run during regulator turn-on.

## E-paper SPI block

Wiring matches the Waveshare 4.2" e-Paper (B) V2 driver HAT pinout:

| E-paper signal | ESP32 GPIO | Direction |
|----------------|------------|-----------|
| VCC            | 3V3_RAIL   | —         |
| GND            | GND        | —         |
| DIN (MOSI)     | GPIO10     | out       |
| CLK (SCK)      | GPIO9      | out       |
| CS             | GPIO5      | out       |
| DC             | GPIO6      | out       |
| RST            | GPIO7      | out       |
| BUSY           | GPIO8      | in        |

SPI clock can be conservative — 4 MHz works, 10 MHz is achievable on
the v2 panel. Full refresh ~7 s, partial refresh ~1.2 s.

## Tactile button block (×3)

```
3V3_RAIL ──[10k pull-up]──┬── ESP32 GPIOn
                          │
                         ─┴─ (BTNxx — closes to GND)
                          │
                         ─┴─ 100 nF debounce
                          │
                         GND
```

(Internal pull-up on the ESP32 also works, but the external 10k makes
the signal robust to long traces and EMI.)

Button function map (firmware-level):

| Button | Default action                                   | Hold (≥2 s)               |
|--------|--------------------------------------------------|--------------------------|
| BTN10  | force full e-paper refresh                       | toggle backlight (n/a — e-paper) |
| BTN11  | cycle to next info screen (cell V / temp / history) | reset to default screen |
| BTN12  | release BLE for 5 min (so user can open phone app) | release BLE indefinitely until next press |

Display always shows a small icon when BLE is released — so it's clear
this isn't a fault.

## RS-485 transceiver (U11)

Identical to the battery-side except:

- **120 Ω termination R10 is permanent** here (this end of the bus is
  always the terminus — kitchen end).
- **Bias resistors R11 / R12 are optional**: the bus is already biased by
  the battery-side. Leaving them populated does no harm (just doubles the
  idle bias current, ~3 mA total — trivial).

## Connector pinout (J11 — T568B)

Identical to J1 on the battery-side board. See
`schematic_battery_side.md`.

Shield drain wire is **not** bonded at this end (single-point bond at the
battery side prevents ground loops over the 5 m run).

## PCB layout hints

- The e-paper FFC connector (J3) must sit at one edge so the panel can fold
  over the PCB on a hinge or sit in a recess.
- Board outline should fit behind the panel — e-paper is ~91×77 mm so a
  ~85×60 mm PCB tucks behind it nicely with the FFC on the long edge.
- Buttons on the opposite edge from the FFC, in a row, so they line up
  under cutouts in the wall plate.
- Single-gang plate cutout: ~70×115 mm visible window for the panel,
  three 8 mm holes for button caps near the bottom edge.
- The R-78E3.3 SIP3 module is tall — keep it on the side opposite the
  panel so it doesn't push into the e-paper's back glass.

## Mounting

Use a single-gang low-voltage box (no electrical box needed since there's
no line voltage). Mount the PCB to standoffs on the box ears, panel sits
on top, wall plate is the visible face.
