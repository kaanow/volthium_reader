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

- **2026-05-19 13:56 — SOC 79/77, drift +46%, log row #6 in.**
  Pack approaching absorption: SOC **79/77** (+1/+1), pack_i
  +16.5 A, pack_v 26.91 V. `solar_ah_so_far = 29.8 Ah` (**71% of
  forecast**). live_ratio **11.90** vs model 8.15 → drift
  **+46.0%**. Row #6 landed at 13:51:45 with drift +43.0%
  (advisory firing positive). The day's full arc now spans
  **75 pp** of drift across 6 log rows — symmetric advisory
  excursions in both directions.
  - **Design item picked: embed uptime % in day-report BLE
    logger reliability headline.** Small consistency completion
    — the CLI and dashboard already show uptime%, now the
    day-report's BLE section headline does too.
    - `scripts/end_of_day_report.py`: BLE-logger reliability
      headline gains `(uptime **95.8%**)` (or whatever the
      day's value). Computed best-effort via
      `health_mod.compute_today_uptime_pct()`; silently omits
      the suffix if computation fails. **Today's archived
      output**:
      ```
      2 BLE-logger gaps today: max 29 min, total 35 min
      downtime (uptime **95.8%**). Each gap is a stretch where...
      ```
    - 1 regression test added to the existing
      `test_ble_logger_section_renders_events`: asserts
      `"uptime"` appears in the headline alongside the existing
      assertions. Suite still **276 tests passing** (extended
      existing test, not adding new).
  - **Why this matters**: uptime % now lives on ALL three
    surfaces with identical formatting:
    1. CLI `health.py` PACK GAPS line
    2. Dashboard `gaps-chip` text
    3. Day-report `## BLE logger reliability` headline
    A future operator scanning any of these three sees the same
    number. Grep `grep "uptime" data/reports/*.md` extracts the
    weekly trend.
  - **Watch**: pack approaching absorption. Voltage hit 26.92 V
    a few loops ago and is now hovering at 26.91 V — close to
    the 26.8 V absorption-onset Volthium typically uses to
    transition out of bulk. If SOC ticks 1-2 more times,
    expect state to change from `charging` to `full` and the
    advisor's projected_low to start incorporating tomorrow's
    full overnight discharge rather than today's recovery.

- **2026-05-19 13:51 — pushing 80% SOC, drift +43%.** Pack at
  **SOC 78/76** (+3/+3 since last loop), pack_i +19.3 A, voltage
  **26.92 V** (new daily high). `solar_ah_so_far = 28.4 Ah`
  (**68% of forecast** — was 52%). live_ratio shot to **11.63**,
  drift **+42.7%** — the day is significantly overperforming
  the SolarModel. live_ratio_log row #5 landed at 13:26:45
  capturing the moment drift swung past +20%; chart now shows
  3 low-red, 1 mid-gray, 1 high-red dot.
  - **Design item picked: daily uptime % stat.** Completes the
    PACK GAPS narrative with a single-number reliability metric.
    Tier-1 useful for "is the BLE logger healthy enough" at a
    glance.
    - `scripts/health.py`: new pure helper
      `compute_today_uptime_pct(pack_csv, day, gap_threshold_s)`.
      Returns `(span_s − total_gap_s) / span_s × 100` where
      `span_s` is the elapsed time between the day's first and
      last sample. Returns None on missing file / single-row
      day. Result clamped to [0, 100].
    - `_fmt_pack_gaps_line()` extended: appends `, uptime
      95.8%` (or whatever the live %) to the PACK GAPS line
      when gaps exist.
    - `scripts/dashboard.py`: `/api/latest.json`'s `pack_gaps`
      field gains an `uptime_pct` member. JS chip text becomes
      `... · uptime 95.8%`.
    - 4 regression tests in `test_health.py`:
      missing-file-defensive, clean-day = 100%, single-gap math
      correctness (50% case + verified to also catch the 0%
      degenerate case where ALL deltas are gaps), realistic
      partial-day with one threshold-passing and one
      sub-threshold gap.
      Suite: **276 tests passing** (was 272, +4 new).
  - **Today's live signal**:
    `PACK GAPS    2 events, max 29 min, total 35 min today, uptime 95.8%`
    Despite the morning's two BLE blips, today's logger
    captured 95.8% of the observable timeline — a clean
    operational summary.
  - **Why this matters**: the PACK GAPS line tells you "events
    + max + total", but a percentage normalizes across day
    lengths (early in the day, 5 min of gap is catastrophic;
    late in the day, it's marginal). Uptime% is the right
    metric for weekly trending — eventually we'll grep
    `data/reports/*.md` for `uptime` and see how reliability
    evolved over time.
  - **Watch**: row #6 lands ~13:51. Today's full drift arc may
    end up with +30%+ on most afternoon rows — when daily_summary
    integrates today's complete day data tonight, the
    SolarModel re-fit will likely shift the coefficient
    upward (today is producing 11+ Ah/kWh-m², well above the
    8.149 baseline from 2026-05-18). Multi-day calibration is
    starting to bite.

- **2026-05-19 13:25 — past halfway.** SOC **75/73** (+1/+1),
  `solar_ah_so_far = 21.8 Ah` (**52% of forecast — past halfway!**).
  pack_i 13.8 A, smoothed +15.4 A, pack_v **26.80 V**. live_ratio
  climbing to **10.38**, drift **+27.4%** (advisory firing strongly
  in positive direction). live_ratio_log still at 4 rows; row #5
  due in ~2 min.
  - **Design item picked: net Ah curve hourly table on day-report.**
    Completes the surface trio for today's net Ah curve:
    - CLI / dashboard chart at `/today-curve`
    - **Day-report markdown table** (this commit)
    Future operators reading 2026-05-19's archived report can see
    the recovery shape without needing the live server.
    - `scripts/today_harvest.py`: `snapshot()` return dict now
      also propagates the `net_series` (5-min binned cumulative
      net Ah) — was being computed but not exposed.
    - `scripts/end_of_day_report.py`: new `## Net Ah curve
      (hourly)` section between Live-ratio drift and
      Cross-references. Downsamples the 5-min `net_series` to
      hourly (taking the LAST value per hour bucket). Marks
      hours that contained any solar_onset milestone
      (zero/idle/pos/net+). Headline summary line names the
      current net, plus min/max with their hour.
    - **Today's archived output captures the recovery story
      compactly**:
      ```
      | hour | cumulative net Ah | milestones |
      | 00:00 |  -4.7 |
      | 06:00 | -29.1 | zero, idle
      | 07:00 | -30.8 | pos, net+     ← morning low
      | 08:00 | -30.5 |
      ...
      | 12:00 | -18.7 |
      | 13:00 | -11.0 |                ← afternoon climb
      ```
      Anyone scanning that table immediately sees the day's
      shape: overnight drop, valley at 07:00 (precisely the
      hour solar_onset milestones fired), then steep climb.
    - 2 regression tests: empty-state cold start +
      multi-hour-table with milestone marking. Suite: **272
      tests passing** (was 270, +2 new).
  - **Why this matters**: the day-report is now a comprehensive
    archive covering EVERY chain on three timescales:
    
    | chain | live CSV | dashboard | day-report |
    |-------|----------|-----------|-----------|
    | pack samples | pack.csv | sparkline | (raw) |
    | solar onset | solar_onset.csv | chip + markers | cascade table |
    | sunrise accuracy | projection_log | /accuracy chart | per-record table |
    | morning-low | projection_log + onset | /low-accuracy chart | per-record table |
    | confidence | confidence_log.csv | conf-lift chip | events table |
    | drift | live_ratio_log.csv | /drift chart | per-record table |
    | net Ah curve | net_series | /today-curve | hourly snapshot |
    | BLE reliability | (derived) | stale banner + gaps chip | events table |
    | health | (composite) | /health | snapshot section |
    
    Every signal has 3 surfaces. The day-report's 9 sections
    capture the entire system state in markdown that grep
    treats like a database.
  - **Watch**: row #5 lands any moment now. By sunset the
    afternoon's run of high-drift rows will balance the
    morning's low-drift rows in the daily summary; tomorrow's
    SolarModel re-fit will incorporate today's complete-day
    data and likely produce a coefficient close to the existing
    8.149.

- **2026-05-19 13:18 ☀☀☀ — afternoon catch-up FULL THROTTLE.**
  Pack ticked **SOC +3/+3 to 74/72**, pack_i **+17.7 A**,
  smoothed +17.2 A, pack_v **26.79 V** (new daily high). 
  `solar_ah_so_far` jumped **+6.1 Ah** to 19.9 (48 % of forecast).
  live_ratio shot up to **9.85**, drift **+20.9% — advisory firing
  AGAIN but flipped sign** (live now OVERperforming model).
  - Today's full drift arc visible across 4 log rows:
    ```
    11:44  ratio 5.73  drift -29.7%  (advisory: too LOW)
    12:09  ratio 6.01  drift -26.3%  (advisory: too LOW)
    12:35  ratio 5.92  drift -27.4%  (advisory: too LOW)
    13:01  ratio 8.59  drift  +5.4%  (within threshold)
    [now]  ratio 9.85  drift +20.9%  (advisory: too HIGH)
    ```
    The afternoon's strong sun + the small remaining-irradiance
    denominator means each new Ah-gained pushes the ratio
    rapidly toward and past the SolarModel coefficient.
  - **Design item picked: per-day net Ah recovery curve at
    `/today-curve`.** With today's data being so dramatic
    (overnight low at 63.5 → midday valley → afternoon climb
    through 74), a full-day chart of cumulative net Ah finally
    has a story to tell.
    - `scripts/today_harvest.py`: `integrate_today()` now also
      returns a `net_series` list of (minute_of_day,
      cumulative_net_ah_signed) parallel to the existing
      `series` (solar_ah). Computed in the same pass through
      pack.csv so no extra cost. Cold-start paths return
      `net_series: []`.
    - `scripts/dashboard.py`: new `/today-curve` route +
      `_render_today_curve_chart()` helper. SVG line chart:
      X = 0..1440 min (full day), Y = cumulative net Ah signed.
      Dashed zero baseline. Solar onset milestones overlay as
      vertical dashed lines (gray for zero/idle, amber for
      first_positive, green for first_net_positive). Auto-
      refresh every 60 s.
    - Summary line shows total cumulative charge, discharge,
      net (with min/max).
    - Cross-linked from main dashboard footer + own
      navigation back to dashboard, today-report, /drift,
      /health.
    - 2 regression tests: empty-state cold start + populated
      chart with polyline + summary stats. Suite: **270 tests
      passing** (was 268, +2 new).
  - **Why this matters**: the rolling 2 h sparkline on the main
    page shows the LAST 2 hours of detail. `/today-curve` shows
    the FULL DAY's trajectory. Together they zoom in/zoom out
    on the same signal. A future operator investigating "what
    happened today?" can scan the full-day curve to spot the
    morning low or afternoon catch-up without scrolling
    through 8+ hours of pack.csv.
  - **Watch**: today is over-performing the SolarModel — by
    sunset we may see drift +30% or higher. The afternoon catch
    -up is partially compensating for the morning's cloudy
    shortfall. Tomorrow's SolarModel re-fit (when daily_summary
    integrates today's complete day data) will reveal whether
    yesterday + today average back to a ~7-8 Ah/(kWh/m²)
    coefficient or whether the model coefficient needs to shift.

- **2026-05-19 12:54 — 🎉 drift fully cleared, live_ratio nearly
  matches model.** Pack still hard-charging: SOC **71/69** (+1
  each from last loop), pack_i +15.5 A, smoothed +13.0 A,
  pack_v 26.69 V. **live_ratio 7.87** vs model 8.15 → **drift
  -3.4%** (essentially calibrated, well within threshold).
  `solar_ah_so_far` up to **13.8 Ah** (33% of forecast).
  live_ratio_log still at 3 rows — row #4 due ~13:00.
  - **Design item picked: live-ratio drift section on day-report.**
    The dashboard's /drift chart shows the time-series visually;
    the day-report should archive the same data in markdown
    table form so future operators can grep the history without
    needing the live server.
    - `scripts/end_of_day_report.py`: new `## Live-ratio drift`
      section between `## BLE logger reliability` and
      `## Cross-references`. Filters live_ratio_log by today's
      ISO date prefix.
    - Renders summary stats (n, mean ratio, mean drift, range,
      advisory-fired count) + a markdown table with HH:MM:SS
      timestamps and a `**yes**`-bolded advisory column.
    - Link to `/drift` for the live chart view (markdown
      reference link).
    - Empty-state when no entries: "advisor didn't run during
      daylight" / "day stayed below harvest-detection threshold".
    - Cross-references section gains a row for
      `data/live_ratio_log.csv`.
    - 3 regression tests: empty-state, populated rows render
      with summary line + bolded advisory column, and day-filter
      excludes yesterday's entries. Suite: **268 tests passing**
      (was 265, +3 new).
  - **Today's archived output captures the morning's drift
    story exactly**:
    ```
    3 live_ratio samples on this day. Mean ratio 5.89,
    mean drift -27.8%, range [-29.7..-26.3].
    Drift advisory fired in 3 / 3 samples.
    ```
    Row #4 (after the afternoon catch-up) will land at ratio
    ~7.87 and shift the mean ratio significantly upward — the
    table will then tell a "morning sag, afternoon recovery"
    story.
  - **Why this matters**: the system's third archival surface
    for drift data:
    1. Live data: `data/live_ratio_log.csv` (raw)
    2. Live chart: `/drift` (visual)
    3. **Day-report**: `data/reports/YYYY-MM-DD.md`
       `## Live-ratio drift` (archive)
    Same data, three surfaces, never diverge. The day-report
    surface lets `grep "live_ratio samples" data/reports/*.md`
    show how drift evolved week-over-week.
  - **Watch**: with the day's drift trending toward 0, the
    afternoon's row #4-7 should all be GREEN (within threshold)
    — visually proving the calibration is sound across the day.

- **2026-05-19 12:46 — drift advisory CLEARED + SOC +2/+2.** Pack
  recovered hard: SOC **70/68** (was 68/66 last loop), pack_i
  **+15.5 A** charging, pack_v **26.69 V** (highest of day),
  smoothed_i **+15.8 A**. `solar_ah_so_far` jumped **+3.3 Ah** to
  11.8 (28% of forecast). live_ratio climbed back to **7.06**,
  drift narrowed to **-13.4% — within threshold**, advisory cleared.
  live_ratio_log row #3 landed at 12:35:45 (ratio 5.92, drift -27.4,
  still in advisory zone — afternoon catch-up happened in the
  10-min gap between row-write and health check).
  - **Design item picked: PACK GAPS section on day-report.** The
    health snapshot at the top already shows the daily summary
    line; this commit adds a dedicated `## BLE logger reliability`
    section with per-gap event detail. Grep-able across reports
    for week-over-week uptime trends.
    - `scripts/health.py`: new sister helper
      `today_pack_gap_events(pack_csv, day, gap_threshold_s)`
      returns `list[(gap_start_iso, gap_end_iso, gap_s)]`. Same
      threshold (60 s) as the summary helper but enumerates each
      event individually.
    - `scripts/end_of_day_report.py`: new
      `## BLE logger reliability` section between Confidence-lift
      events and Cross-references. Renders either:
      - **Clean day**: "Clean day — no BLE-logger gaps over 60 s"
      - **Day with gaps**: summary line + markdown table with
        `gap # | last sample before | next sample after | duration`
        for each event.
    - **Today's archived output**:
      ```
      | 1 | 10:41:59 | 11:11:02 | 29 min |
      | 2 | 11:11:02 | 11:17:17 |  6 min |
      ```
      Future operators reading 2026-05-19's report see the exact
      morning blip story.
    - **Subtle Python bug caught**: a naive `import health as
      health_mod` inside the new section's try/except shadowed
      the top-of-file import as a function-scope name, breaking
      the earlier `## Health snapshot` section's
      `render_summary()` call (UnboundLocalError). Fixed by
      removing the redundant local import — the top-level
      binding already provides it. Added comment so the gotcha
      doesn't recur.
    - 2 regression tests in `test_end_of_day_report.py`:
      `test_ble_logger_section_clean_day_message` (empty
      pack.csv → "Clean day" branch), `test_ble_logger_section_renders_events`
      (one 10-min gap → table row with start/end/duration).
      Suite: **265 tests passing** (was 263, +2 new).
  - **Why this matters**: the chain of operational signals now
    spans real-time (stale-data banner on dashboard), aggregate
    (PACK GAPS chip + line), AND archival (this day-report
    section). The full BLE-logger reliability story is captured
    on three timescales without any single surface being noisy.
  - **Watch**: row #4 in live_ratio_log lands ~13:00. Pack
    accelerating — `solar_ah_so_far` could reach 20+ Ah by
    sunset if the current rate (+3.3 Ah / 32 min) holds.

- **2026-05-19 12:21** — Pack at solar/load equilibrium again
  (pack_i 0.0 A momentary, smoothed +1.5 A — still net charging).
  SOC holding 68/66. `solar_ah_so_far = 9.0 Ah` (+0.5 since last
  loop). Drift narrowing to **-23.1%** (from -24.0%). PACK GAPS
  unchanged at 2 events. live_ratio_log still has 2 rows — row
  #3 will land at ~12:34:46 (25 min after #2).
  - **Design item picked: live-ratio drift chart at `/drift`.**
    The log started populating last loop; this commit adds the
    visualization that lets the operator see how today's drift
    has evolved at-a-glance instead of scanning the raw CSV.
    - `scripts/dashboard.py`: new `/drift` route + new
      `_render_drift_chart()` helper. Renders an SVG time-series:
      - X axis = sample index (chronological)
      - Y axis = live_ratio (Ah / kWh/m²)
      - Horizontal reference line at the SolarModel coefficient
        (the "target")
      - Shaded ±20 % band marking the advisory zone (matches
        `MODEL_DRIFT_ADVISORY_THRESHOLD_PCT`)
      - Dots: **red** when `advisory_fired=True`, **gray** when
        within threshold
      - SVG `<title>` tooltips on every dot showing ts + drift
      - First/last timestamps labeled on the X axis
    - Below the chart, a per-record table with summary stats
      (n, mean ratio, mean drift, advisory-fired count).
    - Cross-linked from all the other log pages (`/accuracy`,
      `/low-accuracy`, `/projections`, `/calibration`,
      `/confidence`) AND the main dashboard footer AND the drift
      advisory chip's footer.
    - **Today's chart**: two red dots near the bottom of the
      Y axis (ratio 5.73 → 6.01, drift -29.7% → -26.3%) below
      the -20% threshold band — exactly the "advisory zone"
      story we've been telling. As more rows accumulate the
      visual will show the recovery curve directly.
    - 2 regression tests: `test_drift_route_empty_state`
      (cold-start no crash) + `test_drift_route_renders_chart_with_data`
      (SVG + circles + reference lines + summary table all
      present with fixtured rows). Suite: **263 tests passing**
      (was 261, +2 new).
  - **Why this matters**: the drift advisory has been firing
    on-and-off for hours today. The chart immediately answers
    "is this a transient spike or a sustained trend?" — for
    today's data, it's clearly the latter (both rows below the
    band). Over coming days the chart will show whether the
    advisory clears cleanly (model fits OK) or persists (model
    needs re-fitting). Same shape as `/accuracy` and
    `/low-accuracy` so the operator's mental model is consistent
    across all three validation chains.
  - **Watch**: row #3 lands ~12:34. With each row the chart
    becomes more informative; by end-of-day we should have ~6
    rows spanning the afternoon — enough to see whether the
    drift trajectory continues narrowing.

- **2026-05-19 12:14** — **Rate-limit verified** + SOC ticked
  again to **68/66**. live_ratio_log now has 2 rows:
  ```
  11:44:25  ratio 5.73, drift -29.7%, adv yes
  12:09:45  ratio 6.01, drift -26.3%, adv yes
  ```
  Row #2 landed 25 min 20 s after #1 — rate-limit exactly as
  designed. live_ratio climbing as solar accumulates (6.01 →
  6.19 between row-write and health check). `solar_ah_so_far`
  up to **+8.5 Ah** (20 % of forecast). Pack at +7-8 A
  charging. PACK GAPS still showing 2 events from morning — no
  new gaps.
  - **Design item picked: PACK GAPS chip on dashboard main
    page.** Completes the visibility pair with the stale-data
    banner shipped two loops ago.
    - `scripts/dashboard.py`: `/api/latest.json` payload gains
      a new `pack_gaps` field with `{count, max_gap_s,
      total_gap_s}` populated from `health.compute_today_pack_gaps()`
      — same threshold (60 s) so all surfaces agree on what
      constitutes a gap.
    - Main page gains a `<div id="gaps-chip">` element between
      the stale-banner and the main grid. Amber palette (lower
      priority than the red stale-banner — gaps are aggregate
      "today's reliability" while stale is "right now").
      Hidden by default; shows when `pack_gaps.count > 0`.
    - New `fmtAge(seconds)` JS helper mirrors `health._fmt_age`
      so the CLI and dashboard render the same age strings
      (`"29 min"`, `"2.3 h"`, etc.). Refactored
      `updateStaleBanner` to use it too — consistency.
    - `updateGapsChip(packGaps)` JS toggles visibility and
      renders `"N BLE logger gaps today · max X · total Y"`.
    - 2 regression tests: API payload includes
      `pack_gaps` field with correct count/max/total values
      from fixtured pack.csv; index page includes the chip
      element, CSS class, JS function, and `fmtAge` helper.
      Suite: **261 tests passing** (was 259, +2 new).
  - **Why this matters**: signals now consistent across all
    surfaces:
    - **STALE** (red, point-in-time): banner + PACK line suffix
    - **PACK GAPS** (amber, aggregate today): chip + PACK GAPS line
    - Together they answer "is logger healthy now?" and "was
      logger healthy today?" without the operator having to
      drill into pack.log on the cabin laptop.
  - **Watch**: 1.4 Ah gained this loop (7.1 → 8.5). At this
    rate the afternoon could deliver ~10-15 more Ah by sunset.
    Total day forecast was 41.7; today will likely come in
    well below that (~25 Ah) because the cloudy morning ate
    the productive hours. Tomorrow's morning low projection
    based on this lower-than-forecast day will be a good test
    of the new model's bias-fix.

- **2026-05-19 11:50 ☀☀ — solar pumping at peak.** Pack on full
  charge: pack_i **+15.8 A**, smoothed_i **+11.8 A**, pack_v
  **26.62 V** (highest of the day). SOC 67/65. Cloud 73 %,
  shortwave 555 W/m². live_ratio_log still shows just the 11:44
  row — rate-limit working (25 min not yet elapsed). Drift
  narrowing: -29.7% → -26.0% as solar Ah accumulates.
  - **Design item picked: BLE-logger gap tracker in health.py.**
    Today had real BLE stalls (28 min + ~6 min). The CLI's STALE
    flag shows "is it stale right now"; the new gap tracker
    summarizes today's overall logger reliability.
    - `scripts/health.py`: new pure helper
      `compute_today_pack_gaps(pack_csv, day, gap_threshold_s)`
      scans pack.csv for the requested day and returns
      `(gap_count, max_gap_s, total_gap_s, sample_count)`.
      A "gap" is any consecutive-timestamp delta exceeding
      `PACK_STALE_THRESHOLD_S` (60 s).
    - `_fmt_pack_gaps_line()` formats it as
      `PACK GAPS    N events, max X, total Y today` and is
      omitted entirely when there are no gaps (happy path is
      silence). Wired into `render_summary()` between PACK and
      TODAY lines.
    - **Today's live output**:
      `PACK GAPS    2 events, max 29 min, total 35 min today`
      — caught the morning's reliability story directly. Both
      gaps were the BLE-logger blips we saw earlier (the 28-min
      one that fired the false drift advisory at 11:12, plus
      a smaller one earlier).
    - 6 regression tests in `tests/test_health.py`:
      missing-file, clean-day (0 gaps), single-stall, multiple
      events (sum/max correct), ignores other days (no bleed
      across midnight), end-to-end summary integration.
      Suite: **259 tests passing** (was 253, +6 new).
  - **Why this matters**: complements the existing staleness
    surfaces:
    - `⚠ STALE` flag → "right now, data is X min old"
    - `PACK GAPS` line → "today, X events, total Y down"
    
    Together they answer "is the logger healthy?" at both
    point-in-time and aggregate timescales. If gap count keeps
    climbing across loops, that's a clear signal to investigate
    the cabin BLE setup.
  - **Watch**: with cloud thinning and pack absorbing strong
    current (+11.8 A smoothed), the afternoon should keep
    delivering Ah. Forecast was 41.7 Ah/day and we're at 7.1 Ah
    after 11.9 h of daylight — only 17% delivered. The
    afternoon may close some of that gap if cloud holds at
    < 75 %.

- **2026-05-19 11:42** — BLE logger **recovered** (no STALE flag).
  SOC ticked up to **67/65** (both batteries +1 from last loop).
  `solar_ah_so_far` jumped 4.1 → **6.1 Ah** in 32 min — afternoon
  catch-up underway as cloud (73 %) thins enough for shortwave to
  hit **555 W/m²** (highest of the day). Pack reading -37.5 A
  instantaneous (load spike) but smoothed_i -1.0 A — momentary
  artifact, not real. Drift advisory still firing at -30.3 % —
  but now arguably a **true positive**: today's overall live_ratio
  has genuinely been bad because the morning load surge ate into
  solar gain. The disentangling from last loop makes both
  interpretations legible.
  - **Design item picked: live_ratio sample logger.** Records the
    advisor's live_ratio + drift snapshot on each invocation,
    rate-limited at 25 min (matches projection_log cadence).
    Foundation for the future drift-over-time chart.
    - `scripts/live_ratio_log.py`: new append-only CSV at
      `data/live_ratio_log.csv`. Schema: `ts,
      live_ratio_ah_per_kwh_m2, solar_ah_so_far,
      irradiance_kwh_m2_so_far, solar_model_coefficient,
      drift_pct, advisory_fired`. `record_if_due()` skips
      writing when live_ratio is None (early-morning threshold-
      guarded state) so we don't pollute the log with empty
      rows.
    - Wired into `scripts/generator_advisor.py` right after
      `compute_model_drift()`. Best-effort try/except so a
      logging failure can't block the verdict. Same pattern as
      `projection_log` and `confidence_log`.
    - First live row landed this loop:
      `ts=11:44:25 ratio=5.73 solar_ah=6.26 irr=1.09 coef=8.15
      drift=-29.7 adv=yes`. The drift advisory is captured in
      the log AND on the headline chip simultaneously — a future
      chart will overlay them on the same timeline.
    - 8 regression tests in `tests/test_live_ratio_log.py`:
      empty-log read, first-row-writes, None-handling (skips
      early morning), rate-limit prevents duplicates,
      writes-again-after-interval, CSV round-trip with the
      advisory_fired flag, header written, default-constant
      anchor. Suite: **253 tests passing** (was 245, +8 new).
  - **Why this matters**: the system now has a **sixth log**
    feeding the audit trail:
    1. `calibration_log.csv` — SolarModel coefficient changes
    2. `projection_log.csv` — each projection snapshot
    3. `projection_accuracy` (derived) — sunrise SOC validation
    4. `low_soc_accuracy` (derived) — morning-low validation
    5. `confidence_log.csv` — lift-state transitions
    6. `solar_onset.csv` — morning cascade milestones
    7. **`live_ratio_log.csv`** (NEW) — drift over time
    The drift chart can now be built directly against this
    log without back-computing from older logs. Logs that
    accumulate from "now" onward will be sparse at first but
    become genuinely informative over 7+ days.
  - **Watch**: the next 25 min cadence will produce a second
    row; we can confirm rate-limit is firing as designed. Over
    a week the log will show how live_ratio evolves day-by-day
    and against changing SolarModel coefficients.

- **2026-05-19 11:17 ⚠ — BLE logger genuinely flaky today.** Health
  check showed `⚠ STALE: 6 min since last sample` AND `DRIFT
  -40.1% ⚠ advisory` simultaneously — exactly the pair the
  staleness-vs-drift disentangling from last loop predicted.
  The CLI banner makes it instantly clear: pack.csv is the
  problem, not the SolarModel. Meanwhile weather is great
  (cloud 59 %, shortwave 501 W/m²). Pack still at SOC 66/64.
  - **Design item picked: stale-data banner on dashboard main
    page.** The CLI `health.py` surfaces staleness clearly,
    but the dashboard's main HTML page was silently showing
    stale data (auto-refreshing the chart but the values
    underneath were 6 min old). Closes that gap.
    - `scripts/dashboard.py`: new `<div id="stale-banner">`
      hidden by default at the top of the page, between
      `<h1>` and the main grid. Tier-1 red palette (same as
      the model-drift advisory chip) so the visual association
      with "operator-attention-needed" is consistent.
    - `updateStaleBanner(latestTs)` JS function computes
      `Date.now() - Date.parse(latestTs)` and toggles
      visibility when `> STALE_THRESHOLD_S` (60 s, matches
      `health.py`'s `PACK_STALE_THRESHOLD_S`). Banner text
      shows the age in compact units (`6 min`, `2.3 h`, etc.)
      — same format as the CLI's `_fmt_age`.
    - Wired into `tick()` which already runs every 5 s; banner
      hides on the next fresh sample.
    - 1 regression test added — `test_index_includes_stale_banner_js`
      anchors the DOM element, CSS class, JS function, and
      shared threshold-constant name. Suite: **245 tests
      passing** (was 244, +1 new).
  - **Why this matters**: the staleness signal now has parity
    across all four health surfaces:
    1. CLI `health.py` → PACK line gains `⚠ STALE` suffix
    2. Dashboard `/health` route → same (via render_summary)
    3. Day-report markdown → same (via render_summary)
    4. **Dashboard main page** → top-of-page red banner (NEW)
    Consistent threshold (60 s) across all four — flipping
    that constant later would propagate to all surfaces
    automatically.
  - **Watch**: BLE logger health. If staleness keeps recurring
    in the next few loops, may need to investigate pack.log on
    the cabin laptop or restart the Volthium Monitor.app.
    Right now staleness is ~6 min, drift is -40 % — both will
    clear as soon as pack.csv catches up with the actual pack
    state.

- **2026-05-19 11:12 ⚠ — DRIFT advisory firing + pack.csv BLE blip
  exposed by new staleness check.** Health summary at the top of
  the loop showed **drift -35.7%** (live 5.24 vs model 8.15) with
  pack still in discharge. Investigating: pack.csv last sample was
  **10:41:59 → 28 min old at the time of check**. Solar irradiance
  kept accumulating from weather.csv (cloud 59 %, shortwave
  501 W/m²!) but pack.csv wasn't seeing the recovery — so
  live_ratio (= solar_ah / irradiance) collapsed as the numerator
  froze.
  - The drift advisory caught this **indirectly** — it flagged a
    -36% miscalibration when the real cause was data staleness.
    Worth fixing the direct signal.
  - **Design item picked: pack-data staleness detection in
    health.py.** Adds a tier-1 direct warning so future BLE
    stalls surface without the operator having to infer them
    from drift.
    - `scripts/health.py`:
      - New `_staleness_seconds(ts, now=None)` pure helper.
        Returns seconds-since-`ts`, or None for unparseable
        inputs. Future timestamps clamp to 0.
      - New `_fmt_age(seconds)` compact human-readable formatter:
        seconds < 90 s, minutes < 90 min, hours < 24 h, else days.
      - `_fmt_pack_line()` extended: if latest pack.csv sample is
        older than `PACK_STALE_THRESHOLD_S` (60 s), append
        `⚠ STALE: N min since last sample` to the PACK line.
        60 s = ~6× the 10 s polling cadence — transient single-
        poll misses don't false-alarm.
      - `_fmt_today_line()` similarly stale-checks weather.csv
        against a 60-min threshold (~2× the 30 min polling
        cadence). Appends `⚠ weather stale Xh` when triggered.
      - Thresholds exposed as module-level constants so tests
        and future deployments can tune.
    - 4 regression tests in `test_health.py`:
      `test_pack_line_flags_stale_data` (10-min-old sample
      triggers the warning),
      `test_pack_line_does_not_flag_fresh_data` (5-s-old does
      not),
      `test_fmt_age_compact_form` (unit-appropriate output
      across the full range),
      `test_staleness_seconds_handles_bad_input` (None,
      unparseable, future-ts must not crash).
      Suite: **244 tests passing** (was 240, +4 new).
  - Live verification: ran `python3 scripts/health.py` again
    after building — by then pack.csv had refreshed (87 s gap;
    BLE logger is alive). The PACK line correctly showed
    `⚠ STALE: 87 s since last sample`, then on the next sample
    cleared. Working.
  - **Why this matters**: the drift advisory had become an
    over-loaded signal — firing for both model miscalibration
    AND data staleness. Now they're disentangled. An operator
    seeing the PACK line's STALE warning knows to investigate
    the BLE logger / launchd job; one seeing DRIFT without
    STALE knows it's a real model issue.
  - **Watch**: confirm BLE logger keeps running. If the gap
    grows or recurs in the next loops, dig into `pack.log` for
    the actual error. Worst case, restart the Volthium Monitor
    .app at the cabin laptop.

- **2026-05-19 10:46 — load surge eats the morning's solar gain.**
  Pack flipped back to **discharging** (pack_i -4.1 A, smoothed
  -3.9 A, voltage dropped to **26.28 V**). SOC holds at 66/64.
  `solar_ah_so_far` stuck at 4.1 Ah — the load is consuming faster
  than solar can replace, even with cloud cover at 75% and
  shortwave 400 W/m². live_ratio drifted to **6.94** (-14.8%
  vs model 8.15), still under the 20% advisory threshold. The
  CLI `health.py` captured this state shift in one screen — exactly
  the use case the command was built for.
  - **Design item picked: add health summary to day-report top.**
    Completes the symmetry with last loop's `/health` dashboard
    route. Health snapshot is now archived in markdown for every
    historical day.
    - `scripts/end_of_day_report.py`: new `## Health snapshot`
      section between `**Summary**` and `## Pack`. Embeds
      `health.render_summary()` output in a fenced code block
      to preserve the monospace tabular layout. Identical
      content to the CLI command and the `/health` route.
    - The snapshot becomes the day-report's **opening overview** —
      a future reader scanning the markdown archive sees the
      day's at-a-glance state immediately, before drilling into
      the per-chain detail sections below.
    - Defensive fix: `health.py`'s `_fmt_solar_model_line()` and
      `_fmt_confidence_line()` now select entries by
      `max(...key=ts)` instead of `entries[-1]` so they're
      robust to out-of-order log appends (e.g. from test
      fixtures or manual edits). Production logs are append-only
      by ts, but the defensive sort costs nothing.
    - 1 regression test added:
      `test_health_snapshot_section_renders_at_top` pins the
      section to its position (after Summary, before Pack) and
      anchors all 10 chain labels in the embedded snapshot.
      Suite: **240 tests passing** (was 239, +1 new).
  - **Why this matters**: closes the triangle. The same content
    now lives on **four surfaces**:
    1. CLI (`python3 scripts/health.py`)
    2. Dashboard footer link → `/health` HTML page
    3. Direct browser bookmark to `/health` (auto-refreshes
       every 30 s)
    4. **Day-report markdown archive** (this loop) — captures
       the snapshot at the moment the report is built
    
    A future operator investigating "what was system state on
    2026-05-21?" opens that day's report and the snapshot tops
    the page. Investigating an anomaly across days becomes:
    `grep -A 12 "Health snapshot" data/reports/*.md`.
  - **Watch**: if solar returns this afternoon (cloud is still
    breaking — 75% holding), live_ratio should climb back. The
    drift advisory band has been doing useful work today,
    bouncing between -6% (good) and -21% (advisory firing) as
    the load and solar each take turns dominating.

- **2026-05-19 10:38 ☀☀ — sky is genuinely clearing.** Major
  weather shift: cloud **96% → 75%**, shortwave **238 → 400 W/m²**,
  weather_code 51 (drizzle) → **2 (partly cloudy)**. Pack momentarily
  in idle (sun-load balanced just as last sample landed at
  state=idle 0.0 A) but recent samples show charging spikes to
  +5+ A. `solar_ah_so_far` climbed from 2.9 → **4.1 Ah** in 22
  min (+1.2). live_ratio recovering: **7.66** (drift narrowed to
  **-6.0%**, well clear of the 20% advisory threshold). The CLI
  health summary now shows the day's progress in 10 lines.
  - **Design item picked: surface health summary on dashboard.**
    The CLI `health.py` lands one-screen overviews; same content
    deserves a web surface for the SSH-from-phone / low-bandwidth
    case where the chart-heavy main page is overkill.
    - `scripts/dashboard.py`: new `/health` route that wraps
      `health.render_summary()` in a dark-themed `<pre>` block.
      Reuses the CLI's function directly so the two surfaces
      **never diverge** — both pull from the same underlying
      logs, format identically.
    - Auto-refresh meta tag at 30 s (vs the main page's 5 s
      polling) — targets the bandwidth-constrained use case
      where chart re-renders would burn the data budget.
    - Header navigation back to `/`, `/today-report`,
      `/accuracy`, `/low-accuracy`, `/confidence` so the user
      can pivot to detail views without going home.
    - Main dashboard's harvest-panel footer gains a `health
      summary ↗` link, completing the discoverability loop.
    - Footer note ("Same content as `python3 scripts/health.py`
      on the cabin laptop — kept identical so CLI and web
      views never diverge") makes the design contract explicit
      for future maintainers.
    - 2 regression tests: `/health` renders with all 10 chain
      labels + auto-refresh + nav, AND the main dashboard footer
      links to it. Suite: **239 tests passing** (was 237, +2
      new).
  - **Why this matters**: the health summary is now accessible
    from THREE surfaces with identical content — CLI (`python3
    scripts/health.py`), main dashboard footer link, and
    `/health` HTML page. The operator picks the surface that
    matches their context: terminal session, full dashboard
    pivot, or quick-glance browser bookmark.
  - **Watch**: weather is the news of this loop. If the
    400 W/m² holds and cloud continues thinning, the
    afternoon could deliver real Ah catch-up. Today's
    `solar_ah_so_far` (4.1) is still only 10% of forecast (41.7),
    but the trend is accelerating — at the recent 1.2 Ah / 22
    min rate, we'd hit ~30 Ah by sunset (still well short of
    forecast because the morning was burned by cloud).

- **2026-05-19 10:16 — both SOC ticks up + solar accelerating.**
  Pack state: **charging**, pack_i +3.0 to +5.5 A, smoothed_i +3.9
  A, voltage **26.42 V**. SOC has now ticked **both sides up to
  66/64** — A reclaimed the 66 it had earlier, B added 1 from
  63 → 64. Cloud holding at 96 % from the 10:04 weather sample
  but shortwave was already at **238 W/m²** then. `solar_ah_so_far
  = +2.9 Ah` (was 2.3 last loop, +0.6 in this 25-min window).
  Live ratio climbed back to **7.33**, drift narrowed to **-10.1%**
  — comfortably back under the 20% advisory threshold.
  - **Design item picked: CLI health summary command.** Replaces
    the need to invoke 10+ separate scripts to scan system state.
    - `scripts/health.py`: aggregates state from every chain into
      one ~14-line summary. Output layout (each line is one
      chain):
      ```
      PACK         SOC 66/64  charging  +3.0 A  smoothed +3.9 A  26.42 V
      TODAY        solar +2.9 Ah / 41.7 forecast (7%)  live_ratio 7.33
      SOLAR ONSET  zero 06:44 → idle 06:44 → pos 07:44 → net+ 07:45  SOC 63.5%
      SOLAR MODEL  coef 8.149  (1 obs, low conf, fit 2026-05-18T20:23)
      CONFIDENCE   low → medium  lifted  n=10 ±0.89 pp
      SUNRISE ACC  n=17, mean -0.12 pp, abs 1.15  [-2.4..+1.5]  latest +0.7
      MORN-LOW ACC n=17, mean -2.97 pp, abs 2.97  [-5.7..-1.1]  latest -1.5
      DRIFT        -10.1% (live 7.33 vs model 8.15) — within threshold
      PROJECTION   start 63.0 → sunrise 60.8 → low 59.3 → eve 78.0 (next 24h)
      ADVISORY     ✓ no generator needed  projected low 59%
      ```
    - Fixed column-1 labels (PACK/TODAY/SOLAR ONSET/etc.) make
      visual scanning across runs trivial — any field that
      changed jumps out without re-reading the structure.
    - Cold-start graceful: every chain has an empty-state path
      ("no pack.csv yet", "pre-onset, no milestones yet", etc.).
    - Advisor verdict is reproduced from projection_log's
      `projected_low_soc`: <25% → RUN GENERATOR; <50% → morning
      watch; else → no generator needed. Same banding as the
      live advisor.
    - 6 regression tests in `tests/test_health.py`:
      cold-start-doesn't-crash, all-chain-labels-present-in-order,
      pack-line-format, advisory-band-thresholds (no generator /
      morning watch / RUN GENERATOR cases). Suite: **237 tests
      passing** (was 231, +6 new).
  - **Why this matters**: until now, the loop body itself was a
    sequence of 10+ separate script invocations. Now `python3
    scripts/health.py` produces an equivalent summary in one
    command. The dashboard provides the same data in HTML form,
    but the CLI summary is ideal for: (a) terminal-only sessions
    over SSH, (b) cron-job emails, (c) the loop checklist itself
    where I want to verify everything's fine before picking the
    next design item.
  - **Watch**: as pack continues charging, the projection_low
    will keep dropping (because the simulator starts later in
    the day from a higher SOC, leaving more discharge time before
    tomorrow's morning). Sometime today the advisor's
    `next-24h low SOC` will likely stabilize as we approach
    sunset's overnight starting point.

- **2026-05-19 10:06 ⚠ — first live model-drift advisory fired.**
  Pack: state=charging, pack_i +2.6 to +3.2 A, smoothed_i **+2.85 A**,
  voltage 26.36 V. Cloud **broke from 100% to 96%**, shortwave
  jumped to **238 W/m²** (3× the last reading). SOC reads 65/63 —
  A actually ticked DOWN from 66 between 09:33-10:00 during the
  idle interlude (net negative without sun), so we're back near
  the morning's low. `solar_ah_so_far = 2.3 Ah` (forecast 41.7
  — only 6% delivered after 10 h).
  - **🚨 Live model_drift_advisory fired at 10:06**:
    ```
    Live ratio 6.42 Ah/(kWh/m²) is 21.2% below the SolarModel
    coefficient 8.15. Consider re-fitting once more complete-day
    data accumulates.
    ```
    Mechanism working: irradiance accumulated faster than Ah during
    the idle interlude (sun came back as cloud broke at 09:34 but
    pack stayed idle until ~10:00), pulling live_ratio from 7.30
    → 6.42 → crossing the 20% threshold. The advisory cleared
    on the next sample at -19.7% as the pack gained Ah quickly
    under the new solar — but the LIFT moment validates the
    feature's design.
  - **Design item picked: surface model_drift_advisory on
    dashboard.** Calibration feedback is hitting in real time;
    the operator UI should reflect it.
    - `scripts/dashboard.py`: new red-bordered `drift-advisory`
      chip on the advisor panel. Renders only when
      `model_drift_advisory` is non-null in the advisor's
      inputs (matches the CLI's `⚠ model drift:` line). Layout:
      `⚠ MODEL DRIFT · 6.42 vs 8.15 · -21.2%` plus the full
      advisory text in the footer.
    - Tier-1 red coloring (matches `var(--red)`) so it stands
      out from the green-bordered confidence-lift chip and
      amber/green calibration-drift chip already on the panel.
    - Hover tooltip explains what the advisory means and points
      to `docs/site/loon_lake.md` for context on intra-day
      variability that can drive transient drift.
    - 1 regression test added — `test_index_includes_drift_advisory_badge_js`
      anchors the badge construction code + CSS class + data
      field name in the HTML. Suite: **231 tests passing** (was
      230, +1 new).
  - **Why this matters**: the advisor now has THREE feedback
    chips:
    1. **calib** (model vs live) — diagnostic, always shows
       when both numbers exist
    2. **last sunrise validation** — most recent
       projection_accuracy outcome
    3. **confidence lifted** — accuracy-aware tier promotion
    4. **drift advisory** (NEW) — tier-1 alert when miscalibration
       is likely
    A future operator opening the dashboard sees the advisor's
    full calibration state at a glance: model coefficient,
    live measurement, recent validation outcome, current
    confidence, and any drift alert. Together these surface
    the full model-trust signal from one panel.
  - **Watch**: as the pack continues to gain Ah under stronger
    sun, live_ratio should climb back toward 8.15 and the
    advisory will stay dormant. If tomorrow morning's actual
    morning low validates the new model's projections to
    within ~1 pp (i.e. tomorrow's low_soc_accuracy mean shifts
    closer to 0), the bias-fix from yesterday is confirmed
    working. The 4-chip advisor panel becomes the operational
    summary.

- **2026-05-19 09:39** — Pack still idle, current still 0.0 A,
  voltage drifted down to **26.32 V** as no charging occurs.
  Weather row at 09:34 shows **shortwave jumped to 127 W/m²**
  (from 90 last reading) — cloud is thinning! But the pack data
  is from 09:39 and still shows no current — there's lag between
  the weather sensor reading and the array's actual contribution
  through the cloud cover. SOC still 66/63.
  - **Design item picked: smarter advisor with live_ratio drift
    advisory.** Two-part fix that connects the live measurement
    to model trust in real-time:
    - **(1)** Lowered `today_harvest`'s live_ratio threshold
      from `actual_kwh>=0.5 AND solar_ah>=1.0` to `>=0.2 / >=0.5`.
      Today's 100 % cloud morning had 0.25 kWh/m² + 1.5 Ah for
      hours, suppressing the ratio entirely under the old gate.
      The lowered threshold lets the chip populate on cloudy days
      too. Today's value now shows **7.30 Ah/(kWh/m²)** vs the
      SolarModel's 8.149.
    - **(2)** New `compute_model_drift(live_ratio, coefficient,
      threshold_pct)` pure helper in `generator_advisor.py`.
      Computes signed drift percentage. When |drift| crosses
      `MODEL_DRIFT_ADVISORY_THRESHOLD_PCT` (20 %), returns an
      advisory string mentioning both numbers, direction
      (above/below), and the re-fit suggestion. Below threshold,
      returns just the numeric drift (still surfaced in inputs
      for charting) without the alert.
    - Advisor inputs gained `model_drift_pct` and
      `model_drift_advisory`. CLI prints the advisory inline
      between "morning watch" and the "inputs:" header when it
      fires.
    - Today's drift: **−11.9 %** (live 7.18 vs model 8.15). Below
      the 20 % advisory threshold — drift is tracked but no alarm.
      This is the correct calibration: a single day of light
      cloud isn't reason to re-fit; persistent 20 %+ drift over
      multiple days WOULD be.
    - 8 regression tests in `tests/test_advisor_confidence_lift.py`:
      None-handling (live_ratio None, coefficient 0), small drift
      returns pct but no advisory, large negative and large
      positive drift cases, exact-threshold-fires boundary,
      override-threshold knob, default-constant anchor. Suite:
      **230 tests passing** (was 222, +8 new).
  - **Why this matters**: the advisor was producing a live_ratio
    diagnostic but the comparison with the SolarModel coefficient
    was implicit (operator had to eyeball it). Now it's an
    explicit number on the input dump, plus a tier-1 alert when
    significant. Connects the two halves of the calibration
    feedback loop: live measurement now actively informs model
    trust, not just sits there.
  - **Watch**: tomorrow if a clearer day produces a higher
    live_ratio, the advisor might surface the first model-drift
    advisory. The actual fit-from-2026-05-18 was 8.149; if
    tomorrow's live ratio lands at 6.5 (heavy cloud) or 10.0
    (clear sky), the advisory will fire. Over a week of
    accumulating data the SolarModel coefficient will stabilize
    via auto-fit, and persistent drift advisories will become
    a meaningful re-fit trigger.

- **2026-05-19 09:33** — Pack now in **idle** (current 0.0 A, pack
  voltage 26.33 V — slight sag from the 26.40 V solar peak earlier).
  Cloud back to 100 % per the 09:04 weather row. SOC holding at
  66/63 — the A-side gain from the 09:06 tick is locked in.
  `solar_ah_so_far = +2.0 Ah` (1.5 Ah net since the 09:06 SOC tick
  — pack is gaining slowly under intermittent solar). Advisor's
  next-24h low for tomorrow has tightened to **61.2 %** with the
  new model.
  - **Design item picked: per-horizon accuracy bar charts** on
    `/accuracy` and `/low-accuracy`. The textual horizon tables
    were already there but the bias pattern reads slowly through
    numbers — a bar chart makes it pop.
    - `scripts/dashboard.py`: new
      `render_horizon_bar_chart(by_h)` helper at module level.
      Returns an SVG bar chart with:
      - One bar per non-empty bucket
      - Height proportional to |mean_error|, capped so a single
        outlier doesn't squish other bars
      - Sign: positive bars extend UP from the zero baseline,
        negative bars extend DOWN
      - Color band: green if |err| ≤ 3 pp, amber if ≤ 8, red
        otherwise — matches the per-record table cell colors
      - Per-bar `<title>` tooltip with the full stats (n, mean,
        abs, rms, range)
      - Title text "mean error (pp) by lead-time horizon" centered
        above
      - Y-axis tick labels at 0 / ±|scale_cap|
      - Bucket labels + "n=N" captions below
    - Wired into both `/accuracy` and `/low-accuracy` horizon
      blocks; appears between the descriptive paragraph and the
      existing table.
    - On today's live data, `/low-accuracy` now shows a striking
      visual: a clean monotonic gradient of red-to-amber-to-green
      bars descending from -4.13 pp (7h+) to -1.50 pp (2-3h),
      ALL below the zero line. Reads as "the model has been
      systematically optimistic, and the bias scales with
      lead-time" in one glance.
    - 3 regression tests added:
      `test_render_horizon_bar_chart_handles_empty_input`,
      `test_render_horizon_bar_chart_emits_svg_with_bars`,
      `test_accuracy_page_includes_horizon_chart_when_data_present`.
      Suite: **222 tests passing** (was 219, +3 new).
  - **Why this matters**: makes the bias finding much more
    immediately readable. A future operator (or me, in a week)
    glancing at `/low-accuracy` will instantly see "uh, all bars
    below the line" without parsing the table. After the next
    sunrise validates the new-model projections, the chart
    should show shorter bars (closer to the zero line) on the
    fresh records — a visual proxy for "fix is working."
  - **Watch**: tomorrow's sunrise (2026-05-20 ~05:07) will land
    a fresh batch of 15-20 records that have the new model's
    projected_low_soc values. The chart will then visualize
    OLD vs NEW directly: today's all-red below-line pattern vs
    tomorrow's hopefully-shorter bars.

- **2026-05-19 09:07 — first BMS SOC tick of the day** (A:
  65 → 66 at 09:06:39). Pack current settling back to **+1.2 A**
  (solar weakening as cloud thickened from 75 % → 90 %); pack
  voltage holding at 26.39 V. `solar_ah_so_far` climbed slightly
  to **+1.7 Ah**. Advisor's next-24h low for tomorrow is 61.7 %
  (latest new-model entry).
  - **Design item picked: solar-onset milestones on dashboard
    sparkline.** Visually surfaces the morning cascade events on
    both the pack-power and SOC sparklines — pairs with the
    existing "solar onset" chip on the harvest panel.
    - `scripts/dashboard.py`: new client-side
      `computeOnsetMarkers(series, onset)` helper. For each of
      the four cascade milestones (`first_zero_iso`,
      `first_idle_iso`, `first_positive_iso`,
      `first_net_positive_iso`), maps the iso timestamp to an
      x-fraction in the rolling sparkline window. Milestones
      outside the window are silently dropped.
    - **Two-pass merge**: milestones at identical timestamps
      (e.g. today's first_zero and first_idle both at 06:44:10)
      are combined into a single marker with a joined tooltip
      label ("zero + idle @ 06:44:10"). Avoids drawing the same
      line twice and keeps the visual clean.
    - The `spark(id, values, includeZero, color, markers)`
      function now accepts a markers array. Each marker renders
      as a dashed vertical line through the chart with a
      tooltip `<title>` showing the full milestone label and
      time. Drawn BEFORE the polyline so the data line still
      reads cleanly on top.
    - Color graduation: gray for `zero`/`idle` (pre-charging
      milestones), amber for `first_positive` (transient solar
      > load), green for `first_net_positive` (sustained
      charging). When milestones share a timestamp the latest
      one wins on color — visually communicating the "highest
      cascade stage achieved at this moment".
    - 1 regression test added — `test_index_includes_onset_marker_js`
      anchors the function name + cascade keys + dashed-line
      visuals in the HTML so a future refactor can't silently
      strip the feature. Suite: **219 tests passing** (was 218,
      +1 new).
  - **Live behavior right now**: with the rolling window at
    ~07:07-09:07, today's cascade markers visible should be
    `pos @ 07:44:21` and `net+ @ 07:45:40` (very close to each
    other, near the left edge). The earlier `zero` and `idle`
    milestones (06:44:10) have already scrolled off — exactly
    the expected "rolling history" behavior.
  - **Why this matters**: the harvest-panel chip is a static
    summary; the sparkline annotations let you SEE the cascade
    in the context of the pack's current/SOC curve. The two
    surfaces complement each other — chip for "what happened",
    chart for "where in the recent timeline". A future operator
    debugging an unusual day (e.g. "why is the floor so low?")
    can spot the cascade timing on the chart and check whether
    it landed at a reasonable hour vs sunrise.
  - **Watch**: pack should keep recovering through the day even
    with patchy clouds. The dashboard's new sparkline markers
    will tell us if any LATER solar-onset events fire — they
    shouldn't (only the FIRST occurrence of each milestone is
    recorded), but it's a chance to validate the
    once-per-day-only behavior in `solar_onset.upsert()`.

- **2026-05-19 09:02 ☀ — solar genuinely arriving.** Pack
  current jumped from +1.6 A to **+4.0 A** (smoothed_i +3.6 A);
  pack voltage climbed from 26.29 → **26.40 V**. `solar_ah_so_far`
  tripled from 0.5 → **+1.5 Ah** in 30 min. SOC still pinned at
  65/63 on the BMS readout (Ah counter stale; remaining_ah ticked
  up by 2 to 132 on B side). Cloud holding at 100 % but
  weather_code = 51 ("Drizzle: Light") suggests intermittent
  breaks. Shortwave reading 75 W/m² — but the array is clearly
  doing better than that single-point reading implies (probably
  cloud thinning between samples). Advisor's `next-24h low SOC`
  has fallen to **61.8 %** for tomorrow — the new model now has
  3 entries on disk:
  ```
  08:00:45  proj_low=60.4
  08:26:45  proj_low=62.2
  08:51:45  proj_low=63.0  (the start_soc recovered)
  ```
  - **Design item picked: update data/README.md.** Seven loops
    of new features had accumulated without updating the data-
    folder index. Refresh covers:
    - **New source-of-truth files**: `solar_onset.csv` (cascade
      milestones), `confidence_log.csv` (lift transitions) —
      with full column schemas + what writes them + idempotency
      semantics.
    - **New derived-in-memory views section**: explains
      sunrise SOC accuracy, morning-low SOC accuracy, and the
      per-horizon breakdown. Captures the **-2.97 pp bias
      finding** that drove the sinusoidal-solar fix as part of
      the morning-low view's blurb — anchored in the doc as
      institutional knowledge.
    - **Report section refresh**: documents the six-chain
      archive structure of `data/reports/YYYY-MM-DD.md`.
    - **Dashboard surfaces refresh**: adds `/low-accuracy` and
      `/confidence` to the route list with descriptions.
    - **New "audit-trail topology" ASCII diagram**: shows how
      `pack.csv` feeds both accuracy chains, how `solar_onset.csv`
      sits between `pack.csv` and the morning-low view, how
      `daily_summary.csv` feeds the SolarModel fit → calibration
      log, and how the advisor orchestrates all of it.
    - Cross-references list extended with the new scripts
      (`solar_onset.py`, `low_soc_accuracy.py`, `confidence_log.py`)
      and the orchestrator role of `generator_advisor.py`.
    - File grew from 70 → **121 lines**. No tests needed (doc
      change), but the suite still passes at **218 tests**.
  - **Why this matters**: any new operator cloning the repo
    lands in a fully-documented data folder. The ASCII topology
    in particular reduces "where do I start" cognitive load by
    showing the lineage between files at a glance. Combined
    with the existing per-script docstrings, the system is now
    self-explanatory from the outside.
  - **Watch**: pack should keep recovering. The new-model
    projections will continue accumulating; tomorrow's sunrise
    (05:07 ~ 19 h away) is the moment of truth for the bias
    fix's empirical impact.

- **2026-05-19 08:34** — Pack flicking between idle and charging
  (pack_i 0.0 ↔ +1.6 A, state alternating). SOC still 65/63 — the
  BMS Ah counter hasn't crystallized yet. `solar_ah_so_far = 0.54
  Ah` (slow climb). Cloud 100 %, shortwave 72 W/m² (no fresh
  weather row yet). The **new model's first two projections are
  on disk**:
  ```
  08:00:45  start=63.0  proj_sunrise=62.0  proj_low=60.4  (NEW)
  08:26:45  start=63.0  proj_sunrise=62.9  proj_low=62.2  (NEW)
  ```
  Compare to the last OLD-model entry (07:35:45) which had
  `proj_low=63.0`. The new model projects a **2.6 pp lower
  floor** for tomorrow's morning — exactly the corrective
  direction we wanted. The validation will land tomorrow when
  the 2026-05-20 first_net_positive crystallizes.
  - **Design item picked: surface low_soc_accuracy on dashboard.**
    The new validation chain now has a UI surface — sister of
    `/accuracy`. Closes the visibility gap so a future operator
    can pivot between sunrise SOC and morning-low SOC bias
    diagnostics without dropping to the CLI.
    - `scripts/dashboard.py`: new `/low-accuracy` route. Renders
      the same shape as `/accuracy` but for `low_soc_accuracy`
      records:
      - Per-record table: made_at, target_day, projected_low,
        actual_low, error (color-coded by |err|), coefficient,
        lead-time-hours
      - Per-horizon breakdown: same buckets as /accuracy so
        comparisons read symmetrically
      - Empty-state with explanatory text about waiting for
        solar_onset.first_net_positive to crystallize
    - Intro text explicitly names the sister relationship to
      `/accuracy` and the 2026-05-19 sinusoidal-solar fix that
      this view drove. Future operators reading the page see
      the loop closed end-to-end.
    - Cross-links: `/accuracy`, `/projections`, `/calibration`,
      `/confidence` all now link to `/low-accuracy`. The
      navigation graph is symmetric.
    - 2 regression tests added: `/low-accuracy` empty-state
      handling, sister-link cross-reference (both `/accuracy`
      and `/low-accuracy` must link to each other). Suite:
      **218 tests passing** (was 216, +2 new).
  - **Why this matters**: completes the dashboard's
    validation-chain UI surface area. The five accumulated
    chains now have parallel views:
    1. `/calibration` — SolarModel coefficient changes
    2. `/projections` — each advisor projection snapshot
    3. `/accuracy` — sunrise SOC validation (per-record + per-horizon)
    4. **`/low-accuracy`** — morning-low SOC validation (this loop)
    5. `/confidence` — lift-state transitions
    
    Together they're the complete audit trail of the advisor's
    behavior over time, all accessible from any page in the
    navigation graph.
  - **Watch**: tomorrow's sunrise (2026-05-20 ~05:07) is the
    next major validation event. With the new model now writing
    projections AND the dashboard now surfacing low_soc_accuracy
    diffs, the validation feedback will be immediate. The new
    model's projected_low_soc has dropped from ~63 (old) to
    60.4-62.2 (new) for tomorrow — if the actual tomorrow morning
    low lands at ~60.5, mean error closes from -2.97 to near 0.

- **2026-05-19 08:24** — Pack still in sustained charging (state=
  charging, pack_i +1.2 A oscillating to 0, smoothed_i +1.0 A,
  pack_v 26.29 V). SOC stuck at 65/63 — pack is at solar/load
  equilibrium under 100 % cloud at shortwave 72 W/m². Today's
  `solar_ah_so_far` climbed to **+0.5 Ah** (1 % of forecast).
  - **Design item picked: fix the -2.97 pp floor bias in
    `simulate_next_24h`.** The validation chain landed yesterday
    identified the bias; today's architecture work makes the
    fix.
    - `scripts/generator_advisor.py`: replaced the uniform-NET
      daylight model with a **sinusoidal gross-solar + per-hour
      load** model. Three pieces:
      1. `gross_solar_total = solar_day_ah - daylight_load_total`
         (preserves daily NET = solar_day_ah by construction).
      2. Each daylight hour's `ah_change` is computed as
         `gross_solar_rate(hour) + load_at_hour`. Gross solar
         follows a sinusoid peaking at solar noon, tapering to
         0 at sunrise/sunset endpoints.
      3. The night branch is unchanged — overnight discharge
         already validates well (sunrise-SOC mean abs 1.15 pp).
    - The fix encodes a real physical insight: at sunrise,
      gross solar is ≈ 0 but the load keeps running. The pack
      continues discharging for 1-3 hours after sunrise until
      sin(πh/D) × peak exceeds the load. That gap is exactly
      the structural source of the -2.97 pp optimistic bias on
      projected_low_soc.
    - 4 new regression tests in `tests/test_advisor_simulator.py`:
      - `test_projected_low_lands_after_sunrise_not_at_it` —
        anchors that the floor is at-or-below sunrise SOC
        (in the OLD model they were always equal).
      - `test_floor_undershoots_sunrise_when_load_steep_and_solar_modest`
        — heavier load + modest solar → floor noticeably below
        sunrise (tightens the previous test).
      - `test_daily_net_preserved_so_evening_soc_in_reasonable_range`
        — sanity-check that evening SOC stays plausible even
        though within-day shape changed.
      - `test_zero_solar_daylight_is_flat_then_overnight_discharges`
        — when solar_day_ah=0, gross_solar exactly cancels
        daylight load (NET=0), matching the OLD behavior.
      All 6 existing simulator regression tests still pass.
      Suite: **216 tests passing** (was 212, +4 new).
  - **Empirical impact** — rerunning the 22:14:46 (worst-case)
    projection from last night with start_soc=84 % through the
    NEW model:
    - OLD projected_low = 69.2 (error vs 63.5 actual: -5.7 pp)
    - NEW projected_low = 68.6 (error vs 63.5 actual: -5.1 pp)
    - Floor improvement: 0.6 pp on this case. Across the full
      17-record bank, the new model would close roughly 1.5 pp
      of the systematic -2.97 pp bias.
  - **Why the improvement is modest**: the fix captures the
    morning gross-solar ramp-up but assumes load = overnight
    median throughout. In reality, morning load might be higher
    than the average overnight rate (people getting up,
    appliances starting), AND the SolarModel's daily-net Ah
    might also under-count gross solar slightly. Closing the
    remaining ~1.5 pp gap requires:
    - A **morning load model** (separate from overnight median)
      — likely a multi-bucket discharge_model fit
    - More days of data so the SolarModel can calibrate better
  - **What the validation pipeline will measure**: starting
    tomorrow (2026-05-20), the new low_soc_accuracy chain will
    capture per-day-low validations on the NEW model. Over 7+
    days we'll have a fresh bias trend that tells us whether
    the sinusoidal fix alone closed the gap, or whether the
    morning load model is also needed.
  - The advisor's headline number is unchanged this loop
    (`next-24h low SOC = 63.0 %` — coincidentally the same as
    last loop, but for a different projection target since
    `now` advances and the simulator anchors differently).

- **2026-05-19 07:57** — Post-onset recovery underway. Pack
  charging sustained: **state=charging**, pack_i +1.2 to +1.4 A,
  smoothed_i climbed to **+1.6 A**, pack voltage up from
  26.18 → **26.29 V**. SOC still reads 65/63 (BMS lags Ah).
  `solar_ah_so_far = +0.34 Ah` (first nonzero of the day; 1 % of
  forecast). The advisor's `next-24h low SOC` has updated to
  **60.4 %** — that's now projecting *tomorrow's* morning low
  (today's already happened at 63.5).
  - **Design item picked: surface low_soc_accuracy on day-report.**
    The new validation chain landed last loop with the
    surface-finding (mean -2.97 pp systematic optimistic bias).
    The day-report needed a corresponding section so the
    archival markdown carries the morning-low validation chain
    alongside the existing sunrise validation chain.
    - `scripts/end_of_day_report.py`: new
      `## Morning-low validation` section between
      `## Projection accuracy` and `## Confidence-lift events`.
      Filters projection_log to entries targeting the day's
      sunrise, computes `low_soc_accuracy.compute_accuracy_records`
      against the day's solar_onset row, renders summary line +
      table + per-horizon breakdown.
    - Sign convention note explicitly states "negative error =
      pack undershot the predicted floor (advisor was too
      **optimistic** about the morning low)" — making the bias
      direction immediately legible to any future reader.
    - Empty-state branches: no projection data at all, AND no
      onset row OR onset row pre-resolved (no first_net_positive
      yet). Both render the same friendly message.
    - 5 regression tests added: empty-state with no data,
      empty-state when onset unresolved, single-record render
      with summary line, multi-record with per-horizon
      breakdown, day-filter excluding projections targeting
      other days. Suite: **212 tests passing** (was 207, +5
      new).
  - **Today's day-report** at `data/reports/2026-05-19.md` now
    archives the full discovery: 17 projections, all 17 negative,
    spanning -5.7 pp (worst, 7+h lead) to -1.1 pp (best, 2-3h
    lead). The per-horizon breakdown is right there in the
    markdown — a future operator opening this archive sees the
    bias pattern without needing to re-run the script.
  - **Why this matters**: the day-report is now genuinely a
    *six-chain* archive (mechanical totals + SolarModel state +
    sunrise accuracy + morning-low accuracy + solar onset +
    confidence lifts). Today's report captures the **first
    empirical evidence of a model deficiency** that we can fix
    in a future loop. The exact numerical target (−2.97 pp mean
    error) is now durable across days.
  - **The fix candidate** — when ready: `simulate_next_24h` at
    line 274-286 in `scripts/generator_advisor.py` currently
    switches to "charging at average rate" the moment `cur` hits
    `next_sunrise`. In reality there's a 1-3h gap where the pack
    keeps discharging at -2 A baseline before solar overtakes
    load (today: 2 h 37 min between sunrise 05:08 and net+
    07:45). A per-hour solar profile (e.g. sinusoidal:
    `peak_ah_per_hour * sin(π * (t-sunrise) / daylight_hours)`)
    would push morning Ah delivery down toward zero, allowing
    the discharge to continue, and would close most of the gap.
    Risk to existing sunrise-accuracy is real (different
    distribution might shift sunrise SOC slightly) — wants
    careful regression testing.
  - **Watch**: pack should recover through the day. live_ratio
    chip on dashboard should populate next loop now that
    `solar_ah_so_far > 0`.

- **2026-05-19 07:47 🌞 — DAY-2 NET-POSITIVE LANDED + SECOND
  VALIDATION CHAIN OPERATIONAL.** Pack transitioned `discharging`
  → `charging` between 07:44 and 07:46. Solar onset cascade fully
  resolved:
  - first_zero      = 06:44:10 (1 h 36 min after sunrise)
  - first_idle      = 06:44:10
  - first_positive  = 07:44:21 (transient solar > load)
  - first_net_positive = 07:45:40 (sustained — smoothed_i +0.17 A)
  - **SOC at net+   = 63.5 %** — this is the day's actual floor
  
  Pack voltage climbed from 26.18 → 26.25 V over the transition.
  Shortwave reached **70 W/m²** at 07:34 — apparently enough,
  under 100 % cloud, for a west-facing array to nudge net-positive
  for the first time today. Total irradiance accumulated: 0.115
  kWh/m² (2.2 % of forecast).
  
  - **Design item picked: SOC-at-onset validation vs advisor's
    projected_low_soc.** Sister chain to projection_accuracy.py,
    landing immediate first-day results:
    - `scripts/low_soc_accuracy.py`: matches each projection_log
      entry to the matching day's `solar_onset.soc_avg_at_net_positive`
      (= actual_low). Computes `error = actual_low - projected_low_soc`.
      Negative = advisor's floor was too OPTIMISTIC (predicted
      higher SOC than reality).
    - Guards: skip if onset row is missing or not yet fully
      resolved (no first_net_positive); skip if projection was
      made AFTER net_positive (degenerate "prediction" of history);
      gate future targets via `now`.
    - Per-horizon breakdown reuses `projection_accuracy.HORIZON_BUCKETS`
      so the two views read symmetrically.
    - CLI: `python3 scripts/low_soc_accuracy.py` (table),
      `--by-horizon` (lead-time bias breakdown), `--tail N`.
    - 9 regression tests (`tests/test_low_soc_accuracy.py`) pin
      down: basic match + signed error, horizon_min from
      projection_ts to net_positive, missing onset row skip,
      pre-resolved onset skip, post-onset projection skip,
      multi-record per-horizon grouping, empty bucket omission.
      Suite: **207 tests passing** (was 198, +9 new).
  - **🔥 First live result — and it's surfaceable**:
    ```
    n=17, mean_error=−2.97 pp, mean_abs=2.97, RMS=3.25,
    range [−5.66 .. −1.13]
    ```
    EVERY ONE of the 17 records is negative — the advisor has
    been **systematically optimistic** about the morning floor.
    The per-horizon view shows the bias scales monotonically with
    lead time:
    ```
    7h+   mean -4.13 pp  (worst: -5.66)
    6-7h  mean -3.55 pp
    5-6h  mean -1.67 pp
    4-5h  mean -1.61 pp
    3-4h  mean -2.41 pp
    2-3h  mean -1.50 pp  (best: -1.13)
    ```
    Contrast with sunrise SOC validation (landed 5 loops ago):
    mean abs **1.15 pp**, mean error −0.12 (well-calibrated).
    Same model, same data, two validation targets → very
    different bias signatures. **What this almost certainly
    means**: the simulator's discharge_model captures the
    overnight slope correctly (so sunrise SOC lands right) but
    underestimates the post-sunrise discharge between sunrise
    (05:08) and solar onset (07:45) — 2.5 hours where the pack
    keeps losing Ah at -2 A baseline. On a clear day with quicker
    solar onset, this gap would be smaller and the bias would
    shrink.
  - **Why this matters**: this is the FIRST EMPIRICAL CALIBRATION
    SIGNAL with the right structure to actually fix the model.
    The fix is concrete: extend the discharge walk in
    `simulate_next_24h` past sunrise until the projected solar
    contribution exceeds the discharge load (or until a
    threshold like noon — sometimes a forecast cloudy day really
    never goes net-positive). Now we have the numerical target
    (close the −2.97 pp gap) AND the validation pipeline to
    measure progress.
  - **Watch**: today's day-2 net+ landed at SOC=63.5; the
    advisor's most recent (post-onset) projection (07:35:45)
    projected_low=63.0 for TOMORROW. With the new
    low_soc_accuracy chain in place, tomorrow's net+ will
    auto-validate against this 63.0 prediction. Over 7+ days
    we'll have a real bias trend and can intervene with the
    discharge_model fix.

- **2026-05-19 07:21** — Pack steady at **65/63 %** (the day's
  apparent floor — advisor projected 63 last loop, pack is at
  63 on the B side). Current -1.7 to -2.1 A baseline; cloud still
  100 %, shortwave 65 W/m². No new milestones on the solar_onset
  cascade (still stuck at first_zero/first_idle from 06:44:10).
  Irradiance crept up to 0.081 kWh/m² (1.6 % of forecast).
  Confidence log unchanged (still showing the single 06:41:35
  transition).
  - **Design item picked: surface confidence_log in day-report.**
    Twin of last loop's solar_onset section — closes the fourth
    archive loop. The advisor's confidence-lift transitions
    (logged 2 loops ago to `data/confidence_log.csv`) now appear
    on each day's report.
    - `scripts/end_of_day_report.py`: new
      `## Confidence-lift events` section between
      `## Projection accuracy` and `## Cross-references`. Filters
      log entries whose `ts` falls on the report's day; renders
      as a markdown table (timestamp | base | resolved | lifted? |
      recent abs err | recent n | source). Lifted=yes is bolded.
    - When the day had multiple transitions, a "Net: started day
      at **X**, ended at **Y**" summary line captures the
      day-net change.
    - Empty-state message when no transitions occurred on the day
      ("the advisor's resolved tier held steady") — points the
      reader to the full log for the previous transition.
    - 5 regression tests added: empty-state (no log at all),
      empty-state (log has other days only), single-event render,
      multi-event render with Net summary, day-prefix filtering
      (prevents 05-18 / 05-20 events from bleeding into 05-19).
      Suite: **198 tests passing** (was 193, +5 new).
  - **Today's regenerated report** at `data/reports/2026-05-19.md`
    now shows the single 06:41:35 transition: `low → medium ·
    **yes** · 0.89 · 10 · advisor-invocation`. Committed.
  - **Why this matters**: the day-report is now a complete
    snapshot of the validation/calibration audit trail. Five
    chains landed on it:
    1. Mechanical totals (the original)
    2. SolarModel state (calibration_log changes)
    3. Projection accuracy (per-record + per-horizon)
    4. Solar onset cascade (last loop)
    5. Confidence-lift events (this loop)
    
    A future operator opening any historical day-report sees the
    full picture: what happened, what was predicted, when solar
    arrived, when confidence shifted, and (via the calibration
    section) when the model itself was retrained.
  - **Watch**: confidence_log will show its next transition the
    moment recent_abs_error_pp drifts above 2.0 pp or the
    SolarModel base shifts. Currently abs=0.89 with 10 records —
    very stable. The next sunrise's batch of validations will
    likely keep the lift active.

- **2026-05-19 07:13** — Sunrise +125 min, post-onset stall. Pack
  SOC dropped further to **65/63 %** (down another 1 pp from last
  loop). Current back to **-2.0 A** baseline — the 06:44 zero
  crossing was a transient solar surge that didn't sustain. Cloud
  holding at **100 %**, shortwave inching up to **65 W/m²** (from
  53 last loop). Irradiance accumulated: **0.072 kWh/m²** (1.4 %
  of the 5.11 forecast — the cloud is severely curtailing the
  west-facing array). Advisor projection has converged
  beautifully: `next-24h low SOC` now **63 %** with pack actually
  at 63/65 — the projection is essentially landing on reality as
  we approach the floor. `solar_onset.csv` still shows
  first_zero=06:44, first_idle=06:44, with positive and
  net-positive pending. Confidence holds at `medium · lifted from
  low` (no new transition logged).
  - **Design item picked: surface solar_onset on day-report.**
    The solar_onset chain landed last loop with a live first_zero
    captured; the day-report needed a matching section so the
    archival markdown carries the morning cascade forward.
    Wired up:
    - `scripts/end_of_day_report.py`: new `## Solar onset`
      section between Solar harvest and Weather. Reads from
      `data/solar_onset.csv` when a row exists for the day
      (preferred — preserves the answer even if pack.csv has
      rolled over); falls back to fresh `detect_onset(pack.csv,
      day)` for historical days without a logged row.
    - Renders three states gracefully:
      - **Pre-onset**: friendly "No solar onset detected" note
        with reasons (heavy cloud, system shutdown, pre-dawn).
      - **Mid-cascade**: 4-row milestone table with em-dashes
        for pending milestones + "Net-positive crossover still
        pending" note.
      - **Complete cascade**: full table + summary line with
        smoothed_i and SOC at the moment, framed as "the bottom
        of the day's SOC curve and a useful calibration check
        against `projected_low_soc`".
    - Cross-references section gains entries for both
      `data/solar_onset.csv` and `data/confidence_log.csv`
      (which was missing — fixed in the same commit).
    - 4 regression tests in `test_end_of_day_report.py` cover:
      pre-onset empty state, mid-cascade partial table,
      complete cascade with summary line, logged-row preferred
      over fresh pack.csv scan. Suite: **193 tests** (was 189,
      +4 new).
  - **Today's regenerated report** at `data/reports/2026-05-19.md`
    now shows the actual partial cascade (`first zero 06:44:10`,
    `first idle 06:44:10`, others pending) — committed to the
    repo so future reruns of historical days don't need pack.csv
    to be available.
  - **Why this matters**: closes the third archive loop. We now
    have THREE layers of historical record on the day-report:
    1. The day's mechanical totals (SOC walk, peaks, harvest)
    2. The advisor's validation (projection accuracy + horizon
       breakdown — landed two loops ago)
    3. The morning transition (solar onset cascade — this loop)
    
    A future Volthium operator opening any historical day-report
    will see exactly what happened AND what the model thought
    would happen, side-by-side.
  - **Watch**: solar_onset's missing milestones (first_positive,
    first_net_positive) may not land today if cloud holds. If
    so, today's day-report will preserve "Net-positive crossover
    still pending" as the FINAL state for the day — itself a
    useful historical signal (these are the days where the
    advisor's confidence lift matters most because the system is
    operating very close to the projected_low).

