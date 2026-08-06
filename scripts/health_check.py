#!/usr/bin/env python3
"""Whole-system health in one shot: every check, run concurrently.

Replaces the four-round-trip ritual (status_check, solar API, an SSH to the
Pi, then the latch guard) with one command that fires them all in parallel
and prints a single verdict. Faster, but more importantly CONSISTENT — the
check can't quietly drift between runs or skip an item.

Runs from the laptop. One SSH connection carries all the Pi-side probes;
everything is read-only.

    python3 scripts/health_check.py            # human-readable
    python3 scripts/health_check.py --json     # machine-readable
    python3 scripts/health_check.py --hours 2  # window for gap analysis

Exit code 0 = all green, 1 = something needs attention.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import subprocess
import sys
import urllib.request

BASE = "https://volts.alti2.de"
PI_HOSTS = ("kwpi.zt", "10.42.100.200", "192.168.192.101")

# Rows upload in 5-minute batches, so anything under ~6 min is normal. An
# earlier 2-minute threshold produced a false alarm on 2026-08-05.
FRESH_LIMIT_S = 400
MEM_CAP_MB = 60          # the systemd MemoryMax on the telemetry service
EXPECT_SCHEMA = 2        # reader emits pv_v_min/max from v2

SERVICES = ("volthium-xanbus-telemetry", "volthium-xanbus-capture",
            "volthium-rs485-logger", "volthium-uploader",
            "volthium-events-uploader", "volthium-modbus-poll")


def jget(path: str, timeout: float = 30.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.load(r)


def check_solar(hours: float) -> dict:
    """Freshness, schema integrity, and row yield of the CAN pipeline."""
    out: dict = {"name": "solar pipeline", "problems": []}
    rows = jget("/api/solar?limit=2")["readings"]
    if not rows:
        out["problems"].append("no solar rows at all")
        return out
    r = rows[-1]
    ts = dt.datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()
    out["age_s"] = round(age)
    out["schema_version"] = r.get("schema_version")
    out["pv_v"] = r.get("pv_v")
    if age > FRESH_LIMIT_S:
        out["problems"].append(f"stale: newest row is {age/60:.1f} min old")
    if r.get("schema_version") != EXPECT_SCHEMA:
        out["problems"].append(
            f"schema_version {r.get('schema_version')} != {EXPECT_SCHEMA}")
    # The 2026-08-05 incident: reader emitted fields the server forbade, so
    # every row 422'd. Presence of the v2 columns is the canary.
    if r.get("pv_v_min") is None and (r.get("pv_v") or 0) > 1:
        out["problems"].append("pv_v_min is NULL — reader/server schema skew?")
    ser = jget(f"/api/solar/series?hours={hours}&bucket_s=3600")["series"]
    got = sum(b["n"] for b in ser if b.get("n"))
    want = int(hours * 240)
    out["rows"] = got
    out["coverage_pct"] = round(100 * got / want, 1) if want else None
    if want and got < want * 0.9:
        out["problems"].append(f"only {got}/{want} rows ({100*got/want:.0f}%)")
    return out


def check_battery() -> dict:
    """BMS side: freshness, state, and the pack-A imbalance we watch."""
    out: dict = {"name": "battery (BMS)", "problems": []}
    L = jget("/api/latest")["latest"]
    if not L:
        out["problems"].append("no readings")
        return out
    ts = dt.datetime.strptime(L["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()
    out.update(age_s=round(age), state=L.get("state"),
               soc_a=L.get("soc_a"), soc_b=L.get("soc_b"),
               pack_p=round(L.get("pack_p") or 0))
    if age > 120:
        out["problems"].append(f"stale: {age/60:.1f} min old")
    for bat in ("a", "b"):
        dv = L.get(f"delta_v_{bat}")
        if dv is not None and dv > 0.45:
            out["problems"].append(
                f"battery {bat.upper()} cell spread {dv*1000:.0f} mV")
        if L.get(f"problem_code_{bat}"):
            out["problems"].append(
                f"battery {bat.upper()} problem_code {L[f'problem_code_{bat}']}")
    return out


def check_events(hours: float) -> dict:
    """Latch activity and anything the reader flagged."""
    out: dict = {"name": "events", "problems": [], "notable": []}
    since = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = jget(f"/api/xanbus_events?since={since}&limit=300")["events"]
    counts: dict = {}
    for e in ev:
        counts[e["event"]] = counts.get(e["event"], 0) + 1
    out["counts"] = counts
    for kind in ("mppt_latched", "latch_detected", "latch_fix_result",
                 "mppt_latch_context", "latch_guard_pending",
                 "node_dropout", "gen_start"):
        if kind in counts:
            out["notable"].append(f"{kind} x{counts[kind]}")
    for e in ev:
        if e["event"] == "latch_fix_result" and not e["data"].get("recovered"):
            out["problems"].append("a latch fix did NOT recover the array")
    return out


def check_pi() -> dict:
    """All Pi-side probes over ONE ssh connection."""
    out: dict = {"name": "pi (kwpi)", "problems": []}
    script = (
        'cd /srv/volthium_reader 2>/dev/null || exit 9; '
        'echo "SERVICES:$(systemctl is-active ' + " ".join(SERVICES) + ' | tr "\\n" ",")"; '
        'echo "MEM:$(systemctl show volthium-xanbus-telemetry -p MemoryCurrent --value)"; '
        'echo "RESTARTS:$(systemctl show volthium-xanbus-telemetry -p NRestarts --value)"; '
        'echo "FREEMB:$(free -m | awk "/^Mem:/{print \\$7}")"; '
        'echo "DISKPCT:$(df --output=pcent / | tail -1 | tr -d " %")"; '
        'echo "SPOOL:$(ls data/solar/*.sealed 2>/dev/null | wc -l)"; '
        'echo "ERRORS:$(journalctl -u volthium-xanbus-telemetry --since \\"-2h\\" '
        '--no-pager 2>/dev/null | grep -icE \\"error|422|fail\\")"; '
        'echo "GUARDRUNS:$(journalctl -u volthium-latch-guard --since \\"-2h\\" '
        '--no-pager 2>/dev/null | grep -c Starting)"; '
        'echo "CAN:$(ip -details link show can0 2>/dev/null | grep -o \\"LISTEN-ONLY\\" || echo TX-CAPABLE)"'
    )
    last_err = None
    for host in PI_HOSTS:
        try:
            p = subprocess.run(["ssh", f"kaan@{host}", script],
                               capture_output=True, text=True, timeout=45)
            if p.returncode == 0 and p.stdout.strip():
                out["host"] = host
                for line in p.stdout.strip().splitlines():
                    if ":" not in line:
                        continue
                    k, _, v = line.partition(":")
                    out[k.lower()] = v.strip()
                break
            last_err = p.stderr.strip()[:120] or f"rc={p.returncode}"
        except Exception as exc:                     # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
    else:
        out["problems"].append(f"unreachable on all hosts ({last_err})")
        return out

    inactive = [s for s, st in zip(SERVICES, out.get("services", "").split(","))
                if st and st != "active"]
    if inactive:
        out["problems"].append(f"services not active: {', '.join(inactive)}")
    try:
        mb = int(out.get("mem", 0)) / 1e6
        out["mem_mb"] = round(mb, 1)
        if mb > MEM_CAP_MB * 0.8:
            out["problems"].append(f"telemetry at {mb:.0f} MB of {MEM_CAP_MB} MB cap")
    except (TypeError, ValueError):
        pass
    if int(out.get("spool", 0) or 0) > 2:
        out["problems"].append(f"{out['spool']} sealed segments — ingest failing?")
    if int(out.get("restarts", 0) or 0) > 0:
        out["problems"].append(f"telemetry restarted {out['restarts']}x")
    if int(out.get("freemb", 999) or 999) < 60:
        out["problems"].append(f"only {out['freemb']} MB RAM available")
    if int(out.get("diskpct", 0) or 0) > 85:
        out["problems"].append(f"disk {out['diskpct']}% full")
    return out


def check_rs485(hours: float) -> dict:
    """Delegate to the existing status_check for gap/wedge analysis."""
    out: dict = {"name": "rs485 telemetry", "problems": []}
    try:
        p = subprocess.run([sys.executable, "scripts/status_check.py",
                            "--hours", str(hours)],
                           capture_output=True, text=True, timeout=90)
        txt = p.stdout
        out["verdict"] = next(
            (l.split("bottom line:")[1].strip(" =")
             for l in txt.splitlines() if "bottom line" in l), "unknown")
        for marker, label in (("gaps > 60s:", "gaps"),
                              ("battery-silent stretches", "silent")):
            for line in txt.splitlines():
                if marker in line and "none" not in line:
                    out["problems"].append(line.strip())
        if "read_fail:" in txt and "read_fail: none" not in txt:
            out["problems"].append("RS485 read failures present")
    except Exception as exc:                          # noqa: BLE001
        out["problems"].append(f"status_check failed: {exc}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    checks = {
        "rs485": lambda: check_rs485(args.hours),
        "solar": lambda: check_solar(args.hours),
        "battery": check_battery,
        "events": lambda: check_events(args.hours),
        "pi": check_pi,
    }
    results: dict = {}
    with cf.ThreadPoolExecutor(max_workers=len(checks)) as ex:
        futs = {ex.submit(fn): key for key, fn in checks.items()}
        for fut in cf.as_completed(futs):
            key = futs[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:                  # noqa: BLE001
                results[key] = {"name": key,
                                "problems": [f"check crashed: {exc}"]}

    problems = [(k, p) for k, r in results.items() for p in r.get("problems", [])]

    if args.json:
        print(json.dumps({"ok": not problems, "results": results}, indent=1))
        return 1 if problems else 0

    s, b = results.get("solar", {}), results.get("battery", {})
    pi, ev = results.get("pi", {}), results.get("events", {})
    print(f"solar    {s.get('rows','?')} rows/{args.hours:g}h "
          f"({s.get('coverage_pct','?')}%)  age {s.get('age_s','?')}s  "
          f"v{s.get('schema_version','?')}  pv {s.get('pv_v') or 0:.0f} V")
    print(f"battery  {b.get('state','?')}  A {b.get('soc_a','?')}% "
          f"B {b.get('soc_b','?')}%  {b.get('pack_p','?')} W")
    print(f"pi       {pi.get('services','?')} mem {pi.get('mem_mb','?')} MB  "
          f"spool {pi.get('spool','?')}  guard runs {pi.get('guardruns','?')}  "
          f"can0 {pi.get('can','?')}")
    print(f"rs485    {results.get('rs485',{}).get('verdict','?')}")
    if ev.get("notable"):
        print(f"events   {', '.join(ev['notable'])}")

    if problems:
        print("\nPROBLEMS:")
        for key, p in problems:
            print(f"  [{key}] {p}")
        return 1
    print("\nall green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
