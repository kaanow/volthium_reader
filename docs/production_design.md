# Production system design — Volthium pack monitor for The Barge Inn

> Status: **draft v1** — top-level architecture/vision. Detailed hardware
> design in [`hardware/`](hardware/README.md), firmware in [`firmware/architecture.md`](firmware/architecture.md).
>
> ⚠ **Parts, RTC, enclosure, and dev-port specifics below are pre-CP1 and
> superseded (decisions.md D18–D27).** This doc captures the system vision
> and rationale, but its component-level details are stale: the RTC
> (DS3231 → RV-3028-C7 + backup cap, D23), the enclosures (COTS Hammond/
> single-gang → custom 3D-printed IP5x boxes; display in a recessed
> double-gang, D20/D27), the dev port (USB-OTG → native USB-C, D22/D27),
> and the power tree (D19). For the **authoritative BOM and parts**, see
> [`hardware/layout/decisions.md`](../hardware/layout/decisions.md),
> [`hardware/layout/cp1_battery_side.md`](../hardware/layout/cp1_battery_side.md),
> [`hardware/layout/cp1_display_side.md`](../hardware/layout/cp1_display_side.md),
> and [`hardware/bom.md`](hardware/bom.md).

## Goal

Wall-mounted display in the kitchen showing the 24V pack's SOC, power, and a
smoothed time-to-full / time-to-empty estimate, updated often enough to feel
live. Must be reliable, must be safe for the batteries (parasitic draw
measured in single-digit watts at most), and must not break the user's ability
to occasionally open the Volthium phone app.

## Physical layout

```
   BATTERIES (24 V, near floor)            KITCHEN WALL (5 m away)

   ┌────────────────────────┐     Cat5e   ┌────────────────────────┐
   │ Battery-side node      │═════════════│ Display-side node      │
   │  • ESP32-S3            │  RS-485     │  • ESP32-S3            │
   │  • BLE central → BMS×2 │  + DC pwr   │  • E-paper display     │
   │  • 24V→3.3V buck       │             │  • Pushbutton(s)       │
   └─────────┬──────────────┘             └──────────┬─────────────┘
             │                                       │
       24 V pack tap                          (no other power needed)
```

The kitchen end has an AC outlet but we deliberately **don't** use it. The AC
outlet is on the inverter, which is on these very batteries — keeping the
inverter alive for a 1 W load wastes 10–50 W in inverter idle. Instead we tap
the 24 V pack directly at the battery-side node and feed the kitchen end over
the unused Cat5e pairs. The AC outlet is a fallback option, not the plan.

## Wiring plan (Cat5e, 5 m, shielded)

Cat5e has 4 twisted pairs. We use:

| Pair | T568B colors      | Use                                 |
|------|-------------------|-------------------------------------|
| 1    | Blue / White-Blue | RS-485 A/B (differential data)      |
| 2    | Orange / White-Org| DC+ (regulated 12 V from battery)   |
| 3    | Green / White-Grn | DC+ (paralleled with pair 2 — less drop, redundancy) |
| 4    | Brown / White-Brn | DC return (GND)                     |

Shield bonded to chassis GND **at one end only** (battery side) to avoid
ground loops.

5 m of #24 AWG copper per pair is ~0.45 Ω round-trip. At our expected ~50 mA
load that's ~22 mV drop — negligible. Paralleling two pairs for DC+ halves
that. Big margin for transient bursts (e-paper refresh, BLE scan).

## Power architecture

- **Battery-side input**: tap the 24 V pack via a small inline fuse (1 A)
  and a TI TPS62933 (or LM5163) buck → 12 V rail @ ~50 mA average. These
  parts have quiescent currents in the tens of µA range.
- **Battery-side local rail**: second tiny buck 12 V → 3.3 V for the
  ESP32-S3.
- **Display-side**: feed the 12 V rail from Cat5e into a 12 V → 3.3 V buck.
- **Total parasitic load on the pack** target: < 1 W average, < 200 mW idle
  (when ESP32s are in light sleep between BLE polls).

Why 12 V on the wire (not 3.3 V or 24 V):
- 3.3 V loses too much in the wire and exposes the rail to noise.
- 24 V directly is fine technically but means both ends carry an 8-fold
  step-down which is less efficient at light load than a single 24→12 step
  at the battery side plus 12→3.3 locally.

## Battery-side node — BLE polling strategy

The Volthium BMS only accepts one BLE central. If we hold a persistent
connection, the user can never open the phone app again. **Polite polling:**

- Wake every 30 s (configurable).
- Connect to battery A, read one sample, disconnect. (~1–2 s end-to-end.)
- Same for battery B.
- Send fused PackReading over RS-485.
- Sleep ESP32-S3 in light-sleep mode until next cycle.

