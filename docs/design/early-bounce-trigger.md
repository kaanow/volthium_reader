# Design: early bounce at the 45 V cliff

## ARMED 2026-08-21. Validated 5/5 over four observe-only days.

Live on the Pi: `--act-on-sustained --act-on-early` on the guard unit. Unit
backed up to `/root/latch-guard.service.bak-20260821-preearly`; rollback is
removing the flag and `daemon-reload`, no code change.

**The pre-registered criterion was that each firing would have been RIGHT —
left alone, the episode goes on to clamp:**

| fired | the episode it fired on | outcome |
|---|---|---|
| 08-17 08:22 | crossing 08:18 | clamped after 48 min |
| 08-18 08:53 | crossing 09:16 | clamped after 108 min |
| 08-19 08:57 | crossing 08:53 | clamped after 68 min |
| 08-20 08:08 | crossing 08:11 | clamped after 92 min |
| 08-21 08:18 | crossing 08:07 | clamped after 100 min |

5 for 5. It also stayed **silent** on 08-17 11:51, which recovered on its own
in 4 minutes — precisely the case a crossing-triggered version would have
bounced needlessly. All five are morning descents at sun 23–43°; none at dawn
or dusk.

**What it addresses**, from the MPPT's own counter — same instrument either
side, no cross-meter arithmetic:

| day | fire | guard fixed | gap | made in the gap |
|---|---|---|---|---|
| 08-17 | 08:51 | 09:06 | 27 min | 5 Wh (11 W) |
| 08-18 | 09:22 | 11:04 | 114 min | 138 Wh (73 W) |
| 08-19 | 09:26 | 10:01 | 47 min | 18 Wh (23 W) |
| 08-20 | 08:37 | 09:43 | 78 min | 38 Wh (29 W) |
| 08-21 | 08:47 | 09:47 | 72 min | 23 Wh (19 W) |

**68 min/day on average**, with the array making 11–73 W. The 2026-08-14 test
showed a tracking array at 25 W recovering to 103 W in one minute, and clamped
arrays have gone to 860 W after a fix. That differential is the prize — but note
it is an ADDRESSABLE window, not a guaranteed saving: a bounced array walks down
again, which is what the 30-minute interval and 6/day cap bound.

### What to watch now that it is armed

- `early_bounce_result` — the acked/before/after record of each actual bounce.
- **A fire NOT followed by a clamp** would mean an episode resolved past 29 min,
  which nothing in 34 episodes has done. That is the signal to disarm and
  re-think, not to adjust the threshold.
- `early_fixes` in the state file against the 6/day cap. Hitting the cap means
  the array is walking down faster than 30 min after each bounce, and the
  economics change.
- The 15–29 minute band is still empty. If an episode ever lands there, the
  threshold's justification changes.

### One defect the observation period found

It logged **57 events across those 5 episodes**, one episode alone producing 18.
`below45_since` is only cleared by a re-arm or a fix, so the due condition stays
true on every 5-minute run for as long as the descent lasts. Fixed to fire on
the transition. Worth recording because the logic was right and the
instrumentation was not — and an 11× noisy stream is how an operator stops
reading it.

---

## RESULT 2026-08-14: the array DOES recover from a tracking state. Test passed.

The gating assumption is confirmed. A still-tracking array at 41.8 V recovers
from a bounce exactly as a clamped one does — instantly, and to full MPP.

Fired 08:20 local by `scripts/early_bounce_test.py`, one bounce, rc=0.

    08:17   43.2 V    25.1 W
    08:18   41.8 V    23.5 W     <- pre-fire
    08:19   42.6 V    25.2 W
    08:20   66.1 V    24.7 W     <- BOUNCE (15 s standby, in this bucket)
    08:21   93.1 V   101.0 W     <- recovered, one minute later
    08:29   99.1 V   104.8 W     <- peak
    09:13   73.6 V   180.6 W     <- +53 min, still tracking, still climbing

Scored against the criteria committed BEFORE the run:

| criterion | required | actual | |
|---|---|---|---|
| recovery peak | > 80 V | **99.1 V** | PASS |
| settled power | > pre-fire | **102.9 W vs 25.0 W** | PASS |
| walk back below 45 V | not within 15 min | **not in 53 min** | PASS |

