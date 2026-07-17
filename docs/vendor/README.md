# Vendor reference docs

Third-party documentation kept in the repo so the wire-protocol source of
truth doesn't rot on a laptop somewhere. Do NOT edit the vendor files
themselves — copy relevant excerpts into our own docs (`reliability_failure_modes.md`,
`cloud_architecture.md`, etc.) with attribution.

> ✅ **Evidence status 2026-07-16 (second revision — original thread now on
> file, F45 closed).** The full support-email thread is committed:
> [`Voltage_monitoring_thread_2023-2024_redacted_transcript.txt`](Voltage_monitoring_thread_2023-2024_redacted_transcript.txt)
> (headers + complete bodies; see
> [`volthium-rs485-correspondence-2024.md`](volthium-rs485-correspondence-2024.md)
> for the dated fact table). Resolutions of the two earlier ambiguities:
> (1) the pack connector is a **4-pin circular threaded-collar
> aviation-style socket** (owner photographs of the actual Loon Lake packs +
> the vendor cable, 2026-07-16) — the vendor's "XLR" is colloquial and the
> earlier "M12" reading of the Pro-Series photo was the same shape guessed
> differently; exact PN = on-site caliper (vendor never supplied it).
> (2) the **CAN "pin 1 and 2" is the battery-side connector domain** (the
> thread context is explicit), so it **does not conflict** with this
> directory's photographed label putting CAN-H/L on RJ45 4/5 — one cable
> maps one to the other. RS-485 A/B on RJ45 **7/8** and "standard RS-485
> adapter, 2-wire, no ground, not raw TTL" are verified in the transcript.

## The picture these files paint together

The Volthium pack exposes **three** integration paths, and these three
files cover them end-to-end:

| Path | What speaks it | Files here |
|---|---|---|
| **BLE (Nordic UART GATT)** | Our reader (`aiobmsble/bms/ej_bms.py`) | Serial protocol doc — the byte format is identical, BLE just tunnels TTL |
| **RS-485 / RS-232 / raw TTL** | Any wired serial client; the RJ45 adapter breaks these out | Serial protocol doc + cable pinout |
| **CAN (2.0A, 250/500 kbps)** | Victron GX device / inverter / charger | Victron CANbus protocol + cable pinout |

The pack can even do the last two simultaneously via the RJ45 adapter —
the photographed Pro-Series label puts RS-485-A/B on pins 7/8 (verified
in the thread too) and CAN-H/L on RJ45 pins 4/5 (consistent with the
thread's battery-side "pin 1 and 2" — different connector domains; see
the banner above).

## Files

### `volthium-bms-serial-protocol-rev1.1.doc`

Volthium's official RS-485 / RS-232 / TTL BMS protocol specification,
revision 1.1. Applies to the 12V and 24V SC-series LiFePO4 packs (same
E&J Technology BMS family that `aiobmsble/bms/ej_bms.py` already decodes).

The pack we monitor at Loon Lake speaks this protocol over BLE (Nordic UART
service): the BLE notify frames we log to
[`data/simulator/pi-barge_raw_frames.jsonl`](../../data/simulator/README.md)
are literally frames of this spec, wrapped in GATT.

**Signaling** — the doc says "TTL 3.3 V" at the pins; RS-485 or RS-232 need
external transceivers (MAX485 / MAX232). The BLE tunnel carries the raw
byte stream without any electrical translation.

**Wire settings**

| | |
|---|---|
| Level | TTL 3.3 V at pins (transceiver-added on RS-485 / RS-232) |
| Baud | 9600 |
| Framing | 8N1, no flow control |

**Frame format**

`:AddrCmdVerLenInfoCRC~` — colon-delimited ASCII-hex, tilde terminator.
`Cmd` bit 7 = 1 for query, 0 for response.

| Cmd (query / response) | Purpose |
|---|---|
| `0x01 / 0x81` | Read protection parameters (overcharge / overdischarge / temp limits etc.) |
| `0x02 / 0x82` | Read real-time data (voltage / current / SOC / per-cell / temp / status bits) — **this is what our reader polls** |
| `0x05 / 0x8A · 0x8B` | Modify protection parameters (write; success / fail) |
| `0x06` | FET operate (turn CFET/DFET on or off) |
| `0x09` | Version info |

