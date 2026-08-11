#!/usr/bin/env python3
"""What the daily ledger's solar_wh would be under a different gate. Runs OFF the Pi.

`AsyncpgReadingsDAO.solar_energy_daily` infers production from the two
non-MPPT meters whenever the MPPT looks low:

    CASE WHEN pv_v < 15 THEN solar_w
         ELSE GREATEST(solar_w, batt + dc_w) END

The inference is physically sound — with solar as the only source,
production = what went into the battery + what the house drew. Its problem is
the GATE. `pv_v >= 15` admits every twilight and overcast hour, and the two
meters disagree by ~32 W, so the difference credits a standing ~32 W of nothing
as solar for the whole daylight period. GREATEST() then makes the error
one-directional: noise can only ever add.

The proposed gate is the CLAMP CONDITION itself, since a clamp is the specific
situation the inference exists to rescue — the MPPT is blind to power crossing
its own body diode, so its self-report is wrong-low and batt+load is better.

    python3 scripts/ledger_gate_compare.py --day 2026-08-09 [--days 3]

Four numbers per day, because no single one is trustworthy here:

  current      reimplementation of the shipped SQL. MUST match the live API or
               nothing below means anything — the script checks and says so.
  proposed     the same thing with the clamp gate.
  mppt_only    the MPPT's own self-report, integrated. Independently confirmed
               against the device's own daily counter to 0.5%.
  balance      load + net battery change, i.e. the energy that demonstrably
               arrived. Shown twice: on dc_w as-is, and on dc_w minus the
               measured 32 W offset. This is the only estimate anchored to
               something other than the MPPT, and the two versions bracket the
               dc_w question rather than pretending it is settled.

READ THE RESULT CAREFULLY. `balance` on raw dc_w is CIRCULAR — solar_wh under
the current gate is *defined* as batt+dc_w for most of the day, so of course it
agrees. Only the offset-corrected column is informative.

The finding this was written to surface: the proposed gate is directionally
right and may OVERSHOOT. It drops solar_wh to within a few percent of
mppt_only, which reinstates the MPPT's known under-read for the whole day —
whereas the inference was introduced partly because the MPPT under-reads
generally, not only while clamped. The clamp-rescue term is worth tens of Wh;
the gate change is worth over a thousand. Those are not the same decision, and
this script exists so they can be told apart.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from solar_geometry import sun_elevation_deg                      # noqa: E402
from xanbus_latch_guard import MIN_SUN_ELEVATION_DEG              # noqa: E402
from xanbus_telemetry import (                                    # noqa: E402
    LATCH_DAYLIGHT_V, LATCH_DELTA_MAX_V, LATCH_DELTA_MIN_V,
)

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7        # site is America/Vancouver, PDT in the study window
BUCKET_S = 15              # the server integrates at 15 s
DC_W_OFFSET_W = 32.0       # measured dark-hours dc_w excess over the BMS
PV_GATE_V = 15.0           # the shipped gate


def _sane_dc_w(w):
    """Same range guard the server applies — a corrupt sample is missing, not
    clamped to a bound."""
    return w if (w is not None and 0.0 <= w <= 6000.0) else None


def fetch_readings(url: str, source: str, start: dt.datetime,
                   end: dt.datetime) -> dict[int, float]:
    """pack_p averaged into 15 s buckets, matching the server's `r` CTE."""
    acc: dict[int, list[float]] = {}
    cur = start
    while cur < end:
        q = (f"{url}/api/readings?source_id={source}&limit=5000"
             f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        with urllib.request.urlopen(q, timeout=120) as r:
            got = json.load(r)
        got = got if isinstance(got, list) else got.get("readings", [])
        got = [x for x in got if x["ts"][:19] < f"{end:%Y-%m-%dT%H:%M:%S}"]
        if not got:
            break
        for x in got:
            p = x.get("pack_p")
            if p is None:
                continue
            t = dt.datetime.strptime(x["ts"][:19], "%Y-%m-%dT%H:%M:%S")
            acc.setdefault(int(t.replace(tzinfo=UTC).timestamp())
                           // BUCKET_S * BUCKET_S, []).append(p)
        nxt = dt.datetime.strptime(max(x["ts"] for x in got)[:19],
                                   "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def compare(url: str, source: str, series: list[dict],
            day_local: dt.date) -> dict:
    start = dt.datetime.combine(day_local, dt.time()).replace(
        tzinfo=UTC) - dt.timedelta(hours=LOCAL_OFFSET_H)
    end = start + dt.timedelta(days=1)
    batt = fetch_readings(url, source, start, end)

    out = dict(current=0.0, proposed=0.0, mppt_only=0.0, load=0.0,
               batt_net=0.0, clamped_buckets=0, buckets=0)
    h = BUCKET_S / 3600.0
    for s in series:
        t = dt.datetime.strptime(s["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC)
        if not (start <= t < end):
            continue
        out["buckets"] += 1
        bw = batt.get(int(t.timestamp()) // BUCKET_S * BUCKET_S, 0.0) or 0.0
        sw = s.get("solar_w") or 0.0
        dw = _sane_dc_w(s.get("dc_w")) or 0.0
        pv = s.get("pv_v") or 0.0
        dv = s.get("dc_v")
        infer = bw + dw

        out["current"] += (sw if pv < PV_GATE_V else max(sw, infer)) * h
        out["mppt_only"] += sw * h
        out["load"] += dw * h
        out["batt_net"] += bw * h

        clamped = (dv is not None and pv > LATCH_DAYLIGHT_V
                   and LATCH_DELTA_MIN_V <= pv - dv <= LATCH_DELTA_MAX_V
                   and sun_elevation_deg(t.timestamp()) >= MIN_SUN_ELEVATION_DEG)
        out["clamped_buckets"] += clamped
        out["proposed"] += (max(sw, infer) if clamped else sw) * h
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="local date, YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=1, help="consecutive days")
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    with urllib.request.urlopen(
            f"{a.url}/api/solar/series?source_id={a.source}&hours=400"
            f"&bucket_s={BUCKET_S}", timeout=180) as r:
        series = json.load(r)["series"]
    with urllib.request.urlopen(
            f"{a.url}/api/solar/energy?source_id={a.source}&days=30",
            timeout=120) as r:
        live = {d["day"]: d for d in json.load(r)["days"]}

    d0 = dt.date.fromisoformat(a.day)
    print(f"gate: current pv_v >= {PV_GATE_V} V | proposed = clamp band "
          f"({LATCH_DELTA_MIN_V}..{LATCH_DELTA_MAX_V} V over "
          f"{LATCH_DAYLIGHT_V} V, sun >= {MIN_SUN_ELEVATION_DEG} deg)\n")
    print("| day | current | API | proposed | mppt_only | balance(dc_w) "
          "| balance(-32W) | clamp min | delta |")
    print("|---|---|---|---|---|---|---|---|---|")
    for i in range(a.days):
        day = d0 + dt.timedelta(days=i)
        c = compare(a.url, a.source, series, day)
        if not c["buckets"]:
            print(f"| {day} | (no data) |")
            continue
        api = live.get(str(day), {}).get("solar_wh")
        api_f = float(api) if api is not None else float("nan")
        bal = c["load"] + c["batt_net"]
        bal_adj = (c["load"] - DC_W_OFFSET_W * c["buckets"] * BUCKET_S / 3600.0
                   + c["batt_net"])
        ok = "" if abs(c["current"] - api_f) <= max(20.0, 0.01 * api_f) else " **MISMATCH**"
        print(f"| {day} | {c['current']:.0f} | {api_f:.0f}{ok} "
              f"| {c['proposed']:.0f} | {c['mppt_only']:.0f} | {bal:.0f} "
              f"| {bal_adj:.0f} | {c['clamped_buckets']*BUCKET_S/60:.0f} "
              f"| {c['proposed']-c['current']:+.0f} |")

    print("\nbalance(dc_w) is CIRCULAR against `current` — solar_wh is defined "
          "as batt+dc_w for most of the day. Only balance(-32W) is independent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
