# Volthium support correspondence — RS-485 / CAN battery interface (authoritative)

**Source:** email thread between Kaan Williams (owner) and Volthium Support
(Chloé Giroux, Yanni Samson), Nov 2023 – Mar 2024. This is the **authoritative
vendor statement** on how to read the actual Loon Lake packs
(**12 V 200 Ah, model ~12.8-200-G4DY-CH20**, built-in heater + Bluetooth, two
in series → 24 V). Where this disagrees with any prior repo note, **this
wins** (it corrected a wrong "M12 connector / CAN on 4-5" assumption — see
[`README.md`](README.md)).

## Load-bearing facts (verbatim / paraphrased with attribution)

| Fact | Vendor statement |
|------|------------------|
| **Interface is RS-485 (not TTL)** | *"Use a Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V adapter directly."* (Mar 2024). The datasheet's "Communication setting TTL, Voltage 3.3V" is the BMS's *internal* signaling; you access it **through an RS-485 adapter**, not by tapping raw TTL. |
| **No ground wire needed** | *"No ground need."* — 2-wire A/B differential; a standard RS-485 adapter works. Validates an **isolated 2-wire** front-end (Ethernet-style floating reference). |
| **Battery connector = XLR** | Vendor ships **"XLR to RJ45 female"** cables (*"$10/Ea"*, later "PACKAGE ADDITIONAL COMMUNICATION CABLE"). The battery port is an **XLR-style** connector — **NOT** the "4-socket M12" a prior repo note guessed. |
| **RS-485 pinout on the RJ45 end** | *"Pin 7 RS485 A · Pin 8 RS485 B"* (Jan 2024). Matches our board's RJ45 7/8 plan. |
| **Which socket** | *"use the one closest to the negative terminal."* (Two XLR sockets per pack.) |
| **Example working adapter** | Vendor-endorsed: a generic USB-RS485 converter (Amazon B081MB6PN2) — i.e. any standard RS-485 transceiver, no special hardware. |
| **CAN pinout (future, not our path)** | *"our CAN uses pin 1 and 2 … first pin is CAN High and the 2nd is CAN Low."* (Nov 2023) — **CAN-H = pin 1, CAN-L = pin 2**, NOT Victron 7/8 and NOT the "4/5" a prior repo note guessed. CAN requires the Volthium **Communication Hub ($105)** + a Victron Cerbo-S GX for a managed-battery bridge. |
| **12 V packs ≠ Insight Home / Xanbus** | *"With the 12V 200Ah batteries, it is not possible to make it communicate with the Insight Home."* So the display/monitor must be our own reader (BLE or RS-485), not a Schneider/Victron ecosystem device. |

## Implications for the design

- **F37 (interface premise) is resolved by the vendor for the RS-485-vs-TTL
  question: it is RS-485 A/B, 2-wire, no ground.** Our isolated-per-channel
  ADM2587E front-end is the correct topology; each isolated channel behaves
  like the vendor-endorsed standalone RS-485 adapter, floating to its pack's
  reference across the isolation barrier.
- Connector chain: **pack XLR → Volthium XLR-to-RJ45-female cable → RJ45 patch
  → our board RJ45 jack (RJHSE-5380)**, RS-485 A/B on pins 7/8.
- Residual bench items for the **~2-week on-site visit** (owner will be at the
  batteries): (a) functional confirmation that the *series-stack top pack*
  (comms referenced to +12 V) reads correctly through the isolated channel;
  (b) scope A/B swing + measure common-mode / bus capacitance to finalize
  whether any local reference/bleed is needed (vendor "no ground" + ADM2587E
  internal fail-safe suggest none).
