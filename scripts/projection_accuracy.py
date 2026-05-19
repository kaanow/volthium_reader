"""Compute projection-vs-actual accuracy from the historical
projection_log entries + the recorded pack.csv truth.

Goal: when the advisor said "sunrise SOC will be 69 %" 8 hours
before sunrise, did it land? Over many days, this is the metric
that tells us whether the SolarModel + discharge_model + simulator
are well-calibrated, drifting, or biased.

For each row in data/projection_log.csv:
    1. parse the target sunrise_iso
    2. skip if that target time is still in the future
    3. find the closest pack.csv sample within ±30 min of the target
    4. compute actual_sunrise_soc = (soc_a + soc_b) / 2 at that sample
    5. error = actual_sunrise_soc − projected_sunrise_soc
       (positive = pack ended up HIGHER than predicted)

Outputs a per-row table + summary (count, mean error, mean abs
error, RMS error).

CLI:
    python scripts/projection_accuracy.py            # full table
    python scripts/projection_accuracy.py --tail 7   # last 7 days
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import projection_log as projection_log_mod  # noqa: E402


@dataclass
class AccuracyRecord:
    """One projection's matched actual outcome."""
    projection_ts: str               # when the projection was MADE
    sunrise_iso: str                 # the target time it predicted FOR
    projected_sunrise_soc: float
    actual_sunrise_soc: float
    error_pct_points: float          # actual − projected
    solar_model_coefficient: float
    sample_ts: str                   # the pack.csv sample we matched
    sample_offset_min: float         # |sample_ts − sunrise_iso| in minutes


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _load_pack_samples(pack_csv: Path) -> list[tuple[datetime, float]]:
    """Return [(ts, soc_avg), ...] for all pack samples with valid
    soc_a/soc_b. Sorted by ts ascending."""
    out: list[tuple[datetime, float]] = []
    if not pack_csv.exists():
        return out
    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            sa = _f(r.get("soc_a"))
            sb = _f(r.get("soc_b"))
            if sa is None or sb is None:
                continue
            out.append((ts, (sa + sb) / 2.0))
    out.sort(key=lambda p: p[0])
    return out


def _find_actual_at(samples: list[tuple[datetime, float]],
                    target: datetime,
                    tolerance_min: float = 30.0) -> Optional[tuple[datetime, float]]:
    """Binary-ish search for the pack sample closest in time to
    `target`. Returns (sample_ts, soc_avg) or None if no sample falls
    within `tolerance_min` minutes."""
    if not samples:
        return None
    # Linear scan is fine for our scale (a few thousand samples/day).
    # Could swap for bisect later if we ever cross 100k samples.
    best_ts: Optional[datetime] = None
    best_soc: Optional[float] = None
    best_delta: float = math.inf
    for ts, soc in samples:
        delta = abs((ts - target).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_ts = ts
            best_soc = soc
    if best_ts is None:
        return None
    if best_delta > tolerance_min * 60:
        return None
    return (best_ts, best_soc)


def compute_accuracy_records(
    projection_entries: Iterable[projection_log_mod.LogEntry],
    pack_samples: list[tuple[datetime, float]],
    now: Optional[datetime] = None,
    tolerance_min: float = 30.0,
) -> list[AccuracyRecord]:
    """For each projection entry whose sunrise_iso target time has
    already passed AND has a matching pack sample within tolerance,
    yield an AccuracyRecord."""
    if now is None:
        now = datetime.now()
    out: list[AccuracyRecord] = []
    for e in projection_entries:
        try:
            sr_target = datetime.fromisoformat(e.sunrise_iso)
        except Exception:
            continue
        # Future sunrise → not validatable yet
        if sr_target > now:
            continue
        match = _find_actual_at(pack_samples, sr_target, tolerance_min)
        if match is None:
            continue
        sample_ts, actual_soc = match
        sample_offset_min = abs((sample_ts - sr_target).total_seconds()) / 60.0
        out.append(AccuracyRecord(
            projection_ts=e.ts,
            sunrise_iso=e.sunrise_iso,
            projected_sunrise_soc=e.projected_sunrise_soc,
            actual_sunrise_soc=actual_soc,
            error_pct_points=actual_soc - e.projected_sunrise_soc,
            solar_model_coefficient=e.solar_model_coefficient,
            sample_ts=sample_ts.isoformat(timespec="minutes"),
            sample_offset_min=sample_offset_min,
        ))
    return out


def summarize(records: list[AccuracyRecord]) -> dict:
    """Aggregate stats across all accuracy records."""
    if not records:
        return {"n": 0}
    errors = [r.error_pct_points for r in records]
    abs_errors = [abs(e) for e in errors]
    return {
        "n":              len(records),
        "mean_error":     round(statistics.mean(errors), 2),
        "mean_abs_error": round(statistics.mean(abs_errors), 2),
        "median_error":   round(statistics.median(errors), 2),
        "rms_error":      round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2),
        "min_error":      round(min(errors), 2),
        "max_error":      round(max(errors), 2),
    }


def pretty_print(records: list[AccuracyRecord], tail: Optional[int] = None) -> None:
    if not records:
        print("(no validatable projections yet — wait for sunrise_iso targets to pass)")
        return
    if tail:
        records = records[-tail:]
    print("=== Projection accuracy: projected sunrise SOC vs actual ===")
    print(f"{'made_at':<19}  {'target':<16}  {'proj':>5}  "
          f"{'actual':>6}  {'err':>5}  coef")
    print("-" * 70)
    for r in records:
        sr = r.sunrise_iso[:16] if len(r.sunrise_iso) >= 16 else r.sunrise_iso
        sign = "+" if r.error_pct_points >= 0 else "−"
        print(f"{r.projection_ts:<19}  {sr:<16}  "
              f"{r.projected_sunrise_soc:5.1f}  "
              f"{r.actual_sunrise_soc:6.1f}  "
              f"{sign}{abs(r.error_pct_points):4.1f}  "
              f"{r.solar_model_coefficient:.3f}")
    print()
    s = summarize(records)
    print(f"summary: n={s['n']}, mean_error={s['mean_error']:+.2f} pp, "
          f"mean_abs={s['mean_abs_error']:.2f}, "
          f"RMS={s['rms_error']:.2f}, "
          f"range [{s['min_error']:+.2f} .. {s['max_error']:+.2f}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=None,
                    help="only show the most-recent N records")
    ap.add_argument("--pack-csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--tolerance-min", type=float, default=30.0,
                    help="how close (in minutes) a pack sample must be "
                         "to the sunrise target to count as a match")
    args = ap.parse_args()

    projections = projection_log_mod.read_log()
    pack_samples = _load_pack_samples(args.pack_csv)
    records = compute_accuracy_records(
        projections, pack_samples, tolerance_min=args.tolerance_min,
    )
    pretty_print(records, tail=args.tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
