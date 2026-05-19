"""Tests for `scripts.solar_onset`.

The advisor / loop runs `detect_and_record()` each iteration. The
detection function scans a day's pack.csv samples in chronological
order and records the earliest occurrence of each milestone in the
cascade: first_zero → first_idle → first_positive → first_net_positive.

Re-running on a fully-resolved day must be a no-op. Pre-onset days
must NOT write a row. Mid-cascade days (only first_zero seen so
far) must write a partial row that gets enriched on a later run.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import solar_onset as so_mod  # noqa: E402


def _write_pack(path: Path, rows: list[dict]) -> None:
    """Write a minimal pack.csv fixture. The detector reads
    ts, state, pack_v, pack_i, smoothed_i, soc_a, soc_b."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ts", "state", "pack_v", "pack_i", "smoothed_i", "soc_a", "soc_b"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def _row(ts: str, state: str = "discharging",
         pack_i: float = -3.0, smoothed_i: float = -3.0,
         pack_v: float = 26.20,
         soc_a: float = 70.0, soc_b: float = 68.0) -> dict:
    return {
        "ts": ts, "state": state,
        "pack_v": str(pack_v),
        "pack_i": str(pack_i), "smoothed_i": str(smoothed_i),
        "soc_a": str(soc_a), "soc_b": str(soc_b),
    }


