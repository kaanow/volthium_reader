# Design: permanent DC current measurement

Draft 2026-08-07. **Not built.** A design sketch for putting real current
measurement on the DC lines, using the Pi and its existing USB hub.

## Why

Three of the longest-running unknowns are all the same complaint — *we have no
independent current meter*, so when two devices disagree there is no arbiter:

| unknown | what it needs |
|---|---|
| **#5** MPPT under-reports ~1.8x | current on the MPPT **output** |
| **#12** BMS and inverter disagree by ~33 W | current on a line both claim to see |
| fridge is *derived*, not measured | current on the **DC load branch** |
| are the two PV strings matched? (soiling) | current per **PV string** — *nothing on this system can see this today* |

That last one is the interesting one. The MPPT has **no PV-side current sensor
at all** on this model (the 0x15 I/W fields are structurally zero), so array
power is not merely uncertain, it is *unmeasurable* with what is installed.

## What the measurements actually have to do

Ranges from 11 days of logged data, bus ~26.5 V:

| line | observed | design range | why |
|---|---|---|---|
| PV string A / B | — (unmeasurable) | **0-10 A** each | ~8 A short-circuit per 3-panel string |
| MPPT output | max 24 A | **0-50 A** | 60 A unit; observed peak 634 W |
| DC load branch | ~3 A | **0-20 A** | fridge ~76 W plus headroom |
| inverter DC in | max 4.9 A | 0-200 A | *cable* sized for a 4 kW inverter |
| battery | max 31 A charge | — | already has two agreeing BMS shunts |

**The ranges must be chosen per channel, and this is not a nicety.** At a
typical 1% -of-full-scale Hall accuracy:

    50 A FS -> +/-13 W      20 A FS -> +/-5 W      10 A FS -> +/-3 W

A single 50 A part on every line would be **marginal for #12** (a 33 W offset)
and **useless for string matching** (a 10% mismatch on 4 A is ~11 W). Fitting
the range to the line is what makes the instrument answer the question.

## Shape: a USB sensor node, matching the pattern already here

    split-core Hall sensors  ->  small MCU (4x ADC)  ->  USB CDC  ->  Pi

The Pi already carries a USB hub with a CAN adapter and RS485 adapters, each
read by its own systemd service. A microcontroller that samples four analog
channels and emits JSON lines on `/dev/ttyACM*` slots into that pattern
exactly: another `volthium-*` service, another spool file, same uploader.

Three reasons to prefer this over wiring sensors straight into the Pi:

1. **Failure isolation.** If it hangs, it cannot touch CAN or RS485. RS485 is
   the *primary* telemetry path — adding devices to that bus to save a USB
   port would risk the thing that matters most for the thing that matters
   least.
2. **The analog domain stays off the Pi**, which has no ADC anyway and a noisy
   5 V rail.
3. **It can oversample.** Reading at a few kHz and reporting means/min/max per
   second captures the fridge's compressor inrush and the MPPT's switching
   ripple, which 15 s means would hide — a lesson this project has learned
   repeatedly.

## Split-core, not shunts — and the reason is install risk, not accuracy

Shunts are more accurate and do not drift. They also require **breaking the
conductor**, and at this site that is the wrong trade:

- Nobody is on site for weeks. A botched lug is a dead cabin and a dead Pi,
  and the Pi is the only thing that can tell anyone.
- Split-core clamps install around an intact cable. The worst case of a failed
  install is a channel that reads nothing — the system keeps running.

The accuracy the shunts would buy is not needed: per the table above, tightly
ranged Hall sensors already resolve every question on the list.

## Auto-zero, which is what makes cheap Hall sensors good enough here

Open-loop Hall's dominant error is **offset drift with temperature**, and this
cabin swings hard. Normally that means periodic manual re-zeroing — impossible
at an unattended site.

But we already know, independently, when each of these currents is *exactly
zero*:

- **PV strings and MPPT output**: zero whenever `pv_v < 15 V`. The array is
  dark every night, without fail.
- **DC load branch**: zero-ish whenever the fridge is off, which the existing
  Otsu split on `pack_p` already identifies.

So each channel can **re-zero itself nightly** against a condition we can
verify from data we already collect. That removes the dominant error term with
no site visit and no calibration equipment. It is the single thing that makes
this design practical here rather than merely possible.

## The payoff: the instrument set becomes self-checking

