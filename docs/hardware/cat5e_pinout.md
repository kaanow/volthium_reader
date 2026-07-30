# Cat5e cable pinout + termination

## Pinout (both ends — T568B)

Same on both ends — the cable is **straight-through, not crossover**.

| RJ45 pin | T568B color    | Pair # | Net      |
|----------|----------------|--------|----------|
| 1        | white-orange   | 2      | +12 V    |
| 2        | orange         | 2      | +12 V    |
| 3        | white-green    | 3      | +12 V (paralleled) |
| 4        | blue           | 1      | RS-485 A |
| 5        | white-blue     | 1      | RS-485 B |
| 6        | green          | 3      | GND (paralleled) |
| 7        | white-brown    | 4      | GND      |
| 8        | brown          | 4      | GND      |

Why this allocation:

- Pair 1 (blue) is the original 100BASE-TX data pair — it stays as data
  here, carrying RS-485 differential. The twist rejects common-mode noise.
- Pair 2 (orange) was the other 100BASE-TX pair — repurposed for +12 V
  power.
- Pair 3 (green) and pair 4 (brown) were unused on 100 Mbit Ethernet —
  they carry parallel +12 V (with pair 2) and GND (with pair 4 alone, or
  pair 3-green half + pair 4) respectively, halving I·R drop.
- Pairs are kept **intact within a twisted pair** — both wires of pair 2
  carry +12 V, both wires of pair 4 carry GND. Don't split a pair across
  rails; that defeats the noise rejection.

## Shield bonding

Shielded Cat5e has a foil shield and a drain wire. Bond the drain to
chassis GND **at the battery-side end only**:

- Connecting both ends creates a ground loop across the 5 m run, which
  picks up 60 Hz hum from the cabin's AC wiring.
- One end is sufficient to drain shield-coupled noise.
- The battery side is chosen because the 24 V system is the actual ground
  reference for the monitor.

**Reality check on the shield's value (both enclosures are plastic, system
is battery-floating).** There is **no earth/chassis** in this design — so
"bond at the battery end" means bond to the **battery-side signal/pack GND**,
not earth. That still drains capacitively-coupled noise and is correct
single-point practice, but the shield's benefit is **secondary** to the
twisted-pair common-mode rejection already protecting RS-485. Don't expect a
big difference; just don't bond both ends.

**Install/procurement checklist (user — not verifiable in the PCB design):**
- If using shielded (FTP/STP) keystones + shielded RJ45 jacks, **confirm the
  shield is electrically continuous through both keystones** — a shield
  broken at a punchdown does nothing.
- Bond the shield/drain to battery-side GND at **one** point only; leave the
  **display-end shield NC** (the display PCB provides no shield bond — the
  shielded jack's shell stays unbonded there).
- Both enclosures are 3D-printed plastic → no second inadvertent chassis tie
  to worry about.

If the existing in-wall Cat5e isn't terminated yet, terminate with
keystone jacks (Leviton 41108-RW5 or similar Cat5e-rated). Use a
punchdown tool — don't crimp RJ45 plugs directly to the in-wall cable
unless you have a stranded-conductor cable, which in-wall runs typically
aren't.

## Cable QA before final install

Steps to validate the run, in order:

1. **Continuity test (no power)**: ohmmeter from RJ45 pin 1 on each end
   to the same pin. Expect < 2 Ω. Repeat all 8 pins. Then test for
   shorts between adjacent pins.
2. **Pair swap check**: with both keystones terminated, use a basic
   network cable tester — every pin should light in order. If a pair is
   reversed at one end, the tester will show it.
3. **Power-only test (no boards)**: connect a 12 V bench supply with
   400 mA current limit at the battery end. Measure +12 V at the kitchen
   end — should read 12.0 ± 0.1 V at no-load, ≥ 11.9 V at 200 mA.
4. **Full bring-up**: install both boards, energize.

## If the wire's not shielded

The user mentioned shielded Cat5e was pulled. If it turns out to be
unshielded:

- RS-485 should still work over 5 m unshielded — the standard supports
  hundreds of meters even on UTP.
- The 12 V power pair is fine.
- 60 Hz noise pickup on the RS-485 lines is the only real risk; if we
  see frame errors we can add ferrite beads near both transceivers or
  drop the baud rate.

## Why not Ethernet?

We considered just running 10/100 Ethernet between two ESP32 boards (the
ESP32-S3 doesn't have native PHY, but two ESP-NOW-over-Ethernet hacks
exist, and W5500 modules are cheap). Rejected because:

- Ethernet PHYs draw 30–80 mA continuously — far more than RS-485.
- 100 Mbit framing carries no useful bandwidth advantage at our data
  rate (43 bytes every 30 s).
- The link-up handshake adds latency.
- Two extra ICs + magnetics complicates the PCB.

RS-485 is the right complexity tier for "send a tiny frame every once in
a while."
