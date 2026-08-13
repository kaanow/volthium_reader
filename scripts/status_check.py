#!/usr/bin/env python3
"""status_check.py — reconstruct the reader's health over a time window.

Answers "did anything happen in the last N hours worth eyeballing?" by
triangulating three data sources so a narrow grep can't hide an incident:

  1. Railway /api/readings — time gaps + partial-row streaks (one battery
     silent while the other keeps reporting)
  2. Railway /api/events   — wedge_snapshot classifications, stack_health
     with non-clean classification, adapter pin/fallback/restored events
  3. Railway /api/solar    — solar pipeline freshness against the reader's
     OWN batch cadence, plus schema-skew (schema_version, pv_v_min/max)
  4. Railway /api/events   — wired RS485 path (primary since the 2026-07-26
     BLE retirement): read_fail rate, rs485_port_error/restart, live transport
  5. Railway /healthz + Pi — BOTH paging paths, reported separately
  6. (optional --with-pi)  — SSHs to kwpi.zt for logger WARNING/ERROR
     line counts + last-24h restart counters + throttled register

Note that source 2 is now DEAD by design (BLE retired) and says so rather
than printing zeros; see section_events.

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


def fetch_events(kind: str, since_iso: str | None,
                 limit: int = 10_000) -> list[dict]:
    """`since_iso=None` means "no window" — used to ask when a family was last
    seen AT ALL, which is how a retired event source is told apart from a
    healthy quiet one. The endpoint returns newest-first."""
    d = _get_json(f"/api/events?event={kind}&limit={limit}")
    evs = d.get("events", [])
    return evs if since_iso is None else [e for e in evs if e["ts"] >= since_iso]


def fetch_readings(
    source: str, since: str | None = None, limit: int = 10_000
) -> list[dict]:
    """Fetch readings. With `since` (ISO ts) the server returns only rows
    after it — we only ever analyze a bounded window, so passing `since`
    avoids re-downloading the full history every run (was ~7.5 MB/call; the
    windowed fetch is a fraction of that, and the server now gzips too)."""
    q = f"/api/readings?source_id={source}&limit={limit}"
    if since:
        q += f"&since={since}"
    d = _get_json(q)
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
    # Fetch only the window (server-side `since`) instead of the full history.
    rows = [r for r in fetch_readings(source, since=since_iso) if r["ts"] >= since_iso]
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


# Every event family section_events() watches is emitted ONLY by the BLE
# logger (scripts/log.py / volthium/pack.py), retired 2026-07-26. Confirmed by
# asking the database when each was last seen: wedge_snapshot 07-25T13:57,
# stack_health 07-26T05:55, recovery_skipped 07-25T13:55, ambient_burst
# 07-25T13:57. Nothing has produced one since.
#
# So this section printed "wedge_snapshot: none" and "stack_health: 0 events,
# all clean" on every run for sixteen days and could not have printed anything
# else. That is the volthium-logger precedent exactly — a permanent reassuring
# zero from a source that no longer exists — and it is the second time in this
# file. The 2-hourly operator prompt asks specifically about wedge_snapshot.
#
# Not deleted, because BLE is retired rather than removed and the families
# would come back with it. Instead the section asks the DATABASE whether each
# family is still alive and says so. Nothing is hardcoded as dead: a family
# that starts producing again reports normally on the next run.
EVENT_FAMILY_DEAD_AFTER_S = 7 * 86400


def _family_last_seen(kind: str) -> Optional[str]:
    """Timestamp of the most recent event of this kind EVER, or None."""
    evs = fetch_events(kind, None, limit=1)
    return evs[0]["ts"] if evs else None


def _dead_families(kinds: tuple[str, ...]) -> list[tuple[str, Optional[str]]]:
    out = []
    now = dt.datetime.now(dt.timezone.utc)
    for k in kinds:
        ts = _family_last_seen(k)
        if ts is None:
            out.append((k, None))
            continue
        age = (now - dt.datetime.strptime(
            ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc))
        if age.total_seconds() > EVENT_FAMILY_DEAD_AFTER_S:
            out.append((k, ts[:16]))
    return out


WATCHED_EVENT_FAMILIES = (
    "wedge_snapshot", "stack_health", "recovery_skipped", "ambient_burst",
)


def section_events(since_iso: str) -> tuple[bool, list[str]]:
    lines = ["Events (Railway ble_events since window start):"]
    notable = False

    # Liveness FIRST, so a dead family can never be read as a clean one.
    dead = _dead_families(WATCHED_EVENT_FAMILIES)
    if len(dead) == len(WATCHED_EVENT_FAMILIES):
        lines.append("  ** THIS WHOLE SECTION IS DEAD. Every event family "
                     "below is emitted only by the BLE logger,")
        lines.append("     retired 2026-07-26. A 'none' here means the "
                     "producer is gone, NOT that the system is healthy.")
        for k, ts in dead:
            lines.append(f"       {k:<20} last seen {ts or 'never'}")
        lines.append("     RS485 is the live path — see the 'Wired RS485' "
                     "section, which is the one that can still fail.")
        return notable, lines
    for k, ts in dead:
        lines.append(f"  ({k}: no producer since {ts or 'ever'} — reported "
                     f"below as 'none' for that reason, not for health)")
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


def section_alerting(ssh_target: str | None = None) -> tuple[bool, list[str]]:
    """Are the paging paths armed? There are TWO, and they fail separately.

      A. cloud -> ntfy. The staleness and event monitors on Railway, gated on
         STALENESS_WEBHOOK_URL. /healthz reports this as alerting=on|off.
      B. Pi -> webhook. The uploader paging when it cannot reach the CLOUD,
         gated on VOLTHIUM_ALERT_WEBHOOK in the uploader's environment.

    B exists precisely because A cannot cover its own outage: if Railway is
    down or unreachable, the thing that would page about it is the thing that
    is down. So "is alerting armed" is not one question.

    Until 2026-08-11 this section asked only A and printed "staleness + event
    alerts armed", which reads as all-clear. B was dormant the whole time —
    VOLTHIUM_ALERT_WEBHOOK has never been set on the Pi — so the check was
    green about the half that works while the half that covers the cloud going
    dark was off.

    B is only observable from the Pi, so without --with-pi it is reported as
    UNVERIFIED rather than omitted. A check must not render the same
    reassuring output for "absent" and "healthy"; that is exactly how the
    volthium-logger check stayed green for months.
    """
    lines = ["Alerting (two independent paths):"]
    notable = False

    try:
        with urllib.request.urlopen(RAILWAY + "/healthz", timeout=20) as r:
            body = r.read().decode("utf-8", "replace").strip()
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        notable = True
        lines.append(f"  A cloud->ntfy   !! /healthz unreachable: {exc}")
    else:
        if "alerting=on" in body:
            lines.append("  A cloud->ntfy   armed (STALENESS_WEBHOOK_URL set) "
                         "— pages on stale telemetry and incident events")
        elif "alerting=off" in body:
            notable = True
            lines.append("  A cloud->ntfy   ← NOT ARMED: STALENESS_WEBHOOK_URL "
                         "unset on the server. Nothing pages on stale")
            lines.append("                     telemetry or on incident events.")
        else:
            # Older deploys answer a bare "ok" and cannot report either way.
            lines.append(f"  A cloud->ntfy   unknown — server predates the "
                         f"alerting flag ({body!r})")

    if ssh_target is None:
        lines.append("  B pi->webhook   UNVERIFIED — needs --with-pi. This is "
                     "the path that fires when the CLOUD is")
        lines.append("                     unreachable, so path A cannot "
                     "substitute for it.")
        return notable, lines

    try:
        out = subprocess.check_output(
            ["ssh", ssh_target, "-o", "ConnectTimeout=8",
             "systemctl show volthium-uploader -p Environment "
             "-p EnvironmentFiles --no-pager"],
            timeout=30, text=True,
        )
    # OSError, not just FileNotFoundError: a transport-level failure (no route
    # to host, connection reset) raises plain OSError, and an uncaught one here
    # takes down the whole section — a health check that dies is worse than one
    # that reports "could not look". Caught by the test that raises OSError.
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError) as exc:
        lines.append(f"  B pi->webhook   UNVERIFIED — Pi unreachable: {exc}")
        return notable, lines

    # Only the presence of the name is checked, never its value: the webhook
    # URL embeds a secret ntfy topic and must not land in check output.
    if "VOLTHIUM_ALERT_WEBHOOK=" in out:
        lines.append("  B pi->webhook   armed (VOLTHIUM_ALERT_WEBHOOK set) "
                     "— pages if the Pi cannot reach the cloud")
    else:
        notable = True
        lines.append("  B pi->webhook   ← NOT ARMED: VOLTHIUM_ALERT_WEBHOOK "
                     "unset on the Pi. If the cloud goes dark or the")
        lines.append("                     uploader stalls, nothing pages. "
                     "Path A cannot report its own outage.")
    return notable, lines


def section_solar(source: str) -> tuple[bool, list[str]]:
    """Solar pipeline freshness and schema, with a threshold that matches how
    the pipeline actually works.

    This check existed only as a line in the operator's 2-hourly prompt —
    "GET /api/solar?limit=2, confirm rows are FRESH (<2 min)" — performed by
    hand every run. Both halves of it are wrong, which is what happens to a
    check that is never codified:

    1. **The 2-minute threshold contradicts the design.** The reader seals and
       uploads in batches (`xanbus_telemetry.UPLOAD_PERIOD_S`, 300 s), so the
       lag is a SAWTOOTH from ~0 to ~300 s. Measured 2026-08-11 at 45 s
       intervals: 31, 76, 121, 166, 212, 257 s, then reset. A 2-minute rule
       therefore reports a false problem roughly 60% of the time, with nothing
       wrong. Codified here against the actual cadence instead.
    2. **`limit=2` reads the wrong rows.** `/api/solar` returns
       OLDEST-FIRST, so the first two entries are the two oldest of the slice,
       not the newest. Always take `max(ts)`.

    The failure this SHOULD catch is a growing backlog — the reader spooling
    faster than it can upload — which shows up as a lag of several batch
    periods rather than one. That is what the threshold keys on.
    """
    lines = ["Solar pipeline (xanbus telemetry -> Railway):"]
    try:
        from xanbus_telemetry import UPLOAD_PERIOD_S as BATCH_S
    except Exception:                      # pragma: no cover - import guard
        BATCH_S = 300.0
    rows = _get_json(f"/api/solar?source_id={source}&limit=200").get("readings", [])
    if not rows:
        return True, lines + ["  !! no solar rows at all"]

    newest = max(r["ts"] for r in rows)    # NOT rows[0] — see docstring
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(
        newest[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc)).total_seconds()

    # One batch period is normal by construction. Two is a missed batch and
    # worth saying. Beyond that the reader is falling behind.
    notable = age > 2.5 * BATCH_S
    verdict = ("BACKLOG — falling behind, check the Pi spool"
               if notable else
               "behind by more than one batch" if age > 2 * BATCH_S else
               "normal (batched upload, sawtooth 0..%ds)" % BATCH_S)
    lines.append(f"  newest row {newest}  lag {age:.0f}s / batch {BATCH_S:.0f}s"
                 f"  -> {verdict}")

    latest = max(rows, key=lambda r: r["ts"])
    sv = latest.get("schema_version")
    if sv != 2:
        notable = True
        lines.append(f"  !! schema_version={sv!r}, expected 2 — reader/server skew")
    missing = [k for k in ("pv_v_min", "pv_v_max") if latest.get(k) is None]
    if missing:
        notable = True
        lines.append(f"  !! {', '.join(missing)} is None — reader/server schema skew")
    else:
        lines.append(f"  schema_version={sv}, pv_v_min/max populated, "
                     f"pv_v={latest.get('pv_v')}")
    return notable, lines


def section_wired(since_iso: str) -> tuple[bool, list[str]]:
    """Wired RS485 path health — the PRIMARY telemetry path since the BLE
    retirement (2026-07-26). Watches serial read failures, port errors/reopens
    and logger restarts, and confirms telemetry is still actually sourced from
    RS485 (a silent revert to another transport would otherwise hide here)."""
    lines = ["Wired RS485 path (primary since BLE retirement):"]
    notable = False
    # read_fail: a serial read that returned nothing. The odd single-cycle
    # timeout self-heals next poll (benign, like the BLE dormancy blips); a
    # steady stream means a flaky adapter / loose USB worth investigating.
    fails = fetch_events("read_fail", since_iso, limit=2000)
    if fails:
        by_addr = Counter(f["data"].get("address", "neither-answered") for f in fails)
        lines.append(f"  read_fail: {len(fails)} in window   by_addr={dict(by_addr)}")
        if len(fails) >= 10:
            notable = True
            lines.append("    ← elevated read-failure rate; check the adapter/USB")
    else:
        lines.append("  read_fail: none")
    # Port errors force a serial reopen; logger stop/start bracket a restart.
    for kind in ("rs485_port_error", "rs485_stop", "rs485_start"):
        evs = fetch_events(kind, since_iso, limit=500)
        if evs:
            lines.append(f"  {kind}: {len(evs)}")
            for e in evs[:3]:
                lines.append(f"    {e['ts']}  {json.dumps(e['data'])[:140]}")
            if kind == "rs485_port_error":
                notable = True
    # Confirm the live transport is still RS485 (not silently degraded).
    recent = fetch_events("read_ok", since_iso, limit=1)
    if recent:
        tr = recent[0]["data"].get("transport", "?")
        lines.append(f"  latest read_ok transport: {tr}")
        if tr != "rs485":
            lines.append("    ← telemetry NOT sourced from RS485 — path degraded!")
            notable = True
    return notable, lines



# The guard and the config watch are TIMERS. `_parse_units` deliberately only
# looks at services, so until 2026-08-12 nothing checked either of them: both
# could be disabled and this whole tool would still print a quiet window. That
# is the volthium-logger precedent for the third time in one file.
#
# What is CHECKED is ActiveState — a disabled or failed timer is flagged. The
# last-fire age is PRINTED but deliberately not thresholded: doing that needs a
# per-timer period, and the timers here range from 5 minutes to monthly, so any
# single bound is either useless or wrong. Printing the age lets a human see a
# stalled timer without this code inventing a rule it cannot justify. Saying
# "armed" and meaning "ActiveState=active" is the honest claim; an earlier
# draft said "firing on schedule" while the staleness parse was silently
# failing, which is exactly the false all-clear being fixed here.



def _check_git_sync(out: str) -> tuple[bool, list[str]]:
    """Does the Pi's working tree match origin/main?

    Reports DIRTY (files whose content differs) separately from BEHIND
    (commits not merged), because they fail differently: behind-but-clean is a
    tree that was never updated, while dirty-but-current is a hand-edit that
    will be silently clobbered by the next sync. The 2026-08-13 drift was both.
    """
    f = {}
    for tok in out.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            f[k] = v
    if "HEAD" not in f:
        return True, ["  ← git sync: probe returned nothing — cannot confirm "
                      "the Pi is running the committed code"]
    behind = int(f.get("BEHIND", "0") or 0)
    dirty = int(f.get("DIRTY", "0") or 0)
    if not behind and not dirty:
        return False, [f"  git: IN SYNC with origin/main ({f['HEAD']})"]
    lines = [f"  ← git OUT OF SYNC: HEAD {f.get('HEAD')} vs origin/main "
             f"{f.get('ORIGIN')}, {behind} commits behind, "
             f"{dirty} code files differ"]
    for path in out.splitlines()[1:6]:
        if path.strip():
            lines.append(f"      {path.strip()}")
    lines.append("      the Pi may not be running the code you are reading")
    return True, lines

def _check_timers(out: str) -> tuple[bool, list[str]]:
    rows = [l.split() for l in out.splitlines() if l.startswith("TIMER ")]
    if not rows:
        # "no output" is NOT "no timers" — say so rather than passing quietly.
        return True, ["  ← timers: probe returned nothing (NOT the same as "
                      "'no timers exist') — cannot confirm the guard is armed"]
    notable = False
    lines: list[str] = []
    armed = 0
    for r in rows:
        if len(r) < 4:
            continue
        _, tid, state, age = r[0], r[1], r[2], r[3]
        try:
            age_s = int(age)
        except ValueError:
            age_s = -1
        if state != "active":
            notable = True
            lines.append(f"  ← {tid} is {state} — NOT ARMED")
            continue
        armed += 1
        when = "never fired" if age_s < 0 else f"last fired {age_s/60:.0f} min ago"
        lines.append(f"    {tid}: active, {when}")
    lines.insert(0, f"  timers: {armed} of {len(rows)} ACTIVE "
                    f"(ages shown for eyeballing; not thresholded — see note)")
    return notable, lines


def section_pi(ssh_target: str, hours: int) -> tuple[bool, list[str]]:
    """Optional — SSH into the Pi for service health / throttled / uptime.

    Asks systemd which services exist rather than naming them. The previous
    version hardcoded `volthium-logger`, the BLE logger, and kept checking it
    for months after RS485 became the primary transport on 2026-07-26. That
    unit is disabled and dead, so its restart count and error count were both
    a permanent, reassuring zero — a health check reporting on a service that
    was not running. The live logger, `volthium-rs485-logger`, was never
    checked at all.

    The rule that replaces it maintains itself: a service that is
    UnitFileState=enabled must be ActiveState=active. Timer-driven units
    (latch-guard, config-watch) are static or disabled and correctly excluded,
    since being inactive between firings is their normal state — and so is a
    retired unit, which is what makes this drift-proof rather than merely
    corrected.
    """
    lines = [f"Pi diagnostics (ssh {ssh_target}):"]
    notable = False
    # NOTE: ssh flags go AFTER the host on this machine — see memory
    # `kwpi-ssh-paths`. Flags before the host hit a DNS resolution quirk.
    # TIMERS TOO. The service rule below explicitly excludes timer-driven
    # units because "being inactive between firings is their normal state" —
    # true, but it meant NOTHING checked the timers themselves. The latch guard
    # and the config watch are both timers. Either could be disabled and this
    # check would stay green, which is the volthium-logger precedent for the
    # third time in this file.
    #
    # A timer is healthy if it is ACTIVE (loaded and scheduled) and has fired
    # RECENTLY. "Recently" is derived from its own configured period, not
    # hardcoded, so retuning the guard's cadence cannot silently break this.
    # Age is computed ON THE PI. `LastTriggerUSec` renders as a human date in
    # the local zone ("Wed 2026-08-12 18:42:34 PDT"), not microseconds, and a
    # first attempt to parse it here failed silently into "unreadable" while
    # still printing "firing on schedule" — a false all-clear, which is the
    # thing this check exists to remove. `date -d` on the box has the zone.
    timer_probe = (
        "for t in $(systemctl list-units 'volthium-*.timer' --no-legend "
        "--plain --all | awk '{print $1}'); do "
        "  st=$(systemctl show $t -p ActiveState --value); "
        "  lt=$(systemctl show $t -p LastTriggerUSec --value); "
        "  if [ -n \"$lt\" ] && [ \"$lt\" != \"n/a\" ]; then "
        "    age=$(( $(date +%s) - $(date -d \"$lt\" +%s) )); else age=-1; fi; "
        "  echo \"TIMER $t $st $age\"; done"
    )
    probe = (
        "uptime; vcgencmd get_throttled; "
        "systemctl show 'volthium-*.service' -p Id -p ActiveState "
        "-p UnitFileState -p NRestarts --no-pager | tr '\\n' '|'; echo; "
        f"sudo journalctl --since '{hours} hours ago' -p warning --no-pager "
        "$(systemctl list-units 'volthium-*.service' --no-legend --plain "
        "--state=active | awk '{printf \" -u \"$1}') 2>/dev/null "
        "| grep -cE 'WARNING|ERROR|Failed' || true"
    )
    try:
        out = subprocess.check_output(
            ["ssh", ssh_target, "-o", "ConnectTimeout=8", probe],
            timeout=45, text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as exc:
        lines.append(f"  (Pi unreachable: {exc})")
        return False, lines

    body = out.strip().splitlines()
    for line in body:
        if "|Id=" in line or line.startswith("Id="):
            continue
        if line.strip().isdigit() and line is body[-1]:
            continue
        lines.append(f"  {line}")

    if "throttled=0x0" not in out:
        notable = True
        lines.append("  ← throttled flag set — check power/temperature")

    # --- is the Pi actually running the code in git? ---
    # This drifted for two weeks and nothing noticed. Deployments were file
    # copies, so the working tree crept forward while git's HEAD stayed at a
    # commit from early August — 143 behind by the time it was caught, and
    # caught by eye, not by any check. "What is on the Pi" was unanswerable
    # from git, which is the whole point of having git on the Pi.
    #
    # Compares the WORKING TREE against origin/main and ignores data/, which
    # is tracked on purpose (the .gitignore says so — the cabin's data trail
    # lives in the repo) and is therefore permanently dirty. Without that
    # exclusion this would cry wolf on every run and be ignored within a day.
    try:
        gout = subprocess.check_output(
            ["ssh", ssh_target, "-o", "ConnectTimeout=8",
             "cd /srv/volthium_reader && "
             "timeout 120 git fetch --no-tags -q origin main 2>/dev/null; "
             "echo HEAD=$(git rev-parse --short HEAD) "
             "ORIGIN=$(git rev-parse --short origin/main) "
             "BEHIND=$(git rev-list --count HEAD..origin/main) "
             "DIRTY=$(git diff --name-only origin/main -- ':!data' | wc -l); "
             "git diff --name-only origin/main -- ':!data' | head -5"],
            timeout=180, text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError) as exc:
        notable = True
        lines.append(f"  ← git sync UNVERIFIED: {exc}")
    else:
        gn, gl = _check_git_sync(gout)
        notable |= gn
        lines += gl

    # --- timers, checked separately because the service rule excludes them ---
    try:
        tout = subprocess.check_output(
            ["ssh", ssh_target, "-o", "ConnectTimeout=8", timer_probe],
            timeout=30, text=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            OSError) as exc:
        notable = True
        lines.append(f"  ← timers UNVERIFIED: {exc}")
    else:
        tn, tl = _check_timers(tout)
        notable |= tn
        lines += tl

    services = _parse_units(out)
    if not services:
        notable = True
        lines.append("  ← could not read any volthium unit state")
    else:
        down = [s for s in services
                if s["UnitFileState"] == "enabled" and s["ActiveState"] != "active"]
        restarted = [s for s in services if s.get("NRestarts", "0") not in ("0", "")]
        enabled = [s for s in services if s["UnitFileState"] == "enabled"]
        lines.append(f"  services: {len(enabled)} enabled, "
                     f"{len(enabled) - len(down)} active")
        for s in down:
            notable = True
            lines.append(f"  ← {s['Id']} is enabled but {s['ActiveState']}")
        for s in restarted:
            notable = True
            lines.append(f"  ← {s['Id']} has restarted {s['NRestarts']}x")

    try:
        warn_count = int(body[-1])
        if warn_count > 0:
            notable = True
            lines.append(f"  ← {warn_count} WARNING/ERROR/Failed lines across "
                         f"all volthium units in the last {hours}h")
    except (ValueError, IndexError):
        pass
    return notable, lines


def _parse_units(out: str) -> list[dict]:
    """`systemctl show` emits key=value blocks; we flattened them with '|'."""
    units: list[dict] = []
    cur: dict = {}
    for tok in out.replace("\n", "|").split("|"):
        k, _, v = tok.partition("=")
        k, v = k.strip(), v.strip()
        if k == "Id":
            if cur.get("Id"):
                units.append(cur)
            cur = {"Id": v}
        elif k in ("ActiveState", "UnitFileState", "NRestarts") and cur.get("Id"):
            cur[k] = v
    if cur.get("Id"):
        units.append(cur)
    return [u for u in units
            if u.get("Id", "").startswith("volthium-")
            and "ActiveState" in u and "UnitFileState" in u]


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
    # Run each section independently and NAME the one that fails. Previously a
    # single try wrapped all three and reported to stderr, which fooled me on
    # 2026-08-07: stdout is block-buffered when redirected to a file while
    # stderr is not, so a connection reset in the LAST section surfaced at the
    # TOP of the captured output. It read as an early blip the run had
    # recovered from, when in fact the run had died and the RS485 section never
    # ran. I went looking for a sick server on the strength of it.
    #
    # One flaky section must also not suppress the others: the point of a
    # health check is to tell you what it did and did not manage to look at.
    failed: list[str] = []
    for name, fn in (("readings", lambda: section_readings(args.source, since_iso)),
                     ("events", lambda: section_events(since_iso)),
                     ("solar", lambda: section_solar(args.source)),
                     ("wired RS485", lambda: section_wired(since_iso)),
                     ("alerting",
                      lambda: section_alerting(
                          args.ssh_target if args.with_pi else None))):
        try:
            n, lines = fn()
            any_notable |= n
            print("\n".join(lines) + "\n")
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            failed.append(name)
            any_notable = True
            print(f"!! {name} section FAILED: {exc}\n")

    if args.with_pi:
        n, lines = section_pi(args.ssh_target, int(args.hours))
        any_notable |= n
        print("\n".join(lines) + "\n")

    # ALWAYS print a bottom line, including on failure. Without one, a run that
    # died mid-way is indistinguishable from output that merely got truncated,
    # and "no verdict" gets read as "probably fine". Say what was not checked.
    if failed:
        tag = f"INCOMPLETE — could not check: {', '.join(failed)}"
    elif any_notable:
        tag = "NOTABLE — investigate above"
    else:
        tag = "quiet window"
    print(f"=== bottom line: {tag} ===")
    if failed:
        return 2
    return 1 if any_notable else 0


if __name__ == "__main__":
    sys.exit(main())
