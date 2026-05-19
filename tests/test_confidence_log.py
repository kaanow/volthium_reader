"""Tests for `scripts.confidence_log`.

The advisor calls `record_if_changed(base, resolved, lifted, ...)` on
every invocation. Only meaningful TRANSITIONS get appended — stable
states are deduped so the log stays a timeline of events. This file
pins down that behaviour and the round-trip read/write contract.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import confidence_log as conf_mod  # noqa: E402


class TestConfidenceLog(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "confidence_log.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_log_reads_as_empty_list(self) -> None:
        """A missing file must NOT crash callers — must return []."""
        self.assertEqual(conf_mod.read_log(self.path), [])
        self.assertIsNone(conf_mod.last_entry(self.path))

    def test_first_invocation_always_writes_a_row(self) -> None:
        """Empty log → any invocation produces the seed row."""
        wrote = conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=0.89, recent_n=10,
            path=self.path,
            now=datetime(2026, 5, 19, 6, 41, 35),
        )
        self.assertTrue(wrote)
        entries = conf_mod.read_log(self.path)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.ts, "2026-05-19T06:41:35")
        self.assertEqual(e.base, "low")
        self.assertEqual(e.resolved, "medium")
        self.assertTrue(e.lifted)
        self.assertAlmostEqual(e.recent_abs_error_pp, 0.89, places=4)
        self.assertEqual(e.recent_n, 10)

    def test_second_identical_invocation_is_noop(self) -> None:
        """Calling again with the same (base, resolved, lifted) tuple
        should NOT write a duplicate row, even if recent_abs_error_pp
        moves a little. We dedupe on tier-transitions only."""
        for _ in range(3):
            conf_mod.record_if_changed(
                base="low", resolved="medium", lifted=True,
                recent_abs_error_pp=0.89, recent_n=10,
                path=self.path,
            )
        # Drift in recent_abs_error_pp shouldn't write either —
        # the lift state is still the same.
        wrote = conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=1.12, recent_n=12,    # changed
            path=self.path,
        )
        self.assertFalse(wrote)
        self.assertEqual(len(conf_mod.read_log(self.path)), 1)

    def test_lift_falls_away_writes_a_new_row(self) -> None:
        """Transition from lifted=True to lifted=False (track record
        drifted above threshold) MUST be captured. This is the event
        a user wants to know about."""
        conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=0.89, recent_n=10,
            path=self.path,
        )
        wrote = conf_mod.record_if_changed(
            base="low", resolved="low", lifted=False,
            recent_abs_error_pp=2.5, recent_n=11,
            path=self.path,
        )
        self.assertTrue(wrote)
        entries = conf_mod.read_log(self.path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1].resolved, "low")
        self.assertFalse(entries[-1].lifted)

    def test_base_change_writes_a_new_row(self) -> None:
        """SolarModel confidence shifting from low → medium (more
        days fit) MUST be captured even if resolved tier happens to
        equal the lifted value."""
        conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=0.5, recent_n=15,
            path=self.path,
        )
        wrote = conf_mod.record_if_changed(
            base="medium", resolved="medium", lifted=False,    # natural medium
            recent_abs_error_pp=0.5, recent_n=15,
            path=self.path,
        )
        self.assertTrue(wrote)
        entries = conf_mod.read_log(self.path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[-1].base, "medium")
        self.assertFalse(entries[-1].lifted)

    def test_resolved_change_writes_a_new_row(self) -> None:
        """Resolved tier moving (e.g. medium → high) is an event."""
        conf_mod.record_if_changed(
            base="medium", resolved="medium", lifted=False,
            recent_abs_error_pp=0.5, recent_n=15,
            path=self.path,
        )
        wrote = conf_mod.record_if_changed(
            base="medium", resolved="high", lifted=True,
            recent_abs_error_pp=0.5, recent_n=20,
            path=self.path,
        )
        self.assertTrue(wrote)
        self.assertEqual(len(conf_mod.read_log(self.path)), 2)

    def test_csv_round_trip_preserves_fields(self) -> None:
        """Write three transitions, read them back, verify all
        fields survive the CSV round-trip including the optional
        None recent_abs_error_pp."""
        # Seed with no track record (None abs error)
        conf_mod.record_if_changed(
            base="low", resolved="low", lifted=False,
            recent_abs_error_pp=None, recent_n=0,
            source="advisor-invocation",
            path=self.path,
            now=datetime(2026, 5, 18, 12, 0, 0),
        )
        # First lift event
        conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=1.15, recent_n=17,
            source="advisor-invocation",
            path=self.path,
            now=datetime(2026, 5, 19, 5, 32, 0),
        )
        # Lift falls away
        conf_mod.record_if_changed(
            base="low", resolved="low", lifted=False,
            recent_abs_error_pp=2.5, recent_n=18,
            source="advisor-invocation",
            path=self.path,
            now=datetime(2026, 5, 19, 7, 0, 0),
        )

        entries = conf_mod.read_log(self.path)
        self.assertEqual(len(entries), 3)
        self.assertIsNone(entries[0].recent_abs_error_pp)
        self.assertEqual(entries[0].recent_n, 0)
        self.assertAlmostEqual(entries[1].recent_abs_error_pp, 1.15, places=4)
        self.assertEqual(entries[1].recent_n, 17)
        self.assertFalse(entries[2].lifted)
        self.assertEqual(entries[2].source, "advisor-invocation")

    def test_csv_has_header_when_first_written(self) -> None:
        """Header row must be present so other tools can read the
        CSV without prior knowledge of column order."""
        conf_mod.record_if_changed(
            base="low", resolved="medium", lifted=True,
            recent_abs_error_pp=0.89, recent_n=10,
            path=self.path,
        )
        with self.path.open() as f:
            reader = csv.reader(f)
            header = next(reader)
        self.assertEqual(header, conf_mod.FIELDS)


if __name__ == "__main__":
    unittest.main()
