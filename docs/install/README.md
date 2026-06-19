# Cabin install — runbook

> ⚠ **STALE / FROZEN — pre-CP1 (decisions.md D18).** The hardware design was
> re-opened at CP1; no fab'd boards exist yet, and the enclosures, e-paper
> interface, and dev port below are all superseded: enclosures are now custom
> 3D-printed (battery IP5x box, D20; display in a recessed **double-gang** box
> with a 3D-printed faceplate, D27 — **not** Hammond/single-gang), the e-paper
> is an **8-pin Waveshare 4.2" Module (B)** (no loose FFC ribbon, DR-7), and
> the dev port is native **USB-C** (D22/D27). This runbook will be regenerated
> after the design is re-validated and fab'd. Do not follow it as written.

> Pre-install assumption: PCB fab is complete and both boards have been
> bench-tested using `docs/install/bench_test.md` *before* you bring
> them to the cabin. Don't install boards you haven't bench-tested.

## What you need at the cabin

- Both PCBs in their enclosures (battery-side in Hammond 1556B2GY,
  display-side ready for the wall plate)
- 4.2" e-paper panel + FFC ribbon cable
- Single-gang low-voltage mounting bracket + blank wall plate
  (pre-cut for the panel + buttons)
- Cat5e patch cables (1 short, ≤30 cm — one per end)
- Two Cat5e keystone jacks if the in-wall run isn't already terminated
- 16 AWG fused tap cable to the 24 V pack (battery + via 1 A inline fuse
  to the battery-side enclosure)
- Ring terminals sized for the battery pack's terminal studs
- Tools: punch-down tool (110-type), wire strippers, multimeter,
  Phillips driver, drywall saw or hole-saw for the wall-plate cutout
  (if not already cut), label maker (optional)

## Order of operations

The order matters. Do these in sequence, **don't skip steps**, and
verify each before moving on.

### 1. Cat5e cable QA (before connecting anything live)

If the in-wall Cat5e hasn't been terminated yet, terminate now.

1. At the battery-side end of the cable, punch down keystone jack to
   **T568B** wire order:
   ```
   pin 1: white-orange     pin 5: white-blue
   pin 2: orange           pin 6: green
   pin 3: white-green      pin 7: white-brown
   pin 4: blue             pin 8: brown
   ```
2. Same T568B order at the display-side end. **Don't crossover.**
3. With cable now terminated:
   - Use a basic continuity tester or multimeter to verify all 8 pins
     conductive end-to-end.
   - Verify no shorts between adjacent pins.
   - **Bond the shield drain wire to the battery-side keystone's
     shield post only.** Do NOT bond at the display end.

Reference: `docs/hardware/cat5e_pinout.md`.

### 2. Power-only test of the Cat5e run

Before introducing the monitor PCBs, verify the cable can carry 12 V.

1. With the **batteries still disconnected** from the system, set up a
   bench 12 V supply with 400 mA current limit.
2. Connect supply (+) to **pins 1, 2, 3** of the battery-side keystone
   (these are the +12 V pins — three pins paralleled to share current).
   Connect supply (−) to **pins 6, 7, 8**.
3. At the display-side keystone, measure pin 1 → pin 6 with a
   multimeter: should read 12.0 ± 0.1 V at no load.
4. Apply a 200 mA test load (e.g. a 56 Ω 5 W resistor) at the display
   end. Voltage should drop no more than ~30 mV. If it drops more,
   something's wrong — re-check terminations.

### 3. Battery-side enclosure mounting

1. Choose a mounting spot **within 2 m of the batteries** but with
   airflow (don't tape it directly to a battery — it'll see thermal
   cycling).
2. Mount the Hammond enclosure with the cable-gland side facing the
   batteries, RJ45 side facing the wall.
3. Don't tighten the lid yet — you'll be working inside it for the next
   steps.

### 4. Tap the 24 V pack

**Pack must be in a stable state — not actively charging or
discharging at heavy current.** If the generator's running, wait for
it to stop. Open the inverter breaker if you can.

