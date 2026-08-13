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
    AMBIGUOUS_FRACTION, HEALTHY_RUNS_TO_CLEAR, MIN_SUN_ELEVATION_DEG,
    CONFIRM_STALE_S, SUSTAINED_PARTIAL_RUNS, needs_second_confirmation,
    note_clamped_run, note_healthy_run, note_partial_run, sun_elevation_deg,
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


class ConfirmationHysteresisTests(unittest.TestCase):
    """A pending confirmation must survive a brief wobble.

    Replays 2026-08-07 exactly. The array clamped at 09:40 and stayed clamped
    until the guard fixed it at 10:21. One run at 10:00 caught a 5.9 V delta —
    still 31 V making 20 W, nowhere near recovered — and under the old
    clear-on-one-healthy-run rule that wiped the confirmation, restarting the
    sequence and delaying the fix by 20 minutes at ~255 W (~85 Wh).
    """

    def test_single_wobble_does_not_clear_a_pending_confirmation(self):
        st = {"clamp_seen_at": 1000.0}
        note_healthy_run(st)                       # the 10:00 wobble
        self.assertIn("clamp_seen_at", st,
                      "one healthy run must not wipe the confirmation")

    def test_sustained_recovery_does_clear_it(self):
        """The grace must not become amnesia."""
        st = {"clamp_seen_at": 1000.0}
        for _ in range(HEALTHY_RUNS_TO_CLEAR):
            note_healthy_run(st)
        self.assertNotIn("clamp_seen_at", st)

    def test_a_clamped_run_resets_the_healthy_streak(self):
        """Wobble, clamp, wobble must NOT accumulate to a clear."""
        st = {"clamp_seen_at": 1000.0}
        note_healthy_run(st)
        note_clamped_run(st)
        note_healthy_run(st)
        self.assertIn("clamp_seen_at", st)
        self.assertEqual(st["healthy_runs"], 1)

    def test_todays_actual_sequence_would_now_act_20_min_sooner(self):
        """09:41 clamped, 09:51 clamped (armed), 10:01 wobble, 10:11 clamped.
        Under the fix the confirmation survives 10:01, so 10:11 is the second
        consecutive confirmation and the fix lands then instead of at 10:21."""
        st: dict = {}
        note_clamped_run(st); st["clamp_seen_at"] = 9.41      # 09:41 arms it
        note_clamped_run(st)                                   # 09:51 clamped
        self.assertIn("clamp_seen_at", st)
        note_healthy_run(st)                                   # 10:01 wobble
        self.assertIn("clamp_seen_at", st, "the wobble cost 20 min before")
        note_clamped_run(st)                                   # 10:11 clamped
        self.assertIn("clamp_seen_at", st)                     # -> would act

    def test_no_pending_confirmation_needs_no_write(self):
        """Healthy runs on a healthy day must not churn the state file."""
        st: dict = {}
        self.assertFalse(note_healthy_run(st))
        self.assertFalse(note_healthy_run(st))


if __name__ == "__main__":
    unittest.main()


class SustainedPartialClampTests(unittest.TestCase):
    """Act on a slow-onset clamp, not only on fraction >= CLAMP_FRACTION.

    2026-08-12: the fraction climbed 0.35 -> 1.0 over an HOUR while the array
    made 26 W against a capability, minutes later, of 479 W. CLAMP_FRACTION is
    right for rejecting a dawn/dusk transient and exactly wrong for a clamp
    that arrives gradually — a different failure that the binary threshold
    cannot see.

    The real 08-12 fractions are used as the fixture rather than invented ones,
    so this tests the case that motivated the rule.
    """

    REAL_0812 = [0.369, 0.358, 0.348, 0.652, 0.430, 0.453]

    def test_one_partial_run_does_not_act(self):
        st = {}
        self.assertFalse(note_partial_run(st, 0.35))

    def test_two_consecutive_do_not_act(self):
        st = {}
        note_partial_run(st, 0.35)
        self.assertFalse(note_partial_run(st, 0.36))

    def test_three_consecutive_DO_act(self):
        """The whole point."""
        st = {}
        note_partial_run(st, 0.35)
        note_partial_run(st, 0.36)
        self.assertTrue(note_partial_run(st, 0.35))

    def test_a_healthy_run_breaks_the_streak(self):
        """The array genuinely recovered, so the clock restarts. Without this
        the rule would fire on any three partials in a morning, however far
        apart, which is not a sustained clamp."""
        st = {}
        note_partial_run(st, 0.35)
        note_partial_run(st, 0.36)
        self.assertFalse(note_partial_run(st, 0.05))   # recovered
        self.assertNotIn("partial_runs", st)
        self.assertFalse(note_partial_run(st, 0.35))   # counting from 1 again

    def test_the_real_0812_sequence_fires_on_the_third_consecutive(self):
        st = {}
        fired = [note_partial_run(st, f) for f in self.REAL_0812]
        self.assertEqual(fired[:3], [False, False, True],
                         "should fire on the third consecutive partial run")

    def test_the_0812_gaps_would_NOT_have_fired_early(self):
        """On the day, 10:02 and 10:27 were 25 min apart and 10:27 -> 10:37 was
        10 min, so HEALTHY runs happened in between and the array had really
        recovered. Feeding those recoveries in must reset the streak, or the
        rule claims a saving it did not earn."""
        st = {}
        seq = [0.369, 0.0, 0.0, 0.0, 0.0,       # 10:02 then silent runs
               0.358, 0.0,                       # 10:27 then a silent run
               0.348, 0.652, 0.430]              # 10:37, 10:43, 10:48
        fired = [note_partial_run(st, f) for f in seq]
        self.assertEqual(fired.index(True), 9,
                         "should first fire at the 10:48 run, not earlier")

    def test_sustained_streak_survives_a_run_at_exactly_the_boundary(self):
        st = {}
        for _ in range(2):
            note_partial_run(st, AMBIGUOUS_FRACTION)
        self.assertTrue(note_partial_run(st, AMBIGUOUS_FRACTION))

    def test_threshold_constant_is_what_the_analysis_assumed(self):
        """The 127 Wh estimate and the n=0 false-positive check were both
        computed at three runs. If someone retunes this, those numbers stop
        applying and should be re-derived."""
        self.assertEqual(SUSTAINED_PARTIAL_RUNS, 3)
        self.assertEqual(AMBIGUOUS_FRACTION, 0.3)

    def test_sustained_streak_skips_the_second_confirmation(self):
        """The branch that makes the rule worth anything. Requiring the normal
        double-confirm on top of three consecutive partials would make it five
        runs and give back most of the 17 minutes. A mutation flipping this
        went undetected while it lived inline in main()."""
        self.assertFalse(needs_second_confirmation({}, 1_000_000.0, True))

    def test_a_normal_first_sighting_still_waits(self):
        self.assertTrue(needs_second_confirmation({}, 1_000_000.0, False))

    def test_a_fresh_pending_confirmation_lets_it_act(self):
        st = {"clamp_seen_at": 1_000_000.0}
        self.assertFalse(needs_second_confirmation(st, 1_000_300.0, False))

    def test_a_stale_pending_confirmation_restarts(self):
        st = {"clamp_seen_at": 1_000_000.0}
        self.assertTrue(
            needs_second_confirmation(st, 1_000_000.0 + CONFIRM_STALE_S + 1, False))
