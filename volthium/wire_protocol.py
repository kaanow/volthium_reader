"""Wire protocol between the future battery-side and display-side ESP32 nodes.

This is also the reference implementation: any embedded firmware (in C, Rust,
whatever) must produce/consume frames that this code parses correctly. The
test suite roundtrips known frames through here.

Design goals:
  - Fixed-size payload so the receiver doesn't need a streaming parser
    on a tiny MCU.
  - Self-synchronizing — 2-byte magic so we can resync on link errors
    without rebooting.
  - Versioned — single byte. Bump when the payload shape changes.
  - All multi-byte fields little-endian (matches ESP32 native ordering).
  - CRC-16/CCITT-FALSE on everything between magic and CRC — catches all
    1-and-2-bit errors, most longer bursts.

Frame layout (43 bytes total):

  offset  size  field             encoding
  ──────  ────  ────────────────  ────────────────────────────────────────
       0     2  magic             0xAA 0x55
       2     1  version           starts at 1
       3     1  seq               wraps 0..255; gaps indicate dropped frames
       4     4  uptime_ms         since boot of battery-side node
       8     1  state             0 unknown, 1 idle, 2 charging, 3 discharging
       9     2  pack_voltage      uint16, 0.01 V (0..655.35 V)
      11     2  pack_current      int16, 0.01 A (-327.68..+327.67 A)
      13     2  pack_power        int16, 1 W (-32768..+32767 W)
      15     1  soc_a             uint8, percent (0..100)
      16     1  soc_b             uint8, percent (0..100)
      17     2  v_a               uint16, 0.001 V
      19     2  v_b               uint16, 0.001 V
      21     2  i_a               int16, 0.01 A
      23     2  i_b               int16, 0.01 A
      25     1  temp_a            int8, °C
      26     1  temp_b            int8, °C
      27     2  remaining_ah_a    uint16, 0.1 Ah
      29     2  remaining_ah_b    uint16, 0.1 Ah
      31     2  delta_v_a_mv      uint16, mV (cell imbalance)
      33     2  delta_v_b_mv      uint16, mV
      35     2  minutes_remaining uint16, minutes (0xFFFF = unknown)
      37     2  flags             bitfield (see below)
      39     2  reserved          0
      41     2  crc16             CCITT-FALSE, init 0xFFFF, over bytes [2..41]

  flags bits (LSB first):
      0  battery A unreachable
      1  battery B unreachable
      2  battery A problem flag (any non-zero problem_code)
      3  battery B problem flag
      4  charging fets on (A AND B)
      5  discharging fets on (A AND B)
      6..15  reserved

At 9600 8N1 a 43-byte frame is ~45 ms. Polling once per 30 s leaves the
line idle 99.85 % of the time — plenty of room for an "alive" beacon
from the display end.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional


MAGIC = b"\xaa\x55"
FRAME_SIZE = 43
VERSION = 1

STATE_UNKNOWN = 0
STATE_IDLE = 1
STATE_CHARGING = 2
STATE_DISCHARGING = 3
STATE_FULL = 4

STATE_FROM_NAME = {
    "unknown": STATE_UNKNOWN,
    "idle": STATE_IDLE,
    "charging": STATE_CHARGING,
    "discharging": STATE_DISCHARGING,
    "full": STATE_FULL,
}
NAME_FROM_STATE = {v: k for k, v in STATE_FROM_NAME.items()}


FLAG_A_UNREACHABLE = 1 << 0
FLAG_B_UNREACHABLE = 1 << 1
FLAG_A_PROBLEM = 1 << 2
FLAG_B_PROBLEM = 1 << 3
FLAG_CHARGING_FETS = 1 << 4
FLAG_DISCHARGING_FETS = 1 << 5


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE — polynomial 0x1021, init 0xFFFF, no reflection."""
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return crc


# fixed body format — 39 bytes between version(@2) and crc16(@41)
_BODY = struct.Struct(
    "<"      # little-endian
    "B"      # version
    "B"      # seq
    "I"      # uptime_ms
    "B"      # state
    "H"      # pack_voltage * 100
    "h"      # pack_current * 100
    "h"      # pack_power
    "B"      # soc_a
    "B"      # soc_b
    "H"      # v_a * 1000
    "H"      # v_b * 1000
    "h"      # i_a * 100
    "h"      # i_b * 100
    "b"      # temp_a
    "b"      # temp_b
    "H"      # rem_ah_a * 10
    "H"      # rem_ah_b * 10
    "H"      # delta_v_a_mv
    "H"      # delta_v_b_mv
    "H"      # minutes_remaining
    "H"      # flags
    "H"      # reserved
)
assert _BODY.size == 39


@dataclass
class WireFrame:
    """The decoded payload of one frame. Optional fields stay None if the
    BMS didn't report them; encode replaces None with a sentinel that decode
    knows to map back to None."""
    seq: int = 0
    uptime_ms: int = 0
    state: str = "unknown"
    pack_v: Optional[float] = None
    pack_i: Optional[float] = None
    pack_p: Optional[float] = None
    soc_a: Optional[int] = None
    soc_b: Optional[int] = None
    v_a: Optional[float] = None
    v_b: Optional[float] = None
    i_a: Optional[float] = None
    i_b: Optional[float] = None
    temp_a: Optional[int] = None
    temp_b: Optional[int] = None
    remaining_ah_a: Optional[float] = None
    remaining_ah_b: Optional[float] = None
    delta_v_a_mv: Optional[int] = None
    delta_v_b_mv: Optional[int] = None
    minutes_remaining: Optional[float] = None
    flags: int = 0


