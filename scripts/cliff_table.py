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
                if mins >= MIN_EPISODE_MIN:
                    out.append({"crossed": start, "ended": local,
                                "minutes": mins, "wh": round(wh),
                                "clamped": clamped})
                start = None
                armed = not clamped    # a clamp needs a fresh climb to re-arm

        if pv >= ARM_V and not clamped:
            armed = True
        if armed and start is None and pv < CROSS_V and not clamped:
            start, wh = local, 0.0
    return out


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

    print("| crossing (local) | outcome at | minutes | Wh in between |")
    print("|---|---|---|---|")
    for e in eps:
        tag = "" if e["clamped"] else " **recovered**"
        print(f"| {e['crossed']:%m-%d %H:%M} | {e['ended']:%H:%M} | "
              f"{e['minutes']} | {e['wh']} |{tag}")

    mins = [e["minutes"] for e in eps if e["clamped"]]
    rec = len(eps) - len(mins)
    print(f"\n**{len(mins)} of {len(eps)} crossings ended in a clamp"
          f"{f'; {rec} recovered' if rec else '; none recovered'}.** "
          f"Time to clamp: min {min(mins)}, median "
          f"{round(statistics.median(mins))}, max {max(mins)} minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
