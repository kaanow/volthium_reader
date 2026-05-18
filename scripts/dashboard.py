"""Tiny localhost dashboard. Opens at http://localhost:8421/

Reads the most recent rows of data/pack.csv and serves a self-refreshing
HTML page plus a JSON endpoint. No web framework dependency — uses the
stdlib http.server.

Run it alongside scripts/log.py; the logger writes the CSV and the dashboard
reads it.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import socket
import sys
import time
from collections import deque
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from volthium.events import detect_events  # noqa: E402
import discharge_model  # noqa: E402  — sibling script
import generator_advisor  # noqa: E402  — sibling script

# Cache the discharge profile fit for 60s.  The fit runs over the
# entire pack.csv, which is fine for our scale (KBs of CSV per day)
# but no need to redo it every 5s dashboard refresh.
_discharge_cache = {"computed_at": 0.0, "profile": None}


_advisor_cache = {"computed_at": 0.0, "rec": None}
_harvest_cache = {"computed_at": 0.0, "snap": None}


def get_today_harvest():
    """Run scripts/today_harvest's snapshot against current data.
    Cached 60s. Returns a dict or None on any error / missing data."""
    import subprocess
    now = time.monotonic()
    if (now - _harvest_cache["computed_at"]) < 60.0 and _harvest_cache["snap"] is not None:
        return _harvest_cache["snap"]
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "today_harvest.py"),
             "--pack-csv", str(CSV_PATH),
             "--weather-csv", str(WEATHER_CSV_PATH),
             "--json"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        if proc.returncode != 0:
            return None
        snap = json.loads(proc.stdout)
    except Exception:
        return None
    _harvest_cache["computed_at"] = now
    _harvest_cache["snap"] = snap
    return snap


def get_recommendation():
    """Run scripts/generator_advisor's logic against current data.
    Cached 60s. Returns a dict (asdict of Recommendation) or None
    on any error / missing data."""
    import subprocess
    now = time.monotonic()
    if (now - _advisor_cache["computed_at"]) < 60.0 and _advisor_cache["rec"] is not None:
        return _advisor_cache["rec"]
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "generator_advisor.py"),
             "--pack-csv", str(CSV_PATH),
             "--weather-csv", str(WEATHER_CSV_PATH),
             "--json"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        if proc.returncode != 0:
            return None
        rec = json.loads(proc.stdout)
    except Exception:
        return None
    _advisor_cache["computed_at"] = now
    _advisor_cache["rec"] = rec
    return rec


def get_discharge_profile():
    """Return the cached hour-of-day discharge profile, recomputing
    at most once a minute."""
    now = time.monotonic()
    if (now - _discharge_cache["computed_at"]) < 60.0 and _discharge_cache["profile"] is not None:
        return _discharge_cache["profile"]
    try:
        samples = discharge_model.load(CSV_PATH)
    except Exception:
        return None
    if not samples:
        return None
    profile = discharge_model.fit(samples)
    _discharge_cache["computed_at"] = now
    _discharge_cache["profile"] = profile
    return profile

try:
    import qrcode
    import qrcode.image.svg
    HAVE_QRCODE = True
except ImportError:
    HAVE_QRCODE = False


def detect_lan_ip() -> str | None:
    """Best-effort: figure out which interface IP the machine uses to reach
    the outside world. Doesn't actually send packets (UDP socket connect is
    purely routing-table lookup). Returns None if we can't tell."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def lan_qr_svg(url: str) -> str:
    """Return an inline SVG QR code for the given URL, or '' if qrcode lib
    isn't installed."""
    if not HAVE_QRCODE:
        return ""
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(url)
    qr.make(fit=True)
    factory = qrcode.image.svg.SvgPathImage
    img = qr.make_image(image_factory=factory)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()

CSV_PATH: Path  # set in main()
WEATHER_CSV_PATH: Path  # set in main()
HISTORY_N = 720   # samples to keep in the rolling window for sparkline (≈ 2h @ 10s)

# Working capacity estimate based on observed peak remaining_ah across the
# Barge Inn pair (see docs/hardware/bms_calibration.md). Used only for the
# overnight SOC projection — not for time-to-X math, which uses smoothed
# current and per-battery SOC % directly.
PROJECTION_CAPACITY_AH = 215.0

# tail-cache so the dashboard doesn't re-read the whole file on every request
_CACHE: dict = {"size": 0, "rows": deque(maxlen=HISTORY_N), "header": None}
CSV_HEADER_FALLBACK = (
    "ts,state,pack_v,pack_i,pack_p,soc_a,soc_b,v_a,v_b,i_a,i_b,t_a,t_b,"
    "remaining_ah_a,remaining_ah_b,delta_v_a,delta_v_b,smoothed_i,"
    "smoothed_p,minutes_remaining,name_a,name_b"
)


def read_recent(path: Path, n: int) -> list[dict]:
    """Return up to n most-recent rows. Reads only new bytes since the last call."""
    if not path.exists():
        return []
    size = path.stat().st_size
    # detect truncation / rotation
    if size < _CACHE["size"]:
        _CACHE["size"] = 0
        _CACHE["rows"].clear()
        _CACHE["header"] = None
    if size == _CACHE["size"]:
        rows = list(_CACHE["rows"])
    else:
        with path.open() as f:
            f.seek(_CACHE["size"])
            new = f.read()
            _CACHE["size"] = f.tell()
        for line in new.splitlines():
            if not line:
                continue
            if line.startswith("ts,"):
                _CACHE["header"] = line
                continue
            _CACHE["rows"].append(line)
        rows = list(_CACHE["rows"])
    header = _CACHE["header"] or CSV_HEADER_FALLBACK
    reader = csv.DictReader([header] + rows[-n:])
    return list(reader)


def to_num(v: str | None):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return v


def latest_weather_row() -> dict | None:
    """Read the last data row of data/weather.csv (or None if missing)."""
    if WEATHER_CSV_PATH is None or not WEATHER_CSV_PATH.exists():
        return None
    last = None
    header = None
    with WEATHER_CSV_PATH.open() as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if header is None:
                header = line.split(",")
                continue
            last = line.split(",")
    if not header or not last:
        return None
    return dict(zip(header, last))


