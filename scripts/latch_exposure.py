#!/usr/bin/env python3
"""How long the array is ACTUALLY clamped per latch. Runs OFF the Pi.

`mppt_latched` carries a `clamped_s` field and it is not exposure. It is
emitted at the instant the confirmation threshold is crossed:

    if not self.latched and now - self.clamp_since >= LATCH_CONFIRM_S:
        ...  "clamped_s": round(now - self.clamp_since)

so it equals LATCH_CONFIRM_S every time, by construction — 601..608 s across
every latch on record, a 7 s spread on a 600 s constant. A field that cannot
vary is not a measurement, and "exposure is down to about 10 minutes" was read
off it.

This is the same shape as the unreachable recovery branch in cliff_table.py:
a number guaranteed by the code, quoted as a property of the array.

Real exposure spans two events and has three parts:

    LATCH_CONFIRM_S            clamped but not yet confirmed (600 s, fixed)
  + unlatched_ts - latched_ts  confirmed, waiting for the guard and the fix
  ( - LATCH_RELEASE_S )        the trailing grace before `mppt_unlatched`
                               fires; NOT subtracted below, see the note.

    python3 scripts/latch_exposure.py [--hours 400]

LATCH_RELEASE_S (120 s) is deliberately left in. The array is genuinely
recovered for that window — the detector is just waiting to be sure — so
subtracting it would give the most flattering number available rather than the
honest one. Treat the result as an upper bound accurate to about two minutes,
and note the bias direction rather than quietly removing it.

WHAT IT SAYS: the median is well above the 10 minutes `clamped_s` implies, and
the exact figure MOVES — it was 19.9 min when this was written and 14.8 min on
2026-08-29, partly because the early-bounce trigger now prevents many clamps
from forming at all. Regenerate; do not quote this paragraph.

The 19.9 figure was also computed on TRUNCATED data. `/api/xanbus_events` is
newest-first with no `before` parameter, so the `since` walk below could not
page backwards: unfiltered, it fetched the newest `limit` rows and then stepped
`since` forward past everything it had missed. Filtering server-side by event
name puts the window under the cap, and the count is now checked so truncation
cannot pass unnoticed.

Only latches with a matching `mppt_unlatched` can be measured. Unpaired ones
are reported as a count rather than dropped silently — a filter that discards
without saying how much is how the cliff table went blind.
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

from xanbus_telemetry import LATCH_CONFIRM_S, LATCH_RELEASE_S   # noqa: E402

UTC = dt.timezone.utc
LOCAL_OFFSET_H = -7


def fetch_events(url: str, source: str, hours: int) -> list[dict]:
    """Walk forward by timestamp; the endpoint caps at 2000 rows per call."""
    out: dict[tuple, dict] = {}
    cur = dt.datetime.now(UTC) - dt.timedelta(hours=hours)
    for _ in range(40):
        # FILTER SERVER-SIDE. /api/xanbus_events is NEWEST-first and has no
        # `before` parameter, so a `since` walk cannot page backwards: with more
        # matches than `limit`, you get the newest `limit` and then advancing
        # `since` to max(ts) steps FORWARD past everything you missed. Silent,
        # and it never recovers.
        #
        # Unfiltered, 400 h of chg_stage/chg_target/mppt_energy is far over the
        # cap, so this script was reading a truncated tail and calling the gap
        # "coverage is partial for older episodes". It was not the cap; it was
        # this walk.
        #
        # Filtering to just the events we need puts the whole window under the
        # cap, and the count is checked below so truncation cannot go unnoticed.
        q = (f"{url}/api/xanbus_events?source_id={source}&limit=2000"
             f"&event=mppt_latched,mppt_unlatched"
             f"&since={cur:%Y-%m-%dT%H:%M:%SZ}")
        with urllib.request.urlopen(q, timeout=90) as r:
            got = json.load(r).get("events", [])
        if not got:
            break
        new = 0
        for e in got:
            k = (e["ts"], e["event"], json.dumps(e.get("data"), sort_keys=True))
            if k not in out:
                out[k] = e
                new += 1
        if len(got) >= 2000:
            print(f"!! {len(got)} events returned at the limit — the window may "
                  f"be TRUNCATED and any total below is a floor, not a count.",
                  file=sys.stderr)
        mx = max(e["ts"] for e in got)
        if not new or mx <= f"{cur:%Y-%m-%dT%H:%M:%SZ}":
            break
        cur = dt.datetime.strptime(mx[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return sorted(out.values(), key=lambda e: e["ts"])


def _ts(e: dict) -> dt.datetime:
    return dt.datetime.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


def pair(events: list[dict]) -> tuple[list[dict], int]:
    """Match each mppt_latched to the next mppt_unlatched."""
    out, pending, unpaired = [], None, 0
    for e in events:
        if e["event"] == "mppt_latched":
            if pending is not None:
                unpaired += 1
            pending = e
        elif e["event"] == "mppt_unlatched" and pending is not None:
            confirm = pending["data"].get("clamped_s", LATCH_CONFIRM_S)
            out.append({
                "at": _ts(pending) + dt.timedelta(hours=LOCAL_OFFSET_H),
                "cleared": _ts(e) + dt.timedelta(hours=LOCAL_OFFSET_H),
                "reported_s": confirm,
                "exposure_s": confirm + (_ts(e) - _ts(pending)).total_seconds(),
            })
            pending = None
    return out, unpaired + (1 if pending is not None else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=400)
    ap.add_argument("--url", default="https://volts.alti2.de")
    ap.add_argument("--source", default="pi-barge")
    a = ap.parse_args()

    ev = fetch_events(a.url, a.source, a.hours)
    rows, unpaired = pair(ev)
    if not rows:
        print("no completed latch/unlatch pairs in window")
        return 1

    print(f"LATCH_CONFIRM_S={LATCH_CONFIRM_S}  LATCH_RELEASE_S={LATCH_RELEASE_S}"
          f"  (release NOT subtracted — see docstring)\n")
    print("| latched (local) | cleared | reported clamped_s | TRUE exposure |")
    print("|---|---|---|---|")
    for r in rows:
        print(f"| {r['at']:%m-%d %H:%M} | {r['cleared']:%H:%M} "
              f"| {r['reported_s']/60:.1f} min | {r['exposure_s']/60:.1f} min |")

    # Spread, not distinct-count: the values are 600/601/602, three "distinct"
    # numbers that are obviously one number plus sampling jitter. Counting
    # distinct values called that "varies" and would have buried the finding.
    rep = [r["reported_s"] for r in rows]
    spread = max(rep) - min(rep)
    exp = [r["exposure_s"] / 60 for r in rows]
    print(f"\n**reported `clamped_s`: {min(rep):.0f}..{max(rep):.0f} s across "
          f"{len(rows)} latches, spread {spread:.0f} s vs LATCH_CONFIRM_S="
          f"{LATCH_CONFIRM_S}** — "
          + ("a CONSTANT. It measures the confirmation threshold, not exposure"
             if spread <= 0.05 * LATCH_CONFIRM_S
             else "this now VARIES; the emitter changed, re-read the docstring"))
    print(f"**TRUE exposure: median {statistics.median(exp):.1f}, "
          f"mean {statistics.mean(exp):.1f}, max {max(exp):.1f} minutes** "
          f"(n={len(exp)})")
    if unpaired:
        print(f"\n{unpaired} latch(es) had no matching mppt_unlatched in the "
              f"window and are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
