"""deploy/pi/install.sh must install every unit the Pi actually runs.

install.sh is the documented deterministic recovery step — the thing you run
to rebuild the box. Until 2026-08-15 it did not install
volthium-config-watch.{service,timer} or volthium-dashboard.service, and
volthium-weekly-reboot.{service,timer} were not versioned in the repo AT ALL.
Rebuilding from it produced a Pi missing the charge-setpoint safety watch, the
local dashboard, and the reboot timer — silently, while RUNBOOK claimed the
script installs everything.

This compares the script against the versioned unit files rather than against
a hand-written list, so a unit added to deploy/pi/systemd/ is in scope the
moment it lands.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy" / "pi" / "systemd"
INSTALL = ROOT / "deploy" / "pi" / "install.sh"

# The BLE logger is retired: present as a dormant fallback, deliberately NOT
# enabled (Conflicts= with the RS485 logger). Installed but never enabled.
RETIRED = {"volthium-logger.service"}


def _enable_args() -> set[str]:
    """Just the arguments of the `systemctl enable` command.

    Splitting on a blank line was too greedy: it swallowed the following
    `systemctl disable volthium-logger` line, so the retired-logger assertion
    saw the name and failed on correct input. Take the command's continued
    lines only.
    """
    lines = INSTALL.read_text().splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith("systemctl enable"))
    args: list[str] = []
    while i < len(lines):
        args += lines[i].replace("systemctl enable", "").rstrip("\\").split()
        if not lines[i].rstrip().endswith("\\"):
            break
        i += 1
    return set(args)


def _units() -> set[str]:
    return {p.name for p in SYSTEMD.iterdir()
            if p.suffix in (".service", ".timer")}


def _installed() -> set[str]:
    return set(re.findall(r"systemd/(volthium-[\w.-]+\.(?:service|timer))",
                          INSTALL.read_text()))


class InstallCompletenessTests(unittest.TestCase):

    def test_the_scan_finds_something(self):
        """Otherwise every assertion below passes vacuously."""
        self.assertGreaterEqual(len(_units()), 10)
        self.assertGreaterEqual(len(_installed()), 10)

    def test_every_versioned_unit_is_installed(self):
        missing = sorted(_units() - _installed())
        self.assertEqual(missing, [],
                         f"units in deploy/pi/systemd/ that install.sh never "
                         f"copies: {missing}")

    def test_every_non_retired_unit_is_enabled_or_is_a_service_of_a_timer(self):
        """A unit that is installed but never enabled does not survive a
        power-cycle, which is the scenario this script exists for."""
        enabled = _enable_args()
        unenabled = []
        for u in sorted(_units() - RETIRED):
            stem = u.rsplit(".", 1)[0]
            # A .service driven by a .timer is started BY the timer, so only
            # the timer needs enabling.
            if u.endswith(".service") and f"{stem}.timer" in _units():
                continue
            if stem not in enabled and u not in enabled:
                unenabled.append(u)
        self.assertEqual(unenabled, [],
                         f"installed but never enabled: {unenabled}")

    def test_the_retired_logger_is_installed_but_NOT_enabled(self):
        """It Conflicts= with the RS485 logger; auto-starting it would fight
        the primary telemetry path."""
        self.assertIn("volthium-logger.service", _installed())
        self.assertNotIn("volthium-logger", _enable_args())
        self.assertIn("systemctl disable volthium-logger", INSTALL.read_text())


if __name__ == "__main__":
    unittest.main()


class GuardArmingSurvivesInstallTests(unittest.TestCase):
    """install.sh must not silently DISARM the latch guard.

    Found by the 2026-10-04 full-stack review. The Pi had been running
    `--act-on-sustained --act-on-early` since those triggers were validated;
    the unit file in this repo carried NEITHER. install.sh installs this file
    verbatim and is documented as the deterministic recovery step after a
    reboot or power-cycle — so running it would have replaced an armed unit
    with an unarmed one.

    Nothing would have caught it. The timer still reports active, the guard
    still runs and still emits detection events, and the only symptom is the
    absence of `early_bounce_result` — which nothing monitors. The guard would
    have looked alive while guarding nothing, through a winter.

    DERIVED from the guard's own argparse, so a renamed or added action flag
    fails here instead of going quietly missing from the unit.
    """

    UNIT = (Path(__file__).resolve().parents[1]
            / "deploy" / "pi" / "systemd" / "volthium-latch-guard.service")
    GUARD = (Path(__file__).resolve().parents[1]
             / "scripts" / "xanbus_latch_guard.py")

    def _exec_start(self) -> str:
        for line in self.UNIT.read_text().splitlines():
            if line.startswith("ExecStart="):
                return line
        self.fail("no ExecStart in the latch-guard unit")

    def _act_flags(self) -> list[str]:
        """Every `--act-on-*` flag the guard defines."""
        return sorted(set(re.findall(r'"(--act-on-[a-z-]+)"',
                                     self.GUARD.read_text())))

    def test_the_scan_finds_the_flags(self):
        """Otherwise the assertion below passes vacuously."""
        flags = self._act_flags()
        self.assertGreaterEqual(len(flags), 2, f"found only {flags}")

    def test_every_act_flag_the_guard_defines_is_in_the_unit(self):
        exec_start = self._exec_start()
        for flag in self._act_flags():
            with self.subTest(flag=flag):
                self.assertIn(
                    flag, exec_start,
                    f"{flag} is missing from ExecStart, so install.sh would "
                    f"deploy a guard that detects and never acts")

    def test_the_guard_actually_gates_action_on_those_flags(self):
        """Confirms the flags are not decorative — if the guard stopped
        reading them, this test would be asserting about nothing."""
        src = self.GUARD.read_text()
        for flag in self._act_flags():
            attr = flag[2:].replace("-", "_")
            with self.subTest(flag=flag):
                self.assertRegex(
                    src, rf"\ba\.{attr}\b|\bargs\.{attr}\b",
                    f"{flag} is declared but never read")
