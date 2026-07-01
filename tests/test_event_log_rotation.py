"""Tests for volthium.pack._EventLogWriter (sealed-segment rotation)
and the raw-frame tap subclass.

Uses BLE dep stubs from tests/test_log_schema so the module can be
imported on any Python.
"""

from __future__ import annotations

import os
import sys
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_ble_deps() -> None:
    """Same stub set as tests/test_log_schema — copy-pasted so this test file
    is self-contained and can be run in isolation."""
    if "aiobmsble" in sys.modules:
        return
    aiobmsble = types.ModuleType("aiobmsble")
    aiobmsble.BMSSample = dict   # type: ignore[attr-defined]
    sys.modules["aiobmsble"] = aiobmsble
    sys.modules["aiobmsble.bms"] = types.ModuleType("aiobmsble.bms")
    ej = types.ModuleType("aiobmsble.bms.ej_bms")

    class _BMS:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def _notification_handler(self, *args, **kwargs):
            return None
    ej.BMS = _BMS   # type: ignore[attr-defined]
    sys.modules["aiobmsble.bms.ej_bms"] = ej

    bleak = types.ModuleType("bleak")
    class _Scanner:
        @staticmethod
        async def find_device_by_address(*a, **kw): return None
    bleak.BleakScanner = _Scanner   # type: ignore[attr-defined]
    sys.modules["bleak"] = bleak
    sys.modules["bleak.backends"] = types.ModuleType("bleak.backends")
    backends_dev = types.ModuleType("bleak.backends.device")
    class _BLEDevice: pass
    backends_dev.BLEDevice = _BLEDevice   # type: ignore[attr-defined]
    sys.modules["bleak.backends.device"] = backends_dev


_stub_ble_deps()

from volthium import pack as pack_mod   # noqa: E402
from volthium.pack import (              # noqa: E402
    _EventLogWriter,
    _reset_writer_for_tests,
    _event,
)


def _sealed_files(root: Path, base: str) -> list[Path]:
    return sorted(root.glob(f"{base}.*.sealed"))


