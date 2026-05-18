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

        advEl.innerHTML = `
            <div class="advisor ${cls} ${rec.confidence === 'low' ? 'conf-low' : ''}">
              <div class="lbl">recommendation<span class="conf-pill ${confClass}">${rec.confidence} confidence</span></div>
              <div class="verdict ${cls}">${headline}</div>
              <div class="reason">${rec.reason}</div>
              ${watchLine}
              ${whenLine}
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
            return self._send(HTTPStatus.OK, "application/json",
                              json.dumps({
                                  "latest": history[-1],
                                  "history": history,
                                  "events": events[-20:],  # last 20 only, keep payload small
                                  "projection": projection,
                                  "recommendation": recommendation,
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
