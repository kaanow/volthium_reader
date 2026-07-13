"""Tests for the FM-9 hardening (2026-07-13 outage):

  - _AdapterManager verifies the pinned adapter with bluetoothd (D-Bus),
    not just hciconfig (kernel) — kernel-only visibility means bleak can't
    use the adapter and every scan fails `adapter not found`.
  - When the primary is unusable the manager switches to
    VOLTHIUM_FALLBACK_ADAPTER (powering it on), and switches back — powering
    the fallback down — once the primary is healthy again.
  - The USB-replug rung locates the dongle's sysfs device dir and toggles
    `authorized` 0→1 (a software unplug/replug).

Uses the same BLE dep stubs as tests/test_log_schema so the module can be
imported on any Python.
"""

from __future__ import annotations

import asyncio
import os
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


UB500_MAC = "20:E1:5D:68:30:8B"
INTERNAL_MAC = "B8:27:EB:37:69:FD"

HCICONFIG_BOTH = (
    "hci2:\tType: Primary  Bus: USB\n"
    f"\tBD Address: {UB500_MAC}  ACL MTU: 1021:6  SCO MTU: 255:12\n"
    "\tUP RUNNING\n"
    "\n"
    "hci1:\tType: Primary  Bus: UART\n"
    f"\tBD Address: {INTERNAL_MAC}  ACL MTU: 1021:8  SCO MTU: 64:1\n"
    "\tUP RUNNING\n"
)

BLUEZ_LIST_BOTH = (
    f"Controller {UB500_MAC} kwpi #1 [default]\n"
    f"Controller {INTERNAL_MAC} kwpi\n"
)
# The 2026-07-12/13 signature: kernel lists the UB500, bluetoothd doesn't.
BLUEZ_LIST_INTERNAL_ONLY = f"Controller {INTERNAL_MAC} kwpi [default]\n"