**CRC** — sum of all payload bytes, then bitwise-invert; C reference:
```c
uint8_t crc = 0;
for (j = 1; j < i; j++) crc += Rx485buf[j];
crc ^= 0xff;
```

Real-time frame (`Cmd=0x82`) layout: per-cell mV, currents (10 mA units),
temperatures (offset +40 °C), capacity, and a 16-bit status/alarm
bitfield (CING / DING / VoltH / VoltL / CurrC / CurrS / CurrD1 / CurrD2 /
TempCH / TempCL / TempDH / TempDL / DFET / CFET / SDFET / SCFET). Consult
the .doc for the field-by-field breakdown when extending `problem_code`
decoding or adding a FET-write path.

**Provenance** — vendor document, includes empirical validation notes from
Stephane Gagnon (March 2023) on a 12V-200Ah unit (raw frame captures
included in the doc).

### `victron-canbus-bms-protocol.pdf`

Victron Energy's "CANBUS BMS Protocol" spec (rev 2019-10). Describes the
CAN 2.0A messages a third-party BMS must send so a Victron GX device
(Cerbo GX, Venus OS) can treat it as a managed battery. If the cabin
ever gets a Victron inverter/charger, the Volthium BMS can talk to it
directly via CAN and honor the BMS-imposed charge/discharge limits.

**Wire settings** — 11-bit standard CAN, 250 kbps or 500 kbps
(selectable in Venus OS's Canbus profile).

**Minimum required CAN-IDs** (rest are optional):

| ID | Purpose | Fields (16-bit little-endian, scaled as noted) |
|---|---|---|
| `0x351` | Charge/discharge limits (CVL/CCL/DCL) | Charge V (0.1 V), Max charge A (0.1 A, signed), Max discharge A (0.1 A, signed), Discharge V (0.1 V) |
| `0x355` | SOC / SOH | SOC (1 %), SOH (1 %), optional high-res SOC (0.01 %) |
| `0x356` | Live pack telemetry | Voltage (0.01 V), Current (0.1 A, signed), Temperature (0.1 °C, signed) |
| `0x35A` | Alarms + warnings | 8 bytes of 2-bit fields (`10` = raised, `01` = cleared; `00`/`11` deprecated) |

Optional IDs include `0x35E` manufacturer name, `0x35F` battery model +
firmware, `0x370/0x371` name, `0x372` module counts, `0x373` cell V and
temp extremes, `0x378` cumulative energy in/out, `0x379` installed
capacity, `0x380/0x381` serial number.

**Timing** — BMS should send `0x351` every ~1 s; the Victron system stops
charging/discharging if `0x351` hasn't arrived in 3 s. The BMS's own
keep-alive is `0x305` from the GX — ≥10 min timeout so GX firmware
updates / reboots don't trip the pack contactor.

Not currently used by our reader — but if we ever build a cabin-side
"talk to the inverter" bridge, this is the target spec.

### `volthium-pro-series-rj45-adapter-pinout.png`

Product photo of the Volthium "Pro Series" adapter cable — a **4-pin
circular threaded aviation-style plug** on the battery end (the earlier
"M12" wording here was a mis-family of the same shape; superseded by the
owner's 2026-07-16 photos of the actual packs and cable), **RJ45 female**
on the client end. The label on the cable gives only the RJ45 pinout
(the battery-end pin layout is not published by the vendor):

| RJ45 pin | Signal |
|---|---|
| 1 | SPARE |
| 2 | SPARE |
| 3 | SPARE |
| **4** | **CAN-H** |
| **5** | **CAN-L** |
| 6 | SPARE |
| **7** | **RS-485-A** |
| **8** | **RS-485-B** |

Both CAN and RS-485 come out on the same RJ45, so a single adapter cable
supports both integration paths at once.

**Field wiring note** — the packs have **two comms sockets** (family per
the scope note above — to be identified on-site). Per vendor guidance,
for RS-485 communication use the socket **closer to the negative battery
post**. The function of the second socket is not documented here (likely
CAN or a daisy-chain, but confirm with the vendor before assuming).