Window between cycles is wide enough that the user can grab the connection
from their phone — if they do, our connect will fail and we just log the
miss and wait for the next slot.

Expected average draw on battery-side ESP32-S3:
- BLE active: ~80 mA @ 3.3 V for ~3 s out of every 30 s ≈ 8 mA average
- Light sleep idle: ~2 mA
- Total average: ~10 mA × 3.3 V = **~33 mW**

## RS-485 link — protocol

Half-duplex RS-485 (one pair). Transceiver: MAX3485 (3.3V) or SN65HVD3082.
Termination: 120 Ω at each end. Bias resistors on the kitchen end.

Frame format (battery-side → display-side, broadcast, no addressing — only
one talker):

```
0xAA 0x55  | LEN(1) | SEQ(1) | TS_MS(4) |
state(1)   | pack_v(2, 0.01V) | pack_i(2, signed, 0.01A) | pack_p(2, signed, W) |
soc_a(1)   | soc_b(1) | v_a(2) | v_b(2) | i_a(2) | i_b(2) |
t_a(1, signed) | t_b(1, signed) | rem_ah_a(2, 0.1Ah) | rem_ah_b(2, 0.1Ah) |
mins_remaining(2, 0=unknown) |
CRC16(2)
```

~38 bytes. 9600 baud is plenty (~40 ms/frame). Display sends back a tiny
"alive" beacon every minute on the same pair (TDM, scheduled so it never
collides).

## Display-side node

- **MCU**: ESP32-S3 (same as battery side — common firmware base, OTA
  symmetry, common spares).
- **Display**: 4.2" tri-color e-paper (Waveshare or Good Display, GDEY042Z98
  or similar). ~7 s full refresh. Partial-refresh for the time-remaining
  number every 30 s. Static between refreshes — zero power.
- **Inputs**: one tactile button for "refresh now" (forces a full redraw),
  one for "switch info screen" (bring up cell-balance / temperatures /
  cycle counts / history graph).
- **Optional**: a small LED bar (low-current, off by default) that flashes
  briefly when discharge crosses a configurable threshold.

### Display screen design (4.2", ~400×300)

```
┌──────────────────────────────────────────────┐
│  THE BARGE INN  •  pack  26.4 V  +12.0 W     │  ← header strip
├──────────────────────────────────────────────┤
│                                              │
│         ████████████░░░  67 %                │  ← SOC bar (big, glanceable)
│                                              │
│         TIME TO FULL                         │
│         5h 20m                               │  ← the headline number
│                                              │
├──────────────────────────────────────────────┤
│  33: 67% 13.22V 23°C   ▲▼ 8mV  ─── (sparkline)│
│  67: 66% 13.22V 23°C   ▲▼ 8mV  ─── (sparkline)│
└──────────────────────────────────────────────┘
```

Headline number is enormous (~80 pt) so it's readable from across the
kitchen. Everything else is supporting context.

Per-battery labels (`33`, `67`) are the last two digits of the BMS-advertised
serial — derived at runtime, so a battery swap auto-relabels with no firmware
flash needed.

When the higher-SOC battery reaches **95 %**, the headline replaces the time
remaining with **FULL** in big letters and the percentage stays visible
underneath. 95 % is the LiFePO4 absorption-onset point — the last 5 % is
constant-voltage taper that's hard to predict linearly and isn't useful to
non-technical viewers ("almost full" forever).

## Low-SOC self-shutdown (tiered)

The monitor must not be the thing that finishes off a deeply discharged pack.
Tiered behavior so we degrade gracefully rather than blink off without warning:

| Pack SOC    | Behavior                                                       |
|-------------|----------------------------------------------------------------|
| > 25 %      | Normal — persistent BLE connection, ~10 s display refresh      |
| 15 – 25 %   | Polling slows to 1 min; display shows "LOW PACK" banner        |
| 10 – 15 %   | BLE disconnected; main MCU deep-sleeps; ULP wakes every 10 min to re-check |
| < 10 %      | Hard cut: P-MOSFET load switch off; ULP voltage-senses ~1×/min (~20 µA) and re-engages on recovery |

Recovery is automatic via the voltage-knee on the way back up. A small
hardware override button on the battery-side enclosure forces enable
regardless of SOC — for the case where you *want* to read the pack manually
right after a deep discharge.

The display-side node **does not** auto-shed at the same threshold. It
keeps showing the last-known reading plus a "MONITOR ASLEEP — pack < 10 %"
hint so a person in the kitchen sees *something* rather than a black panel.
The display side's draw is ~0 mW e-paper static + ~7 mW ESP32-S3 light-sleep
average — trivial compared to the inverter's idle baseline that's keeping
the kitchen AC outlet alive.

### Hysteresis to avoid flapping

