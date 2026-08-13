#!/usr/bin/env python3
"""Did the 28.0 V bulk/absorb ceiling reduce cell imbalance? Runs OFF the Pi.

Task #44, reopened 2026-08-11 after the original closure failed on four counts:
its own pre-registered overturn condition was met the next day; the statistic
was a max-of-one-sample; the change date was wrong by three days; and `dv_b`
never moved, so the whole thing rested on one cell in one pack.

This is the redo, and the criterion below was written and committed BEFORE the
script was run, because the previous answer came from choosing a comparison
after seeing the data.

    python3 scripts/imbalance_ceiling.py [--from 2026-07-30] [--to 2026-08-13]

METHOD, fixed in advance:

  - Split at **2026-08-05 13:10 local**, when the device's own reported charge
    target stepped. NOT 08-08, which is what the original used and which
    nothing actually happened on.
  - Compare only samples with `soc_a` >= 100. The cliff never engages below the
    top of charge, so days that did not get there say nothing either way and
    are excluded — but the count of such days is REPORTED, not hidden.
  - Statistic is DISTRIBUTIONAL: median and p95 of `delta_v_a` while at SOC
    100, pooled per period, plus the per-day spread so "is the shift bigger
    than the noise" can be answered. Peak is printed alongside purely to show
    how badly it misleads; it is not the statistic.
  - `dv_b` computed identically. If only pack A moves, that is reported as a
    limitation of the finding, not omitted.

FALSIFICATION, stated before running:

  The claim "the ceiling reduced imbalance" is NOT supported unless the
  post-change p95 of `delta_v_a` at SOC 100 is lower than the pre-change p95 by
  **more than the larger of the two periods' day-to-day spreads** (max minus
  min of the per-day p95 within a period). A shift smaller than the noise
  between days of the same period is not evidence.

  If fewer than 2 qualifying days fall on either side, the answer is NOT
  ENOUGH DATA and the task stays open. Saying that is a valid outcome.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import urllib.request

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7
CHANGE_LOCAL = dt.datetime(2026, 8, 5, 13, 10)   # device-reported target step
SOC_FULL = 100


def fetch_day(url: str, source: str, day: dt.date) -> list[dict]:
    start = dt.datetime.combine(day, dt.time()).replace(tzinfo=UTC) \
        - dt.timedelta(hours=LOCAL_OFFSET_H)
    end = min(start + dt.timedelta(days=1), dt.datetime.now(UTC))
    rows, cur = [], start
    while cur < end:
        q = (f"{url}/api/readings?source_id={source}&limit=10000"
             f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        with urllib.request.urlopen(q, timeout=180) as r:
            g = json.load(r)
        g = g if isinstance(g, list) else g.get("readings", [])
        g = [x for x in g if x["ts"][:19] < f"{end:%Y-%m-%dT%H:%M:%S}"]
        if not g:
            break
        rows += g
        nxt = dt.datetime.strptime(max(x["ts"] for x in g)[:19],
                                   "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    return rows


def day_stats(rows: list[dict], field: str) -> dict | None:
    """delta_v while at SOC 100. `field` is delta_v_a or delta_v_b."""
    soc = "soc_a" if field.endswith("_a") else "soc_b"
    vals = [x[field] for x in rows
            if x.get(field) is not None and (x.get(soc) or 0) >= SOC_FULL]
    if len(vals) < 30:
        return None
    vals.sort()
    return {
        "n": len(vals),
        "minutes": len(vals) * 5 / 60,          # 5 s cadence
        "median": statistics.median(vals),
        "p95": vals[int(0.95 * (len(vals) - 1))],
        "peak": vals[-1],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="2026-07-30")
    ap.add_argument("--to", dest="d1", default="2026-08-13")
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    d0, d1 = dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1)
    per = {"before": [], "after": []}
    skipped = []
    print(f"split at {CHANGE_LOCAL:%Y-%m-%d %H:%M} local\n")
    print(f"{'day':<12}{'side':<8}{'min@100':>9}{'median':>9}{'p95':>8}{'peak':>8}"
          f"{'  |  dv_b median':>18}")
    d = d0
    while d <= d1:
        rows = fetch_day(a.url, a.source, d)
        sa = day_stats(rows, "delta_v_a")
        sb = day_stats(rows, "delta_v_b")
        if sa is None:
            skipped.append(str(d))
            d += dt.timedelta(days=1)
            continue
        side = "before" if dt.datetime.combine(d, dt.time(23, 59)) < CHANGE_LOCAL \
            else "after"
        # The change happened mid-day on 08-05; that day is neither.
        if d == CHANGE_LOCAL.date():
            side = "split-day"
        else:
            per[side].append((d, sa))
        print(f"{str(d):<12}{side:<8}{sa['minutes']:>9.0f}{sa['median']:>9.3f}"
              f"{sa['p95']:>8.3f}{sa['peak']:>8.3f}"
              f"{(sb['median'] if sb else float('nan')):>18.3f}")
        d += dt.timedelta(days=1)

    print(f"\ndays with <30 samples at SOC {SOC_FULL} (excluded, not hidden): "
          f"{len(skipped)}  {skipped}")

    for k in ("before", "after"):
        print(f"  {k}: {len(per[k])} qualifying days")
    if len(per["before"]) < 2 or len(per["after"]) < 2:
        print("\nVERDICT: NOT ENOUGH DATA — fewer than 2 qualifying days on a "
              "side. Task #44 stays open.")
        return 0

    out = {}
    for k in ("before", "after"):
        p95s = [s["p95"] for _, s in per[k]]
        out[k] = (statistics.median(p95s), max(p95s) - min(p95s))
        print(f"\n  {k}: p95 per day {[round(x,3) for x in p95s]}")
        print(f"        median-of-p95 {out[k][0]:.3f}, day-to-day spread {out[k][1]:.3f}")

    shift = out["before"][0] - out["after"][0]
    noise = max(out["before"][1], out["after"][1])
    print(f"\n  shift (before - after) = {shift:+.3f} V")
    print(f"  larger day-to-day spread = {noise:.3f} V")
    print("\nVERDICT: " + (
        "SUPPORTED — the drop exceeds the day-to-day spread."
        if shift > noise else
        "NOT SUPPORTED — the shift is smaller than the noise between days of "
        "the same period. Pre-registered criterion not met."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
