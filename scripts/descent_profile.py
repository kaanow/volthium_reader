#!/usr/bin/env python3
"""Profile HOW each 45 V crossing descends, not just how long it takes.
Runs OFF the Pi (CLAUDE.md #1).

`cliff_table.py` answers "how long from crossing to outcome". It cannot
distinguish an array walking down its own IV curve under load from one that
was already sitting near open circuit and got yanked down. Those look identical
in a duration column and are not the same event.

The "second, fast path into the clamp" was recorded on 2026-08-10 from a single
episode read by hand — 100 V to 28 V in about two minutes. n=1, and the operator
was right to distrust it. This script exists so that claim is regenerable
instead of remembered.

    python3 scripts/descent_profile.py [--hours 400] [--url https://volts.alti2.de]

What it adds per episode, all from the same 60 s buckets cliff_table uses:

  dV/dt   steepest one-bucket fall in the 15 min before the crossing through
          5 min after. Signed, so more negative is faster.
  preV    highest pv_v in the 20..5 min before the crossing — where the array
          was sitting BEFORE it started down.
  preW    highest solar_w over the same window — how hard it was working there.
  stage   the MPPT's own charge stage at the crossing, from the chg_stage
          events. This is the device telling you whether it was loading the
          array (bulk/absorb) or had stopped (float/not_charging). Only
          available for the span the events API still holds.

WHAT THE DATA SAYS (regenerate before quoting — that is the whole point):

The separator is not speed, it is WHERE THE ARRAY STARTED. Every episode that
began on the loaded part of the curve (preV <= ~71 V) descends at 0.3-5.2 V/min.
The two that began near open circuit (preV >= ~92 V, making almost nothing)
descend an order of magnitude faster. The gap between the two groups in preV is
wide and empty, which is what makes it look like a real split rather than a
tail.

Two consequences, both of which cut against how this was first written down:

  1. The table shows ONE near-Voc episode, and it is not the one that was
     noticed. 2026-08-02 19:09 is the only one that survives as an episode, and
     it RECOVERED. The 2026-08-10 17:13 collapse — the one this whole line of
     enquiry started from — turned out to be a phantom episode opened inside an
     unbroken latch by band jitter, and it is gone since the re-arm fix in
     cliff_table.py.
  2. But the 08-10 collapse itself is REAL, and the table structurally cannot
     represent it. The array fell 87 -> 31 V between 17:10 and 17:11 and was
     clamped in the same minute, so the episode is shorter than
     MIN_EPISODE_MIN and is discarded. Confirmed independently by the Pi's own
     1 Hz detector: mppt_latched 17:29:58, clamped_s 601, no unlatch until the
     guard bounced it at 17:33:54.

So the phenomenon is n=2 in the DATA and n=1 in the TABLE, and the one the
table keeps is the one that recovered. A metric blind to exactly the event it
is being used to characterise is the recurring failure here, not an exception:
the near-Voc descent is fast BECAUSE it is near-Voc, and being fast is what
makes it fall through a minimum-duration filter.

It is therefore NOT established as "a path into the clamp". One recovered in
six minutes; the other clamped. Two points, opposite outcomes.

Why a near-Voc start would behave differently at all: at open circuit the array
current is ~0, so the MPPT has to re-acquire from a standing start rather than
track a moving point. That is also exactly the regime where a current-sensor
OFFSET would dominate the reported power (docs/xanbus-unknowns.md), so these
episodes are the interesting ones for that hypothesis, not the noisy ones.

Caveat kept deliberately: both fast episodes are late in the day. With n=2 that
could be the actual condition rather than the near-Voc start. Do not promote
this to a rule on two points.
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

from cliff_table import BUCKET_S, episodes, fetch   # noqa: E402
from solar_geometry import sun_elevation_deg        # noqa: E402

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7          # matches cliff_table; site is PDT in the window

# The empty gap in preV between the two groups. Not a tuned threshold — it is
# reported so the split can be checked, and print_table shows every preV so a
# reader can see whether the gap is still there.
NEAR_VOC_V = 85.0


def fetch_stages(url: str, source: str, since: dt.datetime) -> list[tuple]:
    """MPPT chg_stage transitions. The events API caps at 2000 rows and has no
    offset, so this walks forward by timestamp and stops when it stops learning
    anything. Coverage is therefore partial for older episodes — reported as
    "(no data)" rather than guessed at."""
    out: dict[tuple, dict] = {}
    cur = since
    for _ in range(30):
        q = (f"{url}/api/xanbus_events?source_id={source}&limit=2000"
             f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        with urllib.request.urlopen(q, timeout=90) as r:
            got = json.load(r).get("events", [])
        if not got:
            break
        new = 0
        for e in got:
            k = (e["ts"], e["event"], json.dumps(e.get("data"), sort_keys=True))
            if k not in out:
                out[k] = e
                new += 1
        mx = max(e["ts"] for e in got)
        if not new or mx <= f"{cur:%Y-%m-%dT%H:%M:%SZ}":
            break
        cur = dt.datetime.strptime(mx[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return sorted(
        (dt.datetime.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC),
         e["data"].get("to"))
        for e in out.values()
        if e["event"] == "chg_stage" and (e.get("data") or {}).get("node") == "mppt"
    )


def profile(series: list[dict], stages: list[tuple]) -> list[dict]:
    pts: dict[dt.datetime, tuple[float, float]] = {}
    for r in series:
        if r.get("pv_v") is None:
            continue
        t = dt.datetime.strptime(r["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        pts[t] = (r["pv_v"], r.get("solar_w") or 0.0)
    ordered = sorted(pts.items())

    def stage_at(u: dt.datetime) -> str:
        prior = [s for s in stages if s[0] <= u]
        return prior[-1][1] if prior else "(no data)"

    out = []
    for e in episodes(series):
        u = e["crossed"].replace(tzinfo=UTC) - dt.timedelta(hours=LOCAL_OFFSET_H)
        win = [(t, v) for t, (v, _) in ordered
               if u - dt.timedelta(minutes=15) <= t <= u + dt.timedelta(minutes=5)]
        rate = 0.0
        for (t0, v0), (t1, v1) in zip(win, win[1:]):
            m = (t1 - t0).total_seconds() / 60
            if m > 0:
                rate = min(rate, (v1 - v0) / m)
        pre = [(v, w) for t, (v, w) in ordered
               if u - dt.timedelta(minutes=20) <= t <= u - dt.timedelta(minutes=5)]
        out.append({
            **e,
            "dvdt": rate,
            "pre_v": max((v for v, _ in pre), default=float("nan")),
            "pre_w": max((w for _, w in pre), default=float("nan")),
            "stage": stage_at(u),
            "sun": sun_elevation_deg(u.timestamp()),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=400)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    series = fetch(a.url, a.hours, a.source)
    since = dt.datetime.now(UTC) - dt.timedelta(hours=a.hours)
    rows = profile(series, fetch_stages(a.url, a.source, since))
    if not rows:
        print("no crossings in window")
        return 1

    print(f"bucket={BUCKET_S}s  near-Voc split at preV >= {NEAR_VOC_V} V\n")
    print("| crossing | out | min | outcome | dV/dt V/min | preV | preW | sun | stage |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['crossed']:%m-%d %H:%M} | {r['ended']:%H:%M} | {r['minutes']} "
              f"| {'clamp' if r['clamped'] else '**recovered**'} | {r['dvdt']:.1f} "
              f"| {r['pre_v']:.1f} | {r['pre_w']:.0f} | {r['sun']:.0f} | {r['stage']} |")

    fast = [r for r in rows if r["pre_v"] >= NEAR_VOC_V]
    slow = [r for r in rows if r["pre_v"] < NEAR_VOC_V]
    print(f"\n**{len(fast)} near-Voc starts, {len(slow)} loaded starts.**")
    for name, grp in (("near-Voc", fast), ("loaded", slow)):
        if not grp:
            continue
        r = [g["dvdt"] for g in grp]
        c = sum(1 for g in grp if g["clamped"])
        print(f"- {name}: dV/dt median {statistics.median(r):.1f}, "
              f"range {min(r):.1f}..{max(r):.1f} V/min; {c} of {len(grp)} clamped")
    if fast and slow:
        gap_lo = max(g["pre_v"] for g in slow)
        gap_hi = min(g["pre_v"] for g in fast)
        print(f"- preV gap between the groups: {gap_lo:.1f} .. {gap_hi:.1f} V "
              f"({'empty — a real split' if gap_hi > gap_lo else 'OVERLAPS — not a split'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
