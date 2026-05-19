"""Validate the advisor's projected_low_soc against the empirical
morning low (= soc_avg_at_net_positive from solar_onset.csv).

Sister module to `projection_accuracy.py`, which validates the
advisor's predicted **sunrise** SOC. This module validates a
different field of the same projection: `projected_low_soc` —
what the advisor thought the minimum SOC over the next 24 h
would be.

Empirically the next-24 h low is the morning trough: the pack
discharges overnight, reaches a floor around dawn, then climbs
back up as solar arrives. The solar_onset cascade captures the
moment net charging begins (`first_net_positive_iso`), and the
SOC at that moment is essentially the day's curve-bottom.

For each projection_log entry P with `sunrise_iso` on day D:
    1. Look up solar_onset[D] (the row for that day)
    2. Skip if the row is missing, has no `first_net_positive_iso`
       yet, or its target day is still in the future
    3. error = solar_onset.soc_avg_at_net_positive
              − P.projected_low_soc
       (positive = pack overshot the projected floor; negative =
        pack undershot, model was too optimistic)

The horizon = (first_net_positive_iso − projection_ts) in minutes
— how far ahead the projection was made. Bucketed identically to
projection_accuracy so the two views read symmetrically.

CLI:
    python scripts/low_soc_accuracy.py            # full table
    python scripts/low_soc_accuracy.py --by-horizon
    python scripts/low_soc_accuracy.py --tail 7
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import projection_log as projection_log_mod  # noqa: E402
import solar_onset as solar_onset_mod  # noqa: E402

# Reuse projection_accuracy's bucket definitions so the by-horizon
# views read identically (operator can compare bucket-for-bucket).
import projection_accuracy as projection_accuracy_mod  # noqa: E402
HORIZON_BUCKETS = projection_accuracy_mod.HORIZON_BUCKETS


@dataclass
class LowSocAccuracyRecord:
    """One projection's matched morning-low outcome."""
    projection_ts: str             # when the projection was MADE
    target_date: str               # ISO date of the morning being validated
    projected_low_soc: float
    actual_low_soc: float          # solar_onset.soc_avg_at_net_positive
    error_pct_points: float        # actual − projected
    solar_model_coefficient: float
    first_net_positive_iso: str    # the moment we're validating against
    horizon_min: float             # first_net_positive − projection_ts


def _date_of(sunrise_iso: str) -> Optional[str]:
    """Return the YYYY-MM-DD portion of an ISO timestamp, or None."""
    if not sunrise_iso or len(sunrise_iso) < 10:
        return None
    return sunrise_iso[:10]


def compute_accuracy_records(
    projection_entries: Iterable[projection_log_mod.LogEntry],
    onset_records: Iterable[solar_onset_mod.SolarOnsetRecord],
    now: Optional[datetime] = None,
) -> list[LowSocAccuracyRecord]:
    """For each projection entry whose target day has a fully-
    resolved solar_onset row (i.e. `first_net_positive_iso` is
    populated), produce a LowSocAccuracyRecord. Otherwise skip.

    `now` defaults to datetime.now() — used to gate future-target
    projections (don't validate ones whose target day hasn't
    happened yet)."""
    if now is None:
        now = datetime.now()
    # Index solar_onset by date for O(1) lookup
    onset_by_date = {r.date: r for r in onset_records
                     if r.first_net_positive_iso is not None
                     and r.soc_avg_at_net_positive is not None}
    out: list[LowSocAccuracyRecord] = []
    for e in projection_entries:
        target_date = _date_of(e.sunrise_iso)
        if target_date is None:
            continue
        onset = onset_by_date.get(target_date)
        if onset is None:
            continue
        # Sanity: only validate if the projection was MADE before
        # the net-positive moment. A projection made AFTER first_
        # net_positive is just recording history, not predicting.
        try:
            proj_dt = datetime.fromisoformat(e.ts)
            np_dt = datetime.fromisoformat(onset.first_net_positive_iso)
        except Exception:
            continue
        if proj_dt > np_dt:
            continue
        if np_dt > now:
            # Future net-positive — shouldn't happen if onset row is
            # complete, but defensive.
            continue
        horizon_min = max(0.0, (np_dt - proj_dt).total_seconds() / 60.0)
        out.append(LowSocAccuracyRecord(
            projection_ts=e.ts,
            target_date=target_date,
            projected_low_soc=e.projected_low_soc,
            actual_low_soc=onset.soc_avg_at_net_positive,
            error_pct_points=onset.soc_avg_at_net_positive - e.projected_low_soc,
            solar_model_coefficient=e.solar_model_coefficient,
            first_net_positive_iso=onset.first_net_positive_iso,
            horizon_min=horizon_min,
        ))
    return out


