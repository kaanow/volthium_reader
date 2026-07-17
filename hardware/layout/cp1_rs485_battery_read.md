# CP1 addendum — RS-485 battery read (alternative transport, both packs)

**Status:** design proposed 2026-07-15 (user-directed). Extends the
approved CP1 architecture; **needs a CP1-delta review pass before CP2**.
**Driver:** BLE to the two BMS has been *worryingly flaky* in the field —
worse than the "benign, self-correcting" characterization in
[`../../docs/firmware/ble_flap_recovery.md`](../../docs/firmware/ble_flap_recovery.md).
This adds a **real, populated wired read path** as a **co-equal
alternative transport** to BLE — deliberately *not* framed as a mere
backup: if the wired path proves more reliable on the bench/in the field
it may become the **primary**, and that call is left open, not baked in.
Both transports feed the same decoder; firmware runs them in parallel and
the selection/merge policy is a field decision. Board space/volume is
explicitly **not** a constraint on the battery side.

---

## 1. The governing constraint — why this is not one shared bus

The two **SC12200G4DPH 12 V packs are wired in series** to make the 24 V
system (README + `volthium/pack.py`). Each pack's comms port is
TTL-referenced to **its own** B− terminal, not to system ground:

| Pack | Comms-ground potential vs system GND |
|------|--------------------------------------|
| **A** (bottom, id 0533) | ≈ 0 V |
| **B** (top, id 0667)    | ≈ **+12 V** (up to +13 V at a 26 V full charge) |

This is a **polled** protocol — the master transmits a query and the
pack answers — so the binding constraint is the **transmit** direction,
not just reception. Pack B's BMS receiver is referenced to +12 V. A
3.3 V RS-485 driver referenced to *system* ground puts its A/B at ≈ 1–3.5 V
absolute → roughly **−9 to −11 V common-mode as seen by pack B** (−13 V
at a 26 V charge), past pack B's own **−7 V** input limit (RS-485 valid
range −7 V…+12 V; THVD1400 datasheet on file). So a system-ground driver
**can't reliably poll the top pack** — and a wide-common-mode *receiver*
doesn't fix it, because it's the drive reference that's wrong. To land
our signal inside pack B's window our front-end must sit **at pack B's
+12 V reference** — i.e. *float* to it. Floating a DC-coupled transceiver
is galvanic isolation. (CAN is worse still — ISO 11898 common-mode is
≈ −2…+7 V — which is why CAN is reserved for a future pack→inverter
bridge, not for reading.)

