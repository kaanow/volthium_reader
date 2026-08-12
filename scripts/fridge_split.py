#!/usr/bin/env python3
"""Split the dark-hours load into fridge-on and fridge-off, and see what dc_w
does across the step. Runs OFF the Pi (CLAUDE.md #1).

Two things fall out, and the second decides a pending ledger question.

**1. The fridge, measured a second way.** Task #32's 76 W / 29% duty came from a
residual method. In full darkness the BMS's own `pack_p` is cleanly bimodal, so
the fridge can be read straight off the histogram with no residual and no
second meter. The two methods agree to within a few percent, which is the first
unfitted convergence this project has produced.

**2. `dc_w` DOES NOT SEE THE FRIDGE.** Across a ~74 W step in real bus load,
`dc_w` moves by less than its own noise. It is the inverter's own draw, not the
DC bus, so `load_w` — a straight passthrough of `dc_w` — structurally omits the
largest cycling load on the system. That is wrong in KIND, not in calibration,
and no offset correction fixes it.

    python3 scripts/fridge_split.py [--hours 60]

WHY THIS ARGUES AGAINST THE -32 W CORRECTION (measured 2026-08-12):

    fridge OFF   BMS  80.3 W    <- only the inverter is drawing
    fridge ON    BMS 153.9 W
    step                 73.6 W    the fridge
    duty                 32.6 %
    true total load     104.3 W    time-weighted
    dc_w                112.9 W

In the fridge-OFF state the only load IS the inverter, so `dc_w` 112.9 against
BMS 80.3 is a genuine ~33 W over-read of the inverter channel — the 32 W on
record, confirmed.

But `load_w` is consumed as TOTAL house load, and there `dc_w` is only 8% high
(112.9 vs 104.3) — because the ~33 W inverter over-read and the ~24 W
time-averaged fridge it omits very nearly cancel.

**So subtracting 32 W from `dc_w` would make `load_wh` WORSE**: 81 W against a
true 104 W, under by 22%, where leaving it alone is over by 8%. The offset is
real and the correction is still wrong, because the quantity it corrects is not
the quantity being used. Two errors cancelling is not the same as being right —
this stops holding the moment the fridge duty or the inverter draw changes — but
the fix is to add the fridge, not to shift `dc_w`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from solar_geometry import sun_elevation_deg   # noqa: E402

UTC = dt.timezone.utc
DARK_ELEV_DEG = -6.0     # civil twilight; no PV contribution at all below this


def _get(u: str):
    with urllib.request.urlopen(u, timeout=180) as r:
        return json.load(r)


def _dark(ts: str) -> bool:
    t = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return sun_elevation_deg(t.timestamp()) < DARK_ELEV_DEG


def bms_dark(url: str, source: str, hours: int) -> list[float]:
    out, cur = [], dt.datetime.now(UTC) - dt.timedelta(hours=hours)
    end = dt.datetime.now(UTC)
    while cur < end:
        g = _get(f"{url}/api/readings?source_id={source}&limit=5000"
                 f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        g = g if isinstance(g, list) else g.get("readings", [])
        if not g:
            break
        out += [abs(x["pack_p"]) for x in g
                if x.get("pack_p") is not None and _dark(x["ts"])]
        nxt = dt.datetime.strptime(max(x["ts"] for x in g)[:19],
                                   "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
        if nxt <= cur:
            break
        cur = nxt + dt.timedelta(seconds=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=60)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    bms = bms_dark(a.url, a.source, a.hours)
    if len(bms) < 200:
        print(f"only {len(bms)} dark BMS samples — widen --hours")
        return 1

    # Otsu-style split: the threshold maximising between-class variance. Chosen
    # from the data rather than hardcoded, so a change in either load moves it.
    vals = sorted(bms)
    best, split = -1.0, vals[len(vals) // 2]
    for i in range(len(vals) // 20, len(vals) - len(vals) // 20):
        lo, hi = vals[:i], vals[i:]
        w = len(lo) * len(hi) * (statistics.mean(hi) - statistics.mean(lo)) ** 2
        if w > best:
            best, split = w, (vals[i - 1] + vals[i]) / 2

    lo = [v for v in bms if v < split]
    hi = [v for v in bms if v >= split]
    step = statistics.mean(hi) - statistics.mean(lo)
    duty = len(hi) / len(bms)
    total = statistics.mean(bms)

    ser = _get(f"{a.url}/api/solar/series?source_id={a.source}"
               f"&hours={a.hours}&bucket_s=60")["series"]
    dw = [s["dc_w"] for s in ser
          if s.get("dc_w") is not None and 0 <= s["dc_w"] <= 6000
          and _dark(s["bucket"])]
    q = statistics.quantiles(dw, n=100)

    print(f"dark samples: BMS {len(bms)}, dc_w {len(dw)}   "
          f"(Otsu split at {split:.1f} W)\n")
    print(f"  fridge OFF   BMS {statistics.mean(lo):6.1f} W   "
          f"n={len(lo)} ({100*(1-duty):.1f}%)")
    print(f"  fridge ON    BMS {statistics.mean(hi):6.1f} W   "
          f"n={len(hi)} ({100*duty:.1f}%)")
    print(f"  step (the fridge)  {step:6.1f} W")
    print(f"  duty               {100*duty:6.1f} %")
    print(f"  fridge energy      {step*duty*24/1000:6.2f} kWh/day"
          f"   (task #32 derived: 0.53)")
    print(f"\n  true total load    {total:6.1f} W   (time-weighted BMS)")
    print(f"  dc_w               {statistics.mean(dw):6.1f} W   "
          f"p5 {q[4]:.0f} .. p95 {q[94]:.0f}, span {q[94]-q[4]:.0f} W")
    print(f"\n  dc_w spans {q[94]-q[4]:.0f} W while the bus steps by {step:.0f} W"
          f"  ->  IT DOES NOT SEE THE FRIDGE")
    print(f"  inverter-only over-read: dc_w {statistics.mean(dw):.1f} vs BMS "
          f"{statistics.mean(lo):.1f} = {statistics.mean(dw)-statistics.mean(lo):+.1f} W")
    print(f"  as TOTAL load          : dc_w {statistics.mean(dw):.1f} vs true "
          f"{total:.1f} = {statistics.mean(dw)-total:+.1f} W "
          f"({(statistics.mean(dw)-total)/total*100:+.0f}%)")
    adj = statistics.mean(dw) - (statistics.mean(dw) - statistics.mean(lo))
    print(f"  if -{statistics.mean(dw)-statistics.mean(lo):.0f} W were applied: "
          f"{adj:.1f} vs true {total:.1f} = {(adj-total)/total*100:+.0f}% "
          f"-> WORSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
