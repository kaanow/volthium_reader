# Volthium support correspondence — RS-485 / CAN battery interface (original thread on file)

> **Provenance (F45 — CLOSED 2026-07-16):** the original email thread is now
> committed as
> [`Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`](Voltage_monitoring_thread_2023-2024_redacted_transcript.txt)
> — a decoded transcript with headers and the complete message bodies in
> both directions. Redaction scheme (privacy for a public repo): personal
> names → [Owner]/[Support Agent], email addresses/phones/address →
> generic placeholders, tracking/CRM URLs → generic descriptions; message
> structure, dates, and all technical content unaltered. The owner
> retains the unredacted original `.eml`
> (SHA-256 `37df1ab1127bb20e36b715c02d0767a0eed23a6b57a7b34436ce39540863f573`);
> transcript SHA-256 `7c7ac607a628295e…`. Every quotation below can be
> checked against the transcript.

**Source:** email thread between the owner and Volthium Support (one
support agent throughout), **2023-11-12 → 2024-03-28**.
Packs: 2× 12 V 200 Ah (heater + Bluetooth; owner's initial email says
"12.8-200-G4DY-CH20 I think"; the pack serial label photographed reads
**V-BTH-0821-12V200Ah-0533**, app ID V-12V200AH-0533), in series → 24 V,
off-grid cabin.

## Verified facts (each dated; check against the transcript)

| Fact | Vendor statement (date) | Status |
|------|------------------|---------------|
| **Interface is RS-485 (not TTL)** | *"Use a Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V adapter directly."* (**2024-03-28**). The protocol doc's "TTL 3.3 V" is the BMS's internal signaling — the owner asked exactly this (2024-03-28 03:37) and this was the answer. | **VERIFIED** (transcript) — also corroborated by the photographed adapter label (RS-485 on the RJ45) |
| **RS-485 pinout on the RJ45 end** | *"Pin 7 RS485 A · Pin 8 RS485 B"* (**2024-01-15**) | **VERIFIED** — two independent sources (thread + photographed label) |
| **Which socket** | *"you'll need to use the one closest to the negative terminal"* (**2024-01-15**). The photographed pack face has **two** identical 4-pin sockets. | VERIFIED (transcript); which-is-which per pack = on-site |
| **CAN pinout — battery-side connector, NOT RJ45** | *"On our CAN, the first pine is CAN High and the 2nd is CAN Low"* (**2023-11-14**); *"our CAN uses pin 1 and 2"* (**2023-11-21**). **Domain resolved by the thread context:** the owner's question (2023-12-27) was explicitly about the **connector on the battery** — *"It is not the RJ45 I expected … it is not clear which pins are 1 and 2"*. So CAN-H/L = **pins 1/2 of the pack's 4-pin connector**. This does **not** conflict with the photographed Pro-Series adapter label putting CAN-H/L on **RJ45 4/5** — different connectors, one cable maps one to the other. | **RESOLVED** (was flagged ambiguous in review F45) |
| **Battery connector** | Vendor sells *"XLR to RJ45 female"* cables ($10/Ea, **2024-01-15**; "PACKAGE ADDITIONAL COMMUNICATION CABLE" $21.98, **2024-03-13**). Owner's photos (attached to the 2023-12-27 email; re-shared 2026-07-16): the pack carries **two 4-pin circular sockets with threaded collars** and the vendor cable's battery end is a **4-pin threaded aviation-style metal plug** — "XLR" is the vendor's colloquial name (true XLR latches; this threads). **Vendor never supplied the connector PN** (asked directly 2023-12-27, unanswered). Exact PN/family = on-site caliper/ID; not load-bearing (we mate at the RJ45 end). | **Photographic evidence**; PN open |
| **Example working adapter** | Generic USB-RS485 converter, Amazon B081MB6PN2 (**2024-03-28**) | VERIFIED (transcript) |
| **Protocol document** | RS-485 protocol shared via SharePoint link (**2024-03-25**) — the rev 1.1 doc stored in this directory | VERIFIED |
| **12 V packs ≠ Insight Home / Xanbus** | *"With the 12V 200Ah batteries, it is not possible to make it communicate with the Insight Home"* (**2023-11-23**, correcting the 2023-11-21 "talk to the home insight" remark); no Xanbus either. Hence our own reader. | VERIFIED (transcript) |
| **CAN path hardware (future, unused)** | Communication Hub $105 + Victron Cerbo-S GX (**2024-01-15**) | VERIFIED |

## Implications for the design

- **F37/F45 premise now stands on the committed original thread**: RS-485
  A/B, 2-wire, no ground, RJ45 7/8. The isolated-per-channel ADM2587E
  front-end is the correct topology class.
- **CAN ambiguity resolved**: battery-connector pins 1/2 (vendor) and the
  Pro-Series label's RJ45 4/5 describe **different connectors** and are
  mutually consistent. CAN remains unused by D36; if the future
  unpopulated pads are routed, follow the RJ45-side label (4/5) and
  bench-verify continuity through the actual cable at CP2+.
- **The on-site electrical test remains topology-gating (F47)** — nothing
  in the thread covers two isolated channels on a series stack; pass
  limits in the design doc §7. Connector-family ID (caliper/photo) rides
  along, plus which socket carries RS-485 on each pack.
- Photo set (pack face w/ two capped sockets + serial label
  V-BTH-0821-12V200Ah-0533; vendor cable both ends; app screenshot
  showing 13.31 V/98 % SOC) received from the owner 2026-07-16 — also
  referenced as attachments inside the 2023-12-27 message.
