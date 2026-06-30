# Reliability & Failure Modes — field log

Running log of failure modes seen in the live Volthium pipeline (BLE logger →
`data/pack.csv` → cloud uploader → Railway dashboard), written so the data we
already gather can drive a **more robust, self-improving system over time**.

Each entry is structured for that goal:

- **Signature** — how the failure shows up in data/logs we already collect, so
  it can be detected automatically.
- **Root cause** — what's actually happening.
- **Current mitigation** — what's in place today.
- **Instrumentation to add** — what we should start logging so this becomes
  *detectable and diagnosable from the data* next time.
- **Robustness ideas** — toward auto-recovery / graceful degradation.

First populated 2026-06-29/30 during the Linux/Pi (`kwpi`) bring-up.

---

## The data we currently gather (and where the gaps are)

| Source | Contains | Good for | Blind to |
|---|---|---|---|
| `data/pack.csv` (32-col) | per-cycle pack snapshot, ts, V/I/SOC/temp/cells/problem_code | trend/health analysis | **only written on a fully successful read** — failures leave no row, so outages are invisible *in the CSV itself* |
| `data/pack.log` / `journalctl -u volthium-logger` | human log incl. read failures + retry counts | spotting read failures | unstructured; no RSSI; no per-battery success/fail breakdown |
| `data/uploader.log` / `journalctl -u volthium-uploader` | POST results, accepted/dup counts | upload health | nothing about *why* the CSV stopped growing |
| dashboard "data is N minutes stale" banner | end-to-end staleness | the canary that actually caught the outage | doesn't say which stage failed |

**Key structural gap:** a failed read produces *no record in `pack.csv`*. The only
evidence an outage happened lives in the journal. The single most valuable change
for a self-improving system is a **structured health/event log** (one row per read
attempt, success or fail, per battery, with RSSI) — see "Cross-cutting" below.

---

## FM-1 — Service user can't write `data/` (logger crash on start)

- **Signature:** logger exits immediately; `PermissionError: [Errno 13] Permission
  denied: '.../data/pack.log'`. No CSV rows, no retry.
- **Root cause:** repo owned by `kaan`; `data/` was `0755` (not group-writable) and
  the service runs as `claude`. Opening `pack.log`/`pack.csv` for append failed.
- **Current mitigation:** `data/` made group-writable (`users`); services run as
  `claude` (see memory `run-as-claude-not-kaan`). systemd `User=claude` is fixed.
- **Instrumentation to add:** a pre-flight check in `log.py` that asserts the CSV
  dir is writable and logs a clear actionable error (and exits non-zero so systemd
  surfaces it) instead of a raw traceback.
- **Robustness ideas:** `systemd-tmpfiles` to own/permission `data/` at boot;
  `ReadWritePaths=` in the unit; fail fast with a one-line diagnosis.

## FM-2 — BlueZ allows only one discovery per adapter (concurrent scans)

