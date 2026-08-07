"""Unit tests for the MPPT latch guard's act/don't-act gating.

Anchored to REAL decision points from 2026-08-06 — the day the guard met its
first genuine latches, and also bounced the MPPT once at night. No socket, no
bus: exercises the pure decision helpers only.
"""
from __future__ import annotations

import calendar
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xanbus_latch_guard import (   # noqa: E402
    MIN_SUN_ELEVATION_DEG, sun_elevation_deg,
)


def epoch(ts: str) -> float:
    return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))


class SunElevationGateTests(unittest.TestCase):
    """`pv_v > 20` is not a daylight test: a dark string floats most of Voc.
    Measured after sunset on 2026-08-06 — 70.4 V at 0.9 W, 78.3 V at 1.2 W —
    and the decay thrashes (29 -> 78 -> 54 -> 71 V) through the clamp band.
    That produced a real unwanted bounce at 21:01 local with the sun at
    -3.6 deg. Sun elevation is the physical quantity, and it separates every
    observed case by tens of degrees."""

    def _acts(self, ts: str) -> bool:
        return sun_elevation_deg(epoch(ts)) >= MIN_SUN_ELEVATION_DEG

    def test_genuine_latches_are_permitted(self):
        # The two real fixes: 10:58 and 17:00 local (PDT = UTC-7).
        self.assertTrue(self._acts("2026-08-06T17:58:04Z"))
        self.assertTrue(self._acts("2026-08-07T00:00:22Z"))

    def test_dawn_transient_is_blocked(self):
        self.assertFalse(self._acts("2026-08-06T12:36:20Z"))

    def test_dusk_transient_is_blocked(self):
        self.assertFalse(self._acts("2026-08-07T03:40:19Z"))

    def test_the_night_bounce_would_not_happen_again(self):
        """The actual regression: 21:01:34 local, fraction 1.0, daylight
        true, sun 3.6 deg BELOW the horizon — and it acted."""
        self.assertFalse(self._acts("2026-08-07T04:01:34Z"))

    def test_real_cases_keep_a_wide_margin(self):
        """The gate is not shaved to fit. Genuine latches sit far above it and
        transients far below, so ordinary error in the solar model or the
        clock cannot flip a decision."""
        real = [sun_elevation_deg(epoch(t)) for t in
                ("2026-08-06T17:58:04Z", "2026-08-07T00:00:22Z")]
        transient = [sun_elevation_deg(epoch(t)) for t in
                     ("2026-08-06T12:36:20Z", "2026-08-07T03:40:19Z",
                      "2026-08-07T04:01:34Z")]
        self.assertGreater(min(real) - MIN_SUN_ELEVATION_DEG, 20.0)
        self.assertLess(max(transient), 0.0)
        # ...and the gate must clear the worst transient by a real margin.
        self.assertGreater(MIN_SUN_ELEVATION_DEG - max(transient), 5.0)

    def test_gate_still_works_in_midwinter(self):
        """The threshold is set by winter, not by summer margins. At 51.12 N
        the sun peaks at ~15.4 deg on 21 Dec, so an over-tight gate would
        silently switch the guard off for most of a winter day — in the month
        when a latch costs proportionally most. Require a usable window
        around solar noon on the shortest day."""
        usable = sum(
            1 for m in range(0, 1440, 5)
            if sun_elevation_deg(epoch("2026-12-21T00:00:00Z") + m * 60)
            >= MIN_SUN_ELEVATION_DEG
        ) * 5 / 60
        self.assertGreater(usable, 5.0,
                           "gate leaves too little of the shortest day usable")

    def test_elevation_tracks_the_day(self):
        """Sanity: solar noon is high and near-midnight is well below."""
        noon = sun_elevation_deg(epoch("2026-08-06T20:15:00Z"))   # 13:15 PDT
        midnight = sun_elevation_deg(epoch("2026-08-07T09:00:00Z"))  # 02:00
        self.assertGreater(noon, 50.0)
        self.assertLess(midnight, -15.0)
        self.assertGreater(noon, midnight)


if __name__ == "__main__":
    unittest.main()
