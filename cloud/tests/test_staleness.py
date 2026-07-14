"""Tests for cloud.server.staleness.StalenessMonitor.

We drive check_once() directly with a fake DAO and stub out httpx.AsyncClient
so the tests don't hit the network. Focus: only transitions fire alerts;
payload shape is stable across fresh↔stale flips; never-uploaded sources
are ignored.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloud.server.staleness import StalenessMonitor   # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeDAO:
    def __init__(self):
        # latest ts per source, or None if source has never uploaded
        self._latest: dict[str, Optional[datetime]] = {}

    def set_latest(self, source_id: str, ts: Optional[datetime]):
        self._latest[source_id] = ts

    async def sources(self) -> list[str]:
        return sorted(self._latest.keys())

    async def recent(self, source_id: Optional[str], limit: int) -> list[dict]:
        if source_id is None:
            return []
        ts = self._latest.get(source_id)
        if ts is None:
            return []
        return [{"ts": ts}]


class _FakeClient:
    """Records POST calls; never actually sends. Async context-manager
    compatible so the monitor's own httpx.AsyncClient() context works if
    tests want to exercise the loop path too."""

    def __init__(self):
        self.posts: list[dict] = []

    async def post(self, url, json=None, timeout=None):
        self.posts.append({"url": url, "json": json})
        class _Resp:
            status_code = 200
        return _Resp()


def _monitor(dao, url="https://ntfy.example/topic", threshold_s=300.0):
    return StalenessMonitor(dao, url, threshold_s, check_interval_s=60.0)


class TransitionTests(unittest.TestCase):

    def test_no_alert_on_first_fresh_check(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        client = _FakeClient()
        m = _monitor(dao)
        _run(m.check_once(client))
        self.assertEqual(len(client.posts), 0)

    def test_fires_on_fresh_to_stale(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)
        _run(m.check_once(client))                           # fresh -> no alert
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=200))
        _run(m.check_once(client))                           # now stale -> alert
        self.assertEqual(len(client.posts), 1)
        body = client.posts[0]["json"]
        self.assertIn("stale", body["title"])
        self.assertEqual(body["priority"], 4)
        self.assertIn("warning", body["tags"])

    def test_fires_on_stale_to_fresh_recovery(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=600))
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)
        _run(m.check_once(client))                           # stale on first check
        self.assertEqual(len(client.posts), 1)
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        _run(m.check_once(client))                           # recovered
        self.assertEqual(len(client.posts), 2)
        recovery = client.posts[1]["json"]
        self.assertIn("recovered", recovery["title"])

    def test_no_alert_while_stale_repeats(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=600))
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)
        _run(m.check_once(client))
        _run(m.check_once(client))
        _run(m.check_once(client))
        # Only one alert — for the initial transition.
        self.assertEqual(len(client.posts), 1)

    def test_never_uploaded_source_is_ignored(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge", None)   # never received data
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)
        _run(m.check_once(client))
        self.assertEqual(len(client.posts), 0)

    def test_multiple_sources_tracked_independently(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        dao.set_latest("esp32-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=600))
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)
        _run(m.check_once(client))
        # Only esp32-barge fired.
        self.assertEqual(len(client.posts), 1)
        self.assertIn("esp32-barge", client.posts[0]["json"]["title"])


class DisabledTests(unittest.TestCase):

    def test_start_noops_without_webhook(self):
        dao = _FakeDAO()
        m = StalenessMonitor(dao, webhook_url="",
                             threshold_s=300.0, check_interval_s=60.0)
        _run(m.start())
        # No background task started
        self.assertIsNone(m._task)
        _run(m.stop())   # should be a no-op


class _FakeEventsDAO:
    """recent_events fake: event kind → list of {ts, event, data} dicts."""

    def __init__(self):
        self._events: dict[str, list[dict]] = {}

    def add(self, event: str, ts: datetime, data: dict):
        self._events.setdefault(event, []).insert(0, {
            "source_id": "pi-barge", "ts": ts, "event": event, "data": data,
        })

    async def recent_events(self, source_id, event, since, limit):
        return [e for e in self._events.get(event, [])
                if e["ts"] >= since][:limit]


class StaleDiagnosisTests(unittest.TestCase):
    """The stale alert must carry a likely-cause hint composed from the
    reader's recent ble_events — the operator asked for exactly this after
    the 2026-07-12/13 outage ('alerts should contain a hint about what the
    issue is')."""

    def _go_stale(self, events_dao) -> dict:
        """Run a fresh→stale transition and return the alert payload."""
        dao = _FakeDAO()
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        client = _FakeClient()
        m = StalenessMonitor(
            dao, "https://ntfy.example/topic", threshold_s=60.0,
            check_interval_s=60.0, events_dao=events_dao,
        )
        _run(m.check_once(client))
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=200))
        _run(m.check_once(client))
        assert len(client.posts) == 1
        return client.posts[0]["json"]

    def test_wedge_classification_lands_in_alert(self):
        ev = _FakeEventsDAO()
        ev.add("wedge_snapshot",
               datetime.now(timezone.utc) - timedelta(minutes=6),
               {"classification": "bluez_adapter_object_missing",
                "recovery_level": 3, "reason": "BleakError: ..."})
        body = self._go_stale(ev)
        self.assertIn("bluez_adapter_object_missing", body["message"])
        self.assertIn("Likely cause", body["message"])
        # The mini-runbook hint rides along.
        self.assertIn("replug", body["message"].lower())

    def test_fallback_and_replug_context_included(self):
        now = datetime.now(timezone.utc)
        ev = _FakeEventsDAO()
        ev.add("adapter_fallback_active", now - timedelta(minutes=10),
               {"resolved": "hci1", "primary_fail_reason": "..."})
        ev.add("usb_replug", now - timedelta(minutes=4), {"ok": True})
        body = self._go_stale(ev)
        self.assertIn("fallback adapter", body["message"])
        self.assertIn("USB-replug", body["message"])

    def test_silent_reader_is_called_out(self):
        # No diagnostics at all → the alert must say the Pi itself may be
        # offline, which changes what the operator does first.
        body = self._go_stale(_FakeEventsDAO())
        self.assertIn("No reader diagnostics", body["message"])

    def test_healthy_diagnostics_point_at_uploader(self):
        ev = _FakeEventsDAO()
        ev.add("stack_health",
               datetime.now(timezone.utc) - timedelta(minutes=3),
               {"classification": "unclassified"})
        body = self._go_stale(ev)
        self.assertIn("uploader", body["message"])

    def test_no_events_dao_still_alerts(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=600))
        client = _FakeClient()
        m = _monitor(dao, threshold_s=60.0)   # events_dao omitted
        _run(m.check_once(client))
        self.assertEqual(len(client.posts), 1)

    def test_diagnosis_failure_never_blocks_the_alert(self):
        class _BrokenEventsDAO:
            async def recent_events(self, *a, **kw):
                raise RuntimeError("db down")
        dao = _FakeDAO()
        dao.set_latest("pi-barge",
                       datetime.now(timezone.utc) - timedelta(seconds=600))
        client = _FakeClient()
        m = StalenessMonitor(
            dao, "https://ntfy.example/topic", threshold_s=60.0,
            check_interval_s=60.0, events_dao=_BrokenEventsDAO(),
        )
        _run(m.check_once(client))
        self.assertEqual(len(client.posts), 1)


