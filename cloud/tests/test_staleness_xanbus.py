"""Xanbus alert rules on EventAlertMonitor.

Why these exist: `xanbus_config_watch.py` was built on 2026-08-06 because a
4.0 V/cell equalize setting is one UI click from returning "and nothing
currently alarms on it". It detected changes — into a table nothing watched.
The paging path was armed and working the whole time against `ble_events`;
it simply was not wired to the newest detector.

The half of this that is easy to get wrong is what must NOT alert. Ordinary
latches happen most days and the guard clears them unattended; paging on
routine self-healing teaches an operator to ignore the channel, and then the
message that matters arrives buried.
"""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone

from cloud.server.staleness import EventAlertMonitor


class _FakeClient:
    def __init__(self):
        self.posts: list[dict] = []

    async def post(self, url, json=None, timeout=None):
        self.posts.append({"url": url, "json": json})

        class _Resp:
            status_code = 200
        return _Resp()


class _FakeDAO:
    """Serves both streams. recent_xanbus_events takes a comma-separated
    list, matching the real DAO after the 2026-08-07 change."""

    def __init__(self):
        self.xanbus: list[dict] = []
        self.alarms: list[dict] = []

    async def sources(self):
        return ["pi-barge"]

    async def recent_events(self, source_id, event, since, limit):
        return []

    async def history_alarms(self, source_id, since):
        return list(self.alarms)

    async def recent_xanbus_events(self, source_id, event, since, limit):
        names = {e.strip() for e in (event or "").split(",") if e.strip()}
        return [e for e in self.xanbus
                if (not names or e["event"] in names) and e["ts"] >= since][:limit]

    def add(self, event: str, data: dict, ts: datetime | None = None):
        self.xanbus.insert(0, {
            "source_id": "pi-barge", "event": event,
            "ts": ts or datetime.now(timezone.utc), "data": data,
        })


def _run(dao) -> _FakeClient:
    mon = EventAlertMonitor(dao, "https://ntfy.example/topic",
                            check_interval_s=60.0)
    client = _FakeClient()
    asyncio.run(mon.check_once(client))
    return client


def _run_twice(dao) -> _FakeClient:
    mon = EventAlertMonitor(dao, "https://ntfy.example/topic",
                            check_interval_s=60.0)
    client = _FakeClient()
    asyncio.run(mon.check_once(client))
    asyncio.run(mon.check_once(client))
    return client


class XanbusAlertTests(unittest.TestCase):

    def test_config_change_pages_at_max_priority(self):
        """The whole reason this was written."""
        dao = _FakeDAO()
        dao.add("xanbus_config_changed",
                {"changes": [{"field": "mppt_equalize"}]})
        posts = _run(dao).posts
        self.assertEqual(len(posts), 1)
        body = posts[0]["json"]
        self.assertEqual(body["priority"], 5)
        self.assertIn("CHARGE SETPOINT CHANGED", body["title"])
        self.assertIn("mppt_equalize", body["message"])
        # The operator needs to know WHY it matters, not just that it moved.
        self.assertIn("4.0 V/cell", body["message"])

    def test_guard_denied_pages(self):
        dao = _FakeDAO()
        dao.add("latch_fix_denied", {"acks": []})
        posts = _run(dao).posts
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["json"]["priority"], 4)
        # It must say what the human has to do.
        self.assertIn("Standby", posts[0]["json"]["message"])

    def test_routine_latch_does_NOT_page(self):
        """mppt_latched happens most days and the guard clears it in ~20 min.
        Paging on it is how the channel becomes noise."""
        dao = _FakeDAO()
        dao.add("mppt_latched", {"pv_v": 27.4, "delta_v": 0.8})
        dao.add("latch_detected", {"fraction": 1.0})
        dao.add("latch_fix_result", {"recovered": True})
        self.assertEqual(_run(dao).posts, [])

    def test_same_event_does_not_page_twice(self):
        """The monitor polls on an interval and the window overlaps, so the
        same row is seen repeatedly."""
        dao = _FakeDAO()
        dao.add("xanbus_config_changed", {"changes": [{"field": "bulk_v"}]})
        self.assertEqual(len(_run_twice(dao).posts), 1)

    def test_missing_dao_method_is_survivable(self):
        """A DB-less deploy has no recent_xanbus_events. Skip, do not crash —
        the rest of this monitor degrades the same way."""
        class _Old:
            async def sources(self):
                return ["pi-barge"]

            async def recent_events(self, *a, **kw):
                return []
        self.assertEqual(_run(_Old()).posts, [])

    def test_query_failure_does_not_kill_the_sweep(self):
        """A broken xanbus query must not stop the BLE rules from running."""
        class _Broken(_FakeDAO):
            async def recent_xanbus_events(self, *a, **kw):
                raise RuntimeError("column does not exist")
        self.assertEqual(_run(_Broken()).posts, [])


class BmsAlarmTests(unittest.TestCase):
    """BMS protection alarms were decoded and shown on /history from the start
    and paged nobody. 16 episodes were already on record — every one
    cell_overvoltage on battery A — including the disconnects that started the
    MPPT investigation. The pack protected itself eight times in silence."""

    def test_cell_overvoltage_pages_at_max_priority(self):
        dao = _FakeDAO()
        dao.alarms = [{"bat": "A", "codes": 0x004}]
        posts = _run(dao).posts
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["json"]["priority"], 5)
        self.assertIn("Battery A", posts[0]["json"]["title"])
        self.assertIn("cell_overvoltage", posts[0]["json"]["title"])

    def test_fragmented_episodes_collapse_to_one_page(self):
        """08-01 produced four episodes inside three minutes. That is one
        event, and it must not be four notifications."""
        dao = _FakeDAO()
        dao.alarms = [{"bat": "A", "codes": 0x004}] * 4
        self.assertEqual(len(_run(dao).posts), 1)

    def test_charge_undertemp_pages(self):
        """Never fired — summer baseline is 16-26 C. It is the one that will,
        months from now, at 51 N with nobody on site."""
        dao = _FakeDAO()
        dao.alarms = [{"bat": "B", "codes": 0x200}]
        posts = _run(dao).posts
        self.assertEqual(len(posts), 1)
        self.assertIn("charge_undertemp", posts[0]["json"]["title"])

    def test_multiple_flags_take_the_worst_priority(self):
        dao = _FakeDAO()
        dao.alarms = [{"bat": "A", "codes": 0x004 | 0x100}]
        self.assertEqual(_run(dao).posts[0]["json"]["priority"], 5)

    def test_no_alarms_no_pages(self):
        self.assertEqual(_run(_FakeDAO()).posts, [])

    def test_missing_dao_method_is_survivable(self):
        class _Old:
            async def sources(self):
                return ["pi-barge"]

            async def recent_events(self, *a, **kw):
                return []
        self.assertEqual(_run(_Old()).posts, [])


if __name__ == "__main__":
    unittest.main()
