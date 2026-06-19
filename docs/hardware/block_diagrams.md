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

Power tree per decisions.md **D19** (CP1 re-architecture). Two domains:
an **always-on** rail that powers the MCU in every state, and a
**switched** rail (the display feed) the MCU sheds at low SOC.

```
        24 V tap (fused 1 A)
              │
              ▼  F1 → D1 (60 V Schottky, reverse-pol) → TVS1 (SMAJ33CA, ~53 V clamp)
        ┌─────┴─────────── V24_FUSED ─────────────────────┐
        │ (always-on)                                      │ (switched)
        ▼                                                  ▼
  ┌──────────────────┐                          Q1 P-FET load switch (60 V)
  │ U1 LM5166 buck   │── 3.3 V always-on ─┐     gate-clamped, ESP-controlled
  │ 24 → 3.3 V        │                    │            │
  │ (Iq ~14 µA)    │                    │            ▼  V24_SW
  └──────────────────┘                    │     ┌──────────────────┐
                                          │     │ U2 R-78HB12 buck │── +12 V to Cat5e
            ┌───────────────┐             │     │ 24 → 12 V (72 V)  │     → display side
            │ ESP32-S3      │◄────────────┘     └──────────────────┘
            │ WROOM-1 N16R8 │   ◄── RV-3028-C7 RTC (I²C, cap-backed)
            │ ULP+BLE+WiFi  │   ◄── 24 V ADC sense (1.2 MΩ/100 k divider, ~19 µA)
            │  GPIO bank    │   ──► WiFi log-push to Starlink server (duty-cycled, D25)
            │               │   ◄── override button (RTC-wake GPIO)
            └──┬────────────┘   ──► drives Q1: sheds the 12 V/display feed
               │                       when SOC < 10 % (ESP stays alive,
               ▼                       deep-sleeps, re-engages on recovery)
      ┌──────────────────┐
      │  SN65HVD3082      │ ◄────► RS-485 A/B  (Cat5e pair 1); ESP gates it
      │  RS-485 xceiver  │          off via DE/RE when idle (no power switch)
      └──────────────────┘
                    ▲
                    │
                  GND (Cat5e pair 4) — shield bonded to chassis HERE only
```

Two power domains worth keeping clear in your head:

1. **Always-on** (U1 LM5166, ~14 µA Iq): ESP32-S3 + RV-3028-C7 RTC + the 24 V
   sense divider. The MCU is *never* unpowered — at low SOC it deep-sleeps
   (~µA) and periodically reads the sense divider. All-in trickle at
   hard-cut ≈ ~1 mW (U1 Iq + divider). The MCU is its own supervisor;
   there is no separate voltage-supervisor IC.
2. **Switched** (Q1 load switch, MCU-controlled): U2 → 12 V → Cat5e → the
   *entire display side*. Opening Q1 at < 10 % SOC cuts the display
   completely (it has no other power source). RS-485 isn't power-switched —
   the ESP disables the transceiver via DE/RE (µA) when there's nothing to
   talk to.

Why the MCU is always-on and not behind the load switch: a downstream MCU
can't gate its own supply (it would lose power the instant it tried, then
default back on — and at power-up it could never start). The load switch
must sit *above* only the sheddable loads. This was the core CP1 defect
that D19 fixes (see DESIGN_REVIEW_ITEMS.md DR-4).

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
