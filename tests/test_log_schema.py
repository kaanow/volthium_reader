"""Tests for scripts/log.py CSV schema — the new fields (problem_code +
cell voltages) and the schema-drift archiver.

These pin the contract that the cloud uploader / Postgres ingest depend on:
if the local CSV ever loses one of these columns, an old reader would silently
produce broken Railway data.
"""

from __future__ import annotations

import csv
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _stub_ble_deps() -> None:
    """Stub the third-party BLE deps that volthium.pack imports at module
    level. These tests only exercise the CSV-writer and the schema-drift
    archiver — neither touches real Bluetooth. Stubbing lets the suite run
    on Python 3.11 even though aiobmsble itself requires 3.12+.
    """
    aiobmsble = types.ModuleType("aiobmsble")
    aiobmsble.BMSSample = dict   # type: ignore[attr-defined]
    sys.modules.setdefault("aiobmsble", aiobmsble)
    bms_pkg = types.ModuleType("aiobmsble.bms")
    sys.modules.setdefault("aiobmsble.bms", bms_pkg)
    ej = types.ModuleType("aiobmsble.bms.ej_bms")

    class _BMS:  # pragma: no cover — placeholder
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
    ej.BMS = _BMS   # type: ignore[attr-defined]
    sys.modules.setdefault("aiobmsble.bms.ej_bms", ej)

    bleak = types.ModuleType("bleak")
    class _Scanner:  # pragma: no cover
        def __init__(self, *a, **kw): ...
        async def start(self): ...
        async def stop(self): ...
        @staticmethod
        async def find_device_by_address(*a, **kw): return None
    bleak.BleakScanner = _Scanner   # type: ignore[attr-defined]
    sys.modules.setdefault("bleak", bleak)
    backends = types.ModuleType("bleak.backends")
    sys.modules.setdefault("bleak.backends", backends)
    backends_dev = types.ModuleType("bleak.backends.device")
    class _BLEDevice:  # pragma: no cover
        pass
    backends_dev.BLEDevice = _BLEDevice   # type: ignore[attr-defined]
    sys.modules.setdefault("bleak.backends.device", backends_dev)


_stub_ble_deps()

# log.py is a script with side-effects in __main__ only — safe to import.
import log as log_script  # noqa: E402


# --- fakes -----------------------------------------------------------------

@dataclass
class _FakeBatt:
    voltage: float | None = 13.20
    current: float | None = -3.0
    soc: float | None = 70
    remaining_ah: float | None = 158.0
    temperature: float | None = 23
    delta_voltage: float | None = 0.008
    name: str = "V-12V200AH-0533"
    problem_code: int | None = 0
    cell_voltages: list | None = None


class _FakePack:
    def __init__(self, a: _FakeBatt, b: _FakeBatt):
        self.a, self.b = a, b

    @property
    def pack_voltage(self): return (self.a.voltage or 0) + (self.b.voltage or 0)
    @property
    def pack_current(self): return self.a.current
    @property
    def pack_power(self):   return self.pack_voltage * self.pack_current


@dataclass
class _FakeEst:
    state: str = "discharging"
    smoothed_current: float = -3.0
    smoothed_power: float = -78.0
    minutes_remaining: float = 2245


# --- tests -----------------------------------------------------------------

class CsvSchemaTests(unittest.TestCase):

    def test_header_includes_new_columns(self):
        for col in (
            "problem_code_a", "problem_code_b",
            "cell_a_1", "cell_a_2", "cell_a_3", "cell_a_4",
            "cell_b_1", "cell_b_2", "cell_b_3", "cell_b_4",
        ):
            self.assertIn(col, log_script.CSV_FIELDS)

    def test_writes_cell_voltages_and_problem_code(self):
        a = _FakeBatt(problem_code=4, cell_voltages=[3.301, 3.302, 3.299, 3.303])
        b = _FakeBatt(problem_code=0, cell_voltages=[3.305, 3.300, 3.299, 3.306])
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            log_script.append_csv(path, _FakePack(a, b), _FakeEst())
            with path.open() as f:
                row = next(csv.DictReader(f))
        self.assertEqual(row["problem_code_a"], "4")
        self.assertEqual(row["problem_code_b"], "0")
        self.assertEqual(row["cell_a_1"], "3.301")
        self.assertEqual(row["cell_b_4"], "3.306")

    def test_handles_missing_cell_voltages(self):
        # BMS dropouts can return None for cell_voltages — that must not crash;
        # the columns should be blank.
        a = _FakeBatt(cell_voltages=None)
        b = _FakeBatt(cell_voltages=None)
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            log_script.append_csv(path, _FakePack(a, b), _FakeEst())
            with path.open() as f:
                row = next(csv.DictReader(f))
        for col in ("cell_a_1", "cell_a_4", "cell_b_1", "cell_b_4"):
            self.assertEqual(row[col], "")

    def test_truncates_extra_cells(self):
        a = _FakeBatt(cell_voltages=[3.30, 3.30, 3.30, 3.30, 3.30, 3.30])
        b = _FakeBatt(cell_voltages=[3.30] * 4)
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            log_script.append_csv(path, _FakePack(a, b), _FakeEst())
            # No extra columns leaked into row — header still has 4 cell_a_*.
            with path.open() as f:
                header = next(csv.reader(f))
        cell_a_cols = [c for c in header if c.startswith("cell_a_")]
        self.assertEqual(len(cell_a_cols), log_script.CELLS_PER_BATTERY)


class SchemaDriftArchiverTests(unittest.TestCase):

    def test_archives_when_header_outdated(self):
        # Simulate the previous-generation CSV: same as today's minus the
        # columns we just added.
        old_header = (
            "ts,state,pack_v,pack_i,pack_p,soc_a,soc_b,v_a,v_b,i_a,i_b,"
            "t_a,t_b,remaining_ah_a,remaining_ah_b,delta_v_a,delta_v_b,"
            "smoothed_i,smoothed_p,minutes_remaining,name_a,name_b\n"
        )
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            path.write_text(old_header + "2026-05-17T15:13:00,discharging,26.4\n")
            import logging
            log_script._archive_if_schema_drift(path, logging.getLogger("t"))
            # Original file should be gone, replaced by an archive sibling.
            self.assertFalse(path.exists())
            siblings = list(path.parent.iterdir())
            self.assertTrue(any(s.name.startswith("pack.csv.v") for s in siblings))

    def test_noop_when_header_matches(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            # Write a fresh file with the CURRENT schema header — nothing
            # to archive.
            path.write_text(",".join(log_script.CSV_FIELDS) + "\n")
            import logging
            log_script._archive_if_schema_drift(path, logging.getLogger("t"))
            self.assertTrue(path.exists())
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_noop_when_file_missing(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "pack.csv"
            import logging
            # Must not raise even though file isn't there yet.
            log_script._archive_if_schema_drift(path, logging.getLogger("t"))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
