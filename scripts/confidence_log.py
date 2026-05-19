"""Record confidence-lift transition events from the generator advisor.

The generator advisor computes a fresh confidence tier on every
invocation. When the recent projection_accuracy track record is
tight, the tier gets lifted one notch (see
`generator_advisor.lift_confidence_by_accuracy`). Without a log,
those lift events are invisible — the dashboard shows the current
tier but not when it first crossed the threshold, whether it has
ever fallen back, or how recent_abs_error_pp has been drifting.

This module appends a row to data/confidence_log.csv whenever the
resolved confidence tier changes or the lifted-by-accuracy flag
flips. It does NOT record on every invocation — only meaningful
transitions. Idempotent: re-calling with identical state is a
no-op.

CSV schema (data/confidence_log.csv):
    ts                     ISO timestamp of the recording
    base                   the SolarModel's underlying confidence
                           ("low" / "medium" / "high")
    resolved               the advisor's emitted confidence (could
                           equal base or be one tier higher)
    lifted                 "True" if accuracy-aware lift fired,
                           else "False"
    recent_abs_error_pp    mean |error| over the recent window
                           (empty if no validated projections)
    recent_n               # of validated records in the window
    source                 short freeform tag ("advisor-invocation",
                           "loop-iteration", etc.)

CLI:
    python scripts/confidence_log.py            # record if changed
    python scripts/confidence_log.py --show     # pretty-print history
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

LOG_PATH = Path("data/confidence_log.csv")
FIELDS = [
    "ts",
    "base",
    "resolved",
    "lifted",
    "recent_abs_error_pp",
    "recent_n",
    "source",
]


@dataclass
class LogEntry:
    ts: str
    base: str
    resolved: str
    lifted: bool
    recent_abs_error_pp: Optional[float]
    recent_n: int
    source: str

    @classmethod
    def from_row(cls, r: dict) -> "LogEntry":
        ae = r.get("recent_abs_error_pp", "")
        try:
            recent_abs = float(ae) if ae not in (None, "", "None") else None
        except ValueError:
            recent_abs = None
        try:
            recent_n = int(r.get("recent_n", 0) or 0)
        except ValueError:
            recent_n = 0
        lifted = str(r.get("lifted", "")).strip().lower() in ("true", "1", "yes")
        return cls(
            ts=r.get("ts", ""),
            base=r.get("base", "") or "",
            resolved=r.get("resolved", "") or "",
            lifted=lifted,
            recent_abs_error_pp=recent_abs,
            recent_n=recent_n,
            source=r.get("source", "") or "",
        )


def read_log(path: Path = LOG_PATH) -> list[LogEntry]:
    if not path.exists():
        return []
    with path.open() as f:
        return [LogEntry.from_row(r) for r in csv.DictReader(f)]


def last_entry(path: Path = LOG_PATH) -> Optional[LogEntry]:
    entries = read_log(path)
    return entries[-1] if entries else None


def is_meaningful_change(prev: Optional[LogEntry],
                         base: str,
                         resolved: str,
                         lifted: bool) -> bool:
    """True if (base, resolved, lifted) differs from the last logged
    entry. We deliberately do NOT key on `recent_abs_error_pp` —
    that would spam the log with every micro-drift in the rolling
    window. Tier/flag transitions are the events worth archiving."""
    if prev is None:
        return True
    if prev.base != base:
        return True
    if prev.resolved != resolved:
        return True
    if prev.lifted != lifted:
        return True
    return False


def append_entry(entry: LogEntry, path: Path = LOG_PATH) -> None:
    """Append one row. Creates the file with a header if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        ae = ("" if entry.recent_abs_error_pp is None
              else f"{entry.recent_abs_error_pp:.4f}")
        w.writerow({
            "ts": entry.ts,
            "base": entry.base,
            "resolved": entry.resolved,
            "lifted": "True" if entry.lifted else "False",
            "recent_abs_error_pp": ae,
            "recent_n": entry.recent_n,
            "source": entry.source,
        })
        f.flush()


def record_if_changed(base: str,
                      resolved: str,
                      lifted: bool,
                      recent_abs_error_pp: Optional[float],
                      recent_n: int,
                      source: str = "advisor-invocation",
                      path: Path = LOG_PATH,
                      now: Optional[datetime] = None) -> bool:
    """Compare the supplied state against the last logged entry;
    append a new row only when (base, resolved, lifted) has changed.
    Returns True if a row was written. Best-effort caller: wrap in
    try/except in the advisor so a logging failure never blocks
    the verdict."""
    prev = last_entry(path)
    if not is_meaningful_change(prev, base, resolved, lifted):
        return False
    if now is None:
        now = datetime.now()
    entry = LogEntry(
        ts=now.isoformat(timespec="seconds"),
        base=base,
        resolved=resolved,
        lifted=lifted,
        recent_abs_error_pp=recent_abs_error_pp,
        recent_n=recent_n,
        source=source,
    )
    append_entry(entry, path)
    return True


def pretty_print(entries: list[LogEntry]) -> None:
    if not entries:
        print("(no confidence-lift events logged yet)")
        return
    print("=== Confidence-lift history ===")
    print(f"{'timestamp':<19}  {'base':<6}  {'resolved':<8}  "
          f"{'lifted':<6}  {'abs err':>7}  {'n':>3}  source")
    print("-" * 76)
    for e in entries:
        ae = "—" if e.recent_abs_error_pp is None else f"{e.recent_abs_error_pp:5.2f}"
        flag = "yes" if e.lifted else "no"
        print(f"{e.ts:<19}  {e.base:<6}  {e.resolved:<8}  "
              f"{flag:<6}  {ae:>7}  {e.recent_n:3d}  {e.source}")
    print()
    last = entries[-1]
    if last.lifted:
        print(f"current state: lifted from '{last.base}' to '{last.resolved}'")
    else:
        print(f"current state: not lifted (resolved = '{last.resolved}')")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="just print the log; don't record")
    args = ap.parse_args()
    if args.show:
        pretty_print(read_log())
        return 0
    # Without --show this CLI is a no-op (the advisor invocation is
    # the canonical recorder; manual invocation has no source state
    # to log). Print the current log as a convenience.
    pretty_print(read_log())
    return 0


if __name__ == "__main__":
    sys.exit(main())
