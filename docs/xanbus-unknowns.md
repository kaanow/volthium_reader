# Xanbus — what we still don't understand

Ranked by (value if solved) × (likelihood of solving). Companion to
`docs/xanbus-decode.md` (read side), `docs/xanbus-write.md` (write side) and
the `xanbus` skill.

## Tier 1 — worth testing soon

**1. Does the latch have a trigger, or is it purely an IV-curve slide?**
We know the *mechanism* (demand exceeds supply → operating point slides to the
diode clamp) but not whether something *precipitates* it: a load step, a cloud
edge, an SOC threshold, a charge-stage transition, or a controller-side
decision. Now instrumented — `mppt_latch_context` ships 20 min of 1 Hz
run-up with every latch event. **Test: read the trail after the next latch.**

**2. Does the latch recur after our fix, and how fast?**
If it re-latches within minutes, the guard's cooldown and daily cap turn into
the real control loop and we need a smarter strategy (e.g. deliberately
limiting charge current so demand never exceeds supply). The guard records
`recovered` on every attempt, so the data will answer this.

**3. The MPPT status byte (offset 0 of DcSrcSts2).**
Always 0x03 in normal operation. Captured now but never seen change. Does it
move during a latch, a fault, or a mode change? **Test: correlate against the
latch trail.** Cheap — pure observation.

**4. Which other config records accept writes?**
We proved 0x11800 (absorption). The same shape *should* work for 0x11700
bulk, 0x11A00 float, 0x11B00 equalize — untested. Also unknown whether the SW
inverter (node 0) honours the same authorization model as the MPPT.
**Test: read-modify-write-restore on each, benign values only.**

**5. The MPPT output-current discrepancy is AFFINE, not a simple error.**
Measured over 839 paired samples while regulating: the ratio true/reported
FALLS from 1.88 to 1.46 as current rises, while the difference RISES from
+3.3 A to +9.8 A. Fit: `true ≈ 1.35 × reported + 2.2 A`. That is neither a
scale error nor an offset, which is odd for a miscalibrated shunt. The fridge
(~0.8 A average) accounts for barely a tenth of it. **Open question: is the
MPPT under-reading, or is the BMS pair over-reading?** They agree with each
other, but they are the same model, so a systematic model error would not show
up as disagreement. **Next test:** compare BMS-integrated Ah against the
MPPT's own energy counters over a full day — an independent third opinion.

## Tier 2 — real value, harder

**6. PGN 127166 ("MPPT Data") — the energy counters.**
60-byte fast packet, >16 frames, with 6 varying byte positions (@0, 19, 23,
46, 50, 58). Almost certainly cumulative Wh/runtime counters matching the
Modbus registers 30:131/135/139/143 (+115 Wh over one morning) and 30:133/137
(operating seconds). Correlation-decodable with the labels we already have.
Nice-to-have: integrating `solar_w` gives the same answer.

**7. Three PGNs that carry information we can't read.**
- `127005` (0x1F01D) — 12% of bus traffic, only bytes 2–3 vary: one u16, 49
  distinct values in 2.5 h. A timer or countdown?
- `126991` (0x1F00F) — one flag byte toggling between two values. This is the
  "Sts" PGN the gateway asks new nodes for, so its 6 bytes encode device
  health somehow.
- `127167`, `127177`, `127174` — byte-for-byte constant all day. Probably
  carry nothing while nothing is wrong; worth re-checking during a fault.

**8. Is there an access-level / unlock mechanism above "gateway"?**
IEA-PVPS T11-04 §5.3 describes Xanbus configuration messages carrying
**user / service / factory** access levels. We reached whatever level the
gateway role grants. Factory-level operations (calibration? firmware?) may sit
behind something else. Unknown whether anything we want lives up there.

**9. The RV-C proprietary path (DGN 0xEF00 + NAME-seeded CRC).**
Implemented and doc-vector-verified in `xanbus_write.py`, but it belongs to
the Freedom product family; no Conext device has been seen using it. Probably
a dead end now that the native path works — keep for reference.

## Tier 3 — open questions about the physical system

**10. Is the array actually healthy?**
The smoke hypothesis explains the current ceiling well, but we've never seen
the array perform in clean air since instrumenting it. **Test: watch dawn
`pv_v` and sustained current once the fire smoke clears.** Recovery signature
= peak `pv_v` back toward ~114 V with >3 A sustained above 60 V.

**11. What is the SW inverter's `dc_w` really measuring?**
Assumed to be its own DC draw (house AC loads). At night it matches total
battery discharge, which is consistent — but that's also consistent with it
being a whole-bus measurement. Matters for the power-balance arithmetic.
**Test: run a large, known AC load and see whether dc_w tracks it 1:1.**

**12. Generator fields — wired on spec, never validated.**
`126998 assoc 0x13` (GEN1) V/I/freq. Correct per Xantrex's own enum table and
berrybms's gen-on captures, but our generator has never run during a capture.
**Test: whenever the generator next runs.**

**13. Pack A's cell imbalance — trajectory unknown.**
Daily worst spread is ~400 mV on A vs ~30 mV on B. Is it stable, worsening, or
seasonal? Now charted on `/v2/history`; needs weeks of data. This is the one
unknown with a hardware-failure tail risk.

## Answered — kept so we don't re-litigate

- ~~Why are our transmitted frames ignored?~~ No address claim (J1939/81).
- ~~Why ACCESS DENIED on commands?~~ NAME function must be 134 (gateway).
- ~~Why ACCESS DENIED on config writes?~~ Must use write-form `byte[0]=0x00`.
- ~~Why NAK on config writes?~~ Change counter is an optimistic-concurrency
  token; echo the one you read.
- ~~Why does PV power read 0?~~ No input-side current sensor on this model.
- ~~Where's the fridge in the data?~~ Bimodal in native 5 s `pack_p`.
  Characterised over 7 night hours / 8 complete cycles (Otsu split at
  −123 W): **draw 76.0 W, duty 29.0%, 0.53 kWh/day, cycle 14 min on /
  36 min off (~50 min period)**. Needs no new logging — 15-minute buckets
  simply averaged straight through it.
- ~~Is the MPPT damaged?~~ No — diode-clamp latch, clears on a mode bounce.