**Therefore: two galvanically-isolated channels.** Each ADM2587E floats
to whatever pack it's connected to and references **locally** — its own
isolated supply is the ground and fail-safe bias resistors tie A/B to
the local rails. In the **primary topology** the only per-pack
connection is the 2-wire A/B pair through the vendor pack-connector→RJ45
cable (Ethernet gets away with no ground the same way: it's isolated) —
**conditional on the §7 two-domain acceptance matrix passing (F52/F58)**;
the qualified fallback is a per-channel **REF conductor** to that pack's
B− (§7). *[The earlier "optional ~1 MΩ bleed to a bus line" idea is
superseded (F52/F58) — the reader drives the bus lines relative to its
own island, so a bleed to one references nothing while the reader
transmits.]* BLE is RF-isolated for the same reason —
the two transports are isolation-equivalent, which is part of why the
wired path is a genuine alternative and not just a fallback.

**Symmetric by decision (user, 2026-07-15): the two channels are
identical and interchangeable — either pack may plug into either RJ45.**
Because each channel is isolated and self-referencing, the physical
assignment is irrelevant; the firmware distinguishes the packs by
**protocol address** (`0x01`/`0x02`), not by which jack. (The asymmetric
option — read the bottom pack non-isolated off system ground, isolate
only the top — was considered and rejected in favor of uniform,
swappable channels; see §8.)

---

## 2. Topology

One shared ESP **UART2** (confirmed free: the ESP32-S3 has three UART
controllers per its datasheet — UART0 = console, UART1 = display RS-485,
**UART2 = this bus**), fanned to **two identical, interchangeable
isolated RS-485 front-ends** (channels 1 and 2 — *not* bound to a
specific pack; either pack plugs into either jack). Only one channel is
powered at a time; **power-gating selects the channel**, and — per §2a —
each channel's **logic pins go to *dedicated* ESP GPIOs** — the retired
wire-OR / shared-DI fan-out (superseded, F30) is gone — so the interface
never depends on the ADM2587E's
*unspecified* powered-off pin behavior. The ESP is the bus master and
polls **sequentially by protocol address** (`:01…~` then `:02…~`);
firmware learns which pack is on which jack from the address in the reply.

```
                         ┌─────────── ISOLATION BARRIER ──────────┐
                         │                                        │
  ESP32-S3   DI1,DE1 ────┼──► ADM2587E ch1 ─A/B─► RJ45_1 ◄─vendor M12↔RJ45-male cable─► (either pack)
             RO1     ◄───┼──  (iso xcvr + iso DC-DC)
                         │        VCC ◄─[P-FET load switch 1]◄─ CH1_PWR
             DI2,DE2 ────┼──► ADM2587E ch2 ─A/B─► RJ45_2 ◄─vendor M12↔RJ45-male cable─► (either pack)
             RO2     ◄───┼──  (iso xcvr + iso DC-DC)
                         │        VCC ◄─[P-FET load switch 2]◄─ CH2_PWR
                         │                                        │
                         └────────────────────────────────────────┘
   UART2 TX/RX routed via the GPIO matrix    │   Isolated side per channel —
   to the *active* channel's DI/RO;          │   floats to whatever pack is
   inactive channel's DI/DE/RO held HIGH-Z   │   plugged in; references locally
   (ESP pins = input) — see §2a              │   (iso-supply GND + fail-safe bias)
```

Because both channels are isolated and self-referencing, the design is
**pack-agnostic**: swap the two cables and nothing changes but which
address answers on which jack. No jumper, no per-jack configuration.

### 2a. Off-state contract (F30 — reviewer iter-29)

The first draft power-gated VCC and *assumed* an unpowered ADM2587E's RO
went high-Z and its DI/DE could be driven safely. **The datasheet does
not specify RO/DI/DE behavior at VCC = 0** (Table 1 input/output specs
apply only over 3.0–5.5 V), so the retired wire-OR'd RO or a driven DI
could clamp or back-power the "off" channel. Superseded by making the off-state
**enforced by the ESP, not assumed of the transceiver**:

- **Dedicated pins (wire-OR retired).** Each channel's `DI`, `DE`, `RO` land on
  their own ESP GPIOs (RO1/RO2 are separate inputs — never tied). `/RE`
  tied low per channel (RX on while that channel is powered).
- **Matrix-muxed UART2.** The ESP32-S3 GPIO matrix routes UART2_TX→DIx
  and UART2_RX←ROx to the **active** channel only, reconfigured in
  firmware per poll (datasheet-confirmed: WROOM-1 UART is matrix-mapped
  to any GPIO).
- **Inactive channel = fully high-Z.** Before de-asserting `CHx_PWR`,
  firmware sets that channel's `DIx/DEx/ROx` ESP pins to **input
  (high-Z)**. So the off channel is *both* unpowered *and* undriven —
  nothing sources current into its de-energized pins, and nothing depends
  on its outputs. This removes all reliance on unspecified VCC=0 behavior.
- A small **series R (≈1 kΩ) on each DIx** remains as a belt-and-braces
  limit during the ~1 ms power-up settle window.

Cost: 6 signal GPIOs (DI/DE/RO ×2) + 2 `CHx_PWR` = **8 GPIOs**, no added
parts. (Alternative if GPIOs get tight: a single 2:1 bus mux/buffer with
a *specified* partial-power-down — trades a part for 3 GPIOs. Deferred
unless the CP2 pin map demands it.)

Remaining §2 wiring notes:

- **Power-gate** each ADM2587E's VCC with a discrete **P-FET high-side
  switch** — a **direct-GPIO-driven NTR4171P** (F51: source is 3V3, the
  same domain as the ESP pin — no level shifter; **F61 iter-40:
  NTR4171P (onsemi) RDS(on) guaranteed 150 mΩ max @ VGS=−2.5 V**, Vgs
  ±12 V ≫ the 3.3 V drive, so the drive is a qualified operating point;
  it replaced DMG3415U, which was NRND at the manufacturer despite
  distributor stock; 100 kΩ gate pull-up to 3V3 gives default-OFF while
  the pin is high-Z), enabled by **active-LOW** `CH_x_PWR`. isoPower
  settles in ≈ 1 ms; firmware waits before the first byte.

---

## 3. Per-channel BOM (×2 identical channels)

Every SKU/stock figure below was resolved against the parts API on
**2026-07-15**; `_verify_` where a value/variant still needs pinning.

| Ref (per ch.) | Part | Why | Sourcing (2026-07-15) |
|---------------|------|-----|-----------------------|
| U_iso1 / U_iso2 | **ADM2587E BRWZ** — isolated RS-485 w/ **integrated isolated DC-DC** (isoPower), 3.3 V, slew-limited **500 kbps**, ±15 kV ESD on bus pins, open/short fail-safe RX | One chip = isolation + transceiver + isolated supply → fewest solder joints for a qty-1 hand build. 500 kbps ≫ our 9600 baud, and slew-limiting *lowers* EMI. | Mouser **584-ADM2587EBRWZ**, 3,848 stock, $22.90. (ADM2582E is 16 Mbps overkill and DK-OOS.) **Datasheet on file** (Rev H, sha 77a52a9e6036): 2500 Vrms iso, CMTI >25 kV/µs, **ICC 90 mA @ 3.3 V/100 Ω** (Table 1; corrected iter-30 F28 — was mis-cited 72 mA, which is the 5 V row) — see §6. |
| Q_ls (×1 per ch.) | **Direct-GPIO-driven NTR4171P** P-FET high-side switch + 100 kΩ gate pull-up to 3V3 (**F51: no 2N7002** — source = 3V3 = the GPIO domain; **F61: RDS(on) guaranteed 150 mΩ max @ −2.5 V**, onsemi NTR4171P/D — replaced DMG3415U, NRND at the manufacturer; `CHx_PWR` **active-LOW**: high-Z/high = OFF, low = ON) | Power-gate VCC so isoPower runs only during a poll (see §5). Default-OFF at reset. ~90 mA channel load → ≤14 mV drop. Off-leakage = IDSS ≤ 1 µA @25 °C / ≤5 µA @85 °C (−24 V test point — pessimistic at −3.3 V); bring-up acceptance enforces the real bound. | DK **NTR4171PT1GOSCT-ND** (11k, Active) / Mouser 863-NTR4171PT1G, $1.13 (API 2026-07-17) |
| J_bat1 / J_bat2 | **Amphenol RJHSE-5380** RJ45 jack, shielded, magnetics-free | Mates the owner's purchased vendor cable **directly — its client end is an RJ45 *male* plug** (photo on file: `docs/vendor/images/volthium-cable-m12-to-rj45male-full.jpg`), no patch cable (the email's "RJ45-female + patch" chain described the $10 variant, not the cable in hand). RS-485 A/B on RJ45 **pins 7/8** — verified in the committed transcript (2024-01-15), the on-file adapter-label photo, *and* the owner's **2026-07-17 continuity beep-out of the in-service cable**. **Full measured map (rung-1):** battery 1→RJ45 4, 2→6, 3→7, 4→8 ⇒ battery **1 = CAN-H (RJ45 4), 2 = CAN-L (RJ45 6), 3 = A (RJ45 7), 4 = B (RJ45 8)**. Note CAN-L lands on RJ45 **6** in this cable — the Pro-Series label's 4/5 describes a different product (the F45 caution validated). CAN unused in D36; any future pad routing follows the measured map of the cable in service. **Identical/interchangeable — either pack on either jack.** | Mouser **523-RJHSE-5380**, 8,697 stock, $2.30; datasheet on file (RJHSE-5380.pdf) |
| TVS_bus + R_ser (**DNP footprints**) | **Semtech SM712** asymmetric RS-485 TVS (VRWM 12/7 V) + per-line series R footprints between the TVS node and the ADM2587E A/B | **F36/F44 — no coordinated protection exists in this design; the port is unprotected.** SM712 clamps **VC = 20 V @ 5 A** positive (Semtech Rev 6.0 p.2), above the ADM2587E bus abs-max of **−9/+14 V** (Rev H p.7), and a series R **does not fix that by itself**: the A/B pins are high-impedance, draw no defined current below their (unpublished) internal clamp, and so see the TVS-node voltage — with no published ADM2587E injection/clamp-current rating there is nothing to size the R against (F44 accepted; the iter-32 "populate as a coordinated pair, residual <14 V" claim is **withdrawn**). The ADM2587E's ±15 kV is **HBM (handling)**, *not* IEC 61000-4-2. **Status: DNP, intentionally unprotected** — accepted risk for a short (~1 m) inside-enclosure link that never leaves the battery box. If field-cable surge/ESD ever becomes a requirement, the fix is a **properly coordinated network chosen then** — a lower-clamp TVS/steering-diode stage whose *documented* residual < 14 V, or a two-stage clamp with the series element sized from a *published* downstream clamp-current rating — not the current footprints. | DK **SM712CT-ND** / Mouser **947-SM712.TCT** (Semtech), 99k+ stock. **Datasheet on file** (Semtech Final Rev 6.0, sha 6deb75310ebe): VRWM 12/7 V, VBR 13.3/7.5 V, VC 20/10 V @ 5 A, SOT-23. |
| R_bias | fail-safe bias A/B → local iso-rails (**idle-noise margin only** — F52/F58: *not* a common-mode fix; the old "~1 MΩ iso-GND↔bus bleed" is retired) | Defines the idle differential locally. DNP by default (ADM2587E has internal fail-safe, p.15); populate only if the §7 bench shows idle chatter | high-value; per §7 |
| REF_pad (×1 per ch.) | **Fallback reference pad**: ISO_BUS_GND → that pack's **B− terminal** by a dedicated conductor (direct link; a series-R footprint is provided but the default is a 0 Ω jumper) | **F52/F58 fallback if the §7 matrix fails** — a real reference that pins both receiver domains (offset ≈ 0 by construction); each channel refs its *own* pack, preserving symmetry. Unwired unless needed | pad + wire only; placed at CP2 |
| R_di1, R_di2 | 1 kΩ series on each DIx | power-up-settle guard (§2a) | 0402/0603 ×2 |
| R_bus term | 120 Ω across A/B — **DNP** | at 9600 baud over a ~1–2 m point-to-point run, reflections settle ≪ 1 bit; termination just loads the driver. Footprint present, unstuffed; populate only if a bench capture shows ringing. | DNP |

