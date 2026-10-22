# Open items — updated 2026-10-21

Everything here is either **verified open** (with the evidence beside it) or
**explicitly waiting on an operator decision**. Items closed in the
2026-10-04/05 session are listed at the bottom so this file reads as the whole
picture rather than a fragment.

State at write time: local / Pi all at `6f30a81`, clean tree, 1200 tests pass,
7/7 Pi services active, telemetry 0.1 min old with zero gaps in the last 900
readings, SOC 93/84, harvest steady at ~1.2 kWh/day for the past week.

Originally written 2026-10-05 at `1687d31`. P0 and P1's detector were closed
on 2026-10-21, and that work surfaced the brownout in P1.5 — which is now the
most important thing on the list.

---

## P0 — DONE 2026-10-21

1. ~~Install the weather fetch timer~~ **DONE.** `volthium-weather.timer` is
   installed, enabled, and firing every 30 min. First fetch wrote a live row
   (`T=7.4 °C, cloud 97%, 2702.8 Wh/m²`) and the file stayed `claude:users
   0664`. Also added to `deploy/pi/install.sh` — a hand-install would have
   vanished on the next rebuild, which `test_install_completeness` caught.
   That test had been RED since `7a0242b`; the "1176 tests pass" in that
   commit message came from a run made before it.
2. ~~`docs/STATUS.md` claims a service that does not exist~~ **DONE.** Now
   describes the real timer and records what it used to claim.

**Plus one that was not on the list and blocked everything:** the advisor was
not merely dark, it was CRASHING. `discharge_model.load()` died on the NUL
bytes (below), at a line that runs *before* the weather guard — so installing
the timer alone would have left it dead while I reported P0 done. Fixed in
`3fd91a7`: unparseable rows are skipped and counted, with a stderr report, and
`load()` raises only when nothing at all parsed.

Verified end to end on the Pi: skips 2 rows of 296,410, reaches the forecast,
and answers `no generator needed — projected low 70 % stays above the 25 %
comfort floor`, with `solar_source: tomorrow_forecast` (that branch only runs
on a fresh forecast, so it exercises the whole chain).

---

## P1 — detector DONE, the tracking decision still open

3. ~~Nothing notices the spool shrinking or corrupting~~ **DETECTOR DONE**
   (`10be24d`). `status_check --with-pi` now reports NUL bytes, calendar days
   missing between present dates, and days short of the 17,280-row cadence.
   One streaming pass, ~1.3 s over 77 MB. It immediately reported all three
   real faults.

4. **Still open: whether `data/` should be git-tracked at all.** The hazard is
   unchanged — the committed `pack.csv` is a June truncation, so any
   `git checkout/restore/reset` of `data/` on the Pi overwrites live telemetry
   and re-arms the ownership trap. Now more pressing: `pack.csv` is **77 MB
   and growing 4.8 MB/day** as a tracked file. Changing this touches the
   autonomous-loop convention documented in `.gitignore`, so it deserves its
   own decision.

---

## P1.5 — NEW, and it is the root cause: the Pi is browning out

**`vcgencmd get_throttled` returns `0x50000`** — bit 16 **under-voltage has
occurred**, bit 18 throttling has occurred. It read `0x0` on 2026-10-05, so
this is new.

The boot record shows **two unclean reboots on 2026-10-11**, at 07:55:05 and
09:32:34. Neither was the weekly timer (its last trigger is 2026-10-04
04:00:10). Both previous boots end mid-sentence in normal uploader output with
no shutdown sequence, and the current boot logged an ext4 journal recovery.
The cloud shows a matching 11.6-minute gap at 14:55Z→15:06Z.

That is a power problem at the cabin, and it is what wrote the NUL bytes:
buffered writes lost when the board lost power. The telemetry record itself is
intact in the cloud.

Open questions, none of them answerable from here:
- What is feeding the Pi, and did the supply sag or the source dip? SOC was
  57–65 % around 2026-10-05, the low point of a thin solar week.
- Is this recurring, or a one-off? The flags are "since boot", so all that is
  certain is that it happened in the last ten days.
- Worth a longer-term watch: nothing currently alerts on `get_throttled`
  changing, which is why a brownout ten days ago surfaced only by accident.

The two consequences are already contained — tools degrade instead of
crashing, and the detector reports the damage — but the cause is untouched.

---

## P2 — waiting on an operator decision

### 4. Restore the Pi's `pack.csv` history for Jul 1 → Oct 4

Lost by the above. **Railway is canonical and verified complete** across the
whole span (14 weekly probes, zero empty days), so nothing is permanently gone.

Not done unprompted because restoring means replacing the live file the
uploader tracks by inode, on a box that is unrecoverable if it wedges, with a
plausible re-upload storm. Cost of leaving it: the Pi's discharge model is
fitted on June data until history re-accumulates, which self-heals.

If wanted: build the reconstruction from Railway **on the laptop**, splice
during a window you are watching, and confirm the uploader's offset/inode
state survives.

### 5. Energy ledger scaling ceiling — approximately February 2027

Measured against production 2026-10-05 with 68 days of history:

