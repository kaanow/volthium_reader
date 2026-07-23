# BT wedge causation — is the UB500 actually failing?

**Started:** 2026-07-16
**Status:** Phase 1 in flight
**Owner:** kaan + assistant

## The claim we're stress-testing

The kernel log says `Bluetooth: hci0: Resetting usb device` after HCI command
timeouts. The comfortable narrative is that the RTL8761B in the UB500 is
failing. Operator's skepticism: **we saw wedges on the on-board BCM chip too;
two independent radios exhibiting the "same" failure means the common factor
isn't the radio.**

That skepticism holds up:
- The BCM43438 (built-in) failed in a *different* mode — it never loaded
  firmware cleanly under the miniUART clock config on this Pi 3B. Not the
  same fault; we can't claim "both chips fail identically."
- The UB500 works cleanly for hours between wedges and recovers to full
  capability after every reset — inconsistent with a genuinely degrading IC.
- Wedges correlate with something in the workload, not with time-since-boot,
  temperature, or accumulated I/O.

**Honest read: the chip is a *victim* of the failure, not necessarily the
*cause*.** Investigation goal is to determine what's actually causing it.

## Hypothesis catalog

### Family A — the chip is *not* failing

| # | Hypothesis | Signature we'd expect |
|---|---|---|
| A1 | BlueZ state race (`stop scanning` while `start scanning` in flight) | Wedges cluster around bleak scanner start/stop operations; kernel HCI trace shows an out-of-order command sequence |
| A2 | BMS peer stops responding mid-transaction; our chip hangs waiting | Wedges preceded by an incomplete GATT read; only the BMS-facing HCI queue stalls |
| A3 | Pi 3B WiFi coexistence (WiFi TX burst saturates dongle front-end) | Wedges correlated with WiFi TX activity; internal BT chip (also on 2.4 GHz) wedges at similar times |
| A4 | Pi 3B USB controller (dwc2) bus glitch | Bus-level USB errors in dmesg; USB error counters climb independent of BlueZ activity |
| A5 | `btusb` kernel driver bug in the RTL path | Reproducible after specific HCI command sequences; documented upstream |

### Family B — *we* are putting the BMS in a locked state

