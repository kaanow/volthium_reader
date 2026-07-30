# Battery-side board — bring-up guide

> **Status: living draft (CP2, 2026-07-23).** Written at schematic stage on
> purpose: every step here is also an audit of the design ("can this step be
> performed with the connections we drew?") — DR-32 (the J5 EN/IO0 header)
> exists because drafting this thinking found a gap. Items marked **[CP3/CP5]**
> get pinned once layout fixes physical access. Companion documents:
> `hardware/layout/requirements.md` (R-numbers), `DESIGN_REVIEW_ITEMS.md`
> (DR-numbers), `cp1_rs485_battery_read.md` §7 (the iso acceptance matrix).

**Golden rule: one energy source, one new subsystem at a time.** The board is
designed so every riskier block is behind a default-OFF gate — use that.

## Stage 0 — bench prep (no board power)

- Visual + continuity: pack input polarity J1, no V24_RAW↔GND short,
  V3V3↔GND resistance sane (≥ ~5 kΩ; R13 1 M + dividers dominate).
- **Do not** insert F1's cartridge yet. Packs stay disconnected.
- Tools: bench PSU (current-limited), USB-C cable, ESP-Prog or USB-UART,
  multimeter. The Volthium packs come LAST.

## Stage 1 — USB-only smoke + first flash (R6/R7)

1. Plug USB-C only. Expected: U5 3.3 V out → U6 selects VIN1 → **V3V3 ≈ 3.3 V**;
   Q4 sees VBUS → Q3 opens → R7 pulls EN high → MCU boots.
   Measure: VBUS 5 V, V3V3, EN ≈ 3.3 V. Idle current [CP5: record baseline].
2. Blank module ⇒ ROM download mode by itself. `esptool.py chip_id` over the
   **native USB** port proves the R7 path end-to-end.
3. First firmware flash over USB. Confirm console output on J5.3 (UART0).
4. **Recovery drill (do this NOW, not when you need it):** jumper J5.6
   (BOOT/IO0) → J5.4 (GND), blip J5.1 (EN) low, confirm the ROM downloader
   appears on the J5.3/J5.5 UART. This is the deep-sleep-proof path (R8) —
   verify it once while nothing is at stake. (J5 is the keyed 2×3 ESP-Prog
   Program pinout — an ESP-Prog ribbon mates directly and its auto-program
   circuit drives EN/IO0 for you; the jumper drill is the no-ESP-Prog path.)

## Stage 2 — pack power path (R14/R5), packs still absent

1. Bench PSU at 24.0 V, current limit ~100 mA, onto J1 (F1 cartridge IN now).
   Expected: V24_FUSED ≈ 24 V, LM5166 runs, **V3V3_BUCK ≈ 3.3 V**; with USB
   also present U6 must prefer VIN1 (USB) — pull USB and V3V3 must stay up
   from the buck (mux switchover).
2. UVLO thresholds (R5): sweep the PSU 22 → 19.5 V watching UVLO_RESET:
   assert LOW at ≈ 20.0 V falling; sweep up: release at ≈ 21.7–21.8 V.
   [CP5: record actuals against D28/F04 numbers.]
3. Sleep-floor current at 24 V with everything gated off
   [CP5: target per power_budget.md; State-4 floor ≈ 1 mW class].

## Stage 3 — gated subsystems, one CHx_PWR at a time (R4)

For each of CH1_PWR, CH2_PWR, CAN_PWR, EXP_PWR_EN — in that order:
- OFF state first: gated rail ≈ 0 V (EXP rail parked ≤ 50 mV per F66),
  incremental current ≈ 0.
- Drive the GPIO low → rail ≈ 3.3 V; incremental current sane
  (ADM2587E ch: ~90 mA class when talking; TCAN332 ~3.5 mA listening).
- Release → rail collapses (bleed/load), draw returns to floor.

## Stage 4 — isolated RS-485 read (R1/R2, DR-26 §7)

**This is the DR-26 acceptance gate — packs appear here for the first time.**
1. One pack, one channel: vendor cable pack → J10. With CH1_PWR on, confirm
   isoPower: V_ISOOUT1/V_ISOIN1 ≈ 3.3 V measured **against ISO_BUS_GND1**
   (floating — use a battery DMM, not a grounded scope).
2. Poll the BMS (9600 8N1 per vendor protocol) — first real data.
   **A/B caution (field 2026-07-25):** both packs idle with pin 8 ~0.4 V
   *above* pin 7 — under TI naming that suggests 8=A, opposite the vendor's
   7=A/8=B. If the first poll gets no reply, mirror A/B before debugging
   anything else.
3. Both packs, both channels: run the §7 **two-domain matrix** (float vs
   REF-pad reference). R27/R37 stay DNP unless the float fails (user call:
   populate only on evidence).
4. Confirm the ±12 V common-mode reality: measure PACK1_Bminus vs
   PACK2_Bminus at the REF pads (expect ≈ 12 V — this is WHY R1 exists).

## Stage 5 — Xanbus CAN listen (R10, DR-31)

1. **Before first attach: ✅ DONE 2026-07-25 (owner field measurement,
   live port, ref pin 8):** 1/2/7 = 12 V (NET_S — one measurement; NET_S
   has NO published max, Xantrex examples run 15 VDC > U7's +14 V abs-max,
   so a NET_S-to-CAN miswire stays treated as fatal to U7 — F11), 3/6 =
   0 V (NET_C), **4 = 2.2 V (CAN_L), 5 = 2.4 V (CAN_H)** — recessive band,
   H > L under traffic averaging, matching the drawn polarity and the
   first-party Xantrex table (975-0136-01-01 Table 3, on file in
   docs/vendor/). **Repeat this measurement whenever the port or cabling
   changes** — it is the standing miswire control, not a one-time formality.
2. CAN_PWR on, TWAI in **listen-only** (no ACK — stays a pure observer),
   250 kbps. Expect Xanbus frames. J7 shunt only if the reader is a chain end.
3. Gate off → confirm the bus is unloaded (TCAN332 high-Z unpowered).

## Stage 6 — display link + system soak (R17/R18)

1. **Before attaching the Cat5e at the display end (F14):** verify the
   cable is a T568B straight-through and beep the J1 pin map at the
   display plug — 12 V on 1/2/3, A on 4, B on 5, GND on 6/7/8 (R17).
   A crossover/rolled cable shorts 12 V to GND (resettable: F1 PTC +
   battery-side foldback) but must not be left in place.
2. **Display termination: J5 shunt FITTED** — the display end is the bus
   terminus, so R2's 120 Ω must be in circuit by default (R18). Battery
   end: J4 per final topology (its terminator lifts only if the battery
   node is mid-bus). Exactly the two physical bus ends carry termination.
   R3/R4 idle bias stay **DNP** unless CP5 link testing shows RO
   glitches (F12).
3. J2/Cat5e link up: 12 V feed present (SSR1 path, PWR_EN), RS-485
   comms up; confirm display ACK-on-BREAK wake (D34 §turnaround).
4. Full-system soak: duty-cycled polling, deep-sleep floor re-measured,
   [CP5: 24 h log against power_budget.md].

## Appendix — recovery cheat-sheet

| Symptom | Path |
|---|---|
| USB dead / firmware sleeps instantly | ESP-Prog ribbon on J5 (auto-program), or jumper J5.6→J5.4 (GND) + blip J5.1 |
| No V3V3 on USB | check U5 out, then U6 VIN1/PR1/MODE bus, then Q3/Q4 (EN held low?) |
| No V3V3 on pack | F1 cartridge, D1 orientation, V24_FUSED, UVLO_RESET state (pack < 21.7 V won't release!) |
| Iso channel silent | CHx_PWR low? V_ISOINx vs ISO_BUS_GNDx? A/B swapped? (vendor: A=7, B=8) |
| No CAN frames | polarity (L=4/H=5), listen-only mode?, 250 kbps?, gate on? |

### Display-board recovery (R21 — F14)

The display Deep-sleeps between frames, so a sleeping/bricked unit is
often uncatchable over USB — same argument as battery J5. Pop the
faceplate (no wall removal) for both ports:

| Symptom | Path |
|---|---|
| Display USB dead / firmware sleeps instantly | ESP-Prog ribbon on **J3** (keyed 2×3, same map as battery J5: 1=EN, 2=VDD, 3=TXD, 4=GND, 5=RXD, 6=IO0). Auto-program via esptool, or manual force-download: **jumper J3.6→J3.4 (IO0 to GND), blip J3.1 (EN)**, then flash; confirm on the J3 console (115200) |
| Display alive but no 12 V (bench work) | **J-USB (USB-C)** powers the board alone: AP2112 → TPS2116 VIN1 priority → V3V3 (R20). Flash/console over native USB |
| No V3V3 on display | USB path: U3-LDO out → U4-MUX VIN1/PR1/MODE, C_mux; 12 V path: J1 pins 1-3 → F1 (PTC tripped? clears on power-off) → TVS1/V12_PROT → U1 |
| Display never wakes on bus traffic | J5 shunt fitted? (terminus, R18) · master BREAK ≥50 ms? · /RE latched LOW via `gpio_hold_en(GPIO15)`? · RO reaching IO18 (ext1 mask)? |
