# CP1 addendum — RS-485 battery-read backup (both packs)

**Status:** design proposed 2026-07-15 (user-directed). Extends the
approved CP1 architecture; **needs a CP1-delta review pass before CP2**.
**Driver:** BLE to the two BMS has been *worryingly flaky* in the field —
worse than the "benign, self-correcting" characterization in
[`../../docs/firmware/ble_flap_recovery.md`](../../docs/firmware/ble_flap_recovery.md).
This adds a **real, populated wired read path** as a BLE-independent
backup (and cross-check). Board space/volume is explicitly **not** a
constraint on the battery side.

---

## 1. The governing constraint — why this is not one shared bus

The two **SC12200G4DPH 12 V packs are wired in series** to make the 24 V
system (README + `volthium/pack.py`). Each pack's comms port is
TTL-referenced to **its own** B− terminal, not to system ground:

| Pack | Comms-ground potential vs system GND |
|------|--------------------------------------|
| **A** (bottom, id 0533) | ≈ 0 V |
| **B** (top, id 0667)    | ≈ **+12 V** (up to +13 V at a 26 V full charge) |

RS-485 receivers are only valid over a bounded common-mode range. The
THVD1400 datasheet (on file) specifies **−7 V ≤ V(A,B) ≤ +12 V**. Pack B
sits **at / just past the +12 V edge**, so a single non-isolated RS-485
bus referenced to system ground **cannot reliably read the top pack**.
(CAN is worse here — ISO 11898 common-mode is ≈ −2 V…+7 V — which is why
CAN is reserved for a future pack→inverter bridge, not for reading.)

**Therefore: two galvanically-isolated channels, one per pack, each
transceiver referenced to its own pack's ground.** This is the standard
topology for reading a series battery stack, and it is what makes BLE
(RF-isolated) the natural primary — the wired backup simply reproduces
that isolation with copper.

---

## 2. Topology

One shared ESP **UART2** (confirmed free: the ESP32-S3 has three UART
controllers per its datasheet — UART0 = console, UART1 = display RS-485,
**UART2 = this bus**), fanned to **two independent isolated RS-485
front-ends**. Only one channel is powered at a time; **power-gating is
the channel-select** (an unpowered ADM2587E's RO output is high-Z, so it
drops off the shared RX line). Because the ESP is the bus master and
polls the packs **sequentially** (`:01…~` then `:02…~`), the two channels
never need to be live simultaneously.

```
                         ┌─────────── ISOLATION BARRIER ──────────┐
                         │                                        │
  ESP32-S3        DI ────┼──► ADM2587E #A ──A/B──► RJ45_A ──patch──► M12 adapter ► Pack A (0533, GND≈0V)
  (UART2)   TX ──┬──1kΩ──┤    (iso xcvr +          (RJHSE-5380)
                 │       │     iso DC-DC)   ▲
           RX ──◄┼───────┼──RO─┘  VCC◄─[P-FET load switch A]◄─ CH_A_PWR (GPIO)
                 │       │
                 └──1kΩ──┼──► ADM2587E #B ──A/B──► RJ45_B ──patch──► M12 adapter ► Pack B (0667, GND≈+12V)
           DE ───────────┤    VCC◄─[P-FET load switch B]◄─ CH_B_PWR (GPIO)
                         │                                        │
                         └────────────────────────────────────────┘
   Shared logic side (ESP 3V3, GND1)      │      Isolated side per channel
                                          │      (each floats at its pack's B−)
```

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
| U_iso_A / U_iso_B | **ADM2587E BRWZ** — isolated RS-485 w/ **integrated isolated DC-DC** (isoPower), 3.3 V, slew-limited 250 kbps, ±15 kV ESD, full fail-safe RX | One chip = isolation + transceiver + isolated supply → fewest solder joints for a qty-1 hand build. 250 kbps ≫ our 9600 baud, and slew-limiting *lowers* EMI. | Mouser **584-ADM2587EBRWZ**, 3,848 stock, $22.90. (ADM2582E is 16 Mbps overkill and DK-OOS.) **D32 TODO: datasheet — ADI host WAF-blocks the proxy; pull manually.** |
| Q_ls_p, Q_ls_n | ZXMP6A13F P-FET + 2N7002 (high-side load switch + gate pull) | Power-gate VCC so isoPower runs only during a poll (see §5). Parts already on the board. | (already in cp1_bom.md) |
| J_bat_A / J_bat_B | **Amphenol RJHSE-5380** RJ45 jack, shielded, magnetics-free | Mates the vendor **M12→RJ45** adapter via a straight patch cable; same jack as the display link (commonality, on file). RS-485 A/B on RJ45 **pins 7/8** per the vendor pinout; CAN-H/L (4/5) to unpopulated pads for a future bridge. | Mouser **523-RJHSE-5380**, 8,697 stock, $2.30; datasheet on file (RJHSE-5380.pdf) |
| TVS_bus | **SM712.TCT** asymmetric RS-485 TVS (+7 V/−12 V, matches the −7/+12 range), on isolated A/B↔iso-GND | Surge/ESD clamp on the exposed cable pair, referenced to the isolated pack ground. | Mouser **947-SM712.TCT**, 103,047 stock, $3.64. **D32 TODO: datasheet (proxy returned an error, pull manually).** |
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
| `CH_A_PWR` | ESP→ | load-switch enable for channel A (power = select) |
| `CH_B_PWR` | ESP→ | load-switch enable for channel B |