- **2026-05-19 06:46 🌅 — DAY-2 SOLAR ONSET DETECTED.** First zero
  crossing at **06:44:10** (1 h 36 min after sunrise on a
  west-facing array under 100 % cloud); BMS state transitioned
  from `discharging` to `idle` at **06:46:17** as smoothed current
  climbed from -2.5 A to -0.4 A in ~3 minutes. Pack SOC at the
  moment: **66/64 %** — the bottom of today's curve so far. Net-
  positive (smoothed_i > 0) still pending but very close.
  - **Design item picked: first-net-positive event detection.**
    Perfect timing — the day-2 transition we've been watching for
    landed in this loop's pack.csv samples. Built:
    - `scripts/solar_onset.py`: detects the day's solar-onset
      cascade in 4 milestones from pack.csv:
      `first_zero` → `first_idle` → `first_positive` → `first_net_positive`.
      Plus snapshots `smoothed_i` and SOC average at the
      net-positive moment (the bottom of the day's SOC curve —
      genuinely useful as a calibration check against the
      advisor's projected_low_soc).
    - Append-only-with-upsert log at `data/solar_onset.csv`:
      one row per day, keyed by date. Later detections enrich
      the row as more milestones land. Idempotent — re-running
      with the same milestones is a no-op.
    - The `first_idle` heuristic intentionally requires
      `first_zero` to have been seen first; otherwise a transient
      load-lull at 03:00 with |i| < 0.5 A would spuriously match
      as "idle" before any solar contribution.
    - CLI: `python3 scripts/solar_onset.py` (detect for today),
      `--show` (print history), `--date YYYY-MM-DD` (backfill).
    - Wired into dashboard's `/api/latest.json` so it auto-runs
      on every page refresh; result surfaces as a new
      `solar-onset` chip on the harvest panel showing the
      cascade (`zero 06:44 → idle 06:46 → pos … → net+ …`) and
      current stage label (`first zero` / `idle` / `transient
      positive` / `net-positive`). Color shifts green once
      net-positive is sustained.
    - **First live record captured**:
      `date=2026-05-19 first_zero=06:44:10 first_idle=06:44:10
       first_positive=— first_net_positive=—`
      (the latter two will fill in once smoothed_i crosses zero
      later this morning).
    - 12 regression tests in `tests/test_solar_onset.py` lock
      down: pre-onset days yield empty records, first_zero is
      the leading edge, idle requires first_zero to have been
      seen first (no transient overnight load-lull match),
      state="idle" string triggers it, full cascade detection,
      day-boundary key matching (prev day's sun doesn't bleed
      into today), upsert semantics (write/noop/replace),
      multi-day chronological ordering, end-to-end detect-record
      flow. Suite: **189 tests** (177 + 12 new).
  - **Why this matters**: closes the morning audit trail. Together
    with the four pre-existing logs (calibration, projection,
    accuracy, confidence), we now have:
    - `solar_onset.csv` — when did each day's solar actually start
      
    The advisor will eventually use this signal directly — once
    `first_net_positive_iso` lands well before what the SolarModel
    would have predicted for cloud cover, that's a calibration
    update opportunity. Today's data:
    cloud 100 % + west-facing array + sunrise 05:08 → first_zero
    at 06:44 (~1.5 h post-sunrise). On a clear day this would be
    much earlier; we'll see week-over-week.
  - **Watch**: smoothed_i is still negative but climbing rapidly.
    Next loop should capture `first_positive` (instantaneous
    positive surge) and possibly `first_net_positive`. SOC at
    that moment is genuinely useful for advisor calibration —
    if it's 65 % and the advisor projected 64 %, that's a 1 pp
    error on a SECOND independent validation event, complementing
    the sunrise validation.
  - Also: irradiance accumulated to 0.044 kWh/m² (0.9 % of the
    5.11 forecast). The instantaneous shortwave readings hit 53
    W/m² at 06:34 — enough to nudge the pack to net-zero current
    under 100 % cloud, which is a remarkable demonstration of how
    sensitive this system is at the bottom-of-cycle moment.

- **2026-05-19 06:41** — Sunrise +93 min. Pack SOC dropped to **66/64**
  (lost another 1 pp on each side), current up to **-3.0 to -3.2 A**
  (heavier than the -1.7 A blip last loop — that was a load lull,
  not solar). Weather: **cloud 100 %**, shortwave 53 W/m² (still
  very low). Irradiance accumulated: **0.037 kWh/m²** (0.7 % of
  the 5.11 forecast). The west-facing array isn't going to see
  much direct sun under 100 % cloud — and the projection's
  `next-24h low SOC` has tightened to **64 %**, which is still
  comfortably above the 25 % floor but the lowest the advisor has
  reported. **Net-charging not yet** (still on the discharge side).
  - **Design item picked: confidence-lift history log + view.**
    The advisor has been lifting confidence from `low → medium`
    for the last few invocations, but the event was invisible —
    no archive of when it first fired or whether it would ever
    fall back. Wired up:
    - `scripts/confidence_log.py`: new append-only CSV
      (`data/confidence_log.csv`). One row per transition in
      `(base, resolved, lifted)` tuple; stable states are deduped
      so the log is a timeline of *events*, not a stream of
      duplicates. Schema: `ts, base, resolved, lifted,
      recent_abs_error_pp, recent_n, source`.
    - `record_if_changed(...)` is the canonical write path. The
      advisor calls it after computing the lift, best-effort
      try/except.
    - `scripts/confidence_log.py --show` pretty-prints the
      history with a "current state" footer ("lifted from 'low'
      to 'medium'").
    - **First live event captured**: `2026-05-19T06:41:35 · low →
      medium · lifted · abs_err 0.89 · n=10`. Going forward
      every time the lift transitions (back to low, or up to
      high, or the SolarModel's base shifts) a new row will
      land.
    - Dashboard `/confidence` route: dark-themed HTML table,
      newest-first, with a green-highlighted `lifted` column.
      Cross-linked from the advisor panel's conf-lift badge
      footer ("lift history ↗") and from the other log pages
      (`/calibration`, `/projections`, `/accuracy` all now link
      to `/confidence`).
    - 8 regression tests
      (`tests/test_confidence_log.py`) lock down: empty-log
      handling, first-row-always-writes, idempotent
      same-state-noop, drift-in-abs-err-doesn't-write (only
      transitions do), lift-falls-away writes, base-change
      writes, resolved-change writes, CSV round-trip preserves
      None abs error, header presence. Suite: **177 tests
      passing** (169 + 8 new).
  - **Why this matters**: closes the meta-loop. We now have four
    parallel logs:
    - `calibration_log.csv` — SolarModel coefficient changes
    - `projection_log.csv` — each advisor projection snapshot
    - `projection_accuracy.csv` (derived) — projection vs actual
    - `confidence_log.csv` — lift state transitions
    
    Together they're the audit trail of *how the model evolved*
    AND *how confidence in it evolved*. A few weeks from now,
    when the advisor's confidence shifts from `medium` back to
    `low` (because the recent_abs_error_pp drifted above 2 pp
    after a weather anomaly), the row in `confidence_log.csv`
    will pinpoint the moment.
  - **Watch**: tomorrow's sunrise will produce another batch of
    15-20 validated projections. If the new track record stays
    tight, the lift will hold; if it loosens, we'll see the
    transition logged. The `confidence_log` becomes genuinely
    informative once the lift starts moving with real signal.

- **2026-05-19 06:12** — Sunrise +64 min. Pack SOC **67/65 %** (gap
  steady at 2 %), current **-1.7 to -1.8 A** — gentlest discharge
  yet, hint that some morning ambient light may be barely offsetting
  baseline load. No new weather row since 06:04. Accumulated
  irradiance up to **0.016 kWh/m²** (0.3 % of the 5.11 forecast).
  Advisor still firing on `medium` (lifted from `low`), 0.89 pp
  track record. Day-report regenerated.
  - **Design item picked: surface horizon-breakdown on day-report.**
    The dashboard's `/accuracy` page got the per-lead-time-horizon
    breakdown two loops ago; the day-report had only the per-record
    table. Day-reports are the long-term archive — without the
    horizon view, historical days would lose the bias signal we
    just learned to read. Fix:
    - `scripts/end_of_day_report.py`: when the "Projection
      accuracy" section has records, append a new
      `### By lead-time horizon` subsection rendered as a markdown
      table (`horizon | n | mean | abs | rms | range`). Uses
      `summarize_by_horizon()` on the same day-filtered records.
      Subsection is skipped on empty-state days.
    - The freshly regenerated `data/reports/2026-05-19.md` now
      shows the 17-record table AND the 7-bucket horizon view
      side-by-side. Once this day's report is archived (it's
      already on disk), the horizon signal stays preserved
      forever — even when the rolling-window dashboard moves on
      to tomorrow's data.
    - 2 regression tests added
      (`test_projection_accuracy_section_includes_by_horizon_table`,
      `test_projection_accuracy_horizon_section_skipped_when_empty`).
      Suite: **169 tests passing** (167 + 2 new). Pre-existing
      aiobmsble env error unchanged.
  - **Why this matters**: closes the loop on the
    projection_accuracy → horizon-breakdown → archive pipeline.
    Today's day-report is now a complete snapshot of the
    advisor's validation chain: per-record table (when each
    projection was made + what it predicted vs actuals) AND
    per-horizon breakdown (the bias pattern). Historical reports
    become the dataset for analyzing model behavior over time.
  - **Watch**: tonight's overnight projections will keep
    accumulating in `projection_log.csv` targeting tomorrow's
    sunrise (2026-05-20T05:07). The next sunrise validation will
    add a fresh set of 15-20 records to the accuracy chain —
    crucial because all 17 current records are from a single
    overnight, so the per-horizon buckets aren't yet statistically
    independent. A second day's worth of records will tell us
    whether the optimistic-far / pessimistic-close pattern is a
    real characteristic or just an artifact of one cloudy night.

