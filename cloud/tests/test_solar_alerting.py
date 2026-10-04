"""The solar/Xanbus pipeline was watched by nothing, and alerts were never verified.

Two findings from the 2026-10-04 review, both in the worst class for a site
nobody visits for weeks.

1. NOTHING WATCHED SOLAR. StalenessMonitor walks dao.sources() + dao.recent(),
   which read the `readings` table only; EventAlertMonitor fires on specific
   event NAMES, so if xanbus events stop entirely no rule can match. The Pi
   side has no alerting on those endpoints either. So the telemetry service
   dying, can0 going down, or the spool failing to drain paged NOBODY — while
   /healthz returned alerting=on and status_check printed "armed — pages on
   stale telemetry", true only of the BMS table.

2. DELIVERY WAS NEVER VERIFIED. _fire_raw logged "alert posted" from any
   status code, so a 404 from a deleted topic or a 429 read as success. And
   the staleness transition was committed BEFORE firing, so one dropped POST
   retired that outage permanently.
"""

from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from cloud.server.staleness import StalenessMonitor


class _Resp:
    def __init__(self, code): self.status_code = code


class _Client:
    """Records posts and returns a scripted status code."""
    def __init__(self, code=200):
        self.code, self.posts = code, []

    async def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        if isinstance(self.code, Exception):
            raise self.code
        return _Resp(self.code)


class _Dao:
    def __init__(self, solar_age_s=None, readings_age_s=0):
        now = dt.datetime.now(dt.timezone.utc)
        self._solar = ([] if solar_age_s is None else
                       [{"ts": (now - dt.timedelta(seconds=solar_age_s))
                         .strftime("%Y-%m-%dT%H:%M:%SZ")}])
        self._rows = [{"ts": (now - dt.timedelta(seconds=readings_age_s))
                       .strftime("%Y-%m-%dT%H:%M:%SZ")}]

    async def sources(self): return ["pi-barge"]
    async def recent(self, src, limit): return self._rows
    async def solar_since(self, src, since, limit): return self._solar


def _mon(dao, **kw):
    return StalenessMonitor(dao, webhook_url="https://example.invalid/x",
                            threshold_s=300, check_interval_s=60, **kw)


class SolarFreshnessTests(unittest.IsolatedAsyncioTestCase):

    async def test_a_dead_solar_stream_pages_even_while_readings_flow(self):
        """The exact unwatched case: battery telemetry fine, solar dead."""
        c = _Client()
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        titles = " ".join(p["title"] for p in c.posts)
        self.assertIn("SOLAR stale", titles,
                      "a dead solar pipeline did not page")

    async def test_the_normal_batch_sawtooth_does_not_page(self):
        """The reader uploads in 300 s batches. An alert that fires every
        cycle trains the operator to ignore it."""
        for age in (30, 180, 299, 420, 600):
            with self.subTest(age_s=age):
                c = _Client()
                m = _mon(_Dao(solar_age_s=age, readings_age_s=5))
                await m.check_once(c)
                self.assertEqual(
                    [p for p in c.posts if "SOLAR" in p["title"]], [],
                    f"solar age {age}s is inside the batch sawtooth")

    async def test_the_threshold_clears_three_batches(self):
        self.assertGreaterEqual(StalenessMonitor.SOLAR_STALE_THRESHOLD_S, 900)

    async def test_recovery_is_announced(self):
        c = _Client()
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        m.dao = _Dao(solar_age_s=30, readings_age_s=5)
        await m.check_once(c)
        self.assertIn("solar recovered",
                      " ".join(p["title"] for p in c.posts))

    async def test_it_does_not_page_twice_for_one_outage(self):
        c = _Client()
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        await m.check_once(c)
        self.assertEqual(
            len([p for p in c.posts if "SOLAR stale" in p["title"]]), 1)

    async def test_a_dao_without_solar_disengages(self):
        """Minimal test fakes must not crash the sweep."""
        class Bare(_Dao):
            solar_since = None
        c = _Client()
        m = _mon(Bare(readings_age_s=5))
        await m.check_once(c)   # must not raise


class DeliveryIsVerifiedTests(unittest.IsolatedAsyncioTestCase):

    async def test_a_rejected_post_does_not_retire_the_outage(self):
        """One dropped POST used to retire the transition permanently, so the
        condition persisted unannounced."""
        c = _Client(code=404)
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        first = len([p for p in c.posts if "SOLAR stale" in p["title"]])
        await m.check_once(c)
        second = len([p for p in c.posts if "SOLAR stale" in p["title"]])
        self.assertEqual(first, 1)
        self.assertEqual(second, 2,
                         "a rejected alert must be retried, not forgotten")

    async def test_an_exception_also_retries(self):
        c = _Client(code=RuntimeError("connection reset"))
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        await m.check_once(c)
        self.assertEqual(len(c.posts), 2)

    async def test_a_delivered_alert_is_not_repeated(self):
        c = _Client(code=200)
        m = _mon(_Dao(solar_age_s=3600, readings_age_s=5))
        await m.check_once(c)
        await m.check_once(c)
        self.assertEqual(len([p for p in c.posts
                              if "SOLAR stale" in p["title"]]), 1)

    async def test_readings_staleness_also_requires_delivery(self):
        """Same bug, same fix, on the original path."""
        c = _Client(code=500)
        m = _mon(_Dao(solar_age_s=30, readings_age_s=99999))
        await m.check_once(c)
        await m.check_once(c)
        stale = [p for p in c.posts if "stale" in p["title"].lower()]
        self.assertGreaterEqual(
            len(stale), 2, "a rejected readings alert must be retried too")

    async def test_fire_raw_reports_non_2xx_as_failure(self):
        m = _mon(_Dao())
        for code, want in ((200, True), (204, True), (301, False),
                           (404, False), (429, False), (500, False)):
            with self.subTest(code=code):
                got = await m._fire_raw(
                    _Client(code=code), title="t", message="m",
                    priority=3, tags=[], context="test")
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
