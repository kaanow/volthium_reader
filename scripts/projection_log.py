"""Record each advisor invocation's projections so we can later
evaluate accuracy.

`scripts/calibration_log.py` records changes to the SolarModel
coefficient. This is the parallel for the advisor's PROJECTIONS —
what it predicted SOC would be at sunrise, tomorrow evening, etc.,
so a later "nightly diff" feature can compare against what actually
happened.

CSV schema (`data/projection_log.csv`):

    ts                          ISO timestamp of the projection
    start_soc_pct               pack SOC at the time of the call
    projected_sunrise_soc       advisor's sunrise SOC prediction
    projected_tomorrow_evening_soc
    projected_low_soc           predicted minimum SOC in next 24 h
    solar_model_coefficient     model coef in effect at this call
    today_irradiance_kwh_m2     forecast irradiance used
    sunrise_iso                 the next-occurring sunrise time
    source                      "advisor-invocation" (default) or
                                "loop-iteration" / "manual" etc.

Rate-limited: a fresh row is appended only when the previous entry
is at least `MIN_MINUTES_BETWEEN` minutes old (default 25). Otherwise
the dashboard's cached-subprocess pattern would spam ~60 rows/hour.

CLI:
    python scripts/projection_log.py            # show
    python scripts/projection_log.py --tail 10  # last 10
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


LOG_PATH = Path("data/projection_log.csv")
FIELDS = [
    "ts", "start_soc_pct",
    "projected_sunrise_soc", "projected_tomorrow_evening_soc",
    "projected_low_soc",
    "solar_model_coefficient", "today_irradiance_kwh_m2",
    "sunrise_iso", "source",
]

# Minutes between rows. The dashboard's get_recommendation runs every
# ~60 s via subprocess (cached) — without this we'd churn out one row
# per call. The autonomous loop fires every ~25-30 min, so a 25-min
# threshold lets the loop's row land while suppressing dashboard noise.
MIN_MINUTES_BETWEEN = 25


@dataclass
class LogEntry:
    ts: str
    start_soc_pct: float
    projected_sunrise_soc: float
    projected_tomorrow_evening_soc: float
    projected_low_soc: float
    solar_model_coefficient: float
    today_irradiance_kwh_m2: Optional[float]
    sunrise_iso: str
    source: str

    @classmethod
    def from_row(cls, r: dict) -> "LogEntry":
        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return cls(
            ts=r.get("ts", ""),
            start_soc_pct=_f(r.get("start_soc_pct")) or 0.0,
            projected_sunrise_soc=_f(r.get("projected_sunrise_soc")) or 0.0,
            projected_tomorrow_evening_soc=_f(r.get("projected_tomorrow_evening_soc")) or 0.0,
            projected_low_soc=_f(r.get("projected_low_soc")) or 0.0,
            solar_model_coefficient=_f(r.get("solar_model_coefficient")) or 0.0,
            today_irradiance_kwh_m2=_f(r.get("today_irradiance_kwh_m2")),
            sunrise_iso=r.get("sunrise_iso", ""),
            source=r.get("source", ""),
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
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "ts": entry.ts,
            "start_soc_pct": f"{entry.start_soc_pct:.2f}",
            "projected_sunrise_soc": f"{entry.projected_sunrise_soc:.2f}",
            "projected_tomorrow_evening_soc":
                f"{entry.projected_tomorrow_evening_soc:.2f}",
            "projected_low_soc": f"{entry.projected_low_soc:.2f}",
            "solar_model_coefficient": f"{entry.solar_model_coefficient:.4f}",
            "today_irradiance_kwh_m2": (
                f"{entry.today_irradiance_kwh_m2:.3f}"
                if entry.today_irradiance_kwh_m2 is not None else ""
            ),
            "sunrise_iso": entry.sunrise_iso,
            "source": entry.source,
        })
        f.flush()


def record_if_due(
    start_soc_pct: float,
    projected_sunrise_soc: float,
    projected_tomorrow_evening_soc: float,
    projected_low_soc: float,
    solar_model_coefficient: float,
    today_irradiance_kwh_m2: Optional[float],
    sunrise_iso: str,
    source: str,
    now: Optional[datetime] = None,
    min_minutes_between: int = MIN_MINUTES_BETWEEN,
    path: Path = LOG_PATH,
) -> bool:
    """Append a projection log row if the previous entry is older than
    `min_minutes_between` minutes. Returns True if a row was written.

    Rate-limit prevents log spam from the dashboard's per-minute
    subprocess. The autonomous loop's ~25-30 min cadence naturally
    aligns with this threshold."""
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
        start_soc_pct=start_soc_pct,
        projected_sunrise_soc=projected_sunrise_soc,
        projected_tomorrow_evening_soc=projected_tomorrow_evening_soc,
        projected_low_soc=projected_low_soc,
        solar_model_coefficient=solar_model_coefficient,
        today_irradiance_kwh_m2=today_irradiance_kwh_m2,
        sunrise_iso=sunrise_iso,
        source=source,
    )
    append_entry(entry, path)
    return True


def pretty_print(entries: list[LogEntry], tail: Optional[int] = None) -> None:
    if not entries:
        print("(no projection log entries yet)")
        return
    if tail:
        entries = entries[-tail:]
    print("=== Advisor projection log ===")
    print(f"{'timestamp':<19}  {'start':>5}  {'sunrise':>7}  "
          f"{'eve':>5}  {'low':>5}  {'coef':>5}  source")
    print("-" * 76)
    for e in entries:
        print(f"{e.ts:<19}  {e.start_soc_pct:5.1f}  "
              f"{e.projected_sunrise_soc:7.1f}  "
              f"{e.projected_tomorrow_evening_soc:5.1f}  "
              f"{e.projected_low_soc:5.1f}  "
              f"{e.solar_model_coefficient:5.2f}  "
              f"{e.source}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=None,
                    help="only show the last N entries")
    args = ap.parse_args()
    pretty_print(read_log(), tail=args.tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
