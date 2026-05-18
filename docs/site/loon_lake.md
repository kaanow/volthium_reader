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
| Fridge compressor (cycle)                  | + ~8 A pulse, peak -8.4 A | **10–55 s ON every ~34 min** (textbook fridge interval) | Detector threshold tuned from -10A to -8A on 2026-05-18 to capture these properly. |
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
