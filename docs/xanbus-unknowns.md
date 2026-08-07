# Xanbus — what we still don't understand

Ranked by (value if solved) × (likelihood of solving). Companion to
`docs/xanbus-decode.md` (read side), `docs/xanbus-write.md` (write side) and
the `xanbus` skill.

## Tier 1 — worth testing soon

**1. It is a SLIDE, not a trigger — observed live 2026-08-06 morning.**

Caught the run-up in progress. Array voltage walks steadily DOWN as the MPPT
extracts more current, with no discrete event anywhere:

| local | pv_v | delta | solar W | house W |
|---|---|---|---|---|
| 07:16 | 63.0 | 36.6 | 24 | 90 |
| 07:42 | 51.5 | 25.0 | 33 | 108 |
| 08:15 | 52.2 | 25.6 | 43 | 130 |
| 08:41 | 44.6 | 18.1 | 41 | 131 |

No load step, no cloud edge, no charge-stage change, no SOC threshold — just a
monotonic walk down the IV curve as demand rises. **The precondition is the
interesting part: the battery was DISCHARGING (−50 W) in full daylight all
morning**, meaning demand exceeded supply continuously, so the MPPT was
pulling maximum current the entire time. That is what walks the operating
point down until it hits the diode clamp and cannot climb back.

**The array faces SOUTH-EAST and is shaded/oblique until early afternoon**
(user, 2026-08-06; confirmed in the data — peak power lands at 13:00-15:00
every single day: 799 W@13, 1001 W@15, 160 W@14, 148 W@13, 712 W@13).
Mornings run 30-130 W regardless of how good the day becomes.

That makes the morning latch **STRUCTURAL, not a fault**. House load is
~90-130 W; morning production is ~25-55 W. Demand exceeds supply every
morning by geometry alone, so the MPPT pulls maximum current, walks down the
IV curve and clamps — on any day, smoke or no smoke. It then stays clamped
until afternoon direct sun supplies enough current to climb back out, or
until demand falls.

This also explains the 2026-08-01..05 "five day latch": those were days when
afternoon sun never got strong enough (smoke) to break out of a clamp that
forms every morning anyway.

So the latch needs no trigger. It needs only *sustained demand above what the
array can supply at that moment*. Which implies a preventative fix exists that
the mode-bounce does not provide: **limit charge current so the operating
point never reaches the clamp.** Worth considering once the write path is
trusted (`CHG_CFG_I_LIMIT` / max charge rate, currently 100%).

### Refinement 2026-08-06 afternoon: it is a RUNAWAY, and it overshoots the MPP

A full day of 5 min buckets shows the walk does not stop at the maximum power
point — it goes straight through it and keeps going:

| local | pv_v | solar W | note |
|---|---|---|---|
| 05:40 | 82.5 | 0.8 | first light, near Voc |
| 06:55 | 55.9 | 22.3 | |
| 08:10 | **52.4** | **44.5** | **peak power — this is the MPP** |
| 08:55 | 42.1 | 35.1 | past the knee, losing power |
| 09:55 | 34.7 | 23.5 | |
| 10:10 | 30.1 | 11.4 | |
| 10:25 | 28.3 | 6.2 | clamped, and stayed clamped |

House load was a flat ~113 W throughout. The tracker sat at 52 V making
44.5 W, then walked *down* the wrong side of the curve for two hours and
never turned around.

**Geometry rules out irradiance as the cause.** For the site (51.119 N,
-121.210 W) on 6 Aug, plane-of-array beam irradiance on a south-east array
*rose* between 08:10 and 10:25 by **+64% to +79%** — and that holds for every
plausible tilt (30/40/50 deg), so it does not depend on knowing the mounting
angle. Available power went up ~1.7x while delivered power went down 7.2x:
the MPPT ended up roughly **12x off** what it had already demonstrated it
could get.

That reframes the mechanism. Past the knee the feedback is **regenerative**,
not restoring: moving left reduces power, which deepens the deficit, which
makes the controller pull harder, which moves it further left. So —

- the morning **geometry** supplies the initiating condition (demand > supply);
- past the knee it becomes a **runaway**, which is why it never recovers on
  its own and why it survives into the afternoon.

Two consequences:

1. **Current-limiting is now the indicated fix, not merely an idea.** It
   attacks initiation; the mode-bounce only treats the end state.
2. **A bounce will only hold if post-sweep power exceeds load.** At 10:55 a
   re-sweep should find roughly 75 W against a ~113 W load — still a deficit,
   so it should re-latch. That is a concrete prediction for Unknown #2 below.

**That prediction was wrong, and the way it was wrong matters.** The re-sweep
at 10:58 found **227 W**, not 75 W — three times the estimate — and the fix
held. The error was assuming the 44.5 W seen at 08:10 was the array at its
MPP. It was not: the tracker was *already* descending by then, so 44.5 W was
just the high-water mark of an already-degrading trajectory, not the array's
capability. Post-fix the array settled at **88 V**, matching the ~89.8 V MPP
measured during the 2026-08-05 standby test.

Which means the runaway had been under way since **first light** — pv_v
declined monotonically from 82.5 V at 05:40 and never had a healthy tracking
period all morning. The morning was not "structurally weak"; it was
**structurally latched**. Corrected accordingly below.

