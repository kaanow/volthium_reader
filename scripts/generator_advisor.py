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
import math
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csv as _csv
import statistics
import discharge_model  # noqa: E402
import weather as weather_mod  # noqa: E402
import today_harvest as today_harvest_mod  # noqa: E402
import calibration_log as calibration_log_mod  # noqa: E402
import projection_log as projection_log_mod  # noqa: E402
import projection_accuracy as projection_accuracy_mod  # noqa: E402
import confidence_log as confidence_log_mod  # noqa: E402
from volthium.solar_model import SolarModel  # noqa: E402

# Cache tomorrow's forecast so re-runs in a 5-min window don't pound the API.
_TOMORROW_KWH_CACHE = {"computed_at": 0.0, "value": None}


# Empirical constants from `docs/hardware/bms_calibration.md` + observed runs.
PACK_CAPACITY_AH_PER_BATTERY = 215.0
GENERATOR_RATE_AH_PER_HOUR   = 55.0     # observed ~+55 A average → 55 Ah/h

# Accuracy-aware confidence:
#   If the last `ACCURACY_LIFT_WINDOW` validated projection_accuracy
#   records have mean |error| below `ACCURACY_LIFT_THRESHOLD_PP`, lift
#   the overall confidence one tier (low → medium, medium → high).
#   `ACCURACY_LIFT_MIN_RECORDS` guards against lifting on a tiny sample.
#
# Threshold of 2.0 pp is the bar requested in the design candidates
# list: "accuracy-aware confidence (lift confidence one tier if recent
# abs error < 2 pp)". Window of 10 keeps the signal recent — old
# records from before a SolarModel re-fit shouldn't dominate.
ACCURACY_LIFT_WINDOW          = 10
ACCURACY_LIFT_THRESHOLD_PP    = 2.0
ACCURACY_LIFT_MIN_RECORDS     = 5


# Confidence tier ordering used by the accuracy-aware lift logic.
_CONFIDENCE_TIERS = ["low", "medium", "high"]


def lift_confidence_by_accuracy(
    base: str,
    recent_abs_error_pp: Optional[float],
    recent_n: int,
    threshold_pp: float = ACCURACY_LIFT_THRESHOLD_PP,
    min_records: int = ACCURACY_LIFT_MIN_RECORDS,
) -> tuple[str, bool]:
    """Return (lifted_confidence, was_lifted).

    Lifts `base` one tier (max "high") when the recent track record
    has at least `min_records` validated entries AND mean |error|
    below `threshold_pp`. Otherwise returns `base` unchanged.

    Pure function so it can be unit-tested without going through the
    full advisor invocation.
    """
    if recent_abs_error_pp is None or recent_n < min_records:
        return base, False
    if recent_abs_error_pp >= threshold_pp:
        return base, False
    try:
        idx = _CONFIDENCE_TIERS.index(base)
    except ValueError:
        return base, False
    if idx >= len(_CONFIDENCE_TIERS) - 1:
        return base, False    # already at "high"
    return _CONFIDENCE_TIERS[idx + 1], True


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


def _get_tomorrow_kwh_per_m2() -> Optional[float]:
    """Cached forecast lookup. 5-minute TTL is fine — weather doesn't
    change that fast and we'd rather miss the latest update than make
    the cabin's Starlink earn its keep on every refresh."""
    import time as _time
    now = _time.monotonic()
    if (now - _TOMORROW_KWH_CACHE["computed_at"]) < 300.0:
        return _TOMORROW_KWH_CACHE["value"]
    _, tomorrow = weather_mod.fetch_today_tomorrow_irradiance()
    _TOMORROW_KWH_CACHE["computed_at"] = now
    _TOMORROW_KWH_CACHE["value"] = tomorrow
    return tomorrow


