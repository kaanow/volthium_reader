"""Roundtrip and edge-case tests for the RS-485 wire protocol.

Run from repo root:
    .venv/bin/python -m unittest discover -s tests
"""
import struct
import unittest

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from volthium.wire_protocol import (
    FRAME_SIZE, FrameError, MAGIC, WireFrame, crc16_ccitt, decode, encode,
)


class TestCRC(unittest.TestCase):
    def test_known_vector(self):
        # CCITT-FALSE("123456789") = 0x29B1
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)

    def test_empty(self):
        self.assertEqual(crc16_ccitt(b""), 0xFFFF)


class TestRoundtrip(unittest.TestCase):
    def test_realistic_frame(self):
        f = WireFrame(
            seq=42, uptime_ms=12345, state="charging",
            pack_v=26.71, pack_i=16.3, pack_p=435.0,
            soc_a=68, soc_b=66,
            v_a=13.353, v_b=13.357, i_a=16.5, i_b=16.1,
            temp_a=23, temp_b=23,
            remaining_ah_a=156.0, remaining_ah_b=138.0,
            delta_v_a_mv=9, delta_v_b_mv=7,
            minutes_remaining=229,
            flags=0b110000,
        )
        wire = encode(f)
        self.assertEqual(len(wire), FRAME_SIZE)
        self.assertEqual(wire[:2], MAGIC)
        back = decode(wire)
        self.assertEqual(back.seq, 42)
        self.assertEqual(back.state, "charging")
        self.assertAlmostEqual(back.pack_v, 26.71, places=2)
        self.assertAlmostEqual(back.pack_i, 16.3, places=2)
        self.assertEqual(back.pack_p, 435.0)
        self.assertEqual(back.soc_a, 68)
        self.assertAlmostEqual(back.v_a, 13.353, places=3)
        self.assertEqual(back.delta_v_a_mv, 9)
        self.assertEqual(back.minutes_remaining, 229)

    def test_negative_current_discharge(self):
        f = WireFrame(state="discharging", pack_i=-15.5, pack_p=-410, temp_a=-5)
        back = decode(encode(f))
        self.assertAlmostEqual(back.pack_i, -15.5, places=2)
        self.assertEqual(back.pack_p, -410)
        self.assertEqual(back.temp_a, -5)
        self.assertEqual(back.state, "discharging")

    def test_unknown_fields_roundtrip_as_none(self):
        f = WireFrame(state="unknown")  # everything else None
        back = decode(encode(f))
        self.assertIsNone(back.pack_v)
        self.assertIsNone(back.pack_i)
        self.assertIsNone(back.soc_a)
        self.assertIsNone(back.minutes_remaining)


class TestErrorPaths(unittest.TestCase):
    def test_short_buf(self):
        with self.assertRaises(FrameError):
            decode(b"\xaa\x55" + b"\x00" * 10)

    def test_bad_magic(self):
        f = encode(WireFrame())
        bad = b"\x12\x34" + f[2:]
        with self.assertRaises(FrameError):
            decode(bad)

    def test_bit_flip_caught_by_crc(self):
        f = encode(WireFrame(seq=1, pack_v=26.0))
        # flip a bit somewhere in the body
        bad = bytearray(f)
        bad[10] ^= 0x01
        with self.assertRaises(FrameError):
            decode(bytes(bad))

    def test_size_is_43_bytes(self):
        # Wire-format invariant — firmware writers will assume this.
        self.assertEqual(FRAME_SIZE, 43)
        self.assertEqual(len(encode(WireFrame())), 43)


if __name__ == "__main__":
    unittest.main()