def _run_coro(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeRunMixin(unittest.TestCase):
    """Patch pack_mod._run with a substring→response table and record calls."""

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")
        # Close the live handle before the temp dir is removed (Windows).
        self.addCleanup(lambda: pack_mod._writer.close())
        self.events_path = Path(d.name) / "ev.jsonl"

        self.mgr = pack_mod._reset_adapter_state_for_tests()
        self.addCleanup(pack_mod._reset_adapter_state_for_tests)

        self._orig_run = pack_mod._run
        self.calls: list[str] = []
        self.responses: dict[str, str] = {}

        async def fake_run(cmd, *, timeout=8.0):
            key = " ".join(cmd)
            self.calls.append(key)
            for pat, out in self.responses.items():
                if pat in key:
                    return out
            return ""
        pack_mod._run = fake_run
        self.addCleanup(setattr, pack_mod, "_run", self._orig_run)

        self._saved_env = {
            k: os.environ.get(k)
            for k in ("VOLTHIUM_ADAPTER", "VOLTHIUM_FALLBACK_ADAPTER",
                      "VOLTHIUM_ADAPTER_USB_ID")
        }
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def events(self) -> str:
        try:
            return self.events_path.read_text()
        except OSError:
            return ""


class PrimaryResolutionTests(_FakeRunMixin):

    def test_primary_resolves_when_kernel_and_dbus_agree(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        os.environ.pop("VOLTHIUM_FALLBACK_ADAPTER", None)
        self.responses = {
            "bluetoothctl list": BLUEZ_LIST_BOTH,
            "hciconfig": HCICONFIG_BOTH,
        }
        hci = _run_coro(self.mgr.resolve())
        self.assertEqual(hci, "hci2")
        self.assertFalse(self.mgr.active_is_fallback)
        self.assertIn('"event": "adapter_pinned"', self.events())

    def test_kernel_only_visibility_is_a_pin_failure(self):
        # hciconfig lists the UB500 but bluetoothd does NOT — bleak would
        # throw `adapter 'hci2' not found` forever. Must NOT resolve.
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        os.environ.pop("VOLTHIUM_FALLBACK_ADAPTER", None)
        self.responses = {
            "bluetoothctl list": BLUEZ_LIST_INTERNAL_ONLY,
            "hciconfig": HCICONFIG_BOTH,
        }
        hci = _run_coro(self.mgr.resolve())
        self.assertIsNone(hci)
        ev = self.events()
        self.assertIn('"event": "adapter_pin_failed"', ev)
        self.assertIn("D-Bus adapter object missing", ev)

    def test_resolution_is_reverified_after_ttl(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        self.responses = {
            "bluetoothctl list": BLUEZ_LIST_BOTH,
            "hciconfig": HCICONFIG_BOTH,
        }
        _run_coro(self.mgr.resolve())
        n_calls = len(self.calls)
        # Within TTL: cached, no new subprocess calls.
        _run_coro(self.mgr.resolve())
        self.assertEqual(len(self.calls), n_calls)
        # Force TTL expiry: must re-probe.
        self.mgr.invalidate()
        _run_coro(self.mgr.resolve())
        self.assertGreater(len(self.calls), n_calls)


class FallbackTests(_FakeRunMixin):

    def _wire_primary_dead_fallback_alive(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        os.environ["VOLTHIUM_FALLBACK_ADAPTER"] = INTERNAL_MAC
        self.responses = {
            "bluetoothctl list": BLUEZ_LIST_INTERNAL_ONLY,
            # hci1 status probe (fallback up-check) must match before the
            # generic "hciconfig" catch-all.
            "hciconfig hci1": (
                f"hci1:\tType: Primary  Bus: UART\n"
                f"\tBD Address: {INTERNAL_MAC}\n\tUP RUNNING\n"
            ),
            "hciconfig": HCICONFIG_BOTH,
        }

    def test_falls_back_when_primary_unusable(self):
        self._wire_primary_dead_fallback_alive()
        hci = _run_coro(self.mgr.resolve())
        self.assertEqual(hci, "hci1")
        self.assertTrue(self.mgr.active_is_fallback)
        ev = self.events()
        self.assertIn('"event": "adapter_pin_failed"', ev)
        self.assertIn('"event": "adapter_fallback_active"', ev)

    def test_fallback_powered_on_if_down(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        os.environ["VOLTHIUM_FALLBACK_ADAPTER"] = INTERNAL_MAC
        seen_up = {"done": False}
        orig_responses = {
            "bluetoothctl list": BLUEZ_LIST_INTERNAL_ONLY,
            "hciconfig": HCICONFIG_BOTH,
        }
        self.responses = orig_responses

        # hci1 reports DOWN until `hciconfig hci1 up` has been called.
        async def fake_run(cmd, *, timeout=8.0):
            key = " ".join(cmd)
            self.calls.append(key)
            if "hciconfig hci1 up" in key:
                seen_up["done"] = True
                return ""
            if key.endswith("hciconfig hci1"):
                state = "UP RUNNING" if seen_up["done"] else "DOWN"
                return (f"hci1:\tType: Primary\n\tBD Address: {INTERNAL_MAC}\n"
                        f"\t{state}\n")
            for pat, out in orig_responses.items():
                if pat in key:
                    return out
            return ""
        pack_mod._run = fake_run

        hci = _run_coro(self.mgr.resolve())
        self.assertEqual(hci, "hci1")
        self.assertTrue(seen_up["done"], "fallback must be powered on from DOWN")

    def test_switches_back_to_primary_and_powers_fallback_down(self):
        self._wire_primary_dead_fallback_alive()
        _run_coro(self.mgr.resolve())
        self.assertTrue(self.mgr.active_is_fallback)
        # Primary comes back (bluetoothd re-registered it after a replug).
        self.responses["bluetoothctl list"] = BLUEZ_LIST_BOTH
        self.mgr.invalidate()
        hci = _run_coro(self.mgr.resolve())
        self.assertEqual(hci, "hci2")
        self.assertFalse(self.mgr.active_is_fallback)
        ev = self.events()
        self.assertIn('"event": "adapter_restored"', ev)
        self.assertTrue(
            any("hciconfig hci1 down" in c for c in self.calls),
            "fallback must be returned to its steady-state DOWN",
        )


class ReplugTargetTests(unittest.TestCase):
    """sysfs discovery for the replug rung — pure-path logic, fake trees."""

    @staticmethod
    def _can_symlink(base: Path) -> bool:
        probe_src = base / "_probe_target"
        probe_src.mkdir()
        try:
            (base / "_probe_link").symlink_to(probe_src, target_is_directory=True)
            return True
        except OSError:
            return False

    def test_find_by_usb_id(self):
        with TemporaryDirectory() as d:
            base = Path(d)
            dev = base / "1-1.5"
            dev.mkdir()
            (dev / "idVendor").write_text("2357\n")
            (dev / "idProduct").write_text("0604\n")
            (dev / "authorized").write_text("1\n")
            other = base / "1-1.1"
            other.mkdir()
            (other / "idVendor").write_text("0424\n")
            (other / "idProduct").write_text("ec00\n")
            (other / "authorized").write_text("1\n")
            found = pack_mod._usb_device_dir_by_id("2357:0604", base=base)
            self.assertEqual(found, dev)

    def test_find_by_usb_id_absent(self):
        with TemporaryDirectory() as d:
            self.assertIsNone(
                pack_mod._usb_device_dir_by_id("2357:0604", base=Path(d))
            )

    def test_find_by_hci_follows_device_link(self):
        with TemporaryDirectory() as d:
            if not self._can_symlink(Path(d)):
                self.skipTest("symlinks unavailable (Windows without "
                              "developer mode) — runs on Linux CI")
            base = Path(d)
            # Fake USB device dir with an interface subdir, and a bluetooth
            # class dir whose `device` symlink points at the interface.
            # (Real interface dirs are named like `1-1.5:1.0`, but `:` is not
            # a legal filename character on Windows dev boxes — the lookup
            # logic never inspects the name, so any name works here.)
            usb_dev = base / "sys-usb" / "1-1.5"
            iface = usb_dev / "if0"
            iface.mkdir(parents=True)
            (usb_dev / "authorized").write_text("1\n")
            bt_class = base / "sys-bt"
            (bt_class / "hci2").mkdir(parents=True)
            (bt_class / "hci2" / "device").symlink_to(iface, target_is_directory=True)
            found = pack_mod._usb_device_dir_for_hci("hci2", base=bt_class)
            self.assertEqual(found, usb_dev)

    def test_find_by_hci_none_for_missing(self):
        with TemporaryDirectory() as d:
            self.assertIsNone(
                pack_mod._usb_device_dir_for_hci("hci9", base=Path(d))
            )


class MaybeRepairPrimaryTests(_FakeRunMixin):

    def test_noop_when_not_on_fallback(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        self.assertIsNone(_run_coro(self.mgr.maybe_repair_primary()))

    def test_rate_limited(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        self.mgr.active_is_fallback = True
        self.mgr._last_replug_at = pack_mod.time.monotonic()  # just attempted
        self.assertIsNone(_run_coro(self.mgr.maybe_repair_primary()))

    def test_skips_replug_when_primary_recovered_on_its_own(self):
        os.environ["VOLTHIUM_ADAPTER"] = UB500_MAC
        self.responses = {
            "bluetoothctl list": BLUEZ_LIST_BOTH,
            "hciconfig": HCICONFIG_BOTH,
        }
        self.mgr.active_is_fallback = True
        self.mgr._verified_at = pack_mod.time.monotonic()  # cache says fallback
        result = _run_coro(self.mgr.maybe_repair_primary())
        self.assertIsNone(result, "healthy primary → no replug, just invalidate")
        self.assertIsNone(self.mgr._verified_at,
                          "cache must be invalidated so resolve() switches back")


if __name__ == "__main__":
    unittest.main()
