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

## Cross-references

- Raw data: `data/pack.csv` (snapshot of the 2026-05-17 session
  captured at `data/pack.csv.v0-1512` as a backup)
- Analysis script: `scripts/analyze.py` (the bucket table is what
  produced this)
- Estimator: `volthium/estimator.py` (Mac-side reference impl)
- Firmware target: `docs/firmware/architecture.md`
