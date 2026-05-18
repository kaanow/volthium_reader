# Battery-side SOC-tier state machine — formal spec

Source of truth for the firmware port. Driven entirely by the smoothed
minimum-of-the-two SOC values (pack-SOC takes the more conservative
battery as the limit). Voltage-only paths exist for the deepest tiers
where we deliberately don't trust BLE / coulomb counting any more.

```
                ┌─────────────────────────────────────────────────┐
                │  (start) — boot, ULP reset, override-button hold │
                └────────────────────┬────────────────────────────┘
                                     │  read 24V via ADC; estimate SOC
                                     │  from voltage table; pick a state
                                     ▼
            ┌──────────────────┐  SOC > 25% sustained 2 min   ┌──────────┐
   ┌─────►  │     NORMAL       │ ◄────────────────────────────│   LOW    │
   │        │  SOC > 25%       │                              │ 15–25%   │
   │        │  • BLE persistent│                              └──────────┘
   │        │  • RS-485 tx 30s │ SOC ≤ 25% for 5s                  ▲
   │        │  • main core on  │ ─────────────────────────────────►│
   │        │  ~ 75 mA / 3.3V  │ • BLE persistent                  │
   │        └────────┬─────────┘ • RS-485 tx 60s                   │ SOC > 18% for 2 min
   │                 │           • banner "LOW PACK"               │
   │                 │           ~ 15 mA avg                       │
   │                 │ SOC ≤ 15% for 5s                            │
   │                 ▼                                              │
   │       ┌──────────────────┐                                    │
   │       │   DEEP_SLEEP     │ ◄──────────────────────────────────┘
   │       │  10–15%          │
   │       │  • BLE off       │ SOC > 18% for 2 consecutive
   │       │  • main core in  │ ULP wakes (i.e. 20 min sustained
   │       │    deep sleep    │ recovery — pessimistic by design)
   │       │  • ULP wakes /10m│
   │       │  ~ 50 µA avg     │
   │       └────────┬─────────┘
   │                │ V24_SENSE → SOC < 10% for one ULP wake
   │                ▼
   │       ┌──────────────────────┐
   │       │   HARD_CUT           │
   │       │  voltage < V_floor   │ V24_SENSE → SOC ≥ 15% AND
   │       │  • P-FET load switch │ stable for 2 ULP wakes
   │       │    off (kills the    │ ─────────────► back to DEEP_SLEEP
   │       │    downstream rails) │ ALSO: override-button (RTC
   │       │  • ULP voltage-only  │     wake) → straight to NORMAL
   │       │    every 60s         │     (manual force-enable)
   │       │  ~ 5 mW total        │
   │       └──────────────────────┘
```

## State table

| State        | SOC band   | BLE          | RS-485 cadence | Wake source(s)            | Avg pack draw |
|--------------|------------|--------------|----------------|---------------------------|----------------|
| NORMAL       | > 25 %     | persistent   | 30 s           | (always-on)               | ~ 1.1 W       |
| LOW          | 15 – 25 %  | persistent   | 60 s           | (always-on)               | ~ 0.31 W      |
| DEEP_SLEEP   | 10 – 15 %  | OFF          | none           | ULP timer 10 min; button  | ~ 0.13 W      |
| HARD_CUT     | < 10 %     | OFF          | none           | ULP timer 60 s; button    | ~ 5 mW         |

Numbers from `docs/hardware/power_budget.md`.

## Transition rules

Every transition uses hysteresis to prevent flapping. Down-transitions
(degraded states) are fast — be cautious. Up-transitions require
sustained recovery — be patient.

| From       | To         | Trigger                                                | Hysteresis            |
|------------|------------|--------------------------------------------------------|-----------------------|
| NORMAL     | LOW        | smoothed min_soc ≤ 25 %                                | 5 s sustained         |
| LOW        | NORMAL     | smoothed min_soc > 27 %                                | 2 min sustained       |
| LOW        | DEEP_SLEEP | smoothed min_soc ≤ 15 %                                | 5 s sustained         |
| DEEP_SLEEP | LOW        | ULP-measured 24V→SOC > 18 %                            | 2 consec. ULP wakes   |
| DEEP_SLEEP | HARD_CUT   | ULP-measured 24V→SOC < 10 %                            | 1 ULP wake (instant)  |
| HARD_CUT   | DEEP_SLEEP | ULP-measured 24V→SOC ≥ 15 %                            | 2 consec. ULP wakes   |
| any        | NORMAL     | hardware override button pressed                       | (instant, no debounce after RC) |

