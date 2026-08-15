# What to distrust

*Written 2026-08-10, at the operator's request, before a context compaction.
Notes from me to whoever picks this up next — most likely me, without memory
of having learned any of it.*

This is not a status document (`STATUS.md`) and not the working record
(`xanbus-unknowns.md`). It is the shortest thing I could write that would have
saved me the most time, and it is mostly about **how information in this
project goes wrong**, because over four days that turned out to be the
dominant failure mode — not hardware, not the cloud, not the Pi.

---

## 1. The single most important habit

**Regenerate numbers. Do not quote them.**

Every figure that matters has a script. If a number in a document was not
produced by one of these, treat it as a rumour:

| script | produces |
|---|---|
| `cliff_table.py` | the 45 V crossing table and everything derived from it |
| `meter_offset.py` | the dark-hours BMS vs `dc_w` offset |
| `float_calibration.py` | the neutral-battery three-way meter comparison |
| `bms_coulomb_check.py` | BMS reported current vs its own coulomb counter |
| `descent_profile.py` | how each 45 V crossing descends, and the near-Voc vs loaded split |
| `latch_exposure.py` | how long the array is actually clamped per latch |
| `ledger_gate_compare.py` | what the daily ledger's `solar_wh` would be under a different gate |
| `energy_balance.py` | the whole-system charge balance for a day, and which meter breaks it |
| `fridge_split.py` | the dark-hours load split into fridge on/off, and what `dc_w` does across it |
| `status_check.py` | live health; prints an explicit INCOMPLETE verdict rather than a false all-clear |

`cliff_table.py` alone produced **three different wrong headline numbers in
three days**, each of which looked completely reasonable at the time. Details
in §3. That is the argument.

---

## 2. What is actually true right now

Stated as pointers, deliberately, so this section cannot rot into another set
of stale numbers.

- **The latch is real, understood well enough to fix, and fixed automatically.**
  `xanbus_latch_guard.py` on a 5-minute timer. It works; exposure is down from
  45 minutes to a median of **about 20** — regenerate with
  `scripts/latch_exposure.py`. This said "about 10" until 2026-08-11, taken
  from the `clamped_s` field on `mppt_latched`, which is emitted the instant
  `now - clamp_since >= LATCH_CONFIRM_S` and therefore reports 600 s every
  time by construction. Twelve latches, spread of 8 seconds. Same shape as the
  unreachable recovery branch in §3: a number the code guarantees, quoted as a
  property of the array. The guard is still a large win, and it is about half
  the win that was written down.
- **The cliff is not absolute.** Roughly a third of 45 V crossings recover on
  their own. What separates them is elapsed time, not depth. Regenerate for
  current figures.
- **No meter on this system has passed an absolute check.** The MPPT is
  self-consistent but reads low; the BMS is self-*in*consistent by ~12%;
  `dc_w` is precise and inaccurate. `energy_balance.py` shows the whole-system
  charge balance failing by about **half the source**, both days tested — the
  sharpest statement of the problem so far. `dc_w`'s share of that is now
  bounded at 8% (see §5), so the residue points at the MPPT under-read, which
  nothing here can currently size.
- **There is NO supported root-cause theory for the latch.** The current-sensor
  offset was the leading candidate and was **refuted 2026-08-11**: the offset
  sits on an OUTPUT-side sensor, so the error is `P_true − 2.2·V_batt` with
  `V_batt` ~constant — a constant subtraction, and `argmax(P−c) = argmax(P)`.
  Exactly as argmax-neutral as the scale error it was invoked to replace. The
  fitted 2.2 A intercept was also a pooling artifact (−0.03 A on the tracking
  regime alone) and 10 of 18 clamps begin above 2.2 A. The guard is symptom
  treatment and that is fine; it works.
- **The 28.0 V ceiling is NOT shown to reduce imbalance — task #44 is REOPENED.**
  Its own pre-registered overturn condition was met the day after it closed:
  08-10 held SOC 100 for 375 min and peaked `dv_a` 0.429, worse than the
  "before" baseline. The metric was also a max-of-one-sample (p95 was 0.108),
  the change date was wrong by three days, and `dv_b` never moves.

---

## 3. The drift catalogue

Not a confession list — a pattern library. Each entry is a real incident from
2026-08-07..10 with the generalisable shape in bold.