# encoded sentinels: how a None becomes a number, and back.
_SENTINEL = {
    "u8": 0xFF,
    "u16": 0xFFFF,
    "i8": -128,
    "i16": -32768,
}


def _e(v, kind, scale=1.0):
    if v is None:
        return _SENTINEL[kind]
    return int(round(v * scale))


def _d(raw, kind, scale=1.0):
    if raw == _SENTINEL[kind]:
        return None
    return raw / scale if scale != 1 else raw


def encode(f: WireFrame) -> bytes:
    """Encode a WireFrame into the 43-byte on-wire representation."""
    body = _BODY.pack(
        VERSION,
        f.seq & 0xFF,
        f.uptime_ms & 0xFFFFFFFF,
        STATE_FROM_NAME.get(f.state, STATE_UNKNOWN),
        _e(f.pack_v, "u16", 100),
        _e(f.pack_i, "i16", 100),
        _e(f.pack_p, "i16", 1),
        _e(f.soc_a, "u8"),
        _e(f.soc_b, "u8"),
        _e(f.v_a, "u16", 1000),
        _e(f.v_b, "u16", 1000),
        _e(f.i_a, "i16", 100),
        _e(f.i_b, "i16", 100),
        _e(f.temp_a, "i8"),
        _e(f.temp_b, "i8"),
        _e(f.remaining_ah_a, "u16", 10),
        _e(f.remaining_ah_b, "u16", 10),
        _e(f.delta_v_a_mv, "u16"),
        _e(f.delta_v_b_mv, "u16"),
        _e(f.minutes_remaining, "u16"),
        f.flags & 0xFFFF,
        0,
    )
    crc = crc16_ccitt(body)
    return MAGIC + body + struct.pack("<H", crc)


class FrameError(ValueError):
    pass


def decode(buf: bytes) -> WireFrame:
    """Decode 43 bytes into a WireFrame. Raises FrameError on any problem."""
    if len(buf) != FRAME_SIZE:
        raise FrameError(f"expected {FRAME_SIZE} bytes, got {len(buf)}")
    if buf[:2] != MAGIC:
        raise FrameError(f"bad magic: {buf[:2].hex()}")
    body = buf[2:2 + 39]
    crc_bytes = buf[41:43]
    got_crc, = struct.unpack("<H", crc_bytes)
    want_crc = crc16_ccitt(body)
    if got_crc != want_crc:
        raise FrameError(f"CRC mismatch: wire={got_crc:04x} computed={want_crc:04x}")
    (version, seq, uptime, state_raw,
     pv, pi, pp, sa, sb, va, vb, ia, ib, ta, tb,
     ra, rb, dva, dvb, mr, flags, _resv) = _BODY.unpack(body)
    if version != VERSION:
        raise FrameError(f"unknown version {version}, expected {VERSION}")
    return WireFrame(
        seq=seq,
        uptime_ms=uptime,
        state=NAME_FROM_STATE.get(state_raw, "unknown"),
        pack_v=_d(pv, "u16", 100),
        pack_i=_d(pi, "i16", 100),
        pack_p=_d(pp, "i16", 1),
        soc_a=_d(sa, "u8"),
        soc_b=_d(sb, "u8"),
        v_a=_d(va, "u16", 1000),
        v_b=_d(vb, "u16", 1000),
        i_a=_d(ia, "i16", 100),
        i_b=_d(ib, "i16", 100),
        temp_a=_d(ta, "i8"),
        temp_b=_d(tb, "i8"),
        remaining_ah_a=_d(ra, "u16", 10),
        remaining_ah_b=_d(rb, "u16", 10),
        delta_v_a_mv=_d(dva, "u16"),
        delta_v_b_mv=_d(dvb, "u16"),
        minutes_remaining=_d(mr, "u16"),
        flags=flags,
    )


def from_pack_reading(pack, estimate, seq: int = 0, uptime_ms: int = 0) -> WireFrame:
    """Build a WireFrame from our existing PackReading + Estimate objects.

    Useful for the dev rig (Mac) acting as a battery-side simulator over USB
    serial — the display-side firmware sees identical frames whether they
    come from the cabin MCU or this laptop.
    """
    flags = 0
    if pack.a.problem_code:           flags |= FLAG_A_PROBLEM
    if pack.b.problem_code:           flags |= FLAG_B_PROBLEM
    if pack.a.charging_fet and pack.b.charging_fet:
        flags |= FLAG_CHARGING_FETS
    if pack.a.discharging_fet and pack.b.discharging_fet:
        flags |= FLAG_DISCHARGING_FETS

    return WireFrame(
        seq=seq,
        uptime_ms=uptime_ms,
        state=estimate.state,
        pack_v=pack.pack_voltage,
        pack_i=pack.pack_current,
        pack_p=pack.pack_power,
        soc_a=int(pack.a.soc) if pack.a.soc is not None else None,
        soc_b=int(pack.b.soc) if pack.b.soc is not None else None,
        v_a=pack.a.voltage,
        v_b=pack.b.voltage,
        i_a=pack.a.current,
        i_b=pack.b.current,
        temp_a=int(pack.a.temperature) if pack.a.temperature is not None else None,
        temp_b=int(pack.b.temperature) if pack.b.temperature is not None else None,
        remaining_ah_a=pack.a.remaining_ah,
        remaining_ah_b=pack.b.remaining_ah,
        delta_v_a_mv=int(round(pack.a.delta_voltage * 1000)) if pack.a.delta_voltage is not None else None,
        delta_v_b_mv=int(round(pack.b.delta_voltage * 1000)) if pack.b.delta_voltage is not None else None,
        minutes_remaining=estimate.minutes_remaining,
        flags=flags,
    )
