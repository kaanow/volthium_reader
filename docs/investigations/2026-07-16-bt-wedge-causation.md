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

### Phase 2 — only if Phase 1 doesn't resolve

Held explicitly out of Phase 1 to avoid changing the workload while
measuring:

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

## Observation log

<!-- Append entries below as wedges are observed with ambient data available. -->

| Wedge onset (UTC) | `ambient_advertising` says | Interpretation | Notes |
|---|---|---|---|
| 2026-07-16T19:38:52Z (L1, `kernel_usb_reset_chip_hung`) | Both batteries visible on hci1 straddling the wedge: B `adv_packets=3` @ 19:38:50, A `adv_packets=1` @ 19:38:50; both jump to 5-8 packets/window immediately after. Neither battery ever showed `adv_packets=0` around the wedge | **Leans Family B / against chip-failure narrative** — the batteries were still transmitting beacons at normal cadence throughout the wedge; hci0's scan came up empty anyway. Rules out "BMS went silent" and "environmental blackout." | Wedge fired 22 s after `ambient_scanner_started` — startup transient can't be fully ruled out. Need 1-2 more observations. Also: RSSI dropped to -127 (sentinel = "unknown") after 19:39:00 on hci1 while packets kept flowing; possible bleak/BlueZ RSSI-reporting quirk on this adapter, not a signal-quality issue |

## Related docs

- `docs/reliability_failure_modes.md` — FM-* catalog and per-mode analysis
- `docs/RUNBOOK.md` — operational responses to alerts
- `docs/vendor/README.md` — vendor protocol reference
