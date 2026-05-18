# Status snapshot — read this when you come back

## Quickest way to look at the pack

**Double-click `Launch Volthium Monitor.command` in the project root.** It
starts the logger and dashboard if they aren't running, and opens
http://localhost:8421/ in your browser. Safe to double-click any number of
times — it's idempotent.

## Currently running (as of this writing)

- **Logger**: `caffeinate -i .venv/bin/python scripts/log.py …`
  (pids 59949 / 59951). Polls both batteries every 10 s. Writes
  `data/pack.csv` and `data/pack.log`. Backs off + retries on BLE flaps.
- **Dashboard**: `scripts/dashboard.py --port 8421` (pid 59952).
  Detached; will survive Claude Code restarts.

## Decisions baked in (your numbered answers)

| Q | Your answer | What's in the system |
|---|---|---|
| 1 — what does "full" mean | Banner "FULL" at 95 %, still show % | Estimator ceiling is now 95 %. Dashboard shows `FULL` headline + actual SOC underneath. New `state="full"` in wire protocol enum. |
| 2 — display style | e-paper, no contest | Locked in: 4.2" tri-color, BOM specced. |
| 3 — replace the app w/ release-BLE button | Hold persistent BLE; display button releases for 5 min | Spelled out in `docs/production_design.md` under "BLE-share button". Cost: +1 tactile switch. |
| 4 — must not finish off a low pack | Tiered self-shutdown | New section in `docs/production_design.md` — 4 tiers (normal / low / deep-sleep / hard-cut) plus hysteresis. BOM additions: DS3231 RTC, P-MOSFET load switch, panel-mount override button. |
| (bonus) Starlink at the cabin | Optional, not a dependency | New section "Optional Starlink sync" in design doc. Battery-side has its own RTC so timekeeping is link-independent. |
| (bonus) Label batteries by serial tail | `33` / `67`, derived at runtime | `BatteryReading.label` property; logger now writes `name_a` / `name_b` columns; dashboard JS derives the label per-row with A/B fallback for legacy rows. |

## What happened in the data while you were typing

The pack flipped **charging → discharging**. Something (fridge?) came on at
about 15:04 and the smoothed current crossed zero into discharge territory
by 15:08. SOC still 68–70 %. We captured the whole transition — the
estimator state cleanly walked `charging → charging (smoothed +0A)
→ discharging` as the EMA caught up.

The pre-relaunch CSV is archived at `data/pack.csv.v0-1512` so we have that
event preserved. The live CSV `data/pack.csv` has the new `name_a` / `name_b`
schema starting fresh at 15:13.

## Files of note

- `Launch Volthium Monitor.command` — double-click to start everything
- `volthium/pack.py` — `BatteryReading.label` (returns "33" / "67")
- `volthium/estimator.py` — 95 % ceiling, new `state="full"` outcome
- `volthium/wire_protocol.py` — STATE_FULL in enum, tests cover it
- `scripts/log.py` — writes `name_a` / `name_b` columns
- `scripts/dashboard.py` — derives labels in JS, banners FULL
- `scripts/monitor.py` — TUI uses `r.label`
- `scripts/read_once.py` — print "Battery 33:" / "Battery 67:"
- `scripts/analyze.py` — offline digest, uses 5-min windows for Ah-rate
- `tests/test_wire_protocol.py` — 9 tests, all passing
- `docs/production_design.md` — full architecture, BOM, all 4 of your design directives
- `data/pack.csv` — live data (new schema)
- `data/pack.csv.v0-1512` — archived data (old schema, has charge→discharge transition)
- `data/pack.log` — human-readable progress log

## Design progress

Hardware design pass complete, **plus** a SKiDL → KiCad handoff package
ready for a different machine to pick up. See
[`hardware/kicad/HANDOFF.md`](../hardware/kicad/HANDOFF.md) for the runbook
the future Claude session will execute, and
[`docs/hardware/`](hardware/README.md) +
[`docs/firmware/`](firmware/) for:

