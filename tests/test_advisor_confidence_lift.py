"""Tests for `scripts.generator_advisor.lift_confidence_by_accuracy`.

Pinned-down behaviour: the advisor's confidence tier gets lifted one
notch when the recent track record of validated projections is tight
(mean |error| < threshold) and there are enough records to be
meaningful. This rule is the bridge between the
projection_accuracy validation history and the headline confidence
the user sees on the dashboard — regressions here would silently
over- or under-promise.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from generator_advisor import (  # noqa: E402
    ACCURACY_LIFT_MIN_RECORDS,
    ACCURACY_LIFT_THRESHOLD_PP,
    MODEL_DRIFT_ADVISORY_THRESHOLD_PCT,
    compute_model_drift,
    lift_confidence_by_accuracy,
)


class TestLiftConfidenceByAccuracy(unittest.TestCase):

    def test_low_to_medium_when_recent_track_record_is_tight(self) -> None:
        """The realistic case after the first sunrise: 10 records, mean
        |error| ~1 pp → should lift `low` to `medium`."""
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=1.15,
            recent_n=10,
        )
        self.assertEqual(out, "medium")
        self.assertTrue(lifted)

    def test_medium_to_high_for_strong_track_record(self) -> None:
        """A second accumulated week of tight projections should lift
        `medium` to `high`."""
        out, lifted = lift_confidence_by_accuracy(
            base="medium",
            recent_abs_error_pp=0.5,
            recent_n=20,
        )
        self.assertEqual(out, "high")
        self.assertTrue(lifted)

    def test_high_is_not_lifted_further(self) -> None:
        """No tier above `high` — return unchanged with lifted=False."""
        out, lifted = lift_confidence_by_accuracy(
            base="high",
            recent_abs_error_pp=0.5,
            recent_n=50,
        )
        self.assertEqual(out, "high")
        self.assertFalse(lifted)

    def test_no_lift_when_too_few_records(self) -> None:
        """Below `ACCURACY_LIFT_MIN_RECORDS` we shouldn't lift even if
        the few we have look perfect — single-day-of-data could be
        misleading."""
        # 4 records < the default MIN of 5
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=0.1,
            recent_n=4,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

    def test_no_lift_when_error_at_or_above_threshold(self) -> None:
        """Just at the threshold should NOT lift (strict <)."""
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=ACCURACY_LIFT_THRESHOLD_PP,    # exactly 2.0
            recent_n=10,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=2.5,
            recent_n=10,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

    def test_no_lift_when_no_records(self) -> None:
        """Empty track record → no lift; advisor falls back to base."""
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=None,
            recent_n=0,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

    def test_unrecognized_base_passes_through(self) -> None:
        """If `solar.confidence` ever returns an unexpected string,
        the lift logic must NOT crash — just leave it alone."""
        out, lifted = lift_confidence_by_accuracy(
            base="experimental",     # not in {"low","medium","high"}
            recent_abs_error_pp=0.1,
            recent_n=20,
        )
        self.assertEqual(out, "experimental")
        self.assertFalse(lifted)

    def test_threshold_and_min_records_overridable(self) -> None:
        """The thresholds are tunable knobs — verify the lift behaviour
        moves with them."""
        # Stricter threshold (0.5 pp) blocks a 1.0 pp track record
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=1.0,
            recent_n=10,
            threshold_pp=0.5,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

        # Higher min_records (50) blocks 10 records that would
        # otherwise lift
        out, lifted = lift_confidence_by_accuracy(
            base="low",
            recent_abs_error_pp=0.5,
            recent_n=10,
            min_records=50,
        )
        self.assertEqual(out, "low")
        self.assertFalse(lifted)

    def test_default_min_records_constant(self) -> None:
        """Anchor the documented default so a tweak shows up as a
        deliberate change, not a silent drift."""
        self.assertEqual(ACCURACY_LIFT_MIN_RECORDS, 5)
        self.assertEqual(ACCURACY_LIFT_THRESHOLD_PP, 2.0)


class TestComputeModelDrift(unittest.TestCase):
    """Pin down the live-vs-model drift advisory. The advisor calls
    compute_model_drift() on each invocation; only meaningful drift
    (|pct| >= threshold) produces an advisory string. Below threshold
    we still return the numeric drift_pct so the dashboard can chart
    the diagnostic value, just without firing an alert."""

    def test_returns_none_when_live_ratio_missing(self) -> None:
        """Early-morning days with no usable live_ratio → (None, None).
        The advisor will suppress the advisory chip entirely."""
        drift, advisory = compute_model_drift(
            live_ratio=None, coefficient=8.0,
        )
        self.assertIsNone(drift)
        self.assertIsNone(advisory)

    def test_returns_none_when_coefficient_zero(self) -> None:
        """Defensive: divide-by-zero must NOT crash the advisor."""
        drift, advisory = compute_model_drift(
            live_ratio=7.0, coefficient=0.0,
        )
        self.assertIsNone(drift)
        self.assertIsNone(advisory)

    def test_small_drift_returns_pct_but_no_advisory(self) -> None:
        """Today's live behavior: ratio 7.21, model 8.15 → drift ~-11.5
        pp, well below the 20% threshold. Drift is tracked (visible on
        the dashboard) but no advisory fires."""
        drift, advisory = compute_model_drift(
            live_ratio=7.21, coefficient=8.149,
        )
        self.assertAlmostEqual(drift, -11.5, delta=0.1)
        self.assertIsNone(advisory)

    def test_large_negative_drift_fires_advisory(self) -> None:
        """An extreme-cloud day measuring 4.0 with a model of 8.0
        produces -50 % drift — well past the 20 % advisory threshold.
        The advisory should mention both numbers and the direction."""
        drift, advisory = compute_model_drift(
            live_ratio=4.0, coefficient=8.0,
        )
        self.assertAlmostEqual(drift, -50.0, delta=0.1)
        self.assertIsNotNone(advisory)
        self.assertIn("4.00", advisory)
        self.assertIn("8.00", advisory)
        self.assertIn("below", advisory)

    def test_large_positive_drift_fires_advisory(self) -> None:
        """Symmetric: a strong clear-sky day might land 10.0 against a
        model of 7.5 → +33 % drift. Advisory should say 'above'."""
        drift, advisory = compute_model_drift(
            live_ratio=10.0, coefficient=7.5,
        )
        self.assertAlmostEqual(drift, 33.3, delta=0.2)
        self.assertIsNotNone(advisory)
        self.assertIn("above", advisory)

    def test_threshold_is_strict_greater_or_equal(self) -> None:
        """Exactly 20 % drift should fire (>=). Just under 20 % must not.
        Anchors the boundary so a tweak to the constant shows up as a
        deliberate change."""
        # At 8.0 coefficient, ratio of 6.4 = -20 % drift exactly
        drift, advisory = compute_model_drift(
            live_ratio=6.4, coefficient=8.0,
        )
        self.assertAlmostEqual(drift, -20.0, delta=0.1)
        self.assertIsNotNone(advisory,
                             "exactly 20 % should fire (>=, not >)")

        # 6.5 → -18.75 %, just under threshold → no advisory
        drift2, advisory2 = compute_model_drift(
            live_ratio=6.5, coefficient=8.0,
        )
        self.assertAlmostEqual(drift2, -18.75, delta=0.1)
        self.assertIsNone(advisory2)

    def test_default_threshold_constant(self) -> None:
        """Anchor the default so a tweak shows up as a deliberate
        change."""
        self.assertEqual(MODEL_DRIFT_ADVISORY_THRESHOLD_PCT, 20.0)

    def test_overridable_threshold(self) -> None:
        """The threshold can be tightened per-call (e.g. for testing
        or sensitive deployments)."""
        # At 10 % threshold, today's 11.5 % drift WOULD fire
        drift, advisory = compute_model_drift(
            live_ratio=7.21, coefficient=8.149,
            threshold_pct=10.0,
        )
        self.assertIsNotNone(advisory)


if __name__ == "__main__":
    unittest.main()
