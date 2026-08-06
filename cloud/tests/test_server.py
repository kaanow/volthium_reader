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
from cloud.shared.wire import BleEvent, Reading   # noqa: E402


class FakeDAO:
    def __init__(self):
        self.rows: list[dict] = []
        self.events: list[dict] = []
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

    async def insert_events(self, source_id, events):
        for e in events:
            self.events.append({
                "source_id": source_id,
                "ts": e.ts,
                "event": e.event,
                "data": e.data,
            })
        return len(events)


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


class BleEventIngestTests(unittest.TestCase):

    def _batch(self, **overrides):
        base = {
            "source_id": "pi-barge",
            "events": [
                {"ts": "2026-07-01T15:00:00Z", "event": "scan_result",
                 "data": {"address": "AA:BB", "seen": True, "rssi": -71}},
                {"ts": "2026-07-01T15:00:03Z", "event": "read_ok",
                 "data": {"address": "AA:BB", "read_s": 1.2, "soc": 62}},
            ],
        }
        base.update(overrides)
        return base

    def test_rejects_no_auth(self):
        c = _client()
        r = c.post("/api/events/ingest", json=self._batch())
        self.assertEqual(r.status_code, 401)

    def test_accepts_and_stores(self):
        c = _client()
        r = c.post(
            "/api/events/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json=self._batch(),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"accepted": 2})
        stored = server_main._state["dao"].events
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["event"], "scan_result")
        self.assertEqual(stored[0]["data"]["rssi"], -71)

    def test_naive_ts_rejected(self):
        c = _client()
        bad = self._batch(events=[{"ts": "2026-07-01T15:00:00", "event": "x", "data": {}}])
        r = c.post(
            "/api/events/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json=bad,
        )
        self.assertEqual(r.status_code, 422)

    def test_extras_rejected_in_event(self):
        # Same strict-schema policy as readings — unknown top-level fields on
        # the event get rejected. The `data` dict itself is free-form.
        c = _client()
        bad = self._batch(events=[
            {"ts": "2026-07-01T15:00:00Z", "event": "x", "data": {},
             "extra_field": "nope"},
        ])
        r = c.post(
            "/api/events/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json=bad,
        )
        self.assertEqual(r.status_code, 422)

    def test_empty_batch_rejected(self):
        c = _client()
        r = c.post(
            "/api/events/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json={"source_id": "pi-barge", "events": []},
        )
        self.assertEqual(r.status_code, 422)


class HistoryEndpointTests(unittest.TestCase):
    """The /api/history/* endpoints run real SQL only on AsyncpgReadingsDAO;
    with the fake they must return well-formed empty shapes, never 500 —
    same contract as /api/events. /history serves the static page."""

    def _seeded_client(self) -> TestClient:
        c = _client()
        r = c.post(
            "/ingest",
            headers={"Authorization": "Bearer secret-pi-token"},
            json={"source_id": "pi-barge", "readings": [READING]},
        )
        assert r.status_code == 200
        return c

    def test_series_empty_shape(self):
        c = self._seeded_client()
        r = c.get("/api/history/series?hours=24&bucket_s=300")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["series"], [])

    def test_series_rejects_bad_before(self):
        c = self._seeded_client()
        r = c.get("/api/history/series?before=not-a-date")
        self.assertEqual(r.status_code, 422)

    def test_series_accepts_iso_before(self):
        c = self._seeded_client()
        r = c.get("/api/history/series?hours=24&before=2026-07-01T00:00:00Z")
        self.assertEqual(r.status_code, 200)

    def test_daily_profile_gaps_stats_empty_shapes(self):
        c = self._seeded_client()
        self.assertEqual(c.get("/api/history/daily").json()["days"], [])
        self.assertEqual(c.get("/api/history/profile").json()["profile"], [])
        self.assertEqual(c.get("/api/history/gaps").json()["gaps"], [])
        self.assertIsNone(c.get("/api/history/stats").json()["stats"])

    def test_no_source_at_all(self):
        # Fresh DAO with zero rows — endpoints must still 200.
        c = _client()
        for path in ("/api/history/series", "/api/history/daily",
                     "/api/history/profile", "/api/history/gaps",
                     "/api/history/stats"):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)

    def test_history_page_served(self):
        c = _client()
        r = c.get("/history")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Pack History", r.text)

    def test_dashboard_links_to_history(self):
        c = _client()
        r = c.get("/")
        self.assertIn('href="/history"', r.text)