- **`hardware/README.md`** — index
- **`hardware/block_diagrams.md`** — system + per-board ASCII block diagrams
- **`hardware/bom.md`** — full BoM with Digi-Key / Mouser part numbers,
  proto-vs-PCB columns, ~$135 total for one of each
- **`hardware/schematic_battery_side.md`** — netlist-form schematic, GPIO
  map, power tree, MOSFET hard-cut path, RS-485 wiring
- **`hardware/schematic_display_side.md`** — same for the display side
- **`hardware/power_budget.md`** — quantified draw for all 4 SOC tiers
  (normal 1.1 W → hard-cut 5 mW), wire losses
- **`hardware/cat5e_pinout.md`** — T568B pin allocation, shield bonding,
  pre-install cable QA
- **`firmware/architecture.md`** — ESP-IDF repo layout, FreeRTOS task
  list, state machine, OTA strategy

Ready to enter into KiCad as a schematic and to order parts.

## What we're still waiting on (no action needed)

- The generator's ~40 A dump — calibrates the BMS current sensor bias
- A trip through the 95 % knee — validates the FULL banner logic + lets us
  see the LiFePO4 CV taper in real data
- A deeper discharge below 25 % — would let us prototype the tiered
  shutdown UX on the Mac before committing it to silicon

## My autonomous loop while you're away

I'm waking every 30 min to check the data and advance the design.
Each cycle: analyze, note new learnings here under the "Loop notes"
section below, push one design item further, schedule the next wake.

## Loop notes

*(appended chronologically)*

- **15:30** — Initial check after design-doc push. 14 min of -3.2 A
  discharge captured; SOC barely moved (69 → 68 % avg, integer-quantized).
  Logger + dashboard healthy. No charge/full transitions yet to test
  the new 95 %-banner logic.

- **15:53** — **Generator captured!** Two clean segments:
  - 15:13–15:34: discharging at avg −3.4 A (probably fridge cycles +
    standby loads). SOC 69 → 68 % over 21 min.
  - 15:34–15:53: charging at avg **+54.8 A**, peak **+60.9 A** — clearly
    the generator. User estimated ~40 A; actual is significantly higher.
    SOC climbed 68 → 77 % in 18 min.
  - **BMS current-sensor bias confirmed**: 5-min Ah-window analysis on
    the fast-charge segment gives +65 dAh/hr at +58 A mean ⇒ ratio
    **1.11**. Earlier overcast-solar data at +16 A gave ratio **1.12**.
    Consistent across two very different current bands ⇒ this looks
    like a **true ~11 % bias** in the BMS current sensor, not a
    voltage-correction artifact.
  - Implication for the time-to-full estimator: it currently
    over-predicts by ~11 % (says "50 min" when reality is ~45). Will
    add a `current_calibration` factor in a future iteration.
  - SKiDL hardware design package (`hardware/kicad/`) done in parallel:
    battery_side.py, display_side.py, HANDOFF.md, symbol_footprint_map.md,
    test_smoke.py, run.sh — ready for another machine to pick up with
    KiCad installed.
  - At +50 A and SOC 76 %, we're ~18 min from the **95 % FULL banner**
    — first chance to validate it on real data. Next loop check should
    catch it.

- **15:59** — Charging continues, now at SOC 78–80 %, current dropped to
  +45 A (generator modulating or solar wind-down). Fast-charge bucket
  ratio now 1.14 across 4 samples — solidly confirming the BMS bias is
  in the 11–14 % range. Adding `current_calibration` to the Estimator
  this iteration: default still 1.0 to preserve raw-data analysis, but
  the parameter and docstring document our finding so future firmware
  can apply it. Time-to-full estimator now reading ~40 min — should
  catch the 95 % banner crossing on the next wake.

