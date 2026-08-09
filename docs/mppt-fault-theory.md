# Why does the MPPT do this? A theory, with its evidence and its holes

Written 2026-08-08 in answer to "is it faulty?". Short version: **yes, in at
least one measurable respect — the output current sensor — and that single
fault plausibly explains everything else.** The power stage is fine.

## What is actually observed

1. **The array walks monotonically down** from ~90-113 V to ~28 V, passing
   straight through its own maximum power point without turning around, and
   ends pinned one diode drop above the battery.
2. **A Standby → Operating bounce fixes it every time** — 7 of 7 in daylight,
   restoring 88-95 V and full output within seconds.
3. **After a bounce it tracks correctly for 15-60 minutes**, then starts down
   again.
4. **The descent start is NOT conditional on power.** Measured across eight
   recoveries, it began at 16, 32, 84, 185, 218, 223, 312 W. It is essentially
   *time since reset*, not irradiance, not load, not SOC.
5. **The unit reports no fault.** Status byte 0x03 throughout.
6. **Its output current sensor under-reads by ~1.8x**, measured against two
   BMS shunts that agree with each other within 0.8 A.
7. **This model has no PV-side current sensor at all** — the 0x15 current and
   power fields are structurally zero.

## The theory

**The controller is chasing a current target with an instrument that reads
low, and it has no independent way to notice.**

Walking left down the IV curve *is* demanding more current. The controller does
that continuously until the array collapses, and never reverses. That is what a
regulator does when it believes it has not yet reached its setpoint — and
`chg_target` advertises **60 A**, which this array can never supply.

Point 7 is what makes it unrecoverable. With no PV-side sensor, the MPP tracker
must infer array power from the output side, `P = Vout x Iout`. Its only power
signal is the very measurement that is wrong. If the error is non-linear with
current — reading progressively lower as current rises — then moving left looks
like *power still increasing*, so the peak is never detected and there is
nothing to turn the tracker around. It walks until physics stops it.

This one fault accounts for all seven observations:

| observation | explained by |
|---|---|
| walks past MPP without reversing | no valid peak in the inferred power signal |
| always walks *down*, never up | under-read → "need more current" → move left |
| 1.8x under-report | the sensor fault, measured directly |
| bounce always works | reset re-runs a fresh sweep from Voc |
| holds 15-60 min after | the push is slew-limited; it takes that long to walk |
| start is time-based, not power-based | it is a control-loop drift, not a response to conditions |
| "no faults active" | the unit cannot detect that its own sensor lies |

## What this does NOT explain, honestly

- **Why a pure 1.8x scale error would matter.** Scaling `P` by a constant does
  not move its argmax, so a clean 1.8x error should still let hill-climbing
  find the peak. The theory therefore *requires* the error to be non-linear,
  and that is inferred rather than measured. It is the weakest link.
- **The 25-50x apparent under-report during a clamp** is a different
  mechanism, not more of the same: once the converter stops switching, current
  reaches the battery through the body diode and bypasses the sensor entirely.

## Alternatives not ruled out

- **A firmware bug in the MPP algorithm.** Cannot be tested by updating — the
  unit is already at its final firmware (1.09).
- **Interaction with the BMS charge request.** The bus advertises 28.6 V / 60 A
  while the MPPT's own config says 28.0 V; if the controller is servoing to a
  request it cannot meet, the same walk follows without any sensor fault.
- **Partial shading / multi-peak IV curve.** Real for a soiled 2-string array,
  but it would produce hunting between peaks, not a monotonic walk to collapse.

## Is it faulty?

**The output current sensor: yes, demonstrably.** ~1.8x low, measured against
two independent shunts, and confirmed by the unit's own Modbus energy counters
agreeing with the wrong value (same sensor, so no arbitration).

**The power stage: no.** It delivers 600+ W and holds a correct MPP for up to
an hour after every reset. Nothing is failing to convert.

**The tracking behaviour: faulty in effect, cause inferred.** The link from
sensor to tracker is a strong argument, not a proof.

**Is it degrading?** Unknown, and worth saying plainly rather than guessing:
the walk-down is present in the earliest data available (07-30 already swings
113 → 28 V). There is no baseline from before it started.

## How to settle it

One measurement decides between "bad sensor" and "bad algorithm": **an
independent clamp meter on the MPPT output**, per
`docs/design/dc-current-instrumentation.md`.

- If actual output current is ~1.8x the reported value **and the ratio changes
  with current**, the sensor fault is confirmed and the causal story stands.
- If the ratio is a clean constant, the theory's weak link breaks and the
  cause is more likely algorithmic or the BMS-request interaction.

Either way the operational answer is unchanged, because the guard already
handles it: bounce on detection, and consider bouncing at the 45 V cliff before
the collapse completes.