| endpoint | time | rows |
|---|---|---|
| `/api/solar/energy?days=30` | 2.24 s | 31 |
| `/api/solar/energy?days=120` | 4.45 s | 68 |
| `/api/solar/energy?days=365` | 4.50 s | 68 (whole archive) |
| `/api/history/stats` | 3.69 s | — |

`days=120` and `days=365` agree because both already scan everything. So the
full-archive scan is at **4.5 s against a 10 s statement timeout**, and
straight-line on row count it crosses around 150 days of history. The failure
mode is an exception, not a slow page.

An index does **not** help — `solar_readings_source_ts_desc` already covers the
range predicate; the time goes on aggregating ~1.2 M rows. The fix is a per-day
rollup so the scan is O(days).

Deliberately not built: a rollup must reproduce `solar_energy_daily`'s
semantics exactly — the clamp-gated `GREATEST()`, the
difference-of-two-miscalibrated-meters inference, the local-day boundary in
`tz` — or it becomes a second source of truth that silently disagrees. The
documented gate history shows small changes there move the ledger by
**1150–1550 Wh/day**. That is a decision about where the ledger's truth lives.

Build it with the `index_builder.py` pattern (after serving, never on the
startup path) and verify day-by-day against the live query first;
`scripts/ledger_gate_compare.py` is the precedent for that comparison. Full
measurement and reasoning are in the comment above `solar_energy_daily` in
`cloud/server/db.py` (`1687d31`).

### 6. Alert canary

Still open **by choice** — previously deferred on the noise tradeoff. A dead
ntfy topic is only discoverable when something real fires. Worth revisiting
now that yesterday showed the staleness path does work (it would have paged
~5 min into the outage).

---

## P3 — lower severity, known

### 7. `daily_summary` reports June

Reads `data/pack.csv`, which on the laptop is the June file, so it prints
`2026-06-29 [partial]` as the latest day. Downstream of items 3 and 4 — a data
problem, not a code defect. Resolves when the history question is settled.

### 8. "Power balance" demand side excludes the DC-bus load

Currently **disclosed rather than drawn** ("DC bus load not shown ⓘ"), on
purpose: the only per-row figure available would be battery discharge + solar −
inverter input, a difference across two meters known to sit ~33 W apart, which
is the method `dcLoadW()` exists to avoid. Drawing it would trade an honest gap
for a plausible wrong number.

Open only as a *feature*: if a per-row DC-bus measurement ever becomes
available, draw it. Do not synthesise it from the meter difference.

---

## Closed in the 2026-10-04/05 session

Each measured before and after, each mutation-verified (every guard broken to
confirm a test failed). 1176 tests pass.

| | what it was |
|---|---|
| `6edadc0` | Stale weather **inverted** the SOC projection — rendered `100% in -52h` where truth was `-5% in 20h`, in the calm colour |
| `d2ff683` | Stale forecast recommended the generator across a 60–80% SOC band with 32–52 points of headroom |
| `1b66c4f` `4c4b8ba` `e779bf0` | The umask trap in three places + a detector, after it crash-looped the primary logger 593 times and left a 70.3-min hole. The detector immediately caught a fourth instance the fix itself created |
| `37dfe7c` | A day with **zero** telemetry archived as "Clean day", crediting a BLE link retired in July. An existing test asserted the defect |
| `2a9100d` | `Decoder` defined three methods **twice** each, byte-identical — editing the first copy would look exactly like a fix and do nothing |
| `5524690` | `node_dropout` could never fire for a node dead at startup; `_chg_sts` relabelled a real third bus node as the SW inverter |
| `e471833` | The latch guard — which **writes** to the device — could act on hours-old readings; `_record_trail` fabricated a 1 Hz record from one frozen value; the `dc_v` guard's stated rationale was factually false |
| `48300e3` | `latch_exposure` claimed a constant from n=1 (spread 0 **by construction**); `/v2/history` reported the query window as the archive's extent (31 vs 67 days) |
| `ad45b8a` | Battery row showed `-4.10 A` beside `+860.8 W` — 74 sign disagreements in 5000 readings; the same EMA was breaking the fridge split |
| `cf50e08` | A health threshold the pack has **never once met** (0 of 3 days), diagnosing cell imbalance daily; "CHARGING START" attributed a generator run to the sun |
| `1ba5bca` | A dead data source looked exactly like live telemetry; two more "cannot tell" branches rendered as "fine" |
| `0d0d013` | Strip chart backfill/live unified (live applied one battery reading to every row in a batch); DC-load omission disclosed; a test that could only fail at midnight — and did |
| `a742a1d` | Generator tile state depended on which row Postgres returned, on a documented same-second `gen_start`/`gen_stop` pair |
| `1687d31` | Recorded the ledger scaling measurement rather than guessing at a fix |

Three mutations passed everything on the first attempt and now have tests:
widening `MPPT_STALE_S` 240× to an hour, reverting one `LOG_PATH` default to a
def-time binding, and planting a duplicate method.

### Not an open item

`docs/what-to-distrust.md` no longer contains the "cabin AC load is
unmeasurable" premise that `wired-integration` flagged — checked 2026-10-05,
already corrected.
