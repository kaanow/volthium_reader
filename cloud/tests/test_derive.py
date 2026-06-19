"""Tests for cloud.server.derive — must match volthium.estimator behavior.

The estimator and the server-side derivation are independent implementations
of the same math. They have to stay in sync; if you change one, change both.
This test confirms a sequence of readings produces the same smoothed/projected
fields through either path.
"""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# Stub the BLE deps so volthium.estimator can be imported on a Python that
# lacks aiobmsble (same trick as tests/test_log_schema.py).
def _stub() -> None:
    aiobmsble = types.ModuleType("aiobmsble")
    aiobmsble.BMSSample = dict   # type: ignore[attr-defined]
    sys.modules.setdefault("aiobmsble", aiobmsble)
    bms_pkg = types.ModuleType("aiobmsble.bms")
    sys.modules.setdefault("aiobmsble.bms", bms_pkg)
    ej = types.ModuleType("aiobmsble.bms.ej_bms")
    class _BMS:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
    ej.BMS = _BMS   # type: ignore[attr-defined]
    sys.modules.setdefault("aiobmsble.bms.ej_bms", ej)
    bleak = types.ModuleType("bleak")
    class _Scanner:
        @staticmethod
        async def find_device_by_address(*a, **kw): return None
    bleak.BleakScanner = _Scanner   # type: ignore[attr-defined]
    sys.modules.setdefault("bleak", bleak)
    backends = types.ModuleType("bleak.backends")
    sys.modules.setdefault("bleak.backends", backends)
    backends_dev = types.ModuleType("bleak.backends.device")
    class _BLEDevice: pass
    backends_dev.BLEDevice = _BLEDevice   # type: ignore[attr-defined]
    sys.modules.setdefault("bleak.backends.device", backends_dev)


_stub()

from cloud.server.derive import derive   # noqa: E402
from cloud.shared.wire import Reading    # noqa: E402
from volthium.estimator import Estimator # noqa: E402
from volthium.pack import BatteryReading, PackReading  # noqa: E402


def _batt(v: float, i: float, soc: float, name: str = "X") -> BatteryReading:
    return BatteryReading(
        address="addr", name=name, voltage=v, current=i, soc=soc,
        remaining_ah=None, temperature=None, cycles=None,
        cell_voltages=None, delta_voltage=None,
        charging_fet=None, discharging_fet=None, problem_code=None,
    )


def _reading(va, vb, ia, ib, sa, sb) -> Reading:
    return Reading(
        ts="2026-06-18T19:00:00Z",
        state="discharging",
        v_a=va, v_b=vb, i_a=ia, i_b=ib, soc_a=sa, soc_b=sb,
    )


SETTINGS = dict(
    alpha=0.15,
    capacity_ah=200.0,
    floor_soc=10.0,
    ceiling_soc=95.0,
    idle_current_a=0.5,
)


class DeriveMatchesEstimatorTests(unittest.TestCase):
    """Same input sequence through both implementations should yield
    matching smoothed_i / smoothed_p / minutes_remaining for every step."""

    def _run_pair(self, sequence):
        """sequence: list of (v_a, v_b, i_a, i_b, soc_a, soc_b)."""
        est = Estimator(
            capacity_ah=SETTINGS["capacity_ah"],
            floor_soc=SETTINGS["floor_soc"],
            ceiling_soc=SETTINGS["ceiling_soc"],
            idle_current_a=SETTINGS["idle_current_a"],
            alpha=SETTINGS["alpha"],
        )
        prev_i = prev_p = None
        for (va, vb, ia, ib, sa, sb) in sequence:
            pack = PackReading(_batt(va, ia, sa, "V-A"), _batt(vb, ib, sb, "V-B"))
            est_out = est.update(pack)

            r = _reading(va, vb, ia, ib, sa, sb)
            d = derive(r, prev_smoothed_i=prev_i, prev_smoothed_p=prev_p, **SETTINGS)

            self.assertAlmostEqual(est_out.smoothed_current, d.smoothed_i, places=5,
                                   msg=f"smoothed_i mismatch at step v_a={va}")
            self.assertAlmostEqual(est_out.smoothed_power, d.smoothed_p, places=4,
                                   msg=f"smoothed_p mismatch at step v_a={va}")
            if est_out.minutes_remaining is None:
                self.assertIsNone(d.minutes_remaining)
            else:
                self.assertAlmostEqual(est_out.minutes_remaining, d.minutes_remaining,
                                       places=2)
            prev_i, prev_p = d.smoothed_i, d.smoothed_p

    def test_discharging_seq(self):
        # All discharging, soc slowly dropping
        self._run_pair([
            (13.2, 13.2, -3.0, -3.0, 70, 68),
            (13.2, 13.2, -3.1, -2.9, 70, 68),
            (13.2, 13.2, -3.4, -3.2, 70, 68),
            (13.2, 13.2, -2.8, -2.7, 70, 68),
        ])

    def test_charging_seq(self):
        self._run_pair([
            (13.3, 13.3, 16.0, 16.0, 70, 68),
            (13.3, 13.3, 16.5, 16.0, 70, 68),
            (13.3, 13.3, 17.0, 17.5, 70, 68),
        ])

    def test_idle_band(self):
        # |smoothed_i| stays under idle_current_a → minutes_remaining None
        self._run_pair([
            (13.2, 13.2, 0.1, 0.0, 70, 68),
            (13.2, 13.2, 0.0, -0.2, 70, 68),
            (13.2, 13.2, 0.3, 0.1, 70, 68),
        ])


if __name__ == "__main__":
    unittest.main()
