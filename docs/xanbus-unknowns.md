# Xanbus — what we still don't understand

Ranked by (value if solved) × (likelihood of solving). Companion to
`docs/xanbus-decode.md` (read side), `docs/xanbus-write.md` (write side) and
the `xanbus` skill.

## Tier 1 — worth testing soon

**1. It is a SLIDE, not a trigger — observed live 2026-08-06 morning.**

Caught the run-up in progress. Array voltage walks steadily DOWN as the MPPT
extracts more current, with no discrete event anywhere:

| local | pv_v | delta | solar W | house W |
|---|---|---|---|---|
| 07:16 | 63.0 | 36.6 | 24 | 90 |
| 07:42 | 51.5 | 25.0 | 33 | 108 |
| 08:15 | 52.2 | 25.6 | 43 | 130 |
| 08:41 | 44.6 | 18.1 | 41 | 131 |

No load step, no cloud edge, no charge-stage change, no SOC threshold — just a
monotonic walk down the IV curve as demand rises. **The precondition is the
interesting part: the battery was DISCHARGING (−50 W) in full daylight all
morning**, meaning demand exceeded supply continuously, so the MPPT was
pulling maximum current the entire time. That is what walks the operating
point down until it hits the diode clamp and cannot climb back.

**The array faces SOUTH-EAST and is shaded/oblique until early afternoon**
(user, 2026-08-06; confirmed in the data — peak power lands at 13:00-15:00
every single day: 799 W@13, 1001 W@15, 160 W@14, 148 W@13, 712 W@13).
Mornings run 30-130 W regardless of how good the day becomes.

That makes the morning latch **STRUCTURAL, not a fault**. House load is
~90-130 W; morning production is ~25-55 W. Demand exceeds supply every
morning by geometry alone, so the MPPT pulls maximum current, walks down the
IV curve and clamps — on any day, smoke or no smoke. It then stays clamped
until afternoon direct sun supplies enough current to climb back out, or
until demand falls.

This also explains the 2026-08-01..05 "five day latch": those were days when
afternoon sun never got strong enough (smoke) to break out of a clamp that
forms every morning anyway.

So the latch needs no trigger. It needs only *sustained demand above what the
array can supply at that moment*. Which implies a preventative fix exists that
the mode-bounce does not provide: **limit charge current so the operating
point never reaches the clamp.** Worth considering once the write path is
trusted (`CHG_CFG_I_LIMIT` / max charge rate, currently 100%).

### Refinement 2026-08-06 afternoon: it is a RUNAWAY, and it overshoots the MPP

A full day of 5 min buckets shows the walk does not stop at the maximum power
point — it goes straight through it and keeps going:

| local | pv_v | solar W | note |
|---|---|---|---|
| 05:40 | 82.5 | 0.8 | first light, near Voc |
| 06:55 | 55.9 | 22.3 | |
| 08:10 | **52.4** | **44.5** | **peak power — this is the MPP** |
| 08:55 | 42.1 | 35.1 | past the knee, losing power |
| 09:55 | 34.7 | 23.5 | |
| 10:10 | 30.1 | 11.4 | |
| 10:25 | 28.3 | 6.2 | clamped, and stayed clamped |

House load was a flat ~113 W throughout. The tracker sat at 52 V making
44.5 W, then walked *down* the wrong side of the curve for two hours and
never turned around.

**Geometry rules out irradiance as the cause.** For the site (51.119 N,
-121.210 W) on 6 Aug, plane-of-array beam irradiance on a south-east array
*rose* between 08:10 and 10:25 by **+64% to +79%** — and that holds for every
plausible tilt (30/40/50 deg), so it does not depend on knowing the mounting
angle. Available power went up ~1.7x while delivered power went down 7.2x:
the MPPT ended up roughly **12x off** what it had already demonstrated it
could get.

That reframes the mechanism. Past the knee the feedback is **regenerative**,
not restoring: moving left reduces power, which deepens the deficit, which
makes the controller pull harder, which moves it further left. So —

- the morning **geometry** supplies the initiating condition (demand > supply);
- past the knee it becomes a **runaway**, which is why it never recovers on
  its own and why it survives into the afternoon.

Two consequences:

1. **Current-limiting is now the indicated fix, not merely an idea.** It
   attacks initiation; the mode-bounce only treats the end state.
2. **A bounce will only hold if post-sweep power exceeds load.** At 10:55 a
   re-sweep should find roughly 75 W against a ~113 W load — still a deficit,
   so it should re-latch. That is a concrete prediction for Unknown #2 below.

**That prediction was wrong, and the way it was wrong matters.** The re-sweep
at 10:58 found **227 W**, not 75 W — three times the estimate — and the fix
held. The error was assuming the 44.5 W seen at 08:10 was the array at its
MPP. It was not: the tracker was *already* descending by then, so 44.5 W was
just the high-water mark of an already-degrading trajectory, not the array's
capability. Post-fix the array settled at **88 V**, matching the ~89.8 V MPP
measured during the 2026-08-05 standby test.

Which means the runaway had been under way since **first light** — pv_v
declined monotonically from 82.5 V at 05:40 and never had a healthy tracking
period all morning. The morning was not "structurally weak"; it was
**structurally latched**. Corrected accordingly below.