- **16:19** — Generator's still on, current jumped *back* up to +61 A
  (bursty output). SOC now 89 %, time-to-full 12 min. Still no FULL
  transition yet — should happen in the next 10 min if current holds.
  Fast-charge ratio now 1.16 across 8 samples — bias finding even
  more robust. Skipping the wake-schedule this iteration since the
  prior loop already queued one for 16:26; let that one take over.
  Design item this round: wrote a 3-doc install/ runbook
  (`docs/install/README.md`, `bench_test.md`, `troubleshooting.md`)
  covering Cat5e QA → battery tap → first power-up → end-to-end
  verification, plus pre-install bench tests and a triage guide.

- **16:26** — **Generator stopped at 16:21**, before SOC crossed the
  95 % FULL banner. Pack went from +60 A bulk to +11 A solar trickle.
  No FULL transition captured yet — closest we got was SOC 91 %.
  Voltage relaxed 27.21 → 26.86 V on the same charge profile,
  confirming we were in BULK phase the whole time (charger
  current-limited, not yet entering CV regulation around 28+ V).
  Generator total run = ~47 min, ~38 Ah delivered to the pack.
  Design item: extended `scripts/analyze.py` with an `--- events ---`
  section that detects named transitions even when the `state` field
  doesn't change — currently catches GENERATOR ON/OFF, heavy-load
  on/off, first-FULL and first-LOW SOC crossings. Output now reads:
  `15:34 GENERATOR ON +42.9A`, `16:21 generator off +15.8A`.

- **16:57** — **🎉 FULL banner crossed at 16:55:30** — first time on
  real data. Pack max_soc hit 95 %; estimator state transitioned to
  `full`; the events log captured it cleanly. Pack was still
  charging at +14 A (solar) when the threshold tripped. Voltage
  26.91 V — well below absorption-CV regulation (28+ V), confirming
  the 95 %-banner heuristic is decoupled from the actual voltage
  knee, which is good (it'd take much longer to wait for true CV
  taper).
  - **Major new finding**: BMS coulomb-counter bias is **non-linear**.
    Fast charge (≥30 A) ratio = 1.12 (Ah counter over-reports). But
    moderate charge (10–30 A) ratio = **0.91** (under-reports).
    Sign flips. Probable cause: BMS blends coulomb counting with
    voltage-corrected SOC; the blend weights shift with current
    magnitude.
  - Design item: wrote `docs/hardware/bms_calibration.md` — analysis
    of the data, two hypotheses, three firmware-port options with a
    **recommendation for a hybrid approach** (trust `remaining_ah`
    as anchor every minute; integrate current between anchors for
    smooth UI). The current `current_calibration` parameter in
    `Estimator` is now formally inadequate (single multiplier won't
    capture the sign flip) — the C-port estimator should use the
    hybrid approach instead.
  - Battery temperatures rose to 26 °C (from 23–24 °C earlier) under
    the generator's high-current charge.

- **17:28** — Pack still in `full` state at +13 A trickle, SOC
  climbed to 97 % (avg). Notable BLE flap at 17:23 (1 read failure,
  auto-recovered within 5 s — the logger's backoff worked in
  production, not just in tests). Implemented the **hybrid
  coulomb-counter** as a parameter on `Estimator`:
  `use_remaining_ah_anchor=True`. Code path is fully tested (5 new
  tests, all 23 passing). Replayed the captured CSV through both
  modes — interesting result: hybrid predictions converge much
  faster than SOC-based (1h 30m vs 1h 51m at start of charge; 20 min
  vs 36 min mid-charge). But ALSO surfaced a deeper issue: **the
  BMS's `remaining_ah` reaches 213 Ah at SOC 97 %, implying real
  per-battery capacity is closer to 220 Ah, not the 200 Ah
  nameplate.** Documented in `docs/hardware/bms_calibration.md`. The
  configured `capacity_ah` should probably bump to ~215 Ah pending a
  controlled full-depth cycle to get a precise number.