Each tier transition needs hysteresis so a brief load doesn't bounce the
monitor through three states. Suggested:

- Down-transitions: instant (be cautious)
- Up-transitions: require 2 minutes of sustained SOC above the higher
  threshold before promoting back up

## BLE-share button

Pressing the display-side's "release BLE" button broadcasts an RS-485
command to the battery-side node, which:

1. Disconnects from both batteries cleanly.
2. Stays disconnected for **5 minutes** so the user can open the Volthium
   phone app (the BMS only accepts one BLE central at a time).
3. Auto-re-engages after 5 min — or sooner if the user presses the button
   again ("done with app").

The display shows a 5-minute countdown so the user knows when the monitor
will resume. The "ASLEEP" e-paper screen in the meantime says "phone-app
window open" rather than implying a fault.

This obviates the need for "polite polling" — we hold persistent BLE
connections for low-latency updates, and the user has an explicit, visible
way to step aside when they want the app.

## Optional Starlink sync (the cabin has it; production must not depend on it)

When Starlink is reachable, the display-side node (which has Wi-Fi
hardware anyway) optionally:

- Posts the latest sample + alerts to a small HTTP endpoint (somewhere
  we control, or just an InfluxDB / Grafana Cloud free tier).
- Pulls NTP time once a day to keep the on-board RTC accurate.
- Listens for a "you have a software update" ping → fetches OTA image.

**All optional.** The battery-side node has its own DS3231 RTC chip
($1) so timekeeping doesn't depend on the link or Wi-Fi. The display-side
falls back to free-running RTC if Starlink is offline. Local features
(time-remaining, display, alerts) work identically with or without
internet.

## Failure-mode handling

| Failure                          | Detection                       | Behavior                              |
|----------------------------------|---------------------------------|----------------------------------------|
| BLE disconnect mid-read          | bleak exception                 | Log, retry next cycle                  |
| One battery unreachable          | timeout on read                 | Show pack value from the other half + flag |
| Both batteries unreachable       | > 3 consecutive cycles fail     | Display "BMS OFFLINE", keep retrying   |
| RS-485 silent                    | display didn't see frame in 90s | Display "LINK DOWN", show last value   |
| Battery-side node power loss     | RS-485 silent                   | same as above                          |
| ESP32-S3 firmware crash          | watchdog                        | reset                                  |
| User opened phone app            | connect fails with "in use"     | Skip cycle silently, don't alarm       |

## BOM (prototype)

Prices and SKUs are May 2026 ballpark, North-American sourcing. Substitutes
fine; specific part numbers given for click-to-cart convenience.

### Battery-side node

| Item                                       | Qty | Source            | ~Price |
|--------------------------------------------|-----|-------------------|--------|
| ESP32-S3-DevKitC-1-N8R2 dev board          |  1  | DigiKey/Mouser    | $15    |
| SN65HVD3082EDR — RS-485 transceiver, 3.3 V |  1  | DigiKey 296-21908 | $1.20  |
| Pololu D24V5F3 12→3.3 V 500 mA buck        |  1  | Pololu #2842      | $7     |
| Pololu D24V6F12 24→12 V 600 mA buck (or a TPS62933 with feedback for 12V) | 1 | Pololu #2851 | $7 |
| 1 A fast-blow fuse + ATO holder            |  1  | DigiKey           | $3     |
| DS3231 RTC module (battery-backed)         |  1  | Adafruit/Amazon   | $5     |
| P-MOSFET load switch (e.g. AOI4127E)       |  1  | DigiKey           | $1.50  |
| Hardware override button (panel-mount)     |  1  | DigiKey           | $2     |
| 120 Ω 1/4 W resistor (RS-485 term)         |  1  | any               | $0.10  |
| RJ45 keystone jack + 8P8C breakout         |  1  | DigiKey/Amazon    | $4     |
| Ring terminals for the 24 V pack tap       |  2  | hardware store    | $2     |
| Project box, IP65, ~80×60×40 mm            |  1  | Hammond/Amazon    | $8     |
| Hookup wire, headers, 100 µF cap, etc.     |     |                   | $5     |

### Display-side node

| Item                                       | Qty | Source            | ~Price |
|--------------------------------------------|-----|-------------------|--------|
| ESP32-S3-DevKitC-1-N8R2 dev board          |  1  | DigiKey/Mouser    | $15    |
| SN65HVD3082EDR — RS-485 transceiver, 3.3 V |  1  | DigiKey 296-21908 | $1.20  |
| Pololu D24V5F3 12→3.3 V 500 mA buck        |  1  | Pololu #2842      | $7     |
| Waveshare 4.2" tri-color e-paper (B) v2 + driver HAT | 1 | Waveshare/Adafruit | $40 |
| 120 Ω 1/4 W resistor (RS-485 term)         |  1  | any               | $0.10  |
| RJ45 keystone jack + 8P8C breakout         |  1  | DigiKey/Amazon    | $4     |
| Tactile button switches 6×6 mm + caps      |  3  | DigiKey           | $1.50  |
|                                            |     |   (3rd is "release BLE")    |        |
| Single-gang low-voltage mounting bracket   |  1  | hardware store    | $4     |
| Single-gang wall plate, blank to cut       |  1  | hardware store    | $3     |
| Standoffs, hookup wire, caps               |     |                   | $5     |

