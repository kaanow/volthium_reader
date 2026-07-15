# Vendor reference docs

Third-party documentation kept in the repo so the wire-protocol source of
truth doesn't rot on a laptop somewhere. Do NOT edit the vendor files
themselves — copy relevant excerpts into our own docs (`reliability_failure_modes.md`,
`cloud_architecture.md`, etc.) with attribution.

## Files

### `volthium-bms-serial-protocol-rev1.1.doc`

Volthium's official RS-485 / RS-232 BMS protocol specification, revision 1.1.
Applies to the 12V and 24V SC-series LiFePO4 packs (same E&J Technology BMS
family that `aiobmsble/bms/ej_bms.py` already decodes).

The pack we monitor at Loon Lake speaks this protocol over BLE (Nordic UART
service): the BLE notify frames we log to
[`data/simulator/pi-barge_raw_frames.jsonl`](../../data/simulator/README.md)
are literally frames of this spec, wrapped in GATT.

**Wire settings**

| | |
|---|---|
| Level | TTL 3.3 V |
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

**Real-time frame (`Cmd=0x82`) layout** — the exact byte fields for cell
voltages, currents (10 mA units), temperatures (offset by 40 °C), capacity,
and the 16-bit status/alarm bitfield (CING / DING / VoltH / VoltL / CurrC /
CurrS / CurrD1 / CurrD2 / TempCH / TempCL / TempDH / TempDL / DFET / CFET /
SDFET / SCFET). Consult the .doc for the field-by-field breakdown when
extending `problem_code` decoding or adding a FET-write path.

**Provenance** — vendor document, includes empirical validation notes from
Stephane Gagnon (March 2023) on a 12V-200Ah unit (raw frame captures
included in the doc).
