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

## Related docs

- `docs/reliability_failure_modes.md` — FM-* catalog and per-mode analysis
- `docs/RUNBOOK.md` — operational responses to alerts
- `docs/vendor/README.md` — vendor protocol reference
