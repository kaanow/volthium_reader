#!/usr/bin/env python3
"""Measure the fixed offset between the two DC power meters. Runs OFF the Pi.

There are two independent measurements of power leaving the battery:

  pack_p   BMS shunts, via RS485 (readings.pack_p)
  dc_w     the Conext SW inverter's own DC-input meter, via Xanbus
           (solar_readings.dc_w)

They disagree, and the disagreement is measured IN DARKNESS on purpose. With
no solar there is nothing to attribute the difference to: the battery is the
only source, so whatever leaves it must equal the inverter's draw plus the
unmetered DC load (the fridge). Any daytime comparison has the MPPT's own
metering in the loop, which is exactly the quantity under suspicion — that is
what made every earlier attempt at this circular.

The result is not a calibration wobble. It is a fixed ~32 W offset, stable to
within 8 W across five consecutive nights, and it points the wrong way:

    battery supplies  81 W        (pack_p, fridge off)
    inverter draws   113 W        (dc_w)

You cannot draw more from a battery than it supplies, and the fridge is an
ADDITIONAL load that should make |pack_p| larger than dc_w, not smaller. So
one of these two meters is definitively wrong by ~32 W. Which one is not
settled here — see docs/xanbus-unknowns.md #5.

Why it matters beyond tidiness: the daily ledger's load column is dc_w
straight through, so if dc_w is the wrong one the ledger overstates house
load by 32 W x 24 h = ~768 Wh/day, against a reported ~2730 Wh/day.

    python3 scripts/meter_offset.py [--nights 5] [--url https://volts.alti2.de]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import urllib.request

# Fridge-off selection. The night load is strongly bimodal (compressor on vs
# off); the offset is only clean in the quiet mode, because the fridge is a
# real load that legitimately widens the gap. 110 W sits in the empty middle
# of the two modes (quiet ~81 W, running ~150-170 W).
FRIDGE_OFF_MAX_W = 110.0
DARK_PV_V_MAX = 15.0      # array is dark, not merely dim
DARK_SOLAR_W_MAX = 5.0


def _get(url: str, timeout: int = 90):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def solar_buckets(url: str, hours: int) -> dict:
    s = _get(f"{url}/api/solar/series?hours={hours}&bucket_s=300")["series"]
    return {dt.datetime.strptime(r["bucket"], "%Y-%m-%dT%H:%M:%SZ"): r for r in s}


def pack_buckets(url: str, source: str, start: dt.datetime,
                 end: dt.datetime) -> dict:
    """The readings endpoint pages on `since` with a row limit — it has no
    `hours`, and passing one silently returns the default 720 rows (one hour).
    That is worth spelling out; it produced a completely empty regime table
    the first time and looked like missing data rather than a bad query."""
    out: dict = {}
    cur = start
    while cur < end:
        rows = _get(f"{url}/api/readings?source_id={source}&limit=5000"
                    f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        rows = rows if isinstance(rows, list) else rows.get("readings", [])
        rows = [x for x in rows if x["ts"][:19] < f"{end:%Y-%m-%dT%H:%M:%S}"]
        if not rows:
            break
        for x in rows:
            t = dt.datetime.strptime(x["ts"][:19], "%Y-%m-%dT%H:%M:%S")
            k = t.replace(minute=t.minute // 5 * 5, second=0)
            out.setdefault(k, []).append(x.get("pack_p") or 0.0)
        newest = max(x["ts"] for x in rows)
        nxt = dt.datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    return {k: sum(v) / len(v) for k, v in out.items()}


def night_offset(sol: dict, pack: dict, day: dt.date) -> list[tuple]:
    """Dark hours are 07:00-11:00 UTC (00:00-04:00 local, PDT)."""
    res = []
    for t, pp in pack.items():
        s = sol.get(t)
        if s is None:
            continue
        if t.date() != day or not (7 <= t.hour < 11):
            continue
        if (s.get("pv_v") or 0) > DARK_PV_V_MAX:
            continue
        if (s.get("solar_w") or 0) > DARK_SOLAR_W_MAX:
            continue
        dw = s.get("dc_w") or 0
        if dw <= 0 or abs(pp) > FRIDGE_OFF_MAX_W:
            continue
        res.append((pp, dw, pp + dw))
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nights", type=int, default=5)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    ap.add_argument("--end", help="last night to include, YYYY-MM-DD")
    a = ap.parse_args()

    last = (dt.date.fromisoformat(a.end) if a.end
            else dt.datetime.now(dt.timezone.utc).date())
    sol = solar_buckets(a.url, hours=(a.nights + 1) * 24)

    print(f"{'night':<12}{'n':>4}{'pack_p':>10}{'dc_w':>10}"
          f"{'residual':>11}{'ratio':>8}")
    pooled: list[tuple] = []
    for i in range(a.nights - 1, -1, -1):
        day = last - dt.timedelta(days=i)
        start = dt.datetime.combine(day, dt.time(7), dt.timezone.utc)
        end = dt.datetime.combine(day, dt.time(11), dt.timezone.utc)
        res = night_offset(sol, pack_buckets(a.url, a.source, start, end), day)
        if not res:
            continue
        pooled += res
        pm = statistics.median(x[0] for x in res)
        dm = statistics.median(x[1] for x in res)
        print(f"{day.isoformat():<12}{len(res):>4}{pm:>10.1f}{dm:>10.1f}"
              f"{statistics.median(x[2] for x in res):>11.1f}"
              f"{abs(pm) / dm:>8.2f}")

    if not pooled:
        print("no dark fridge-off buckets found")
        return 1
    resid = [x[2] for x in pooled]
    print(f"\npooled n={len(pooled)}  median residual "
          f"{statistics.median(resid):.1f} W  stdev {statistics.pstdev(resid):.1f} W")
    print("residual > 0 means the inverter claims to draw MORE than the "
          "battery supplies, which is impossible — see the module docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
