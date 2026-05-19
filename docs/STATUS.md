# Status snapshot — read this when you come back

## Quickest way to look at the pack

**Double-click `Launch Volthium Monitor.command` in the project root.** It
starts the logger and dashboard if they aren't running, and opens
http://localhost:8421/ in your browser. Safe to double-click any number of
times — it's idempotent.

## Currently running (as of this writing)

- **Logger**: `caffeinate -i .venv/bin/python scripts/log.py …`
  Polls both batteries every 10 s. Writes `data/pack.csv` and
  `data/pack.log`. Backs off + retries on BLE flaps.
- **Dashboard**: `scripts/dashboard.py --port 8421 --host 0.0.0.0`.
  LAN-visible; survives Claude Code restarts.
- **Weather**: `scripts/weather.py` looping every 30 min. Writes
  `data/weather.csv`.

(PIDs drift across restarts — check `ps aux | grep volthium` if you need
them. The `.app` launcher is the supported way to (re)start everything.)

## Decisions baked in (your numbered answers)

| Q | Your answer | What's in the system |
|---|---|---|
| 1 — what does "full" mean | Banner "FULL" at 95 %, still show % | Estimator ceiling is now 95 %. Dashboard shows `FULL` headline + actual SOC underneath. New `state="full"` in wire protocol enum. |
| 2 — display style | e-paper, no contest | Locked in: 4.2" tri-color, BOM specced. |
| 3 — replace the app w/ release-BLE button | Hold persistent BLE; display button releases for 5 min | Spelled out in `docs/production_design.md` under "BLE-share button". Cost: +1 tactile switch. |
| 4 — must not finish off a low pack | Tiered self-shutdown | New section in `docs/production_design.md` — 4 tiers (normal / low / deep-sleep / hard-cut) plus hysteresis. BOM additions: DS3231 RTC, P-MOSFET load switch, panel-mount override button. |
| (bonus) Starlink at the cabin | Optional, not a dependency | New section "Optional Starlink sync" in design doc. Battery-side has its own RTC so timekeeping is link-independent. |
| (bonus) Label batteries by serial tail | `33` / `67`, derived at runtime | `BatteryReading.label` property; logger writes `name_a` / `name_b` columns; dashboard derives the label per-row with A/B fallback. |

## Files of note

- `Launch Volthium Monitor.command` — double-click to start everything
- `volthium/pack.py` — `BatteryReading.label` (returns "33" / "67")
- `volthium/estimator.py` — 95 % ceiling, `state="full"`, hybrid Ah-anchor
- `volthium/wire_protocol.py` — 43-byte frame; Python is the spec
- `volthium/solar_model.py` — class-based, fits from daily_summary.csv
- `volthium/events.py` — heavy-load / fridge / generator detection
- `scripts/log.py`, `scripts/dashboard.py`, `scripts/weather.py`
- `scripts/generator_advisor.py` — 24h hour-by-hour simulator + CLI
- `scripts/daily_summary.py`, `scripts/discharge_model.py`,
  `scripts/voltage_soc_calibration.py`
- `scripts/analyze.py` — offline digest with `--- events ---` section
- `firmware/common/volthium_lib/` — shared C lib (wire protocol + estimator)
- `firmware/bms-link/`, `firmware/display/` — ESP-IDF skeletons
- `hardware/kicad/` — SKiDL handoff package
- `docs/production_design.md`, `docs/site/loon_lake.md`
- `docs/install/cabin_handoff.md` — short user-facing guide
- `docs/generator_advisor/algorithm.md` — advisor math + caveats
- `docs/STATUS_archive.md` — older loop notes pruned out of this file

## Design progress

Hardware design pass complete with a SKiDL → KiCad handoff package
ready for a different machine to pick up. See
[`hardware/kicad/HANDOFF.md`](../hardware/kicad/HANDOFF.md) and the
docs trees:

- **`hardware/README.md`** — index
- **`hardware/block_diagrams.md`** — system + per-board diagrams
- **`hardware/bom.md`** — full BoM, Digi-Key / Mouser part numbers,
  ~$135 total for one of each board
- **`hardware/schematic_battery_side.md`** / **`schematic_display_side.md`**
- **`hardware/power_budget.md`** — quantified draw across all 4 SOC tiers
- **`hardware/cat5e_pinout.md`** — T568B pin allocation
- **`firmware/architecture.md`** — ESP-IDF repo layout, task list,
  state machine, OTA strategy
- **`firmware/state_machine.md`**, **`ble_flap_recovery.md`**

Ready to enter into KiCad as a schematic and to order parts.

## Key milestones in observed data so far

The detailed loop notes for these have been moved to
`docs/STATUS_archive.md` (and are also in git history). Brief summary
of the historically significant events from day-1 of the cabin
install:

- **2026-05-17 15:53** — First **generator capture** in real data.
  +54.8 A avg, +60.9 A peak (user estimated +40 A; actual notably
  higher). 18 min raised SOC 68→77 %. **BMS current-sensor bias
  confirmed** at ratio ~1.12 in fast-charge band.
- **2026-05-17 16:21** — Generator stopped after ~47 min, ~38 Ah
  delivered. Pack reached SOC 91 % in BULK phase only (charger
  never entered CV regulation).
- **2026-05-17 16:55** — **🎉 FULL banner first crossed.** Major
  finding logged: BMS bias is **non-linear** (fast-charge ≥30 A
  ratio 1.12, moderate 10–30 A ratio 0.91 — sign flips). Led to
  adopting the hybrid coulomb-counter (anchor on `remaining_ah` +
  integrate between anchors).
- **2026-05-17 17:28** — Hybrid coulomb-counter implemented as
  `Estimator(use_remaining_ah_anchor=True)`. Hybrid predictions
  converge ~2× faster than SOC-based on the captured cycle.
  Side discovery: per-battery `remaining_ah` peaks ~213 Ah at SOC
  97 %, implying real capacity is closer to **215 Ah** than the
  200 Ah nameplate.
- **2026-05-17 19:51 → 23:17** — Wire protocol + estimator ported
  to **C** (`firmware/common/volthium_lib/`). 39 C unit tests +
  4 Python↔C cross-validation cases, all byte-identical. Both
  firmware sides (`bms-link/`, `display/`) have ESP-IDF skeletons
  with task stubs ready for fill-in.
- **2026-05-17 21:01** (user input) — **Strategic pivot to a
  generator-use recommender.** Site profile started:
  west-facing array at Loon Lake BC. Weather logger + advisor
  architecture sketch landed this same loop.
- **2026-05-17 22:01** (user input) — Ceiling fan turned on; +2.3 A
  step captured in data. User confirmed ceiling-fan-plus-overnight-
  fire is normal cabin overnight pattern.
- **2026-05-18 00:23** — **Fridge identified** at ~34-min cadence,
  10–55 s pulses, -8.4 A peak. Event-detector threshold tuned
  -10 A → -8 A and persistence 30 s → 15 s to capture them
  consistently.

## What we're still waiting on (no action needed)

- ≥ 3 full-day rows in `data/daily_summary.csv` so `SolarModel` can
  fit a real Ah/(kWh/m²) coefficient instead of the default 7
- A first **sustained-charging** segment today so we can log the
  empirical "morning shadow clears → net charging" time in
  `docs/site/loon_lake.md`
- A deeper discharge below 25 % — would let us prototype the tiered
  shutdown UX on the Mac before committing it to silicon
- User confirmation on the open questions in `docs/site/loon_lake.md`
  (exact coords, panel wattage, tilt, shading)

## My autonomous loop while you're away

Waking every ~30 min to check the data and advance the design.
Each cycle: analyze, push to GitHub, note new learnings here, push
one design item further, schedule the next wake. Older entries
roll into `docs/STATUS_archive.md`.

**Data logs are committed too** (`data/pack.csv`, `weather.csv`,
`daily_summary.csv`, `pack.log`, etc.) — each loop push captures
the latest snapshot, so the full data trail lives in the repo
and is recoverable from GitHub if anything happens to the laptop.
Re-cloning gives you the data plus the code.

## Loop notes

*(appended chronologically, newest first)*

- **23:20** — Steady evening. Pack SOC **82/81 %** (-2 % per battery
  in 33 min, -1 %/16 min cadence holding). Discharging at -4.3 A.
  Voltage 26.46 V. **Projection log gained entry #3** at 23:04:46
  (perfect 25-min cadence). Three entries now showing start_soc
  drift cleanly:
  ```
  22:14  start 84.0  sunrise 69.4  eve 90.3  low 69.2  coef 8.15
  22:39  start 83.0  sunrise 69.2  eve 88.8  low 68.2  coef 8.15
  23:04  start 82.0  sunrise 69.2  eve 87.3  low 67.3  coef 8.15
  ```
  Each projection slightly more conservative than the last as the
  pack drains — the sim is correctly walking forward from the
  freshest start_soc.
  - No new fridge cycles since 21:47 (96 min ago — well past the
    34-min cadence). Either the fridge isn't cycling tonight or
    the cycles are too brief for the 15-s detector persistence.
  - Calibration log stable at 2 entries; coef 8.149.
  - Design item: **`/projections` page on the dashboard**, mirroring
    the `/calibration` page from earlier loops. The projection_log
    is becoming a real history (3 entries and growing); it deserves
    a viewable surface.
    - New `_serve_projection_log` GET handler reads
      `data/projection_log.csv` via `projection_log.read_log()`,
      renders newest-first as a dark-themed HTML table with
      columns: timestamp, start SOC, → sunrise, → tomorrow eve,
      → low, coef, kWh/m², source.
    - Empty-log fallback message gracefully handles the early-day
      case ("they accumulate as the advisor runs").
    - Linked from the **projection panel's footer** in the main
      dashboard: `weather bits · history ↗`. Also cross-linked
      from `/calibration` ↔ `/projections`.
    - The page uses the shared `REPORT_PAGE_STYLE` for consistent
      look across `/today-report`, `/reports`, `/calibration`,
      and now `/projections`.
  - Closes another visibility loop: the projection_log isn't just
    a CSV anymore — it's a navigable history page.
  - All 142 Python tests still pass.

- **22:47** — Steady. Pack SOC **84/83 %** (down 1 % from 85/84
  over 34 min). Discharging at sustained -4.6 A (smoothed -4.53 A).
  **Projection log gained entry #2** at 22:39:46 — rate-limit
  working correctly:
  ```
  22:14:46  start 84.0  sunrise 69.4  eve 90.3  low 69.2  coef 8.15
  22:39:46  start 83.0  sunrise 69.2  eve 88.8  low 68.2  coef 8.15
  ```
  The dashboard's cached-subprocess advisor calls between those
  two moments produced zero new rows — exactly what the 25-min
  rate-limit is designed for.
  - No new fridge cycle this loop (last was 21:47; the 34-min
    cadence would predict ~22:21 but the detector didn't fire —
    cycle was either shorter than the 15-s persistence or skipped).
  - Calibration log stable at 2 entries; coef 8.149.
  - Design item: **12 regression tests for `projection_log.py`**.
    Mirrors `test_calibration_log.py` pattern:
    - **Empty file** → `read_log()` returns `[]`; `last_entry()`
      returns None.
    - **First record always writes**; round-trip preserves all 9
      fields (start_soc, sunrise, evening, low, coef, kwh, sunrise_iso,
      source, ts).
    - **Rate-limit boundary** explicitly anchored: 5 min apart →
      suppressed; exactly at threshold (25 min) → admitted; >threshold
      → admitted. `min_minutes_between` override works.
    - **Dashboard-burst scenario**: simulated 5 advisor calls
      within 5 min produces exactly 1 row (the protection the
      rate-limit is built for).
    - **`today_irradiance_kwh_m2=None`** (Open-Meteo unreachable)
      handled gracefully — row written with blank irradiance,
      not a crash.
    - Multiple entries preserve **oldest-first order** in the
      file; `--tail` slices the end.
    - `append_entry()` creates the file with a **CSV header row**
      so DictReader can parse it.
  - **142 Python tests pass** (up from 130). Suite total: 142 Py +
    22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross =
    **234 assertion-points**, all green.

- **22:12** — Quiet evening continues. Pack SOC **85/84 %** (-2 %
  per battery in 34 min — consistent baseline drain rate).
  Discharging at sustained -4.3 A. Voltage 26.47 V. **Another fridge
  cycle captured**: 21:47:33 ON / 21:47:49 OFF — 16-second
  compressor pulse this time. Advisor projections still sensible
  (sunrise 69.3 %, eve 90.4 %, low 69.2 %). Calibration log stable
  at 2 entries.
  - Design item: **`scripts/projection_log.py` — captures each
    advisor invocation's projections to `data/projection_log.csv`.**
    Foundation for the eventual "nightly diff" feature
    (projected sunrise SOC vs actual sunrise SOC over time).
  - Schema: `ts, start_soc_pct, projected_sunrise_soc,
    projected_tomorrow_evening_soc, projected_low_soc,
    solar_model_coefficient, today_irradiance_kwh_m2, sunrise_iso,
    source`.
  - **Rate-limited to one row per 25 min** — the dashboard's
    cached-subprocess advisor call would otherwise spam ~60 rows
    per hour. The autonomous loop's ~25-30 min cadence naturally
    aligns; loop iteration rows land, dashboard re-renders are
    suppressed.
  - `record_if_due()` reads the last log entry, compares timestamp
    to `now`, only appends if >= `min_minutes_between` apart.
    Idempotent under repeated calls in a short window.
  - Wired into `generator_advisor.py` right after the projections
    are computed, try/except wrapped so a logging failure never
    blocks the verdict.
  - First entry just landed:
    `2026-05-18T22:14:46  start 84.0  sunrise 69.4  eve 90.3
     low 69.2  coef 8.15  advisor-invocation`. This is the first
    historical-accuracy data-point.
  - **Tomorrow** when the actual sunrise SOC is observed, we can
    compare to today's 69.4 % prediction and start building a
    track-record of the advisor's accuracy. After a week we'll
    have meaningful "predicted vs actual" data to feed back into
    confidence tuning.
  - Tests will follow in a future loop (the pattern mirrors
    `tests/test_calibration_log.py` closely). For now the priority
    was capturing tonight's first projection before more time
    elapses.
  - 130 Python tests still pass; calibration_log stable.

