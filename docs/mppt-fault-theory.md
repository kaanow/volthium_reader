# Why does the MPPT do this? A theory, with its evidence and its holes

Written 2026-08-08 in answer to "is it faulty?".

**Short version, after the theory below was tested and its mechanism failed:**
the output current sensor IS faulty (~1.5-2.1x under-read, measured), and the
power stage is fine — but the sensor probably does **not** explain the tracking
failure. The leading explanation is now a controller servoing to a charge
current it can never reach. Read the REFUTED section before the theory.

## What is actually observed

1. **The array walks monotonically down** from ~90-113 V to ~28 V, passing
   straight through its own maximum power point without turning around, and
   ends pinned one diode drop above the battery.
2. **A Standby → Operating bounce fixes it every time** — 7 of 7 in daylight,
   restoring 88-95 V and full output within seconds.
3. **After a bounce it tracks correctly for 15-60 minutes**, then starts down
   again.
4. **The descent start is NOT conditional on power.** Measured across eight
   recoveries, it began at 16, 32, 84, 185, 218, 223, 312 W. It is essentially
   *time since reset*, not irradiance, not load, not SOC.
5. **The unit reports no fault.** Status byte 0x03 throughout.
6. **Its output current sensor under-reads by ~1.8x**, measured against two
   BMS shunts that agree with each other within 0.8 A.
7. **This model has no PV-side current sensor at all** — the 0x15 current and
   power fields are structurally zero.

## The theory

**The controller is chasing a current target with an instrument that reads
low, and it has no independent way to notice.**

Walking left down the IV curve *is* demanding more current. The controller does
that continuously until the array collapses, and never reverses. That is what a
regulator does when it believes it has not yet reached its setpoint — and
`chg_target` advertises **60 A**, which this array can never supply.

Point 7 is what makes it unrecoverable. With no PV-side sensor, the MPP tracker
must infer array power from the output side, `P = Vout x Iout`. Its only power
signal is the very measurement that is wrong. If the error is non-linear with
current — reading progressively lower as current rises — then moving left looks
like *power still increasing*, so the peak is never detected and there is
nothing to turn the tracker around. It walks until physics stops it.

This one fault accounts for all seven observations:

| observation | explained by |
|---|---|
| walks past MPP without reversing | no valid peak in the inferred power signal |
| always walks *down*, never up | under-read → "need more current" → move left |
| 1.8x under-report | the sensor fault, measured directly |
| bounce always works | reset re-runs a fresh sweep from Voc |
| holds 15-60 min after | the push is slew-limited; it takes that long to walk |
| start is time-based, not power-based | it is a control-loop drift, not a response to conditions |
| "no faults active" | the unit cannot detect that its own sensor lies |

## MECHANISM REFUTED 2026-08-08 (same day, by the test it predicted)

The theory required the under-read to **ease as current rises**, so that moving
left past the MPP would still look like rising power. That is testable against
data already held, using the BMS plus inverter draw as an independent estimate
of true output.

Binned by **actual output current** — the variable the mechanism depends on,
and not the same as power, since left of the MPP current rises while power
falls:

| I_out | n | actual/reported |
|---|---|---|
| 0-2 A | 111 | 1.46x |
| 2-4 A | 175 | 1.92x |
| 4-6 A | 66 | 1.94x |
| 6-9 A | 64 | **2.14x** |
| 9-13 A | 105 | 1.91x |
| 13-25 A | 65 | 1.51x |

**It does not fall with current.** A hump with essentially equal endpoints
(1.46 vs 1.51) is approximately a *scale* error — and a scale error does not
move the argmax, so hill-climbing should still find the peak. The mechanism
proposed above therefore **does not work**.

Two false starts on the way, both worth recording:

- Binning by *power* first gave a clean 2.84x → 1.46x fall, which looked like
  confirmation. Most of that was the known constant +33 W offset in `dc_w`:
  `(W+33)/W` alone produces almost exactly that curve. Correcting for it cut
  the spread from 1.31 to 0.43.
- Even the residual was measured against the wrong variable. Power and current
  are not interchangeable across the MPP, which is the whole point of the peak.

Caveats on the refutation itself: the -33 W correction is an estimate, the
fridge is unmodelled, and the mid-range hump may be an artefact of which
conditions populate each bin. But there is **no evidence** for the specific
current-dependent non-linearity the theory needed, and that was its load-bearing
assumption.

**So the sensor fault is real and better characterised (~1.5-2.1x under-read
across the range), but it probably does not explain the tracking failure.**

### What that leaves

The alternatives below move up, and one now leads: **the controller servoing to
a charge request it can never meet.** `chg_target` advertises **60 A**, the
array can supply at most ~24 A, and `chg_stage` was observed flapping
bulk ↔ not_charging **~40 times in 11 hours**. A current regulator chasing an
unreachable setpoint, with MPP limiting not overriding it, produces exactly the
observed monotonic walk toward more current — and needs no sensor fault at all.

