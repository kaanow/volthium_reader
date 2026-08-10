"""The Pi must be able to report that the cloud is down.

The staleness monitor runs ON Railway, so the one failure it structurally
cannot report is Railway itself being unreachable — the watchdog dies with the
thing it watches. On 2026-08-09 Railway returned intermittent 502s for ~35
minutes and the only record was a WARNING in a journal nobody reads.

The half of this that is easy to get wrong is what must NOT alert. Every
Railway redeploy causes a brief 502 window — including redeploys triggered by
documentation-only commits — and paging on those teaches an operator to ignore
the channel, which is how the message that matters arrives buried.
"""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

from cloud.uploader import uploader


class _FakeClient:
    def __init__(self):
        self.posts: list[dict] = []

    async def post(self, url, json=None, timeout=None):
        self.posts.append({"url": url, "json": json})

        class _R:
            status_code = 200
        return _R()


def _alert(title="t", message="m", priority=4, url="https://ntfy.example/topic"):
    client = _FakeClient()
    env = {"VOLTHIUM_ALERT_WEBHOOK": url} if url is not None else {}
    with mock.patch.dict(os.environ, env, clear=False):
        if url is None:
            os.environ.pop("VOLTHIUM_ALERT_WEBHOOK", None)
        asyncio.run(uploader._post_alert(client, title, message, priority))
    return client


class PostAlertTests(unittest.TestCase):

    def test_sends_when_configured(self):
        posts = _alert(title="Cloud upload FAILING", priority=4).posts
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["json"]["priority"], 4)
        self.assertIn("FAILING", posts[0]["json"]["title"])

    def test_silent_when_no_webhook_configured(self):
        """An unset webhook is the default state on a fresh Pi. It must be a
        no-op, not a crash and not a log-spamming error."""
        self.assertEqual(_alert(url=None).posts, [])

    def test_a_broken_webhook_cannot_break_uploading(self):
        """Alerting is strictly best-effort. If ntfy is down too — entirely
        plausible during a wider network fault — the uploader must keep going."""
        class _Boom(_FakeClient):
            async def post(self, *a, **kw):
                raise RuntimeError("ntfy unreachable")
        with mock.patch.dict(os.environ,
                             {"VOLTHIUM_ALERT_WEBHOOK": "https://x/y"}):
            asyncio.run(uploader._post_alert(_Boom(), "t", "m", 4))  # must not raise


class ThresholdTests(unittest.TestCase):
    """The decision logic, exercised directly against the same expressions the
    upload loop uses. A blip must not page; a sustained outage must."""

    @staticmethod
    def _should_alert(down_s, alerted_at, now=10_000.0):
        due = alerted_at is None or (now - alerted_at) > uploader.ALERT_REPEAT_S
        return down_s > uploader.ALERT_AFTER_S and due

    def test_default_threshold_is_half_an_hour(self):
        self.assertEqual(uploader.ALERT_AFTER_S, 1800)

    def test_redeploy_length_outage_does_not_page(self):
        """A Railway redeploy is a few minutes. Well under the threshold, and
        in practice consecutive failures reset on the first success anyway."""
        self.assertFalse(self._should_alert(240, None))

    def test_sustained_outage_pages(self):
        self.assertTrue(self._should_alert(1801, None))

    def test_does_not_repage_immediately_while_still_down(self):
        self.assertFalse(self._should_alert(3600, alerted_at=9_990.0))

    def test_repages_after_the_repeat_window(self):
        self.assertTrue(
            self._should_alert(60_000, alerted_at=10_000.0 - uploader.ALERT_REPEAT_S - 1))

    def test_threshold_is_env_overridable(self):
        """So a site with a flakier link can raise it without a code change."""
        with open(uploader.__file__) as fh:
            self.assertIn("VOLTHIUM_UPLOAD_ALERT_AFTER_S", fh.read())


if __name__ == "__main__":
    unittest.main()