### Diagnostic: cloud vs runaway

They separate cleanly, because a cloud and a tracker walk-down move different
axes:

- **Cloud/smoke** cuts irradiance, which cuts *current*. Panel Vmp barely
  moves with irradiance, so power drops at roughly **constant voltage**.
- **Runaway** is the operating point sliding left, so power and **voltage
  fall together**.

Worked example, 2026-08-06 11:10 to 12:40: pv_v 85.4 -> 48.2 (-44%) and power
235.8 -> 127.2 W (-46%). Voltage and power fell in lockstep, so this is the
runaway restarting, not weather — even though it happened while irradiance
was still climbing toward the 13:00-15:00 peak.

Use this before blaming smoke for any future production shortfall.

### The descent is a SAWTOOTH — it aborts unless it reaches the clamp

Watching the whole afternoon of 08-06 corrects the "monotonic runaway"
reading from earlier the same day. The tracker descends and then **re-acquires
on its own**, repeatedly, on a roughly 30-60 min cycle:

| local | pv_v | W | |
|---|---|---|---|
| 11:10 | 85.4 | 236 | post-bounce peak |
| 12:40 | 47.7 | 124 | descended |
| 13:00 | 61.4 | 213 | **recovered unaided** |
| 14:00 | 46.6 | 143 | descended again |
| 14:05 | 52.1 | 181 | **recovered unaided** |

So a descent is not committed. The MPPT re-sweeps periodically and climbs
back — *provided it has not yet reached the diode clamp*. The clamp is the
point of no return, because there the converter stops switching entirely and
no sweep can occur. That is the real threshold, and it is why the guard's job
is specifically to break the clamp rather than to chase every dip.

The condition that turns a dip into a latch is a *sustained* deficit. On a
day like 08-06 (surplus only ~+50 W against a ~115 W load) the array flirts
with the deficit condition all afternoon, hence the sawtooth; in the morning,
when supply was genuinely below load for hours, one of those descents ran all
the way to the clamp and stuck.

Note the earlier 12:40 entry in this file predicted the descent then under way
was "the runaway restarting". It was a genuine descent by the voltage-and-
power test — but it aborted at 12:55 without intervention, which the
prediction did not allow for. Recorded rather than removed, because the
correction is the finding.

### The deficit crossover is the trigger — caught cleanly at 15:15 on 08-06

The sawtooth model above predicts that descents abort while surplus is
positive and become terminal once it is not. The afternoon of 08-06 shows the
transition happening at a single identifiable moment:

| local | pv_v | solar W | load W | surplus | |
|---|---|---|---|---|---|
| 14:00 | 46.6 | 143 | 121 | +22 | dips, recovers |
| 14:05 | 52.1 | 181 | 113 | +69 | **recovered** |
| 14:45 | 48.1 | 146 | 112 | +34 | dips |
| 14:50 | 51.1 | 168 | 109 | +59 | **recovered** |
| 15:15 | 46.9 | 112 | 113 | **-1** | **crossover** |
| 15:30 | 44.7 | 65 | 112 | -47 | no recovery |
| 16:00 | 34.9 | 22 | 116 | -94 | no recovery |
| 16:35 | 29.6 | 5.3 | 114 | -109 | **clamped** |

Before 15:15 every dip recovered, three times in an hour. From the moment
surplus went negative there was **not one recovery** — a monotonic 80 minute
walk into the clamp. That is the predicted behaviour, on data collected after
the prediction was written.

It is not merely sunset: computed POA falls ~36% between 15:00 and 16:00 while
measured power fell 85%, and voltage fell with it. The evening irradiance
decline supplies the *crossover*; the runaway supplies the *collapse*.

**Proposed consequence — the guard should not fix a latch it cannot hold.**
At 17:00 local the sun is 33 deg up but an SE array is nearly edge-on to it;
scaling the healthy 11:00 measurement (228 W at POA 867) gives roughly **32 W
available against a ~113 W load**. A bounce then cannot be sustained by
definition. Prediction, recorded before the guard's 17:00 run: it will ACK,
the array will fly up briefly, and it will **re-latch within ~10-30 min**.
That is the Unknown #2 deficit case, arriving on its own without anyone
forcing it.

#### RESULT — prediction wrong, and the proposal above is RETRACTED

The guard fixed it at 17:00:22 (`recovered=true`, pv_v 27.5 -> 94.3). Then:

| local | pv_v | solar W | load W | surplus |
|---|---|---|---|---|
| 17:03 | 94.3 | 98 | 111 | -13 |
| 17:10 | 90.4 | 94 | 113 | -19 |
| 17:20 | 85.1 | 79 | 115 | -36 |
| 17:35 | 73.3 | 77 | 115 | -38 |

**It did not re-latch.** 35 minutes on, in a continuous 13-40 W deficit, the
array is still tracking with a healthy 47 V delta. Two things were wrong:

1. *The power estimate.* Predicted 32 W, actual 98 W — 3x low. The POA model
   used is **beam-only**, and it collapses to zero once an SE array goes
   off-axis in the afternoon. Diffuse irradiance dominates by then. Use the
   beam model for *ratios near solar noon* only; it is useless late in the day.