None of the three kill conditions triggered. Power gain **+312%**. The 15 s
standby cost is invisible at 1-minute resolution — the fire bucket reads
24.7 W against 25.0 W before it.

### What this does NOT show, stated plainly

**It does not show that the bounce averted a clamp.** The crossing was at
07:59 and the bounce landed at 08:20 — **21 minutes in**, which is inside the
under-29-minute region where the rule says episodes recover on their own (10
for 10). This episode might well have recovered unaided. The first crossing of
the same morning, 07:28, did exactly that in 8 minutes with no intervention.

So the causal claim is limited to what was actually asked: **a tracking array
recovers from a bounce**. That was the untested assumption behind the entire
trigger design, every prior bounce having started from a clamped array at
27-30 V, and it is now answered. Whether an early bounce PREVENTS clamps needs
a fire at or after 29 minutes, where the outcome is otherwise determined.

### What to build

Fire at the **29-minute mark**, not at the crossing. At 29 min the rule is 20
for 20 that a clamp follows, so every fire is justified and none is wasted; at
the crossing about a third of episodes would be bounced needlessly. The control
design already specified below (separate daily cap, 48 V re-arm, 30 min minimum
interval, elevation floor, two confirmations) is unchanged.

### Methodological consequence

`cliff_table.py` is no longer pure natural history from this date. This
episode is recorded there as a RECOVERY at 22 minutes; it was a deliberate
write. The 20-of-30 figure and the 29-minute rule are pre-intervention and must
stay that way.

---

## PRE-REGISTERED TEST, authorised 2026-08-13, not yet run

Operator approved the supervised bounce without supervision, on the correct
reasoning that it is the SAME operation the guard already performs. Verified
before accepting: `run_fix()` and `xanbus_node.py --bounce --dest 1
--function 134 --send` issue identical CAN writes — claim an address
presenting NAME function 134, `set_mode(dest, 0x02)` standby, wait,
`set_mode(dest, 0x03)` operating. 16 `latch_fix_result` events on record, all
16 acked.

**What is new is not the command, it is the array's starting state.** All 16
bounces were from a CLAMPED array between 27.3 and 29.8 V. None was from a
still-tracking array at ~42 V, and the whole trigger design assumes it
recovers the same way.

**Fire condition:** array TRACKING in the 40–45 V band during a descent, sun
above 15 deg, not already clamped, and not within 2 min of a guard run (both
claim an address). ONE bounce.

**Measurements, fixed in advance:**

| | recorded before | recorded after |
|---|---|---|
| `pv_v` | at fire | peak within 5 min, and settled value at +10 min |
| `solar_w` | 5-min mean before | 5-min mean at +5..+10 min |
| time to walk back below 45 V | — | minutes from fire |

**What counts as SUCCESS:** `pv_v` recovers above 80 V (a clamp bounce reaches
~88–93 V) AND settled `solar_w` exceeds the pre-fire value by more than the
5-min noise. Anything less and the trigger is not worth building.

**What KILLS the design, stated in advance:**
- recovery peak below 60 V — the tracker cannot re-acquire from a tracking
  state the way it does from a clamp, and the premise is false;
- settled power at or below pre-fire — the bounce buys nothing;
- the array walks back below 45 V in under 15 min — the intervention would
  need to repeat so often it is worse than the clamp.

**Cost if it fails:** 15 s of standby, ~0.15 Wh. Standby drives the array to
Voc (~114 V), inside the MPPT's 150 V rating; it is the device's own
documented transition. A resulting clamp is cleared by the guard within
~20 min.

**A caveat this document's own numbers create.** Everything below was written
2026-08-07/08 and rests on "12 of 12, every crossing clamps, none recover".
That is RETRACTED. The regenerated table is **20 of 30 clamped, 10 recovered**,
and every recovery resolved in under 29 minutes. So firing at the crossing
would bounce needlessly on about a third of episodes, while firing at the
29-minute mark catches every clamp on record with no wasted bounce. The
supervised test is still the right first step — it settles the
does-it-recover question that gates either variant — but the trigger it feeds
should be the 29-minute one, not the crossing.

---

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
