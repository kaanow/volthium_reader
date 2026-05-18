# Generator advisor

> Status: **architecture draft.** Data collection has just started — we
> have one full pack cycle on file and one weather snapshot. The
> implementation here will fill in over the coming days as data
> accumulates.

## What it does

Recommends:
1. **Whether** to run the generator at all today / tonight.
2. **When** to run it (now, this evening, tomorrow morning).
3. **For how long** (i.e. target SOC at the end of the run).

The recommendation is shown on the dashboard (eventually on the wall
e-paper too) so the cabin user makes informed decisions instead of
guessing.

## Goal in user terms

> *"I'd like this to build out into a system that recommends generator
>  use and for how long."*

The user-visible answer should be something like:

```
  GENERATOR RECOMMENDATION
  Run for 2 h 15 m, starting around 6 am tomorrow.
  Reason: forecast is heavy overcast (only ~30 % of normal harvest);
          at current discharge rate, pack would hit 22 % by morning
          and 14 % by tomorrow evening without a top-up.
```

Or, on good days:

```
  GENERATOR: not needed.
  Forecast is clear; expected harvest ~ 110 Ah will fully recharge
  even from tonight's projected low of 65 %.
```

## Inputs the advisor needs

1. **Current pack state** — already have it (logger writes `data/pack.csv`).
   - SOC, voltage, current, remaining_ah.
2. **Recent discharge profile** — we know how the pack has been
   trending for the last 24 h. Used to estimate tonight's overnight
   discharge.
3. **Weather forecast** — irradiance prediction for the next 24 h.
   `scripts/weather.py` writes `data/weather.csv` from Open-Meteo.
4. **Site solar model** — empirical Ah-per-irradiance-Wh/m² coefficient
   learned from past days of (`pack.csv` + `weather.csv`) joined.
5. **Generator characteristics** — empirical Ah/h delivered (we observed
   ~ +55 A average → ~ 55 Ah/hr, or ~ 1.6 kW into the batteries).

## Architecture (planned)

```
  ┌─────────────┐     ┌──────────────┐
  │ pack.csv    │     │ weather.csv  │
  └──────┬──────┘     └──────┬───────┘
         │                    │
         └────────┬───────────┘
                  ▼
         ┌─────────────────┐         ┌─────────────────────┐
         │ daily_summary   │ ◄───────│ solar model fit     │
         │  (Ah harvested  │         │  (irradiance Wh/m²  │
         │  vs. forecast)  │ ───────►│   → Ah delivered)   │
         └────────┬────────┘         └─────────────────────┘
                  │
                  ▼
         ┌──────────────────────┐
         │ overnight discharge  │
         │  model (Ah/h by load │
         │  profile + hour-of-  │
         │  day)                │
         └────────┬─────────────┘
                  │
                  ▼
         ┌─────────────────────────────────┐
         │ forward simulation:             │
         │   - tonight's discharge         │
         │   - tomorrow's expected harvest │
         │   - decide if pack stays > 25 % │
         │   - if not: compute generator   │
         │     hours needed to maintain    │
         └────────┬────────────────────────┘
                  ▼
         ┌────────────────────┐
         │ recommendation     │
         │  text + run window │
         └────────────────────┘
```

## Component plan (incremental)

### 1. `scripts/daily_summary.py`  (~ 50 lines)

Joins `pack.csv` and `weather.csv` by hour. Emits one row per day with
columns:
- start/end SOC
- min/max SOC
- total Ah delivered while charging
- total Ah consumed while discharging
- weather: total irradiance Wh/m², mean cloud cover, mean temperature,
  weather codes seen
- duration of generator runs (events with pack_i > +30 A)

This is the ground truth for the solar model. Run nightly.

### 2. `volthium/solar_model.py`  (~ 80 lines)

Fits a simple coefficient: **Ah delivered per kWh/m² irradiance**.
Initially a single scalar; later can split by hour-of-day to account
for the west-facing array's afternoon-heavy profile.

```python
class SolarModel:
    def fit(self, daily_summaries: list[DailyRow]): ...
    def predict_ah_from_forecast(self, forecast: WeatherForecast) -> float: ...
```

Honest about uncertainty: returns (mean, 25th, 75th) percentile of
expected Ah given the fit's confidence.

### 3. `volthium/discharge_model.py`  (~ 60 lines)

Looks at the last 24-48 h of discharge data and produces an expected
Ah/h consumption pattern by hour-of-day. Simple averaging is enough
for v1; later this can become a Markov / state-based model if loads
have clear patterns (fridge cycles, etc.).

### 4. `volthium/advisor.py`  (~ 100 lines)

Forward-simulates from now → 24 h ahead using the discharge model and
solar model. If projected pack SOC dips below the configured comfort
floor (default 25 %), computes the generator runtime needed and the
best window to run it (preferably mid-morning, before the west-facing
array kicks in around midday).

Returns a structured recommendation:

```python
@dataclass
class Recommendation:
    run_generator: bool
    reason: str
    when:    Optional[datetime]   # earliest reasonable start
    duration_h: Optional[float]
    projected_floor_pct: float    # how low pack would go without action
    confidence: str               # "high" / "medium" / "low"
```

### 5. Dashboard integration

A new section at the top of the dashboard:

```
  ┌─────────────────────────────────────────────────────────────┐
  │  RECOMMENDATION                                              │
  │  Run generator ~2 h tomorrow morning (start by 7 am)        │
  │  Pack would otherwise hit 22 % by tomorrow night.            │
  │                                                              │
  │  forecast: heavy overcast (WMO 65, 6.2 kWh/m² expected)      │
  │  confidence: medium (only 8 days of data)                    │
  └─────────────────────────────────────────────────────────────┘
```

When confidence is low ("we've never seen weather like this before"),
the UI says so honestly rather than hide it.

## Data we need before this works

Approximate weeks-of-observation required for each subsystem to give
useful answers:

| Subsystem            | Days of data | Reason |
|----------------------|--------------|--------|
| Discharge model      | 3–5          | Patterns repeat hourly + daily |
| Solar model (rough)  | 7–10         | Need several weather types     |
| Solar model (tuned)  | 30+          | Need seasonal variation        |
| Advisor (v1)         | 7–10         | Discharge model + rough solar  |
| Advisor (good)       | 30+          | Both models tuned              |

Right now: 1 day of data. We're at the "log everything and wait"
stage. The loop is doing that.

## Open questions

- Confirm cabin coordinates (multiple Loon Lakes in BC — `docs/site/loon_lake.md`)
- Solar array specs (panel watts, count, tilt) — needed for tighter
  expected-harvest predictions, and to make sense of "% of normal" in
  the recommendation text
- Generator runtime cost (fuel burn rate) — useful if we want the
  advisor to balance "run a little tonight" vs. "run a lot tomorrow"
- Comfort floor preference (default 25 %; could be 20 % or 30 %)
- Whether the advisor should also consider weather **after** tomorrow,
  e.g. "tomorrow's overcast but the next two days are sunny, so we
  can ride it out without a generator"
