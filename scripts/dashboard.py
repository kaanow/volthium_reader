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
from html import escape as html_escape  # noqa: E402
from volthium.events import detect_events  # noqa: E402
import discharge_model  # noqa: E402  — sibling script
import generator_advisor  # noqa: E402  — sibling script
import end_of_day_report as end_of_day_report_mod  # noqa: E402

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


def render_horizon_bar_chart(by_h: list[dict],
                             *,
                             title_color: str = "#c9d1d9") -> str:
    """Render the per-horizon error breakdown as an SVG bar chart.

    Used on both /accuracy (sunrise SOC validation) and /low-accuracy
    (morning-low SOC validation). Each bar is one lead-time bucket;
    height = |mean_error| (signed bars extend up for positive error,
    down for negative); color follows the same |error| thresholds as
    the per-record table (green < 3 pp, amber < 8, red >= 8).

    Returns an empty string when `by_h` is empty (caller can
    unconditionally concatenate).
    """
    if not by_h:
        return ""
    W = 600
    H = 160
    PAD_X = 40
    ZERO_Y = 80   # zero line in the middle (60 px above, 60 below)
    BAR_PAD = 8   # gap between bars
    n = len(by_h)
    slot_w = (W - 2 * PAD_X) / n
    bar_w = max(8.0, slot_w - BAR_PAD)
    # Scale: max bar height represents the largest |mean_error| observed,
    # capped at a sensible upper bound so a single outlier doesn't
    # squish all other bars to nothing.
    max_abs = max(abs(b["mean_error"]) for b in by_h)
    scale_cap = max(max_abs, 1.0)   # avoid div-by-zero on all-zero data
    max_bar = 50  # pixels
    pieces: list[str] = []
    # Zero baseline
    pieces.append(
        f"<line x1='{PAD_X}' y1='{ZERO_Y}' "
        f"x2='{W - PAD_X}' y2='{ZERO_Y}' "
        f"stroke='#30363d' stroke-width='1' stroke-dasharray='2,3'/>"
    )
    # Y-axis ticks at -|max| / 0 / +|max| equivalent
    pieces.append(
        f"<text x='{PAD_X - 6}' y='{ZERO_Y + 4}' "
        f"fill='#8b949e' font-size='10' text-anchor='end' "
        f"font-family='ui-monospace,monospace'>0</text>"
    )
    pieces.append(
        f"<text x='{PAD_X - 6}' y='{ZERO_Y - max_bar + 4}' "
        f"fill='#8b949e' font-size='10' text-anchor='end' "
        f"font-family='ui-monospace,monospace'>+{scale_cap:.1f}</text>"
    )
    pieces.append(
        f"<text x='{PAD_X - 6}' y='{ZERO_Y + max_bar + 4}' "
        f"fill='#8b949e' font-size='10' text-anchor='end' "
        f"font-family='ui-monospace,monospace'>-{scale_cap:.1f}</text>"
    )
    for i, b in enumerate(by_h):
        cx = PAD_X + slot_w * (i + 0.5)
        bx = cx - bar_w / 2
        err = b["mean_error"]
        # Height: |err| / scale_cap * max_bar
        bh = abs(err) / scale_cap * max_bar
        if err >= 0:
            by = ZERO_Y - bh
            value_y = by - 4
            label_y = ZERO_Y + 14
        else:
            by = ZERO_Y
            value_y = ZERO_Y + bh + 12
            label_y = ZERO_Y + max_bar + 18
        # Color by |error| threshold (matches per-record table)
        ae = abs(err)
        if ae <= 3:
            fill = "#3fb950"     # green
        elif ae <= 8:
            fill = "#d29922"     # amber
        else:
            fill = "#f85149"     # red
        pieces.append(
            f"<rect x='{bx:.1f}' y='{by:.1f}' "
            f"width='{bar_w:.1f}' height='{bh:.1f}' "
            f"fill='{fill}' opacity='0.85'>"
            f"<title>{b['bucket']}: n={b['n']}, "
            f"mean {err:+.2f} pp, abs {b['mean_abs_error']:.2f}, "
            f"rms {b['rms_error']:.2f}, "
            f"range [{b['min_error']:+.2f}..{b['max_error']:+.2f}]</title>"
            f"</rect>"
        )
        # Value above/below the bar
        pieces.append(
            f"<text x='{cx:.1f}' y='{value_y:.1f}' "
            f"fill='{fill}' font-size='11' text-anchor='middle' "
            f"font-family='ui-monospace,monospace' "
            f"font-variant-numeric='tabular-nums'>{err:+.2f}</text>"
        )
        # Bucket label below the zero line
        pieces.append(
            f"<text x='{cx:.1f}' y='{label_y:.1f}' "
            f"fill='#8b949e' font-size='10' text-anchor='middle' "
            f"font-family='ui-monospace,monospace'>"
            f"{html_escape(b['bucket'])}</text>"
        )
        # Tiny "n=N" caption under the bucket label
        pieces.append(
            f"<text x='{cx:.1f}' y='{label_y + 12:.1f}' "
            f"fill='#6e7681' font-size='9' text-anchor='middle' "
            f"font-family='ui-monospace,monospace'>n={b['n']}</text>"
        )
    body = "".join(pieces)
    title = (
        f"<text x='{W // 2}' y='14' fill='{title_color}' "
        f"font-size='11' text-anchor='middle' "
        f"font-family='ui-monospace,monospace'>"
        f"mean error (pp) by lead-time horizon"
        f"</text>"
    )
    return (
        f"<svg viewBox='0 0 {W} {H}' "
        f"preserveAspectRatio='xMidYMid meet' "
        f"style='display:block;width:100%;max-width:{W}px;"
        f"margin:10px auto 0;background:#0d1117;border-radius:4px;"
        f"padding:6px;box-sizing:border-box'>"
        f"{title}{body}"
        f"</svg>"
    )


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
  /* Stale-data banner: shown when latest pack sample is older than
     STALE_THRESHOLD_S (60 s by default, matches health.py). Same
     red palette as the model-drift advisory chip so the operator
     associates both with "something needs attention". */
  .stale-banner {
    background: rgba(248, 81, 73, 0.10);
    border-left: 3px solid var(--red);
    color: var(--red);
    padding: 8px 14px;
    margin: 0 0 16px;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 500;
    display: flex;
    gap: 10px;
    align-items: baseline;
    font-variant-numeric: tabular-nums;
  }
  .stale-banner .stale-icon { font-size: 16px; }
  .stale-banner .stale-hint { color: var(--dim); font-size: 11px;
                              font-weight: 400; margin-left: auto; }
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
  .harvest .report-link { color: var(--blu); text-decoration: none; }
  .harvest .report-link:hover { text-decoration: underline; }
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
                         flex-wrap: wrap;
                         cursor: help; }
  .harvest .live-ratio .lbl { text-transform: uppercase; letter-spacing: .1em;
                              font-size: 10px; color: var(--dim); margin: 0; }
  .harvest .live-ratio .v { font-size: 14px; font-weight: 500;
                            font-variant-numeric: tabular-nums; color: var(--grn); }
  .harvest .live-ratio .aside { font-size: 11px; color: var(--dim);
                                margin-left: auto; }
  .harvest .forecast-rev { display: flex; gap: 8px; align-items: baseline;
                           flex-wrap: wrap; margin-top: 6px;
                           padding: 4px 10px; border-radius: 4px;
                           background: #0d1117; font-size: 11px;
                           cursor: help; }
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
  /* Solar-onset cascade chip: lands once today's first zero-crossing
     has happened. Color shifts green once net-positive is sustained. */
  .harvest .solar-onset { display: flex; gap: 8px; align-items: baseline;
                          flex-wrap: wrap; margin-top: 6px;
                          padding: 4px 10px; border-radius: 4px;
                          background: #0d1117; font-size: 11px;
                          cursor: help; }
  .harvest .solar-onset .lbl { text-transform: uppercase; letter-spacing: .1em;
                               font-size: 10px; color: var(--dim); margin: 0; }
  .harvest .solar-onset .v { font-variant-numeric: tabular-nums;
                             font-size: 12px; font-weight: 500; }
  .harvest .solar-onset .drift { margin-left: auto; color: var(--dim);
                                 font-size: 11px;
                                 font-variant-numeric: tabular-nums; }
  .harvest .solar-onset.ok   { border-left: 3px solid var(--grn); }
  .harvest .solar-onset.ok   .v { color: var(--grn); }
  .harvest .solar-onset.warn { border-left: 3px solid var(--ylw); }
  .harvest .solar-onset.warn .v { color: var(--ylw); }
  .harvest .solar-onset.dim  { border-left: 3px solid #30363d; }
  .harvest .solar-onset.dim  .v { color: var(--dim); }
  .harvest .peaks { margin-top: 8px; padding: 6px 10px; border-radius: 4px;
                    background: #0d1117;
                    display: flex; gap: 14px; flex-wrap: wrap;
                    align-items: baseline; font-size: 11px;
                    cursor: help; }
  .harvest .peaks .lbl { text-transform: uppercase; letter-spacing: .1em;
                         font-size: 10px; color: var(--dim); margin: 0;
                         width: 100%; margin-bottom: 4px; }
  .harvest .peaks .stat { font-variant-numeric: tabular-nums; }
  .harvest .peaks .stat .v { font-size: 14px; font-weight: 500; color: var(--ink); }
  .harvest .peaks .stat .v.warn { color: var(--ylw); }
  .harvest .peaks .stat .u { font-size: 10px; color: var(--dim); margin-left: 3px; }
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
                    background: rgba(13, 17, 23, 0.6); font-size: 12px;
                    cursor: help; }
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
  /* Confidence-lift badge: shown when the advisor's recent
     projection track record was tight enough to lift the
     confidence tier one notch. */
  .advisor .conf-lift { display: flex; gap: 8px; align-items: baseline;
                        flex-wrap: wrap; margin-top: 6px;
                        padding: 6px 10px; border-radius: 4px;
                        background: rgba(63, 185, 80, 0.08);
                        border-left: 3px solid var(--grn);
                        font-size: 12px; cursor: help; }
  .advisor .conf-lift .lbl { text-transform: uppercase; letter-spacing: .1em;
                             font-size: 10px; color: var(--dim); margin: 0; }
  .advisor .conf-lift .v { font-variant-numeric: tabular-nums; color: var(--grn);
                           font-weight: 500; }
  .advisor .conf-lift .drift { margin-left: auto; color: var(--dim);
                               font-size: 11px; font-variant-numeric: tabular-nums; }
  /* Model-drift advisory: red-bordered chip when today's live_ratio
     diverges significantly from the SolarModel coefficient. Tier-1
     visibility — operator should notice and consider re-fitting. */
  .advisor .drift-advisory { display: flex; gap: 8px; align-items: baseline;
                             flex-wrap: wrap; margin-top: 6px;
                             padding: 6px 10px; border-radius: 4px;
                             background: rgba(248, 81, 73, 0.08);
                             border-left: 3px solid var(--red);
                             font-size: 12px; cursor: help; }
  .advisor .drift-advisory .lbl { text-transform: uppercase; letter-spacing: .1em;
                                  font-size: 10px; color: var(--red); margin: 0;
                                  font-weight: 500; }
  .advisor .drift-advisory .v { font-variant-numeric: tabular-nums;
                                color: var(--red); font-weight: 500; }
  .advisor .drift-advisory .drift { margin-left: auto; color: var(--red);
                                    font-weight: 500;
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
  <!-- Stale-data banner: hidden by default; the JS toggles its
       visibility when latest pack sample is > 60 s old. Tier-1
       visibility because a stalled BLE logger means everything
       below is reading frozen data. -->
  <div id="stale-banner" class="stale-banner" style="display:none">
    <span class="stale-icon">⚠</span>
    <span id="stale-text">pack data is stale</span>
    <span class="stale-hint">(check the BLE logger at the cabin)</span>
  </div>
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

// Threshold matches scripts/health.py PACK_STALE_THRESHOLD_S so
// the CLI and dashboard agree on when "stale" means stale.
const STALE_THRESHOLD_S = 60;

function updateStaleBanner(latestTs) {
  const banner = document.getElementById("stale-banner");
  if (!banner) return;
  if (!latestTs) {
    banner.style.display = "none";
    return;
  }
  const t = Date.parse(latestTs);
  if (isNaN(t)) {
    banner.style.display = "none";
    return;
  }
  const ageS = (Date.now() - t) / 1000;
  if (ageS <= STALE_THRESHOLD_S) {
    banner.style.display = "none";
    return;
  }
  // Compact unit-appropriate age string (mirrors health._fmt_age)
  let ageStr;
  if (ageS < 90) ageStr = `${Math.floor(ageS)} s`;
  else if (ageS < 60 * 90) ageStr = `${Math.floor(ageS / 60)} min`;
  else if (ageS < 24 * 3600) ageStr = `${(ageS / 3600).toFixed(1)} h`;
  else ageStr = `${(ageS / 86400).toFixed(1)} d`;
  setText("stale-text", `pack data is stale — last sample ${ageStr} ago`);
  banner.style.display = "flex";
}

async function tick() {
  try {
    const r = await fetch("/api/latest.json");
    const j = await r.json();
    if (!j.latest) {
      setText("state-value", "no data yet");
      updateStaleBanner(null);
      return;
    }
    const x = j.latest;
    updateStaleBanner(x.ts);
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

    // Compute solar-onset milestone markers for the visible window.
    // Each milestone (first_zero / idle / positive / net_positive)
    // becomes a dashed vertical line on the sparklines if its
    // timestamp falls within the rolling window. Today's morning
    // cascade is most useful right after it happens; older milestones
    // scroll off the chart as the window advances.
    // Milestones at identical timestamps (first_zero and first_idle
    // are commonly equal) are de-duped to a single marker.
    function computeOnsetMarkers(series, onset) {
      if (!series || !series.length || !onset) return [];
      const milestones = [
        {key: "first_zero_iso",         label: "zero", color: "#8b949e"},
        {key: "first_idle_iso",         label: "idle", color: "#8b949e"},
        {key: "first_positive_iso",     label: "pos",  color: "#d29922"},
        {key: "first_net_positive_iso", label: "net+", color: "#3fb950"},
      ];
      const out = [];
      const firstT = Date.parse(series[0].ts);
      const lastT  = Date.parse(series[series.length - 1].ts);
      const span = lastT - firstT;
      if (!(span > 0)) return [];
      // Two-pass: first collect raw label-parts per iso ts, then build
      // markers. Keeps the merge clean ("zero + idle @ 06:44:10") even
      // when 2+ milestones share the same timestamp (very common —
      // first_zero and first_idle often coincide).
      const partsByIso = new Map();
      for (const m of milestones) {
        const iso = onset[m.key];
        if (!iso) continue;
        const t = Date.parse(iso);
        if (isNaN(t) || t < firstT || t > lastT) continue;
        if (!partsByIso.has(iso)) {
          partsByIso.set(iso, {labels: [], color: m.color, t});
        }
        partsByIso.get(iso).labels.push(m.label);
        // Latest milestone wins on color (so net+ green overrides idle gray)
        partsByIso.get(iso).color = m.color;
      }
      for (const [iso, info] of partsByIso) {
        const xFrac = (info.t - firstT) / span;
        out.push({
          xFrac,
          label: info.labels.join(" + ") + " @ " + iso.slice(11, 19),
          color: info.color,
        });
      }
      return out;
    }

    function spark(id, values, includeZero, color, markers) {
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
      // Solar-onset milestone markers: dashed vertical lines at the
      // mapped x-fraction, with a hover-tooltip showing which event
      // and when. Drawn UNDER the polyline so the data still reads
      // cleanly on top.
      const markerSvg = (markers || []).map(m => {
        const x = (PAD + m.xFrac * (W - 2 * PAD)).toFixed(1);
        return `<line x1="${x}" y1="0" x2="${x}" y2="${H}" `
             + `stroke="${m.color}" stroke-width="1" `
             + `stroke-dasharray="3,2" opacity="0.6">`
             + `<title>${m.label}</title></line>`;
      }).join("");
      svg.innerHTML = zeroLine + markerSvg +
        `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/>`;
    }

    const onsetMarkers = computeOnsetMarkers(series, j.solar_onset);
    const ps = series.map(x => x.pack_p ?? 0);
    spark("spark-p", ps, true, ps[ps.length-1] >= 0 ? "var(--grn)" : "var(--ylw)", onsetMarkers);
    const socs = series.map(x => (x.soc_a != null && x.soc_b != null) ? (x.soc_a + x.soc_b) / 2 : null).filter(v => v != null);
    spark("spark-soc", socs, false, "var(--blu)", onsetMarkers);
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

        // Accuracy-aware confidence badge: when the advisor's recent
        // projection track record is tight enough to lift the tier, the
        // user should see WHY. Surfaces (base → lifted) and the
        // empirical evidence behind it.
        const insTmp = rec.inputs || {};
        const liftedByAccuracy = insTmp.confidence_lifted_by_accuracy === true;
        let confLiftBadge = "";
        if (liftedByAccuracy) {
            const base = insTmp.confidence_base || "low";
            const ae   = insTmp.recent_abs_error_pp;
            const n    = insTmp.recent_accuracy_n;
            const liftTip = (
              "The advisor's recent projection track record is tight enough "
              + "to lift the confidence tier one notch. Base is the SolarModel's "
              + "data-fit confidence (driven by how many full days of harvest "
              + "we have). The lift comes from observed agreement between "
              + "projected and actual sunrise SOC — see /accuracy for the "
              + "full history."
            );
            confLiftBadge = `
              <div class="conf-lift" title="${liftTip}">
                <span class="lbl">confidence lifted</span>
                <span class="v">${base} → ${rec.confidence}</span>
                <span class="drift">last ${n} within ±${ae.toFixed(2)} pp</span>
              </div>
              <div class="calib-footer">
                <a href="/confidence" target="_blank" class="report-link">lift history ↗</a>
              </div>`;
        }

        // Model-drift advisory: when today's live_ratio diverges from
        // the SolarModel coefficient by >= MODEL_DRIFT_ADVISORY_THRESHOLD_PCT,
        // the advisor surfaces a string advisory. Render as a tier-1
        // red-bordered chip so the operator notices when the model is
        // potentially miscalibrated.
        let driftBadge = "";
        if (insTmp.model_drift_advisory) {
            const driftPct = insTmp.model_drift_pct;
            const ratio    = insTmp.live_ratio_ah_per_kwh_m2;
            const coef     = insTmp.solar_model_coefficient;
            const driftSign = (driftPct != null && driftPct >= 0) ? "+" : "";
            const driftTip = (
              "Today's measured live_ratio (Ah / kWh/m²) diverges "
              + "significantly from the SolarModel coefficient (fit from "
              + "prior complete days). When this advisory fires, the model "
              + "may be miscalibrated for current conditions — re-fitting "
              + "once more complete-day data accumulates is recommended. "
              + "See docs/site/loon_lake.md for context on known intra-day "
              + "and seasonal solar variability."
            );
            driftBadge = `
              <div class="drift-advisory" title="${driftTip}">
                <span class="lbl">⚠ model drift</span>
                <span class="v">${ratio.toFixed(2)} vs ${coef.toFixed(2)}</span>
                <span class="drift">${driftSign}${driftPct.toFixed(1)}%</span>
              </div>
              <div class="calib-footer">${insTmp.model_drift_advisory}</div>`;
        }

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
              // Link the footer to the full calibration log page so
              // the user can drill into the history of coefficient
              // changes (especially useful when a new auto-fit lands).
              calibFooter = `<div class="calib-footer">model last updated ${niceTs}${srcTxt} · <a href="/calibration" target="_blank" class="report-link">full log ↗</a></div>`;
            }
            const calibTip = (
              "Solar harvest efficiency check.\n"
              + "LEFT NUMBER (model): what the SolarModel uses to predict "
              + "tomorrow's harvest — fit from prior complete days.\n"
              + "RIGHT NUMBER (live): what today is measuring right now, "
              + "Ah harvested / kWh/m² of irradiance delivered.\n"
              + "DRIFT %: how far apart they are. <10% green (model and "
              + "reality agree), 10-20% amber (today is unusual), "
              + ">20% red (real divergence — see docs/site/loon_lake.md "
              + "for known intra-day non-linearity on the west-facing array)."
            );
            calibLine = `
              <div class="calib ${driftCls}" title="${calibTip}">
                <span class="lbl">model vs live</span>
                <span class="v">${modelCoef.toFixed(2)} → ${liveRatio.toFixed(2)} Ah/(kWh/m²)</span>
                <span class="drift">${driftSign}${driftPct.toFixed(1)}%</span>
              </div>
              ${calibFooter}`;
        }
        // Last sunrise accuracy chip (uses projection_accuracy data)
        // — shows up once the first projection_log entry's sunrise
        // target has crossed. Empty before that, naturally.
        let lastAccuracyLine = "";
        if (ins.last_accuracy_proj != null && ins.last_accuracy_actual != null) {
            const errPP = ins.last_accuracy_error_pp;
            const errCls = Math.abs(errPP) < 3 ? "ok"
                           : Math.abs(errPP) < 8 ? "warn" : "bad";
            const errSign = errPP >= 0 ? "+" : "−";
            const targetShort = ins.last_accuracy_target_iso ?
                ins.last_accuracy_target_iso.slice(0, 16) : "—";
            const accuracyTip = (
              "Result of the most recent projection_accuracy validation. "
              + "When the projection_log captures an advisor's predicted "
              + "sunrise SOC, we wait until that sunrise time arrives, then "
              + "compare against the actual pack SOC at that moment.\n"
              + "Positive error = pack overshot the prediction (good).\n"
              + "Negative = pack undershot.\n"
              + "Color band: |err| < 3 pp green, < 8 pp amber, otherwise red."
            );
            lastAccuracyLine = `
              <div class="calib ${errCls}" title="${accuracyTip}" style="margin-top:6px">
                <span class="lbl">last sunrise validation</span>
                <span class="v">predicted ${ins.last_accuracy_proj.toFixed(1)}% · actual ${ins.last_accuracy_actual.toFixed(1)}%</span>
                <span class="drift">${errSign}${Math.abs(errPP).toFixed(1)} pp</span>
              </div>
              <div class="calib-footer">target ${targetShort} · <a href="/accuracy" target="_blank" class="report-link">full history ↗</a></div>`;
        }

        advEl.innerHTML = `
            <div class="advisor ${cls} ${rec.confidence === 'low' ? 'conf-low' : ''}">
              <div class="lbl">recommendation<span class="conf-pill ${confClass}">${rec.confidence} confidence</span></div>
              <div class="verdict ${cls}">${headline}</div>
              <div class="reason">${rec.reason}</div>
              ${watchLine}
              ${whenLine}
              ${calibLine}
              ${lastAccuracyLine}
              ${confLiftBadge}
              ${driftBadge}
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
          <div class="footer">${weatherBits.join(" · ")}
            · <a href="/projections" target="_blank" class="report-link">history ↗</a></div>
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
          <div class="live-ratio" title="Solar harvest efficiency: Ah delivered to the pack today divided by kWh/m² of horizontal-plane irradiance received so far.&#10;Around 7 Ah/(kWh/m²) is the calibrated baseline for this west-facing array (see docs/site/loon_lake.md).&#10;A higher number in late afternoon is normal — direct beam hits the array at a more favorable angle than a horizontal pyranometer measures.">
            <span class="lbl">live ratio</span>
            <span class="v">${harv.live_ratio_ah_per_kwh_m2.toFixed(2)} Ah/(kWh/m²)</span>
            <span class="aside">${harv.irradiance_kwh_m2_so_far.toFixed(2)} kWh/m² actual so far</span>
          </div>` : ""}
          ${(() => {
            // "Today's peaks" subrow: glanceable end-of-day summary
            // even mid-day. Peak charge / smoothed / SOC / first
            // charging time. Hidden until we have at least a
            // peak_charge value (otherwise the row reads empty).
            const pk = harv.peaks;
            if (!pk || pk.peak_charge_a == null) return "";
            const charge = pk.peak_charge_a.toFixed(1);
            const smoothed = pk.peak_smoothed_a != null
              ? pk.peak_smoothed_a.toFixed(1) : "—";
            const soc = pk.peak_soc_pct != null
              ? pk.peak_soc_pct.toFixed(0) : "—";
            const startedAt = pk.first_charge_time || "—";
            const pkTip = (
              "Running maxima for today, captured from the full pack.csv "
              + "(not just the rolling window).\n"
              + "A PEAK: highest raw pack current.\n"
              + "A SMOOTHED: highest EMA-smoothed current.\n"
              + "% SOC: highest of either battery.\n"
              + "CHARGING START: HH:MM of the first sample with pack "
              + "current > 1 A — the empirical 'morning shadow cleared' "
              + "time for this west-facing array.\n"
              + "BEST HOUR: clock hour with the largest Ah delivered today; "
              + "useful retrospective on when the array peaked.\n"
              + "A↔B GAP: the largest |soc_a − soc_b| seen today. In a "
              + "healthy series pack this stays under ~3 %. Widening gap "
              + "under heavy load is an early signal of cell imbalance "
              + "or one battery aging faster."
            );
            // Best harvest hour (if any solar today). Show as 'HHh' →
            // 'NN Ah' so the user sees both 'when' and 'how much'.
            let bestHourStat = "";
            if (pk.best_harvest_hour != null && pk.best_harvest_hour_ah != null) {
              const hh = String(pk.best_harvest_hour).padStart(2, "0");
              bestHourStat =
                `<span class="stat"><span class="v">${hh}h →${pk.best_harvest_hour_ah.toFixed(1)}</span>`
                + `<span class="u">best hr (Ah)</span></span>`;
            }
            // A vs B SOC gap (max seen today). Subtle amber color above
            // 3 % to surface a widening trend without raising alarm.
            let gapStat = "";
            if (pk.peak_soc_gap_pct != null) {
              const g = pk.peak_soc_gap_pct;
              const cls = g >= 3.0 ? "warn" : "";
              gapStat =
                `<span class="stat"><span class="v ${cls}">${g.toFixed(1)}%</span>`
                + `<span class="u">A↔B gap (max)</span></span>`;
            }
            return `
              <div class="peaks" title="${pkTip}">
                <span class="lbl">today's peaks</span>
                <span class="stat"><span class="v">${charge}</span><span class="u">A peak</span></span>
                <span class="stat"><span class="v">${smoothed}</span><span class="u">A smoothed</span></span>
                <span class="stat"><span class="v">${soc}</span><span class="u">% SOC</span></span>
                <span class="stat"><span class="v">${startedAt}</span><span class="u">charging start</span></span>
                ${bestHourStat}
                ${gapStat}
              </div>`;
          })()}
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
            const frTip = (
              "Open-Meteo's day-total irradiance forecast as it has been "
              + "revised throughout the day.\n"
              + "FIRST: forecast at the start of the day (often from "
              + "yesterday's overnight model run).\n"
              + "LATEST: current forecast after Open-Meteo has ingested "
              + "today's observations.\n"
              + "DRIFT: net change first → latest.\n"
              + "SWING: (max − min) across the day, a measure of how "
              + "uncertain the forecast was. A flat line means Open-Meteo "
              + "was sure; a wide swing means the day was hard to predict."
            );
            return `
              <div class="forecast-rev ${driftCls}" title="${frTip}">
                <span class="lbl">forecast revisions</span>
                <span class="v">${fh.first.toFixed(2)} → ${fh.latest.toFixed(2)} kWh/m²</span>
                <span class="drift">${driftSign}${driftAbs.toFixed(1)}%${swingStr}</span>
              </div>`;
          })()}
          ${(() => {
            // Solar onset chip: the morning cascade of milestones.
            // Empty until at least the first zero-crossing has been
            // observed. Reads from j.solar_onset (set by the API).
            const so = j.solar_onset;
            if (!so || !so.first_zero_iso) return "";
            const tShort = (iso) => iso ? iso.slice(11, 16) : "—";
            // Determine how far along the cascade we are. The class
            // toggles between "ok" (net-positive achieved), "warn"
            // (still mid-cascade), and "dim" (just first-zero so far).
            let stage, cls;
            if (so.first_net_positive_iso) {
              stage = "net-positive";  cls = "ok";
            } else if (so.first_positive_iso) {
              stage = "transient positive";  cls = "warn";
            } else if (so.first_idle_iso) {
              stage = "idle";  cls = "warn";
            } else {
              stage = "first zero";  cls = "dim";
            }
            // Build a compact cascade line: zero → idle → pos → net+
            const cascadeBits = [
              `zero ${tShort(so.first_zero_iso)}`,
              so.first_idle_iso ? `idle ${tShort(so.first_idle_iso)}` : null,
              so.first_positive_iso ? `pos ${tShort(so.first_positive_iso)}` : null,
              so.first_net_positive_iso ? `net+ ${tShort(so.first_net_positive_iso)}` : null,
            ].filter(Boolean);
            const cascade = cascadeBits.join(" → ");
            // SOC at net-positive is the bottom of the day's curve —
            // valuable as a calibration check against the advisor's
            // projected_low_soc. Show only when available.
            const socLine = (so.soc_avg_at_net_positive != null)
              ? `<span class="drift">SOC ${so.soc_avg_at_net_positive.toFixed(1)} %</span>`
              : "";
            const onsetTip = (
              "Today's solar-onset cascade.\n"
              + "ZERO: first sample at pack_i = 0 (solar matched load).\n"
              + "IDLE: BMS classified state as idle, or |i| ≤ 0.5 A.\n"
              + "POS: instantaneous current went strictly positive (a "
              + "transient surge of solar over load).\n"
              + "NET+: smoothed current went net-positive — sustained "
              + "charging has begun.\n"
              + "SOC at NET+ is the bottom of today's curve, useful as "
              + "a check on the advisor's projected_low_soc."
            );
            return `
              <div class="solar-onset ${cls}" title="${onsetTip}">
                <span class="lbl">solar onset</span>
                <span class="v">${stage}</span>
                <span class="drift">${cascade}</span>
                ${socLine}
              </div>`;
          })()}
          <div class="footer">${harv.duration_h.toFixed(1)} h of data so far · ${harv.confidence} confidence
            · <a href="/today-report" target="_blank" class="report-link">today's report ↗</a>
            · <a href="/reports" target="_blank" class="report-link">all reports ↗</a>
            · <a href="/health" target="_blank" class="report-link">health summary ↗</a></div>
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
        if self.path == "/today-report" or self.path == "/today-report.md":
            return self._serve_report(datetime.now().date())
        if self.path == "/reports" or self.path == "/reports/":
            return self._serve_report_index()
        if self.path == "/calibration" or self.path == "/calibration/":
            return self._serve_calibration_log()
        if self.path == "/projections" or self.path == "/projections/":
            return self._serve_projection_log()
        if self.path == "/accuracy" or self.path == "/accuracy/":
            return self._serve_projection_accuracy()
        if self.path == "/low-accuracy" or self.path == "/low-accuracy/":
            return self._serve_low_soc_accuracy()
        if self.path == "/confidence" or self.path == "/confidence/":
            return self._serve_confidence_log()
        if self.path == "/health" or self.path == "/health/":
            return self._serve_health()
        # /report/YYYY-MM-DD — historical day-report
        if self.path.startswith("/report/"):
            date_str = self.path[len("/report/"):].rstrip("/")
            try:
                from datetime import date as _date
                d = _date.fromisoformat(date_str)
            except ValueError:
                return self._send(HTTPStatus.NOT_FOUND, "text/plain",
                                  b"bad date format; use /report/YYYY-MM-DD")
            return self._serve_report(d)
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
            # Run solar-onset detection + upsert for today. Best-effort:
            # detection scans a single day's pack.csv rows (cheap) and
            # upserts the result. The returned record (which may have
            # nones for milestones still pending) is surfaced on the
            # harvest panel as a chip.
            solar_onset = None
            try:
                import solar_onset as so_mod
                rec, _ = so_mod.detect_and_record(pack_csv=CSV_PATH)
                solar_onset = {
                    "date": rec.date,
                    "first_zero_iso": rec.first_zero_iso,
                    "first_idle_iso": rec.first_idle_iso,
                    "first_positive_iso": rec.first_positive_iso,
                    "first_net_positive_iso": rec.first_net_positive_iso,
                    "smoothed_i_at_net_positive": rec.smoothed_i_at_net_positive,
                    "soc_avg_at_net_positive": rec.soc_avg_at_net_positive,
                }
            except Exception:
                solar_onset = None
            return self._send(HTTPStatus.OK, "application/json",
                              json.dumps({
                                  "latest": history[-1],
                                  "history": history,
                                  "events": events[-20:],  # last 20 only, keep payload small
                                  "projection": projection,
                                  "recommendation": recommendation,
                                  "today_harvest": today_harvest,
                                  "solar_onset": solar_onset,
                              }).encode())
        return self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")

    REPORT_PAGE_STYLE = (
        "body{background:#0d1117;color:#c9d1d9;"
        "font-family:ui-monospace,SFMono-Regular,monospace;"
        "max-width:780px;margin:0 auto;padding:24px 16px;"
        "font-size:14px;line-height:1.5}"
        "a{color:#58a6ff}"
        "pre{white-space:pre-wrap;word-wrap:break-word;margin:0}"
        "ul{padding-left:18px} li{margin:6px 0}"
        ".today{color:#3fb950;font-weight:600}"
    )

    @staticmethod
    def _markdown_to_html(md: str) -> str:
        """Minimal markdown → HTML converter sized for our day-report
        format. Supports: # heading, ## heading, ### heading,
        **bold**, *italic*, `code`, - list items, [text](url),
        markdown tables. Anything unrecognized passes through
        html-escaped. No external dep so the dashboard stays
        self-contained.

        Deliberately not a full markdown spec — just the subset
        end_of_day_report.build_report emits.
        """
        import re

        lines = md.split("\n")
        out: list[str] = []
        in_ul = False
        in_table = False
        table_rows: list[list[str]] = []
        table_header: list[str] = []

        def flush_ul() -> None:
            nonlocal in_ul
            if in_ul:
                out.append("</ul>")
                in_ul = False

        def flush_table() -> None:
            nonlocal in_table, table_rows, table_header
            if in_table and table_header and table_rows:
                hdr = "".join(f"<th>{c}</th>" for c in table_header)
                body = "".join(
                    "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                    for row in table_rows
                )
                out.append(
                    f"<table><thead><tr>{hdr}</tr></thead>"
                    f"<tbody>{body}</tbody></table>"
                )
            in_table = False
            table_rows = []
            table_header = []

        def inline(text: str) -> str:
            """Apply inline formatters to an already-escaped line."""
            # `code`
            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            # **bold**
            text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
            # *italic* (only when not part of **)
            text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
            # [text](url)
            text = re.sub(
                r"\[([^\]]+)\]\(([^)]+)\)",
                r'<a href="\2">\1</a>',
                text,
            )
            return text

        for raw in lines:
            line = raw.rstrip()
            # Tables
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                # Header separator row (---|---|---)
                if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                    continue
                cells_esc = [inline(html_escape(c)) for c in cells]
                if not in_table:
                    in_table = True
                    table_header = cells_esc
                else:
                    table_rows.append(cells_esc)
                flush_ul()
                continue
            else:
                flush_table()

            # Empty line ends list
            if not line:
                flush_ul()
                out.append("")
                continue

            # Headings
            m = re.match(r"^(#{1,3})\s+(.+)$", line)
            if m:
                flush_ul()
                level = len(m.group(1))
                # H1 in the page is already the <h1>; bump report
                # headings down one level so the visual hierarchy
                # stays sane.
                tag = {1: "h2", 2: "h3", 3: "h4"}[level]
                out.append(f"<{tag}>{inline(html_escape(m.group(2)))}</{tag}>")
                continue

            # List item
            m = re.match(r"^[-*]\s+(.+)$", line)
            if m:
                if not in_ul:
                    out.append("<ul>")
                    in_ul = True
                out.append(f"<li>{inline(html_escape(m.group(1)))}</li>")
                continue

            # Paragraph (single-line)
            flush_ul()
            out.append(f"<p>{inline(html_escape(line))}</p>")

        flush_ul()
        flush_table()
        return "\n".join(out)

    def _serve_report(self, day):
        """Render one day's report. For today the report is regenerated
        live on each request (no stale-snapshot risk); for historical
        days, read the committed file as-is (avoids touching old data
        with newer scripts)."""
        from datetime import date as _date
        today = datetime.now().date()
        try:
            if day == today:
                report_md = end_of_day_report_mod.build_report(day)
            else:
                fpath = Path("data/reports") / f"{day.isoformat()}.md"
                if not fpath.exists():
                    return self._send(
                        HTTPStatus.NOT_FOUND, "text/plain",
                        f"no report for {day.isoformat()}".encode())
                report_md = fpath.read_text()
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not generate report: {e}".encode())
        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Day report — {day.isoformat()}</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " h2{margin-top:24px;margin-bottom:8px;color:#f0f6fc}"
            " h3{margin-top:18px;margin-bottom:6px;color:#c9d1d9}"
            " p{margin:6px 0}"
            " ul{padding-left:22px;margin:6px 0}"
            " li{margin:3px 0}"
            " strong{color:#f0f6fc}"
            " code{background:#161b22;padding:1px 4px;border-radius:3px;font-size:12px}"
            " table{border-collapse:collapse;margin:10px 0;font-size:12px;"
            " font-variant-numeric:tabular-nums}"
            " th,td{padding:4px 10px;border-bottom:1px solid #21262d;text-align:left}"
            " th{color:#8b949e;border-bottom:1px solid #30363d}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/reports'>all reports</a></p>"
            + self._markdown_to_html(report_md)
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_projection_accuracy(self):
        """Render projection-vs-actual diff. Empty until the first
        projection_log entry's sunrise_iso target time passes (first
        sunrise after the log starts collecting). Until then shows
        a graceful 'waiting for first sunrise' message."""
        import projection_log as proj_mod
        import projection_accuracy as acc_mod

        try:
            projections = proj_mod.read_log()
            pack_samples = acc_mod._load_pack_samples(CSV_PATH)
            records = acc_mod.compute_accuracy_records(
                projections, pack_samples,
            )
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not compute accuracy: {e}".encode())

        records = list(reversed(records))   # newest first

        if records:
            def _row(r):
                sr = r.sunrise_iso[:16] if len(r.sunrise_iso) >= 16 else r.sunrise_iso
                made = r.projection_ts[:16] if len(r.projection_ts) >= 16 else r.projection_ts
                sign = "+" if r.error_pct_points >= 0 else "−"
                err_cls = ("ok" if abs(r.error_pct_points) <= 3
                           else "warn" if abs(r.error_pct_points) <= 8
                           else "bad")
                return (
                    "<tr>"
                    f"<td>{html_escape(made)}</td>"
                    f"<td>{html_escape(sr)}</td>"
                    f"<td style='text-align:right'>{r.projected_sunrise_soc:.1f}</td>"
                    f"<td style='text-align:right'>{r.actual_sunrise_soc:.1f}</td>"
                    f"<td style='text-align:right' class='err-{err_cls}'>"
                    f"{sign}{abs(r.error_pct_points):.1f}</td>"
                    f"<td style='text-align:right'>{r.solar_model_coefficient:.3f}</td>"
                    f"<td style='text-align:right;color:#8b949e'>"
                    f"{r.sample_offset_min:.0f} min</td>"
                    "</tr>"
                )
            rows_html = "".join(_row(r) for r in records)
            chronological = list(reversed(records))
            s = acc_mod.summarize(chronological)  # mean over all
            summary_html = (
                "<p style='color:#8b949e;font-size:12px;margin-top:14px'>"
                f"<strong>summary</strong> · n = {s['n']} · "
                f"mean error <strong>{s['mean_error']:+.2f} pp</strong> · "
                f"mean abs <strong>{s['mean_abs_error']:.2f} pp</strong> · "
                f"RMS <strong>{s['rms_error']:.2f} pp</strong> · "
                f"range [{s['min_error']:+.2f} .. {s['max_error']:+.2f}]"
                "</p>"
            )

            # Per-horizon breakdown: how does the error change with
            # lead-time? Shows whether the advisor is biased one way
            # far out and the other way close in.
            by_h = acc_mod.summarize_by_horizon(chronological)
            if by_h:
                def _h_row(b):
                    err_cls = ("ok" if abs(b['mean_error']) <= 3
                               else "warn" if abs(b['mean_error']) <= 8
                               else "bad")
                    return (
                        "<tr>"
                        f"<td>{html_escape(b['bucket'])}</td>"
                        f"<td style='text-align:right'>{b['n']}</td>"
                        f"<td style='text-align:right' class='err-{err_cls}'>"
                        f"{b['mean_error']:+.2f}</td>"
                        f"<td style='text-align:right'>{b['mean_abs_error']:.2f}</td>"
                        f"<td style='text-align:right'>{b['rms_error']:.2f}</td>"
                        f"<td style='text-align:right;color:#8b949e'>"
                        f"[{b['min_error']:+.2f}..{b['max_error']:+.2f}]</td>"
                        "</tr>"
                    )
                horizon_rows_html = "".join(_h_row(b) for b in by_h)
                horizon_chart_svg = render_horizon_bar_chart(by_h)
                horizon_block = (
                    "<h3 style='margin-top:24px;margin-bottom:6px;"
                    "color:#c9d1d9;font-size:14px'>By lead-time horizon</h3>"
                    "<p style='color:#8b949e;font-size:12px;margin-top:0'>"
                    "How far ahead the projection was made vs how it landed. "
                    "A consistent bias here is the strongest signal of a "
                    "model-fit issue — e.g. far-out projections systematically "
                    "optimistic suggests the discharge_model is too gentle, "
                    "while close-in projections systematically pessimistic "
                    "suggests something else (e.g. solar arriving earlier than "
                    "the SolarModel expects)."
                    "</p>"
                    + horizon_chart_svg
                    + "<table>"
                    "<thead><tr>"
                    "<th>horizon</th>"
                    "<th style='text-align:right'>n</th>"
                    "<th style='text-align:right'>mean</th>"
                    "<th style='text-align:right'>abs</th>"
                    "<th style='text-align:right'>rms</th>"
                    "<th style='text-align:right'>range</th>"
                    "</tr></thead>"
                    f"<tbody>{horizon_rows_html}</tbody></table>"
                )
            else:
                horizon_block = ""

            table = (
                "<h3 style='margin-top:24px;margin-bottom:6px;"
                "color:#c9d1d9;font-size:14px'>All records</h3>"
                "<table>"
                "<thead><tr>"
                "<th>made at</th>"
                "<th>target</th>"
                "<th style='text-align:right'>projected</th>"
                "<th style='text-align:right'>actual</th>"
                "<th style='text-align:right'>error</th>"
                "<th style='text-align:right'>coef</th>"
                "<th style='text-align:right'>±t</th>"
                "</tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
            )
            body = horizon_block + table + summary_html
        else:
            body = (
                "<p style='color:#8b949e;font-style:italic'>"
                "(no validatable projections yet — the first record "
                "lands at the next sunrise after the projection log "
                "starts collecting; until then, all entries' sunrise "
                "targets are still in the future)"
                "</p>"
            )

        intro = (
            "<h2 style='margin-top:0'>Projection accuracy</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "For each historical advisor projection whose sunrise "
            "target time has passed, the actual pack SOC at that time "
            "(closest sample within ±30 min) is compared to what the "
            "advisor predicted. <strong>Positive error</strong> = pack "
            "did better than predicted; <strong>negative</strong> = "
            "worse. Color band: |error| &lt; 3 pp green, &lt; 8 pp "
            "amber, otherwise red. Useful for spotting systematic "
            "bias in the SolarModel or discharge_model over many days."
            "</p>"
        )

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Projection accuracy</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " table{border-collapse:collapse;font-size:12px;"
            "font-variant-numeric:tabular-nums;margin-top:10px}"
            " th,td{padding:5px 10px;border-bottom:1px solid #21262d;text-align:left}"
            " th{color:#8b949e;border-bottom:1px solid #30363d}"
            " .err-ok{color:#3fb950}"
            " .err-warn{color:#d29922}"
            " .err-bad{color:#f85149}"
            " strong{color:#c9d1d9}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/projections'>projection log</a> · "
            "<a href='/calibration'>calibration log</a> · "
            "<a href='/low-accuracy'>morning-low accuracy</a> · "
            "<a href='/confidence'>confidence log</a></p>"
            + intro
            + body
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_low_soc_accuracy(self):
        """Render morning-low validation diff. Sister of /accuracy.
        For each projection_log entry that has a matching, fully-
        resolved solar_onset row, shows projected_low_soc vs the
        empirical morning low (= soc_avg_at_net_positive). The
        per-horizon breakdown surfaces the systematic lead-time bias
        that drove the 2026-05-19 simulator floor-bias fix."""
        import projection_log as proj_mod
        import solar_onset as so_mod
        import low_soc_accuracy as low_mod

        try:
            projections = proj_mod.read_log()
            onsets = so_mod.read_log()
            records = low_mod.compute_accuracy_records(projections, onsets)
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not compute low-soc accuracy: {e}".encode())

        records = list(reversed(records))   # newest first

        if records:
            def _row(r):
                made = r.projection_ts[:16] if len(r.projection_ts) >= 16 else r.projection_ts
                sign = "+" if r.error_pct_points >= 0 else "−"
                # Color band: <3 ok, <8 warn, else bad
                err_cls = ("ok" if abs(r.error_pct_points) <= 3
                           else "warn" if abs(r.error_pct_points) <= 8
                           else "bad")
                return (
                    "<tr>"
                    f"<td>{html_escape(made)}</td>"
                    f"<td>{html_escape(r.target_date)}</td>"
                    f"<td style='text-align:right'>{r.projected_low_soc:.1f}</td>"
                    f"<td style='text-align:right'>{r.actual_low_soc:.1f}</td>"
                    f"<td style='text-align:right' class='err-{err_cls}'>"
                    f"{sign}{abs(r.error_pct_points):.1f}</td>"
                    f"<td style='text-align:right'>{r.solar_model_coefficient:.3f}</td>"
                    f"<td style='text-align:right;color:#8b949e'>"
                    f"{r.horizon_min/60:.1f}h</td>"
                    "</tr>"
                )
            rows_html = "".join(_row(r) for r in records)
            chronological = list(reversed(records))
            s = low_mod.summarize(chronological)
            summary_html = (
                "<p style='color:#8b949e;font-size:12px;margin-top:14px'>"
                f"<strong>summary</strong> · n = {s['n']} · "
                f"mean error <strong>{s['mean_error']:+.2f} pp</strong> · "
                f"mean abs <strong>{s['mean_abs_error']:.2f} pp</strong> · "
                f"RMS <strong>{s['rms_error']:.2f} pp</strong> · "
                f"range [{s['min_error']:+.2f} .. {s['max_error']:+.2f}]"
                "</p>"
            )

            by_h = low_mod.summarize_by_horizon(chronological)
            if by_h:
                def _h_row(b):
                    err_cls = ("ok" if abs(b['mean_error']) <= 3
                               else "warn" if abs(b['mean_error']) <= 8
                               else "bad")
                    return (
                        "<tr>"
                        f"<td>{html_escape(b['bucket'])}</td>"
                        f"<td style='text-align:right'>{b['n']}</td>"
                        f"<td style='text-align:right' class='err-{err_cls}'>"
                        f"{b['mean_error']:+.2f}</td>"
                        f"<td style='text-align:right'>{b['mean_abs_error']:.2f}</td>"
                        f"<td style='text-align:right'>{b['rms_error']:.2f}</td>"
                        f"<td style='text-align:right;color:#8b949e'>"
                        f"[{b['min_error']:+.2f}..{b['max_error']:+.2f}]</td>"
                        "</tr>"
                    )
                horizon_rows_html = "".join(_h_row(b) for b in by_h)
                horizon_chart_svg = render_horizon_bar_chart(by_h)
                horizon_block = (
                    "<h3 style='margin-top:24px;margin-bottom:6px;"
                    "color:#c9d1d9;font-size:14px'>By lead-time horizon</h3>"
                    "<p style='color:#8b949e;font-size:12px;margin-top:0'>"
                    "How floor-projection error varies with how far ahead "
                    "the projection was made. A monotonic negative trend "
                    "with lead-time is the fingerprint of a model that "
                    "doesn't account for post-sunrise discharge before "
                    "solar overtakes load — driving force behind the "
                    "2026-05-19 sinusoidal-solar fix."
                    "</p>"
                    + horizon_chart_svg
                    + "<table>"
                    "<thead><tr>"
                    "<th>horizon</th>"
                    "<th style='text-align:right'>n</th>"
                    "<th style='text-align:right'>mean</th>"
                    "<th style='text-align:right'>abs</th>"
                    "<th style='text-align:right'>rms</th>"
                    "<th style='text-align:right'>range</th>"
                    "</tr></thead>"
                    f"<tbody>{horizon_rows_html}</tbody></table>"
                )
            else:
                horizon_block = ""

            table = (
                "<h3 style='margin-top:24px;margin-bottom:6px;"
                "color:#c9d1d9;font-size:14px'>All records</h3>"
                "<table>"
                "<thead><tr>"
                "<th>made at</th>"
                "<th>target day</th>"
                "<th style='text-align:right'>projected low</th>"
                "<th style='text-align:right'>actual low</th>"
                "<th style='text-align:right'>error</th>"
                "<th style='text-align:right'>coef</th>"
                "<th style='text-align:right'>lead</th>"
                "</tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
            )
            body = horizon_block + table + summary_html
        else:
            body = (
                "<p style='color:#8b949e;font-style:italic'>"
                "(no validatable morning-low projections yet — the first "
                "record lands once a day's <code>solar_onset.csv</code> "
                "row has its <code>first_net_positive_iso</code> populated)"
                "</p>"
            )

        intro = (
            "<h2 style='margin-top:0'>Morning-low validation</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "Sister of <a href='/accuracy'>/accuracy</a>. Validates the "
            "advisor's <code>projected_low_soc</code> field against the "
            "empirical morning low (the SOC at "
            "<code>solar_onset.first_net_positive_iso</code> — the moment "
            "sustained net charging begins). <strong>Negative error</strong> "
            "= pack undershot the predicted floor (advisor was too "
            "<em>optimistic</em>). The bias surfaced here drove the "
            "2026-05-19 simulator fix: replacing uniform-NET daylight "
            "solar with a sinusoidal gross-solar + per-hour-load model. "
            "Watch this view over coming days to see whether the fix "
            "closes the gap or whether a separate morning-load model is "
            "needed."
            "</p>"
        )

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Morning-low accuracy</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " table{border-collapse:collapse;font-size:12px;"
            "font-variant-numeric:tabular-nums;margin-top:10px}"
            " th,td{padding:5px 10px;border-bottom:1px solid #21262d;text-align:left}"
            " th{color:#8b949e;border-bottom:1px solid #30363d}"
            " .err-ok{color:#3fb950}"
            " .err-warn{color:#d29922}"
            " .err-bad{color:#f85149}"
            " strong{color:#c9d1d9}"
            " code{background:#161b22;padding:1px 4px;border-radius:3px}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/accuracy'>sunrise accuracy</a> · "
            "<a href='/projections'>projection log</a> · "
            "<a href='/calibration'>calibration log</a> · "
            "<a href='/confidence'>confidence log</a></p>"
            + intro
            + body
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_projection_log(self):
        """Render data/projection_log.csv as a dark-themed HTML table.
        Each row is an advisor invocation's projection snapshot —
        start SOC, predicted sunrise SOC, predicted tomorrow-evening
        SOC, predicted low SOC, the SolarModel coefficient in effect.

        Builds the historical record for the eventual 'nightly diff'
        feature (predicted sunrise SOC vs actual). Newest-first so
        the freshest data is at the top of the page."""
        import projection_log as proj_mod
        try:
            entries = proj_mod.read_log()
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not read projection log: {e}".encode())

        entries = list(reversed(entries))  # newest first

        if entries:
            def _row(e):
                kwh = (f"{e.today_irradiance_kwh_m2:.2f}"
                       if e.today_irradiance_kwh_m2 is not None else "—")
                return (
                    "<tr>"
                    f"<td>{html_escape(e.ts)}</td>"
                    f"<td style='text-align:right'>{e.start_soc_pct:.1f}</td>"
                    f"<td style='text-align:right'>{e.projected_sunrise_soc:.1f}</td>"
                    f"<td style='text-align:right'>{e.projected_tomorrow_evening_soc:.1f}</td>"
                    f"<td style='text-align:right'>{e.projected_low_soc:.1f}</td>"
                    f"<td style='text-align:right'>{e.solar_model_coefficient:.3f}</td>"
                    f"<td style='text-align:right'>{kwh}</td>"
                    f"<td>{html_escape(e.source)}</td>"
                    "</tr>"
                )
            rows_html = "".join(_row(e) for e in entries)
            table = (
                "<table>"
                "<thead><tr>"
                "<th>timestamp</th>"
                "<th style='text-align:right'>start SOC</th>"
                "<th style='text-align:right'>→ sunrise</th>"
                "<th style='text-align:right'>→ tom eve</th>"
                "<th style='text-align:right'>→ low</th>"
                "<th style='text-align:right'>coef</th>"
                "<th style='text-align:right'>kWh/m²</th>"
                "<th>source</th>"
                "</tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
            )
            body_lines = [table]
        else:
            body_lines = ["<p style='color:#8b949e;font-style:italic'>"
                          "(no projection log entries yet — they accumulate "
                          "as the advisor runs)"
                          "</p>"]

        intro = (
            "<h2 style='margin-top:0'>Advisor projection log</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "Each row captures a `generator_advisor` invocation's "
            "projection of next-24-h SOC walk. Newest first. "
            "Rate-limited to one entry per 25 min so the dashboard's "
            "minute-rate subprocess calls don't spam the log. Use this "
            "history to compare past predictions against subsequently-"
            "observed reality (the 'nightly diff' is on the roadmap)."
            "</p>"
        )

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Projection log</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " table{border-collapse:collapse;font-size:12px;"
            "font-variant-numeric:tabular-nums;margin-top:10px}"
            " th,td{padding:5px 10px;border-bottom:1px solid #21262d;text-align:left}"
            " th{color:#8b949e;border-bottom:1px solid #30363d}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/calibration'>calibration log</a> · "
            "<a href='/accuracy'>accuracy</a> · "
            "<a href='/low-accuracy'>morning-low accuracy</a> · "
            "<a href='/confidence'>confidence log</a></p>"
            + intro
            + "".join(body_lines)
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_calibration_log(self):
        """Render data/calibration_log.csv as a dark-themed HTML table.
        Each row captures a SolarModel coefficient change with timestamp
        + cause. Linked from the advisor panel's calib-footer line so
        the user can drill in from 'model last updated 2026-05-18 21:00'
        to the full history. Empty log degrades gracefully."""
        import calibration_log as cal_mod
        try:
            entries = cal_mod.read_log()
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not read calibration log: {e}".encode())

        # Newest first (the log appends so file order is oldest-first)
        entries = list(reversed(entries))

        if entries:
            rows_html = "".join(
                f"<tr><td>{html_escape(e.ts)}</td>"
                f"<td style='text-align:right'>{e.coefficient:.4f}</td>"
                f"<td style='text-align:right'>{e.n_observations}</td>"
                f"<td>{html_escape(e.confidence)}</td>"
                f"<td>{html_escape(e.source)}</td>"
                f"<td>{html_escape(e.notes)}</td></tr>"
                for e in entries
            )
            table = (
                "<table style='border-collapse:collapse;width:100%;"
                "font-size:12px;font-variant-numeric:tabular-nums'>"
                "<thead><tr style='text-align:left;color:#8b949e;"
                "border-bottom:1px solid #30363d'>"
                "<th style='padding:6px 8px'>timestamp</th>"
                "<th style='padding:6px 8px;text-align:right'>coef</th>"
                "<th style='padding:6px 8px;text-align:right'>n_obs</th>"
                "<th style='padding:6px 8px'>confidence</th>"
                "<th style='padding:6px 8px'>source</th>"
                "<th style='padding:6px 8px'>notes</th>"
                "</tr></thead>"
                "<tbody style='border-bottom:1px solid #30363d'>"
                + rows_html.replace("<tr>",
                                    "<tr style='border-bottom:1px solid #21262d'>"
                                    .replace("<tr>", "<tr>"))
                + "</tbody></table>"
            )
            body_lines = [table]
        else:
            body_lines = ["<p style='color:#8b949e;font-style:italic'>"
                          "(no calibration log entries yet — "
                          "they accumulate as SolarModel coefficients change)"
                          "</p>"]

        intro = (
            "<h2 style='margin-top:0'>SolarModel calibration log</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "Every meaningful SolarModel coefficient change is recorded here, "
            "newest first. Triggered automatically by the generator advisor "
            "(once per invocation, idempotent — no-op when nothing has shifted). "
            "Sources: <code>loop-iteration</code>, <code>advisor-invocation</code>, "
            "<code>manual</code>. See <code>scripts/calibration_log.py</code>.</p>"
        )

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Calibration log</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " td{padding:6px 8px;vertical-align:top}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/projections'>projection log</a> · "
            "<a href='/accuracy'>accuracy</a> · "
            "<a href='/low-accuracy'>morning-low accuracy</a> · "
            "<a href='/confidence'>confidence log</a></p>"
            + intro
            + "".join(body_lines)
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_confidence_log(self):
        """Render data/confidence_log.csv as a dark-themed HTML table.
        One row per confidence-lift TRANSITION (base/resolved/lifted
        flag changes). The advisor calls confidence_log.record_if_changed
        on each invocation; stable states stay quiet so the log is a
        timeline of meaningful events, not a stream of duplicates.

        Linked from the advisor panel's `conf-lift` badge tooltip and
        from the other log pages."""
        import confidence_log as conf_mod
        try:
            entries = conf_mod.read_log()
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not read confidence log: {e}".encode())

        entries = list(reversed(entries))    # newest first

        if entries:
            def _row(e):
                lifted_cls = "ok" if e.lifted else "dim"
                lifted_label = "lifted" if e.lifted else "—"
                ae = ("—" if e.recent_abs_error_pp is None
                      else f"{e.recent_abs_error_pp:.2f}")
                # The "delta" column makes the transition obvious at a
                # glance: when base == resolved it's just the base;
                # when lifted, it's "base → resolved" with an arrow.
                if e.base == e.resolved:
                    transition = html_escape(e.base)
                else:
                    transition = (
                        f"{html_escape(e.base)} → "
                        f"<strong>{html_escape(e.resolved)}</strong>"
                    )
                return (
                    "<tr>"
                    f"<td>{html_escape(e.ts)}</td>"
                    f"<td>{transition}</td>"
                    f"<td class='lift-{lifted_cls}' style='text-align:center'>"
                    f"{lifted_label}</td>"
                    f"<td style='text-align:right'>{ae}</td>"
                    f"<td style='text-align:right'>{e.recent_n}</td>"
                    f"<td>{html_escape(e.source)}</td>"
                    "</tr>"
                )
            rows_html = "".join(_row(e) for e in entries)
            table = (
                "<table>"
                "<thead><tr>"
                "<th>timestamp</th>"
                "<th>tier (base → resolved)</th>"
                "<th style='text-align:center'>lifted?</th>"
                "<th style='text-align:right'>recent abs err (pp)</th>"
                "<th style='text-align:right'>recent n</th>"
                "<th>source</th>"
                "</tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
            )
            body = table
        else:
            body = (
                "<p style='color:#8b949e;font-style:italic'>"
                "(no confidence-lift events logged yet — the first "
                "row lands the next time the generator advisor "
                "computes a confidence tier with a non-default "
                "track record)"
                "</p>"
            )

        intro = (
            "<h2 style='margin-top:0'>Confidence-lift history</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "Each row marks a moment when the advisor's accuracy-aware "
            "confidence state changed. Sources: <code>advisor-invocation</code>. "
            "<strong>base</strong> is the SolarModel's underlying confidence "
            "(driven by days-of-fit data); <strong>resolved</strong> is what "
            "the advisor actually emits after the accuracy-aware lift. "
            "<strong>lifted?</strong> = whether the recent track record was "
            "tight enough to bump the tier one notch "
            "(see <code>scripts/generator_advisor.py</code> → "
            "<code>lift_confidence_by_accuracy</code>). Stable states are "
            "deduped so this view is a timeline of transitions."
            "</p>"
        )

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Confidence-lift history</title>"
            f"<style>{self.REPORT_PAGE_STYLE}"
            " table{border-collapse:collapse;font-size:12px;"
            "font-variant-numeric:tabular-nums;margin-top:10px;width:100%}"
            " th,td{padding:5px 10px;border-bottom:1px solid #21262d;text-align:left}"
            " th{color:#8b949e;border-bottom:1px solid #30363d}"
            " .lift-ok{color:#3fb950;font-weight:500}"
            " .lift-dim{color:#8b949e}"
            " strong{color:#c9d1d9}"
            "</style>"
            "<p><a href='/'>&larr; dashboard</a> · "
            "<a href='/accuracy'>accuracy</a> · "
            "<a href='/low-accuracy'>morning-low accuracy</a> · "
            "<a href='/projections'>projection log</a> · "
            "<a href='/calibration'>calibration log</a></p>"
            + intro
            + body
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

    def _serve_health(self):
        """Render scripts.health.render_summary() as a clean preformatted
        HTML page. Quick lightweight overview when the chart-heavy main
        page is overkill (SSH on slow link, mobile, etc.). Reuses the
        CLI's render function directly so the two surfaces never
        diverge."""
        import health as health_mod
        try:
            summary = health_mod.render_summary()
        except Exception as e:
            return self._send(HTTPStatus.OK, "text/plain; charset=utf-8",
                              f"could not build summary: {e}".encode())

        # Auto-refresh every 30 s so the page stays fresh without the
        # full dashboard's per-5-s polling. Targets the SSH-from-phone
        # use case where bandwidth is the constraint.
        body = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='30'>"
            "<title>Volthium health</title>"
            "<style>"
            "body{background:#0d1117;color:#c9d1d9;"
            "font-family:ui-monospace,SFMono-Regular,monospace;"
            "max-width:780px;margin:0 auto;padding:16px;"
            "font-size:14px;line-height:1.5}"
            "a{color:#58a6ff}"
            "pre{white-space:pre-wrap;word-wrap:break-word;margin:0;"
            "padding:14px;background:#161b22;border-radius:6px;"
            "font-size:13px}"
            ".footer{color:#8b949e;font-size:11px;margin-top:14px}"
            "</style>"
            "<p><a href='/'>&larr; full dashboard</a> · "
            "<a href='/today-report'>today's report</a> · "
            "<a href='/accuracy'>accuracy</a> · "
            "<a href='/low-accuracy'>morning-low accuracy</a> · "
            "<a href='/confidence'>confidence log</a></p>"
            f"<pre>{html_escape(summary)}</pre>"
            "<p class='footer'>Auto-refreshes every 30 s. "
            "Same content as <code>python3 scripts/health.py</code> on "
            "the cabin laptop — kept identical so CLI and web views "
            "never diverge.</p>"
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8",
                          body.encode())

    def _serve_report_index(self):
        """List every data/reports/*.md, newest first, with the live
        'today' entry pinned at top (re-rendered each request)."""
        from datetime import date as _date
        today = datetime.now().date()
        reports_dir = Path("data/reports")
        if reports_dir.exists():
            files = sorted(
                [p.stem for p in reports_dir.glob("*.md")
                 if len(p.stem) == 10],
                reverse=True,
            )
        else:
            files = []
        # Drop today from the historical list — we want it pinned at top
        # as the live link so even if the file is stale it gets regenerated.
        today_iso = today.isoformat()
        historical = [d for d in files if d != today_iso]

        lines = ["<ul>"]
        lines.append(
            f'<li><a class="today" href="/today-report">📊 {today_iso} '
            "(today, live)</a></li>"
        )
        for d in historical:
            lines.append(
                f'<li><a href="/report/{d}">{d}</a></li>'
            )
        if not historical:
            lines.append(
                '<li style="color:#8b949e;font-style:italic">'
                "(no past reports yet — they accumulate from tonight onward)"
                "</li>"
            )
        lines.append("</ul>")

        html = (
            "<!doctype html><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Day reports</title>"
            f"<style>{self.REPORT_PAGE_STYLE}</style>"
            "<p><a href='/'>&larr; dashboard</a></p>"
            "<h2 style='margin-top:0'>Day reports</h2>"
            "<p style='color:#8b949e;font-size:12px'>"
            "Generated by <code>scripts/end_of_day_report.py</code> at every "
            "autonomous-loop iteration. Each entry links to a Markdown "
            "summary of that day's pack data, solar harvest, weather, "
            "and SolarModel state."
            "</p>"
            + "".join(lines)
        )
        return self._send(HTTPStatus.OK, "text/html; charset=utf-8", html.encode())

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
