#!/usr/bin/env python3
"""status_check.py — reconstruct the reader's health over a time window.

Answers "did anything happen in the last N hours worth eyeballing?" by
triangulating three data sources so a narrow grep can't hide an incident:

  1. Railway /api/readings — time gaps + partial-row streaks (one battery
     silent while the other keeps reporting)
  2. Railway /api/events   — wedge_snapshot classifications, stack_health
     with non-clean classification, adapter pin/fallback/restored events
  3. (optional --with-pi)  — SSHs to kwpi.zt for logger WARNING/ERROR
     line counts + last-24h restart counters + throttled register

Prints one section per source and a bottom-line "notable events" summary.
Exit 0 = quiet window, 1 = anything worth investigating.

Usage:
    scripts/status_check.py                        # last 24h, no SSH
    scripts/status_check.py --hours 6
    scripts/status_check.py --with-pi              # add SSH probes
    scripts/status_check.py --source pi-barge      # override default source
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from typing import Optional

RAILWAY = "https://volts.alti2.de"
DEFAULT_SOURCE = "pi-barge"
DEFAULT_SSH_TARGET = "kaan@kwpi.zt"

# Thresholds matching the alerting side (cloud/server/staleness.py) so the
# tool flags the same conditions the ntfy pushes fire on.
STALENESS_THRESHOLD_S = 300
BATTERY_SILENT_THRESHOLD_S = 15 * 60


# ---- HTTP helpers --------------------------------------------------------

def _get_json(path: str) -> dict:
    with urllib.request.urlopen(RAILWAY + path, timeout=20) as r:
        return json.load(r)


def fetch_events(kind: str, since_iso: str, limit: int = 10_000) -> list[dict]:
    d = _get_json(f"/api/events?event={kind}&limit={limit}")
    return [e for e in d.get("events", []) if e["ts"] >= since_iso]


def fetch_readings(source: str, limit: int = 10_000) -> list[dict]:
    """Returns newest-first. API caps `limit` at 10 000 — at ~10 s cadence
    that's about 27 h of data, comfortably more than the default 24 h window."""
    d = _get_json(f"/api/readings?source_id={source}&limit={limit}")
    # API returns rows under either "readings" or "rows" depending on version
    return d.get("readings") or d.get("rows") or []


# ---- Analysis ------------------------------------------------------------

def _parse_ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def find_time_gaps(rows: list[dict], min_gap_s: float) -> list[tuple]:
    """Return (gap_s, earlier_ts, later_ts), sorted worst-first. `rows` are
    newest-first from the API; we reverse to chronological here."""
    times = sorted(_parse_ts(r["ts"]) for r in rows if r.get("ts"))
    out = []
    for i in range(len(times) - 1):
        g = (times[i + 1] - times[i]).total_seconds()
        if g >= min_gap_s:
            out.append((g, times[i].isoformat(), times[i + 1].isoformat()))
    return sorted(out, reverse=True)


def find_partial_runs(
    rows: list[dict], min_duration_s: float
) -> list[tuple[str, str, str, float]]:
    """Runs where exactly one battery reported. Returns
    (which, start_ts, end_ts, duration_s), sorted longest-first.

    `which` is "A" or "B" — the battery that WAS reporting during the run
    (the other one is the silent one you'd want to alert on)."""
    events = []
    for r in reversed(rows):  # chronological
        a_ok = r.get("soc_a") is not None or r.get("v_a") is not None
        b_ok = r.get("soc_b") is not None or r.get("v_b") is not None
        if a_ok and b_ok:
            typ = "both"
        elif a_ok:
            typ = "A"
        elif b_ok:
            typ = "B"
        else:
            typ = "neither"
        events.append((r["ts"], typ))
    if not events:
        return []
    runs: list[tuple[str, str, str]] = []
    cur_typ, cur_start = events[0][1], events[0][0]
    last_ts = events[0][0]
    for ts, typ in events[1:]:
        if typ != cur_typ:
            runs.append((cur_typ, cur_start, last_ts))
            cur_typ, cur_start = typ, ts
        last_ts = ts
    runs.append((cur_typ, cur_start, last_ts))
    out = []
    for typ, st, en in runs:
        if typ in ("both", "neither"):
            continue
        dur = (_parse_ts(en) - _parse_ts(st)).total_seconds()
        if dur >= min_duration_s:
            out.append((typ, st, en, dur))
    return sorted(out, key=lambda r: r[3], reverse=True)