2. *The timing.* A deficit does not latch promptly — it latches after a long
   walk. This morning took **80 min** from the 15:15 crossover to the clamp;
   this descent is running at ~0.65 V/min and would need ~60 min more. "Deficit
   -> latch" is right; "deficit -> latch within 10-30 min" is not.

**So the "don't fix what you cannot hold" gate would have been a mistake.**
It would have skipped this fix, which recovered ~80 W for 35+ minutes and
counting — roughly **47 Wh** against the ~5 W the clamp was yielding — without
ever needing to hold surplus. A bounce does not have to be permanent to be
worth doing. Do not add that gate.

What remains true is the narrower version: near *darkness* a bounce is
pointless because there is no power to recover. That is a sun-elevation test,
not a surplus test, and the existing `daylight` check already approximates it.

`mppt_latch_context` still ships 20 min of 1 Hz run-up with each latch event
for the finer detail.

**2. Does the latch recur after our fix, and how fast?**
If it re-latches within minutes, the guard's cooldown and daily cap turn into
the real control loop and we need a smarter strategy (e.g. deliberately
limiting charge current so demand never exceeds supply). The guard records
`recovered` on every attempt, so the data will answer this.

> Still unanswered on 2026-08-06, because the guard's first meeting with a
> real latch found a bug instead. **The detection ceiling was tighter than the
> MPPT's own reporting dither.** With `out_v` steady at 26.50 V, reported
> `pv_v` hops over a ~1.1 V range (27.5-29.9), so the delta swings 0.90-3.44 V
> second to second. Against a 2.5 V ceiling, 47% of 15 s buckets held at least
> one out-of-band sample. The detector therefore raised `mppt_latched` at
> 17:28:03Z and retracted it 25 s later on a 2.96 V delta while the array
> stayed clamped for hours; and the guard's clamp fraction never reached 0.9,
> so it declined to act on every 20 min run — *silently*, because a
> below-threshold fraction returned without emitting anything. Five hours of
> latch, no trace. Fixed in f42e88e: both ceilings to 4.0 V (observed dither
> plus margin, still far below the 8.2 V smallest healthy delta), 120 s
> hysteresis on release, and a `latch_guard_ambiguous` event so a
> below-threshold bail can never be invisible again. After the fix the same
> live clamp sampled at **fraction 1.0 (179/179)**.
>
> Lesson worth generalising: a threshold on a reported value has to clear that
> sensor's own quantisation, and a guard that declines to act must say so.

**ANSWERED (first half), 2026-08-06 10:58 local — the guard cleared a real
latch, unattended, end to end.** Sequence from its own journal:

```
10:58:09  claimed 0x80, answered discovery (0x1F00F/1F810/1F014/1F80E) from node 2
10:58:11  sent PGN 0x14000 -> node 1: 02 (Standby)    <- node 1: ACK
10:58:26  sent PGN 0x14000 -> node 1: 03 (Operating)  <- node 1: ACK
10:59:34  latch_fix_result: acked=true recovered=true
          before: fraction 1.00  pv_v 29.6
          after : fraction 0.00  pv_v 93.0 (max 98.3)
```

Production went **5.3 W -> 235.8 W**, a 44x step, and the battery flipped from
-110 W (discharging in full daylight) to +119 W charging. The clamp had been
costing ~110 W continuously.

**It did not re-latch**: five subsequent guard runs (11:17 / 11:37 / 11:57 /
12:17 / 12:38) were all silent. So a bounce is durable when the array can
out-supply the load, and the 45 min cooldown / 4-per-day cap are not acting as
the control loop — at least on a day like this one.

Still open: the recurrence question in the *deficit* case, i.e. what happens
when a bounce lands while production is still below load. The 12:40 descent
(see the cloud-vs-runaway diagnostic above) should produce that test today.

### The `daylight` test is wrong, and sun elevation is the fix

`DAYLIGHT_V = 20.0` is commented "a dark string still floats a few volts".
**That assumption is false.** Measured after sunset on 08-06 (sun already below
the horizon):

| local | pv_v | solar W |
|---|---|---|
| 20:15 | 70.4 | 0.9 |
| 20:25 | 78.3 | 1.2 |
| 20:35 | 71.5 | 0.9 |
| 20:40 | 29.4 | 2.6 |

A dark string floats most of **Voc**, not a few volts, so `pv_v > 20` stays
true for 30-45 min after sunset. Worse, the decay is not monotonic — the array
thrashes (29 -> 78 -> 54 -> 71 V) as the MPPT hunts and gives up for the night,
so it repeatedly dips through the clamp band. At 20:41 on 08-06 the guard duly
logged `latch_guard_pending` with `fraction 1.0` and `daylight: true` **with
the sun at -0.55 deg**.

Today the two-confirmation rule is the only thing standing between that and a
pointless 3 a.m.-style bounce. That rule is a *timing* heuristic; the real
quantity is physical and free to compute:

| moment | sun elevation |
|---|---|
| real latch #1, fixed 10:58 | **+46.6** |
| real latch #2, fixed 17:00 | **+33.1** |
| dawn transient 05:36 | -1.1 |
| dusk pending 20:41 | -0.6 |
| next run 21:01 | -3.3 |

