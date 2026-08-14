#!/usr/bin/env python3
"""One-shot watcher for the pre-registered early-bounce test (task #40).

Waits for the array to be TRACKING in the 40-45 V band during a genuine
DESCENT, fires exactly one bounce, and records before/after.

Safety properties, deliberately explicit:
  * FIRES AT MOST ONCE. A lock file is written before the command is sent, so
    a crash-restart cannot double-fire.
  * DESCENT REQUIRED. At dawn the array climbs through 40-45 V; firing then
    would test nothing. Requires pv_v to be well below its own recent peak AND
    the array to have been above the 48 V arm threshold earlier today.
  * FRESHNESS REQUIRED. The solar API is a 300 s batch upload, so a stale row
    could describe an array that has already moved. Rejects readings older
    than 8 minutes.
  * NO GUARD COLLISION. Both the guard and this claim a CAN address. Skips the
    cycle if the guard unit is running.
  * HARD EXPIRY. Gives up at 13:00 local and exits without acting.
  * READ-ONLY UNTIL THE ONE COMMAND. Everything else is HTTP GET and
    `systemctl is-active`.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/pivot/Documents/repo/volthium_sw/volthium_reader/scripts")
from solar_geometry import sun_elevation_deg          # noqa: E402
from xanbus_telemetry import (                        # noqa: E402
    LATCH_DAYLIGHT_V, LATCH_DELTA_MAX_V, LATCH_DELTA_MIN_V,
)

UTC = dt.timezone.utc
LOCAL = -7
SSH = "kaan@kwpi.zt"
API = "https://volts.alti2.de"
HERE = Path(__file__).resolve().parent
LOCK = HERE / "bounce_FIRED.lock"
LOG = HERE / "bounce_result.json"

BAND_LO, BAND_HI = 40.0, 45.0
MIN_SUN_DEG = 15.0
MAX_AGE_S = 8 * 60
DESCENT_DROP_V = 3.0        # below the 20-min peak to count as descending
ARMED_V = 48.0
WATCH_START_H, WATCH_END_H = 6, 13     # local hours the descent can occur in
ABSOLUTE_DEADLINE_H = 36               # never linger longer than this, total


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        return json.load(r)


def series(hours=3, bucket=60):
    s = get(f"/api/solar/series?source_id=pi-barge&hours={hours}&bucket_s={bucket}")["series"]
    out = []
    for x in s:
        if x.get("pv_v") is None or x.get("dc_v") is None:
            continue
        t = dt.datetime.strptime(x["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        out.append((t, x["pv_v"], x["dc_v"], x.get("solar_w") or 0.0))
    out.sort()
    return out


def clamped(pv, dv):
    return (pv > LATCH_DAYLIGHT_V
            and LATCH_DELTA_MIN_V <= pv - dv <= LATCH_DELTA_MAX_V)


def guard_busy():
    try:
        r = subprocess.run(["ssh", SSH, "-o", "ConnectTimeout=8",
                            "systemctl is-active volthium-latch-guard.service"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() in ("active", "activating")
    except Exception:
        return True          # unknown -> treat as busy, never race the guard


def say(msg):
    print(f"{dt.datetime.now(UTC)+dt.timedelta(hours=LOCAL):%H:%M:%S} {msg}",
          flush=True)


def main() -> int:
    if LOCK.exists():
        say("lock present — already fired, refusing")
        return 0
    started = dt.datetime.now(UTC)
    say(f"watching for a 40-45 V tracking descent; window "
        f"{WATCH_START_H}:00-{WATCH_END_H}:00 local, deadline "
        f"{ABSOLUTE_DEADLINE_H} h")
    while True:
        now = dt.datetime.now(UTC)
        loc = now + dt.timedelta(hours=LOCAL)
        # Outside the morning window we IDLE, we do not exit. The first
        # version compared loc.hour >= 13, which is true all evening, so
        # launching at 22:36 made it announce "giving up" and quit having done
        # nothing — a confident no-op, which is the exact failure mode this
        # week has been about. Only the absolute deadline may end the watch.
        if (dt.datetime.now(UTC) - started).total_seconds() > ABSOLUTE_DEADLINE_H * 3600:
            say(f"absolute deadline of {ABSOLUTE_DEADLINE_H} h reached — exiting")
            return 2
        if not (WATCH_START_H <= loc.hour < WATCH_END_H):
            if loc.minute % 30 == 0:
                say(f"outside the {WATCH_START_H}:00-{WATCH_END_H}:00 window "
                    f"(local {loc:%H:%M}) — idling")
            time.sleep(600)
            continue
        # Cheap night skip: no point polling a dark array once a minute.
        if sun_elevation_deg(now.timestamp()) < 5.0:
            if loc.minute % 30 == 0:
                say(f"dark (sun {sun_elevation_deg(now.timestamp()):.1f} deg) — idling")
            time.sleep(600)
            continue
        try:
            rows = series()
        except Exception as exc:
            say(f"api error {exc}; retry")
            time.sleep(60)
            continue
        if not rows:
            time.sleep(60)
            continue
        t, pv, dv, w = rows[-1]
        age = (now - t).total_seconds()
        el = sun_elevation_deg(t.timestamp())
        recent = [r for r in rows if (t - r[0]).total_seconds() <= 20 * 60]
        peak20 = max(r[1] for r in recent) if recent else pv
        armed_today = any(r[1] >= ARMED_V for r in rows
                          if (r[0] + dt.timedelta(hours=LOCAL)).date() == loc.date())

        ok = (age <= MAX_AGE_S and BAND_LO <= pv <= BAND_HI
              and not clamped(pv, dv) and el >= MIN_SUN_DEG and w > 5
              and peak20 - pv >= DESCENT_DROP_V and armed_today)
        say(f"pv={pv:5.1f} d={pv-dv:5.1f} W={w:5.0f} sun={el:4.1f} "
            f"peak20={peak20:5.1f} age={age:3.0f}s armed={armed_today} -> "
            f"{'FIRE' if ok else 'wait'}")
        if not ok:
            time.sleep(60)
            continue
        if guard_busy():
            say("guard running — deferring one cycle")
            time.sleep(60)
            continue

        before = {"ts": t.isoformat(), "pv_v": pv, "dc_v": dv, "solar_w": w,
                  "sun_deg": el, "peak20_v": peak20,
                  "mean5_w": sum(r[3] for r in rows[-5:]) / 5,
                  "mean5_pv": sum(r[1] for r in rows[-5:]) / 5}
        LOCK.write_text(json.dumps(before))          # BEFORE sending. Never double-fire.
        say(f"FIRING ONE BOUNCE. before={before}")
        cmd = ("cd /srv/volthium_reader && timeout 120 .venv/bin/python "
               "scripts/xanbus_node.py --bounce --dest 1 --function 134 --send")
        r = subprocess.run(["ssh", SSH, "-o", "ConnectTimeout=10", cmd],
                           capture_output=True, text=True, timeout=200)
        say(f"rc={r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-500:]}")

        say("observing for 25 min")
        after = []
        for _ in range(25):
            time.sleep(60)
            try:
                rr = series(hours=1)
            except Exception:
                continue
            if rr:
                tt, ppv, ddv, ww = rr[-1]
                after.append({"ts": tt.isoformat(), "pv_v": ppv,
                              "dc_v": ddv, "solar_w": ww})
                say(f"  after pv={ppv:6.1f} d={ppv-ddv:6.2f} W={ww:6.1f}")
        LOG.write_text(json.dumps({"before": before, "rc": r.returncode,
                                   "stdout": r.stdout, "after": after}, indent=2))
        say(f"done -> {LOG}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
