#!/usr/bin/env python3
"""Autonomous BLE pipeline watchdog + health logger.

Goal: keep the logger producing rows without an active operator, recover from
adapter-side wedges automatically, and gather the per-battery health data we
need to diagnose dropouts (see docs/reliability_failure_modes.md, FM-3/5/6).

Design notes
------------
* Single-adapter rule (FM-2): only ONE thing may run BLE discovery at a time.
  So in NORMAL operation this watchdog never touches the radio — it just stats
  the CSV. It only scans during a recovery window, and only AFTER it has
  stopped the logger, so the two never contend for the adapter.
* Staleness, not success, is the trigger: a failed read writes no CSV row, so
  `pack.csv` mtime is the ground-truth liveness signal.
* Escalating recovery ladder with backoff so a source-side outage (e.g. a
  battery whose BMS BLE is genuinely off) doesn't thrash the BT stack all night.
* Always leaves the logger running (try/finally) — a watchdog that dies with the
  logger stopped would be worse than no watchdog.

Health log: one JSON object per line appended to --health (data/ble_health.jsonl):
  {"ts","csv_age_s","logger_active","event","rung","a_rssi","b_rssi","a_seen","b_seen","note"}
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

A_ADDR = "09:01:00:14:7E:DC"  # battery A / V-12V200AH-0533
B_ADDR = "09:01:00:11:55:DF"  # battery B / V-12V200AH-0667
LOGGER_UNIT = "volthium-logger.service"
BT_UNIT = "bluetooth.service"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


def csv_age(csv: Path) -> float | None:
    try:
        return time.time() - csv.stat().st_mtime
    except FileNotFoundError:
        return None


def logger_active() -> bool:
    return _run(["systemctl", "is-active", LOGGER_UNIT])[1] == "active"


async def quick_scan(seconds: float) -> dict:
    """Return {addr: rssi} for our two batteries. Caller MUST have stopped the
    logger first — this drives the radio."""
    from bleak import BleakScanner  # imported lazily so --help works without bleak

    seen: dict[str, int] = {}

    def cb(d, adv):
        a = d.address.upper()
        if a in (A_ADDR, B_ADDR):
            seen[a] = adv.rssi

    s = BleakScanner(detection_callback=cb)
    await s.start()
    try:
        await asyncio.sleep(seconds)
    finally:
        await s.stop()
    return seen


class HealthLog:
    def __init__(self, path: Path):
        self.path = path

    def write(self, **fields) -> None:
        rec = {"ts": _utc(), **fields}
        try:
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as e:  # noqa: BLE001
            print(f"[watchdog] health-log write failed: {e}", file=sys.stderr, flush=True)
        print(f"[watchdog] {json.dumps(rec)}", flush=True)


# Recovery ladder: index = attempt count this outage (capped). Each rung is a
# superset of the cheaper ones.
def recovery_action(rung: int, dry: bool) -> str:
    actions: list[str] = []
    # rung 0 is the implicit stop->scan->start cycle (no extra action).
    if rung >= 1:
        actions.append("adapter-power-cycle")
        if not dry:
            _run(["bluetoothctl", "power", "off"]); time.sleep(2)
            _run(["bluetoothctl", "power", "on"]); time.sleep(2)
    if rung >= 2:
        actions.append("bluetooth-restart")
        if not dry:
            _run(["sudo", "-n", "systemctl", "restart", BT_UNIT]); time.sleep(5)
    return ",".join(actions) or "logger-cycle-only"


async def maintenance_cycle(rung: int, scan_s: float, dry: bool, health: HealthLog) -> dict:
    """Stop logger, (escalate recovery), scan for both batteries, restart logger.
    Returns the scan result. Logger is guaranteed running on return."""
    if not dry:
        _run(["sudo", "-n", "systemctl", "stop", LOGGER_UNIT]); time.sleep(2)
    try:
        action = recovery_action(rung, dry)
        seen = {} if dry else await quick_scan(scan_s)
    finally:
        if not dry:
            _run(["sudo", "-n", "systemctl", "start", LOGGER_UNIT])
    a_rssi, b_rssi = seen.get(A_ADDR), seen.get(B_ADDR)
    health.write(event="recovery", rung=rung, action=action,
                 a_seen=A_ADDR in seen, b_seen=B_ADDR in seen,
                 a_rssi=a_rssi, b_rssi=b_rssi)
    return seen


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--health", type=Path, default=Path("data/ble_health.jsonl"))
    ap.add_argument("--stale", type=float, default=150.0,
                    help="CSV age (s) that counts as an outage")
    ap.add_argument("--interval", type=float, default=30.0,
                    help="normal-mode poll interval (s)")
    ap.add_argument("--scan", type=float, default=8.0, help="recovery scan seconds")
    ap.add_argument("--recover-base", type=float, default=180.0,
                    help="base seconds between recovery attempts (backs off)")
    ap.add_argument("--recover-max", type=float, default=1800.0,
                    help="max backoff between recovery attempts")
    ap.add_argument("--once", action="store_true", help="run one poll iteration and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="never touch services/radio; just report")
    args = ap.parse_args()

    health = HealthLog(args.health)
    health.write(event="watchdog-start", note=f"stale>{args.stale}s interval={args.interval}s dry={args.dry_run}")

    outage_attempts = 0
    next_recovery_at = 0.0

    while True:
        age = csv_age(args.csv)
        active = logger_active()

        # Safety net: if the logger somehow ended up stopped and we are NOT in a
        # controlled recovery, bring it back.
        if not active and not args.dry_run:
            _run(["sudo", "-n", "systemctl", "start", LOGGER_UNIT])
            health.write(event="logger-restart", note="found inactive, restarted")
            active = True

        stale = age is None or age > args.stale

        if not stale:
            if outage_attempts:
                health.write(event="recovered", csv_age_s=round(age, 1),
                             note=f"fresh after {outage_attempts} attempt(s)")
            outage_attempts = 0
            next_recovery_at = 0.0
            health.write(event="ok", csv_age_s=round(age, 1), logger_active=active)
        else:
            now = time.time()
            if now >= next_recovery_at:
                rung = min(outage_attempts, 2)
                health.write(event="outage", csv_age_s=None if age is None else round(age, 1),
                             rung=rung, note="starting maintenance cycle")
                await maintenance_cycle(rung, args.scan, args.dry_run, health)
                outage_attempts += 1
                backoff = min(args.recover_base * (2 ** (outage_attempts - 1)), args.recover_max)
                next_recovery_at = time.time() + backoff
                health.write(event="next-recovery", note=f"in {int(backoff)}s (attempt {outage_attempts})")
            else:
                health.write(event="outage-wait", csv_age_s=None if age is None else round(age, 1),
                             note=f"next recovery in {int(next_recovery_at - time.time())}s")

        if args.once:
            return 0
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