- **17:55** (out-of-band, user-requested) — Made the dashboard
  LAN-visible for phone access. Changes:
  - `scripts/dashboard.py` default `--host` → `0.0.0.0`. Also
    overrode `address_string()` on the request handler to skip
    reverse-DNS (default Python `BaseHTTPRequestHandler` blocks ~30 s
    per request on LANs without rDNS — debugged from a hang
    symptom).
  - `Launch Volthium Monitor.command` now prints both the laptop URL
    and the LAN URL, plus a Unicode QR code (uses the new `qrcode`
    Python dep) so a phone camera can scan the URL directly.
  - macOS application firewall blocks the LAN binding by default
    despite reporting the bundle as "allowed" — almost certainly
    because we ad-hoc-resigned Python.app during the Bluetooth fix,
    invalidating the firewall's cached signature. User went with
    `socketfilterfw --add` Python (Path B). Confirmed working.
  - Side observation: **SOC hit 100 %** at 17:50 and pack flipped to
    slight discharge (-2.9 A); state machine still showing `full`
    because EMA hasn't caught up. Will be the first full→discharging
    transition we capture once smoothing settles.

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

- **23:51** — Loop wake. Pack at SOC 90-91 %, ~ -4.5 A baseline.
  No new fridge cycle events tonight — either the threshold is too
  conservative (-10 A) for this fridge's compressor, OR the fridge
  hasn't cycled yet (would expect to see at least one by now). Will
  watch in subsequent wakes.
  - Design item: top-level `Makefile` — single `make test` runs the
    entire test suite end-to-end:
    - Python tests (23 unittest cases across `volthium/`)
    - C tests (22 wire-protocol + 17 estimator unit cases)
    - Cross-validation (4 frames × ~25 assertions per byte-identity
      check + 21-field decode match)
    - Auto-regenerates the Python test-vector `.bin` files first if
      `gen_test_vectors.py` or `volthium/wire_protocol.py` are newer
    Other targets: `make test-py`, `make test-c`, `make vectors`,
    `make clean`, `make help`. Everything still works via the
    sub-tree Makefiles independently.

- **23:17** — Loop wake. Pack SOC 92-93 % discharging at -4.5 A
  smoothed. Down ~1 % per 30 min on the fan+fridge baseline. No
  new events. voltage_soc_calibration rerun yields the same 4
  rest windows (pack hasn't been idle long enough since to add new
  points). Projection from 22:42 implies ~ 80 % at sunrise — the
  EMA-settled rate is more honest than the original 21:35
  prediction of 75 % which was made just as the fan came on.
  - Design item: **display-side ESP-IDF skeleton** in
    `firmware/display/`. Symmetric to the battery-side one I built
    last loop. Differences (per `docs/firmware/architecture.md` and
    `state_machine.md`):
    - `CONFIG_BT_ENABLED=n` — display never talks BLE
    - No MOSFET / no ULP — display stays alive longer than the
      battery side
    - SPI bus to the e-paper instead of BLE
    - 3 buttons (refresh / next / release-BLE) instead of one
      override button
    - Task set: `rx_task` (RS-485 receive + decode), `render_task`
      (e-paper), `input_task` (buttons), `watchdog_task`
      (link-down detection)
    - rx_task stub posts a synthetic decoded frame every 30 s so
      render_task can be developed independently of the RS-485 link
  - Both `firmware/bms-link/` and `firmware/display/` now share the
    common `firmware/common/volthium_lib/` C library via
    EXTRA_COMPONENT_DIRS — single source for wire protocol +
    estimator across both firmware images and the host C test suite.

