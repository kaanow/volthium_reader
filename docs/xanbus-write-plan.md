# Xanbus write experiments — execution plan (A and B RUN 2026-08-06)

**Status 2026-08-06, all approved by the operator and executed that night:**

| | what | outcome |
|---|---|---|
| A1 | float_v, MPPT (dest 1), 27.2 → 27.4 → restore | **ACK, verified, restored** |
| A2 | bulk_v, MPPT (dest 1), 28.0 → 28.2 → restore | **ACK, verified, restored** |
| A3 | float_v, SW inverter (dest 0), 27.2 → 27.4 → restore | **ACK, verified, restored** |
| B1 | read equalize record | done — **inconclusive, see below** |
| B2 | monitor equalize | done, but **whole-record** watcher instead |
| C1 | lower bulk/absorb to 28.0 V | **NO-OP — already 28.0 V** |

**A's success criterion was met: the write path is general.** Same record
shape, four PGNs, and — the informative part — **A3 proves authority is
bus-wide, not per-device**: the SW inverter accepted the identical write
model on the first try. Change counters incremented and restores verified
each time.

Measured setpoints after the run (MPPT): bulk 28.0 V, absorb 28.0 V,
float 27.2 V, absorption time 3600 s.

Each experiment below is one command, listed with its exact effect, its blast
radius, and how to undo it.

Prerequisites, all already true: `can0` out of listen-only; address claim +
discovery + gateway function working; `xanbus_setpoint.py` deployed with
range guards and `--restore`.

Every experiment below uses `--restore`, which captures the original value,
writes the test value, verifies, then puts the original back and verifies
again. A run that fails mid-way leaves the original in place because the
restore path re-reads current state rather than assuming.

---

## A. Prove the write path generalises (30 min, benign)

We proved 0x11800 (absorption). The same record shape *should* work for the
others, but "should" is what got us four different refusals last time.

### A1 — Float voltage, MPPT
```
sudo .venv/bin/python scripts/xanbus_setpoint.py \
    --field float_v --dest 1 --set 27.4 --restore --send
```
- **Effect:** float target 27.2 → 27.4 V for ~10 s, then back.
- **Blast radius:** none at night (not floating). If it ran during float, a
  0.2 V rise for 10 s is far below any protection threshold.
- **Undo:** automatic; also trivially settable from the Insight UI.

### A2 — Bulk voltage, MPPT
```
sudo .venv/bin/python scripts/xanbus_setpoint.py \
    --field bulk_v --dest 1 --set 28.2 --restore --send
```
- **Effect:** bulk target 28.4 → 28.2 V briefly. Deliberately chosen
  *downward* — a lower ceiling is strictly safer if the restore fails.
- **Guard:** the tool refuses anything above 28.8 V, so the 29.2 V that ran
  pack A's weak cell away on 2026-07-29 is unreachable.

### A3 — Does the SW inverter honour the same model?
```
sudo .venv/bin/python scripts/xanbus_setpoint.py \
    --field float_v --dest 0 --set 27.4 --restore --send
```
- **Effect:** same field, different node. Tests whether authorization is
  per-device or bus-wide.
- **Blast radius:** the SW's charger is idle (no AC in), so its charge
  setpoints are inert until a generator runs.
- **If it NAKs or ACCESS DENIEs:** informative, and nothing changed.

**Success criterion for A:** all three ACK, verify, and restore cleanly. Then
the write path is general, not a quirk of one record.

---

## B. Retire a real risk (5 min, high value)

### B1 — Confirm equalize is still disabled, and that we can read it
```
sudo .venv/bin/python scripts/xanbus_setpoint.py \
    --field equalize_v --dest 1 --read --send
```
Read-only. Records the equalize voltage and the enable flag on PGN 0x11B00.

> **RUN 2026-08-06 — and it did NOT find the enable flag.** Recorded honestly
> because a false reassurance here is worse than none.
>
> Live record (instance `0x04`) vs factory defaults (`0x06`):
>
> ```
> live: 04 01 03 03 00 7d 00 00  78 69 00 00  00 7d 00 00 ...
> defs: 06 00 03 03 00 7d 00 00  00 7d 00 00  00 7d 00 00 ...
>                                 ^^^^^^^^^^^
> ```
>
> The only substantive difference is **offset 8: 27.0 V live, 32.0 V default.**
> The offset we map as `equalize_v` (offset 4) reads **32.0 V in both**, so it
> has never been changed from factory and is probably not what governs
> anything. Bytes 2 and 3 (`0x03 0x03`, the obvious flag candidates) are
> identical in both.
>
> So: **our field mapping for 0x11B00 is suspect**, and whatever was done on
> 2026-07-29 to disable equalize touched offset 8, not offset 4. We cannot
> currently assert either that equalize is safe or that it is dangerous.
>
> Resolving it needs the marker-and-diff method against the Insight UI — but
> **not** by toggling equalize, which is the one setting worth never touching.
> The safe version is observational: someone reads what the Insight's equalize
> page actually displays (enabled?, what voltage?) and we match it to the
> bytes. Until then, B2 watches the whole record.

