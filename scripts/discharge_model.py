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


@dataclass
class LoadStats:
    """What the last load() actually managed to read.

    Exposed because a skip counter nobody can read is how this codebase has
    repeatedly turned a broken input into a quiet one — see the decoder's
    rejection counters, which were incremented and never surfaced.
    """
    rows: int = 0
    parsed: int = 0
    skipped_bad_ts: int = 0
    skipped_missing: int = 0
    nul_lines: int = 0

    @property
    def skipped(self) -> int:
        return self.skipped_bad_ts + self.skipped_missing


# Updated by every load(). Read it instead of assuming the file was clean.
LAST_LOAD = LoadStats()


def _count_nuls(lines):
    """Count NUL-bearing lines. Deliberately does NOT strip them.

    I first wrote this to strip NULs, on the belief that Python's csv module
    raises `_csv.Error: line contains NUL`. It does not — measured on 3.11,
    csv parses such a line happily and hands it on, which is exactly how the
    production failure surfaced as `ValueError: Invalid isoformat string` from
    fromisoformat rather than as a csv error. The test I wrote to pin the
    stripping behaviour is what disproved the premise.

    Stripping is also the wrong thing to want. The torn row is
    `<1753 NULs>2026-10-11T07:54:38-07:00`; remove the NULs and it becomes a
    VALID timestamp, so the row would be silently resurrected from damaged
    bytes with its other fields gone. Reconstructing data that was never
    written is worse than dropping it — a row destroyed by an unflushed
    reboot should be skipped and counted, not repaired by coincidence.

    So the NULs stay, the timestamp stays unparseable, the row is skipped, and
    the count tells the operator this file has PHYSICAL damage rather than a
    formatting typo.
    """
    for line in lines:
        if "\x00" in line:
            LAST_LOAD.nul_lines += 1
        yield line


def load(path: Path, *, quiet: bool = False) -> list[Sample]:
    """Parseable samples from a pack CSV. Unparseable rows are SKIPPED.

    WHY THIS TOLERATES DAMAGE. Until 2026-10-21 this did
    `datetime.fromisoformat(r["ts"])` with no guard, so a single malformed row
    raised and took down every caller. On 2026-10-11 the Pi rebooted and left
    a 1753-byte run of NUL bytes in data/pack.csv — buffered writes that were
    never flushed, ending mid-row at 2026-10-11T07:54:38. From that moment
    generator_advisor crashed on startup:

        ValueError: Invalid isoformat string: '\\x00\\x00\\x00...'

    It stayed broken for TEN DAYS and nothing noticed, because the failure was
    a traceback on a tool nobody was running rather than a wrong number on a
    page someone reads. The cloud record was complete the whole time — only
    the local copy was scuffed, and only 1753 bytes of a 77 MB file.

    Losing a handful of samples out of 296,000 changes no model. Losing every
    local analysis tool because of them is the actual damage, and it is the
    same crash-instead-of-degrade shape fixed elsewhere this month.

    Skips are COUNTED and, by default, reported to stderr — a silent skip
    would just move the failure from loud to invisible, which is worse. Read
    `discharge_model.LAST_LOAD` for the breakdown.

    Raises only when NOTHING parsed: a model fitted on zero samples is not a
    degraded answer, it is no answer, and the caller must not mistake it for
    one.
    """
    global LAST_LOAD
    LAST_LOAD = LoadStats()
    out: list[Sample] = []
    with path.open(errors="replace") as f:
        for r in csv.DictReader(_count_nuls(f)):
            LAST_LOAD.rows += 1
            ts_raw = (r.get("ts") or "").strip()
            if not ts_raw or r.get("state") is None:
                LAST_LOAD.skipped_missing += 1
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                LAST_LOAD.skipped_bad_ts += 1
                continue
            out.append(Sample(
                ts=ts,
                state=r["state"],
                pack_i=_f(r.get("pack_i") or ""),
                smoothed_i=_f(r.get("smoothed_i") or ""),
            ))
    LAST_LOAD.parsed = len(out)
    if LAST_LOAD.skipped and not quiet:
        print(f"[discharge_model] skipped {LAST_LOAD.skipped} unparseable row(s) "
              f"of {LAST_LOAD.rows} in {path} "
              f"(bad ts {LAST_LOAD.skipped_bad_ts}, missing fields "
              f"{LAST_LOAD.skipped_missing}, NUL-bearing lines "
              f"{LAST_LOAD.nul_lines})", file=sys.stderr)
    if not out:
        raise ValueError(
            f"{path}: no parseable rows out of {LAST_LOAD.rows} — refusing to "
            f"return an empty sample set that would fit a model on nothing")
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