- **22:42** — Loop wake. Pack SOC 94 % discharging at -4.7 A smoothed
  (EMA has absorbed the ceiling-fan baseline). Tracking close to the
  projection.
  - Design item: **ESP-IDF skeleton for the battery-side firmware**
    in `firmware/bms-link/`. Concrete pieces:
    - top-level `CMakeLists.txt` finding the sibling
      `firmware/common/volthium_lib/` component (single-source for
      wire protocol + estimator across host C tests AND ESP-IDF
      firmware)
    - `sdkconfig.defaults` pre-configured for ESP32-S3-WROOM-1-N16R8
      (16 MB flash, 8 MB octal PSRAM, BLE NimBLE central role with 2
      connections, light-sleep enabled)
    - `main/main.c` initializes NVS, sets up the estimator with
      `use_hybrid=true` and `capacity_ah=215` (our empirical value),
      creates 4 FreeRTOS tasks per `architecture.md` § "Battery-side
      tasks", returns
    - 4 task stubs (`ble_task`, `tx_task`, `power_task`,
      `adc_task`), each with a header comment listing the
      implementation TODO checklist + cross-references to the design
      docs
    - `ble_task` already posts synthetic samples every 30 s so the
      rest of the pipeline (estimator + wire-frame encode) can be
      exercised end-to-end on real hardware as soon as someone
      flashes it. `tx_task` builds + logs the encoded frames (UART
      DE pin handling pending).
    - `firmware/common/volthium_lib/CMakeLists.txt` as an ESP-IDF
      component manifest. Host-side `Makefile` still works
      (re-ran: 39 unit + 4 cross-validation cases still passing).
    - `firmware/bms-link/README.md` documents status, build flow,
      and the rough order to fill in the stubs.
  - **Result**: someone with ESP-IDF v5.x installed can now
    `idf.py build` and get a runnable image that exercises the
    shared library on real silicon, even before BLE/RS-485 plumbing
    is wired up. Big de-risking step for the eventual firmware
    push.

- **22:09** — Loop wake. Projection sanity check: at 21:35 we predicted
  75 % SOC at sunrise from a -5.9 A baseline; pack now at SOC 95-96 %
  having dropped only ~1 % in 34 min (slightly worse than -5.9 A
  would imply, because the ceiling-fan baseline shift bumped average
  draw to ~ -6 to -8 A). Projection panel will catch up as the EMA
  settles on the new baseline.
  - Design item: wrote `scripts/voltage_soc_calibration.py`. Walks
    pack.csv for rest windows (|smoothed_I| < 0.5 A sustained for
    ≥ 5 min), records average OCV and SOC%, bucketizes into 5%-bins
    so it produces a discrete table the firmware's ULP can
    interpolate. First-run output: 4 rest windows today, all at
    SOC ≈ 100 % (range 26.7 – 28.0 V depending on how relaxed the
    pack was). Writes `data/voltage_soc_table.csv`. Designed to be
    re-run periodically over the production install — every full
    cycle the pack sees adds samples across the SOC range, and the
    table sharpens. Especially valuable for the steep OCV regions
    near 10 % (HARD_CUT threshold) and 95 % (FULL banner).
  - Cross-references to `docs/firmware/state_machine.md` § "SOC
    source per state" — this table will live in the ULP code path.

- **22:01** (user input + observed) — User turned on a ceiling fan;
  said this paired with an overnight fire is normal nighttime
  pattern. **Captured cleanly in the data** at 22:00:41 — pack
  current stepped from -2.8 A to -5.1 A, a +2.3 A jump consistent
  with a residential ceiling fan running via the inverter at low-
  medium speed.
  - Below the -10 A "heavy load" event threshold by design — this
    is a baseline shift, not an alarm event. The discharge EMA will
    absorb the new level and the sunrise projection will drift down
    accordingly (estimating new arrival ~ 70 % instead of 75 % once
    EMA settles).
  - Updated `docs/site/loon_lake.md` with an observed-load-signatures
    table and a typical "overnight normal" range (-5 to -8 A
    baseline, +7 A fridge bumps). This is calibration data for the
    eventual discharge model in the generator advisor.

