#!/usr/bin/env python3
"""Close the whole-system energy balance for a day, and see which meter breaks it.
Runs OFF the Pi (CLAUDE.md #1).

Every previous attempt on #5/#11 compared TWO meters. This uses all three at
once against a conservation law, which is stronger: it does not need to assume
which meter is right, only that charge is conserved.

    MPPT delivered  =  net charge into the pack  +  house load

The MPPT is the only source. There is no grid at the site, and the generator
has never run — `gen_start` count is zero over the entire record — so anything
the pack gained plus anything the house drew had to come through the MPPT.

    python3 scripts/energy_balance.py --day 2026-08-11

Each term from a different instrument, deliberately:

  MPPT delivered   the MPPT's own `day_ah` counter (PGN 127166 @46), read out
                   of the device rather than integrated here. Guarded: day_wh /
                   day_ah must come out near the pack voltage or the decode has
                   moved, and the script says so instead of continuing.
  net into pack    integral of the BMS's reported current. The pack is two 4-cell
                   units in SERIES, so the pack current is the AVERAGE of the
                   two, not the sum — summing double-counts and is an easy and
                   invisible error here.
  house load       dc_w / dc_v from the inverter's DC-bus view, integrated.

WHAT IT SAYS, 2026-08-11 (regenerate before quoting):

    MPPT delivered      60.00 Ah
    net into pack      +14.44 Ah
    house load          88.31 Ah
    -> sinks 102.75 Ah against a 60.00 Ah source: a 42.75 Ah / ~1170 Wh DEFICIT

The day consumed far more than the only source supplied while the battery
GAINED charge. That is impossible, so at least one meter is wrong by a lot, and
the load term dominates the error budget.

Implied average house load, by whose number you believe:

    dc_w as measured                 116.9 W
    MPPT counter taken as truth       60.3 W
    BMS dark-hours measurement        81.0 W    (docs #12, meter_offset.py)

RUN IT ON MORE THAN ONE DAY. On 2026-08-11 a 20% MPPT under-read gives 80.5 W
against the BMS's 81.0 W, which looks like a decisive convergence. It is not:
on 2026-08-10 the correction needed to hit 81 W is 30%. Checking the second day
is what turned a "settled" result back into a bounded one.

What survives both days:

    day     deficit   dc_w implies   MPPT@25% implies   BMS says
    08-10   1409 Wh      116.0 W          76.1 W         81.0 W
    08-11   1173 Wh      117.2 W          87.1 W         81.0 W

- The balance fails badly and consistently — about half the source goes
  unaccounted for, both days.
- `dc_w` is remarkably STABLE at 116-117 W and 43-45% above the BMS on both
  days. Precise, and apparently inaccurate — which is the worst combination,
  because precision reads as trustworthiness.
- A single ~25% MPPT under-read brackets the BMS figure (one day above, one
  below, mean ~81.6 W). That is consistent, but it is a two-point bracket, not
  a calibration.
- No single documented correction CLOSES the balance. Taking dc_w as truth
  needs the MPPT to under-read by ~51%; taking the MPPT as truth needs dc_w
  ~51% high. Either is far outside anything measured. So the error is probably
  split across both, and the largest term — `dc_w` — remains the prime suspect,
  as the night-time comparison also concluded.

Unmetered DC loads cannot rescue any of this: they would make the deficit
LARGER. A systematic error in the BMS current integral could, and the BMS is
known to be 12% self-inconsistent. Treat the output as a bound on how far the
three can be reconciled, not as a calibration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7
MAX_SAMPLE_GAP_S = 60.0
BUCKET_S = 15


def _get(url: str):
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.load(r)


def bms_net_ah(url: str, source: str, start: dt.datetime,
               end: dt.datetime) -> tuple[float, float, float]:
    rows, cur = [], start
    while cur < end:
        g = _get(f"{url}/api/readings?source_id={source}&limit=5000"
                 f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        g = g if isinstance(g, list) else g.get("readings", [])
        g = [x for x in g if x["ts"][:19] < f"{end:%Y-%m-%dT%H:%M:%S}"]
        if not g:
            break
        rows += g
        nxt = dt.datetime.strptime(max(x["ts"] for x in g)[:19],
                                   "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    rows.sort(key=lambda x: x["ts"])
    ah = cov = worst = 0.0
    prev = None
    for x in rows:
        ia, ib = x.get("i_a"), x.get("i_b")
        if ia is None or ib is None:
            continue
        # SERIES pack: average, never sum.
        i = (ia + ib) / 2
        t = dt.datetime.strptime(x["ts"][:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        if prev:
            g = t - prev[0]
            worst = max(worst, g)
            if 0 < g < MAX_SAMPLE_GAP_S:
                ah += (i + prev[1]) / 2 * g / 3600
                cov += g
        prev = (t, i)
    span = (end - start).total_seconds()
    return ah, cov / span * 100 if span else 0.0, worst


def load_ah(url: str, source: str, start: dt.datetime,
            end: dt.datetime) -> tuple[float, float]:
    ser = _get(f"{url}/api/solar/series?source_id={source}&hours=400"
               f"&bucket_s={BUCKET_S}")["series"]
    ah = 0.0
    n = 0
    for s in ser:
        t = dt.datetime.strptime(s["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if not (start <= t <= end):
            continue
        w, v = s.get("dc_w"), s.get("dc_v")
        if w is None or v is None or not (0 <= w <= 6000) or v < 10:
            continue
        ah += (w / v) * BUCKET_S / 3600
        n += 1
    return ah, n * BUCKET_S / 3600


def mppt_day(url: str, source: str, day: dt.date) -> tuple[float, float]:
    ev = _get(f"{url}/api/xanbus_events?source_id={source}"
              f"&event=mppt_energy&limit=2000")["events"]
    same = [e for e in ev
            if (dt.datetime.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S")
                + dt.timedelta(hours=LOCAL_OFFSET_H)).date() == day]
    if not same:
        return 0.0, 0.0
    return (max(e["data"]["day_ah"] for e in same),
            max(e["data"]["day_wh"] for e in same))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="local date YYYY-MM-DD")
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    day = dt.date.fromisoformat(a.day)
    start = dt.datetime.combine(day, dt.time()).replace(tzinfo=UTC) \
        - dt.timedelta(hours=LOCAL_OFFSET_H)
    end = min(start + dt.timedelta(days=1), dt.datetime.now(UTC))

    mp_ah, mp_wh = mppt_day(a.url, a.source, day)
    if not mp_ah:
        print("no MPPT counter data for that day")
        return 1
    v_implied = mp_wh / mp_ah
    if not (20.0 <= v_implied <= 35.0):
        print(f"DECODE GUARD FAILED: day_wh/day_ah = {v_implied:.2f}, "
              f"not a pack voltage. PGN 127166 layout may have moved.")
        return 1

    net, cov, worst = bms_net_ah(a.url, a.source, start, end)
    ld, hrs = load_ah(a.url, a.source, start, end)

    print(f"{day}  ({hrs:.1f} h covered)   pack V from MPPT counter "
          f"= {v_implied:.2f}\n")
    print(f"  MPPT delivered (own day_ah) : {mp_ah:8.2f} Ah   ({mp_wh:.0f} Wh)")
    print(f"  net into pack (BMS current) : {net:+8.2f} Ah   "
          f"(coverage {cov:.1f}%, worst gap {worst:.0f}s)")
    print(f"  house load (dc_w / dc_v)    : {ld:8.2f} Ah")
    sinks = net + ld
    print(f"  {'-'*44}")
    print(f"  sinks                       : {sinks:8.2f} Ah")
    print(f"  DEFICIT (sinks - source)    : {sinks - mp_ah:+8.2f} Ah  "
          f"= {(sinks - mp_ah) * v_implied:+.0f} Wh")

    if hrs:
        print(f"\n  implied average house load over {hrs:.1f} h:")
        print(f"    dc_w as measured          : {ld * v_implied / hrs:6.1f} W")
        print(f"    MPPT counter as truth     : {(mp_ah - net) * v_implied / hrs:6.1f} W")
        for ur in (0.20, 0.25, 0.30):
            t = (mp_ah / (1 - ur) - net) * v_implied / hrs
            print(f"    MPPT corrected by {ur*100:.0f}% under-read: {t:6.1f} W")
        print(f"    BMS dark-hours (docs #12) :   81.0 W")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
