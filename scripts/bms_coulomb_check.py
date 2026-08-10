#!/usr/bin/env python3
"""Check the BMS against its OWN coulomb counter. Runs OFF the Pi.

The direct analogue of the test that settled the MPPT's internal consistency
(docs/xanbus-unknowns.md #6): integrate the device's reported instantaneous
current and compare against the device's own accumulator. Same instrument on
both sides, so no cross-meter arithmetic — the trap this project keeps falling
into.

The MPPT passed that test at 0.99. The BMS does not: its `remaining_ah`
counter moves ~12% further than integrating `i_a`/`i_b` says it should, on
both battery units, in both directions.

Why the direction matters. A coulombic-efficiency correction — normal, and
what you would expect a decent BMS to apply — is ASYMMETRIC: the counter
should fall faster than the integral while discharging and rise SLOWER while
charging, because some charge is lost to heat. Measuring both directions is
therefore the whole experiment. Observed 2026-08-10:

    discharge   0.875  0.875  0.875  0.871
    charge      0.891  0.890  0.889  0.889

Larger in magnitude both ways, so it is a scale factor and not an efficiency
term. (The ~1.6% gap between the two directions is about the right size to be
genuine coulombic efficiency sitting on top of it.)

What this does NOT establish is which side is wrong — the reported current or
the accumulator. It does bound how far `pack_p` can be trusted in absolute
terms, which matters because "trust the BMS shunts for absolute DC power" is
the standing rule this project navigates by (#11).

Two controls are built in, because both would fake this result:
  - sampling gaps, which would bias the integral low — reported, and must be
    zero for the number to mean anything;
  - `remaining_ah` being nothing but SOC rescaled, in which case it is not an
    independent accumulator at all — checked by counting distinct
    remaining_ah/soc ratios.

    python3 scripts/bms_coulomb_check.py --start 2026-08-10T04:30 --hours 7
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request

MAX_SAMPLE_GAP_S = 60.0   # beyond this we cannot honestly interpolate current


def fetch(url: str, source: str, start: dt.datetime,
          end: dt.datetime) -> list[dict]:
    rows: list[dict] = []
    cur = start
    while cur < end:
        q = (f"{url}/api/readings?source_id={source}&limit=5000"
             f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        with urllib.request.urlopen(q, timeout=90) as r:
            got = json.load(r)
        got = got if isinstance(got, list) else got.get("readings", [])
        got = [x for x in got if x["ts"][:19] < f"{end:%Y-%m-%dT%H:%M:%S}"]
        if not got:
            break
        rows += got
        nxt = dt.datetime.strptime(max(x["ts"] for x in got)[:19],
                                   "%Y-%m-%dT%H:%M:%S").replace(
                                       tzinfo=dt.timezone.utc)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    rows.sort(key=lambda x: x["ts"])
    return rows


def integrate(rows: list[dict], batt: str) -> tuple[float, float, float]:
    """Trapezoidal Ah, plus the coverage stats that could fake the result."""
    ah = 0.0
    prev = None
    covered = 0.0
    worst = 0.0
    for x in rows:
        t = dt.datetime.strptime(x["ts"][:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        i = x.get(f"i_{batt}")
        if i is None:
            continue
        if prev is not None:
            gap = t - prev[0]
            worst = max(worst, gap)
            if 0 < gap < MAX_SAMPLE_GAP_S:
                ah += (i + prev[1]) / 2 * gap / 3600.0
                covered += gap
        prev = (t, i)
    return ah, covered, worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="UTC, YYYY-MM-DDTHH:MM")
    ap.add_argument("--hours", type=float, default=7.0)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    start = dt.datetime.fromisoformat(a.start).replace(tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(hours=a.hours)
    rows = fetch(a.url, a.source, start, end)
    if len(rows) < 100:
        print(f"only {len(rows)} readings in the window")
        return 1

    span = (dt.datetime.strptime(rows[-1]["ts"][:19], "%Y-%m-%dT%H:%M:%S")
            - dt.datetime.strptime(rows[0]["ts"][:19],
                                   "%Y-%m-%dT%H:%M:%S")).total_seconds()
    print(f"n={len(rows)}  span={span:.0f}s")

    for batt in ("a", "b"):
        ah, covered, worst = integrate(rows, batt)
        r0 = rows[0].get(f"remaining_ah_{batt}")
        r1 = rows[-1].get(f"remaining_ah_{batt}")
        if r0 is None or r1 is None:
            continue
        delta = r1 - r0
        # Control 1: a gap makes the integral small and fakes a low ratio.
        loss = (span - covered) / span * 100 if span else 0
        # Control 2: if remaining_ah is only SOC rescaled it is not an
        # independent accumulator and none of this means anything.
        ratios = {round(x[f"remaining_ah_{batt}"] / x[f"soc_{batt}"], 4)
                  for x in rows
                  if x.get(f"soc_{batt}") and x.get(f"remaining_ah_{batt}")}
        print(f"\n  battery {batt.upper()}")
        print(f"    integral of reported current : {ah:+9.3f} Ah")
        print(f"    remaining_ah {r0:7.2f} -> {r1:7.2f} : {delta:+9.3f} Ah")
        if abs(delta) > 0.5:
            print(f"    ratio integral/counter       : {ah / delta:9.3f}")
        print(f"    uncovered time (gap bias)    : {loss:8.2f}%  "
              f"worst gap {worst:.0f}s")
        print(f"    remaining_ah/soc distinct    : {len(ratios):4d}  "
              f"({'independent counter' if len(ratios) > 5 else 'JUST SOC RESCALED — result is meaningless'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