**ADM2587E isoPower support network per channel (F32 — required, from Rev H
pp.8/17, not optional decoupling):**

Pinout (Rev H p.8): pin 1/3/9/10 = GND1, 2/8 = VCC, 4 = RxD, 5 = /RE,
6 = DE, 7 = TxD; 11/14/16/20 = GND2, 12 = **VISOOUT**, 13 = Y, 15 = Z,
17 = B, 18 = A, 19 = **VISOIN**. (**F35:** the first draft wrongly called pin 11 VISOIN was **corrected** —
pin 11 is GND2; VISOIN is pin 19.)

**Two distinct isolated-side ground nets (F43 — binding for CP2
capture).** The four "GND2" pins are **not one net**: Rev H Table 10
(p.8) says pins 11/14 are the *isolated DC-DC converter* ground and
that bus-side **pin 16 "must not be connected directly to Pin 14 and
Pin 11"**; p.17 places L2 between the two regions, with pin 16 tied to
the pin-11 region **"on the outside (bus side) of the L2 ferrite"**.
One shared `GND2` label would short across L2 and defeat the filter.
Schematic nets:

- **`GND2_DCDC`** = pins **11 + 14** (converter ground, device side of L2)
- **`ISO_BUS_GND`** = pins **16 + 20** + the isolated bus copper/plane
  (bus side of L2); A/B network returns (TVS, bias, termination) land here