The separation is not marginal — every true case is tens of degrees up, every
false case is **below the horizon**. A gate at elevation > 10 deg admits both
real fixes with 23 deg to spare and excludes every transient seen so far. It
needs no sensor (astronomy from lat/lon/clock), it fails safe (strictly fewer
actions), and unlike the confirmation delay it costs no time on a real latch.

**And the two confirmations need not be adjacent.** The night gate

```
if not before["daylight"]:
    return 0                       # night: quiet, no event
if before["fraction"] < CLAMP_FRACTION:
    if st.pop("clamp_seen_at", None):   # <-- the reset lives HERE, below it
```

returns *above* the line that clears `clamp_seen_at`, so darkness never resets
a pending confirmation. A dusk confirmation at 20:41 therefore stays armed
until the 2.5 h staleness window expires at 23:11, and **any** run in that
window that catches `fraction >= 0.9` with `pv_v > 20` counts as the second
confirmation — no adjacency required, nothing sensible needed in between.
Given the array thrashes 27-78 V at dusk, that is a plausible pairing rather
than a theoretical one.

Two ways to close it: the elevation gate (blocks both samples, and is right
for other reasons), or clearing `clamp_seen_at` when it goes dark. The
elevation gate is preferable because it removes the whole class rather than
this instance.

**IT HAPPENED — 2026-08-06 21:01:34 local, so this is now a shipped fix.**
The watch caught the guard doing exactly the predicted thing:

```
21:01:34  latch_detected: fraction 1.0, pv_v 28.1, daylight true   [sun -3.6 deg]
21:01:40  sent PGN 0x14000 -> node 1: 02 (Standby)     <- ACK
21:01:55  sent PGN 0x14000 -> node 1: 03 (Operating)   <- ACK
```

The 20:41 sample paired with the 21:01 sample, exactly as the non-adjacency
analysis predicted, and bounced the MPPT in the dark. Third fix slot of four
spent on nothing, plus a 45 min cooldown.

Shipped in the same session: `sun_elevation_deg()` computed from the clock
alone, `MIN_SUN_ELEVATION_DEG = 10.0`, and the gate now clears `clamp_seen_at`
when it blocks. Verified on the Pi against the live path — the guard went
quiet and the stale confirmation was dropped from the state file. Also adds
`tests/test_latch_guard.py`, which the guard had never had, anchored to the
five real decision points of the day including the bad one.

Worth noting *why* this beats tightening the confirmation rule: the elevation
gate is free on a real latch, whereas every timing heuristic buys its safety
with delay — and delay was most of the 198 Wh residual below.

### What the guard was worth on its first full day: +801 Wh of 1031 Wh (78%)

Measured energy for local day 2026-08-06 (UTC buckets, local day = 07:00Z to
07:00Z — getting that boundary wrong truncates the evening and was worth an
hour of confusion):

| window | Wh |
|---|---|
| dawn → morning clamp, 05:40-10:10 | 125 |
| **morning clamp, 10:10-10:55** | **11** |
| after fix 1, 10:55-16:35 | 782 |
| **evening clamp, 16:35-17:00** | **3** |
| after fix 2, 17:00-18:40 | 110 |
| **day total** | **1031** |

Counterfactual: the clamp continues at its own measured yield (14.1 W morning,
6.3 W evening). That is not speculation — **a clamped array has no
self-recovery path** (the sawtooth's unaided recoveries all happen *before*
the clamp), and 08-01..04 demonstrated it by staying latched for days.

    fix 1:  782 Wh over 5.66 h  vs   80 Wh clamped  -> +702 Wh
    fix 2:  110 Wh over 1.67 h  vs   11 Wh clamped  -> + 99 Wh
    ------------------------------------------------------------
                                        RECOVERED     +801 Wh

So without the guard the day would have yielded roughly **230 Wh instead of
1031 Wh**. And this was a *dim* day (clear-sky index 30% of 08-05); on a bright
day the absolute recovery is larger.

#### Both figures are FLOORS — every number above is MPPT-metered

Measured over the healthy regulating window of 08-06 (11:00-16:00, 60 buckets,
clamped samples excluded): MPPT self-report **154 W** average against
battery-charge-plus-inverter-draw of **304 W**, or **271 W** once the 33 W
meter offset of #12 is removed. That is a **1.76x** under-report, independently
reproducing the 1.78x measured on 08-04 by a different route.

Three routes then agree on what the day actually produced:

| route | Wh |
|---|---|
| MPPT self-report × 1.80 | 1856 |
| ledger inferred branch, minus the 33 W bias × 15 daylight h | 1863 |
| *(ledger raw, uncorrected, for reference)* | *2358* |

The first two agree to **0.4%**, which is better than either deserves alone —
they fail in opposite directions (one under-reads at the sensor, the other
over-reads by a meter offset), so the agreement is meaningful rather than
circular.

**Restating the headline honestly: the day produced ~1.86 kWh, not 1031 Wh,
and the guard recovered ~1.44 kWh, not 801 Wh.** The MPPT-metered figures are
the conservative floor and are fine to quote as such — but they are not the
quantity a person means by "how much did the panels make".

Two clamps totalling 70 minutes cost ~198 Wh even *with* prompt clearing
(morning ~160 Wh, evening ~38 Wh, using the power measured minutes after each
fix as the counterfactual). That is the residual worth attacking with
current-limiting — the preventative fix in Unknown #1 — since the guard by
construction cannot act until a clamp has already formed and been confirmed.

