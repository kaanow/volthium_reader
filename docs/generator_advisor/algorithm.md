# Generator advisor — algorithm + caveats

This doc tracks how `scripts/generator_advisor.py` decides whether to
recommend a generator run. The high-level architecture is in the
sibling [`README.md`](README.md); this file gets specific about the
math.

## Pipeline

```
   pack.csv tail        weather.csv tail      Open-Meteo (live API)
        │                     │                       │
        ▼                     ▼                       ▼
   current SOC          today's irradiance     tomorrow's forecast
   (min of A & B)         (kWh/m², cloud %)     (kWh/m², cached 5min)
        │                     │                       │
        │                     └──────┬────────────────┘
        │                            │
        ▼                            ▼
   discharge_model              SolarModel.predict_ah()
   .project_overnight_ah()      (default constant OR fit from
   (sum of per-hour median       data/daily_summary.csv)
    |I| × 1h across the hours
    we'll traverse)
        │                            │
        └────────────┬───────────────┘
                     ▼
            forward simulate the next 24 h
                     │
                     ▼
            compare projected_low SOC against comfort_floor
                     │
                     ▼
            emit Recommendation
                run_generator | morning_watch | OK
                + reason, when, duration, confidence
```

## Step by step

### 1. Current state

From `pack.csv`'s most recent row. We take the **lower** of the two
batteries' SOC as `start_soc` — the limiting battery on discharge.

### 2. Sunrise / sunset

Pulled from the most recent `weather.csv` row's `sunrise_iso` /
`sunset_iso` fields. If today's value is already past, we bump it by
24 h (tomorrow's value drifts by ≤ 2 min at this latitude in mid-May —
close enough).

### 3. Overnight discharge from now to sunrise

```
overnight_ah = discharge_model.project_overnight_ah(profile, now.hour, sunrise.hour)
```

The model fits a **per-hour-of-day median** pack current from all
`state ∈ {"discharging", "idle"}` samples in `pack.csv`. Then we sum
the `|median current| × 1 h` across the hours we'll traverse before
sunrise. Falls back to the overall median if a particular hour bin
has no data yet.

This is robust against the BMS counter quirks at any single moment
(fridge spikes, EMA lag) because we use the *median* of many samples
per hour.

### 4. Solar harvest tomorrow

```
solar_ah, source = project_solar_ah(weather_row, SolarModel)
```

Two-stage:

1. **Try `weather.fetch_today_tomorrow_irradiance()`** — Open-Meteo
   API call for tomorrow's forecast `kwh/m²`. 5-min cache so re-runs
   don't pound the API. On success: `source = "tomorrow_forecast"`.
2. **Fall back to today's measured** irradiance as a proxy for
   tomorrow if the API call fails (offline / Starlink down).
   `source = "today_as_proxy"`.

Then `solar_ah = SolarModel.predict_ah(kwh_per_m2)`. The model's
coefficient is **7 Ah/(kWh/m²) by default** — anchored on the
2026-05-17 partial-day observation. As `data/daily_summary.csv`
accumulates full-day rows, `SolarModel.fit_from_daily_summary()`
takes over with a real fit (median-of-ratios, clamped to
`[2, 15] Ah/(kWh/m²)`).

### 5. Discharge from sunrise to tomorrow evening

Same `discharge_model.project_overnight_ah()` call but over the
sunrise → sunset hour range. This is rough — solar usually offsets
load during the day, so the per-hour medians (which only see
discharging/idle samples) will *over-estimate* daytime consumption
once we have charge days to widen the bins. For now it's
conservative, which is fine.

### 6. Forward simulation

```
projected_sunrise_soc        = start_soc       − overnight_pct
projected_tomorrow_evening   = projected_sunrise + solar_pct − daytime_pct
projected_low                = min(sunrise, tomorrow_evening)
```

### 7. Decide

| Condition                                          | Verdict           |
|---------------------------------------------------|--------------------|
| `projected_low ≥ comfort_floor`                    | ✓ no run           |
| `projected_low < comfort_floor`                    | ▶ RUN GENERATOR    |
| above, but within 60 min of sunrise AND `< 50 %`   | ⚠ MORNING WATCH    |