class SizeBasedRotationTests(unittest.TestCase):

    def test_writes_go_to_live_file(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            w = _EventLogWriter(p, max_segment_bytes=10_000, max_segment_age_s=999.0)
            w.write_line('{"a": 1}\n')
            w.write_line('{"a": 2}\n')
            self.assertTrue(p.exists())
            self.assertEqual(p.read_text(), '{"a": 1}\n{"a": 2}\n')
            self.assertEqual(_sealed_files(Path(d), "ev.jsonl"), [])

    def test_seals_when_size_exceeded(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            # 11-byte lines, cap at 30 → rotates on write #3 (_size hits 33)
            w = _EventLogWriter(p, max_segment_bytes=30, max_segment_age_s=999.0)
            for i in range(3):
                w.write_line(f'{{"n": {i:03d}}}\n')
            sealed = _sealed_files(Path(d), "ev.jsonl")
            self.assertEqual(len(sealed), 1)
            # Sealed file has all three lines
            content = sealed[0].read_text()
            self.assertIn('"n": 000', content)
            self.assertIn('"n": 002', content)

    def test_seq_survives_across_writer_instances(self):
        # Fresh writer must not clobber sealed files from a previous run.
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            # Simulate a prior run's sealed segment
            (Path(d) / "ev.jsonl.0007.sealed").write_text('{"old": true}\n')
            # 9-byte lines, cap at 20 → rotates on write #3 (_size hits 27)
            w = _EventLogWriter(p, max_segment_bytes=20, max_segment_age_s=999.0)
            for i in range(3):
                w.write_line(f'{{"n": {i}}}\n')
            sealed = _sealed_files(Path(d), "ev.jsonl")
            # Old .0007.sealed + new .0008.sealed
            self.assertEqual(len(sealed), 2)
            names = {s.name for s in sealed}
            self.assertIn("ev.jsonl.0007.sealed", names)
            self.assertIn("ev.jsonl.0008.sealed", names)


class TimeBasedRotationTests(unittest.TestCase):

    def test_seals_when_aged_out(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            w = _EventLogWriter(p, max_segment_bytes=1_000_000, max_segment_age_s=0.05)
            w.write_line('{"first": 1}\n')
            time.sleep(0.08)
            w.write_line('{"second": 1}\n')  # this write should trip aged_out
            sealed = _sealed_files(Path(d), "ev.jsonl")
            self.assertEqual(len(sealed), 1)


class SealedCapTests(unittest.TestCase):

    def test_drops_oldest_when_cap_reached(self):
        # Simulate a stuck uploader — we should never grow tmpfs beyond cap.
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            # Seed 3 fake sealed files that "should be uploaded but aren't"
            for i in (1, 2, 3):
                (Path(d) / f"ev.jsonl.000{i}.sealed").write_text(f"seed{i}\n")
            # Writer with cap = 3 and small size trigger
            w = _EventLogWriter(
                p,
                max_segment_bytes=20,
                max_segment_age_s=999.0,
                max_sealed_keep=3,
            )
            # Fill enough to trigger rotation once; before renaming the live
            # to sealed, cap enforcement should have dropped the oldest.
            w.write_line("a" * 25 + "\n")
            sealed = _sealed_files(Path(d), "ev.jsonl")
            self.assertEqual(len(sealed), 3)
            # 0001 should have been evicted; 0004 should be present
            names = {s.name for s in sealed}
            self.assertNotIn("ev.jsonl.0001.sealed", names)
            self.assertTrue(any("0004" in n for n in names))


class ModuleLevelEventTests(unittest.TestCase):
    """Cover the public `_event()` path — the one every caller uses."""

    def test_reset_for_tests_swaps_writer(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            w = _reset_writer_for_tests(p)
            self.assertIs(pack_mod._writer, w)
            _event("test_event", value=42)
            self.assertTrue(p.exists())
            line = p.read_text().strip()
            self.assertIn('"event": "test_event"', line)
            self.assertIn('"value": 42', line)
            self.assertIn('"ts": "', line)
            self.assertTrue(line.rstrip().endswith("}"))


class RawTapTests(unittest.TestCase):
    """The _VolthiumBMSTapped subclass wraps _notification_handler to emit
    raw_frame events. Uses the stubbed base class from _stub_ble_deps()."""

    def test_notification_emits_raw_frame(self):
        from volthium.pack import _VolthiumBMSTapped
        with TemporaryDirectory() as d:
            p = Path(d) / "ev.jsonl"
            _reset_writer_for_tests(p)
            bms = _VolthiumBMSTapped()
            bms._raw_addr = "AA:BB:CC:DD:EE:FF"
            fake_data = bytes([0x3a, 0x30, 0x30, 0x7e])   # ":00~" — plausible frame
            bms._notification_handler(None, fake_data)
            content = p.read_text()
            self.assertIn('"event": "raw_frame"', content)
            self.assertIn('"address": "AA:BB:CC:DD:EE:FF"', content)
            self.assertIn('"data_hex": "3a30307e"', content)
            self.assertIn('"data_len": 4', content)

    def test_capture_gate_off_by_default(self):
        # Import fresh state — env var not set
        os.environ.pop("VOLTHIUM_CAPTURE_RAW", None)
        pack_mod._capture_pack_cycles = 0
        self.assertFalse(pack_mod._capture_active())

    def test_capture_gate_on_with_env(self):
        os.environ["VOLTHIUM_CAPTURE_RAW"] = "1"
        pack_mod._capture_pack_cycles = 0
        try:
            self.assertTrue(pack_mod._capture_active())
        finally:
            os.environ.pop("VOLTHIUM_CAPTURE_RAW", None)

    def test_capture_gate_deactivates_after_cap(self):
        os.environ["VOLTHIUM_CAPTURE_RAW"] = "1"
        pack_mod._capture_pack_cycles = pack_mod._CAPTURE_CYCLE_CAP
        try:
            self.assertFalse(pack_mod._capture_active())
        finally:
            os.environ.pop("VOLTHIUM_CAPTURE_RAW", None)
            pack_mod._capture_pack_cycles = 0


if __name__ == "__main__":
    unittest.main()