**3. The MPPT status byte (offset 0 of DcSrcSts2).**
Always 0x03 in normal operation. Captured now but never seen change. Does it
move during a latch, a fault, or a mode change? **Test: correlate against the
latch trail.** Cheap — pure observation.

**4. Which other config records accept writes?**
We proved 0x11800 (absorption). The same shape *should* work for 0x11700
bulk, 0x11A00 float, 0x11B00 equalize — untested. Also unknown whether the SW
inverter (node 0) honours the same authorization model as the MPPT.
**Test: read-modify-write-restore on each, benign values only.**

**5. The MPPT under-reports EVERYTHING, and no third meter exists to arbitrate.**
Two results from 2026-08-06:

*The energy counter is not independent.* Modbus reg 131 is the MPPT's own
daily output Wh (resets at local midnight; reg 135/139/143 are week/month/year,
reg 133/137/141 the matching second-counters). Over the REGULATING window only
(post-unlatch 14:08-20:28, excluding latched hours the counter legitimately
cannot see) it logged 1153 Wh where battery charge + inverter draw + fridge
require **2053 Wh — a 1.78x under-report**, consistent with the instantaneous
current error. So the counter is derived from the same sensor and is useless
as a cross-check.

*There is no independent third meter.* The SW inverter's Modbus reg 81 reads
−5580 mA, identical to CAN `dc_a` — it measures its own terminals, not the
battery. Every other candidate (SOC, remaining_ah) is BMS-derived from the
same shunt, so it is circular.

**Therefore #5 cannot be settled remotely.** It needs an external
measurement — a DC clamp meter on the MPPT output during an on-site visit.

### PARTIALLY SETTLED 2026-08-06: during a clamp, the MPPT is blind, and the power is REAL

The clamped case *can* be settled remotely, because the two meters are on
opposite sides of the diode and the load is known. Comparing every clamped
5 min bucket (`pv_v > 20`, delta 0.3-4.0 V) against BMS pack power:

| day | n | MPPT reports | BMS pack power | max BMS |
|---|---|---|---|---|
| 07-30 | 25 | 23.5 W | **+267 W** | +359 W |
| 07-31 | 36 | 14.1 W | +135 W | +323 W |
| 08-01 | 59 | 10.0 W | +111 W | +462 W |
| 08-03 | 64 | 14.5 W | +157 W | **+535 W** |
| 08-04 | 120 | 10.9 W | +106 W | +311 W |
| 08-06 | 11 | 6.3 W | **-31 W** | +20 W |

(charger-free buckets only — see below.)

**So the diode path really does carry hundreds of watts that the MPPT does not
meter.** This confirms the overcharge story rather than the "it just stops
producing" reading: during a clamp, setpoints do not apply and the battery can
be taking +500 W with the controller reporting 15 W. That is a **safety**
finding, not merely a production one, and it is the mechanism behind the BMS
cell-overvoltage disconnect.

Why: at ~28 V the array sits far left of Vmp, deep in its current-source
region, so it delivers close to Isc — and Isc scales with irradiance. Hence
the effect is huge in strong midday sun and absent on 08-06, whose clamps fell
in morning shade and late-afternoon sun on a dim day (index 30%). **The clamp's
danger scales with irradiance**, which is exactly why the 08-01..05 event was
damaging and today's was not.

Three alternative explanations were checked and rejected:

1. *Generator or shore charger.* Ruled out with `charger_frac`: 07-30 had
   **zero** charger buckets and still showed +267 W against 23.5 W reported.
   The table above excludes every charger-on bucket anyway.
2. *Wrong meter.* A first pass used CAN `dc_a`, which showed the battery
   discharging in all 589 clamped buckets and suggested the opposite
   conclusion. `dc_a` is the **inverter's own DC draw** (Unknown #11), not
   battery net current. Retracted before it reached a commit.
3. *Bucket averaging.* A second pass at 1800 s buckets mixed clamped and
   healthy minutes and inflated the excess. At 300 s the effect survives on
   07-30..08-04 and correctly vanishes on 08-06.

**Consequence for every production figure in this file:** `solar_w` and the
Modbus Wh counters understate latched periods by 10-40x, so latched-day totals
are not floors-with-a-small-gap — they can miss the majority of the energy.
Only healthy-delta samples may be used for array-health work, which is what
the clear-sky index in #10 already does.

**Consequence for detection:** **BMS pack power greatly exceeding MPPT reported
power** means the converter is bypassed, full stop — no thresholds, no dither
problem, no dawn/dusk ambiguity.

But note what it does *not* do. On 08-06 the clamps were real and the excess
was zero, because there was too little irradiance to push current through the
diode. So this signature does not detect "is it clamped" — it detects **"is
this clamp dangerous"**, which is arguably the more useful question. It is a
*severity* signal, and the two are complementary:

| | voltage band | BMS excess |
|---|---|---|
| answers | is the converter clamped? | is the clamp doing harm? |
| fails when | sensor dither, dawn/dusk | irradiance too low to matter |

