"""Extract OCV → SOC calibration points from the live pack.csv.

The production firmware needs a voltage-only SOC inference path for
the DEEP_SLEEP / HARD_CUT states (when BLE is off and we can only
read the 24 V rail via the ULP). See `docs/firmware/state_machine.md`
§ "SOC source per state".

This script walks pack.csv and finds rest windows — periods where the
absolute current is below a threshold (default 0.5 A) for at least a
sustained duration (default 5 min). In those windows the pack voltage
is close to its open-circuit voltage (OCV), and the BMS-reported SOC is
trustworthy. Each rest window contributes one calibration point.

The resulting table is what the C ULP routine will linearly interpolate
between to translate a measured 24 V reading into a rough SOC %.

Run repeatedly as more data accumulates (it's idempotent — overwrites
the output table from scratch every run). The output is intended to be
shipped alongside the firmware.

Usage:
    .venv/bin/python scripts/voltage_soc_calibration.py [--csv data/pack.csv]

Outputs:
    data/voltage_soc_table.csv  — the calibration table
    plus a printed summary
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


@dataclass
class Row:
    ts: datetime
    pack_v: Optional[float]
    pack_i: Optional[float]
    smoothed_i: Optional[float]
    soc_a: Optional[float]
    soc_b: Optional[float]


def _f(v: str) -> Optional[float]:
    if v in ("", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load(path: Path) -> list[Row]:
    out = []
    with path.open() as f:
        for r in csv.DictReader(f):
            out.append(Row(
                ts=datetime.fromisoformat(r["ts"]),
                pack_v=_f(r["pack_v"]),
                pack_i=_f(r["pack_i"]),
                smoothed_i=_f(r["smoothed_i"]),
                soc_a=_f(r["soc_a"]),
                soc_b=_f(r["soc_b"]),
            ))
    return out


@dataclass
class RestWindow:
    start: datetime
    end:   datetime
    avg_voltage: float
    avg_soc_a: float
    avg_soc_b: float
    n_samples: int

    @property
    def avg_soc(self) -> float:
        return (self.avg_soc_a + self.avg_soc_b) / 2.0


def find_rest_windows(
    rows: list[Row],
    *,
    idle_current_threshold_a: float = 0.5,
    min_duration_s: float = 300.0,
) -> list[RestWindow]:
    """Yield contiguous spans of |smoothed_i| < threshold lasting >= min_duration_s."""
    out: list[RestWindow] = []
    span_start: Optional[int] = None
    for i, r in enumerate(rows):
        idle = (
            r.smoothed_i is not None
            and abs(r.smoothed_i) < idle_current_threshold_a
        )
        if idle and span_start is None:
            span_start = i
        elif (not idle) and span_start is not None:
            _maybe_emit(rows, span_start, i, out, min_duration_s)
            span_start = None
    if span_start is not None:
        _maybe_emit(rows, span_start, len(rows), out, min_duration_s)
    return out


def _maybe_emit(rows, start, end, out, min_duration_s):
    if end - start < 2:
        return
    span = rows[start:end]
    duration = (span[-1].ts - span[0].ts).total_seconds()
    if duration < min_duration_s:
        return
    vs = [r.pack_v for r in span if r.pack_v is not None]
    sas = [r.soc_a for r in span if r.soc_a is not None]
    sbs = [r.soc_b for r in span if r.soc_b is not None]
    if not vs or not sas or not sbs:
        return
    out.append(RestWindow(
        start=span[0].ts, end=span[-1].ts,
        avg_voltage=statistics.mean(vs),
        avg_soc_a=statistics.mean(sas),
        avg_soc_b=statistics.mean(sbs),
        n_samples=len(span),
    ))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/voltage_soc_table.csv"))
    ap.add_argument("--idle-a", type=float, default=0.5,
                    help="|smoothed_I| below this counts as idle")
    ap.add_argument("--min-rest-s", type=float, default=300.0,
                    help="minimum continuous idle duration in seconds")
    args = ap.parse_args()

    rows = load(args.csv)
    if not rows:
        print("no data yet.")
        return 1

    windows = find_rest_windows(
        rows,
        idle_current_threshold_a=args.idle_a,
        min_duration_s=args.min_rest_s,
    )

    print(f"\n=== OCV calibration from {args.csv.name} ===")
    print(f"  total samples:     {len(rows)}")
    print(f"  rest-window count: {len(windows)}  (|I|<{args.idle_a}A for ≥{args.min_rest_s:.0f}s)")
    print()

    if windows:
        print(f"  {'start':>10} {'dur':>6} {'V':>7} {'SOC%':>5}")
        for w in windows:
            dur_s = (w.end - w.start).total_seconds()
            print(f"  {w.start:%H:%M:%S} {dur_s:5.0f}s {w.avg_voltage:6.3f} V {w.avg_soc:4.1f}")

        # SOC bucketing — collapse to 5 % bins so we end with a discrete
        # lookup table the firmware can interpolate against.
        bins: dict[int, list[RestWindow]] = {}
        for w in windows:
            b = int(round(w.avg_soc / 5.0) * 5)
            bins.setdefault(b, []).append(w)

        print(f"\n  bucketed (5%-bin) calibration table:")
        print(f"  {'SOC %':>6} {'avg V':>8} {'#wins':>6}")
        table_rows = []
        for soc in sorted(bins.keys()):
            ws = bins[soc]
            avg_v = statistics.mean(w.avg_voltage for w in ws)
            print(f"  {soc:>5}% {avg_v:7.3f} V {len(ws):>5}")
            table_rows.append((soc, round(avg_v, 3), len(ws)))

        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["soc_pct", "avg_voltage", "n_windows"])
            w.writerows(table_rows)
        print(f"\n  wrote {args.out}")
    else:
        print("  no rest windows long enough yet — pack hasn't been idle ≥5 min")
        print("  (this is normal during active charging or discharging)")
        print("  let the dataset accumulate; re-run later.")

    print()
    print("Firmware integration target:")
    print("  - C ULP routine in firmware/bms-link/ulp/ reads 24 V via ADC,")
    print("    walks this table, returns the bracketing SOC.")
    print("  - Used during DEEP_SLEEP and HARD_CUT (state_machine.md).")
    print("  - Re-run this script monthly while the pack is in production —")
    print("    each cycle adds new rest-window samples and the table sharpens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