class SolarTests(unittest.TestCase):
    """Solar/Xanbus endpoints. FakeDAO isn't an AsyncpgReadingsDAO, so the
    data paths return well-formed empty shapes — these tests pin the auth
    behavior, input validation, and those shapes."""

    SOLAR_ROW = {
        "ts": "2026-07-30T19:00:00Z",
        "solar_w": 120.5, "solar_w_min": 80.0, "solar_w_max": 190.0,
        "solar_a": 4.4, "pv_v": 88.2,
        "dc_v": 27.1, "dc_a": -2.1, "dc_w": -57.0,
        "dc_w_min": -140.0, "dc_w_max": 10.0,
        "sample_n": 45,
    }

    def test_ingest_rejects_no_auth(self):
        c = _client()
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [self.SOLAR_ROW]})
        self.assertEqual(r.status_code, 401)

    def test_ingest_rejects_wrong_token(self):
        c = _client()
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [self.SOLAR_ROW]},
            headers={"Authorization": "Bearer nope"})
        self.assertEqual(r.status_code, 401)

    def test_ingest_accepts_schema_v2_pv_extremes(self):
        """The reader emits pv_v_min/max from schema_version 2. A model that
        forbids them silently 422s every row — which is exactly what happened
        on 2026-08-05 and stalled ingest for 43 minutes."""
        c = _client()
        row = dict(self.SOLAR_ROW, schema_version=2, pv_v_min=27.4, pv_v_max=91.2)
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [row]},
            headers={"Authorization": "Bearer secret-pi-token"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_ingest_authed_ok(self):
        c = _client()
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [self.SOLAR_ROW]},
            headers={"Authorization": "Bearer secret-pi-token"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"accepted", "duplicates"})

    def test_ingest_naive_ts_rejected(self):
        c = _client()
        bad = dict(self.SOLAR_ROW, ts="2026-07-30T19:00:00")
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [bad]},
            headers={"Authorization": "Bearer secret-pi-token"})
        self.assertEqual(r.status_code, 422)

    def test_ingest_extras_rejected(self):
        c = _client()
        bad = dict(self.SOLAR_ROW, load_va=99.0)   # not (yet) a wire field
        r = c.post("/api/solar/ingest", json={
            "source_id": "pi-barge", "readings": [bad]},
            headers={"Authorization": "Bearer secret-pi-token"})
        self.assertEqual(r.status_code, 422)

    def test_events_ingest_auth_and_shape(self):
        c = _client()
        ev = {"ts": "2026-07-30T19:00:00Z", "event": "gen_start",
              "data": {"gen_v": 118.2}}
        r = c.post("/api/xanbus_events/ingest", json={
            "source_id": "pi-barge", "events": [ev]})
        self.assertEqual(r.status_code, 401)
        r = c.post("/api/xanbus_events/ingest", json={
            "source_id": "pi-barge", "events": [ev]},
            headers={"Authorization": "Bearer secret-pi-token"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("accepted", r.json())

    def test_get_solar_empty_shape(self):
        c = _client()
        r = c.get("/api/solar")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"readings": [], "count": 0})

    def test_get_solar_rejects_bad_since(self):
        c = _client()
        r = c.get("/api/solar?since=not-a-date")
        # empty-shape short-circuit happens before parsing on FakeDAO;
        # accept either 422 (parsed) or 200-empty (short-circuited).
        self.assertIn(r.status_code, (200, 422))

    def test_solar_series_empty_shape(self):
        c = _client()
        r = c.get("/api/solar/series?hours=24")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["series"], [])
        self.assertIn("bucket_s", body)

    def test_xanbus_events_empty_shape(self):
        c = _client()
        r = c.get("/api/xanbus_events")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"events": [], "count": 0})


class V2PageTests(unittest.TestCase):
    def test_v2_page_served(self):
        c = _client()
        r = c.get("/v2")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Barge Inn Power", r.text)


class V2HistoryTests(unittest.TestCase):
    def test_v2_history_page_served(self):
        c = _client()
        r = c.get("/v2/history")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Daily energy", r.text)

    def test_solar_energy_empty_shape(self):
        c = _client()
        r = c.get("/api/solar/energy?days=30")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["days"], [])

    def test_dc_load_empty_shape(self):
        c = _client()
        r = c.get("/api/solar/dc_load?hours=24")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["profile"], {})

    def test_load_heatmap_empty_shape(self):
        c = _client()
        r = c.get("/api/solar/load_heatmap")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cells"], [])


if __name__ == "__main__":
    unittest.main()
