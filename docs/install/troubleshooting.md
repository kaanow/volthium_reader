# Troubleshooting

Common failure modes, in approximate order of likelihood, with the
quick check and the actual fix.

## Display panel stays blank after power-up

| Quick check                         | Likely cause / fix                        |
|-------------------------------------|-------------------------------------------|
| 12 V at U10 VIN?                    | No → check Cat5e termination, polarity     |
| 3.3 V at U10 VOUT?                  | No → buck regulator failure; replace U10  |
| E-paper FFC fully seated both ends? | No → reseat; the latch is easy to miss     |
| Onboard LED blinking?               | No → ESP32 isn't running; flash check     |
| BUSY line stays high forever?       | Panel firmware-level issue; reset board   |

## Display shows "LINK DOWN" after running fine

The battery-side stopped sending frames.

| Quick check                                | Likely cause / fix                                  |
|--------------------------------------------|-----------------------------------------------------|
| Is the battery-side enclosure powered?     | Fuse blown? 24 V tap loose?                          |
| Battery-side LED state?                    | Off = no power; fast blink = LOW state (pack < 25 %) |
| Continuity on Cat5e RS-485 pair?           | Cable damage somewhere in-wall                       |
| Display side's RS-485 transceiver hot?     | Driver fight (two transceivers trying to drive)      |

## Battery-side never finds the BLE batteries

| Quick check                              | Likely cause / fix                              |
|------------------------------------------|--------------------------------------------------|
| Are the batteries powered on?            | Volthium BMSes need to be active                 |
| Volthium phone app open somewhere?       | Only one BLE central allowed; close the app      |
| Distance from batteries < 3 m?           | Move closer; BLE 4.0 is range-limited            |
| Antenna keepout respected on PCB?        | Re-check layout near the WROOM-1 antenna corner  |
| Firmware version recent?                 | Check `git log firmware/bms-link/`               |

## Wall display shows "BMS A OFFLINE" (just one battery)

One of the two BMSes isn't being read.

1. Read the displayed serial number — which battery is offline?
2. Open the Volthium phone app and check that battery directly.
3. If the phone app can't see it either → battery's BMS may be in a
   protection state. Reset the battery per Volthium's procedure.
4. If the phone app sees it but ours doesn't → BLE address may have
   shifted (iOS-style randomization isn't a thing on these BMSes, but
   firmware-level address caching can drift). Force a re-scan via the
   override button.

## "MONITOR ASLEEP — pack <10%"

This is *correct behavior* when the pack is deeply discharged. The
monitor has hard-cut to protect the pack. To re-enable:

- Wait for the pack to recover (e.g. solar charges it back up) — the
  ULP voltage-sense will auto-re-engage when voltage indicates SOC
  recovery.
- Or press the **override button** on the battery-side enclosure to
  force re-engage right now.

## "LOW PACK" banner shows but pack is fine

False positive — the monitor thinks SOC is < 25 % but the Volthium app
says otherwise. Possible causes:

| Cause                                     | Fix                                                  |
|-------------------------------------------|------------------------------------------------------|
| BMS reporting bad SOC (rare)              | Cycle the battery; let the BMS re-learn its SOC      |
| Stuck reading from one battery dominating | Look at per-battery SOC on the display; if asymmetric, one BMS may be the source |
| Capacity drift in our config              | The estimator's `capacity_ah` is hard-coded at 200 Ah; if the batteries have aged, update via the firmware build configuration |

## Display refresh "ghosting" (faint old image)

Normal for e-paper after many partial refreshes. The firmware schedules
a full refresh every 10 minutes to clear ghosting. If it's persistent:

- Force a full refresh with BTN_REFRESH (long press = full refresh).
- Temperature too low (< 0 °C) → e-paper specs degrade; this should
  only happen if the cabin is unheated and the heater hasn't kicked on.

## Buttons not responding

| Quick check                            | Likely cause / fix                              |
|----------------------------------------|--------------------------------------------------|
| Multimeter: button closes to GND?      | No → mechanical failure; replace switch         |
| 10 kΩ pull-up to V3V3 across button?   | No → pull-up resistor open; trace damage        |
| Same button across all three?          | Yes → firmware issue, not hardware              |

## RS-485 frame errors in the log

Battery-side firmware logs CRC mismatches as `WARN frame crc fail
got=XXXX want=YYYY`. Occasional ones (< 1 per minute) are fine —
60 Hz noise pickup or a brief bus glitch. Frequent ones suggest:

| Cause                                       | Fix                                                  |
|---------------------------------------------|------------------------------------------------------|
| Shield bonded at both ends                  | Lift the display-side bond                           |
| Termination missing or doubled              | Verify 120 Ω only at the **two endpoints**; lift internal terms |
| Bias resistors missing                      | Drop in R2/R3 idle-bias on the battery side          |
| Cable run next to high-current AC wiring    | Separation rules — keep > 30 cm from AC for the cable run |

## Mac dashboard shows "no data yet"

The CSV logger isn't producing rows. Common reasons:

1. **Logger crashed**: `pgrep -f scripts/log.py` returns nothing.
   Restart via `./Launch Volthium Monitor.command` or the manual
   commands in `README.md`.
2. **Bluetooth permission dropped**: macOS 15 sometimes revokes
   Bluetooth permission for Terminal after a major update. See
   `memory/macos_bluetooth_tcc.md` for the patch.
3. **Both batteries unreachable**: rare; same situation as the wall
   display would show "BMS OFFLINE."

## When in doubt

Capture the state and ask:

```bash
# Snapshot of current state
{
  echo "== processes =="
  pgrep -fl 'scripts/log\.py'
  pgrep -fl 'scripts/dashboard\.py'
  echo
  echo "== last 10 log lines =="
  tail -10 data/pack.log
  echo
  echo "== last 5 CSV rows =="
  tail -5 data/pack.csv
  echo
  echo "== analyze =="
  .venv/bin/python scripts/analyze.py
} > /tmp/volthium_snapshot.txt
```

Paste `/tmp/volthium_snapshot.txt` into a new Claude Code session for
fresh-eyes triage.
