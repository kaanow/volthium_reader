"""First-pass generator-use recommender.

Combines:
    - current pack state          (data/pack.csv tail)
    - hour-of-day discharge model (discharge_model.fit)
    - weather forecast            (data/weather.csv tail)
    - solar harvest stub          (irradiance Wh/m² × naive coefficient
                                   until we have a fitted model)
    - generator characteristics   (~55 A average, from observed
                                   generator run earlier today)

Produces a structured Recommendation:
    run_generator: bool
    reason:        str        — human-readable explanation
    when:          ISO ts     — earliest sensible start (None if not needed)
    duration_h:    float      — hours to run (None if not needed)
    projected_low: %          — pack's projected low SOC over next 24h
    confidence:    str        — "high" / "medium" / "low" (currently always low —
                                we have less than a day of data)

This is intentionally rough. See `docs/generator_advisor/README.md` for
the architecture. The recommendation tightens as the solar model fits
on real harvest-vs-irradiance data and as the discharge model picks up
seasonal patterns.

Usage:
    .venv/bin/python scripts/generator_advisor.py
    .venv/bin/python scripts/generator_advisor.py --comfort-floor 25 --json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csv as _csv
import discharge_model  # noqa: E402
from volthium.solar_model import SolarModel  # noqa: E402


# Empirical constants from `docs/hardware/bms_calibration.md` + observed runs.
PACK_CAPACITY_AH_PER_BATTERY = 215.0
GENERATOR_RATE_AH_PER_HOUR   = 55.0     # observed ~+55 A average → 55 Ah/h


def load_solar_model() -> SolarModel:
    """Try to fit the solar model from data/daily_summary.csv; fall
    back to the default constant if there's not enough data yet."""
    path = Path("data/daily_summary.csv")
    if not path.exists():
        return SolarModel.default()
    try:
        with path.open() as f:
            rows = list(_csv.DictReader(f))
    except Exception:
        return SolarModel.default()
    return SolarModel.fit_from_daily_summary(rows)


@dataclass
class Recommendation:
    run_generator: bool
    reason: str
    when_iso: Optional[str]
    duration_h: Optional[float]
    projected_low_soc: float
    projected_sunrise_soc: float
    projected_tomorrow_evening_soc: float
    confidence: str
    inputs: dict
    # Morning-watch advisory: True when we're approaching sunrise with
    # less SOC margin than feels comfortable, but not bad enough to
    # demand a generator run. UI should surface this as "consider
    # running generator soon" without sounding an alarm.
    morning_watch: bool = False
    morning_watch_reason: Optional[str] = None