| # | Hypothesis | Signature we'd expect |
|---|---|---|
| B1 | Leaked BleakClient (documented as FM-8) — BMS's one connection slot stays occupied through L2CAP timeout, so it can't advertise | BMS invisible to a *second* independent scanner during wedges; our teardown events show unclean disconnects preceding wedges |
| B2 | Reconnecting before BMS's post-disconnect settling window | Wedges cluster on cycles that follow rapid disconnect→connect; connect time longer than average |
| B3 | GATT MTU renegotiation crashing thin BMS firmware | HCI trace shows MTU exchange preceding hang |
| B4 | Two concurrent BLE centrals (our reader + someone's phone app) contending for the BMS's one slot | Adjacent BLE central visible in ambient scan; wedges timed with mobile-user activity |
| B5 | `keep_alive=True` extends the FM-8 leak window | Correlation between per-cycle connection duration and wedge onset |

### Family C — environmental

| # | Hypothesis | Signature |
|---|---|---|
| C1 | RF interference (external, non-WiFi) | Both radios silent simultaneously; correlated with time-of-day / other equipment cycling |
| C2 | BMS peer firmware bug (BMS wedges itself independently) | BMS silent to all observers even without our interaction |

## Phased plan

### Phase 1 — passive instrumentation, ship immediately

Three additions, all **passive** (nothing that changes reader workload,
nothing that could alter the failure pattern we're trying to measure):

1. **Ambient scanner on the internal BT (`hci1`)**
   - Runs a continuous BLE scan on the second adapter, filtered to our two
     battery MACs, emits an `ambient_advertising` event every ~10 s with
     per-battery visibility (adv packet count in the window, last RSSI,
     seconds since last seen)
   - Gated on new env var `VOLTHIUM_AMBIENT_ADAPTER`; unset = disabled
     (macOS dev rig and single-adapter Pis stay a no-op)
   - **Decisive because:** during a wedge on `hci0`, if `hci1` still sees
     beacons, the BMS is fine and the problem is on our side of the radio.
     If `hci1` also goes silent, the BMS itself is quiet — problem is peer
     or environmental. This one signal eliminates roughly half the
     hypothesis catalog per observed wedge.

2. **Enrich teardown events with a `disconnect_clean` bit**
   - We already log `disconnect_error`, `inner_disconnect_error`, `forced`,
     `still_connected` — add the boolean roll-up so a filter query answers
     "was this a clean disconnect?" without downstream logic having to
     reason about all four fields
   - Lets us test B1 by joining wedge onsets against the preceding cycles'
     `disconnect_clean` values

3. **USB counters in `stack_health` / `wedge_snapshot`**
   - Read `urbnum` and `authorized` from the UB500's `/sys/bus/usb/devices/`
     entry (found by VID:PID `2357:0604`) each snapshot
   - Reveals bus-level trouble independent of BlueZ (hypothesis A4)

None of the three introduces new BMS traffic. hci1 is already UP and idle
on this Pi so ambient scanning is free.

### Phase 1 exit criteria

Phase 1 is done when we've observed **at least 2-3 wedges** with
`ambient_advertising` data across them. Expected outcomes:

| Ambient shows during wedge | Interpretation | Next step |
|---|---|---|
| Both batteries still advertising at normal RSSI/rate | Reader-side problem (our chip / BlueZ / bleak / our code) | Phase 2A — btmon capture to see what HCI conversation is going wrong |
| Both batteries silent | Peer or environmental — BMS or RF | Phase 2B — WiFi timeline + adjacent-central scan |
| One battery silent, one visible | Per-BMS problem (independent from our stack) | Phase 2C — targeted per-BMS logging + timing analysis |
| hci1 wedges at the same time as hci0 | Common-mode RF or Pi-level fault | Phase 2D — RF spectrum analysis (physical hardware required) |

### Phase 2A — ambient-gated recovery ladder (shipped 2026-07-17)

Motivated by Iter 12: the recovery ladder ran through all four rungs
(L1 hciconfig reset → L2 bluetoothd restart → L3 USB replug → L4
process exit) trying to fix what the ambient scanner clearly showed
was a peer-side silence. Every rung after L1 was wasted motion and
each churned adapter state (adapter_pin_failed / adapter_restored /
another adapter_pin_failed …).

**The fix:** before firing anything past the cheap L1 rung, consult
`ambient_says_peers_silent()`. If both peers have been invisible to the
ambient scanner for more than 30 s, the wedge is peer-side or
environmental — the destructive rungs can't help. Skip and just keep
looping until peers return. L1 always fires (cheap, sometimes clears
real reader-side wedges; rules nothing out).

New event kind: `recovery_skipped` — emitted whenever the gate stops an
escalation. Includes `reason`, `scan_errors` count, and what would have
been done. Directly measurable "how much wasted motion did we prevent."

New classification: `peer_silent_ambient_corroborated` — takes
precedence over any dmesg-derived label. Any wedge_snapshot with this
classification means "not our stack, not the chip, and not something
recovery can fix."

Two invariants preserved:
- The reader still logs and snapshots the wedge — we just don't act on
  it destructively. Analysis still gets the full evidence trail.
- If ambient is unavailable (`None` return), we fall back to the
  legacy escalation — the gate never worsens behavior versus pre-2A.

### Experiment: single-adapter operation (2026-07-17T14:21:15Z / 07:21 PDT)

Between 2026-07-17T02:26Z and 14:20Z we observed 8 wedges, all Family B
or peer-context. 4 fired within 22 s of `ambient_scanner_started`; 2
more fired during long peer-silent stretches. All had the same
underlying signature: `[org.bluez.Error.InProgress]` on hci0's next
scan. Hypothesis: **BlueZ's per-adapter discovery state machine wedges
when stressed, and running two concurrent discovery sessions is a
strong stressor.** Ambient scanner startup is one demonstrated trigger.

To test how much of the observed wedge rate is caused by our own
dual-adapter operation, we disabled the ambient scanner at
2026-07-17T14:21:15Z. Only the primary adapter (UB500 / hci0) is
scanning; the internal chip (hci1) is powered down as it would be
without instrumentation.

Reversion: uncomment `VOLTHIUM_AMBIENT_ADAPTER=…` in
`/etc/systemd/system/volthium-logger.service.d/10-reader-env.conf`
(currently prefixed with `#EXPERIMENT-2026-07-17`).

Immediate baseline: 2 min post-restart, 0 wedges. Historical rate for
this time window with ambient enabled was 4/4 InProgress wedges within
22 s. The next 12-24 h will tell us:

- If wedge rate drops significantly → dual-adapter operation is a
  material contributor; the permanent answer is burst-mode ambient or
  event-triggered ambient (Phase 2B option) rather than continuous.
- If wedge rate is similar → our operation isn't the primary cause;
  the InProgress wedges have other stressors we haven't found and the
  ambient-scanner startup timing was coincidence + rare per-restart
  wedges. Turn ambient back on and dig further.
- Peer-side dormancies will continue independently — those aren't
  affected by which adapter we're running.

Cost during experiment: we lose the `peer_silent_ambient_corroborated`
classification. New peer-silent wedges will fall back to the reason-
string signals (`InProgress`, `TimeoutError`) and be classified as
`bluez_discovery_state_stuck` or `bms_peer_not_responding`.

**Checkpoint 2026-07-17T17:50Z (~3.5 h in):** zero InProgress wedges,
including through the experiment-start restart itself (previous 4
restarts all wedged within 22 s). One wedge of a different class at
17:03:49Z (`adapter_rx_deaf`, see observation log) — not an InProgress
event, so the primary metric is still clean.

### Phase 2B — burst-mode ambient (built 2026-07-17, ✅ DEPLOYED 2026-07-19T03:51Z)

**DEPLOYED 2026-07-19T03:51Z.** Single-adapter experiment concluded (≥24 h,
0 InProgress wedges vs ~8 expected — dual-adapter operation confirmed as
the InProgress cause). Pi pulled to current `main`; set
`VOLTHIUM_AMBIENT_MODE=burst` + re-enabled `VOLTHIUM_AMBIENT_ADAPTER` in
the logger drop-in; restarted. **Validation on the restart itself:** emitted
`ambient_scanner_unavailable: mode=burst` (continuous scan correctly
disabled), NO `ambient_scanner_started`, and **NO InProgress wedge** — where
all prior continuous-ambient restarts wedged within ~22 s. B flashed a
momentary FM-8 leaked-link on restart that self-cleared in 9 s; both
batteries reading, no `wedge_snapshot`/`recovery_skipped`. First live
`ambient_burst` will fire on the next wedge/recovery decision. Deploy note:
the Pi checkout has mixed ownership (`claude` owns code, `kaan` owns root/
`data`), so pulls must run as root — flagged as deploy-hygiene debt.



Ambient as an on-demand instrument instead of an always-on second radio
(operator-proposed; converges with the "burst-mode ambient" option above).
`VOLTHIUM_AMBIENT_MODE=burst` keeps hci1 powered down; the reader brings
it up for one ~12 s scan (`ambient_burst_check`) only when a recovery
decision needs the peers-or-us verdict, then powers it back down. Burst
points: L1 wedge snapshot (informational — L1 stays unconditional),
L2/L3/L4 escalation gates (verdict can skip the rung), and the
consecutive-total-read-failure snapshot. Emits one `ambient_burst` event
per burst.

Design properties:

- **Verdict discrimination**: heard a target → peers NOT silent (False);
  heard only neighbor devices → radio provably works, peers silent
  (True); dead air → inconclusive (None, mirrors FM-11 rx-deaf logic).
- **Timing caveat**: a burst samples ~15 s after wedge onset — short peer
  dormancies can end before the burst starts, so False verdicts are
  weaker than continuous ambient's; True verdicts remain decisive.
- **Self-stressor accounting**: bursts run a discovery session on hci1 —
  the demonstrated cross-adapter InProgress trigger. Wedge snapshots now
  carry `recent_burst_age_s` + `ambient_mode`; wedges within ~60 s of a
  burst are tallied separately from the steady-state rate. 60 s cooldown
  between real bursts (cached verdict in between) stops a stuck recovery
  loop from bursting every cycle.

Deployment plan: after the single-adapter experiment concludes, set
`VOLTHIUM_AMBIENT_MODE=burst` and re-enable `VOLTHIUM_AMBIENT_ADAPTER`
in the systemd drop-in. This is the likely permanent configuration if
the experiment confirms dual-adapter operation as a wedge contributor.

### Phase 2B+ — held for now

Only if Phase 2A doesn't resolve the picture:

- **`btmon` ring-buffer capture** — kernel HCI trace, dump last N seconds on
  wedge. Big instrumentation with verbose output; worth it only after Phase 1
  narrows to "something in the HCI conversation is weird."
- **WiFi TX activity timeline** — `/proc/net/wireless` sampled every ~5 s;
  correlate with wedge timing. Useful specifically for A3.
- **Adjacent-central scan** — one-shot BlueZ scan for other BLE centrals
  connected to the batteries; catches B4.
- **Connection lifetime histograms** — instrument `_read_device` to emit
  per-phase timings (connect, first notify, last notify, disconnect).
  Answers B2, B5.

**Explicitly NOT considered even for Phase 2:** active BMS pings (e.g.
querying version after each real-time data read to test if BMS is alive).
That changes the workload we're trying to measure — if our workload is
what puts the BMS in a bad state, adding queries can only make it worse
or muddy the picture.

## Interpreting `ambient_advertising`

**Important gotcha discovered 2026-07-16 iter 4:** `adv_packets=0` on
the ambient scanner is NOT by itself the wedge payoff signal — it fires
on every reader connect cycle, because when hci0 has an open GATT
connection to a battery, that battery stops advertising (standard BLE
peripheral behavior). Observed live at 21:05-21:06: both batteries had
overlapping adv=0 windows on hci1 during a 33 s stretch where hci0's
own `scan_result` events also gapped out — i.e. hci0 was mid-read, not
wedged.

The right diagnostic question is: **when hci0's scan itself fails
(wedge or discovery timeout), does the ambient scanner *still see the
batteries advertising in that exact window*?** That's the split
between "our chip/BlueZ failed to see beacons that were there"
(Family B) and "batteries genuinely stopped transmitting"
(Family A2 / peer or Family C / environmental).

Filter accordingly when reading the observation log: entries below
tie each wedge to the specific ambient window(s) that straddle it, not
to per-cycle adv=0 counts.

## Observation log

<!-- Append entries below as wedges are observed with ambient data available. -->

| Wedge onset (UTC) | `ambient_advertising` says | Interpretation | Notes |
|---|---|---|---|
| 2026-07-16T19:38:52Z (L1, `kernel_usb_reset_chip_hung`) | Both batteries visible on hci1 straddling the wedge: B `adv_packets=3` @ 19:38:50, A `adv_packets=1` @ 19:38:50; both jump to 5-8 packets/window immediately after. Neither battery ever showed `adv_packets=0` around the wedge | **Leans Family B / against chip-failure narrative** — the batteries were still transmitting beacons at normal cadence throughout the wedge; hci0's scan came up empty anyway. Rules out "BMS went silent" and "environmental blackout." | Wedge fired 22 s after `ambient_scanner_started` — startup transient can't be fully ruled out. Need 1-2 more observations. Also: RSSI dropped to -127 (sentinel = "unknown") after 19:39:00 on hci1 while packets kept flowing; possible bleak/BlueZ RSSI-reporting quirk on this adapter, not a signal-quality issue |
| 2026-07-16T21:34:42Z (partial cycle, not a wedge — A `TimeoutError` on connect; B `read_ok`) | Ambient windows 21:34:22 and 21:34:52 healthy on both batteries (~5-7 packets each). The 21:34:42 window: **both adv=0, age_s=15.4 — neither battery seen from 21:34:27 → 21:34:42** | **Different pattern from Iter 1** — ambient corroborates hci0's silence rather than contradicting it. Consistent with Family A2 (BMS peer not responding) or Family C (environmental RF hit affecting both radios). Two independent BMS dormancies overlapping by ~15 s at random would be very unlikely, suggesting either coordinated silence or a shared cause | Not a `wedge_snapshot`-triggering event — logged as a `read_fail` + `partial` cycle_done. Reader recovered on next cycle. Worth watching for the pattern: partial cycles concurrent with both-silent ambient windows might indicate a class of failure separate from the hci0-scan-wedge class |
| 2026-07-16T23:54-23:57Z (5 consecutive partial cycles, `a_read=False`; 88 s CSV gap; not a wedge) | Ambient shows **battery A silent on hci1 for ~3.5 min** — `age_s` grew monotonically 16.4 → 206.4 s (23:54:25 → 23:57:35). Then A came back cleanly (23:57:45: adv=3, age=0.8 s). B advertised normally throughout except a couple of brief 10 s dips | **Definitively Family A2 — BMS peer dormancy.** A stopped transmitting on RF; both independent radios confirm the silence; A came back on its own without any recovery action. Matches the FM-6 quiet-bus pattern previously documented on B, but this time on A. Not our stack, not the chip | Reader was well-behaved: 5 partial cycles logged with A missing, retries with exponential backoff produced the 88 s CSV gap, but no wedge_snapshot fired and no service restart needed. This class of failure is already handled correctly by existing partial-row + 15-min battery-silent-alert logic (3.5 min is below the alert threshold — right call) |
| 2026-07-17T01:14:15-01:20:00Z (full L1→L4 recovery cascade including USB replug; 6 min CSV gap) | **BOTH batteries silent on hci1 for the entire 6-minute window** — age_s grew monotonically A: 10 → 311 s, B: 10 → 331 s. Then both back simultaneously. Ambient scanner itself stayed healthy (kept emitting events). Reader's hci0 also went blind (adapter_pin_failed at 01:14:45, four wedge_snapshot events L1-L4, adapter_restored 01:17:07, another L4 at 01:19:38) | **Family C (environmental) or coordinated Family A2** — the most parsimonious reads for two independent radios simultaneously losing sight of two independent BMSes for 6 minutes are either (a) an RF blast covering the whole 2.4 GHz band around the cabin or (b) some shared upstream event that pushed both BMSes to stop advertising. Pack was completely IDLE (0 A, 0 W) throughout with rock-steady voltages A=13.66 V / B=13.34 V — no electrical event on the DC bus. NOT chip failure (both radios agreed), NOT Family B (hci1 saw the same silence hci0 did), NOT single-BMS dormancy (both silenced together) | **The recovery ladder ran through all four rungs trying to fix a problem that wasn't reader-side.** If ambient corroborates peer silence, escalating recovery is at best wasted motion and at worst destabilizes the reader. Strong argument for a Phase-2 change: use the ambient scanner as a "should I recover?" gate — if ambient says batteries are silent too, wait rather than escalate |
| 2026-07-17T02:30:49Z (L1 only; `reason: BleakDBusError [org.bluez.Error.InProgress]`) | Ambient scanner freshly running (started 14 s earlier after retry-with-reset). Wedge snapshot carried the new Phase 2A fields: `ambient_peers_silent: False`, `ambient_peer_ages_s: {A: 0.9 s, B: 4.2 s}` — hci1 was watching both batteries advertise normally at the moment hci0 hit `InProgress` | **Family B, root cause named: stale BlueZ discovery session on hci0.** `[org.bluez.Error.InProgress]` = bluetoothd already had a discovery going, `StartDiscovery` was refused. Not chip, not peer, not environmental — a specific bug in BlueZ's per-adapter session state machine (`_AdapterManager` and cascading scans leave bluetoothd's Discovering flag stuck). Recovery Level 1 (`hciconfig hci0 reset`) cleared it | **Phase 2A worked as designed** for the diagnostic side: `ambient_peers_silent: False` immediately falsified the Family C/A2 hypothesis for this event. The `recovery_skipped` events did NOT fire (correctly — this was actually a reader-side wedge that L1 could fix). But two mislabels worth noting: (1) classification came back `kernel_usb_reset_chip_hung` because dmesg has stale USB reset lines from the ambient scanner's own `hciconfig hci1 reset` retry — the dmesg-based classifier needs to filter by adapter. (2) Second data point of wedge-immediately-following-ambient-startup (Iter 1 was 22 s, this is 14 s) — could be coincidence, could be that concurrent discovery sessions on hci0 + hci1 stress bluetoothd's state machine. Watch for a third |
| 2026-07-17T04:42:58Z + 04:45:42Z (two L1 back-to-back; both `bluez_discovery_state_stuck`; both `ambient_peers_silent: False`) | Ambient scanner started 04:42:44 → wedge 14 s later. Ambient scanner started 04:45:25 → wedge 17 s later. Both wedges immediately followed logger restarts (deploys of ddc091f dmesg fix + ade480f WiFi telemetry). WiFi metrics clean at wedge time: retries=0, missed_beacon=0, link_quality=70 | **Ambient-scanner-startup → hci0 InProgress correlation is now a real pattern.** 3rd and 4th data points on the "wedge fires 14-22 s after ambient_scanner_started" observation. Root cause hypothesis for Family B InProgress subtype: **starting a discovery session on hci1 while hci0 already has one running triggers a bluetoothd cross-adapter state race that leaves hci0's Discovering flag stuck**. If confirmed, our Phase 1 instrumentation is causing the very wedges it's built to observe. | **Both wedges classified correctly** thanks to the dmesg time-bound fix — no more `kernel_usb_reset_chip_hung` mislabels. WiFi telemetry confirms not RF-related. Recovery ran only at L1; Phase 2A gate correctly didn't fire (ambient shows peers visible, so escalation wasn't needed and it didn't try). **Test now underway:** don't restart the logger for the next several hours and see if InProgress wedges stop. If the rate falls to zero over a many-hour stretch without restarts, the hypothesis is confirmed |
| 2026-07-17T09:21:41Z (L1; `peer_silent_ambient_corroborated`; `reason: BleakDBusError [InProgress]`) | Same InProgress reason as ambient-startup wedges — but this one fired ~4.5 hours into steady-state operation with no ambient scanner restart. Context: B had been silent for ~50 min (age 2999 s), A had just gone silent ~40 s earlier. Ambient windows show A dipped 09:21:00 → 09:21:50 while B stayed silent throughout. `ambient_peers_silent: True` → classifier correctly upgraded to `peer_silent_ambient_corroborated` | **Hypothesis refinement:** the InProgress mechanism isn't uniquely caused by ambient-startup. Extended peer silence ALSO triggers `[org.bluez.Error.InProgress]` on hci0. Best current mental model: **BlueZ's discovery-session state machine gets stuck whenever it's stressed** — whether by concurrent discovery on hci1 or by long unanswered scan sessions on hci0. `hciconfig hci0 reset` (L1) clears both. First ambient-startup hypothesis still stands for THAT trigger class, but the ROOT-cause mechanism generalizes | **Phase 2A working correctly**: this event is the first live use of the `peer_silent_ambient_corroborated` classification — the classifier picked it up from `ambient_peers_silent: True` and prioritized that over the InProgress reason. L1 still fires (unconditionally), which is correct here — the `hciconfig hci0 reset` is exactly what clears the stuck flag. No `recovery_skipped` event because L2+ was never reached. **Meanwhile: 5 h steady-state without ambient restarts produced only this one wedge**, vs 3 wedges in the preceding ~5 h with 2 restarts — hypothesis still leans strongly toward ambient-startup being A trigger (not the only one) |
| 2026-07-17T13:20:14Z (L1; `peer_silent_ambient_corroborated`; `reason: BleakDBusError [InProgress]`) | End of B's ~4h 48min dormancy (started 08:32Z). Wedge fired 34 s after A ALSO went briefly silent (both silent 13:19:46 → 13:20:17), then **both batteries came back together at 13:20:27** — 13 s after the wedge. Both to full adv rate within 40 s | **Peer-stress InProgress mechanism reconfirmed** (2nd of this subtype). Same reason string, same class. **New signal: coordinated recovery.** Both batteries returned in the SAME 10 s ambient window after A had just briefly joined B's silence. Second time we've seen batteries recover exactly together (Iter 12 was the first). Coincidence for 2 independent BMSes coming back within one window is unlikely; leans toward the pack's shared electrical bus (or a shared periodic wake) synchronizing them | Reinforces the Iter 12 read that "long both-silent" events may be coordinated rather than truly independent. Still not chip, still not our stack. Existing alerting handled the B dormancy correctly at start/end. Steady-state test now at ~8.5 h without ambient restart → 2 wedges total, both peer-context. **The signal is quite clean: with our instrumentation stable, wedges happen only in peer-stress windows — a strong argument that most of our historical wedges also had non-reader triggers we couldn't see** |
| 2026-07-18T07:22:47Z→ongoing (**battery A BLE dormancy ≥6 h 24 min, DURING DISCHARGE — EXCEEDS PRECEDENT**; crossed 15-min alert; NOT a wedge) | n/a — ambient OFF. **B read cleanly on hci0 the entire time** (SOC 64%→44%, discharging, v_b 13.09 V) while **A stayed fully null** from 07:23:12Z through ≥13:47Z. Live BlueZ probe at 09:47Z: **A absent from the bluez object list entirely** (not connected, not cached), B present at RSSI -76, hci0 UP with 0 errors, zero active LE connections | **Family A2, confirmed peer-side — but now the longest on record.** Prior max was the 2026-07-17 **B dormancy of ~4 h 48 min**; A has now blown past it (≥6.4 h and counting) and shows no sign of self-recovery. The "it'll come back on its own like the others" assumption has broken. A absent from bluez *rules out* a leaked/stale connection (FM-8 shows `Connected: yes`); A simply isn't advertising. **Electrical safety from topology:** series pack → identical current; B actively discharging ⇒ current flows through A ⇒ A's discharge FET closed ⇒ A conducting normally. **A's BMS works electrically; only its BLE radio is dormant** — battery safe, just invisible | **Reader correct**: partial rows preserve B, no false wedge, no recovery churn. No reader-side lever exists while A isn't advertising (a fresh BlueZ client / logger restart still won't find a non-advertising peer, and would interrupt B's good telemetry). **Escalation options for operator wake:** (1) **physical** — power-cycle / wake A's BMS at the cabin (only guaranteed fix for a hung BMS-BLE); (2) **end the now-conclusive single-adapter experiment** (23 h, 0 InProgress wedges) and deploy burst-mode → gives hci1 back for a **directed-connect probe of A** (some BMSes drop advertising but still accept directed connections). (3) Strategic: this is the **strongest case yet for the wired RS-485/CAN path** — BLE is the fragile leg. **Watch A/B SOC imbalance** (A ~100% vs B now 44%) once A returns. **UPDATE 13:52Z — DEFINITIVE two-radio confirmation:** brought up hci1 (internal BCM43438) for an isolated 20 s scan while ambient stayed off otherwise. Result: **A=0 adv packets, B=5 packets @ RSSI -71.** Two independent radios on different silicon (UB500/hci0 + internal/hci1) BOTH hear B fine and BOTH hear zero from A → **A's BMS has genuinely stopped BLE advertising; conclusively peer-side, not any adapter/reader fault.** Corollary: a directed connect is futile (can't connect to a non-advertising peripheral), so **no remote software fix exists — physical BMS wake is the only recovery.** hci0 stayed UP/healthy through the probe (no InProgress wedge from the one-off hci1 scan). This is the indisputable root cause for this event class: **BMS-side BLE hang** |
| 2026-07-19 (**historical confirmation — 4/4 B dormancies triggered by our read-timeout AT onset**) | Went back through Railway history. `event=read_exception` filter returns the full read-failure history: **3262 read-timeouts back to 2026-07-01** (all `TimeoutError`, all exactly 15.0 s = full `_READ_TIMEOUT` — every failed read is a complete hang, never a fast/connect failure). Cross-referenced against distinct ≥60 s dormancy episodes in the ~40 h readings window: **B 06:30 (452 min), B 16:52 (128 min), B 22:48 (49 min), B 19:05 (48 min) — all four have a B read-timeout at the exact onset (0–1 s offset).** The lone A episode (07:23, 524 min / 8 h 44 m) had NO timeout at onset (nearest 54 min prior) — either a genuine spontaneous peer event or a logging gap | **The read-timeout → dormancy mechanism is confirmed historically, not just for one onset.** 4/4 lasting B dormancies are triggered by our own read hanging out. Base rate the other way: only ~13 % of read-timeouts (≈4/30 in-window) cause a lasting dormancy — the battery usually shrugs it off — and since every timeout is an identical 15 s hang, no logged read feature predicts which wedges. The A 8 h 44 m outlier is the one case not fitting the pattern; worth classifying with the new instrumentation | **This is the strongest reframe of the whole investigation: the dormancies I earlier called "definitively peer-side, nothing we can do" are, at least for B, triggered by our reader.** The connection-state-at-timeout instrumentation (deployed 23:31Z) targets the open question — is the peer half-open at the timeout instant. Reads hanging the full 15 s (never failing fast) strongly implies the connection WAS established and the GATT read hung → abrupt cancel → half-open risk on every one. Next fix candidates: real disconnect on timeout; graceful close before cancel; and investigate why reads hang at all (normal read is 1–3 s) |
| 2026-07-19T22:48:19Z (**dormancy onset MECHANISM found — triggered by our read TimeoutError**) | Reconstructed B's full per-cycle event trail across the onset from retained Railway events (scan_result/read_ok/teardown/read_exception). B read cleanly every ~9 s (READ_OK soc=80, clean ~2 s teardown, scan seen=True @ RSSI −74 to −78) for 8+ min straight — **RSSI steady, no fade** — then at 22:48:19 a **read hit TimeoutError**, teardown returned in 0.03 s, and B went `seen=False` within 20 s and stayed dark 30 min+ | **Dormancy is NOT a spontaneous BMS hang — it is triggered by our own failed read cycle.** The clean-RSSI cut (not a fade) rules out link-budget; the onset rides on OUR TimeoutError. Mechanism hypothesis: `keep_alive=True` means we own teardown; when a read times out, the abrupt asyncio cancellation can leave the peer **half-open** (our HCI side drops, the BMS still thinks it's connected → a connected peripheral does not advertise → dark until B's stack gives up). **Refined by data:** 5 read-timeouts in the retained 4.5 h (A×3, B×2), but only 1 → dormancy, and all 5 teardowns were identical (~0.01 s no-op, forced=False, still_conn=False). So the timeout is the TRIGGER but not sufficient — B's firmware wedges on it only sometimes. Joint cause: our abrupt teardown + occasional BMS mishandling. **This reframes every prior "peer-side, nothing we can do" dormancy** (incl. A's 8 h 44 m) — those may all have been triggered by our timed-out reads | **Instrumented + deployed 2026-07-19T23:31Z:** `read_exception` now captures `client_connected` (bleak's view) and `hci_connected` (controller view) AT the failure instant — the missing half-open discriminator (the teardown's later hcitool check reads "not connected" by then and hid it). Next timeout-triggered onset will show whether B was still connected when the read timed out. **Data-collection first, fix second** (deliberately not changing teardown behavior until the mechanism is confirmed — same discipline that avoided a wrong call on FM-9). Candidate fixes once confirmed: force a real disconnect on timeout, or graceful-close before the hard cancel, to stop leaving B half-open. Also worth: WHY do reads time out at all (reads normally 1-3 s)? |
| 2026-07-18T16:07:31Z (**battery A RECOVERED after 8 h 44 min** — record dormancy self-clears; then **B hands off into dormancy** at 16:52Z) | n/a — ambient OFF (but see the 13:52Z two-radio probe that confirmed A silent). A returned at 59% SOC / 13.12 V, with two brief re-flickers (16:19Z, 16:41Z null-then-back) before stabilizing. **B went null at 16:52:15Z** with A reading fine on hci0 → same peer-side signature, now on B. By 17:47Z the pack had switched to **charging** (solar midday): A climbing 59→63 %, discharge concern over | **CORRECTION to the prior row's "physical wake is the only recovery":** A's 8 h 44 min hang **cleared on its own — operator confirmed nobody touched the batteries.** So BMS-BLE hangs self-recover *unaided* across a wide range (3.5 min → 8.7 h confirmed); a physical wake would only *shorten* an outage, it isn't required. **No remote-wake or physical-wake feature is strictly necessary** — the battery stays safe and telemetry returns by itself. The alternating A↔B handoff pattern continues (rarely both dark at once). Possible trigger correlation worth watching: A's recovery and B's onset both sit near the discharge→charge transition — BMSes often (re)start advertising on a state change | **Reader behaved correctly throughout** the whole 8.7 h: partial rows kept B (then A) flowing, no false wedge, no recovery churn, alerts fired/cleared at the 15-min boundary. The self-recovery **lowers the urgency of any remote-wake feature** — the battery is safe and telemetry returns by itself. Still: burst-mode (for rx_deaf + permanent InProgress fix) and the wired RS-485/CAN path (to sidestep BMS-BLE entirely) remain the two forward bets. **Watch the A/B SOC readings on charge** — A returned at 59 % vs B 40 %, a ~19-pt gap worth confirming isn't a real imbalance |
| 2026-07-18T05:01:48Z (L1; `adapter_rx_deaf`; **2nd of this class**, 104 s gap) | n/a — ambient OFF. Near-identical to the 2026-07-17T17:03Z rx_deaf: hci0 UP, **0 HCI errors**, `Discovering: no`, empty dmesg, ub500 present, temp 63 °C, no USB reset. Scan completed clean but heard **zero adv from ANY device** (not just our batteries). L1 `hciconfig reset` cleared it | **FM-11 deaf-receiver is the residual failure mode.** With InProgress (dual-adapter) eliminated by the experiment and USB resets (autosuspend) fixed at 03:53Z, this is what's left: ~twice in 12 h, ~100 s each, always L1-cleared. That the scan hears NOTHING neighborhood-wide (not just peers) argues receiver-side deafness over a coincidental all-peer silence — but single-adapter can't prove it | **This is exactly the ambiguous case burst-mode ambient resolves**: a burst on hci1 during the deaf window would show whether hci1 hears the neighborhood (→ hci0 genuinely deaf, FM-11 confirmed) or also hears nothing (→ real RF blackout). Strong argument for deploying burst-mode once the single-adapter experiment closes. Low urgency: L1 already fixes it in ~100 s with no cascade |
| 2026-07-18T03:17:58–03:23:48Z (**2nd UB500 kernel USB reset in ~70 min**; full L1→L4 cascade; 350 s outage; 2nd stale-push alert) — **ROOT CAUSE FOUND** | n/a — ambient OFF. Same dwc2 signature (`hci: urb failed to resubmit (2)` → `usb 1-1.5: reset full-speed USB device using dwc2` → re-enumerate). `journalctl -kb`: **6 of these resets since the 2026-07-15 boot** (Jul 16 07:56, 10:49, 10:56, 18:14; Jul 17 19:09, 20:18) — irregular, cluster-prone (two within 7 min once; two within 70 min here; a 25 h clean gap between). throttled=0x0 on all, temp 63–68 °C | **The autosuspend-disable protection was silently OFF.** Live sysfs at incident time: `power/control=auto` (should be `on`), device autosuspended ~3.6 % of the time. There IS a udev rule to disable autosuspend (installed after the 2026-07-12 FM-9 hang — the SAME root cause), but it fires only on `ACTION=="add"`. **A dwc2 reset-in-place does not re-fire add**, so after the first reset `power/control` reverts to `auto`, autosuspend returns, and the 2 s idle timer racing the 5 s scan cadence re-arms the exact suspend/resume-vs-scan-enable race that hangs the RTL8761B → next reset → protection still off → cascade. This is why resets cluster and why the "new" UB500 shows the same hang we blamed on the old onboard chip: **neither chip is faulty — autosuspend was never actually staying disabled.** throttled=0x0 exonerates SoC power; the fault is USB power-management policy, not the radio and not the 5 V rail | **FIX SHIPPED 2026-07-18T03:53Z (no reboot, non-disruptive):** (1) runtime `echo on > …1-1.5/power/control` — stopped it immediately; (2) `volthium-usb-keepawake.timer` (systemd, every 30 s) re-asserts `power/control=on` for VID 2357:0604 whenever it drifts, so a reset can't leave autosuspend on for more than 30 s — breaks the cascade without touching the logger or the single-adapter experiment. Repo: `deploy/pi/bin/volthium-usb-keepawake.sh` + `.service`/`.timer`, wired into `install.sh`; udev rule comment updated with the ADD-only limitation. **Test:** watch for zero `reset full-speed USB device` in `journalctl -kb` from 03:53Z onward. If clean for 24 h+, FM-9 is definitively closed. **✅ CLOSED 2026-07-19T03:42Z — 24 h elapsed, 0 resets** (vs the prior ~6-in-2-days rate). `control=on` held throughout, keepawake timer active. FM-9 (UB500 USB-reset chip-hang) resolved by the autosuspend-revert fix |
| 2026-07-18T02:09:43–02:15:09Z (**UB500 kernel USB reset**; full L1→L4 cascade; 339 s / 5.6 min outage; the stale-push alert) | n/a — ambient OFF. dmesg is decisive: `hci0: urb … failed to resubmit (2)` → `Unable to disable scanning: -2` → **`usb 1-1.5: reset full-speed USB device number 4 using dwc2`** → dongle re-enumerated hci0→**hci2**, firmware reloaded (`rtl8761bu_fw.bin`, MGMT ver 1.22). `adapter_pin_failed` (BD 20:E1:5D:68:30:8B gone) at 02:09:50 → `adapter_restored` (resolved hci2) at 02:12:12. busid 1-1.5 in the reset line == the UB500's own busid → this is genuinely the dongle, not a classifier mislabel | **This is the RTL8761B doing the SAME kernel USB-reset chip-hang we attributed to the onboard BCM43438 before the swap.** Classification `kernel_usb_reset_chip_hung` is CORRECT here (real re-enumeration to a new hci index, real BD-address disappearance — unlike the iter-5 dmesg-stale mislabel). **Vindicates the operator's standing skepticism that "the Bluetooth device is failing": BOTH radios hit this on the Pi 3B, so the fault is upstream of the radio — the dwc2 USB controller / power delivery to the USB bus, not the chip.** Happened single-adapter, so NOT dual-adapter stress and NOT an InProgress wedge — a distinct, independent failure class. SoC temp 68–70 °C, throttled=0x0 (warm, no under-voltage) | **Recovery worked, unattended**: the ladder kept the reader alive through the dongle's own re-enumeration + firmware reload (the bulk of the 5.6 min is the hardware coming back, not our latency). Two rough edges: (1) all four rungs reported `BleakError: adapter 'hci0' not found` — the reader chased the stale hci0 index while the dongle was mid-re-enumeration to hci2; L1/L2 fired before hci2 even existed (02:11:39), so they were no-ops by necessity. (2) The **fallback to the internal chip (hci1) produced zero readings** during the outage despite `active=hci1` — the L2 bluetoothd restart + L3 USB replug churn likely destabilized hci1 too. Worth: on an `adapter 'hciN' not found` signature, treat it as re-enumeration and poll for the BD address to reappear on a NEW index rather than climbing rungs that can't help until the firmware reload finishes |
| 2026-07-18T01:13:47–01:26:43Z (~13 min single-battery B dormancy; NOT a wedge; no events fired) | n/a — ambient OFF. But hci0 was provably healthy: **battery A (`V-...0533`) read cleanly on every cycle throughout** (soc_a=100, v_a=13.66 V), while **battery B (`V-...0667`) went fully null** (soc_b=None) for ~13 min and returned on its own. Reader wrote partial rows and backed off to ~24 s/cycle; one retry stretched to 81 s (the only >60 s gap status_check flagged — it missed the larger story because partial rows kept the stream alive) | **Family A2 peer dormancy, cleanly attributable to B.** The single-battery signature is decisive without ambient: because A kept reporting on the same adapter, the radio/BlueZ/reader path were all working — so a one-battery dropout MUST be peer-specific. Second instance of this pattern (2026-07-16 was a 3.5 min A-dormancy). Pack idle, voltages rock-steady, problem_code=0. Not chip, not our stack | **Reader handled it correctly**: partial rows preserved A's data, backoff instead of recovery churn, zero false wedge_snapshot, no `recovery_skipped`. Sat just under the 15-min battery-silent alert threshold (13 min) → no push. Edge case worth noting — a B dormancy 2+ min longer would have alerted. **Takeaway for burst-mode design: a single-battery dropout never needs an ambient burst** — if the other battery is still reading, we already know the radio works and the fault is that specific peer. The burst gate should only fire when BOTH are missing |
| 2026-07-17T17:03:49Z (L1; `adapter_rx_deaf`; reason: scan heard zero advertisements, FM-11) | n/a — ambient scanner OFF (single-adapter experiment, 2h42m in). `ambient_peers_silent: null` correctly reflects no second observer. Reading gap 17:01:16 → 17:04:00 (164 s); reading resumed 11 s after L1 `hciconfig hci0 reset` | **First wedge of the single-adapter experiment, and it is NOT InProgress** — different reason string, different class. The InProgress-free streak through the experiment-start restart (previous 4 restarts: 4/4 wedged in ≤22 s) and 3.5 h of runtime keeps the dual-adapter hypothesis alive. This event is a plain FM-11 rx-deaf: hci0 UP RUNNING, 0 HCI errors, `Discovering: no`, empty dmesg, throttled=0x0, WiFi clean. L1 cleared it in one shot | Without ambient we can't rule out "both peers briefly silent" as the real cause of the empty scan — that's the known cost of the experiment. Weak lean toward reader-side: an L1 reset shouldn't end a genuine peer dormancy, and readings returned 11 s after reset. Note SoC temp 58.0 °C vs 73.1 °C at the 13:20Z wedge — one radio + no continuous scan runs measurably cooler. If rx-deaf recurs at a notable rate with ambient off, consider it a separate, adapter-intrinsic failure mode that dual-adapter operation was masking or aggravating |
| 2026-07-21T07:29:42Z (L1; `adapter_rx_deaf` / FM-11; **FIRST live `ambient_burst` fired during a real rx-deaf event**; 119 s gap 07:27:57→07:29:56) | Burst ran on hci1 (internal BCM43438) for 12 s inside the deaf window. **Both batteries `adv_packets=0` AND `other_adv_packets=0`** — hci1 heard dead air from *every* device, not just our peers. `peers_silent` verdict = **null** (inconclusive) by design: verdict is target>0→False, else other>0→True, else None (`pack.py:1798`). Onset trail: 2 `read_exception` (A 07:28:14, B 07:28:29, both 15 s `TimeoutError`) → 3 consecutive `scan_deaf` on hci0 (07:28:49/07:29:09/07:29:30, "zero adv from any device, FM-11"). Snapshot: hci0 UP RUNNING, 0 HCI errors, USB present/authorized, `throttled=0x20000` (freq-cap *has occurred* — latched bit 17, NOT currently under-voltage/throttled), SoC 62.3 °C, WiFi clean (signal −16, quality 70, 0 missed beacon). dmesg tail had `Malformed LE Event 0x0d`/`unexpected HCI Event 0x00` but from 00:25 PDT (~4 h stale, not event-time). L1 `hciconfig hci0 reset` @ 07:29:44 cleared it; data resumed 12 s later. | **The burst experiment's first real test — and the site's empty RF environment confounds it.** Two radios on different silicon (UB500/hci0 + internal/hci1) both heard zero adv, cabin-wide, across the same ~2 min. Under the prior rx-deaf rows' own framing, "hci1 also hears nothing → real RF blackout / both-radio deafness, not isolated hci0." **But `other_adv_packets=0` means there was no ambient BLE reference to prove hci1's receiver actually works** — so null is genuinely ambiguous between (a) hci1 also deaf (shared host/RF cause) and (b) hci1 fine but nothing to hear (our batteries are the only emitters and were briefly silent → peer-side). One weak asymmetry: an L1 reset of **hci0 only** ended the outage, which leans slightly toward an hci0-side component over a pure both-radio blackout — not conclusive. | **No `peers_silent=false` fired (that's the isolated-adapter-wedge alarm) → no adapter-wedge escalation, correctly.** Recovery unattended (L1, ~2 min, no cascade, USB resets still 0). **Actionable unlock:** the burst will keep returning null on rx-deaf events at this site until there is an ambient BLE reference. **Recommend a cheap always-advertising BLE beacon near the Pi** — then `other_adv_packets>0` whenever hci1 is healthy, converting every future rx-deaf into a decisive verdict: beacon-heard-but-batteries-not = `peers_silent=True` (peer-side, definitive); beacon-not-heard = both radios deaf (shared cause, definitive). Burst verdict logic is correct; the gap is physical (no reference emitter), not code |
| 2026-07-21T18:42:26Z (L1; `adapter_rx_deaf` / FM-11; **2nd burst-during-rx-deaf, identical to 07:29**; 118 s gap 18:40:42→18:42:40) | Byte-for-byte the same signature as the 07:29 event: burst on hci1, both batteries `adv_packets=0`, `other_adv_packets=0`, `peers_silent=null`. Onset: 3× `scan_deaf` (18:41:33/18:41:53/18:42:14) → burst 18:42:26 → wedge_snapshot (throttled=0x20000, WiFi signal −16/quality 70) → L1 `hciconfig hci0 reset` 18:42:28 → data resumed 18:42:40. | **Establishes a cadence, not new mechanism.** Two rx-deaf/burst-null events **~11 h apart** (07:29, 18:42) → this is a *recurring* residual mode at roughly **2×/day**, each self-healing in ~2 min via L1, each returning an inconclusive null for the same empty-RF reason. No drift in signature between the two. | **Reinforces the beacon recommendation with a rate:** at ~2 wasted-diagnostic events/day, the reference beacon would be converting a real rx-deaf into a decisive verdict twice daily. No code change (verdict logic correct, confirmed across both events); no escalation (no `peers_silent=false`); USB resets still 0. Next occurrence with a beacon in range is the one that finally answers hci0-only vs shared-deafness |
| 2026-07-23T00:00Z→ongoing (**battery A dormancy ≥3 h 19 m; NEW: partner-cadence-degradation mechanism characterized**) | A (7E:DC) absent from BlueZ since last read_ok 23:59:12, `soc_a` null throughout; **B (55:DF) still reporting but cadence degraded ~3×** — normal ~10 s spacing stretched to ~24–29 s typical with 62–96 s spikes. In a 2 h window: **69 `read_exception` TimeoutErrors on B vs 2 on A**, 36 gaps >60 s, only 211 rows (vs ~690 healthy). hci0 UP, 0 errors; no wedge/recovery fired (reader correctly does not escalate a peer-absence). SoC visible on B only: 88 %→79 % (discharging). | **A long single-battery dormancy degrades the *healthy* battery's telemetry — a mechanism not previously isolated.** With A absent, every cycle spends its scan window hunting A before it gets to B; the stretched cycles + adapter churn make B's GATT reads time out repeatedly (69×). B stays in the stream but at ⅓ cadence. **Compounding risk:** this doc's own earlier finding is that read-timeouts *trigger* dormancies (the 2026-07-19 onset analysis) — so pounding B with timing-out reads throughout A's absence plausibly raises the odds of B following A into dormancy (partner-following). The two documented mechanisms chain. | **Reader behaves correctly per current design** (partial rows, no false wedge, no recovery churn) and the battery event itself is benign/self-healing per policy — no battery action. **Reliability improvement proposed (not yet implemented — reader hot-path, awaiting go-ahead):** once a peer is confirmed absent for N cycles, back off from re-hunting it every cycle (longer rescan interval for the *absent* peer) and prioritise fast reads of the present one. Keeps the healthy battery at full cadence and cuts the read-timeout churn that risks dragging it down too. |
| 2026-07-23T03:39Z→ongoing (**BOTH-down dormancy ≥1 h 41 m; three live firsts**: decisive burst verdict, `recovery_skipped`, partner-following) | A dormant since 23:59; **B followed A into dormancy at 03:39:42** (last CSV row: B soc=77, −13 A discharge, A already null) — ~3 h 40 m after A's onset, right after the 69→80 read-timeout churn on B. Both now absent from BlueZ. 5 wedge_snapshots (3×L1, 2×L4, class `unclassified`) + 5 bursts over 03:42–04:49. **Bursts returned `peers_silent=TRUE`, `other_adv_packets=15–30`** (hci1 heard 15–30 *other* BLE devices — likely a phone at the cabin — but 0 from either battery). | **The decisive verdict the beacon was meant to provide — obtained here by luck (ambient BLE happened to be present).** `peers_silent=True` with a working-radio reference definitively rules out adapter/RF/host causes: both BMSes genuinely stopped advertising. Confirms the empty-RF `null`s of 07-21/07-22 were the *only* thing missing was a reference emitter. **Partner-following is now observed, not just hypothesized:** B's dormancy onset rode directly on top of the sustained read-timeout churn that A's absence forced onto B — the two documented mechanisms chained exactly as predicted last tick. | **First live `recovery_skipped` × 2** (`ambient_confirms_peers_silent`, `would_have=process_exit`, consec_errors=30): the Phase-2 ambient gate prevented two pointless self-restarts — working exactly as designed. Battery safe (electrically normal, just BLE-invisible), self-heal expected (precedent ≤8 h 44 m). **Two actions reinforced:** (1) a permanent **reference beacon** would make this decisive verdict reliable instead of luck-dependent; (2) the **adaptive-backoff** fix (reduce read churn on the present peer during the other's dormancy) is now backed by an observed partner-following, not just a hypothesis. Classifier gap noted: both-peers-silent wedges log as `unclassified` (no label for this cause) — cosmetic, the gate handles it correctly regardless. |
| 2026-07-23T14:12Z (**RESOLVED — coordinated recovery after a RECORD outage; settle-grace fix validated live**) | Both batteries resumed in the SAME cycle — first post-gap row **14:12:12Z with A and B both present (both SOC 29 %)** — genuinely coordinated. (Corrects an earlier report of 14:37 that came from a stale `scan_result` read; the authoritative signals all agree on ~14:12: history bucket gap ends 14:10, first raw row 14:12:12, and the 404-row count at the recovery tick fits data from ~14:12 not 14:37.) **Durations (new records): A dormant 23:59:12→14:12:12 = ~14 h 13 m** (obliterates the prior 8 h 44 m A record); **B 03:39:42→14:12:12 = ~10 h 33 m**; **both-down ~10 h 33 m** (prior both-down was 6 min). No physical intervention confirmed by operator — likely self-heal, though recovery landed ~07:37 PDT so a cabin wake can't be ruled out. Pack drained **B 88 %→25 %, A→26 %** over the blind window (overnight cabin load; BMS self-protected). Ambient gate held throughout (many `recovery_skipped`, zero self-restarts). | **Longest dormancy on record by 5+ h, yet still self-resolved** — the "it always comes back" property holds even at ~14.5 h, and the coordinated A+B return again points to a shared wake (pack bus / periodic BMS wake) rather than two independent recoveries. Confirms no remote lever was needed for recovery, though visibility was lost ~11 h. | **Settle-grace fix (commit 6a0277a) VALIDATED in production across all three regimes**, measured on the recovery transition: both-present cycles `scan_s` 0.5–2.6 s (unchanged, `done` fires); **one-present cycles 4.5–5.1 s (was 20 s pre-fix)** — B's post-recovery flickers (14:42, 15:16, 15:17) absorbed in ~5 s instead of starving it; both-absent cycles held 20.02 s (FM-11 intact). **Zero `read_exception` on B since recovery** (vs 69–80/window during the pre-fix starvation). The partner-starvation mechanism is now both characterized AND fixed. Remaining open items unchanged: reference beacon (make the decisive verdict reliable, not luck-dependent) and `beacon_seen` code (parked for hardware). |
| 2026-07-23T19:19→20:17Z (**settle-grace fix definitively validated under a real 58-min single-battery dormancy**) | B dormant 19:19:02→20:17:22 (58 min), A reporting throughout — same class as the 07-23-morning A-dormancy but now *post-fix*. Result: **A held full ~10 s cadence, 0 gaps >60 s, 708 rows/2 h, 1 `read_exception`.** | **Direct before/after on the same scenario proves the fix end-to-end.** Pre-fix (A dormant 78 min, ~06:00Z): partner cadence collapsed to ~27 s, 36 gaps, 211 rows, **69** read-timeouts. Post-fix (B dormant 58 min): full cadence, **0** gaps, 708 rows, **1** read-timeout. Both the partner-cadence starvation AND the read-timeout churn (the partner-following *trigger*) are eliminated. | **Stronger evidence than the recovery-transition flickers** (14:12 entry): a *sustained* single-battery dormancy — the exact condition that dragged B down on 07-23 — is now absorbed with zero degradation. Partner-following risk is neutralised: with ~1 read-timeout instead of ~70, the healthy battery is no longer pounded toward its own dormancy. Benign per policy (single-battery, self-healed); no action. |

## Related docs

- `docs/reliability_failure_modes.md` — FM-* catalog and per-mode analysis
- `docs/RUNBOOK.md` — operational responses to alerts
- `docs/vendor/README.md` — vendor protocol reference