### Wire run

Already in walls — shielded Cat5e between battery area and kitchen mount.
Add two RJ45 keystone jacks (one per end) and short Cat5e patch cables to the
boards. If the existing run wasn't terminated yet: keystone jacks (~$2 each)
and a punchdown tool ($25 or borrow).

**Estimated total prototype cost: ~$170** including shipping. Round to $220
to allow for a second e-paper to test substitutes.

### Why these choices

- **ESP32-S3 (not ESP32 classic)**: USB-OTG for clean dev workflow, much
  lower deep-sleep current, BLE 5 with multiple concurrent connections.
- **SN65HVD3082**: 3.3 V native, full-duplex tolerant, ESD-protected.
  Cheaper alternative is MAX3485; both work.
- **Pololu D24V series**: tiny, ~80% efficiency at light load, integrated
  regulator with EN pin we can pull low to deep-sleep the rail. Quiescent
  current ~20 µA.
- **4.2" tri-color e-paper**: black + red + white gives us color-coded
  states (red for low-SOC alarm, etc.) without an always-on backlight.
  ~7 s full refresh, 1-2 s partial, ~0 W static. Tradeoffs vs LCD discussed
  in the *Open questions* section.

## Firmware architecture

Two ESP32-S3 firmware binaries sharing a small `volthium_lib` core:

- `volthium-bms-link/`  — battery-side. Owns BLE, reads BMS, fuses into a
  PackReading, sends RS-485 frames. Stays in light sleep otherwise.
- `volthium-display/`   — display-side. Receives RS-485 frames, runs the
  estimator (or trusts the battery-side number — TBD), drives e-paper,
  handles buttons.
- `volthium_lib/`       — shared: BMS protocol decoder (port the Python
  ej_bms logic), Estimator (port from `volthium/estimator.py`), RS-485
  frame codec, persistent storage of estimator state in NVS.

Build with ESP-IDF (not Arduino — we want fine power control and proper
light-sleep handling) or with Rust + `esp-hal` if that ecosystem is mature
enough by the time we build (5/2026 — likely yes).

Where the estimator runs: **battery-side**, sent over the wire as a number.
That way the display is dumb, and the battery-side has access to the raw
high-frequency current readings for accurate smoothing.

## OTA updates

ESP32-S3 has dual app partitions. Battery-side node has no Wi-Fi connection
(off-grid). Two options:

1. **USB-C port behind the project-box lid** for occasional manual updates.
   Simplest. Update is "go out to the cabin once a year."
2. **Use the display-side ESP32 as a temporary Wi-Fi AP** for over-the-air
   pushes, since the display-side could plausibly enable Wi-Fi briefly
   when the user holds both buttons. Update propagates over RS-485 to the
   battery side.

Option 1 first, option 2 as a stretch.

## Open questions / things to validate

- [ ] Does the BMS expose a "design capacity" field reliably across our two
      units? Currently we hardcode 200 Ah; should grab the value from each
      battery if available so we don't drift after a re-cell.
- [ ] What's the actual deep-sleep current of an ESP32-S3 with the
      transceiver attached? Spec says ~10 µA but transceiver standby varies.
- [ ] Can the e-paper handle a 30 s partial-refresh cadence for the time
      number without ghosting / requiring full refresh every cycle? Some
      panels need a periodic full-refresh "cleanup" — that's fine, schedule
      one full refresh every 10 min.
- [ ] BLE polite-poll cycle time — once we have logged data we'll know how
      fast we can plausibly read both batteries on this hardware.
- [ ] Whether a single ESP32-S3 near the batteries can hold both BLE
      connections concurrently (it has multiple BLE links available). If
      yes, polite-polling becomes faster.

## Next steps after this draft

1. (auto, in progress) Collect ~24 h of CSV data on the Mac → tune the
   estimator and decide whether to surface "time-to-full" vs
   "time-to-bulk-end" (LiFePO4 charging tapers hard above ~95%).
2. Order one of each BOM item, breadboard the battery-side node, prove the
   BLE polite-poll cycle works on hardware.
3. Wire up the RS-485 link, breadboard the display-side node with a placeholder
   serial console (skip e-paper for v1).
4. Add the e-paper, build the final wall plate, install.
