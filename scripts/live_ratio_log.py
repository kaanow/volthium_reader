"""Record live_ratio + drift snapshots on each advisor invocation.

The advisor computes today's live_ratio (Ah delivered to the pack /
kWh/m² of horizontal-plane irradiance received) on every run. That
number was previously emitted only in stdout / the dashboard chip
— this module appends it to `data/live_ratio_log.csv` as a time
series. Future loops will visualize it as a chart with the drift
threshold band overlaid.

Why a separate log instead of piggybacking on projection_log:
`projected_low_soc` and `live_ratio` evolve on totally different
timescales (projection refreshes each advisor invocation; live_ratio
slowly accumulates over the day). Splitting them keeps either log
readable on its own.

Rate-limited: at most one row per `MIN_MINUTES_BETWEEN` minutes (25 by
default) so dashboard subprocesses don't spam the log.

Schema (data/live_ratio_log.csv):
    ts                            ISO timestamp of recording
    live_ratio_ah_per_kwh_m2      today_harvest.snapshot's live ratio
    solar_ah_so_far               cumulative pack gain today
    irradiance_kwh_m2_so_far      cumulative day-total irradiance
    solar_model_coefficient       SolarModel coef in effect right now
    drift_pct                     (live - coef) / coef * 100
    advisory_fired                "True" if |drift| crossed threshold

CLI:
    python scripts/live_ratio_log.py            # print log
    python scripts/live_ratio_log.py --show     # same
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOG_PATH = Path("data/live_ratio_log.csv")
FIELDS = [
    "ts",
    "live_ratio_ah_per_kwh_m2",
    "solar_ah_so_far",
    "irradiance_kwh_m2_so_far",
    "solar_model_coefficient",
    "drift_pct",
    "advisory_fired",
]

# Minimum gap between rows. Matches projection_log so the two
# time-series sample at the same cadence — useful when overlaying.
MIN_MINUTES_BETWEEN = 25


@dataclass
class LogEntry:
    ts: str
    live_ratio_ah_per_kwh_m2: float
    solar_ah_so_far: float
    irradiance_kwh_m2_so_far: float
    solar_model_coefficient: float
    drift_pct: float
    advisory_fired: bool

    @classmethod
    def from_row(cls, r: dict) -> "LogEntry":
        def _f(v, default=0.0):
            try:
                return float(v) if v not in (None, "", "None") else default
            except (TypeError, ValueError):
                return default
        af = str(r.get("advisory_fired", "")).strip().lower()
        return cls(
            ts=r.get("ts", ""),
            live_ratio_ah_per_kwh_m2=_f(r.get("live_ratio_ah_per_kwh_m2")),
            solar_ah_so_far=_f(r.get("solar_ah_so_far")),
            irradiance_kwh_m2_so_far=_f(r.get("irradiance_kwh_m2_so_far")),
            solar_model_coefficient=_f(r.get("solar_model_coefficient")),
            drift_pct=_f(r.get("drift_pct")),
            advisory_fired=af in ("true", "1", "yes"),
        )


def read_log(path: Path = LOG_PATH) -> list[LogEntry]:
    if not path.exists():
        return []
    with path.open() as f:
        return [LogEntry.from_row(r) for r in csv.DictReader(f)]


def last_entry(path: Path = LOG_PATH) -> Optional[LogEntry]:
    entries = read_log(path)
    return entries[-1] if entries else None


def append_entry(entry: LogEntry, path: Path = LOG_PATH) -> None:
    """Append one row. Creates the file with a header if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "ts": entry.ts,
            "live_ratio_ah_per_kwh_m2": f"{entry.live_ratio_ah_per_kwh_m2:.4f}",
            "solar_ah_so_far":          f"{entry.solar_ah_so_far:.4f}",
            "irradiance_kwh_m2_so_far": f"{entry.irradiance_kwh_m2_so_far:.4f}",
            "solar_model_coefficient":  f"{entry.solar_model_coefficient:.4f}",
            "drift_pct":                f"{entry.drift_pct:.2f}",
            "advisory_fired":           "True" if entry.advisory_fired else "False",
        })
        f.flush()


def record_if_due(
    live_ratio_ah_per_kwh_m2: Optional[float],
    solar_ah_so_far: Optional[float],
    irradiance_kwh_m2_so_far: Optional[float],
    solar_model_coefficient: float,
    drift_pct: Optional[float],
    advisory_fired: bool,
    now: Optional[datetime] = None,
    min_minutes_between: int = MIN_MINUTES_BETWEEN,
    path: Path = LOG_PATH,
) -> bool:
    """Append a row IF (a) the live_ratio is populated (not the
    early-morning threshold-guarded None state), AND (b) the last
    logged row is older than min_minutes_between.

    Returns True iff a row was written. Best-effort caller — wrap
    in try/except so the advisor never blocks on a logging failure.
    """
    # Skip when live_ratio isn't meaningful yet (very early morning,
    # or 100 % cloud with sub-threshold accumulation)
    if (live_ratio_ah_per_kwh_m2 is None
            or solar_ah_so_far is None
            or irradiance_kwh_m2_so_far is None
            or drift_pct is None):
        return False

    if now is None:
        now = datetime.now()

    prev = last_entry(path)
    if prev is not None:
        try:
            prev_ts = datetime.fromisoformat(prev.ts)
        except ValueError:
            prev_ts = None
        if prev_ts is not None:
            if (now - prev_ts) < timedelta(minutes=min_minutes_between):
                return False

    entry = LogEntry(
        ts=now.isoformat(timespec="seconds"),
        live_ratio_ah_per_kwh_m2=live_ratio_ah_per_kwh_m2,
        solar_ah_so_far=solar_ah_so_far,
        irradiance_kwh_m2_so_far=irradiance_kwh_m2_so_far,
        solar_model_coefficient=solar_model_coefficient,
        drift_pct=drift_pct,
        advisory_fired=advisory_fired,
    )
    append_entry(entry, path)
    return True


def pretty_print(entries: list[LogEntry]) -> None:
    if not entries:
        print("(no live_ratio_log entries yet)")
        return
    print("=== live_ratio history ===")
    print(f"{'timestamp':<19}  {'ratio':>5}  {'solar_ah':>8}  "
          f"{'irr':>5}  {'coef':>5}  {'drift':>6}  adv")
    print("-" * 70)
    for e in entries:
        adv = "yes" if e.advisory_fired else "—"
        print(f"{e.ts:<19}  {e.live_ratio_ah_per_kwh_m2:5.2f}  "
              f"{e.solar_ah_so_far:8.2f}  "
              f"{e.irradiance_kwh_m2_so_far:5.2f}  "
              f"{e.solar_model_coefficient:5.2f}  "
              f"{e.drift_pct:+6.1f}  {adv}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="print the log (default)")
    ap.parse_args()
    pretty_print(read_log())
    return 0


if __name__ == "__main__":
    sys.exit(main())