- **L2 is the only connection** between the two nets

| Ref (per ch.) | Value | Connection (Rev H pp.8/17) | Net side |
|---------------|-------|------------------------|------|
| C_vcc1a / C_vcc1b | 0.1 µF + 0.01 µF | VCC pin 2 ↔ GND1 pin 1 | GND1 (logic bypass) |
| C_vcc2a / C_vcc2b | 0.1 µF + 10 µF | VCC pin 8 ↔ GND1 pin 9 | GND1 (logic bulk + bypass) |
| C_vout_a / C_vout_b | 10 µF + 0.1 µF | **VISOOUT pin 12 ↔ pin 11**, device side of L1/L2 (p.17: "C1 … on the device side of the L1 and L2 ferrites") | **`GND2_DCDC`** |
| C_vin_a / C_vin_b | 0.1 µF + 0.01 µF | **VISOIN pin 19 ↔ pin 20** | **`ISO_BUS_GND`** |
| **L1** | ferrite bead | **VISOOUT pin 12 → VISOIN pin 19** | the VISOOUT↔VISOIN connection *is through this ferrite* (Fig 35) |
| **L2** | ferrite bead | **`GND2_DCDC` (pins 11+14) → `ISO_BUS_GND` (pins 16+20 + plane)** | the *only* GND2_DCDC↔ISO_BUS_GND tie (Fig 35) |
| C_stitch | HV-rated Y-cap (~1 nF) rated to the **safety/working** requirement (VIORM = **524 V peak / 396 V rms** continuous per IEC 60747-17 — *not* the 2500 V rms 1-min proof voltage) | GND1 pin 10 ↔ **pin 11 (`GND2_DCDC`)** — the 2-layer discrete-cap placement per Rev H p.17 | GND1 ↔ `GND2_DCDC`; on 4-layer use an embedded GND1↔GND2 plane capacitor instead |

