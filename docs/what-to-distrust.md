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
  45 minutes to about 10.
- **The cliff is not absolute.** Roughly a third of 45 V crossings recover on
  their own. What separates them is elapsed time, not depth. Regenerate for
  current figures.
- **No meter on this system has passed an absolute check.** The MPPT is
  self-consistent but reads low; the BMS is self-*in*consistent by ~12%;
  `dc_w` disagrees with both. See `xanbus-unknowns.md` #5 and #11. This is the
  single biggest open technical question and it needs a clamp meter on site.
- **The suspected root cause of the latch is the MPPT's current-sensor
  offset**, not its under-report — a scale error cannot move an `argmax`, an
  offset can. Unproven. If it holds, the guard and the early-bounce trigger
  are both symptom treatments.
- **The 28.0 V ceiling change is working** — cell imbalance roughly halved at
  matched exposure.

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

---

## 4. Standing suspicions

Where I would look first, in order:

1. **Anything `cliff_table.py` says.** Three defects in three days. The
   28-minute/29-minute recovery-vs-clamp separation is clean across 27
   episodes but survived its first stress test only because I examined an
   outlier instead of accepting it. Treat it as an observed boundary, not a law.
2. **Any absolute power or energy figure.** All of them rest on meters that
   disagree with each other by 12–40%.
3. **The daily ledger's `solar_wh`.** Its inferred branch credits house load as
   solar whenever `pv_v ≥ 15`, which admits every twilight and overcast hour —
   about 600 Wh/day on a clean day. Quantified, deliberately not fixed, see §5.
4. **Anything in a `.md` that is not regenerable.** Especially if it has a
   number in it.

---

## 5. Open, and who owns it

**Needs the operator:**
- **#40** — one supervised early-bounce test at 40–45 V. The only blocked task.
  Design it knowing a third of crossings self-resolve, or the bounce will get
  credit for cases that needed nothing.
- **Three ledger decisions, best settled together**, because they are one
  question — whether to correct `dc_w` by its measured offset everywhere it is
  consumed: the `solar_wh` inferred-branch gate, the `load_wh` column, and the
  offset itself. Each is quantified in `xanbus-unknowns.md`. I have twice
  declined to change them unilaterally because they move every historical day
  on the dashboard.
- **Clamp meter on site.** Priority is the **MPPT output on a dim morning at
  low current** — that is where the sensor-offset hypothesis is decisive — not
  the inverter input at night.
- **Arm the outage alerting.** Deployed, tested, dormant until
  `VOLTHIUM_ALERT_WEBHOOK` is set on the Pi.
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
