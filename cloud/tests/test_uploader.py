"""Tests for cloud.uploader.uploader — CSV → wire conversion + offset state."""

from __future__ import annotations

import csv
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloud.uploader.uploader import (   # noqa: E402
    _collect_cells,
    _local_to_utc_z,
    csv_row_to_wire,
    load_state,
    read_new_rows,
    save_state,
)


def _csv_row(**overrides) -> dict:
    base = {
        "ts": "2026-05-17T15:13:00",
        "state": "discharging",
        "pack_v": "26.432", "pack_i": "-3.1", "pack_p": "-81.9",
        "soc_a": "70", "soc_b": "68",
        "v_a": "13.215", "v_b": "13.217",
        "i_a": "-3.2", "i_b": "-3.0",
        "t_a": "23", "t_b": "23",
        "remaining_ah_a": "158.0", "remaining_ah_b": "142.0",
        "delta_v_a": "0.008", "delta_v_b": "0.009",
        "smoothed_i": "-3.1", "smoothed_p": "-81.9",
        "minutes_remaining": "2245",
        "name_a": "V-12V200AH-0533", "name_b": "V-12V200AH-0667",
        "problem_code_a": "0", "problem_code_b": "0",
        "cell_a_1": "3.301", "cell_a_2": "3.302",
        "cell_a_3": "3.299", "cell_a_4": "3.303",
        "cell_b_1": "3.305", "cell_b_2": "3.300",
        "cell_b_3": "3.299", "cell_b_4": "3.306",
    }
    base.update(overrides)
    return base


class CellCollectorTests(unittest.TestCase):
    def test_all_present(self):
        row = _csv_row()
        cells = _collect_cells(row, "a")
        self.assertEqual(cells, [3.301, 3.302, 3.299, 3.303])

    def test_all_missing(self):
        row = _csv_row(cell_a_1="", cell_a_2="", cell_a_3="", cell_a_4="")
        self.assertIsNone(_collect_cells(row, "a"))

    def test_partial(self):
        row = _csv_row(cell_a_1="3.30", cell_a_2="", cell_a_3="3.31", cell_a_4="")
        # We don't preserve cell-index — partial reads become a shorter list.
        # That's acceptable for v1; the dashboard fills in dashes.
        self.assertEqual(_collect_cells(row, "a"), [3.30, 3.31])


class TimestampConversionTests(unittest.TestCase):
    def test_local_to_utc_z_shape(self):
        # We can't assert the exact UTC hour without knowing the test
        # machine's tz. But the output must end in Z, have second precision,
        # and parse cleanly as ISO.
        out = _local_to_utc_z("2026-05-17T15:13:00")
        self.assertTrue(out.endswith("Z"))
        # Re-parsing must succeed
        dt = datetime.fromisoformat(out.replace("Z", "+00:00"))
        self.assertEqual(dt.tzinfo, timezone.utc)


class CsvRowToWireTests(unittest.TestCase):
    def test_full_row(self):
        wire = csv_row_to_wire(_csv_row())
        self.assertTrue(wire["ts"].endswith("Z"))
        self.assertEqual(wire["state"], "discharging")
        self.assertEqual(wire["v_a"], 13.215)
        self.assertEqual(wire["problem_code_a"], 0)
        self.assertEqual(wire["cell_voltages_b"], [3.305, 3.300, 3.299, 3.306])
        # Derived fields from the CSV are deliberately NOT forwarded — the
        # server computes them.
        self.assertNotIn("pack_v", wire)
        self.assertNotIn("smoothed_i", wire)
        self.assertNotIn("minutes_remaining", wire)

    def test_missing_optional(self):
        row = _csv_row(i_a="", soc_b="", problem_code_b="")
        wire = csv_row_to_wire(row)
        self.assertIsNone(wire["i_a"])
        self.assertIsNone(wire["soc_b"])
        self.assertIsNone(wire["problem_code_b"])


class StatePersistenceTests(unittest.TestCase):
    def test_load_missing(self):
        with TemporaryDirectory() as d:
            self.assertEqual(load_state(Path(d) / "pack.csv")["offset_bytes"], 0)

    def test_save_and_load_roundtrip(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            save_state(p, {"offset_bytes": 12345, "inode": 99})
            self.assertEqual(load_state(p)["offset_bytes"], 12345)


class ReadNewRowsTests(unittest.TestCase):
    def _write_csv(self, path: Path, n: int) -> None:
        cols = list(_csv_row().keys())
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for _ in range(n):
                w.writerow(_csv_row())

    def test_first_read_consumes_all(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            self._write_csv(p, 3)
            rows, state = read_new_rows(p, {"offset_bytes": 0, "inode": None}, 10)
            self.assertEqual(len(rows), 3)
            self.assertGreater(state["offset_bytes"], 0)
            self.assertEqual(state["inode"], p.stat().st_ino)
            self.assertIsNotNone(state["header"])

    def test_second_read_is_empty(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            self._write_csv(p, 3)
            _, state = read_new_rows(p, {"offset_bytes": 0, "inode": None}, 10)
            rows, state2 = read_new_rows(p, state, 10)
            self.assertEqual(rows, [])
            self.assertEqual(state2["offset_bytes"], state["offset_bytes"])

    def test_picks_up_appended_rows(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            self._write_csv(p, 2)
            _, state = read_new_rows(p, {"offset_bytes": 0, "inode": None}, 10)
            # Append two more rows
            cols = list(_csv_row().keys())
            with p.open("a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writerow(_csv_row(ts="2026-05-17T15:13:10"))
                w.writerow(_csv_row(ts="2026-05-17T15:13:20"))
            rows, _ = read_new_rows(p, state, 10)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["ts"], "2026-05-17T15:13:10")

    def test_rotation_resets_offset(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            self._write_csv(p, 2)
            _, state = read_new_rows(p, {"offset_bytes": 0, "inode": None}, 10)
            # Simulate rotation: nuke the file, write a new one.
            p.unlink()
            self._write_csv(p, 1)
            rows, new_state = read_new_rows(p, state, 10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(new_state["inode"], p.stat().st_ino)

    def test_batch_size_caps(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "pack.csv"
            self._write_csv(p, 100)
            rows, _ = read_new_rows(p, {"offset_bytes": 0, "inode": None}, 5)
            self.assertEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