Generator runtime is computed as
`deficit_ah / GENERATOR_RATE_AH_PER_HOUR` (observed ~ 55 Ah/h). The
recommended start time is **1 h before sunrise** — pack is at its
daily low then, and topping off bridges to the morning before
afternoon solar takes over.

## Confidence

`Recommendation.confidence` inherits from the `SolarModel`:

| SolarModel.n_observations | confidence |
|---------------------------|------------|
| < 3                       | low        |
| 3–6                       | medium     |
| ≥ 7                       | high       |

The dashboard surfaces the confidence label so users know how much
to trust the verdict. While confidence is "low", a wise user is
slightly conservative beyond the bare math.

## Known limitations (sorted by impact)

1. **Solar model is a single constant until we have ≥ 3 full-day
   rows**. Stub coefficient of 7 Ah/(kWh/m²) is anchored on ONE
   partial-day observation. Could be off by ±50 %. Improves daily
   as data accumulates.

2. **Discharge model doesn't yet bin by season or day-type**. A
   weekend with all the lights on looks the same as a Tuesday with
   just the fridge. Will need ≥ 1 month of data + a few notable
   events (weekend houseful vs. weekday quiet) before refining.

3. **Tomorrow's discharge profile = today's**. We assume the next
   day's loads will match what we've seen. Reasonable steady-state
   assumption for an off-grid cabin but breaks during atypical use
   (parties, generators-running-the-laundry, etc.).

4. **The "1h before sunrise" start window is a heuristic**. A more
   sophisticated advisor would pick the cheapest hour considering
   fuel cost, noise (don't wake people up at 5am), and rate-of-
   change in projected_low.

5. **Comfort floor is a single number (default 25 %)**. Real comfort
   varies — 25 % at 4pm with sun coming is different from 25 % at
   10pm with hours of fridge cycles ahead.

6. **No look-ahead beyond tomorrow**. If we're heading into 3 days
   of overcast, running the generator tonight to "bank" buffer is
   reasonable. Current advisor only sees 24 h forward.

## What the next iterations should add (priority order)

1. Replace `SolarModel.default()` with `fit_from_daily_summary()` —
   automatic once we have ≥ 3 full-day rows.
2. Pull the **tomorrow-discharge profile** from the *previous*
   matching weekday rather than the global hourly median (after
   enough data).
3. Multi-day look-ahead — if Open-Meteo forecasts overcast for
   day+2, factor it into today's decision.
4. Add an output for *historical accuracy* — when the advisor said
   "no run needed" yesterday, did the projection hold? Track to
   tune.
5. Wire the advisor's output into the cabin-side firmware so the
   wall display can show the recommendation directly, not just the
   laptop dashboard.

## Bug history (added 2026-05-18)

The advisor's hour-by-hour simulator (`simulate_next_24h`) has been
through two important bug-fixes, both surfaced when real cabin data
exercised the edges of the simulator's day/night frame handling.
Both are now anchored with regression tests so they can't quietly
come back. Recording the history here so future-me knows *why* the
code is shaped the way it is.

### Bug #1 — 2026-05-18 06:10 — "daytime false-positive"

**Symptom**: at 06:10 (1 h past sunrise), the advisor reported
`RUN GENERATOR — projected sunrise SOC 32 %`, a false alarm. Pack
was actually fine at 73 % SOC.

**Root cause**: the *original* projection code (pre-simulator) did
"discharge from `now` until `next sunrise`", but when `now` was
past today's sunrise, `next sunrise` got bumped to **tomorrow's**
05:09. The 23-hour window between 06:10 today and 05:09 tomorrow
was then treated as one big pure-discharge interval — ignoring
the ~14 of those hours that were daytime with active solar.
Result: a predicted SOC drop of ~40 % across the "overnight"
falsely tripped the RUN GENERATOR threshold.

**Fix**: replaced the single-window calc with
`simulate_next_24h()` — an hour-by-hour walk that classifies each
hour as daylight (apply solar Ah uniformly across the day) or
night (apply per-hour discharge median). Five regression tests in
`tests/test_advisor_simulator.py` anchor the bug-shape, most
importantly
`test_daytime_with_balancing_solar_keeps_soc_close_to_start`.

**Lesson**: when a projection's time window crosses a major state
transition (night→day), you can't treat the whole window as a
single rate. Walk it hour-by-hour.

### Bug #2 — 2026-05-18 21:00 — "post-sunset projection collapse"

**Symptom**: at 21:00 (post-sunset), the advisor reported identical
values for `sunrise SOC` and `tomorrow evening SOC` — both
89.78 %. Physically impossible (an overnight discharge sits
between those two times). `projected_low_soc` was correct at ~69 %.

**Root cause**: the calling code at the advisor's lines 272-275
bumps `sunrise_dt` / `sunset_dt` past `now` so they're always
*next-occurring* times (needed elsewhere, e.g. to schedule
generator runs in the future). Post-sunset, both got bumped to
tomorrow's date. Then inside `simulate_next_24h`:

```python
sunrise_tomorrow = sunrise_today + timedelta(days=1)  # day-AFTER-tomorrow!
sunset_tomorrow  = sunset_today  + timedelta(days=1)
```

These target times then sat OUTSIDE the 24-h sim window. The
`soc_at()` linear-interpolator fell off the end of the samples
list and returned `samples[-1]` for both — collapsing the two
projections to the same end-of-window value.

Pre-sunset this was masked: the lines 289-292 "pull back by 1 day"
heuristics put `sunrise_today` inside the window when needed, so
`sunrise_tomorrow` also stayed inside. Those pull-back heuristics
don't fire post-sunset (the gaps don't exceed the >12 h / >24 h
thresholds), exposing the bug.

