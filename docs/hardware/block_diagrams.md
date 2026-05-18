# Hardware block diagrams

## System

```
       ┌──────────── batteries (under-floor, sealed) ────────────┐
       │                                                          │
       │   BMS-33  (V-12V200AH-0533)   BMS-67 (V-12V200AH-0667)  │
       │      │                            │                     │
       │      └──── BLE 4.0 (~1–3 m) ──────┘                     │
       │                    │                                     │
       └────────────────────│─────────────────────────────────────┘
                            │
                  ┌─────────▼─────────────┐
                  │  BATTERY-SIDE BOARD    │
                  │  (sealed enclosure,    │  ◄── 24 V tap, fused
                  │   IP65, near floor)    │
                  └──┬─────────┬────┬──────┘
                     │         │    │
              data (RS-485)  +12V  GND
                     │         │    │
        ┌────────────│─────────│────│────────────────┐
        │            │         │    │                │
        │      Cat5e (shielded, ~5 m, in-wall)       │
        │            │         │    │                │
        │            │         │    │                │
        └────────────│─────────│────│────────────────┘
                     │         │    │
                  ┌──▼─────────▼────▼──────┐
                  │  DISPLAY-SIDE BOARD    │
                  │  (single-gang wall     │
                  │   mount in kitchen)    │
                  └──────────┬─────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  4.2" e-paper panel   │
                  │  + 3 tactile buttons  │
                  └──────────────────────┘
```

Cat5e carries 4 functions over its 4 twisted pairs:

| Pair | Purpose             | Direction              |
|------|---------------------|------------------------|
| 1    | RS-485 A / B        | Bidirectional (half-duplex) |
| 2    | +12 V DC            | Battery side → display  |
| 3    | +12 V DC (parallel) | Battery side → display  |
| 4    | DC return (GND)     | Battery side → display  |

Power flows *from* the battery side. The kitchen AC outlet at the
display location is **deliberately unused** — going through the
inverter would burn 10–50 W in inverter idle losses for a 1 W load.

## Battery-side board (block-level)

```
                   24 V tap (fused 1 A)
                          │
                          ▼
                ┌──────────────────┐
                │ TPS62933 buck     │── 3.3 V rail ─┐
                │ 24 → 3.3 V         │              │
                │ (Q-curr ~22 µA)   │              │
                └──────────────────┘              │
                                                  │
                ┌──── 12 V buck (Recom R-78E12) ──┴── +12 V to Cat5e
                │
                ▼
            ┌───────────────┐
            │ ESP32-S3      │
            │ WROOM-1       │   ◄── DS3231 RTC (I²C, battery-backed)
            │ N16R8         │
            │               │
            │ ┌─ ULP ────┐  │   ◄── 24 V ADC sense (through 1:10 divider)
            │ │          │  │
            │ └─ BLE 5  ─┘  │   ◄── override button (RTC-wake-capable GPIO)
            │  GPIO bank   │
            └──┬───────────┘   ──► P-MOSFET load switch (kills the entire
               │                     downstream rail when SOC < 10%)
               │
               ▼
      ┌──────────────────┐
      │  SN65HVD3082      │ ◄────► RS-485 A/B  (Cat5e pair 1)
      │  RS-485 xceiver  │
      └──────────────────┘
                    ▲
                    │
                  GND (Cat5e pair 4) — shield bonded to chassis HERE only
```

Three power domains worth keeping clear in your head:

1. **Always-on**: DS3231 + ESP32 ULP (~25 µA total).
2. **Switched** (controlled by ESP32-S3 main core): RS-485 driver,
   3.3 V → MCU active state, 12 V → Cat5e.
3. **Hard-cut** (P-MOSFET kills it): everything except the ULP voltage
   sense. Re-engages on voltage recovery.

## Display-side board (block-level)

```
        +12 V from Cat5e ──────► Recom R-78E3.3 ──── 3.3 V rail
                                                          │
                                                          ▼
                                                ┌───────────────┐
                                                │ ESP32-S3      │
                                                │ WROOM-1       │
                                                │ N16R8         │
                                                │               │  ┌─ button: refresh-now
                                                │  GPIO bank ──┼──┼─ button: change-screen
                                                │               │  └─ button: release-BLE
        ┌─── e-paper 24-pin FFC ──────► SPI ───┤               │
        │   (CS, DC, RST, BUSY, MOSI, SCK)     │               │
        │                                       └──────┬────────┘
        │                                              │
        ▼                                              ▼
  4.2" e-paper                              ┌───────────────────┐
  (tri-color, B-version)                    │  SN65HVD3082       │ ◄──► RS-485 A/B
                                            └───────────────────┘
                                                       ▲
                                                       │
                                                     GND (Cat5e pair 4)
```

The display side has no battery / no RTC chip — it gets time from
the battery-side over RS-485 (or free-running if the link is silent).

## Where the firmware estimator runs

**Battery-side**, then ships a single `minutes_remaining` value to the
display in each frame. Reasoning:

- Battery side already has the high-frequency raw current samples to
  feed the EMA. Display side would have to re-derive everything from
  downsampled wire data.
- Single source of truth: dashboard + wall display agree.
- Display side can deep-sleep harder between frames — it just has to
  re-render when a new number arrives.