def simulate_next_24h(
    start_soc: float,
    now: datetime,
    profile: dict,
    capacity_ah: float,
    # Preferred new names — both old aliases below also accepted.
    next_sunrise: Optional[datetime] = None,
    next_sunset: Optional[datetime] = None,
    solar_first_day_ah: Optional[float] = None,
    solar_second_day_ah: Optional[float] = None,
    # Backwards-compat: old kwarg names still accepted.
    sunrise_today: Optional[datetime] = None,
    sunset_today: Optional[datetime] = None,
    solar_today_full_ah: Optional[float] = None,
    solar_tomorrow_full_ah: Optional[float] = None,
) -> dict:
    """Hour-by-hour SOC simulation over the next 24 hours.

    Parameters (preferred new names — see "Bug history" in
    `docs/generator_advisor/algorithm.md` for the rename rationale):

      next_sunrise          — the FIRST sunrise that occurs at or
                              after `now` (caller is expected to bump
                              past-time sunrises to the next-occurring;
                              see the advisor's lines 272-275).
      next_sunset           — same idea for sunset.
      solar_first_day_ah    — predicted Ah delivered during the
                              first daylight window in the 24-h sim
                              (i.e. the window between next_sunrise
                              and next_sunset). Use today's forecast
                              if pre-sunset, tomorrow's if post-sunset.
      solar_second_day_ah   — Ah for the window after that. Rarely
                              relevant inside a single 24-h sim;
                              passed for completeness.

    Old aliases `sunrise_today` / `sunset_today` / `solar_today_full_ah`
    / `solar_tomorrow_full_ah` still work but are deprecated.

    Spreads each daylight window's solar harvest uniformly across its
    hours (rough first cut — a future refinement can weight by the
    west-facing array's afternoon-heavy profile). For night hours,
    uses the discharge_model's per-hour median current.

    Returns a dict with:
        projected_low_soc       — minimum SOC anywhere in the window
        projected_sunrise_soc   — SOC at the next sunrise from now
        projected_tomorrow_evening_soc — SOC at the next sunset from now
    """
    # Backwards-compat shim: if old kwargs passed, route them.
    # Caller MUST provide one or the other of each pair.
    if next_sunrise is None:
        next_sunrise = sunrise_today
    if next_sunset is None:
        next_sunset = sunset_today
    if solar_first_day_ah is None:
        solar_first_day_ah = solar_today_full_ah
    if solar_second_day_ah is None:
        solar_second_day_ah = solar_tomorrow_full_ah
    if next_sunrise is None or next_sunset is None:
        raise TypeError(
            "simulate_next_24h requires next_sunrise + next_sunset "
            "(or the deprecated sunrise_today / sunset_today aliases)"
        )
    if solar_first_day_ah is None or solar_second_day_ah is None:
        raise TypeError(
            "simulate_next_24h requires solar_first_day_ah + "
            "solar_second_day_ah (or the deprecated solar_today_full_ah "
            "/ solar_tomorrow_full_ah aliases)"
        )

    subsequent_sunrise = next_sunrise + timedelta(days=1)
    subsequent_sunset  = next_sunset + timedelta(days=1)

    hours_first_daylight = max(0.1, (next_sunset - next_sunrise).total_seconds() / 3600)
    hours_second_daylight = max(0.1, (subsequent_sunset - subsequent_sunrise).total_seconds() / 3600)

    # Per-hour median discharge (signed; negative for consumption)
    # Falls back to overall median when an hour has no data yet.
    medians = [d["median_i"] for d in profile.values()] if profile else [-3.5]
    overall_median = statistics.median(medians) if medians else -3.5

    def _load_at_hour(hour: int) -> float:
        """Per-hour median current from the profile, or overall median."""
        hd = profile.get(hour)
        return hd["median_i"] if hd is not None else overall_median

    def _daylight_load_total(sunrise: datetime, sunset: datetime) -> float:
        """Sum the per-hour median load across the daylight window.
        Negative (since the medians are negative consumption)."""
        total = 0.0
        h = sunrise
        # Iterate hourly. Partial trailing hour gets a fractional weight
        # so the total integrates accurately for non-integer daylight.
        while h < sunset:
            step = min(timedelta(hours=1), sunset - h)
            frac = step.total_seconds() / 3600.0
            total += _load_at_hour(h.hour) * frac
            h = h + step
        return total

    # Pre-compute load and gross-solar totals once per day. The fix from
    # the 2026-05-19 floor-bias loop: the previous code distributed
    # `solar_first_day_ah` uniformly across daylight hours and credited
    # only solar during daylight (no load). That meant at sunrise the
    # simulator IMMEDIATELY switched from "discharging" to "charging at
    # daily-average rate", which overestimated the morning floor.
    #
    # New model: during daylight, ah_change = gross_solar_at_hour +
    # load_at_hour (load is negative). `gross_solar` follows a
    # sinusoidal arc that peaks at solar noon and tapers to 0 at the
    # sunrise/sunset endpoints. `gross_solar_total` is chosen so that
    # (gross_solar_total + daylight_load_total) == solar_first_day_ah,
    # preserving the daily NET pack gain (the quantity SolarModel was
    # fit against). The within-day shape is what changes.
    daylight_load_total_first  = _daylight_load_total(next_sunrise, next_sunset)
    daylight_load_total_second = _daylight_load_total(subsequent_sunrise,
                                                      subsequent_sunset)
    gross_solar_total_first    = solar_first_day_ah - daylight_load_total_first
    gross_solar_total_second   = solar_second_day_ah - daylight_load_total_second

    def _gross_solar_rate(cur: datetime, sunrise: datetime, sunset: datetime,
                          gross_total: float, daylight_h: float) -> float:
        """Sinusoidal gross-solar rate at the midpoint of the hour
        starting at `cur`. Returns 0 outside daylight or when total is
        non-positive."""
        if daylight_h <= 0 or gross_total <= 0:
            return 0.0
        hours_since_sunrise = (cur - sunrise).total_seconds() / 3600.0
        h_sample = hours_since_sunrise + 0.5
        if h_sample < 0 or h_sample > daylight_h:
            return 0.0
        peak = gross_total * math.pi / (2.0 * daylight_h)
        return peak * math.sin(math.pi * h_sample / daylight_h)

    soc = start_soc
    cur = now
    samples: list[tuple[datetime, float]] = [(cur, soc)]

    for _ in range(24):
        # Classify the current hour as daylight or night
        if next_sunrise <= cur < next_sunset:
            gross_solar = _gross_solar_rate(
                cur, next_sunrise, next_sunset,
                gross_solar_total_first, hours_first_daylight)
            ah_change = gross_solar + _load_at_hour(cur.hour)
        elif subsequent_sunrise <= cur < subsequent_sunset:
            gross_solar = _gross_solar_rate(
                cur, subsequent_sunrise, subsequent_sunset,
                gross_solar_total_second, hours_second_daylight)
            ah_change = gross_solar + _load_at_hour(cur.hour)
        else:
            # Night — pull this hour's median discharge rate
            ah_change = _load_at_hour(cur.hour)

        soc += ah_change / capacity_ah * 100.0
        soc = max(0.0, min(100.0, soc))
        cur = cur + timedelta(hours=1)
        samples.append((cur, soc))

    def soc_at(target: datetime) -> float:
        """Linear-interpolate SOC at target time from the samples."""
        for i in range(len(samples) - 1):
            t0, s0 = samples[i]
            t1, s1 = samples[i + 1]
            if t0 <= target <= t1:
                span = (t1 - t0).total_seconds()
                if span <= 0:
                    return s0
                f = (target - t0).total_seconds() / span
                return s0 + (s1 - s0) * f
        return samples[-1][1]

    # Project to "the next sunrise after now" and "the next sunset after
    # now", not unconditionally subsequent's pair. Bug-fix from 2026-05-18
    # 21:00 loop: post-sunset, next_sunrise/next_sunset are already
    # tomorrow's date (the caller's bumping made sunrise_dt next-occurring),
    # so subsequent_sunrise ends up at day-after-tomorrow — outside the
    # 24h sim window — and soc_at() falls off the end of samples,
    # returning the same value for both projections. Fix: pick the
    # actual next-occurring time relative to `now`, then clamp into
    # the 24h window if needed.
    proj_sunrise = next_sunrise if next_sunrise > now else subsequent_sunrise
    proj_sunset  = next_sunset  if next_sunset  > now else subsequent_sunset
    return {
        "projected_low_soc": min(s for _, s in samples),
        "projected_sunrise_soc": soc_at(proj_sunrise),
        "projected_tomorrow_evening_soc": soc_at(proj_sunset),
    }


