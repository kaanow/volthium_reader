# Open items — as of 2026-10-05

Written at the end of the 2026-10-04/05 session. Everything here is either
**verified open** (with the evidence beside it) or **explicitly waiting on an
operator decision**. Items I closed in that session are listed at the bottom so
this file can be read as the whole picture rather than a fragment.

State at write time: local / Pi / Railway all at `1687d31`, clean tree, 1176
tests pass, 7/7 Pi services active, telemetry 0.1 min old with zero gaps in the
last 900 readings.

---

## P0 — ready to ship, verified, NOT yet installed

### 1. Install the weather fetch timer on the Pi

**Nothing on the Pi has ever fetched weather.** No service, no timer, no cron
entry. `data/weather.csv` is a git-tracked fixture frozen at its last row of
**2026-05-19** — 139 days stale at discovery.

Found by the staleness guard added the same day (`d2ff683`), which refused on
real data:

```
forecast is 3327.6 h old (limit 1.0 h) — refusing to advise.
```

Before that guard the advisor simulated 24 h of darkness and recommended
running the generator. That failure was **live since May**.

- Units are written and committed-ready: `deploy/pi/systemd/volthium-weather.service`
  and `.timer` (oneshot + 30 min timer, `UMask=0002`, `MemoryMax=80M`,
  `OOMScoreAdjust=500`, `Persistent=true`).
- A bounded one-shot fetch is **verified working from the Pi**: `T=9.4 °C,
  cloud=38%, irr=24.0 W/m², day_total=3713.9 Wh/m², sunrise 07:11` — the
  sunrise matching that morning's observed behaviour.
- Chose a timer over `weather.py --loop` deliberately: a long-lived process on
  a 1 GB Pi is memory-creep risk for no benefit when systemd already has a
  scheduler, and a timer self-recovers where a crashed loop stays dead.

**Until this is installed, my staleness guards permanently refuse** — the
generator advisor and the dashboard's sunrise projection stay dark. The guards
are correct; the input is missing.

Steps: `install -m 644` both units, `daemon-reload`, `enable --now` the timer,
confirm one fire writes a fresh row, then re-run `generator_advisor` and
confirm it produces a real recommendation instead of the refusal.

### 2. `docs/STATUS.md` claims a service that does not exist

Lines 59–60:

```
- **Weather**: `scripts/weather.py` looping every 30 min. Writes
  `data/weather.csv`.
```

False, and it is why nobody noticed for four months. Correct it when item 1
lands, so the doc describes the timer that actually exists.

---

## P1 — a footgun that already fired once

### 3. `git checkout -- data/` on the Pi destroys live telemetry

`.gitignore` documents that `data/` is **committed on purpose** ("so each
autonomous-loop push keeps the cabin's data"). But commit `47e60c7` (2026-06-30
16:43, "WIP: BLE event/health logging…") truncated `data/pack.csv` from 16,715
rows to **2,330** — the June file. Its committed size matches **byte-for-byte**
what appeared on the Pi at 20:16:43 on 2026-10-04.

So any command that restores tracked files from the index on the Pi —
`git checkout -- data/`, `git restore data/` — overwrites the live telemetry
spool with a four-month-old snapshot **and** re-arms the ownership trap (the
file comes back owned by whoever ran it, 0644, locking out the `claude`
services). That is what cost 70 minutes of telemetry and the Pi's Jul–Oct local
history.

I use `git checkout -- data/` routinely on the laptop to discard generated
files. The habit is safe there and destructive on the Pi.

- [ ] Finish the proof: append a row locally, run `git checkout -- data/`,
      confirm the row vanishes. (Bash was unavailable when I tried; the file
      sizes already match exactly.)
- [ ] Then pick a guard. Options, roughly in order of preference:
      - stop tracking the genuinely-live files (`pack.csv`, `weather.csv`, the
        `*_log.csv` set) and keep a seed/archive copy under a different name —
        cleanest, but changes the autonomous-loop convention in `.gitignore`,
        so it is a real decision rather than a tidy-up;
      - a `status_check` detector for `pack.csv` **losing rows or going
        backwards in time** — cheap, catches every mechanism including ones I
        have not thought of, and fits the existing "assert the property, don't
        trust the mechanism" pattern;
      - a documented hard rule plus never running the command over SSH.
- [ ] Whichever is chosen, the detector is worth having regardless: nothing
      currently notices that the primary spool shrank.

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
