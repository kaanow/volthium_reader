# BLE flap recovery — observed behavior + firmware expectations

The Volthium SC12200G4DPH BMSes drop their BLE advertisement / connection
intermittently. The Mac-side dev rig captured 5 such events in the first
~5 hours of continuous logging on 2026-05-17, giving us real numbers
to drive the firmware design.

## Observed events (2026-05-17 dev session)

| #  | UTC time   | which battery     | recovery time | what happened                                          |
|----|------------|-------------------|---------------|--------------------------------------------------------|
| 1  | 17:23:45   | A (0533)          | ~5 s          | `find_device_by_address` returned None                 |
| 2  | 18:04:02   | B (0667)          | ~6 s          | same — battery not in scan results                     |
| 3  | 18:23:43   | A (0533)          | ~3 s          | same                                                   |
| 4  | 18:45:21   | A (0533)          | ~5 s          | same                                                   |
| 5  | 20:02:23   | B (0667)          | ~10 s         | same                                                   |

Patterns:
- **Roughly one flap per hour** during continuous polling at 10 s
  intervals (5 events in ~5 h).
- **Each flap was a single failure** — the next 10 s cycle succeeded.
  Never observed > 1 consecutive failure.
- **Recovery time 3–10 s** — matches one full BLE scan cycle on macOS.
- Both batteries flap **roughly equally** (3× A, 2× B) — not specific
  to one BMS.
- All flap signatures look the same: `find_device_by_address` returns
  `None` because the device wasn't visible in the scan during that
  attempt.

## Root cause (best guess)

The BMS's BLE advertising interval and our scan window aren't
synchronized. If the BMS happens to be in a quiet phase of its
advertisement pattern while we're scanning, we miss it. macOS scans on
a duty cycle, the BMS advertises on a duty cycle, and aliasing
between the two produces the occasional miss.

This is **expected, benign, and self-correcting.** It is NOT:
- a sign of weak signal (we're < 3 m from both batteries)
- a sign of one BMS being broken (both flap equally)
- a sign the BMS has crashed (next scan succeeds without intervention)

## Mac-side handling (in production already)

`scripts/log.py` catches the exception, logs a WARNING with a flap
counter, and retries on the next cycle. Backoff escalates only after
3 consecutive failures (we never saw that in practice). The CSV writer
just skips the row for the flap interval — there's no entry written
for the failed sample, and the next successful sample's timestamp shows
the gap. Downstream analysis treats > 60 s timestamp gaps as "ignore"
in rate calculations (see `scripts/analyze.py::ah_rate_by_current_bucket`).

## Firmware design expectations (production ESP32)

The C-port firmware should handle flaps with the same shape:

### Connection model

In NORMAL mode, hold **persistent BLE connections** to both batteries
(we decided this in `docs/firmware/architecture.md` — the BMS only
accepts one central, but having a persistent connection is fine; the
phone app only fails to connect if WE step aside via the release-BLE
button). When a flap happens, we'll see one of:

- `GATT disconnect` event (BMS terminated the link)
- A scheduled read timing out (BMS stopped responding mid-session)

### Retry policy

```
   on disconnect / timeout:
     log a flap event with monotonic ms
     wait min_backoff_ms (initial 500 ms)
     attempt reconnect (esp_ble_gattc_open or similar)
     on success: reset backoff, resume normal cycle
     on failure: backoff = min(backoff * 2, max_backoff_ms)
                 attempt again after backoff
     after >= 5 consecutive failures totaling >= 60 s:
         emit "BLE OUT — battery X" frame on RS-485
         continue retries at max_backoff
```

`min_backoff_ms = 500`, `max_backoff_ms = 30_000` works well per the
Mac data — most flaps recover in well under the second attempt.

### Telemetry

Every flap should set a frame-level flag bit
(`VOLTHIUM_FLAG_A_UNREACHABLE` or `_B_UNREACHABLE` in
`firmware/common/volthium_lib/wire_protocol.h`) for the next RS-485
frame after the flap, so the display side can show "A: re-syncing"
briefly. Frame after the *next* successful read clears the flag.

The frame also has a `seq` field; if a battery is unreachable for an
extended period, the display side notices by inspecting the
unreachable flag persistence across many `seq` values.

### Display-side handling

Already specified in `docs/firmware/state_machine.md` § "Display-side
reactions":

- Flap < 90 s → no visible change; the per-battery row briefly shows
  the unreachable flag, then clears
- Flap > 90 s → display starts a "A: OFFLINE since HH:MM" overlay
- Flap > 6 min → battery-side may have entered DEEP_SLEEP (low SOC);
  display shows "MONITOR ASLEEP" if both go silent

### What NOT to do

- **Don't immediately escalate** on a single missed read. Five flaps
  in five hours is normal background noise.
- **Don't tear down the BLE stack** on a flap. Reconnect at the GATT
  layer; the controller stays initialized.
- **Don't alert the user** for short-term flaps. The wall display
  should only surface persistent issues.

## Testing the firmware path

The Mac dev rig's logger code (`scripts/log.py`) plus its observed
flap events form a regression set. A firmware unit test should
simulate the same shape:

```c
TEST_CASE("single-cycle BLE flap recovers silently", "[ble]") {
    fake_ble_set_next_scan_result(BLE_NO_DEVICE);
    ble_task_run_one_cycle();    // produces 1 flap event
    fake_ble_set_next_scan_result(BLE_DEVICE_VISIBLE);
    ble_task_run_one_cycle();    // recovers
    ASSERT_FRAME_FLAGS_AFTER_RECOVERY == 0;
    ASSERT_FLAP_COUNTER == 1;
}

TEST_CASE("sustained flap sets unreachable flag and decays", "[ble]") {
    for (int i = 0; i < 10; i++) {
        fake_ble_set_next_scan_result(BLE_NO_DEVICE);
        ble_task_run_one_cycle();
    }
    // 10 missed reads = 100 s @ 10 s cycle
    ASSERT_LAST_FRAME_FLAGS & VOLTHIUM_FLAG_A_UNREACHABLE;
    // and once it comes back...
    fake_ble_set_next_scan_result(BLE_DEVICE_VISIBLE);
    ble_task_run_one_cycle();
    ASSERT_LAST_FRAME_FLAGS == 0;
}
```

## When the cabin install is live

Logger output should be monitored for the *rate* of flaps. Sudden jump
from "1/h" to "5/min" is a real signal — either:
- BLE interference (microwave, neighboring 2.4 GHz device)
- One of the BMSes degrading
- Software regression in our reader

The dashboard's events panel could surface "elevated flap rate" the
same way it surfaces "heavy load on" — define a new event type
`flap_burst` for > 3 flaps in 60 s.