5 GPIOs. The battery-side map notes "all other GPIOs unused; available
for expansion" — no contention with the approved pin assignments.

---

## 5. Firmware polling sequence (per pack, sequential)

```
for pack in (A @ addr 0x01, B @ addr 0x02):
    assert CH_x_PWR                 # power that isolated front-end
    wait ~2 ms                      # isoPower + transceiver settle (~1 ms typ)
    DE = 1; send :xx02...~ (0x02 real-time query, 9600 8N1); DE = 0
    read response frame (ej_bms decoder — identical byte format to BLE)
    deassert CH_x_PWR               # power down → drops off shared RX
```

Poll cadence: alongside BLE, every 30 s (or on-demand when BLE misses).
Window ≈ 50–100 ms/pack → **duty ≈ 0.5 %**.

The decoded frame is the **same E&J `:AddrCmd…CRC~` format** the BLE path
already tunnels, so `volthium/pack.py` / `ej_bms` decoding is reused
byte-for-byte — the backup shares the parser, only the transport differs.

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

1. **Comms ground.** The 4-pin M12 breaks out A/B **and** CAN-H/L on the
   RJ45 (pins 7/8 + 4/5) — that is **4 signals on 4 pins, leaving no
   dedicated comms-ground pin.** An isolated 2-wire RS-485 front-end
   still needs a DC reference on its isolated side. Plan: tie each
   channel's isolated GND to **that pack's B−** (pack A's B− = system
   GND; pack B's B− = the **series midpoint, +12 V** — which is *not*
   currently routed to the board and would need a sense lead), **or**
   establish the reference with a high-value bias network from iso-GND
   to the bus. **Confirm the real M12 pinout + whether the adapter
   carries comms GND before committing the reference scheme.**
2. **Series-midpoint reference for channel B** — see above; decide sense-
   lead vs bias-network at review.
3. **Second M12 socket** — vendor doc flags its function as undocumented
   ("likely CAN or daisy-chain"). Confirm which socket carries RS-485
   ("closer to the negative post" per vendor) on each physical pack.
4. **Straight-through vs crossover** patch cable to preserve pins 7/8 →
   7/8 (standard patch is straight; verify the adapter isn't crossed).

---

## 8. Alternatives considered

- **Discrete isolation** (ISO7741 digital isolator + the already-
  qualified THVD1400 on the isolated side + a small isolated DC-DC): ~$6
  vs ~$23 per channel and TI datasheets are fetchable, but ~3× the part
  count per channel. Reasonable if we want lower cost/power or an on-file
  datasheet immediately; the integrated ADM2587E wins on hand-build
  simplicity, which is why it's the primary.
- **Asymmetric isolation** (isolate only channel B at +12 V; read
  channel A with a plain transceiver at system GND): saves one isolated
  part but is non-uniform and less robust to wiring changes. Rejected
  given "space is no concern" + "want a *real* backup."
- **One shared multi-drop bus:** impossible for a series stack — no
  single ground reference lands within RS-485 common-mode of both packs
  (see §1).

---

## 9. Impact & next step

This **extends the approved CP1 architecture** (new nets, 2 connectors,
2 isolated front-ends, 5 GPIOs, a firmware read path). It should get a
**CP1-delta engineering-review pass** (G1 isolation/coordination, G2
datasheets incl. the two D32 TODOs, G3 stock — done here, G5 registry)
**before CP2 schematic capture** folds it in. Two D32 datasheets
(ADM2587E, SM712) must be pulled manually and manifested first.