That suggests a two-speed guard: the band drives the ordinary path (two
confirmations, dawn/dusk exclusion, 20 min cadence), while a large BMS excess
justifies **skipping the confirmation delay** — an unregulated +500 W into the
pack is precisely the case where waiting 20 minutes for a second confirmation
is the wrong trade. Not built; the obstacle is plumbing, not physics, since
the Xanbus reader and the RS485 BMS logger are separate services.
Operationally this is low-stakes: SOC and energy come from the BMS, and the
display already derives production from battery + inverter rather than
trusting the MPPT. Recording it so nobody re-runs the analysis expecting
a different answer.

*Original characterisation, retained:*
Measured over 839 paired samples while regulating: the ratio true/reported
FALLS from 1.88 to 1.46 as current rises, while the difference RISES from
+3.3 A to +9.8 A. Fit: `true ≈ 1.35 × reported + 2.2 A`. That is neither a
scale error nor an offset, which is odd for a miscalibrated shunt. The fridge
(~0.8 A average) accounts for barely a tenth of it. **Open question: is the
MPPT under-reading, or is the BMS pair over-reading?** They agree with each
other, but they are the same model, so a systematic model error would not show
up as disagreement. **Next test:** compare BMS-integrated Ah against the
MPPT's own energy counters over a full day — an independent third opinion.

## Tier 2 — real value, harder

### Modbus side settled 2026-08-07, using the midnight rollover

Local midnight is the one moment that labels these registers for free: the
daily counters reset and the longer-period ones do not. Watching slave 30
across 00:01:19 on 08-07, **exactly two registers went to zero** — 131
(1050 → 0) and 133 (52714 → 0) — while 135/137, 139/141 and 143 held. That
pins the block layout, read as 32-bit (high, low) pairs:

| period | Wh pair | Wh | seconds pair | s | h |
|---|---|---|---|---|---|
| daily | (130,131) | 1050 | (132,133) | 52714 | 14.6 |
| weekly | (134,135) | 3426 | (136,137) | 269187 | 74.8 |
| monthly | (138,139) | 3670 | (140,141) | 323845 | 90.0 |
| yearly | (142,143) | 8067 | — | | |

Three independent cross-checks, all consistent:

- **daily Wh**: Modbus 1050 vs my own local-day integration of CAN `solar_w`,
  1031 Wh — **+1.8%**.
- **monthly Wh**: Modbus 3670 vs the 08-01..06 sum, 3794 Wh — **-3.3%**
  (the residual is UTC-vs-local day edges).
- **daily seconds**: 14.6 h against an array-awake window of 05:40-20:45,
  15.1 h. So 133 counts *operating* time, not wall clock — it froze at 52714
  from 23:33 through midnight while the MPPT idled.

Monotonicity holds too: daily 1050 ≤ weekly 3426 ≤ monthly 3670 ≤ yearly 8067.

**Consequence for #5, and it is the useful one:** the Modbus daily counter
agrees with the CAN `solar_w` stream to within 2%. They are the *same sensor*,
so the counter can never arbitrate the MPPT's under-reporting — it inherits it
exactly. That was suspected; it is now measured, and the suspicion can stop
being re-tested.

**6. PGN 127166 ("MPPT Data") — PARTIALLY DECODED 2026-08-06.**
60-byte fast packet, >16 frames (so it needs the standard 3/5 split; the
berrybms nibble split cannot reassemble it). 10,842 records paired against
labelled Modbus counters within 30 s:

| offset | width | meaning | evidence |
|---|---|---|---|
| 46 | u32 | **daily output Ah** | offset50/offset46 = 27.2-27.5 V across all samples — that ratio IS the battery voltage, so 46 is amp-hours of the same quantity 50 counts in watt-hours. Resets at local midnight. |
| 50 | u32 | **daily output Wh** | tracks Modbus reg 131 with a constant +7..8 offset; both reset to 0 at local midnight |
| 54 | u32 | active-seconds counter | increments ~1/s while producing, freezes when production stops, does NOT reset daily — so a week/month/lifetime accumulator, period unidentified |
| 58 | u16 | a daily counter | resets at midnight, held 712 all evening; semantics unknown |
| 19, 23 | u32 | slow lifetime counters | +1 and +12 over ~4.6 h |

The daily Wh/Ah pair is the useful part and is now confirmed. NOTE it inherits
the MPPT's current-sensor under-report (see #5), so it is a convenience, not a
truth source — integrating the derived production is still more accurate.

**7. RESOLVED 2026-08-06 — neither carries telemetry we want.**

`127005` (0x1F01D) is **not a counter or a measurement**. It is a **20.0 Hz
(50 ms) s16 at offset 2**, broadcast by BOTH the SW and the MPPT, oscillating
around zero (range −67..+74, mean +16, stdev 30) and **flipping sign between
consecutive samples**. Values are quantised in ~3.4 steps. Nothing physical on
this system changes sign twenty times a second, so this is a control or
clock-synchronisation term, not telemetry — consistent with IEA-PVPS T11-04
describing Xanbus master election and sync. It accounts for ~12% of bus
traffic and can be safely ignored.

`126991` (0x1F00F, "Sts") is **byte-for-byte CONSTANT** — `030403030200` on
both nodes across 39,586 frames overnight. Earlier notes claimed a toggling
flag byte; that was wrong. It is a static "operating normally" heartbeat, and
it is what the gateway asks a new node for during discovery (which is why we
answer it in `xanbus_node.py`). Only interesting if it ever changes — worth a
re-check during a fault.

