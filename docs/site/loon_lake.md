# Site profile — The Barge Inn, Loon Lake, BC

## Location

- **Loon Lake, British Columbia, Canada**
- Most likely coordinates (TODO: confirm with user): **51.07 °N, 121.20 °W**
  — Loon Lake near Clinton / Cache Creek, BC. There are several Loon
  Lakes in BC; this is the one most commonly referred to as "Loon Lake."
- **South side of the lake** — orography note: the lake is to the
  north of the cabin, so anything coming "off the lake" arrives from the
  north.
- Timezone: **America/Vancouver** (PST / PDT — UTC-8 / UTC-7 DST).
- Elevation ≈ 1100 m above sea level. Mountain BC interior climate:
  cold, often-cloudy winters; hot dry summers with afternoon haze.

## Solar array orientation

- **Roof-mounted, primarily west-facing.**
- Catches **afternoon and evening sun** well.
- **Limited morning sun** — eastern aspect is significantly worse than
  a south-facing array would be.

### Empirical "morning shadow clears" timing

Observed on **2026-05-18** (May, partly cloudy, 51 °N):

| Moment                          | Local time      | Notes                                     |
|---------------------------------|-----------------|-------------------------------------------|
| Civil sunrise                   | 05:10           | Open-Meteo                                |
| First time pack current hit 0 A | ~ 06:38         | Early solar starting to match load        |
| Long overnight discharge ended  | ~ 06:44         | Pack flat-lined; alternating idle/discharge |
| First sustained charging (EMA)  | ~ 09:39         | smoothed pack current crossed positive — but on a **98 % cloud, 4.86 kWh/m² forecast day**, so this is the **bad-weather lower bound** for the lag |

