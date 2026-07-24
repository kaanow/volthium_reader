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
import time
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


class DiscoverySettleGraceTests(unittest.TestCase):
    """A dormant battery must not force the full scan timeout every cycle
    (2026-07-23 partner-following). Once the first target is heard, the scan
    returns after a short grace instead of waiting the full timeout for the
    absent one — but a fully-silent scan still runs the full timeout so FM-11
    deaf detection is preserved."""

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        self.addCleanup(lambda: pack_mod._writer.close())
        self._orig_scanner = pack_mod.BleakScanner
        self.addCleanup(setattr, pack_mod, "BleakScanner", self._orig_scanner)

    def test_one_present_one_absent_returns_after_grace(self):
        # A advertises, B is silent: return ~grace after A is heard, NOT the
        # full 5 s timeout — that starvation is what dragged B down.
        pack_mod.BleakScanner = _fake_scanner_class([
            (_Dev(ADDR_A, "V-A"), _Adv("V-A", -70)),
        ])
        t0 = time.monotonic()
        found, ambient = _run(pack_mod._discover_addresses(
            {ADDR_A, ADDR_B}, timeout=5.0, settle_grace=0.05))
        elapsed = time.monotonic() - t0
        self.assertIn(ADDR_A, found)
        self.assertNotIn(ADDR_B, found)
        self.assertLess(elapsed, 1.0)  # grace-bounded, not the 5 s timeout

    def test_both_present_returns_immediately(self):
        pack_mod.BleakScanner = _fake_scanner_class([
            (_Dev(ADDR_A, "V-A"), _Adv("V-A", -70)),
            (_Dev(ADDR_B, "V-B"), _Adv("V-B", -72)),
        ])
        t0 = time.monotonic()
        found, _ = _run(pack_mod._discover_addresses(
            {ADDR_A, ADDR_B}, timeout=5.0, settle_grace=4.0))
        elapsed = time.monotonic() - t0
        self.assertEqual(set(found), {ADDR_A, ADDR_B})
        self.assertLess(elapsed, 1.0)  # `done` fired; grace never consulted

    def test_none_present_runs_full_timeout(self):
        # Regression: a silent scan must still burn the full timeout so the
        # ambient==0 FM-11 signal and the recovery ladder stay intact.
        pack_mod.BleakScanner = _fake_scanner_class([])
        t0 = time.monotonic()
        found, ambient = _run(pack_mod._discover_addresses(
            {ADDR_A, ADDR_B}, timeout=0.3, settle_grace=0.05))
        elapsed = time.monotonic() - t0
        self.assertEqual(found, {})
        self.assertEqual(ambient, 0)
        self.assertGreaterEqual(elapsed, 0.3)  # full timeout, not grace


class PrefetchedAndPersistentTests(unittest.TestCase):
    """Persistent-connection experiment: one battery read over a held link on a
    dedicated adapter (passed to read_pack via `prefetched`), the other on/off.
    Verifies the prefetched battery is excluded from the primary adapter's
    discovery, that the off-path is unchanged, and the held-connection lifecycle."""

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        self.addCleanup(lambda: pack_mod._writer.close())
        self.events_path = Path(d.name) / "ev.jsonl"
        self._orig_scanner = pack_mod.BleakScanner
        self.addCleanup(setattr, pack_mod, "BleakScanner", self._orig_scanner)
        pack_mod._persistent_bms.clear()
        self.addCleanup(pack_mod._persistent_bms.clear)

    def _events(self):
        try:
            return self.events_path.read_text()
        except OSError:
            return ""

    def _reading(self, addr):
        return pack_mod.BatteryReading(
            address=addr, name="X", voltage=13.2, current=-1.0, soc=80,
            remaining_ah=None, temperature=20, cycles=None, cell_voltages=None,
            delta_voltage=None, charging_fet=None, discharging_fet=None,
            problem_code=0)

    def test_prefetched_battery_is_not_discovered(self):
        # A is prefetched (read on the dedicated adapter); the primary scanner
        # hears only an unrelated device (not deaf) and not B. A's reading must
        # be used verbatim, B marked absent, and A never scanned for.
        pack_mod.BleakScanner = _fake_scanner_class([
            (_Dev("EE:B3:03:C6:38:40", "Govee"), _Adv("Govee", -90)),
        ])
        a = self._reading(ADDR_A)
        pack = _run(pack_mod.read_pack(ADDR_A, ADDR_B, timeout=0.05,
                                       prefetched={ADDR_A: a}))
        self.assertIs(pack.a, a)              # prefetched used verbatim
        self.assertIsNone(pack.b.voltage)     # B absent -> missing reading
        import json
        for ln in self._events().splitlines():
            e = json.loads(ln)
            if e.get("event") == "scan_result":
                self.assertNotEqual(e.get("address"), ADDR_A)  # A never scanned

    def test_prefetched_none_is_legacy_behaviour(self):
        # Regression: with the feature off (no prefetched), nothing-found still
        # raises the both-down RuntimeError exactly as before.
        pack_mod.BleakScanner = _fake_scanner_class([
            (_Dev("EE:B3:03:C6:38:40", "Govee"), _Adv("Govee", -90)),
        ])
        with self.assertRaises(RuntimeError):
            _run(pack_mod.read_pack(ADDR_A, ADDR_B, timeout=0.05))

    def test_persistent_read_absent_returns_none(self):
        # Target not advertising -> can't (re)connect -> None + persist_absent,
        # and nothing cached (next cycle retries cleanly).
        pack_mod.BleakScanner = _fake_scanner_class([])
        r = _run(pack_mod.persistent_read(ADDR_A, "hci1", timeout=0.05))
        self.assertIsNone(r)
        self.assertIn('"event": "persist_absent"', self._events())
        self.assertNotIn(ADDR_A, pack_mod._persistent_bms)

    def test_persistent_shutdown_releases_held(self):
        # A held connection must be disconnected + forgotten on shutdown (the
        # SIGTERM graceful-release path that keeps deploys from wedging the BMS).
        class _Held:
            def __init__(self):
                self.disconnected = False

            async def disconnect(self, reset=False):
                self.disconnected = True

        held = _Held()
        pack_mod._persistent_bms[ADDR_A] = held
        _run(pack_mod.persistent_shutdown())
        self.assertEqual(pack_mod._persistent_bms, {})
        self.assertTrue(held.disconnected)


if __name__ == "__main__":
    unittest.main()
