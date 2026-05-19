# BMS current-sensor calibration finding

A non-trivial deviation between the BMS's reported `pack_current` and
the rate at which its own `remaining_ah` field changes. Captured during
a 1+ hour data session at The Barge Inn, 2026-05-17.

## What we observed

Method: compare `(remaining_ah_a + remaining_ah_b)/2` change over ≥5-min
windows against the mean `pack_current` during that window. If the
current sensor were perfect, the ratio would be ~1.0.

| Current band                   | Observations | Median dAh/hr | Mean current | **Ratio** |
|--------------------------------|--------------|---------------|--------------|-----------|
| Fast charge (≥30 A)            | 9            | +59.6 Ah/hr   | +53.1 A      | **1.12**  |
| Moderate charge (10–30 A)      | 6            | +11.8 Ah/hr   | +13.1 A      | **0.91**  |
| Light discharge (-1 to -10 A)  | 4            | ~0            | -3.6 A       | *(window too short — Ah field hasn't ticked yet)* |

The ratio is **not constant**. It flips direction between bulk charge
(>30 A → BMS reports ~12 % more Ah than current would imply) and
trickle/absorption (10–30 A → BMS reports ~9 % less). This rules out
a simple multiplicative offset on the current sensor.

## Hypotheses

### A. Current sensor has a fixed offset bias

If the Hall sensor reads as `I_reported = I_true + offset`, with
`offset` constant, then at high currents the offset is a small
percentage and at low currents it's a large percentage — and **the
sign of the apparent ratio change matches what we'd see** if the
offset were ~−1 A (sensor reads 1 A high on charging, so apparent
current overshoots true current at low currents → BMS-counter ratio
is < 1).

Let's test the numbers: solve
  `I_true × 3600 / 60 ≈ Ah_per_hour`
  `I_reported = I_true + offset`

Fast band: `Ah_per_hour=59.6`, so `I_true ≈ 59.6 / 60 × 60 = 59.6 A`.
  Reported is 53.1 A → offset ≈ **−6.5 A**? That's a lot.

Trickle band: `Ah_per_hour=11.8`, so `I_true ≈ 11.8 A`. Reported is
  13.1 A → offset ≈ **+1.3 A**.

The offsets don't match. So a fixed Hall offset alone doesn't explain
the data. The bias direction even flips sign. So:

### B. BMS uses voltage-corrected SOC, not pure coulomb counting

Most modern smart-BMS firmwares blend coulomb counting with voltage-
based SOC inference. The blending weights depend on cell-voltage
stability (i.e. how much it can trust the voltage reading at this
moment):

- **High current → voltage is far from equilibrium** → BMS leans harder
  on coulomb counting; relative error vs. our `current` measurement is
  small but biased the way it integrates.
- **Low current → voltage is closer to equilibrium** → BMS leans on
  voltage-implied SOC; if the OCV curve says we're "lower" than the
  coulomb-counter says, the BMS pulls `remaining_ah` down to match,
  *underreporting* dAh.

This matches our observed sign flip. It also matches a known property
of LiFePO4: the OCV curve is very flat in the 30–80 % SOC band, then
steep near 95+ %. Where it's steep, the BMS *gains* information about
true SOC from voltage. As the pack approached 95 %, voltage was
rising (26.86 → 26.91 V); the BMS could see that and apply a
voltage-based correction that pulled coulomb-counted SOC down
slightly, presenting as a ratio < 1.

### C. The Volthium BMS has known undocumented behavior in the BLE feed

Without the BMS source code we can't be sure. We could rule between (A)
and (B) by:

1. Running a controlled-current sweep (e.g. a programmable DC load) at
   several known currents and comparing observed dAh against truth.
2. Watching the ratio's relationship to voltage rather than current —
   if it correlates with `|V - V_OCV(SOC)|` rather than with current
   magnitude, hypothesis (B) wins.

## What this means for production

The current Python `Estimator` defaults to `current_calibration=1.0`,
using the raw reported `pack_current` for time-to-X arithmetic. Given
the non-linear bias, **a single calibration factor is the wrong fix**.

Three options for the firmware port, in increasing complexity:

### Option 1 — Trust the BMS's `remaining_ah` field directly

Time-to-full = `(capacity_ah - remaining_ah_avg) × 60 / smoothed_dAh_per_hour`

where `smoothed_dAh_per_hour` is computed from `remaining_ah` itself,
EMA-smoothed. This eliminates the calibration question entirely — we
trust the BMS's own arithmetic.

**Downside**: `remaining_ah` ticks in 2 Ah steps, so the EMA needs
patience (~5 min lag at low current) to converge. The headline
"time remaining" number would be jittery without smoothing.

### Option 2 — Piecewise calibration

Apply `current_calibration = 1.12` for `|I| > 30 A`, `0.91` for
`10 ≤ |I| ≤ 30 A`, and `1.0` elsewhere. Quick. Crude. Won't generalize
to other batteries.

### Option 3 — Hybrid (recommended for production)

Use `remaining_ah` as the **anchor** every minute or so. Between
anchor readings, integrate `current × dt` for smooth UI updates. When
the next anchor arrives, blend: 80 % current-integration result, 20 %
new anchor value. Over time the anchor wins — but the headline number
doesn't jump.

```c
// pseudocode for the firmware estimator
remaining_ah_displayed += pack_current * dt / 3600;     // continuous
if (new_anchor_arrived) {
    remaining_ah_displayed =
        0.8 * remaining_ah_displayed + 0.2 * bms_remaining_ah;
}
```

This is the design intent for the C port. Update
`firmware/common/volthium_lib/estimator.{h,c}` accordingly when we
get there.

## Pack capacity finding (added later)

Replaying the captured CSV through the new hybrid estimator surfaced
something the SOC-based mode hid: **the BMS-reported `remaining_ah`
disagrees with the BMS-reported SOC percentage by a substantial margin**.

| time   | reported SOC | reported rem_avg | implied % at 200 Ah cap |
|--------|--------------|------------------|--------------------------|
| 16:20  | 90 %         | 197 Ah           | 98.5 %                   |
| 16:55  | 94 %         | 206 Ah           | 103 %                    |
| 17:25  | 97.5 %       | 213 Ah           | 106.5 %                  |

`remaining_ah > capacity` should be impossible. Conclusion: **our
`capacity_ah=200` default is wrong**. Real per-battery capacity
appears to be ~215–220 Ah (consistent with LiFePO4 vendors typically
shipping more capacity than rated to hit cycle-life specs).

Without an explicit cap re-cal we can either:

1. **Trust the BMS's SOC %** as primary truth for charge/discharge
   state, and treat `remaining_ah` as proportional-only (use the
   ratio to estimate state-of-charge fraction). Conservative but
   sound.
2. **Run a controlled full-depth cycle** (discharge to 10 % cutoff at
   a known rate, count Ah, then charge to 100 %, count Ah) to get the
   real capacity number. Worth doing once for the install.
3. **Set `capacity_ah=220`** based on the observed max — a guess but
   probably ±5 % of truth.

### Capacity-calc results (2026-05-17 charge cycle)

`scripts/capacity_calc.py` against the captured 67→94 % charge segment
gives three different numbers per battery:

| Method                                             | Battery A | Battery B |
|----------------------------------------------------|-----------|-----------|
| Coulomb integral of `pack_current` over charge     | 197 Ah    | 197 Ah    |
| BMS `remaining_ah` delta / ΔSOC%                   | 223 Ah    | 215 Ah    |
| Peak `remaining_ah` observed at SOC = 100 %        | 228 Ah    | 208 Ah    |

Coulomb integration nearly matches the nameplate 200 Ah. The BMS's
own counter reads higher — consistent with the 1.12 fast-charge
ratio finding (BMS over-counts at high current).

The asymmetry between A (228) and B (208) is interesting. Battery A
has 200 cycles, B has 193 — small but nonzero difference. Could be:
- Real capacity asymmetry (e.g. A was filled with slightly stronger
  cells at the factory)
- BMS counter calibration drift between the two
- Different recent thermal histories
We'll learn more when we capture a second full charge cycle.

**Recommendation crystallized**: do NOT set a single `capacity_ah`
constant in the production firmware. Either:
- Track each battery's own learned max `remaining_ah` over time
  (NVS-stored, updated whenever we see a higher value than recorded),
  and use *that* as the per-battery "full" Ah threshold;
- Or simply use the hybrid coulomb-counter as already implemented —
  it never needs to know capacity, it just tracks where `remaining_ah`
  is and integrates current between BMS reports.

The hybrid path is simpler and is what `volthium/estimator.py`'s
`use_remaining_ah_anchor=True` mode does.

The hybrid estimator will produce confusing "—" output when its
integrator passes the ceiling because we used 200 Ah for the check.
Bumping the default to 215–220 in the production firmware is on the
backlog.

## Action items

- [ ] Once we have a charge cycle that crosses through 95 % into the
      voltage-CV-taper region, look at the ratio there — expect it to
      tip below 1 even further as the BMS uses voltage more.
- [ ] Run the controlled-current bench test described in *§ Hypotheses*
      to disambiguate (A) vs (B). Requires a programmable load —
      probably not worth the trouble; the firmware's hybrid approach
      doesn't need to know which is true.
- [ ] Update `docs/firmware/architecture.md` to point at this doc
      when describing the estimator port.
- [x] (Done) Add a `current_calibration` parameter to
      `volthium/estimator.py` so Mac-side analysis can experiment with
      Option 2.

## Per-BMS sensor bias — i_a vs i_b (added 2026-05-18)

The two batteries are wired in **series**, so by Kirchhoff's law the
current through them is physically identical at every instant. Any
spread between the per-battery `i_a` and `i_b` readings is BMS-A's
current sensor reading differently from BMS-B's.

Captured 2026-05-18 mid-afternoon over 1,487 charging samples across
four pack-current bands (full day's data, charging samples only,
`pack_i > 0.5 A`):

| Pack-current band  |    n |  med i_a |  med i_b | med (i_a − i_b) | median % spread |
|--------------------|-----:|---------:|---------:|----------------:|----------------:|
| 0.5 – 2 A          |  104 |   1.40 A |   1.40 A |       +0.000 A  |       +0.00 %   |
| 2 – 5 A            |  450 |   3.60 A |   3.40 A |       +0.200 A  |       +4.44 %   |
| 5 – 10 A           |  742 |   7.40 A |   7.20 A |       +0.200 A  |       +3.03 %   |
| 10 – 20 A          |  191 |  11.20 A |  10.80 A |       +0.400 A  |       +3.33 %   |

### What this tells us

1. **A reads systematically high by ~ 0.2 – 0.4 A** across every
   practical charging band. Direction is consistent — never the other
   way around.

2. The 0.5 – 2 A row tied at zero is a **quantization artifact**: BMS
   current is reported in **0.2 A steps**, so in that band both A and
   B often land in the same bin and the median diff floors at zero.
   Visible in raw `pack.csv` rows — `i_a` / `i_b` values are always
   multiples of 0.2.

3. The bias profile leans toward "**fixed offset on A** with maybe a
   tiny gain term":
   - 0.2 A absolute at 2 – 10 A → ~ 3 – 4 % relative
   - 0.4 A absolute at 10 – 20 A → ~ 3.3 % relative

   A pure scale-factor bias would give a constant relative %; a pure
   offset bias would give a constant absolute. We're seeing something
   in between. Could also be ADC nonlinearity in one of the BMS units;
   we can't disambiguate from passive observation alone.

### Implications for the production firmware

- **Don't trust `i_a` and `i_b` independently** as a sanity check on
  each other — they should agree but won't. Use their **average** as
  the pack current (which is what `PackReading.pack_current` already
  does), or fall back to the BMS's own `remaining_ah` ticks (the
  hybrid coulomb-counter path).

