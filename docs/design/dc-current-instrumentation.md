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