- **21:35** — Loop wake. Pack at SOC 96 % discharging at -5.9 A
  smoothed. Both data streams (pack + weather) flowing. **First
  forward projection wired into the dashboard**:
  - New "PROJECTED SOC AT SUNRISE" panel on the left column,
    visible when pack is discharging or idle, hidden when charging.
  - Math: `projected = current_SOC + smoothed_I × hours_to_sunrise
    / 215 Ah × 100` (215 Ah from `bms_calibration.md` peak
    observation).
  - Live numbers right now: SOC 96 % → projected **75 % at 05:10
    tomorrow** (7h 33m away) at -5.9 A. Comfortable margin.
  - Shows current cloud %, temperature, today's total irradiance
    (kWh/m²) as context.
  - Color-coded: yellow if projected < 25 %, red if < 10 %.
  - Updated `Volthium Monitor.app` and `Launch …command` so they
    also start the weather logger and pass `--weather-csv` to the
    dashboard. Anyone running the .app from cold-start now gets the
    full pack-plus-weather pipeline.
  - This is the first concrete piece of the generator-advisor
    architecture wired into the UI. Solar / discharge models still
    needed for accuracy (days more data required); for now the
    projection is naive-extrapolation at current rate, which is
    fine for the overnight question we're answering tonight.

- **21:27** — Loop wake. Pack at SOC 97 % discharging at -3 to -7 A
  baseline (no big events since the 20:22 lights demo). Five BLE
  flaps now captured in the first ~5 h of logging — wrote up the
  pattern in `docs/firmware/ble_flap_recovery.md`:
  - All flaps were single-cycle (1 missed read, recovered on next).
  - Recovery times 3–10 s.
  - Both batteries flap roughly equally (3× A, 2× B).
  - Rate ~ 1/hour at 10 s polling.
  - Root cause likely advertise-vs-scan duty-cycle aliasing — no
    intervention needed.
  - Doc spells out firmware retry policy (backoff 500 ms → 30 s,
    escalate to unreachable-flag after 5 consec / ≥60 s), display-
    side responses by duration, and a future "flap burst" event
    type for when the rate spikes (real signal of interference or
    BMS degradation).
  - Cross-linked from `docs/firmware/architecture.md`.
  - Skipping wake-schedule this iteration — one already queued at
    21:35 from the strategic-shift work.

- **21:01** (user input) — **Strategic shift**: user wants to build
  toward a **generator-use recommender**. Provided cabin context:
  - Location: **Loon Lake, BC** (lat/lon to confirm; defaulting to
    51.07 °N / 121.20 °W, the Clinton-area Loon Lake)
  - Cabin on south side of lake
  - Roof-mounted PV array, **mostly west-facing** — afternoon /
    evening sun strong, morning sun limited
  - Implication: daily harvest curve shifted late vs. typical
    south-facing arrays. SOC low-point is late-morning, not dawn
  - **Correction to earlier data**: the 20:22 "heavy load on
    -10.3 A" event was the user turning on lights to demo the
    monitor, NOT a fridge cycle. Real fridge cycles are still
    pending capture.
  - New design directions started this iteration:
    - `docs/site/loon_lake.md` — site profile, panel orientation,
      generator role, open questions (panel specs, exact coords)
    - `scripts/weather.py` — Open-Meteo fetcher (no API key needed);
      writes `data/weather.csv`. First fetch successful: 5.8 °C,
      70 % cloud, sunset was 20:51 today, day total ~ 25.9 MJ/m²
      ≈ 7.2 kWh/m². Added `certifi` to requirements (macOS
      Python.org needed it for SSL).
    - `docs/generator_advisor/README.md` — architecture sketch
      for the recommendation system: ingest pack.csv + weather.csv
      → fit solar model → fit discharge model → forward-simulate
      → output `Recommendation{run_generator, when, duration_h, …}`.
      Honest about confidence given how little data we have.
  - **Cumulative C tests: 39 unit + 4 cross-validation cases.**

