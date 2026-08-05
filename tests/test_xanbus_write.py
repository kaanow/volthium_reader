"""Tests for the Xanbus write path.

The safety-critical assertion: frames we would transmit are byte-identical
to what the real Insight Home transmitted, captured live on 2026-08-05 while
it fixed the latched MPPT. If this test fails, do NOT send anything.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import xanbus_write  # noqa: E402
from xanbus_write import (  # noqa: E402
    CAN_EFF_FLAG, DEFAULT_SRC_ADDR, MODE_OPERATING, MODE_STANDBY,
    build_mode_frame, crc16_ccitt, pack_frame, self_test, send_frame,
)

# Exactly what the Insight Home put on the wire (see /tmp capture analysis
# and docs/xanbus-decode.md): standby then operating, 24 s apart.
CAPTURED = [(0x19400102, "02"), (0x19400102, "03")]


class ModeFrameTests(unittest.TestCase):
    def test_matches_captured_insight_frames(self):
        for (want_id, want_data), mode in zip(CAPTURED,
                                              (MODE_STANDBY, MODE_OPERATING)):
            can_id, payload = build_mode_frame(dest=1, mode=mode, src=2)
            self.assertEqual(can_id, want_id, f"id for mode 0x{mode:02X}")
            self.assertEqual(payload.hex(), want_data)

    def test_default_src_is_unused_address(self):
        # our bus has nodes 0 (SW), 1 (MPPT), 2 (Insight) — don't impersonate
        self.assertNotIn(DEFAULT_SRC_ADDR, (0, 1, 2))
        can_id, _ = build_mode_frame(dest=1, mode=MODE_STANDBY)
        self.assertEqual(can_id & 0xFF, DEFAULT_SRC_ADDR)

    def test_destination_lands_in_ps_byte(self):
        can_id, _ = build_mode_frame(dest=1, mode=MODE_OPERATING, src=2)
        self.assertEqual((can_id >> 8) & 0xFF, 1)

    def test_refuses_unknown_mode(self):
        for bad in (0x00, 0x01, 0x04, 0xFF):
            with self.assertRaises(ValueError):
                build_mode_frame(dest=1, mode=bad)

    def test_payload_is_single_byte(self):
        _, payload = build_mode_frame(dest=1, mode=MODE_STANDBY)
        self.assertEqual(len(payload), 1)


class CrcRegressionTests(unittest.TestCase):
    def test_doc_vectors_still_pass(self):
        self.assertEqual(self_test(), 0)

    def test_crc_known_value(self):
        self.assertEqual(
            crc16_ccitt(bytes.fromhex("8412F76418020500BB32E76408")), 0xB81B)



class TransmitPathTests(unittest.TestCase):
    """The send path must be exercised without hardware. A missing `socket`
    import shipped once (2026-08-05) and only surfaced mid-experiment on the
    Pi — these tests make that class of bug impossible to ship again."""

    def test_module_has_transmit_dependencies(self):
        # NameError at send time is the failure mode being locked out
        self.assertTrue(hasattr(xanbus_write, "socket"))
        self.assertTrue(hasattr(xanbus_write, "struct"))

    def test_pack_frame_layout(self):
        can_id, payload = build_mode_frame(dest=1, mode=MODE_STANDBY, src=2)
        raw = pack_frame(can_id, payload)
        self.assertEqual(len(raw), 16)                 # SocketCAN frame size
        import struct as _s
        got_id, dlc, data = _s.unpack("=IB3x8s", raw)
        self.assertEqual(got_id, can_id | CAN_EFF_FLAG)  # EFF bit set
        self.assertEqual(dlc, 1)
        self.assertEqual(data[:1], b"\x02")
        self.assertEqual(data[1:], b"\x00" * 7)         # padded, not garbage

    def test_send_frame_binds_and_sends_without_hardware(self):
        # AF_CAN is Linux-only, so stand in a whole fake socket module —
        # this runs the real send_frame body on any dev machine.
        sent = {}

        class FakeSock:
            def bind(self, addr): sent["iface"] = addr
            def send(self, b): sent["bytes"] = b
            def close(self): sent["closed"] = True

        class FakeSocketModule:
            AF_CAN = 29
            SOCK_RAW = 3
            CAN_RAW = 1
            @staticmethod
            def socket(*a, **k):
                sent["args"] = a
                return FakeSock()

        real = xanbus_write.socket
        xanbus_write.socket = FakeSocketModule
        try:
            can_id, payload = build_mode_frame(dest=1, mode=MODE_OPERATING, src=2)
            send_frame(can_id, payload, iface="can9")
        finally:
            xanbus_write.socket = real
        self.assertEqual(sent["args"], (29, 3, 1))     # AF_CAN raw socket
        self.assertEqual(sent["iface"], ("can9",))
        self.assertEqual(sent["bytes"], pack_frame(can_id, payload))
        self.assertTrue(sent["closed"])                # socket always released

    def test_send_frame_closes_socket_on_error(self):
        sent = {}

        class ExplodingSock:
            def bind(self, addr): raise OSError("no such device")
            def close(self): sent["closed"] = True

        class FakeSocketModule:
            AF_CAN, SOCK_RAW, CAN_RAW = 29, 3, 1
            @staticmethod
            def socket(*a, **k): return ExplodingSock()

        real = xanbus_write.socket
        xanbus_write.socket = FakeSocketModule
        try:
            with self.assertRaises(OSError):
                send_frame(0x19400180, b"\x02", iface="nope0")
        finally:
            xanbus_write.socket = real
        self.assertTrue(sent["closed"])   # no fd leak on a failed transmit


if __name__ == "__main__":
    unittest.main()
