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
powered at a time; **power-gating is the channel-select** (an unpowered
ADM2587E's RO output is high-Z, so it drops off the shared RX line).
Because the ESP is the bus master and polls **sequentially by protocol
address** (`:01…~` then `:02…~`), the two channels never need to be live
at once, and firmware learns which pack is on which jack from the address
in the reply.

```
                         ┌─────────── ISOLATION BARRIER ──────────┐
                         │                                        │
  ESP32-S3        DI ────┼──► ADM2587E ch1 ─A/B─► RJ45_1 ─patch─► M12 adapter ► (either pack)
  (UART2)   TX ──┬──1kΩ──┤    (iso xcvr +         (RJHSE-5380)
                 │       │     iso DC-DC)   ▲
           RX ──◄┼───────┼──RO─┘  VCC◄─[P-FET load switch 1]◄─ CH1_PWR (GPIO)
                 │       │
                 └──1kΩ──┼──► ADM2587E ch2 ─A/B─► RJ45_2 ─patch─► M12 adapter ► (either pack)
           DE ───────────┤    VCC◄─[P-FET load switch 2]◄─ CH2_PWR (GPIO)
                         │                                        │
                         └────────────────────────────────────────┘
   Shared logic side (ESP 3V3, GND1)      │   Isolated side per channel —
                                          │   floats to whatever pack is
                                          │   plugged in; references locally
                                          │   (iso-supply GND + fail-safe bias)
```

Because both channels are isolated and self-referencing, the design is
**pack-agnostic**: swap the two cables and nothing changes but which
address answers on which jack. No jumper, no per-jack configuration.

- **DI (TX)** fanned to both ADM2587E, each through a **1 kΩ series R**
  so the unpowered channel's logic input can't leak from the ESP's
  idle-high TXD into its de-powered VCC.
- **RO (RX)** wire-OR'd back to ESP RXD with a **pull-up**; only the
  powered channel drives it, the other is high-Z.
- **DE** shared (half-duplex direction); `/RE` tied low per channel
  (receiver always on while that channel is powered).
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
| U_iso1 / U_iso2 | **ADM2587E BRWZ** — isolated RS-485 w/ **integrated isolated DC-DC** (isoPower), 3.3 V, slew-limited 250 kbps, ±15 kV ESD, full fail-safe RX | One chip = isolation + transceiver + isolated supply → fewest solder joints for a qty-1 hand build. 250 kbps ≫ our 9600 baud, and slew-limiting *lowers* EMI. | Mouser **584-ADM2587EBRWZ**, 3,848 stock, $22.90. (ADM2582E is 16 Mbps overkill and DK-OOS.) **D32 TODO: datasheet — ADI host WAF-blocks the proxy; pull manually.** |
| Q_ls_p, Q_ls_n | ZXMP6A13F P-FET + 2N7002 (high-side load switch + gate pull) | Power-gate VCC so isoPower runs only during a poll (see §5). Parts already on the board. | (already in cp1_bom.md) |
| J_bat1 / J_bat2 | **Amphenol RJHSE-5380** RJ45 jack, shielded, magnetics-free | Mates the vendor **M12→RJ45** adapter via a straight patch cable; same jack as the display link (commonality, on file). RS-485 A/B on RJ45 **pins 7/8** per the vendor pinout; CAN-H/L (4/5) to unpopulated pads for a future bridge. **Identical/interchangeable — either pack on either jack.** | Mouser **523-RJHSE-5380**, 8,697 stock, $2.30; datasheet on file (RJHSE-5380.pdf) |
| TVS_bus | **SM712.TCT** asymmetric RS-485 TVS (+7 V/−12 V), on A/B↔iso-GND | Surge/ESD clamp on the exposed cable pair, referenced to the **local isolated** ground. | Mouser **947-SM712.TCT**, 103,047 stock, $3.64. **D32 TODO: datasheet (proxy returned an error, pull manually).** |
| R_bias | fail-safe bias A/B → local iso-rails, + optional ~1 MΩ iso-GND↔bus bleed | References the floating island **locally** (defines idle; bleeds barrier leakage) — no battery-negative wire | high-value; per §7 |
| R_di | 1 kΩ series on DI | de-powered-input leakage guard | 0402/0603 |
| R_bus term | 120 Ω across A/B — **DNP** | at 9600 baud over a ~1–2 m point-to-point run, reflections settle ≪ 1 bit; termination just loads the driver. Footprint present, unstuffed; populate only if a bench capture shows ringing. | DNP |
| C_iso | ADM2587E bypass (VCC + isolated Viso per datasheet) | isoPower decoupling | per datasheet (pull) |

Rough added cost: ~2 × ($22.90 + $2.30 + $3.64 + passives) ≈ **~$60**
for the pair. (Cheaper discrete alternative in §8.)

---

## 4. Control / GPIO map (all on currently-free battery-side GPIOs)

| Net | Dir | Purpose |
|-----|-----|---------|
| `RS485B_TX` | ESP→ | UART2 TXD → both ADM2587E DI (via 1 kΩ each) |
| `RS485B_RX` | →ESP | UART2 RXD ← both ADM2587E RO (wire-OR + pull-up) |
| `RS485B_DE` | ESP→ | shared half-duplex driver-enable (both DE; only the powered channel acts) |
| `CH1_PWR` | ESP→ | load-switch enable for channel 1 (power = select) |
| `CH2_PWR` | ESP→ | load-switch enable for channel 2 |

5 GPIOs. The battery-side map notes "all other GPIOs unused; available
for expansion" — no contention with the approved pin assignments.

---

## 5. Firmware polling sequence (per pack, sequential)

```
for ch in (1, 2):                   # channels are pack-agnostic
    assert CHx_PWR                  # power that isolated front-end
    wait ~2 ms                      # isoPower + transceiver settle (~1 ms typ)
    DE = 1; send :0002...~ (0x00 broadcast, or :01/:02 real-time query); DE = 0
    read response; the reply's Addr field says which pack is on this jack
    deassert CHx_PWR                # power down → drops off shared RX
```
(9600 8N1; addresses `0x01`/`0x02`. Because either pack may be on either
jack, firmware maps address→pack from the reply, not from the channel.)

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

ADM2587E isoPower draws on the order of tens of mA **while enabled**
(exact figure = D32 datasheet pull). Left continuously on, 2 channels
would add ≈ 0.1–0.15 W to the ~0.9 W battery-side State-1 draw — a real
hit. **Gated at ~0.5 % duty it averages well under 1 mW**, i.e. below the
rounding floor of the existing budget. In States 3–4 (deep-sleep / hard-
cut) both channels are unpowered, so the ~1.08 mW hard-cut headline is
**unchanged**. This is the reason for the load-switch-per-channel rather
than a simpler always-on wiring.

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

Remaining items to confirm on the real hardware (COTS interface-reality):

1. **The pair is really a clean 2-wire A/B** on RJ45 7/8 (vs. TTL, which
   the vendor serial doc mentions "at the pins") — a 60-second scope/
   continuity check on the adapter output.
2. **Second M12 socket** — vendor doc flags its function as undocumented
   ("likely CAN or daisy-chain"). Confirm which socket carries RS-485
   ("closer to the negative post" per vendor) on each physical pack.
3. **Straight-through vs crossover** patch cable to preserve pins 7/8 →
   7/8 (standard patch is straight; verify the adapter isn't crossed).
4. **CMTI headroom.** The series midpoint can move relative to system
   ground under load transients; confirm the ADM2587E's rated CMTI
   covers it (it will — kV/µs class — but note it once the datasheet is
   on file).

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
2 isolated front-ends, 5 GPIOs, a firmware read path). It should get a
**CP1-delta engineering-review pass** (G1 isolation/coordination, G2
datasheets incl. the two D32 TODOs, G3 stock — done here, G5 registry)
**before CP2 schematic capture** folds it in. Two D32 datasheets
(ADM2587E, SM712) must be pulled manually and manifested first.
