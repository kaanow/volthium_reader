# Xanbus decoding — retiring the Insight Home

Goal: read the same telemetry from the raw Xanbus (Schneider Conext CAN network)
that we currently get from the Insight Home's Modbus/TCP server, so the Insight
Home can be retired. Two live captures feed this (both running on the Pi as
systemd services):

- `scripts/can_capture.py` → `data/xanbus/*.jsonl[.gz]` — every CAN frame,
  `{"t", "id":"0xHEX", "ext":bool, "d":"hex"}`.
- `scripts/modbus_poll.py` → `data/modbus/*.jsonl[.gz]` — labelled register
  snapshots from the Conext gateway (192.168.1.71:503), the ground truth.

`scripts/xanbus_decode.py` does two things: (1) **catalogs** the bus by parsing
the 29-bit J1939/NMEA2000 arbitration IDs into PGN + source + rate, and (2)
**correlates** each varying Modbus register against every (CAN id, offset, width,
endian, sign) candidate to recover field scaling.

## Bus map (first capture, ~15 min, nighttime steady discharge)

25 PGN/source groups, two source nodes (SA 0 and SA 1 = SW inverter + MPPT).
All observed PGNs are in the 126990–127177 range — **Schneider proprietary
Conext PGNs**, not standard NMEA2000 (only 126998 Config Information is standard).
Priority 6 for most; 127005 is priority 2. Several are NMEA2000 **fast-packet**
(multi-frame): 126998, 127166, 127172. Highest-rate: 126998 (~48/s), 127005
(~20/s), 127173 (~16/s), 127172 (~12/s each node).

## Confirmed field (by eye, pending correlation confirmation)

**PGN 127172 = per-node DC status; DC bus voltage at reassembled data offset 2,
u16 little-endian ×0.001 V.**

Fast-packet frame 0 for 127172 src 0: `20 24 03 03 70 67 00 00`
- `20` = fast-packet sequence/frame counter
- `24` = total payload size (36 bytes)
- data[0:6] = `03 03 70 67 00 00` → data offset 2–3 = `0x6770` LE = 26480 → **26.48 V**

Node 1 (src 1) reads `0x67c0` = 26.56 V. Both track the ~26.5 V bus that Modbus
SW-inverter reg 79 reports (26.51 V). This is the inverter and MPPT each
broadcasting their measured DC bus voltage.

## Key limitation — fast-packet reassembly needed before correlating multi-frame PGNs

The correlation engine currently treats each CAN frame's ≤8 bytes independently.
For **fast-packet** PGNs (flagged `fp=Y` in the catalog) the real fields span a
reassembled multi-frame buffer, and the first byte(s) of frame 0 are the
seq/size header — so raw-frame offsets are shifted and split. Single-frame PGNs
(no `fp`) correlate directly. **Next enhancement:** add a fast-packet reassembly
stage (group by PGN+source, order by sequence counter, concatenate data bytes)
and correlate against the reassembled buffer. That will let correlation confirm
the 127172 DC-voltage field above and find current / SOC / power fields.

## Why correlation is thin so far

Correlation needs the values to *move*. The first captures are nighttime steady
discharge — the DC bus barely varies, so no register cleared the r ≥ 0.95 bar
yet. It sharpens a lot across daytime solar and load swings. Re-run
`scripts/xanbus_decode.py` after a day of mixed data.

## Modbus ground-truth so far

Responsive slaves: gateway=1, MPPT60=30, SW-inverter=90 (BattMon 190 returns no
data — there is no separate battery monitor). Known: SW reg 79 = DC bus voltage
×0.001. The poller sweeps regs 0–384 in 16-register chunks (the server excepts
on any invalid address in a block, so small chunks are merged).