1. Crimp a 16 AWG ring terminal on one end of a length of red wire,
   long enough to reach from the pack's (+) terminal to the
   battery-side enclosure's terminal block J2.
2. Same for the (−) terminal with black wire.
3. **Add a 1 A inline ATO fuse holder** in the red wire, within
   ~15 cm of the (+) ring terminal.
4. Connect **black first** to the pack's (−) terminal. Tighten to spec.
5. Strip the other ends and wire to J2:
   - Red (with fuse) → J2 pin 1 (V24_RAW)
   - Black → J2 pin 2 (GND)
6. Insert the 1 A fuse last (or have it already in the holder when
   you do step 4). Tightening the (+) ring terminal is the energization
   moment.

**Verify before continuing**: with a multimeter across J2,
read 24–28 V (depending on pack state). If it reads 0 V or negative,
**stop** — the polarity is reversed. The reverse-protect Schottky
saved you this time; un-reverse before powering on the rest.

### 5. First power-up — battery side

1. Close the battery-side enclosure lid (not screwed tight yet, just
   sit it on top).
2. Plug a short Cat5e patch cable from the battery-side board's J1
   into the wall-side keystone.
3. **Look at the battery-side enclosure's debug LED** (visible through
   a translucent lid, or temporarily look inside before closing):
   - Slow heartbeat blink (~1 Hz) = normal, BLE searching.
   - Fast blink = LOW state. Pack SOC is < 25 %. Bench test pre-deploy
     should rule this out.
   - Off = problem. Check fuse, check 24 V at J2.

Wait ~10 seconds for the BLE central to discover both batteries. The
ESP32-S3's onboard LED should transition to a slower, steadier blink
once BLE handshake completes.

### 6. Display-side install

1. With the battery-side already powered, plug a short Cat5e patch
   cable from the wall keystone into the display-side board's J11.
2. **Watch the e-paper panel** — within ~15 s of power-up, it should
   do a full refresh and draw the initial screen.
3. If the screen stays blank for > 30 s:
   - Check 12 V is reaching the display-side board: multimeter from
     U10 VIN to GND should read 12.0 V.
   - Check 3.3 V output of U10: should be 3.30 ± 0.05 V.
   - Check the FFC ribbon is fully seated on both ends (panel and J3).
4. Mount the display-side board to the single-gang bracket using M3
   standoffs.
5. Sit the e-paper panel against the bracket's panel-cutout.
6. Snap the wall plate over the bracket. The buttons should align with
   the cutouts.

### 7. First-time verification

The first screen the display draws should match what the Mac dashboard
shows. With both running:

1. Open the Volthium phone app on a phone and note the SOC + voltage.
   *(Don't keep the app connected — close it before the next step.)*
2. Compare against the e-paper headline numbers — should match within
   1 %.
3. Compare against `http://localhost:8421/` on the laptop.
4. Press **BTN_REFRESH** on the display panel. Within ~7 s the panel
   should redraw the same data.
5. Press **BTN_RELEASE** for 1 s. The panel should switch to a
   "phone-app mode" screen with a 5-minute countdown. The battery-side
   should disconnect from BLE; you should now be able to open the
   Volthium app and connect.
6. After 5 minutes, the battery-side should auto-reconnect.

### 8. Override button check

This is the deepest fail-safe. Test it once on install.

1. Press and hold the **override button** on the battery-side
   enclosure for 5 seconds.
2. The battery-side should force a reading cycle regardless of any
   shutdown state.

(This is mainly useful after a deep-discharge auto-cut — you press the
button to bring monitoring back manually rather than waiting for the
ULP-detected voltage recovery.)

### 9. Tighten everything

- Tighten the battery-side enclosure lid screws.
- Verify the cable-gland is snug around the Cat5e and 24 V tap cable
  bundle.
- Tighten the display wall plate screws.
- Run the cable-tester end-to-end one final time. (Easy when both ends
  are accessible. Hard to do later if a wall plate has to come off.)

## Trouble?

See `docs/install/troubleshooting.md`.

## Done

The system should be self-sufficient at this point. The Mac monitor at
`data/pack.csv` keeps logging if it's running; the wall display works
without the Mac.
