"""Detect meaningful events in pack data.

Shared between scripts/analyze.py (offline analysis) and
scripts/dashboard.py (live UI). Operates on a generic iterable of dicts
with these fields:

    ts          : datetime
    pack_i      : float | None
    max_soc     : float | None
    min_soc     : float | None
    state       : str

Event-detection rules — chosen to match the actual loads observed at
The Barge Inn on 2026-05-17:

    GENERATOR ON   — pack_i crosses +30A going up, sustained ≥30 s
    generator off  — pack_i crosses +30A going down, sustained ≥30 s
    heavy load on  — pack_i crosses -10A going down, sustained ≥30 s
    heavy load off — pack_i crosses -10A going up, sustained ≥30 s
    FULL banner    — first time max_soc ≥ 95
    LOW tier       — first time min_soc ≤ 25
    STATE: full    — first time state == "full"

Thresholds + persistence times can be tuned via the kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass
class Event:
    ts: datetime
    kind: str      # "GENERATOR ON", "generator off", "FULL banner", etc.
    descriptor: str
    severity: str  # "info" | "warning" | "good" — for UI styling

    def to_dict(self) -> dict:
        return {
            "ts": self.ts.isoformat(timespec="seconds"),
            "kind": self.kind,
            "descriptor": self.descriptor,
            "severity": self.severity,
        }


# (kind, severity, threshold, direction, persist_s)
_CURRENT_RULES = [
    ("GENERATOR ON",  "good",    30.0,  "up",   30.0),
    ("generator off", "info",    30.0,  "down", 30.0),
    ("heavy load on", "warning", -10.0, "down", 30.0),
    ("heavy load off","info",    -10.0, "up",   30.0),
]


def _crossings(
    rows: list[dict],
    field: str,
    threshold: float,
    going: str,
    persist_s: float,
) -> list[int]:
    """Indices where rows[i][field] crosses threshold in the requested
    direction AND stays past it for >= persist_s seconds."""
    out: list[int] = []
    was_past: bool | None = None
    for i, r in enumerate(rows):
        v = r.get(field)
        if v is None:
            continue
        is_past = (v >= threshold) if going == "up" else (v <= threshold)
        if was_past is False and is_past:
            t_cross = r["ts"]
            ok = True
            for j in range(i + 1, len(rows)):
                dt = (rows[j]["ts"] - t_cross).total_seconds()
                if dt > persist_s:
                    break
                vj = rows[j].get(field)
                if vj is None:
                    continue
                if (going == "up" and vj < threshold) or (going == "down" and vj > threshold):
                    ok = False
                    break
            if ok:
                out.append(i)
        was_past = is_past
    return out


def detect_events(rows: Iterable[dict]) -> list[Event]:
    rows = list(rows)
    if not rows:
        return []

    events: list[Event] = []

    for kind, severity, threshold, going, persist_s in _CURRENT_RULES:
        for i in _crossings(rows, "pack_i", threshold, going, persist_s):
            pi = rows[i].get("pack_i")
            events.append(Event(rows[i]["ts"], kind, f"{pi:+.1f}A" if pi is not None else "—", severity))

    # First-time SOC threshold crossings — only fired once per data window
    seen_full = seen_low = seen_state_full = False
    for r in rows:
        if not seen_full and r.get("max_soc") is not None and r["max_soc"] >= 95:
            events.append(Event(r["ts"], "FULL banner", f"max SOC {r['max_soc']:.0f}%", "good"))
            seen_full = True
        if not seen_low and r.get("min_soc") is not None and r["min_soc"] <= 25:
            events.append(Event(r["ts"], "LOW tier", f"min SOC {r['min_soc']:.0f}%", "warning"))
            seen_low = True
        if not seen_state_full and r.get("state") == "full":
            events.append(Event(r["ts"], "STATE: full", "", "good"))
            seen_state_full = True
        if seen_full and seen_low and seen_state_full:
            break

    events.sort(key=lambda e: e.ts)
    return events