`127167`, `127177`, `127174` — still byte-for-byte constant. Same conclusion:
recheck during a fault, ignore otherwise.

**8. Is there an access-level / unlock mechanism above "gateway"?**
IEA-PVPS T11-04 §5.3 describes Xanbus configuration messages carrying
**user / service / factory** access levels. We reached whatever level the
gateway role grants. Factory-level operations (calibration? firmware?) may sit
behind something else. Unknown whether anything we want lives up there.

**9. The RV-C proprietary path (DGN 0xEF00 + NAME-seeded CRC).**
Implemented and doc-vector-verified in `xanbus_write.py`, but it belongs to
the Freedom product family; no Conext device has been seen using it. Probably
a dead end now that the native path works — keep for reference.

## Tier 3 — open questions about the physical system

**12. The two DC meters disagree by ~33 W on the baseline, and it matters.**

Found while auditing 2026-08-06's own work. In darkness the only DC consumers
are the inverter and the fridge, so `battery_out - inverter_draw` should be
the fridge and nothing else. Over five dark nights it is **negative**:

| night | battery out (4 h) | inverter draw | implied DC load |
|---|---|---|---|
| 08-02 | 409 Wh | 452 Wh | **-43 Wh** |
| 08-04 | 388 Wh | 453 Wh | **-65 Wh** |
| 08-06 | 412 Wh | 455 Wh | **-43 Wh** |

A negative unmetered load is impossible, so one meter is wrong. Localised: the
BMS puts the non-fridge baseline at **80.3 W** (`baseline_w` from the Otsu
profile) while the Conext reports drawing **113 W** — a 33 W / 29% gap. Same
family as #5, but between the BMS shunt and the *inverter's* shunt rather than
the MPPT's.

**The fridge itself is fine.** The differenced signal is still cleanly bimodal
— two clusters 63 W apart at ~35% duty on 5 min buckets — it just sits on a
-32 W pedestal. And the published profile (75.8 W, 29.1%, 0.528 kWh/day) is
**immune** to this, because `dc_load_profile` splits `pack_p` against itself
rather than differencing the two meters. The 63 W I measured is lower only
because 5 min buckets smear the compressor edges; the 15 s server figure is
the better one.

What was NOT immune: `/v2`'s dark-path `dcLoadW()` computed `-batt - inv` and
clamped the negative to zero, which hid the sign but not the bias and so
rendered the fridge at roughly half size. Fixed to use the server's split
(`battW() <= split_w`), which compares one meter with itself.

Cautionary note on method: the server endpoint and the earlier hand analysis
"independently agreed within ~1%", which felt like confirmation. It was not —
they were two implementations of the same method. Agreement between two
routes only means something when the routes can fail differently.

**Third victim, found the same night: the 30-day energy ledger.**
`solar_energy_daily` infers production as `GREATEST(solar_w, batt + dc_w)` to
compensate for the MPPT under-reading — the same two-meter difference, and it
stays positive after dark. Measured 2026-08-07: **54 Wh of "solar" across
2.2 hours of full darkness**, ~25 W of pure bias. Fixed by gating the inferred
branch on array voltage (`pv_v < 15` → use the MPPT reading), which removed
110-190 Wh/day — about 6% — from every day in the ledger:

| day | before | after |
|---|---|---|
| 08-07 (all dark) | 54 Wh | **1 Wh** |
| 08-06 | 2543 | 2358 |
| 08-05 | 3835 | 3652 |

Note the gate is on **voltage, not power**, for the third time in this file:
during a clamp the MPPT reports single-digit watts in broad daylight, so a
power gate would zero out exactly the hours the inferred branch exists to
rescue.

**The pattern worth remembering: every place that differenced the two DC
meters was wrong, and there were three of them** (`/v2` dark path, the daily
ledger, and my own hand analysis). The one place that was right —
`dc_load_profile` — compared a meter with itself. Prefer same-meter
comparisons over cross-meter arithmetic wherever the question allows it.

Open: which meter is right. Unresolvable remotely for the same reason as #5 —
it needs a clamp meter. Practical rule meanwhile: **trust the BMS shunts for
absolute DC power** (two of them, and they agree with each other within
0.8 A), and treat `dc_w` as indicative.

Still unfixed and deliberately so: `load_wh` in the ledger is inverter draw
only, so it omits the ~0.53 kWh/day fridge. Adding a modelled figure to a
measured column would mix the two; the honest options are a separate DC-load
column or leaving it, and that is a display decision, not a data one.

**10. Array health — improving, but the record is CONFOUNDED by the latch.**

Peak array voltage by local day: 07-30 112.7, 07-31 111.5, 08-01 111.8,
08-02 76.9, 08-03 68.4, 08-04 61.7, **08-05 98.9**. MPPT-metered energy the
same days: 984, 775, 242, 189, 261, 189, **1735** Wh.

Do NOT read that 9x energy jump as smoke clearing. 08-02..04 were spent
LATCHED, and a latched MPPT cannot meter power that bypasses it through the
diode — so those totals are floors, not measurements. The 08-05 jump is mostly
the latch being cleared at 13:37, not extra sun.