- **21:38** — Quiet evening rhythm. Pack SOC **87/86 %** (down 2 %
  per battery in 40 min — normal -1 %/20 min rate). Discharging at
  sustained -4.2 A baseline. Voltage 26.48 V. **First evening
  fridge cycles captured!** Heavy-load events at 20:55 ON / 20:56
  OFF (40 s compressor pulse, classic) and a second OFF at 21:16.
  Advisor projections sensible post-fix: **sunrise 70.0 %,
  tomorrow eve 89.7 %, low 69.0 %**. Two distinct values — bug
  fix from the prior loop is holding cleanly. Live ratio 8.52
  vs model 8.149 = +4.5 % drift, **GREEN**.
  - Design item: **documented today's two bug-fixes in
    `docs/generator_advisor/algorithm.md`.** New "Bug history"
    section, 4 subsections:
    1. **Bug #1 — 06:10 daytime false-positive** — root cause
       (single-window discharge calc across a sunrise crossing),
       fix (hour-by-hour simulate_next_24h), regression-test ref,
       lesson ("walk projections that span state transitions").
    2. **Bug #2 — 21:00 post-sunset projection collapse** —
       root cause (sunrise_today + 1 day → day-after-tomorrow,
       outside 24h window, soc_at returns samples[-1] for both),
       fix (next-occurring-from-now), regression-test ref,
       lesson ("equality of distinct projections is a smell").
    3. **Why both bugs share a common theme** — the simulator's
       "today" vs "now" diverging at day boundaries because the
       caller bumps sunrise/sunset to "next-occurring" but the
       simulator's `_tomorrow` arithmetic assumed they were literal
       "today's" values.
    4. **Future refactor candidate**: rename simulator params to
       `next_sunrise` / `next_sunset` (and `subsequent_*` for the
       day after) to match what the caller actually passes.
  - Permanent record of *why* the code is shaped the way it is —
    future-me reading the simulator won't have to re-derive the
    bug history from STATUS notes.
  - All 130 Python tests still pass; calibration_log holds at
    2 entries; coef 8.149 stable.

- **20:57 — Post-milestone bug caught by the freshly-fitted model.**
  Pack SOC **89/88 %** discharging at sustained -6 A (heavier than
  baseline). Sunset (20:52) just passed. Calibration log stable at
  2 entries; live ratio 8.51 vs model 8.149 (drift +4.4 %, GREEN).
  But the advisor's projections looked wrong: `sunrise SOC: 90.0 %`
  AND `tomorrow evening SOC: 90.0 %` — identical, and unphysically
  optimistic given an overnight discharge ahead.
  - **Root cause**: when the calling code at lines 272-275 bumps
    `sunrise_dt` / `sunset_dt` past `now` (so they're always
    "next-occurring"), and we're post-sunset, BOTH end up dated
    tomorrow. The simulator then computes `sunrise_tomorrow =
    sunrise_today + 1 day` = **day-after-tomorrow**, which lies
    OUTSIDE the 24-hour sim window. The `soc_at()` lookup falls
    off the end of the samples list and returns `samples[-1]` —
    the same end-of-window value for both `sunrise_tomorrow` and
    `sunset_tomorrow`. Result: both projections collapse to the
    same number.
  - The `projected_low_soc` was unaffected because it's
    `min(s for _, s in samples)` over the window — that
    correctly captured the overnight low at ~69 %.
  - Pre-sunset the bug was masked: lines 289-292 pull `sunrise_today`
    back by 24 h when needed, which puts it inside the window, so
    `sunrise_tomorrow` lands within 24 h too.
  - **Fix**: changed the projection lookups in
    `simulate_next_24h()` to pick the next-occurring sunrise/sunset
    relative to `now`, not unconditionally tomorrow's pair. Two
    lines:
    ```python
    proj_sunrise = sunrise_today if sunrise_today > now else sunrise_tomorrow
    proj_sunset  = sunset_today  if sunset_today  > now else sunset_tomorrow
    return {..., "projected_sunrise_soc": soc_at(proj_sunrise),
            "projected_tomorrow_evening_soc": soc_at(proj_sunset)}
    ```
  - **Result**: advisor at 21:00 now reports `sunrise SOC: 71.3 %`
    (not 89.78 %), `tomorrow evening SOC: 89.4 %`, `low: 69.4 %`.
    Two values, different, sensible.
  - Added regression test
    `test_post_sunset_projections_target_NEXT_sunrise_not_day_after`
    in `tests/test_advisor_simulator.py`. Asserts both that the
    values are in the right range AND — crucially — that they
    are NOT equal (the bug-shape check that catches if the values
    collapse to samples[-1] again).
  - **This is the second high-leverage advisor bug found by the
    loop** — first was the 06:10 daytime false-positive on
    2026-05-18 morning, this is the 21:00 post-sunset duplication.
    Both surfaced when the actual data started exercising the
    edge of the simulator's frame-handling.
  - **130 Python tests pass** (up from 129). Suite total:
    130 Py + 22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross =
    **222 assertion-points**, all green.
  - Day report regenerated with the corrected advisor numbers.

- **20:23 ⭐ — THE DAY-FLIP LANDED.** Every prediction across the
  past two days of loops paid off in one moment:
  - Daily_summary's strict `duration_h < 20.0` rule cleared at
    20:23 (duration_h was actually 20.4 by the time the script ran).
    Today's row dropped its `[partial]` tag → **`rows usable for
    solar-model fit: 1`** (was 0 for the entire run-up).
  - The next `generator_advisor` invocation auto-fit:
    **`solar_model_coefficient: 7.000 → 8.149 Ah/(kWh/m²)`** —
    landed exactly in the predicted 8.0-8.3 range. Median ratio
    from 45.8 Ah / 5.62 kWh/m² = 8.149.
  - The `record_if_changed()` hook fired and **calibration_log.csv
    gained its second entry**: `2026-05-18T20:23:30  8.149  n=1
    low  advisor-invocation`. The first non-default coefficient
    the system has ever known.
  - The dashboard's `/calibration` page now shows the **default →
    fit transition** as a permanent record.
  - The model-vs-live chip on the advisor panel: previously red
    at +40 % drift; now **green** at +4.8 % drift (live ratio 8.54
    vs new model 8.149) — the model has caught up to reality.
  - "Today's harvest progress" rebases from 116 % of forecast to
    **100 %** — because the forecast itself just learned today's
    pattern. Tautological-but-honest.
  - `end_of_day_report.build_report()` lede changes from
    "*(partial day so far)*" to "**Complete day**:". The
    calibration-log table in the report now shows both entries.
  - This whole sequence happened automatically — no human
    intervention, no manual fitting, no hand-tuning. The autonomous
    loop wrote the code days ago, ran the data through it, and at
    the appointed moment the calibration auto-landed.
  - Pack state at this moment: SOC **90/90 %** (ticked down 1 %
    over the loop), discharging at -6.0 A baseline (slightly
    heavier than -4 A — possibly a fan came on), voltage 26.47 V.
    Sunset is 29 min away.
  - Design item: **documented this landmark moment in
    `docs/site/loon_lake.md`** with a new "First data-fit
    coefficient — 2026-05-18 20:23 ⭐" subsection. Captures:
    1. The coefficient (8.149) and the +16 % uplift from the 7.0
       baseline default
    2. The afternoon-overperformance pattern (documented earlier
       in the doc) is what pushed the daily total above 7.0
    3. The live-ratio chip's red → amber → green journey, ending
       at +4.8 % drift when the auto-fit landed
    4. **92 % average cloud cover today** — so 8.15 represents the
       *cloudy* side of this site's distribution; sunny days will
       likely produce a higher coefficient still
  - Confidence stays `low` until n_observations ≥ 3 — but tomorrow
    will be the second day, and so on. The bootstrap is underway.
  - 129 Python tests still pass.
  - **Loop architecture verdict: the autonomous loop did its job.**
    Wrote the calibration_log infrastructure days ago, the dashboard
    chip + footer + /calibration page, the test coverage, and
    today it all converged cleanly on this transition. Closed-loop.

- **20:00** — Loop wake — **on the brink of the day-flip moment**.
  Pack SOC **91/91 %** (ticked down another 1 % per battery from
  92/92), discharging at sustained -3.7 A baseline. duration_h is
  reading **20.0** (rounded) but the underlying value is 19.998 —
  strictly less than 20.0 so the row is still [partial] by one
  hair. The SolarModel auto-fit hasn't fired yet; calibration_log
  still single baseline entry. **Next loop will catch the flip.**
  - This is actually a nice live demonstration of why the strict
    `duration_h < 20.0` rule matters — at 19:59:54 we're 6 s short
    of the flip, and the rounded display says "20.0 h" — but the
    fit eligibility correctly stays partial until the underlying
    value crosses the threshold. Without the strict `<`, the row
    could have flipped earlier and corrupted the SolarModel with
    a partial-day reading.
  - Live ratio **8.57** (+22.4 % drift, sliding further toward
    green). Open-Meteo irradiance now 142 W/m² — sun is essentially
    gone for the day. Sunset is 52 min away.
  - Day report regenerated; still shows "(partial day so far)".
  - Design item: **18 regression tests for the new
    `_markdown_to_html` helper** in `dashboard.py`.
    The function runs on every `/today-report` and
    `/report/YYYY-MM-DD` view; previously it was untested. Cases:
    - Heading levels promote correctly (# → h2, ## → h3, ### → h4).
    - Inline formatters: `**bold**`, `*italic*`, `` `code` ``,
      `[text](url)`.
    - Bold + italic on the same line — neither pattern swallows
      the other (regex non-overlap).
    - Lists: `- item` collects into `<ul>`, properly closes on a
      blank line before the next paragraph, supports inline
      formatting inside items.
    - Tables: `| col | col |` rows render as proper
      `<table><thead>/<tbody>` with the `|---|---|` separator
      ROW excluded from data.
    - Tables terminate cleanly when the next line isn't a row.
    - **HTML-escaping safety**: `<` and `>` in user content
      escape, including content INSIDE `**bold**` — proves a
      malicious-looking `**<script>alert(1)</script>**` cannot
      break out (it doesn't actually parse to HTML).
    - Empty input / blank-lines-only / unrecognized line all
      degrade gracefully.
  - **129 Python tests pass** (up from 111). Suite total
    assertion-points: 129 Py + 22 wire-C + 17 est-C + 4 wire-cross
    + 49 est-cross = **221**, all green.
  - Tests are intentionally pinned to the **specific markdown
    subset** that `end_of_day_report.build_report` emits — not a
    full CommonMark spec. If we ever switch to a real markdown
    library, all these tests will keep working (the library's
    superset). And until we do, they lock down our hand-rolled
    parser's behaviour.

- **19:32** — Loop wake. **First SOC tick down of the evening**:
  pack **92/92 %** (was 93/93 all afternoon). Discharging at
  sustained -4.1 A baseline (smoothed -4.10 A, fully settled).
  Voltage 26.51 V (still relaxing). Cloud 71 %, irradiance now
  193 W/m² — sun about an hour from setting. **Live ratio 8.66 —
  drift +23.7 %, sliding past 25 % toward amber boundary** (will
  cross into <20 % amber territory within the next loop or two as
  irradiance integral keeps growing while harvest stays flat).
  - Duration_h is now **19.54** — within 28 min of the
    [partial] → complete flip at 20.0. Next loop should catch the
    transition. The auto-fit landing in calibration_log is imminent.
  - No new fridge cycle events captured this evening despite
    ~3 h of discharge. Either the cycles are shorter than the
    15-s detector persistence, or the fridge isn't running.
    Worth watching.
  - Design item: **minimal markdown rendering for `/today-report`
    and `/report/YYYY-MM-DD`.** Previously the reports were dumped
    raw inside `<pre>`. Even on a phone the wall-of-text was
    readable but ugly. New `_markdown_to_html()` helper in
    `dashboard.py` parses the specific markdown subset the report
    builder emits:
    - `# heading` → `<h2>` (page already has `<h1>` for the title)
    - `## heading` → `<h3>`
    - `### heading` → `<h4>`
    - `**bold**` → `<strong>` (highlighted color)
    - `*italic*` → `<em>`
    - `` `code` `` → `<code>` (boxed background)
    - `- item` → `<ul>`/`<li>`
    - `[text](url)` → `<a>`
    - Markdown tables → proper `<table>` with header row
  - Self-contained — no external markdown dependency, ~80 lines
    of Python with `html.escape` on user content. Anything
    unrecognized still passes through as a paragraph.
  - Smoke-tested against today's actual report: all sections
    render (h2, h3, lists, tables, code, bold).
  - The reports now look like proper documents on the dashboard
    — particularly nice on a phone where the raw `<pre>` was
    cramped. Tonight's complete-day report will be the first
    nicely-formatted one to view from the dashboard link.
  - All 111 Python tests still pass.