def summarize(records: list[LowSocAccuracyRecord]) -> dict:
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


def summarize_by_horizon(records: list[LowSocAccuracyRecord]) -> list[dict]:
    """Bucket records by lead-time and summarise each bucket. Same
    buckets as projection_accuracy so the two views read
    symmetrically."""
    out: list[dict] = []
    for label, lo, hi in HORIZON_BUCKETS:
        bucket = [r for r in records if lo <= r.horizon_min < hi]
        if not bucket:
            continue
        s = summarize(bucket)
        s["bucket"] = label
        s["lo_min"] = lo
        s["hi_min"] = hi if hi != math.inf else None
        out.append(s)
    return out


def pretty_print(records: list[LowSocAccuracyRecord],
                 tail: Optional[int] = None) -> None:
    if not records:
        print("(no validatable low-SOC projections yet — wait for "
              "a day's solar_onset to fully resolve)")
        return
    if tail:
        records = records[-tail:]
    print("=== Low-SOC accuracy: projected_low_soc vs actual morning low ===")
    print(f"{'made_at':<19}  {'target':<11}  {'proj':>5}  "
          f"{'actual':>6}  {'err':>5}  {'coef':>5}")
    print("-" * 64)
    for r in records:
        sign = "+" if r.error_pct_points >= 0 else "−"
        print(f"{r.projection_ts:<19}  {r.target_date:<11}  "
              f"{r.projected_low_soc:5.1f}  "
              f"{r.actual_low_soc:6.1f}  "
              f"{sign}{abs(r.error_pct_points):4.1f}  "
              f"{r.solar_model_coefficient:.3f}")
    print()
    s = summarize(records)
    print(f"summary: n={s['n']}, mean_error={s['mean_error']:+.2f} pp, "
          f"mean_abs={s['mean_abs_error']:.2f}, "
          f"RMS={s['rms_error']:.2f}, "
          f"range [{s['min_error']:+.2f} .. {s['max_error']:+.2f}]")


def pretty_print_by_horizon(records: list[LowSocAccuracyRecord]) -> None:
    if not records:
        print("(no validatable low-SOC projections yet)")
        return
    by_h = summarize_by_horizon(records)
    if not by_h:
        print("(no horizon buckets matched)")
        return
    print("=== Low-SOC accuracy by lead-time horizon ===")
    print(f"{'horizon':<8}  {'n':>3}  {'mean':>6}  {'abs':>5}  "
          f"{'rms':>5}  {'min':>5}  {'max':>5}")
    print("-" * 50)
    for s in by_h:
        print(f"{s['bucket']:<8}  {s['n']:>3}  "
              f"{s['mean_error']:+6.2f}  "
              f"{s['mean_abs_error']:5.2f}  "
              f"{s['rms_error']:5.2f}  "
              f"{s['min_error']:+5.2f}  "
              f"{s['max_error']:+5.2f}")
    print()
    print("legend: mean/min/max are signed errors (actual − projected, pp);")
    print("        abs = mean |error|; rms = root-mean-square.")
    print("        Bias signal: negative mean → advisor's floor was too")
    print("        OPTIMISTIC (predicted higher SOC than reality).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=None,
                    help="only show the most-recent N records")
    ap.add_argument("--by-horizon", action="store_true",
                    help="show the per-lead-time-horizon breakdown")
    args = ap.parse_args()

    projections = projection_log_mod.read_log()
    onsets = solar_onset_mod.read_log()
    records = compute_accuracy_records(projections, onsets)
    if args.by_horizon:
        pretty_print_by_horizon(records)
    else:
        pretty_print(records, tail=args.tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