> **Why this matters:** equalize was set to 32 V — **4.0 V/cell on an LFP
> bank** — and was *enabled* until 2026-07-29. It is disabled now, but the
> setting is one UI click from returning, and nothing currently alarms on it.
> Being able to read it means we can monitor it continuously.

### B2 — Add equalize state to the monitored fields

> **DONE 2026-08-06, but built differently than planned.** B1 failed to locate
> the enable flag, so watching "the flag" was not available. Watching the
> **whole record** is strictly better anyway: it cannot miss a change by
> looking at the wrong offset, which is precisely the failure B1 exposed.
>
> Shipped as `scripts/xanbus_config_watch.py` on an hourly timer, covering all
> four charge records (bulk / absorb / float / equalize) on **both** the MPPT
> and the SW inverter — 8 records, baselined and digested. Emits
> `xanbus_config_changed` with the changed offsets. Ignores byte[1], the change
> counter, which increments on every accepted write and would otherwise fire on
> our own restores.
>
> It runs at night too, unlike the latch guard: someone editing settings from
> the Insight UI in the evening is exactly the case worth catching.

Not a write. Once B1 confirms the layout, `xanbus_telemetry.py` emits an
event if the equalize-enable flag ever changes. Cheap permanent guard against
the single most dangerous setting on the system.

---

## C. The one with real operational value (needs discussion)

### C1 — Lower the bulk/absorb ceiling further, permanently

> **NO-OP as of 2026-08-06 — do not run.** Both records already read
> **28.0 V**, which is exactly what this proposed. The premise below ("28.4 V
> may still be too high") was stale: they had already been lowered from the
> Insight UI. Verified by direct read, not assumed.
>
> The watch item is unchanged and is about the *cells*, not the ceiling: if
> pack A's cell 4 still peaks above 3.65 V on the `/v2/history` imbalance
> chart at 28.0 V, then the problem is the imbalance itself and lowering the
> ceiling further only trades capacity for a symptom.

Pack A's cell 4 still reaches ~3.83 V at top of charge; that spread caused two
BMS disconnects. 28.4 V may still be too high for the weakest cell.

```
sudo .venv/bin/python scripts/xanbus_setpoint.py --field bulk_v   --dest 1 --set 28.0 --send
sudo .venv/bin/python scripts/xanbus_setpoint.py --field absorb_v --dest 1 --set 28.0 --send
```
- **No `--restore`** — this one is meant to stick.
- **Trade-off:** 28.0 V (3.50 V/cell average) charges LFP to ~97% and keeps
  the balancer active (threshold ~3.4 V/cell), while pulling the weak cell
  further from its cutoff. Slightly less capacity, materially less stress.
- **Discuss first:** this changes steady-state behaviour, unlike A and B.
- **Watch after:** cell-4 peak on `/v2/history` cell-imbalance chart; if it
  still exceeds 3.65 V, the problem is the imbalance itself, not the ceiling.

---

## D. Not planned, deliberately

- **Anything on the SW inverter that affects AC output.** It runs the cabin.
- **Equalize enable.** Never, on LFP.
- **Absorption time increases.** Longer at high voltage is the wrong direction
  for a pack with a runaway cell.
- **Firmware anything.** The MPPT is at its final version (1.09); the
  InsightHome is behind but is the fallback control path and nobody is on site.

---

## Rollback for all of it

Every field above is settable from the Insight UI at
`https://localhost:8443` (tunnel: `ssh -f -N -L 8443:192.168.1.71:443
kaan@kwpi.zt`). The physical fallback is unchanged: the Insight remains the
authority and our writes are ordinary config writes it can overwrite.

To revoke our write capability entirely: set `listen-only on` in
`deploy/pi/systemd/volthium-xanbus-capture.service` and restart the service —
the interface then physically cannot transmit.
