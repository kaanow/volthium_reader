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

**5. The MPPT under-reports EVERYTHING, and no third meter exists to arbitrate.**
Two results from 2026-08-06:

*The energy counter is not independent.* Modbus reg 131 is the MPPT's own
daily output Wh (resets at local midnight; reg 135/139/143 are week/month/year,
reg 133/137/141 the matching second-counters). Over the REGULATING window only
(post-unlatch 14:08-20:28, excluding latched hours the counter legitimately
cannot see) it logged 1153 Wh where battery charge + inverter draw + fridge
require **2053 Wh — a 1.78x under-report**, consistent with the instantaneous
current error. So the counter is derived from the same sensor and is useless
as a cross-check.

*There is no independent third meter.* The SW inverter's Modbus reg 81 reads
−5580 mA, identical to CAN `dc_a` — it measures its own terminals, not the
battery. Every other candidate (SOC, remaining_ah) is BMS-derived from the
same shunt, so it is circular.

**Therefore #5 cannot be settled remotely.** It needs an external
measurement — a DC clamp meter on the MPPT output during an on-site visit.
Operationally this is low-stakes: SOC and energy come from the BMS, and the
display already derives production from battery + inverter rather than
trusting the MPPT. Recording it so nobody re-runs the analysis expecting
a different answer.

*Original characterisation, retained:*
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

**6. PGN 127166 ("MPPT Data") — PARTIALLY DECODED 2026-08-06.**
60-byte fast packet, >16 frames (so it needs the standard 3/5 split; the
berrybms nibble split cannot reassemble it). 10,842 records paired against
labelled Modbus counters within 30 s:

| offset | width | meaning | evidence |
|---|---|---|---|
| 46 | u32 | **daily output Ah** | offset50/offset46 = 27.2-27.5 V across all samples — that ratio IS the battery voltage, so 46 is amp-hours of the same quantity 50 counts in watt-hours. Resets at local midnight. |
| 50 | u32 | **daily output Wh** | tracks Modbus reg 131 with a constant +7..8 offset; both reset to 0 at local midnight |
| 54 | u32 | active-seconds counter | increments ~1/s while producing, freezes when production stops, does NOT reset daily — so a week/month/lifetime accumulator, period unidentified |
| 58 | u16 | a daily counter | resets at midnight, held 712 all evening; semantics unknown |
| 19, 23 | u32 | slow lifetime counters | +1 and +12 over ~4.6 h |

The daily Wh/Ah pair is the useful part and is now confirmed. NOTE it inherits
the MPPT's current-sensor under-report (see #5), so it is a convenience, not a
truth source — integrating the derived production is still more accurate.

**7. RESOLVED 2026-08-06 — neither carries telemetry we want.**

`127005` (0x1F01D) is **not a counter or a measurement**. It is a **20.0 Hz
(50 ms) s16 at offset 2**, broadcast by BOTH the SW and the MPPT, oscillating
around zero (range −67..+74, mean +16, stdev 30) and **flipping sign between
consecutive samples**. Values are quantised in ~3.4 steps. Nothing physical on
this system changes sign twenty times a second, so this is a control or
clock-synchronisation term, not telemetry — consistent with IEA-PVPS T11-04
describing Xanbus master election and sync. It accounts for ~12% of bus
traffic and can be safely ignored.

`126991` (0x1F00F, "Sts") is **byte-for-byte CONSTANT** — `030403030200` on
both nodes across 39,586 frames overnight. Earlier notes claimed a toggling
flag byte; that was wrong. It is a static "operating normally" heartbeat, and
it is what the gateway asks a new node for during discovery (which is why we
answer it in `xanbus_node.py`). Only interesting if it ever changes — worth a
re-check during a fault.

`127167`, `127177`, `127174` — still byte-for-byte constant. Same conclusion:
recheck during a fault, ignore otherwise.

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
- ~~What is the SW inverter's `dc_w` measuring?~~ **Its own draw (house AC
  loads) only — it is blind to solar.** Proven 2026-08-05 by comparing a
  known latch (~380 W bypassing the converter) against dusk darkness: dc_a
  and dc_w were identical in both (~−4.5 A, ~120 W). So it can never serve as
  a bus-total, and it cannot discriminate a latch from darkness.
- ~~Can the latch guard false-positive at dawn/dusk?~~ **Yes, and it was
  able to.** The array voltage passes through battery voltage on its way
  up/down, so darkness reads as a clamp for ~5–10 min (observed 20:40:
  pv_v 28.7 vs out 26.5, delta 2.2 V, 1 W production). Fixed by requiring two
  CONSECUTIVE confirmations 20 min apart — longer than the dusk window,
  far shorter than a real latch.
