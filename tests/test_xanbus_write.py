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

from xanbus_write import (  # noqa: E402
    DEFAULT_SRC_ADDR, MODE_OPERATING, MODE_STANDBY,
    build_mode_frame, crc16_ccitt, self_test,
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


if __name__ == "__main__":
    unittest.main()