### ...and that lead is refuted too, 2026-08-09

The `chg_stage` flapping is real — 1035 of 1054 transitions over ten days are
`bulk ↔ not_charging`, and the unit reached absorption only **4 times in ten
days**, so it essentially never completes a charge cycle. But it does not
happen when the descent happens.

08-08 transitions by local hour:

| hour | transitions |
|---|---|
| **05:00** | **40** |
| 06:00 | 5 |
| 09:00 / 13:00 / 17:00 | 2 / 2 / 2 — these are the guard's own bounces |
| **20:00** | **39** |
| 21:00 | 6 |

Median gap between transitions: **17 seconds**. It is concentrated entirely in
the dawn and dusk hours, and there are **zero transitions during the
descents** — the array walks 91 → 29 V with the controller sitting in a single
uninterrupted `bulk` state.

So the descent is a **smooth continuous control action inside one mode**, not a
state-machine artefact. That is worth knowing: it rules out mode-thrash as the
cause, and it is consistent with (though it does not prove) a regulator pushing
steadily toward a setpoint. `chg_target` does advertise **60 A** throughout
bulk, against an array good for ~24 A.

**Separately, the dawn/dusk chatter is itself a previously unnoticed
behaviour.** ~40 start/stop cycles at ~17 s intervals, twice a day, as the
array crosses the converter's start threshold — classic hysteresis chatter at a
marginal input. Probably benign if the switching is solid-state, but it is ~80
cycles a day that nobody had counted.

### Where that leaves the diagnosis

Three candidate mechanisms have now been tested against data and **all three
have failed**: low-light dependence (descent starts at every power level from
16 to 312 W), sensor non-linearity (error is scale-like in current), and
mode-thrash (no transitions during descents).

What survives is only the observation, not an explanation: within one
continuous bulk state, with an unreachable 60 A target, the controller walks
the operating point down past its own MPP and never turns around. Whether that
is a firmware defect, a deliberate-but-wrong current-priority behaviour, or
something about how it arbitrates the BMS request is **not established**, and I
have stopped guessing at it.

## What this does NOT explain, honestly

- **Why a pure 1.8x scale error would matter.** Scaling `P` by a constant does
  not move its argmax, so a clean 1.8x error should still let hill-climbing
  find the peak. The theory therefore *requires* the error to be non-linear,
  and that is inferred rather than measured. It is the weakest link.
- **The 25-50x apparent under-report during a clamp** is a different
  mechanism, not more of the same: once the converter stops switching, current
  reaches the battery through the body diode and bypasses the sensor entirely.

## Alternatives not ruled out

- **A firmware bug in the MPP algorithm.** Cannot be tested by updating — the
  unit is already at its final firmware (1.09).
- **Interaction with the BMS charge request.** The bus advertises 28.6 V / 60 A
  while the MPPT's own config says 28.0 V; if the controller is servoing to a
  request it cannot meet, the same walk follows without any sensor fault.
- **Partial shading / multi-peak IV curve.** Real for a soiled 2-string array,
  but it would produce hunting between peaks, not a monotonic walk to collapse.

## Is it faulty?

**The output current sensor: yes, demonstrably.** ~1.8x low, measured against
two independent shunts, and confirmed by the unit's own Modbus energy counters
agreeing with the wrong value (same sensor, so no arbitration).

**The power stage: no.** It delivers 600+ W and holds a correct MPP for up to
an hour after every reset. Nothing is failing to convert.

**The tracking behaviour: faulty in effect, cause NOT established.** The link
from sensor to tracker was tested the same day and did not hold — see the
REFUTED section. Something is wrong with how this unit decides where to sit on
the curve; which subsystem is at fault is still open.

**Is it degrading?** Unknown, and worth saying plainly rather than guessing:
the walk-down is present in the earliest data available (07-30 already swings
113 → 28 V). There is no baseline from before it started.

## How to settle it

One measurement decides between "bad sensor" and "bad algorithm": **an
independent clamp meter on the MPPT output**, per
`docs/design/dc-current-instrumentation.md`.

Note the BMS-derived version of this test has already been run and pointed
*away* from the sensor. A clamp meter would settle it properly, since the
derived estimate carries the +33 W offset, an unmodelled fridge, and bin
confounds. But on present evidence the more valuable next step is cheaper:
**analyse the `chg_stage` bulk ↔ not_charging flapping**, which is logged
already and needs no hardware.

Either way the operational answer is unchanged, because the guard already
handles it: bounce on detection, and consider bouncing at the 45 V cliff before
the collapse completes.
