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
4. **Recovery drill (do this NOW, not when you need it):** jumper J5.5
   (BOOT/IO0) → J5.6 (GND), blip J5.1 (EN) low, confirm the ROM downloader
   appears on J5.3/4 UART. This is the deep-sleep-proof path (R8) — verify it
   once while nothing is at stake.

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
3. Both packs, both channels: run the §7 **two-domain matrix** (float vs
   REF-pad reference). R27/R37 stay DNP unless the float fails (user call:
   populate only on evidence).
4. Confirm the ±12 V common-mode reality: measure PACK1_Bminus vs
   PACK2_Bminus at the REF pads (expect ≈ 12 V — this is WHY R1 exists).

## Stage 5 — Xanbus CAN listen (R10, DR-31)

1. **Before first attach:** on the live Schneider port, verify pins 4/5
   polarity per LYNK II §4.2.1 — recessive both ≈ 2.5 V vs network reference,
   differential ≈ 0; dominant pulses split H up / L down. Confirm NO voltage
   on pins 4/5 beyond CAN levels (NET power lives on other pins we left NC).
2. CAN_PWR on, TWAI in **listen-only** (no ACK — stays a pure observer),
   250 kbps. Expect Xanbus frames. J7 shunt only if the reader is a chain end.
3. Gate off → confirm the bus is unloaded (TCAN332 high-Z unpowered).

## Stage 6 — display link + system soak

1. J2/Cat5e to the display node: 12 V feed present (SSR1 path, PWR_EN),
   RS-485 comms up, J4 termination per final topology.
2. Full-system soak: duty-cycled polling, deep-sleep floor re-measured,
   [CP5: 24 h log against power_budget.md].

## Appendix — recovery cheat-sheet

| Symptom | Path |
|---|---|
| USB dead / firmware sleeps instantly | ESP-Prog on J5 (auto-program), or jumper J5.5→GND + blip J5.1 |
| No V3V3 on USB | check U5 out, then U6 VIN1/PR1/MODE bus, then Q3/Q4 (EN held low?) |
| No V3V3 on pack | F1 cartridge, D1 orientation, V24_FUSED, UVLO_RESET state (pack < 21.7 V won't release!) |
| Iso channel silent | CHx_PWR low? V_ISOINx vs ISO_BUS_GNDx? A/B swapped? (vendor: A=7, B=8) |
| No CAN frames | polarity (L=4/H=5), listen-only mode?, 250 kbps?, gate on? |