**Fix**: replaced the unconditional `+1 day` projection target
with "pick the next-occurring time relative to `now`":

```python
proj_sunrise = sunrise_today if sunrise_today > now else sunrise_tomorrow
proj_sunset  = sunset_today  if sunset_today  > now else sunset_tomorrow
```

Post-sunset, `proj_sunrise = sunrise_today` (which is already
tomorrow's 05:09, in the future) → within the 24-h window →
`soc_at()` returns the actual interpolated overnight SOC.

Regression test:
`test_post_sunset_projections_target_NEXT_sunrise_not_day_after`
includes a **bug-shape assertion** that the two projection values
are NOT equal — so if either lookup ever falls off the end of
samples again, the test fires.

**Lesson**: a function returning two interpolated lookups should
defend against both falling off the end and returning the same
sentinel value. Equality of distinct projections is a smell.

### Why both bugs share a common theme

Both came from the simulator's idea of "today" vs "now" getting
out of sync at day-boundary edges. The simulator was designed
assuming `sunrise_today` and `sunset_today` were literally
**today's calendar** sunrise/sunset, but the calling code bumps
them to mean *next-occurring* — at certain times of day, those
two meanings diverge.

If the simulator's API were redesigned today, the parameters would
rename to `next_sunrise` / `next_sunset` (matching what the caller
actually passes), and the second pair would be `subsequent_sunrise`
/ `subsequent_sunset` (= next + 1 day).

**Update 2026-05-19 02:44 — the rename was done.** The simulator's
preferred kwargs are now `next_sunrise` / `next_sunset` /
`solar_first_day_ah` / `solar_second_day_ah`. The old aliases
(`sunrise_today` / `sunset_today` / `solar_today_full_ah` /
`solar_tomorrow_full_ah`) are still accepted for backwards
compatibility — passing either set works. The internal logic uses
the `next_*` names throughout, matching the comment-level mental
model. Caller validation: if neither old nor new is provided, a
`TypeError` is raised with a clear message.

## Cross-references

- [`README.md`](README.md) — architecture overview
- [`../hardware/bms_calibration.md`](../hardware/bms_calibration.md) —
  why we use `min(SOC_a, SOC_b)` and what the per-battery capacity
  bounds really are
- [`../site/loon_lake.md`](../site/loon_lake.md) — west-facing array
  context that explains why the discharge profile is shifted late
- `scripts/generator_advisor.py` — the implementation
- `volthium/solar_model.py` — `SolarModel` class
- `scripts/discharge_model.py` — `project_overnight_ah()`
- `scripts/daily_summary.py` — feeds the solar model fit
