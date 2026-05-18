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
from volthium.events import detect_events  # noqa: E402

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
HISTORY_N = 720   # samples to keep in the rolling window for sparkline (≈ 2h @ 10s)

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
  .panel { background: var(--panel); border-radius: 10px; padding: 22px; }
  .headline { font-size: 64px; font-weight: 700; line-height: 1; margin: 4px 0 6px; }
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
      <div class="label" id="state-label">state</div>
      <div class="headline num"><span id="state-value">…</span></div>
      <div class="label">time to <span id="target">—</span></div>
      <div class="headline num" id="time-value">—</div>
      <div class="soc-bar"><div id="soc-fill" style="width: 0%"></div></div>
      <div class="row">
        <div class="stat"><div class="label">soc</div><div class="v num"><span id="soc">—</span><span class="u">%</span></div></div>
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
    setText("state-value", (x.state || "—").toUpperCase());
    document.getElementById("state-value").className = stateClass(x.state);
    if (x.state === "charging") {
      setText("target", "full (95%)");
      setText("time-value", fmtMin(x.minutes_remaining));
    } else if (x.state === "discharging") {
      setText("target", "10%");
      setText("time-value", fmtMin(x.minutes_remaining));
    } else if (x.state === "full") {
      setText("target", "—");
      setText("time-value", "FULL");
    } else {
      setText("target", "—");
      setText("time-value", "—");
    }
    setText("soc", x.soc_a != null && x.soc_b != null ? Math.round((x.soc_a + x.soc_b) / 2) : "—");
    const soc = (x.soc_a != null && x.soc_b != null) ? (x.soc_a + x.soc_b) / 2 : 0;
    document.getElementById("soc-fill").style.width = soc + "%";
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
            return self._send(HTTPStatus.OK, "application/json",
                              json.dumps({
                                  "latest": history[-1],
                                  "history": history,
                                  "events": events[-20:],  # last 20 only, keep payload small
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
    global CSV_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("data/pack.csv"))
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
