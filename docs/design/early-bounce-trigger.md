# Design: early bounce at the 45 V cliff

Draft 2026-08-07. **Not built, and the first step is deliberately not code.**

## The finding this rests on

Across 200 h of daylight buckets, for every sample where the array was
tracking, does a clamp follow within the hour?

| pv_v | n | clamps within 60 min |
|---|---|---|
| 35-40 V | 60 | **85%** |
| 40-45 V | 55 | **55%** |
| **45-50 V** | 90 | **2%** |
| 50 V+ | 336 | **0%** |

Below 45 V: 72%. At 45 V and up: 2 of 426. Confirmed once out-of-sample the
same evening (crossed 45 V at 16:55, clamped 17:45).

The guard currently waits for the clamp at `pv_v` ~28 V. By then the array has
already spent an hour or two producing almost nothing.

## What the trigger would cost and buy

Firing rate if the trigger were `pv_v < 45 V` while tracking, with re-arm at
48 V, 06:00-16:00:

| day | crossings | first | time below 45 V | Wh harvested below 45 V |
|---|---|---|---|---|
| 08-01 | 1 | 07:20 | 8.6 h | 114 |
| 08-03 | 1 | 07:55 | 8.1 h | 152 |
| 08-04 | 1 | 07:50 | 8.2 h | 121 |
| 08-05 | 2 | 08:25 | 3.9 h | 121 |
| 08-06 | 2 | 08:50 | 2.6 h | 67 |
| 08-07 | 1 | 08:25 | 1.9 h | 45 |

**Read that carefully — the low crossing count is an artefact.** Once below
45 V the array *stays* below until something intervenes, so history shows one
crossing per day. With the intervention in place each bounce restores the
array and it walks down again, creating a new crossing. On 08-07 the walk from
87 V to 45 V took ~100 minutes, so the realistic post-intervention rate is
**up to ~6/day**, not 1-2. The historical data cannot tell us this directly
because the intervention changes the trajectory it would be measured on.

**The prize is biggest on the worst days.** 08-04 spent 8.2 h below 45 V and
harvested 121 Wh in that window — about 15 W average — on a day that made
189 Wh in total. If bouncing held the array near its MPP for those hours, that
day roughly doubles. On a good day like 08-07 the addressable window is 1.9 h
and 45 Wh, so the gain is small. That is a good property: it helps most
exactly when help is worth most.

## Re-sized 2026-08-08 on a BRIGHT day: the prize is ~10x bigger

The table above was built from 08-01..07, which were all dim. 08-08 was the
first bright day with the instrumentation in place, and it changes the number
completely.

Second crossing of 08-08: crossed 45 V at 12:10, clamped 13:05, guard fixed at
13:14.

| | |
|---|---|
| descent window 12:10-13:05 | 55 min |
| actually produced in it | **82 Wh** (~90 W average) |
| post-fix output, same conditions | **534 W** |
| what the window was worth at that rate | **490 Wh** |
| **loss to the descent** | **~408 Wh** |

Against a 1525 Wh day that is **27% of everything the array made**, and it is
an order of magnitude more than the 23-43 Wh estimated from the dim days.

The reason is obvious in hindsight and matters for how the trigger should be
valued: on a dim day the array cannot make much *anyway*, so the descent
window is cheap. On a bright day the same 55 minutes costs 400+ Wh. **The
early bounce is worth little exactly when it is easy to test, and a great deal
exactly when it is not.**

*Caveat, stated because the number is large:* the 534 W reference is what the
array produced after the fix at 13:15, roughly an hour later. Both times sit
near solar noon so the plane-of-array irradiance is comparable, but the
reference may be slightly optimistic. Even discounted heavily this is
hundreds of watt-hours, not tens.

*Second caveat:* a single bounce would not hold for the rest of the day. The
array walks down again — 55 min is the measured time — so a bright day would
need 2-3 early bounces, which is what the 6/day cap in the control design
below is for.

## The assumption nobody has tested

**Every bounce we have ever done was from a clamped array** — four of them,
all from ~28 V, all recovering to 88-93 V. We have never bounced a
*still-tracking* array at 45 V.

It should work: Standby opens the PV input, the array flies to Voc, and
Operating forces a fresh sweep — none of which depends on where it started.
But "should" is what produced four separate guard bugs already, and the whole
premise of the trigger is that a 45 V bounce recovers as well as a 28 V one.

## So the first step is one supervised manual bounce, not automation

Run `xanbus_node.py --bounce --dest 1 --function 134 --send` once, by hand,
while the array is tracking somewhere in the 40-45 V band, and measure:

1. Does `pv_v` return to ~88 V, the same as it does from a clamp?
2. How much power does it settle at, versus the 30-40 W it was making?
3. How long before it walks back down to 45 V?

That third number is the one the whole design hinges on: it sets the firing
rate, the daily cap, and whether the energy gained exceeds the nuisance. One
morning's observation answers all three, and costs a 15 s interruption of
~35 W — about 0.15 Wh.

If it recovers poorly, the design dies cheaply and nothing was automated.

## If it does work: the control design

Fold into the existing guard rather than adding a second actor — one actuator
must have one owner.

    priority 1  clamped (delta 0.3-4.0 V)   -> existing clamp fix, cap 4/day
    priority 2  tracking and pv_v < 45 V    -> early bounce, cap 6/day

Guards on the early path, each with a reason:

- **Re-arm hysteresis at 48 V.** Without it the trigger chatters across the
  threshold. 3 V is wider than the ~1.1 V reporting dither.
- **Minimum 30 min between early bounces.** The measured walk-down from MPP to
  45 V is ~100 min, so anything firing faster than 30 min means the bounce did
  not take, and repeating it will not help.
- **Sun elevation > 15 deg**, higher than the clamp guard's 5 deg. A 45 V
  reading near dusk is the array genuinely decaying, and a bounce recovers
  nothing. The clamp fix stays at 5 deg because breaking a clamp is worth
  doing even late.
- **Two consecutive confirmations**, same as the clamp path, and the same
  two-healthy-runs hysteresis to clear. Every threshold here needs hysteresis
  in both directions; that lesson has been paid for three times.
- **Separate daily cap** from the clamp fix, so a busy morning of early
  bounces cannot exhaust the budget that clears an actual clamp. The clamp is
  the more serious condition and must never be starved by the cheaper one.

## How we would know it worked

Log `early_bounce` with before/after `pv_v` and power, and track one KPI:
**hours per day spent above 45 V while the sun is up.** That is the quantity
the trigger exists to increase, it is measurable from data we already keep,
and it does not depend on the MPPT's under-reporting watt figures.

Compare like days using the near-MPP clear-sky index from `xanbus-unknowns.md`
#10, so a bright week does not get mistaken for a working feature.

## Risks, honestly

- **More automated hardware writes.** Currently up to 4/day; this could take it
  to 10. Each is a supported mode change the Insight UI performs itself.
- **Wear is almost certainly a non-issue** — even a mechanical contactor rated
  for 10^5 cycles survives 27 years at 10 bounces/day — but nobody has
  confirmed from the datasheet whether Standby opens a contactor at all.
- **A bounce during a genuine cloud edge** achieves nothing and costs 15 s of
  production. Harmless, but it will happen.
- **Failure mode if the trigger is wrong**: the array gets bounced repeatedly
  without recovering, capped at 6/day, each costing ~15 s. Bounded and
  visible, not dangerous.
