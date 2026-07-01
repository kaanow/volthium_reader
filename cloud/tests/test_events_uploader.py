"""Tests for cloud.uploader.events_uploader — sealed-segment draining."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloud.uploader.events_uploader import (   # noqa: E402
    _read_events,
    _sealed_segments,
    _to_wire,
)


class SegmentDiscoveryTests(unittest.TestCase):

    def test_finds_sealed_only(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "ble_events.jsonl").write_text("live\n")
            (root / "ble_events.jsonl.0001.sealed").write_text("a\n")
            (root / "ble_events.jsonl.0002.sealed").write_text("b\n")
            (root / "other.log").write_text("nope\n")
            segs = _sealed_segments(root, "ble_events.jsonl")
        names = [s.name for s in segs]
        # Sealed only, oldest-first
        self.assertEqual(
            names,
            ["ble_events.jsonl.0001.sealed", "ble_events.jsonl.0002.sealed"],
        )

    def test_missing_dir(self):
        with TemporaryDirectory() as d:
            self.assertEqual(
                _sealed_segments(Path(d) / "nope", "ble_events.jsonl"), []
            )


class EventParsingTests(unittest.TestCase):

    def test_skips_blank_and_malformed(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "seg.sealed"
            p.write_text(
                json.dumps({"ts": "2026-07-01T15:00:00Z", "event": "a"}) + "\n"
                "\n"                           # blank
                "not-json\n"                   # malformed
                + json.dumps({"ts": "2026-07-01T15:00:01Z", "event": "b"}) + "\n"
            )
            events = list(_read_events(p))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "a")
        self.assertEqual(events[1]["event"], "b")


class WireReshapeTests(unittest.TestCase):

    def test_folds_extras_into_data(self):
        rec = {"ts": "2026-07-01T15:00:00Z", "event": "read_ok",
               "address": "AA:BB", "read_s": 1.4, "soc": 61}
        wire = _to_wire(rec)
        self.assertEqual(wire["ts"], "2026-07-01T15:00:00Z")
        self.assertEqual(wire["event"], "read_ok")
        self.assertEqual(wire["data"], {"address": "AA:BB", "read_s": 1.4, "soc": 61})

    def test_empty_data_when_only_ts_event(self):
        rec = {"ts": "2026-07-01T15:00:00Z", "event": "cycle_done"}
        wire = _to_wire(rec)
        self.assertEqual(wire["data"], {})

    def test_rejects_missing_required(self):
        for bad in ({"event": "x"}, {"ts": "2026-07-01T15:00:00Z"}, {}):
            with self.assertRaises(ValueError):
                _to_wire(bad)


if __name__ == "__main__":
    unittest.main()
