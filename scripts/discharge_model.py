"""First-pass discharge model — fits an Ah/h-consumed profile by
hour-of-day from captured pack.csv data.

This is the second building block of the generator advisor described
in `docs/generator_advisor/README.md`. The forward simulation needs an
expected discharge rate at each hour of the night; this script
estimates that rate empirically.

Approach:
    For each pack.csv sample where the pack is in discharging or idle
    state (i.e. NOT charging — solar / generator periods are explicitly
    excluded), bucket the sample by hour-of-day. Within each bucket,
    take the MEDIAN pack_current (robust against outliers like fridge
    pulses pulling individual samples high).

    The median across a discharging hour describes the "typical" rate,
    not the spike rate. To capture spikes, we also report 25th–75th
    percentile range.

    Output:
      - per-hour table (Ah/h consumed)
      - overall mean discharge rate
      - rough heuristic for "tonight's overnight Ah budget"

This rerun-it-as-data-grows pattern matches voltage_soc_calibration.py.
A real production model will eventually account for day-of-week,
season, and observed event patterns (heavy-load on/off). For now,
hour-of-day is a sensible first cut.

Usage:
    .venv/bin/python scripts/discharge_model.py
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Optional


@dataclass
class Sample:
    ts: datetime
    state: str
    pack_i: Optional[float]
    smoothed_i: Optional[float]


def _f(v: str) -> Optional[float]:
    if v in ("", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load(path: Path) -> list[Sample]:
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            out.append(Sample(
                ts=datetime.fromisoformat(r["ts"]),
                state=r["state"],
                pack_i=_f(r["pack_i"]),
                smoothed_i=_f(r["smoothed_i"]),
            ))
    return out


def fit(samples: list[Sample]) -> dict[int, dict]:
    """Return {hour_of_day: {n, median_i, p25, p75, sample_minutes}}."""
    by_hour: dict[int, list[float]] = defaultdict(list)
    for s in samples:
        if s.state not in ("discharging", "idle"):
            continue
        if s.pack_i is None:
            continue
        # Only consider net-consumption samples (current < 0 or essentially 0).
        # If we're charging at +1A in a "discharging" state due to EMA lag,
        # skip — would corrupt the consumption-rate fit.
        if s.pack_i > 0.5:
            continue
        by_hour[s.ts.hour].append(s.pack_i)

    result: dict[int, dict] = {}
    for hour in range(24):
        vals = by_hour.get(hour, [])
        if not vals:
            continue
        # Sort for percentiles
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        median = statistics.median(vals_sorted)
        p25 = vals_sorted[int(n * 0.25)]
        p75 = vals_sorted[int(n * 0.75)]
        # n samples × 10s polling = n * 10 / 60 minutes of observation
        sample_minutes = n * 10 / 60.0
        result[hour] = {
            "n": n,
            "median_i": median,
            "p25_i": p25,
            "p75_i": p75,
            "sample_minutes": sample_minutes,
        }
    return result


def project_overnight_ah(
    profile: dict[int, dict],
    start_hour: int,
    end_hour: int,
) -> Optional[float]:
    """Sum the per-hour |median current| × 1 h across the window.
    Returns expected Ah consumed from start_hour to end_hour (next day).
    """
    if start_hour == end_hour:
        return None
    hours = []
    h = start_hour
    while h != end_hour:
        hours.append(h)
        h = (h + 1) % 24
    total_ah = 0.0
    for h in hours:
        if h not in profile:
            # No data for this hour — fall back to overall median
            all_medians = [d["median_i"] for d in profile.values()]
            if not all_medians:
                return None
            fallback = statistics.median(all_medians)
            total_ah += abs(fallback)
        else:
            total_ah += abs(profile[h]["median_i"])
    return total_ah


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--start-hour", type=int, default=21,
                    help="hour-of-day to start the projection from (default 21:00)")
    ap.add_argument("--end-hour", type=int, default=7,
                    help="hour-of-day where solar typically kicks in (default 07:00)")
    args = ap.parse_args()

    samples = load(args.csv)
    if not samples:
        print("no data.")
        return 1
    print(f"\n=== discharge-rate fit from {args.csv.name} ===")
    print(f"  total samples:          {len(samples)}")
    consuming = sum(1 for s in samples if s.state in ("discharging", "idle"))
    print(f"  discharging/idle:       {consuming}")
    print()

    profile = fit(samples)
    if not profile:
        print("no discharging/idle data yet.")
        return 1

    print(f"  per-hour median discharge rate (A; negative = consuming):")
    print(f"  {'hr':>3} {'n':>5} {'mins':>6} {'p25':>6} {'med':>6} {'p75':>6}")
    for hour in sorted(profile.keys()):
        d = profile[hour]
        print(f"  {hour:>02}h  {d['n']:>4} {d['sample_minutes']:>5.0f} "
              f"{d['p25_i']:>+5.1f}A {d['median_i']:>+5.1f}A {d['p75_i']:>+5.1f}A")

    all_medians = [d["median_i"] for d in profile.values()]
    overall = statistics.median(all_medians)
    print(f"\n  overall median rate (across observed hours): {overall:+.2f} A")

    # Project an overnight-budget number from current window
    overnight_ah = project_overnight_ah(profile, args.start_hour, args.end_hour)
    if overnight_ah is not None:
        hours_span = ((args.end_hour - args.start_hour) % 24) or 24
        print(f"\n  projected overnight discharge from {args.start_hour:02d}h to {args.end_hour:02d}h")
        print(f"    span:        {hours_span} hours")
        print(f"    expected Ah: {overnight_ah:.1f}")
        print(f"    @ pack 215 Ah ≈ {overnight_ah / 215 * 100:.1f} % SOC drop")
    print()
    print("Caveats:")
    print("  - With < 24h of data the fit is dominated by recent hours")
    print("    and missing hours fall back to the overall median.")
    print("  - The fit ignores generator runs, sun-driven charging, and")
    print("    any state explicitly outside discharging/idle.")
    print("  - As more days accumulate, expect: 17-22h higher consumption")
    print("    (cabin active), 22-07h lower (overnight), 07-12h baseline")
    print("    rising, 12-17h often negative (solar covering load).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
