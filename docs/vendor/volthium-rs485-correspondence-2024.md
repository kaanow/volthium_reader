# Volthium support correspondence — RS-485 / CAN battery interface (owner-supplied summary)

> **Provenance (F45, iter-34):** this file is an **owner-written summary** of
> an email thread — selected quotations and paraphrases, without message
> headers, dates-per-message, the owner's questions, or an immutable export.
> It is therefore **rung-2 evidence held at "owner-reported"**: strong enough
> to guide design direction, **not** strong enough to be independently
> re-verified or to silently overwrite other physical evidence (e.g. the
> photographed Pro-Series adapter label in [`README.md`](README.md)).
> **Requested from the owner:** a redacted `.eml` / PDF export / screenshots
> of the actual thread (with per-message metadata), committed alongside this
> file with its hash recorded. When that lands, this banner is replaced and
> the facts below graduate to verifiable vendor statements.

**Source:** email thread between Kaan Williams (owner) and Volthium Support
(Chloé Giroux, Yanni Samson), Nov 2023 – Mar 2024, as summarized by the
owner on 2026-07-16. Subject: how to read the actual Loon Lake packs
(**12 V 200 Ah, model ~12.8-200-G4DY-CH20**, built-in heater + Bluetooth, two
in series → 24 V).

## Reported facts (verbatim-as-recalled / paraphrased with attribution)

| Fact | Vendor statement (owner-reported) | Corroboration |
|------|------------------|---------------|
| **Interface is RS-485 (not TTL)** | *"Use a Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V adapter directly."* (Mar 2024). The datasheet's "Communication setting TTL, Voltage 3.3V" is the BMS's *internal* signaling; you access it **through an RS-485 adapter**, not by tapping raw TTL. | **Corroborated** by the independent photographed adapter label (RS-485-A/B present on the RJ45) |
| **No ground wire needed** | *"No ground need."* — 2-wire A/B differential; a standard RS-485 adapter works. | Consistent with an isolated 2-wire front-end; **final proof = on-site test** (design §7 pass limits) |
| **Battery connector** | Vendor sells **"XLR to RJ45 female"** cables (*"$10/Ea"*). The email calls the port **XLR**. | **In tension** with the photographed Pro-Series cable (4-socket M12-style plug). Exact family = **on-site identification**; not load-bearing (we mate at the RJ45 end) |
| **RS-485 pinout on the RJ45 end** | *"Pin 7 RS485 A · Pin 8 RS485 B"* (Jan 2024). | **Corroborated** — the photographed label also shows 7/8. The one mapping with two independent sources |
| **Which socket** | *"use the one closest to the negative terminal."* (Two comms sockets per pack.) | On-site check |
| **Example working adapter** | Vendor-endorsed: a generic USB-RS485 converter (Amazon B081MB6PN2) — i.e. any standard RS-485 transceiver, no special hardware. | — |
| **CAN pinout (future, not our path)** | *"our CAN uses pin 1 and 2 … first pin is CAN High and the 2nd is CAN Low."* (Nov 2023). **The quotation does not name the connector** — pins 1/2 could be the pack connector or the RJ45. CAN requires the Volthium **Communication Hub ($105)** + a Victron Cerbo-S GX. | **Conflicts** with the photographed adapter label (CAN-H/L on RJ45 **4/5**) if read as RJ45 pins. **CAN RJ45 mapping = UNRESOLVED** pending the original thread and/or on-site pin-out; CAN is unused by the current design |
| **12 V packs ≠ Insight Home / Xanbus** | *"With the 12V 200Ah batteries, it is not possible to make it communicate with the Insight Home."* So the display/monitor must be our own reader (BLE or RS-485), not a Schneider/Victron ecosystem device. | — |

## Implications for the design

- **F37 (interface premise):** the RS-485-vs-TTL question is answered
  RS-485 A/B, 2-wire, no ground — at owner-reported strength, corroborated
  on the RS-485/7-8 point by the photographed label. The isolated-per-channel
  ADM2587E front-end is the correct topology class under this premise.
  **The series-stack top-pack case is not covered by any source and remains
  gated on the on-site test** (design §7 pass limits — F47).
- Connector chain: **pack socket → Volthium pack-connector→RJ45-female cable →
  RJ45 patch → our board RJ45 jack (RJHSE-5380)**, RS-485 A/B on pins 7/8.
- On-site items (~2-week visit): the §7 gating measurements (top-pack read,
  common-mode window, differential margin, idle behavior, both orientations),
  plus connector-family identification and the CAN pin-domain question.
