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
