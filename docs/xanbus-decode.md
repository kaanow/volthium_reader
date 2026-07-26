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

## Confirmed field — PGN 127172 DC status (reassembly proven on live data)

**PGN 127172 = per-node DC status. DC bus voltage = u16 little-endian ×0.001 V
at reassembled offset 2.** Verified after fast-packet reassembly:

    127172 src 0: 0303 8467 0000 18fcffff 1a000000 ffffffff00ffff64...  -> 0x6784 = 26.500 V
    127172 src 1: 0303 c067 0000 00000000 00000000 ffffffff00ffff64...  -> 0x67c0 = 26.560 V

Both track the ~26.5 V bus that Modbus SW-inverter reg 79 reports (26.51 V) —
the inverter (src 0) and MPPT (src 1) each broadcast their measured DC voltage.

**Lead (unconfirmed):** in src 0's buffer, offset 6 = `18 fc ff ff` = s32 LE
−1000, plausibly DC current (×0.001 → −1.0 A, or a per-node current); offset 10
= `1a 00 00 00` = 26. src 1's buffer is all-zero there (MPPT idle at night), which
is consistent with these being live current/power fields. Correlation across
daytime load swings will confirm the scale and sign.

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
