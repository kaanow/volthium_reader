"""FM-11 — deaf-receiver detection (2026-07-14 incident).

The RTL8761B's firmware hang can leave the command path answering while the
RX path is dead: scans complete without error and hear NOTHING — not the
batteries, not the neighbors' gadgets. 52 minutes of "neither battery found"
went uncaught because no ladder rung fires without an exception. read_pack
now treats a zero-ambient scan as a DiscoveryWedgeError so the standard
ladder escalates to the USB replug (the cure).

Uses the same BLE dep stubs as the other test modules, with a controllable
fake BleakScanner that replays scripted advertisements.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


class _Adv:
    def __init__(self, name=None, rssi=-70):
        self.local_name = name
        self.rssi = rssi


class _Dev:
    def __init__(self, address, name=""):
        self.address = address
        self.name = name


def _fake_scanner_class(advertisements):
    """A BleakScanner stand-in that fires the scripted (dev, adv) pairs on
    start() and returns immediately on stop()."""

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


class DeafReceiverTests(unittest.TestCase):

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        self.addCleanup(lambda: pack_mod._writer.close())
        self.events_path = Path(d.name) / "ev.jsonl"
        self._orig_scanner = pack_mod.BleakScanner
        self.addCleanup(setattr, pack_mod, "BleakScanner", self._orig_scanner)

    def _events(self) -> str:
        try:
            return self.events_path.read_text()
        except OSError:
            return ""

    def test_silent_scan_raises_wedge_error(self):
        pack_mod.BleakScanner = _fake_scanner_class([])   # hears NOTHING
        with self.assertRaises(pack_mod.DiscoveryWedgeError) as ctx:
            _run(pack_mod.read_pack(ADDR_A, ADDR_B, timeout=0.05))
        self.assertIn("deaf", str(ctx.exception))
        self.assertIn('"event": "scan_deaf"', self._events())

    def test_ambient_only_scan_is_batteries_down_not_deaf(self):
        # The radio hears the neighbors but not the batteries: that's a
        # genuine battery outage (FM-5/FM-6), NOT a deaf receiver — read_pack
        # must keep its normal contract (raise RuntimeError for total loss,
        # so the logger takes the consec-errors path, not the wedge ladder).
        pack_mod.BleakScanner = _fake_scanner_class([
            (_Dev("EE:B3:03:C6:38:40", "Govee_H619D"), _Adv("Govee_H619D", -94)),
        ])
        with self.assertRaises(RuntimeError) as ctx:
            _run(pack_mod.read_pack(ADDR_A, ADDR_B, timeout=0.05))
        self.assertNotIsInstance(ctx.exception, pack_mod.DiscoveryWedgeError)
        self.assertNotIn("scan_deaf", self._events())

    def test_deaf_classification(self):
        cls = pack_mod._classify_wedge(
            reason="scan heard zero advertisements from any device — "
                   "BLE receiver deaf (FM-11)",
            dmesg=[], hci_state={"up": True}, bctl="", ub500_present=True,
        )
        self.assertEqual(cls, "adapter_rx_deaf")

    def test_dmesg_evidence_still_wins_over_deaf_reason(self):
        # Fresh kernel USB-reset evidence is more specific than the deaf
        # inference — keep the layer ordering.
        cls = pack_mod._classify_wedge(
            reason="... BLE receiver deaf (FM-11)",
            dmesg=["Bluetooth: hci0: Resetting usb device."],
            hci_state={"up": True}, bctl="", ub500_present=True,
        )
        self.assertEqual(cls, "kernel_usb_reset_chip_hung")


if __name__ == "__main__":
    unittest.main()