**Hand-maintained numbers always drift.** The cliff table had 9 rows, prose
under it saying "twelve of twelve", and a summary saying "14 of 14". All three
were written at different times and none was wrong when written. Worse, it had
only ever looked at *mornings* — the missing afternoon crossings were the
energetically expensive ones.

**Documentation outlives the system it describes.** `RUNBOOK.md` described a
four-service BLE system weeks after RS485 became primary and BLE was retired.
The `xanbus` skill still taught `delta < 2.5` — the exact detector bug that had
already been fixed in code, so anyone following the skill would have rebuilt a
shipped defect.

**A monitor can watch something that no longer exists and report health
forever.** `status_check.py` checked `volthium-logger` — disabled since July.
Its error count and restart count were a permanent, reassuring zero. The
process actually producing every reading was never checked. The fix was to
derive the service list from systemd rather than name it.

**A metric can go blind because the system IMPROVED.** As the guard got
faster, clamps became too brief to survive 5-minute bucket averaging, and
crossings silently stopped being counted. The table still looked complete.
This is the subtlest one in the catalogue and I would not have found it
without a crossing I had watched happen.

**A detector that cannot represent an outcome cannot discover it.** In
`cliff_table.py` the re-arm ran one line before the outcome check and wiped the
open episode, making the recovery branch unreachable. "None ever recovered"
was therefore guaranteed by the code, and I quoted it as a finding for days.

**Confounds recur in new contexts.** Demand limitation (battery full → MPPT
stops loading → array flies to Voc) first invalidated peak `pv_v` as an
array-health metric, then came back and faked a 47-minute "recovery" in the
cliff table.

**Partial measurements get filed as conclusions.** Task #44's test condition
was met by a day I had measured at lunchtime and filed as "incomplete". It sat
satisfied for a full day before anyone looked again.

**Verification needs verifying.** Twice, a patch string silently failed to
match and I proceeded as though the edit had applied. Once, a regression check
reported "CAUGHT" while actually testing unmodified code. Once, a "toothless
test" check itself was toothless. **Always confirm the thing you think you
broke actually broke.**

**Cross-meter arithmetic is wrong here, every time.** Every derivation that
differenced BMS against inverter was wrong. The ones that worked compared an
instrument with *itself* — the Otsu split on `pack_p`, the MPPT counter against
its own instantaneous reading, the BMS counter against its own current. When a
question can be posed as same-instrument, pose it that way.

**Guards have blind spots shaped like their design.** The skill-sync test
catches the two copies *disagreeing*; it cannot catch both being stale
together, which promptly happened.

*Added 2026-08-11, from the adversarial cleanup pass.*

**A field that cannot vary is not a measurement.** `clamped_s` on
`mppt_latched` is emitted on the sample where `now - clamp_since >=
LATCH_CONFIRM_S` first holds, so it reports 600 s every time — an 8-second
spread across twelve latches. "Exposure is down to about 10 minutes" was read
straight off it; the real median is 20. Identical in shape to the unreachable
recovery branch, and it went unnoticed because 10 minutes was a *plausible*
number. **The test: does this quantity have a distribution? If every sample
agrees to within noise, suspect a constant before you believe a finding.**

**An idempotence guard protects whichever copy is wrong.** Three copy-pasted
BLE stubs each began `if "aiobmsble" in sys.modules: return`, so only the first
importer won. `cloud/` sorts before `tests/`, the copy that won was the one
missing a method, and a real test failed in the full suite while passing alone
— for months, looking like flakiness. The guard existed to prevent
double-stubbing and in doing so it made the drift *fatal instead of harmless*.

**"Cosmetic" settings are rarely cosmetic.** `DISPLAY_TZ` was documented as
"Dashboard rendering tz (cosmetic only)". It is the `GROUP BY` key for every
daily and hourly aggregate, and it is set to Toronto for a site in British
Columbia. Most of the damage was nil — the day boundary lands in darkness — but
it silently breaks `mppt_counter_wh`, which is the standing pipeline audit.
**Grep for the word "cosmetic" and check each one.**

