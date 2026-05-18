"""Offline analysis of accumulated pack.csv.

Prints a digest of what was captured: total duration, charge/discharge segments,
SOC range, observed currents, accuracy of the estimator's time-remaining vs what
actually happened, and any obvious anomalies.

Doesn't draw plots — terminal-friendly numbers only. (If we want plots later,
matplotlib is one pip away.)
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class Row:
    ts: datetime
    state: str
    pack_v: Optional[float]
    pack_i: Optional[float]
    pack_p: Optional[float]
    soc_a: Optional[float]
    soc_b: Optional[float]
    rem_ah_a: Optional[float]
    rem_ah_b: Optional[float]
    minutes_remaining: Optional[float]
    smoothed_i: Optional[float]

    @property
    def avg_rem_ah(self) -> Optional[float]:
        if self.rem_ah_a is None or self.rem_ah_b is None:
            return None
        return (self.rem_ah_a + self.rem_ah_b) / 2

    @property
    def soc(self) -> Optional[float]:
        if self.soc_a is None or self.soc_b is None:
            return None
        return (self.soc_a + self.soc_b) / 2

    @property
    def min_soc(self) -> Optional[float]:
        return None if self.soc_a is None or self.soc_b is None else min(self.soc_a, self.soc_b)

    @property
    def max_soc(self) -> Optional[float]:
        return None if self.soc_a is None or self.soc_b is None else max(self.soc_a, self.soc_b)


def _f(v: str) -> Optional[float]:
    if v in ("", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load(path: Path) -> list[Row]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            rows.append(Row(
                ts=datetime.fromisoformat(r["ts"]),
                state=r["state"],
                pack_v=_f(r["pack_v"]),
                pack_i=_f(r["pack_i"]),
                pack_p=_f(r["pack_p"]),
                soc_a=_f(r["soc_a"]),
                soc_b=_f(r["soc_b"]),
                rem_ah_a=_f(r["remaining_ah_a"]),
                rem_ah_b=_f(r["remaining_ah_b"]),
                minutes_remaining=_f(r["minutes_remaining"]),
                smoothed_i=_f(r["smoothed_i"]),
            ))
    return rows


@dataclass
class Segment:
    state: str
    start: datetime
    end: datetime
    start_soc: Optional[float]
    end_soc: Optional[float]
    avg_current: Optional[float]
    peak_current: Optional[float]
    samples: int

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def __str__(self) -> str:
        dur = self.duration
        h, rem = divmod(int(dur.total_seconds()), 3600)
        m = rem // 60
        soc_change = (
            f"  SOC {self.start_soc:.0f}→{self.end_soc:.0f}%"
            if self.start_soc is not None and self.end_soc is not None
            else ""
        )
        i_part = (
            f"  avg {self.avg_current:+.1f} A  peak {self.peak_current:+.1f} A"
            if self.avg_current is not None else ""
        )
        return (
            f"{self.start:%H:%M:%S}-{self.end:%H:%M:%S}  "
            f"{h}h {m:02d}m  {self.state:<11}{soc_change}{i_part}  "
            f"({self.samples} samples)"
        )


def segment(rows: list[Row], min_samples: int = 6) -> list[Segment]:
    """Group consecutive rows of the same state into segments.

    Short segments (< min_samples) are merged into their neighbors — keeps the
    output digestible when state flickers around the idle threshold.
    """
    if not rows:
        return []
    out: list[Segment] = []
    cur_state = rows[0].state
    cur_start = 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i].state != cur_state:
            block = rows[cur_start:i]
            if out and len(block) < min_samples and out[-1].state == block[0].state:
                # merge tiny continuation
                out[-1] = _make_seg(rows[cur_start - out[-1].samples:i], out[-1].state)
            else:
                out.append(_make_seg(block, cur_state))
            if i < len(rows):
                cur_state = rows[i].state
                cur_start = i
    return out


def _make_seg(rows: list[Row], state: str) -> Segment:
    currents = [r.pack_i for r in rows if r.pack_i is not None]
    return Segment(
        state=state,
        start=rows[0].ts,
        end=rows[-1].ts,
        start_soc=rows[0].soc,
        end_soc=rows[-1].soc,
        avg_current=statistics.mean(currents) if currents else None,
        peak_current=max(currents, key=abs) if currents else None,
        samples=len(rows),
    )


def ah_rate_by_current_bucket(
    rows: list[Row],
    window_s: float = 300.0,
) -> dict[str, list[tuple[float, float]]]:
    """Compute (dAh/hr observed, average current over the window) for every pair
    of samples ~window_s apart. Bucket by average current.

    Why a window: the BMS reports remaining_ah in integer-Ah steps. Adjacent
    10-second samples almost never tick. ~5-minute windows give 1-2 Ah of
    motion at typical currents — enough signal to be honest.
    """
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    i = 0
    while i < len(rows):
        # find a partner row at least window_s later
        j = i + 1
        while j < len(rows) and (rows[j].ts - rows[i].ts).total_seconds() < window_s:
            j += 1
        if j >= len(rows):
            break
        a, b = rows[i], rows[j]
        if a.avg_rem_ah is None or b.avg_rem_ah is None:
            i += 1
            continue
        # average current over the window — only valid if state didn't change
        states = {r.state for r in rows[i:j + 1]}
        if len(states) > 1:
            i = j  # skip across the state transition
            continue
        currents = [r.pack_i for r in rows[i:j + 1] if r.pack_i is not None]
        if not currents:
            i += 1
            continue
        avg_i = statistics.mean(currents)
        dt = (b.ts - a.ts).total_seconds()
        dah_per_hr = (b.avg_rem_ah - a.avg_rem_ah) / dt * 3600

        if abs(avg_i) < 1:    label = "idle (|I|<1A)"
        elif avg_i >= 30:     label = "fast charge (≥30A)"
        elif avg_i >= 10:     label = "moderate charge (10-30A)"
        elif avg_i >= 1:      label = "trickle charge (1-10A)"
        elif avg_i <= -10:    label = "heavy discharge (≤-10A)"
        elif avg_i <= -1:     label = "light discharge (-1 to -10A)"
        else:                 label = "other"
        buckets[label].append((dah_per_hr, avg_i))
        i = j  # non-overlapping windows so we don't double-count
    return buckets


def estimator_accuracy(rows: list[Row], horizon_min: float = 60.0) -> list[tuple[float, float]]:
    """For each (state, predicted-minutes) pair, find the actual time later when
    the prediction came true.

    Charging "true": max_soc hits 95 % (the FULL banner threshold, which is
    what the estimator actually targets — not 100 %).
    Discharging "true": min_soc hits 10 % (the floor).

    Returns a list of (predicted_minutes, actual_minutes) we can summarize.
    Filters:
      - state must be "charging" or "discharging" (NOT "full" — those have
        minutes_remaining = 0 by definition and would drag accuracy)
      - prediction must be ≤ horizon_min (so we don't chase predictions
        beyond what's plausibly verifiable in our window)
      - prediction must be > 0 (a 0-min prediction means we're already there)
    """
    pairs: list[tuple[float, float]] = []
    for i, r in enumerate(rows):
        if r.state not in ("charging", "discharging"):
            continue
        if r.minutes_remaining is None or r.minutes_remaining <= 0:
            continue
        if r.minutes_remaining > horizon_min:
            continue
        if r.state == "charging":
            target = 95.0
            soc_attr = "max_soc"
            cmp_op = lambda cur, t: cur >= t
        else:
            target = 10.0
            soc_attr = "min_soc"
            cmp_op = lambda cur, t: cur <= t
        # find first future row that crosses the target
        for j in range(i + 1, len(rows)):
            cur = getattr(rows[j], soc_attr)
            if cur is None:
                continue
            if cmp_op(cur, target):
                actual = (rows[j].ts - r.ts).total_seconds() / 60.0
                if actual > 0:
                    pairs.append((r.minutes_remaining, actual))
                break
    return pairs


def detect_events(rows: list[Row]):
    """Delegates to volthium.events.detect_events, which is the shared
    impl used by the dashboard too.  Adapts our Row objects to the dict
    interface that module expects."""
    from volthium.events import detect_events as _detect
    return _detect([
        {
            "ts": r.ts,
            "pack_i": r.pack_i,
            "max_soc": r.max_soc,
            "min_soc": r.min_soc,
            "state": r.state,
        }
        for r in rows
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--horizon", type=float, default=120.0,
                    help="estimator-accuracy horizon in minutes")
    args = ap.parse_args()

    rows = load(args.csv)
    if not rows:
        print("no data yet.")
        return 1
    dur = rows[-1].ts - rows[0].ts
    print(f"\n=== {args.csv.name} ===")
    print(f"samples:   {len(rows)}")
    print(f"window:    {rows[0].ts:%Y-%m-%d %H:%M:%S} → {rows[-1].ts:%H:%M:%S}  "
          f"({int(dur.total_seconds() // 3600)}h "
          f"{int((dur.total_seconds() % 3600) // 60)}m)")

    socs = [r.soc for r in rows if r.soc is not None]
    if socs:
        print(f"SOC range: {min(socs):.1f}% – {max(socs):.1f}%")
    currents = [r.pack_i for r in rows if r.pack_i is not None]
    if currents:
        print(f"current:   min {min(currents):+.1f} A  "
              f"max {max(currents):+.1f} A  "
              f"mean {statistics.mean(currents):+.2f} A")

    print("\n--- segments (consecutive same-state, short ones merged) ---")
    for seg in segment(rows):
        print(f"  {seg}")

    events = detect_events(rows)
    if events:
        print("\n--- events (named transitions, even within same state) ---")
        for e in events:
            print(f"  {e.ts:%H:%M:%S}  {e.kind:<18}  {e.descriptor}")

    print("\n--- Ah rate by current bucket (from remaining_ah; coulomb-counting sanity check) ---")
    buckets = ah_rate_by_current_bucket(rows)
    for label in ("fast charge (≥30A)", "moderate charge (10-30A)",
                  "trickle charge (1-10A)", "idle (|I|<1A)",
                  "light discharge (-1 to -10A)", "heavy discharge (≤-10A)"):
        if label not in buckets:
            continue
        obs = buckets[label]
        rates = [r for r, _ in obs]
        currents = [c for _, c in obs]
        mean_i = statistics.mean(currents)
        med_rate = statistics.median(rates)
        # If the BMS were pure coulomb counter, dAh/hr should ≈ mean_i.
        # Ratio tells us how much the BMS is "rounding" or voltage-correcting.
        ratio = med_rate / mean_i if abs(mean_i) > 0.5 else float("nan")
        print(f"  {label:<28}  n={len(obs):>4}  "
              f"median dAh/hr {med_rate:+6.2f}  vs mean I {mean_i:+6.2f}A  "
              f"(ratio {ratio:.2f})")

    pairs = estimator_accuracy(rows, args.horizon)
    if pairs:
        # ratio of predicted/actual — 1.0 = perfect, <1 = under-predicted (showed lower number than real)
        ratios = [p / a for p, a in pairs if a > 0]
        if ratios:
            print(f"\n--- estimator accuracy (predicted / actual within {args.horizon:.0f} min) ---")
            print(f"  observations: {len(ratios)}")
            print(f"  ratio:        median {statistics.median(ratios):.2f}  "
                  f"(want ≈ 1.0; <1 = under-predicted, >1 = over-predicted)")
            errs = [(p - a) for p, a in pairs]
            print(f"  abs error:    median {statistics.median(abs(e) for e in errs):.1f} min")
    else:
        print(f"\n--- estimator accuracy: no SOC ceiling/floor crossings within {args.horizon:.0f} min horizon yet ---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
