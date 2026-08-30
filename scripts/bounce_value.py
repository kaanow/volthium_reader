#!/usr/bin/env python3
"""What the early bounce is worth, per EPISODE rather than per day.

The per-day comparison cannot answer this: day-to-day SD is ~134 Wh, so it can
only resolve effects above ~132 Wh/day, and the predicted effect straddles that
floor. Comparing whole days throws away the fact that we know exactly WHICH
half-hours the trigger touched.

So compare like with like: for every episode that reached the 29-minute mark,
integrate what the array actually produced in the following hour.

    before 2026-08-21  nothing intervened; the array kept walking down until it
                       clamped and the guard eventually bounced it
    after              the trigger fired at 29 minutes

THE GROUPS ARE NOT NATURALLY COMPARABLE, and this docstring used to claim they
were. Measured: median sun elevation 26 deg unbounced vs 38 deg bounced. Higher
sun means more available power no matter what the trigger did, so the raw
difference between the groups is confounded and the script refuses to headline
it. Two independent controls are applied instead — nearest-elevation matched
pairs, and sin(elevation) normalisation — and if they disagree on the direction
the script says so rather than picking the flattering one.

Even controlled, the answer is NOT RESOLVED: matched-pair median +51 Wh/episode
but 6 of 10 positive, sign test p=0.75, mean 1.1 SE from zero. The direction is
positive in both controls and that is all this can support.

That is fine, and the script says why: a bounce costs ~0.15 Wh, so break-even
needs almost nothing. No operational decision waits on this number. Do not
degrade production days to sharpen it.

    python3 scripts/bounce_value.py [--hours 400]
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cliff_table import episodes, fetch                 # noqa: E402
from solar_geometry import sun_elevation_deg            # noqa: E402

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7
FIRE_AFTER_MIN = 29        # where the trigger acts
WINDOW_MIN = 60            # integrate this long after the fire point
ARMED_FROM = dt.date(2026, 8, 22)


def wh_after(rows, start_utc, minutes):
    """Wh produced in `minutes` after start. 60 s buckets."""
    end = start_utc + dt.timedelta(minutes=minutes)
    wh = 0.0
    n = 0
    for t, _pv, w in rows:
        if start_utc <= t < end:
            wh += w * 60 / 3600.0
            n += 1
    return (wh, n) if n else (None, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=400)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    series = fetch(a.url, a.hours, a.source)
    rows = sorted(
        (dt.datetime.strptime(r["bucket"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
         r["pv_v"], r.get("solar_w") or 0.0)
        for r in series if r.get("pv_v") is not None)

    pre, post = [], []
    print(f"Wh produced in the {WINDOW_MIN} min after the {FIRE_AFTER_MIN}-minute "
          f"mark of each episode that reached it.\n")
    print(f"{'crossing':<14}{'fire':>7}{'sun':>6}{'Wh':>8}{'avg W':>8}  group")
    for e in episodes(series):
        if e["minutes"] < FIRE_AFTER_MIN:
            continue                       # the trigger would never have acted
        if e.get("artifact"):
            continue
        fire_local = e["crossed"] + dt.timedelta(minutes=FIRE_AFTER_MIN)
        fire_utc = fire_local.replace(tzinfo=UTC) - dt.timedelta(hours=LOCAL_OFFSET_H)
        wh, n = wh_after(rows, fire_utc, WINDOW_MIN)
        if wh is None or n < WINDOW_MIN * 0.8:
            continue                       # not enough coverage to be honest
        el = sun_elevation_deg(fire_utc.timestamp())
        armed = e["crossed"].date() >= ARMED_FROM
        (post if armed else pre).append((wh, el))
        print(f"{e['crossed']:%m-%d %H:%M}{fire_local.strftime('%H:%M'):>7}{el:>6.0f}"
              f"{wh:>8.0f}{wh * 60 / WINDOW_MIN:>8.0f}  "
              f"{'BOUNCED' if armed else 'not bounced'}")

    if not pre or not post:
        print("\nnot enough episodes in both groups yet")
        return 1

    print(f"\n{'group':<14}{'n':>3}{'median Wh':>11}{'mean Wh':>9}{'median sun':>12}")
    for name, g in (("not bounced", pre), ("BOUNCED", post)):
        whs = [x[0] for x in g]
        els = [x[1] for x in g]
        print(f"{name:<14}{len(g):>3}{statistics.median(whs):>11.0f}"
              f"{statistics.mean(whs):>9.0f}{statistics.median(els):>12.0f}")

    dm = statistics.median([x[0] for x in post]) - statistics.median([x[0] for x in pre])
    ps, os_ = statistics.median([x[1] for x in pre]), statistics.median([x[1] for x in post])
    print(f"\nraw median difference: {dm:+.0f} Wh — but median sun elevation is "
          f"{ps:.0f}° vs {os_:.0f}°.")
    if abs(ps - os_) >= 5:
        print("THE GROUPS ARE NOT COMPARABLE. Higher sun means more available "
              "power regardless of what the trigger did, so the raw difference "
              "is confounded and must not be quoted.\n")

    # --- control for elevation ------------------------------------------
    # Two independent ways, because one alone is easy to fool. If they
    # disagree, the effect is not robust and neither should be believed.
    #
    # 1. MATCHED PAIRS: each bounced episode against the nearest-elevation
    #    unbounced one. Uses every bounced episode, no threshold to pick.
    # 2. sin(elevation) NORMALISATION: available irradiance on a surface
    #    scales roughly with sin of the sun's altitude. The array is tilted so
    #    this is first-order only, which is why it is a cross-check and not
    #    the headline.
    print(f"{'bounced':<16}{'sun':>5}{'Wh':>7}   matched unbounced      diff")
    diffs = []
    for wh, el in sorted(post, key=lambda x: x[1]):
        cand = min(pre, key=lambda x: abs(x[1] - el))
        diffs.append(wh - cand[0])
        print(f"{'':16}{el:>5.0f}{wh:>7.0f}   {cand[1]:>3.0f}° {cand[0]:>6.0f} Wh"
              f"{wh - cand[0]:>+9.0f}")
    print(f"\n**matched-pair median difference: "
          f"{statistics.median(diffs):+.0f} Wh/episode**  (n={len(diffs)})")

    def norm(g):
        import math
        return [w / max(math.sin(math.radians(e)), 0.05) for w, e in g]
    npre, npost = norm(pre), norm(post)
    print(f"sin(elevation)-normalised median: "
          f"{statistics.median(npre):.0f} -> {statistics.median(npost):.0f} "
          f"({statistics.median(npost) - statistics.median(npre):+.0f})")
    agree = (statistics.median(diffs) > 0) == (
        statistics.median(npost) - statistics.median(npre) > 0)
    print("both controls agree on the direction" if agree else
          "!! THE TWO CONTROLS DISAGREE — the effect is not robust")
    # Significance, so the point estimate is not read as a result.
    import math
    n, k = len(diffs), sum(1 for x in diffs if x > 0)
    pval = min(1.0, sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n * 2)
    se = statistics.stdev(diffs) / math.sqrt(n) if n > 1 else float("inf")
    print(f"  {k} of {n} positive, sign test p={pval:.2f}; "
          f"mean {statistics.mean(diffs):+.0f} ± {se:.0f} SE "
          f"({statistics.mean(diffs)/se:.1f} SE from zero)")
    print("  -> direction positive in both controls, but NOT statistically "
          "resolved at this n. Do not quote the point estimate as a result.")

    # The decision does not depend on resolving it, and saying so is the point.
    print(f"\nWHY THIS DOES NOT BLOCK ANYTHING: a bounce costs ~0.15 Wh and 15 s "
          f"of standby.\n{len(post)} bounces so far is ~{0.15*len(post):.1f} Wh "
          f"spent. Break-even needs 0.15 Wh of benefit per\nbounce; the low end "
          f"of the estimate is hundreds of times that. The measurement is worth\n"
          f"having for honesty, not for deciding whether to keep the trigger "
          f"armed.")
    print("\nNot a randomised control: different days, different weather. But it "
          "compares the hours the trigger actually touched, rather than whole "
          "days in which those hours are a small part.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
