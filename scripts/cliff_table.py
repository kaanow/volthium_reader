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
     recovery back above 48 V. Whichever comes first ends the episode.
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

ARM_V = 48.0        # must get back up here before another crossing counts
CROSS_V = 45.0      # the cliff itself
LOCAL_OFFSET_H = -7  # site is America/Vancouver; PDT during the study window


def fetch(url: str, hours: int, source: str) -> list[dict]:
    q = f"{url}/api/solar/series?source_id={source}&hours={hours}&bucket_s=300"
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
        if pv >= ARM_V and not clamped:
            armed, start = True, None
        if armed and start is None and pv < CROSS_V and not clamped:
            start, wh = local, 0.0
        if start is None:
            continue
        wh += sw * 300 / 3600.0
        if clamped or pv >= ARM_V:
            out.append({"crossed": start, "ended": local,
                        "minutes": round((local - start).total_seconds() / 60),
                        "wh": round(wh), "clamped": clamped})
            start = None
            if clamped:
                armed = False
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
