"""Snapshot of today's solar harvest progress vs forecast.

Drives the "today's harvest tracker" widget on the dashboard so the user
can see, throughout the day, how much solar we've harvested so far and
how that compares to the forecast for the whole day. Helpful answer
to "is the day going as expected, better, or worse?".

Inputs:
    data/pack.csv     — integrated for net charge (excluding generator)
    data/weather.csv  — latest forecast for today's full-day kWh/m²
    SolarModel        — converts forecast kWh/m² → expected Ah

Output (JSON via --json, otherwise pretty text):

    date                          today's ISO date
    samples                       pack samples seen today so far
    duration_h                    hours of data covered today
    solar_ah_so_far               charge_ah − generator_ah
    charge_ah                     total Ah into pack today (any source)
    generator_ah                  Ah delivered by generator today
    irradiance_kwh_m2_forecast    Open-Meteo's full-day forecast for today
    solar_ah_forecast             SolarModel.predict_ah(forecast)
    pct_of_forecast               solar_ah_so_far / solar_ah_forecast × 100
                                  (clamped [0, 200] so a runaway doesn't
                                   blow the UI)
    confidence                    pass-through from SolarModel
    note                          short human caveat ("partial day",
                                   "no forecast yet", etc.)

Usage:
    .venv/bin/python scripts/today_harvest.py            # pretty
    .venv/bin/python scripts/today_harvest.py --json     # for dashboard
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from volthium.solar_model import SolarModel  # noqa: E402


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def compute_today_peaks(pack_csv: Path, today: date) -> dict:
    """Walk today's pack.csv rows once and extract running-max stats.
    Drives the dashboard's "TODAY'S PEAKS" subrow. Cheap — single
    linear pass, no integration.

    Returns dict with:
        peak_charge_a       — max pack_i seen today (positive A)
        peak_smoothed_a     — max smoothed_i seen today
        peak_soc_pct        — max(soc_a, soc_b) across the day
        peak_pack_voltage_v — max pack voltage observed
        first_charge_time   — HH:MM of first sample where pack_i > +1A
                              (the "net charging started" marker)

    All values are None when no data is available yet for today.
    """
    peak_charge: Optional[float] = None
    peak_smoothed: Optional[float] = None
    peak_soc: Optional[float] = None
    peak_voltage: Optional[float] = None
    first_charge_time: Optional[str] = None

    try:
        with pack_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                pi = _f(r.get("pack_i"))
                si = _f(r.get("smoothed_i"))
                pv = _f(r.get("pack_v"))
                sa = _f(r.get("soc_a"))
                sb = _f(r.get("soc_b"))
                if pi is not None:
                    if peak_charge is None or pi > peak_charge:
                        peak_charge = pi
                    if first_charge_time is None and pi > 1.0:
                        first_charge_time = ts.strftime("%H:%M")
                if si is not None and (peak_smoothed is None or si > peak_smoothed):
                    peak_smoothed = si
                if pv is not None and (peak_voltage is None or pv > peak_voltage):
                    peak_voltage = pv
                if sa is not None:
                    if peak_soc is None or sa > peak_soc:
                        peak_soc = sa
                if sb is not None:
                    if peak_soc is None or sb > peak_soc:
                        peak_soc = sb
    except FileNotFoundError:
        pass

    return {
        "peak_charge_a":       round(peak_charge, 2) if peak_charge is not None else None,
        "peak_smoothed_a":     round(peak_smoothed, 2) if peak_smoothed is not None else None,
        "peak_soc_pct":        round(peak_soc, 1) if peak_soc is not None else None,
        "peak_pack_voltage_v": round(peak_voltage, 2) if peak_voltage is not None else None,
        "first_charge_time":   first_charge_time,
    }


def integrate_today(pack_csv: Path, today: date,
                    series_bin_minutes: int = 5) -> dict:
    """Walk pack.csv rows for `today` and integrate.

    Returns dict with: samples, duration_h, charge_ah, discharge_ah,
    generator_ah, solar_ah (= charge_ah − generator_ah), and a
    downsampled `series` of (minute_of_day, solar_ah_cumulative)
    points binned to `series_bin_minutes` (default 5 min ⇒ up to
    ~288 points per day, plenty for a sparkline).

    Mirrors `scripts/daily_summary.summarize_day` math but only for the
    given date. Trapezoidal integration of `pack_i` over time; samples
    > 60 s apart are treated as a gap and skipped. Generator threshold
    is +30 A on the average between two adjacent samples (matches the
    daily_summary + event-detector convention).
    """
    rows: list[dict] = []
    try:
        with pack_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                rows.append({"ts": ts, "pack_i": _f(r.get("pack_i"))})
    except FileNotFoundError:
        return {"samples": 0, "duration_h": 0.0, "charge_ah": 0.0,
                "discharge_ah": 0.0, "generator_ah": 0.0, "solar_ah": 0.0,
                "series": []}

    if not rows:
        return {"samples": 0, "duration_h": 0.0, "charge_ah": 0.0,
                "discharge_ah": 0.0, "generator_ah": 0.0, "solar_ah": 0.0,
                "series": []}

    rows.sort(key=lambda r: r["ts"])
    duration_h = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / 3600.0

    charge_ah = 0.0
    discharge_ah = 0.0
    generator_ah = 0.0

    # Downsampled cumulative-solar series. Emit at most one point per
    # `series_bin_minutes` window (keeps payload tiny). Solar_ah is
    # monotonically non-decreasing, so keeping the latest value per
    # bucket gives an honest sparkline.
    series: list[tuple[int, float]] = []
    last_bin = -1

    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["pack_i"] is None or b["pack_i"] is None:
            continue
        dt_s = (b["ts"] - a["ts"]).total_seconds()
        if dt_s <= 0 or dt_s > 60:
            continue
        avg_i = (a["pack_i"] + b["pack_i"]) / 2.0
        delta_ah = avg_i * dt_s / 3600.0
        if avg_i > 0:
            charge_ah += delta_ah
            if avg_i > 30:
                generator_ah += delta_ah
        else:
            discharge_ah += -delta_ah

        # Emit one (minute_of_day, solar_ah) per series_bin_minutes window.
        # b['ts'] is timezone-naive ISO from pack.csv — use clock minutes.
        minute_of_day = b["ts"].hour * 60 + b["ts"].minute
        bin_idx = minute_of_day // series_bin_minutes
        if bin_idx != last_bin:
            series.append((minute_of_day,
                           round(charge_ah - generator_ah, 3)))
            last_bin = bin_idx

    return {
        "samples": len(rows),
        "duration_h": round(duration_h, 2),
        "charge_ah": round(charge_ah, 2),
        "discharge_ah": round(discharge_ah, 2),
        "generator_ah": round(generator_ah, 2),
        "solar_ah": round(charge_ah - generator_ah, 2),
        "series": series,
    }


def latest_weather_forecast_kwh(weather_csv: Path, today: date) -> Optional[float]:
    """Return the most recent `shortwave_radiation_sum_today_wh_m2` for
    today from weather.csv, converted to kWh/m². Returns None if we
    have no row for today."""
    latest_kwh: Optional[float] = None
    try:
        with weather_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                v = _f(r.get("shortwave_radiation_sum_today_wh_m2"))
                if v is not None:
                    latest_kwh = v / 1000.0    # Wh/m² → kWh/m²
    except FileNotFoundError:
        return None
    return latest_kwh


def weather_forecast_history(weather_csv: Path, today: date) -> dict:
    """Open-Meteo's `shortwave_radiation_sum_today` is the model's
    forecast for the WHOLE day, refreshed every weather-logger tick
    (~30 min). It moves as the model ingests today's observations and
    refits — sometimes upward (today was conservative), sometimes
    downward (today was over-confident). Tracking the revision
    history is a forecast-confidence signal: a flat day-long line
    means Open-Meteo was sure; a 10 %+ swing means there was real
    uncertainty.

    Returns a dict with:
        first      — first kWh/m² value seen today (initial forecast)
        latest     — most recent kWh/m² (current forecast)
        min, max   — extremes seen today
        drift_pct  — (latest − first) / first × 100, signed
        n          — number of weather samples included

    All values are None / 0 when no data is available yet.
    """
    values: list[float] = []
    try:
        with weather_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                v = _f(r.get("shortwave_radiation_sum_today_wh_m2"))
                if v is not None:
                    values.append(v / 1000.0)
    except FileNotFoundError:
        return {"first": None, "latest": None, "min": None, "max": None,
                "drift_pct": None, "n": 0}

    if not values:
        return {"first": None, "latest": None, "min": None, "max": None,
                "drift_pct": None, "n": 0}

    first = values[0]
    latest = values[-1]
    drift = ((latest - first) / first * 100.0) if first > 0 else None
    return {
        "first":     round(first, 3),
        "latest":    round(latest, 3),
        "min":       round(min(values), 3),
        "max":       round(max(values), 3),
        "drift_pct": round(drift, 1) if drift is not None else None,
        "n":         len(values),
    }


def best_harvest_hour(series: list) -> tuple[Optional[int], Optional[float]]:
    """Given a 5-min-binned cumulative_solar_ah series (the same one
    the dashboard sparkline uses), find the (hour_of_day, ah_in_hour)
    pair that contributed the most Ah today.

    Walks the series, tracks the running cumulative_ah at each hour
    boundary (last seen value within that hour), and computes
    per-hour deltas: harvest in hour h = cumulative_at_end_of_h −
    cumulative_at_end_of_prior_h. Returns the hour with the biggest
    delta. Empty hours register as 0 and naturally lose.

    Mirrors the dashboard JS's per-hour bar logic so the two views
    agree on "best hour".
    """
    if not series or len(series) < 2:
        return (None, None)

    last_in_hour: dict[int, float] = {}
    for minute_of_day, ah in series:
        h = int(minute_of_day) // 60
        if 0 <= h < 24:
            last_in_hour[h] = ah

    # Carry-forward baseline so empty hours produce 0, not negative.
    baseline = 0.0
    best_h: Optional[int] = None
    best_ah: float = -1.0
    for h in range(24):
        if h in last_in_hour:
            delta = max(0.0, last_in_hour[h] - baseline)
            baseline = last_in_hour[h]
        else:
            delta = 0.0
        if delta > best_ah:
            best_ah = delta
            best_h = h

    if best_h is None or best_ah <= 0.0:
        return (None, None)
    return (best_h, round(best_ah, 2))


def latest_weather_sun_times(weather_csv: Path, today: date) -> tuple[Optional[int], Optional[int]]:
    """Pull today's sunrise/sunset times out of weather.csv and return
    them as minute-of-day integers, suitable for plotting on the
    sparkline's 0..1440 x-axis.

    Returns (sunrise_min, sunset_min). Either or both may be None if
    we don't have weather data yet or the columns are missing.
    """
    sunrise_min: Optional[int] = None
    sunset_min: Optional[int] = None
    try:
        with weather_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                # Latest-wins: weather.csv appends rows every 30 min
                sr = r.get("sunrise_iso")
                ss = r.get("sunset_iso")
                if sr:
                    try:
                        sr_dt = datetime.fromisoformat(sr)
                        sunrise_min = sr_dt.hour * 60 + sr_dt.minute
                    except Exception:
                        pass
                if ss:
                    try:
                        ss_dt = datetime.fromisoformat(ss)
                        sunset_min = ss_dt.hour * 60 + ss_dt.minute
                    except Exception:
                        pass
    except FileNotFoundError:
        return (None, None)
    return (sunrise_min, sunset_min)


def integrate_today_irradiance(weather_csv: Path, today: date,
                               now: Optional[datetime] = None,
                               max_extrap_seconds: float = 2400.0,
                               ) -> Optional[float]:
    """Integrate `shortwave_radiation_wm2` from today's weather samples
    to estimate the kWh/m² actually delivered SO FAR today.

    weather.csv has ~one row per 30 min. Each row reports the
    instantaneous shortwave_radiation in W/m². Trapezoidal integration
    in time, divided by 3600 s/h and 1000 W/kW, gives kWh/m².

    To avoid an artifact where the live ratio jumps between weather
    samples (denominator goes stale while harvest keeps growing), this
    extends the integral with a flat-extrapolation tail from the last
    weather sample to `now`, holding the most-recent wm2 constant.
    Capped at `max_extrap_seconds` (default 40 min — slightly longer
    than the 30-min weather cadence so a single missed sample doesn't
    silently stall the integral).

    Independent of Open-Meteo's `shortwave_radiation_sum_today` field
    (which is the forecast TOTAL for the day) — by integrating live
    samples ourselves we get a partial-day actual that can pair with
    the partial-day pack harvest to extract a real Ah/(kWh/m²)
    coefficient as the day progresses, instead of waiting for sunset.

    Returns None if we have <2 samples for today.
    """
    samples: list[tuple[datetime, float]] = []
    try:
        with weather_csv.open() as f:
            for r in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(r["ts"])
                except Exception:
                    continue
                if ts.date() != today:
                    continue
                v = _f(r.get("shortwave_radiation_wm2"))
                if v is not None:
                    samples.append((ts, v))
    except FileNotFoundError:
        return None

    if len(samples) < 2:
        return None

    samples.sort(key=lambda p: p[0])
    wh_m2 = 0.0   # accumulated Wh/m²
    for i in range(1, len(samples)):
        (t0, w0), (t1, w1) = samples[i - 1], samples[i]
        dt_h = (t1 - t0).total_seconds() / 3600.0
        if dt_h <= 0 or dt_h > 2.0:
            # gap larger than 2 h — treat as missing data, skip
            continue
        wh_m2 += (w0 + w1) / 2.0 * dt_h

    # Flat-extrapolation tail past the last weather sample: hold the
    # last-known wm2 constant up to now (or +max_extrap_seconds,
    # whichever is sooner). Removes the ratio-jump artifact at weather
    # sample boundaries.
    if now is None:
        now = datetime.now()
    last_ts, last_w = samples[-1]
    if now > last_ts:
        gap_s = (now - last_ts).total_seconds()
        capped_s = min(gap_s, max_extrap_seconds)
        wh_m2 += last_w * (capped_s / 3600.0)

    return wh_m2 / 1000.0    # Wh/m² → kWh/m²


def load_solar_model() -> SolarModel:
    """Same fit pipeline as generator_advisor — read daily_summary.csv
    if it exists, fall back to the constant default."""
    path = Path("data/daily_summary.csv")
    if not path.exists():
        return SolarModel.default()
    try:
        with path.open() as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return SolarModel.default()
    return SolarModel.fit_from_daily_summary(rows)


def snapshot(pack_csv: Path, weather_csv: Path, today: Optional[date] = None) -> dict:
    if today is None:
        today = datetime.now().date()

    integrated = integrate_today(pack_csv, today)
    forecast_kwh = latest_weather_forecast_kwh(weather_csv, today)
    actual_kwh_so_far = integrate_today_irradiance(weather_csv, today)
    sunrise_min, sunset_min = latest_weather_sun_times(weather_csv, today)
    forecast_hist = weather_forecast_history(weather_csv, today)
    peaks = compute_today_peaks(pack_csv, today)
    # Best-harvest-hour fold-in: peaks struct gains two more fields
    # derived from the 5-min series.
    best_h, best_h_ah = best_harvest_hour(integrated.get("series", []))
    peaks["best_harvest_hour"] = best_h
    peaks["best_harvest_hour_ah"] = best_h_ah
    model = load_solar_model()

    forecast_ah: Optional[float] = None
    if forecast_kwh is not None:
        forecast_ah = round(model.predict_ah(forecast_kwh), 2)

    pct: Optional[float] = None
    if forecast_ah is not None and forecast_ah > 0:
        pct = max(0.0, min(200.0, integrated["solar_ah"] / forecast_ah * 100.0))
        pct = round(pct, 1)

    # Live ratio: Ah harvested so far / kWh/m² delivered so far.
    # First useful real-time measurement of the SolarModel coefficient.
    # Threshold-guarded so noisy near-zero numerator/denominator early
    # in the day don't produce a wild reading.
    live_ratio: Optional[float] = None
    if (actual_kwh_so_far is not None and actual_kwh_so_far >= 0.5
            and integrated["solar_ah"] >= 1.0):
        live_ratio = round(integrated["solar_ah"] / actual_kwh_so_far, 2)

    note = None
    if integrated["samples"] == 0:
        note = "no pack data yet today"
    elif forecast_kwh is None:
        note = "no weather forecast yet today"
    elif integrated["solar_ah"] <= 0.0:
        note = "no solar harvest yet today"
    elif integrated["duration_h"] < 12.0:
        note = "partial day — still gathering"

    return {
        "date": today.isoformat(),
        "samples": integrated["samples"],
        "duration_h": integrated["duration_h"],
        "solar_ah_so_far": integrated["solar_ah"],
        "charge_ah": integrated["charge_ah"],
        "generator_ah": integrated["generator_ah"],
        "irradiance_kwh_m2_forecast": (
            round(forecast_kwh, 2) if forecast_kwh is not None else None
        ),
        "irradiance_kwh_m2_so_far": (
            round(actual_kwh_so_far, 3) if actual_kwh_so_far is not None else None
        ),
        "live_ratio_ah_per_kwh_m2": live_ratio,
        "solar_ah_forecast": forecast_ah,
        "pct_of_forecast": pct,
        "confidence": model.confidence,
        "note": note,
        # Sunrise / sunset minute-of-day, for sparkline marker overlays.
        # Either or both may be null if weather.csv doesn't yet have a
        # row with the iso columns.
        "sunrise_min_of_day": sunrise_min,
        "sunset_min_of_day": sunset_min,
        # Open-Meteo day-total forecast revision history (first vs latest,
        # min/max, signed drift %). High drift = forecast uncertainty.
        "forecast_history": forecast_hist,
        # Today's running-max stats — peak charge current, peak SOC,
        # peak voltage, and HH:MM of first net charging.
        "peaks": peaks,
        # 5-min binned cumulative solar Ah series:
        # [[minute_of_day, ah], ...]. Sparkline source on the dashboard.
        "series": integrated.get("series", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-csv", type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--weather-csv", type=Path, default=Path("data/weather.csv"))
    ap.add_argument("--json", action="store_true",
                    help="emit JSON suitable for the dashboard widget")
    args = ap.parse_args()

    snap = snapshot(args.pack_csv, args.weather_csv)

    if args.json:
        print(json.dumps(snap, indent=2))
        return 0

    print(f"=== today's harvest ({snap['date']}) ===")
    print(f"  pack samples:     {snap['samples']}")
    print(f"  duration so far:  {snap['duration_h']} h")
    sa = snap["solar_ah_so_far"]
    print(f"  solar Ah so far:  {sa:+.1f} Ah  "
          f"(charge {snap['charge_ah']:+.1f}, generator {snap['generator_ah']:+.1f})")
    if snap["irradiance_kwh_m2_forecast"] is not None:
        print(f"  forecast kWh/m²:  {snap['irradiance_kwh_m2_forecast']:.2f}")
        print(f"  forecast solar:   {snap['solar_ah_forecast']:.1f} Ah  "
              f"(via SolarModel, {snap['confidence']} confidence)")
        if snap["pct_of_forecast"] is not None:
            print(f"  progress:         {snap['pct_of_forecast']:.0f}% of forecast")
    else:
        print(f"  forecast kWh/m²:  (no weather data yet)")
    if snap["irradiance_kwh_m2_so_far"] is not None:
        print(f"  actual kWh/m² so far:  {snap['irradiance_kwh_m2_so_far']:.3f}")
        if snap["live_ratio_ah_per_kwh_m2"] is not None:
            print(f"  live ratio so far:     "
                  f"{snap['live_ratio_ah_per_kwh_m2']:.2f} Ah/(kWh/m²)")
    if snap["note"]:
        print(f"  note: {snap['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
