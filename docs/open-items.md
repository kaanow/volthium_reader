# Open items

Only things that are **still open**. Each carries the measurement it rests on,
so work starts from evidence rather than re-deriving it. Closed work is in the
git log — the commit messages carry the before/after numbers.

Last reviewed 2026-10-21.

---

## 1. The Pi is browning out — live, and what corrupted `pack.csv`

`vcgencmd get_throttled` returns **`0x50000`**: bit 16 **under-voltage has
occurred**, bit 18 throttling has occurred. It read `0x0` on 2026-10-05, so
this is recent.

Evidence it was a power event, not a clean restart:

- **Two unclean reboots on 2026-10-11**, at 07:55:05 and 09:32:34 local.
- **Neither was the weekly timer** — `volthium-weekly-reboot.timer`'s last
  trigger is 2026-10-04 04:00:10.
- Both prior boots end mid-sentence in ordinary uploader output with **no
  shutdown sequence**. A clean `systemctl reboot` logs service stops.
- The current boot logged an **ext4 journal recovery**.
- The cloud shows a matching **11.6-minute gap at 14:55Z → 15:06Z**.

That is what wrote the NUL bytes into `data/pack.csv` — buffered writes lost
when the board lost power. The telemetry record itself is intact in the cloud.

**Consequences are contained; the cause is untouched.** Tools now degrade
instead of crashing (`3fd91a7`) and `status_check` reports the damage
(`10be24d`), but nothing has been done about the power itself.

Open questions, none answerable remotely:

- What feeds the Pi, and did the supply sag or the source dip? SOC was 57–65 %
  around 2026-10-05, the low point of a thin solar week.
- One-off or recurring? The throttle flags are "since boot", so all that is
  certain is it happened within the current boot (2026-10-11 onward).
- **Nothing alerts on `get_throttled` changing.** A brownout ten days old
  surfaced only because I was looking for something else. A cheap watch on
  that register would have caught it the same day — worth doing regardless of
  what the cause turns out to be.

---

## 2. Whether `data/` should be git-tracked at all

`.gitignore` documents that `data/` is committed on purpose ("so each
autonomous-loop push keeps the cabin's data"). Two consequences:

**The hazard.** The committed `data/pack.csv` is a June truncation —
`47e60c7` cut it from 16,715 rows to 2,330. So any `git checkout -- data/`,
`git restore data/` or `git reset --hard` on the Pi overwrites live telemetry
with a four-month-old snapshot *and* re-arms the ownership trap (the file
returns owned by whoever ran it, 0644, locking out the `claude` services).
That is exactly what cost 70 minutes of telemetry and the Jul–Oct local
history on 2026-10-04. It also means a pushed commit cannot be amended once
the Pi has pulled it, since re-syncing would need `reset --hard`.

**The growth.** `pack.csv` is **77 MB and growing ~4.8 MB/day** as a tracked
file.

The detector in item 1's fix catches the *symptom*. The decision here is
whether to stop tracking the genuinely-live files (`pack.csv`, `weather.csv`,
the `*_log.csv` set) and keep a seed/archive copy under a different name.
That changes the autonomous-loop convention, which is why it is a decision and
not a tidy-up.

---

## 3. Restore the Pi's `pack.csv` history for Jul 1 → Oct 4

**Railway is canonical and verified complete** across the whole span (14
weekly probes, zero empty days), so nothing is permanently lost.

Not done unprompted: restoring means replacing the live file the uploader
tracks by inode, on a box that is unrecoverable if it wedges, with a plausible
re-upload storm. Cost of leaving it is that the Pi's discharge model is fitted
on a shorter history, which self-heals as days accumulate.

If wanted: build the reconstruction from Railway **on the laptop**, splice
during a window you are watching, and confirm the uploader's offset/inode
state survives.

---

## 4. Energy ledger scaling ceiling — approximately February 2027

Measured against production 2026-10-05 with 68 days of history:

| endpoint | time | rows |
|---|---|---|
| `/api/solar/energy?days=30` | 2.24 s | 31 |
| `/api/solar/energy?days=120` | 4.45 s | 68 |
| `/api/solar/energy?days=365` | 4.50 s | 68 (whole archive) |
| `/api/history/stats` | 3.69 s | — |

`days=120` and `days=365` agree because both already scan everything there is.
So the full-archive scan sits at **4.5 s against a 10 s statement timeout**,
and straight-line on row count it crosses around 150 days of history. The
failure mode is an exception, not a slow page.

An index does **not** help — `solar_readings_source_ts_desc` already covers
the range predicate; the time goes on aggregating ~1.2 M rows. The fix is a
per-day rollup so the scan is O(days).

Deliberately not built: a rollup must reproduce `solar_energy_daily`'s
semantics exactly — the clamp-gated `GREATEST()`, the
difference-of-two-miscalibrated-meters inference, the local-day boundary in
`tz` — or it becomes a second source of truth that silently disagrees. The
documented gate history shows small changes there move the ledger by
**1150–1550 Wh/day**. That is a decision about where the ledger's truth lives.

Build it with the `index_builder.py` pattern (after serving, never on the
startup path) and verify day-by-day against the live query first;
`scripts/ledger_gate_compare.py` is the precedent. Full measurement and
reasoning sit in the comment above `solar_energy_daily` in
`cloud/server/db.py`.

---

## 5. Alert canary

Open **by choice** — deferred on the noise tradeoff. A dead ntfy topic is only
discoverable when something real fires. Both paging paths currently report
armed, and the staleness path demonstrably works (it would have paged ~5 min
into the 2026-10-04 outage), so this is about proving the topic still
*delivers*, not whether the code fires.

---

## 6. `daily_summary` reports June

Reads `data/pack.csv`, which on the laptop is the June file, so it prints
`2026-06-29 [partial]` as the latest day. Downstream of items 2 and 3 — a data
problem, not a code defect. Resolves when the history question is settled.

---

## 7. "Power balance" demand side excludes the DC-bus load

Currently **disclosed rather than drawn** ("DC bus load not shown ⓘ"), on
purpose: the only per-row figure available would be battery discharge + solar
− inverter input, a difference across two meters known to sit ~33 W apart,
which is the method `dcLoadW()` exists to avoid. Drawing it would trade an
honest gap for a plausible wrong number.

Open only as a *feature*: if a per-row DC-bus measurement becomes available,
draw it. Do not synthesise it from the meter difference.
