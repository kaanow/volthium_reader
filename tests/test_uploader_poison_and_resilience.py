"""A poison batch must not stall the stream, and the loop must not die.

Two findings from the 2026-10-04 review, both silent-forever failures at a
site nobody visits for weeks.

1. `except Exception: return False` made a 422 indistinguishable from a 502,
   so a batch the server will NEVER accept was retried forever and blocked
   every segment behind it. That is the 2026-08-05 incident — one unknown
   field, extra="forbid", 43 minutes of stalled solar ingest — and only the
   deploy ORDER was ever mitigated, never the mechanism.

   It is worse than 43 minutes now: Spool.seal() prunes the OLDEST sealed file
   at KEEP_SEALED=2000 x 300 s, so a poison segment yields a 6.9-DAY silent
   outage that "self-heals" by unlinking five minutes of data with no log line.

2. uploader_loop's docstring said "never raises" with no try/except anywhere
   in it. A FileNotFoundError from the KEEP_SEALED prune racing _read_jsonl
   killed the thread; the CAN loop kept spooling, Restart=always did nothing
   because the process was alive, and no WatchdogSec exists.
"""

from __future__ import annotations

import inspect
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import xanbus_telemetry as X   # noqa: E402


def _http_error(code):
    return urllib.error.HTTPError("u", code, "msg", {}, None)


class PostVerdictTests(unittest.TestCase):

    def _verdict(self, raises=None, status=200):
        class _R:
            def __init__(s): s.status = status
            def __enter__(s): return s
            def __exit__(s, *a): return False
        def fake(req, timeout=None):
            if raises:
                raise raises
            return _R()
        with mock.patch("urllib.request.urlopen", fake):
            return X._post("http://x/y", "tok", {})

    def test_success_is_ok(self):
        self.assertEqual(self._verdict(), X.POST_OK)

    def test_a_5xx_is_retryable(self):
        self.assertEqual(self._verdict(_http_error(502)), X.POST_RETRY)

    def test_a_connection_failure_is_retryable(self):
        self.assertEqual(self._verdict(OSError("refused")), X.POST_RETRY)

    def test_a_422_is_POISON_not_a_retry(self):
        """The exact 2026-08-05 shape: the server has judged the CONTENT, so
        retrying is pointless and blocks everything behind it."""
        self.assertEqual(self._verdict(_http_error(422)), X.POST_POISON)

    def test_a_400_is_poison(self):
        self.assertEqual(self._verdict(_http_error(400)), X.POST_POISON)

    def test_408_and_429_stay_retryable(self):
        """These are 4xx but they are about TIMING, not content."""
        for code in (408, 429):
            with self.subTest(code=code):
                self.assertEqual(self._verdict(_http_error(code)),
                                 X.POST_RETRY)

    def test_401_is_poison_rather_than_an_infinite_retry(self):
        """A bad token will never fix itself by retrying; quarantining makes
        it loud instead of a silent stall."""
        self.assertEqual(self._verdict(_http_error(401)), X.POST_POISON)


class QuarantineTests(unittest.TestCase):

    def test_the_drain_quarantines_rather_than_retrying_or_deleting(self):
        src = inspect.getsource(X._drain_once)
        self.assertIn("POST_POISON", src)
        self.assertIn(".poison", src,
                      "a poison segment must be moved aside, not retried")
        self.assertIn("continue", src,
                      "the queue must keep draining past a poison segment")

    def test_it_does_not_simply_delete_the_evidence(self):
        """The poison segment is the only copy of whatever exposed a schema
        mismatch. Deleting it destroys the diagnosis."""
        src = inspect.getsource(X._drain_once)
        i = src.index("POST_POISON")
        window = src[i:i + 700]
        self.assertIn("rename", window)
        self.assertNotIn("unlink", window.split("continue")[0])


class LoopResilienceTests(unittest.TestCase):

    def test_the_loop_actually_guards_itself(self):
        """"never raises" was a claim with no mechanism."""
        src = inspect.getsource(X.uploader_loop)
        self.assertIn("try:", src)
        self.assertIn("except Exception", src)
        self.assertIn("log.exception", src,
                      "a swallowed error must still be visible")

    def test_a_throwing_pass_does_not_kill_the_loop(self):
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FileNotFoundError("segment pruned mid-read")
            X._stop = True
            return 30.0

        with mock.patch.object(X, "_drain_once", boom), \
             mock.patch.object(X, "time") as t:
            t.sleep = lambda *_: None
            X._stop = False
            X.uploader_loop(None, None, "http://x", "tok", "src")
        self.assertGreaterEqual(
            calls["n"], 2,
            "the loop died on the first exception instead of retrying")
        X._stop = False


if __name__ == "__main__":
    unittest.main()