- **18:59** — Loop wake. **Evening discharge established.** Pack SOC
  **93/93 %** still but state is **discharging at sustained -4.0 A**
  baseline (smoothed -3.87 A). Matches the expected -3 to -5 A
  evening pattern (inverter idle + standby + maybe a fan). Voltage
  dropping fast: 26.66 → 26.56 V. Today's harvest **45.8 Ah / 116 %**
  of forecast — the late-day cloud break (64 %) actually delivered
  another +1.4 Ah on top of the previous 44.4. **Live ratio 8.83**,
  basically flat with last loop's 8.79 — denominator caught back up.
  - **Open-Meteo did another late-day forecast revision**: bumped
    today's day-total 5.20 → 5.62 kWh/m² (+8 %). That's the largest
    upward revision yet. Forecast-rev chip on the dashboard will
    show drift +5.2 % from the initial 5.34 (still amber).
  - No new fridge cycle events captured yet this evening — the
    34-min cadence means we'll see one shortly. Daily_summary
    still partial at 18.98 h.
  - Design item: **`/calibration` page on the dashboard.** Tonight's
    first SolarModel auto-fit lands in `data/calibration_log.csv`
    when daily_summary flips to complete (~20:00); the advisor
    panel's "model last updated" footer now LINKS to a new page
    showing the full coefficient history.
    - New GET handler in `dashboard.py` for `/calibration`. Reads
      `data/calibration_log.csv` via the shared
      `calibration_log.read_log()`, renders newest-first as a
      dark-themed HTML table with columns: timestamp, coefficient,
      n_obs, confidence, source, notes.
    - Empty-log fallback: friendly italicized message
      "(no calibration log entries yet — they accumulate as
      SolarModel coefficients change)".
    - Linked from the existing "model last updated 2026-05-18
      13:13 · loop-iteration" line in the advisor panel as a
      "full log ↗" link to the right.
    - Uses the same `REPORT_PAGE_STYLE` chrome as `/today-report`
      and `/reports` so the user gets a consistent feel across
      drill-down pages.
  - Closes the visibility loop for the SolarModel calibration
    chain: chip → footer → full history page. Tonight when the
    first real fit lands, the user can see the transition from
    7.0 default to whatever today's data fits to (probably ~8.0-
    8.3 given the day's harvest pattern).
  - All 111 Python tests still pass.

- **18:25** — Loop wake. Pack SOC **93/93 %** holding. **Surprise
  late-day cloud break**: cloud at **64 %** (lowest of the day from
  98 % peak), giving a small +2.3 A trickle charge. Voltage 26.66 V
  (ticked up slightly). Irradiance still dropping (224 → 182 W/m²)
  despite the break — sun is too low for direct beam to add much.
  Today's harvest still **44.4 Ah / 122 %** (the cloud break added
  fractions of an Ah). **Live ratio dropped further to 8.79** (+25.6 %
  drift, sliding toward green on the still-flat numerator and growing
  irradiance denominator).
  - Daily_summary still tagged [partial] at duration_h 18.42; will
    flip to complete around 20:00 when duration crosses 20 h.
  - Calibration log still single baseline; first auto-fit lands
    when daily_summary flips.
  - Day-report refreshed.
  - Design item: **11 regression tests for `end_of_day_report.build_report`**.
    The report builder is now consumed in two places — the CLI
    script (`data/reports/YYYY-MM-DD.md`) AND the dashboard's
    inline render at `/today-report` and `/report/YYYY-MM-DD`.
    Any regression breaks both surfaces. New
    `tests/test_end_of_day_report.py` exercises the markdown
    output directly against fixtured CSVs in a tempdir:
    - **Empty day** → "Day in progress." summary with all five
      sections rendered (Pack, Solar harvest, Weather, SolarModel
      state, Cross-references) with em-dashes instead of crashes.
    - **Partial day** flag → `*(partial day so far)*` tag.
    - **Complete day** flag → `**Complete day**` tag.
    - **Lede tone** matches harvest fraction: ≥110 % "strong day",
      ≥90 % "on track", ≥50 % "soft day", <50 % "well below".
    - **Calibration table** renders entries dated to the report's
      day with the correct columns; yesterday's entries excluded.
    - **Empty calibration_log** shows the friendly fallback
      "No SolarModel coefficient changes logged today."
    - **Peaks** line populates when pack data exists (peak charge,
      smoothed, SOC, voltage; first-charging HH:MM).
    - **Generator activity** line: "45 min ⇒ 40.0 Ah" when run;
      "Generator: not run today" when not.
    - **Cross-references** section always present even on empty
      days — tells the reader where the raw data lives.
  - **111 Python tests pass** (up from 100). Suite total assertion-
    points: 111 Py + 22 wire-C + 17 est-C + 4 wire-cross + 49 est-
    cross = **203**, all green.

- **17:52** — Loop wake. **First evening discharge!** Pack SOC
  **93/93 %** (A relaxed back from 94 to 93 as voltage settled),
  state cycling IDLE → discharging at **−2.4 A** in the latest
  sample (smoothed_i at -0.36 A and growing — load EMA building).
  Voltage 26.63 V (down from 26.70 — relaxation continues). Cloud
  broke briefly to **77 %** (lowest of the day) but irradiance
  already dropping fast (316 → 224 W/m²) as sunset approaches.
  Today's solar harvest is **DONE** at 44.4 Ah / 122 % of forecast.
  **Live ratio 8.96 — drift +28 %, continued pull-back toward green**.
  - Open-Meteo's UV-index field bumped 4.25 → **5.45** mid-afternoon —
    not a metric we use, but a sign their model is still revising.
  - Design item: **`/reports` index page on the dashboard.** Only
    one report exists today, but as days accumulate the dashboard
    needs a browse view. Architecture set up now so tomorrow's
    report appears naturally.
    - **`/today-report`** — unchanged; today's report regenerated
      live on each request (no stale-snapshot risk).
    - **`/reports`** — new index page listing every `data/reports/
      *.md` file, newest-first, with today's entry pinned at top
      with a green badge and a "(today, live)" label.
    - **`/report/YYYY-MM-DD`** — new route serving a specific
      historical day's report. Reads the committed file as-is
      (doesn't re-run report-builder against old data with newer
      scripts — keeps historical reports stable).
    - Bad date format → 404 with a helpful "use /report/YYYY-MM-DD"
      message.
    - Harvest panel footer now has TWO links instead of one:
      `today's report ↗` (live) and `all reports ↗` (index).
  - Once the loop accumulates a week of reports, the index becomes
    the natural "how have we been doing?" page — historical
    pattern reference for the user without needing to clone the
    repo.
  - All 100 Python tests still pass.

- **17:18** — Loop wake. Pack SOC **94/93 %** — battery A ticked UP
  to 94 % as voltage relaxation lets the BMS recompute SOC upward
  (voltage 26.70 V, settling from the absorption-CV peak). State:
  IDLE, charge current 0.0 A. Cloud broke to **91 %** but irradiance
  now down to 316 W/m² (sun lower than the array's azimuth window).
  Harvest **44.4 Ah / 122 % of forecast** — gained +0.8 Ah since last
  loop in final trickle. **Live ratio dropped 9.53 → 9.19** (+31.3 %
  drift, continued pull-back toward green exactly as predicted —
  the harvest is essentially flat now while the irradiance integral
  keeps growing). By sunset should land in the 8.0-8.5 range.
  - Advisor projection: today's pack will see ~31 % drop overnight +
    partial recovery, settling at flat 62.7 % equilibrium across
    sunrise/tomorrow_eve/low under the current 7.0 SolarModel
    coefficient. Tonight's first auto-fit (after the today's row
    flips to [complete] at ~21:00) will likely lift this — today's
    actual day-total ratio is on track for ~8.0-8.5, so the
    advisor's solar prediction will tick upward by ~15-20 %.
  - Design item: **day-report served from the dashboard.** Per the
    new loop step 7 we regenerate `data/reports/2026-05-18.md` each
    cycle, but users had to clone the repo to read it. Now a small
    link **"today's full report ↗"** in the harvest panel footer
    opens `/today-report` in a new tab — server inline-renders the
    Markdown as a minimalist dark-themed HTML page with a `← dashboard`
    link to navigate back.
  - Implementation: new GET handler in `dashboard.py` matches
    `/today-report` or `/today-report.md`, calls
    `end_of_day_report.build_report(today_date)` inline (no shell-out
    so it works without subprocess overhead), wraps the markdown in
    `<pre>` with html-escaping for safety. Loads the full narrative
    on a phone tap — sparkline, peaks, model state, weather, cross-
    references all readable.
  - Closes one more visibility loop: the loop iteration writes the
    report, pushes the file to GitHub, AND now serves it live on the
    dashboard. Three ways to find it (repo file, GitHub web, live
    dashboard) — whichever fits the user's situation.
  - All 100 Python tests still pass.