**Judge array health from AFTERNOON hours only.** The array is south-east
facing and shaded until early afternoon, so morning comparisons measure
shade, not air quality — an earlier "smoke has not cleared" reading based on
07:00/08:00 hours was withdrawn for exactly this reason.

Peak `pv_v` is the sounder indicator since it is independent of the metering
fault, and 61.7 -> 98.9 V is a genuine improvement. But it is still partly
latch-dependent (a latched array pins at ~28 V), so it is not clean either.

**08-06 is the first day that starts with a working latch detector and a
known-good converter, so its daily total will be the first uncontaminated
production figure this project has.** Judge smoke recovery from that, not from
the back-history.

### A metric that survives all of this: the clear-sky index

Raw daily totals confound weather, geometry and the latch. Normalising by
computed clear-sky plane-of-array irradiance removes geometry, and filtering
to healthy-delta samples removes the latch:

    index = solar_w / POA(day, local_hour)      # W per W/m2, arbitrary units
    keep only  pv_v - dc_v > 8 V                # exclude clamped samples
    keep only  09:00-16:00 local, POA > 200

| day | n | index | vs 08-05 | usable? |
|---|---|---|---|---|
| 07-30 | 56 | 0.144 | 21% | **no — demand-limited** |
| 07-31 | 19 | 0.099 | 15% | **no — demand-limited** |
| 08-01 | 1 | 0.012 | 2% | no — latched all day |
| 08-05 | 51 | 0.675 | 100% | yes |
| 08-06 | 59 | 0.205 | 30% | yes |

**The filter that matters most is one I nearly missed: exclude
DEMAND-limited samples.** An MPPT only produces what is asked of it, so once
the battery is full the array idles near Voc and the index measures load, not
sunlight. 07-30 20:20 is the giveaway — `pv_v` 114.1 V with **3.0 W**, at
`dc_v` 28.03 (absorption). Those days must be dropped, not read as "worse than
today". Require a battery that is actually accepting charge (`dc_v` well below
absorb, meaningful surplus).

On the two comparable days — both with a discharged battery taking everything
offered — **08-06 sits at 30% of 08-05**. Today is simply a dim day.

Independent confirmation from the discriminator above: right after each day's
bounce the array sat at essentially the same voltage but very different
current — 08-05 **91.9 V / 634 W**, 08-06 **88.3 V / 228 W**. Same voltage,
2.8x the current: that is irradiance, not the tracker. And it is not
geometry — computed POA at 08-06 11:00 is slightly *higher* than at 08-05
13:40.

So: today's poor numbers are weather, not degradation, and the array itself
demonstrated a healthy ~88-92 V MPP on both days.

Dawn 08-06 also showed the array reaching `pv_v_max` 103.4 V at low load —
encouraging, though dawn Voc is not comparable to midday Voc.

**12. Generator fields — wired on spec, never validated.**
`126998 assoc 0x13` (GEN1) V/I/freq. Correct per Xantrex's own enum table and
berrybms's gen-on captures, but our generator has never run during a capture.
**Test: whenever the generator next runs.**

**13. Pack A's cell imbalance — trajectory unknown.**
Daily worst spread is ~400 mV on A vs ~30 mV on B. Is it stable, worsening, or
seasonal? Now charted on `/v2/history`; needs weeks of data. This is the one
unknown with a hardware-failure tail risk.

## Answered — kept so we don't re-litigate

- ~~Why are our transmitted frames ignored?~~ No address claim (J1939/81).
- ~~Why ACCESS DENIED on commands?~~ NAME function must be 134 (gateway).
- ~~Why ACCESS DENIED on config writes?~~ Must use write-form `byte[0]=0x00`.
- ~~Why NAK on config writes?~~ Change counter is an optimistic-concurrency
  token; echo the one you read.
- ~~Why does PV power read 0?~~ No input-side current sensor on this model.
- ~~Where's the fridge in the data?~~ Bimodal in native 5 s `pack_p`.
  Characterised over 7 night hours / 8 complete cycles (Otsu split at
  −123 W): **draw 76.0 W, duty 29.0%, 0.53 kWh/day, cycle 14 min on /
  36 min off (~50 min period)**. Needs no new logging — 15-minute buckets
  simply averaged straight through it.
- ~~Is the MPPT damaged?~~ No — diode-clamp latch, clears on a mode bounce.
- ~~What is the SW inverter's `dc_w` measuring?~~ **Its own draw (house AC
  loads) only — it is blind to solar.** Proven 2026-08-05 by comparing a
  known latch (~380 W bypassing the converter) against dusk darkness: dc_a
  and dc_w were identical in both (~−4.5 A, ~120 W). So it can never serve as
  a bus-total, and it cannot discriminate a latch from darkness.
- ~~Can the latch guard false-positive at dawn/dusk?~~ **Yes, and it was
  able to.** The array voltage passes through battery voltage on its way
  up/down, so darkness reads as a clamp for ~5–10 min (observed 20:40:
  pv_v 28.7 vs out 26.5, delta 2.2 V, 1 W production). Fixed by requiring two
  CONSECUTIVE confirmations 20 min apart — longer than the dusk window,
  far shorter than a real latch.
