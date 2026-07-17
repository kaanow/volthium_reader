"""Burst-mode ambient checks (2026-07-17).

Continuous dual-adapter operation is itself a demonstrated InProgress-wedge
trigger, so VOLTHIUM_AMBIENT_MODE=burst keeps the second radio off and
brings it up only when a recovery decision needs the peers-or-us verdict.
These tests cover the verdict logic (target heard / only-others heard /
dead air), the cooldown that stops a stuck recovery loop from bursting
every cycle, the power-state restore, and the continuous loop's no-op.

Uses the same BLE dep stubs as the other test modules.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_ble_deps() -> None:
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
        async def disconnect(self, reset: bool = False) -> None: ...
        def _notification_handler(self, *args, **kwargs): return None
    ej.BMS = _BMS   # type: ignore[attr-defined]
    sys.modules["aiobmsble.bms.ej_bms"] = ej

    bleak = types.ModuleType("bleak")

    class _Scanner:
        def __init__(self, *a, **kw): ...
        async def start(self): ...
        async def stop(self): ...
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

ADDR_A = "09:01:00:14:7E:DC"
ADDR_B = "09:01:00:11:55:DF"
NEIGHBOR = "AA:BB:CC:DD:EE:FF"


class _Adv:
    def __init__(self, name=None, rssi=-70):
        self.local_name = name
        self.rssi = rssi


class _Dev:
    def __init__(self, address, name=""):
        self.address = address
        self.name = name


def _fake_scanner_class(advertisements):
    class _FakeScanner:
        def __init__(self, detection_callback=None, **kw):
            self._cb = detection_callback

        async def start(self):
            for dev, adv in advertisements:
                if self._cb:
                    self._cb(dev, adv)

        async def stop(self):
            pass

    return _FakeScanner


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class AmbientModeTests(unittest.TestCase):

    def test_off_without_adapter(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VOLTHIUM_AMBIENT_ADAPTER", None)
            self.assertEqual(pack_mod.ambient_mode(), "off")

    def test_continuous_is_default(self):
        with mock.patch.dict(os.environ, {
            "VOLTHIUM_AMBIENT_ADAPTER": "hci1",
        }):
            os.environ.pop("VOLTHIUM_AMBIENT_MODE", None)
            self.assertEqual(pack_mod.ambient_mode(), "continuous")

    def test_burst(self):
        with mock.patch.dict(os.environ, {
            "VOLTHIUM_AMBIENT_ADAPTER": "hci1",
            "VOLTHIUM_AMBIENT_MODE": "burst",
        }):
            self.assertEqual(pack_mod.ambient_mode(), "burst")

    def test_unknown_mode_falls_back_to_continuous(self):
        with mock.patch.dict(os.environ, {
            "VOLTHIUM_AMBIENT_ADAPTER": "hci1",
            "VOLTHIUM_AMBIENT_MODE": "sometimes",
        }):
            self.assertEqual(pack_mod.ambient_mode(), "continuous")


class BurstCheckTests(unittest.TestCase):

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        self.addCleanup(lambda: pack_mod._writer.close())
        self.events_path = Path(d.name) / "ev.jsonl"
        self._orig_scanner = pack_mod.BleakScanner
        self.addCleanup(setattr, pack_mod, "BleakScanner", self._orig_scanner)
        # Reset burst + ambient state between tests.
        pack_mod._last_burst_end_mono = None
        pack_mod._last_burst_verdict = None
        pack_mod._ambient_last_seen_mono.clear()
        self.run_calls: list[list[str]] = []

        async def _fake_run(cmd, **kw):
            self.run_calls.append(cmd)
            return ""

        self._orig_run = pack_mod._run
        pack_mod._run = _fake_run
        self.addCleanup(setattr, pack_mod, "_run", self._orig_run)

    def _events(self) -> str:
        try:
            return self.events_path.read_text()
        except OSError:
            return ""

    def _burst(self, advertisements, was_up=True):
        pack_mod.BleakScanner = _fake_scanner_class(advertisements)

        async def _fake_acquire():
            return ("hci1", was_up)

        with mock.patch.object(
            pack_mod, "_acquire_ambient_adapter", _fake_acquire,
        ):
            return _run(pack_mod.ambient_burst_check(
                {ADDR_A, ADDR_B}, trigger="test", duration_s=0.0,
            ))

    def test_target_heard_verdict_false(self):
        verdict = self._burst([(_Dev(ADDR_A, "kwbat"), _Adv("kwbat", -60))])
        self.assertIs(verdict, False)
        # Sighting feeds the shared last-seen state used by the gate + snapshot.
        self.assertIn(ADDR_A, pack_mod._ambient_last_seen_mono)
        ev = self._events()
        self.assertIn('"ambient_burst"', ev)
        self.assertIn('"peers_silent": false', ev)

    def test_only_neighbors_heard_verdict_true(self):
        verdict = self._burst([(_Dev(NEIGHBOR, "tv"), _Adv("tv", -80))])
        self.assertIs(verdict, True)
        self.assertIn('"peers_silent": true', self._events())
        self.assertIn('"other_adv_packets": 1', self._events())

    def test_dead_air_verdict_none(self):
        verdict = self._burst([])
        self.assertIsNone(verdict)
        self.assertIn('"peers_silent": null', self._events())

    def test_cooldown_reuses_verdict_without_second_event(self):
        verdict = self._burst([(_Dev(NEIGHBOR), _Adv())])
        self.assertIs(verdict, True)
        self.assertEqual(self._events().count('"ambient_burst"'), 1)
        # Immediately re-check: inside cooldown → cached verdict, no scan.
        verdict2 = self._burst([(_Dev(ADDR_A), _Adv())])  # would be False if scanned
        self.assertIs(verdict2, True)
        self.assertEqual(self._events().count('"ambient_burst"'), 1)
        # Age the last burst past the cooldown → scans again.
        pack_mod._last_burst_end_mono = (
            time.monotonic() - pack_mod.AMBIENT_BURST_COOLDOWN_S - 1.0
        )
        verdict3 = self._burst([(_Dev(ADDR_A), _Adv())])
        self.assertIs(verdict3, False)
        self.assertEqual(self._events().count('"ambient_burst"'), 2)

    def test_powers_adapter_back_down_when_it_was_down(self):
        self._burst([(_Dev(ADDR_A), _Adv())], was_up=False)
        self.assertIn(
            ["sudo", "-n", "hciconfig", "hci1", "down"], self.run_calls)

    def test_leaves_adapter_up_when_it_was_up(self):
        self._burst([(_Dev(ADDR_A), _Adv())], was_up=True)
        self.assertNotIn(
            ["sudo", "-n", "hciconfig", "hci1", "down"], self.run_calls)


class ContinuousLoopBurstModeTests(unittest.TestCase):

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        self.addCleanup(lambda: pack_mod._writer.close())
        self.events_path = Path(d.name) / "ev.jsonl"

    def test_loop_noops_in_burst_mode(self):
        with mock.patch.dict(os.environ, {
            "VOLTHIUM_AMBIENT_ADAPTER": "hci1",
            "VOLTHIUM_AMBIENT_MODE": "burst",
        }):
            _run(pack_mod.ambient_scanner_loop({ADDR_A, ADDR_B}))
        ev = self.events_path.read_text()
        self.assertIn("mode=burst", ev)
        self.assertNotIn('"ambient_scanner_started"', ev)


if __name__ == "__main__":
    unittest.main()
