# Design Review Items

Engineering concerns the build agents raise for a human call. Agents
decide routine matters themselves; an item lands here only when the
concern is substantive **and** the right answer depends on design intent
the agents can't recover from the files. Not a legacy/continuity log —
end-product correctness is the only bar. Each item is OPEN (awaiting a
call) or RESOLVED (with the decision recorded).

---

## Best-practice baseline (clean sheet)

For a DC input arriving from off-board, connector inward:
1. **Overcurrent** — fuse / PTC polyfuse.
2. **Reverse polarity** — series element (Schottky = simple; ideal-diode
   P-FET = low loss).
3. **Surge/transient** — unidirectional TVS, **cathode → rail**, sized so
   `Vrwm ≥ max operating V` (with margin) **and** `Vclamp ≤ downstream
   abs-max VIN`. The clamp must land *below* what it protects.
4. **Bulk capacitance.**
5. Cabled inputs: optional LC / common-mode filtering for EMI/ESD.

The decisive, often-missed rule is 3: a TVS only protects if its clamp
voltage is below the abs-max of the part behind it.

## DR-1 — Display TVS1 (SMAJ15A) was reversed  [RESOLVED 2026-06-17]

Display 12 V input was: F1 polyfuse ✓, bulk C1 ✓, **TVS1 anode→rail /
cathode→GND** ✗ — a unidirectional TVS forward across the rail gives no
positive-surge clamp (only a reverse-polarity crowbar). The part is
correctly *sized* for surge (Vrwm 15 V > 12 V; Vclamp ~24 V < R-78E3.3
VIN max ~32 V), which proves surge intent — so the orientation, not the
part, was the error. agent-reviewer passed it CP1–CP6; Claude raised it.