### Diagnostic: cloud vs runaway

They separate cleanly, because a cloud and a tracker walk-down move different
axes:

- **Cloud/smoke** cuts irradiance, which cuts *current*. Panel Vmp barely
  moves with irradiance, so power drops at roughly **constant voltage**.
- **Runaway** is the operating point sliding left, so power and **voltage
  fall together**.

Worked example, 2026-08-06 11:10 to 12:40: pv_v 85.4 -> 48.2 (-44%) and power
235.8 -> 127.2 W (-46%). Voltage and power fell in lockstep, so this is the
runaway restarting, not weather — even though it happened while irradiance
was still climbing toward the 13:00-15:00 peak.

Use this before blaming smoke for any future production shortfall.

`mppt_latch_context` still ships 20 min of 1 Hz run-up with each latch event
for the finer detail.

**2. Does the latch recur after our fix, and how fast?**
If it re-latches within minutes, the guard's cooldown and daily cap turn into
the real control loop and we need a smarter strategy (e.g. deliberately
limiting charge current so demand never exceeds supply). The guard records
`recovered` on every attempt, so the data will answer this.

> Still unanswered on 2026-08-06, because the guard's first meeting with a
> real latch found a bug instead. **The detection ceiling was tighter than the
> MPPT's own reporting dither.** With `out_v` steady at 26.50 V, reported
> `pv_v` hops over a ~1.1 V range (27.5-29.9), so the delta swings 0.90-3.44 V
> second to second. Against a 2.5 V ceiling, 47% of 15 s buckets held at least
> one out-of-band sample. The detector therefore raised `mppt_latched` at
> 17:28:03Z and retracted it 25 s later on a 2.96 V delta while the array
> stayed clamped for hours; and the guard's clamp fraction never reached 0.9,
> so it declined to act on every 20 min run — *silently*, because a
> below-threshold fraction returned without emitting anything. Five hours of
> latch, no trace. Fixed in f42e88e: both ceilings to 4.0 V (observed dither
> plus margin, still far below the 8.2 V smallest healthy delta), 120 s
> hysteresis on release, and a `latch_guard_ambiguous` event so a
> below-threshold bail can never be invisible again. After the fix the same
> live clamp sampled at **fraction 1.0 (179/179)**.
>
> Lesson worth generalising: a threshold on a reported value has to clear that
> sensor's own quantisation, and a guard that declines to act must say so.

**ANSWERED (first half), 2026-08-06 10:58 local — the guard cleared a real
latch, unattended, end to end.** Sequence from its own journal:

```
10:58:09  claimed 0x80, answered discovery (0x1F00F/1F810/1F014/1F80E) from node 2
10:58:11  sent PGN 0x14000 -> node 1: 02 (Standby)    <- node 1: ACK
10:58:26  sent PGN 0x14000 -> node 1: 03 (Operating)  <- node 1: ACK
10:59:34  latch_fix_result: acked=true recovered=true
          before: fraction 1.00  pv_v 29.6
          after : fraction 0.00  pv_v 93.0 (max 98.3)
```

Production went **5.3 W -> 235.8 W**, a 44x step, and the battery flipped from
-110 W (discharging in full daylight) to +119 W charging. The clamp had been
costing ~110 W continuously.

**It did not re-latch**: five subsequent guard runs (11:17 / 11:37 / 11:57 /
12:17 / 12:38) were all silent. So a bounce is durable when the array can
out-supply the load, and the 45 min cooldown / 4-per-day cap are not acting as
the control loop — at least on a day like this one.

Still open: the recurrence question in the *deficit* case, i.e. what happens
when a bounce lands while production is still below load. The 12:40 descent
(see the cloud-vs-runaway diagnostic above) should produce that test today.

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

**10. Array health — improving, but the record is CONFOUNDED by the latch.**

Peak array voltage by local day: 07-30 112.7, 07-31 111.5, 08-01 111.8,
08-02 76.9, 08-03 68.4, 08-04 61.7, **08-05 98.9**. MPPT-metered energy the
same days: 984, 775, 242, 189, 261, 189, **1735** Wh.

Do NOT read that 9x energy jump as smoke clearing. 08-02..04 were spent
LATCHED, and a latched MPPT cannot meter power that bypasses it through the
diode — so those totals are floors, not measurements. The 08-05 jump is mostly
the latch being cleared at 13:37, not extra sun.

**Judge array health from AFTERNOON hours only.** The array is south-east
facing and shaded until early afternoon, so morning comparisons measure
shade, not air quality — an earlier "smoke has not cleared" reading based on
07:00/08:00 hours was withdrawn for exactly this reason.

Peak `pv_v` is the sounder indicator since it is independent of the metering
fault, and 61.7 -> 98.9 V is a genuine improvement. But it is still partly
latch-dependent (a latched array pins at ~28 V), so it is not clean either.

**08-06 is the first day that starts with a working latch detector and a
known-good converter, so its daily total will be the first uncontaminated
production figure this project has.** Judge smoke recovery from that, not from
the back-history.

Dawn 08-06 also showed the array reaching `pv_v_max` 103.4 V at low load —
encouraging, though dawn Voc is not comparable to midday Voc.

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
