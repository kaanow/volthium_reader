"""Tests for cloud.shared.wire — the wire-protocol Pydantic models.

These pin the contract that the future ESP32 firmware needs to honor:
  - Timestamps MUST be UTC with a `Z` suffix; naive datetimes are rejected.
  - cell_voltages_a/_b are arrays trimmed to CELLS_PER_BATTERY.
  - extra fields are rejected (forbids future cross-version drift).
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloud.shared.wire import IngestBatch, Reading, CELLS_PER_BATTERY  # noqa: E402


GOOD_TS = "2026-05-17T19:13:00Z"


def _reading(**overrides) -> dict:
    base = {"ts": GOOD_TS, "state": "discharging"}
    base.update(overrides)
    return base


class TimestampTests(unittest.TestCase):

    def test_accepts_utc_z(self):
        r = Reading(**_reading())
        self.assertEqual(r.ts.tzinfo, timezone.utc)
        self.assertEqual(r.ts.year, 2026)

    def test_normalizes_offset_to_utc(self):
        r = Reading(**_reading(ts="2026-05-17T15:13:00-04:00"))
        # 15:13 local-04:00 → 19:13 UTC
        self.assertEqual(r.ts.hour, 19)
        self.assertEqual(r.ts.tzinfo, timezone.utc)

    def test_rejects_naive_string(self):
        with self.assertRaises(Exception):
            Reading(**_reading(ts="2026-05-17T19:13:00"))

    def test_rejects_naive_datetime(self):
        with self.assertRaises(Exception):
            Reading(**_reading(ts=datetime(2026, 5, 17, 19, 13)))


class FieldShapeTests(unittest.TestCase):

    def test_extras_rejected(self):
        # If a future ESP32 firmware tries to send a column the server
        # doesn't recognize, we want to know — silent drops cause data loss.
        with self.assertRaises(Exception):
            Reading(**_reading(undeclared_field=1.0))

    def test_cell_voltages_trimmed(self):
        r = Reading(**_reading(cell_voltages_a=[3.30, 3.31, 3.30, 3.30, 3.30, 3.30]))
        self.assertEqual(len(r.cell_voltages_a), CELLS_PER_BATTERY)

    def test_cell_voltages_none_passthrough(self):
        r = Reading(**_reading(cell_voltages_a=None))
        self.assertIsNone(r.cell_voltages_a)

    def test_full_roundtrip(self):
        body = {
            "source_id": "pi-barge",
            "readings": [_reading(
                v_a=13.21, v_b=13.22, i_a=-3.2, i_b=-3.0,
                soc_a=70, soc_b=68, t_a=23, t_b=23,
                remaining_ah_a=158.0, remaining_ah_b=142.0,
                delta_v_a=0.008, delta_v_b=0.009,
                name_a="V-12V200AH-0533", name_b="V-12V200AH-0667",
                problem_code_a=0, problem_code_b=0,
                cell_voltages_a=[3.301, 3.302, 3.299, 3.303],
                cell_voltages_b=[3.305, 3.300, 3.299, 3.306],
            )],
        }
        batch = IngestBatch(**body)
        self.assertEqual(batch.source_id, "pi-barge")
        self.assertEqual(len(batch.readings), 1)
        r = batch.readings[0]
        self.assertEqual(r.problem_code_a, 0)
        self.assertEqual(r.cell_voltages_b[0], 3.305)


class BatchShapeTests(unittest.TestCase):

    def test_rejects_empty(self):
        with self.assertRaises(Exception):
            IngestBatch(source_id="pi-barge", readings=[])

    def test_rejects_oversize(self):
        rows = [_reading() for _ in range(1001)]
        with self.assertRaises(Exception):
            IngestBatch(source_id="pi-barge", readings=rows)


if __name__ == "__main__":
    unittest.main()