- For the ESP32 firmware in `firmware/bms-link/`, the pack-current
  field encoded into the RS-485 wire frame is the **average** of the
  two BMS readings, accepting the ~ 2 % noise floor that this implies.
  Fine for time-to-X math; not fine if we ever tried to use the
  per-battery currents as cell-imbalance detectors.

- The hybrid coulomb-counter sidesteps the issue entirely by
  anchoring on `remaining_ah`, which is the BMS's *own* integrated
  output and is unaffected by sensor-bias asymmetry with its sibling.

### Useful negative finding (watch-against)

If we ever capture data where `i_a − i_b` **flips sign** or grows
beyond this ~ 0.4 A envelope, something has materially changed —
loose connection, BMS firmware update, swap of which battery is "A",
or one of the sensors degrading. The 3 – 4 % bias is a baseline to
watch against.

## Per-BMS voltage agreement — v_a vs v_b (added 2026-05-19)

Companion analysis to the i_a vs i_b drift above, but for the
per-battery **voltage** readings. Captured 2026-05-19 03:30 over
**12,655 samples** spanning a full day (charge + idle + overnight
discharge). For each sample, computed `v_b − v_a` (signed).

| Pack-current band       |    n |  med v_a |  med v_b | median diff |
|-------------------------|-----:|---------:|---------:|------------:|
| charging > +5 A         | 2444 | 13.446 V | 13.447 V |  **+0.000 V** |
| charging +1 – +5 A      | 1080 | 13.397 V | 13.395 V |   −0.001 V  |
| idle (\|I\| < 1 A)      | 1349 | 13.300 V | 13.294 V |  **+0.011 V** |
| discharging −1 to −5 A  | 5474 | 13.234 V | 13.232 V |   −0.001 V  |
| discharging > −5 A      | 2308 | 13.221 V | 13.218 V |   −0.002 V  |

