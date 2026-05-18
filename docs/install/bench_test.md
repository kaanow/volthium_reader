# Pre-install bench test

Run this with both PCBs in hand, **before** you take them to the
cabin. Catches assembly defects without involving the cabin's batteries.

## Bench setup

- Variable bench supply (24 V, 0–500 mA limit)
- Multimeter
- Oscilloscope (nice to have, not required)
- Two Volthium batteries OR an open-source BMS sim (out of scope here)
- USB-C cable + a Mac/Linux machine with `esptool` for flashing
- A laptop on the same Cat5e/RS-485 bus (use the dev rig's USB-RS485
  dongle if you don't have boards yet)

## Battery-side board

### Smoke test (no firmware)

1. Apply **24 V at 100 mA limit** to J2 (red to +24, black to GND).
2. Verify the current draw is ≤ 50 mA (mostly the TPS62933 inrush
   spike, then steady-state ~20 mA without firmware).
3. Multimeter across V3V3 net (test point or U1 output): **3.30 ± 0.05 V**.
4. Multimeter across V12_CAT5E (J1 pin 1 → pin 6): **12.0 ± 0.2 V**.
5. With power off, multimeter continuity from V24_RAW through F1 to
   D1 anode to D1 cathode to U1/U2 VIN: should all be conductive.
6. Reverse-polarity test: briefly reverse the supply polarity (still
   limited to 100 mA). The Schottky D1 should block — verify no
   current flows past it. **Don't hold this state more than ~1 s.**

### Firmware flash

1. Hold BOOT, tap RESET, release BOOT (puts ESP32-S3 in download mode).
2. `idf.py -p /dev/cu.usbserial-... flash` from `firmware/bms-link/`.
3. After flash, RESET. The console (`idf.py monitor`) should show:
   ```
   I (123) volthium: starting battery-side firmware vX.Y.Z
   I (135) volthium: 24 V sense: 25.xx V
   I (210) volthium: BLE central up; scanning for V-12V???Ah-*
   ```

### BLE scan check

The board should discover both Volthium batteries by their advertised
names (`V-12V200AH-0533` and `V-12V200AH-0667`). If only one shows up:
re-verify the antenna keepout area — the ESP32-S3 has reduced range if
there's copper too close to its antenna.

### MOSFET hard-cut check

1. Force `PWR_EN_N` high (in firmware, or yank GPIO4 to V3V3 manually).
2. Verify V24_SW (downstream of Q1) drops to 0 V.
3. Restore PWR_EN_N low.
4. V24_SW returns to ~V24_RAW.

This test confirms the hard-cut path before you rely on it in the
field.

## Display-side board

### Smoke test (no firmware)

1. Apply **12 V at 100 mA limit** to J11 pin 1 (+) and pin 6 (−).
   (Use a Cat5e jumper for convenience.)
2. Current draw should be ≤ 30 mA without firmware.
3. Multimeter on the 3.3 V rail: **3.30 ± 0.05 V**.

### Firmware flash

Same procedure as battery-side, but `firmware/display/`.

### E-paper init

After flash + reset, the panel should do a full refresh within ~10 s
of power-up. The initial screen is "WAITING FOR DATA" since the
battery-side isn't connected yet.

### Button check

The firmware has a debug mode (long-press BTN_REFRESH + BTN_NEXT) that
shows raw button events on the e-paper. Use it to verify all three
buttons register cleanly.

## End-to-end on the bench

1. Power both boards.
2. Connect them with a 1 m Cat5e patch cable.
3. Display should transition from "WAITING FOR DATA" to live readings
   within ~30 s.
4. If the boards are within BLE range of actual batteries, the
   readings should match the Volthium app.

## Acceptance criteria

A board passes bench test if and only if:

- [ ] Current draw on 24 V (battery-side) is < 80 mA in NORMAL state
- [ ] 3.3 V rail is within 3.25–3.35 V at both ends
- [ ] 12 V at the display end is > 11.7 V at full load
- [ ] BLE successfully connects to both batteries
- [ ] MOSFET hard-cut works
- [ ] E-paper does a clean full refresh
- [ ] All three buttons register
- [ ] End-to-end: display shows live data, matches Volthium app

Boards that fail any of these stay on the bench.