With PV strings, MPPT output, DC load measured, plus the battery from the BMS
and the inverter from the Conext, Kirchhoff gives a closure test:

    I_mppt_out + I_batt_discharge  =  I_inverter + I_dc_load  (+ losses)

Any drift, any failed sensor, any device lying — shows up as non-closure. This
project's whole difficulty has been meters disagreeing with **no way to tell
which was wrong**. A closure residual is that way.

It also directly answers the standing rule in `xanbus-unknowns.md` #12: prefer
same-meter comparisons because cross-meter arithmetic was always wrong. With a
conservation law you get to do cross-meter arithmetic *and know when it fails*.

## Staging — cheapest and highest value first

**Stage 1 (do this first): PV string A, PV string B, MPPT output.**
Small cables, low currents, cheap sensors. Delivers array power for the first
time ever, string matching for the soiling question, and settles #5. Three
channels.

**Stage 2: DC load branch.** Replaces the derived fridge with a measurement.

**Stage 3 (only if wanted): inverter DC input.** Settles #12, but it is the
expensive channel — the cable is sized for a 4 kW inverter, so it needs a
large-aperture 200 A part to measure a 5 A current.

## What must be checked on site before ordering anything

I cannot size the hardware from here, and guessing would be the whole
project's recurring mistake:

1. **Cable outside diameters** at each measurement point. Aperture is driven by
   *cable size*, not current — this is the #1 spec and nobody has measured it.
2. **Whether the combiner allows per-string access** with room to fit a clamp
   around one string's conductor.
3. **Where 5 V (or 12 V) is available** for sensor supply near each point, and
   the cable run back to the Pi.
4. **PV strings run at up to 115 V DC.** Clamping is non-contact so measurement
   is safe, but opening the combiner is not — that is an eyes-open,
   gloves-on job, and the strings should be broken at the breakers first.

## Software, once it exists

- `scripts/dc_sensors.py` reading `/dev/ttyACM*`, same spool/upload path as
  everything else.
- Nightly auto-zero as above, with the offset logged so drift is visible.
- KCL residual computed server-side and surfaced on `/history` next to the
  existing charts, alarming if it exceeds a threshold.
- Nothing on the Pi does analysis — it spools, the server aggregates. Per
  `CLAUDE.md`.

---

## BOM, 2026-08-09 — real parts, verified against datasheets

Cable gauges from the operator (all "I think", so apertures still need a tape
measure on site): battery 2/0 AWG, PV strings 4 AWG, MPPT combined input
8 AWG. Approximate ODs with insulation: 2/0 ~14-16 mm, 4 AWG PV wire ~8-10 mm,
8 AWG ~6-7 mm.

### The sensor family that actually fits

YHDC split-core Hall, open-loop, DC-capable. Verified specs:

| model | aperture | ranges | supply / output | accuracy |
|---|---|---|---|---|
| **HSTS016L** | **16 mm** | ±10, 20, 30, 50, 100, 150, 200 A | +5 V → 2.5±0.625 V, **or +3.3 V → 1.65±0.625 V** | 1%, linearity <0.1% |
| **HSTS21** | **21 mm** | ±50 … ±600 A | +5 V → 2.5±0.625 V | 1% |

Both are DC-25 kHz, zero offset ≤±15 mV at 25 °C, dielectric 2.5 kV.

### Two things the datasheets changed about the design

**1. 16 mm does not clear a 2/0 cable.** At ~14-16 mm OD there is no working
margin, so the inverter/battery channel needs the 21 mm HSTS21 — whose
smallest range is ±50 A. At 1% of full scale that is ±0.5 A ≈ ±13 W against a
32 W question. Stage 3 was already flagged as the awkward channel; this is
why, concretely. The handheld clamp settles that one-off reading instead.

**2. Operating range is -10 to +70 °C, and this site goes below that.** At
51°N in an unheated space, midwinter will take these sensors out of spec —
undefined behaviour exactly when solar data matters most for a different
reason (short days, low SOC). Options: accept a winter gap and flag it in the
data, mount inside a heated enclosure, or pay for an industrial part. Not a
blocker for a summer build, but it must not be discovered in December.

**CORRECTION — the Pico's own ADC cannot be used, and the ADS1115 is required.**
An earlier draft of this BOM had the 3.3 V sensor variant feeding the Pico's
ADC directly and treated the ADS1115 as an optional fallback. That was wrong.

