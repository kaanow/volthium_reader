#!/usr/bin/env python3
"""Derive the 45 V cliff table from telemetry. Runs OFF the Pi (CLAUDE.md #1).

The cliff finding — every 45 V crossing ends in a diode clamp, none recover —
was for a week maintained by hand in docs/xanbus-unknowns.md, and it drifted:
the table listed 9 crossings, the prose under it said "twelve of twelve", and
the summary at the top of the file said 14 of 14. All three were written at
different times and none was wrong when written.

Worse than the arithmetic, the hand-built table only ever looked at MORNINGS.
Four afternoon crossings (08-06 15:30, 08-07 16:55, 08-08 12:10 and 15:20)
were simply absent, and they are the ones that carry the most energy — the
array is at full output when it starts walking down. Their omission is what
made the median look like 80 minutes.

So: state the rule, run it, paste the output. Any number in the doc that this
script does not produce is stale by definition.

    python3 scripts/cliff_table.py [--hours 300] [--url https://volts.alti2.de]

The rule (all four conditions, deliberately explicit):
  1. DAYLIGHT — sun elevation >= MIN_SUN_ELEVATION_DEG, the same gate the
     latch guard uses. Without it, dusk dominates: the array decays below
     45 V every single evening because it is getting dark, which is not the
     tracker walking down its own IV curve. Ungated, one "crossing" ran 485
     minutes from 21:10 to 05:15 the next morning.
  2. ARMED — pv_v reached 48 V while tracking since the last outcome, so the
     sawtooth (repeated dips that abort on their own) counts once, not once
     per wobble.
  3. CROSSING — pv_v falls below 45 V while NOT already clamped.
  4. OUTCOME — either a clamp (delta band, matching the live detector) or a
     recovery back above 48 V. Whichever comes first ends the episode. An
     episode that has not resolved by nightfall is DISCARDED, not counted —
     see MAX_BUCKET_SPREAD_V for what that costs.
  5. PINNED — the array must not have oscillated through the bucket, which is
     what the MPPT does at dawn and dusk. Defence in depth behind (1).

FROM 2026-08-14 THIS TABLE IS NO LONGER PURE NATURAL HISTORY. The early-bounce
test intervened in the 08-14 morning descent, which recovered the array to 93 V
and is therefore recorded here as a RECOVERY. It was not one — it was a
deliberate write. Any future automated early-bounce trigger will do the same at
scale, so recoveries after this date must be cross-checked against
latch_fix_result and the manual test log before being read as the array's own
behaviour. The 20-of-30 figure and the 29-minute rule are pre-intervention and
should stay that way.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xanbus_latch_guard import (   # noqa: E402
    MIN_SUN_ELEVATION_DEG, sun_elevation_deg,
)
from xanbus_telemetry import (     # noqa: E402
    LATCH_DAYLIGHT_V, LATCH_DELTA_MAX_V, LATCH_DELTA_MIN_V,
)

# A real walk-down is PINNED; the MPPT hunting at dawn or dusk OSCILLATES.
# Measured spread of pv_v INSIDE a single 5 min bucket:
#
#     real descent (08-09 11:00-13:00)   median  5.1 V, max  9.7 V
#     dawn hunting (05:xx)               median 41.1 V, p90 71.6 V
#     dusk hunting (20:xx)               median 48.6 V, p90 64.4 V
#
# 20 V is twice the worst descent and half the mildest hunting median. It
# rejects 3.8% of buckets and changes the current table by nothing, because
# the daylight gate already excludes every hunting episode on record — today
# the last sub-45 V hunting dip was at 05:50 local with the sun at 0.0 deg,
# and the gate admits from 5 deg.
#
# It is kept as defence in depth for one specific scenario: at 51.12 N the
# winter sun climbs far more slowly while low irradiance persists longer into
# the morning, so hunting could still be running when elevation passes 5 deg.
# This test keys on the physics rather than the clock, so that case is covered.
#
# It is NOT, however, a substitute for the daylight gate, and an earlier draft
# of this comment wrongly claimed it made the metric "season-proof". Measured:
# removing the elevation gate and keeping only the spread test gives 21
# crossings against the correct 16 — no better than no filter at all. The two
# catch different things. What the elevation gate actually excludes is not
# oscillation but EVENING EPISODES THAT RUN INTO NIGHTFALL, which have a
# perfectly smooth low-spread decay the spread test cannot see:
#
#     07-30 19:35 (sun +10.4)  ->  20:45     70 min
#     07-31 20:05 (sun  +5.7)  ->  20:10      5 min
#     08-04 21:10 (sun  -4.2)  ->  05:15    485 min   overnight, meaningless
#     08-06 19:45 (sun  +7.3)  ->  05:35    590 min   overnight, meaningless
#     08-07 20:55 (sun  -3.0)  ->  21:00      5 min
#
# KNOWN LIMITATION, recorded rather than fixed: three of those five are
# obvious artifacts (two run all night; two resolve in 5 min as the array
# simply goes dark), but 07-30 19:35 is a plausible genuine 70 min crossing
# that the gate drops because the episode had not resolved before dusk. So
# the table may under-count late-afternoon crossings by roughly one in
# seventeen. Dropping an episode whose OUTCOME is contaminated by nightfall is
# the more defensible error than counting a dusk decay as a clamp, but it is
# an error, and "16 of 16" should be read as "16 of 16 that resolved in
# daylight".
MAX_BUCKET_SPREAD_V = 20.0

ARM_V = 48.0        # must get back up here before another crossing counts
CROSS_V = 45.0      # the cliff itself
LOCAL_OFFSET_H = -7  # site is America/Vancouver; PDT during the study window


# 60 s, not 300. The guard has got steadily faster — 45 min exposure, then 22,
# then ~10, and on 2026-08-10 the array read as clamped for ELEVEN MINUTES in
# the whole day. At 5 min resolution a clamp that brief no longer survives
# averaging: the bucket mixes clamped samples with the post-fix recovery and
# the mean lands outside the detector band, so the crossing vanishes from this
# table entirely. That is a measurement instrument going blind BECAUSE the
# system improved, which is the worst kind of silent failure — the metric
# looks fine and simply stops counting.
#
# Measured: 300 s finds 16 crossings, 60 s finds 19. Of the three extra, two
# are 1-minute dusk artifacts (killed by MIN_EPISODE_MIN below) and one is the
# genuine 112 min crossing of 2026-08-10.
#
# BUT THIS CONSTANT DECIDES THE HEADLINE, AND THAT IS A PROBLEM. Same window,
# same rule, only BUCKET_S varied (2026-08-11, after the re-arm fix):
#
#     30 s   n=30  17 clamped  13 recovered   clamp min 29   longest rec 47
#     60 s   n=27  17 clamped  10 recovered   clamp min 29   longest rec 28
#    120 s   n=26  18 clamped   8 recovered   clamp min  2   longest rec 26
#    300 s   n=24  17 clamped   7 recovered   clamp min 10   longest rec 120
#
# At 60 s the one-directional rule is a PERFECT two-way separation — every
# episode of 29 min or more clamps, every one under it recovers. That is an
# artifact of this constant, not a law:
#
#   - at 30 s, 08-10 12:42 is a 47-minute RECOVERY, so "still running at 29 min
#     always clamps" becomes 17 of 18. It is really demand limitation (the Pi
#     logged bulk->absorption 13:28:57, absorption->float 13:30:47) but
#     DEMAND_LIMITED_V compares ONE bucket against the crossing, and at 30 s
#     that bucket has HIGHER output than the crossing did, so the test passes
#     it through.
#   - at 300 s, the 08-10 morning episode is a 120-minute RECOVERY. At 60 s the
#     same physical event is a 112-minute CLAMP. Opposite labels, same event:
#     the clamped buckets at 10:18-10:23 average out of band at 5-minute
#     resolution.
#
# Raw sample cadence is 15 s, so by this comment's own argument 30 s is the
# more defensible choice — and 30 s is the one that breaks the rule. 60 s is
# kept because it is what every published figure rests on, but treat the clean
# two-way separation as UNCONFIRMED. The honest claim remains the
# one-directional one, and even that is one 30 s bucket away from 17 of 18.
BUCKET_S = 60

# 2 minutes, and the number is calibrated, not guessed. Sweeping the floor:
#
#     floor  episodes  clamped  recovered   shortest recovery / clamp
#       0       32       19        13            1 /  1
#       2       27       17        10            2 / 29
#       5       24       17         7            6 / 29
#      10       21       17         4           12 / 29
#
# The clamped count is 17 at every floor from 2 upward — the floor does not
# touch that side at all, it only decides how many brief RECOVERIES survive.
# A 10 min floor was set on 2026-08-10 to kill 1-minute dusk artifacts, before
# it was known that recoveries exist; it was silently discarding the most
# interesting class of episode. 2 minutes removes the single-sample noise and
# nothing else.
MIN_EPISODE_MIN = 2

# A "recovery" must be the TRACKER re-acquiring, not the battery filling up.
# When the pack reaches float the MPPT stops loading the array and it flies to
# open circuit — pv_v shoots past 100 V while output COLLAPSES. That satisfies
# "climbed back above ARM_V" and is not a recovery at all; it is the array
# being switched off from the other end.
#
# 2026-08-10 12:43 was exactly this: 47 min below 45 V, then 112.6 V at 3.0 W
# against 115.3 W at the crossing. Counted naively it was the longest recovery
# on record and it destroyed the clean 28-min/29-min separation between
# recoveries and clamps. It is the same demand-limitation confound that made
# peak pv_v a useless array-health metric (docs #10) — it reaches the cliff
# table too.
#
# Both conditions required: Voc-like voltage AND output below where the
# crossing started. Genuine re-acquires on record end at 43-90 V with output
# equal or higher.
DEMAND_LIMITED_V = 100.0

# A RECOVERY MUST PERSIST, and the threshold here is not fitted.
#
# Two of the eleven "recoveries" were the MPPT giving up in low light and
# RELEASING the array to open circuit — 91-99 V at 0.00 W — then retrying a
# minute later. Both on 2026-08-02, a smoke day whose peak output was 42.6 W.
# The 18:56 bucket reads 51.4 V / 1.29 W, which satisfies "climbed back above
# ARM_V"; the very next minute is 91.5 V / 0.00 W. The declared recovery was
# the array caught mid-flight on its way to Voc.
#
# Neither the elevation gate nor MAX_BUCKET_SPREAD_V could see it. The sun was
# 12-20 deg, well above the 5 deg gate, and the oscillation is BETWEEN buckets,
# not within one, so the spread test never fires.
#
# The discriminator that works needs no tuning: a tracker that has re-acquired
# is drawing current, and open circuit is 0 W by definition. Consecutive
# minutes still producing after the declared outcome:
#
#     the two artifacts   0 and 1 min
#     all nine genuine    241 .. 767 min
#
# A 240x gap. Any value from 2 to 240 gives an identical table, so this is an
# observed separation rather than a chosen cut — unlike MIN_EPISODE_MIN, whose
# value does change the answer.
RECOVERY_MUST_PRODUCE_MIN = 5


def fetch(url: str, hours: int, source: str) -> list[dict]:
    q = (f"{url}/api/solar/series?source_id={source}&hours={hours}"
         f"&bucket_s={BUCKET_S}")
    with urllib.request.urlopen(q, timeout=60) as r:
        return json.load(r)["series"]


def is_clamped(pv: float, dv: float) -> bool:
    """Same band as the live detector — a clamp pins the array one diode drop
    above the battery, so it is a BAND, not an upper bound."""
    return pv > LATCH_DAYLIGHT_V and LATCH_DELTA_MIN_V <= pv - dv <= LATCH_DELTA_MAX_V


def episodes(series: list[dict]) -> list[dict]:
    rows = []
    for r in series:
        pv, dv = r.get("pv_v"), r.get("dc_v")
        if pv is None or dv is None:
            continue
        # Reject buckets the array oscillated through — see MAX_BUCKET_SPREAD_V.
        lo, hi = r.get("pv_v_min"), r.get("pv_v_max")
        if lo is not None and hi is not None and hi - lo > MAX_BUCKET_SPREAD_V:
            continue
        tu = dt.datetime.strptime(r["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)
        rows.append((tu, pv, dv, r.get("solar_w") or 0.0))
    rows.sort()

    out: list[dict] = []
    armed = False
    start: dt.datetime | None = None
    wh = 0.0
    for tu, pv, dv, sw in rows:
        local = tu + dt.timedelta(hours=LOCAL_OFFSET_H)
        if sun_elevation_deg(tu.timestamp()) < MIN_SUN_ELEVATION_DEG:
            armed, start = False, None       # night resets everything
            continue
        clamped = is_clamped(pv, dv)

        # ORDER MATTERS, and getting it wrong invented a finding. An earlier
        # version re-armed first — `armed, start = True, None` — which wiped
        # the open episode, and the `if start is None: continue` below then
        # skipped the outcome block entirely. The recovery branch was
        # unreachable: the function could only ever emit clamps, so "none
        # recovered" was a property of the code, not of the array. Close any
        # open episode BEFORE re-arming.
        if start is not None:
            wh += sw * BUCKET_S / 3600.0   # NOT a hardcoded 300 — see BUCKET_S
            if clamped or pv >= ARM_V:
                mins = round((local - start).total_seconds() / 60)
                demand_limited = (not clamped and pv > DEMAND_LIMITED_V
                                  and sw < start_sw)
                if mins >= MIN_EPISODE_MIN and not demand_limited:
                    out.append({"crossed": start, "ended": local,
                                "minutes": mins, "wh": round(wh),
                                "clamped": clamped, "held_min": None})
                start = None
                armed = not clamped    # a clamp needs a fresh climb to re-arm
        elif clamped:
            # A clamp seen with NO open episode must disarm too, and leaving
            # this out invented an entire crossing. `armed` was only ever reset
            # inside the outcome block above, so once the array latched without
            # an episode open, `armed` stayed True for the whole latch — and the
            # first bucket where the delta jittered back out of the band then
            # opened a "crossing" from 30 V.
            #
            # 2026-08-10 is the case: the array fell 87 -> 31 V at 17:11 and sat
            # at 30-32 V making 4-8 W until the guard bounced it at 17:31. From
            # 17:13 to 17:25 the delta drifted to 4.06-5.66 V — just outside the
            # 4.0 V band, because dc_v was sagging, not because the array moved
            # — so the table opened an episode at 17:13 and closed it "clamped"
            # at 17:26. Thirteen minutes, entirely INSIDE one unbroken latch,
            # with pv_v never once above 33 V. The Pi's own 1 Hz detector agrees
            # it was continuous: mppt_latched at 17:29:58 with clamped_s=601 and
            # no mppt_unlatched until 17:33:54.
            #
            # That phantom was the sole source of "min 13", the sole exception
            # making the under-29-min rule read 10 of 11 instead of 10 of 10,
            # and the sole evidence for the "13 min to formally clamp" figure in
            # the fast-path table in docs/xanbus-unknowns.md.
            armed = False

        if pv >= ARM_V and not clamped:
            armed = True
        if armed and start is None and pv < CROSS_V and not clamped:
            start, wh, start_sw = local, 0.0, sw
    _annotate_held(out, rows)
    _drop_nonproducing_recoveries(out, rows)
    return out


def _drop_nonproducing_recoveries(eps: list[dict], rows: list) -> None:
    """Reclassify a "recovery" that stops producing immediately.

    See RECOVERY_MUST_PRODUCE_MIN. These are dusk/low-light hunting episodes
    where the MPPT releases the array to open circuit; counting them as
    recoveries put a 28-minute artifact at the top of the recovery
    distribution, which is what the 29-minute boundary was resting on.
    """
    idx = {r[0]: r[3] for r in rows}          # utc -> solar_w
    order = sorted(idx)
    for e in list(eps):
        if e["clamped"]:
            continue
        end_utc = e["ended"] - dt.timedelta(hours=LOCAL_OFFSET_H)
        if end_utc not in idx:
            continue
        i = order.index(end_utc)
        run = 0
        for t in order[i:]:
            if idx[t] > 0:
                run += 1
            else:
                break
        e["produced_min"] = run
        if run < RECOVERY_MUST_PRODUCE_MIN:
            e["artifact"] = True


# HOW LONG THE CLAMP ACTUALLY HELD, added 2026-08-13.
#
# The outcome has no persistence requirement: one 60 s bucket whose MEAN dips
# into the band closes an episode as "clamped". Measured across the table, the
# in-band run after each declared clamp is
#
#   2, 2, 3, 5, 6, 9, 9, 11, 12, 13, 17, 23, 29, 42, 44, 46, 141, 218, 249, 336
#
# Seventeen are real; three (08-06 15:31, 08-08 12:08, 08-12 08:05) are touches
# of <=3 min where the array left the band on its own with no guard fix
# anywhere near — checked, because a short run can also mean the guard simply
# fixed it fast, and for seven episodes that is exactly what it means.
#
# NOT reclassified. A duration threshold cannot separate these: the shortest
# GENUINE clamps ran 6 and 9 minutes before the guard truncated them, so any
# cut that removes the 2-3 minute touches also removes real ones. Doing it
# properly needs the guard-fix join, which is a judgement call about
# intermittent clamps and a bigger change than this column.
#
# So the number is simply SHOWN. A reader can see that a "clamp" held for two
# minutes and discount it, which is all the earlier silence prevented.
def _annotate_held(eps: list[dict], rows: list) -> None:
    idx = {r[0]: (r[1], r[2]) for r in rows}
    order = sorted(idx)
    for e in eps:
        if not e["clamped"]:
            continue
        end_utc = e["ended"] - dt.timedelta(hours=LOCAL_OFFSET_H)
        if end_utc not in idx:
            continue
        i = order.index(end_utc)
        run = 0
        for t in order[i:]:
            if is_clamped(*idx[t]):
                run += 1
            else:
                break
        e["held_min"] = run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=300)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    eps = episodes(fetch(a.url, a.hours, a.source))
    if not eps:
        print("no crossings in window")
        return 1

    print("| crossing (local) | outcome at | minutes | Wh in between | held |")
    print("|---|---|---|---|---|")
    for e in eps:
        tag = "" if e["clamped"] else " **recovered**"
        h = e.get("held_min")
        held = "—" if h is None else (f"{h} min" + (" **touch**" if h <= 3 else ""))
        print(f"| {e['crossed']:%m-%d %H:%M} | {e['ended']:%H:%M} | "
              f"{e['minutes']} | {e['wh']} | {held} |{tag}")

    arts = [e for e in eps if e.get("artifact")]
    eps = [e for e in eps if not e.get("artifact")]
    mins = [e["minutes"] for e in eps if e["clamped"]]
    rec = len(eps) - len(mins)
    if not mins:
        # No clamps in the window. This used to crash on min() of an empty
        # list, which never happened while every crossing clamped — and then
        # 2026-08-14 the early-bounce test PREVENTED the day's clamp and the
        # script died on its own success. A summariser that cannot describe a
        # good day is not a summariser.
        print(f"\n**0 of {len(eps)} crossings ended in a clamp; "
              f"{rec} recovered.** No clamp in this window.")
        return 0
    print(f"\n**{len(mins)} of {len(eps)} crossings ended in a clamp"
          f"{f'; {rec} recovered' if rec else '; none recovered'}.** "
          f"Time to clamp: min {min(mins)}, median "
          f"{round(statistics.median(mins))}, max {max(mins)} minutes.")
    if arts:
        print(f"\n**{len(arts)} episode(s) EXCLUDED as open-circuit artifacts** "
              f"— declared a recovery but stopped producing within "
              f"{RECOVERY_MUST_PRODUCE_MIN} min (the MPPT releasing the array "
              f"to Voc in low light, not a re-acquire):")
        for e in arts:
            print(f"  - {e['crossed']:%m-%d %H:%M} -> {e['ended']:%H:%M} "
                  f"({e['minutes']} min), produced {e.get('produced_min', 0)} "
                  f"min afterwards")
    touches = [e for e in eps if e["clamped"] and (e.get("held_min") or 99) <= 3]
    if touches:
        when = ", ".join(f"{e['crossed']:%m-%d %H:%M}" for e in touches)
        print(f"\n**{len(touches)} of {len(mins)} 'clamps' held the band for "
              f"<=3 min** ({when}) — the outcome has no persistence "
              f"requirement, so a momentary band touch closes an episode. "
              f"Not reclassified; see _annotate_held for why a duration "
              f"threshold cannot separate these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
