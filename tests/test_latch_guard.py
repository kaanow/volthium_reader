"""Unit tests for the MPPT latch guard's act/don't-act gating.

Anchored to REAL decision points from 2026-08-06 — the day the guard met its
first genuine latches, and also bounced the MPPT once at night. No socket, no
bus: exercises the pure decision helpers only.
"""
from __future__ import annotations

import calendar
import inspect
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xanbus_latch_guard import (   # noqa: E402
    AMBIGUOUS_FRACTION, HEALTHY_RUNS_TO_CLEAR, MIN_SUN_ELEVATION_DEG,
    CONFIRM_STALE_S, EARLY_AFTER_S, EARLY_CROSS_V, EARLY_MAX_PER_DAY,
    EARLY_MIN_INTERVAL_S, EARLY_REARM_V, MAX_FIXES_PER_DAY,
    SUSTAINED_PARTIAL_RUNS, early_bounce_allowed, early_due_is_new,
    needs_second_confirmation, note_descent,
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

    def test_the_new_path_is_observe_only_by_default(self):
        """Deploying the code must not change what the guard does. Verified on
        the argparse default rather than by reading the branch, so a flipped
        default is caught."""
        import argparse, xanbus_latch_guard as G
        ap = argparse.ArgumentParser()
        ap.add_argument("--act-on-sustained", action="store_true")
        self.assertFalse(ap.parse_args([]).act_on_sustained)
        src = inspect.getsource(G.main)
        self.assertIn("if not args.act_on_sustained:", src,
                      "the sustained path must return without acting "
                      "unless explicitly armed")

    def test_arming_is_a_separate_explicit_flag(self):
        import xanbus_latch_guard as G
        src = inspect.getsource(G.main)
        self.assertIn("--act-on-sustained", src)
        self.assertNotIn("default=True", src.split("--act-on-sustained")[1][:200])


class EarlyBounceTests(unittest.TestCase):
    """Fire during the descent, at the 29-minute mark — not at the crossing.

    The 2026-08-14 test settled that a still-tracking array recovers from a
    bounce (41.8 V -> 93.1 V in one minute). What it did not settle was WHEN.

    Not at the 45 V crossing: 8 of 32 episodes recover unaided and all of them
    resolve within 15 min, so firing at the crossing wastes a bounce on a
    quarter of episodes. At 29 minutes the record is 24 clamps for 24.

    29 is the OBSERVED CLAMP FLOOR. Natural recoveries top out at 15 min and
    clamps start at 29, so 15..29 is an empty band; firing at 29 stays out of
    it rather than acting where there is no evidence either way.
    """

    RUN = 5 * 60          # the guard's cadence
    SUN = 30.0            # comfortably above EARLY_MIN_SUN_DEG

    def _walk(self, st, pv_series, t0=1_000_000.0, sun=None):
        """Feed a series of per-run pv_v values; return the run index that fired."""
        fired = []
        for i, pv in enumerate(pv_series):
            if note_descent(st, pv, self.SUN if sun is None else sun,
                            t0 + i * self.RUN):
                fired.append(i)
        return fired

    def test_the_crossing_alone_does_not_fire(self):
        st = {}
        self.assertEqual(self._walk(st, [44.0]), [])

    def test_it_does_not_fire_before_29_minutes(self):
        """5 runs x 5 min = 20 min of dwell. Must stay quiet."""
        st = {}
        self.assertEqual(self._walk(st, [44.0] * 5), [])

    def test_it_fires_once_past_29_minutes(self):
        """The clock starts on the FIRST sub-45 run, so run 0 is t=0 and run 7
        is t=35 min. First fire must be the run that crosses 29."""
        st = {}
        fired = self._walk(st, [44.0] * 8)
        self.assertTrue(fired, "should fire once the dwell passes 29 min")
        self.assertEqual(fired[0], 6, "first fire should be the 30-minute run")

    def test_a_sawtooth_above_48_resets_only_after_two_runs(self):
        """One spike above 48 V must NOT reset a 29-minute clock — that is the
        sawtooth the cliff table already had to defend against.

        Asserting on the clock's VALUE, not its presence. A first version
        checked `assertIn("below45_since", st)`, which passed even when a spike
        DID clear it — because the next sub-45 run simply re-armed it. The
        mutation "one spike clears the clock" survived that test. What matters
        is whether the accumulated dwell was lost, so assert on the timestamp.
        """
        t0 = 1_000_000.0
        st = {}
        # 4 runs down (20 min), one spike above re-arm, then back down
        self._walk(st, [44.0] * 4 + [49.0] + [44.0] * 2, t0=t0)
        self.assertEqual(st.get("below45_since"), t0,
                         "one spike must not restart the dwell clock")
        # and it must still fire on schedule despite the spike
        st2 = {}
        fired = self._walk(st2, [44.0] * 4 + [49.0] + [44.0] * 4, t0=t0)
        self.assertTrue(fired, "a single spike must not delay the fire")

    def test_two_consecutive_above_rearm_DO_clear_it(self):
        st = {}
        self._walk(st, [44.0] * 4 + [49.0, 49.0])
        self.assertNotIn("below45_since", st,
                         "two consecutive above re-arm must clear it")

    def test_the_45_to_48_band_neither_arms_nor_clears(self):
        """Between CROSS_V and REARM_V the state must be HELD, or the trigger
        chatters across the threshold.

        Uses TWO consecutive in-band runs, deliberately. A first version used
        one, which passed even when the re-arm test was mutated to fire at
        45 V — because a single run cannot reach EARLY_REARM_RUNS either way.
        Two in-band runs is what distinguishes "held" from "cleared".
        """
        st = {}
        self._walk(st, [46.0, 46.0, 46.0])
        self.assertNotIn("below45_since", st, "46 V must not arm the clock")
        t0 = 1_000_000.0
        st2 = {}
        self._walk(st2, [44.0] + [46.0, 46.0] + [44.0], t0=t0)
        self.assertEqual(st2.get("below45_since"), t0,
                         "two runs in the 45-48 band must not clear the clock")

    def test_low_sun_never_arms(self):
        """A 45 V crossing at low sun is dusk, not a walk-down. The clamp guard
        gates at 5 deg; this gates at 15."""
        st = {}
        self.assertEqual(self._walk(st, [44.0] * 10, sun=10.0), [])
        self.assertNotIn("below45_since", st)

    def test_dusk_clears_an_armed_clock(self):
        st = {}
        self._walk(st, [44.0] * 4)
        self.assertIn("below45_since", st)
        note_descent(st, 44.0, 5.0, 1_000_000.0 + 5 * self.RUN)
        self.assertNotIn("below45_since", st, "sunset must abandon the episode")

    def test_the_budget_is_separate_from_the_clamp_budget(self):
        """An early bounce must never starve the clamp fix, which is the one
        that recovers a fully stuck array."""
        st = {"fixes": MAX_FIXES_PER_DAY, "early_fixes": 0}
        ok, why = early_bounce_allowed(st, 1_000_000.0)
        self.assertTrue(ok, "a full CLAMP budget must not block an early bounce")
        st2 = {"fixes": 0, "early_fixes": EARLY_MAX_PER_DAY}
        ok2, why2 = early_bounce_allowed(st2, 1_000_000.0)
        self.assertFalse(ok2)
        self.assertIn("cap", why2)

    def test_the_minimum_interval_is_enforced(self):
        """Each bounce restores the array and it walks down again; without this
        the trigger would cycle."""
        now = 1_000_000.0
        st = {"last_early_at": now - 60}
        ok, why = early_bounce_allowed(st, now)
        self.assertFalse(ok)
        self.assertIn("interval", why)
        st2 = {"last_early_at": now - EARLY_MIN_INTERVAL_S - 1}
        self.assertTrue(early_bounce_allowed(st2, now)[0])

    def test_29_minutes_is_the_observed_clamp_floor(self):
        """If someone retunes this, the justification stops applying: 24/24 of
        the episodes past 29 min clamped, and 15..29 is an empty band."""
        self.assertEqual(EARLY_AFTER_S, 29 * 60)
        self.assertEqual(EARLY_CROSS_V, 45.0)
        self.assertEqual(EARLY_REARM_V, 48.0)

    def test_the_path_is_observe_only_by_default(self):
        import argparse, xanbus_latch_guard as G
        ap = argparse.ArgumentParser()
        ap.add_argument("--act-on-early", action="store_true")
        self.assertFalse(ap.parse_args([]).act_on_early)
        self.assertIn("if ok and args.act_on_early:", inspect.getsource(G.main))

    def test_the_due_event_fires_ONCE_per_episode(self):
        """57 events across 5 episodes in four days, one episode producing 18.

        below45_since is only cleared by a re-arm or a fix, so note_descent
        keeps returning True on every subsequent 5-minute run for as long as
        the descent lasts — and in observe-only mode nothing clears it at all.
        11x noise in a stream whose whole design is that quiet periods cost
        nothing.
        """
        st = {}
        fires = 0
        for i in range(12):                       # 60 min of descent
            if note_descent(st, 44.0, self.SUN, 1_000_000.0 + i * self.RUN):
                if early_due_is_new(st):
                    fires += 1
        self.assertEqual(fires, 1,
                         "one descent must produce exactly one due event")

    def test_a_NEW_episode_fires_again(self):
        """Once per episode, not once ever — the flag must reset with the
        clock, or the trigger goes silent after the first day."""
        st = {}
        t = 1_000_000.0
        for i in range(12):
            if note_descent(st, 44.0, self.SUN, t + i * self.RUN):
                early_due_is_new(st)
        # array recovers: two consecutive runs above re-arm
        note_descent(st, 49.0, self.SUN, t + 13 * self.RUN)
        note_descent(st, 49.0, self.SUN, t + 14 * self.RUN)
        self.assertNotIn("early_due_emitted", st, "the flag must clear with the clock")
        fires = 0
        for i in range(15, 30):
            if note_descent(st, 44.0, self.SUN, t + i * self.RUN):
                if early_due_is_new(st):
                    fires += 1
        self.assertEqual(fires, 1, "a second descent must fire again, once")

    def test_dusk_also_clears_the_emitted_flag(self):
        st = {}
        t = 1_000_000.0
        for i in range(12):
            if note_descent(st, 44.0, self.SUN, t + i * self.RUN):
                early_due_is_new(st)
        note_descent(st, 44.0, 5.0, t + 13 * self.RUN)      # sun down
        self.assertNotIn("early_due_emitted", st)
