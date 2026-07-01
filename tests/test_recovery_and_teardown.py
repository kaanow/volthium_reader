"""Tests for the two recent FM-3 / FM-8 hardening changes:

  - recover_adapter now verifies the adapter is UP after each recovery
    rung and calls hciconfig up + bluetoothctl power on if not.
  - _teardown now also calls bms._client.disconnect() directly with its own
    timeout, because aiobmsble's disconnect() silently swallows BleakError
    and can leave the underlying BleakClient in a partially-torn-down state
    that auto-reconnects the moment the external link drops.

Uses the same BLE dep stubs as tests/test_log_schema so the module can be
imported on any Python.
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


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class RecoverAdapterPowerOnTests(unittest.TestCase):
    """recover_adapter should verify the adapter is UP after each rung and
    call hciconfig up + bluetoothctl power on if not (the FM-3 addendum
    gap we hit live on 2026-07-01)."""

    def setUp(self):
        # Route _event to a temp file so tests don't pollute state.
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")

        # Patch _run to a controllable fake. Each test constructs its own
        # command→output mapping.
        self._orig_run = pack_mod._run
        self.calls: list[list[str]] = []
        self.responses: dict[str, str] = {}

        async def fake_run(cmd, *, timeout=8.0):
            self.calls.append(list(cmd))
            # Match on last two args (the leaf tool + its arg), or the whole cmd
            key = " ".join(cmd)
            for pat, out in self.responses.items():
                if pat in key:
                    return out
            return ""
        pack_mod._run = fake_run

    def tearDown(self):
        pack_mod._run = self._orig_run

    def test_level2_powers_on_if_down(self):
        # After `systemctl restart bluetooth`, hciconfig reports DOWN.
        self.responses = {
            "systemctl restart bluetooth": "",
            "hciconfig hci0": "hci0:\tType: Primary\n\tDOWN\n",
            "hciconfig hci0 up": "",
            "bluetoothctl power on": "Changing power on succeeded",
            "hciconfig": "hci0:...",   # for _default_adapter
        }
        # _default_adapter parses `hciconfig` output; give it a valid line
        self.responses["hciconfig"] = "hci0:\tType: Primary  Bus: UART"
        action = _run(pack_mod.recover_adapter(level=2))
        cmds = [" ".join(c) for c in self.calls]
        # Must have called systemctl restart AND then the two power-up steps
        self.assertTrue(any("systemctl restart bluetooth" in c for c in cmds))
        self.assertTrue(any("hciconfig hci0 up" in c for c in cmds))
        self.assertTrue(any("bluetoothctl power on" in c for c in cmds))
        self.assertIn("power on", action)

    def test_level2_skips_power_on_if_already_up(self):
        self.responses = {
            "systemctl restart bluetooth": "",
            "hciconfig hci0": "hci0:\tType: Primary\n\tUP RUNNING\n",
            "hciconfig": "hci0:\tType: Primary  Bus: UART",
        }
        action = _run(pack_mod.recover_adapter(level=2))
        cmds = [" ".join(c) for c in self.calls]
        self.assertTrue(any("systemctl restart bluetooth" in c for c in cmds))
        self.assertFalse(any("hciconfig hci0 up" in c for c in cmds))
        self.assertFalse(any("bluetoothctl power on" in c for c in cmds))
        self.assertNotIn("power on", action)


class TeardownInnerDisconnectTests(unittest.TestCase):
    """_teardown must also call bms._client.disconnect() directly, because
    aiobmsble's disconnect() swallows BleakError silently."""

    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        pack_mod._reset_writer_for_tests(Path(d.name) / "ev.jsonl")

        self._orig_run = pack_mod._run
        async def fake_run(cmd, *, timeout=8.0):
            # Return an empty `hcitool con` so _connected_targets is empty,
            # skipping the force-disconnect path — we only care about the
            # bms.disconnect + client.disconnect sequence here.
            return ""
        pack_mod._run = fake_run

    def tearDown(self):
        pack_mod._run = self._orig_run

    def test_calls_both_disconnects(self):
        called = {"bms": 0, "client": 0}

        class _FakeClient:
            async def disconnect(self):
                called["client"] += 1

        class _FakeBms:
            _client = _FakeClient()
            async def disconnect(self, reset: bool = False):
                called["bms"] += 1

        _run(pack_mod._teardown(_FakeBms(), "AA:BB:CC:DD:EE:FF"))
        self.assertEqual(called["bms"], 1)
        self.assertEqual(called["client"], 1,
                         "raw _client.disconnect() must also be called")

    def test_client_disconnect_called_even_if_bms_disconnect_raises(self):
        # This is the exact FM-8 scenario: aiobmsble's disconnect throws (or
        # would swallow silently) — we still need to clean up the client.
        called = {"bms": 0, "client": 0}

        class _FakeClient:
            async def disconnect(self):
                called["client"] += 1

        class _FakeBms:
            _client = _FakeClient()
            async def disconnect(self, reset: bool = False):
                called["bms"] += 1
                raise RuntimeError("simulated BleakError")

        _run(pack_mod._teardown(_FakeBms(), "AA:BB:CC:DD:EE:FF"))
        self.assertEqual(called["bms"], 1)
        self.assertEqual(called["client"], 1,
                         "client disconnect MUST run even after bms.disconnect() fails")

    def test_teardown_never_raises(self):
        # Both disconnects blowing up must not propagate.
        class _FakeClient:
            async def disconnect(self):
                raise RuntimeError("client blew up")

        class _FakeBms:
            _client = _FakeClient()
            async def disconnect(self, reset: bool = False):
                raise RuntimeError("bms blew up")

        # Simply not raising is the assertion here.
        _run(pack_mod._teardown(_FakeBms(), "AA:BB:CC:DD:EE:FF"))


if __name__ == "__main__":
    unittest.main()
