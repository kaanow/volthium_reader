# CP1 — Display-side board, design baseline

**Status**: draft, ready for review
**Board codename**: `volthium-display`
**Mounts**: behind a 3D-printed faceplate over a US double-gang plastic
old-work box (drywall-mount), kitchen-side. ~85 × 65 mm PCB.
**Function**: receives RS-485 frames over Cat5e, drives a 4.2" tri-color
e-paper, handles 3 tactile buttons whose function is software-defined
and rendered as on-screen labels next to each button.

## 1. Scope of this document

Companion to [`cp1_battery_side.md`](cp1_battery_side.md). Read this in
context of:
- [`../../docs/hardware/block_diagrams.md`](../../docs/hardware/block_diagrams.md)
- [`../../docs/hardware/schematic_display_side.md`](../../docs/hardware/schematic_display_side.md)
- [`../../docs/hardware/power_budget.md`](../../docs/hardware/power_budget.md)
- [`../../docs/hardware/cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md)
- [`../../docs/production_design.md`](../../docs/production_design.md) §display-screen design

Where this CP1 disagrees with the cross-references, **CP1 wins**.

## 2. Mechanical envelope

The display-side PCB lives inside a US **double-gang plastic old-work
box** (drywall-mount, "grey plastic" type, e.g. Carlon B232ADJ or
similar). Standard interior dimensions:

| Dimension      | Interior | Usable (after ribs / wire room) |
|----------------|----------|----------------------------------|
| Width          | ~95 mm   | ~85 mm                           |
| Height         | ~75 mm   | ~70 mm                           |
| Depth          | ~50 mm   | ~45 mm                           |

PCB outline target: **85 × 65 mm**. Mounting:

- 4× M3 mounting holes near corners: (4, 4), (81, 4), (4, 61), (81, 61)
- The PCB attaches to a 3D-printed bracket that drops into the
  double-gang box and screws to the box's two original side-mount
  screw holes (US double-gang spacing is 84 mm vertical between the
  M3.5×0.5 mounting screws; the bracket interfaces those to M3 standoffs
  for our PCB). User prints the bracket.

**Faceplate (3D-printed, user-supplied)**: ~115 × 117 mm overall
(matches standard double-gang plate footprint). Cutouts:

- 84.8 × 63.2 mm rectangular window for e-paper active area, centered
  vertically with ~5 mm offset toward the top edge to leave room for
  the button labels
- 3× 6 mm round cutouts along the bottom edge, on 18 mm centers, for
  the 6×6 mm tactile button caps to poke through (~16 mm horizontal
  span between centers of buttons 1 and 3)

The user designs the faceplate against a STEP file of the PCB +
mechanical envelope, exported at CP5.

## 3. Power architecture

```
+12 V from Cat5e (J1 RJ45 pins 1/2/3)
    │
    ▼
F1 [PTC polyfuse 0.5 A hold, 1 A trip]    ← resettable; protects cable
    │
    ▼
TVS1 [SMAJ15A unidirectional, V12 ↔ GND]   ← inductive kick from cable
    │
    ▼
U1 [Recom R-78E3.3-0.5, 12 V → 3.3 V, 0.5 A] ← stocked module, no inductor BOM
    │
    ▼
3V3 ──┬─── ESP32-S3 (MOD1)
      ├─── e-paper VCC (LCD1 via FFC J2)
      ├─── SN65HVD3082E (U2) VCC
      └─── RS-485 bias (R10/R11 optional — see §4.5)
```

No 24 V on this board. No RTC chip (time syncs from RS-485 frames). No
load-switching MOSFETs (the e-paper draws ~0 in idle thanks to its
bistable display; the ESP32-S3 self-manages its sleep states).

## 4. Component list

### 4.1 Power input

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| J1  | RJ45 keystone jack (T568B), shielded       | THT shielded   | 1   | Same part as battery-side J2; shield drain NOT bonded at this end (single-point bond at battery side per [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md)) |
| F1  | PTC polyfuse, 0.5 A hold / 1 A trip (e.g. Bel Fuse 0ZCG0050FF2C) | THT radial   | 1 | Resettable; protects against cable shorts |
| TVS1 | SMAJ15A unidirectional TVS (Vrwm 15 V)    | SMA            | 1   | Clamps V12 transients (cable inrush, regulator turn-on) |
| C1  | 22 µF / 25 V X7R (V12 input bulk)          | 1210           | 1   | U1 input bulk; smooths cable inductive ringing |

### 4.2 Power conversion

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| U1  | Recom R-78E3.3-0.5 (12 V → 3.3 V, 0.5 A) | SIP3 THT        | 1   | 80–90 % efficient, integrated; same family as battery-side U2 → common SPN inventory |
| C2  | 10 µF X7R (V3V3 bulk)                      | 0805           | 1   | Output bulk on R-78E3.3 |

### 4.3 MCU & support

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| MOD1 | ESP32-S3-WROOM-1-N16R8                    | SMD module     | 1   | Matches battery-side; common firmware base. (Same D-OPEN-1 question: -N8 vs -N16R8 — defer to reviewer) |
| C3  | 10 µF X7R (ESP bulk, ≤ 2 mm from 3V3 pin)  | 0805           | 1   | |
| C4  | 100 nF X7R (ESP HF decoupling, 0402 if possible) | 0402 | 1 | |
| C5  | 1 µF X7R (EN soft-start)                    | 0603           | 1   | |
| R1  | 10 kΩ EN pull-up                            | 0805           | 1   | |

### 4.4 E-paper interface (4.2" tri-color BWR, Waveshare 4.2 B v2)

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| LCD1 | Waveshare 4.2" e-Paper Module (B) v2 (panel only — we don't use the HAT) | bare panel | 1 | Bistable display; B&W partial refresh ~500–700 ms, color full refresh ~7 s. See [`decisions.md#d6`](decisions.md#d6-display-42-tri-color-bwr-e-paper). The driver IC is on the panel's own PCB tail, we connect via FFC |
| J2  | Hirose FH12-24S-0.5SH(55) FFC connector, 24-pin 0.5 mm pitch, top-contact | SMT | 1 | Mating to the panel's flex ribbon |
| C6  | 1 µF X7R (panel VCC bulk; some panels need this) | 0603 | 1   | Per Waveshare schematic; reduces VCC dip during refresh |

The FFC pinout (J2 pins) is panel-specific. The original SKiDL has a
placeholder mapping with notes that it MUST be verified against the
panel datasheet before fab. **CP1 commits to verifying this at CP2**;
the verified mapping will land in `hardware/layout/cp2_fcc_pinout.md`.

Tentative ESP↔panel signals (from the Waveshare 4.2" B v2 reference):

| Signal | ESP GPIO | Direction |
|--------|----------|-----------|
| BUSY   | GPIO8    | input     |
| RST    | GPIO7    | output    |
| DC     | GPIO6    | output    |
| CS     | GPIO5    | output    |
| CLK    | GPIO9    | output    |
| DIN    | GPIO10   | output    |
| VCC    | V3V3      | -         |
| GND    | GND       | -         |

SPI clock target: 4 MHz (conservative); 10 MHz achievable per panel
datasheet.

### 4.5 RS-485 interface

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| U2  | SN65HVD3082E                                | SOIC-8         | 1   | Same as battery-side U3 |
| R2  | 120 Ω 1 % termination, A ↔ B              | 0805           | 1   | This end is always the bus terminus → populated by default |
| R3  | 680 Ω idle bias: A → V3V3                  | 0805           | 1   | Optional — battery-side already biases the bus. **Power-first**: leave footprints, don't populate by default on hand-assembly. Reviewer to confirm |
| R4  | 680 Ω idle bias: B → GND                   | 0805           | 1   | (paired with R3, optional) |
| TVS2 | SMAJ12CA bidirectional                    | SMA            | 1   | RS-485 surge clamp |
| C7  | 100 nF X7R (U2 VCC decoupling)             | 0603           | 1   | |

**Power-first note**: depopulating R3/R4 (idle bias at this end) saves
~2.3 mA continuous on V3V3 → ~7.6 mW. The battery-side's bias is
sufficient to define the idle state for the whole bus. Footprints stay
so a future build can populate them if the bus topology changes.

### 4.6 User input (3 tactile buttons, software-defined labels)

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| BTN1, BTN2, BTN3 | 6×6×4.3 mm tactile SMT switch (e.g. C&K PTS525 SMT) | SMT | 3 | Mounted on the **bottom edge** of the PCB, on 18 mm centers; line up under faceplate cutouts |
| R5, R6, R7 | 1 MΩ pull-ups (BTN ↔ V3V3)        | 0805 ×3        | 3   | High-value to minimize Iq; ESP internal pullup also available as backup |
| C8, C9, C10 | 100 nF X7R RC debounce             | 0603 ×3        | 3   | RC = 100 ms — human-button slow |

**Change from existing schematic doc**: button function is **not
hardcoded**. The firmware decides what each button does based on
context, and renders matching labels on the e-paper directly above each
button. This is captured in [`decisions.md#d7`](decisions.md#d7-user-input-3-tactile-buttons-on-pcb-bottom-edge).

ESP GPIO mapping (BTN inputs):

| Button | ESP GPIO | Physical position (X mm from PCB left edge) |
|--------|----------|----------------------------------------------|
| BTN1   | GPIO12   | 22 mm                                        |
| BTN2   | GPIO13   | 42 mm (center)                               |
| BTN3   | GPIO14   | 62 mm                                        |

### 4.7 Status indicator

**None.** Per [D4](decisions.md#d4) — no idle indicator LEDs.

The e-paper handles all status display: red text for alerts, B&W partial
refresh for live updates, etc.

### 4.8 Dev / debug headers

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| J3  | 4-pin 2.54 mm header (UART debug: TX/RX/GND/RESET#) | THT | 1 | FTDI for ESP-IDF console |
| J4  | 4-pin 2.54 mm header (USB-OTG breakout: D+/D−/VBUS/GND) | THT | 1 | Firmware flash for bring-up |
| J5  | 2-pin 2.54 mm jumper (RS-485 term lift, R2 bypass) | THT | 1 | Same as battery-side |

## 5. Net list

| Net          | Voltage     | Source                | Sinks                                         | Notes |
|--------------|-------------|-----------------------|-----------------------------------------------|-------|
| V12_CAT5E    | 12 V        | J1 pins 1/2/3        | F1                                            | From battery side over Cat5e |
| V12_PROT     | 12 V        | F1 out               | TVS1, U1 VIN, C1                              | Post-PTC, post-TVS |
| V3V3         | 3.3 V       | U1 VOUT              | ESP3V3, U2 VCC, panel VCC, R3 (if pop), R5/R6/R7 | Switched 3.3 V (only one switch: the ESP itself sleeps) |
| GND          | 0 V         | (chassis)            | All IC GNDs, J1 pins 6/7/8                    | Single-point bond at battery side; J1 shield drain NC at this end |
| UART_TX_3V3  | 3.3 V       | ESP IO17              | U2 D pin                                       | RS-485 driver input |
| UART_RX_3V3  | 3.3 V       | U2 R pin              | ESP IO18                                       | RS-485 receiver output |
| DE_RE        | 3.3 V       | ESP IO2               | U2 DE & RE pins (tied)                         | Active-HIGH = transmit |
| RS485_A      | 0–5 V diff  | U2 A pin              | J1 pin 4, R2, R3 (opt), TVS2                   | Differential pair |
| RS485_B      | 0–5 V diff  | U2 B pin              | J1 pin 5, R2, R4 (opt), TVS2                   | (paired with A) |
| EPD_CS       | 3.3 V       | ESP IO5               | J2 (FFC CS pin)                                | SPI chip select |
| EPD_DC       | 3.3 V       | ESP IO6               | J2 (FFC DC pin)                                | Data/command |
| EPD_RST      | 3.3 V       | ESP IO7               | J2 (FFC RST pin)                                | Hardware reset, active-low |
| EPD_BUSY     | 3.3 V       | J2 (FFC BUSY pin)     | ESP IO8                                        | Panel ready-to-receive flag |
| SPI_SCK      | 3.3 V       | ESP IO9               | J2 (FFC CLK pin)                                | SPI clock |
| SPI_MOSI     | 3.3 V       | ESP IO10              | J2 (FFC DIN pin)                                | SPI data out (write-only) |
| BTN1_IN      | 3.3 V LV    | BTN1 + R5             | ESP IO12                                       | Active-LOW |
| BTN2_IN      | 3.3 V LV    | BTN2 + R6             | ESP IO13                                       | Active-LOW |
| BTN3_IN      | 3.3 V LV    | BTN3 + R7             | ESP IO14                                       | Active-LOW |
| RESET#       | 3.3 V LV    | ESP EN / J3 pin 4     | -                                              | Pulled HIGH via R1 + C5 |

## 6. ESP32-S3 pin assignment

Inherits from [`schematic_display_side.md`](../../docs/hardware/schematic_display_side.md)
with one change: GPIO15 (debug LED) is **unused** (D4); becomes
expansion pad on J3 or J4.

| GPIO   | Direction | Function                | Sleep behavior              |
|--------|-----------|--------------------------|------------------------------|
| GPIO0  | (strap)   | Bootloader strap         | -                            |
| GPIO2  | output    | RS-485 DE/RE             | Hi-Z in deep sleep           |
| GPIO5  | output    | E-paper CS               | Hi-Z; pulled HIGH externally? No — leave at last state |
| GPIO6  | output    | E-paper DC               | "                            |
| GPIO7  | output    | E-paper RST              | "                            |
| GPIO8  | input     | E-paper BUSY             | Hi-Z input                   |
| GPIO9  | output    | SPI SCK                  | "                            |
| GPIO10 | output    | SPI MOSI                 | "                            |
| GPIO12 | input     | BTN1 (RTC-capable)       | Wake source for "any button press" |
| GPIO13 | input     | BTN2 (RTC-capable)       | "                            |
| GPIO14 | input     | BTN3 (RTC-capable)       | "                            |
| GPIO15 | (expansion) | brought to J3, unused   | -                            |
| GPIO17 | UART1 TX  | to SN65HVD3082E D pin    | Hi-Z in deep sleep           |
| GPIO18 | UART1 RX  | from SN65HVD3082E R pin   | Hi-Z in deep sleep; **RS-485 RX wakes the ESP** (configure as RTC-capable wake) |
| GPIO19/20 | USB DM/DP | USB-OTG (J4 dev header) | Hi-Z; not on bus when unused |

## 7. Power budget (per [`power_budget.md`](../../docs/hardware/power_budget.md))

State A — Normal (showing live data, RS-485 RX, ESP light-sleep
between frames):

| Subsystem            | Avg draw on V3V3 | At V12 input (80 % eff) |
|----------------------|------------------|--------------------------|
| ESP32-S3 light-sleep | ~2 mA            |                          |
| RS-485 receive       | ~1 mA            |                          |
| Panel idle           | ~0               |                          |
| Panel refresh        | ~25 mA × 7 s every 30 s = 5.8 mA avg | |
| Subtotal             | ~8.8 mA at 3.3 V = 29 mW | ~36 mW at V12 = ~3 mA |

This is the typical state. At the 24 V pack end (R-78E12 80 % eff) →
~45 mW, in line with the existing power budget.

State B — Idle (no frames coming in for > 5 minutes, ESP deeper sleep):

| Subsystem            | Avg draw |
|----------------------|----------|
| ESP32-S3 deep sleep  | ~10 µA   |
| RS-485 receive       | ~1 mA    |
| Panel static         | 0        |
| Total                | ~1 mA at 3.3 V = 3.3 mW |

Could improve further by gating RS-485 receiver power via an N-FET on
the U2 VCC line — defer to a future revision; ~1 mA is fine.

State C — Hard cut (no V12 from battery side because Q1 is OFF over
there): **board is off**. No draw.

## 8. RS-485 interface

- Bus terminus → R2 populated.
- Idle bias (R3, R4) **footprints provided but unpopulated by default**;
  see §4.5.
- Shield drain wire from J1 is **NC** at this end. Single-point bond at
  battery side. (See [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md).)

## 9. Decoupling strategy

| Cap   | Value  | Net     | Placement (within mm of pin) | Function       |
|-------|--------|---------|------------------------------|----------------|
| C1    | 22 µF  | V12_PROT | U1 VIN < 5 mm                | Input bulk     |
| C2    | 10 µF  | V3V3    | U1 VOUT < 5 mm               | Output bulk    |
| C3    | 10 µF  | V3V3    | ESP 3V3 pin < 2 mm           | ESP bulk       |
| C4    | 100 nF | V3V3    | ESP 3V3 pin < 2 mm           | ESP HF (0402 if possible) |
| C5    | 1 µF   | EN net  | ESP EN < 5 mm                | Soft-start    |
| C6    | 1 µF   | V3V3 (panel) | J2 VCC pin < 3 mm        | Panel refresh dip suppression |
| C7    | 100 nF | V3V3    | U2 VCC < 2 mm                | RS-485 decoupling |
| C8, C9, C10 | 100 nF | BTNn_IN | -                       | Button RC debounce (×3) |

## 10. Layout strategy

### 10.1 Layer stackup

2-layer; same convention as battery-side (F.Cu for signals, B.Cu for
ground pour).

### 10.2 Placement priorities

1. **J2 FFC on the long edge** (top of board, the side closest to the
   e-paper panel above the buttons in the faceplate). The panel ribbon
   bends only 90° from panel back to PCB front.
2. **Buttons BTN1/2/3 on the bottom edge**, in a row, 18 mm centers,
   centered laterally on the PCB. So at X = (PCB_width − 2×18 mm) / 2 =
   (85 − 36) / 2 = 24.5 mm to first button center → buttons at
   24.5 mm / 42.5 mm / 60.5 mm. Slightly off the rules I stated above —
   reconciling: **use 24, 42, 60 mm to match a 3 mm offset from the
   left mounting hole.**
3. **ESP32-S3 antenna pointing toward the box back wall** (away from
   the e-paper panel — the panel has a metal-foil back layer that
   reflects RF and might detune the antenna).
4. **U1 (R-78E3.3) tall** — SIP3 footprint sticks up ~9 mm. Place on
   the **back** of the PCB (B.Cu side) so it points into the empty
   double-gang box space, not into the e-paper panel.
5. **RS-485 + RJ45 on a short edge**, accessible from the back of the
   box (where the in-wall Cat5e arrives). Either short edge works
   mechanically; preference is the LEFT edge (X = 0) so the cable
   doesn't push the box too far forward.
6. **Buttons exit the PCB toward the faceplate side**; their height
   plus PCB to faceplate distance must clear the box's interior front
   ribs. Tactile switch is 4.3 mm tall; PCB + standoff stack adds ~5 mm;
   total ~10 mm from PCB back to button cap top. Faceplate sits ~12 mm
   in front of the PCB back. Caps need 2 mm of travel to actuate plus
   the faceplate's 2 mm thickness → caps need to be ~4 mm above the
   faceplate front surface to be operable. Will need ~5–6 mm cap height
   custom or a longer rubber dome cap. **3D-print extension required.**

### 10.3 Net classes

| Class      | Width    | Clearance | Nets                                       |
|------------|----------|-----------|---------------------------------------------|
| Power-12V  | 0.5 mm   | 0.25 mm   | V12_CAT5E, V12_PROT                         |
| Power-3V3  | 0.4 mm   | 0.2 mm    | V3V3                                        |
| Default sig| 0.2 mm   | 0.20 mm   | UART, SPI, BTN_IN, EPD_*                    |
| RS485-diff | 0.25 mm  | 0.2 mm    | RS485_A, RS485_B (route as pair)            |

### 10.4 Ground

B.Cu continuous ground pour. Stitching vias every 10 mm. The FFC J2's
GND pins all tie to the pour directly; no thermal relief on those (they
carry the return current for SPI signal edges).

## 11. JLCPCB design-rule compliance

Same as battery-side §12 (all CP1 design rules within JLCPCB's 6-mil
minimum).

## 12. Open decisions for reviewer

| ID            | Question | Default if no reviewer input |
|---------------|----------|------------------------------|
| **D-OPEN-1**  | ESP32-S3-WROOM-1-N16R8 vs -N8? | N16R8 (consistent with battery side) |
| **D-OPEN-8**  | Populate R3/R4 idle-bias on display side or leave footprints unpopulated? | **Unpopulated by default** — battery-side bias is sufficient |
| **D-OPEN-9**  | RS-485 receiver power-gate (N-FET on U2 VCC) for further idle-current reduction? | **No** — adds complexity for ~1 mA savings; defer to v2 |
| **D-OPEN-10** | Button hardware-debounce RC values? CP1 specs 1 MΩ + 100 nF (RC = 100 ms). Some prefer 10 kΩ + 100 nF (RC = 1 ms, faster response). | **100 ms** — human buttons; the RC delay is invisible. 1 MΩ keeps Iq trivially low even if any GPIO ever inverts polarity at fab |
| **D-OPEN-11** | Where does the panel mount mechanically? (a) on the PCB front via M2 standoffs, (b) on the 3D-printed bracket separately from the PCB, (c) glued to the faceplate? | **(b) — on the 3D-printed bracket**, panel sits between PCB and faceplate. User redesigns the bracket if (a) or (c) is preferred |
| **D-OPEN-12** | Faceplate dimensions — 115 × 117 mm to match standard double-gang, or larger? | **115 × 117 mm** matches user's reference; can override at CP5 |

## 13. Risk register

1. **FFC connector pinout verification** — the SKiDL placeholder mapping
   for J2 must be replaced with verified panel datasheet mapping before
   CP2. The Hirose FH12-24S has a fixed pin-1 indication, but the
   panel's flex tail can be flipped — verify by tracing the panel's own
   PCB tail on the actual unit at hand or against the Waveshare 4.2"
   B v2 schematic from manufacturer.
2. **Tactile button cap height** — 4.3 mm switch + standoffs leaves
   ~10 mm from PCB back to cap top, while the faceplate sits ~12 mm
   ahead. Need cap extensions in the 3D print. Compute exactly at CP3
   based on actual standoff stack.
3. **R-78E3.3 SIP3 footprint orientation** — taller side of the module
   must face AWAY from the e-paper to avoid clearance issues.
4. **Panel SPI bus timing on 4 MHz** — verify partial refresh works at
   our intended ~500 ms target; if SPI is too slow, increase to 10 MHz
   per panel datasheet.

## 14. What changed vs the existing `docs/hardware/` baseline

| Section                          | Old                                     | CP1                                          |
|----------------------------------|-----------------------------------------|----------------------------------------------|
| Form factor                      | Single-gang plate                       | Double-gang plastic old-work box, 3D-printed faceplate |
| Board outline                    | ~85 × 60 mm                              | 85 × 65 mm — slightly bigger thanks to double-gang  |
| Button function                  | Hardcoded (Refresh / Next-screen / Release-BLE) | **Software-defined**, with on-screen labels rendered next to each button |
| Debug LED                        | LED1 + R_led                            | **Removed** per D4                          |
| Idle bias on RS-485              | R11/R12 populated (~2.3 mA)              | Footprints provided, unpopulated by default per D5 |
| Mounting                         | Single-gang low-voltage bracket          | Custom 3D-printed bracket (drops into double-gang box and secures PCB) |
| Faceplate                        | Blank single-gang plate, cut for window  | Custom 3D-printed plate (user designs against PCB STEP from CP5) |

## 15. What's NOT in CP1

- Verified FFC pin mapping for the panel (CP2)
- Schematic capture in KiCad (CP2)
- Footprint placement (CP3)
- Routing (CP4)
- PCB STEP export for faceplate design (CP5)
- 3D-printed bracket / faceplate STL/STEP files (user-owned)
