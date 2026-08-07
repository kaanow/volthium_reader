"""Unit tests for the Xanbus charge-config watcher's change detection.

Pure logic — no socket, no bus. The point of the watcher is that it cannot
miss a change by looking at the wrong offset, so these pin the two ways that
could silently fail: ignoring the change counter, and noticing every other
byte.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xanbus_config_watch import COUNTER_OFFSET, digest   # noqa: E402


# A real 0x11B00 equalize record read from the MPPT on 2026-08-06.
LIVE = bytes.fromhex(
    "04010303007d000078690000007d0000"   #  0..15
    "204e0000204e0000204e0000ffffff7f"   # 16..31
    "ffffff7fffffff7fffffffffffff3c00"   # 32..47
    "3c003c00fc"                         # 48..52
)


class ConfigDigestTests(unittest.TestCase):

    def test_change_counter_is_ignored(self):
        """byte[1] increments on every accepted write, so including it would
        report a change for every change — doubling the noise and, worse,
        firing on our own restores."""
        a = bytearray(LIVE)
        b = bytearray(LIVE)
        b[COUNTER_OFFSET] = (a[COUNTER_OFFSET] + 7) & 0xFF
        self.assertEqual(digest(bytes(a)), digest(bytes(b)))

    def test_a_voltage_change_is_detected(self):
        """Offset 4 is the mapped equalize value: 32.0 V -> 28.0 V."""
        a = bytearray(LIVE)
        b = bytearray(LIVE)
        b[4:6] = (28000).to_bytes(2, "little")
        self.assertNotEqual(digest(bytes(a)), digest(bytes(b)))

    def test_the_unmapped_offset_8_is_detected(self):
        """The one field that actually differed between live config and
        factory defaults, and whose meaning we could NOT establish. Watching
        whole records exists precisely so this is covered without knowing
        what it means."""
        a = bytearray(LIVE)
        b = bytearray(LIVE)
        b[8:10] = (32000).to_bytes(2, "little")
        self.assertNotEqual(digest(bytes(a)), digest(bytes(b)))

    def test_every_single_byte_is_covered(self):
        """No offset may be invisible except the change counter."""
        base = digest(LIVE)
        for i in range(len(LIVE)):
            mutated = bytearray(LIVE)
            mutated[i] ^= 0xFF
            same = digest(bytes(mutated)) == base
            if i == COUNTER_OFFSET:
                self.assertTrue(same, "counter must be ignored")
            else:
                self.assertFalse(same, f"offset {i} is invisible to the watcher")


if __name__ == "__main__":
    unittest.main()