"Smoothed" here means an EMA-smoothed reading; same EMA the time-to-X
estimator uses. SOC = `min(bms_a.soc, bms_b.soc)` — the limiting
battery sets the tier (a series pack is only as healthy as its weakest
cell).

## SOC source per state

| State       | SOC source                                    |
|-------------|-----------------------------------------------|
| NORMAL      | BLE: BMS-reported SOC %                       |
| LOW         | BLE: BMS-reported SOC %                       |
| DEEP_SLEEP  | ULP: 24V-rail voltage divider → table lookup  |
| HARD_CUT    | ULP: 24V-rail voltage divider → table lookup  |

The voltage-to-SOC table for LiFePO4 is roughly:

| Pack 24V    | Implied SOC (rest, no load) |
|-------------|------------------------------|
| > 27.2 V    | > 80 %                       |
| 26.4 V      | ~ 50 %                       |
| 26.0 V      | ~ 25 %                       |
| 25.6 V      | ~ 15 %                       |
| 25.0 V      | ~ 10 %  ← hard cut threshold  |
| 24.0 V      | ~ 0 %    ← never reach here   |

These are *resting* voltages; under load voltage sags. The ULP routine
should wake, wait ~10 s for the pack to settle (assuming load is light
when SOC is this low), then read. If we can't get a stable reading,
default to the more pessimistic interpretation.

## Display-side reactions

The display node observes RS-485 frames. State transitions arrive in
the `state` field of each frame. UI response:

| Battery-side state | Display behavior                                          |
|--------------------|-----------------------------------------------------------|
| NORMAL             | normal headline, refresh on each frame                    |
| LOW                | "LOW PACK" banner + dim/invert background                  |
| (no frames > 90 s) | "LINK DOWN — last reading at HH:MM" overlay                |
| (no frames > 6 min — battery-side likely in DEEP_SLEEP) | "MONITOR ASLEEP — pack < 15 %" |
| (no frames > 30 min — DEEP_SLEEP or HARD_CUT)           | "MONITOR ASLEEP — pack < 10 %" (red banner) |

The display side has its own RTC and last-seen-frame timestamp. It does
NOT auto-shed at low SOC — its own draw is trivial (~50 mW) and the
person in the kitchen needs to see *something* even when the pack is
sick.

## Persistence

State (current tier + hysteresis-counter) survives reboot via NVS so
that an unplanned reset doesn't lose hysteresis state. Voltage-table
calibration is also NVS-stored so we can refine over time.

## Test plan

`firmware/bms-link/test/` should include a state-machine test harness
that feeds synthetic SOC sequences and asserts the state trajectory:

```c
TEST_CASE("clean charge from 12% to 30% triggers proper recovery",
          "[state_machine]") {
    sm_init(/*initial_soc=*/12);
    ASSERT_EQ(sm_state(), STATE_DEEP_SLEEP);
    sm_advance_5s(15); // SOC=15% for 5s
    ASSERT_EQ(sm_state(), STATE_DEEP_SLEEP); // not yet (need 2 ULP wakes)
    sm_advance_10min(18);
    sm_advance_10min(18);
    ASSERT_EQ(sm_state(), STATE_LOW);
    sm_sustained_min(28, /*duration=*/120 /*s*/);
    ASSERT_EQ(sm_state(), STATE_NORMAL);
}
```

## Cross-references

- Prose-level architecture: `docs/firmware/architecture.md`
- Power numbers: `docs/hardware/power_budget.md`
- Hardware MOSFET hard-cut path: `docs/hardware/schematic_battery_side.md`
- BMS bias context (why we don't trust SOC% blindly): `docs/hardware/bms_calibration.md`