**CP2/CP3 layout contract (binding):** isolation keep-out under the
barrier (no copper/planes bridging GND1↔GND2 except C_stitch);
**two** ferrites (L1 on VISO, L2 between `GND2_DCDC` and
`ISO_BUS_GND`) per Fig 35, with the p.17 keep-out (no GND2 fill on any
layer under L1/L2); split GND1 / `ISO_BUS_GND` planes with
`GND2_DCDC` as a local island at the chip; C_stitch (or embedded
stitching) rated to the ≥524 Vpeak working requirement. The ADM2587E is a **20-lead wide-body *leaded* SOIC** — so
it is *not* a hand-solder concern like the leadless U6, but it **is
creepage-critical** (flag for CP3 barrier keep-out).

Rough added cost: ~2 × ($22.90 + $2.30 RJ45 + ~$1.5 support passives) ≈
**~$54** for the pair (SM712 DNP; +~$0.30/ch Semtech if populated).
Cheaper discrete alternative in §8.

---

## 4. Control / GPIO map (all on currently-free battery-side GPIOs)

| Net | Dir | Purpose |
|-----|-----|---------|
| `RS485B_DI1` / `RS485B_DI2` | ESP→ | UART2 TXD matrix-routed to the *active* channel's DI (1 kΩ series each); inactive = high-Z input |
| `RS485B_RO1` / `RS485B_RO2` | →ESP | *dedicated* RX pin per channel; UART2 RXD matrix-routed to the active one; **not** wire-OR'd (that fan-out was retired, F30) |
| `RS485B_DE1` / `RS485B_DE2` | ESP→ | per-channel half-duplex driver-enable; inactive = high-Z input |
| `CH1_PWR` / `CH2_PWR` | ESP→ | load-switch enable per channel (power = select). **Active-LOW** (F51 direct-drive P-FET: low = ON; high-Z/high = OFF — safe default at reset) |