def project_solar_ah(weather_row: dict, model: SolarModel) -> tuple[float, str]:
    """Predict Ah delivered to the pack tomorrow. Returns (ah, source).

    Preferred path: query Open-Meteo for tomorrow's forecast irradiance.
    Fallback: today's irradiance from the latest weather.csv row as a
    proxy (worse but doesn't require network).
    """
    tomorrow_kwh = _get_tomorrow_kwh_per_m2()
    if tomorrow_kwh is not None and tomorrow_kwh > 0:
        return model.predict_ah(tomorrow_kwh), "tomorrow_forecast"

    # Fallback: today's irradiance as a proxy
    today_total = _f(weather_row.get("shortwave_radiation_sum_today_wh_m2"))
    if today_total is None:
        return 0.0, "no_data"
    kwh_per_m2 = today_total / 1000.0
    return model.predict_ah(kwh_per_m2), "today_as_proxy"


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

    # === Hour-by-hour 24-hour simulation ===
    # Determines today's daylight window vs night, distributes solar
    # over daylight hours, uses per-hour discharge medians for night.
    # Handles "now is past today's sunrise" correctly (previous logic
    # treated everything from now to tomorrow's sunrise as one big
    # discharge window — which over-predicted SOC drop by ~50 % during
    # the daytime, causing false-positive "RUN GENERATOR" recs).
    sunrise_today = sunrise_dt if sunrise_dt > now else sunrise_dt
    sunset_today  = sunset_dt
    # If both sunrise and sunset are tomorrow (i.e. we're in the dead
    # of night), pull today's pair back by 24h. The weather row has
    # today's, but our earlier bumping moved them ahead.
    if sunrise_today > now and (sunrise_today - now) > timedelta(hours=12):
        sunrise_today = sunrise_today - timedelta(days=1)
    if sunset_today > now and (sunset_today - now) > timedelta(hours=24):
        sunset_today = sunset_today - timedelta(days=1)

    solar = load_solar_model()

    # Quietly record the model state to data/calibration_log.csv if it
    # changed since the last entry (different coefficient, n_obs, or
    # confidence tier). No-op when nothing has shifted. Best-effort:
    # failures here must NOT block the advisor from emitting a verdict.
    model_last_updated_iso: Optional[str] = None
    model_last_updated_source: Optional[str] = None
    try:
        calibration_log_mod.record_if_changed(solar, source="advisor-invocation")
        _last = calibration_log_mod.last_entry()
        if _last is not None:
            model_last_updated_iso = _last.ts
            model_last_updated_source = _last.source
    except Exception:
        pass

    # Pull the most-recent projection_accuracy record (if any) so the
    # dashboard can surface "last sunrise: predicted X, actual Y,
    # error ±Z". Empty until the first sunrise after the projection_log
    # starts collecting (lands the first time projection_accuracy
    # produces a record). Best-effort.
    last_accuracy_proj: Optional[float] = None
    last_accuracy_actual: Optional[float] = None
    last_accuracy_error_pp: Optional[float] = None
    last_accuracy_target_iso: Optional[str] = None
    # Accuracy-aware confidence: if recent validated projections have
    # been consistently within `ACCURACY_LIFT_THRESHOLD_PP` of actual,
    # lift the advisor's confidence one tier. Computed below; surfaced
    # in inputs so the dashboard can show "lifted by accuracy" badge.
    recent_abs_error_pp: Optional[float] = None
    recent_accuracy_n: int = 0
    try:
        _all_proj = projection_log_mod.read_log()
        _pack_samples = projection_accuracy_mod._load_pack_samples(args.pack_csv)
        _records = projection_accuracy_mod.compute_accuracy_records(
            _all_proj, _pack_samples)
        if _records:
            _r = _records[-1]    # newest validated record
            last_accuracy_proj = _r.projected_sunrise_soc
            last_accuracy_actual = _r.actual_sunrise_soc
            last_accuracy_error_pp = _r.error_pct_points
            last_accuracy_target_iso = _r.sunrise_iso
            # Window the last N records and compute mean |error|. We
            # use the most recent ones because the model evolves: an
            # old bad record before yesterday's coefficient fit shouldn't
            # drag down today's confidence.
            _recent = _records[-ACCURACY_LIFT_WINDOW:]
            recent_accuracy_n = len(_recent)
            recent_abs_error_pp = (
                sum(abs(r.error_pct_points) for r in _recent) / recent_accuracy_n
            )
    except Exception:
        pass

    # Reach into today_harvest for the live coefficient measurement.
    # This is what the SolarModel *would* fit to if it were trained on
    # today's morning data. Surfacing it in inputs lets the user (and
    # the dashboard) see "what the system is observing right now" vs
    # "what the SolarModel was fit to from prior days" — a transparency
    # input, not a decision input. The advisor itself still uses
    # `solar.predict_ah(...)` for projections; live_ratio is diagnostic.
    try:
        _harvest_snap = today_harvest_mod.snapshot(args.pack_csv, args.weather_csv)
        live_ratio = _harvest_snap.get("live_ratio_ah_per_kwh_m2")
        irradiance_so_far = _harvest_snap.get("irradiance_kwh_m2_so_far")
        solar_ah_so_far   = _harvest_snap.get("solar_ah_so_far")
    except Exception:
        live_ratio = None
        irradiance_so_far = None
        solar_ah_so_far = None

    today_kwh, tomorrow_kwh = weather_mod.fetch_today_tomorrow_irradiance()
    # Fall back to weather.csv's today value if the live API isn't reachable
    if today_kwh is None:
        t = _f(weather_now.get("shortwave_radiation_sum_today_wh_m2"))
        today_kwh = (t / 1000.0) if t is not None else 0.0
    if tomorrow_kwh is None:
        tomorrow_kwh = today_kwh
    solar_today_full_ah    = solar.predict_ah(today_kwh)
    solar_tomorrow_full_ah = solar.predict_ah(tomorrow_kwh)
    solar_ah = solar_tomorrow_full_ah    # what we expect to gain across tomorrow
    solar_source = "tomorrow_forecast" if tomorrow_kwh > 0 else "no_data"

    sim = simulate_next_24h(
        start_soc=start_soc, now=now, profile=profile,
        next_sunrise=sunrise_today, next_sunset=sunset_today,
        solar_first_day_ah=solar_today_full_ah,
        solar_second_day_ah=solar_tomorrow_full_ah,
        capacity_ah=PACK_CAPACITY_AH_PER_BATTERY,
    )
    projected_sunrise_soc           = sim["projected_sunrise_soc"]
    projected_tomorrow_evening_soc  = sim["projected_tomorrow_evening_soc"]
    projected_low                   = sim["projected_low_soc"]

    # Record the projection to data/projection_log.csv (rate-limited,
    # at most one row per ~25 min). Builds the historical record for
    # advisor self-evaluation: did the projection hold up vs reality?
    # Best-effort try/except — must NOT block the verdict.
    try:
        projection_log_mod.record_if_due(
            start_soc_pct=start_soc,
            projected_sunrise_soc=projected_sunrise_soc,
            projected_tomorrow_evening_soc=projected_tomorrow_evening_soc,
            projected_low_soc=projected_low,
            solar_model_coefficient=solar.coefficient_ah_per_kwh_m2,
            today_irradiance_kwh_m2=today_kwh,
            sunrise_iso=sunrise_dt.isoformat(timespec="minutes"),
            source="advisor-invocation",
            now=now,
        )
    except Exception:
        pass

    # Kept for the "inputs" diagnostic — show what we projected for each piece
    overnight_ah = discharge_model.project_overnight_ah(profile, now.hour, sunrise_dt.hour) or 0.0
    next_eve_ah  = discharge_model.project_overnight_ah(profile, sunrise_dt.hour, sunset_dt.hour) or 0.0

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

    # The solar model's confidence is the advisor's base confidence
    # tier. As days accumulate it shifts low → medium → high.
    # discharge_model confidence isn't tracked yet; for now the advisor
    # inherits the solar model's label.
    confidence_base = solar.confidence

    # Accuracy-aware lift: if the recent projection_accuracy track
    # record looks tight, lift one tier. The base is preserved in
    # `inputs` so the dashboard can show both ("low → medium, lifted
    # by accuracy"). See lift_confidence_by_accuracy() above for the
    # rule.
    overall_confidence, confidence_lifted = lift_confidence_by_accuracy(
        confidence_base, recent_abs_error_pp, recent_accuracy_n,
    )

    # Log the lift transition to data/confidence_log.csv. Only fires
    # when (base, resolved, lifted) differs from the last logged
    # entry — so a stable "lifted to medium" state writes one row
    # and stays quiet; the next event is logged the moment the lift
    # changes (e.g. recent_abs_error_pp drifts above the threshold
    # and the lift falls away). Best-effort.
    try:
        confidence_log_mod.record_if_changed(
            base=confidence_base,
            resolved=overall_confidence,
            lifted=confidence_lifted,
            recent_abs_error_pp=recent_abs_error_pp,
            recent_n=recent_accuracy_n,
            source="advisor-invocation",
            now=now,
        )
    except Exception:
        pass

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
                "solar_source": solar_source,
                "next_eve_ah": next_eve_ah,
                "today_irradiance_kwh_m2":
                    _f(weather_now.get("shortwave_radiation_sum_today_wh_m2")) and
                    _f(weather_now.get("shortwave_radiation_sum_today_wh_m2")) / 1000.0,
                # Diagnostic — live measurement, not used in the projection
                "solar_model_coefficient": solar.coefficient_ah_per_kwh_m2,
                "live_ratio_ah_per_kwh_m2": live_ratio,
                "irradiance_kwh_m2_so_far": irradiance_so_far,
                "solar_ah_so_far": solar_ah_so_far,
                "model_last_updated_iso": model_last_updated_iso,
                "model_last_updated_source": model_last_updated_source,
                "last_accuracy_proj": last_accuracy_proj,
                "last_accuracy_actual": last_accuracy_actual,
                "last_accuracy_error_pp": last_accuracy_error_pp,
                "last_accuracy_target_iso": last_accuracy_target_iso,
                "confidence_base": confidence_base,
                "confidence_lifted_by_accuracy": confidence_lifted,
                "recent_abs_error_pp": recent_abs_error_pp,
                "recent_accuracy_n": recent_accuracy_n,
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
                "solar_source": solar_source,
                "next_eve_ah": next_eve_ah,
                # Diagnostic — live measurement, not used in the projection
                "solar_model_coefficient": solar.coefficient_ah_per_kwh_m2,
                "live_ratio_ah_per_kwh_m2": live_ratio,
                "irradiance_kwh_m2_so_far": irradiance_so_far,
                "solar_ah_so_far": solar_ah_so_far,
                "model_last_updated_iso": model_last_updated_iso,
                "model_last_updated_source": model_last_updated_source,
                "last_accuracy_proj": last_accuracy_proj,
                "last_accuracy_actual": last_accuracy_actual,
                "last_accuracy_error_pp": last_accuracy_error_pp,
                "last_accuracy_target_iso": last_accuracy_target_iso,
                "confidence_base": confidence_base,
                "confidence_lifted_by_accuracy": confidence_lifted,
                "recent_abs_error_pp": recent_abs_error_pp,
                "recent_accuracy_n": recent_accuracy_n,
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
    if rec.inputs.get("confidence_lifted_by_accuracy"):
        base = rec.inputs.get("confidence_base")
        ae = rec.inputs.get("recent_abs_error_pp")
        n = rec.inputs.get("recent_accuracy_n")
        print(f"    lifted from '{base}' — last {n} projections within "
              f"±{ae:.2f} pp of actual (< {ACCURACY_LIFT_THRESHOLD_PP:.1f} pp threshold)")
    else:
        print(f"    (only ~1 day of data; solar model is still a stub — see")
        print(f"    docs/generator_advisor/README.md for the path to higher confidence)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
