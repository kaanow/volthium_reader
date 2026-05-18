"""Per-day rollup: one row per calendar day with the metrics the
solar model will eventually fit against.

For each day in pack.csv (and the matching day in weather.csv):

    duration_h              — how many hours of data we covered
    samples                 — n
    soc_min / soc_max       — pack SOC extremes (avg of A & B)
    soc_start / soc_end     — at first/last sample within the day
    charge_ah               — integral of pack_current where >0
    discharge_ah            — integral of pack_current where <0 (abs)
    net_ah                  — charge_ah - discharge_ah
    generator_minutes       — minutes where pack_i > +30 A
    generator_ah            — Ah delivered during those minutes
    solar_ah_estimated      — charge_ah minus generator_ah (the rest)
    weather_kwh_m2          — total ground irradiance, kWh/m²
    weather_cloud_pct_avg   — mean cloud cover
    weather_temp_c_min/max  — daily air-temp range

Writes data/daily_summary.csv (one row per day, append-only if a row
for that date already exists it's overwritten — re-run nightly).

Critical input for the solar model fit:
    (weather_kwh_m2, solar_ah_estimated) pairs across many days
    → linear regression → coefficient for production solar predictor

Usage:
    .venv/bin/python scripts/daily_summary.py
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, fields, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class DailyRow:
    date: str
    duration_h: float
    samples: int
    soc_min: float
    soc_max: float
    soc_start: float
    soc_end: float
    charge_ah: float
    discharge_ah: float
    net_ah: float
    generator_minutes: float
    generator_ah: float
    solar_ah_estimated: float
    weather_kwh_m2: Optional[float]
    weather_cloud_pct_avg: Optional[float]
    weather_temp_c_min: Optional[float]
    weather_temp_c_max: Optional[float]
    # True if this row does NOT cover the full solar day. Bug-fix from
    # 2026-05-18 12:02 loop: the old `duration_h > 12` complete-day
    # heuristic tripped at NOON for a midnight-start logger because
    # duration_h is just (last_ts − first_ts), not "data spans the whole
    # solar day". A midnight-to-noon row got included in the SolarModel
    # fit and produced a bogus 3.1 Ah/(kWh/m²) coefficient against the
    # full-day FORECAST irradiance. New rule: complete = duration_h >= 20
    # (must cover past ~21:00, post-sunset at this site/season).
    partial: bool = True


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_pack(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            rows.append({
                "ts": ts,
                "date": ts.date().isoformat(),
                "pack_i": _f(r.get("pack_i")),
                "soc_a": _f(r.get("soc_a")),
                "soc_b": _f(r.get("soc_b")),
            })
    return rows


def load_weather(path: Path) -> dict[str, list[dict]]:
    """Returns {date_iso: [rows]} grouped from weather.csv."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        return by_date
    with path.open() as f:
        for r in csv.DictReader(f):
            try:
                ts = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            by_date[ts.date().isoformat()].append({
                "ts": ts,
                "cloud_pct": _f(r.get("cloud_cover_pct")),
                "temp_c": _f(r.get("temperature_c")),
                "kwh_m2_today": _f(r.get("shortwave_radiation_sum_today_wh_m2")),
            })
    return by_date