- **Signature:** every read fails with `org.bluez.Error.InProgress` ("Operation
  already in progress"); deterministic, never succeeds. **Linux/BlueZ only.**
- **Root cause:** `read_pack` ran two `BleakScanner.find_device_by_address` scans
  concurrently via `asyncio.gather`. BlueZ permits one discovery session per
  adapter; the second always errors. CoreBluetooth (macOS, where this code first
  ran) tolerates concurrent discovery, so it was latent until the Pi.
- **Current mitigation:** fixed — `read_pack` now does ONE shared discovery
  (`_discover_addresses`) that resolves both MACs, then reads each device. See the
  fix commit on branch `fix/pi-bluez-and-uploader-rotation`.
- **Instrumentation to add:** count and log `InProgress` distinctly from "not
  found" so the two are separable in metrics.
- **Robustness ideas:** never run concurrent BLE discovery on one adapter; treat
  the adapter as a serialized resource with a single owner.

## FM-3 — Adapter wedged by a lingering GATT connection

- **Signature:** persistent `InProgress` even when only one reader runs; a
  power-cycle of the adapter shows a full GATT service tree being *deleted* for a
  device that should have been disconnected.
- **Root cause:** an interrupted/manual BLE read left a half-open GATT connection
  in BlueZ; the controller wouldn't start new operations cleanly.
- **Current mitigation:** `bluetoothctl power off/on` cleared it. `async with`
  context managers in the read path normally disconnect cleanly.
- **Instrumentation to add:** log `hcitool con` (HCI-level connections) and
  BlueZ connected-device count alongside read failures, so "stuck connection" is
  distinguishable from "device silent" in the data.
- **Robustness ideas:** an **escalating recovery ladder** in the logger after N
  consecutive failures: (1) stop/restart discovery, (2) `bluetoothctl remove`
  the device, (3) adapter power-cycle, (4) restart the BlueZ service. Record which
  rung fixed it — that data tells us which remedy matters.

## FM-4 — Uploader re-ingests header row after CSV rotation (inode reuse)

- **Signature:** failing unit test `test_rotation_resets_offset` (2 rows vs 1);
  in production, a bogus reading with `ts == "ts"` POSTed right after a rotation.
- **Root cause:** when the logger archives + recreates `pack.csv` (schema-drift
  rotation), the OS often **reuses the inode**. The inode-change check missed it,
  so the smaller-file *truncation* branch fired — but that branch preserved the
  stale cached header, which suppressed the offset-0 header-skip, so the new file's
  header line was parsed as a data row.
- **Current mitigation:** fixed — truncation branch now resets `header=None` like
  the rotation branch. Test passes.
- **Instrumentation to add:** uploader should log rotation/truncation events with
  old/new inode+size; reject any wire row whose `ts` doesn't parse as a timestamp
  (defense in depth) and count rejects.
- **Robustness ideas:** detect rotation by `(inode, size, first-line hash)` rather
  than inode alone; server-side schema validation rejects malformed `ts`.

## FM-5 — One battery drops out → the WHOLE pack read fails → logging halts ⚠️

*The most important one for robustness.*

- **Signature:** logger logs `RuntimeError: battery <MAC> not found in scan`
  repeatedly; `pack.csv` mtime stops advancing; uploader has nothing new to send;
  dashboard shows "data is N minutes stale." Observed 2026-06-30: battery B
  (0667) dropped at 23:51, logging halted entirely even though battery A (0533)
  was still readable.
- **Root cause:** `read_pack` is **atomic** — it requires *both* batteries in one
  scan and raises if either is missing, so a single battery's dropout discards the
  good battery's data too and writes **no row at all**. The outage is then
  invisible in `pack.csv` (no row = no evidence), only in the journal.
- **Current mitigation:** logger retries with backoff; `Restart=always`; recovers
  automatically when the missing battery returns. But **zero telemetry** is
  retained during the gap.
- **Instrumentation to add (high value):**
  - Write a `pack.csv` row **even on partial success**, with the present
    battery's data and the absent one's columns null + a `read_status` /
    `batteries_seen` field. Keeps half the telemetry and makes dropouts a
    first-class, queryable data point.
  - Per-battery success/fail + RSSI logged every cycle (structured health log).
- **Robustness ideas:** decouple the two batteries into independent read+state
  loops; treat the pack view as a join over the two latest per-battery readings
  rather than an all-or-nothing read. Alert when either battery is stale > T.

## FM-6 — Battery advertises, then goes silent with no holding connection (OPEN)

- **Signature:** a battery that read fine then **emits no BLE advertisements at
  all** in a 15–20 s scan, while `hcitool con` shows **no** connection holding it
  and BlueZ lists nothing connected. Observed: B (0667), strongest in the room at
  −74 dBm at session start, went fully silent ~1 cycle after its first
  connect-and-disconnect. Simultaneously A (0533) degraded −78 → −89 dBm.
- **Ruled out (by operator):** phone app connected (none), Pi/battery moved
  (didn't). Ruled out by data: lingering LE connection (none at HCI level).
- **Root cause:** **still open.** Candidates to disambiguate with data:
  - BMS-side: BLE module fault, or the BMS stops advertising for a cooldown after
    a central disconnects (would correlate dropout timing with our connects).
  - RF/coexistence: Pi onboard radio shares the 2.4 GHz antenna between Wi-Fi and
    BT; the uploader's continuous Wi-Fi POSTs could degrade BT RX sensitivity
    (A's RSSI decay is consistent, though B going *fully* silent is not purely a
    sensitivity story).
  - Environmental 2.4 GHz interference.
- **Instrumentation to add (to actually solve this):**
  - **RSSI + per-battery last-seen timestamp every cycle** — turns "B is gone"
    into a time series we can correlate against Wi-Fi/upload activity and against
    our own connect events.
  - Log each connect/disconnect with timestamps; if dropouts always follow a
    disconnect by ~constant delay → BMS cooldown. If they track Wi-Fi TX bursts →
    coexistence.
  - Periodically log adapter stats and Wi-Fi TX rate.
- **Robustness ideas (hypothesis-dependent):** if coexistence — pin BT/Wi-Fi
  coexistence params, throttle/space uploads, or move BLE to an external USB
  adapter on its own antenna. If BMS cooldown — lengthen scan windows and reduce
  connect frequency (read less often, or hold a connection). External USB BLE
  dongle is the highest-leverage hardware mitigation for both.

## FM-7 — End-to-end staleness detection (the canary that worked)

- **Signature (working as intended):** dashboard banner "data is ~6 minutes
  stale" — this is what surfaced FM-5/FM-6 to the operator.
- **Keep & extend:** make staleness a **structured, alerting** signal (push/email,
  not just a banner), with per-stage attribution: is the CSV stale (logger/BLE) or
  is the uploader stale (network/cloud)? The data to attribute it already exists
  (CSV mtime vs uploader last-success time vs cloud last-ts).

---

## Cross-cutting: what to build for a self-improving system

1. **Structured health/event log** (JSONL, e.g. `data/health.jsonl`), one record
   per read cycle: `ts, battery_a_seen, battery_b_seen, rssi_a, rssi_b,
   read_status, error_class, recovery_action`. This is the missing dataset that
   makes every failure above *measurable over time* and lets us A/B mitigations.
   `volthium/events.py` (`detect_events`) is a natural home/consumer.
2. **Partial-success logging** (FM-5): never discard a good battery because its
   sibling is absent.
3. **Per-battery RSSI time series** (FM-6): the single most useful new signal for
   the open dropout mystery and for predicting failures before they happen.
4. **Escalating BLE recovery ladder** with recorded outcomes (FM-3): learn which
   remedy actually fixes wedges.
5. **Staleness alerting with per-stage attribution** (FM-7).
6. **Defensive wire validation** (FM-4): reject malformed `ts`/rows server-side.

The throughline: today an outage erases its own evidence (no CSV row). Start
recording *attempts and their outcomes*, not just successes, and the system can
begin diagnosing and improving itself.

---

## Live incident log — 2026-06-30 (battery B / 0667 outage)

Ongoing monitoring run (goal: keep both batteries logging until 08:00, recover
issues, gather data).

- **~00:51 (prev session)** B (0667) stops advertising; logging halts (FM-5).
- **00:00–00:06** A-only; B absent across 10+ scans. Ruled out: phone app,
  movement (operator), lingering connection (`hcitool con` empty).
- **Recovery ladder attempted on B (all Pi-side levers):**
  - Adapter power-cycle (`bluetoothctl power off/on`): **A recovered −89→−79 dBm,
    B still absent.**
  - Full `systemctl restart bluetooth`: **A −80 dBm, B still absent.**
  - → Conclusion: **B's silence is source-side (BMS BLE), not the Pi adapter.**
    A recovers with adapter resets; B does not. No Pi-side action recovers B —
    it needs B's BMS to resume (likely a physical battery power-cycle).
- **RSSI samples (data/ble_health.jsonl):** A ranges −79..−89 dBm depending on
  adapter state; B: no advertisements at all. A's signal is also marginal/weak.
- **Built `scripts/ble_watchdog.py`** — staleness-triggered auto-recovery +
  per-battery RSSI health logging to `data/ble_health.jsonl`, single-adapter-safe
  (only scans while it has stopped the logger), escalating ladder with backoff.
  **Not installed as a service** (safety policy: a new privileged always-on
  daemon needs explicit operator approval). Runs on demand via
  `.venv/bin/python scripts/ble_watchdog.py --once`. Pending operator decision to
  install as `volthium-watchdog.service`.
- **Logger** keeps retrying every ~70 s (`Restart=always`) and will resume both-
  battery logging automatically the instant B re-advertises — this doubles as a
  zero-churn "is B back yet?" probe, so no need to thrash the BT stack overnight.

**Operator note:** battery B (0667) **cannot be physically power-cycled** (per
operator), so it stays down until its BMS BLE resumes on its own. Consider an
external USB BLE dongle: A's RSSI (−79..−89) is marginal and the onboard Pi radio
shares its antenna with Wi-Fi (the uploader's traffic).

### Resolution (00:30): partial logging deployed — FM-5 fixed

Since B can't be recovered and the goal requires data flowing to both the local
and remote dashboards, implemented **partial-success logging**:

- `volthium/pack.py::read_pack` no longer raises when one battery is absent — it
  reads whichever batteries are present and substitutes an all-None placeholder
  (`_missing_reading`) for the missing one. Raises only if BOTH are gone. The
  whole downstream path was already null-tolerant (PackReading properties,
  Estimator, uploader `_maybe_float`, wire `Optional`, cloud NULL/dash), so no
  other code — and crucially **not** the wire contract — had to change.
- `scripts/log.py` logs a `battery presence: A=up B=DOWN` transition line so
  dropouts/returns are visible in the journal.

**Result:** logging resumed at 00:30 with A-only rows (B columns blank,
`pack_i` = A's current since series, `pack_v`/`pack_p` blank). Verified flowing to
`pack.csv` → uploader (200 OK) → cloud `/api/latest` (fresh, B null) → local
dashboard `/api/latest.json` (fresh, B null). 312 main + 14 uploader tests pass.
When B's BMS eventually re-advertises, the logger resumes full both-battery rows
automatically (logs `A=up B=up`) with no intervention.

### Self-heal on wedge (00:39): logger exits → systemd respawns fresh

Added agent-free recovery for the adapter-wedge case (FM-3) that needs no
privilege escalation and no extra service: after `RESTART_AFTER_CONSEC_ERRORS`
(30) consecutive **total** read failures, `log.py` exits non-zero so its
`Restart=always` unit respawns it with a fresh BlueZ client — which clears
`org.bluez.Error.InProgress` wedges that a same-process retry cannot. Because
partial logging means a single-battery dropout no longer raises, this only fires
on a genuine both-batteries-down wedge, exactly where a fresh process helps; a
real RF blackout just restart-loops harmlessly until a battery returns. This is
the privilege-free subset of the `volthium-watchdog` ladder (adapter power-cycle
/ bluetooth restart still need the reviewed service).

### 00:41 — B re-addressing ruled out

Checked whether B's BMS had reset and come back under a *different* BLE address
(some BMS rotate addresses; the logger only looks for the fixed MAC). A 12 s
**name-based** scan for any `V-12V*` advertiser found **only** battery A
(0533, now −51 dBm — its link fully recovered). No second Volthium battery on
any address. So B (0667) is emitting nothing at all — conclusively source-side
(BMS BLE off), not a re-addressing or RF-sensitivity issue. All Pi-side levers
exhausted (adapter power-cycle, bluetooth restart, cache purge, fixed-MAC and
name-based scans). B can only return when its own BMS resumes; the logger probes
for it every cycle and will resume full logging automatically.