# ---- Sections ------------------------------------------------------------

def section_readings(source: str, since_iso: str) -> tuple[bool, list[str]]:
    rows = [r for r in fetch_readings(source) if r["ts"] >= since_iso]
    # Enforce ordering rather than trusting the API's default — we care about
    # "which row was actually newest" for the freshness computation.
    rows.sort(key=lambda r: r["ts"], reverse=True)
    lines = [f"Readings for source={source} since {since_iso}: {len(rows)} rows"]
    notable = False
    if not rows:
        lines.append("  (no rows in window — extremely stale or wrong source)")
        return True, lines
    # Freshness
    latest = _parse_ts(rows[0]["ts"])
    age = (dt.datetime.now(dt.timezone.utc) - latest).total_seconds()
    freshness = f"  latest row: {rows[0]['ts']} (age {int(age)}s)"
    if age > STALENESS_THRESHOLD_S:
        freshness += "  ← STALE"
        notable = True
    lines.append(freshness)
    # Time gaps
    gaps = find_time_gaps(rows, min_gap_s=60)
    if gaps:
        alerting_gaps = [g for g in gaps if g[0] > STALENESS_THRESHOLD_S]
        header = f"  time gaps > 60s: {len(gaps)} total"
        if alerting_gaps:
            header += f", {len(alerting_gaps)} would fire stale-push"
            notable = True
        lines.append(header)
        for g, a, b in gaps[:5]:
            tag = "  STALE" if g > STALENESS_THRESHOLD_S else ""
            lines.append(f"    {g:>6.0f}s   {a}  →  {b}{tag}")
    else:
        lines.append("  time gaps > 60s: none")
    # Partial-row runs (one battery silent)
    runs = find_partial_runs(rows, min_duration_s=BATTERY_SILENT_THRESHOLD_S)
    if runs:
        lines.append(f"  battery-silent stretches ≥ 15 min: {len(runs)}")
        for reporting, st, en, dur in runs[:5]:
            silent = "B" if reporting == "A" else "A"
            lines.append(
                f"    battery {silent} silent  {st}  →  {en}   "
                f"({int(dur)}s = {int(dur / 60)} min; {reporting} kept reporting)"
            )
        notable = True
    else:
        lines.append("  battery-silent stretches ≥ 15 min: none")
    return notable, lines


def section_events(since_iso: str) -> tuple[bool, list[str]]:
    lines = ["Events (Railway ble_events since window start):"]
    notable = False
    # Wedges
    wedges = fetch_events("wedge_snapshot", since_iso)
    if wedges:
        by_cls = Counter(w["data"].get("classification", "?") for w in wedges)
        by_lvl = Counter(w["data"].get("recovery_level", "?") for w in wedges)
        lines.append(
            f"  wedge_snapshot: {len(wedges)}   levels={dict(by_lvl)}   "
            f"classes={dict(by_cls)}"
        )
        if any(int(w["data"].get("recovery_level", 0) or 0) >= 2 for w in wedges):
            notable = True
        for w in wedges[:5]:
            d = w["data"]
            p = d.get("power_thermal") or {}
            lines.append(
                f"    {w['ts']}  L{d.get('recovery_level')}  "
                f"{d.get('classification','?')}   throttled={p.get('throttled_hex','?')}"
            )
    else:
        lines.append("  wedge_snapshot: none")
    # stack_health with non-clean classification. "healthy" and
    # "unclassified" both count as clean; anything else (e.g.
    # peer_silent_ambient_corroborated firing on a periodic snapshot,
    # or legacy classifications from before the health-vs-wedge split)
    # gets flagged.
    health = fetch_events("stack_health", since_iso)
    non_clean = [
        e for e in health
        if (e["data"].get("classification") not in (None, "", "unclassified", "healthy"))
    ]
    if non_clean:
        by_cls = Counter(e["data"].get("classification") for e in non_clean)
        lines.append(
            f"  stack_health non-clean: {len(non_clean)} of {len(health)}   "
            f"classes={dict(by_cls)}"
        )
        notable = True
    else:
        lines.append(f"  stack_health: {len(health)} events, all clean")
    # Adapter transitions
    for kind in ("adapter_pin_failed", "adapter_fallback", "adapter_restored"):
        evs = fetch_events(kind, since_iso, limit=500)
        if evs:
            lines.append(f"  {kind}: {len(evs)}")
            for e in evs[:3]:
                lines.append(f"    {e['ts']}  {json.dumps(e['data'])[:140]}")
            notable = True
    # Phase 2A: ambient-gated recovery skips — highlight prominently
    # because they represent the gate doing its job (preventing wasted
    # destructive recovery when the wedge is peer-side).
    skipped = fetch_events("recovery_skipped", since_iso, limit=500)
    if skipped:
        lines.append(f"  recovery_skipped: {len(skipped)}  ← ambient gate prevented "
                     f"pointless recovery escalation")
        for e in skipped[:5]:
            d = e['data']
            lines.append(
                f"    {e['ts']}  reason={d.get('reason')}  "
                f"would_have={d.get('would_have', 'escalate')}  "
                f"scan_errors={d.get('scan_errors','?')}"
            )
        notable = True
    # peer-silent classifications: these are the Iter-12 class that
    # motivated Phase 2A. Callers can now cleanly see which wedges are
    # in this bucket vs the reader-side (Family B) ones.
    peer_silent = [
        w for w in wedges
        if w["data"].get("classification") == "peer_silent_ambient_corroborated"
    ]
    if peer_silent:
        lines.append(f"  wedges classified peer_silent_ambient_corroborated: "
                     f"{len(peer_silent)}")
    return notable, lines


