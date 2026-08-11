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


class SecondPagingPathTests(unittest.TestCase):
    """There are two paging paths and they fail separately.

      A. cloud -> ntfy, gated on STALENESS_WEBHOOK_URL, visible via /healthz
      B. Pi -> webhook when the CLOUD is unreachable, gated on
         VOLTHIUM_ALERT_WEBHOOK in the uploader's environment

    B exists because A cannot page about its own outage. Until 2026-08-11 this
    section asked only A and printed "staleness + event alerts armed", which
    reads as all-clear; B had never been armed. Verified against the live Pi
    that day: `systemctl show volthium-uploader -p Environment` is empty.
    """

    def _ssh(self, out: str):
        return mock.patch.object(S.subprocess, "check_output",
                                 lambda *a, **k: out)

    def test_A_armed_alone_never_reads_as_all_clear(self):
        """The actual regression. Path A green must not imply B."""
        with _serving(b"ok alerting=on"):
            _, lines = S.section_alerting()
        text = " ".join(lines)
        self.assertIn("UNVERIFIED", text,
                      "B must be reported, not omitted, when it wasn't checked")
        self.assertIn("B pi->webhook", text)

    def test_B_unset_on_the_pi_is_NOTABLE(self):
        """The live state as of 2026-08-11. Must nag until it is fixed."""
        with _serving(b"ok alerting=on"), self._ssh("Environment=\n"):
            notable, lines = S.section_alerting("kaan@kwpi.zt")
        self.assertTrue(notable, "a dormant second paging path must be flagged")
        self.assertIn("NOT ARMED", " ".join(lines))

    def test_B_set_on_the_pi_is_quiet(self):
        """The positive branch — otherwise 'NOT ARMED' could be unconditional
        and this suite would happily pass a check that can only say one thing."""
        with _serving(b"ok alerting=on"), \
                self._ssh("Environment=VOLTHIUM_ALERT_WEBHOOK=https://x/y\n"):
            notable, lines = S.section_alerting("kaan@kwpi.zt")
        self.assertFalse(notable)
        self.assertNotIn("NOT ARMED", " ".join(lines))

    def test_B_never_prints_the_webhook_value(self):
        """The URL embeds a secret ntfy topic. Check output gets pasted around."""
        secret = "https://ntfy.sh/super-secret-topic-9f3a"
        with _serving(b"ok alerting=on"), \
                self._ssh(f"Environment=VOLTHIUM_ALERT_WEBHOOK={secret}\n"):
            _, lines = S.section_alerting("kaan@kwpi.zt")
        text = " ".join(lines)
        self.assertNotIn(secret, text)
        self.assertNotIn("super-secret-topic", text)

    def test_B_unreachable_pi_is_unverified_not_armed(self):
        """Must not silently downgrade to a green line when SSH fails."""
        def boom(*a, **k):
            raise OSError("no route to host")
        with _serving(b"ok alerting=on"), \
                mock.patch.object(S.subprocess, "check_output", boom):
            _, lines = S.section_alerting("kaan@kwpi.zt")
        self.assertIn("UNVERIFIED", " ".join(lines))

    def test_both_paths_are_always_named(self):
        """Whatever happens, the reader must see that there are two."""
        for body in (b"ok alerting=on", b"ok alerting=off", b"ok"):
            with self.subTest(body=body), _serving(body):
                _, lines = S.section_alerting()
                text = " ".join(lines)
                self.assertIn("A cloud->ntfy", text)
                self.assertIn("B pi->webhook", text)


if __name__ == "__main__":
    unittest.main()