def summarize_day(rows: list[dict], weather_rows: list[dict]) -> Optional[DailyRow]:
    """Roll up one day's worth of pack rows (already filtered to that
    date) plus the matching weather rows."""
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["ts"])
    duration_s = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds()
    duration_h = duration_s / 3600.0

    socs = []
    for r in rows:
        if r["soc_a"] is not None and r["soc_b"] is not None:
            socs.append((r["soc_a"] + r["soc_b"]) / 2.0)
    if not socs:
        return None

    # Trapezoidal integration of pack_current over time
    charge_ah = 0.0
    discharge_ah = 0.0
    generator_minutes = 0.0
    generator_ah = 0.0
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["pack_i"] is None or b["pack_i"] is None:
            continue
        dt_s = (b["ts"] - a["ts"]).total_seconds()
        if dt_s <= 0 or dt_s > 60:
            continue   # gap; skip
        avg_i = (a["pack_i"] + b["pack_i"]) / 2
        delta_ah = avg_i * dt_s / 3600
        if avg_i > 0:
            charge_ah += delta_ah
        else:
            discharge_ah += -delta_ah
        # Generator threshold: > +30 A
        if avg_i > 30:
            generator_minutes += dt_s / 60.0
            generator_ah += delta_ah

    solar_ah_estimated = charge_ah - generator_ah

    weather_kwh = None
    weather_cloud_avg = None
    weather_t_min = None
    weather_t_max = None
    if weather_rows:
        # Use the LAST irradiance-sum reading of the day (it accumulates).
        sums = [w["kwh_m2_today"] for w in weather_rows if w["kwh_m2_today"] is not None]
        if sums:
            weather_kwh = max(sums) / 1000.0     # Wh/m² → kWh/m²
        clouds = [w["cloud_pct"] for w in weather_rows if w["cloud_pct"] is not None]
        if clouds:
            weather_cloud_avg = statistics.mean(clouds)
        temps = [w["temp_c"] for w in weather_rows if w["temp_c"] is not None]
        if temps:
            weather_t_min = min(temps)
            weather_t_max = max(temps)

    return DailyRow(
        date=rows[0]["date"],
        duration_h=round(duration_h, 2),
        samples=len(rows),
        soc_min=round(min(socs), 1),
        soc_max=round(max(socs), 1),
        soc_start=round(socs[0], 1),
        soc_end=round(socs[-1], 1),
        charge_ah=round(charge_ah, 1),
        discharge_ah=round(discharge_ah, 1),
        net_ah=round(charge_ah - discharge_ah, 1),
        generator_minutes=round(generator_minutes, 1),
        generator_ah=round(generator_ah, 1),
        solar_ah_estimated=round(solar_ah_estimated, 1),
        weather_kwh_m2=round(weather_kwh, 2) if weather_kwh is not None else None,
        weather_cloud_pct_avg=round(weather_cloud_avg, 1) if weather_cloud_avg is not None else None,
        weather_temp_c_min=round(weather_t_min, 1) if weather_t_min is not None else None,
        weather_temp_c_max=round(weather_t_max, 1) if weather_t_max is not None else None,
        partial=(duration_h < 20.0),
    )


def write_csv(path: Path, rows: list[DailyRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_names = [f.name for f in fields(DailyRow)]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=field_names)
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-csv",    type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--weather-csv", type=Path, default=Path("data/weather.csv"))
    ap.add_argument("--out",         type=Path, default=Path("data/daily_summary.csv"))
    args = ap.parse_args()

    pack = load_pack(args.pack_csv)
    weather = load_weather(args.weather_csv)
    if not pack:
        print("no pack data.", file=sys.stderr)
        return 1

    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in pack:
        by_date[r["date"]].append(r)

    daily_rows: list[DailyRow] = []
    for date in sorted(by_date.keys()):
        s = summarize_day(by_date[date], weather.get(date, []))
        if s is not None:
            daily_rows.append(s)

    if not daily_rows:
        print("no day with usable data.", file=sys.stderr)
        return 1

    # Pretty print
    print()
    print("=== daily summary ===")
    for r in daily_rows:
        tag = " [partial]" if r.partial else ""
        print(f"\n{r.date}{tag}  ({r.samples} samples over {r.duration_h:.1f} h)")
        print(f"  SOC:        {r.soc_start:.0f} → {r.soc_end:.0f} %   "
              f"(range {r.soc_min:.0f}–{r.soc_max:.0f} %)")
        print(f"  charge:     +{r.charge_ah:.1f} Ah  (generator {r.generator_minutes:.0f} min ⇒ "
              f"{r.generator_ah:.1f} Ah; solar ≈ {r.solar_ah_estimated:.1f} Ah)")
        print(f"  discharge:  -{r.discharge_ah:.1f} Ah   net: {r.net_ah:+.1f} Ah")
        if r.weather_kwh_m2 is not None:
            print(f"  weather:    {r.weather_kwh_m2:.2f} kWh/m²", end="")
            if r.weather_cloud_pct_avg is not None:
                print(f"   cloud avg {r.weather_cloud_pct_avg:.0f} %", end="")
            if r.weather_temp_c_min is not None and r.weather_temp_c_max is not None:
                print(f"   temp {r.weather_temp_c_min:.1f}–{r.weather_temp_c_max:.1f} °C", end="")
            print()
        else:
            print(f"  weather:    (no data yet)")

    # Fit feedstock summary — how many usable (kwh, solar_ah) pairs?
    # A row is "complete" when it covers the full solar day (see the
    # DailyRow.partial docstring for why duration_h > 12 was wrong).
    fittable = [r for r in daily_rows
                if r.weather_kwh_m2 is not None and r.solar_ah_estimated > 0
                and not r.partial]
    print(f"\nrows usable for solar-model fit: {len(fittable)}")
    if fittable:
        for r in fittable:
            ratio = r.solar_ah_estimated / r.weather_kwh_m2 if r.weather_kwh_m2 > 0 else 0
            print(f"  {r.date}: {r.solar_ah_estimated:.1f} Ah / {r.weather_kwh_m2:.2f} kWh/m² "
                  f"= {ratio:.1f} Ah/(kWh/m²)")
    else:
        print("  (need at least one full-day row with weather + solar charge to fit)")

    write_csv(args.out, daily_rows)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
