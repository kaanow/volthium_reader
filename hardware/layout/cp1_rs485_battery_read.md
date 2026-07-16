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
isolated supply is the ground, fail-safe bias resistors tie A/B to the
local rails, and an optional ~1 MΩ bleed to a bus line keeps the island
from charging up on barrier leakage. **Nothing lands on a battery
negative terminal** — the only per-pack connection is the 2-wire A/B pair
through the vendor M12→RJ45 adapter (Ethernet gets away with no ground
the same way: it's isolated). BLE is RF-isolated for the same reason —
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
each channel's **logic pins go to *dedicated* ESP GPIOs** (no wire-OR, no
shared DI), so the interface never depends on the ADM2587E's
*unspecified* powered-off pin behavior. The ESP is the bus master and
polls **sequentially by protocol address** (`:01…~` then `:02…~`);
firmware learns which pack is on which jack from the address in the reply.

```
                         ┌─────────── ISOLATION BARRIER ──────────┐
                         │                                        │
  ESP32-S3   DI1,DE1 ────┼──► ADM2587E ch1 ─A/B─► RJ45_1 ─patch─► M12 adapter ► (either pack)
             RO1     ◄───┼──  (iso xcvr + iso DC-DC)
                         │        VCC ◄─[P-FET load switch 1]◄─ CH1_PWR
             DI2,DE2 ────┼──► ADM2587E ch2 ─A/B─► RJ45_2 ─patch─► M12 adapter ► (either pack)
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
apply only over 3.0–5.5 V), so a wire-OR'd RO or a driven DI could clamp
or back-power the "off" channel. Fixed by making the off-state
**enforced by the ESP, not assumed of the transceiver**:

- **Dedicated pins, no wire-OR.** Each channel's `DI`, `DE`, `RO` land on
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
  switch** (ZXMP6A13F P-FET + 2N7002 gate pull — both already qualified
  on this board, no new part class), enabled by `CH_x_PWR`. isoPower
  settles in ≈ 1 ms; firmware waits before the first byte.

---

## 3. Per-channel BOM (×2 identical channels)

Every SKU/stock figure below was resolved against the parts API on
**2026-07-15**; `_verify_` where a value/variant still needs pinning.

| Ref (per ch.) | Part | Why | Sourcing (2026-07-15) |
|---------------|------|-----|-----------------------|
| U_iso1 / U_iso2 | **ADM2587E BRWZ** — isolated RS-485 w/ **integrated isolated DC-DC** (isoPower), 3.3 V, slew-limited **500 kbps**, ±15 kV ESD on bus pins, open/short fail-safe RX | One chip = isolation + transceiver + isolated supply → fewest solder joints for a qty-1 hand build. 500 kbps ≫ our 9600 baud, and slew-limiting *lowers* EMI. | Mouser **584-ADM2587EBRWZ**, 3,848 stock, $22.90. (ADM2582E is 16 Mbps overkill and DK-OOS.) **Datasheet on file** (Rev H, sha 77a52a9e6036): 2500 Vrms iso, CMTI >25 kV/µs, **ICC 90 mA @ 3.3 V/100 Ω** (Table 1; corrected iter-30 F28 — was mis-cited 72 mA, which is the 5 V row) — see §6. |
| Q_ls_p, Q_ls_n | ZXMP6A13F P-FET + 2N7002 (high-side load switch + gate pull) | Power-gate VCC so isoPower runs only during a poll (see §5). Parts already on the board. | (already in cp1_bom.md) |
| J_bat1 / J_bat2 | **Amphenol RJHSE-5380** RJ45 jack, shielded, magnetics-free | Mates the vendor **M12→RJ45** adapter via a straight patch cable; same jack as the display link (commonality, on file). RS-485 A/B on RJ45 **pins 7/8** per the vendor pinout; CAN-H/L (4/5) to unpopulated pads for a future bridge. **Identical/interchangeable — either pack on either jack.** | Mouser **523-RJHSE-5380**, 8,697 stock, $2.30; datasheet on file (RJHSE-5380.pdf) |
| TVS_bus (**optional / DNP**) | **Semtech SM712** asymmetric RS-485 TVS (VRWM 12 V/7 V — matches −7/+12), on A/B↔iso-GND | Surge clamp on the cable pair. **The ADM2587E already has ±15 kV ESD on the bus pins**, so for this short internal run to a pack ~1 m away the SM712 is *surge* insurance (8/20 µs), not ESD — **DNP by default**, populate if the cable proves long/exposed. | DK **SM712CT-ND** / Mouser **947-SM712.TCT** (Semtech), 99k+ stock. **D32 OPEN (F29):** ordered part is **Semtech**; the on-file PDF is SMC's (electrically representative but wrong-manufacturer). Semtech datasheet is Salesforce-hosted (blocks the proxy) → **user-provide before populating**. Values below are from the SMC sheet as a placeholder: VBR 13.3/7.5 V, VC 20/12 V @ 5 A, Cj 75 pF, SOT-23. |
| R_bias | fail-safe bias A/B → local iso-rails, + optional ~1 MΩ iso-GND↔bus bleed | References the floating island **locally** (defines idle; bleeds barrier leakage) — no battery-negative wire | high-value; per §7 |
| R_di1, R_di2 | 1 kΩ series on each DIx | power-up-settle guard (§2a) | 0402/0603 ×2 |
| R_bus term | 120 Ω across A/B — **DNP** | at 9600 baud over a ~1–2 m point-to-point run, reflections settle ≪ 1 bit; termination just loads the driver. Footprint present, unstuffed; populate only if a bench capture shows ringing. | DNP |

**ADM2587E isoPower support network per channel (F32 — required, from Rev H
pp.8/17, not optional decoupling):**

| Ref (per ch.) | Value | Connection | Note |
|---------------|-------|------------|------|
| C_vcc1a / C_vcc1b | 0.1 µF + 0.01 µF | VCC pin 2 ↔ GND1 pin 1 | logic-side bypass |
| C_vcc2a / C_vcc2b | 0.1 µF + 10 µF | VCC pin 8 ↔ GND1 pin 9 | logic-side bulk + bypass |
| C_viso_a / C_viso_b | 10 µF + 0.1 µF | VISOOUT pin 12 ↔ VISOIN pin 11 | isolated-supply reservoir + decoupling; **VISOOUT must tie to VISOIN** |
| FB_gnd2 | ferrite bead | GND2 (pins 11+14) → PCB isolated ground | isoPower return, EMI (Rev H Fig 35) |
| C_stitch | HV-rated Y-cap (~1 nF, ≥ the 2500 V barrier working V) | GND1 ↔ GND2 | emissions-control return on **2-layer**; on 4-layer use an embedded GND1/GND2 stitching capacitor instead |

**CP2/CP3 layout contract (binding):** isolation keep-out clearance under
the barrier (no copper/planes bridging GND1↔GND2 except C_stitch);
GND2/ferrite topology per Fig 35; split GND1/GND2 planes; C_stitch (or
embedded stitching) sized to the working-voltage. Flag both ADM2587E as
the leadless/creepage-critical parts at CP1 (like U6) so CP3 gets the
keep-out right.

Rough added cost: ~2 × ($22.90 + $2.30 + ~$1 support passives) ≈ **~$52**
for the pair (SM712 DNP; +~$0.30/ch Semtech if populated). Cheaper
discrete alternative in §8.

---

## 4. Control / GPIO map (all on currently-free battery-side GPIOs)

| Net | Dir | Purpose |
|-----|-----|---------|
| `RS485B_DI1` / `RS485B_DI2` | ESP→ | UART2 TXD matrix-routed to the *active* channel's DI (1 kΩ series each); inactive = high-Z input |
| `RS485B_RO1` / `RS485B_RO2` | →ESP | *dedicated* RX pin per channel; UART2 RXD matrix-routed to the active one; **not** wire-OR'd |
| `RS485B_DE1` / `RS485B_DE2` | ESP→ | per-channel half-duplex driver-enable; inactive = high-Z input |
| `CH1_PWR` / `CH2_PWR` | ESP→ | load-switch enable per channel (power = select) |

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
72 mA, which is the 5 V row. 125 mA @ 54 Ω if terminated; our bus is
unterminated → ~100 Ω regime). Because the isoPower DC-DC runs whenever
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

## 7. Interface-reality open items (confirm before BOM-lock)

Per the COTS interface-reality discipline — these depend on undocumented
vendor hardware and must be checked on the bench / with Volthium, not
assumed:

**No battery-negative reference is required.** The 4-pin M12 breaks out
A/B **and** CAN-H/L on the RJ45 (7/8 + 4/5) — 4 signals on 4 pins, no
dedicated comms-ground pin — and that's fine: each isolated front-end
references **locally** (its own iso-supply ground + fail-safe bias to the
local rails, like Ethernet), connecting to the pack only through the
2-wire A/B pair. We do **not** tie iso-GND to any pack terminal and do
**not** run a series-midpoint sense lead. An optional ~1 MΩ bleed from
iso-GND to one bus line is belt-and-suspenders for barrier-leakage
charge-up and common-mode-transient settling — still entirely local.

**Worst-case DC common-mode (F31 — both transceivers must stay in range).**
Both the pack's BMS transceiver *and* our ADM2587E must sit within
−7 V…+12 V of their *own* grounds (Rev H Table 1). Because each end is
DC-referenced to its own ground and the link is 2-wire differential with
the master end **isolated**, the master's iso-island floats to the pack's
common-mode → *our* transceiver sees ≈ 0 V CM by construction (that's the
point of isolation). The pack's transceiver sees only its own drive/our
drive at *its* ground → also ≈ 0 V CM. **The series-stack +12 V offset is
absorbed entirely across the isolation barrier** (2500 V rms rating ≫
12 V), not across either transceiver's inputs. The bias/bleed only has to
define the *idle* differential and bleed barrier leakage — it does **not**
carry the +12 V. Concrete values: fail-safe bias is **internal** to the
ADM2587E (Rev H p.15 explicitly: external bias unnecessary); the local
bleed = **1 MΩ** iso-GND→A (sets a µA-scale DC operating point; the
75 pF-class bus capacitance and 1 MΩ give a ~µs settling floor, ≪ a
9600-baud bit). No resistor carries steady current in idle.

**Hard pre-freeze gate (must clear before CP2 commits this topology).**
The vendor serial doc says the M12 pins are **"3.3 V TTL, external MAX485
needed for RS-485"**, while the *adapter* label maps **RS-485 A/B to RJ45
7/8**. These can't both describe the same node, so **whether the adapter
presents true differential A/B or raw TTL is load-bearing** — a TTL M12
would invalidate the RS-485 front-end entirely (TTL referenced to the
pack's +12 V is single-ended and unreadable without a per-pack level
shift). **Bench-confirm on the real pack + adapter before freezing:**

1. **Scope RJ45 7/8** during a poll: differential RS-485 swing (A/B
   complementary around a mid-rail) vs. single-ended TTL. **This gates
   the whole topology.**
2. **Second M12 socket** function; which socket carries RS-485 (vendor:
   "closer to the negative post") on each physical pack.
3. **Patch cable straight-through** (pins 7/8 → 7/8; standard patch is,
   but verify the adapter isn't crossed).
4. **CMTI headroom** — confirmed on file: ADM2587E **>25 kV/µs** ≫ any
   series-midpoint dV/dt under load; no concern.

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
  has): saves one isolated part and also needs no battery-negative wire,
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
