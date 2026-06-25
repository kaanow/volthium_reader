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
cold-start, and again ~22 µF (C3, U2 input on V24_SW) when Q1 enables the
display. With ceramic ESR + SS26 + trace ≈ 0.1–0.5 Ω, single-event
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
**EN-asserting** supervisor (**U4 = TPS3890**), not a Q1-only shed. The key
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
R-78HB12 / R-78E3.3 −40, SN65HVD3082E −40, TPS3890 −40, all ceramics X7R −55
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
