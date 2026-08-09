#!/usr/bin/env python3
"""Calibrate the DC meters against each other during float. Runs OFF the Pi.

Float with a full battery is the most useful regime on this system and it went
unused for weeks. When the MPPT is in float and `pack_p` sits at zero, the
battery is neither charging nor discharging, so an energy balance with no
battery term holds exactly:

    solar_w  ==  inverter draw + unmetered DC load (the fridge)

Every other comparison on this system has had at least two unknowns in it.
This one has one, and the fridge conveniently cycles on its own, which turns a
single equation into two and lets both terms be solved.

It is also the only measurement of the fridge by an instrument other than the
BMS. The published profile (75.8 W, 29.1%, 0.528 kWh/day) comes from an Otsu
split on `pack_p` — a good method, but a single instrument. The MPPT is fully
independent of the BMS shunts, so agreement between them means something that
two analyses of the same `pack_p` never could.

What it found on 2026-08-09 (n=170 min, median |pack_p| = 0.00 W):

    inverter draw, MPPT-measured    66.2 W
    inverter draw, BMS at night     81.0 W     (scripts/meter_offset.py)
    inverter draw, dc_w claims     113.7 W

Two independent instruments put the inverter's draw well below what its own
meter claims. `dc_w` is the outlier, by 40% against the BMS and 72% against
the MPPT — which is the strongest evidence yet on which meter is wrong
(docs/xanbus-unknowns.md #5, #11).

    python3 scripts/float_calibration.py [--hours 6]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import urllib.request

# Battery must be genuinely neutral for the balance to hold. 5 W is ~0.19 A at
# 27 V — tight enough that the battery term cannot hide either load, and loose
# enough to survive the BMS's own quantisation.
NEUTRAL_W = 5.0
MIN_PV_V = 60.0          # array tracking, not clamped and not dark
BMS_NIGHT_INVERTER_W = 81.0   # from scripts/meter_offset.py
BMS_OTSU_FRIDGE_W = 75.8      # published dc_load_profile figure


def _get(url: str, timeout: int = 90):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def collect(url: str, source: str, hours: int) -> list[tuple]:
    sol = {dt.datetime.strptime(r["bucket"], "%Y-%m-%dT%H:%M:%SZ"): r
           for r in _get(f"{url}/api/solar/series?hours={hours}&bucket_s=60")["series"]}
    if not sol:
        return []
    pack: dict = {}
    cur = min(sol)
    end = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    while cur < end:
        rows = _get(f"{url}/api/readings?source_id={source}&limit=5000"
                    f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        rows = rows if isinstance(rows, list) else rows.get("readings", [])
        if not rows:
            break
        for x in rows:
            t = dt.datetime.strptime(x["ts"][:19], "%Y-%m-%dT%H:%M:%S")
            pack.setdefault(t.replace(second=0), []).append(x.get("pack_p") or 0.0)
        nxt = dt.datetime.strptime(max(x["ts"] for x in rows)[:19],
                                   "%Y-%m-%dT%H:%M:%S")
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)

    pts = []
    for t, s in sorted(sol.items()):
        if t not in pack or (s.get("pv_v") or 0) < MIN_PV_V:
            continue
        pp = sum(pack[t]) / len(pack[t])
        if abs(pp) > NEUTRAL_W:
            continue
        pts.append((s["solar_w"], s.get("dc_w") or 0.0, pp))
    return pts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    pts = collect(a.url, a.source, a.hours)
    if len(pts) < 30:
        print(f"only {len(pts)} neutral-battery minutes in the last {a.hours}h "
              f"— needs a float period with a full battery")
        return 1

    print(f"n = {len(pts)} minutes with |pack_p| <= {NEUTRAL_W:.0f} W "
          f"(median |pack_p| = "
          f"{statistics.median(abs(p[2]) for p in pts):.2f} W)")

    # The load is strongly bimodal; split at the midpoint of the two clusters
    # rather than assuming a threshold.
    sw = sorted(p[0] for p in pts)
    gaps = [(sw[i + 1] - sw[i], (sw[i] + sw[i + 1]) / 2)
            for i in range(len(sw) - 1)]
    split = max(gaps)[1]
    off = [p for p in pts if p[0] < split]
    on = [p for p in pts if p[0] >= split]
    if not off or not on:
        print("load did not cycle in this window — cannot separate the fridge")
        return 1

    med = lambda g, i: statistics.median(x[i] for x in g)  # noqa: E731
    print(f"\nsplit at {split:.1f} W")
    print(f"{'mode':<12}{'n':>5}{'solar_W':>10}{'dc_w':>10}")
    print(f"{'fridge OFF':<12}{len(off):>5}{med(off, 0):>10.1f}{med(off, 1):>10.1f}")
    print(f"{'fridge ON':<12}{len(on):>5}{med(on, 0):>10.1f}{med(on, 1):>10.1f}")

    inv, fridge = med(off, 0), med(on, 0) - med(off, 0)
    print(f"\ndc_w change across the fridge step: {med(on, 1) - med(off, 1):+.1f} W"
          f"   (a DC load bypasses the inverter, so this should be ~0)")
    print("\nWith pack_p == 0, solar_w IS the total DC load:")
    print(f"  inverter draw, MPPT-measured  {inv:>7.1f} W")
    print(f"  inverter draw, BMS at night   {BMS_NIGHT_INVERTER_W:>7.1f} W")
    print(f"  inverter draw, dc_w claims    {med(off, 1):>7.1f} W  <-- outlier")
    print(f"\n  fridge, MPPT-measured         {fridge:>7.1f} W")
    print(f"  fridge, BMS Otsu (published)  {BMS_OTSU_FRIDGE_W:>7.1f} W")
    print(f"\n  MPPT/BMS ratio, inverter      {inv / BMS_NIGHT_INVERTER_W:>7.3f}")
    print(f"  MPPT/BMS ratio, fridge        {fridge / BMS_OTSU_FRIDGE_W:>7.3f}")
    print("\nThe two ratios are close but NOT equal, so the MPPT's under-report "
          "is\napproximately — not exactly — a single scale factor. Do not "
          "collapse it to one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
