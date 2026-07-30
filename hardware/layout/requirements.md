# Design requirements register (both boards)

> **Living register, created 2026-07-23.** One numbered, testable requirement
> per row. Sources: `docs/production_design.md` (vision), `decisions.md`
> (D-numbers), `hardware/reviews/DESIGN_REVIEW_ITEMS.md` (DR-numbers), and
> direct user calls. Verification classes:
> **[M]** mechanical — checked every build (`build.py` gates: readability,
> netlist intent==actual, GOLDEN contracts, footprint gate) or by
> `hardware/tools/check_requirements.py`;
> **[B]** bench — CP5 bring-up measurement (see `docs/hardware/bringup_guide.md`);
> **[R]** review — datasheet/analysis evidence on file.
>
> If a requirement changes, change it HERE first, then the design.

| ID | Requirement | Source | Verification | Status |
|----|-------------|--------|--------------|--------|
| R1 | Read both Volthium 12 V packs (24 V series stack) over their RS-485 BMS ports; the two interfaces MUST be galvanically isolated from the logic domain and from each other (series stack ⇒ ±12 V common-mode by construction) | DR-26/D36; user 2026-07-20 | [M] goldens: barrier integrity (GND1 never meets GND2; per-channel GND2_DCDC{n}/ISO_BUS_GND{n}; L2 only tie; C_stitch only bridge) · [B] DR-26 §7 two-domain float test | M ✅ / B pending |
| R2 | Battery RS-485 ports present the vendor's real interface: RJ45, A on pin 7 / B on pin 8, no ground pin | vendor-measured 2026-07-17 | [M] goldens J10/J11.7=BUS_A, .8=BUS_B | ✅ |
| R3 | Display link: half-duplex RS-485 + regulated 12 V over one Cat5e — A=4, B=5, 12 V=1-3, GND=6-8; termination liftable via jumper (J4) | D34; cat5e_pinout.md | [M] goldens J2 pinout + R10-through-J4 contract | ✅ |
| R4 | Power-first: NO continuous draws. Every non-essential subsystem power-gated, default-OFF with the MCU unpowered/high-Z (gate pull-ups to the rail, active-LOW enables) | user standing; power_budget.md | [M] goldens: Q10/Q11/Q5/Q_exp source-on-rail + gate-net + drain-isolated contracts; [M] value check: all gate pull-ups 100k | ✅ |
| R5 | Hard low-voltage cutoff: trip ≈ 20.0 V, release ≈ 21.7–21.8 V (TPS3808G01 + release-sized divider + hysteresis leg) | D28/D33, F01/F04 | [M] value check R_uv1=5.16M, R_uv2=100k, R_hys=11.5M · [B] threshold measurement | M ✅ / B pending |
| R6 | USB-C maintenance port: powers and boots the MCU with packs absent/dead; ESD-protected data lines | D22/D29/F03 | [M] goldens: U5/U6 mux chain, Q3/Q4 bypass chain, U-ESD on DP/DM/VBUS | ✅ |
| R7 | **Initial firmware load MUST work on a blank module over native USB-C alone** (ROM USB-Serial/JTAG + empty-flash download mode + R6 power path) | DR-32; user 2026-07-23 | [R] ESP32-S3 ROM behaviour + [M] R6 chain + DP/DM to MOD1 pins 13/14 · [B] first-flash | M/R ✅ / B pending |
| R8 | **Forced-download recovery MUST exist independent of the USB stack** (deep-sleep-heavy firmware can be uncatchable over USB): EN and IO0 on a keyed 2×3 IDC header in the real ESP-Prog "Program" pinout — 1=EN, 2=VDD, 3=TXD(target), 4=GND, 5=RXD(target), 6=IO0 — so the ESP-Prog ribbon mates directly | DR-32; user 2026-07-23; F01 + ESP-Prog SCH V2.1 (on file) | [M] goldens J5.1=MCU_EN, .2=V3V3, .3=DBG_TXD, .4=GND, .5=DBG_RXD, .6=BOOT(IO0) + MOD1.27=BOOT | ✅ |
| R9 | Serial console available on the same header (UART0) for bring-up/diagnostics | DR-30 | [M] runner proves the end-to-end nets: J5.3 same-net as MOD1.37 (TXD0) and J5.5 same-net as MOD1.36 (RXD0) | ✅ |
| R10 | **Listen to the Schneider Xanbus (CAN 250 kbps)**: TWAI transceiver, power-gated to zero parked draw, bus pins high-Z when unpowered, CAN_L=RJ45 pin 4 / CAN_H=pin 5, network-power pins untouched, termination in series with a jumper (fitted = chain end) | DR-31; user 2026-07-22 (approved requirements change); Xantrex 975-0136-01-01 Table 3 (first-party pinout, on file) | [M] goldens: U7/Q5/R14 gate contracts, J6.4/J6.5 polarity, R15-through-J7, NET pins NC · [R] TCAN332 DS (high-Z unpowered, ±12 V CM) · [B] pin-4/5 polarity **measured on the live SW4024 port 2026-07-25** (4=2.2 V/5=2.4 V recessive, H>L; NET_S 1/2/7=12 V, NET_C 3/6/8) — remaining [B]: CP5 listen test | M/R ✅ / B polarity ✅, listen pending |
| R11 | Timekeeping across pack loss: RTC on always-on rail + backup storage | D23 | [M] goldens RTC1 VDD/VBACKUP/C-bk + PWR_FLAG | ✅ |
| R12 | Expansion: 8-ckt header with dedicated I2C1 + 2 AIO + DIO on a switched rail, default-OFF, rail parked ≤50 mV | D37/F48/F51/F66 | [M] goldens Q_exp/J_EXP/bleed contracts · [B] parked-rail ≤50 mV | M ✅ / B pending |
| R13 | User override button, dry-circuit-rated contacts, zero unpressed draw | D-series/F22 | [M] goldens BTN1/R13 · [R] 8125 B-contact rating on file | ✅ |
| R14 | Input protection: time-lag fuse + series reverse diode + 33 V clamp on the pack input | DR-12 | [M] goldens F1/D1/TVS1 chain + [M] value check F1="1A T" | ✅ |
| R15 | Hand-assembly buildability (qty 1): leaded packages preferred; leadless only where power costs forbid alternatives, reflowed with a paste stencil | D33/DR-24; user | [R] BOM package audit (TPS2116 SOT-583 sole waiver, documented) | ✅ |
| R16 | One free GPIO margin is NOT required — budget may be fully allocated (JTAG forfeited; debug via USB + UART) | DR-31 note | [M] MCU pin map (IO40/41/42 = last free, now used) | ✅ (accepted) |

