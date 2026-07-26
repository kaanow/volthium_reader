"""Wired RS-485 reader for the Volthium BMS.

Speaks the same vendor serial protocol as the BLE path (aiobmsble `ej_bms`),
just over a serial line instead of a GATT tunnel: 9600 8N1, ASCII frame
`:AddrCmdVerLenInfoCRC~`, Cmd 0x02 real-time + Cmd 0x10 capacity. Decodes into
the same `BMSSample`-shaped dict that `BatteryReading.from_sample` consumes, so
the entire CSV/cloud pipeline is reused unchanged.

The wired path is immune to the BLE dormancy/wedge failure modes — it's a
separate interface on the BMS. Validated 2026-07-25: read both batteries
cleanly, including one that was simultaneously BLE-dormant. Frame layout /
field offsets mirror `aiobmsble/bms/ej_bms.py::_FIELDS` (the same decoder the
BLE reader uses on the identical byte stream). See
docs/investigations/2026-07-16-bt-wedge-causation.md.
"""
from __future__ import annotations

import time
from typing import Optional

import serial

from volthium.pack import BatteryReading

BAUD = 9600
QUERY_RT = b":000250000E03~"    # Cmd 0x02 real-time (addr 00; BMS ignores the query CRC)
QUERY_CAP = b":001031000E05~"   # Cmd 0x10 capacity (cycle_charge -> remaining_ah)
_CELL_POS = 12                  # cell voltages start here (ej_bms._CELL_POS)
_CELLS = 4                      # 12 V pack = 4 series cells
_FRAME_TIMEOUT = 2.0


def open_port(port: str) -> serial.Serial:
    """Open one RS-485 adapter at the BMS wire settings (9600 8N1)."""
    return serial.Serial(port, BAUD, timeout=1.0, bytesize=8, parity="N", stopbits=1)


def read_frame(ser: serial.Serial, query: bytes, timeout: float = _FRAME_TIMEOUT) -> Optional[bytes]:
    """Send `query`, read one `:...~` frame, return its hex-decoded body bytes.

    Returns None on timeout / malformed / non-hex frame. Never raises for a bad
    frame (only a serial-layer error propagates)."""
    ser.reset_input_buffer()
    ser.write(query)
    ser.flush()
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = ser.read(128)
        if not chunk:
            continue
        buf.extend(chunk)
        i, j = buf.find(b":"), buf.rfind(b"~")
        if i != -1 and j > i:
            try:
                return bytes.fromhex(buf[i + 1:j].decode("ascii", "ignore"))
            except ValueError:
                return None
    return None


def _u(msg: bytes, off: int, length: int) -> int:
    return int.from_bytes(msg[off:off + length], "big")


def decode_sample(rt: Optional[bytes], cap: Optional[bytes]) -> Optional[dict]:
    """RT (Cmd 0x82) + optional CAP frame -> BMSSample dict.

    Offsets mirror `ej_bms._FIELDS` exactly (both are decoding the same vendor
    byte stream). `rt` is the hex-decoded frame *including* its 5-byte header
    (Addr, Cmd, Ver, Len[2]), same as ej_bms's `_msg`."""
    if rt is None or len(rt) < 67:
        return None
    cells = [_u(rt, _CELL_POS + 2 * i, 2) / 1000.0 for i in range(_CELLS)]
    cells = [c for c in cells if c > 0]              # drop absent cells (report 0)
    cur_raw = _u(rt, 44, 4)                           # hi16 = charge, lo16 = discharge
    current = ((cur_raw >> 16) - (cur_raw & 0xFFFF)) / 100.0
    status = _u(rt, 52, 2)                            # 16-bit status/alarm word
    sample: dict = {
        "voltage": round(sum(cells), 3) if cells else None,
        "current": current,
        "battery_level": rt[61],                     # SOC %
        "temp_values": [rt[48] - 40],                # °C (offset +40)
        "cycles": _u(rt, 57, 2),
        "problem_code": status & 0x0FFC,             # alarm bits 2-11
        "chrg_mosfet": bool(rt[52] & 0x20),
        "dischrg_mosfet": bool(rt[52] & 0x10),
        "balancer": _u(rt, 55, 2),
        "heater": bool(rt[54]),
        "design_capacity": _u(rt, 66, 2) // 10 if len(rt) > 67 else None,
        "cell_voltages": cells or None,
        "delta_voltage": round(max(cells) - min(cells), 3) if cells else None,
    }
    if cap is not None and len(cap) >= 9:
        sample["cycle_charge"] = _u(cap, 7, 2) / 10.0
    return sample


def read_battery(ser: serial.Serial, address: str, name: str) -> Optional[BatteryReading]:
    """Query one battery over an already-open serial handle. None if unreadable.

    Raises only on a serial-layer error (so the caller can reopen the port);
    a timed-out / malformed frame returns None."""
    rt = read_frame(ser, QUERY_RT)
    if rt is None:
        return None
    time.sleep(0.1)                                  # vendor: ≥ ~1 s between queries; RT then CAP
    cap = read_frame(ser, QUERY_CAP)
    sample = decode_sample(rt, cap)
    if sample is None:
        return None
    return BatteryReading.from_sample(address, name, sample)
