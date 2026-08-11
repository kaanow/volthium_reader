"""Install the BLE dependency stubs ONCE, before any test module is imported.

`volthium/pack.py` imports `aiobmsble` and `bleak` unconditionally at module
level, and neither is installed in this environment (BLE was retired as a
transport on 2026-07-26; the packages went with it). Every test that touches
`volthium.pack` therefore has to fake them.

Three test files grew their own copy-pasted version of that fake, and the
copies DRIFTED:

    tests/test_event_log_rotation.py   _BMS has _notification_handler
    tests/test_log_schema.py           _BMS is a bare placeholder
    cloud/tests/test_derive.py         _BMS has no _notification_handler

Each copy also guards itself with `if "aiobmsble" in sys.modules: return` (or
`setdefault`), so only the FIRST one to import takes effect. Since `cloud/`
sorts before `tests/`, a full-suite run installed the copy WITHOUT
`_notification_handler`, and `_VolthiumBMSTapped._notification_handler`'s
`super()` call died with AttributeError. `tests/test_event_log_rotation.py`
passed on its own and failed in the suite — for months, as far as anyone can
tell, because the failure looked like flakiness rather than a missing method.

The guard is what made the drift fatal instead of harmless: it is designed to
prevent double-stubbing, so it actively PROTECTS whichever copy is wrong.

pytest imports the rootdir conftest before collecting any test module, so
installing the canonical stub here wins every one of those races. The local
copies still exist so the files can be run standalone with `python tests/...`;
they no-op under pytest. `tests/test_ble_stub_completeness.py` fails if any of
them drifts away from what `volthium.pack` actually reaches for.
"""
from __future__ import annotations

import sys
import types


def install_ble_stubs() -> None:
    """Fake out `aiobmsble` and `bleak` hard enough to import volthium.pack.

    Idempotent, but unlike the local copies this one OVERWRITES rather than
    setdefault()s, so a thinner stub installed earlier cannot win.
    """
    aiobmsble = types.ModuleType("aiobmsble")
    aiobmsble.BMSSample = dict          # type: ignore[attr-defined]
    sys.modules["aiobmsble"] = aiobmsble
    sys.modules["aiobmsble.bms"] = types.ModuleType("aiobmsble.bms")

    ej = types.ModuleType("aiobmsble.bms.ej_bms")

    class _BMS:
        """Base for volthium.pack._VolthiumBMSTapped.

        Every method the tap reaches through `super()` MUST exist here. See
        tests/test_ble_stub_completeness.py, which derives that list from the
        source rather than trusting this comment to stay current.
        """

        def __init__(self, *a, **kw): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def _notification_handler(self, *args, **kwargs):
            return None

    ej.BMS = _BMS                        # type: ignore[attr-defined]
    sys.modules["aiobmsble.bms.ej_bms"] = ej

    bleak = types.ModuleType("bleak")

    class _Scanner:
        @staticmethod
        async def find_device_by_address(*a, **kw):
            return None

    bleak.BleakScanner = _Scanner        # type: ignore[attr-defined]
    sys.modules["bleak"] = bleak
    sys.modules["bleak.backends"] = types.ModuleType("bleak.backends")

    backends_dev = types.ModuleType("bleak.backends.device")

    class _BLEDevice:
        pass

    backends_dev.BLEDevice = _BLEDevice  # type: ignore[attr-defined]
    sys.modules["bleak.backends.device"] = backends_dev


install_ble_stubs()