class _BattDAO:
    """Fake DAO whose rows carry per-battery fields (newest-first)."""

    def __init__(self):
        self.rows: list[dict] = []

    def build(self, minutes_b_absent: float, span_min: float = 25.0):
        """Rows every ~30 s for `span_min` minutes; battery B's fields are
        None for the newest `minutes_b_absent` minutes."""
        now = datetime.now(timezone.utc)
        self.rows = []
        t = now
        while (now - t).total_seconds() / 60 <= span_min:
            absent = (now - t).total_seconds() / 60 < minutes_b_absent
            self.rows.append({
                "ts": t, "soc_a": 95.0, "v_a": 13.2, "i_a": -3.0,
                "soc_b": None if absent else 81.0,
                "v_b": None if absent else 13.1,
                "i_b": None if absent else -3.0,
                "name_b": None if absent else "V-12V200AH-0667",
            })
            t = t - timedelta(seconds=30)

    async def sources(self):
        return ["pi-barge"]

    async def recent(self, source_id, limit):
        return self.rows[:limit]


class BatterySilenceTests(unittest.TestCase):
    """One battery vanishing from otherwise-flowing telemetry (FM-6) must
    page after the dwell threshold — and announce recovery with duration.
    Micro-blips (B misses single scan cycles constantly) must not page."""

    def _monitor(self, dao):
        return StalenessMonitor(dao, "https://ntfy.example/topic",
                                threshold_s=300.0, check_interval_s=60.0)

    def test_prolonged_silence_fires_once(self):
        dao = _BattDAO()
        dao.build(minutes_b_absent=20)
        client = _FakeClient()
        m = self._monitor(dao)
        _run(m.check_once(client))
        _run(m.check_once(client))   # still silent — no refire
        batt = [p for p in client.posts if "battery B" in p["json"]["title"]]
        self.assertEqual(len(batt), 1)
        self.assertIn("silent", batt[0]["json"]["title"])
        self.assertIn("FM-6", batt[0]["json"]["message"])
        self.assertIn("inverter breakers", batt[0]["json"]["message"])

    def test_brief_blip_does_not_fire(self):
        dao = _BattDAO()
        dao.build(minutes_b_absent=3)
        client = _FakeClient()
        _run(self._monitor(dao).check_once(client))
        self.assertEqual(client.posts, [])

    def test_recovery_fires_with_duration(self):
        dao = _BattDAO()
        dao.build(minutes_b_absent=20)
        client = _FakeClient()
        m = self._monitor(dao)
        _run(m.check_once(client))          # silent alert
        dao.build(minutes_b_absent=0)       # B is back
        _run(m.check_once(client))
        backs = [p for p in client.posts if "battery B back" in p["json"]["title"]]
        self.assertEqual(len(backs), 1)
        self.assertIn("advertising again", backs[0]["json"]["message"])

    def test_stale_source_suppresses_battery_alert(self):
        # When ALL telemetry stopped, the stale alert owns the page — a
        # battery-silence page on top would be noise.
        dao = _BattDAO()
        dao.build(minutes_b_absent=20)
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        for i, r in enumerate(dao.rows):
            r["ts"] = old - timedelta(seconds=30 * i)
        client = _FakeClient()
        _run(self._monitor(dao).check_once(client))
        titles = [p["json"]["title"] for p in client.posts]
        self.assertTrue(any("stale" in t for t in titles))
        self.assertFalse(any("battery" in t for t in titles))

    def test_rows_without_battery_fields_disengage(self):
        dao = _FakeDAO()
        dao.set_latest("pi-barge", datetime.now(timezone.utc))
        client = _FakeClient()
        _run(self._monitor(dao).check_once(client))
        self.assertEqual(client.posts, [])


class ParseTests(unittest.TestCase):

    def test_iso_string_and_datetime_both_accepted(self):
        from cloud.server.staleness import _parse_ts
        s = "2026-07-01T15:00:00Z"
        d = datetime(2026, 7, 1, 15, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(_parse_ts(s), d)
        self.assertEqual(_parse_ts(d), d)
        self.assertIsNone(_parse_ts("nonsense"))
        self.assertIsNone(_parse_ts(None))


if __name__ == "__main__":
    unittest.main()