Whole-dataset distribution of `v_b − v_a`:

- median **−0.001 V** (effectively zero)
- mean +0.019 V (skewed by occasional outliers)
- stdev 0.082 V
- range −0.013 to +0.957 V (max-magnitude outliers are samples
  where one BMS momentarily dropped out — see `pack.log` BLE flap
  notes; these don't reflect a sustained drift)

### What this tells us

1. **Per-BMS voltage agreement is excellent.** Median spreads
   within a few mV across every current band; in the high-current
   charging band where physical loading matters most, the two
   BMSes agree to within 1 mV. This is **markedly better** than
   the 3 – 4 % `i_a − i_b` drift documented above.

2. The brief 60 mV "gap" observed at 01:35 / 02:09 in the loop
   notes was a **transient sample-time artifact** (one BMS's value
   stale relative to the other when the pack was changing fast),
   not a sustained drift. Subsequent samples agree within 10 mV.

3. **Implication**: per-battery voltage is **reliable to read
   independently** in production firmware (e.g. for cell-overrange
   alarms, OCV calibration anchors). Per-battery current is NOT
   (use the average via `PackReading.pack_current`, or anchor on
   the BMS's own `remaining_ah`).

### Watch-against baseline

A sustained `|v_a − v_b| ≥ 50 mV` (10× the steady-state stdev)
across many samples would indicate real cell-level divergence —
one battery's pack voltage is meaningfully different from the
other's. That's a balance / health concern. The current 1-2 mV
typical spread is a healthy baseline.

## Cross-references

- Raw data: `data/pack.csv` (snapshot of the 2026-05-17 session
  captured at `data/pack.csv.v0-1512` as a backup)
- Analysis script: `scripts/analyze.py` (the bucket table is what
  produced this)
- Estimator: `volthium/estimator.py` (Mac-side reference impl)
- Firmware target: `docs/firmware/architecture.md`