- **20:55** — Loop wake. **Full fridge cycle captured** in the
  event detector: "heavy load on -10.3A" at 20:22:22, "heavy load
  off -9.3A" at 20:23:29 (~67 s = compressor run). Pack now in 1h+
  of sustained discharge, SOC ticked 100 → 98 %. Discharge bucket
  growing (n=18 light-discharge windows) but BMS rem_ah still flat
  at this current — confirms 5+ min windows needed for that field
  to tick.
  - Design item: **Python ↔ C cross-validation test.**
    `scripts/gen_test_vectors.py` builds 4 canonical Python-encoded
    frames covering charging / discharging-with-negatives / full /
    battery-A-offline-with-sentinels, dumps each to a 43-byte .bin
    and a hex manifest in
    `firmware/common/volthium_lib/test_vectors/`. New
    `test_cross_validation.c` (1) decodes each Python frame in C and
    asserts every one of the 21 body fields matches the expected
    value, (2) re-encodes the same body in C and asserts the bytes
    are BYTE-IDENTICAL to the Python reference. **All 4 cases pass
    on both directions** — strongest possible proof the two
    implementations agree. Wired into the Makefile so `make test`
    runs all three test programs.
  - **Cumulative C tests: 39 unit assertions + 4 cross-validation
    cases (≈ 90 per-field assertions) all passing.** The wire
    protocol is now provably stable across both impls. Firmware
    writer can swap between Python tools and embedded C with
    confidence.

- **20:23** — Loop wake. Pack flipped to **discharging** at -3.5 A
  around 20:00 — overnight cabin loads have started kicking in. Also
  caught a **heavy-load event at 20:22:22 (-10.3 A)** via the event
  detector — first overnight load that crossed the threshold
  (probably the fridge compressor). The events log is doing its job
  in production. Third BLE flap auto-recovered at 20:02.
  - Design item: **C port of the estimator** in
    `firmware/common/volthium_lib/estimator.{h,c}`. Both modes
    implemented (SOC-based + hybrid coulomb-counter w/ anchor blending).
    Math identical to `volthium/estimator.py`. New
    `test_estimator.c` has 17 assertions covering charging /
    discharging / idle / full states, calibration multiplier
    (including the "smoothed_current_a stays raw" invariant), hybrid
    seeding, integrator advancement across 60 timestamped samples,
    anchor blend math (0.8 × integrator + 0.2 × anchor), and the
    legacy-mode no-displayed_ah path.
  - **Cumulative C tests: 39 passing** (22 wire-protocol +
    17 estimator). Both compile with stock clang on macOS, no
    ESP-IDF dependency — firmware writer can iterate on any dev box.

- **19:51** — Loop wake. Pack settled to OCV ~28.00 V at SOC 100 %
  (well into rest); trickle-charge bucket ratio climbed to **2.11**
  with 8 samples — non-linear BMS bias even more pronounced as
  voltage approaches the LiFePO4 OCV knee. Stable evening overall,
  no major events.
  - Design item: implemented the wire protocol in **C** —
    `firmware/common/volthium_lib/wire_protocol.{h,c}` byte-for-byte
    matching `volthium/wire_protocol.py`. Same CRC test vector
    (`crc16("123456789") == 0x29B1`) confirmed on both sides. Added
    a standalone C test (`test_wire_protocol.c`) plus a Makefile.
    **22/22 C tests pass on this Mac** with stock clang. The C lib
    has no ESP-IDF dependency so it builds on any C11 compiler —
    the firmware writer can iterate against it on a dev laptop.
  - Repo now also synced to GitHub:
    https://github.com/kaanow/volthium_reader (public).

