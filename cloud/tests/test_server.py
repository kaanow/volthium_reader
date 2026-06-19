"""Integration test for cloud.server.main using a fake DAO.

This doesn't need Postgres — the DAO is the contract; we substitute an
in-memory implementation that exercises every code path in main.py.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Configure tokens BEFORE importing the server, since settings.tokens is
# built at module load via _state population in get_settings().
os.environ["READER_TOKEN_PI_BARGE"] = "secret-pi-token"
os.environ["READER_TOKEN_ESP32_BARGE"] = "secret-esp-token"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient   # noqa: E402

from cloud.server import main as server_main   # noqa: E402
from cloud.server.derive import Derived   # noqa: E402
from cloud.shared.wire import Reading   # noqa: E402


class FakeDAO:
    def __init__(self):
        self.rows: list[dict] = []
        # rows are stored newest-first (mirroring DAO.recent contract)

    async def latest_smoothed(self, source_id: str, before_ts: datetime):
        for r in self.rows:
            if r["source_id"] == source_id and r["ts"] < before_ts:
                return (r.get("smoothed_i"), r.get("smoothed_p"))
        return (None, None)

    async def insert(
        self,
        source_id: str,
        readings: Sequence[Reading],
        deriveds: Sequence[Derived],
    ):
        accepted = 0
        duplicates = 0
        existing_ts = {r["ts"] for r in self.rows if r["source_id"] == source_id}
        for r, d in zip(readings, deriveds):
            if r.ts in existing_ts:
                duplicates += 1
                continue
            row = {
                "source_id": source_id, "ts": r.ts, "state": r.state,
                "v_a": r.v_a, "v_b": r.v_b, "i_a": r.i_a, "i_b": r.i_b,
                "soc_a": r.soc_a, "soc_b": r.soc_b,
                "t_a": r.t_a, "t_b": r.t_b,
                "remaining_ah_a": r.remaining_ah_a, "remaining_ah_b": r.remaining_ah_b,
                "delta_v_a": r.delta_v_a, "delta_v_b": r.delta_v_b,
                "name_a": r.name_a, "name_b": r.name_b,
                "problem_code_a": r.problem_code_a, "problem_code_b": r.problem_code_b,
                "cell_voltages_a": r.cell_voltages_a,
                "cell_voltages_b": r.cell_voltages_b,
                "pack_v": d.pack_v, "pack_i": d.pack_i, "pack_p": d.pack_p,
                "smoothed_i": d.smoothed_i, "smoothed_p": d.smoothed_p,
                "minutes_remaining": d.minutes_remaining,
            }
            self.rows.insert(0, row)  # newest-first
            accepted += 1
            existing_ts.add(r.ts)
        # Sort newest-first across the table
        self.rows.sort(key=lambda r: r["ts"], reverse=True)
        return (accepted, duplicates)

    async def recent(self, source_id: Optional[str], limit: int):
        if source_id is None:
            if not self.rows:
                return []
            source_id = self.rows[0]["source_id"]
        return [r for r in self.rows if r["source_id"] == source_id][:limit]

    async def sources(self) -> list[str]:
        return sorted({r["source_id"] for r in self.rows})


def _client() -> TestClient:
    # Wire fake DAO + force settings reload so the token env vars are picked up.
    server_main._state["dao"] = FakeDAO()
    server_main._state["settings"] = None   # reload via get_settings()
    return TestClient(server_main.app)


# ---- tests ---------------------------------------------------------------


READING = {
    "ts": "2026-06-18T19:00:00Z",
    "state": "discharging",
    "v_a": 13.2, "v_b": 13.2, "i_a": -3.0, "i_b": -3.0,
    "soc_a": 70, "soc_b": 68,
    "delta_v_a": 0.008, "delta_v_b": 0.009,
    "problem_code_a": 0, "problem_code_b": 0,
    "cell_voltages_a": [3.301, 3.302, 3.299, 3.303],
    "cell_voltages_b": [3.305, 3.300, 3.299, 3.306],
}


class HealthTests(unittest.TestCase):
    def test_healthz(self):
        c = _client()
        r = c.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")


class IngestTests(unittest.TestCase):
    def test_rejects_no_auth(self):
        c = _client()
        r = c.post("/ingest", json={"source_id": "pi-barge", "readings": [READING]})
        self.assertEqual(r.status_code, 401)

    def test_rejects_wrong_token(self):
        c = _client()
        r = c.post(
            "/ingest",
            headers={"Authorization": "Bearer nope"},
            json={"source_id": "pi-barge", "readings": [READING]},
        )
        self.assertEqual(r.status_code, 401)

    def test_rejects_unknown_source(self):
        c = _client()
        r = c.post(
            "/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json={"source_id": "ghost", "readings": [READING]},
        )
        self.assertEqual(r.status_code, 401)

    def test_accepts_and_derives(self):
        c = _client()
        r = c.post(
            "/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json={"source_id": "pi-barge", "readings": [READING]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body, {"accepted": 1, "duplicates": 0})

        # The DAO should have one row with pack_v derived from v_a + v_b.
        rows = server_main._state["dao"].rows
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["pack_v"], 26.4, places=2)

    def test_idempotent_repost(self):
        c = _client()
        body = {"source_id": "pi-barge", "readings": [READING]}
        hdr = {"Authorization": "Bearer secret-pi-token"}
        r1 = c.post("/ingest", headers=hdr, json=body)
        r2 = c.post("/ingest", headers=hdr, json=body)
        self.assertEqual(r1.json(), {"accepted": 1, "duplicates": 0})
        self.assertEqual(r2.json(), {"accepted": 0, "duplicates": 1})

    def test_multiple_sources_dont_collide(self):
        c = _client()
        c.post("/ingest",
               headers={"Authorization": "Bearer secret-pi-token"},
               json={"source_id": "pi-barge", "readings": [READING]})
        c.post("/ingest",
               headers={"Authorization": "Bearer secret-esp-token"},
               json={"source_id": "esp32-barge", "readings": [READING]})
        sources = c.get("/api/sources").json()["sources"]
        self.assertEqual(sources, ["esp32-barge", "pi-barge"])

    def test_naive_ts_rejected(self):
        c = _client()
        bad = dict(READING, ts="2026-06-18T19:00:00")   # no Z
        r = c.post(
            "/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json={"source_id": "pi-barge", "readings": [bad]},
        )
        self.assertEqual(r.status_code, 422)


class ReadbackTests(unittest.TestCase):
    def test_readings_round_trip(self):
        c = _client()
        c.post("/ingest",
               headers={"Authorization": "Bearer secret-pi-token"},
               json={"source_id": "pi-barge", "readings": [READING]})
        r = c.get("/api/readings?source_id=pi-barge")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 1)
        row = body["readings"][0]
        self.assertEqual(row["source_id"], "pi-barge")
        self.assertTrue(row["ts"].endswith("Z"))
        self.assertEqual(row["problem_code_a"], 0)
        self.assertEqual(row["cell_voltages_a"], [3.301, 3.302, 3.299, 3.303])

    def test_latest(self):
        c = _client()
        c.post("/ingest",
               headers={"Authorization": "Bearer secret-pi-token"},
               json={"source_id": "pi-barge", "readings": [READING]})
        r = c.get("/api/latest")
        self.assertEqual(r.status_code, 200)
        latest = r.json()["latest"]
        self.assertEqual(latest["state"], "discharging")


if __name__ == "__main__":
    unittest.main()