def latest_csv_row(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    header = None
    last = None
    with path.open() as f:
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


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def project_solar_ah(weather_row: dict, model: SolarModel) -> float:
    """Predict Ah delivered to the pack tomorrow given today's
    irradiance total + a SolarModel. Today's irradiance is used as a
    proxy for tomorrow's — a real implementation would query the
    forecast for *tomorrow* specifically. Open-Meteo can do this; the
    weather logger just isn't recording forecast-day rows yet."""
    today_total = _f(weather_row.get("shortwave_radiation_sum_today_wh_m2"))
    if today_total is None:
        return 0.0
    kwh_per_m2 = today_total / 1000.0
    return model.predict_ah(kwh_per_m2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-csv",    type=Path, default=Path("data/pack.csv"))
    ap.add_argument("--weather-csv", type=Path, default=Path("data/weather.csv"))
    ap.add_argument("--comfort-floor", type=float, default=25.0,
                    help="don't let projected SOC drop below this percent")
    ap.add_argument("--json", action="store_true", help="output machine-readable JSON only")
    args = ap.parse_args()

    pack_now = latest_csv_row(args.pack_csv)
    weather_now = latest_csv_row(args.weather_csv) or {}
    if pack_now is None:
        print("no pack data yet.", file=sys.stderr)
        return 1

    soc_a = _f(pack_now.get("soc_a"))
    soc_b = _f(pack_now.get("soc_b"))
    if soc_a is None or soc_b is None:
        print("pack SOC missing.", file=sys.stderr)
        return 1
    start_soc = min(soc_a, soc_b)   # conservative: limiting battery

    # Fit the discharge model from history.
    samples = discharge_model.load(args.pack_csv)
    profile = discharge_model.fit(samples)

    now = datetime.now()
    sunrise_iso = weather_now.get("sunrise_iso")
    sunset_iso  = weather_now.get("sunset_iso")
    if not sunrise_iso or not sunset_iso:
        print("no sunrise/sunset in weather data.", file=sys.stderr)
        return 1
    try:
        sunrise_dt = datetime.fromisoformat(sunrise_iso)
        sunset_dt  = datetime.fromisoformat(sunset_iso)
    except ValueError:
        print("malformed sunrise/sunset.", file=sys.stderr)
        return 1
    if sunrise_dt < now:
        sunrise_dt += timedelta(days=1)
    if sunset_dt < now:
        sunset_dt += timedelta(days=1)

    # === Discharge from now to sunrise ===
    overnight_ah = discharge_model.project_overnight_ah(profile, now.hour, sunrise_dt.hour) or 0.0
    sunrise_pct_drop = overnight_ah / PACK_CAPACITY_AH_PER_BATTERY * 100.0
    projected_sunrise_soc = start_soc - sunrise_pct_drop

    # === Solar harvest tomorrow ===
    solar = load_solar_model()
    solar_ah = project_solar_ah(weather_now, solar)
    solar_pct_gain = solar_ah / PACK_CAPACITY_AH_PER_BATTERY * 100.0

    # === Discharge sunrise → tomorrow evening (rough; same profile) ===
    # We'll re-traverse hours from sunrise to ~sunset of the same day.
    next_eve_ah = discharge_model.project_overnight_ah(profile, sunrise_dt.hour, sunset_dt.hour) or 0.0
    next_eve_pct = next_eve_ah / PACK_CAPACITY_AH_PER_BATTERY * 100.0

    # Forward simulation, naive:
    #   sunrise:           start_soc − overnight_pct_drop
    #   daytime peak:      + solar_gain − daytime_discharge
    #   tomorrow evening:  daytime_peak − ~3-4 more hours of normal load
    projected_tomorrow_evening_soc = (
        projected_sunrise_soc + solar_pct_gain - next_eve_pct
    )
    projected_low = min(projected_sunrise_soc, projected_tomorrow_evening_soc)

    # === Morning watch ===
    # If we're approaching sunrise (within 60 min) and projected_low is
    # less comfortable than we'd like, surface a soft advisory even
    # when not enough to trigger a hard "run generator" recommendation.
    minutes_to_sunrise = (sunrise_dt - now).total_seconds() / 60.0
    morning_watch = (
        0.0 < minutes_to_sunrise <= 60.0
        and projected_low < 50.0
        and projected_low >= args.comfort_floor    # only soft warning above floor
    )
    morning_watch_reason = None
    if morning_watch:
        morning_watch_reason = (
            f"Approaching sunrise with projected low SOC at {projected_low:.0f} %. "
            f"Still above the {args.comfort_floor:.0f} % floor, but tighter than "
            f"comfortable — consider running the generator soon if today's "
            f"forecast doesn't promise a strong harvest."
        )

    # The solar model's confidence is the advisor's overall confidence
    # ceiling. As days accumulate it shifts low → medium → high.
    # discharge_model confidence isn't tracked yet; for now the advisor
    # inherits the solar model's label.
    overall_confidence = solar.confidence

    # === Decide ===
    if projected_low >= args.comfort_floor:
        rec = Recommendation(
            run_generator=False,
            reason=(
                f"No action needed. Projected low {projected_low:.0f} % "
                f"stays above the {args.comfort_floor:.0f} % comfort floor "
                f"(overnight: {projected_sunrise_soc:.0f} %, tomorrow eve: "
                f"{projected_tomorrow_evening_soc:.0f} %)."
            ),
            when_iso=None, duration_h=None,
            projected_low_soc=projected_low,
            projected_sunrise_soc=projected_sunrise_soc,
            projected_tomorrow_evening_soc=projected_tomorrow_evening_soc,
            confidence=overall_confidence,
            inputs={
                "start_soc_pct": start_soc,
                "overnight_ah": overnight_ah,
                "solar_ah_estimate": solar_ah,
                "next_eve_ah": next_eve_ah,
                "today_irradiance_kwh_m2":
                    _f(weather_now.get("shortwave_radiation_sum_today_wh_m2")) and
                    _f(weather_now.get("shortwave_radiation_sum_today_wh_m2")) / 1000.0,
            },
            morning_watch=morning_watch,
            morning_watch_reason=morning_watch_reason,
        )
    else:
        deficit_pct = args.comfort_floor - projected_low
        deficit_ah = deficit_pct / 100.0 * PACK_CAPACITY_AH_PER_BATTERY
        duration_h = deficit_ah / GENERATOR_RATE_AH_PER_HOUR
        # Recommend running in the morning before sun, around 1h before
        # sunrise — pack is at its lowest, we want to bridge to harvest.
        when = sunrise_dt - timedelta(hours=1)
        if when < now:
            when = now
        rec = Recommendation(
            run_generator=True,
            reason=(
                f"Pack would dip to {projected_low:.0f} %, below the "
                f"{args.comfort_floor:.0f} % comfort floor. "
                f"Run generator for {duration_h:.1f} h to top up by "
                f"{deficit_ah:.0f} Ah."
            ),
            when_iso=when.isoformat(timespec="minutes"),
            duration_h=duration_h,
            projected_low_soc=projected_low,
            projected_sunrise_soc=projected_sunrise_soc,
            projected_tomorrow_evening_soc=projected_tomorrow_evening_soc,
            confidence=overall_confidence,
            inputs={
                "start_soc_pct": start_soc,
                "overnight_ah": overnight_ah,
                "solar_ah_estimate": solar_ah,
                "next_eve_ah": next_eve_ah,
            },
            morning_watch=False,    # subsumed by the hard recommendation
        )

    if args.json:
        print(json.dumps(asdict(rec), indent=2))
        return 0

    # Pretty printable
    print()
    print(f"=== generator recommendation ({datetime.now():%Y-%m-%d %H:%M}) ===")
    if rec.run_generator:
        print(f"  ▶ RUN GENERATOR for {rec.duration_h:.1f} h starting ~ {rec.when_iso}")
    elif rec.morning_watch:
        print(f"  ⚠ MORNING WATCH — soft advisory")
    else:
        print(f"  ✓ no generator needed")
    print(f"\n  reason: {rec.reason}")
    if rec.morning_watch_reason:
        print(f"  morning watch: {rec.morning_watch_reason}")
    print(f"\n  inputs:")
    for k, v in rec.inputs.items():
        if v is None:
            print(f"    {k:<30s}  —")
        elif isinstance(v, float):
            print(f"    {k:<30s}  {v:.2f}")
        else:
            print(f"    {k:<30s}  {v}")
    print(f"\n  projection:")
    print(f"    sunrise SOC:               {rec.projected_sunrise_soc:.1f} %")
    print(f"    tomorrow evening SOC:      {rec.projected_tomorrow_evening_soc:.1f} %")
    print(f"    next-24h low SOC:          {rec.projected_low_soc:.1f} %")
    print(f"\n  confidence: {rec.confidence}")
    print(f"    (only ~1 day of data; solar model is still a stub — see")
    print(f"    docs/generator_advisor/README.md for the path to higher confidence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