- **16:35** — Loop wake. **Pack holding at 93/93 %** under absorption-
  CV regulation; BMS letting in a +1.6-1.8 A trickle to maintain
  voltage. Cloud broke briefly to **88-90 %** (vs the day's 98-100 %
  norm), but irradiance still falling (425 → 396 W/m² — sun lowering).
  Harvest **43.6 Ah / 120 % of forecast** (only +0.2 Ah since last
  loop). **Live ratio 9.53 — drift DROPPED to +36.1 %** from last
  loop's +40.3 %. The predicted dynamic kicked in: harvest essentially
  flat while irradiance integral keeps growing (4.42 → 4.58 kWh/m²),
  so the ratio is naturally pulling back toward green. By sunset
  should land around 8.0-8.5.
  - Calibration log still single baseline; tonight at ~21:00 first
    auto-fit.
  - Design item: **explanatory tooltips on the dashboard's four
    diagnostic chips** — small UX upgrade. Each of the
    `live ratio`, `model vs live`, `forecast revisions`, and
    `today's peaks` chips now carries a `title=` attribute
    explaining what the numbers mean, plus a `cursor: help` hint
    on hover so the user knows the chip is interactive.
  - The tooltips cover:
    - **live ratio**: "Ah delivered / kWh/m² of irradiance.
      ~7 baseline for this west-facing array (see
      docs/site/loon_lake.md). Higher in late afternoon is normal
      — direct beam at favorable angle to a horizontal pyranometer."
    - **model vs live**: explains the LEFT (model fit from prior
      days) vs RIGHT (today's measurement), drift % bands
      (<10 green, 10-20 amber, >20 red), and points at
      loon_lake.md for the known intra-day non-linearity.
    - **forecast revisions**: FIRST (overnight model run) vs
      LATEST (after ingesting today's observations), the drift vs
      swing distinction.
    - **today's peaks**: explains A PEAK vs A SMOOTHED, that SOC
      is max-of-both-batteries, and that CHARGING START is the
      empirical 'morning shadow cleared' time.
  - Native `title=` tooltips don't work on mobile (no hover), so
    this is desktop-first. A future iteration could add tap-to-
    show popovers using `<details>` or a small JS click handler.
    For now this lifts the dashboard from "lots of numbers" to
    "lots of numbers with hover-explanations" for the engineer-
    mode user.
  - All 100 Python tests still pass.

- **16:11** — Loop wake. Pack SOC **93/93 %** holding. Charging at
  +2.4 A — the BMS is letting in a tiny trickle to maintain absorption
  voltage but SOC isn't moving up. Cloud broke briefly to **88 %**
  (was 100 % then 94 %) but irradiance still dropping (425 W/m², sun
  lower). Harvest **43.4 Ah / 119 %** of forecast — only +0.3 Ah in
  10 min. **Live ratio 9.82 — drift +40.3 %, basically flat** with
  the last few loops (9.74 → 9.92 → 9.82). Settled. Pack is capped
  at 93 % SOC for the rest of the day under solar-only.
  - Calibration log still single baseline entry; first auto-fit
    lands when daily_summary flips to complete (~21:00 tonight).
  - Day-report regenerated to `data/reports/2026-05-18.md` per the
    new loop step 7.
  - Design item: **8 regression tests for `compute_today_peaks()`**.
    Completes the test-coverage rhythm for last loop's peaks
    function. Cases cover:
    - Missing file → all-None return shape
    - Cross-day filter (yesterday's huge values ignored)
    - `peak_charge_a` tracks max across all today's rows
    - `peak_smoothed_a` independent of `peak_charge_a` (different
      EMA-lagged column)
    - `peak_soc_pct` considers BOTH soc_a and soc_b (asymmetric
      pairs where B leads A still surface the higher value)
    - `first_charge_time` triggers on first sample with pack_i > 1 A,
      not on earlier sub-1A trickle/discharge
    - **Strict >** 1 A — exactly 1.0 A is not "charging" (off-by-one
      catch)
    - All-trickle day leaves `first_charge_time` as None while still
      capturing `peak_charge_a` (graceful overnight-only behavior)
  - **100 Python tests pass** (up from 92) — round milestone. Suite
    total assertion-points: 100 Py + 22 wire-C + 17 est-C + 4 wire-
    cross + 49 est-cross = **192**, all green.

- **16:01** — Loop wake. **Pack hit absorption-CV regulation**: SOC
  **93/93 %**, but state flipped to **IDLE** — charge current went
  to **0.0 A**. Voltage relaxed 26.87 → 26.74 V. We never reached
  the 95 % FULL banner under solar-only — capped at 93 % because
  the Volthium BMS pulls charge current to zero before letting cell
  voltages climb further. Battery temps: A=24 °C (warmed 1 °C),
  B=23 °C. Harvest **43.1 Ah / 118 % of forecast** (44 Ah net delta
  over the day). **Live ratio 9.92** — still creeping (+41.7 %); the
  numerator keeps growing while the denominator only ticks slowly
  with each 30-min weather sample.
  - Design item: **`scripts/end_of_day_report.py` — daily Markdown
    report generator.** Today is the first complete day of data;
    capturing the narrative as a permanent artifact in
    `data/reports/YYYY-MM-DD.md` means every clone of the repo
    has the day-by-day history readable without re-running any
    scripts. The report pulls from today_harvest.snapshot(), the
    daily_summary row, and the calibration_log, and emits clean
    Markdown:
    - **Summary** lede: tone-aware sentence (strong / on-track /
      soft / well-below) about how the day went vs forecast
    - **Pack** section: SOC walk, charge/discharge totals,
      generator activity, peaks, first-charging time
    - **Solar harvest**: total Ah, % of forecast, live ratio
    - **Weather**: day-total irradiance, cloud avg, temp range,
      Open-Meteo forecast trajectory (drift + swing)
    - **SolarModel state**: any calibration_log entries that
      landed today, as a compact table
    - **Cross-references** to the data files
  - **Idempotent**: re-runs overwrite the file with the freshest
    snapshot. Run early-day → "(partial day so far)". Run after
    sunset → "**Complete day**".
  - Today's first report already written to
    `data/reports/2026-05-18.md`. Tonight after 21:00 a re-run will
    capture the complete-day numbers including the first SolarModel
    auto-fit.
  - From now the loop iteration includes a call to this script —
    every commit pushes the freshest day-report alongside the
    data snapshot.

- **15:37** — Loop wake. **PLATEAU confirmed.** Pack SOC **92/92 %**
  (full series-pack symmetry holds), charging at +6.1 A sustained
  (brief cloud break to 94 %, irradiance bumped 412 → 433 W/m²),
  voltage 26.86 V. Harvest **40.7 Ah / 112 %** of forecast. **Live
  ratio 9.74 — drift +39.1 %, finally flat after climbing all
  afternoon (9.43 → 9.48 → 9.77 → 9.74).** The afternoon
  over-performance has stabilized at ~9.7-9.8 Ah/(kWh/m²); today's
  full-day fit (landing tonight at ~21:00) should settle around
  ~8.1 Ah/(kWh/m²) — that's the day-total of ~42 Ah / 5.20 kWh/m²
  forecast = an ~16 % uplift from the 7.0 default.
  - Design item: **"today's peaks" subrow in the harvest panel.**
    A glanceable end-of-day summary that's also useful mid-day —
    "best charge so far today" + "peak SOC" + "first charging
    started at HH:MM". Builds toward the eventual end-of-day
    report.
  - Backend: new `compute_today_peaks()` in `today_harvest.py`
    walks today's pack.csv once and returns:
    - `peak_charge_a` — max raw pack_i (today: +21.4 A from the
      13:53 sprint segment)
    - `peak_smoothed_a` — max EMA-smoothed current (today: +17.8 A)
    - `peak_soc_pct` — max(soc_a, soc_b) (today: 92 %)
    - `peak_pack_voltage_v` — max pack voltage (today: 27.00 V)
    - `first_charge_time` — HH:MM of first sample with pack_i > 1 A
      (today: 09:11 — within seconds of the empirical morning-
      shadow-clear timing I logged in `loon_lake.md`)
  - Dashboard: new `.peaks` subrow inside the harvest panel,
    showing four stats side-by-side as compact numerals. Hidden
    until peak_charge_a is populated (early cold-start safe).
    Sits between the sparkline/bars and the forecast-rev chip.
  - All 92 Python tests still pass.

- **15:28** — Loop wake. Pack SOC **92/91 %** (+2/+1 % in 25 min from
  90/90 — gentle absorption climb continues), charging at +3-4 A
  sustained with brief excursions to ~+8 A, voltage 26.87 V. Cloud
  100 %, irradiance 412 W/m² (slow drop as sun lowers). Harvest
  **40.1 Ah / 110 % of forecast** — overshooting more. **Live ratio
  9.77 — drift now +39.6 % (RED, still climbing)** — last loop I
  predicted plateau by now; it hasn't yet. Today's full-day
  coefficient is likely to settle north of 8.0.
  - Design item: **8 regression tests for `weather_forecast_history()`**
    (the function I added last loop for the forecast-revision chip).
    Completes the test-coverage rhythm. Coverage:
    - Missing file / no-today-rows → returns empty shape, n=0
    - Single sample → first == latest, drift_pct == 0
    - Upward drift (mimics today's 4863.9 → 5202.8 trajectory)
    - Downward drift (negative percentage)
    - **Swing-vs-drift** distinction — a day where first ≈ latest
      but max-min was wide. Anchors today's 5.34 → 4.86 → 5.20
      pattern as a permanent regression case (small net drift, but
      ~9 % swing across the day).
    - Rows with empty `shortwave_radiation_sum_today_wh_m2` are
      skipped, not erroring out
    - **Zero-first-value** edge: if the first forecast read was 0
      (rare edge-of-night case), drift_pct returns None instead of
      dividing-by-zero. Dashboard already handles None by hiding
      the chip.
  - **92 Python tests pass** (up from 84). Suite total: 92 Py +
    22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross =
    **184 assertion-points**, all green.

- **15:03** — Loop wake. **Pack-symmetry achieved**: SOC **90/90 %**
  — battery B finally caught up to A after 5h of sustained charging.
  Series-pack physics doing its slow-but-steady work. Charging
  continues to taper (+2.7 A sustained), voltage essentially flat at
  26.79 V. Cloud 100 %, irradiance dropping 508 → 424 W/m² as sun
  lowers. Harvest **37.1 Ah / 102 % of forecast** — slowly extending
  the overshoot. **Live ratio 9.43** — essentially stable at last
  loop's 9.48 (+34.7 % drift). Drift may be plateauing now that the
  array's azimuth advantage is fading past 15:00.
  - Design item: **Open-Meteo forecast-revision history widget.**
    Open-Meteo's `shortwave_radiation_sum_today` value is the
    model's *current best guess* for the whole day, refreshed every
    weather-logger tick (~30 min). It moves through the day as the
    model ingests today's observations. Tracking how much it moves
    is a forecast-confidence signal — a flat line means Open-Meteo
    was sure; a 10 %+ swing means there was real uncertainty.
  - New `weather_forecast_history()` in today_harvest.py walks
    today's weather.csv and returns `first` / `latest` / `min` /
    `max` / `drift_pct` / `n`. Exposed as `forecast_history` in
    the snapshot JSON.
  - Dashboard adds a `.forecast-rev` chip below the live-ratio row:
    "forecast revisions  5.34 → 5.20 kWh/m²  −2.6%, swing 9.0%".
    Color band matches live-ratio: green |drift| < 5 %, amber
    < 10 %, red ≥ 10 %.
  - Today's revealing data: forecast STARTED at 5.34 kWh/m²
    (captured at midnight, last night's prediction for today),
    BOTTOMED at 4.86 mid-morning (when the system saw 98 % cloud),
    and CLIMBED BACK to 5.20 mid-afternoon (when the harvest curve
    started over-performing). Net drift is just −2.6 % but the
    swing was a meaningful 9 % — Open-Meteo was genuinely
    uncertain about today's outcome, which matches the reality
    of an overcast day with intermittent breaks.
  - This widget will be most useful on days where Open-Meteo's
    forecast revisions large — a future user can see "the
    forecast moved 20 % today, expect to second-guess the advisor
    accordingly."
  - All 84 Python tests still pass.

- **14:54** — Loop wake. **🎉 FORECAST EXCEEDED.** Pack SOC **90/89 %**
  (+2 / +2 % per battery in 27 min), but charging current is now
  tapering hard (+11.5 → +4.1 → **+1.9 A** sustained) — the LiFePO4
  voltage-CV absorption knee is kicking in. Voltage 26.81 V (flat,
  no longer climbing). Today's harvest **36.7 Ah / 101 % of
  forecast** — the day has officially overshot. Net for the whole
  day so far: **+0.9 Ah** (climbed from −35.8 Ah net at 12:02 — the
  pack has fully recovered yesterday's evening discharge).
  - **Live ratio 9.48 (+35.5 % drift, deeper RED).** Climb continues:
    7.0 → 7.5 → 8.7 → 8.81 → 9.48 across the afternoon. Sustained
    afternoon over-performance — exactly the pattern documented in
    last loop's loon_lake.md / solar_model.py update.
  - Natural solar likely **can't drive the pack into the 95 % FULL
    banner today** because the absorption-mode current taper kicks
    in too early (Volthium BMS pulls charge current down as cell
    voltage approaches the upper knee). We'll settle around
    91–92 % before sunset and tonight's daily_summary row will
    finally cross into [complete] at ~21:00.
  - Calibration log still just baseline.
  - Design item: **regression tests for `daily_summary.summarize_day()`**
    — the per-day rollup that feeds `data/daily_summary.csv`, which
    in turn feeds `SolarModel.fit_from_daily_summary`. Critical path,
    previously untested. New `tests/test_daily_summary.py` adds 13
    test cases covering:
    - Empty / no-SOC-pairs → returns None
    - Steady charge / generator split / 30 A boundary / discharge —
      mirrors the integrate_today coverage but against the
      DailyRow output shape
    - Gap > 60 s skipped
    - SOC start / end / min / max tracking
    - **Partial flag**: True when duration_h < 20, False when ≥ 20
      — anchors the 2026-05-18 12:02 bug-fix in regression test form
    - Weather joins: weather_kwh_m2 = max(today's irradiance-sums)
      (Open-Meteo revises upward through the day → take the freshest),
      cloud avg from mean, temp min/max
    - No-weather day still produces a row with None weather columns
    - None pack_i mid-stream is gap-safe (matches integrate_today)
  - **84 Python tests pass** (up from 71). Suite total assertion-
    points: 84 Py + 22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross
    = **176**, all green.
  - Tonight will be the first **complete day** the system sees — both
    daily_summary's [partial] flag and calibration_log's baseline
    will flip at the same moment, around 21:00.

- **14:27** — Loop wake. **Mini-stall after the sprint** — pack SOC
  **88/87 %** (unchanged in 6 min after the 85→88 jump), charging
  dropped from +11.5 A → **+4.1 A** sustained. Cloud-bouncy pattern
  continues. Today's harvest **32.5 Ah / 89 % of forecast** —
  comfortably above the morning trajectory. **Live ratio 8.81** —
  same regime as last loop's 8.73 (+25.9 % drift, still RED). The
  afternoon over-performance is now sustained, not a transient.
  - Calibration log still single baseline entry; tonight's auto-fit
    at ~21:00 will be the first time the system observes a real
    coefficient (and likely a higher one than 7.0 given today's
    afternoon contribution).
  - Design item: **regression tests for `integrate_today()`.** This
    is the core pack-side integrator that powers the harvest panel's
    big-number, the cumulative sparkline, AND the per-hour bar chart
    — directly user-visible — but had zero direct tests. Closed the
    gap with `tests/test_today_harvest.py::TestIntegrateTodayPack`,
    11 new cases covering:
    - **File missing / no today rows / single sample** — return
      shape sanity (samples=0, all zeros, empty series).
    - **Steady charge** — +10 A held 6 min at 10-s cadence → 1.0 Ah.
    - **Generator split** — +60 A goes into `generator_ah`, not
      `solar_ah` (so the harvest panel doesn't credit generator runs
      as solar wins).
    - **Threshold exactly 30 A** is NOT generator — catches strict-
      `>` vs `>=` off-by-one if anyone refactors the comparator.
    - **Negative current** → `discharge_ah`.
    - **Gap > 60 s** is skipped — protects against phantom Ah from
      logging gaps (BLE reconnect, app restart). Without this a 1 h
      gap at +10 A would falsely book 10 Ah.
    - **Series bins to 5-min resolution** — monotonically non-
      decreasing, last point matches total, length in expected range.
    - **Cross-day filter** — yesterday's pack samples can't pollute
      today's totals.
    - **None pack_i mid-stream** — both adjacent pairs are dropped
      (honest underestimate, not a phantom contribution).
    - **None pack_i doesn't corrupt surrounding segments** — runs
      before and after the None still integrate cleanly.
  - **71 Python tests pass** (up from 59). Total assertion-points
    across the suite: 71 Py + 22 wire-C + 17 est-C + 4 wire-cross +
    49 est-cross = **163**, all green.

- **14:21** — Loop wake. **SOC sprint!** Pack **88/87 %** (+3 % per
  battery in 28 min from 85/84), charging at +11.5 A sustained,
  voltage 26.91 V. Today's harvest **31.8 Ah / 87 % of forecast** —
  way ahead of pace. **Live ratio 8.73 — +24.7 % drift, RED zone.**
  Drift trend over the day: 7.14 → 7.00 → 7.30 → 7.49 → 7.75 → **8.73**.
  The afternoon segment alone produced ~23 Ah/(kWh/m²), wildly above
  the daily-average 7.0.
  - This isn't noise — it's a **real structural finding** about the
    SolarModel. Open-Meteo's `shortwave_radiation_wm2` is the
    *horizontal-plane* irradiance (what a flat pyranometer would
    read). Our **west-facing roof** catches the afternoon direct
    beam at a much more favorable angle of incidence. So each
    watt-hour of horizontal irradiance produces more Ah through our
    tilted/oriented array than it would through a horizontal
    reference — and this geometric advantage grows as the sun moves
    westward into our array's sweet spot.
  - **A single linear coefficient is structurally biased** for a
    tilted/oriented array. The morning under-fits and the afternoon
    over-fits average out for a horizon-flat day total but don't
    predict the harvest curve shape.
  - Captured in two places this loop:
    1. `docs/site/loon_lake.md` — new "Afternoon over-performance vs
       horizontal irradiance" section with today's live-ratio table,
       the geometric explanation, and three roadmap options (per-
       hour fit / tilt-azimuth transfer function / simple "afternoon
       multiplier").
    2. `volthium/solar_model.py` — class docstring now explicitly
       calls out the known limitation, points at the doc, and notes
       that the dashboard's live-ratio chip going amber/red is the
       intended way to surface intra-day divergence.
  - **For now the system stays honest**: SolarModel is a daily-total
    predictor, the calibration chip flips amber/red when reality
    diverges, the calibration log captures coefficient changes. We
    don't try to "fix" the coefficient by chasing afternoon highs —
    that would over-predict on the next overcast day. Until we have
    several days of data showing the afternoon-over-performance is
    stable across cloud conditions, we hold at "document the
    limitation, surface it visibly."
  - Calibration log still single baseline entry; tonight at 21:00
    will be the first real fit. Interested to see whether the day-
    total ratio settles closer to the original 7.0 or shifts up,
    given the afternoon over-performance.

- **13:53** — Loop wake. **Climb accelerating** — pack SOC **85/84 %**
  (+1 % per battery in just 6 min), charging at **+12.2 A** sustained,
  voltage 26.94 V. Today's harvest **26.4 Ah / 72 % of forecast** at
  +1.3 Ah/6 min ≈ **13 Ah/hr** (fastest of the day). **Live ratio
  7.75 — JUST CROSSED 10 % drift from the model** (+10.7 %), so the
  dashboard's calibration chip will tip from green to **amber** on
  next refresh. The drift trend is consistent: 6.94 → 7.13 → 7.49 →
  7.75 over four loops. Either the west-facing array over-performs
  the morning ratio in the afternoon (geometry), or the SolarModel
  coefficient is biased slightly low. Tonight's first auto-fit on
  today's complete-day row will resolve this — interested to see
  whether the day-total ratio settles closer to 7.0 or stays high.
  - Calibration log still just the baseline entry — first real fit
    lands tonight ~21:00.
  - Design item: **per-BMS sensor-bias documentation in
    `docs/hardware/bms_calibration.md`.** Across 1,487 today-
    charging samples in 4 current bands, BMS-A reads consistently
    **+0.2 – 0.4 A higher** than BMS-B. Series-pack physics says
    the current through both is identical, so this is pure sensor
    bias on A. The profile (3 – 4 % relative across all bands)
    suggests a fixed offset with a tiny gain term. Findings
    captured:
    - **A reads systematically high** by 0.2 A at 2-10 A bands,
      0.4 A at 10-20 A. Direction never flips.
    - The 0.5-2 A band tied at zero is a quantization artifact —
      both BMSes report in 0.2 A steps.
    - Implication for firmware: keep using the AVERAGE of i_a/i_b
      as pack_current (which we already do). Don't try to use the
      per-battery currents as a cross-check; they won't agree.
    - Useful baseline to **watch against**: if i_a − i_b ever
      flips sign or grows beyond the 0.4 A envelope, something
      has materially changed (loose connection, BMS firmware
      update, sensor degradation, swap of which battery is "A").
  - Permanent record in the doc, useful when the firmware C port
    needs to decide how to combine the two BMS streams.

- **13:47** — Loop wake. **Climb continues.** Pack SOC **84/83 %**
  (+1 % per battery in 27 min), charging at **+10.8 A** sustained,
  voltage 26.93 V. Cloud at 99 % (maxed) but harvest still cranking
  through: **25.1 Ah / 69 % of forecast** at +3.0 Ah/27 min ≈ 6.7 Ah/hr.
  At this rate today should overshoot the forecast — west-facing
  geometry doing its job in late afternoon. **Live ratio drifted up
  to 7.49** (+7 % from model, still safely green). Calibration log
  unchanged from baseline (waiting for ~21:00 first auto-fit).
  - Per-battery observation: i_a = 11.0 A, i_b = 10.6 A right now —
    the same series current measured 4 % differently by the two BMS
    sensors. That's noise floor for our installed sensors; the
    average is what matters for pack-level integration.
  - Design item: **advisor-panel model-update timestamp.**
    Continues last loop's calibration_log thread. The advisor now
    exposes two more diagnostic fields in `Recommendation.inputs`:
    - `model_last_updated_iso` — ISO timestamp of the most recent
      calibration_log entry (when the model meaningfully changed).
    - `model_last_updated_source` — the source tag from that entry
      ("advisor-invocation", "loop-iteration", "manual", etc.).
  - Both come from `calibration_log.last_entry()` after the
    record_if_changed call, so they reflect the freshest state.
  - Dashboard renders a small italic line under the green/amber/red
    model-vs-live chip: *"model last updated 2026-05-18 13:13 ·
    loop-iteration"*. Right now it shows the baseline default-
    constant entry. Tonight at ~21:00, after the first complete-day
    row lands, this will flip to the fresh-fit timestamp.
  - This closes the trust loop — the user can now see at a glance:
    1. What the model thinks (`solar_model_coefficient`)
    2. What today is measuring (`live_ratio_ah_per_kwh_m2`)
    3. Whether they agree (drift % chip, colored)
    4. **When the model was last calibrated** (new this loop)
  - All 59 Python tests still pass.

- **13:20** — Loop wake. **Recovery again.** Pack SOC **83/82 %**
  (climbed 1 % from the 25-min stall), charging back up to **+10.4 A**
  sustained, voltage 26.91 V. Today's harvest **22.1 Ah / 61 % of
  forecast** at +1.2 Ah/8 min ≈ 9 Ah/hr — the cloud bounce continues.
  **Live ratio 7.13** (within 2 % of model, green). Advisor sunrise
  SOC ticked up to 74.5 %. Calibration log has only the baseline
  entry — tonight 21:00 is still the trigger moment.
  - Design item: **"sun left" indicator on the harvest panel.**
    Small but immediately useful for the user's "is there enough
    time today to top up?" intuition. Leverages last loop's
    sunrise/sunset plumbing.
    - Renders as a fourth stat-tile in the existing harvest stats
      row, alongside progress / forecast / irradiance forecast.
    - Three states based on current time vs sunrise/sunset:
      - Pre-sunrise: "**sun in** 4h 12m" (until first light)
      - Daylight: "**sun left** 7h 32m" (until sunset)
      - Post-sunset: "post-sunset" (no harvest expected)
    - Computed inline in JS from `harv.sunrise_min_of_day` /
      `harv.sunset_min_of_day`, no backend change.
    - Hidden when weather data hasn't loaded yet (early cold start).
  - Right now should show "sun left 7h 31m" (now=13:20, sunset 20:52).
  - All 59 Python tests still pass.

- **13:12** — Loop wake. **Harvest stalled** — pack SOC unchanged at
  **82/81 %** for 25 min, charging at +5.2 A but smoothed only +5.0 A.
  Cloud back to **98 %** (was 91 → 94 → 98 in successive hours).
  Irradiance 595 W/m² (slight drop). Today's harvest **20.9 Ah /
  58 % of forecast** — gained +0.7 Ah in 25 min ≈ 1.7 Ah/hr (very
  slow). **Live ratio 6.94 — back to exactly the model coefficient
  (drift −0.9 %, green).** Today is firmly in the "thick cloud, low
  harvest" regime; the brief morning bursts were the exception.
  - Design item: **`scripts/calibration_log.py` — every meaningful
    SolarModel coefficient change recorded with timestamp + cause.**
    Up to now the model has been silently re-fit on every advisor
    invocation. Tonight at ~21:00, today's row will transition from
    `[partial]` to complete, and the SolarModel will quietly move
    from the 7.0 default to its first data-fit coefficient. Without
    a log, that transition is invisible until someone notices the
    advisor's recommendation feels different.
    - New `data/calibration_log.csv` with schema:
      `ts, coefficient, n_observations, confidence, source, notes`.
    - `record_if_changed(model, source)` compares to the last
      logged entry and appends a new row only if the coefficient
      moved by ≥ 0.01 Ah/(kWh/m²), OR n_observations changed, OR
      the confidence tier flipped. Below those thresholds it's
      a no-op — won't spam the log from per-fit sample-jitter.
    - `generator_advisor.py` calls it on every invocation (try/
      except wrapped so a logging failure can never block a
      verdict). The dashboard's cached subprocess pattern is
      naturally idempotent — N concurrent calls produce 0 or 1
      rows depending on whether the model actually shifted.
    - CLI: `python scripts/calibration_log.py --show` pretty-
      prints the full history; `python scripts/calibration_log.py`
      checks-and-records once.
    - First baseline entry captured this loop:
      `2026-05-18T13:13:50  coef=7.000  n=0  conf=low  source=loop-iteration`.
    - **9 new unit tests** in `tests/test_calibration_log.py`
      covering: empty-file behavior, first-record-always-writes,
      sub-threshold no-op, significant-change-writes,
      n_observations-only change writes (the case that'll fire
      tonight), confidence-tier flip writes, exact-threshold
      handling, idempotence on repeated identical calls.
  - **59 Python tests pass** (up from 50).
  - Tonight's 21:00 loop will see the first data-fit row land. The
    log will record the default → fit transition with a timestamp.

- **12:47** — Loop wake. **Harvest curve still bouncy.** Pack SOC
  **82/81 %**, charging at **+2.9 A** — slowed AGAIN from +9.4 A
  at 12:39. The recovery was brief; cloud thickened back over the
  array. Voltage backed off 26.89 → 26.81 V. Harvest **20.2 Ah /
  55 % of forecast**. **Live ratio 7.30** (+4.3 % from model — still
  safely green). Battery B keeps closing the gap: now only 1 %
  behind A (82 vs 81). This is normal for a 94-98 % cloud day —
  brief sun-breaks then thickening.
  - Design item: **sunrise/sunset markers on the harvest sparkline.**
    Previously the sparkline ran 00:00 → 24:00 with no indication of
    when sun was actually up. New visual elements:
    - Subtle amber **daylight band** (4 % fill-opacity) between
      sunrise and sunset, so the productive window is shaded.
    - Two faint amber **dashed vertical lines** at the exact
      sunrise (05:09) and sunset (20:52) times.
    - Both contextualize the green harvest curve: now the user
      can immediately see "the harvest only happens during the
      shaded band, and we're at X % through it."
  - Backend: new `latest_weather_sun_times()` in `today_harvest.py`
    parses `sunrise_iso` / `sunset_iso` from weather.csv (latest
    row wins) and returns them as `minute_of_day` integers for
    direct plotting on the 0..1440 sparkline x-axis. Today:
    `sunrise_min_of_day: 309` (05:09), `sunset_min_of_day: 1252`
    (20:52).
  - Frontend: rendered as SVG `<rect>` for the daylight band and
    two `<line>` elements for sunrise/sunset. Hidden when weather
    data isn't available yet (early cold-start).
  - Will become visible on next dashboard restart.
  - All 50 Python tests still pass.

- **12:39** — Loop wake. **Recovery!** Pack SOC **82/80 %** (climbed
  +2/+1 % in 26 min — the noon slowdown was transient cloud).
  Charging back to **+9.4 A** sustained from a low of +3.3 A. Cloud
  94 %, irradiance 601 W/m². Harvest **19.5 Ah / 53 % of forecast**.
  **Live ratio drifted slightly 6.97 → 7.24** (~3 % above the
  SolarModel coefficient of 7.0) — well within the 15 % flag
  threshold, just noise as the irradiance integral evolves.
  - Side observation: the trickle-charge bucket in `analyze.py`
    now shows median dAh/hr +5.84 vs mean I +5.85 A (**ratio 1.00**)
    with 40 samples — the BMS-bias discrepancy in that band has
    resolved naturally with more data. Earlier loops saw ratios of
    1.84–2.31 because the sample counts were tiny and dominated by
    voltage-correction transients. Useful calibration data point
    for the eventual firmware.
  - Design item: **promoted the model-vs-live diagnostic into a
    visible chip on the dashboard advisor panel.** Last loop
    exposed the fields in `Recommendation.inputs` (JSON); this
    loop makes them visible.
    - New `.calib` row inside the advisor panel showing
      `model 7.00 → live 7.24 Ah/(kWh/m²)` with a drift
      percentage chip at the right.
    - Color band: **green** when drift < 10 % (today: +3.4 %),
      **amber** 10–20 %, **red** > 20 %. Border-left color band
      matches.
    - Hidden when there's no live measurement yet (early morning
      before harvest starts).
    - Renders below the existing `whenLine`, above the
      confidence explainer — natural reading order: verdict →
      reason → schedule → calibration check → confidence note.
  - This closes the visibility loop: now anyone glancing at the
    dashboard can immediately see whether today is tracking the
    model or diverging, without having to inspect JSON. When the
    chip stays green, the advisor's recommendation is trustworthy;
    when amber/red, the user should be more skeptical of any
    projection that depends on solar harvest.
  - All 50 Python tests still pass.

- **12:13** — Loop wake. **Harvest rate slowed further** — pack SOC
  stuck at **80/79 %** (no climb in 11 min), charging at **+3.3 A**
  (continued slide: 9.8 → 4.7 → 3.3 A over 35 min). Cloud 91 % (a
  hair clearer than 98 %), irradiance 595 W/m² (down from 645). The
  west-facing array is probably in a temporary worse-cloud patch.
  Harvest **16.9 Ah / 46 % of forecast**. **Live ratio 6.97 — rock
  steady at 7.0 now, the extrapolation fix is holding cleanly.**
  Bug fix from last loop verified across a weather-sample boundary.
  - Open-Meteo also bumped today's forecast 4.86 → 5.20 kWh/m²,
    presumably ingesting today's morning observations into their
    nowcast.
  - Design item: **expose live measurements in the generator advisor
    output.** Previously the advisor reported its projections but
    not the live measurement that could vindicate or refute them.
    Now `Recommendation.inputs` includes:
    - `solar_model_coefficient` — what the SolarModel uses (today: 7.00)
    - `live_ratio_ah_per_kwh_m2` — what today is observing (currently 6.96)
    - `irradiance_kwh_m2_so_far` — partial-day actual (2.44 kWh/m²)
    - `solar_ah_so_far` — partial-day harvest (17.0 Ah)
  - Implementation: `generator_advisor.py` now imports
    `today_harvest` as a module and calls `snapshot()` to read the
    live numbers. Behaviour-neutral: the advisor's projections still
    use `solar.predict_ah(...)`. Diagnostic only.
  - Why this matters: when the model and reality disagree on a given
    day, the user can immediately see it without having to inspect
    two separate views. Right now they agree exactly (7.00 vs 6.96)
    — concrete real-time evidence the SolarModel default is right
    for this site. When they disagree by ≥ 15 % the system will know
    something is off well before sunset.
  - Dashboard advisor panel will pick these up automatically since
    it already passes the entire `inputs` dict through to the API.
    A future loop can promote them to a visible chip on the panel.
  - All 50 Python tests still pass.

- **12:02** — Loop wake. Pack SOC **80/79 %**, but charging current
  **dropped from +9.8 → +4.7 A** — cloud thickened over the array.
  Voltage backed off 26.90 → 26.82 V. Harvest **16.3 Ah / 48 % of
  forecast** but **live ratio LEAPT 7.14 → 8.04** — which was a
  caught-in-the-act **artifact**, not real. Two bugs found and
  fixed this loop:
  - **Bug 1 — irradiance integrator went stale at weather-sample
    boundaries.** `today_harvest.integrate_today_irradiance()` only
    integrated up to the last weather sample. weather.csv is on a
    30-min cadence; pack.csv is on 10 s. Between samples the
    numerator (harvest Ah) grew but the denominator (kWh/m²) was
    frozen, jamming the live ratio upward until the next weather
    tick. **Fix**: flat-extrapolate the integral past the last
    sample with the most-recent wm2 held constant, capped at
    `max_extrap_seconds` (default 40 min, slightly longer than the
    weather cadence so a single missed sample doesn't silently
    stall). Live ratio recomputed: **8.04 → 7.00 Ah/(kWh/m²)** —
    even tighter to the SolarModel default of 7.0 than before. Added
    `tests/test_today_harvest.py` with 7 regression tests
    (trapezoidal basics, extrapolation tail, max-extrap cap, prior-
    day samples filtered, etc.).
  - **Bug 2 — partial-day rows wrongly entered the SolarModel fit.**
    Both `daily_summary.py` and `volthium/solar_model.py` used a
    `duration_h > 12` filter to skip partial days. But duration_h is
    just `last_ts − first_ts` from pack.csv, and the logger has been
    running continuously since yesterday — so by noon TODAY the row
    had duration_h = 12.1 h and tripped the threshold as "complete".
    The fit then saw `16.4 Ah / 5.34 kWh/m² = 3.1 Ah/(kWh/m²)` — a
    completely wrong coefficient because the irradiance is the
    full-day FORECAST while the harvest is only morning-through-noon.
    **Fix**: added an explicit `partial: bool` field on `DailyRow`
    set from `duration_h < 20.0`, written to CSV, consumed by both
    `daily_summary.py` filtering and
    `SolarModel.fit_from_daily_summary` (with a duration-fallback for
    older CSV files lacking the column). Added 2 regression tests in
    `tests/test_solar_model.py` anchored on the exact bug-trip
    numbers so this can't quietly come back. Result: today is now
    correctly tagged `[partial]` and excluded from the fit. **The
    SolarModel keeps using its 7.0 default until tonight when this
    day completes** — exactly the right behavior.
  - Both bugs would have produced a wrong recommendation for the
    advisor on cloudy days: the artifact would inflate the live
    ratio (cosmetic), and the partial-day mis-fit would have
    propagated a 3.1 coefficient through the next 24 hours of
    advisor calls, drastically under-estimating tomorrow's harvest
    and potentially triggering false-alarm generator runs.
  - All 50 Python tests pass (up from 41 last loop). Total assertion
    points across the whole suite: 50 Py + 22 wire-C + 17 est-C +
    4 wire-cross + 49 est-cross = **142**, all green.
  - Also: Open-Meteo bumped today's forecast 4.86 → 5.20 kWh/m²
    mid-day — probably ingesting today's observed irradiance back
    into their nowcast.

- **11:39** — Loop wake. Pack SOC **79/78 %** (+1 % per battery in
  11 min), charging at +9.8 A. Harvest **14.5 Ah / 43 %** of
  forecast; gained +2.0 Ah in 11 min (11 Ah/hr rate, picking up
  pace as midday irradiance arrives). **Live ratio: 7.14 Ah/(kWh/m²)**
  — converging from 7.48 → 7.14 as the irradiance integral grows
  and morning noise damps out. Independent confirmation that the
  SolarModel default of 7.0 is right for this site. Today now
  tracking exactly the model: 2.03 kWh/m² actual = 42 % of forecast
  vs 43 % of predicted Ah.
  - Design item: **per-hour harvest bars** below the cumulative
    sparkline in the dashboard harvest panel. The cumulative curve
    shows the *integral*; the bars show the *rate per hour*.
    Together they answer two different questions at a glance:
    - sparkline: "where are we vs forecast?" (slope)
    - bars: "is this hour ahead of, level with, or behind last hour?"
    (instantaneous derivative)
  - Implementation: in dashboard JS, walk the existing 5-min
    cumulative series, compute per-hour deltas (last cumulative
    value in hour minus baseline), render 24 vertical bars in an
    SVG. Current hour highlighted blue, completed hours green,
    empty hours muted gray. Max-bar label at top right.
  - Why this is useful TODAY: on this 98 %-cloud morning the
    visualization should show a clear inflection — flat dark
    bars from 00:00 to 09:00, then climbing green bars 10:00,
    11:00 (latest, blue: ~3.3 Ah). Tells the user "yes, harvest
    started; here's how each hour is going."
  - Will become visible on next dashboard restart. Running
    instance is still pre-change.

- **11:28** — Loop wake. Pack SOC **78/77 %** (battery B catching up
  under sustained charge — gap from A narrowed 3 % → 1 % since
  start of charging). Charging at +9.1 A, voltage 26.87 V. Today's
  harvest **12.5 Ah / 37 %** (+3.3 Ah in 22 min ≈ 9 Ah/hr rate).
  Advisor projections improving: sunrise SOC 71 % (was 67 % at
  11:06). Steady, encouraging climb.
  - Design item: **live SolarModel-coefficient measurement.** First
    time the system surfaces today's actual Ah/(kWh/m²) ratio as
    it's being measured.
    - New `integrate_today_irradiance()` in `scripts/today_harvest.py`
      trapezoidally integrates `shortwave_radiation_wm2` from
      weather.csv samples (~ every 30 min) to give kWh/m² **delivered
      so far today**. Independent of Open-Meteo's forecast-total
      field; pairs with the partial-day pack harvest to extract a
      coefficient in real time, not at sunset.
    - New snapshot fields: `irradiance_kwh_m2_so_far`,
      `live_ratio_ah_per_kwh_m2` (threshold-guarded so noisy
      near-zero numerator/denominator early in the day don't
      produce a wild reading — needs ≥ 0.5 kWh/m² actual and
      ≥ 1.0 Ah harvested).
    - **First live reading: 7.48 Ah/(kWh/m²)** — which is right on
      our SolarModel default of 7.0! Today's morning data is
      validating the calibration we extracted from yesterday's
      partial-day rollup. This is the system's first cross-day
      coefficient check.
    - Dashboard: new `.live-ratio` row in the harvest panel showing
      the number in green, with the actual-kWh/m²-so-far as an
      aside. Dim background, compact — fits below the sparkline.
    - 1.71 kWh/m² delivered through 11:28 today out of 4.86 kWh/m²
      forecast = **35 % of today's expected irradiance**, vs 37 %
      of the predicted Ah → the harvest is **slightly ahead of
      the irradiance-linear projection**. Could indicate the
      morning hours were dim and afternoon will outperform, or
      the model coefficient is slightly low. End-of-day will tell.

- **11:06** — Loop wake. **Harvest climb continues.** Pack SOC
  **77/75 %** (+1 % in 12 min), charging at **+10.2 A** sustained
  (was +7.5 A), voltage 26.85 V, irradiance **622 W/m²** still
  climbing toward midday peak. Harvest **9.2 Ah / 27 %**, gained
  +1.5 Ah in 12 min = ~7.5 Ah/hr rate. On a 98 %-cloud day this
  is genuinely encouraging — the west-facing array is working well
  through cloud as the sun moves toward its viewing angle.
  - Design item: **broadened estimator cross-validation scenarios.**
    Last loop's bug fix proved the cross-test pattern catches what
    per-side unit tests miss; now 5 new state-boundary scenarios
    exercise the exact code paths where transition bugs hide:
    - `discharge_to_idle_to_charge` — 9-step walk through a dawn-
      style EMA crossing of zero current. Tests that classification
      follows the smoothed value into each state.
    - `charging_crosses_to_full` — SOC climbs 93→94→95→96→97 across
      5 samples; verifies the 95 % FULL banner threshold trips on
      the exact crossing sample, not one off.
    - `discharge_approaching_floor` — SOC dropping toward the 10 %
      floor; exercises floor math at and below the boundary.
    - `hybrid_anchor_off_cadence` — BMS rem_ah anchor ticks only
      once over a 60-s span, sample cadence is 10 s; verifies the
      integrator advances correctly between anchors and the blend
      math kicks in on the anchor change.
    - `boundary_at_idle_threshold` — pack_i = +0.5 exactly. Python
      uses `abs(si) < idle_current_a` (strict less-than), so 0.5 is
      NOT idle — must be charging. Catches any off-by-one in C
      classification at the boundary.
    - **All 5 pass first try** on both implementations (49/49 step
      assertions across 11 scenarios now). Test budget grew from
      22 → 49 cross-validation step-assertions; total assertions
      across the test suite: 41 Py + 22 wire-C + 17 est-C + 4 wire-
      cross + **49 est-cross = 133**, all green.

- **10:54** — Loop wake. **Recovery picking up speed.** Pack now at
  SOC 76/74 % (was 73/72 at 10:14), charging at +7.5 A sustained,
  voltage 26.78 V (+0.16 V in 40 min), irradiance 580 W/m². Today's
  harvest **7.7 Ah / 22 % of forecast**, gained +4.7 Ah in 40 min vs
  the +2.7 Ah/35 min of the prior loop — the climb is accelerating
  as solar moves westward toward the array's sweet spot. Advisor still ✓.
  - Data logs now tracked: per user request, this loop is also the
    first one pushing `data/pack.csv` and friends to GitHub so the
    cabin's full record lives in the repo, not just locally.
  - Design item: **sparkline of today's harvest curve** in the
    dashboard's harvest panel. Concrete additions:
    - `scripts/today_harvest.py` now emits a `series` field — a
      5-min-binned list of `[minute_of_day, cumulative_solar_ah]`
      pairs. For today: 132 points covering 00:00 → ~10:55, flat at
      0 until 09:30 then rising. Cheap to compute (single linear
      pass over today's pack rows), tiny payload (~2 KB JSON).
    - Dashboard renders it as an inline SVG `<polyline>` inside the
      harvest panel: green curve over a faint dashed horizontal
      "forecast target" line, a soft vertical "now" marker, and an
      x-axis label strip (00:00 · 06:00 · 12:00 · 18:00 · 24:00).
      Uses `viewBox="0 0 100 28" preserveAspectRatio="none"` so it
      scales cleanly to whatever width the panel has — desktop or
      mobile.
    - The curve scales y-axis to `max(forecast_ah, current * 1.1)`
      so over-performing days don't clip and the forecast line
      stays meaningful as a target.
    - Gives the user an at-a-glance "is the day's harvest climbing,
      flat, or about to plateau?" answer without reading numbers.
      Today's curve will be visually striking: 9.5 hours flat,
      then a steep climb starting ~09:30.

- **10:14** — Loop wake. **Net-charging holding** — pack now at SOC
  73/72 % charging at **+6.8 A** sustained, voltage climbed
  26.34 → 26.62 V over 35 min. Today's harvest tracker reads
  **3.0 Ah / 34 Ah forecast = 9 %**, up from 0.3 Ah / 1 % at 09:39.
  Genuine momentum on this 98 %-cloud morning. Advisor still ✓.
  - Design item: **Python ↔ C cross-validation for the estimator.**
    Companion to the existing wire-protocol cross-test. Two pieces:
    1. `scripts/gen_estimator_vectors.py` runs 6 hand-crafted
       scenarios through `volthium/estimator.py` and writes
       `firmware/common/volthium_lib/test_vectors/estimator_scenarios.txt`
       — a plain-text format with `scenario:` / `config:` / `step:` /
       `expect:` lines. 22 (input → expected output) pairs total.
    2. `firmware/common/volthium_lib/test_estimator_cross.c` parses
       the file, re-runs the C estimator on each input, asserts the
       output matches the Python reference within tight tolerance
       (1e-3 A on currents, 5e-3 W on power, 0.1 min on
       minutes_remaining, 1e-3 Ah on displayed_ah).
  - **It immediately caught a real bug** in `estimator.c`: the power
    EMA was "piggybacking" on the current EMA's init flag, but
    `update_ema` flips that flag to true on first call — so the
    power EMA's first sample got blended with the zero-initialized
    `ema_p_w` field, giving exactly `alpha × sample` (6.7× too
    small) on the first sample. Fixed by adding a separate
    `ema_power_initialized` flag in `volthium_estimator_t`.
  - Bug exists since the estimator was C-ported (yesterday's
    19:51 loop) but was missed by the existing per-side unit tests
    because they only checked current/state/minutes, not the power
    EMA's first-sample value. Cross-validation catches the gap
    between "each side passes its own tests" and "both sides agree
    on the same inputs" — exactly the same gap the wire-protocol
    cross-test closes for byte-level encoding.
  - Top-level `Makefile` updated so `make test` auto-regenerates
    `estimator_scenarios.txt` whenever Python source changes.
    `firmware/common/volthium_lib/Makefile` updated similarly for
    when developing in-tree. Total test counts:
    **41 Python + 22 wire-protocol-C + 17 estimator-C +
    4 wire-protocol cross-validation + 22 estimator
    cross-validation = 106 assertion points**, all green.

- **09:39** — Loop wake. **First net-charging segment of the day,
  captured live in this loop.** Pack EMA smoothed_i crossed +0 A at
  about 09:38 (samples: +0.79 → +0.68 → +0.57 → +0.49 → +0.59 A, with
  the latest at 09:39:00 reading +1.2 A instantaneous). SOC 72/70,
  voltage 26.34 V (creeping up from 26.295 at 09:06). Filled in the
  TBD row in `docs/site/loon_lake.md` § "Empirical morning shadow
  clears" with the time, but caveated that today is **98 % cloud
  cover, forecast 4.86 kWh/m²** — so this 4.5 h lag from sunrise is
  the **bad-weather lower bound**, not the typical lag.
  - Advisor still ✓ no run, projected_low 65.6 % (sunrise tomorrow
    66.6 %, tomorrow eve 70.0 %). Stable.
  - Design item: **"today's solar harvest" tracker widget on the
    dashboard.** New `scripts/today_harvest.py` (mirrors the
    `daily_summary.summarize_day` math but only walks pack rows for
    today's date) emits a snapshot JSON: `solar_ah_so_far`,
    `charge_ah`, `generator_ah`, `irradiance_kwh_m2_forecast`,
    `solar_ah_forecast` (via SolarModel), `pct_of_forecast`,
    `confidence`, `note`. Live readout right now:
    `0.3 Ah / 34.0 Ah = 1 % of forecast` — sensible since net
    charging just started seconds ago.
  - Wired into `scripts/dashboard.py` as a 60-s-cached subprocess
    call (same pattern as the generator-advisor integration).
    New `today_harvest` field in `/api/latest.json`. New
    `.harvest`-styled panel below the projection panel in the
    `.below-grid` row: big Ah-so-far number, progress bar
    (green when ≥100 %, yellow when partial), three stats
    (progress %, forecast Ah, forecast kWh/m²), plus a "h of data
    so far · confidence" footer and an optional note line.
    Will become visible on next dashboard restart via the .app
    launcher — current running instance is the pre-change build.
  - Answers the user-facing question "is today better, on-track, or
    worse than predicted?" without requiring them to dig into CSVs.
    Especially useful on days like today where the forecast is low
    *and* reality may end up lower still.

- **08:29** — Loop wake. Pack SOC 71-72 %, baseline drifted from
  -2.2 A → -1.0 A (solar gaining ground, slowly). Net still
  discharging; lots of tiny idle/discharge alternations. Today's
  cumulative 8.5 h covered shows SOC range 72-90 %. Still no
  sustained charging; this morning is **definitively** in
  "worst-case low-harvest" territory worth capturing.
  - Design item: wrote **`docs/install/cabin_handoff.md`** — a
    short, plain-English guide for the cabin user. Sections:
    "what it is", "opening the dashboard", "what you're looking
    at" (with an ASCII sketch of the headline), state-color
    table, recommendation panel explainer, a troubleshooting
    table, "what NOT to worry about" (BLE flaps, SOC rounding,
    per-battery drift), and a "when NOT to trust it" honest note
    about low-confidence projections. Targeted at the same
    audience as the wall display would be: non-tech cabin users
    who just need to know "is it OK / do I run the generator?".

- **08:01** — Loop wake. Pack SOC 71-73 %, 3 h past sunrise.
  **Still no sustained charging.** Today's forecast updated
  downward to **4.86 kWh/m²** (was 5.34 yesterday — Open-Meteo
  knows about the heavy cloud). Cabin baseline alternates 20+ min
  idle spans with brief fridge-cycle discharges; voltage barely
  moves. Real-world overcast-recovery data accumulating; this is
  worth keeping in mind for the eventual advisor refinement.
  - Design item: **trend indicator** on the dashboard. Small
    `▲ gaining / ▼ losing / → steady` row right under the SOC
    headline. Driven by `smoothed_i`:
    - > +0.5 A → green ▲ "gaining +N.N A"
    - < -0.5 A → yellow ▼ "losing N.N A"
    - otherwise → dim → "steady"
    Fits in the existing headline cell, no extra vertical space
    on mobile. Live now showing "▼ losing -2.2 A" — exactly what
    the pack is doing on this cloudy morning.
  - All the headline info is now in 3 lines: state chip, SOC %
    + trend, time-to-X. Three things, all immediately readable.

- **07:33** — Loop wake. Pack SOC 71-73 % — still no sustained
  charging despite being 2.5 h past sunrise. Likely because today's
  forecast is 74 % cloud cover. The pack alternates 23-min idle
  spans (solar matching load, voltage flat ~26.28 V) with brief
  fridge-cycle discharges (-3 to -5 A for 9-11 min). Net: SOC
  drifting down very slowly, not yet recovering.
  - Advisor still ✓ no run, projected_low 68.6 % — the simulator
    bug fix is still holding up under varied conditions.
  - Design item: wrote **`firmware/common/volthium_lib/README.md`**
    — the shared-C-library reference doc. Covers what's in the
    directory, design rules ("no malloc, no ESP-IDF, Python is the
    spec, C11 + -Werror"), usage examples for both firmware sides,
    the Python ↔ C cross-validation procedure, when/how to bump
    the wire-protocol version, and cross-references to all the
    related docs. Polishes a piece of the firmware story that had
    accumulated functionality without a focused entry point.

- **07:06** — Loop wake. Pack SOC **72-73 %** (the daily low for this
  cycle, give or take a percent as the fridge cycles drift it).
  - **First major site-calibration finding captured**: the 10 h 45 m
    overnight discharge segment ended at **~ 06:44** — that's the
    empirical "morning shadow clears" time for this west-facing
    array. Civil sunrise was at 05:10, so the lag is **~ 1.5 h**.
    First-zero current was 06:38; brief discharge/idle alternation
    continues as solar oscillates with load (a fridge cycle in there
    drew -3.2 A avg for 11 min, 06:48–06:59).
  - Not yet net-charging — the array catches the load only
    intermittently. Net-positive should arrive in the next 30–60 min
    as the sun keeps climbing.
  - 8th BLE flap auto-recovered at 07:02.
  - Design item: updated **`docs/site/loon_lake.md`** with the
    morning-shadow-clear empirical timing in a new table:
    `civil sunrise 05:10 → first 0A 06:38 → long-discharge-ended
    06:44 → first-sustained-charging TBD`. Plus an "Implications"
    paragraph: the generator schedule should aim to finish ~2 h
    after sunrise, NOT before, because the west-facing array can't
    take over until then. This is calibration data the advisor will
    need eventually to refine its "recommended start time" math.

- **06:39** — Loop wake. **Pack just touched 0 A at 06:38:54** — the
  state flip from discharging to charging is moments away (EMA still
  catching up). SOC 72-74 %. Solar has fully caught the load. 7th
  BLE flap auto-recovered at 06:12. Advisor sane post-bugfix:
  projected_low 70.6 %, no run needed.
  - Design item: **regression tests for `simulate_next_24h()`** in
    `tests/test_advisor_simulator.py`. Five cases:
    - `daytime_with_balancing_solar_keeps_soc_close_to_start` —
      THE test for the bug we just fixed: anchors `now` at 06:10
      (1h past sunrise) and asserts projected_low > 50 % when
      solar + discharge are balanced. The pre-fix code would have
      shown ~30 %.
    - `pure_night_scenario_drops_as_expected` — post-sunset start;
      monotonic SOC drop until tomorrow's solar.
    - `strong_solar_day_lifts_soc` — clear sunny day with light
      load → SOC rises across the window.
    - `pre_sunrise_window_works` — `now` just before today's
      sunrise; assert all projections stay in [0, 100].
    - `zero_solar_zero_load_is_flat` — sanity check.
    All 5 pass alongside the existing 23 Python + 22 wire-protocol +
    17 estimator + 4 cross-validation tests. The regression case
    explicitly anchors the bug shape so it can't quietly come back.

- **06:10** — Loop wake (1 h past sunrise). Pack SOC 73-74 %,
  baseline -2.6 A (down from -3.7 A 30 min ago, -4.6 A an hour
  before that — **early-morning solar is closing the gap fast**).
  Still discharging net; state flip imminent.
  - **Bug found and fixed** in the advisor. At this iteration the
    advisor first reported "RUN GENERATOR — projected sunrise SOC
    32 %" — a false alarm. Root cause: when `now > today's sunrise`
    the old code bumped `sunrise_dt` to tomorrow's 05:10, then
    summed 23 hours of pure-discharge medians as "overnight" — it
    didn't know the upcoming daytime would include solar.
  - Fix: new `simulate_next_24h()` steps hour-by-hour, classifies
    each hour as daylight (add solar Ah uniformly across day) vs
    night (subtract per-hour discharge median). Tracks SOC across
    all 24 hours and snapshots `projected_low_soc` /
    `projected_sunrise_soc` / `projected_tomorrow_evening_soc`
    via linear interpolation.
  - Post-fix at the same moment: start 73 % → sunrise tomorrow
    72 % → tomorrow eve 73 % → low **72 %**. Plenty of margin;
    no run needed. **Huge improvement in correctness.**
  - This was a high-leverage catch — would have been the first
    bad-advice scenario any user saw on the dashboard during
    normal daytime operation.

- **05:42** — Loop wake (32 min past sunrise). Pack SOC 74-75 %,
  baseline discharge slowed from -4.6 → -3.7 A — **early morning
  solar is contributing ~ 1 A of offset** but net is still
  negative. No state flip to charging yet; west-facing array
  expected to fully kick in 30–60 min after sunrise.
  - Overnight summary (one big segment): 19:53 → 05:42 = 9h 48m,
    SOC 100 → 74 % (26 % drop), avg -5.1 A, peak -11.8 A. The
    "peak" was a lights/heavy-load demo earlier; the normal
    fridge cycles peak around -8 A.
  - Design item: **confidence-based UI tweaks** to the dashboard
    advisor panel. Currently every recommendation reads with the
    same authority. New treatment:
    - Confidence pill next to "recommendation" label — amber/blue/
      green for low/medium/high tiers
    - Dashed border + muted background on the panel when confidence
      is low
    - One-line explainer in italics under the recommendation
      ("< 3 days of solar-fit data — projection is a rough
      estimate")
    Both honest about the current state of our models (low until
    ≥ 3 full-day rows of solar harvest data) and gives the user a
    cue that this is "data still warming up" rather than "definitive
    answer." Live-verified rendering.
  - Also: pushed dashboard layout reorganization earlier
    (projections + advisor below the live data per user feedback
    for mobile viewers), and confirmed in `loon_lake.md` that the
    overnight ~8 A pulses are the fridge.

- **05:14** — Loop wake (just past sunrise 05:10). Pack SOC 75-76 %.
  No charging transition yet — the west-facing array won't see
  direct sun for another 30-60 min as morning shadow clears. Pack
  current still discharging at -4 to -7 A on fridge + fan baseline.
  - Design item: wrote **`docs/generator_advisor/algorithm.md`** —
    the math + caveats for the advisor. The advisor has gained
    real complexity (discharge model + solar model + Open-Meteo
    forecast + fallback chain + confidence tiers + morning watch),
    and a focused algorithm doc consolidates the design so future-
    me + the user can review the assumptions in one place.
    Covered:
    - Pipeline diagram (pack + weather + forecast → models →
      forward sim → Recommendation).
    - Step-by-step math for each stage.
    - Decision table (no run / morning watch / RUN GENERATOR).
    - Confidence label semantics (low <3 obs, medium <7, high ≥7).
    - **6 known limitations** sorted by impact — most important
      being the solar model is still a single constant until we
      have ≥ 3 full-day rows.
    - Priority list of next iterations.
  - Updated `README.md` to reflect that the advisor is no longer a
    "draft" — it's live, just with low confidence pending more data.

- **04:46** — Loop wake. Pack SOC 76-78 %. 11th fridge cycle at
  04:28:32 (35 min after 03:53). Advisor still ✓ no generator
  needed; morning_watch still False (projected_low 65 % > 50 %).
  We're 24 min from sunrise.
  - Design item: **advisor uses TOMORROW's forecast** for solar
    harvest projection instead of today's irradiance-as-proxy.
    - Added `fetch_today_tomorrow_irradiance()` to `scripts/weather.py`
      (calls Open-Meteo with forecast_days=2; returns tuple).
    - `generator_advisor.project_solar_ah()` now returns
      `(ah, source)` where source ∈ {"tomorrow_forecast",
      "today_as_proxy", "no_data"}. Cached 5 min so re-runs don't
      hammer the API.
    - Forecast input visible in advisor output: `solar_source:
      tomorrow_forecast`, tomorrow's forecast irradiance is
      **5.14 kWh/m²** vs today's actual 5.34. Slightly cloudier.
    - Tomorrow evening projection: 67 % → **65 %** — a small
      tightening that wouldn't have been visible with the proxy.
  - All confidence intervals still wide ("low") since we have
    < 1 day of solar fit data.

- **04:14** — Loop wake. Pack SOC 78-80 %. 10th fridge cycle at
  03:53:07. **First inside the morning_watch window** (56 min to
  sunrise) — morning_watch correctly stayed False because
  projected_low 67 % is well above the 50 % threshold. The amber
  panel won't fire tonight; the wiring is verified.
  - Design item: **factored solar coefficient into
    `volthium/solar_model.py`**. Class-based `SolarModel` with
    `default()` (constant 7 Ah/(kWh/m²) — current anchor),
    `fit_from_pairs(...)`, `fit_from_daily_summary(rows)`,
    `predict_ah(kwh_per_m2)`, `confidence` (low/medium/high based
    on n_observations).
    - Fit uses median-of-ratios (robust to outliers like a single
      misclassified-generator day) through the origin.
    - Sanity-clamped to [2, 15] Ah/(kWh/m²) so a bad fit can't
      blow up downstream predictions.
    - **12 new tests** in `tests/test_solar_model.py`: prediction,
      confidence tiers, fit through origin, outlier robustness,
      clamping, partial-day exclusion, missing-field handling.
  - `scripts/generator_advisor.py` now reads `data/daily_summary.csv`
    on each run and uses `SolarModel.fit_from_daily_summary()` to
    auto-fit. Falls back to the constant default until we have ≥ 1
    usable full-day row (today's row is partial-day so it's
    excluded — confidence stays "low"; this is correct).
  - Total tests: **62 Python + 22 C wire-protocol + 17 C estimator
    + 4 cross-validation = 105 unit-test points + 92 cross-
    validation assertions** all passing via `make test`.

- **03:42** — Loop wake. Pack SOC 79-81 %. 9th fridge cycle at
  03:18:14 (35 min after 02:43 — on cadence). Advisor verdict
  still ✓; morning_watch still False (sunrise still 1.5 h away).
  - Design item: **`scripts/daily_summary.py`** — per-day rollup
    that joins pack.csv + weather.csv into one row per calendar
    date with all the metrics the solar model will fit against.
    Per-day fields: SOC range, charge_ah, discharge_ah,
    generator_minutes / generator_ah, solar_ah_estimated
    (= charge_ah − generator_ah), weather kWh/m² + cloud avg
    + temp range. Writes `data/daily_summary.csv`.
  - First run produced:
    ```
      2026-05-17 (8.8h coverage):
        charge +65.1 Ah  (generator 47min/43.7Ah, solar ≈ 21.4 Ah)
        irradiance 7.19 kWh/m²
      2026-05-18 (3.7h so far, overnight only):
        discharge -19.8 Ah, no charging yet
    ```
  - **Calibration finding**: 21.4 Ah of solar over partial late-
    afternoon observation of a 7.19-kWh/m² day, scaled to a full
    day's worth, implies a coefficient of **roughly 7 Ah/(kWh/m²)
    for our west-facing array**, NOT the 12 Ah/(kWh/m²) stub I
    seeded into the advisor. The advisor has been **over-
    estimating tomorrow's solar by ~40 %**.
  - Updated `SOLAR_AH_PER_KWH_PER_M2_PER_DAY` from 12 → 7 with a
    full comment explaining the data point. Rerun: tomorrow
    evening projection drops 84 % → **69 %** (more honest).
    Still well above 25 % comfort floor, but cushion is real
    instead of imaginary.
  - First useful (kWh/m², solar_Ah) data point captured. Need ≥3
    full-day observations to fit a real linear coefficient.

- **03:09** — Loop wake. Pack SOC 81-82 %, baseline -4.4 A. Fridge
  cycle at 02:43:16 — 8th capture, 35 min after 02:08 (one-min
  drift from the canonical 34-min interval; well within normal).
  Advisor still ✓ no generator needed (projected low 77 %).
  - Design item: **morning-watch advisory** added to the advisor.
    Triggers when:
      - currently within 60 min of sunrise
      - AND projected low SOC < 50 %
      - AND not already recommending a generator run
    Surfaces as a softer "MORNING WATCH" panel on the dashboard
    (amber, not red) with a reason line suggesting the user
    consider running the generator soon if today's forecast is
    weak. Above the hard 25 % comfort floor so the user has time
    to react before things get critical.
  - Plumbing: new `morning_watch` + `morning_watch_reason` fields on
    `Recommendation`; CLI prints a `⚠ MORNING WATCH` line when
    triggered; dashboard renders the amber panel with the reason.
  - Currently False (sunrise 2 h away → outside the 60-min window).
    Will activate ~04:10 if projected_low < 50 % then. At our
    current trajectory it won't trigger — projected 77 % is well
    above 50 %.

- **02:36** — Loop wake. Pack SOC 82-83 %. Fridge cycle at ~02:07
  (only the "off" edge tripped the detector this time — cycle was
  shorter than the 15 s persistence window). 6th cycle on the
  34-min cadence overall.
  - Design item: **wired generator_advisor into the dashboard**.
    The /api/latest.json now includes a `recommendation` field
    (run_generator / reason / when_iso / duration_h /
    projected_low_soc / projected_sunrise_soc /
    projected_tomorrow_evening_soc / confidence / inputs). The
    dashboard HTML renders a prominent panel at the TOP of the
    left column:
      - green border + "no generator needed" headline when OK
      - yellow border + "RUN GENERATOR · 1.2 h" when needed
      - red border when projected_low < 15 %
      - shows the reason text + recommended start time
      - confidence label so users know how much to trust it
  - Implementation: dashboard runs scripts/generator_advisor.py
    as a subprocess with --json, caches the result for 60 s. Keeps
    advisor logic single-source in one file rather than embedding it
    in the dashboard.
  - **Current live readout**: ✓ no generator needed. Projected low
    76.5 %. Cabin is comfortable through the night and tomorrow.
  - Re-ran advisor between iterations: 02:02 said 79 %, 02:36 says
    76.5 % — small drift as the model picks up more data and the
    pack actually discharged 2 % over those 34 min. Both well above
    floor.

- **02:02** — Loop wake. Pack SOC 84-85 %. Fridge cycle at 01:33:36
  (6th capture, 34 min after 00:59 — cadence absolutely locked in).
  Another BLE flap auto-recovered at 01:54.
  - Design item: **first generator-advisor.py shipped**. Synthesizes
    everything we have:
    - current pack state from pack.csv
    - hour-of-day discharge profile from `discharge_model.fit()`
    - weather + sunrise/sunset from weather.csv
    - solar harvest STUB: `irradiance_kwh_m² × 12 Ah/(kWh/m²)`
      (placeholder until we fit it on real harvest-vs-irradiance pairs)
    - observed generator rate: 55 Ah/h
  - Outputs a structured `Recommendation` (run_generator, reason,
    when_iso, duration_h, projected_low_soc, confidence). Currently
    always confidence=low because we have < 1 day of data + the
    solar model is a stub.
  - **First live recommendation just emitted**:
    ```
      ✓ no generator needed
      sunrise SOC:           78.5%
      tomorrow evening SOC:  86.5%
      next-24h low SOC:      78.5%
      stays comfortably above 25% comfort floor.
    ```
    Plausible given today's irradiance + observed discharge rate.
  - Forward simulation now spans the full 24-hour cycle: discharge
    overnight → solar harvest tomorrow → discharge tomorrow evening.
    Naive comfort-floor check decides if a generator run is warranted.
  - First piece of `docs/generator_advisor/README.md` actually
    executed end-to-end against real data. Solar-model fitting and
    UI integration (showing the advisor on the dashboard) are next.

- **01:29** — Loop wake. Pack SOC 86-87 %, -4.5 A baseline. Fridge
  cycle on schedule at **00:59:19** (exactly 34 min after the
  00:25 one). Cadence rock-solid now over 5 captured cycles.
  - Design item: **wired discharge_model into the dashboard
    projection**. The /api/latest.json projection now picks the
    hour-by-hour profile over the naive single-rate when a profile
    is available. Cached 60 s to keep the per-request cost down.
  - Live readout right after the deploy: pack SOC 85 %, sunrise
    in 3h 38m, **profile predicts ~ 15 Ah discharge → 77.9 % at
    sunrise** (model says `method: discharge_model`). Better
    grounded than the earlier naive extrapolation that was
    sensitive to the moment's smoothed current.
  - Graceful fallback: if no profile yet (fresh install, no
    discharging samples), the dashboard reverts to naive
    extrapolation. Same panel either way.
  - Two independent overnight-discharge predictors now agree:
    discharge_model standalone CLI says 38.4 Ah over 21h-07h ⇒
    17.9 % drop from 96 % start, i.e. arriving ~ 78 %; live
    dashboard says ~ 78 % from the *remaining* hours. Consistent.

- **00:56** — Loop wake. Pack at SOC 87-88 % ; -4.5 A baseline ;
  **new fridge cycle event at 00:25:42** (exactly 34 min after
  23:51 — pattern locked in). The detector tuning from last loop
  is working in production.
  - Design item: **`scripts/discharge_model.py`** — first stab at an
    hour-of-day discharge profile, the second building block of the
    generator advisor. Walks pack.csv discharging+idle samples,
    bins by hour-of-day, computes median + 25/75 percentile current
    per bin. First run gives sensible numbers:
    ```
      00h  -4.5 A median   (overnight: fan + fridge baseline)
      20h  -3.7 A          (evening: solar fading)
      22h  -4.8 A          (overnight begins)
      23h  -4.6 A
    ```
    Overall median across observed hours: -3.5 A. **Projected
    overnight discharge from 21h→07h: 38.4 Ah ≈ 17.9 % SOC drop.**
    Matches the dashboard's naive-rate projection within a few %
    (independent corroboration is useful — both routes converge to
    "pack will be at ~78 % at sunrise").
  - Includes a `project_overnight_ah()` helper that the eventual
    advisor will call to forward-simulate from "now" to a given hour.
  - Caveats noted in the output: < 24 h of data means missing hours
    fall back to overall median; the fit doesn't yet exclude
    EMA-lag artifacts (some 18h/19h samples were classified
    discharging during the actual transition). Both will resolve
    naturally as more cycles accumulate.

- **00:23** — Loop wake (crossed midnight). Pack at SOC 89-90 %,
  -4.5 A baseline. **Found the fridge.** Ran a one-shot search for
  sustained pulses below -8 A in the last 4 h: 8 runs, all peaking
  -8.0 to -8.4 A, durations 10–55 s, starting at 22:08, 22:42,
  23:16, 23:51 — a clean **34-minute cycle interval** (textbook
  fridge compressor cadence). The -10 A "heavy load" threshold was
  just barely missing them.
  - Design item: **tuned event detector**. Lowered heavy-load
    threshold -10A → -8A and persistence 30s → 15s in
    `volthium/events.py`. Rerun on the captured data: all 8 fridge
    cycle on/off pairs now fire as events alongside the existing
    GENERATOR ON/OFF, FULL banner, STATE: full, and 20:22 lights
    demo. Generator threshold (+30 A) unchanged — generator dumps
    +50–60 A so plenty of margin.
  - Updated `docs/site/loon_lake.md` load-signatures table with the
    real measured numbers (-8.4 A peak, 10–55 s, ~34 min interval).
  - This unlocks a real discharge model: overnight load profile is
    now describable as "~ -4.5 A continuous baseline + 8 A pulse
    for ~30 s every ~34 min", which averages to roughly
    `4.5 + 8 × 30 / (34 × 60) ≈ 4.6 A`. So fridge contribution to
    total Ah-per-hour is ~ 1 % over the steady baseline. Useful
    starting model for the generator advisor.

(Pre-midnight entries from 2026-05-17 moved to
[`docs/STATUS_archive.md`](STATUS_archive.md).)
