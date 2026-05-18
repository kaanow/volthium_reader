"""Estimate per-battery capacity from a captured charge cycle.

We have several truths in the data and they don't all agree:

    A. Coulomb-counted Ah delivered = ∫ pack_current dt over the charge
    B. BMS-reported remaining_ah delta over the same interval
    C. BMS-reported SOC% delta over the same interval

If the BMS were a pure coulomb counter with the nameplate 200 Ah, all
three would tell the same story. They don't — see
docs/hardware/bms_calibration.md. This script prints all three side-by-
side for the longest sustained charging segment in the CSV so we can
make an evidence-based decision about what `capacity_ah` to use in the
production firmware.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Row:
    ts: datetime
    state: str
    pack_i: Optional[float]
    soc_a: Optional[float]
    soc_b: Optional[float]
    rem_a: Optional[float]
    rem_b: Optional[float]

    @property
    def avg_soc(self) -> Optional[float]:
        if self.soc_a is None or self.soc_b is None:
            return None
        return (self.soc_a + self.soc_b) / 2

    @property
    def avg_rem(self) -> Optional[float]:
        if self.rem_a is None or self.rem_b is None:
            return None
        return (self.rem_a + self.rem_b) / 2


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
                state=r["state"],
                pack_i=_f(r["pack_i"]),
                soc_a=_f(r["soc_a"]),
                soc_b=_f(r["soc_b"]),
                rem_a=_f(r["remaining_ah_a"]),
                rem_b=_f(r["remaining_ah_b"]),
            ))
    return out


def find_longest_charge(rows: list[Row]) -> tuple[int, int] | None:
    """Returns (start_idx, end_idx) of the longest contiguous charging run."""
    best = None
    cur_start = None
    for i, r in enumerate(rows):
        is_charging = r.state == "charging"
        if is_charging and cur_start is None:
            cur_start = i
        elif not is_charging and cur_start is not None:
            length = i - cur_start
            if best is None or length > best[1] - best[0]:
                best = (cur_start, i)
            cur_start = None
    if cur_start is not None:
        length = len(rows) - cur_start
        if best is None or length > best[1] - best[0]:
            best = (cur_start, len(rows))
    return best


def integrate_current(rows: list[Row], start: int, end: int) -> float:
    """∫ pack_current dt — coulomb-counted Ah, trapezoidal."""
    total = 0.0
    for i in range(start + 1, end):
        a, b = rows[i - 1], rows[i]
        if a.pack_i is None or b.pack_i is None:
            continue
        dt = (b.ts - a.ts).total_seconds()
        if dt <= 0 or dt > 60:  # ignore gaps
            continue
        total += (a.pack_i + b.pack_i) / 2 * dt / 3600
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    args = ap.parse_args()

    rows = load(args.csv)
    if not rows:
        print("no data.")
        return 1

    seg = find_longest_charge(rows)
    if seg is None:
        print("no charge segment found yet.")
        return 1
    s, e = seg
    a, b = rows[s], rows[e - 1]

    duration_min = (b.ts - a.ts).total_seconds() / 60

    print(f"\n=== capacity estimation from longest charge segment ===")
    print(f"window:     {a.ts:%H:%M:%S} → {b.ts:%H:%M:%S}  ({duration_min:.1f} min, {e - s} samples)")
    print()
    print(f"SOC:        {a.avg_soc:.1f}%  →  {b.avg_soc:.1f}%   (Δ {b.avg_soc - a.avg_soc:+.1f}%)")
    print(f"Battery A:  rem_ah {a.rem_a:.1f}  →  {b.rem_a:.1f}     (Δ {b.rem_a - a.rem_a:+.1f} Ah)")
    print(f"Battery B:  rem_ah {a.rem_b:.1f}  →  {b.rem_b:.1f}     (Δ {b.rem_b - a.rem_b:+.1f} Ah)")
    print()

    # Method A — coulomb count
    ah_integrated = integrate_current(rows, s, e)
    print(f"Method A — coulomb-count integral of pack_current:")
    print(f"            {ah_integrated:.1f} Ah delivered during this segment")
    print(f"            (same Ah passes through both batteries in series)")
    print()

    # Method B — BMS remaining_ah delta
    delta_rem_a = b.rem_a - a.rem_a
    delta_rem_b = b.rem_b - a.rem_b
    print(f"Method B — BMS-reported remaining_ah delta:")
    print(f"            battery A: {delta_rem_a:+.1f} Ah    battery B: {delta_rem_b:+.1f} Ah")
    print(f"            (each battery's own coulomb counter)")
    print()

    # Implied capacity from SOC% swing
    dsoc = b.avg_soc - a.avg_soc
    print(f"Method C — capacity implied by SOC% swing:")
    if dsoc > 0:
        # If BMS uses pure Ah-counting: capacity_per_battery = ΔAh / (ΔSOC/100)
        cap_from_int = ah_integrated / (dsoc / 100)
        cap_from_rem_a = delta_rem_a / (dsoc / 100)
        cap_from_rem_b = delta_rem_b / (dsoc / 100)
        print(f"            from integration (Method A): {cap_from_int:.0f} Ah per battery")
        print(f"            from BMS rem_a   (Method B): {cap_from_rem_a:.0f} Ah per battery")
        print(f"            from BMS rem_b   (Method B): {cap_from_rem_b:.0f} Ah per battery")
    else:
        print(f"            ΔSOC% ≤ 0; cannot estimate")
    print()

    # Also surface the peak remaining_ah observed anywhere in the data
    max_rem_a = max(r.rem_a for r in rows if r.rem_a is not None)
    max_rem_b = max(r.rem_b for r in rows if r.rem_b is not None)
    print(f"Method D — peak observed remaining_ah (cross-checked across full dataset):")
    print(f"            battery A peak: {max_rem_a:.0f} Ah    battery B peak: {max_rem_b:.0f} Ah")
    print(f"            (this is what the BMS calls 'full' Ah-wise; "
          f"differs from the SOC=100% point)")
    print()

    # Recommendation
    print("=== reading ===")
    print(f"  • If you want the most conservative capacity (won't over-promise")
    print(f"    time-to-empty): use Method B / lower per-battery rem-delta.")
    print(f"  • If you want to match what the BMS calls 'full': use Method D.")
    print(f"  • For the production firmware, the hybrid coulomb-counter")
    print(f"    avoids the question entirely — it just tracks the BMS's own")
    print(f"    remaining_ah and integrates current between BMS ticks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
