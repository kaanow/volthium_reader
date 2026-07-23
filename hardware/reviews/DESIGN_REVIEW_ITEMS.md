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

## DR-5 — Baseline documentation contradicts the schematic  [RESOLVED 2026-06-18 — all baseline docs reconciled to D19]

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
Module (B)** and change **J2 → an 8-pin JST-PH 2.0 mm post header** matching
its onboard connector (verified 2026-06-25 — the module is JST-PH 2.0, not
2.54 mm; user caught the mismatch): **VCC, GND, DIN (MOSI), CLK (SCK), CS,
DC, RST, BUSY**. Same family both ends → off-the-shelf pre-crimped PH↔PH
cable, no tool, keyed by design.
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

**Resolution (D27) — geometry corrected.** The box is recessed in the wall,
so only the faceplate *front* is exposed — a bottom-edge port doesn't work.
Instead: routine firmware is **OTA over RS-485** (battery side pulls it via
WiFi and propagates to the display), so the display's physical USB is a
**bench/recovery port only**. Make it a board-edge **USB-C** (native USB)
reached by **popping the faceplate** (detaches from the front without wall
removal) — **no front-face cutout**. + **USB ESD array** (USBLC6-2); keep
an internal UART header for bench.

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

---

# Designer fresh-look pass (2026-06-22) — pre-iter-3

Self-review + datasheet homework before the next reviewer pass, on the
principle that errors are cheapest to catch at CP1. Each item below is the
*designer's* analysis with a proposed resolution; the iter-3 reviewer brief
(packet §10) asks for independent verification. Several need a **user call**.

## DR-12 — Input fuse vs ceramic inrush (F1 1 A fast-blow + low-ESR bulk)  [RESOLVED 2026-06-22 — F1 → 1 A time-lag "T" (user-approved)]

**Issue.** F1 (1 A fast-blow, 5×20 mm) sees inrush charging low-ESR ceramic
bulk on each power event: ~22 µF (C1, LM5166 input on V24_FUSED) at
cold-start, and **~3.3 µF** (C3, U2 input on V24_SW; was 22 µF — F90) when
**SSR1 closes** the display feed. With ceramic ESR + SS26 + trace ≈ 0.1–0.5 Ω, single-event
I²t ≈ **0.06–0.13 A²s** — the same order as a 1 A **fast-blow**'s melting
I²t. Risk: nuisance trip / fuse fatigue over repeated cold-starts.
**Mitigation already present:** Q1's 1 kΩ gate resistor soft-starts the C3
event; the cold-start C1 event is unmitigated.
**Proposed:** spec F1 as a **1 A time-lag ("T"/slow-blow)** cartridge (same
holder) — tolerates µs-scale inrush, still protects the ~45 mA steady load
and a hard short. **Confidence: medium** — depends on the exact fuse I²t and
real loop R; reviewer to verify against the chosen fuse's datasheet I²t.

## DR-13 — RS-485 fail-safe bias margin is thin (236 mV, dual-termination)  [RESOLVED 2026-06-22 — Rb 390→330 Ω, ~275 mV (user-approved); reviewer to confirm vs datasheet threshold]

**Derivation.** Both ends terminated (120 Ω each → 60 Ω across A–B) + a
single display-end fail-safe bias (Rb = 390 Ω up/down): idle differential =
3.3 × 60/(60 + 2·390) = **236 mV** — only ~18 % over the +200 mV a receiver
needs for a guaranteed idle "1". Should be checked against the
SN65HVD3082E's **guaranteed** fail-safe threshold, not nominal ±200 mV.
**Key freedom:** the bias is at the **display end** (shed at hard-cut), so
more bias current costs nothing on the battery hard-cut budget.
**Proposed:** drop Rb 390 → **~300–330 Ω** for ~280–300 mV (~45 % margin).
Reviewer to confirm the datasheet threshold and pick the value.

## DR-14 — Display 12 V TVS ↔ R-78E3.3 coordination is tight (15 %)  [RESOLVED — coordinated; margin logged]

**Derivation.** SMAJ15A VC(max) = **24.4 V** (@ IPP 16.4 A) vs R-78E3.3-0.5
abs-max input = **28 V** → margin 3.6 V (**15 %**); standoff 15 V > 12 V
nominal ✓. DR-1's "sound" holds, but this is the **tightest coordination on
the display side**, and 24.4 V is only reached at the TVS's full pulse
current. **No change required**; logged so any TVS sub keeps VC < 28 V (a
13 V-standoff part would add margin — optional). Evidence: Littelfuse SMAJ
datasheet; Recom R-78E-0.5 (6–28 V).

## DR-15 — Cat5e 12 V power pair: TVS only at the display end  [RESOLVED 2026-06-22 — added battery-side SMAJ15A (TVS3) (user-approved)]

**Issue.** The in-wall 12 V/GND pair (several metres, surge-exposed) has a
TVS (SMAJ15A) at the **display** end only. The **battery** end — U2 output
into the cable — has just a 22 µF bulk cap (C4), no clamp. A surge induced
on a long inductive pair isn't fully clamped at the far end by a single
near-end TVS.
**Proposed:** add a **battery-side 12 V TVS** on V12_CAT5E at J2 (e.g.
SMAJ15A, matching the display end) — cheap symmetric protection. Standard
practice on long exposed DC pairs is a clamp at **both** ends.
**Confidence: medium**; reviewer to judge near-end-only vs both-ends.

## DR-16 — "Must not finish off a low pack" rests entirely on firmware  [RESOLVED 2026-06-22 — user-approved: hardware UVLO backstop, see D28]

**Issue.** The load-shed-at-low-SOC guarantee (the product's core safety
promise) depends on firmware: the ESP must read V24_SENSE, deep-sleep, and
open Q1 below ~10 % SOC. The hardware default (R3 pull-up) only protects
against a **dead** MCU (Q1 defaults OFF). A **hung-but-powered** MCU —
firmware crash with the WDT mis-serviced, or stuck active — keeps the
display on and draws ~38 mA at low SOC indefinitely: exactly the failure the
design exists to prevent.
**Options.** (a) Firmware-only (status quo): rely on the ESP internal WDT +
careful firmware; zero added parts. (b) **Independent hardware UVLO** (
recommended): a ~µA voltage supervisor (e.g. TPS3839, or a micropower
comparator on the sense node) force-opens Q1 below a hardware threshold
(~21 V ≈ 10 % SOC, 8S LiFePO₄), independent of firmware. Cost: 1 IC + 2
passives, ~1–3 µA (hard-cut stays ≈1 mW).
**Designer recommendation: (b)** — directly backstops the one requirement
the user singled out, for ~µA and ~$1; the power-first tension is negligible
at µA. **Needs a user decision** (accept the part + µA?) and the reviewer's
independent take on whether firmware-only is acceptable for an unattended
pack.

**RESOLVED 2026-06-22 (user-approved).** Option (b), refined: an
**EN-asserting** supervisor (**U4 = TPS3808G01DBVR**, repackaged per D33/DR-24),
not a Q1-only shed. The key
realization from the design discussion: the dominant low-SOC drain is the
**MCU itself** (~38 mA), not the display (~5 mA), so the backstop must act
on the MCU. Asserting ESP **EN** low (i) drops the MCU to ~µA reset and
(ii) auto-sheds the display for free (PWR_EN Hi-Z → R4/R3 default-OFF) — and
because it's EN, not power, the MCU stays wakeable (D19 intact). Floor
~20 V trip / ~22 V release, CT-deglitched. Full design + topology + power in
**D28** and `cp1_battery_side.md §4.3a`. **Reviewer (iter-3):** verify the
threshold/divider, the EN-assert→auto-shed chain, U4 SKU/stock, and that the
floor sits safely below the firmware shed.

