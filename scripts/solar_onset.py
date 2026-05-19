"""Detect the day's solar-onset transition from pack.csv.

After overnight discharge, the pack reaches its low SOC sometime
around dawn. As solar starts arriving (1-3 h after sunrise on a
west-facing array like the Loon Lake cabin's), the current goes
through a cascade:

    1. discharge eases (smoothed_i creeps from -3 A toward zero)
    2. instantaneous current touches 0.0 A (the BMS still
       classifies state as "discharging" because no positive
       current has been seen)
    3. BMS state transitions to "idle" (|i| stays near zero)
    4. instantaneous current goes positive (solar exceeds load)
    5. smoothed current goes net-positive (sustained charging)

The day's "solar onset" is the moment in this cascade we want to
archive. Each milestone lands earlier on a sunny day, later on a
cloudy day; the gap between (4) and (5) tells us about load
variability vs. solar steadiness.

Schema (data/solar_onset.csv):
    date                       ISO calendar date (the key)
    first_zero_iso             first sample at pack_i == 0.0
    first_idle_iso             first sample with state == "idle"
    first_positive_iso         first sample at pack_i > 0
    first_net_positive_iso     first sample at smoothed_i > 0
    smoothed_i_at_net_positive A snapshot of smoothed_i at (5)
    soc_avg_at_net_positive    (soc_a + soc_b)/2 at (5) — the
                               daily low SOC, essentially

Idempotent: re-running on the same day with the same pack.csv
overwrites that day's row (newest detection wins). The row is
only written when at least the first_zero or first_idle event
has occurred — otherwise we skip (still pre-onset).

CLI:
    python scripts/solar_onset.py            # detect for today
    python scripts/solar_onset.py --show     # print log
    python scripts/solar_onset.py --date 2026-05-20
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOG_PATH = Path("data/solar_onset.csv")
PACK_PATH = Path("data/pack.csv")
FIELDS = [
    "date",
    "first_zero_iso",
    "first_idle_iso",
    "first_positive_iso",
    "first_net_positive_iso",
    "smoothed_i_at_net_positive",
    "soc_avg_at_net_positive",
]

# How close to zero a sample's instantaneous current must be to
# count as the "first idle" event when state classification isn't
# available. The BMS's own state field is preferred; this is the
# fallback heuristic.
IDLE_CURRENT_THRESHOLD_A = 0.5


@dataclass
class SolarOnsetRecord:
    """One day's onset cascade. Any field may be None if that
    milestone hasn't happened yet (still pre-onset)."""
    date: str
    first_zero_iso: Optional[str] = None
    first_idle_iso: Optional[str] = None
    first_positive_iso: Optional[str] = None
    first_net_positive_iso: Optional[str] = None
    smoothed_i_at_net_positive: Optional[float] = None
    soc_avg_at_net_positive: Optional[float] = None

    @classmethod
    def from_row(cls, r: dict) -> "SolarOnsetRecord":
        def _opt_f(v):
            if v in (None, "", "None"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        def _opt_s(v):
            return v if v not in (None, "", "None") else None

        return cls(
            date=r.get("date", ""),
            first_zero_iso=_opt_s(r.get("first_zero_iso")),
            first_idle_iso=_opt_s(r.get("first_idle_iso")),
            first_positive_iso=_opt_s(r.get("first_positive_iso")),
            first_net_positive_iso=_opt_s(r.get("first_net_positive_iso")),
            smoothed_i_at_net_positive=_opt_f(r.get("smoothed_i_at_net_positive")),
            soc_avg_at_net_positive=_opt_f(r.get("soc_avg_at_net_positive")),
        )

    def is_empty(self) -> bool:
        """True if no milestone has been observed yet (still
        pre-onset). Worth not writing such rows."""
        return all(v is None for v in (
            self.first_zero_iso,
            self.first_idle_iso,
            self.first_positive_iso,
            self.first_net_positive_iso,
        ))


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _iter_day_samples(pack_csv: Path, day: date) -> Iterable[dict]:
    """Yield raw pack.csv rows whose `ts` falls on `day`."""
    if not pack_csv.exists():
        return
    iso_prefix = day.isoformat()
    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            ts = r.get("ts", "")
            if ts.startswith(iso_prefix):
                yield r


def detect_onset(pack_csv: Path, day: date) -> SolarOnsetRecord:
    """Scan a day's pack.csv samples in chronological order and
    record the first occurrence of each milestone. Stops scanning
    once all four milestones have been seen (cheap when re-running
    later in the day)."""
    rec = SolarOnsetRecord(date=day.isoformat())
    for r in _iter_day_samples(pack_csv, day):
        ts = r.get("ts", "")
        state = r.get("state", "")
        pack_i = _f(r.get("pack_i"))
        smoothed_i = _f(r.get("smoothed_i"))
        soc_a = _f(r.get("soc_a"))
        soc_b = _f(r.get("soc_b"))

        if pack_i is None or smoothed_i is None:
            continue

        # first_zero: first time the instantaneous current touches 0.0
        # (or crosses to positive). This is the leading edge — solar
        # has matched load for at least one sample.
        if rec.first_zero_iso is None and pack_i >= 0.0:
            rec.first_zero_iso = ts

        # first_idle: BMS classifies state as "idle". Prefer the BMS's
        # own state field; fall back to |i| < threshold for robustness.
        if rec.first_idle_iso is None:
            if state == "idle" or abs(pack_i) <= IDLE_CURRENT_THRESHOLD_A:
                # Only consider it "idle" AFTER we've seen the first
                # zero crossing — otherwise a transient gap in the
                # overnight load would spuriously match.
                if rec.first_zero_iso is not None:
                    rec.first_idle_iso = ts

        # first_positive: instantaneous current strictly positive
        if rec.first_positive_iso is None and pack_i > 0.0:
            rec.first_positive_iso = ts

        # first_net_positive: smoothed current strictly positive
        # (sustained charging). This is the durable transition.
        if rec.first_net_positive_iso is None and smoothed_i > 0.0:
            rec.first_net_positive_iso = ts
            rec.smoothed_i_at_net_positive = smoothed_i
            if soc_a is not None and soc_b is not None:
                rec.soc_avg_at_net_positive = (soc_a + soc_b) / 2.0
            else:
                rec.soc_avg_at_net_positive = None

        # Cheap early exit once all four milestones have landed.
        if (rec.first_zero_iso is not None
            and rec.first_idle_iso is not None
            and rec.first_positive_iso is not None
            and rec.first_net_positive_iso is not None):
            break

    return rec


def read_log(path: Path = LOG_PATH) -> list[SolarOnsetRecord]:
    if not path.exists():
        return []
    with path.open() as f:
        return [SolarOnsetRecord.from_row(r) for r in csv.DictReader(f)]


def _write_log(records: list[SolarOnsetRecord], path: Path = LOG_PATH) -> None:
    """Rewrite the whole log. Used by upsert."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in records:
            w.writerow({
                "date": r.date,
                "first_zero_iso": r.first_zero_iso or "",
                "first_idle_iso": r.first_idle_iso or "",
                "first_positive_iso": r.first_positive_iso or "",
                "first_net_positive_iso": r.first_net_positive_iso or "",
                "smoothed_i_at_net_positive":
                    "" if r.smoothed_i_at_net_positive is None
                    else f"{r.smoothed_i_at_net_positive:.4f}",
                "soc_avg_at_net_positive":
                    "" if r.soc_avg_at_net_positive is None
                    else f"{r.soc_avg_at_net_positive:.2f}",
            })
        f.flush()


def upsert(rec: SolarOnsetRecord, path: Path = LOG_PATH) -> bool:
    """Insert or update the row for `rec.date`. Returns True iff a
    row was written (no-op when the day's record is empty AND no
    prior row existed; also no-op when the fresh record is
    byte-identical to what's already on disk)."""
    if rec.is_empty():
        return False
    existing = read_log(path)
    by_date = {r.date: r for r in existing}
    prior = by_date.get(rec.date)
    if prior == rec:
        return False
    by_date[rec.date] = rec
    # Keep stable chronological order by date string.
    rebuilt = [by_date[d] for d in sorted(by_date.keys())]
    _write_log(rebuilt, path)
    return True


def detect_and_record(pack_csv: Path = PACK_PATH,
                      day: Optional[date] = None,
                      log_path: Path = LOG_PATH) -> tuple[SolarOnsetRecord, bool]:
    """Combined helper: scan pack.csv for `day` (default today),
    upsert the result. Returns (record, wrote_a_row)."""
    if day is None:
        day = datetime.now().date()
    rec = detect_onset(pack_csv, day)
    wrote = upsert(rec, log_path)
    return rec, wrote


def _short_ts(iso: Optional[str]) -> str:
    """Return HH:MM:SS slice of an ISO timestamp for tabular
    display, or '—' if None."""
    if iso is None:
        return "—"
    # ISO with T separator: 2026-05-19T06:46:17
    return iso[11:19] if "T" in iso else iso


def pretty_print(records: list[SolarOnsetRecord]) -> None:
    if not records:
        print("(no solar-onset events logged yet — first row lands "
              "the moment a day's current first touches zero)")
        return
    print("=== Solar-onset history ===")
    print(f"{'date':<11}  {'zero':>8}  {'idle':>8}  {'pos':>8}  "
          f"{'net+':>8}  {'smI':>5}  {'SOC':>5}")
    print("-" * 64)
    for r in records:
        smi = ("—" if r.smoothed_i_at_net_positive is None
               else f"{r.smoothed_i_at_net_positive:+5.2f}")
        soc = ("—" if r.soc_avg_at_net_positive is None
               else f"{r.soc_avg_at_net_positive:5.1f}")
        print(f"{r.date:<11}  {_short_ts(r.first_zero_iso):>8}  "
              f"{_short_ts(r.first_idle_iso):>8}  "
              f"{_short_ts(r.first_positive_iso):>8}  "
              f"{_short_ts(r.first_net_positive_iso):>8}  "
              f"{smi:>5}  {soc:>5}")
    print()
    last = records[-1]
    if last.first_net_positive_iso is not None:
        print(f"latest: {last.date} crossed net-positive at "
              f"{_short_ts(last.first_net_positive_iso)} "
              f"(SOC {last.soc_avg_at_net_positive:.1f} %)")
    elif last.first_zero_iso is not None:
        print(f"latest: {last.date} first zero at "
              f"{_short_ts(last.first_zero_iso)}, "
              f"net-positive still pending")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="just print the log; don't run detection")
    ap.add_argument("--date", default=None,
                    help="ISO date to detect for (default: today)")
    ap.add_argument("--pack-csv", type=Path, default=PACK_PATH)
    args = ap.parse_args()

    if args.show:
        pretty_print(read_log())
        return 0

    if args.date:
        day = date.fromisoformat(args.date)
    else:
        day = datetime.now().date()

    rec, wrote = detect_and_record(args.pack_csv, day)
    if wrote:
        print(f"recorded onset for {day.isoformat()}: "
              f"zero={_short_ts(rec.first_zero_iso)} "
              f"idle={_short_ts(rec.first_idle_iso)} "
              f"pos={_short_ts(rec.first_positive_iso)} "
              f"net+={_short_ts(rec.first_net_positive_iso)}")
    elif rec.is_empty():
        print(f"{day.isoformat()}: still pre-onset "
              f"(no zero/idle/positive milestone yet)")
    else:
        print(f"{day.isoformat()}: no change since last detection "
              f"(net+={_short_ts(rec.first_net_positive_iso)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
