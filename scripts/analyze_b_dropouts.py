"""One-off forensic: correlate battery-B BLE dropouts with pack load.

Hypothesis (2026-07-13, FM-6 follow-up): B's BLE module is knocked over by
load transients on the DC bus — brief dropouts recur in the same evening
window, and the operator's proven manual cure is 30 s of breaker-open quiet
bus. If dropouts coincide with load steps, that's the smoking gun.

Reads the pack CSVs (current + archives), finds every A-up/B-down span,
and prints its duration plus the load before/at/after the dropout edge.

Usage (on the Pi):  .venv/bin/python scripts/analyze_b_dropouts.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
FILES = [
    "pack.csv.v0-1512", "pack.csv.v1-1028", "pack.csv.v1-2324", "pack.csv",
]
MIN_SPAN_ROWS = 1          # count even single-cycle blips
LOAD_WINDOW_ROWS = 8       # ~1 min of context either side


def rows():
    for name in FILES:
        p = DATA / name
        if not p.exists():
            continue
        with p.open(newline="", errors="replace") as f:
            for r in csv.reader(f):
                # Data rows start with an ISO timestamp; skip headers and
                # the stray merge-marker lines in one archive.
                if not r or not r[0].startswith("20"):
                    continue
                yield r


def f(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def main() -> int:
    hist = []          # (ts_str, a_present, b_present, i_a, pack_p)
    for r in rows():
        if len(r) < 11:
            continue
        hist.append((r[0], r[5] != "", r[6] != "", f(r[9]), f(r[4])))

    spans = []         # (start_idx, end_idx or None)
    in_span = False
    start = 0
    for i, (_ts, a_up, b_up, _ia, _p) in enumerate(hist):
        if a_up and not b_up:
            if not in_span:
                in_span, start = True, i
        else:
            if in_span:
                spans.append((start, i))
                in_span = False
    if in_span:
        spans.append((start, None))

    def dt(s):
        return datetime.fromisoformat(s)

    print(f"{'start':<20}{'dur':>9}  {'load before -> at drop -> after (W)':<40}")
    n_step = 0
    for start, end in spans:
        ts0 = hist[start][0]
        if end is not None:
            dur = (dt(hist[end][0]) - dt(ts0)).total_seconds()
            durs = f"{dur/60:.1f}m" if dur >= 90 else f"{dur:.0f}s"
        else:
            durs = "ongoing"
        before = [h[4] for h in hist[max(0, start - LOAD_WINDOW_ROWS):start]
                  if h[4] is not None]
        after_src = hist[start:start + LOAD_WINDOW_ROWS]
        # During B-absence pack_p is blank; fall back to i_a * ~26 V.
        after = [h[4] if h[4] is not None
                 else (h[3] * 26.0 if h[3] is not None else None)
                 for h in after_src]
        after = [x for x in after if x is not None]
        b_avg = sum(before) / len(before) if before else None
        a_avg = sum(after) / len(after) if after else None
        step = (b_avg is not None and a_avg is not None
                and abs(a_avg - b_avg) > 60)
        n_step += bool(step)
        fmt = lambda x: f"{x:7.0f}" if x is not None else "      ?"
        print(f"{ts0:<20}{durs:>9}  {fmt(b_avg)} -> {fmt(a_avg)}"
              f"{'   << load step' if step else ''}")
    print(f"\n{len(spans)} B-only dropouts; {n_step} coincide with a "
          f">60 W load step across the edge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
