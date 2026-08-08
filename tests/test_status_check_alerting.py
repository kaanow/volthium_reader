"""The alerting section of status_check.

Point of this section: the staleness and event monitors are silently disabled
when STALENESS_WEBHOOK_URL is unset, and until 2026-08-08 nothing observable
distinguished "armed and quiet" from "never configured". Discovering that at
the moment something needed to page is discovering it when nobody is looking.
"""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import status_check as S   # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serving(body: bytes):
    return mock.patch.object(S.urllib.request, "urlopen",
                             lambda *a, **k: _Resp(body))


class AlertingSectionTests(unittest.TestCase):

    def test_armed_is_quiet(self):
        with _serving(b"ok alerting=on"):
            notable, lines = S.section_alerting()
        self.assertFalse(notable)
        self.assertIn("armed", " ".join(lines))

    def test_disarmed_is_NOTABLE(self):
        """The whole reason the section exists. This must not be quiet."""
        with _serving(b"ok alerting=off"):
            notable, lines = S.section_alerting()
        self.assertTrue(notable, "a disabled alerter must be flagged")
        self.assertIn("NOT ARMED", " ".join(lines))

    def test_old_server_is_unknown_not_a_fault(self):
        """A deploy predating the flag answers a bare 'ok'. That is missing
        information, not a failure, and must not cry wolf."""
        with _serving(b"ok"):
            notable, lines = S.section_alerting()
        self.assertFalse(notable)
        self.assertIn("unknown", " ".join(lines))

    def test_unreachable_is_notable(self):
        def boom(*a, **k):
            raise urllib.error.URLError("refused")
        with mock.patch.object(S.urllib.request, "urlopen", boom):
            notable, lines = S.section_alerting()
        self.assertTrue(notable)
        self.assertIn("unreachable", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