**8 GPIOs.** Free RTC/generic pins exist (§2a); exact numbers assigned at
CP2 with no clash vs the display UART1, I2C0, or the D37 header.

---

## 5. Firmware polling sequence (per pack, sequential)

```
for ch in (1, 2):                       # channels are pack-agnostic
    matrix-route UART2 TX→DIx, RX←ROx   # active channel only
    set the OTHER channel's DI/DE/RO ESP pins = INPUT (high-Z)
    assert CHx_PWR                      # power that isolated front-end
    wait ~2 ms                          # isoPower + transceiver settle (~1 ms)
    DEx = 1; send :xx02...~ (real-time query, 9600 8N1); DEx = 0
    read response; reply's Addr field says which pack is on this jack
    deassert CHx_PWR                    # power down
    set DIx/DEx/ROx = INPUT (high-Z)    # off channel fully de-driven (§2a)
```
(9600 8N1; addresses `0x01`/`0x02`. Because either pack may be on either
jack, firmware maps address→pack from the reply, not from the channel.
The high-Z steps are the §2a off-state contract — not optional.)

Poll cadence: **run in parallel with BLE**, every ~30 s per pack (window
≈ 50–100 ms/pack → **duty ≈ 0.5 %**). The two transports are peers — the
firmware can cross-check them, prefer whichever is answering, or make the
wired path primary; that policy is a field/bench call (D36), not hard-
coded, so nothing here presumes BLE is "the" primary.

The decoded frame is the **same E&J `:AddrCmd…CRC~` format** the BLE path
already tunnels, so `volthium/pack.py` / `ej_bms` decoding is reused
byte-for-byte — **both transports share the parser; only the transport
differs.**

---

## 6. Power analysis (power-first, D5 preserved)

**The datasheet number is bigger than a first guess, which makes the
gating essential (not optional).** ADM2587E **ICC = 90 mA @ 3.3 V, 100 Ω
load** (Rev H Table 1; **corrected iter-30 F28** — the first draft cited
72 mA, which is the 5 V row. **F42:** 90 mA/100 Ω is the *conservative
documented bound* — the datasheet has no unloaded-ICC row, and our
default bus is **unterminated (high-Z)**, not ~100 Ω, so actual draw is
lower; bench-measure the real number). Because the isoPower DC-DC runs
whenever
VCC is applied, the draw is ~this whether transmitting or listening. Left
**continuously on**, one channel ≈ **297 mW**; two ≈ **594 mW** — that
would roughly *halve* the battery-side runtime. Hence the load-switch-
per-channel and one-channel-at-a-time select.

**Gated**, each poll powers one channel for ~50–100 ms; both packs every
30 s → ~150 ms/30 s ≈ **0.5 % duty**. Average added draw ≈ 90 mA × 0.5 %
≈ **0.45 mA @ 3.3 V ≈ 1.49 mW** in the polling states (1/2) — call it
**~1.5 mW average**, ~0.17 % of the ~0.9 W State-1 budget. Negligible,
but *not* "below the µW floor" — that claim is **corrected** here (it was
a first-draft error). In States 3–4
(deep-sleep / hard-cut) both channels are **unpowered** → **hard-cut
~1.08 mW unchanged** — *contingent on the enforceable off-state
contract in §2a (F30) and no leakage path; the load switch defaults off
at reset.* (Even as *primary*, State-3 reads are ~1/10 min → far lower
duty; State-4 does no reads.)

---

## 7. Interface premise — redacted transcript on file; on-site test still GATES the topology (F37/F45/F47/F52)