---

# Designer fresh-look pass 2 (2026-06-22) — pre-iter-4

Second self-review + datasheet homework, aimed at domains no prior pass
touched: system integrity (grounding/EMC), the new D28 supervisor's
second-order effects, USB power interactions, single-point-failure (FMEA),
and the cabin's real cold-temperature environment. Each item is the
*designer's* analysis with a proposed resolution; the iter-4 reviewer brief
(packet §11) asks for independent verification. Items needing a **user call**
are flagged.

## DR-17 — D28 supervisor on the boot-critical EN node: second-order interactions  [RESOLVED — analysis done; reviewer to verify]

**Why.** D28 put U4's open-drain RESET on the **EN node**, which already
carries R7 (10 kΩ pull-up to V3V3) + C8 (1 µF soft-start). EN decides
whether the board boots, so any interaction is high-stakes.

**Analysis.**
- **Brownout vs UVLO never fight.** ESP32-S3 brown-out detector ≈ **2.43 V
  on the 3.3 V rail** (Espressif). U4 trips on the **24 V pack at ~20 V**.
  The LM5166 holds 3.3 V regulated until the pack nears its ~3.6 V dropout,
  so U4 *always* asserts first (at 20 V pack); the 3.3 V brown-out detector
  is never reached in the low-pack path. No chatter between the two.
- **Open-drain vs C8.** U4 sinks EN low through R7 (0.33 mA, trivial) and
  discharges C8 (1 µF) — open-drain handles it. On release, EN rises via
  R7·C8 = **10 ms** (the intended soft-start ramp) → clean single cold-boot.
