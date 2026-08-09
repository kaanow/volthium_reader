"""The Pi service check must notice a service that is down.

It did not, for months. `section_pi` hardcoded `volthium-logger` — the BLE
logger — and kept checking it after RS485 became the primary transport on
2026-07-26. That unit is disabled and dead, so its restart count and its error
count were both a permanent zero, and the check reported healthy. Meanwhile
`volthium-rs485-logger`, the process actually producing every reading, was
never looked at.

A hardcoded list cannot notice that it is describing a system that no longer
exists. So the rule is derived instead: UnitFileState=enabled implies
ActiveState=active. These tests pin that rule against real `systemctl show`
output, including the shapes that must NOT alarm.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from status_check import _parse_units   # noqa: E402


# Real output from kwpi 2026-08-09, flattened with '|' the way the probe does.
LIVE = (
    "Id=volthium-events-uploader.service|ActiveState=active|"
    "UnitFileState=enabled|NRestarts=0|"
    "Id=volthium-xanbus-telemetry.service|ActiveState=active|"
    "UnitFileState=enabled|NRestarts=0|"
    "Id=volthium-rs485-logger.service|ActiveState=active|"
    "UnitFileState=enabled|NRestarts=0|"
)


def _down(units):
    return [u["Id"] for u in units
            if u["UnitFileState"] == "enabled" and u["ActiveState"] != "active"]


class ParseUnitsTests(unittest.TestCase):

    def test_parses_real_systemctl_output(self):
        units = _parse_units(LIVE)
        self.assertEqual(len(units), 3)
        self.assertEqual(units[0]["Id"], "volthium-events-uploader.service")
        self.assertEqual(units[0]["ActiveState"], "active")
        self.assertEqual(_down(units), [])

    def test_the_rs485_logger_is_actually_in_scope(self):
        """The specific regression: the live logger must be one of the units
        the check looks at. It was invisible to the old hardcoded list."""
        ids = [u["Id"] for u in _parse_units(LIVE)]
        self.assertIn("volthium-rs485-logger.service", ids)

    def test_enabled_but_dead_service_is_flagged(self):
        bad = LIVE.replace(
            "Id=volthium-rs485-logger.service|ActiveState=active|",
            "Id=volthium-rs485-logger.service|ActiveState=failed|")
        self.assertEqual(_down(_parse_units(bad)),
                         ["volthium-rs485-logger.service"])

    def test_disabled_dead_unit_is_NOT_flagged(self):
        """volthium-logger is retired. Being dead is now correct, and a check
        that nags about it is a check people learn to ignore."""
        retired = LIVE + ("Id=volthium-logger.service|ActiveState=inactive|"
                          "UnitFileState=disabled|NRestarts=0|")
        units = _parse_units(retired)
        self.assertEqual(len(units), 4)
        self.assertEqual(_down(units), [])

    def test_timer_driven_service_is_NOT_flagged(self):
        """The latch guard runs from a timer every 5 min and is inactive in
        between. That is its healthy state, not an outage."""
        timed = LIVE + ("Id=volthium-latch-guard.service|ActiveState=inactive|"
                        "UnitFileState=static|NRestarts=0|")
        self.assertEqual(_down(_parse_units(timed)), [])

    def test_restart_counts_survive_parsing(self):
        churn = LIVE.replace(
            "Id=volthium-xanbus-telemetry.service|ActiveState=active|"
            "UnitFileState=enabled|NRestarts=0|",
            "Id=volthium-xanbus-telemetry.service|ActiveState=active|"
            "UnitFileState=enabled|NRestarts=14|")
        got = {u["Id"]: u["NRestarts"] for u in _parse_units(churn)}
        self.assertEqual(got["volthium-xanbus-telemetry.service"], "14")

    def test_garbage_input_yields_nothing_rather_than_a_false_all_clear(self):
        """An SSH hiccup must not read as 'zero services down'. section_pi
        treats an empty parse as notable for exactly this reason."""
        self.assertEqual(_parse_units("ssh: connect to host port 22: timeout"), [])

    def test_non_volthium_units_are_ignored(self):
        noise = LIVE + ("Id=ssh.service|ActiveState=active|"
                        "UnitFileState=enabled|NRestarts=0|")
        self.assertTrue(all(u["Id"].startswith("volthium-")
                            for u in _parse_units(noise)))


if __name__ == "__main__":
    unittest.main()
