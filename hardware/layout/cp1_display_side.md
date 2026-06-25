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

- 84.8 × 63.6 mm rectangular window for e-paper active area (Waveshare 4.2" (B) verified active area), centered
  vertically with ~5 mm offset toward the top edge to leave room for
  the button labels
- 3× round clearance holes (sized to the chosen plunger ⌀, ~4–6 mm) along
  the bottom edge, on 18 mm centers, for the **tall tactile actuators to poke
  through** (~16 mm horizontal span between centers of buttons 1 and 3)

The user designs the faceplate against a STEP file of the PCB +
mechanical envelope, exported at CP5.

### 2.1 Assembly & depth stack (D27 — aggressive mechanical pass)

The double-gang box is **shallow (~45 mm usable depth)**, which is the
binding mechanical constraint. The stack, front → back:

```
faceplate (~3 mm) → e-paper MODULE (glass + driver PCB, ~4 mm)
   → gap/standoffs → main PCB (1.6 mm + part heights) → bracket → box floor
```

Hard constraints this imposes (CP3 must honor; a depth tally is produced then):

- **Tall THT parts eat the budget.** A vertical RJ45 (~13–21 mm) and the
  R-78E3.3 SIP (~11 mm) would blow the depth. → **right-angle / low-profile
  RJ45** (also lets the in-wall Cat5e enter from the side/bottom cleanly);
  orient/seat the R-78 for minimum height. Keep tall parts off the
  module-facing side.
- **The e-paper module doesn't fit *inside* the box.** Its **driver-board
  outline is 103.0 × 78.5 mm** (the 91 × 77 mm figure is the screen/panel
  only — reviewer Finding 02), which exceeds the ~95 mm box interior. → **mount the module to the back of the oversized custom
  faceplate** (~115×117 mm), with the main PCB in the box behind it; the
  8-pin SPI cable (DR-7) runs between, with slack + a strain-relief anchor.
- **Button actuator height spans the PCB→faceplate gap + protrudes slightly**
  (user call: real tall-actuator THT tactiles, not printed caps). The plunger
  length can only be fixed once the depth stack is → pick the catalog height
  at CP3/CP5 from the PCB STEP (§4.6).
- **Service port (D27, geometry corrected):** the box is recessed in the
  wall, so a "bottom" port isn't accessible — only the faceplate front is
  exposed. Routine firmware is **OTA over RS-485** (battery side pulls it
  via WiFi), so the display's USB is **bench/recovery only**: a board-edge
  **USB-C** reached by **popping the faceplate** (detaches without wall
  removal) — **no front cutout**. The faceplate is specified as a
  snap/magnetic pop-off for exactly this.
- **No antenna keepout** (D26): the display radio is unused (RS-485 link),
  so the WROOM antenna region carries no keepout — frees the layout.

**Depth tally (computed now, not deferred — confirm exact part dims at CP3):**

| Element, front → back into the ~45 mm usable box        | Depth   |
|---------------------------------------------------------|---------|
| e-paper module (panel 1.2 mm + driver PCB + connector)  | ~5 mm   |
| module-back → PCB-front standoff gap (clears 8-pin cable + button throw) | ~8 mm |
| main PCB                                                 | 1.6 mm  |
| tallest back-side part: R-78E3.3 SIP (oriented low) **or** low-profile right-angle RJ45 | ~11 mm |
| bracket standoff + clearance to box floor               | ~5 mm   |
| **Total**                                               | **~30–31 mm** |

Against ~45 mm usable → **~14 mm margin**. The binding parts are the
R-78E3.3 SIP (~11 mm vertical) and the RJ45; both are addressable — a
**low-profile right-angle RJ45 protrudes only ~4.4 mm above the PCB** (e.g.
SUYIN 100362-series, 9.6 mm overall), and the R-78 is oriented for minimum
height. Even with a standard ~13 mm right-angle RJ45 the total stays
~33 mm. **Module dims (reviewer Finding 02): driver-board (binding for the
faceplate mount) = 103.0 × 78.5 mm; screen/panel = 91 × 77 mm; active area
84.8 × 63.6 mm.** The 103 mm board exceeds the ~95 mm box interior but mounts
to the faceplate regardless (D-OPEN-11) — and still fits the 115 × 117 mm
faceplate; **lay out the mounting bosses, cable exit, and M2 holes against
103 × 78.5 mm, not 91 × 77 mm.** The earlier ~21 mm vertical-RJ45 worry is
exactly what the right-angle choice removes. CP3 re-checks the ~5 mm module
thickness against the physical part.

**Deliverable:** the **PCB STEP** (with the e-paper-module envelope +
connector/button/USB-C positions) is the contract the user designs the
bracket + faceplate against.

## 3. Power architecture

```
+12 V from Cat5e (J1 RJ45 pins 1/2/3)
    │
    ▼
F1 [PTC polyfuse ~0.25 A hold (DR-11)]    ← resettable; protects cable
    │
    ▼
TVS1 [SMAJ15A unidirectional, V12 ↔ GND]   ← inductive kick from cable
    │
    ▼
U1 [Recom R-78E3.3-0.5, 12 V → 3.3 V, 0.5 A] ← stocked module, no inductor BOM
    │
    ▼
3V3 ──┬─── ESP32-S3 (MOD1)
      ├─── e-paper VCC (LCD1 module via 8-pin J2)
      ├─── SN65HVD3082E (U2) VCC
      └─── RS-485 bias (R3/R4 ~330 Ω — the bus's only bias; see §4.5)
```

No 24 V on this board. No RTC chip (time syncs from RS-485 frames). No
load-switching MOSFETs (the e-paper draws ~0 in idle thanks to its
bistable display; the ESP32-S3 self-manages its sleep states).

## 4. Component list

### 4.1 Power input

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| J1  | **Right-angle / low-profile RJ45** jack (T568B), shielded | THT shielded   | 1   | **Right-angle (DR-10):** a vertical jack (~13–21 mm) blows the shallow-box depth budget; right-angle keeps height down and lets the in-wall Cat5e enter from the side/bottom. Shield drain NOT bonded here (single-point bond at battery side, [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md)). |
| F1  | PTC polyfuse, **~0.25 A hold** (DR-11) | THT radial   | 1 | Resettable cable protection. 0.25 A covers the ~40 mA load + ~150 mA refresh/inrush peaks, and trips well below the battery-side U2's ~0.5 A foldback → real cable + upstream protection (was 0.5 A — too loose). |
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
| MOD1 | ESP32-S3-WROOM-1-N16R8 (`-1`)             | SMD module     | 1   | Matches battery-side (firmware + footprint commonality). **Radio unused** — RS-485 is the only link, so disable RF in firmware and **drop the antenna keepout** (D26). **D-OPEN-1 RESOLVED (D31): keep -N16R8 on both boards** — the $1.10 vs -N8 is moot at build qty 1; one SKU avoids mix-ups. PSRAM unused (30 KB framebuffer fits internal SRAM). |
| J-USB | **USB-C receptacle** on native ESP32-S3 USB (board edge) | SMD | 1 | **D27:** bench/recovery port — reached by popping the faceplate (no front cutout). Routine firmware is OTA over RS-485, so it's rarely used. |
| U-ESD | USB ESD array (USBLC6-2)                   | SOT-23-6       | 1   | ESD clamp on the USB-C D+/D−/VBUS (D27). |
| U3-LDO | 3.3 V LDO (AP2112K-3.3, ~600 mA), VBUS→3V3_USB | SOT-23-5 | 1 | **USB maintenance power (D29):** run/program/troubleshoot the display MCU off USB **without 12 V**. VBUS-referenced → zero draw when unplugged. |
| U4-MUX | **TI TPS2116** priority power mux (~1.3 µA Iq, reverse-blocking) | SOT-23-6 | 1 | **D29:** VIN1=USB-LDO (priority), VIN2=R-78E3.3 output, OUT=V3V3. USB present → R-78E3.3 idles. **No UVLO bypass** — the display has no supervisor (it's shed by the battery side), so simpler than the battery board. No 5 V on V3V3 (LDO). |
| C3  | 10 µF X7R (ESP bulk, ≤ 2 mm from 3V3 pin)  | 0805           | 1   | |
| C4  | 100 nF X7R (ESP HF decoupling, 0402 if possible) | 0402 | 1 | |
| C5  | 1 µF X7R (EN soft-start)                    | 0603           | 1   | |
| R1  | 10 kΩ EN pull-up                            | 0805           | 1   | |

### 4.4 E-paper interface (4.2" tri-color BWR, Waveshare 4.2 B v2)

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| LCD1 | **Waveshare 4.2inch e-Paper Module (B)** — module **with onboard driver PCB + 8-pin SPI header** | module | 1 | Bistable B/W/R; B&W partial refresh ~500–700 ms, color full refresh ~7 s. See [`decisions.md#d6`](decisions.md#d6-display-42-tri-color-bwr-e-paper). The driver + booster live on the module; we provide only 3.3 V + SPI (DR-7) |
| J2  | **JST-PH 2.0 mm, 8-pin** post header (B8B-PH-K-S top-entry; S8B-PH-K-S side-entry option), e-paper SPI; service = unplug | THT 1×8 | 1 | **Matches the module's connector (verified):** the Waveshare Module (B) onboard connector is **JST-PH 2.0 mm 8-pin** and ships with a PH2.0 20 cm 8-pin cable. We put the **same JST-PH family on our board** so an off-the-shelf **pre-crimped PH↔PH cable assembly** (e.g. JST ASPHSPH24K102-class) connects module↔board — **no crimp tool**. **JST-PH is mechanically keyed/latched → can't seat reversed** (the earlier 2.54 mm-header + printed-keying-rib plan is dropped). **Δ (DR-7): was a 24-pin Hirose FH12-24S FFC** (the *bare*-panel connector, needs a booster network we don't carry). The module is on the pop-off faceplate, J2 on the PCB behind; the ~200 mm cable gives service slack — faceplate-off = unplug. CP3: pick top- vs side-entry from the cable-routing/depth stack. |
| C6  | 1 µF X7R (panel VCC bulk) | 0603 | 1   | Reduces V3V3 dip during refresh |

**J2 8-pin pinout** (canonical Waveshare e-paper interface — match the
physical pin order to the module's silk at assembly):

| J2 pin | Signal | Net | ESP GPIO | Direction |
|--------|--------|-----|----------|-----------|
| 1 | VCC  | V3V3      | —      | 3.3 V |
| 2 | GND  | GND       | —      | — |
| 3 | DIN  | SPI_MOSI  | GPIO10 | out |
| 4 | CLK  | SPI_SCK   | GPIO9  | out |
| 5 | CS   | EPD_CS    | GPIO5  | out |
| 6 | DC   | EPD_DC    | GPIO6  | out |
| 7 | RST  | EPD_RST   | GPIO7  | out |
| 8 | BUSY | EPD_BUSY  | GPIO8  | in |

SPI clock target: 4 MHz (conservative); 10 MHz achievable per the module
datasheet. *(This closes the old "verify the FFC pinout at CP2" open item —
there's no FFC; the module exposes the fixed 8-signal SPI bus above.)*

### 4.5 RS-485 interface

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| U2  | SN65HVD3082E                                | SOIC-8         | 1   | Same as battery-side U3 |
| R2  | 120 Ω 1 % termination, A ↔ B              | 0805           | 1   | This end is always the bus terminus → populated by default |
| R3  | ~330 Ω idle bias: A → V3V3                 | 0805           | 1   | **POPULATED — the bus's ONLY fail-safe bias (D19/DR-4).** ~330 Ω gives **~275 mV** idle across the two 120 Ω terminators (60 Ω ∥) — ~38 % over the 200 mV floor (DR-13; was 390 Ω → 236 mV, only ~18 %). Free margin: this bias is display-end, shed at hard-cut. Reviewer to confirm vs the SN65HVD3082E guaranteed threshold |
| R4  | ~330 Ω idle bias: B → GND                  | 0805           | 1   | (paired with R3) |
| TVS2 | SMAJ12CA bidirectional                    | SMA            | 1   | RS-485 surge clamp |
| C7  | 100 nF X7R (U2 VCC decoupling)             | 0603           | 1   | |

**Power-first note (D19/DR-4)**: the bus's idle bias lives **here, on the
display end** — *not* on the battery side. The battery 3V3 rail is now
always-on, so battery-side bias (~2.3 mA) would draw continuously and blow
the ~1 mW hard-cut budget. On the display side, the bias is sourced from
the display 3V3, which is **shed with the display** when the battery opens
Q1 at low SOC — so it costs nothing in the state that matters. Resized
680 → ~330 Ω so a single bias point clears 200 mV idle across both
terminators.

### 4.6 User input (3 tactile buttons, software-defined labels)

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| BTN1, BTN2, BTN3 | **THT tall-actuator tactile switch** (6×6 mm body, long plunger — e.g. the 6×6×N mm family, N ≈ 13–17 mm) | THT | 3 | **User call (2026-06-23): real tactile button whose actuator protrudes slightly through the faceplate** — no printed caps. Mounted on the **bottom edge**, actuator pointing **toward the faceplate (+Z)**, on 18 mm centers under the faceplate cutouts. **Actuator height = (PCB-front → faceplate-front gap) + ~2–3 mm protrusion**; the gap is set by the module/standoff depth stack, so the exact plunger length is locked at CP3/CP5 from the PCB STEP (DR-10). Pick the catalog height nearest that figure |
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

**No status LED** (consistent with D4) — and deliberately **no last-gasp
supercap** either (a tri-color refresh is ~7 s / ~1.3 J → would need ~0.7 F,
and wouldn't reliably complete on a dying rail). Instead, "is the display
dead?" is solved in firmware/sequencing per **D30**:
- **"Last updated HH:MM" timestamp on every refresh** — a frozen e-paper
  showing a stale time is the unmistakable tell (covers both comms-loss and
  power-loss, since the bistable image keeps the old time).
- **Graceful pre-shed render** — the battery side sends a "sleeping" frame
  and waits for the display to draw it *before* opening Q1; the bistable
  screen then holds "Monitor sleeping — low battery."
- **Battery-side heartbeat detection** — missing display acks → flagged via
  the WiFi push (D25).
- Comms-dead-but-powered is already caught by `watchdog_task` ("LINK DOWN").

A status LED was rejected because it **dies with the board** → tells you
nothing about the power-loss case. See D30.

### 4.8 Dev / debug headers

| Ref | Part                                       | Pkg            | Qty | Rationale |
|-----|--------------------------------------------|----------------|-----|-----------|
| J3  | 4-pin 2.54 mm header (UART debug: TX/RX/GND/RESET#) | THT | 1 | FTDI for ESP-IDF console |
| J4  | _(removed — superseded by the USB-C maintenance port, D27)_ | — | 0 | Native USB now exits J-USB (USB-C); keep one UART header (below) for bench bring-up. |
| J5  | 2-pin 2.54 mm jumper (RS-485 term lift, R2 bypass) | THT | 1 | Same as battery-side |

## 5. Net list

| Net          | Voltage     | Source                | Sinks                                         | Notes |
|--------------|-------------|-----------------------|-----------------------------------------------|-------|
| V12_CAT5E    | 12 V        | J1 pins 1/2/3        | F1                                            | From battery side over Cat5e |
| V12_PROT     | 12 V        | F1 out               | TVS1, U1 VIN, C1                              | Post-PTC, post-TVS |
| V3V3         | 3.3 V       | **U4-MUX OUT (TPS2116)** — sources: R-78E3.3 (VIN2) / USB-LDO U3-LDO (VIN1, priority) | ESP3V3, U2 VCC, panel VCC, R3 (if pop), R5/R6/R7 | USB present → from USB-LDO (R-78E3.3 idles); USB absent → from R-78E3.3. D29 (mirrors battery side; **no UVLO bypass** — display has no supervisor) |
| 3V3_USB      | 3.3 V       | U3-LDO (from VBUS)   | TPS2116 VIN1 (U4-MUX)                          | USB maintenance rail (D29); present only with a cable in; VBUS-referenced |
| VBUS         | 5 V (USB)   | J-USB VBUS           | U-ESD, U3-LDO VIN                              | Present only with a USB cable; powers the USB-LDO (D29). **Never tied to V3V3** (LDO regulates — reviewer F04) |
| GND          | 0 V         | (chassis)            | All IC GNDs, J1 pins 6/7/8                    | Single-point bond at battery side; J1 shield drain NC at this end |
| UART_TX_3V3  | 3.3 V       | ESP IO17              | U2 D pin                                       | RS-485 driver input |
| UART_RX_3V3  | 3.3 V       | U2 R pin              | ESP IO18                                       | RS-485 receiver output |
| DE_RE        | 3.3 V       | ESP IO2               | U2 DE & RE pins (tied)                         | Active-HIGH = transmit |
| RS485_A      | 0–5 V diff  | U2 A pin              | J1 pin 4, R2, R3 (opt), TVS2                   | Differential pair |
| RS485_B      | 0–5 V diff  | U2 B pin              | J1 pin 5, R2, R4 (opt), TVS2                   | (paired with A) |
| EPD_CS       | 3.3 V       | ESP IO5               | J2 (CS pin)                                | SPI chip select |
| EPD_DC       | 3.3 V       | ESP IO6               | J2 (DC pin)                                | Data/command |
| EPD_RST      | 3.3 V       | ESP IO7               | J2 (RST pin)                                | Hardware reset, active-low |
| EPD_BUSY     | 3.3 V       | J2 (BUSY pin)     | ESP IO8                                        | Panel ready-to-receive flag |
| SPI_SCK      | 3.3 V       | ESP IO9               | J2 (CLK pin)                                | SPI clock |
| SPI_MOSI     | 3.3 V       | ESP IO10              | J2 (DIN pin)                                | SPI data out (write-only) |
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
| GPIO0  | (strap)   | Bootloader strap         | weak pull-up                 |
| GPIO3  | (strap)   | USB-JTAG select; leave NC (internal default) | - (reviewer F05) |
| GPIO45 | (strap)   | VDD_SPI strap; leave NC (internal default)   | - (reviewer F05) |
| GPIO46 | (strap)   | Boot-mode strap; leave NC (internal default) | - (reviewer F05) |
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
| GPIO19/20 | USB DM/DP | native USB → USB-C port (J-USB), ESD-clamped | maintenance port (D27) |

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

This is the typical state. At the 24 V pack end (U2 R-78HB12, 80 % eff) →
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
- Idle bias (R3, R4, ~330 Ω) **populated — this is the bus's only
  fail-safe bias** (D19/DR-4; battery side carries none). See §4.5.
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
| C_usb1, C_usb2 | 1 µF | 3V3_USB / VBUS | U3-LDO in/out < 2 mm   | AP2112 in/out (D29, reviewer F04) |
| C_mux | ~47 µF | V3V3 | TPS2116 OUT < 5 mm           | Mux OUT bulk for RCB on USB hot-plug (D29; mirrors battery C13, reviewer F11) |

## 10. Layout strategy

### 10.1 Layer stackup

2-layer; same convention as battery-side (F.Cu for signals, B.Cu for
ground pour).

### 10.2 Placement priorities

1. **J2 (8-pin header) on the long edge** (top of board, closest to the
   e-paper module above the buttons in the faceplate), so the module's
   8-pin cable run to the board is short.
2. **Buttons BTN1/2/3 on the bottom edge**, in a row, 18 mm centers,
   centered laterally on the PCB. So at X = (PCB_width − 2×18 mm) / 2 =
   (85 − 36) / 2 = 24.5 mm to first button center → buttons at
   24.5 mm / 42.5 mm / 60.5 mm. Slightly off the rules I stated above —
   reconciling: **use 24, 42, 60 mm to match a 3 mm offset from the
   left mounting hole.**
3. **No antenna placement constraint (D26):** the radio is unused
   (RS-485 link), so there's no antenna keepout/orientation to honor —
   freed layout. (No PCB-antenna-vs-panel-foil concern.)
4. **Watch the depth stack (DR-10).** Keep tall parts low and off the
   module-facing side: the **R-78E3.3 SIP (~9–11 mm)** and the RJ45 are the
   offenders. Place the R-78 flat/on the back pointing into the box;
   confirm the full faceplate→module→PCB→bracket→floor tally fits the
   ~45 mm box at CP3.
5. **Right-angle / low-profile RJ45 on a short edge** (DR-10), so the
   in-wall Cat5e enters from the side/bottom and the jack doesn't consume
   depth. Preference: LEFT edge so the cable doesn't push the box forward.
6. **USB-C bench/recovery port at a board edge** (D27) — reached by
   popping the faceplate (no front cutout); routine updates are OTA over
   RS-485, so it's rarely used.
7. **Buttons exit the PCB toward the faceplate (+Z)** with a **tall-actuator
   THT tactile** whose plunger reaches through the faceplate cutout and
   **protrudes ~2–3 mm** for an easy press (user call — no printed caps).
   Actuator length = (PCB-front → faceplate-front gap) + protrusion; the gap
   is set by the module/standoff depth stack, so pick the catalog plunger
   height at CP3/CP5 from the PCB STEP. The faceplate carries a clearance
   hole per button (not a cap pocket). Keep the switch bodies clear of the
   box's interior front ribs.

### 10.3 Net classes

| Class      | Width    | Clearance | Nets                                       |
|------------|----------|-----------|---------------------------------------------|
| Power-12V  | 0.5 mm   | 0.25 mm   | V12_CAT5E, V12_PROT                         |
| Power-3V3  | 0.4 mm   | 0.2 mm    | V3V3                                        |
| Default sig| 0.2 mm   | 0.20 mm   | UART, SPI, BTN_IN, EPD_*                    |
| RS485-diff | 0.25 mm  | 0.2 mm    | RS485_A, RS485_B (route as pair)            |

### 10.4 Ground

B.Cu continuous ground pour. Stitching vias every 10 mm. The J2 header's
GND pins all tie to the pour directly; no thermal relief on those (they
carry the return current for SPI signal edges).

## 11. JLCPCB design-rule compliance

Same as battery-side §12 (all CP1 design rules within JLCPCB's 6-mil
minimum).

## 12. Open decisions for reviewer

| ID            | Question | Default if no reviewer input |
|---------------|----------|------------------------------|
| **D-OPEN-1**  | ESP32-S3-WROOM-1-N16R8 vs -N8? | N16R8 (consistent with battery side) |
| ~~**D-OPEN-8**~~ | Populate R3/R4 idle-bias on display side? | **RESOLVED (D19/DR-4): populate at ~330 Ω** — this is the bus's *only* bias (battery side carries none, to keep its always-on rail at zero static draw) |
| **D-OPEN-9**  | RS-485 receiver power-gate (N-FET on U2 VCC) for further idle-current reduction? | **No** — adds complexity for ~1 mA savings; defer to v2 |
| **D-OPEN-10** | Button hardware-debounce RC values? CP1 specs 1 MΩ + 100 nF (RC = 100 ms). Some prefer 10 kΩ + 100 nF (RC = 1 ms, faster response). | **100 ms** — human buttons; the RC delay is invisible. 1 MΩ keeps Iq trivially low even if any GPIO ever inverts polarity at fab |
| ~~**D-OPEN-11**~~ | Panel mount? | **RESOLVED (D27/DR-10):** the e-paper **module mounts to the back of the oversized custom faceplate** (the ~90–103 mm module doesn't fit inside the ~95 mm box); the main PCB sits in the box behind, 8-pin cable between. |
| **D-OPEN-12** | Faceplate dimensions — 115 × 117 mm to match standard double-gang, or larger? | **115 × 117 mm** matches user's reference; can override at CP5 |

## 13. Risk register

1. ~~**FFC connector pinout verification**~~ — **RESOLVED (DR-7):** there
   is no FFC. J2 is an **8-pin JST-PH 2.0 mm** post header matching the
   Waveshare Module (B)'s onboard PH connector (§4.4) — keyed by design.
   Residual: match the physical pin order on J2 to the module's silk/cable.
2. **Tall-actuator tactile plunger length** — pick the catalog height so the
   plunger spans the PCB-front→faceplate gap and protrudes ~2–3 mm through
   the faceplate hole (user call — no printed caps). Lock the exact height at
   CP3 from the actual standoff/depth stack.
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
| Idle bias on RS-485              | Battery-side R11/R12 (~2.3 mA, always-on leak under D19) | **Moved here, populated at ~330 Ω** — the bus's only bias; shed with the display at low SOC (D19/DR-4) |
| Mounting                         | Single-gang low-voltage bracket          | Custom 3D-printed bracket (drops into double-gang box and secures PCB) |
| Faceplate                        | Blank single-gang plate, cut for window  | Custom 3D-printed plate (user designs against PCB STEP from CP5) |

## 15. What's NOT in CP1

- Final J2 8-pin pin-order match to the e-paper module silk (CP2)
- Schematic capture in KiCad (CP2)
- Footprint placement (CP3)
- Routing (CP4)
- PCB STEP export for faceplate design (CP5)
- 3D-printed bracket / faceplate STL/STEP files (user-owned)
