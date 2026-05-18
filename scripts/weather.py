"""Fetch current conditions + short-range forecast for the cabin site.

Uses Open-Meteo's free API (no key required). Writes to data/weather.csv
in a schema compatible with the pack.csv columns (matching `ts`
timestamps) so the two can be joined later for correlation analysis.

Usage:
    # one-shot — fetch current + forecast, print and append to CSV
    .venv/bin/python scripts/weather.py

    # loop mode — every 30 min
    .venv/bin/python scripts/weather.py --loop --interval 1800

Open-Meteo returns:
    - current conditions: temp, cloud cover, shortwave radiation (W/m²)
    - hourly forecast: same fields, 24h ahead
    - daily: sunrise/sunset, max solar radiation, total radiation Wh/m²

The shortwave-radiation column is the most useful: it's the actual
ground-level irradiance W/m², which (multiplied by panel area × DC
efficiency × MPPT efficiency) gives expected pack current. Once we have
a few days of (shortwave_radiation × time) integrated alongside actual
Ah delivered, we can fit our system's effective W/m² → Ah/h coefficient
and start predicting.

Cabin / panel parameters live in docs/site/loon_lake.md. The defaults
here can be overridden via CLI flags.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
import ssl
import urllib.error
import urllib.parse
import urllib.request

# macOS Python.org doesn't include root certs by default. Use certifi if
# available; fall back to the system default.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Default site — Loon Lake near Clinton/Cache Creek, BC. Confirm in
# docs/site/loon_lake.md.
DEFAULT_LAT = 51.07
DEFAULT_LON = -121.20
DEFAULT_TZ = "America/Vancouver"
API_BASE = "https://api.open-meteo.com/v1/forecast"

CSV_FIELDS = [
    "ts",                       # local-ish timestamp; matches pack.csv format
    "lat", "lon",
    "temperature_c",            # current air temp
    "cloud_cover_pct",          # 0..100
    "shortwave_radiation_wm2",  # current ground-level irradiance
    "wind_speed_ms",
    "wind_gusts_ms",
    "weather_code",             # WMO code; 0=clear, 1-3=partly, 45/48=fog, 51-67=rain, 71-77=snow
    "is_day",                   # 0/1
    "sunrise_iso",              # today's sunrise (next-day's after sunset)
    "sunset_iso",               # today's sunset
    "shortwave_radiation_sum_today_wh_m2",   # cumulative day-total irradiance
    "uv_index_max_today",
]


def fetch(lat: float, lon: float, tz: str, timeout: float = 10.0,
          forecast_days: int = 2) -> dict:
    """One HTTPS GET; returns parsed JSON. Raises on network/parse failure.

    forecast_days=2 gets today + tomorrow in the daily arrays — used by
    the generator advisor to plan against tomorrow's expected irradiance
    rather than treating today's number as a proxy.
    """
    params = {
        "latitude":  lat,
        "longitude": lon,
        "timezone":  tz,
        "current":   ",".join((
            "temperature_2m",
            "cloud_cover",
            "shortwave_radiation",
            "wind_speed_10m",
            "wind_gusts_10m",
            "weather_code",
            "is_day",
        )),
        "daily":     ",".join((
            "sunrise",
            "sunset",
            "shortwave_radiation_sum",
            "uv_index_max",
        )),
        "wind_speed_unit": "ms",
        "forecast_days":   forecast_days,
    }
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "volthium-reader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def fetch_today_tomorrow_irradiance(
    lat: float = DEFAULT_LAT,
    lon: float = DEFAULT_LON,
    tz: str = DEFAULT_TZ,
) -> tuple[Optional[float], Optional[float]]:
    """Return (today_kwh_per_m2, tomorrow_kwh_per_m2). None on either
    if Open-Meteo didn't supply that day. Wraps fetch() for callers
    (like the generator advisor) that don't need the full payload."""
    try:
        data = fetch(lat, lon, tz, forecast_days=2)
    except Exception:
        return None, None
    dly = data.get("daily") or {}
    rad = dly.get("shortwave_radiation_sum") or []
    # MJ/m² → kWh/m² (1 MJ ≈ 277.78 Wh, /1000 → kWh)
    def conv(x):
        return x * 277.778 / 1000.0 if x is not None else None
    today    = conv(rad[0]) if len(rad) > 0 else None
    tomorrow = conv(rad[1]) if len(rad) > 1 else None
    return today, tomorrow


def flatten(data: dict, lat: float, lon: float) -> dict:
    """Normalize the open-meteo response into a single CSV row.

    Note on units: Open-Meteo defaults to MJ/m² for the daily-sum field;
    we convert to Wh/m² for intuition (1 MJ = 277.78 Wh). The
    instantaneous `shortwave_radiation` is already W/m².
    """
    cur = data.get("current") or {}
    dly = data.get("daily") or {}
    rad_sum_mj = (dly.get("shortwave_radiation_sum") or [None])[0]
    rad_sum_wh = rad_sum_mj * 277.7778 if rad_sum_mj is not None else None

    row = {
        "ts":  datetime.now().isoformat(timespec="seconds"),
        "lat": lat, "lon": lon,
        "temperature_c":             cur.get("temperature_2m"),
        "cloud_cover_pct":           cur.get("cloud_cover"),
        "shortwave_radiation_wm2":   cur.get("shortwave_radiation"),
        "wind_speed_ms":             cur.get("wind_speed_10m"),
        "wind_gusts_ms":             cur.get("wind_gusts_10m"),
        "weather_code":              cur.get("weather_code"),
        "is_day":                    cur.get("is_day"),
        "sunrise_iso":               (dly.get("sunrise") or [None])[0],
        "sunset_iso":                (dly.get("sunset") or [None])[0],
        "shortwave_radiation_sum_today_wh_m2": round(rad_sum_wh, 1) if rad_sum_wh is not None else None,
        "uv_index_max_today":        (dly.get("uv_index_max") or [None])[0],
    }
    return row


def append_csv(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def fetch_once(lat: float, lon: float, tz: str, csv_path: Optional[Path]) -> int:
    try:
        data = fetch(lat, lon, tz)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[weather] fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    row = flatten(data, lat, lon)
    print(f"[weather] {row['ts']}  "
          f"T={row['temperature_c']}°C  "
          f"cloud={row['cloud_cover_pct']}%  "
          f"irr={row['shortwave_radiation_wm2']}W/m²  "
          f"day_total={row['shortwave_radiation_sum_today_wh_m2']}Wh/m²  "
          f"WMO={row['weather_code']}")
    if csv_path is not None:
        append_csv(csv_path, row)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat",  type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon",  type=float, default=DEFAULT_LON)
    ap.add_argument("--tz",   default=DEFAULT_TZ)
    ap.add_argument("--csv",  type=Path, default=Path("data/weather.csv"))
    ap.add_argument("--loop", action="store_true", help="poll forever")
    ap.add_argument("--interval", type=float, default=1800.0,
                    help="seconds between polls in --loop mode")
    args = ap.parse_args()
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    if not args.loop:
        return fetch_once(args.lat, args.lon, args.tz, args.csv)

    print(f"[weather] looping every {args.interval:.0f}s")
    while True:
        fetch_once(args.lat, args.lon, args.tz, args.csv)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