**Erratum RP2040-E11** (RP2040 datasheet p. 629): the ADC has DNL spikes at
codes **512, 1536, 2560 and 3584**, exceeding **9 LSB** at code 512, from
incorrect capacitor sizing in its capacitive DAC — confirmed by Raspberry Pi,
a mismatch between simulation and shipped silicon. The transfer function is
non-monotonic there.

Why that disqualifies it here rather than merely degrading it:

- 9 LSB at 12-bit/3.3 V is 7.3 mV = **0.12 A** on a ±10 A part, 0.35 A on ±30 A.
- The spikes sit at 1/8, 3/8, 5/8, 7/8 of full scale. A bipolar sensor idles at
  mid-scale, so codes 1536 and 2560 fall at about ±6.6 A on a ±10 A part —
  **inside the normal operating range**, not out at the rails.
- It is a fixed non-linearity at specific codes, so **averaging cannot remove
  it**. Oversampling cures noise, not a non-monotonic converter.

This instrument exists to arbitrate between meters that already disagree. A
converter with known missing codes is the wrong foundation for that, and $15
buys the problem away entirely.

**Consequence, and it simplifies sourcing:** with the ADS1115 converting, the
3.3 V sensor variant no longer matters. Buy the common +5 V parts, power the
ADS1115 from the Pico's VBUS, use its ±4.096 V PGA range — 125 µV/LSB, about
**2 mA per count** on a ±10 A sensor. The Pico's ADC goes unused; it is a USB
bridge and I2C master only.

Its channel count would have been a dead end regardless: three external
channels (GP26/27/28) is exactly stage 1 with no spare, because GP29/ADC3 is
committed to VSYS sensing on the Pico board. Stage 2 would have forced an
external ADC anyway.

### Stage 1 — three channels, ~$70

| qty | part | for | supplier | ~unit |
|---|---|---|---|---|
| 2 | YHDC HSTS016L, **±10 A**, +5 V | PV string A, PV string B | PowerUC / Amazon | $15 |
| 1 | YHDC HSTS016L, **±30 A**, +5 V | MPPT output | PowerUC / Amazon | $15 |
| 1 | **Adafruit 1085** (ADS1115, 16-bit, 4-ch, I2C) | the actual converter | Digi-Key | $14.95 |
| 1 | Raspberry Pi Pico, **SC0915** | USB CDC bridge + I2C master | Digi-Key | $4.59 |
| 1 | USB A-to-micro-B cable | power + data, one run | any | $5 |
| — | small IP-rated box, glands, hookup wire | | | ~$15 |

The ADS1115's 4th channel is already there for stage 2's fridge branch.

Ranges are chosen per line deliberately. A ±10 A part on a ~8 A string gives
0.1 A resolution; a ±50 A part on the same string would give 0.5 A and could
not see a 10% mismatch. This is the whole reason not to buy one part in bulk.

### Stage 2 / 3

- **DC load branch** (fridge, ~3 A): HSTS016L ±10 A. Gauge unmeasured.
- **Inverter DC input** (2/0): HSTS21 ±50 A, 21 mm, ~$13. Coarse, per above.

### Still unmeasured, and required before ordering

1. **Cable ODs at each point** — aperture is driven by cable, not current.
2. **MPPT output cable gauge** — the one stage-1 line with no estimate.
3. **Combiner access** to a single string conductor with room for a clamp body.
4. **Distance from combiner/MPPT back to the Pi.** USB is ~5 m. Beyond that
   the topology changes (second node, or RS485 instead of USB). This is the
   only finding that would force a redesign.
5. Confirm the 4 AWG / 8 AWG assignment — a combined input thinner than the
   strings feeding it is unusual and may simply be swapped in the estimate.

**Pico specs that bear on the build.** Dual Cortex-M0+ at 133 MHz, 264 KB
SRAM, 2 MB flash, USB 1.1 device+host on micro-B, VSYS 1.8-5.5 V, 21 x 51 mm,
and **-20 to +85 °C** — wider than the sensors' -10 to +70, so the winter
limitation above is entirely a sensor problem and the bridge needs no change
if it is solved.

Sources: YHDC HSTS016L and HST(S)21 product pages and distributor datasheets;
Digi-Key SC0915 and Adafruit 1085 listings; RP2040 datasheet erratum RP2040-E11
and raspberrypi/pico-feedback issue 91. All figures above are quoted, not
estimated, except the cable ODs and the enclosure allowance.
