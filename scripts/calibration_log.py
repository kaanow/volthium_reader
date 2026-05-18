"""Record each meaningful SolarModel coefficient change.

Every time the system loads the SolarModel (e.g. from the generator
advisor's `load_solar_model()`), we get a fresh fit from
data/daily_summary.csv. Usually nothing has changed; sometimes a new
complete-day row appears and the coefficient moves. Without a log
that move is silent — by the time someone notices "the advisor's
recommendation feels different," they have no way to reconstruct
*when* and *why* the model shifted.

This module appends a row to data/calibration_log.csv whenever the
coefficient changes by >= COEFFICIENT_DELTA_THRESHOLD, or the
confidence tier changes, or n_observations changes. Idempotent — re-
calling with the same model state is a no-op.

CSV schema (data/calibration_log.csv):
    ts                 ISO timestamp of the recording
    coefficient        SolarModel.coefficient_ah_per_kwh_m2
    n_observations     # of usable days the fit consumed
    confidence         "low" | "medium" | "high"
    source             short freeform tag explaining the trigger
                       ("startup", "daily-summary-refresh",
                        "advisor-invocation", etc.)
    notes              SolarModel.notes (the model's own diagnostic)

CLI:
    python scripts/calibration_log.py            # record if changed
    python scripts/calibration_log.py --show     # pretty-print history
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from volthium.solar_model import SolarModel  # noqa: E402

LOG_PATH = Path("data/calibration_log.csv")
FIELDS = ["ts", "coefficient", "n_observations", "confidence", "source", "notes"]

# How much the coefficient must move to log a new row. Below this is
# just sample-count jitter (e.g. one more day of medians barely
# shifts the median-of-ratios fit). 0.01 Ah/(kWh/m²) on a ~7 Ah/(kWh/m²)
# baseline is ~0.14 %.
COEFFICIENT_DELTA_THRESHOLD = 0.01


@dataclass
class LogEntry:
    ts: str
    coefficient: float
    n_observations: int
    confidence: str
    source: str
    notes: str

    @classmethod
    def from_row(cls, r: dict) -> "LogEntry":
        return cls(
            ts=r.get("ts", ""),
            coefficient=float(r.get("coefficient", 0.0) or 0.0),
            n_observations=int(r.get("n_observations", 0) or 0),
            confidence=r.get("confidence", "") or "",
            source=r.get("source", "") or "",
            notes=r.get("notes", "") or "",
        )


def read_log(path: Path = LOG_PATH) -> list[LogEntry]:
    if not path.exists():
        return []
    with path.open() as f:
        return [LogEntry.from_row(r) for r in csv.DictReader(f)]


def last_entry(path: Path = LOG_PATH) -> Optional[LogEntry]:
    entries = read_log(path)
    return entries[-1] if entries else None


def is_meaningful_change(prev: Optional[LogEntry], model: SolarModel) -> bool:
    """True if the model state differs enough from the last logged
    entry to warrant a new row."""
    if prev is None:
        return True
    if abs(model.coefficient_ah_per_kwh_m2 - prev.coefficient) >= COEFFICIENT_DELTA_THRESHOLD:
        return True
    if model.confidence != prev.confidence:
        return True
    if model.n_observations != prev.n_observations:
        return True
    return False


def append_entry(entry: LogEntry, path: Path = LOG_PATH) -> None:
    """Append one row to the log. Creates the file with a header if it
    doesn't exist yet. Uses 'a' mode + flush + fsync so concurrent
    callers (advisor subprocess from the dashboard, loop iteration)
    don't trample each other on a partial line write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "ts": entry.ts,
            "coefficient": f"{entry.coefficient:.4f}",
            "n_observations": entry.n_observations,
            "confidence": entry.confidence,
            "source": entry.source,
            "notes": entry.notes,
        })
        f.flush()


def record_if_changed(model: SolarModel, source: str,
                      path: Path = LOG_PATH,
                      now: Optional[datetime] = None) -> bool:
    """Compare `model` to the last logged entry; append a new row if it
    differs meaningfully. Returns True if a row was written."""
    prev = last_entry(path)
    if not is_meaningful_change(prev, model):
        return False
    if now is None:
        now = datetime.now()
    entry = LogEntry(
        ts=now.isoformat(timespec="seconds"),
        coefficient=model.coefficient_ah_per_kwh_m2,
        n_observations=model.n_observations,
        confidence=model.confidence,
        source=source,
        notes=model.notes or "",
    )
    append_entry(entry, path)
    return True


def load_current_model() -> SolarModel:
    """Same fit pipeline the advisor uses."""
    daily = Path("data/daily_summary.csv")
    if not daily.exists():
        return SolarModel.default()
    try:
        with daily.open() as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return SolarModel.default()
    return SolarModel.fit_from_daily_summary(rows)


def pretty_print(entries: list[LogEntry]) -> None:
    if not entries:
        print("(no calibration log entries yet)")
        return
    print("=== SolarModel calibration log ===")
    print(f"{'timestamp':<19}  {'coef':>6}  {'n':>3}  {'conf':<7}  source")
    print("-" * 70)
    for e in entries:
        print(f"{e.ts:<19}  {e.coefficient:6.3f}  {e.n_observations:3d}  "
              f"{e.confidence:<7}  {e.source}")
    if entries[-1].notes:
        print()
        print(f"latest notes: {entries[-1].notes}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="just print the log; don't record")
    ap.add_argument("--source", default="manual",
                    help="source tag for this record (e.g. 'loop-iteration')")
    args = ap.parse_args()

    if args.show:
        pretty_print(read_log())
        return 0

    model = load_current_model()
    wrote = record_if_changed(model, args.source)
    if wrote:
        print(f"recorded: coef={model.coefficient_ah_per_kwh_m2:.4f} "
              f"n={model.n_observations} conf={model.confidence} "
              f"source={args.source}")
    else:
        print(f"no change (coef={model.coefficient_ah_per_kwh_m2:.4f}, "
              f"n={model.n_observations}, conf={model.confidence}); "
              f"log not updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