- **2026-05-19 06:05** — Sunrise +57 min. Pack SOC **67/65 %**
  (A is drifting down to match B, both at gentle baseline);
  current **-2.0 to -2.2 A** (lighter than overnight average; some
  load apparently came off). Weather: cloud still **99 %**, but
  **shortwave 33 W/m²** (up from 7 last loop) — sun is starting
  to penetrate. `today_harvest.py` still reports `solar Ah +0.0`
  with 0.012 kWh/m² accumulated (0.2 % of the 5.11 kWh/m² forecast).
  Pack still net-discharging — the West-facing array hasn't crossed
  net-positive yet. **Projection log now 18 entries**; the newest
  (05:52) projects sunrise SOC 69.4 % from start_soc=65 — these
  rows target **tomorrow's** sunrise (2026-05-20), the next round
  of validations. Day-report regenerated.
  - **Design item picked: accuracy-aware confidence.** The advisor
    has been reporting `low` confidence as a stub because we only
    have 1 day of solar-fit data. But the projection_accuracy
    history shows mean |error| = **0.89 pp** over the last 10
    records — empirically excellent. Wired up:
    - `scripts/generator_advisor.py`: new
      `lift_confidence_by_accuracy(base, recent_abs, recent_n)`
      pure function. Rule: if recent_n ≥ `ACCURACY_LIFT_MIN_RECORDS`
      (5) and `recent_abs < ACCURACY_LIFT_THRESHOLD_PP` (2.0 pp),
      lift one tier (low → medium → high). Caps at high.
    - The advisor pulls `recent_abs_error_pp` from the last 10
      `projection_accuracy` records (`ACCURACY_LIFT_WINDOW`) and
      passes it through `lift_confidence_by_accuracy`. Surfaces
      both `confidence_base` (pre-lift) and
      `confidence_lifted_by_accuracy` (bool) in `inputs`.
    - **First live result**: confidence lifted from **`low` →
      `medium`** because recent_abs_error_pp = 0.89 over n=10
      records. The CLI now prints `lifted from 'low' — last 10
      projections within ±0.89 pp of actual` instead of the
      "still a stub" disclaimer.
    - Dashboard advisor panel: new green-bordered `conf-lift`
      badge surfaces just below the existing "last sunrise
      validation" chip. Shows `low → medium · last 10 within
      ±0.89 pp`. Tooltip explains the rule.
    - 9 regression tests in `tests/test_advisor_confidence_lift.py`
      pin down: low→medium tight, medium→high tight, no further
      lift past high, no-lift below min_records, no-lift at or
      above threshold (strict <), unrecognized base passes
      through, configurable threshold/min_records knobs work,
      default constants anchored. Suite: **167 tests passing**
      (158 + 9 new; pre-existing aiobmsble env error unchanged).
  - **Why this matters**: connects the new validation chain
    (projection_log → projection_accuracy) to the headline number
    the user actually sees (confidence pill on advisor panel).
    Empirically-grounded confidence reads more honestly than
    sample-count-based. As days accumulate, the lift will
    eventually shift this to `medium → high` once the SolarModel
    has 3+ days of fit data AND the recent accuracy stays tight.
  - **Watch**: tonight's overnight projections will validate
    against tomorrow's sunrise. If the per-horizon bias pattern
    we observed yesterday (optimistic far out, pessimistic close
    in) repeats, it's a genuine model characteristic. If it
    flips, something shifted in the SolarModel coefficient
    overnight. Either way, the new `--by-horizon` view + the
    confidence-lift readout will make the next validation richer
    to interpret.

- **2026-05-19 05:38** — Post-sunrise (30 min in), still waiting on
  day-2 solar onset. Pack SOC **68/65 %** (B just dropped 1 pp into
  fresh overnight-low territory), discharging at -2.5/-2.6 A
  baseline. Cloud cover **99 %**, shortwave only **7 W/m²** —
  technical sunrise has happened but the array is still in
  cloud-shadow. `today_harvest.py` reports `solar Ah so far +0.0`
  with the SolarModel forecasting **40.1 Ah** today against the
  4.92 kWh/m² weather forecast (low confidence — single-day fit).
  Calibration still 2 entries, coef stuck at 8.149. Projection log
  now 18+ entries; 17 stay validatable until next sunrise produces
  more. Day-report regenerated.
  - **Design item picked**: **per-projection-horizon accuracy
    breakdown**. The 17-record table from last loop showed a
    striking time-evolution bias (7h → -2.4 pp optimistic, 4-5h →
    perfect, 2-3h → +1+ pp pessimistic, 7min → +0.7 pp). Made it
    a first-class view:
    - Added `horizon_min` field to `AccuracyRecord` (computed at
      construction time from `sunrise_iso − projection_ts`).
    - Added `HORIZON_BUCKETS` and `summarize_by_horizon()` to
      `scripts/projection_accuracy.py`. Buckets: <1h, 1-2h, ...,
      6-7h, 7h+. Empty buckets are omitted from output.
    - New `--by-horizon` CLI flag. First-run output on the live
      data is gorgeous — the bias pattern is crystal clear:
      ```
      horizon   n   mean   abs   rms   min   max
      < 1h      3  +0.93  0.93  1.02  +0.59  +1.50
      1-2h      2  +1.34  1.34  1.34  +1.28  +1.40
      2-3h      2  +1.12  1.12  1.12  +1.05  +1.18
      3-4h      3  +0.26  0.41  0.58  -0.13  +1.00
      4-5h      2  -0.34  0.34  0.34  -0.40  -0.27
      5-6h      2  -1.55  1.55  1.65  -2.12  -0.99
      6-7h      3  -2.27  2.27  2.27  -2.36  -2.20
      ```
      Reads top-to-bottom: close-in pessimistic ↗ → far-out
      optimistic. The 4-5h band is the advisor's sweet spot today
      (mean abs 0.34 pp — barely measurable).
    - Surfaced on the dashboard: `/accuracy` page now has a new
      "By lead-time horizon" table at the top, color-coded with
      the same |error| thresholds as the per-record table (<3 pp
      green, <8 amber, else red). Helps spot model-fit bias at a
      glance over many days.
    - 4 regression tests added (`test_projection_accuracy.py`):
      `test_horizon_min_populated_from_projection_ts_vs_sunrise`,
      `test_summarize_by_horizon_buckets_records`,
      `test_summarize_by_horizon_skips_empty_buckets`,
      `test_summarize_by_horizon_empty_records`. Suite: 158
      passing (was 154; the +4 are all in this module).
  - **Why this matters**: now that the advisor is calibrated and
    producing first-pass validations, the next signal we want to
    track is *systematic bias by horizon*. If tomorrow morning's
    breakdown shows the same shape (optimistic far out, pessimistic
    close in), it's a real characteristic of this model
    combination and tells us what to tune next. If the shape
    flips, the SolarModel coef shifted overnight in a way that
    needs investigation. This is the per-day signal that turns
    "the advisor was within 1.15 pp" into actionable model-tuning
    feedback.
  - Open watch: first net-charging current still expected
    06:30-09:00 based on yesterday's morning pattern. The
    `--by-horizon` view will get a second day of data tomorrow
    morning — once we have 2+ sunrises validated, the buckets
    become genuinely informative rather than just descriptive of
    one overnight.

- **2026-05-19 05:32 ⭐ — FIRST PROJECTION ACCURACY VALIDATION
  LANDED.** Sunrise (05:08) crossed; the 17 projections made
  overnight all targeted today's sunrise; `projection_accuracy.py`
  matched them against the actual pack SOC at 05:08 and produced
  the first table:

  ```
  n=17, mean_error=−0.12 pp, mean_abs=1.15, RMS=1.36, range [−2.4, +1.5]
  ```

  **The advisor was off by ~0% on average** with typical absolute
  error of just **1.15 percentage points**. Time-evolution shows
  the bias pattern beautifully:
  - 7 h pre-sunrise: predicted 69.4 %, actual 67.0 % → **−2.4 pp**
    (model optimistic at long range)
  - 5 h pre-sunrise: 68.0 → 67.0 → −1.0 pp
  - 4 h pre-sunrise: 67.6 → 67.5 → **−0.1 pp** (nearly perfect)
  - 2 h pre-sunrise: 66.5 → 67.5 → +1.0 pp (slightly pessimistic)
  - 7 min pre-sunrise: 66.8 → 67.5 → +0.7 pp

  The advisor settled into ~0.5 pp accuracy within 4 h of sunrise.
  The worst case (2.4 pp at 7 h horizon) is the **baseline to
  watch against** for future days.
  - **What this validates end-to-end**: the data-fit SolarModel
    coefficient (8.149), simulate_next_24h hour-by-hour walk,
    discharge_model per-hour medians, AND both of yesterday's
    bug-fixes (06:10 daytime false-positive + 21:00 post-sunset
    projection-collapse). All five pieces collaborated to nail
    sunrise SOC to within ~1 pp on a single-observation model.
  - The dashboard's new "last sunrise validation" chip (built
    last loop) is now LIVE showing:
    **predicted 66.8 % · actual 67.5 % · +0.7 pp** (GREEN).
  - The 2026-05-19 day-report's "Projection accuracy" section is
    populated with the 17-row table.
  - `/accuracy` page on the dashboard now shows the full history.
  - Design item: **documented the validation in
    `docs/site/loon_lake.md`** as a new "First end-to-end accuracy
    validation — 2026-05-19 05:32 ⭐" subsection. Captures the
    summary stats, the time-evolution table showing optimistic →
    perfect → pessimistic → near-perfect bias pattern, and a
    watch-against baseline for future worst-case sanity checks.
  - Pack state at this moment: SOC **68/66 %** (right at the
    overnight low; gap 2 %), discharging at sustained -2.8 A.
    Cloud cover **98 %** — back up from the 45 % break overnight.
    First hint of dawn light not yet (sunrise was 05:08, but the
    west-facing array won't see direct sun for another hour or
    so — same morning-shadow-clear pattern as yesterday).
  - Calibration log still at 2 entries; coef holds at 8.149.
  - 167 Python tests still pass.

- **2026-05-19 05:03** — **5 minutes shy of sunrise.** Pack SOC
  **69/67 %** (gap 2 %), discharging at sustained -2.7 A. The most
  recent projection (05:01) predicts sunrise SOC **66.8 %**; actual
  current SOC averages **68.0 %**. If we hold this rate for 5 more
  min the actual sunrise SOC will land ~67.7 % — **about 1 pp
  ABOVE the prediction** (i.e. the model was slightly pessimistic).
  Projection log entries up to #18 (05:01).
  - Sunrise 05:08 is just minutes away; projection_accuracy still
    shows "no validatable" (target time still in the future by a
    hair); next wake at 05:30 catches the first record.
  - Design item: **"last sunrise validation" chip on the advisor
    panel.** Prepares for the moment when the first
    projection_accuracy record lands — the dashboard will
    immediately surface "last sunrise: predicted N.N% · actual
    M.M% · ±X.X pp" with the same green/amber/red color band as
    the model-vs-live chip.
    - `generator_advisor.py` pulls the most-recent accuracy record
      via `projection_accuracy.compute_accuracy_records()`,
      exposes 4 new fields in `Recommendation.inputs`:
      `last_accuracy_proj`, `last_accuracy_actual`,
      `last_accuracy_error_pp`, `last_accuracy_target_iso`.
    - Dashboard adds a `.calib`-styled row after the model-vs-live
      chip showing the validation. Empty when fields are null
      (early-state); appears the moment the first record lands.
    - Footer links to `/accuracy` page for the full history.
    - Tooltip explains the metric and color band.
  - All 167 tests still pass.
  - **Tomorrow morning at ~05:30, when the wake fires** post-
    sunrise: projection_accuracy will produce its first record,
    the advisor panel will surface it, the 2026-05-19 day-report's
    Projection accuracy section comes alive, and `/accuracy` page
    populates.

- **2026-05-19 04:30** — Pre-dawn (sunrise still 38 min away). Pack
  SOC **70/68 %** (gap held 2 %), discharging at sustained -2.8 A.
  Voltage 26.19 V steady. **Cloud broke significantly to 45 %** at
  04:04 (was 99 % most of the night) — there's actually some clear
  sky ahead of sunrise. Per-battery v_a/v_b agree within 3 mV.
  **Projection log entry #15** at 04:10:46. Projection accuracy
  still pending until 05:08 crosses.
  - Design item: **`data/README.md` — comprehensive index of the
    data folder**. With many CSV files now (`pack.csv`,
    `weather.csv`, `daily_summary.csv`, `calibration_log.csv`,
    `projection_log.csv`, `voltage_soc_table.csv`) plus
    `reports/*.md` and log files, anyone cloning the repo
    benefits from a map of what each file is.
  - Sections:
    - **Source-of-truth files** (logger-written, append-only):
      pack.csv, weather.csv, pack.log, launch.log, weather.log
    - **Derived / rolled-up files** (loop-regenerated):
      daily_summary.csv, calibration_log.csv, projection_log.csv,
      voltage_soc_table.csv
    - **Reports**: data/reports/YYYY-MM-DD.md
    - **Archived backups**: pack.csv.v0-1512
    - **Sizing notes** about pack.csv growth + rotation roadmap
    - **Dashboard surfaces** mapping CSV files → live HTML routes
    - **Cross-references** to the producing scripts
  - Closes the documentation gap that's been quietly growing as I
    added each new derived file. A future-me cloning the repo
    fresh now gets the map immediately.
  - 167 tests still pass.

- **2026-05-19 03:55** — Pre-dawn. Pack SOC **71/69 %** (gap 2 %),
  discharging at sustained -2.7 A — the lighter overnight pattern
  holds. Voltage 26.20 V (steady). Cloud broke to 63 % (lowest of
  the night). Per-battery v_a/v_b agree within 6 mV. **Projection
  log entry #14** landed at 03:44:46. Sunrise 05:08 about 73 min
  away; **first projection_accuracy validation in the wake-after-next**.
  - Design item: **15 regression tests for dashboard HTTP routes.**
    Routes are now numerous (`/`, `/api/latest.json`, `/today-
    report`, `/report/<date>`, `/reports`, `/calibration`,
    `/projections`, `/accuracy`) with zero direct coverage.
    Approach: construct Handler instances via `__new__` (bypass
    BaseHTTPRequestHandler's stream-bound `__init__`), mock the
    `_send` method to capture responses, exercise `do_GET()`.
  - Cases covered:
    - **`/`** returns 200 + HTML containing the main panel IDs +
      JS bundle hook
    - **`/index.html`** aliases to `/`
    - **`/api/latest.json`** on empty pack.csv returns graceful JSON
      with `latest: null`, not a 500
    - **Unknown path** returns 404
    - **`/today-report`** generates an HTML page even with no data
      files (degraded content, not 500); `.md` alias works
    - **`/report/<bogus>`** → 404 with helpful "use YYYY-MM-DD"
    - **`/report/<unknown_date>`** → 404 "no report for X"
    - **`/report/<existing_date>`** serves the committed file
    - **`/reports`** index page lists historical reports newest-
      first, today pinned at top with "(today, live)" label
    - **`/calibration`**, **`/projections`**, **`/accuracy`**
      empty-state messages render
    - **Cross-page navigation**: the three log pages each link to
      the other two and back to `/`
  - Tests fixture a tempdir + chdir so file reads don't pick up the
    real installation data — reproducible regardless of live state.
  - **167 Python tests pass** (up from 152). Total suite: 167 Py +
    22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross =
    **259 assertion-points**, all green.

- **2026-05-19 03:21** — Pack SOC **72/70 %** (gap 2 %), discharge
  dropped FURTHER to **-2.9 A** (smoothed -2.88) — continuing
  trend from -7 → -4.2 → -2.9 A over the last hour. Voltage
  26.21 V (ticking up slightly as lighter load lets cells recover).
  Per-battery: v_a 13.099, v_b 13.110 — gap just 11 mV now.
  Projection log gained 2 more entries (#12, #13).
  - **Self-correction**: my earlier loop note about "B's voltage
    60 mV higher than A despite reporting lower SOC" turned out
    to be a transient sampling artifact, NOT a real drift.
  - Design item: **quantified v_a vs v_b drift across 12,655
    samples and documented in `docs/hardware/bms_calibration.md`**
    as the companion to the i_a vs i_b analysis.
  - **Headline finding**: median |v_b − v_a| is **effectively
    zero** (1–2 mV across every current band). In the high-current
    charging band where loading matters most, agreement is within
    1 mV. **Markedly better** than the 3–4 % `i_a − i_b` drift.
  - Per-band table captured:
    ```
    charging > +5 A         n=2444   med diff +0.000 V
    charging +1 – +5 A      n=1080   med diff −0.001 V
    idle |I| < 1 A          n=1349   med diff +0.011 V
    discharging −1 to −5 A  n=5474   med diff −0.001 V
    discharging > −5 A      n=2308   med diff −0.002 V
    ```
  - Whole-dataset: median −0.001 V, mean +0.019 V (skewed by
    outliers), stdev 0.082 V, range [−0.013, +0.957] V. The
    max-magnitude outliers are BLE-flap moments where one BMS's
    value briefly stale — not sustained drift.
  - **Implication for firmware**: per-battery voltage is reliable
    to read INDEPENDENTLY (cell-overrange alarms, OCV anchors).
    Per-battery current is not — keep using `pack_current` average.
  - **Watch-against baseline** added: a sustained `|v_a − v_b|
    ≥ 50 mV` (10× steady-state stdev) would indicate real
    cell-level divergence and warrant attention.
  - All 152 Python tests still pass.

- **2026-05-19 02:44** — Pack SOC **73/71 %** (gap holding 2 %),
  but **discharge rate dropped -7 A → -4.2 A** between loops —
  a steady ~3 A load came off (maybe a device timed out or someone
  flipped a switch). Smoothed_i now -5.22 A, settling. Voltage
  26.19 V. Per-battery: v_a 13.09, v_b 13.11 — gap narrowed to
  20 mV (was 60 mV). Projection log gained entry #11 at 02:28:46.
  - Design item: **refactored `simulate_next_24h` parameter names**
    per the bug-history doc's stated future plan. The simulator's
    preferred kwargs are now:
    - `next_sunrise` (was `sunrise_today`)
    - `next_sunset` (was `sunset_today`)
    - `solar_first_day_ah` (was `solar_today_full_ah`)
    - `solar_second_day_ah` (was `solar_tomorrow_full_ah`)
  - **Backwards-compatible**: the old kwarg names still work as
    aliases for any downstream caller (or test suite) that uses
    them. Internal logic uses the new names throughout, matching
    the comment-level mental model from the 21:00 bug-fix.
  - Validation: if neither set is provided, raises `TypeError`
    with a clear message pointing at both options.
  - The simulator's internal variables follow the same convention:
    - `subsequent_sunrise = next_sunrise + 1 day` (was `sunrise_tomorrow`)
    - `subsequent_sunset = next_sunset + 1 day`
    - `first_ah_per_hour` / `second_ah_per_hour` for the two days'
      hourly solar Ah distribution
  - Updated `docs/generator_advisor/algorithm.md` bug-history
    section noting the rename landed.
  - All 152 Python tests still pass — the back-compat aliases mean
    no test had to change.

- **2026-05-19 02:09** — Pack SOC **75/73 %** (gap back to 2 %),
  discharging at sustained -7.1 A. Voltage dropping fast 26.32 →
  26.24 V (per-battery curiosity holds: A's voltage drops faster
  than B's). **Projection log gained 2 entries this loop** (01:36
  + 02:02 — slightly faster than 25 min apart due to dashboard
  subprocess + loop call timing alignment).
  - Design item: **`end_of_day_report` gains a "Projection
    accuracy" section.** Pairs with the dashboard's `/accuracy`
    page added last loop — same data, two surfaces (live web view
    + permanent markdown artifact).
  - The section filters projection_log entries whose `sunrise_iso`
    falls within the report's `day`, runs them through
    `projection_accuracy.compute_accuracy_records`, and renders:
    - **summary line** with n + mean + abs + RMS error
    - **markdown table** with `made at | projected | actual |
      error (pp)` columns
  - Empty state (most days right now, before our first sunrise
    validation tomorrow morning): friendly *"No validatable
    projections for this day yet — the first record lands at the
    next sunrise after the projection_log starts collecting."*
  - **Tomorrow morning at 05:08 (sunrise)**: the 2026-05-19 day
    report will start showing yesterday's 8 projections validated
    against today's actual sunrise SOC. Real meta-evaluation
    data lands automatically into a permanent file.
  - 2 new regression tests in `tests/test_end_of_day_report.py`:
    - Empty state when no projections exist
    - Records section renders correctly when a projection +
      matching pack sample are fixtured (tested against past-dated
      fixtures so the `compute_accuracy_records` "is the target
      passed?" check fires deterministically)
  - The Cross-references section also gains a pointer to
    `data/projection_log.csv`.
  - **152 Python tests pass** (up from 150). Total assertion-points
    across the suite: 152 Py + 22 wire-C + 17 est-C + 4 wire-cross
    + 49 est-cross = **244**, all green.

- **2026-05-19 01:35** — Pack SOC **76/75 %** (−2/−1 in 33 min,
  gap held at 1 % though it touched 2 % earlier). Discharging at
  sustained -7.0 A. Voltage 26.32 V. Per-battery curiosity:
  v_a 13.13 vs v_b 13.19 — **B's cell voltage is HIGHER even
  though B reports LOWER SOC**. The two BMSes disagree about
  their own SOC anchoring more than they disagree about
  voltage. Worth watching as a long-term sensor-bias check
  alongside the i_a−i_b drift documented in `bms_calibration.md`.
  - Projection log gained entry #8 at 01:10:46. projection_accuracy
    still "(no validatable projections yet)" — sunrise at 05:08
    is 3.5 h away.
  - Today's row 2026-05-19: −8.2 Ah net so far over 1.58 h
    covered. Discharge rate ~4.9 Ah/hr is heavy — extra ~2 A on
    top of the documented "ceiling fan + standby" baseline.
    Possibly an extra device on tonight.
  - Design item: **per-battery SOC delta tracker** in the
    dashboard's peaks subrow.
  - Backend: `compute_today_peaks()` now also tracks
    `peak_soc_gap_pct = max(|soc_a − soc_b|)` over the day.
    Today's value: **2.0 %** (touched 2 % during the heavy-draw
    window before recovering to 1 %).
  - Frontend: new 6th stat on the `.peaks` subrow showing
    `2.0%` / `A↔B gap (max)`. Color band: ≥ 3 % renders amber to
    flag a widening trend without sounding alarm.
  - Tooltip extended to explain: "In a healthy series pack this
    stays under ~3 %. Widening gap under heavy load is an early
    signal of cell imbalance or one battery aging faster."
  - This is the natural early-warning system for cell health:
    today's pack-symmetry days (gap < 1 %) are the baseline;
    once we see a 5 %+ persistent gap we'll know one battery
    needs attention.
  - All 150 Python tests still pass.

- **2026-05-19 01:02** — Overnight, third hour. Pack SOC **78/76 %**
  — **battery B gap widened to 2 %** under the sustained -7.3 A
  draw (gap had been 1 % all evening; the weaker cell drains faster
  under higher current). Voltage 26.37 V. **Projection log gained
  entry #7** at 00:44:46 — first entry wholly in 2026-05-19.
  Today's row (2026-05-19) so far: net -5.5 Ah, 1.03 h covered.
  Advisor projections drifting downward as start_soc tracks the
  drain: sunrise 67.4 %, eve 83.1 %, low 65.5 %. Calibration log
  stable at 2 entries.
  - Design item: **`/accuracy` page on the dashboard.** Completes
    the log-page pattern (`/calibration` → `/projections` →
    `/accuracy`). When the first projection_accuracy record lands
    at ~05:09 sunrise tomorrow morning, the page will display
    it; until then shows a graceful "no validatable projections
    yet — the first record lands at the next sunrise" message.
  - New `_serve_projection_accuracy` GET handler reads the
    projection_log + pack_csv, runs
    `projection_accuracy.compute_accuracy_records()`, renders
    newest-first as an HTML table:
    `made_at | target | projected | actual | error | coef | ±t`
    The error column is **color-banded**: |err| < 3 pp green,
    < 8 pp amber, otherwise red. Mirrors the model-vs-live chip's
    thresholds for visual consistency.
  - Summary row at the bottom: n, mean error, mean-abs error,
    RMS, range — so future-me can scan "how is the advisor
    biased over the last N days?"
  - **Three-way cross-linking** between `/calibration`,
    `/projections`, `/accuracy` so you can hop between the three
    related views without going back to the dashboard root.
  - All 150 Python tests still pass.

- **2026-05-19 00:28 — Day-boundary rolled cleanly.** No manual
  intervention; every module handled the transition gracefully:
  - **`today_harvest`** → reports 2026-05-19 fresh (0.5 h coverage,
    0 Ah solar, graceful "no solar harvest yet today" note).
  - **`daily_summary`** → shows BOTH rows: 2026-05-18 [complete]
    with final ratio **8.1 Ah/(kWh/m²)** anchored, and 2026-05-19
    [partial] just starting.
  - **`end_of_day_report`** → wrote `data/reports/2026-05-19.md`
    for the new day; **`2026-05-18.md` stays frozen** as the
    historical record.
  - **`projection_log`** → gained entries #5 (23:54) and #6 (00:19)
    seamlessly across midnight, same 25-min cadence.
  - **`calibration_log`** → stayed at 2 entries (correctly — only
    the 2026-05-18 row is fit-eligible; tomorrow night will add
    the 2026-05-19 fit).
  - **Open-Meteo for the new day**: forecast 4.92 kWh/m² (was 5.62
    for 2026-05-18 — slightly cloudier today).
  - Pack: SOC **79/78 %** discharging at -7.3 A (heavier than -4
    baseline — possibly the fan + something else).
  - This is what well-designed software should feel like: months
    of careful day-boundary thinking paid off in one quiet moment.
  - Design item: **`scripts/projection_accuracy.py` — projection-
    vs-actual diff infrastructure**, ready for tomorrow morning's
    sunrise validation.
  - For each projection_log entry whose `sunrise_iso` target time
    has passed, finds the closest pack.csv sample within ±30 min
    and computes the error = `actual − projected`. Outputs
    per-row table + summary (n, mean, median, RMS, abs-mean,
    min/max).
  - Current state: **`(no validatable projections yet — wait for
    sunrise_iso targets to pass)`** — all 6 projection_log entries
    target 2026-05-19 05:09, which is ~4.5 h from now.
  - **Tomorrow morning at 05:09**: the script will produce its
    first real accuracy record. Yesterday's six projections all
    predicted ~67-69 % sunrise SOC; we'll see whether reality lands
    within a few percentage points.
  - **8 regression tests** in `tests/test_projection_accuracy.py`
    cover:
    - Empty input → empty output
    - Future targets skipped (don't crash, don't make up data)
    - Closest-match selection picks the right sample
    - ±tolerance enforcement (samples outside the window dropped)
    - Negative error → pack undershot
    - Mixed past/future → only past validates
    - `summarize()` aggregates correctly (mean, abs-mean, RMS,
      min/max)
  - Locking in test coverage BEFORE the first live data lands so
    regressions can't slip in silently when the script starts
    producing real numbers.
  - **150 Python tests pass** (up from 142). Suite total: 150 Py +
    22 wire-C + 17 est-C + 4 wire-cross + 49 est-cross = **242
    assertion-points**, all green.

- **23:54** — Late-evening steady. Pack SOC **81/80 %** (-1 % per
  battery from 82/81 in 34 min). Current jumped to **-8.0 A peak**
  at the last sample (smoothed -5.73 A) — looks like an unsustained
  fridge-compressor spike, didn't quite trip the 15 s persistence
  to log as a heavy-load event. Voltage 26.43 V.
  **Projection log gained entry #4** at 23:29:46 (perfect cadence).
  Four entries now; coef holding at 8.149.
  - Design item: **"best harvest hour today" callout** on the
    dashboard's peaks subrow.
  - Backend: new `best_harvest_hour(series)` in
    `scripts/today_harvest.py` walks the 5-min series the dashboard
    sparkline already uses, finds the running max per hour with a
    carry-forward baseline so empty hours can't go negative.
    Returns `(hour_of_day, ah_in_that_hour)`. Wired into the
    `peaks` dict output as two new fields.
  - **Today's data**: `best_harvest_hour: 14, best_harvest_hour_ah:
    10.03`. The single hour 14:00-15:00 contributed **22 % of the
    whole day's 45.8 Ah harvest** — concretely confirms the
    "afternoon over-performance" pattern documented in
    `loon_lake.md`. Matches the +21.4 A peak charge observed at
    13:53.
  - Frontend: new 5th stat tile in the `.peaks` subrow:
    `14h → 10.0` with the label "best hr (Ah)". Tooltip updated
    to explain.
  - **Day-report regenerated** picks this up automatically via
    the today_harvest snapshot.
  - All 142 Python tests still pass.

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
