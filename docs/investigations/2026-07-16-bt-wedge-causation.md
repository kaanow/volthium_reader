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

### Phase 2B — burst-mode ambient (built 2026-07-17, deploy after experiment)

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
| 2026-07-18T02:09:43–02:15:09Z (**UB500 kernel USB reset**; full L1→L4 cascade; 339 s / 5.6 min outage; the stale-push alert) | n/a — ambient OFF. dmesg is decisive: `hci0: urb … failed to resubmit (2)` → `Unable to disable scanning: -2` → **`usb 1-1.5: reset full-speed USB device number 4 using dwc2`** → dongle re-enumerated hci0→**hci2**, firmware reloaded (`rtl8761bu_fw.bin`, MGMT ver 1.22). `adapter_pin_failed` (BD 20:E1:5D:68:30:8B gone) at 02:09:50 → `adapter_restored` (resolved hci2) at 02:12:12. busid 1-1.5 in the reset line == the UB500's own busid → this is genuinely the dongle, not a classifier mislabel | **This is the RTL8761B doing the SAME kernel USB-reset chip-hang we attributed to the onboard BCM43438 before the swap.** Classification `kernel_usb_reset_chip_hung` is CORRECT here (real re-enumeration to a new hci index, real BD-address disappearance — unlike the iter-5 dmesg-stale mislabel). **Vindicates the operator's standing skepticism that "the Bluetooth device is failing": BOTH radios hit this on the Pi 3B, so the fault is upstream of the radio — the dwc2 USB controller / power delivery to the USB bus, not the chip.** Happened single-adapter, so NOT dual-adapter stress and NOT an InProgress wedge — a distinct, independent failure class. SoC temp 68–70 °C, throttled=0x0 (warm, no under-voltage) | **Recovery worked, unattended**: the ladder kept the reader alive through the dongle's own re-enumeration + firmware reload (the bulk of the 5.6 min is the hardware coming back, not our latency). Two rough edges: (1) all four rungs reported `BleakError: adapter 'hci0' not found` — the reader chased the stale hci0 index while the dongle was mid-re-enumeration to hci2; L1/L2 fired before hci2 even existed (02:11:39), so they were no-ops by necessity. (2) The **fallback to the internal chip (hci1) produced zero readings** during the outage despite `active=hci1` — the L2 bluetoothd restart + L3 USB replug churn likely destabilized hci1 too. Worth: on an `adapter 'hciN' not found` signature, treat it as re-enumeration and poll for the BD address to reappear on a NEW index rather than climbing rungs that can't help until the firmware reload finishes |
| 2026-07-18T01:13:47–01:26:43Z (~13 min single-battery B dormancy; NOT a wedge; no events fired) | n/a — ambient OFF. But hci0 was provably healthy: **battery A (`V-...0533`) read cleanly on every cycle throughout** (soc_a=100, v_a=13.66 V), while **battery B (`V-...0667`) went fully null** (soc_b=None) for ~13 min and returned on its own. Reader wrote partial rows and backed off to ~24 s/cycle; one retry stretched to 81 s (the only >60 s gap status_check flagged — it missed the larger story because partial rows kept the stream alive) | **Family A2 peer dormancy, cleanly attributable to B.** The single-battery signature is decisive without ambient: because A kept reporting on the same adapter, the radio/BlueZ/reader path were all working — so a one-battery dropout MUST be peer-specific. Second instance of this pattern (2026-07-16 was a 3.5 min A-dormancy). Pack idle, voltages rock-steady, problem_code=0. Not chip, not our stack | **Reader handled it correctly**: partial rows preserved A's data, backoff instead of recovery churn, zero false wedge_snapshot, no `recovery_skipped`. Sat just under the 15-min battery-silent alert threshold (13 min) → no push. Edge case worth noting — a B dormancy 2+ min longer would have alerted. **Takeaway for burst-mode design: a single-battery dropout never needs an ambient burst** — if the other battery is still reading, we already know the radio works and the fault is that specific peer. The burst gate should only fire when BOTH are missing |
| 2026-07-17T17:03:49Z (L1; `adapter_rx_deaf`; reason: scan heard zero advertisements, FM-11) | n/a — ambient scanner OFF (single-adapter experiment, 2h42m in). `ambient_peers_silent: null` correctly reflects no second observer. Reading gap 17:01:16 → 17:04:00 (164 s); reading resumed 11 s after L1 `hciconfig hci0 reset` | **First wedge of the single-adapter experiment, and it is NOT InProgress** — different reason string, different class. The InProgress-free streak through the experiment-start restart (previous 4 restarts: 4/4 wedged in ≤22 s) and 3.5 h of runtime keeps the dual-adapter hypothesis alive. This event is a plain FM-11 rx-deaf: hci0 UP RUNNING, 0 HCI errors, `Discovering: no`, empty dmesg, throttled=0x0, WiFi clean. L1 cleared it in one shot | Without ambient we can't rule out "both peers briefly silent" as the real cause of the empty scan — that's the known cost of the experiment. Weak lean toward reader-side: an L1 reset shouldn't end a genuine peer dormancy, and readings returned 11 s after reset. Note SoC temp 58.0 °C vs 73.1 °C at the 13:20Z wedge — one radio + no continuous scan runs measurably cooler. If rx-deaf recurs at a notable rate with ambient off, consider it a separate, adapter-intrinsic failure mode that dual-adapter operation was masking or aggravating |

## Related docs

- `docs/reliability_failure_modes.md` — FM-* catalog and per-mode analysis
- `docs/RUNBOOK.md` — operational responses to alerts
- `docs/vendor/README.md` — vendor protocol reference
