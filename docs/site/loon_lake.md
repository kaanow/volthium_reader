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
