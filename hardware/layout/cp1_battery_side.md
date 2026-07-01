# CP1 — Battery-side board, design baseline

**Status**: draft, ready for review
**Board codename**: `volthium-bms-link`
**Mounts**: on the wall above the two batteries (air gap), user-3D-printed IP5x plastic box; board outline TBD at placement (D20)
**Function**: BLE-central to the two BMS modules, fuses readings into a
PackReading, ships RS-485 frames to the display side over Cat5e, runs the
4-tier SOC self-shutdown that protects the pack, and pushes logs over
**WiFi** (duty-cycled) to the Starlink-connected server (D25).

## 1. Scope of this document

This file is the **complete design intent** for the battery-side board
at the moment we start KiCad capture (CP2). Anything not specified here
is either (a) a stock convention noted in [`decisions.md`](decisions.md)
or (b) an open decision listed in §13 awaiting reviewer input.

Cross-references (unchanged from prior pass — read in this order):
- [`../../docs/hardware/block_diagrams.md`](../../docs/hardware/block_diagrams.md) — visual orientation
- [`../../docs/hardware/schematic_battery_side.md`](../../docs/hardware/schematic_battery_side.md) — original net intent
- [`../../docs/hardware/power_budget.md`](../../docs/hardware/power_budget.md) — per-state current budget
- [`../../docs/hardware/cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md) — Cat5e allocation
- [`../../docs/production_design.md`](../../docs/production_design.md) — system-level architecture and rationale
- [`../../docs/site/loon_lake.md`](../../docs/site/loon_lake.md) — site context driving the SOC tiers

Where this CP1 doc disagrees with the cross-references, **CP1 wins**.

## 2. Mechanical envelope

| Dimension      | Target               | Constraint source                           |
|----------------|----------------------|---------------------------------------------|
| Board outline  | **TBD — derived at CP3 placement** | Form factor unconstrained (D10/D20): "as small as comfortable, never artificially large." No pre-set size |
| Thickness      | 1.6 mm               | JLCPCB default, lowest cost                 |
| Layers         | 2 (top + bottom; **double-sided assembly OK**) | Trace counts low; 2L sufficient |
| Mounting holes | 4× M3 corner, 3.2 mm | To 3D-printed standoffs/bracket; coords set with the outline at CP3 |
| Antenna keepout | 15×6 mm at the PCB-antenna edge | ESP32-S3-WROOM-1 (**`-1`, PCB antenna** — D21) |
| Maintenance port | board-edge USB-C | Native ESP32-S3 USB, accessible without opening (D22) |

**Enclosure (D20):** user-3D-printed **plastic** box, **IP5x** (dust,
indoors), wall-mounted a short distance *above* the two batteries with
**air between** (no metal pressed against the board).

**Antenna (D21):** the `-1` module's PCB antenna sits at a board edge with
its 15×6 mm keepout (no copper/traces) at a board edge. **No special
orientation needed** — the Volthium batteries are ABS-plastic cased (no
metal pack), and the plastic box is RF-transparent. The same antenna serves
**BLE** (to the BMS, ~1–3 m) **and WiFi** (to the nearby Starlink router) —
D21/D25.

## 3. Power architecture

Per decisions.md **D19** (CP1 re-architecture). The MCU lives on an
**always-on µA-Iq rail**; the load switch sheds **only the display feed**.

```
24V pack tap
    │
    ▼
J1 [2-pin Phoenix MSTB-G-5.08, screw-clamp pluggable]    ← user lands ring lugs here
    │
    ▼
F1 [5×20 mm cartridge, 1 A time-lag (T), in clip]        ← field-replaceable
    │
    ▼
D1 [SS26 Schottky 60V, A→K]                              ← reverse-polarity protect
    │
    ├─[V24_FUSED]──────────────┬───────────────┬───────────────────┐
    │                          │               │                   │
    ▼                          ▼               ▼                   ▼
TVS1 [SMAJ33CA,           U1 [LM5166         R5/R6 divider      Q1/Q2 load switch
 V24_FUSED↔GND,           µA-Iq buck,        →V24_SENSE         (60V P/N-FET, gate-
 ~53V clamp]              24V→3V3]           (always alive)     clamped) — SWITCHED
                              │                                      │
                       ALWAYS-ON 3V3                                 ▼ V24_SW
                              │                              U2 [R-78HB12 24V→12V]
       ┌────────┬────────┬───┴─────┬──────────┐                     │
       ▼        ▼        ▼         ▼          ▼                     ▼ V12_CAT5E
   ESP32-S3   RV-3028   SN65...    R10      decoupling           J2 RJ45 → display
   (MOD1)    (RTC1)    (U3)    term Ω   (no idle bias here — display-end only)

Always-on (off V24_FUSED, never via Q1):
    U1 LM5166 → 3V3 → ESP32-S3 + RV-3028 VCC + RS-485 + sense divider
    R5/R6 sense divider → V24_SENSE → ESP GPIO1 (ADC1_CH0)
    RV-3028 VBACKUP     → small backup cap (C-bk), trickle-charged by RTC
Switched (Q1, MCU-controlled): U2 → 12V → Cat5e → the entire display side
```

**Two power domains** (D19):

| Domain         | What it powers                                          | Killed by                |
|----------------|---------------------------------------------------------|---------------------------|
| Always-on 3V3  | ESP32-S3, RV-3028 VCC, RS-485 xceiver (+ R10 term; **no idle bias — display-end only, DR-4b**), sense divider | Never (MCU deep-sleeps at low SOC) |
| Switched 12V   | U2 → Cat5e → the **entire display side**                | Q1 OFF (ESP opens it at < 10 % SOC) |

The MCU is **always powered** — it cannot sit behind the load switch: it
must stay alive to drive Q1 and to wake on voltage recovery, and a
downstream MCU can't gate its own supply (nor boot if it starts unpowered).
At < 10 % SOC the ESP deep-sleeps (~µA), periodically reads V24_SENSE, and
sheds the display by opening Q1; RS-485 is disabled via DE/RE (not
power-switched). All-in trickle at hard-cut ≈ **~1 mW** (U1 Iq ~14 µA +
sense divider ~19 µA + ESP deep-sleep). The **RV-3028-C7 RTC adds only
~45 nA** — negligible (D23 swapped out the power-hungry DS3231; see DR-8).
This replaces the pre-D19 design where the MCU sat on the switched rail and
could not boot — see DESIGN_REVIEW_ITEMS DR-3/DR-4.

### 3.1 Protection coordination — worst-case clamp vs part ratings

The defect that reached CP6 last round (DR-1/DR-2) was a protective part
out-rated by what it protected, so this coordination is derived explicitly
rather than asserted.

The highest voltage any part on V24_FUSED/V24_SW can see during a clamped
transient is the **SMAJ33CA maximum clamping voltage VC = 53.3 V** (at
IPP = 7.5 A, 10/1000 µs — Littelfuse SMAJ datasheet). Every part on that
node is rated against that ceiling:

| Part on the protected node | Voltage rating        | Margin over 53.3 V |
|----------------------------|-----------------------|--------------------|
| D1  SS26 (Schottky)        | VRRM **60 V**         | +6.7 V (**13 %**)  |
| Q1  ZXMP6A13F (P-FET)      | Vds **−60 V**         | +6.7 V (**13 %**)  |
| Q2  2N7002 (N-FET)         | Vds **60 V**          | +6.7 V (**13 %**)  |
| U1  LM5166Y buck           | VIN abs-max **65 V**  | +11.7 V (22 %)     |
| U2  R-78HB12               | VIN max **72 V**      | +18.7 V (35 %)     |
| C1, C3 input caps          | **100 V**             | +46.7 V (88 %)     |

The three **60 V** parts (D1/Q1/Q2) set the floor at **~13 % margin** — the
tightest coordination in the design. Because the clamp is a non-repetitive
transient and 60 V is an absolute-max rating, 13 % is acceptable; but it is
a hard constraint: **any substitution on this node must hold ≥ 60 V.**
(75 V/100 V parts would buy margin at higher cost/size — judged unnecessary.)
Note 53.3 V is the TVS's *full* 7.5 A pulse; the actual transient on a
1 A-fused battery tap is far smaller, so this is a conservative ceiling.

**Gate-source clamp (Q1 Vgs).** Q1 ZXMP6A13F Vgs abs-max = **±20 V**
(Diodes DS32014). Without a clamp, turning Q1 on pulls the gate toward
(source − bus) and would drive Vgs to ~−29 V at full charge — destroying
the gate (DR-4). **DZ1 = BZX84C12** across gate↔source clamps |Vgs| to the
Zener voltage **~12 V** (11.4–12.7 V) regardless of bus voltage → **~36 %
margin** under the ±20 V max across the whole range. The same 12 V fully
enhances the FET: RDS(on) is specified at Vgs = −4.5 V (600 mΩ) and −10 V
(400 mΩ), so −12 V sits in the fully-on region. The clamp therefore both
protects the gate **and** guarantees turn-on.

## 4. Component list

### 4.1 Power input

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| J1  | Phoenix **MSTBA 2,5/2-G-5,08** board header (1757242) **+ MSTB 2,5/2-ST-5,08** wire plug (1757019), 2-pin, 5.08 mm | THT 5.08 mm | 1 | Field-replaceable wiring; **pluggable** means user can disconnect the board from the pack without unscrewing wires (D19). Plug = 2-pos screw rising-cage clamp (12–30 AWG). *(Plug corrected from 1727010 — a wrong 3.81 mm MKDS terminal — per the D32 datasheet check, 2026-07-01.)* |
| F1  | 5×20 mm fuse + 2× PCB-mount clips (**1 A time-lag "T"**, e.g. Littelfuse 0215001.MXP) | THT clip      | 1 | Cartridge fuses are universally stocked; pops out for replacement. **Time-lag, not fast-blow (DR-12):** tolerates the µs-scale ~22 µF ceramic inrush (I²t ≈ 0.06–0.13 A²s) without nuisance-tripping, while still clearing the ~45 mA steady load and a hard short |
| D1  | SS26 Schottky (60 V, 2 A, low Vf)   | **DO-214AA (SMB)** | 1 | Reverse-polarity protection; 60 V out-rates the ~53 V clamp (D19/DR-3). Vf ~0.4 V, ~20 mW dissipation. **Package SMA → SMB (SS26-E3/52T is DO-214AA; API 2026-06-25)** |
| TVS1 | SMAJ33CA bidirectional TVS (Vrwm 33 V) | SMA       | 1 | Clamps 24 V transients; 33 V Vrwm clears the ~29 V full-charge bus with margin (D19/DR-2). Clamps ~53 V — every part on V24_FUSED/V24_SW is rated ≥60 V to suit |

**Change from existing BOM**: removed `1 A ATO fast-blow fuse + holder` +
`ring terminals`. Added cartridge fuse + clip + Phoenix terminal block.
TVS1 on the 24 V input is **SMAJ33CA** (D19/DR-2); D1 is a **60 V** SS26
so the protected rail out-rates the clamp (D19/DR-3).

### 4.2 Power conversion

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| U1  | **LM5166YDRCR** (24 V→3.3 V sync buck, **always-on**, **fixed-3.3 V** variant — FB→VOUT, no divider) | VSON-10 | 1 | **~14 µA Iq**, 3–65 V in (65 V out-rates the 53.3 V clamp, §3.1), **500 mA** — enough to power a **WiFi session** (D25); a brick can't be both µA-Iq *and* surge-tolerant (D19/DR-4). **Suffix trap (reviewer Finding 01): `LM5166Y` = 3.3 V, `LM5166X` = 5 V** — order **Y**DRCR; the X variant would force the ESP rail to ~5 V (destructive). FB→VOUT, no divider. TI Active; **confirm live stock at BOM-lock** (TI.com showed YDRCR out-of-stock on 2026-06-21 — fallback `LM5166YDRCT` cut-tape, else adjustable `LM5166DRCR` + high-Z divider; never XDRCR) |
| L1  | 10–47 µH ≥0.3 A shielded SMD inductor | per datasheet | 1 | LM5166 buck inductor; low-Iq COT mode favors a larger L than a fast buck |
| C1, C2 | C1 22 µF / **100 V**, C2 22 µF / 25 V X7R | 1210      | 2   | LM5166 input (C1 on V24_FUSED, behind the ~53 V clamp → 100 V) / output (C2, 3.3 V) |
| U2  | Recom R-78HB12-0.5 (24 V→12 V, 0.5 A, 17–72 V in) | SIP3 THT | 1   | **Switched** (behind Q1) — drives the Cat5e/display. 72 V in tolerates the ~53 V clamp (D19/DR-3). Was R-78E12 (34 V, under-rated) |
| C3, C4 | C3 22 µF / **100 V**, C4 22 µF / 25 V X7R | 1210      | 2   | U2 input (C3 on V24_SW, behind the clamp → 100 V) / 12 V output (C4) |
| TVS3 | SMAJ15A unidirectional TVS, V12_CAT5E ↔ GND (at J2) | SMA | 1 | **DR-15:** clamps surges induced on the long in-wall Cat5e **12 V power pair** at the **battery** end — matches the display-end SMAJ15A so both ends of the exposed pair are protected (standard for long DC runs). Standoff 15 V > 12 V; zero static draw (conducts only on a transient). U2's 72 V VIN and the always-on rail are upstream/unaffected |

**Regulator thermals (worst case, no heatsink).** Both converters are
switchers, so dissipation is conversion loss — and both run far below rated
load:

- **U1 LM5166Y (24→3.3 V, always-on).** Worst case is a WiFi push: ~250 mA
  at 3.3 V = 0.83 W out; at ~85 % efficiency, loss ≈ 0.83·(1/0.85 − 1) ≈
  **0.15 W**. VSON-10 θJA ≈ 50 °C/W → **ΔT ≈ 7 °C**, and only for the
  ~2–6 s burst; steady normal load (~75 mA) dissipates ~0.04 W → ΔT ~2 °C.
  Non-issue. (The exposed-pad VSON wants a few thermal vias to the GND
  pour — standard practice, not heatsinking.)
- **U2 R-78HB12-0.5 (24→12 V, switched).** The display draws only ~5 mA avg
  / tens-of-mA peak at 12 V (power_budget.md) ≈ 0.06 W out — **~1 %** of the
  module's 0.5 A / 6 W rating; loss ≈ 0.015 W. Recom's derating allows full
  6 W to ~50 °C ambient unheatsinked, so at ~1 % load there is effectively
  no rise. (The "~0.3 A" in the Q1 row below is turn-on **inrush** into U2's
  input cap, not steady load — it does not change the thermal picture.)

Neither regulator needs heatsinking; the always-on rail's thermal is
dominated by the brief WiFi burst (~7 °C).

**U1 500 mA headroom vs WiFi peak (reviewer Finding 03).** The 3V3 rail is
sized so the **worst-case simultaneous peak stays ≤ 500 mA**:

- ESP32-S3 WiFi: ~150–250 mA sustained during a push, with sub-ms TX peaks
  to ~350–500 mA.
- U3 SN65HVD3082E: ~0.4–1 mA idle/receive; only the *driver actively
  transmitting into a terminated bus* approaches tens of mA.
- RV-3028 ~45 nA, sense ~22 µA — negligible.

**Firmware policy (D25):** the WiFi push and RS-485 transmit are **mutually
exclusive** — during the ~2–6 s WiFi session the firmware holds U3 in
**driver-disable / receive-idle** (DE low), so the transceiver is never
sourcing bus-drive current while WiFi peaks. Net simultaneous load is then
**ESP-dominated and within the 500 mA rating**; the only excursions above it
are **sub-millisecond** TX peaks, which **C2 (22 µF)** buffers (size per the
LM5166 datasheet at CP2). Even if a peak briefly hits the LM5166 current
limit, foldback on a duty-cycled, seconds-long session is benign (the rail
sags momentarily, not a fault). **CP2 action:** scope the combined peak and
confirm ≤ 500 mA with the policy active; if margin < 10 %, document the
foldback explicitly. The 530 mA "driver-active + WiFi-peak" case is
**designed out by the mutual-exclusion policy**, not left implicit.

### 4.3 Hard-cut load switch

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| Q1  | ZXMP6A13F (P-MOSFET, Vds −60 V, 0.9 A, SOT-23) | SOT-23 | 1 | Load switch for the 12 V/display feed (~0.3 A). **60 V** Vds survives the ~53 V clamp when open (D19/DR-4); AO3401A (30 V) did not. In stock @ DigiKey, Active (2026-06-17) |
| Q2  | 2N7002 (N-MOSFET, Vds 60 V, drives Q1 gate) | SOT-23 | 1 | **60 V** because its drain follows the V24 rail (up to the clamp) when Q1 is off (D19/DR-4); AO3400A (30 V) did not |
| DZ1 | BZX84C12 (12 V Zener, Q1 gate–source clamp) | SOT-23 | 1 | Holds Q1 Vgs ≤ 12 V regardless of bus voltage — without it, turning Q1 on drove Vgs to −29 V (D19/DR-4) |
| Rg  | ~1 kΩ series gate (Q2 drain → Q1 gate) | 0805    | 1   | Limits gate transient current; works with DZ1 |
| R3  | 100 kΩ pull-up: Q1 gate → V24_FUSED | 0805          | 1   | Default-OFF behavior — pack-safe on MCU lockup |
| R4  | 100 kΩ pull-down: Q2 gate → GND     | 0805          | 1   | Defines Q2 state when MCU GPIO floats (boot / brown-out) |

**Power-first note on R3 sizing**: a 10 kΩ pull-up (as in the original
SKiDL) draws 24 V / 10 kΩ = 2.4 mA continuously while Q1 is OFF —
substantial. Increased to 100 kΩ (24 V / 100 kΩ = 240 µA). Q1's gate
capacitance is ~330 pF; even at 100 kΩ the RC turn-OFF time is
~33 µs, plenty fast for a load switch.

### 4.3a UVLO backstop — hardware low-pack supervisor (D28 / DR-16)

Independent hardware floor below the firmware's smart shed. Protects against
a **hung-but-powered** MCU (~38 mA, the dominant low-SOC load) that the
firmware-only shed + R3 default-OFF do **not** cover (R3 only handles a
*dead* MCU).

| Ref | Part | Pkg | Qty | Rationale |
|-----|------|-----|-----|-----------|
| U4  | **TI TPS3808G01DBVR** voltage supervisor (~2.4 µA Iq, adj SENSE, open-drain RESET, prog. CT delay, +MR) | **SOT-23-6 (leaded ✓)** | 1 | Asserts ESP **EN** low when the pack droops below the hardware floor. Powered from always-on V3V3. **Repackaged WSON→SOT-23-6 for hand-assembly (D33/DR-24)** — functional superset, ~same Iq |
| R_uv1 (top), R_uv2 (bottom) | pack divider → U4 SENSE. **VIT = 0.405 V** (TPS3808G01, datasheet-confirmed). For a ~20 V trip: R2/(R1+R2) = 0.405/20 = **0.02025** → **R1 ≈ 4.87 MΩ, R2 ≈ 100 kΩ** (E96 → trip ≈ 20.1 V) | 0805 ×2 | 2 | From V24_FUSED. **ISENSE ±25 nA max** → divider current ≥ 100× = **≥ 2.5 µA**; 0.405 V/100 kΩ = 4.05 µA at trip ✓. The lower 0.405 V threshold lets the high-R divider draw *less* (~4.8 µA at 24 V) than the old 2.89 V/2.0 MΩ part. Add a small SENSE filter cap for the high-Z node. |
| R_hys | external hysteresis: U4 RESET → SENSE | 0805 | 1 | **F01/D33:** the TPS3808G01 *built-in* VHYS is only **1.5 % of VIT** (≈6 mV at SENSE, ~0.3 V at pack) — too small, would chatter. R_hys sets a deliberate band: ΔV_trip ≈ V_RESET(3.3 V) × R1/R_hys → **~1.3 V band** (trip ~20.1 V / release ~21.3 V). Finalize at CP2 |
| C_ct | CT delay cap (deglitch, ~tens of ms) | 0603 | 1 | Rejects momentary sags so only a sustained low-pack condition trips the floor |

**How it acts (reuses the existing default-OFF chain — no extra Q1 driver):**
U4 RESET (open-drain) ties to the **EN/RESET# node** (already pulled up by
R7). Below the floor it pulls EN low →
1. the ESP drops to its ~µA reset state — **kills the ~38 mA hung drain**, and
2. a reset ESP floats **GPIO4 (PWR_EN) Hi-Z → R4 holds Q2 OFF → R3 holds Q1
   OFF → display shed** — automatically.

On recovery (pack ≥ release threshold + hysteresis) U4 releases EN → the ESP
**cold-boots fresh** (un-hangs) and resumes. Asserting **EN, not power**,
keeps the MCU wakeable (D19 intact; DR-4 not reopened).

**Thresholds:** trip ~**20 V** pack (LiFePO₄ cliff, well below the firmware's
~10 % SOC shed); release ~**21.3 V** set by the **external** hysteresis
resistor R_hys (reviewer F01 — the chip's built-in band (~0.3 V at pack) is
too small and would chatter, since shedding the ~38 mA load rebounds the pack
well past that). The two layers never fight — staggered voltages; the hardware floor
is silent in normal operation. **Override button:** the hardware floor wins
(can't force-drain a dead pack). CP2: confirm on the bench that release +
deglitch give a clean single re-engage (no oscillation).

**Power (F02/D33):** divider ~4.8 µA at 24 V (~5.9 µA at 29 V full charge →
~0.17 mW) + U4 Iq ~2.4 µA ≈ **~0.25 mW** — the 0.405 V part's high-R divider
draws less than the old 2.89 V/2.0 MΩ one while still satisfying the ≥100×
ISENSE rule. **Hard-cut now ≈ 1.1 mW**; ~5 orders of magnitude under any
meaningful pack drain. The EN-asserted floor (~µA, chip in reset) is still
*lower* power than the firmware deep-sleep it backstops.

### 4.3b USB maintenance power (run/program/troubleshoot off USB) — D29 / DR-18

Lets the USB-C port power the MCU for bring-up, flashing, and field
troubleshooting **without a 24 V supply** — integrated so it draws **zero**
from the pack when unplugged (all VBUS-referenced) and leaves the UVLO and
hard-cut budget intact.

| Ref | Part | Pkg | Qty | Rationale |
|-----|------|-----|-----|-----------|
| U5  | 3.3 V LDO (e.g. AP2112K-3.3, ~600 mA) | SOT-23-5 | 1 | VBUS (5 V) → 3V3_USB. **Powered from VBUS only** — no pack draw when unplugged. ~600 mA covers programming + occasional WiFi |
| U6  | **TI TPS2116DRLR** 2-input priority power mux (1.6–5.5 V, 2.5 A, ~1.3 µA Iq / 50 nA standby, auto-switchover, reverse-blocking) | **SOT-583 (leadless ⚠)** | 1 | **VIN1 (priority) = 3V3_USB, VIN2 = U1 buck 3V3, OUT = V3V3.** USB present → output from USB, buck idles; USB absent → buck. Reverse-blocking N-FETs (no Schottky drop). **Package SOT-583, not SOT-23 (API 2026-06-25)** — leadless, see DR-24 |
| Q3  | small signal N-FET, **series in U4 RESET→EN** | SOT-23 | 1 | **Default-ON (UVLO active) — fail-safe (reviewer F03):** gate pulled to **V3V3 via R_byp1 (100 kΩ)** so with VBUS **absent** Q3 conducts → U4 drives EN → UVLO active. When VBUS **present**, Q4 pulls the gate LOW → Q3 opens → U4 isolated → MCU boots off USB on a dead/absent pack. Q3 Rds (~7 Ω) ≪ R7 (10 kΩ) → no effect on the assert level |
| Q4  | small signal N-FET, **VBUS-driven gate pulldown** | SOT-23 | 1 | **NEW (reviewer F03):** VBUS (via R_byp2 divider) turns Q4 ON → pulls Q3 gate to GND → opens the bypass. VBUS absent → Q4 OFF → Q3 stays default-ON. Draws from VBUS only |
| C_usb1, C_usb2 | LDO in/out caps (1 µF / 1 µF) | 0603 | 2 | per AP2112 datasheet |
| R_byp1 | Q3 gate pull-up to **V3V3** (100 kΩ) | 0805 | 1 | sets the fail-safe default-ON; only carries current when Q4 pulls low (VBUS present) → ~0 always-on draw when unplugged |
| R_byp2 | VBUS → Q4 gate divider | 0805 | 1 | VBUS-referenced |

**Behavior.** USB present → TPS2116 selects 3V3_USB → the LM5166 sees its
output held high → **stops switching → pack draw ≈ its ~14 µA Iq** (MCU now
on USB); Q4 (VBUS-driven) pulls Q3's gate low → Q3 opens → U4 isolated from
EN → MCU boots even on a dead/absent pack (bench). USB absent → mux falls
back to the buck; Q4 OFF → Q3 default-ON via the 100 kΩ to V3V3 → U4 drives
EN → V3V3 and the UVLO behave **exactly as without this circuit**.

**Bypass truth table (fail-safe — reviewer F03):**

| VBUS | Q4 | Q3 (series in U4→EN) | UVLO |
|------|----|----------------------|------|
| absent (unattended) | OFF | **ON** (gate→V3V3) | **active** — the safe default |
| present (attended)  | ON  | OFF (gate→GND)     | bypassed — MCU runs off USB |

**Why no requirement is compromised:** every part except U6 is
**VBUS-referenced → 0 pack draw unplugged** (R_byp1 only carries current when
Q4 pulls it low, i.e. VBUS present); U6 adds only **~1.3 µA** always-on
(~4 µW). With the F02 UVLO-divider resize, **hard-cut ≈ 1.3 mW** (still
negligible). UVLO protects the *unattended* (always USB-absent) system fully;
the bypass relaxes it only during *attended* USB sessions, when the MCU is on
USB and isn't draining the pack. No 5 V reaches V3V3 (LDO). D19 always-on
unchanged. **Residual (accepted):** attended USB + low pack + firmware
enabling the display could drain the pack via U2 — attended/transient.

**Display side** mirrors U5 + U6 (VIN2 = R-78E3.3 output); **no Q3** (the
display has no UVLO). See `cp1_display_side.md`.

### 4.4 24 V sense (always-on)

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| R5  | 1.2 MΩ 1 % (top of divider)          | 0805          | 1   | Iq ≈ 24 V / 1.3 MΩ ≈ 18.5 µA (~22 µA at 29 V full charge). Was 100 kΩ → 220 µA |
| R6  | 100 kΩ 1 % (bottom of divider)       | 0805          | 1   | Ratio 100 k / 1.3 M: full charge 29.2 V → **2.25 V**, nominal 24 V → 1.85 V — inside the ESP ADC's linear band (DR-6) |
| C5  | 100 nF X7R (sense filter + ADC tank) | 0603          | 1   | Anti-aliasing + S/H tank; Thevenin source R5‖R6 ≈ 92 kΩ, so RC ≈ 9.2 ms (corner ~17 Hz) — slow vs transients, ideal for SOC. **Load-bearing for ADC settling (§4.4); do not reduce below 100 nF** |

**Power-first commentary**: increasing the divider impedance from
100 kΩ/11 kΩ to 1.2 MΩ/100 kΩ trades 220 µA for ~19 µA on the
permanently-alive path. **This is the single biggest power optimization
in the design.**

**ADC range (DR-6)**: the ratio is set so **full charge (~29.2 V) maps to
~2.25 V** — inside the ESP32-S3 ADC's linear region. The ADC compresses
above ~2.45 V at 12 dB attenuation, so the earlier 1 MΩ/110 kΩ ratio (full
charge → ~2.9 V) would have been *least* accurate exactly at the top of
the pack, where SOC math leans hardest. **Surge is inherently safe**: the
TVS clamps V24_FUSED to ~53 V, and the 1.2 MΩ top resistor limits the
ADC-pin fault current to (53 − 3.6)/1.2 MΩ ≈ 41 µA, which the ESP's
internal ADC clamp diodes sink — no extra clamp part needed.

**ADC accuracy**: Espressif's
[ESP32-S3 Hardware Design Guidelines (ADC section)](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32s3/schematic-checklist.html)
recommend a 100 nF cap on every ADC input (C5 here does that). On source
impedance:

- Divider Thevenin source: 1.2 MΩ ‖ 100 kΩ ≈ 92 kΩ
- Tank cap C5 = 100 nF on the ADC node
- ADC S/H cap (~10 pF) draws from C5, not directly from the divider — so
  per-sample SAR settling is dominated by C5, not the divider impedance

For SOC monitoring at ≤1 Hz sample cadence, the tank cap is fully
settled between samples and ADC reads should match a DMM within
calibration tolerance. Transient detection (load surges, inrush during
charging) is via the BMS-reported `pack_i` over BLE, not this ADC.

**CP2 validation TODO**: measure ADC reading vs DMM across the full
pack-voltage range (20.0 V → 29.2 V) and verify error ≤ 1 %. If error
exceeds 1 %, drop divider impedance (e.g. 470 kΩ/39 kΩ) or buffer.

### 4.5 MCU & support

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| MOD1 | ESP32-S3-WROOM-1-N16R8 (16 MB flash, 8 MB PSRAM, onboard antenna) | SMD module | 1 | BLE 5, light-sleep ~7 µA, dual-core, ULP-RISC-V. **D-OPEN-1 candidate confirmed**: 8 MB PSRAM is overkill for this task (firmware ~256 KB) — consider downgrading to ESP32-S3-WROOM-1-N8 (8 MB flash, no PSRAM) for ~$1.50 savings; reviewer to weigh |
| C6  | 10 µF X7R (ESP bulk, near 3V3 pin)  | 0805          | 1   | Per Espressif WROOM-1 reference design |
| C7  | 100 nF X7R (ESP decoupling, ≤3 mm from 3V3 pin) | 0402 | 1 | Per Espressif reference; 0402 because it has to be **very** close (0603 OK if no 0402 stocked) |
| C8  | 1 µF X7R (EN pin filter)            | 0603          | 1   | Soft-start; Espressif notes 470 nF–1 µF on EN |
| R7  | 10 kΩ EN pull-up                    | 0805          | 1   | EN to V3V3 |
| RTC1 | **Micro Crystal RV-3028-C7** (45 nA ultra-low-power I²C RTC, integrated 32.768 kHz crystal) | 4-pin SMD 3.2×1.5 mm | 1 | **D23:** ±1 ppm RT / ±3 ppm range; built-in backup switchover + trickle charger. **45 nA** → the RTC is no longer a meaningful load (was RV-3028 ~0.2 mA / ~0.5 mW; DR-8). −40…+85 °C |
| C-bk | **Low-leakage backup cap ~10–50 mF** (ceramic/tantalum, **not a supercap**) on RV-3028 VBACKUP | SMD | 1 | Trickle-charged by the RTC; rides a full pack disconnect (45 nA → weeks). **≤50 mF, low-leakage (DR-23, reviewer F09):** a 0.1 F supercap's ~µA leakage would dwarf the 45 nA RTC and *shorten* hold time. No coin cell, no D14 short risk |
| C9  | 100 nF X7R (RTC decoupling)         | 0603          | 1   | RV-3028 datasheet recommends 100 nF on V_CC |
| R8, R9 | 4.7 kΩ I²C pull-ups (to V3V3) | 0805 ×2       | 2   | Standard I²C bias; 4.7 kΩ sits in the 1–10 kΩ window for 100/400 kHz I²C |

### 4.6 RS-485 interface

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| U3  | SN65HVD3082E (3.3 V, half-duplex, ESD)  | SOIC-8     | 1   | 30 µA Iq, slew-rate-limited (low EMI). On the **always-on** rail; the ESP shuts it to ~µA via DE/RE when idle. **D-OPEN-2** flagged; alternatives MAX3485 (higher Iq), ISL3170E (lower Iq). Recommend keeping SN65HVD3082E |
| R10 | 120 Ω 1 % termination, A↔B          | 0805          | 1   | This end is one terminus; populate by default (display side is the other terminus, also populated) |
| TVS2 | SMAJ12CA bidirectional (A↔B)         | SMA           | 1   | Differential surge clamp on the RS-485 wires |
| C10 | 100 nF X7R (U3 decoupling)           | 0603          | 1   | |

**Power-first note (D19/DR-4)**: the bus idle-bias resistors are **on the
display end only** (resized to ~330 Ω there — see cp1_display_side.md), not
here. The reason: the battery 3V3 rail is now *always-on*, so a ~2.3 mA
battery-side bias would draw continuously and blow the ~1 mW hard-cut
budget (~8×). Putting bias on the display end means it is sourced from the
display's 3V3 — which is shed with the display at low SOC — so the
battery always-on rail carries **zero** RS-485 static draw. The battery
keeps only the terminator (R10, no static draw) and the transceiver (U3,
~µA in DE/RE shutdown). Idle bias is present whenever the display is
powered (i.e. whenever the link is actually used).

### 4.7 User input & visible status

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| BTN1 | Panel-mount pushbutton, NO, momentary, SPST (e.g. E-Switch RP3502MA series) | Panel-mount (off-PCB lead) | 1 | Hardware-override for the load switch; mounts through the enclosure lid |
| R13 | 1 MΩ pull-up: BTN signal → V3V3   | 0805          | 1   | High-value pull-up minimizes Iq while ESP GPIO7 is in RTC-wake state. ESP32-S3 GPIO leakage is ~50 nA → divider error is negligible |
| C11 | 100 nF X7R debounce                 | 0603          | 1   | RC = 100 ms — slow but the user is pressing a physical button, not racing |

**Change from existing BOM/SKiDL**: removed `LED1 + R_led` (debug LED).
Per [D4](decisions.md#d4), no idle indicator LEDs. The ESP32-S3 has a
USB-C connector for dev builds; that's the debug path, not a board LED.

If a "thing is alive" indicator is wanted, a future hardware revision
could add an LED on a GPIO that the firmware pulses (e.g. 50 ms ON every
30 s; ~0.5 % duty cycle keeps average draw <50 µA). **Not in CP1.**

### 4.8 Connectivity

| Ref | Part                                | Pkg            | Qty | Rationale |
|-----|-------------------------------------|----------------|-----|-----------|
| J2  | RJ45 modular jack with integrated PoE-style hood (e.g. Amphenol RJHSE-538X) | THT shielded | 1 | T568B straight-through pinout (see [`cat5e_pinout.md`](../../docs/hardware/cat5e_pinout.md)); shield drain to chassis ground at this end |
| J3  | **USB-C receptacle** on native ESP32-S3 USB (D+/D−, VBUS, GND, CC) | SMD | 1 | **D22:** board-edge maintenance port — flash + console + JTAG over native USB, accessible without opening (IP5x dust cap). Replaces the old dev-only pin header |
| J4  | 2-pin 2.54 mm jumper (RS-485 term lift) | THT | 1 | Allows R10 to be lifted via removable jumper if the board ever sits mid-bus instead of at the terminus |
| J5  | 4-pin 2.54 mm pin header, **debug UART** (TX/RX/GND/RESET#) | THT | 1 | FTDI cable lands here; ESP-IDF console at 115200 8N1 |

### 4.9 Passives summary

Total: 4× 1210 caps (bulk), 2× 0805 caps (bulk + EN filter), 5× 0603 caps
(decoupling + debounce + sense filter), 10–12 resistors mostly 0805,
1× 0805 (R3, R4, R5, R6, R10, Rg) and 0603 (RTC pull-ups, EN, button).

## 5. Net list

| Net          | Voltage     | Source                | Sinks                                         | Notes |
|--------------|-------------|-----------------------|-----------------------------------------------|-------|
| V24_RAW      | 24–28 V     | J1 pin 1             | F1                                            | Pack tap, unfused |
| V24_FUSED    | 24–28 V     | D1 cathode           | Q1 source, R5 top (sense divider), R3 (Q1 gate pull-up), TVS1, **R_uv1 (UVLO divider top)** | Always-alive 24 V rail (post-fuse, post-reverse). Loads: load-switch input, sense divider, gate pull-up, TVS clamp, and the ~4.9 MΩ UVLO divider (~4.8 µA, D28/D33) — minimal idle draw |
| V24_SW       | 24–28 V     | Q1 drain             | R-78HB12 VIN (U2) only                         | Switched 24 V branch downstream of the load switch. Feeds **only** U2 (12 V/display). Collapses when PWR_EN is LOW/Hi-Z — sheds the display, **not** the MCU |
| V3V3         | 3.3 V       | **TPS2116 OUT (U6)** — sources: U1 buck (VIN2) / USB-LDO U5 (VIN1, priority) | ESP3V3, RTC VCC, U3 VCC, U4 VDD, R8/R9, R13, C6/C7/C8 | **Always-on** 3.3 V (D19). USB present → from USB-LDO (buck idles); USB absent → from buck. Powers the MCU in every state; never gated. No RS-485 bias here (display-end only) |
| 3V3_USB      | 3.3 V       | U5 LDO (from VBUS)   | TPS2116 VIN1 (U6)                             | USB maintenance rail (D29); present only when a cable is plugged in; VBUS-referenced |
| VBUS         | 5 V (USB)   | J3 VBUS              | U-ESD, U5 VIN, R_byp2 (Q4 gate)               | Present only with a USB cable; powers U5 + the UVLO-bypass driver Q4 (D29). Q3 gate defaults ON via R_byp1→V3V3 (fail-safe; reviewer F03) |
| V12_CAT5E    | 12 V        | R-78HB12 VOUT (U2)   | J2 RJ45 pins 1/2/3, C4, **TVS3**              | Powers display side over Cat5e; off when Q1 sheds it. TVS3 clamps cable surges at this end (DR-15) |
| GND          | 0 V         | (chassis)            | every IC GND, J2 pins 6/7/8, chassis stud near J2 | Single-point shield-drain bond at J2 |
| V24_SENSE    | 0–2.3 V     | R5/R6 midpoint       | ESP IO1 (ADC1_CH0)                            | Always-alive; 1.2 M/100 k divider → ~2.25 V at full charge (DR-6) |
| I2C_SDA      | 3.3 V LV    | ESP IO5 ↔ RTC SDA    | R8                                            | Pull-up R8 to V3V3 |
| I2C_SCL      | 3.3 V LV    | ESP IO6 ↔ RTC SCL    | R9                                            | Pull-up R9 to V3V3 |
| UART_TX_3V3  | 3.3 V LV    | ESP IO17             | U3 D pin                                       | UART1 TX → RS-485 driver input |
| UART_RX_3V3  | 3.3 V LV    | U3 R pin             | ESP IO18                                       | UART1 RX ← RS-485 receiver output |
| DE_RE        | 3.3 V LV    | ESP IO2              | U3 DE & RE pins (tied)                         | Active-HIGH = transmit; LOW = receive |
| RS485_A      | 0–5 V diff  | U3 A pin             | J2 pin 4 (blue), R10, TVS2                     | Differential pair (bias is display-end only) |
| RS485_B      | 0–5 V diff  | U3 B pin             | J2 pin 5 (white-blue), R10, TVS2               | (paired with A) |
| PWR_EN       | 3.3 V LV    | ESP IO4              | Q2 gate, R4 pull-down to GND                  | **Active-HIGH**: HIGH = rails ON; LOW or Hi-Z = rails OFF. Canonical truth table in §8 |
| BTN_OVERRIDE | 3.3 V LV    | BTN1 + R13           | ESP IO7 (RTC-wake capable)                    | Active-LOW; pulled HIGH by 1 MΩ |
| RTC_BACKUP   | ~3.0 V      | C-bk (backup cap)    | RTC1 VBACKUP                                  | RTC ride-through (trickle-charged by RV-3028) |
| RESET#       | 3.3 V LV    | ESP EN pin / J5 pin 4 | **U4 RESET via Q3**                           | Pulled HIGH via R7 + C8 (RC soft-start); **U4 (UVLO, D28) pulls it LOW below the ~20 V floor** → ESP reset → display auto-sheds. **Q3 (D29) opens this path when VBUS present** → UVLO bypassed so the MCU boots off USB on the bench |

## 6. ESP32-S3 pin assignment

Inherits from [`schematic_battery_side.md`](../../docs/hardware/schematic_battery_side.md)
with one change: GPIO15 (debug LED) is now **unused** (D4 — no LEDs).
GPIO15 becomes an expansion pad on J3.

| GPIO    | Direction | Function                  | Sleep behavior              |
|---------|-----------|---------------------------|------------------------------|
| GPIO0   | (strap)   | Bootloader strap; weak pull-up | -                        |
| GPIO1   | analog in | **V24_SENSE ADC (ADC1_CH0)** | ULP-wakeable in deep sleep |
| GPIO2   | output    | RS-485 DE/RE              | Hi-Z in deep sleep           |
| GPIO3   | (strap)   | USB-JTAG select; leave NC | -                            |
| GPIO4   | output    | **PWR_EN** (active-HIGH rail enable) | Latches via RTC-GPIO; default state at reset is LOW (rails OFF — safe). Firmware drives HIGH after boot to bring rails up |
| GPIO5   | I²C SDA   | RV-3028                    | Hi-Z; OK because RTC is on its backup cap |
| GPIO6   | I²C SCL   | RV-3028                    | "                            |
| GPIO7   | input, RTC | **BTN_OVERRIDE** (deep-sleep wake) | RTC-GPIO wake source     |
| GPIO15  | (expansion) | brought to J3, not used   | -                            |
| GPIO17  | UART1 TX  | to SN65HVD3082 D pin      | Hi-Z in deep sleep           |
| GPIO18  | UART1 RX  | from SN65HVD3082 R pin    | Hi-Z in deep sleep           |
| GPIO19/20 | USB DM/DP | USB-C (J3 dev header)  | Hi-Z; not connected to bus when not in use |
| GPIO45  | (strap)   | VDD_SPI strap; leave NC   | -                            |
| GPIO46  | (strap)   | Boot-mode strap; leave NC | -                            |

All other GPIOs left unused; available for expansion (temperature probe,
extra LED, etc.) via J3.

## 7. Power budget per state

Computed for **D19 part choices**: U1 LM5166 always-on µA-Iq buck,
1.2 MΩ/100 kΩ sense divider, no debug LED, P-FET load switch on the
**switched display-feed branch only** (§8), V12 policy split between
deep-sleep (alive) and hard-cut (off) — see [§13 D-OPEN-7a/7b](#13-open-decisions-for-reviewer).

| State | SOC band | Subsystem draws (at 24 V end) | Pack draw | Notes |
|-------|----------|--------------------------------|-----------|-------|
| 1 — Normal | > 25 % | ESP active BLE ~38 mA + U3 ~0.5 mA + RTC <100 µA + **display-end** RS-485 bias (via Cat5e) ~1.5 mA + rest of display side ~5 mA + sense 22 µA = 45 mA × 24 V | **~1.08 W** | ±2 % vs power_budget.md. **No battery-side idle bias (DR-4b)** — the ~1.5 mA is sourced at the display end and shed with the display at hard-cut |
| 2 — Low SOC | 15–25 % | ESP polled BLE ~15 mA + **display-end** RS-485 bias (via Cat5e, shed at hard-cut) ~1.5 mA + display unchanged + sense 22 µA | **~0.30 W** | — |
| 3 — Deep sleep | 10–15 % | ESP ULP+RTC ~50 µA + RV-3028 ~45 nA (negligible; D23) + display ~5 mA at 24 V conv. + sense 22 µA | **~0.13 W** | Display still up (Q1 ON) |
| 4 — Hard cut | < 10 % | U1 LM5166 Iq ~14 µA + ESP deep-sleep ~10 µA + sense divider ~19 µA + **RV-3028-C7 RTC ~45 nA (negligible)**; display shed (Q1 OFF) | **~1 mW** | RTC swapped DS3231→RV-3028-C7 to kill the ~0.5 mW always-on draw (D23/DR-8). MCU re-engages on recovery (D19) |

State 4 budget: at ~1 mW, decades to lose 1 % SOC from the monitor alone —
self-discharge dominates. A literal full cut + supervisor could reach
~0.7 mW; D19 judged the extra part not worth it.

## 8. Load switch (display-feed shed) behavior

**Topology** (D19/DR-4): a P-FET high-side load switch on the **switched
branch only** — it gates U2 (the 12 V/display feed), **not** the MCU. The
MCU rail (U1 LM5166) is always-on and never behind Q1. Q1 (ZXMP6A13F,
60 V P-FET) passes V24_FUSED → V24_SW; Q2 (2N7002, 60 V N-FET) drives Q1's
gate from ESP GPIO4 (`PWR_EN`, active-HIGH); DZ1 (12 V Zener) + Rg clamp
Q1's gate-source voltage.

```
V24_FUSED ──┬──── ALWAYS-ON: U1 (LM5166 → 3V3 MCU rail), TVS1, R5/R6, R3
            │
            │  R3 [100 kΩ gate pull-up → source]   DZ1 [12V] clamps Vgs
            ▼
         Q1 [P-FET 60V] ──── V24_SW ──► U2 (R-78HB12 → 12V → Cat5e → display)
              │
              gate ◄── Rg [~1k] ◄── Q2 [N-FET 60V] drain
                                        source ── GND
                                        gate   ◄── PWR_EN (ESP IO4) + R4 [100 kΩ pulldown]
```

**State table** (Q1 gates the display feed only — the MCU stays up regardless):

| PWR_EN (ESP IO4) | Q2 | Q1 | Display feed | Notes |
|------------------|----|----|--------------|-------|
| LOW (reset/boot default) | OFF | OFF | OFF | Display off at boot; the MCU is *already running* on its always-on rail and drives PWR_EN HIGH when it wants the display up |
| HIGH (3.3 V)     | ON  | ON  | ON  | Normal — display powered |
| Hi-Z (brown-out) | R4 pulls Q2 OFF | OFF | OFF | Failsafe — display feed drops; the MCU rides through on its own rail |

**Why this topology** (D19/DR-4):
- The MCU is **always-on**, so it boots unconditionally and is never gated
  by Q1. (A downstream MCU could neither boot from cold nor gate its own
  supply — the core pre-D19 defect.)
- Q1 sheds only the sheddable load (U2 → 12 V → display). At < 10 % SOC the
  ESP opens Q1 to drop the display, then stays awake in deep-sleep to
  monitor recovery and re-engage — it is its own supervisor.
- **Vgs is clamped** by DZ1 to ≤ 12 V; without it, pulling Q1's gate toward
  GND drove Vgs to −V24 ≈ −29 V (vs the FET's ±12 V) — a latent gate-oxide
  failure in the old design.
- 60 V Q1/Q2 survive the ~53 V clamp; the old 30 V AO340x parts did not.

**V12 (Cat5e/display) policy**:
- **State 3 (deep-sleep, 10–15 % SOC)**: Q1 ON — display up at a slower
  frame cadence, can show a "LOW PACK" banner. See D-OPEN-7a.
- **State 4 (hard-cut, < 10 % SOC)**: Q1 OFF → display dark. The MCU stays
  alive (~µA) on U1 and re-engages on recovery. See D-OPEN-7b.

This matches the documented State 4 budget in
[`power_budget.md`](../../docs/hardware/power_budget.md) §State 4.

## 9. RS-485 interface

Unchanged from the existing design (see §4.6 above and the cross-ref).
This board is **one terminus of the RS-485 bus**, so R10 (120 Ω) is
populated. **Idle bias is NOT here** — it lives on the display end only
(~330 Ω), so the always-on battery rail carries no RS-485 static draw
(D19/DR-4; see CP1 display-side §4.6).

## 10. Decoupling strategy

| Cap   | Value  | Net      | Placement (within mm of pin) | Function       |
|-------|--------|----------|------------------------------|----------------|
| C1    | 22 µF/100 V | V24_FUSED | LM5166 VIN < 2 mm       | Bulk input (behind ~53 V clamp → 100 V) |
| C2    | 22 µF/25 V  | V3V3  | LM5166 VOUT < 2 mm          | Bulk output (3.3 V) |
| C3    | 22 µF/100 V | V24_SW | R-78HB12 (U2) VIN < 5 mm    | U2 input bulk (behind clamp → 100 V) |
| C4    | 22 µF/25 V  | V12_CAT5E | R-78HB12 (U2) VOUT < 5 mm | Bulk output to Cat5e |
| C5    | 100 nF | V24_SENSE | ADC1_CH0 < 3 mm            | Sense filter   |
| C6    | 10 µF  | V3V3  | ESP 3V3 pin < 2 mm           | ESP module bulk |
| C7    | 100 nF | V3V3  | ESP 3V3 pin < 2 mm (0402 if poss.) | ESP HF decoupling |
| C8    | 1 µF   | EN net   | ESP EN < 5 mm                | Soft-start    |
| C9    | 100 nF | V3V3  | RV-3028 VCC < 2 mm            | RTC decoupling |
| C10   | 100 nF | V3V3  | SN65HVD3082 VCC < 2 mm       | RS-485 decoupling |
| C11   | 100 nF | BTN_OVERRIDE | -                       | Button RC debounce |
| C12   | 1 µF   | 3V3_USB | U5 (LDO) in/out < 2 mm       | AP2112 in/out (D29) |
| C13   | **~47 µF** | V3V3 | TPS2116 OUT < 5 mm          | **CP2/reviewer F11:** TI recommends ~100 µF on the mux OUT when reverse-current-blocking is exercised (USB hot-plug holds the buck output high). Design bulk on V3V3 is C2 22 µF + C6 10 µF ≈ 32 µF; add ~47 µF (→ ~79 µF) **or** scope USB hot-plug at CP2 to confirm VOUT stays < 5.5 V on the mux/buck pins |

**CP2 schematic TODOs surfaced by the iter-2 review:**
- **LM5166 support network (F10):** document the **EN** strap (recommend EN→V24_FUSED via the part's enable threshold network for always-on start), the **SS** pin (open = 900 µs default, or a soft-start cap), and **ILIM** (default unless a lower limit is wanted). These are required-support pins not yet enumerated in CP1.
- **TPS2116 OUT capacitance (F11):** see C13 above.
- **TPS2116 config (datasheet-confirmed 2026-07-01):** tie **MODE → VIN1** for
  **automatic priority mode** (auto-selects VIN1 when valid, falls back to
  VIN2 when it drops); with **VIN1 = USB-LDO (priority), VIN2 = U1 buck**, USB
  takes over when plugged in and the buck idles — exactly the D29 intent. ST
  (open-drain status) optional; PR1 unused in priority mode. Same on the
  display mux.
- **UVLO hysteresis (F01) + divider (F02/D33):** finalize R_uv1/R_uv2 (R1≈4.87 MΩ/R2≈100 kΩ for the TPS3808G01 0.405 V VIT, ≥2.5 µA at trip) + SENSE filter cap and R_hys (~1.3 V band); bench-verify clean re-engage.
- **Q3/Q4 UVLO-bypass (F03):** verify the fail-safe default-ON truth table on the bench.

## 11. Layout strategy

### 11.1 Layer stackup

| Layer | Use                                |
|-------|-------------------------------------|
| F.Cu  | Signals, components, all routing where possible |
| B.Cu  | Ground pour (single contiguous), with a few crossover signals where unavoidable |

### 11.2 Placement priorities

1. **Antenna keepout** (rule 1): 15×6 mm no-copper-no-track at the
   ESP32-S3-WROOM-1 antenna corner. Place the module so the antenna
   points OUT of the board edge.
2. **Switching loop compact**: U1, L1, C1, C2 in a tight triangle
   ≤ 10 mm sides. The U1→L1→C2→GND loop is the high-di/dt path.
3. **Sense divider quiet**: R5/R6/C5 on the **opposite half** of the
   board from U1, ideally on the bottom layer, away from L1.
4. **RS-485 + RJ45 on the edge**: U3 within 15 mm of J2. Use a copper
   pour from U3's GND pin to the J2 shell.
5. **Hard-cut MOSFETs near the regulators they control**, on the V24
   side; do not run a long V24 trace.
6. **RTC near MCU**: minimize I²C trace length; the RV-3028 has an
   integrated crystal — keep it away from the LM5166 switching node (L1).
7. **High-current paths fat**: V24_RAW → F1 → D1 → V24_FUSED → U1/U2 in
   a continuous copper run; design rule applies in §11.3.

### 11.3 Net classes (track widths)

| Class       | Width    | Clearance | Nets                                       |
|-------------|----------|-----------|--------------------------------------------|
| Power-24V   | 1.0 mm   | 0.3 mm    | V24_RAW, V24_FUSED                         |
| Power-12V   | 0.5 mm   | 0.25 mm   | V12_CAT5E                                  |
| Power-3V3   | 0.4 mm   | 0.2 mm    | V3V3                                    |
| Default sig | 0.2 mm   | 0.20 mm   | UART, I²C, SPI (none here), BTN, sense     |
| RS485-diff  | 0.25 mm  | 0.2 mm    | RS485_A, RS485_B (route as pair, equal-length, no stubs) |

JLCPCB minimum is 6 mil (0.152 mm) trace and 6 mil clearance — all
classes clear that comfortably.

### 11.4 Ground

Contiguous pour on B.Cu. Stitching vias every ~10 mm around the
switching regulator. Two GND-pin paths from U1 connect to the pour
directly (no thermal relief on the U1 GND pad — it's the return for the
SW loop).

## 12. JLCPCB design-rule compliance

| Rule                         | Min spec  | Our spec   | Margin |
|------------------------------|-----------|------------|--------|
| Min trace width              | 0.152 mm  | 0.2 mm     | 32 %    |
| Min trace clearance          | 0.152 mm  | 0.20 mm    | 32 %    |
| Min drill hole               | 0.3 mm    | 0.3 mm (vias 0.4 mm)  | 0 % via, 33 % through-hole |
| Min annular ring             | 0.13 mm   | 0.15 mm    | 15 %    |
| Edge clearance               | 0.3 mm    | 0.3 mm     | 0 %    |
| Hole-to-trace                | 0.2 mm    | 0.2 mm     | 0 %    |

All net classes sit comfortably above JLCPCB's 6 mil (0.152 mm)
minimums. Default-sig clearance is committed to 0.20 mm for safety
margin.

## 13. Open decisions for reviewer

| ID            | Question | Default if no reviewer input |
|---------------|----------|------------------------------|
| **D-OPEN-1**  | ESP32-S3-WROOM-1-N16R8 vs -N8 (no PSRAM)? | N16R8 — keep existing BOM choice; minor $1.50 difference doesn't move the needle |
| **D-OPEN-2**  | SN65HVD3082E vs lower-Iq alternative (ISL3175E)? | SN65HVD3082E — stocked, proven |
| **D-OPEN-3**  | Internal ESP32 ADC vs external supervisor IC (TPS3839) for ULP voltage monitoring? | **Internal ADC** — saves $1.50 + footprint; ULP draws ~10 µA which dominates over the regulator Iq anyway |
| ~~D-OPEN-5~~  | ~~Hard-cut topology~~ — **RESOLVED 2026-05-23 (post-CP1 agent-reviewer Finding 01)**: original P-FET in the 24 V path. Topology described in §8. No EN-pin alternative |
| **D-OPEN-6**  | Q1 gate pull-up value — 10 kΩ (~2.4 mA) vs 100 kΩ (~240 µA) vs 1 MΩ (~24 µA)? | **100 kΩ** — balance of fast turn-OFF (RC ~33 µs) and low idle current |
| **D-OPEN-7a** | **Deep-sleep V12 policy** — should the 12 V Cat5e rail be kept alive in State 3 (10–15 % SOC, deep-sleep)? | **Yes** — Q1 stays ON in deep-sleep; display side sees slow-cadence frames and can show "LOW PACK" banner. Cost: ~5 mA × 24 V continuous via V24_SW |
| **D-OPEN-7b** | **Hard-cut V12 policy** — should the 12 V Cat5e rail die in State 4 (<10 % SOC, hard-cut)? | **Yes (forced OFF)** — Q1 OFF kills V24_SW which kills V12. Required to preserve the State 4 ≤5 mW pack-draw target. Display side goes dark; ESP NVS preserves its last-rendered screen for the next State-1 recovery |

## 14. Risk register

1. **RV-3028 SOIC-16W footprint not in stock libraries on some KiCad
   distributions** — verify at CP2; create custom footprint if needed
   (low effort).
2. **R-78HB12 SIP3 + LM5166 VSON-10 footprints** — Recom provides KiCad
   libraries at recom-power.com/design-tools; the LM5166 VSON-10 is in
   TI's library. Pulling/verifying these is part of CP2. **Candidate MPNs
   (LM5166 fixed-3.3 V, R-78HB12-0.5, ZXMP6A13F, RV-3028-C7) need a final availability check
   before BOM lock** (D-OPEN-6).
3. **ESP32-S3-WROOM-1 antenna keepout violations** are easy to make
   by accident. CP3 layout review must verify visually.
4. **5×20 mm fuse clip footprint** — common (Keystone 3517 etc.) but
   should verify at CP2.
5. **JLCPCB Cat5e termination header part** — the SKiDL specifies
   Hammond-style; JLC stocks many compatible variants. Confirm SKU
   at CP5.
6. **Brown-out behavior** (D19) — if the MCU resets, PWR_EN drops
   LOW/Hi-Z → R4 holds Q2 OFF → R3 pulls Q1 OFF → the **display feed**
   drops. The MCU itself is on the always-on rail, so it rides through /
   reboots cleanly and re-asserts PWR_EN after re-init. The MCU's own
   supply is never gated. **Verify at CP2.**

## 15. What changed vs. the existing `docs/hardware/` baseline

| Section                          | Old                                       | CP1                                          |
|----------------------------------|-------------------------------------------|----------------------------------------------|
| 24 V input                       | Ring lugs + external ATO fuse holder     | Phoenix terminal block + on-board 5×20 mm cartridge fuse |
| 24 V TVS                         | Not specified                              | TVS1 = SMAJ33CA across V24_FUSED ↔ GND (D19/DR-2) |
| 3.3 V regulator + domain         | TPS62933 on the *switched* rail (MCU died at hard-cut → couldn't boot) | LM5166 µA-Iq buck on the **always-on** rail; MCU always powered (D19/DR-4) |
| 12 V regulator                   | R-78E12 (34 V — under-rated behind the ~53 V clamp) | R-78HB12 (72 V), switched behind Q1 (D19/DR-3) |
| Load switch FETs                 | AO3401A/AO3400A (30 V), no Vgs clamp       | 60 V ZXMP6A13F/2N7002 + 12 V Vgs Zener clamp (D19/DR-4) |
| Reverse-polarity diode           | SS24 (40 V)                                | SS26 (60 V) — out-rates the clamp (D19/DR-3) |
| RS-485 idle bias                 | Both ends (battery bias always-on → ~8 mW leak) | Display end only, ~330 Ω (battery rail draws 0; D19/DR-4) |
| Sense divider                    | 100 kΩ / 11 kΩ (220 µA idle)              | 1.2 MΩ / 100 kΩ (~19 µA idle; full charge → 2.25 V, in ADC linear band — DR-6) |
| Q1 gate pull-up                  | 10 kΩ (2.4 mA idle)                        | 100 kΩ (240 µA idle) — 10× power saving      |
| Debug LED                        | LED1 + R_led (always available, GPIO-controlled) | **Removed** per D4                       |
| RS-485 numbering                 | TVS1 (RS-485), TVS2 (12 V), TVS3 (24 V) confused | TVS1 (24 V), TVS2 (RS-485) — display side has its own TVS3/TVS4 |
| Mounting holes                   | Not specified                              | 4× M3 corner standoffs to the 3D-printed enclosure; exact coordinates set at CP3 placement once the outline is fixed (D20) |
| Dev headers                      | Not in original BOM                        | J3 (USB-C breakout), J4 (term-lift jumper), J5 (UART debug) added for bring-up |
| Mechanical board outline         | "60 × 38 mm" (Hammond 1556B2GY)            | **Deferred** (D20): no fixed outline at CP1; routed-area dictates size, then a custom 3D-printed IP5x enclosure is designed against the PCB STEP. No COTS box. |

## 16. What's NOT in CP1 (defers to later checkpoints)

- Actual KiCad schematic capture (CP2)
- Symbol library completeness audit beyond what's in the SKiDL files (CP2)
- Footprint placement (CP3)
- Routing (CP4)
- 3D model exports for the user's faceplate work (CP5)
- Manufacturing files (CP5)