**Resolution (agent call):** the clean-sheet analysis removed the
ambiguity, so flipped TVS1 to **cathode→rail** (angle 270). Now
reverse-biased in normal operation, clamps positive transients. ERC 0/0,
audit PASS. Residual gap vs. ideal: no dedicated series reverse-polarity
device — judged acceptable for a fixed, keyed inter-board CAT5e feed
(a series Schottky is an available enhancement if field miswiring is a
real risk; say so and I'll add it).

## DR-2 — Battery TVS clamp exceeded the buck's VIN rating  [RESOLVED 2026-06-17]

**Was.** Battery input topology was right (F1 fuse, series SS24 Schottky
reverse-polarity, TVS, bulk) but mis-**coordinated**: `SMAJ30CA` clamps
~48 V while the TPS62933 buck was rated ~30 V (abs-max ~32 V) — a surge
would destroy the buck *before* the TVS protected it. A single TVS can't
fix it (to clear a ~29 V full-charge bus it needs Vrwm ≥ 29 V, which
clamps > 40 V — always above 32 V).

**Resolution (agent call, per "make the excellent choice").** Raised the
regulator above the clamp instead of trying to lower the clamp:
- **3V3 buck → Recom R-78HB3.3-0.5 module (9–72 V VIN).** 72 V rating
  tolerates the ~53 V clamp with margin. Drops the inductor + bootstrap
  cap, and makes all three rails (battery 3V3, battery 12 V U2, display
  3V3) the same R-78 family.
- **TVS1 → SMAJ33CA.** 33 V stand-off gives clean margin over the ~29 V
  full-charge bus (30 V was ~1 V — could leak/clamp in normal use).
- **Input bulk caps on V24_SW (C1, C3) → 100 V.** They sit behind the
  TVS and can see its ~53 V clamp; the old 25 V / 35 V parts were a
  latent short-on-surge.

Net result: fuse → SS24 → SMAJ33CA → 100 V bulk → 72 V module is now a
genuinely protective, well-coordinated chain. Verified U1 VIN→V24_SW,
GND→GND, VOUT→V3V3_SW; ERC 0/0, audit gate PASS.

**Trade accepted:** R-78HB is 0.5 A (vs the old 3 A discrete). The
battery 3V3 load (ESP32-S3 + RTC + RS-485) peaks ≲0.5 A and is buffered
by bulk caps — the display side already runs the same ESP32-S3 on a
0.5 A R-78. If the battery node ever needs >0.5 A, revisit with a 60 V
discrete buck.

---

# CP1 re-open findings (clean-sheet engineering review, decisions.md D18)

The items below were found re-deriving the battery-side power architecture
from first principles per `ENGINEERING_REVIEW.md`. They are CP1/CP2-class
defects that every automated gate (ERC/DRC/readability) passed — the
reason for the D18 re-open.

## DR-3 — Surge clamp coordination only half-fixed (U2 12 V buck + load FET still exposed)  [RESOLVED 2026-06-17 — see D19, impl pending CP2]

DR-2 raised U1 (3V3) above the ~53 V SMAJ33CA clamp but left the other
parts on the same protected rail exposed. The 24 V chain is:

    J1 → F1 → D1(SS24) → V24_FUSED {TVS1 clamps ~53 V, R5 sense} → Q1 → V24_SW {C1/C3 100V, U1 72V, U2}

- **U2 = Recom R-78E12-1.0** on V24_SW. R-78E input abs-max is ~32–34 V.
  A surge the TVS clamps to ~53 V destroys U2 — identical failure mode to
  DR-2, just on the 12 V Cat5e-feed regulator instead of the 3V3 one.
- **D1 = SS24** (40 V) is the series reverse-polarity element; it conducts
  forward during a positive surge so its reverse rating isn't the issue,
  but a 60 V Schottky (SS26/SK56) is the consistent choice if the rail
  is rated to the clamp.

**Recommended resolution (complete the DR-2 philosophy — raise every part
on the protected rail above the clamp):** U2 → **Recom R-78HB12** family
(9–72 V in); D1 → 60 V Schottky. Then the whole V24_FUSED/V24_SW rail is
≥60 V and the SMAJ33CA's ~53 V clamp actually protects everything.
*Sourcing note:* confirm R-78HB12 output-current variant (Cat5e feed
needs only ~0.1–0.15 A) and a real 60 V Schottky PN before committing
(no fabricated PNs, per BOM D-OPEN-6).

## DR-4 — Hard-cut load switch: MCU on the switched rail (cannot boot) + Vgs overstress + no wake path  [RESOLVED 2026-06-17 — see D19, impl pending CP2]

**Resolution (user call: "Option 1 done right", see D19).** MCU + U1 move
to an always-on, wide-Vin **µA-Iq** buck (LM5165-class, ≥60 V); Q1 sheds
only U2/the display feed; Q1 gets a Vgs Zener clamp + series gate
resistor and becomes a 60 V P-FET (Q2 → 60 V N-FET). ESP self-supervises
in deep-sleep (~1 mW all-in at hard-cut) — no separate supervisor IC.
Implementation is CP2 schematic work.


The battery-side power-domain split as implemented does not match the
architecture intent (block_diagrams.md: "always-on = ESP ULP + RTC;
hard-cut kills everything except the sense divider") and has three
coupled defects:

1. **Bootstrap / cannot power up (critical).** U1 (3V3 MCU regulator)
   VIN is on **V24_SW** — the hard-cut rail downstream of Q1. Q1 is a
   default-OFF high-side P-FET (R3 pulls its gate to source; R4 holds
   PWR_EN low at power-on, failsafe-off on brown-out). So at power-on
   V24_SW is dead → U1 makes no 3V3 → the ESP never runs → it can never
   drive PWR_EN to close Q1. The board latches off. (Symmetrically, a
   downstream MCU can't cut its *own* supply: if it did, it would lose
   power and Q1 would revert, oscillating.) The MCU + its regulator must
   live on the **always-on** rail; only sheddable loads belong behind Q1.

2. **Gate-source overstress.** Q1 = AO3401A (Vgs ±12 V). When Q2 turns
   Q1 on it pulls Q1's gate to GND with no clamp/divider, so
   Vgs = −V24_FUSED ≈ **−29 V** normally (−53 V on surge) — gate-oxide
   destruction the instant Q1 is commanded on. A high-side P-FET switch
   on a 24 V rail needs a **gate-source Zener clamp (~10–12 V) + series
   gate resistor**, sizing Vgs into the safe range regardless of bus
   voltage.

3. **No wake-from-hard-cut.** If the intent is to fully unpower the ESP
   at <10 % SOC (power_budget.md state 4), nothing re-enables Q1 on
   voltage recovery — the ESP is off and there is no hardware voltage
   supervisor/comparator in the BOM. A fully-cut MCU can't wake itself.

**Recommended resolution (re-architect the power domains):**
- Move **U1 (3V3) + the MCU/RTC/sense** to the **always-on** rail
  (V24_FUSED, post reverse-polarity + TVS). The ESP self-manages: in
  normal use it runs; at low SOC it deep-sleeps in ULP (~50 µA) and
  periodically reads V24_SENSE, **shedding the heavy/peripheral loads**
  (U2 12 V → Cat5e, RS-485 driver, display feed) via Q1.
- Keep **Q1 switching only the sheddable loads** (U2/12 V + peripherals),
  not the MCU. Add the Vgs clamp from #2. This removes the bootstrap and
  wake problems entirely and matches the always-on/hard-cut intent.
- Net low-SOC draw becomes ESP-deep-sleep (~50 µA @ 3V3 ≈ sub-mW at the
  pack) + sense divider — still far under budget, no supervisor part
  needed.

**Open design-intent question for the user:** at <10 % SOC, is
ESP-deep-sleep-always-on (simple, recommended, ~sub-mW) acceptable, or is
a literal full cut of the ESP required (needs an added hardware voltage
supervisor to re-engage)? This determines whether DR-4 is a rail-reassign
+ gate-clamp fix or also adds a supervisor.

## DR-5 — Baseline documentation contradicts the schematic  [OPEN — fix on resolution of DR-3/DR-4]

The CP1 "design baseline" docs describe the *pre-DR* design and are now
wrong in load-bearing ways — a baseline that contradicts the design is
worse than none:
- `docs/hardware/bom.md`: U1 still TPS62933 + L1 + 2.2 µH; caps 25 V/35 V;
  TVS refdes/parts pre-DR-2; sense divider "100 k/11 k".
- `docs/hardware/power_budget.md`: TPS62933/R-78E efficiency table; sense
  divider "111 kΩ → 216 µA" (actual is 1 M/110 k ≈ 22 µA).
- `docs/hardware/block_diagrams.md`: TPS62933 buck, old domain split.
- `hardware/outputs/.../fab/*-bom.csv`: stale CP6 export (TPS62933,
  SMAJ30CA, 25 V caps) — superseded per D18, regenerate after fixes.

**Resolution:** reconcile all baseline docs to the schematic *after*
DR-3/DR-4 land (so they're rewritten once against the final topology, not
twice). **DONE** — all baseline docs reconciled to D19.

---

# Pre-handoff excellence pass (2026-06-18)

Found while raising CP1 to a genuinely-excellent bar before review
(display-side clean-sheet + a second look at the sensing path).

## DR-6 — 24 V sense divider lands in the ESP ADC's nonlinear top region  [RESOLVED 2026-06-18]

The 1 MΩ/110 kΩ divider maps the bus to `Vbus·110/1110`, so at full
charge (~29.2 V) the ADC pin sees **~2.9 V**. The ESP32-S3 ADC at 12 dB
attenuation is only linear to ~2.45 V and compresses above that — so the
*least* accurate readings would be at full charge, and SOC math leans on
exactly that region.

**Resolution.** Re-ratio to **R5 = 1.2 MΩ / R6 = 100 kΩ** (`·100/1300`):
full charge → **~2.25 V** (inside the linear band), 20 V → 1.54 V. Draw
~18–23 µA (≈ unchanged, still power-first). **Surge is inherently safe:**
the TVS clamps V24_FUSED to ~53 V; the 1.2 MΩ top resistor limits the
ADC-pin fault current to (53−3.6)/1.2 MΩ ≈ **41 µA**, which the ESP's
internal ADC clamp diodes sink — no extra clamp part needed. C5 (100 nF)
still filters. (Agent call — clean ratio fix, no added parts.)

## DR-7 — E-paper interface: wrong connector + missing panel-driver support  [RESOLVED 2026-06-18 — see also a CP2 note]

The display drives a standard **8-pin SPI** e-paper (the schematic wires
exactly CS/DC/RST/BUSY/SCK/MOSI + VCC/GND, and the firmware matches), and
the BOM's *intent* is the **Waveshare 4.2" e-Paper Module (B)** — which
carries its own driver PCB and exposes an 8-pin header. But **J2 is a
24-pin 0.5 mm FFC (Hirose FH12-24S)** — the connector for the *bare*
`WFT0420CZ15` panel, with pins 11–24 marked "NC". A bare e-paper panel
needs an on-board booster network (VGH/VGL/VDH/VDL/VCOM charge-pump caps +
boost diode) on those very pins; the schematic has none. So as drawn it
fits neither part: it can't drive a bare panel (no booster), and it's the
wrong connector for the module.

**Resolution (agent call — use the module, the simplest robust choice for
a hand-soldered cabin product).** Commit to the **Waveshare 4.2" e-Paper
Module (B)** and change **J2 → an 8-pin 2.54 mm header** matching its
interface: **VCC, GND, DIN (MOSI), CLK (SCK), CS, DC, RST, BUSY** (the
canonical Waveshare e-paper pinout; the module includes the mating cable).
This drops the FH12-24S FFC, the 16 NC pins, and the entire missing-booster
risk, and closes the old "verify the FFC pinout before fab" open item.
*CP2 note:* match the physical pin order on J2 to the module's silk at
assembly; source = Waveshare 4.2inch e-Paper Module (B) wiki.

## DR-8 — DS3231 is a ~0.5 mW always-on load the hard-cut budget missed  [RESOLVED 2026-06-18 — budget corrected]

The "~1 mW hard-cut" figure assumed the DS3231 runs off its backup cell
(0 from pack) at low SOC — which was true *pre-D19*, when the 3V3 rail
died at hard-cut. Under D19 **V3V3 is always-on**, so the DS3231 runs off
V3V3 continuously and draws its active **~0.1–0.2 mA (~0.5 mW)** from the
pack even at hard-cut — ~⅓ of the budget, and the dominant term after the
sense divider. (The D23 supercap backup only carries the RTC through a
*full pack disconnect*, not at hard-cut.)

**Resolution (D23).** Rather than accept the penalty, **swapped the RTC to
the Micro Crystal RV-3028-C7 (45 nA)** — ~3000× lower draw. The ~0.5 mW
load is *eliminated*, hard-cut returns to **~1 mW**, and accuracy (±1–3 ppm)
is comparable. The user's prompt ("there must be an ultra-low-power RTC")
caught that the DS3231 is a power-hungry RTC by class (its TCXO is the
cost). Budget reverted to ~1 mW across power_budget.md + cp1_battery_side.

---

# Display-side clean-sheet review (domain-complete, 2026-06-18)

Same first-principles pass as the battery side, now with the hardened
mechanical/RF/serviceability domains. Electrical cleared with minor notes
(DR-1 TVS already fixed; R-78E3.3 coordination sound; RS-485 term + sole
display-end bias coordinated; decoupling/EN fine). The substantive finds
are mechanical + serviceability.

## DR-9 — Display has no service access (wall-mounted, internal headers only)  [RESOLVED 2026-06-18 — D27]

The display lives in a double-gang wall box behind a faceplate, yet only
has internal dev pin headers — reflashing means pulling it out of the
wall. Same gap D22 fixed on the battery side.

**Resolution (D27).** Add a board **bottom-edge USB-C** on the native
ESP32-S3 USB (flash/console/JTAG) exiting a discreet slot in the bottom of
the faceplate/box — reachable without wall removal, invisible head-on. Add
a **USB ESD array** (USBLC6-2) on D+/D−/VBUS. Keep one internal UART header
for bench bring-up.

## DR-10 — Display mechanical: shallow box, module-vs-box fit, tall THT parts, button/cap stack  [RESOLVED 2026-06-18 — D27, PCB-side contract]

Aggressive mechanical pass on the double-gang assembly surfaced several
coupled constraints that CP3 placement must honor:

1. **Depth budget is tight.** A double-gang old-work box is shallow
   (~45 mm usable). The stack is faceplate → e-paper module → main PCB →
   bracket → box floor. **Tall THT parts eat the budget**: a vertical RJ45
   (~13–21 mm) and the R-78E3.3 SIP (~11 mm). → use a **right-angle /
   low-profile RJ45** (also routes the in-wall Cat5e cleanly), and budget
   the R-78 orientation; produce an explicit depth-stack tally at CP3.
2. **The e-paper module likely won't fit *inside* the box.** The Waveshare
   4.2" Module (B) outline (~90–103 mm — *verify exact*) meets/exceeds the
   double-gang interior (~95 mm). → **mount the module to the back of the
   oversized custom faceplate** (~115×117 mm), with the main PCB in the box
   behind it and the 8-pin cable (DR-7) between — slack + strain relief.
3. **Button-cap geometry** spans the PCB→faceplate gap (set by the module
   + standoff stack), so it can't be fixed until the depth stack is. → spec
   tall-actuator tactiles or printed cap extensions, sized to the final gap.
4. **STEP export is the contract.** The bracket + faceplate are user-3D-
   printed, so the deliverable is a **PCB STEP** (with the e-paper-module
   envelope + connector/button/USB-C positions) the user designs against.

These are CP1 *constraints* (captured in cp1_display_side §2/§10) + a CP3
placement obligation; the user's print is out of scope.

## DR-11 — Display PTC over-sized for the load  [RESOLVED 2026-06-18]

F1 (MF-R050, 0.5 A hold / ~1 A trip) is loose against the actual display
load (~40 mA steady, ~150 mA refresh peaks). And it barely coordinates
with the battery-side U2 (R-78HB12, ~0.5 A foldback) — a display short
would more likely fold U2 back than trip the PTC. **Resolution:** tighten
to a **~0.25 A-hold PTC** (covers refresh/inrush, trips well below U2's
limit → real cable + upstream protection). Agent call.