class TestSolarOnsetDetection(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pack = self.root / "data" / "pack.csv"
        self.log = self.root / "data" / "solar_onset.csv"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ---------- detection ----------

    def test_pre_onset_day_yields_empty_record(self) -> None:
        """A whole morning of discharge — no current touches zero —
        must yield an is_empty() record."""
        _write_pack(self.pack, [
            _row("2026-05-19T03:00:00", pack_i=-3.0, smoothed_i=-2.8),
            _row("2026-05-19T04:00:00", pack_i=-2.5, smoothed_i=-2.6),
            _row("2026-05-19T05:00:00", pack_i=-2.2, smoothed_i=-2.4),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertTrue(rec.is_empty())

    def test_first_zero_captured_at_first_zero_crossing(self) -> None:
        """The earliest sample at pack_i >= 0 is first_zero_iso."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:00:00", pack_i=-2.0, smoothed_i=-2.5),
            _row("2026-05-19T06:44:10", pack_i=0.0, smoothed_i=-2.0),
            _row("2026-05-19T06:45:00", pack_i=-1.0, smoothed_i=-1.5),
            _row("2026-05-19T06:50:00", pack_i=0.0, smoothed_i=-0.8),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertEqual(rec.first_zero_iso, "2026-05-19T06:44:10")

    def test_first_idle_requires_zero_to_have_been_seen(self) -> None:
        """A transient gap in overnight load (|i| momentarily < 0.5
        before any zero-crossing) must NOT be mistaken for idle."""
        _write_pack(self.pack, [
            # Pre-dawn load lull: |i| brushes against the 0.5 A
            # threshold but no zero crossing yet.
            _row("2026-05-19T03:00:00", state="discharging",
                 pack_i=-0.3, smoothed_i=-1.5),
            # Then load comes back; still discharging
            _row("2026-05-19T04:00:00", state="discharging",
                 pack_i=-3.0, smoothed_i=-2.5),
            # First real zero crossing
            _row("2026-05-19T06:44:00", state="discharging",
                 pack_i=0.0, smoothed_i=-2.0),
            # Then |i| < threshold (genuine idle)
            _row("2026-05-19T06:46:00", state="idle",
                 pack_i=0.0, smoothed_i=-0.5),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        # The 03:00 sample's |i|=0.3 must NOT have triggered idle
        self.assertNotEqual(rec.first_idle_iso, "2026-05-19T03:00:00")
        # Idle should land at 06:44:00 (first sample where |i|<=0.5
        # AFTER first_zero has been seen — actually 06:44 itself).
        self.assertEqual(rec.first_idle_iso, "2026-05-19T06:44:00")

    def test_state_idle_string_triggers_first_idle(self) -> None:
        """If the BMS itself flags `state="idle"`, that wins
        regardless of the |i| heuristic."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:43:00", state="discharging",
                 pack_i=0.0, smoothed_i=-2.0),     # zero crossing
            _row("2026-05-19T06:46:17", state="idle",
                 pack_i=0.0, smoothed_i=-0.4),     # state=idle
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        # zero at 06:43, idle at 06:43 too (since |i|<=0.5) — the
        # state=idle would have fired anyway. This test pins down
        # that BOTH conditions count, not just state.
        self.assertEqual(rec.first_idle_iso, "2026-05-19T06:43:00")

    def test_first_positive_and_net_positive_captured(self) -> None:
        """Each milestone in the cascade lands at its own moment."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:00:00", pack_i=-2.0, smoothed_i=-2.5),
            _row("2026-05-19T06:44:00", pack_i=0.0,  smoothed_i=-2.0),
            _row("2026-05-19T07:00:00", pack_i=+0.5, smoothed_i=-0.8),
            _row("2026-05-19T08:00:00", pack_i=+2.0, smoothed_i=+0.5,
                 soc_a=68.0, soc_b=66.0),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertEqual(rec.first_zero_iso, "2026-05-19T06:44:00")
        self.assertEqual(rec.first_positive_iso, "2026-05-19T07:00:00")
        self.assertEqual(rec.first_net_positive_iso, "2026-05-19T08:00:00")
        self.assertAlmostEqual(rec.smoothed_i_at_net_positive, 0.5, places=2)
        # SOC at the net-positive moment: avg of 68 and 66 = 67
        self.assertAlmostEqual(rec.soc_avg_at_net_positive, 67.0, places=2)

    def test_other_days_samples_are_ignored(self) -> None:
        """Detector keys on the date prefix of the ts column —
        samples from the previous day must not bleed into today."""
        _write_pack(self.pack, [
            # Previous day evening — current was going up after sun
            _row("2026-05-18T14:00:00", pack_i=+5.0, smoothed_i=+4.0),
            # Today's overnight low (still discharging)
            _row("2026-05-19T04:00:00", pack_i=-2.5, smoothed_i=-2.4),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertTrue(rec.is_empty())

    # ---------- upsert + log ----------

    def test_upsert_writes_first_row_for_new_day(self) -> None:
        rec = so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
            first_idle_iso="2026-05-19T06:46:17",
        )
        wrote = so_mod.upsert(rec, self.log)
        self.assertTrue(wrote)
        all_recs = so_mod.read_log(self.log)
        self.assertEqual(len(all_recs), 1)
        self.assertEqual(all_recs[0].first_zero_iso, "2026-05-19T06:44:10")

    def test_upsert_is_noop_on_empty_record(self) -> None:
        """Pre-onset detection should NOT pollute the log with
        empty rows."""
        rec = so_mod.SolarOnsetRecord(date="2026-05-19")
        self.assertTrue(rec.is_empty())
        wrote = so_mod.upsert(rec, self.log)
        self.assertFalse(wrote)
        self.assertEqual(so_mod.read_log(self.log), [])

    def test_upsert_replaces_existing_row_for_same_day(self) -> None:
        """A later detection (more milestones now seen) should
        overwrite, not duplicate."""
        # Morning: only first_zero
        so_mod.upsert(so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
        ), self.log)
        # Afternoon: now first_net_positive too
        wrote = so_mod.upsert(so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
            first_idle_iso="2026-05-19T06:46:17",
            first_positive_iso="2026-05-19T07:30:00",
            first_net_positive_iso="2026-05-19T08:00:00",
            smoothed_i_at_net_positive=+0.5,
            soc_avg_at_net_positive=66.0,
        ), self.log)
        self.assertTrue(wrote)
        all_recs = so_mod.read_log(self.log)
        self.assertEqual(len(all_recs), 1)
        self.assertEqual(all_recs[0].first_net_positive_iso,
                         "2026-05-19T08:00:00")

    def test_upsert_is_noop_when_record_unchanged(self) -> None:
        """Same milestones as previous run → no rewrite, no churn."""
        rec = so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
        )
        so_mod.upsert(rec, self.log)
        wrote = so_mod.upsert(rec, self.log)
        self.assertFalse(wrote)
        self.assertEqual(len(so_mod.read_log(self.log)), 1)

    def test_multiple_days_stay_in_chronological_order(self) -> None:
        """The log keeps days sorted by date string regardless of
        insertion order."""
        so_mod.upsert(so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
        ), self.log)
        so_mod.upsert(so_mod.SolarOnsetRecord(
            date="2026-05-18",
            first_zero_iso="2026-05-18T07:15:00",
        ), self.log)
        recs = so_mod.read_log(self.log)
        self.assertEqual([r.date for r in recs],
                         ["2026-05-18", "2026-05-19"])

    def test_detect_and_record_end_to_end(self) -> None:
        """End-to-end: writing a pack fixture, running
        detect_and_record, reading back the log."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:00:00", pack_i=-2.0, smoothed_i=-2.5),
            _row("2026-05-19T06:44:10", pack_i=0.0,  smoothed_i=-2.0),
        ])
        rec, wrote = so_mod.detect_and_record(
            pack_csv=self.pack, day=date(2026, 5, 19), log_path=self.log,
        )
        self.assertTrue(wrote)
        self.assertEqual(rec.first_zero_iso, "2026-05-19T06:44:10")
        # Read back
        all_recs = so_mod.read_log(self.log)
        self.assertEqual(len(all_recs), 1)
        self.assertEqual(all_recs[0].first_zero_iso, "2026-05-19T06:44:10")

    # ---------- afternoon cascade (absorption + full) ----------

    def test_full_state_milestone_captured(self) -> None:
        """When the BMS reports state='full', first_full_iso records
        that exact sample's timestamp."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:00:00", pack_i=-3.0, smoothed_i=-2.5),
            # First net-positive: solar exceeds load
            _row("2026-05-19T07:44:00", pack_v=26.40,
                 pack_i=2.0, smoothed_i=1.0),
            # Later, BMS classifies as full
            _row("2026-05-19T15:00:00", state="full", pack_v=27.30,
                 pack_i=0.5, smoothed_i=0.5),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertEqual(rec.first_full_iso, "2026-05-19T15:00:00")

    def test_absorption_milestone_via_voltage_and_taper(self) -> None:
        """first_absorption_iso fires when (a) pack_v exceeds the
        absorption threshold AND (b) smoothed_i has dropped below
        the configured fraction of the running peak (post-net+).
        Today's heuristic: V > 26.7, smoothed_i < peak × 0.75."""
        _write_pack(self.pack, [
            _row("2026-05-19T06:00:00", pack_v=26.10,
                 pack_i=-3.0, smoothed_i=-2.5),
            # First net-positive — smoothed crosses zero
            _row("2026-05-19T07:44:00", pack_v=26.45,
                 pack_i=2.0, smoothed_i=1.0),
            # Peak charging: smoothed_i reaches 18 A
            _row("2026-05-19T11:00:00", pack_v=26.70,
                 pack_i=18.0, smoothed_i=18.0),
            # Absorption: V crosses threshold AND smoothed has tapered
            # below 0.75 × 18 = 13.5 A. 13 A here qualifies.
            _row("2026-05-19T13:44:00", pack_v=26.92,
                 pack_i=13.0, smoothed_i=13.0),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        self.assertEqual(rec.first_absorption_iso, "2026-05-19T13:44:00")
        # full not present
        self.assertIsNone(rec.first_full_iso)

    def test_absorption_not_fired_before_net_positive(self) -> None:
        """The absorption heuristic must only consider samples AFTER
        first_net_positive — otherwise a transient voltage spike on
        a discharging morning would spuriously fire."""
        _write_pack(self.pack, [
            # Early-morning sample with high voltage but discharging
            # (the BMS sometimes reports high V at rest before load).
            _row("2026-05-19T05:00:00", pack_v=27.00,
                 pack_i=-0.5, smoothed_i=-2.0),
            _row("2026-05-19T07:00:00", pack_v=26.40,
                 pack_i=-3.0, smoothed_i=-2.5),
        ])
        rec = so_mod.detect_onset(self.pack, date(2026, 5, 19))
        # No net_positive ever happens → no absorption either
        self.assertIsNone(rec.first_absorption_iso)
        self.assertIsNone(rec.first_net_positive_iso)

    def test_csv_round_trip_preserves_new_fields(self) -> None:
        """Writing then reading back the log must preserve
        first_absorption_iso and first_full_iso. Anchors the
        schema-upgrade backward compat (the new fields land at
        the end of the FIELDS list so old CSVs still load)."""
        rec = so_mod.SolarOnsetRecord(
            date="2026-05-19",
            first_zero_iso="2026-05-19T06:44:10",
            first_idle_iso="2026-05-19T06:44:10",
            first_positive_iso="2026-05-19T07:44:21",
            first_net_positive_iso="2026-05-19T07:45:40",
            smoothed_i_at_net_positive=0.17,
            soc_avg_at_net_positive=63.5,
            first_absorption_iso="2026-05-19T13:44:00",
            first_full_iso="2026-05-19T15:30:00",
        )
        so_mod.upsert(rec, self.log)
        read_back = so_mod.read_log(self.log)
        self.assertEqual(len(read_back), 1)
        e = read_back[0]
        self.assertEqual(e.first_absorption_iso, "2026-05-19T13:44:00")
        self.assertEqual(e.first_full_iso, "2026-05-19T15:30:00")


if __name__ == "__main__":
    unittest.main()
