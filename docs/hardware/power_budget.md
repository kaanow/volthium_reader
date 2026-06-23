# Power budget

The constraint: **average draw on the 24 V pack must be small compared
to the parasitic baseline of the cabin** — i.e. small relative to the
inverter's idle draw (~10–50 W). Goal is well under 1 W typical, with
the monitor self-disabling below 10 % SOC so it can't drain a sick
pack.

## Battery-side draw, per state

Conversion efficiency assumptions (per decisions.md D19):

- **U1 LM5166** (24 V → 3.3 V, *always-on*), ~14 µA Iq; 70–85 % at
  5–80 mA load. The microamp quiescent is the point — the always-on rail
  costs almost nothing at idle, which keeps the low-SOC trickle ~1 mW
  (the RV-3028-C7 RTC adds only 45 nA — D23).
- **U2 R-78HB12** (24 V → 12 V, *switched*, display feed), ~80 % over the
  relevant range. Behind the Q1 load switch, so it draws **zero** when
  the display is shed at < 10 % SOC.

### State 1 — Normal (> 25 % SOC, persistent BLE)

| Subsystem               | 3.3 V load        | 24 V draw (with conversion) | Note |
|-------------------------|-------------------|----------------------------|------|
| ESP32-S3 active (BLE)   | ~75 mA avg        | ~38 mA   ≈ 0.92 W           | BLE central holding 2 links + UART |
| RS-485 transceiver idle | ~1 mA             | ~0.5 mA                     | Driver disabled, receiver listening (idle bias is display-end only, DR-4b — no battery-side bias draw) |
| RV-3028-C7 RTC          | 45 nA             | negligible                  | (was DS3231 ~150 µA — DR-8) |
| **Battery-side subtotal**| —                | **~38 mA at 24 V ≈ 0.9 W**  | |
| Display-side via Cat5e  | (see below)       | +~5 mA at 24 V ≈ 0.12 W     |  |
| **Whole-system total (avg)** |              | **~43 mA at 24 V ≈ 1.0 W**  |  |
| WiFi log push (D25)     | ~150–250 mA for a ~2–6 s session, a few ×/hour | small added *average* | duty-cycled; logs buffered in flash between pushes (LM5166 500 mA feeds it) |

Per day: 1.1 W × 24 h = 26 Wh ≈ 1.1 Ah / day off the 24 V pack.
At 200 Ah usable per battery (400 Ah pack × ~85 % usable to 10 %),
that's ~340 days of monitoring on a fully charged pack with no other
load. Way under the budget.

### State 2 — Low SOC (15–25 %, BLE polling slows to 1/min)

| Subsystem            | Avg draw                         |
|----------------------|----------------------------------|
| ESP32-S3             | ~15 mA avg (mostly light-sleep, wakes for ~1 s once/min for BLE) |
| RS-485               | ~1 mA                            |
| RV-3028-C7 RTC       | 45 nA (negligible)               |
| Display side         | unchanged (~5 mA at 24 V)        |
| **Total**            | **~13 mA at 24 V ≈ 0.31 W**       |

### State 3 — Deep sleep (10–15 %, BLE off, ULP only)

| Subsystem            | Avg draw                         |
|----------------------|----------------------------------|
| ESP32-S3 ULP+RTC     | ~50 µA (RTC slow-clock + ULP wake every 10 min) |
| RV-3028-C7 RTC       | 45 nA (negligible)               |
| Q1/Q2 path off       | ~10 µA (pull-up leakage)         |
| Display side         | still receiving 12 V; ESP32 + e-paper light-sleep ≈ ~5 mA at 24 V conv. |
| **Total**            | **~5.4 mA at 24 V ≈ 0.13 W**      |

### State 4 — Hard cut (< 10 % SOC)