- **Deglitch.** C8 + U4's CT deglitch must reject LM5166/load transients
  (don't false-trip) yet act on a real sustained sag — CT in the tens-of-ms
  range. R7·C8 = 10 ms is the recommended Espressif value; keep it.
- **One thing to design at CP2:** U4 RESET is open-drain, so it must tie to
  the EN node *directly* (it relies on R7 as its pull-up); don't add a second
  series R. Confirm U4 Vol < the ESP EN logic-low at the always-on rail.

**Reviewer:** verify the brownout-vs-UVLO ordering, the open-drain/C8 edge,
and the CT deglitch value vs LM5166 start-up.

## DR-18 — USB-C VBUS / 3.3 V interaction → USB maintenance power ADDED  [RESOLVED 2026-06-22 — user chose to integrate USB-power; see D29]

**Issue (latent layout trap).** The maintenance USB-C carries 5 V VBUS. Dev-
board reference schematics routinely OR VBUS into the system 3.3 V. If that
pattern is copy-pasted at CP2, 5 V lands on the 3.3 V rail and fights the
LM5166 / destroys 3.3 V parts.

**Correction (2026-06-22).** My first write of this item also claimed USB
power would "defeat the D28 UVLO floor." **That was wrong.** U4 asserts the
ESP **EN** pin, which holds the chip in reset **independent of where 3.3 V
comes from** — so USB power does *not* defeat the UVLO; the pack stays
protected either way. The only real reason not to bare-tie VBUS→V3V3 is the
5 V-vs-3.3 V voltage conflict.

**Could the MCU run off USB (user question)?** Yes, and with ~zero pack draw
— but it is **not** automatic: it needs a **µA-class power-OR** (ideal-diode
/ LDO from VBUS into V3V3, priority over the buck). With it, USB present →
the LM5166 sees its output already high → stops switching → pack draw ≈ its
~14 µA quiescent. UVLO via EN is unaffected.

**Resolution (2026-06-22 — USER chose to integrate USB-power; see D29).**
The user values USB-power for bring-up/programming/troubleshooting (every
hand-built unit). It integrates **without compromising** the hard-cut
budget, the UVLO, or D19 — because all added parts except the mux are
**VBUS-referenced** (present only with a cable in → 0 pack draw unplugged):
- **U5 LDO** VBUS→3V3_USB; **U6 TPS2116** priority mux (VIN1=USB-LDO,
  VIN2=U1 buck, OUT=V3V3, ~1.3 µA Iq) → USB present = buck idles, pack draw
  ~µA; USB absent = buck, unchanged.
- **Q3** opens U4's RESET→EN line when VBUS present → MCU boots off USB on a
  dead/absent pack (solves the "(c)" objection that previously argued
  against it). UVLO fully active whenever USB is out (the unattended state).
- Display side mirrors U5+U6, no Q3.
Hard-cut stays **≈1 mW** (+~1.3 µA mux). No 5 V on V3V3 (LDO). Residual
(accepted): attended USB + low pack + firmware enabling the display could
drain the pack via U2 — attended/transient.

**Reviewer:** verify (a) both netlists keep raw 5 V VBUS off V3V3 (LDO
regulates); (b) the TPS2116 priority/idle behavior + that the buck tolerates
its output held high; (c) the Q3 VBUS-bypass correctly inhibits U4 only when
VBUS present and restores full UVLO when out; (d) the always-on adder is just
the ~1.3 µA mux; (e) EN-gating preserves the UVLO regardless of supply.

## DR-19 — End-to-end grounding & shield (single-point bond) — audit the whole link  [OPEN — per-board clean; reviewer to verify as a loop]

**State.** Per-board it looks textbook: signal GND on RJ45 pins 6/7/8;
cable shield bonds to chassis **at the battery end only**; display-end shield
drain NC (`cat5e_pinout.md`, both layout docs). That's the correct
single-point scheme.

**What's un-audited:** the link as a *loop*. (a) Is signal GND tied to
chassis GND at exactly **one** point (battery end), with no inadvertent
second tie at the display (e.g. a mounting-screw/bracket path to chassis, or
the e-paper frame)? (b) Is the RS-485 GND reference solid across 5 m given
GND is paralleled on pins 6/7/8? (c) Does the display 3D-printed bracket
(plastic) guarantee no chassis path — so the single point really is single?

**Reviewer:** trace GND/chassis end-to-end; confirm one and only one
signal-GND-to-chassis tie, at the battery end.

## DR-20 — EMC: buck ripple on the 12 V Cat5e pairs vs the RS-485 pair in the same jacket  [RESOLVED — acceptable; optional DNP choke; reviewer to confirm]

**Concern.** R-78HB12 (switching) drives the 12 V pairs that share the Cat5e
jacket with the RS-485 differential pair for ~5 m → switching noise could
couple onto RS-485.

**Analysis — why it's acceptable.** (a) RS-485 is on its **own twisted pair**
(pair 1), separate from the 12 V pairs (2/3) — twist gives common-mode
rejection. (b) U3/U2 are **SN65HVD3082E, slew-rate-limited** (~250 kbps
class) → high immunity to fast switching edges and low emitted harmonics.
(c) Bulk + ceramic on the 12 V at **both** ends (C4 battery / C1 display).
(d) `cat5e_pinout.md` already notes ferrite beads as a contingency. At this
data rate the margin is large.

**Proposed:** keep as-is, but **add a DNP footprint for a common-mode choke
(or pi-filter) on the 12 V feed** at the battery end — zero cost now, an
escape hatch if bench EMC shows RS-485 bit errors. **Reviewer:** confirm the
low-rate immunity argument and whether the DNP choke is worth the footprint.

## DR-21 — FMEA: single-point failures of the protective network (esp. U4 silent failure)  [RESOLVED 2026-06-22 — user accepted the fail-to-baseline residual; no self-test added]

**Why.** Protective parts can fail and *remove protection without any
symptom*. Tabulated fail-open / fail-short consequence + fail-safe direction:

| Part | Fails OPEN | Fails SHORT | Notes |
|------|-----------|-------------|-------|
| F1 fuse | (is the fail-safe) | n/a | catch-all |
| TVS1/TVS3 | no surge clamp (**silent**; surge rare) | clamps rail → blows F1 (safe, visible) | |
| DZ1 (gate Zener) | Q1 Vgs unclamped → possible gate damage on switch | Q1 held off (display never comes up — visible) | |
| R3 / R4 (default-OFF) | Q1/Q2 default state lost → display could latch on (**bad at low SOC**) | gate pinned → display off (visible) | |
| **U4 (UVLO)** | **stuck Hi-Z → backstop silently gone → reverts to firmware-only** | **holds EN low → board dark, no comms (very visible)** | asymmetric |
| **R_uv1 open** | SENSE→0 → U4 reads UV → asserts → board off (visible) | — | |
| **R_uv2 open** | SENSE→full → U4 never trips → **backstop silently gone** | — | |

**Key finding — fail-to-baseline (acceptable property).** U4's *silent*
failure modes (stuck-Hi-Z, R_uv2-open) revert to **firmware-only** — i.e.
the exact baseline we had *before* D28. So the backstop can never make things
*worse* than not having it; at worst it silently doesn't help. For a
backstop that is a sound property. Its *visible* failures (stuck-asserted,
R_uv1-open) are safe (board off, can't drain pack).

**Residual to accept:** there's no cheap self-check that U4 is alive. Option
(if desired): firmware periodically reads the pack via its own ADC and could
log "UVLO divider sanity" — but it can't truly test U4's output without
forcing a low rail. My recommendation was **accept**.

**RESOLVED 2026-06-22 (user-approved): accept the fail-to-baseline residual;
no self-test provision added.** Reviewer: verify the FMEA table and the
fail-to-baseline conclusion (don't reopen the accept).

## DR-22 — Full-BOM cold-temperature survey (off-grid cabin can go sub-zero)  [RESOLVED 2026-06-22 — user accepted e-paper 0 °C as the floor; no heater]

**Why.** An unheated off-grid cabin in winter can sit **below freezing**.
We accepted the **e-paper 0 °C** operating limit (D24) as *the* limiting
device — this verifies that's actually true across the BOM.

**Survey (operating min):** ESP32-S3 −40, **RV-3028-C7 −40**, LM5166 −40,
R-78HB12 / R-78E3.3 −40, SN65HVD3082E −40, TPS3808 −40, all ceramics X7R −55
(capacitance drops with cold but no failure), **no electrolytics anywhere**
(so no cold-ESR problem — a deliberately good property of the all-ceramic
BOM). **E-paper (B) = 0 °C → confirmed the floor.**

**Two real notes:** (1) The **LiFePO₄ pack must not be *charged* below 0 °C**
— but that's the **BMS's** job, not ours; our board only *monitors*, and
reads SOC fine when cold. Worth stating so it's not mistaken for our
responsibility. (2) **Product decision (USER):** below 0 °C the e-paper
won't refresh, but the electronics keep logging (and WiFi-push). Is
"display blank/again-on-warmup, logging continues" acceptable for the cabin,
or do we need a heater / different display? D24 implicitly accepted this; DR-
22 makes it explicit for sign-off.

**RESOLVED 2026-06-22 (user-approved): e-paper 0 °C floor accepted; no heater
/ no display change.** "Display blank below 0 °C, logging continues" is fine
for the cabin. Reviewer: confirm e-paper is the cold floor and no BOM part is
colder-limited (don't reopen the accept).

## DR-23 — RTC backup-cap (C-bk): leakage vs 45 nA, and VBACKUP rating  [RESOLVED — spec tightened; reviewer to verify hold time]

**Issue.** C-bk was speced loosely as "~10 mF–0.1 F." That range spans two
very different parts: a small low-leakage cap vs a **supercap whose own
leakage (~µA) dwarfs the RTC's 45 nA** — which would (a) dominate the
always-on draw and (b) *shorten* the hold time it's meant to extend.

**Analysis.** Hold time ≈ C·ΔV / I_total. At 45 nA the RTC sips tiny charge,
so a **low-leakage ~10–50 mF** cap already rides a full pack disconnect for
days–weeks, with leakage ≪ a supercap's. Trickle charge: RV-3028 internal
charger (selectable series R) → τ = R·C; tens-of-mF charges in minutes.
VBACKUP abs-max (per datasheet, ~5.5 V) > the 3.3 V trickle source → safe.

**Resolution:** spec **C-bk = low-leakage ~10–50 mF (not a leaky supercap)**;
pick the trickle resistor for a few-minute charge; confirm hold-time =
C·ΔV/(45 nA + cap leakage) at BOM-lock. **Reviewer:** verify the leakage
argument and the VBACKUP max vs trickle voltage.

---

## DR-24 — Assembly reality: three key parts are leadless (hand-solder concern)  [RESOLVED 2026-07-01 (D33) — reflow + stencil; U4 repackaged to SOT-23-6; U1/U6 stay leadless]

**Surfaced by the COTS sweep (API `package` field, 2026-06-25).** The project
is described as **hand-soldered**, but three central parts are **leadless /
bottom-terminated** — they have no accessible pins and (usually a thermal pad)
and are **not reliably solderable with an iron alone**; they want **hot-air,
a hotplate, or stencil+reflow**:

| Ref | Part | Package | Note |
|-----|------|---------|------|
| U4 | ~~TPS389030DSER~~ → **TPS3808G01DBVR** | ~~6-WSON~~ → **SOT-23-6 (leaded)** | **swapped (D33)** — leaded equivalent found |
| U6 | TPS2116DRLR (power mux) | **SOT-583** (~1.6×1.6, leadless) | kept — leaded TPS2113A costs 57× the Iq |
| U1 | LM5166YDRCR (always-on buck) | **VSON-10 3×3 mm** | leadless, has thermal pad |

(The ESP32-S3-WROOM-1 module is also reflow-style but is castellated/edge —
more forgiving. Everything else — SOT-23/SMA/SMB/SIP/THT — is iron-friendly.)

**Why it's hard to design around:** these are modern **µA-Iq** parts, and the
µA/wide-Vin/small combo is exactly what drove D19/D28/D29 — leaded equivalents
largely don't exist without giving up the power-first goal that's the heart of
the design. So "swap to a leaded package" likely means a worse part.

**RESOLVED 2026-07-01 (user has heat gun + oven → reflow available; D33).**
The stated pain was *"getting the right amount of solder on tiny pads,"* which
a **paste stencil** solves directly (exact volume per aperture; JLCPCB bundles
one). With reflow + stencil in the plan, each part was judged on merit:
- **U4 → swapped to TPS3808G01DBVR (SOT-23-6, leaded).** A genuine functional
  superset at the same Iq (2.4 µA vs 2.1 µA) — a free solderability win.
  Divider re-derived for its 0.405 V VIT (D28); datasheet stored.
- **U6 kept (TPS2116, SOT-583).** The only leaded mux (TPS2113A, TSSOP-8) draws
  ~75 µA operating vs the TPS2116's 1.32 µA — a power-first violation; the
  stencil makes SOT-583 tractable instead.
- **U1 kept (LM5166, VSON-10).** No leaded µA-Iq wide-Vin equivalent; reflowed.

**Assembly plan:** stencil + reflow (heat gun/oven) for U1/U6 + the WROOM
module; iron for everything else. **Add a stencil to the fab order.** Informs
CP3 footprint/thermal-pad/via choices for the two remaining leadless parts.

## DR-25 — RS-485 transceiver: wrong-VCC part + tied-enable can't reach shutdown + max-to-max reselect + per-board sleep policy  [RESOLVED 2026-07-02 (D34, revised iter-10, further revised iter-14 F15 + iter-16 F17 + iter-18 F18) — THVD1400DR; DE + /RE split; battery = default-shutdown, display = latched RX-active with `ext1` `ANY_LOW` wake mask (GPIO12/13/14 buttons + GPIO18 RO), triggered by master-side sustained-LOW BREAK (`DE=1, TXD=0` → A LOW, B HIGH, RO LOW). **Observable turnaround guard**: master sets `DE=0` + `/RE=0` before ACK timeout; display waits for RO HIGH ≥50 µs before asserting DE for ACK — makes the handoff observable so no driver-overlap window even if display boot completes mid-BREAK]

**Reviewer iter-8 F05 + F06, iter-10 F08 + F09.** Multi-turn resolution.

**F05 (BLOCKER, iter-8).** Both boards specified `SN65HVD3082EDR` as a
"3.3 V" transceiver and powered it from V3V3. The stored TI family
datasheet (§6.3 Recommended Operating Conditions) puts the whole
`SN65HVD30xx` family at **VCC = 4.5–5.5 V** — none of the -3082/85/88 is
a 3.3 V part. The "3.3 V" label was invented in `docs/hardware/bom.md`
and repeated across CP1 without a datasheet check
([[cots-interface-reality]], [[part-availability-early]]). Even
D-OPEN-2's "recommend keeping SN65HVD3082E" line survived without one.

**F06 (IMPORTANT, iter-8).** The enable topology tied DE (active-HIGH)
and /RE (active-LOW) across a single ESP GPIO. That gives receive (both
low) or transmit (both high), but shutdown requires **DE=0 AND /RE=1**
simultaneously — topologically unreachable. So the "silently active
~800 µA" transceiver was absent from the State-4 hard-cut budget.

**F08 (IMPORTANT, iter-10).** The iter-8 first cut picked
`ISL3175EIBZ` and quoted its **typical** shutdown Iq (10 nA) as though
it were the design bound. The datasheet **maximum** is 12 µA, 1200×
higher — a G1 (engineering-correctness) miss. Redoing the candidate
table max-to-max shifted the winner, correctly.

**F09 (IMPORTANT, iter-10).** The iter-8 sleep policy (both GPIOs Hi-Z →
transceiver defaults to shutdown) applied to the display broke the
GPIO18 UART-RX wake path — receiver off + wake-on-RX are mutually
exclusive.

**Fix (D34, current form).** After the F08 max-to-max sweep, picked
**`THVD1400DR`** (TI). VCC 3.0–5.5 V, RX-only Iq 900 µA max / 700 µA
typ, **shutdown Iq 1 µA max** (12× better than ISL3175 on the
load-bearing hard-cut spec), full fail-safe RX, datasheet-guaranteed
internal DE 2 MΩ pull-DOWN + /RE 2 MΩ pull-UP so an un-driven pair
defaults to shutdown *without external components*. Standard SN75176
8-SOIC pinout so it drops into the existing footprint. TI Active,
DK+Mouser 35016 stock, $1.38 at qty 1. Datasheet stored at
`hardware/datasheets/THVD1400DR.pdf`
(sha `5ba9785d9fb8dc878b90fd196ff5faed27b5fff0ddfccb8346a82ac3c6a5c47f`).
ISL3175EIBZ datasheet retained at
`hardware/datasheets/ISL3175EIBZ.pdf` (sha `dee60a6b…`) as the record
of the iter-8 candidate table + iter-10 max-to-max evidence.

**Enable topology fix (F06 close).** DE and /RE routed on **two
independent ESP GPIOs** (GPIO2 = DE, GPIO15 = /RE — reclaiming the
ex-debug-LED GPIO that D4 freed). **No external R_DE / R_RE resistors
needed** — THVD1400's internal pulls default to shutdown when both
GPIOs float. Saves 2 board parts vs the iter-8 first cut. Firmware
truth table in D34.

**Per-board sleep policy (F09 close, revised iter-12 F11 + iter-14 F15).**
- **Battery side (State 3/4).** Both GPIOs Hi-Z → THVD1400 internal
  pulls → shutdown (max 1 µA). Battery does not use RS-485 as a wake
  source; wakes from its own RTC timer + GPIO7 BTN_OVERRIDE only.
- **Display side (State B, revised iter-12 F11 + iter-14 F15).** ESP
  `gpio_hold_en(GPIO15)` + `gpio_deep_sleep_hold_en()` latches GPIO15
  LOW through Deep-sleep, overriding the internal pull-UP so /RE = 0
  (receiver on). GPIO2 (DE) Hi-Z → internal pull-DOWN keeps DE = 0
  (driver off). **Wake source = `ext1` `ESP_EXT1_WAKEUP_ANY_LOW` mask
  over GPIO12, GPIO13, GPIO14, GPIO18** — one RTC-GPIO wake API covers
  the 3 active-LOW buttons and the RS-485 RO wake. **NOT the ESP UART
  wake API.** Espressif docs are explicit: UART wake is Light-sleep-only;
  Deep-sleep powers off the APB-clocked UART so the triggering byte is
  lost. **Corrected wake waveform (iter-14 F15, polarity + bus-ownership
  tightened iter-16 F17, observable turnaround guard added
  iter-18 F18):** the master drives the RS-485 pair with
  **`DE=1, D/TXD=0`**, which per
  [THVD1400 §7.4](https://www.ti.com/lit/ds/symlink/thvd1400.pdf)
  Function Tables puts **A LOW, B HIGH, `V_A − V_B` negative** on the
  bus → every enabled receiver drives **RO LOW**. Hold for a
  sustained-LOW interval bounded ≥3 RTC slow-clock cycles (~20 µs at
  the 150 kHz internal slow clock) + margin. **CP2 firmware nominal
  is 50 ms** — orders of magnitude above the 20 µs sampling minimum
  and comfortably above ESP32-S3 wake+boot (~10 ms typical from
  Deep-sleep). **Bus-ownership with observable turnaround guard**
  (F17 + iter-18 F18): the display can and often will finish booting
  inside the master's 50 ms BREAK window, so numbered ordering alone
  cannot prevent driver overlap — both sides need an observable
  condition. `ESP_EXT1_WAKEUP_ANY_LOW` is a **level** wake, so ext1
  fires during the LOW sampling window itself (not on the LOW→HIGH
  transition when the master releases).
  - **Master:** `DE=1, TXD=0` → BREAK → hold 50 ms → **set `DE=0`
    AND `/RE=0` simultaneously** (deassert driver + enable own
    receiver) *before* starting the ACK timeout, otherwise the
    master cannot observe the display's ACK arriving → watch RO
    for the ACK frame → on ACK, transmit payload.
  - **Display:** ext1 fires on LOW-level → ESP wakes + boots →
    firmware initializes with **`DE=0` kept low** (/RE=0 already
    latched via `gpio_hold_en(GPIO15)` so RO is valid) → firmware
    polls GPIO18/RO until RO has been **HIGH continuously for a
    bus-idle guard interval ≥50 µs**, sized against the slowest
    relevant THVD1400 §6.7 path: driver-disable
    `tPHZ/tPLZ = 80 ns typ / 200 ns max` plus receiver-enable/
    fail-safe `tR(F) = 4 µs typ / 10 µs max` — the 10 µs
    receiver-fail-safe max dominates and 50 µs is ≥5× that path plus
    4 µs UART-bit noise margin at 250 kbps → display asserts `DE=1`,
    transmits ACK, sets `DE=0`.
  The guard makes the handoff observable: display cannot assert DE
  until it sees the bus idle, which requires the master's `DE=0`
  transition to have propagated through THVD1400's driver-disable
  time. This eliminates the driver-overlap risk left open when boot
  happens to complete mid-BREAK. **CP2 bench-verify:** scope both DE
  pins simultaneously plus A/B/RO and confirm no driver-overlap
  window ever appears — including cases where display boot completes
  mid-BREAK. BREAK duration + guard interval + ACK timeout + retry
  policy are CP2 firmware-layer decisions. Transceiver draws its RX-only Iq (~900 µA max)
  continuously in State B — appears explicitly in the display §7 State
  B budget. GPIO12/13/14/15/18 all RTC-capable per Espressif ESP32-S3
  datasheet Table 5-3. **Alternative rejected: Light-sleep + UART wake**
  (revised iter-14 F15 numbers). ESP32-S3-WROOM-1-N16R8 module datasheet
  Table 6 lists Light-sleep at **240 µA typ** plus **~140 µA for the
  N16R8's 8-line PSRAM** (retention), so Light-sleep vs ~10 µA Deep-sleep
  is a **~0.37 mA (~1.2 mW at 3.3 V)** mode delta — not the ~1 mA/~3 mW
  I quoted iter-12. Even Light-sleep loses the UART triggering character
  per Espressif docs so a preamble byte is normally still required.
  Deep-sleep + BREAK still wins on power (1.2 mW is meaningful on a
  ~1 mW hard-cut budget and ~50 mW display State A total) and unifies
  buttons + bus on one wake API.

**Hard-cut impact (revised iter-12 F13 + iter-14 F16 wording sweep —
rebuilt on datasheet max where spec'd + explicit engineering margin
where no max is published).** Transceiver contribution ≤ 1 µA max @
3.3 V ≈ 7 µW referred — inside the µW rounding floor. Full State-4 sum
uses **max** for LM5166 (15 µA), TPS3808 (5 µA), TPS2116 (4.5 µA), and
THVD1400 (1 µA); **typ + margin** for ESP32-S3 Deep-sleep (10 µA typ
+ 5 µA margin, since Espressif publishes no spec max in ES §5.4) and
RV-3028-C7 RTC (45 nA typ, ≤200 nA per Micro Crystal AN — well under
the µW floor) → **~1.1 mW** headline (iter-48 F76: the discrete Q1/Q2 gate driver → AQY212EH SSR, whose ≤1 µA off-leakage removed the gate-network terms; was ~1.08 mW pre-leakage, and ~1.0 mW iter-6,
then claimed "max throughout" iter-10 with typ still buried, corrected
iter-12 F13, wording tightened iter-14 F16 across power_budget.md /
D34 / DR-25 / cp1_battery_side.md §7 State-4 row). Order-of-magnitude
conclusion unchanged.

**Display idle bias R3/R4 policy (iter-12 F12 close).** R3/R4 at
~330 Ω would draw 3.3 V / 720 Ω = **4.58 mA ≈ 15 mW** continuously
whenever the display board is powered. This was omitted from States A
and B and mis-labeled "free margin". THVD1400 datasheet §8.2.1.4
guarantees Full Fail-Safe RX (open/short/idle bus all drive RO HIGH
built-in) so the bias is not needed for correct RS-485 idle behavior.
**Marked DNP by default** in both BOMs and both packet §4.5 tables;
footprint remains on the PCB so it can be stuffed at CP5 bench if EMI
testing reveals a need. Removes 15 mW × States A+B duty from the
display budget — meaningful given State A totals ~29 mW at 3.3 V.

**DR-13 (RS-485 bias margin) note.** THVD1400's built-in Full Fail-Safe
makes the previously-critical DR-13 bias a noise-margin luxury, not a
correctness requirement — hence the iter-12 F12 DNP decision. If bench
testing shows spurious RO glitches, populate at ~330 Ω and re-budget
the 15 mW. Prior justification lines about the receiver's guaranteed
threshold:
(datasheet §8.2.1.4), so 275 mV of A-B differential is comfortably in
the guaranteed-HIGH region. Bias is noise-margin insurance, not a
fail-safe requirement.
DR-13 stays RESOLVED with the improved threshold picture.

## DR-26 — RS-485 wired battery read: co-equal alternative transport (both packs)  [OPEN — design proposed 2026-07-15 (D36); needs CP1-delta review before CP2]

User directive: BLE to the two BMS is worryingly flaky → add a real,
populated wired read path as a **co-equal alternative** (may become
primary — not pre-judged). Design: [`../layout/cp1_rs485_battery_read.md`](../layout/cp1_rs485_battery_read.md); decision **D36**.

Because the two 12 V packs are in **series** and the protocol is polled,
the front-end must float to each pack's reference → **two isolated
channels** (ADM2587E), **symmetric/interchangeable**, addressed by
protocol address. Reuses the `ej_bms` parser.

**Interface premise — REDACTED TRANSCRIPT ON FILE (F45 closed 2026-07-16; F55: owner-supplied redaction, original off-file);
on-site test is TOPOLOGY-GATING (F47).** The owner supplied the original
`.eml`; a redacted transcript with headers is committed
([`../../docs/vendor/Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`](../../docs/vendor/Voltage_monitoring_thread_2023-2024_redacted_transcript.txt),
original SHA-256 `37df1ab1…`). Verified verbatim (2024-03-28): *"Use a
Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V
adapter directly."* → RS-485 (not TTL), 2-wire/no-ground, A/B on RJ45
**7/8** (double-sourced: thread 2024-01-15 + photographed label); socket
closest to the negative terminal. **CAN pin-domain resolved**: the
thread's "pin 1 and 2" is the battery-side connector (owner's 2023-12-27
question is explicit). **Connector + conductor map measured 2026-07-17**
(cable photos on file): 4-position M12-pattern screw coupling, ~12.3 mm
thread ID, numbered 1→4 CCW; beep-out gives battery 1/2 = CAN-H/L →
**RJ45 4/6** and battery 3/4 = RS-485 A/B → RJ45 7/8. **The separate
Pro-Series *label* prints CAN on RJ45 4/5 — a different cable product,
not the in-service cable; the two are NOT the same map** (F63). The
purchased cable ends RJ45-male → direct mate. Vendor PN never supplied
— not load-bearing. On-site side-item
remaining: which socket per pack. The isolated ADM2587E front-end
is the correct circuit class under this premise.
**DR-26 stays OPEN and GATING on the ~2-week on-site test** — the test
decides whether the floating island needs a local reference/bleed;
**pass limits (top-pack read 0-CRC-fail, −7…+12 V CM window, ≥±1.5 V
differential margin, clean idle/recovery, both orientations) + the DNP
fallback circuit are specified in design §7.**

**Current topology (iter-30, F30) — supersedes the first draft:**
- Off-state: **dedicated per-channel DI/DE/RO** on the ESP, UART2
  matrix-muxed to the active channel, inactive pins held **high-Z**;
  8 GPIOs. *(The first draft's "1 kΩ series on DI + wire-OR RX pull-up"
  is retired — it leaned on the ADM2587E's unspecified VCC=0 behavior.)*
- isoPower support (iter-31, F35): full net-by-net set — VCC bypass
  0.1+0.01 (pin 2) & 0.1+10 µF (pin 8); VISOOUT(12)↔GND2(11) 10+0.1 µF;
  VISOIN(19)↔GND2(20) 0.1+0.01 µF; **two** ferrites (L1 VISO, L2 GND2);
  GND1↔GND2 stitching cap rated to VIORM 524 Vpeak. Leaded wide SOIC,
  creepage-critical.

**Review asks:**
- **G1 (gating): the on-site test** (design §7 pass limits) — decides
  the local-reference/bleed question; D36 nets freeze after it passes.
- G1: **F36/F44 protection status = DNP, intentionally unprotected** —
  SM712 VC 20 V > ADM2587E +14 V abs-max, and a series R alone cannot
  coordinate into a high-Z pin (no published injection rating); the
  iter-32 "coordinated pair" claim is withdrawn. Accepted risk for the
  inside-enclosure link. ±15 kV is HBM, not IEC cable ESD.
- G1 (iter-34, F43): isolated-side grounds are **two nets** —
  `GND2_DCDC` (pins 11+14) / `ISO_BUS_GND` (pins 16+20 + plane), L2 the
  only tie (Rev H p.8 "do not connect Pin 16 to Pin 14/11"; p.17 Fig 35).
- G2: **D32 closed** — ADM2587E (90 mA @ 3.3 V/100 Ω; F28 fix of the
  72 mA=5 V-row mis-cite) + **Semtech** SM712 (F29) on file, verified.
- G3: re-verify stock at BOM-lock.
- Power: gated ~0.5 % → ~1.5 mW avg; States 3–4 unpowered → hard-cut
  unchanged (contingent on the F30 off-state + default-off switch).

## DR-27 — Battery-side PicoBlade expansion header (D37)  [OPEN — design 2026-07-15; folds into the same CP1-delta review as DR-26]

8-ckt Molex PicoBlade (53398-0871 vert / 53261-0871 r-a). Signals: 3V3,
GND×2, dedicated **I2C1** (SDA/SCL, isolates the RV-3028 timekeeping bus),
2× **ADC1+RTC-wake** AIO, 1 generic DIO. Rationale/pinout: decisions.md
**D37**.

**Power domain (iter-36, F48/F51 — supersedes the iter-34 wording):**
the EXP_3V3 pin is a **load-switched, default-OFF** rail — a
**direct-GPIO-driven NTR4171P** (F51: no 2N7002 level shifter — source
= 3V3 = the GPIO domain; 100 kΩ gate pull-up; `EXP_PWR_EN` active-LOW),
**force-OFF in State 4**, with a **testable off-state contract**
(decisions.md D37): I2C pull-ups powered from the **switched** rail; all
5 signals **high-Z before/while rail-off** (firmware, binding);
**R_exp_bleed 100 kΩ** parks the rail ≤ 50 mV. Off-leakage bound stated
honestly (F51; FET = NTR4171P per F61 — RDS(on) guaranteed 150 mΩ @ −2.5 V; replaced DMG3415U, which was itself NRND): IDSS ≤ 1 µA @25 °C / ≤5 µA @85 °C (−24 V) is a **test point, not
a full-range max**; engineering **allocation ≤ 5 µA @ ≤40 °C ambient**,
with the **bring-up acceptance measurement as the binding limit**
(V(EXP_3V3) ≤ 50 mV, block draw ≤ 5 µA, add-on plugged, rail off);
fallback if exceeded = specified-over-temp load-switch IC (part swap,
no respin). It is **on/off gating, not a current limiter** (real ceiling
= F1 1 A + LM5166 500 mA). *(The first draft's "series ferrite /
budget-counting always-on 3V3" is retired — a ferrite is not a DC
limit.)*

**Mate/rating (iter-36, F49/F53 — CLOSED):** exact header-system spec
**PS-51021-024 Rev AD on file** (owner upload 2026-07-17, sha
b7d3ec9b74b9): scope lists **53398\*\*71 vertical headers (ours)** +
51021 housing + 50079/50058 terminals; ratings **1.0 A max (AWG
26/28/30), 125 V, −40…+105 °C**; 8-ckt derating reference 1.5 A
(AWG 26/28) @ 30 °C rise, reference-only. PS-51021-009 retained scoped
to the wire-to-wire mate side only. Qty-1 mating = OTS cable assembly
**0151340801** (DK WM15273-ND, Active, $10.53 — optional, with the
add-on); loose terminals have 25k MOQ.

**Review asks:**
- Pin map (CP2): each expansion pin on a GPIO with the required
  capability — 2× **ADC1** (GPIO1–10, not ADC2/WiFi) **and** RTC-wake;
  I2C1 on a second controller; DIO on GPIO38–42; `EXP_PWR_EN`; and **no
  clash** with D36's 8 GPIOs or the module's flash/PSRAM (GPIO26–37).
- Protection: series-R footprints on all 5 signals (F48 item 6) + ESD on
  exposed IO (DNP vs populate).
- Dedicated vs shared I2C: confirm dedicated-I2C1 (RTC isolation).

## DR-28 — SSR switched-branch bring-up acceptance tests (F83 hot leakage + F84 fault coordination)  [OPEN — tests defined, run at CP5 bring-up]

Two design claims on the AQY212EH switched branch rest on **bring-up
measurements**, not on guaranteed datasheet maxima, and must be captured as
actionable acceptance tests rather than left as prose (self-caught before
the reviewer, post-iter-52):

1. **State-4 leakage (F83).** The AQY212EH off-leakage is a **25 °C ≤1 µA
   spec with no published hot maximum**. State-4 is guaranteed ~1.1 mW at
   25 °C; the 85 °C figure is an *engineering estimate* (~30–60 µA →
   est. ceiling ~2.5 mW). **Acceptance test:** with SSR1 open (hard-cut),
   measure total pack-referred State-4 power across the operating
   temperature range (or at the 85 °C worst case). **Pass: < 5 mW.** Fail →
   swap to an SSR with a guaranteed hot-leakage max (the no-self-turn-on
   architecture is unaffected either way).

2. **Fault/inrush coordination (F84, re-coordinated iter-54 for F86/F87).**
   R_inrush = **2× 75 Ω 1206-HP in series (=150 Ω)** + F2 = **80 mA**.
   Worst case (29.2 V, R−1 %, no fuse/SSR credit): I=0.197 A. Analysis:
   inrush 0.197 A < SSR 0.30 A@85 °C continuous (0.66×); short 0.197 A =
   246 % of F2 (214 % at −40 °C) clears within 200 %→5 s; fault power 5.74 W
   total = **2.87 W each < the CRCW-HP §8.1 guarantee 4.69 W/5 s at P70**;
   turn-on I²t 9.5e-6 = 2.9 % of F2 melt I²t at C3=3.3 µF (≤4.3 % at the
   5 µF max-effective ceiling; ≤20 %/100 k Littelfuse *selection basis*).
   **C3 selection gate (F90):** the exact C3 chosen at CP5 must have
   **max-effective capacitance ≤ 5 µF** over initial tolerance + X7R
   temperature + aging (DC bias only reduces it); otherwise re-derive.

   **Quantified bring-up acceptance test plan (F90):**
   | Test | Units | Cycles/unit | Temperatures | Cooling | Pass criterion |
   |------|-------|-------------|--------------|---------|----------------|
   | (a) F2 turn-on pulse-cycle endurance | **≥ 3** | **1 000** turn-on cycles (a **1 %** engineering screen of the ≤100 k life bound — **not** a full life test, and no acceleration factor is claimed; the ≥100 k margin rests on the Littelfuse 22 %/100 k **selection basis**, F90) | 25 °C + **85 °C** (hot = worst for fuse fatigue) | **≥ 10 s** between cycles | F2 cold resistance rise **≤ 10 %** and no open; R_inrush value within ±1 %; SSR Ron within spec |
   | (b) Turn-on inrush peak | ≥ 3 | 1 | −40 / 25 / 85 °C | — | measured peak **≤ 0.22 A** (≤ SSR 0.30 A@85 °C continuous) |
   | (c) Fault clear | **≥ 2** (sacrificial) | 1 deliberate V24_SW short | **−40 °C** (worst) + 85 °C | — | **F2 opens ≤ 5 s**; both R_inrush 75 Ω halves and the SSR measure undamaged afterward |
   | (d) State-4 leakage (F83) | ≥ 3 | — | 25 / 85 °C | — | total pack-referred hard-cut power **< 5 mW** |

   **Lifetime bound:** SOC-hard-cut→recovery is a rare event; bound it at
   **≤ 100 000** over life (≫ realistic — daily for 27 yr ≈ 10 000). If the
   field rate could exceed that, re-derate F2 or add cooling headroom. Any
   test failure → re-pick the fuse/R_inrush/C3 network.

**Why OPEN:** these are physical measurements deferred to CP5 hardware
bring-up; the design is complete and analysis-backed, but the claims are
not closed until measured. Neither gates CP1 architecture.

## DR-29 — U1 LM5166 CP2 component network: PFM (not COT) + concretized L/C/ILIM  [RESOLVED 2026-07-19 — user approved PFM ("no real downside to PFM"); CP1 §4.2 reconciled]

CP2 schematic capture required valuing U1's support network, which CP1
(`cp1_battery_side.md` §4.2) left partly deferred. The values below are
derived from the LM5166 datasheet (`LM5166YDRCR.pdf`), cross-checked
against TI's own **Design 3** (24 V→3.3 V fixed, the near-exact match to
this instance). One choice **reverses a CP1 assumption** and is flagged
for a user nod:

| Pin/part | CP2 value | CP1 said | Basis |
|----------|-----------|----------|-------|
| **Mode (RT pin)** | **PFM** (RT→GND) | "low-Iq **COT** mode favors a larger L" (§4.2 L1 row) | PFM sleep Iq = COT sleep Iq (9.7 µA typ/15 µA max), but PFM **active** Iq 205 µA vs COT 320 µA and PFM has longer sleep intervals at light load (§6.5, §7.3.2.2). For an always-on light-load rail, PFM is the lower-Iq choice — and it's TI's pick for the 24 V/3.3 V Design 3. **This is the reversal to confirm.** |
| **L1** | **4.7 µH**, Isat ≥ 2.2 A, low DCR | 10–47 µH ≥0.3 A | L_min ≈ 3.3 µH at worst case (Eq 29); Design 3 uses 4.7 µH/2.2 A. The "10–47 µH" guess assumed COT; PFM peak-current sets a smaller L. |
| **R_ILIM** | **56.2 kΩ** → 750 mA peak / 300 mA IOUT (PFM) | (unspecified) | Table 3 (§7.3.5). Covers 250 mA sustained Wi-Fi; 500 mA sub-ms peaks buffered by C2 (consistent with CP1 §4.2 "C2 buffers sub-ms peaks"). 24.9 kΩ (→500 mA IOUT) is the higher-margin alt if sustained load hardens — not needed for the 250 mA sustained case. |
| **C2 (VOUT)** | **47 µF / 25 V** X7R 1210 | 22 µF / 25 V | Eq 31 needs ~22 µF at peak-current overshoot; 22 µF/25 V derates to ~18 µF effective → under. 47 µF gives margin (Design 3 uses 47 µF). Voltage rating unchanged. |
| **EN** | tie **direct to VIN** (no divider) | (implied always-on) | "connect EN directly to VIN" (§7.3.6); EN rec-op max **65 V** ≥ 53.3 V clamp ceiling. A UVLO divider here would only add continuous bleed — pack-UVLO is the separate U4 supervisor's job. HYS/SS/PGOOD left open (Design 3). |
| **C1 (VIN)** | 22 µF / 100 V (unchanged) | 22 µF / 100 V | Confirmed ≥ CIN min, rating ≥ 2×VIN behind the clamp. |

**Iq impact:** EN→VIN, HYS/PGOOD/SS/RT all open-or-short → **zero added
continuous bleed** beyond the IC's 9.7 µA typ / 15 µA max sleep Iq — fully
preserves the CP1 hard-cut budget.

**Why OPEN:** the PFM-vs-COT reversal is the one judgment where CP1 leaned
the other way; the rest are datasheet concretizations of deferred values.
All are analysis-backed and the schematic is built with them (ERC-clean,
readable). Non-gating for the block's structure — only the values would
change if the user prefers COT (then L1→larger, R_ILIM/C2 re-pick).

## DR-30 — CP2 schematic capture of the isolated RS-485 read (DR-26) + remaining battery-side elements  [OPEN — drawn + self-verified 2026-07-20; DR-26 test still gates population]

CP2 drew the DR-26 isolated RS-485 subsystem (2× ADM2587E channels, one
sheet each) plus the battery-side elements that were BOM-listed but not yet
captured. All 8 battery sheets are readability-gate-clean and per-sheet
ERC-clean; the assembled hierarchy is ERC-clean (only the known headless
dangling artifact + the 1 pre-existing power-flag baseline).

**Added this pass:** the 2 iso channels (U10/U11 + isoPower network + power-
gates + DNP protection cluster + J10/J11 RJ45 + the 8 MCU GPIOs, itemized in
the new BOM subsection); **C_mux** (47 µF mux-OUT bulk, reviewer F11 — was
missing); **U-ESD** (USBLC6-2SC6 on J3, was missing); **J4** (RS-485 term-
lift jumper in series with R10); **J5** (debug/console UART header on
U0TXD/U0RXD). MCU pins re-checked: the 8 iso GPIOs (IO6/16/13/14/21/47/48/39)
avoid all strapping/PSRAM/console pins.

**Defects caught + fixed during self-review (evidence the pass worked):**
- **Critical net-name disconnect:** the iso power-gate source + default-OFF
  pull-up were wired to `3V3`, but the whole design's rail is `V3V3` → the
  ADM2587E VCC would never have been powered and default-OFF would not hold.
  Fixed (both channels). Caught by a full-schematic net-name reconciliation
  (all nets now appear on ≥2 sheets except the 2 intentional `PACKn_Bminus`
  REF pads).
- **RJ45 footprint typo:** `RJ45_Amphenol_RJHSE-5380`/`-538X` (hyphen) don't
  exist in KiCad's `Connector_RJ` lib — corrected to the no-hyphen names on
  J2 (pre-existing) **and** J10/J11.
- **isoPower ferrites** were placeholder `"ferrite"` → specified TDK
  MPZ2012S601 (600 Ω/2 A/0805), now a BOM line item (L10–L13).
- **Three symbol-readability defects (found on user review 2026-07-22, fixed):**
  (1) **root sheet overflow** — the 8 hierarchical-sheet boxes were on a grid
  sized for 6, so the bottom row (MCU + Connectors&I/O) ran off the bottom
  frame and printed over the title block; regridded to a 2×4 that ends above
  the title block. (2) **U-ESD (USBLC6-2SC6)** and (3) **D10/D11 (SM712)** each
  rendered their *own* pin-name glyphs inside a small body — `I/O1/I/O2/VBUS/
  GND` over the ESD diode array, and `A1/A2/`vertical-`Common` over the
  `D#/SM712` text — as illegible mush. Fixed by blanking those pin names (net-
  label stubs carry the meaning; pin numbers stay). J5's `Conn_01x04` had the
  same generic-`Pin_N` issue and was added to the existing connector name-blank
  list. **Root-cause of the miss:** the readability gate models bodies, ref/
  value text, labels, and wires, but is **structurally blind to a symbol's own
  pin-name/number glyphs** — so it can't catch name-over-art / name-over-
  refdes, and the visual pass that *would* have caught it was shortcut. A full
  8-sheet symbol-zoom re-sweep confirmed no other instances.
  **RESOLVED 2026-07-22 — gate limitation closed + deeper root cause found:**
  the true root cause was **kiutils (KiCad-6 era) failing to parse KiCad-10's
  nested `(pin_names … (hide yes))`** — the flatten silently UN-hid pin names
  the library author explicitly hid (USBLC6, SM712, Conn_01x0N, 2N7002's
  G/D/S, SW_SPDT's A/B/C, PWR_FLAG). Fixes, all in build.py:
  (1) `_raw_pin_names_hidden()` reads the RAW library (following `extends`)
  and restores the intended hide by blanking names — replaces the hand-kept
  blank list; (2) the readability gate now models symbol-own pin-name/number
  glyph geometry (`pin_glyph_boxes`/`art_boxes`) and collides it against body
  art, outline edges, ref/value text, labels, and other glyphs — regression-
  proven (un-hiding SM712 fails the gate; restored = 0 flags); (3) the glyph
  gate immediately caught real defects on sheets previously passed as clean:
  **U1 stacked pins 10/11** (pad "11" overprinting "10" — spread + wired) and
  **U6 stacked VOUT 2/7** (the twin was no_connect'd ON the driven wire —
  spread + both wired); (4) a **footprint hard gate in place()** (existence +
  lib-prefix normalization) after 6 phantom footprints surfaced: U6
  "Package_SON:Texas_SOT-563" → SOT-583-8 (BOM already said SOT-583), J1
  MSTBA name typo, RTC1 invented C7 name → MicroCrystal_C7_SON-8, BTN1
  fictional lib → 1x03 THT holes for the panel-button flying leads, SSR1
  nonexistent Relay_SolidState lib → Package_DIP:DIP-4_W7.62mm, F1/F2 →
  Keystone-3517 clip / NANO2-451 patterns; bare `R_/C_/L_/D_*` names now
  auto-prefixed (they would all have failed footprint resolution at CP3).

**Still OPEN (needs a call / BOM-lock task):**
- **C28/C38 (C_stitch HV Y-cap):** must be a safety-agency-rated Y1/Y2 part
  to the *working* voltage (VIORM 524 Vpk / 396 Vrms, IEC 60747-17) — not the
  2500 Vrms 1-min proof. No live SKU yet; pick a rated Murata DE/GA-class cap
  at BOM-lock. Left `_verify_` in the BOM.
- **EXP I2C pull-ups:** DR-27/D37/F48 says the expansion I2C (EXP_SDA/EXP_SCL)
  gets pull-ups on the *switched* EXP_3V3 rail; the current `blk_exp` has the
  rail + Q_exp + bleed but no dedicated EXP-side I2C pull-up resistors. Verify
  whether those live on-board or on the (optional) daughterboard before CP5.
- DR-26 itself stays OPEN and **gating on the ~2-week on-site two-domain
  test**; the schematic/BOM are drawn so the test can run, but population of
  the isolated front-end is not committed until it passes.

---

## DR-31 — Xanbus CAN read (provisioned)  [OPEN — drawn + verified 2026-07-22; population gated on the Xanbus software work]

**User-approved requirements change (2026-07-22):** add a CAN transceiver so
the reader can listen to the **Xanbus** network of the Schneider stack
(XW+-class inverter + MPPT charge controller + optional InsightHome). The
protocol work is a software project outside this repo; the hardware is
provisioned now because adding it at CP2 costs ~$6 of parts while adding it
later costs a respin.

**Verified interface facts (COTS interface-reality):**
- Xanbus physical layer = CAN 2.0 @ 250 kbps over RJ45 daisy-chain.
- **CAN_L = RJ45 pin 4, CAN_H = pin 5, no ground pin** — per the LYNK II
  gateway manual for exactly this Schneider stack (Discover 805-0052 Rev B,
  §4.2.1 "Xanbus Pin Assignments"; PDF reviewed 2026-07-22). The LYNK II is
  a battery-side Xanbus device relying on the shared DC bank for common-mode
  reference — the same topology as this reader (user-confirmed: all devices
  on the 24 V bank; batteries not on the Xanbus; no battery center tap).
- Other RJ45 pins carry Xanbus **network power** — left NC, never touched.
- 120 Ω termination required only at chain ends → **R15 in series with the
  J7 jumper: fitted = terminated, pulled = mid-chain** (user asked for easy
  on/off).

**Design (sheet_periph, blk_can):** U7 **TCAN332DR** (3.3 V CAN, ±12 V CM,
±14 V bus fault, 12 kV IEC ESD integrated; SOIC-8 leaded; DK 296-43711-1-ND,
6.3k stock, CA$3.69, Active; datasheet TCAN332.pdf on file, SLLSEQ7F) —
key property: **bus pins high-Z when unpowered**, so the default-OFF power
gate (Q5 NTR4171P, CAN_PWR active-LOW + 100 k pull-up — the CH1/CH2 pattern,
zero parked draw, power-first) also guarantees the sleeping reader never
loads the live Xanbus. D2 **NUP2105L** dual CAN TVS (belt-and-braces for the
field cable; CA$0.66). MCU: TWAI (native CAN controller) on **IO40=TXD,
IO41=RXD, IO42=CAN_PWR** — the last free safe GPIOs (JTAG forfeited; debug
stays on J5 UART). **GPIO budget is now exhausted.**

**Still open:** bench-verify pin 4/5 polarity on the actual Schneider port
before first live attach (measure recessive ~2.5 V bias / dominant split with
the pack on); decide populated-vs-DNP at BOM-lock once the software project
firms up (parts are cheap — default: populate U7/Q5/D2/R14/R15/C12/J6/J7,
leave J7's shunt off unless the reader is a chain end).