**Evidence label (F55-corrected):** the committed artifact is an
**owner-supplied redacted transcript** decoded from an off-file original
`.eml` ([`../../docs/vendor/Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`](../../docs/vendor/Voltage_monitoring_thread_2023-2024_redacted_transcript.txt);
the original's SHA-256 `37df1ab1…` is recorded but reproducible only
from the owner's copy). Within that scope, the load-bearing quote is
transcript-verified, dated **2024-03-28**: *"Use a Standard RS485
adapter with A & B. No ground need. Don't use a TTL 3.3V adapter
directly."* Dated fact table: [`../../docs/vendor/volthium-rs485-correspondence-2024.md`](../../docs/vendor/volthium-rs485-correspondence-2024.md).

- **It is RS-485, not TTL** (transcript-verified, 2024-03-28 — the
  owner asked the TTL-vs-RS-485 question explicitly and this was the
  answer). The protocol doc's "TTL 3.3 V" is the BMS's *internal*
  signaling; you read it **through an RS-485 adapter** (A/B). The
  ADM2587E RS-485 front-end is the correct circuit class. RS-485 A/B on
  RJ45 **7/8** is double-sourced (thread 2024-01-15 + photographed
  label).
- **No ground wire needed** (transcript-verified) — 2-wire A/B
  differential. Consistent with the **isolated 2-wire** approach: each
  isolated channel floats to its pack's reference across the barrier
  like a standalone adapter would.
- **Connector — IDENTIFIED at family level (measured + photographed
  2026-07-17; cable photos ON FILE):** the purchased cable's battery end
  is a **4-position M12-pattern screw-coupling female cordset** —
  coupling-thread ID ≈ 12.3 mm (M12×1 nut; owner caliper), molded body,
  knurled metal ring, insert **numbered 1→4 counter-clockwise, keying
  notch between 1 and 4** (`../../docs/vendor/images/volthium-cable-m12-face-numbered.jpg`);
  client end = **RJ45 male** (`volthium-cable-m12-to-rj45male-full.jpg`).
  The pack side carries the male pins (owner-reported pack photos, still
  uncommitted). The vendor's "XLR" was colloquial — the repo's original
  "4-socket M12" reading was closest all along. **Vendor PN still never
  supplied** (asked 2023-12-27, unanswered) — curiosity only; nothing in
  D36 depends on it (we mate at the RJ45 end). Use the socket **closest
  to the negative terminal** (thread, 2024-01-15).

**Corrected over-claim (reviewer F37).** My earlier "both transceivers
see ≈ 0 V CM by construction" over-stated it — isolation *permits* a
ground offset but does not *force* the floating GND2 to track the pack;
and my settling math was wrong (**1 MΩ × 75 pF = 75 µs**, comparable to a
104 µs bit, not ≪ it, and 75 pF was the DNP-TVS Cj, not a measured bus
C). The vendor's real-world "standard RS-485 adapter works, no ground"
is strong evidence a floating isolated channel settles fine (standard
adapters share the −7/+12 constraint and work), but the *series-stack top
pack* at +12 V through one shared reader is the one case the vendor's
single-battery guidance doesn't directly cover.

**On-site test (owner at the batteries in ~2 weeks) — TOPOLOGY-GATING
(F47; matrix made two-domain per F52 — the earlier single-reference
criterion and the 1 MΩ-to-B "fallback" are withdrawn as insufficient).**
The test decides exactly the open electrical question: whether the
floating two-wire island keeps **both** receivers inside their
common-mode windows. Vendor guidance covers a *standard single-pack
adapter*; it does not document two independently isolated channels on a
series stack, and the top pack at +12 V is the uncovered case.

**Common-mode is defined at each receiver against ITS OWN local ground
(F52), so the matrix has two measurement domains:**

| # | Direction | Measure | Reference | Pass limit |
|---|-----------|---------|-----------|------------|
| 1 | Functional | ≥100 consecutive `:AddrCmd…CRC~` polls of the **+12 V top pack**, 9600 8N1 | — | **0 CRC failures** |
| 2a | **Reader TX** (pack's receiver active) | A and B | **the active pack's B− terminal** (top pack = the series midpoint) — isolated differential probe or battery-floated scope | within **−7…+12 V** at all times |
| 2b | **Pack TX** (reader's receiver active) | A and B | the adapter/channel's **isolated ground** (`ISO_BUS_GND` stand-in) | within **−7…+12 V** at all times |
| 3 | Both | \|A−B\| during driven bits | (differential) | ≥ **1.5 V** (5× the 200 mV threshold); clean edges at 9600 baud (settling ≤ ~10 % of the 104 µs bit after DE turn-around) |
| 4 | Idle | line state after DE release | each domain in turn | stable fail-safe idle within 1 bit; no RO chatter |
| 5 | Repeat | items 1–4 with the **packs swapped between channels** (either-pack-on-either-jack) | — | same limits |

If any row marginally fails or drifts, capture the waveforms — they size
the fallback.

**Fallback if the matrix fails (F52-revised iter-38 per F58 — a genuine
reference, not a bleed):** per-channel **REF pad/terminal** tying that
channel's `ISO_BUS_GND` **directly to that pack's B− terminal by a
dedicated conductor** (a series-R footprint exists on the pad but the
default is a 0 Ω link — F58: no resistance is claimed without a bounded
reference current) — a real reference that pins *both* domains together
(offset → ≈0 by construction), which the withdrawn signal-wire bleed
could not do (the reader itself drives B relative to `ISO_BUS_GND`, so
a bleed to B references nothing during reader TX).
Because each channel is isolated, referencing each island to **its own
pack's** B− preserves the symmetric/interchangeable-channel property
(the top-pack channel's "ground" is simply the series midpoint — its
barrier, rated 524 Vpk working, isolates it from board ground). Cost on
failure: **one extra wire per channel + a pad provided at CP2** — no
respin. The R_bias fail-safe footprints (§3) remain for **idle-noise
margin only**; they are *not* claimed as a common-mode fix.

**Status:** premise transcript-verified (F55 label: owner-supplied
redacted transcript; original off-file) + corroborated by the on-file
adapter-label photo; CMTI closed (>25 kV/µs). **D36/DR-26 and
the CP1 delta stay gated on the on-site pass** — CP2 capture may
proceed on the approved core, but the D36 nets are frozen only after
items 1–4 pass. D37 (expansion) is independent and CP2-ready
regardless. On-site also (non-gating): which socket carries RS-485 on
each pack. *(Retired from the on-site list — done on the bench
2026-07-17: connector family/dimensions measured (M12-pattern, ~12.3 mm
coupling-thread ID) and the cable-conductor map beeped out; and no patch
cable exists to check — the purchased vendor cable ends in an RJ45 male
plug and mates our jack directly.)*

---

## 8. Alternatives considered

- **Discrete isolation** (ISO7741 digital isolator + the already-
  qualified THVD1400 on the isolated side + a small isolated DC-DC): ~$6
  vs ~$23 per channel and TI datasheets are fetchable, but ~3× the part
  count per channel. Reasonable if we want lower cost/power or an on-file
  datasheet immediately; the integrated ADM2587E wins on hand-build
  simplicity, which is why it's the primary.
- **Asymmetric isolation** (isolate only the top pack; read the bottom
  pack with a plain transceiver off the system ground the board already
  has): saves one isolated part and shares the primary topology's
  2-wire property,
  but the two channels aren't interchangeable — the bottom-pack jack must
  get the bottom pack. **Rejected by user choice (2026-07-15) in favor of
  symmetric, swappable channels** ("either battery on either channel").
- **One shared multi-drop bus:** impossible for a series stack — the two
  packs' BMS transceivers are 12 V apart, so on a common pair each pack's
  own (fixed E&J) transceiver sees the other past its ±common-mode range,
  regardless of what the master does (see §1).

---

## 9. Impact & next step

This **extends the approved CP1 architecture** (new nets, 2 connectors,
2 isolated front-ends, 8 GPIOs, a firmware read path). It should get a
**CP1-delta engineering-review pass** (G1 isolation/coordination, G2
datasheets, G3 stock, G5 registry) **before CP2 schematic capture** folds
it in. **D32 closed:** ADM2587E + SM712 datasheets are now on file
(user-provided 2026-07-16), read and verified — see the manifest
"Proposed CP1-delta additions" section.