Q1 is OFF — the 12 V/display feed (U2) is shed, so the entire display
side is dark. The **ESP stays powered** on the always-on rail (U1) and
deep-sleeps, waking briefly to read the sense divider and re-engage Q1
when the pack recovers. No full power-down, no separate supervisor IC
(D19 / DR-4: a fully-unpowered MCU couldn't wake itself).

| Subsystem               | Draw (referred to 24 V pack)      |
|-------------------------|-----------------------------------|
| U1 LM5166 Iq            | ~14 µA → **~0.34 mW**            |
| ESP32-S3 deep-sleep     | ~10 µA @ 3.3 V → **~0.2 mW**       |
| 24 V sense divider (1.2 MΩ/100 k) | 24 V / 1.3 MΩ ≈ 18.5 µA → **~0.44 mW** |
| UVLO supervisor U4 + **~2.0 MΩ** divider (D28; reviewer F02) | ~2.1 µA Iq + ~10–14 µA divider → **~0.45 mW** (2.0 MΩ, not 10 MΩ: TPS3890 needs ≥10 µA divider current for threshold accuracy) |
| USB power-mux U6 TPS2116 (D29, always-on) | ~1.3 µA → **~4 µW** (the rest of the USB circuit is VBUS-referenced → 0 when unplugged) |
| RV-3028-C7 RTC (always-on) | 45 nA → **negligible** (D23/DR-8; was DS3231 ~0.5 mW) |
| Display side (U2 shed)  | 0                                 |
| **Total from pack**     | **~1.3 mW** (the F02 divider resize added ~0.35 mW; still negligible) |

**Hardware floor (D28/DR-16), an even lower state below state 4.** If the
firmware ever fails to shed (hung-but-powered MCU), U4 asserts ESP **EN**
low below ~20 V pack: the ESP drops to its ~µA reset state (killing the
~38 mA hung drain) and the display auto-sheds (PWR_EN Hi-Z). Draw in this
floor state is *lower* than state 4 — only U1 Iq + the two dividers + U4 ≈
**~1.1 mW** — and it holds until the pack recovers past **~21.5 V** (set by
the external hysteresis resistor R_hys; reviewer F01).

At ~1 mW the pack would take **~10 years** to lose 1 % SOC from this load
alone — self-discharge and the cabin's own parasitics dominate by orders
of magnitude. (A literal full cut + hardware supervisor could reach
~0.7 mW, but D19 judged the extra part not worth the marginal saving.)

## Display-side draw

The display side gets 12 V over Cat5e. Looking at it from the display
end (before tracing back to the 24 V pack):

| Subsystem               | 3.3 V load     | 12 V draw  | Note |
|-------------------------|----------------|------------|------|
| ESP32-S3 active (RX only) | ~30 mA       | ~10 mA     | Listening, refreshing e-paper occasionally |
| ESP32-S3 light-sleep    | ~2 mA          | ~0.8 mA    | Most of the time |
| RS-485 receive-only     | ~1 mA          | ~0.4 mA    |  |
| E-paper during refresh  | ~25 mA × ~2 s every 30 s | ~1.5 mA avg | Worst-case full refresh; partial refresh much less |
| E-paper static          | 0              | 0          | The whole point of e-paper |
| **Display-side average**| —              | **~3–5 mA at 12 V ≈ 50 mW** | |

At the **24 V pack** end, with 80 % conversion through U2 (R-78HB12),
that becomes ~63 mW.

## Wire loss

5 m of Cat5e at #24 AWG, 0.084 Ω/m per wire, round-trip on a single pair
is ~0.84 Ω. We use two pairs in parallel for +12 V (pair 2 + pair 3) and
one for GND (pair 4) — so:

- +12V resistance: 0.84 / 2 = 0.42 Ω
- GND resistance:  0.84 Ω
- Total loop:      1.26 Ω

At our peak transient (~50 mA during e-paper refresh): 63 mV drop. At
average (~5 mA): 6 mV drop. The R-78E3.3 needs ≥4.5 V input, so even
with a hypothetical 10 V cable arrival we're still in spec.

## Time-to-deplete (no charging) at each state

Assuming a fully charged 200 Ah pack with no other loads:

| State                              | Pack draw  | Days to 10 % cutoff |
|------------------------------------|------------|---------------------|
| Normal (state 1)                   | 1.1 W      | ~340 days           |
| Low (state 2)                      | 0.31 W     | ~1,200 days         |
| Deep sleep (state 3)               | 0.13 W     | ~2,800 days         |
| Hard cut (state 4)                 | ~1 mW      | decades (self-discharge dominates first) |

These are upper bounds — in reality the inverter idle is dozens of watts,
the cabin's fridge is ~5 A intermittent, etc. The monitor is rounding
error in the total cabin power budget.

## Sanity check: against the inverter

If the cabin is running the inverter to keep the kitchen outlet alive,
inverter idle is often 15–40 W. If we'd powered the display side from
that outlet instead of from the Cat5e DC feed, we'd spend ~20 W × 24 h =
**480 Wh/day** just to deliver 0.05 W to the e-paper. Twenty thousand
times the marginal cost of the DC-over-Cat5e approach. The DC path is the
right call.

That said: the inverter is likely on already for the fridge etc. anyway,
so the marginal cost of plugging the display end into AC is just the
wall-wart's load. Either approach works; the DC-over-Cat5e one survives
inverter-off conditions, which is the point.
