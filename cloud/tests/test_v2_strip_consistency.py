"""The strip chart's two fill paths, and what its demand side leaves out.

1. BACKFILL AND LIVE WERE TWO COPIES OF ONE LOOP, differing in a single line,
   and that line was the bug:

       // backfill
       const batt = pByT.get(t) ?? 0;     // this row's own 15 s bucket
       // live
       const batt = battW();              // the ONE latest reading

   The live branch recomputed nothing per row, so every row in a multi-row
   batch got the SAME battery power. At the steady 15 s poll that is one row
   and looks correct; after a tab sleep or a network stall the entire
   recovered span is drawn with one flat value — exactly when someone is
   looking to find out what they missed.

   Before 2026-10-04 it was worse: battW() returned the smoothed EMA while the
   backfill used AVG(pack_p), so the join was across two different signals.

2. THE DEMAND SIDE OMITS THE DC-BUS LOAD. loadAt() returns dc_w, the
   INVERTER's DC input, which is blind to the bus-wired fridge (~5 A) and the
   Xanbus accessories. Supply therefore legitimately exceeds demand whenever
   the compressor runs, under a heading reading "Power balance" with a legend
   implying nothing was left out.

   It is disclosed rather than drawn, on purpose. A per-row DC-bus figure
   would have to come from battery discharge + solar - inverter input: a
   difference across two meters known to sit ~33 W apart, which is the method
   dcLoadW() exists to avoid. Closing a cosmetic gap with a plausible wrong
   number is a worse trade than an honest gap that says so.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "cloud/server/static/v2.html"


def _code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


def test_there_is_one_row_push_path_not_two():
    code = _code_only(PAGE.read_text())
    assert "pushRows" in code, "the unified push helper is gone"
    # Scope to pushRows. drawFlow() legitimately uses battW() for the LIVE
    # flow diagram — an earlier version of this assertion was global and
    # matched that, which is a false positive, not a finding.
    m = re.search(r"pushRows\s*=\s*\([^)]*\)\s*=>\s*\{(.*?)\n  \};",
                  code, re.S)
    assert m, "pushRows is gone or was restructured"
    assert "battW()" not in m.group(1), (
        "a row's battery power is being taken from the single latest reading "
        "again; a catch-up batch would be drawn with one flat value")
    # And there must be no second, divergent fill loop.
    fills = len(re.findall(r"hist\.push\(", code))
    assert fills == 1, (
        f"found {fills} hist.push sites — backfill and live have diverged "
        f"into separate loops again")


def test_rows_join_on_their_own_bucket():
    code = _code_only(PAGE.read_text())
    m = re.search(r"pushRows\s*=\s*\(([^)]*)\)\s*=>\s*\{(.*?)\n  \};",
                  code, re.S)
    assert m, "pushRows is gone or was restructured"
    body = m.group(2)
    assert re.search(r"pByT\.get\(t\)", body), (
        "pushRows no longer looks the battery value up by the row's own ts")


def test_a_row_without_a_bucket_is_skipped_not_zero_filled():
    """`?? 0` would draw a fictitious moment of no battery activity whenever
    the aggregate lagged the raw row."""
    code = _code_only(PAGE.read_text())
    m = re.search(r"pushRows\s*=\s*\([^)]*\)\s*=>\s*\{(.*?)\n  \};", code, re.S)
    body = m.group(1)
    assert "pByT.has(t)" in body, (
        "a missing bucket is no longer skipped — it will be zero-filled")
    assert not re.search(r"pByT\.get\(t\)\s*\?\?\s*0", body), (
        "zero-fill is back")


def test_the_battery_series_and_the_bucket_average_share_a_signal():
    """p_avg must stay AVG(pack_p) while battW() returns pack_p, or the two
    halves of the chart mean different things again."""
    db = (REPO / "cloud/server/db.py").read_text()
    assert "AVG(pack_p)" in db and "AS p_avg" in db, (
        "p_avg is no longer AVG(pack_p); the strip's battery series would be "
        "on a different signal from battW()")


def test_the_demand_side_omission_is_disclosed():
    src = PAGE.read_text()
    assert "DC bus load not shown" in src, (
        "the chart implies its demand side is complete; it excludes the "
        "DC-bus load (fridge + Xanbus accessories)")
    # And the disclosure must not be styled as if it were a data series.
    assert ".legend .legend-note::before { display: none; }" in src, (
        "the note would render with an empty colour swatch, reading as a "
        "legend entry whose colour failed to load")


def test_the_discredited_meter_difference_was_not_revived():
    """The tempting fix is to synthesise DC load by differencing meters. That
    is the ~33 W-offset method dcLoadW() exists to avoid."""
    code = _code_only(PAGE.read_text())
    m = re.search(r"function\s+loadAt\([^)]*\)\s*\{(.*?)\n\}", code, re.S)
    assert m, "loadAt is gone"
    # dLoad must still come straight from h.load, not a reconstructed figure.
    assert re.search(r"dLoad\s*=\s*hist\.map\(h\s*=>\s*h\.load\)", code), (
        "the demand series is no longer the measured load; check whether a "
        "meter-difference estimate was introduced")