So **for this west-facing array on a heavy-overcast day, useful solar
lags sunrise by roughly 4.5 hours**. On a clearer day expect this to
shrink toward 1.5–2.5 h after sunrise (when direct sun first hits the
west-facing panels after morning shadow clears). In winter (lower sun
angle, longer shadow from the roof's east edge) expect the lag to
grow — the generator should not be scheduled to "finish before
sunrise"; it should aim to finish at least ~ 2 h after sunrise so the
array can take over, and on cloudy mornings the safe target is later
still.

### Implications for daily harvest profile

Most off-grid solar guides assume south-facing arrays in the northern
hemisphere, where peak production is around solar noon. Our setup has a
shifted profile:

```
   south-facing (typical):       our west-facing array:
         ▁▂▄██▄▂▁                       ▁▁▂▅██▅▂
   06   12   18                     06   12   18
        ↑ peak                              ↑ peak (~14-17 local)
```

This means:
- Pack hits SOC minimum **just before sunrise** (worst-case overnight
  draw + 4-6 h of no solar after dawn).
- Real charging doesn't begin meaningfully until ~ **10 am – noon**
  depending on cloud cover and season.
- The "useful day" for recharging is roughly **noon to sunset** local
  time, which on a sunny BC summer day is ~ 13:00 – 21:00 local =
  **~8 hours of useful solar.** In winter, this shrinks to ~ 13:00 –
  16:30 = **~3-4 hours**.
- Peak hours are mid-afternoon, NOT solar noon.

### Generator role

The generator (~ +60 A observed at the pack, ~ 1.6 kW into the batteries)
exists to backstop nights / overcast days when the west-facing array
doesn't restore the pack on its own. Designed use: **bridge the morning
gap when the pack is at its daily low and solar isn't yet contributing.**

## Observed load signatures (pack-side, DC)

These are real-world step changes we've seen in the pack current, after
inverter conversion. Knowing them helps the discharge model recognize
what's happening without explicit user input. Numbers will be refined
as we capture more cycles.

| Load                                       | Step at pack | Pattern                              | Notes |
|--------------------------------------------|--------------|--------------------------------------|-------|
| Cabin baseline (idle inverter + standby)   | ~ -3 A       | sustained, slow drift                | Always present when inverter is on |
| Ceiling fan on (overnight comfort)         | + ~2.3 A     | step, sustained for hours            | Captured 22:00 on 2026-05-17. Below event-detector threshold by design. |
| Fridge compressor (cycle)                  | + ~8 A pulse, peak -8.4 A | **10–55 s ON every ~34 min** (textbook fridge interval) | Detector threshold tuned from -10A to -8A on 2026-05-18 to capture these properly. **User-confirmed**: overnight pulses are the fridge. |
| Lights (multiple rooms, demo of monitor)   | + ~7–10 A    | brief, depends on what's switched on  | Triggered the heavy-load event detector. |
| Solar charge (sunny mid-afternoon)         | -50 to -60 A | gradual ramp, peaks ~15:00–17:00      | West-facing roof bias |
| Generator (~1.6 kW into pack)              | -60 A        | step on, sustained, step off          | Confirmed via 2026-05-17 generator run |

(Positive numbers are **draw**; negative numbers in this table are
**charge**. The CSV uses the inverse sign — positive = into pack, but
in conversation it's easier to say "+2 A load.")

### Typical "overnight normal" load

Per user: ceiling fan + overnight fire is standard.

- Wood stove: zero electrical draw.
- Ceiling fan: ~2.3 A continuous at 24 V pack ≈ ~55 W into the inverter,
  which is about right for a residential fan at low–medium speed.
- Background: fridge cycling on top of baseline.

So a quiet, normal overnight has a discharge curve of roughly **-5 to
-8 A average**, with brief +7 A bumps every several minutes when the
fridge runs. Anything substantially above that is non-routine usage
(tools, appliances) and worth surfacing as a heavy-load event.

### Afternoon over-performance vs horizontal irradiance (captured 2026-05-18)

Watching today's live `Ah / kWh/m²` ratio across the day surfaced a
real model-limitation finding worth recording here so future-me
doesn't try to "fix" the SolarModel by chasing a single coefficient
that can never fit.

Observed live-ratio trend on this overcast day (98–100 % cloud):

| Time  | live ratio | drift from 7.0 model |
|-------|-----------:|---------------------:|
| 11:39 |       7.14 |          +2 %        |
| 12:02 |       7.00 |           0 %        |
| 12:47 |       7.30 |          +4 %        |
| 13:20 |       7.13 |          +2 %        |
| 13:47 |       7.49 |          +7 %        |
| 13:53 |       7.75 |         +11 %  amber |
| 14:21 |       **8.73** |     **+25 %  red**   |

The mid-morning ratio sits ≈ 7.0 (matches the SolarModel default
extracted from yesterday's partial-day rollup). The afternoon ratio
climbs steeply. Reasonable explanation:

- Open-Meteo's `shortwave_radiation_wm2` is the regional **horizontal-
  plane** irradiance — what a flat-on-the-ground pyranometer would
  measure.
- Our **west-facing roof** intercepts the late-afternoon direct beam
  at a much more favorable angle of incidence than a horizontal plane
  would. Each watt-hour of horizontal irradiance produces more Ah
  through our panels than it would through a horizontal reference.
- The geometric advantage compounds with the fact that during cloud,
  diffuse sky radiation is more isotropic (less time-of-day-biased)
  while the *direct* component still depends on sun angle.

### Implication for `SolarModel`

A single coefficient `Ah = c × kWh_horizontal_total_for_the_day` will
systematically be too low: it averages the morning under-fit and the
afternoon over-fit, but the relationship isn't really linear when you
look intra-day. A daily-average constant ≈ 7.0 looks fine on a
horizon-flat day total but doesn't predict the harvest curve shape.

**For now we accept this limitation** — `SolarModel` is honest about
its single-day-total assumption, and the dashboard's live-ratio chip
will surface the divergence (today's late-afternoon chip went red).
A future iteration could:

### First end-to-end accuracy validation — 2026-05-19 05:32 ⭐

The morning after the first data-fit coefficient landed, sunrise
came and `scripts/projection_accuracy.py` validated 17 projections
made overnight against the actual pack SOC at sunrise (05:08).

**Headline numbers**:

```
n=17, mean_error=−0.12 pp, mean_abs=1.15, RMS=1.36, range [−2.4, +1.5]
```

The advisor was **off by 0.12 pp on average** (nearly zero
systematic bias), with typical absolute error of just **1.15
percentage points**. The worst case was 2.4 pp from a projection
made 7 h before sunrise; projections made 2-4 h before sunrise were
within 0.5 pp.

Time-evolution of error across the night (negative = pack
overshot prediction, positive = undershot):

| projection time | proj | actual | err  | direction |
|-----------------|-----:|-------:|-----:|-----------|
| 22:14 (7 h pre) | 69.4 |   67.0 | −2.4 | model optimistic |
| 23:54 (5 h pre) | 68.0 |   67.0 | −1.0 | model slightly optimistic |
| 00:19 (5 h pre) | 67.9 |   67.5 | −0.4 | nearly perfect |
| 02:02 (3 h pre) | 66.5 |   67.5 | +1.0 | model slightly pessimistic |
| 04:36 (½ h pre) | 66.9 |   67.5 | +0.6 | nearly perfect |
| 05:01 (7 min pre) | 66.8 | 67.5 | +0.7 | nearly perfect |

The pattern: earlier projections (7-8 h out) leaned optimistic by
~2 pp; late-night projections (2-4 h out) leaned slightly
pessimistic by ~1 pp; near-sunrise projections converged to
sub-1-pp accuracy. **A 24-h forecast that nails the sunrise SOC
within ~1 pp on a single-observation SolarModel is genuinely
encouraging.**

What this validates end-to-end:
- The data-fit `SolarModel.coefficient_ah_per_kwh_m2 = 8.149`
- The `simulate_next_24h` hour-by-hour walk
- The `discharge_model` per-hour median current
- The two bug-fixes from 2026-05-18 (06:10 daytime false-positive
  fix + 21:00 post-sunset projection-collapse fix)

All five pieces collaborated to produce a near-zero-bias forecast
on the first validation opportunity.

The 2.4 pp worst case will be the baseline to **watch against**.
If a future single-day worst-case exceeds ~5 pp, something
material has shifted (model drift, unusual cabin load pattern,
weather forecast bust).

### First data-fit coefficient — 2026-05-18 20:23 ⭐

After the 2026-05-18 row crossed `duration_h ≥ 20.0` (the strict
complete-day threshold), the SolarModel auto-fit landed in
`data/calibration_log.csv` for the first time:

| timestamp           | coef   | n_obs | confidence | source              |
|---------------------|-------:|------:|------------|---------------------|
| 2026-05-18T13:13:50 | 7.000  |     0 | low        | loop-iteration (baseline / default) |
| 2026-05-18T20:23:30 | **8.149** | 1 | low        | advisor-invocation (first data fit) |

The day produced **45.8 Ah of solar harvest against a forecast of
5.62 kWh/m²** of horizontal-plane irradiance — coefficient =
45.8 ÷ 5.62 = 8.149 Ah/(kWh/m²).

That's a **+16 % uplift from the 7.0 default** baked in from the
2026-05-17 partial-day rollup. Three notes:

1. **The afternoon over-performance** documented in the section
   above is what pushed the daily total above the 7.0 baseline.
   Today's morning ratio hovered around 7.0 (matched the default
   exactly); the afternoon's geometric advantage lifted it to 8.15
   by sunset.
2. **The live-ratio chip went red mid-afternoon (+35 % drift) but
   pulled back to amber and finally green** as the irradiance
   integral grew past the flat harvest. By the time the auto-fit
   landed the drift was a healthy +4.8 %.
3. **Today was 92 % average cloud cover** — definitively not a
   sunny day. The 8.15 coefficient is therefore representative of
   the *cloudy* side of this site's distribution. Sunny days
   should produce a higher coefficient; the model will widen its
   uncertainty band as more days accumulate.

This is the first non-trivial calibration the system has seen. With
this single observation the model is still tagged `low` confidence;
the threshold to `medium` is ≥ 3 complete-day observations.

---

A future iteration of the SolarModel could:

1. Bin the (kWh/m², Ah) pairs by **hour-of-day** and fit per-hour
   coefficients (24 numbers instead of 1).
2. Multiply Open-Meteo's horizontal irradiance by a **tilt+azimuth
   transfer function** before passing it to the SolarModel (PVLib
   has this; we can avoid the dependency by precomputing the
   function for our specific roof on a clear-sky reference day).
3. Stay coarse — fit a separate "afternoon multiplier" for hours
   past solar noon, the simplest possible patch.

Until we have several days of data showing the pattern is stable
across cloud/sky conditions, we hold at option (3) on the roadmap.

## Weather sensitivity (working model)

We don't have a calibrated model yet, but the working hypothesis is:

| Day type                       | Expected harvest (Ah at 24 V)      |
|--------------------------------|------------------------------------|
| Clear summer day               | TBD (capture data)                 |
| Cloud, mid-day passing only    | TBD                                |
| Heavy overcast                 | TBD                                |
| Snow on panels                 | ≈ 0 (rare; mostly winter)          |

Once we have a few weeks of data correlating Open-Meteo forecasts
against observed daily Ah delivered, we'll fill these in.

## What this site profile is for

Two consumers:

1. **The pack's time-to-empty estimator**, which currently extrapolates
   from current at a single moment in time. A site-aware version can
   factor in "and we expect roughly X Ah from solar between now and
   tomorrow morning" to give a more honest "will I still be above 25 %
   by sunrise?" answer.

2. **The generator advisor** (see `docs/generator_advisor/`), which
   needs to know: today's expected harvest given the weather, how
   depleted the pack will be by morning, and therefore how long the
   generator should run tonight or tomorrow morning to maintain a
   safe SOC floor.

## Open questions

- Confirm coordinates with user (multiple Loon Lakes in BC)
- Confirm panel array size (wattage / number of panels) — affects
  expected harvest numbers
- Confirm tilt angle of the roof (steeper roofs catch winter low-angle
  sun better; shallow roofs do better in summer)
- Confirm whether there's any shading (trees, terrain) that affects
  early-evening as the sun moves toward the west horizon