**A monitor can be green about the half that works.** The alerting check asked
whether the cloud could page and printed "alerts armed". The second path — the
Pi paging when the *cloud* is unreachable — had never been armed, and it is
precisely the one the first cannot substitute for. Not a stale check this time:
an incomplete one, which reads identically.

**A detector can invent an event out of its own jitter.** `cliff_table.py` only
ever reset `armed` inside the outcome block, so a latch that began with no open
episode left it armed for the whole latch — and the first bucket where the
delta drifted out of the band opened a "45 V crossing" from 30 V. The 13-minute
clamp of 2026-08-10 was that: thirteen minutes entirely inside one unbroken
latch, `pv_v` never above 33 V, while the Pi's own 1 Hz detector reported a
single continuous clamp. It was the sole source of "min 13" and the sole
exception to the timing rule. **Fourth defect in this one file.**

**A threshold that decides the headline is a finding about the threshold.**
Vary `BUCKET_S` alone and the cliff table says: 30 s → 17/13 with a 47-min
recovery; 60 s → 17/10, a *perfect* two-way separation; 300 s → the same
physical event that 60 s calls a 112-min CLAMP becomes a 120-min RECOVERY.
Raw cadence is 15 s, so 30 s is the more defensible choice by the file's own
reasoning — and 30 s is the one that breaks the rule. **Before believing any
result, re-run it with the arbitrary constants moved one notch.**

*Added 2026-08-15, clearing the found-but-not-fixed backlog. Almost every item
turned out to be one shape.*

**"I looked and it was fine" and "I could not look" must not print the same
thing.** Six separate instances, all shipping, all reporting health:
`status_check --hours 24` fetched the oldest 13.9 h of a 24 h window because
the endpoint caps at 10 000 rows, then called the missing newest hours STALE;
`health_check` parsed status_check's verdict — including the INCOMPLETE it
emits specifically so partial runs cannot read clean — and never put it in
`problems`; `section_wired` flagged a transport SWITCH but had no `else`, so
zero `read_ok` events (the path producing nothing at all) fell through quiet;
the git-sync check discarded `git fetch`'s exit status and compared against a
stale ref; `meter_offset` pooled four nights when asked for five and said
nothing; and the config watch could go blind with nothing watching. **The
test: can this check tell the difference between a clean result and no result?
If the same output covers both, it is not a check.**

**A guard scoped by a hand-written list is blind to exactly the case it was
written for.** The dc_w regression test named three read paths, so when
`solar_series` became the fourth it sailed through — for eight days, feeding
the history explorer from a table that still holds the corrupt −27844 W row.
The same shape as the BLE stub list and the install-script unit list. **Derive
the scope from the source; a list you maintain by hand is a list that goes
stale the moment someone else is careful.**

**Measure the fix before shipping it, not just the bug.** The ledger's
inferred-branch gate was estimated at ~600 Wh/day. It was 1150–1550. And the
authorised fix, measured against an independent estimate, *overshoots* in the
other direction. Both numbers were needed to describe the change honestly, and
only one of them had been asked for.

---

## 4. Standing suspicions

Where I would look first, in order:

1. **Anything `cliff_table.py` says.** Three defects in three days. The
   28-minute/29-minute recovery-vs-clamp separation is clean across 27
   episodes but survived its first stress test only because I examined an
   outlier instead of accepting it. Treat it as an observed boundary, not a law.
2. **Any absolute power or energy figure.** All of them rest on meters that
   disagree with each other by 12–40%.
3. **The daily ledger's `solar_wh`.** The gate was fixed 2026-08-11 — the
   inference is now reached only during a clamp, which removed 1150–1550 Wh/day
   (not the ~600 estimated). It is still not right: measured against the only
   non-MPPT estimate it now sits 23–31% LOW where it used to sit 28–45% high.
   `scripts/ledger_gate_compare.py`. The remaining lever is the `dc_w` offset,
   which is yours — see §5.
4. **Anything in a `.md` that is not regenerable.** Especially if it has a
   number in it.
5. **Any number that is the same every time you look at it.** See `clamped_s`
   in §3. A plausible constant is the hardest kind of wrong number to see.

---

## 5. Open, and who owns it

**Needs the operator:**
- **#40** — one supervised early-bounce test at 40–45 V. The only blocked task.
  Design it knowing a third of crossings self-resolve, or the bounce will get
  credit for cases that needed nothing.
