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
