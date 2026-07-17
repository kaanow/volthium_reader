# Volthium support correspondence — RS-485 / CAN battery interface (redacted transcript on file)

> **Provenance (F45 closed 2026-07-16; labels corrected per F55):** the
> support thread is committed as an **owner-supplied redacted transcript**
> derived from an off-file original —
> [`Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`](Voltage_monitoring_thread_2023-2024_redacted_transcript.txt)
> — decoded headers plus the complete message bodies in both directions. Redaction scheme (privacy for a public repo): personal
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
"12.8-200-G4DY-CH20 I think"; the owner-reported serial label reads
**V-BTH-0821-12V200Ah-0533**, app ID V-12V200AH-0533), in series → 24 V,
off-grid cabin.

## Verified facts (each dated; check against the transcript)

| Fact | Vendor statement (date) | Status |
|------|------------------|---------------|
| **Interface is RS-485 (not TTL)** | *"Use a Standard RS485 adapter with A & B. No ground need. Don't use a TTL 3.3V adapter directly."* (**2024-03-28**). The protocol doc's "TTL 3.3 V" is the BMS's internal signaling — the owner asked exactly this (2024-03-28 03:37) and this was the answer. | **VERIFIED** (transcript) — also corroborated by the photographed adapter label (RS-485 on the RJ45) |
| **RS-485 pinout on the RJ45 end** | *"Pin 7 RS485 A · Pin 8 RS485 B"* (**2024-01-15**) | **VERIFIED** — two independent sources (thread + photographed label) |
| **Which socket** | *"you'll need to use the one closest to the negative terminal"* (**2024-01-15**). Owner-reported inspection: **two** identical 4-pin sockets on the pack face. | VERIFIED (transcript); which-is-which per pack = on-site |
| **CAN pinout — battery-side connector, NOT RJ45** | *"On our CAN, the first pine is CAN High and the 2nd is CAN Low"* (**2023-11-14**); *"our CAN uses pin 1 and 2"* (**2023-11-21**). **Domain resolved by the thread context:** the owner's question (2023-12-27) was explicitly about the **connector on the battery** — *"It is not the RJ45 I expected … it is not clear which pins are 1 and 2"*. So CAN-H/L = **pins 1/2 of the pack's 4-pin connector**. This does **not** conflict with the photographed Pro-Series adapter label putting CAN-H/L on **RJ45 4/5** — different connectors, one cable maps one to the other. | **RESOLVED** (was flagged ambiguous in review F45) |
| **Battery connector** | Vendor sells *"XLR to RJ45 female"* cables ($10/Ea, **2024-01-15**; "PACKAGE ADDITIONAL COMMUNICATION CABLE" $21.98, **2024-03-13**). **Measured + photographed 2026-07-17 (photos ON FILE, `images/`):** the purchased cable's battery end is a **4-position M12-pattern screw-coupling female cordset** — coupling-thread ID ≈ 12.3 mm (M12×1 nut), molded body + knurled metal ring, insert **numbered 1→4 CCW, keying notch between 1 and 4**; client end is an **RJ45 male** plug (no patch cable needed). "XLR" was the vendor's colloquial name; the repo's original "4-socket M12" reading was closest. Pack side carries male pins (owner-reported pack photos, uncommitted). **Vendor PN still never supplied** (asked 2023-12-27, unanswered) — of curiosity value only; we mate at the RJ45 end. | **Measured; photos on file** (`volthium-cable-m12-face-numbered.jpg`, `volthium-cable-m12-to-rj45male-full.jpg`) |
| **Measured cable conductor map (owner multimeter, 2026-07-17)** | Battery pin → RJ45 pin: **1→4, 2→6, 3→7, 4→8**. Combined with the thread's battery-side CAN-1/2: **battery 1 = CAN-H (RJ45 4) · 2 = CAN-L (RJ45 6) · 3 = RS-485 A (RJ45 7) · 4 = RS-485 B (RJ45 8)**. All four positions wired. Note: CAN-L lands on RJ45 **6** in this cable — the Pro-Series label's "4/5" does not describe it (different products; the F45 caution about generalizing one artifact's mapping was correct). | **Rung-1 measurement** of the in-service cables |
| **Example working adapter** | Generic USB-RS485 converter, Amazon B081MB6PN2 (**2024-03-28**) | VERIFIED (transcript) |
| **Protocol document** | RS-485 protocol shared via SharePoint link (**2024-03-25**) — the rev 1.1 doc stored in this directory | VERIFIED |
| **12 V packs ≠ Insight Home / Xanbus** | *"With the 12V 200Ah batteries, it is not possible to make it communicate with the Insight Home"* (**2023-11-23**, correcting the 2023-11-21 "talk to the home insight" remark); no Xanbus either. Hence our own reader. | VERIFIED (transcript) |
| **CAN path hardware (future, unused)** | Communication Hub $105 + Victron Cerbo-S GX (**2024-01-15**) | VERIFIED |

## Implications for the design

- **F37/F45 premise now stands on the committed transcript** (owner-supplied redaction of an off-file original): RS-485
  A/B, 2-wire, no ground, RJ45 7/8. The isolated-per-channel ADM2587E
  front-end is the correct topology class.
- **CAN fully mapped (2026-07-17 beep-out supersedes the interim
  "follow the label 4/5" guidance)**: battery pins 1/2 = CAN-H/L; on the
  **in-service cable** they arrive at RJ45 **4 and 6** (measured — the
  Pro-Series label's 4/5 describes a different cable product). CAN
  remains unused by D36; any future pad routing follows the measured map
  of the cable actually in service.
- **The on-site electrical test remains topology-gating (F47)** — nothing
  in the thread covers two isolated channels on a series stack; pass
  limits in the design doc §7. Remaining on-site side-item: only which
  socket carries RS-485 on each pack (connector ID + conductor map were
  closed on the bench 2026-07-17).
- Photo set (pack face w/ two capped sockets + serial label
  V-BTH-0821-12V200Ah-0533; vendor cable both ends; app screenshot
  showing 13.31 V/98 % SOC) was shared with the designer in-session
  2026-07-16 but is **not committed** — the claims it supports are
  labeled owner-reported (F55). The 2023-12-27 message references the
  same photos as attachments.
