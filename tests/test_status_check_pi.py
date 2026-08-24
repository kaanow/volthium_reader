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
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import status_check as S                 # noqa: E402
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


class ThrottleDecodeTests(unittest.TestCase):
    """The throttle word is graded, not compared to zero.

    `!= 0x0` treats a sticky historical bit exactly like a live fault, so one
    frequency cap twenty days ago flags every run until the next reboot — a
    permanent warning, which is a warning nobody reads. It also hid WHICH
    condition occurred, and the difference matters enormously: under-voltage
    means the supply is failing and an unattended Pi is at risk; a thermal cap
    in August means it was warm.

    Observed 2026-08-23: throttled=0x20000 — bit 17 alone, ARM frequency
    capping has occurred, no under-voltage, core 1.3375 V at 66.6 C.
    """

    # Tests the PURE grader, not section_pi. Going through section_pi, the one
    # canned fixture is returned to all three ssh probes, so the git and timer
    # checks report "cannot confirm" and set notable=True by themselves — and
    # every assertion here passed regardless of the throttle branch. A mutation
    # making a LIVE throttle non-notable survived the entire suite.
    def _lines(self, throttled: str):
        return S.grade_throttle(f"12:00:00 up 21 days\nthrottled={throttled}\n")

    def test_all_clear_is_quiet(self):
        notable, lines = self._lines("0x0")
        self.assertNotIn("THROTTLED NOW", " ".join(lines))

    def test_a_HISTORICAL_thermal_cap_is_reported_but_not_notable(self):
        """The live 2026-08-23 state. Must not nag until the next reboot."""
        notable, lines = self._lines("0x20000")
        text = " ".join(lines)
        self.assertIn("historical, not current", text)
        self.assertIn("ARM frequency capping occurred", text)
        self.assertNotIn("THROTTLED NOW", text)

    def test_a_LIVE_throttle_is_NOTABLE(self):
        notable, lines = self._lines("0x4")
        self.assertTrue(notable)
        self.assertIn("THROTTLED NOW", " ".join(lines))

    def test_LIVE_undervoltage_is_NOTABLE(self):
        notable, lines = self._lines("0x1")
        self.assertTrue(notable)
        self.assertIn("under-voltage", " ".join(lines))

    def test_HISTORICAL_undervoltage_is_NOTABLE_unlike_thermal(self):
        """The distinction that justifies grading at all: a supply that has
        sagged is the failure mode that takes an unattended box down, so it is
        worth flagging even after the fact. A thermal cap is not."""
        notable, lines = self._lines("0x10000")
        self.assertTrue(notable, "past under-voltage must still be flagged")
        self.assertIn("check the supply", " ".join(lines))

    def test_an_unreadable_register_is_NOTABLE(self):
        """Cannot-look must not read as all-clear."""
        notable, lines = S.grade_throttle("12:00:00 up 1 day\n")
        self.assertTrue(notable)
        self.assertIn("could not read the throttled register", " ".join(lines))

    def test_all_clear_is_genuinely_not_notable(self):
        """Only assertable now that the grader is pure — through section_pi
        this was always True for unrelated reasons."""
        notable, _ = self._lines("0x0")
        self.assertFalse(notable)

    def test_a_historical_thermal_cap_is_genuinely_not_notable(self):
        notable, _ = self._lines("0x20000")
        self.assertFalse(notable, "a sticky thermal bit must not nag forever")