def compute_projection(latest_pack: dict, weather: dict | None) -> dict | None:
    """Return {sunrise_iso, hours_to_sunrise, projected_soc_at_sunrise, ...}
    or None if we can't compute (no weather, not discharging, etc.).

    Only emits when state is `discharging` or `idle` and we have a sunrise.
    For charging/full, the existing time-to-full headline is the right answer.
    """
    if weather is None:
        return None
    sunrise_iso = weather.get("sunrise_iso")
    if not sunrise_iso:
        return None
    state = latest_pack.get("state")
    if state not in ("discharging", "idle"):
        return None

    # Parse sunrise. The weather CSV stores today's sunrise. If it's in
    # the past (overnight), the relevant one is +24h.
    try:
        sunrise_dt = datetime.fromisoformat(sunrise_iso)
    except ValueError:
        return None
    now = datetime.now()
    if sunrise_dt < now:
        from datetime import timedelta
        sunrise_dt = sunrise_dt + timedelta(days=1)
    hours_to_sunrise = (sunrise_dt - now).total_seconds() / 3600.0

    smoothed_i = latest_pack.get("smoothed_i")
    if smoothed_i is None:
        return None
    smoothed_i = float(smoothed_i)

    # Use the lower of (avg) per-battery SOC as the conservative starting
    # point for the projection — that's the limiting battery on discharge.
    sa = latest_pack.get("soc_a")
    sb = latest_pack.get("soc_b")
    if sa is None or sb is None:
        return None
    start_soc = min(float(sa), float(sb))

    # Two ways to project — prefer the hour-by-hour discharge model
    # if we have one, otherwise fall back to naive single-rate
    # extrapolation. Both are signed: negative = consuming.
    profile = get_discharge_profile()
    rate_label = f"at {smoothed_i:+.1f} A (smoothed)"
    method = "naive"

    if abs(smoothed_i) < 0.5 and (profile is None or not profile):
        projected_soc = start_soc
        rate_label = "current near zero"
    elif profile is not None and profile:
        # Hour-by-hour projection: sum |median current| × 1h across
        # the hours we'll traverse before sunrise.
        ah_consumed = discharge_model.project_overnight_ah(
            profile, now.hour, sunrise_dt.hour
        )
        if ah_consumed is not None and ah_consumed > 0:
            pct_change = -ah_consumed / PROJECTION_CAPACITY_AH * 100.0
            projected_soc = start_soc + pct_change
            method = "discharge_model"
            rate_label = f"profile fit (~{ah_consumed:.0f} Ah)"
        else:
            # No useful model output; fall through to naive
            ah_change = smoothed_i * hours_to_sunrise
            projected_soc = start_soc + ah_change / PROJECTION_CAPACITY_AH * 100.0
    else:
        # Naive fallback when no profile yet
        ah_change = smoothed_i * hours_to_sunrise
        projected_soc = start_soc + ah_change / PROJECTION_CAPACITY_AH * 100.0

    # Clamp display to reasonable bounds (-5 .. 100)
    projected_soc_clamped = max(-5.0, min(100.0, projected_soc))

    return {
        "sunrise_iso": sunrise_dt.isoformat(timespec="minutes"),
        "hours_to_sunrise": hours_to_sunrise,
        "start_soc": start_soc,
        "projected_soc": projected_soc_clamped,
        "projected_soc_raw": projected_soc,
        "rate_label": rate_label,
        "method": method,
        "weather_cloud_pct": float(weather["cloud_cover_pct"]) if weather.get("cloud_cover_pct") not in (None, "") else None,
        "weather_temp_c": float(weather["temperature_c"]) if weather.get("temperature_c") not in (None, "") else None,
        "day_irradiance_wh_m2": float(weather["shortwave_radiation_sum_today_wh_m2"]) if weather.get("shortwave_radiation_sum_today_wh_m2") not in (None, "") else None,
    }


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Barge Inn — Volthium 24 V Pack</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    color-scheme: dark;
    --bg: #0e1116;
    --panel: #161b22;
    --ink: #e6edf3;
    --dim: #8b949e;
    --grn: #3fb950;
    --ylw: #d29922;
    --red: #f85149;
    --blu: #58a6ff;
  }
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg); color: var(--ink); margin: 0; padding: 24px; }
  h1 { font-size: 14px; font-weight: 600; color: var(--dim); margin: 0 0 18px; letter-spacing: .12em; text-transform: uppercase; }
  .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 18px; max-width: 980px; }
  .below-grid { max-width: 980px; margin-top: 18px; }
  .below-grid .panel { margin-bottom: 18px; }
  .panel { background: var(--panel); border-radius: 10px; padding: 22px; }
  .headline { font-size: 64px; font-weight: 700; line-height: 1; margin: 4px 0 6px; }
  .state-badge {
    display: inline-block; font-size: 13px; font-weight: 600;
    letter-spacing: .14em; text-transform: uppercase;
    padding: 3px 10px; border-radius: 9px;
    background: rgba(139, 148, 158, 0.16); color: var(--dim);
  }
  .state-badge.state-charging    { background: rgba(63, 185, 80, 0.16);  color: var(--grn); }
  .state-badge.state-discharging { background: rgba(210, 153, 34, 0.16); color: var(--ylw); }
  .state-badge.state-idle        { background: rgba(139, 148, 158, 0.16); color: var(--dim); }
  .state-badge.state-full        { background: rgba(63, 185, 80, 0.24);  color: var(--grn); letter-spacing: .2em; }
  .state-badge.state-unknown     { background: rgba(248, 81, 73, 0.16); color: var(--red); }
  .headline-pair {
    display: flex; gap: 28px; flex-wrap: wrap; margin: 10px 0 14px;
  }
  .headline-pair .cell { flex: 1 1 130px; min-width: 130px; }
  .headline-pair .cell .h { font-size: 64px; font-weight: 700; line-height: 1;
                            font-variant-numeric: tabular-nums; }
  .headline-pair .cell .h .u { font-size: 28px; color: var(--dim); margin-left: 4px; }
  .headline-pair .cell .h-sub { color: var(--dim); font-size: 12px;
                                 text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }
  .trend { font-size: 14px; font-weight: 500; margin-top: 6px;
           font-variant-numeric: tabular-nums; }
  .trend.up    { color: var(--grn); }
  .trend.down  { color: var(--ylw); }
  .trend.flat  { color: var(--dim); }
  .label { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .1em; margin-bottom: 6px; }
  .row { display: flex; gap: 24px; flex-wrap: wrap; margin-top: 16px; }
  .stat { min-width: 90px; }
  .stat .v { font-size: 24px; font-weight: 600; }
  .stat .u { color: var(--dim); font-size: 13px; margin-left: 4px; }
  .state-charging { color: var(--grn); }
  .state-discharging { color: var(--ylw); }
  .state-idle { color: var(--dim); }
  .state-unknown { color: var(--red); }
  .state-full { color: var(--grn); letter-spacing: .15em; }
  .soc-bar { background: #21262d; height: 18px; border-radius: 9px; overflow: hidden; margin: 14px 0; }
  .soc-bar > div { height: 100%; background: linear-gradient(90deg, var(--blu), var(--grn)); transition: width .4s; }
  table.batt { width: 100%; border-collapse: collapse; margin-top: 8px; font-variant-numeric: tabular-nums; }
  table.batt td, table.batt th { padding: 6px 4px; text-align: right; }
  table.batt th { color: var(--dim); font-weight: 500; font-size: 12px; }
  table.batt td:first-child, table.batt th:first-child { text-align: left; }
  ul.events { list-style: none; margin: 8px 0 0; padding: 0; }
  ul.events li { font-size: 13px; padding: 4px 0; border-top: 1px solid #21262d; display: flex; gap: 10px; }
  ul.events li:first-child { border-top: 0; }
  ul.events .t { color: var(--dim); font-variant-numeric: tabular-nums; flex: 0 0 56px; }
  ul.events .k { flex: 1; }
  ul.events .d { color: var(--dim); font-variant-numeric: tabular-nums; }
  ul.events .good    .k { color: var(--grn); }
  ul.events .warning .k { color: var(--ylw); }
  ul.events .info    .k { color: var(--ink); }
  .share {
    margin-top: 16px; padding: 12px; border: 1px dashed #30363d;
    border-radius: 8px; font-size: 12px; color: var(--dim);
  }
  .share .url { color: var(--ink); font-family: ui-monospace, SFMono-Regular, monospace;
                font-size: 14px; user-select: all; }
  .share svg { width: 120px; height: 120px; background: #fff; padding: 6px; border-radius: 4px; display: block; }
  .share-label { text-transform: uppercase; letter-spacing: .1em; font-size: 11px; margin-bottom: 4px; }
  .projection { margin-top: 16px; padding: 14px; border-radius: 8px;
                background: #161b22; border: 1px solid #21262d; }
  .projection .lbl { text-transform: uppercase; letter-spacing: .12em;
                     color: var(--dim); font-size: 11px; margin-bottom: 4px; }
  .projection .big { font-size: 32px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .projection .row { display: flex; gap: 18px; margin-top: 12px; align-items: baseline; }
  .projection .stat .v { font-size: 18px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .projection .stat .u { color: var(--dim); font-size: 12px; margin-left: 3px; }
  .projection .footer { color: var(--dim); font-size: 11px; margin-top: 10px; }
  .projection .alarm { color: var(--ylw); }
  .projection .critical { color: var(--red); }
  .harvest { margin-top: 16px; padding: 14px; border-radius: 8px;
             background: #161b22; border: 1px solid #21262d; }
  .harvest .lbl { text-transform: uppercase; letter-spacing: .12em;
                  color: var(--dim); font-size: 11px; margin-bottom: 4px; }
  .harvest .big { font-size: 28px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .harvest .row { display: flex; gap: 18px; margin-top: 8px; align-items: baseline; }
  .harvest .stat .v { font-size: 16px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .harvest .stat .u { color: var(--dim); font-size: 12px; margin-left: 3px; }
  .harvest .bar-wrap { margin-top: 10px; height: 8px; background: #21262d;
                       border-radius: 4px; overflow: hidden; }
  .harvest .bar { height: 100%; background: var(--grn); transition: width 0.5s; }
  .harvest .bar.partial { background: var(--ylw); }
  .harvest .bar.over { background: var(--grn); }
  .harvest .footer { color: var(--dim); font-size: 11px; margin-top: 8px; }
  .harvest .note { color: var(--dim); font-style: italic; font-size: 11px;
                   margin-top: 6px; }
  .harvest-spark { display: block; width: 100%; height: 48px;
                   margin-top: 12px; }
  .harvest .spark-x-labels { display: flex; justify-content: space-between;
                             color: var(--dim); font-size: 10px;
                             font-variant-numeric: tabular-nums;
                             margin-top: 2px; }
  .harvest .live-ratio { margin-top: 10px; padding: 6px 10px;
                         background: #0d1117; border-radius: 4px;
                         display: flex; gap: 8px; align-items: baseline;
                         flex-wrap: wrap; }
  .harvest .live-ratio .lbl { text-transform: uppercase; letter-spacing: .1em;
                              font-size: 10px; color: var(--dim); margin: 0; }
  .harvest .live-ratio .v { font-size: 14px; font-weight: 500;
                            font-variant-numeric: tabular-nums; color: var(--grn); }
  .harvest .live-ratio .aside { font-size: 11px; color: var(--dim);
                                margin-left: auto; }
  .harvest .forecast-rev { display: flex; gap: 8px; align-items: baseline;
                           flex-wrap: wrap; margin-top: 6px;
                           padding: 4px 10px; border-radius: 4px;
                           background: #0d1117; font-size: 11px; }
  .harvest .forecast-rev .lbl { text-transform: uppercase; letter-spacing: .1em;
                                font-size: 10px; color: var(--dim); margin: 0; }
  .harvest .forecast-rev .v { font-variant-numeric: tabular-nums;
                              font-size: 12px; }
  .harvest .forecast-rev .drift { margin-left: auto; font-weight: 500;
                                  font-variant-numeric: tabular-nums; }
  .harvest .forecast-rev.ok   { border-left: 3px solid var(--grn); }
  .harvest .forecast-rev.ok   .drift { color: var(--grn); }
  .harvest .forecast-rev.warn { border-left: 3px solid var(--ylw); }
  .harvest .forecast-rev.warn .drift { color: var(--ylw); }
  .harvest .forecast-rev.bad  { border-left: 3px solid var(--red); }
  .harvest .forecast-rev.bad  .drift { color: var(--red); }
  .harvest .hourly-wrap { margin-top: 10px; }
  .harvest .hourly-wrap .lbl { text-transform: uppercase; letter-spacing: .12em;
                               color: var(--dim); font-size: 10px;
                               margin-bottom: 3px; }
  .harvest-hourly { display: block; width: 100%; height: 36px; }
  .harvest-hourly .hbar { fill: var(--grn); fill-opacity: 0.85; }
  .harvest-hourly .hbar.now { fill: #58a6ff; fill-opacity: 0.95; }
  .harvest-hourly .hbar.empty { fill: #30363d; fill-opacity: 0.4; }
  .advisor {
    margin-bottom: 18px; padding: 14px 16px; border-radius: 8px;
    background: #161b22; border-left: 4px solid var(--grn);
  }
  .advisor.run { border-left-color: var(--ylw); }
  .advisor.critical { border-left-color: var(--red); }
  .advisor .lbl { text-transform: uppercase; letter-spacing: .12em;
                  color: var(--dim); font-size: 11px; }
  .advisor .verdict { font-size: 22px; font-weight: 600; margin: 4px 0 8px; }
  .advisor .verdict.run { color: var(--ylw); }
  .advisor .verdict.critical { color: var(--red); }
  .advisor .verdict.good { color: var(--grn); }
  .advisor .reason { font-size: 13px; line-height: 1.4; }
  .advisor .meta { color: var(--dim); font-size: 11px; margin-top: 8px; }
  .advisor.conf-low { border-style: dashed; background: rgba(22, 27, 34, 0.5); }
  .advisor .conf-pill {
    display: inline-block; padding: 1px 7px; margin-left: 8px;
    border-radius: 9px; font-size: 10px; letter-spacing: .08em;
    text-transform: uppercase; vertical-align: middle;
  }
  .advisor .conf-pill.low    { background: rgba(210, 153, 34, 0.18); color: var(--ylw); }
  .advisor .conf-pill.medium { background: rgba(88, 166, 255, 0.18); color: var(--blu); }
  .advisor .conf-pill.high   { background: rgba(63, 185, 80, 0.18); color: var(--grn); }
  .advisor .conf-explainer { color: var(--dim); font-size: 11px; font-style: italic; margin-top: 6px; }
  .advisor .calib { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap;
                    margin-top: 10px; padding: 6px 10px; border-radius: 4px;
                    background: rgba(13, 17, 23, 0.6); font-size: 12px; }
  .advisor .calib .lbl { text-transform: uppercase; letter-spacing: .1em;
                         font-size: 10px; color: var(--dim); margin: 0; }
  .advisor .calib .v { font-variant-numeric: tabular-nums; }
  .advisor .calib .drift { margin-left: auto; font-weight: 500;
                           font-variant-numeric: tabular-nums; }
  .advisor .calib.ok   { border-left: 3px solid var(--grn); }
  .advisor .calib.ok   .drift { color: var(--grn); }
  .advisor .calib.warn { border-left: 3px solid var(--ylw); }
  .advisor .calib.warn .drift { color: var(--ylw); }
  .advisor .calib.bad  { border-left: 3px solid var(--red); }
  .advisor .calib.bad  .drift { color: var(--red); }
  .advisor .calib-footer { color: var(--dim); font-size: 10px; font-style: italic;
                           margin-top: 4px; padding-left: 10px;
                           font-variant-numeric: tabular-nums; }
  .spark { width: 100%; height: 80px; }
  .footer { color: var(--dim); font-size: 11px; margin-top: 14px; }
  .num { font-variant-numeric: tabular-nums; }
  @media (max-width: 700px) {
    .grid { grid-template-columns: 1fr; }
    .headline { font-size: 48px; }
  }
</style>
</head>
<body>
  <h1>The Barge Inn — Volthium 24 V Pack</h1>
  <div class="grid">
    <div class="panel">
      <span class="state-badge" id="state-value">…</span>
      <div class="headline-pair">
        <div class="cell">
          <div class="h" id="soc-headline">—<span class="u">%</span></div>
          <div class="h-sub">state of charge</div>
          <div class="trend" id="trend">—</div>
        </div>
        <div class="cell">
          <div class="h" id="time-value">—</div>
          <div class="h-sub">time to <span id="target">—</span></div>
        </div>
      </div>
      <div class="soc-bar"><div id="soc-fill" style="width: 0%"></div></div>
      <div class="row">
        <div class="stat"><div class="label">pack V</div><div class="v num"><span id="pv">—</span><span class="u">V</span></div></div>
        <div class="stat"><div class="label">pack I</div><div class="v num"><span id="pi">—</span><span class="u">A</span></div></div>
        <div class="stat"><div class="label">pack P</div><div class="v num"><span id="pp">—</span><span class="u">W</span></div></div>
      </div>
      <div class="label" style="margin-top:6px">pack power (W) — last 2 h</div>
      <svg class="spark" id="spark-p" viewBox="0 0 600 80" preserveAspectRatio="none"></svg>
      <div class="label">SOC (%) — last 2 h</div>
      <svg class="spark" id="spark-soc" viewBox="0 0 600 80" preserveAspectRatio="none"></svg>
      <div class="footer"><span id="updated">—</span></div>
    </div>
    <div class="panel">
      <div class="label">per battery</div>
      <table class="batt">
        <thead><tr><th>id</th><th>SOC</th><th>V</th><th>A</th><th>T</th><th>ΔmV</th></tr></thead>
        <tbody>
          <tr id="rowA"><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
          <tr id="rowB"><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
        </tbody>
      </table>
      <div class="label" style="margin-top:18px">recent events</div>
      <ul class="events" id="events"><li class="info"><span class="t">—</span><span class="k">no events yet</span></li></ul>
      {{SHARE_PANEL}}
    </div>
  </div>

  <!-- Projections + advisor below the grid — secondary info on desktop,
       bottom-of-scroll on mobile. -->
  <div class="below-grid">
    <div class="panel" id="advisor-panel-wrap" style="display:none"><div id="advisor-panel"></div></div>
    <div class="panel" id="projection-panel-wrap" style="display:none"><div id="projection-panel"></div></div>
    <div class="panel" id="harvest-panel-wrap" style="display:none"><div id="harvest-panel"></div></div>
  </div>

<script>
const fmtMin = m => {
  if (m == null || m < 0) return "—";
  if (m < 60) return Math.round(m) + " min";
  const h = Math.floor(m / 60), mm = Math.round(m % 60);
  if (h < 48) return h + "h " + String(mm).padStart(2, "0") + "m";
  const d = Math.floor(h / 24); return d + "d " + (h % 24) + "h";
};
const setText = (id, v) => document.getElementById(id).textContent = v;
const fixed = (v, p) => v == null ? "—" : (+v).toFixed(p);
const stateClass = s => "state-" + (s || "unknown");

async function tick() {
  try {
    const r = await fetch("/api/latest.json");
    const j = await r.json();
    if (!j.latest) {
      setText("state-value", "no data yet");
      return;
    }
    const x = j.latest;
    const stateEl = document.getElementById("state-value");
    stateEl.textContent = (x.state || "—").toUpperCase();
    stateEl.className = "state-badge " + stateClass(x.state);
    if (x.state === "charging") {
      setText("target", "full (95%)");
      setText("time-value", fmtMin(x.minutes_remaining));
    } else if (x.state === "discharging") {
      setText("target", "10%");
      setText("time-value", fmtMin(x.minutes_remaining));
    } else if (x.state === "full") {
      setText("target", "—");
      document.getElementById("time-value").innerHTML = "FULL";
    } else {
      setText("target", "—");
      setText("time-value", "—");
    }
    // SOC headline + bar
    const socAvg = (x.soc_a != null && x.soc_b != null) ? (x.soc_a + x.soc_b) / 2 : null;
    if (socAvg != null) {
      document.getElementById("soc-headline").innerHTML =
          `${Math.round(socAvg)}<span class="u">%</span>`;
      document.getElementById("soc-fill").style.width = socAvg + "%";
    } else {
      document.getElementById("soc-headline").innerHTML = `—<span class="u">%</span>`;
    }

    // Trend indicator under the SOC headline — quick "gaining / losing / steady"
    // read using the smoothed pack current.
    const trendEl = document.getElementById("trend");
    if (x.smoothed_i != null) {
      const si = +x.smoothed_i;
      let cls, arrow, label;
      if (si > 0.5)       { cls = "up";   arrow = "▲"; label = `gaining +${si.toFixed(1)} A`; }
      else if (si < -0.5) { cls = "down"; arrow = "▼"; label = `losing ${si.toFixed(1)} A`; }
      else                { cls = "flat"; arrow = "→"; label = "steady"; }
      trendEl.className = "trend " + cls;
      trendEl.textContent = `${arrow} ${label}`;
    } else {
      trendEl.className = "trend flat";
      trendEl.textContent = "—";
    }
    setText("pv", fixed(x.pack_v, 2));
    setText("pi", x.pack_i == null ? "—" : (x.pack_i > 0 ? "+" : "") + (+x.pack_i).toFixed(2));
    setText("pp", x.pack_p == null ? "—" : Math.round(x.pack_p));

    // Derive per-battery label from the BMS-advertised name; fall back to A/B for old rows.
    const labelOf = (name, fallback) => {
      if (name && name.includes("-")) {
        const tail = name.split("-").pop();
        if (tail && tail.length >= 2) return tail.slice(-2);
      }
      return fallback;
    };
    const rA = document.getElementById("rowA").children;
    const rB = document.getElementById("rowB").children;
    rA[0].textContent = labelOf(x.name_a, "A");
    rA[1].textContent = x.soc_a != null ? Math.round(x.soc_a) + "%" : "—";
    rA[2].textContent = fixed(x.v_a, 2);
    rA[3].textContent = x.i_a == null ? "—" : (x.i_a > 0 ? "+" : "") + (+x.i_a).toFixed(2);
    rA[4].textContent = x.t_a == null ? "—" : Math.round(x.t_a) + "°";
    rA[5].textContent = x.delta_v_a == null ? "—" : Math.round(x.delta_v_a * 1000);
    rB[0].textContent = labelOf(x.name_b, "B");
    rB[1].textContent = x.soc_b != null ? Math.round(x.soc_b) + "%" : "—";
    rB[2].textContent = fixed(x.v_b, 2);
    rB[3].textContent = x.i_b == null ? "—" : (x.i_b > 0 ? "+" : "") + (+x.i_b).toFixed(2);
    rB[4].textContent = x.t_b == null ? "—" : Math.round(x.t_b) + "°";
    rB[5].textContent = x.delta_v_b == null ? "—" : Math.round(x.delta_v_b * 1000);

    const series = j.history || [];
    const W = 600, H = 80, PAD = 4;
    function spark(id, values, includeZero, color) {
      const svg = document.getElementById(id);
      if (values.length < 2) { svg.innerHTML = ""; return; }
      let lo = Math.min(...values), hi = Math.max(...values);
      if (includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
      const pad = (hi - lo) * 0.05 || 1;
      lo -= pad; hi += pad;
      const range = hi - lo || 1;
      const zeroY = H - PAD - ((0 - lo) / range) * (H - 2 * PAD);
      const pts = values.map((p, i) => {
        const x = PAD + (i / (values.length - 1)) * (W - 2 * PAD);
        const y = H - PAD - ((p - lo) / range) * (H - 2 * PAD);
        return x.toFixed(1) + "," + y.toFixed(1);
      }).join(" ");
      const zeroLine = includeZero && lo <= 0 && hi >= 0
        ? `<line x1="0" y1="${zeroY}" x2="${W}" y2="${zeroY}" stroke="#30363d" stroke-width="1"/>` : "";
      svg.innerHTML = zeroLine +
        `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/>`;
    }
    const ps = series.map(x => x.pack_p ?? 0);
    spark("spark-p", ps, true, ps[ps.length-1] >= 0 ? "var(--grn)" : "var(--ylw)");
    const socs = series.map(x => (x.soc_a != null && x.soc_b != null) ? (x.soc_a + x.soc_b) / 2 : null).filter(v => v != null);
    spark("spark-soc", socs, false, "var(--blu)");
    setText("updated", new Date().toLocaleTimeString() + "  •  " + series.length + " samples");

    // Advisor panel — and hide its wrapper if there's nothing to show
    const advWrap = document.getElementById("advisor-panel-wrap");
    const advEl = document.getElementById("advisor-panel");
    const rec = j.recommendation;
    if (rec) {
      advWrap.style.display = "";
        let cls, headline;
        if (rec.run_generator) {
            cls = (rec.projected_low_soc != null && rec.projected_low_soc < 15) ? "critical" : "run";
            headline = `RUN GENERATOR · ${rec.duration_h.toFixed(1)} h`;
        } else if (rec.morning_watch) {
            cls = "run";        // amber styling, same as run-recommended
            headline = "MORNING WATCH";
        } else {
            cls = "good";
            headline = "no generator needed";
        }
        let whenLine = "";
        if (rec.run_generator && rec.when_iso) {
            const whenStr = rec.when_iso.slice(11, 16);
            whenLine = `<div class="meta">recommended start ~ ${whenStr}</div>`;
        }
        const watchLine = (!rec.run_generator && rec.morning_watch && rec.morning_watch_reason)
            ? `<div class="reason" style="margin-top:6px;color:var(--ylw)">${rec.morning_watch_reason}</div>`
            : "";

        // Confidence styling: dashed border + muted background when "low",
        // explanatory line about how confidence grows with data.
        const confClass = `conf-${rec.confidence}`;
        const confExplainer = {
            "low":    "< 3 days of solar-fit data — projection is a rough estimate; expect refinement as the model accumulates observations.",
            "medium": "3–6 days of solar-fit data — projection is plausible but still tightening.",
            "high":   "",
        }[rec.confidence] || "";
        const confLine = confExplainer
            ? `<div class="conf-explainer">${confExplainer}</div>`
            : "";

        // Model-vs-live calibration chip: show what the SolarModel uses
        // vs what today's live measurement is producing. Green when they
        // agree (drift < 10 %), amber 10-20 %, red > 20 %.  Hidden until
        // there's enough data for a live ratio.
        const ins = rec.inputs || {};
        const modelCoef = ins.solar_model_coefficient;
        const liveRatio = ins.live_ratio_ah_per_kwh_m2;
        let calibLine = "";
        if (modelCoef != null && liveRatio != null && modelCoef > 0) {
            const driftPct = Math.abs(liveRatio - modelCoef) / modelCoef * 100;
            const driftCls = driftPct < 10 ? "ok" : (driftPct < 20 ? "warn" : "bad");
            const driftSign = liveRatio >= modelCoef ? "+" : "−";
            // Model-update timestamp: when did the SolarModel last
            // meaningfully change? Until tonight's first post-sunset
            // fit this just shows the baseline default; once a real
            // fit lands, the timestamp marks that calibration event.
            let calibFooter = "";
            const luIso = ins.model_last_updated_iso;
            const luSrc = ins.model_last_updated_source;
            if (luIso) {
              // Render as 'YYYY-MM-DD HH:MM (source)'. Strip seconds
              // and the 'T' for readability; keep the date because
              // an old log entry vs a fresh one matters.
              const niceTs = luIso.length >= 16
                ? luIso.slice(0, 10) + " " + luIso.slice(11, 16)
                : luIso;
              const srcTxt = luSrc ? ` · ${luSrc}` : "";
              calibFooter = `<div class="calib-footer">model last updated ${niceTs}${srcTxt}</div>`;
            }
            calibLine = `
              <div class="calib ${driftCls}">
                <span class="lbl">model vs live</span>
                <span class="v">${modelCoef.toFixed(2)} → ${liveRatio.toFixed(2)} Ah/(kWh/m²)</span>
                <span class="drift">${driftSign}${driftPct.toFixed(1)}%</span>
              </div>
              ${calibFooter}`;
        }

        advEl.innerHTML = `
            <div class="advisor ${cls} ${rec.confidence === 'low' ? 'conf-low' : ''}">
              <div class="lbl">recommendation<span class="conf-pill ${confClass}">${rec.confidence} confidence</span></div>
              <div class="verdict ${cls}">${headline}</div>
              <div class="reason">${rec.reason}</div>
              ${watchLine}
              ${whenLine}
              ${calibLine}
              ${confLine}
            </div>`;
    } else {
        advEl.innerHTML = "";
        advWrap.style.display = "none";
    }

    // Projection panel — hide its wrapper too when not applicable
    const projWrap = document.getElementById("projection-panel-wrap");
    const projEl = document.getElementById("projection-panel");
    const proj = j.projection;
    if (proj) {
      projWrap.style.display = "";
      const h = Math.floor(proj.hours_to_sunrise);
      const m = Math.round((proj.hours_to_sunrise - h) * 60);
      const sunriseTime = proj.sunrise_iso.slice(11, 16);   // HH:MM
      let cls = "";
      let label = `PROJECTED SOC AT SUNRISE (${sunriseTime})`;
      if (proj.projected_soc < 10) cls = "critical";
      else if (proj.projected_soc < 25) cls = "alarm";
      const weatherBits = [];
      if (proj.weather_cloud_pct != null) weatherBits.push(`${Math.round(proj.weather_cloud_pct)}% cloud`);
      if (proj.weather_temp_c != null) weatherBits.push(`${proj.weather_temp_c.toFixed(1)}°C`);
      if (proj.day_irradiance_wh_m2 != null) weatherBits.push(`${(proj.day_irradiance_wh_m2 / 1000).toFixed(1)} kWh/m² today`);
      projEl.innerHTML = `
        <div class="projection">
          <div class="lbl">${label}</div>
          <div class="big ${cls}">${proj.projected_soc.toFixed(0)}%</div>
          <div class="row">
            <div class="stat"><div class="lbl">in</div>
              <div class="v">${h}h ${String(m).padStart(2,"0")}m</div></div>
            <div class="stat"><div class="lbl">starting from</div>
              <div class="v">${proj.start_soc.toFixed(0)}<span class="u">%</span></div></div>
            <div class="stat"><div class="lbl">${proj.rate_label}</div>
              <div class="v">&nbsp;</div></div>
          </div>
          <div class="footer">${weatherBits.join(" · ")}</div>
        </div>`;
    } else {
      projEl.innerHTML = "";
      projWrap.style.display = "none";
    }

    // Today's harvest tracker
    const harvWrap = document.getElementById("harvest-panel-wrap");
    const harvEl = document.getElementById("harvest-panel");
    const harv = j.today_harvest;
    if (harv && harv.solar_ah_forecast != null) {
      harvWrap.style.display = "";
      const pct = harv.pct_of_forecast;
      const pctTxt = (pct != null) ? `${pct.toFixed(0)}%` : "—";
      const barW = (pct != null) ? Math.min(100, Math.max(0, pct)) : 0;
      const barCls = (pct != null && pct >= 100) ? "over"
                     : (pct != null && pct >= 50) ? "" : "partial";
      const note = harv.note ? `<div class="note">${harv.note}</div>` : "";

      // Sparkline: cumulative solar Ah over the day so far. x = 0..1440
      // (minute of day), y = 0..max(forecast, current * 1.1). Forecast
      // target shown as a faint horizontal reference.
      const series = harv.series || [];
      let sparkSvg = "";
      if (series.length >= 2) {
        const W = 100, H = 28;   // viewBox units; CSS scales it up
        const yMax = Math.max(harv.solar_ah_forecast, harv.solar_ah_so_far * 1.1, 1);
        const xOf = m => (m / 1440) * W;
        const yOf = ah => H - (ah / yMax) * H;
        const points = series.map(([m, a]) => `${xOf(m).toFixed(2)},${yOf(a).toFixed(2)}`).join(" ");
        const forecastY = yOf(harv.solar_ah_forecast).toFixed(2);
        const nowMin = (new Date()).getHours() * 60 + (new Date()).getMinutes();
        const nowX = xOf(nowMin).toFixed(2);
        // Optional sunrise/sunset marker lines.
        const srMin = harv.sunrise_min_of_day;
        const ssMin = harv.sunset_min_of_day;
        const sunMarkers = [];
        if (srMin != null) {
          const x = xOf(srMin).toFixed(2);
          sunMarkers.push(`<line x1="${x}" y1="0" x2="${x}" y2="${H}"
                stroke="#d29922" stroke-width="0.3" stroke-opacity="0.55"
                stroke-dasharray="0.6 0.6"/>`);
        }
        if (ssMin != null) {
          const x = xOf(ssMin).toFixed(2);
          sunMarkers.push(`<line x1="${x}" y1="0" x2="${x}" y2="${H}"
                stroke="#d29922" stroke-width="0.3" stroke-opacity="0.55"
                stroke-dasharray="0.6 0.6"/>`);
        }
        // Daylight tint between sunrise and sunset, very subtle, to
        // contextualize "this is the productive window."
        let daylightBand = "";
        if (srMin != null && ssMin != null && ssMin > srMin) {
          const x0 = xOf(srMin).toFixed(2);
          const x1 = xOf(ssMin).toFixed(2);
          daylightBand = `<rect x="${x0}" y="0" width="${(x1 - x0).toFixed(2)}"
                                height="${H}"
                                fill="#d29922" fill-opacity="0.04"/>`;
        }
        sparkSvg = `
          <svg class="harvest-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
            ${daylightBand}
            <line x1="0" y1="${forecastY}" x2="${W}" y2="${forecastY}"
                  stroke="#30363d" stroke-width="0.4" stroke-dasharray="1 1.5"/>
            ${sunMarkers.join("")}
            <polyline points="${points}" fill="none"
                      stroke="var(--grn)" stroke-width="0.9"
                      stroke-linecap="round" stroke-linejoin="round"/>
            <line x1="${nowX}" y1="0" x2="${nowX}" y2="${H}"
                  stroke="#58a6ff" stroke-width="0.3" stroke-opacity="0.5"/>
          </svg>
          <div class="spark-x-labels">
            <span>00:00</span><span>06:00</span><span>12:00</span>
            <span>18:00</span><span>24:00</span>
          </div>`;
      }

      // Hourly delta bars: turn the cumulative series into per-hour Ah.
      // For each hour 0..23, take the last cumulative value seen in that
      // hour minus the last value before the hour started. Skips empty
      // hours, then renders one bar per hour scaled to the largest hour.
      let hourlySvg = "";
      if (series.length >= 2) {
        // Map of cumulative_ah at each hour boundary's "last seen" point.
        // Use a sparse approach: for each point, update hourBuckets[hour]
        // to its cumulative value. The hour's harvest = bucket[h] - bucket[h-1].
        const lastByHour = new Array(24).fill(null);
        for (const [m, a] of series) {
          const h = Math.floor(m / 60);
          if (h >= 0 && h < 24) lastByHour[h] = a;
        }
        // Carry forward the previous hour's "last" value as the baseline
        // for an empty hour so the delta is 0 there, not negative.
        let baseline = 0;
        const hourDeltas = new Array(24).fill(0);
        for (let h = 0; h < 24; h++) {
          if (lastByHour[h] != null) {
            hourDeltas[h] = Math.max(0, lastByHour[h] - baseline);
            baseline = lastByHour[h];
          } else {
            hourDeltas[h] = 0;
            // baseline stays the same
          }
        }
        const maxDelta = Math.max(...hourDeltas, 0.001);
        const Wh = 100, Hh = 22, gap = 0.6;
        const barW = (Wh - gap * 23) / 24;
        const nowHr = (new Date()).getHours();
        const bars = hourDeltas.map((d, h) => {
          const x = h * (barW + gap);
          const bh = (d / maxDelta) * Hh;
          const y = Hh - bh;
          const fillCls = h === nowHr ? "now" : (d > 0 ? "" : "empty");
          return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}"
                        width="${barW.toFixed(2)}" height="${bh.toFixed(2)}"
                        class="hbar ${fillCls}"/>`;
        }).join("");
        const maxLabel = maxDelta.toFixed(1);
        hourlySvg = `
          <div class="hourly-wrap">
            <div class="lbl">PER-HOUR HARVEST · max ${maxLabel} Ah</div>
            <svg class="harvest-hourly" viewBox="0 0 ${Wh} ${Hh}"
                 preserveAspectRatio="none">${bars}</svg>
          </div>`;
      }

      harvEl.innerHTML = `
        <div class="harvest">
          <div class="lbl">TODAY'S SOLAR HARVEST</div>
          <div class="big">${harv.solar_ah_so_far.toFixed(1)} <span class="u" style="font-size:14px">Ah</span></div>
          <div class="bar-wrap"><div class="bar ${barCls}" style="width:${barW}%"></div></div>
          ${sparkSvg}
          ${hourlySvg}
          <div class="row">
            <div class="stat"><div class="lbl">progress</div>
              <div class="v">${pctTxt}</div></div>
            <div class="stat"><div class="lbl">forecast</div>
              <div class="v">${harv.solar_ah_forecast.toFixed(0)}<span class="u">Ah</span></div></div>
            <div class="stat"><div class="lbl">irradiance forecast</div>
              <div class="v">${harv.irradiance_kwh_m2_forecast.toFixed(2)}<span class="u">kWh/m²</span></div></div>
            ${(() => {
              // Hours of useful daylight remaining. Computed from
              // sunrise/sunset minute-of-day in the snapshot. Hidden
              // when we don't have weather sun-times yet.
              if (harv.sunset_min_of_day == null) return "";
              const nowD = new Date();
              const nowMin = nowD.getHours() * 60 + nowD.getMinutes();
              const remaining = harv.sunset_min_of_day - nowMin;
              if (remaining <= 0) {
                return `<div class="stat"><div class="lbl">daylight</div>
                          <div class="v">post-sunset</div></div>`;
              }
              const preSunrise = harv.sunrise_min_of_day != null &&
                                  nowMin < harv.sunrise_min_of_day;
              if (preSunrise) {
                const untilSr = harv.sunrise_min_of_day - nowMin;
                const h = Math.floor(untilSr / 60), m = untilSr % 60;
                return `<div class="stat"><div class="lbl">sun in</div>
                          <div class="v">${h}h ${String(m).padStart(2,"0")}m</div></div>`;
              }
              const h = Math.floor(remaining / 60), m = remaining % 60;
              return `<div class="stat"><div class="lbl">sun left</div>
                        <div class="v">${h}h ${String(m).padStart(2,"0")}m</div></div>`;
            })()}
          </div>
          ${harv.live_ratio_ah_per_kwh_m2 != null ? `
          <div class="live-ratio">
            <span class="lbl">live ratio</span>
            <span class="v">${harv.live_ratio_ah_per_kwh_m2.toFixed(2)} Ah/(kWh/m²)</span>
            <span class="aside">${harv.irradiance_kwh_m2_so_far.toFixed(2)} kWh/m² actual so far</span>
          </div>` : ""}
          ${(() => {
            // Open-Meteo forecast-revision history: how stable was the
            // day's predicted kWh/m² as the model ingested today's
            // observations? Big drift or wide swing = forecast was
            // uncertain. Hidden when we don't have ≥2 weather samples
            // (early cold start).
            const fh = harv.forecast_history;
            if (!fh || !fh.first || !fh.latest || fh.n < 2) return "";
            const drift = fh.drift_pct;
            const swingPct = fh.first > 0
              ? ((fh.max - fh.min) / fh.first * 100)
              : null;
            const driftSign = drift >= 0 ? "+" : "−";
            const driftAbs = Math.abs(drift);
            const driftCls = driftAbs < 5 ? "ok"
                             : (driftAbs < 10 ? "warn" : "bad");
            const swingStr = swingPct != null
              ? `, swing ${swingPct.toFixed(1)}%`
              : "";
            return `
              <div class="forecast-rev ${driftCls}">
                <span class="lbl">forecast revisions</span>
                <span class="v">${fh.first.toFixed(2)} → ${fh.latest.toFixed(2)} kWh/m²</span>
                <span class="drift">${driftSign}${driftAbs.toFixed(1)}%${swingStr}</span>
              </div>`;
          })()}
          <div class="footer">${harv.duration_h.toFixed(1)} h of data so far · ${harv.confidence} confidence</div>
          ${note}
        </div>`;
    } else {
      harvEl.innerHTML = "";
      harvWrap.style.display = "none";
    }

    // Events
    const evList = document.getElementById("events");
    const events = (j.events || []).slice().reverse();   // newest first
    if (events.length === 0) {
      evList.innerHTML = '<li class="info"><span class="t">—</span><span class="k">no events yet</span></li>';
    } else {
      evList.innerHTML = events.map(e => {
        const tStr = e.ts.slice(11, 16);   // HH:MM
        return `<li class="${e.severity}"><span class="t">${tStr}</span>` +
               `<span class="k">${e.kind}</span><span class="d">${e.descriptor}</span></li>`;
      }).join("");
    }
  } catch (e) {
    setText("state-value", "fetch failed");
  }
}
tick();
setInterval(tick, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet logs
        return

    def address_string(self):
        # Skip reverse-DNS — home LANs typically don't have rDNS configured,
        # and the default impl will block each request for ~30 s waiting for
        # a response that never comes. We only ever use this for logs anyway.
        return self.client_address[0]

    INDEX_HTML = INDEX_HTML  # patched in main() with the share-panel template filled

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            return self._send(HTTPStatus.OK, "text/html; charset=utf-8", self.INDEX_HTML.encode())
        if self.path.startswith("/api/latest.json"):
            rows = read_recent(CSV_PATH, HISTORY_N)
            if not rows:
                return self._send(HTTPStatus.OK, "application/json",
                                  json.dumps({"latest": None, "history": [], "events": []}).encode())
            history = [{k: to_num(v) if k not in ("ts", "state") else v for k, v in row.items()}
                       for row in rows]
            # Build events from the same window. Hand the detector parsed dicts.
            ev_rows = []
            for r in history:
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except (TypeError, ValueError):
                    continue
                sa, sb = r.get("soc_a"), r.get("soc_b")
                ev_rows.append({
                    "ts": ts,
                    "pack_i": r.get("pack_i"),
                    "max_soc": max(sa, sb) if sa is not None and sb is not None else None,
                    "min_soc": min(sa, sb) if sa is not None and sb is not None else None,
                    "state": r.get("state"),
                })
            events = [e.to_dict() for e in detect_events(ev_rows)]
            projection = compute_projection(history[-1], latest_weather_row())
            recommendation = get_recommendation()
            today_harvest = get_today_harvest()
            return self._send(HTTPStatus.OK, "application/json",
                              json.dumps({
                                  "latest": history[-1],
                                  "history": history,
                                  "events": events[-20:],  # last 20 only, keep payload small
                                  "projection": projection,
                                  "recommendation": recommendation,
                                  "today_harvest": today_harvest,
                              }).encode())
        return self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")

    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    global CSV_PATH, WEATHER_CSV_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--weather-csv", type=Path, default=Path("data/weather.csv"))
    ap.add_argument("--port", type=int, default=8421)
    ap.add_argument(
        "--host",
        default="0.0.0.0",
        help="bind address. 0.0.0.0 = visible to anyone on the LAN; "
             "127.0.0.1 = laptop-only. Default is LAN-visible since this is "
             "the whole point of a wall-mounted readout. The page is read-only "
             "and shows only battery telemetry — low secrecy risk.",
    )
    args = ap.parse_args()
    CSV_PATH = args.csv
    WEATHER_CSV_PATH = args.weather_csv

    # Compute the share panel HTML once at startup.
    lan_ip = detect_lan_ip()
    if lan_ip and args.host in ("0.0.0.0", "::", ""):
        lan_url = f"http://{lan_ip}:{args.port}/"
        qr_svg = lan_qr_svg(lan_url)
        share_panel = (
            f'<div class="share">'
            f'<div class="share-label">share with phones</div>'
            f'{qr_svg}'
            f'<div class="share-label" style="margin-top:8px">scan or type</div>'
            f'<div class="url">{lan_url}</div>'
            f'</div>'
        )
    else:
        share_panel = ""
    Handler.INDEX_HTML = INDEX_HTML.replace("{{SHARE_PANEL}}", share_panel)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"dashboard running at http://{args.host}:{args.port}/  (csv={args.csv})",
          file=sys.stderr, flush=True)
    if lan_ip:
        print(f"LAN share URL: http://{lan_ip}:{args.port}/", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