## Display-side board (added at display CP2, 2026-07-27)

| ID | Requirement | Source | Verification | Status |
|----|-------------|--------|--------------|--------|
| R17 | Display receives 12 V + RS-485 over the one Cat5e with the SAME pin map as battery J2 (12 V = 1-3, A = 4, B = 5, GND = 6-8); shield drain NC at the display end (single-point bond at battery, DR-19) | D34; cat5e_pinout.md | [M] goldens J1 pinout + SH no-connect | ✅ |
| R18 | Display end is the bus terminus: 120 Ω termination in SERIES with a lift jumper (J5, fitted default); idle-bias R3/R4 footprints present at ~330 Ω but **DNP by default** (THVD1400 Full Fail-Safe RX; CP5 bench-stuff only if EMI shows a need) | iter-12 F12; D19/DR-4 | [M] goldens R2-through-J5 + netlist dnp markers on R3/R4 | ✅ |
| R19 | Deep-sleep wake path MUST work: /RE on RTC-capable IO15 (gpio_hold LOW in sleep), RO on RTC-capable IO18, buttons on RTC-capable IO12/13/14 — one `ext1 ANY_LOW` mask over all four wake inputs; 1 MΩ button pull-ups (power-first) + 100 nF debounce | D34 F09/F15; ESP32-S3 DS Table 3-1 | [M] goldens MOD1 pin map + value checks · [B] CP5 BREAK-wake test | M ✅ / B pending |
| R20 | Display USB-C maintenance port powers and boots the MCU without 12 V (AP2112 LDO → TPS2116 priority mux; no UVLO bypass — no supervisor on this board); ESD-clamped; 5.1 kΩ CC UFP advertisement | D27/D29 | [M] goldens LDO→mux chain, U-ESD, R_cc1/2, D± to MOD1 13/14 | ✅ |
| R21 | Forced-download recovery independent of USB on the DISPLAY board too (it Deep-sleeps between frames): keyed 2×3 ESP-Prog "Program" header J3, same map as battery J5 | DR-32 (display CP2 decision) | [M] goldens J3.1-6 + MOD1.27 BOOT + end-to-end UART0 | ✅ |
| R22 | E-paper interface exactly matches the Waveshare 4.2" (B) Module: PH2.0 8-pin, canonical order VCC/GND/DIN/CLK/CS/DC/RST/BUSY on the D31 GPIO map | DR-7/F21 evidence on file | [M] goldens J2 order + MOD1 pin map + [exact-part] B8B-PH-K-S | ✅ |
| R23 | Display input protection: ~0.25 A PTC (resettable, DR-11) → SMAJ15A clamp + bulk → R-78E3.3; regulator output (V3V3_REG) reaches the system rail only through the mux | DR-11/DR-15; D29 | [M] goldens F1/TVS1/C1/U1 chain + V3V3_REG≠V3V3 | ✅ |

Exact-variant contracts for the display board (J1 Würth 615008145521 with the
manufacturer-official footprint — its tail fan-out is NON-monotone, see
`hardware/kicad/footprints/README.md` — J2 B8B-PH-K-S, J3 IDC 2×3, J-USB
USB4085-GF-A, U1 R-78E3.3-0.5, F1 MF-R025) are enforced by the build's
[exact-part] gate in `build_display.py`, not listed as separate rows.

## Verification runner

`python3 hardware/tools/check_requirements.py` re-derives every **[M]** row
from the build artifacts of BOTH boards (`build/volthium_reader.net` +
`build_display/volthium_display.net` + BOM; each build's own gate suite must
be green) and prints a per-requirement PASS/FAIL table. Run it after any
schematic change; it is the "does the design match the requirements" test.