- **19:20** — Loop wake. Services running (started ~19:00 via the
  user's .app launcher after the Stop-app test). Pack at SOC 100 %
  in `full` state, +3.7 A residual solar trickle. Quiet evening,
  no major events. New trickle-charge bucket samples push ratio to
  **1.84** (was 1.50 with 2 samples; now 6 samples) — BMS heavily
  voltage-corrects at low currents, sign-flipping the bias relative
  to bulk charge. Hybrid coulomb-counter recommendation
  re-confirmed.
  - Design item: wrote `docs/firmware/state_machine.md` — formal
    spec for the 4-tier battery-side state machine. State table
    with avg power draw per tier (1.1 W → 5 mW), transition rules
    with hysteresis directions (down-fast, up-slow), SOC-source
    rules per state (BLE in upper tiers, ULP voltage-table in
    lower), display-side reactions for each state, and an
    `assert`-style firmware test sketch. Cross-linked from
    `architecture.md`.

- **18:50** — Loop wake. **The .app launcher worked in real-world
  use** — user killed services around 18:30, double-clicked the
  Desktop alias, and at 18:49 the launcher's `starting` line landed
  in `data/launch.log` and a fresh logger+dashboard came up clean.
  Production-ready, no Terminal interaction needed.
  - Logger also auto-recovered from another BLE flap at 18:45
    (separate from the user-initiated stop) — second-in-the-wild
    confirmation of the backoff path.
  - Design item: fixed the misleading `estimator_accuracy` metric in
    `scripts/analyze.py`. Was reporting median ratio 0.31 because it
    counted state="full" samples (where `minutes_remaining = 0`)
    against the next-sample 10 s gap, pulling the median way down.
    Now filters to `state in {"charging","discharging"}` AND
    `minutes_remaining > 0`. Re-run on the same data:
    **median ratio 0.73, median abs error 16.4 min** — the
    SOC-based estimator systematically under-predicts charge time
    by ~27 %. Consistent with capacity defaulting to 200 Ah when
    BMS-implied real capacity is ~215–228 Ah. Strong empirical
    argument to default the production firmware to hybrid mode.

- **18:20** — Loop wake. Services healthy; pack bouncing between
  brief `full`, `idle`, and `discharging` states as evening sets in
  (no major event since the 17:50 SOC=100 % peak). Design item:
  wrote `scripts/capacity_calc.py` to estimate per-battery capacity
  from the captured 67→94 % charge cycle. Three methods produce
  three different numbers (197 Ah from coulomb integration, 215–223
  Ah from BMS Ah-delta, 208/228 Ah from peak BMS Ah at SOC=100 %).
  Conclusion: **don't bake a fixed `capacity_ah` into the production
  firmware**. Use the hybrid coulomb-counter (already implemented
  via `use_remaining_ah_anchor=True`) which sidesteps the question.
  Battery A shows ~10 % more apparent capacity than B; small
  difference, but real asymmetry will matter for time-to-empty math
  in series. Findings appended to `docs/hardware/bms_calibration.md`.

- **18:15** (out-of-band, user-requested) — Made the dashboard
  one-double-click launchable for non-tech users. Built a proper
  `Volthium Monitor.app` bundle in the repo root with:
  - `Contents/Info.plist` (LSUIElement=true so it doesn't appear in
    the Dock when running)
  - `Contents/MacOS/VolthiumMonitor` shell script that idempotently
    starts the logger + dashboard, opens the browser, and fires a
    `display notification` with the LAN share URL
  - Failure mode: missing `.venv/` triggers a native dialog with a
    clear "ask the dev" message
  Created a Finder alias on the Desktop (`~/Desktop/Volthium Monitor`,
  1124-byte alias file pointing at the repo's .app). End-to-end
  tested via `open` — clean cold-start, services up, dashboard
  reachable on LAN.
  - Added `scripts/install_desktop_launcher.sh` so the alias can be
    recreated by anyone after a fresh clone or accidental deletion.

- **18:08** — Pack went through every state in the last hour:
  full(94→100%) → idle(brief) → discharging(8 min at -2.5 A) →
  idle(0 A, 26 °C, evening solar gone). **Full state coverage of the
  state machine validated on real data.** New 1.50 ratio in the
  trickle-charge (1-10 A) bucket — confirms the BMS uses heavy
  voltage-correction at low currents, where the OCV-vs-Ah curve
  steepens above 95 % SOC. Hybrid coulomb-counter is the right
  architectural answer; single-multiplier calibration would be
  catastrophic at low currents.
  - Design item: extracted event-detection from `scripts/analyze.py`
    into a shared `volthium/events.py` module. Dashboard now exposes
    `events` array in `/api/latest.json` and renders a "recent events"
    list in the right panel. Live test: events showing up properly —
    "generator off 16:21", "FULL banner max SOC 95%", "STATE: full".
    Phone-side dashboard (firewall-fixed) shows the same.
  - Skipping wake-schedule this iteration; one's already queued for
    18:19 from the LAN-fix iteration.