- **RESOLVED 2026-08-12 — do NOT apply the −32 W correction to `load_wh`.**
  The offset is real, and correcting for it would still make the ledger worse.
  `scripts/fridge_split.py`, 12,573 dark samples over 60 h, split by Otsu:

  | | |
  |---|---|
  | fridge OFF, BMS | 80.7 W — the inverter is the only load |
  | fridge ON, BMS | 154.9 W |
  | step (the fridge) | 74.2 W at 32.3% duty = 0.58 kWh/day |
  | true total load | **104.7 W** |
  | `dc_w` | **113.6 W**, p5–p95 span only 22 W |

  **`dc_w` does not see the fridge.** It moves less than its own noise across a
  74 W step in real bus load, because it is the *inverter's own draw*, not the
  DC bus. So the +32.8 W over-read is genuine **for the inverter channel** —
  the 32 W on record, confirmed to three figures — but `load_w` is consumed as
  TOTAL house load, and there `dc_w` is only **8% high**, because the 33 W
  over-read and the 24 W time-averaged fridge it omits nearly cancel.

  Subtracting 33 W gives 80.7 W against a true 104.7 W: **−23%, where leaving
  it alone is +8%.** The correction is right about the wrong quantity.

  Two errors cancelling is not the same as being right — it stops holding the
  moment the fridge duty or the inverter draw changes — so the fix is to **add
  the fridge to `load_wh` (task #32), not to shift `dc_w`.** That also removes
  the reason this was ever load-bearing.

  This is also the second operating point the site visit was supposed to
  provide. The fridge duty cycle supplied it for free, every night, the whole
  time.

- **The remaining ledger question is `solar_wh`, not `load_wh`.** With the gate
  fixed, `solar_wh` tracks the MPPT's self-report, and
  `scripts/energy_balance.py` shows the whole-system balance failing by about
  half the source on both days tested — far more than `dc_w` can account for
  now that its total-load error is bounded at 8%. That points at the MPPT
  under-read, which no meter here can currently size.
- **`DISPLAY_TZ` is `America/Toronto` for a site in British Columbia.** Daily
  totals are unaffected (the boundary lands in darkness) but it silently
  misattributes `mppt_counter_wh` by a day, which defeats the pipeline audit,
  and shifts every hour-of-day axis by three. Setting it to
  `America/Vancouver` moves every historical day, so it is yours.
  `docs/cloud_architecture.md` has the measurements.
- **Clamp meter on site.** Priority is the **MPPT output on a dim morning at
  low current** — that is where the sensor-offset hypothesis is decisive — not
  the inverter input at night.
- **Arm the outage alerting.** Deployed, tested, dormant until
  `VOLTHIUM_ALERT_WEBHOOK` is set on the Pi. `status_check.py --with-pi` now
  reports this as NOT ARMED and will keep nagging; before 2026-08-11 it printed
  a green line based only on the cloud half of the paging path.
- **Railway Watch Paths** scoped to `cloud/**`, so documentation commits stop
  redeploying the telemetry ingest server.

**Mine, unblocked:** nothing of substance. That is worth saying plainly rather
than inventing work.

---

## 6. How to work here

- The Pi is a 1 GB box at an unreachable cabin. `CLAUDE.md` rule 1 is not
  advisory. Decode off the Pi; every ad-hoc job bounded.
- Consult the `xanbus` skill first — it is the distilled version of
  `xanbus-unknowns.md`. It lives in `kaanow/skillz`, is semver-versioned, and
  the rule there is **edit → bump `version:` → commit → push, same turn**.
- When a finding changes an operational rule, the skill is stale until you bump
  it. This document and `xanbus-unknowns.md` are the record; the skill is what
  you act on.
- Write the disconfirming check before believing a result. Most of the good
  findings here came from trying to break a result rather than from producing
  one, and most of the bad ones came from not bothering.

---

*A note on proportion, since a catalogue like this reads worse than the
situation is. The system itself has been stable throughout: telemetry has run
without a gap, the guard has cleared every latch unattended, and an
independent counter later showed the data pipeline is lossless to 0.44% across
a day that included two service restarts and a 35-minute cloud outage. The
failures above are almost entirely in the layer that describes the system, not
the system. That is the layer to be suspicious of.*