def section_pi(ssh_target: str, hours: int) -> tuple[bool, list[str]]:
    """Optional — SSH into the Pi for logger warnings / throttled / uptime."""
    lines = [f"Pi diagnostics (ssh {ssh_target}):"]
    notable = False
    try:
        out = subprocess.check_output(
            ["ssh", "-o", "ConnectTimeout=8", ssh_target,
             f"uptime; vcgencmd get_throttled; "
             f"sudo systemctl show -p NRestarts volthium-logger "
             f"volthium-uploader volthium-events-uploader volthium-dashboard "
             f"| tr '\\n' ' '; echo; "
             f"sudo journalctl -u volthium-logger --since '{hours} hours ago' "
             f"--no-pager | grep -cE 'WARNING|ERROR'"],
            timeout=30, text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        lines.append(f"  (Pi unreachable: {exc})")
        return False, lines
    for line in out.strip().splitlines():
        lines.append(f"  {line}")
    if "throttled=0x0" not in out:
        notable = True
    if "NRestarts=0" in out and out.count("NRestarts=0") < 4:
        notable = True
    # Last line of the output is the warning/error count
    try:
        warn_count = int(out.strip().splitlines()[-1])
        if warn_count > 0:
            notable = True
            lines.append(f"  ← logger has {warn_count} WARNING/ERROR "
                         f"lines in the last {hours}h")
    except (ValueError, IndexError):
        pass
    return notable, lines


# ---- Main ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--hours", type=float, default=24.0,
                    help="how many hours back to scan (default 24)")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help=f"source_id to check (default {DEFAULT_SOURCE})")
    ap.add_argument("--with-pi", action="store_true",
                    help=f"also SSH to {DEFAULT_SSH_TARGET} for logger diag")
    ap.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET,
                    help="override the ssh target for --with-pi")
    args = ap.parse_args()

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"=== status_check.py  window: last {args.hours}h  "
          f"(since {since_iso}) ===\n")

    any_notable = False
    try:
        n, lines = section_readings(args.source, since_iso)
        any_notable |= n
        print("\n".join(lines) + "\n")
        n, lines = section_events(since_iso)
        any_notable |= n
        print("\n".join(lines) + "\n")
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"HTTP error against {RAILWAY}: {exc}", file=sys.stderr)
        return 2

    if args.with_pi:
        n, lines = section_pi(args.ssh_target, int(args.hours))
        any_notable |= n
        print("\n".join(lines) + "\n")

    tag = "NOTABLE — investigate above" if any_notable else "quiet window"
    print(f"=== bottom line: {tag} ===")
    return 1 if any_notable else 0


if __name__ == "__main__":
    sys.exit(main())
