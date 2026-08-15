"""The alerting section of status_check.

Point of this section: the staleness and event monitors are silently disabled
when STALENESS_WEBHOOK_URL is unset, and until 2026-08-08 nothing observable
distinguished "armed and quiet" from "never configured". Discovering that at
the moment something needed to page is discovering it when nobody is looking.
"""
from __future__ import annotations

import datetime as dt
import inspect
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



class DeadEventFamilyTests(unittest.TestCase):
    """A retired event source must not read as a healthy quiet one.

    Every family section_events() watches — wedge_snapshot, stack_health,
    recovery_skipped, ambient_burst — is emitted only by the BLE logger
    (scripts/log.py, volthium/pack.py), retired 2026-07-26. Confirmed against
    the live DB: last seen 07-25T13:57, 07-26T05:55, 07-25T13:55, 07-25T13:57.

    So the section printed "wedge_snapshot: none" and "stack_health: 0 events,
    all clean" on every run for sixteen days and could not print anything else.
    Second instance of the volthium-logger precedent in this same file, and the
    2-hourly operator prompt asks specifically about wedge_snapshot.

    Nothing is hardcoded as dead — liveness is asked of the database — so these
    tests drive the behaviour from fetched data, both ways.
    """

    def _events(self, mapping):
        """mapping: kind -> list of ts strings, newest first."""
        def fake(kind, since_iso, limit=10_000):
            evs = [{"ts": t, "data": {}} for t in mapping.get(kind, [])]
            return evs if since_iso is None else [
                e for e in evs if e["ts"] >= since_iso]
        return mock.patch.object(S, "fetch_events", fake)

    def test_all_families_dead_says_so_loudly(self):
        old = "2026-07-25T13:57:29Z"
        with self._events({k: [old] for k in S.WATCHED_EVENT_FAMILIES}):
            _, lines = S.section_events("2026-08-11T00:00:00Z")
        text = " ".join(lines)
        self.assertIn("DEAD", text)
        self.assertIn("2026-07-25T13:57", text, "must name when it died")
        self.assertNotIn("all clean", text,
                         "a dead source must never render a clean line")
        self.assertNotIn("wedge_snapshot: none", text)

    def test_a_live_family_reports_normally(self):
        """The positive branch. Without it, 'DEAD' could be unconditional and
        this suite would pass a check that can only say one thing."""
        now = "2026-08-11T09:00:00Z"
        with self._events({k: [now] for k in S.WATCHED_EVENT_FAMILIES}):
            _, lines = S.section_events("2026-08-11T00:00:00Z")
        text = " ".join(lines)
        self.assertNotIn("DEAD", text)
        self.assertIn("stack_health", text)

    def test_a_family_that_never_existed_is_not_silently_fine(self):
        with self._events({}):
            _, lines = S.section_events("2026-08-11T00:00:00Z")
        self.assertIn("DEAD", " ".join(lines))

    def test_partial_death_is_annotated_not_hidden(self):
        """One dead family among live ones must still be called out."""
        m = {k: ["2026-08-11T09:00:00Z"] for k in S.WATCHED_EVENT_FAMILIES}
        m["wedge_snapshot"] = ["2026-07-25T13:57:29Z"]
        with self._events(m):
            _, lines = S.section_events("2026-08-11T00:00:00Z")
        text = " ".join(lines)
        self.assertNotIn("DEAD", text, "not every family is dead")
        self.assertIn("no producer since", text)
        self.assertIn("wedge_snapshot", text)

    def test_fetch_events_accepts_no_window(self):
        """The liveness probe passes since_iso=None; the old signature would
        have raised comparing str to None."""
        with mock.patch.object(S, "_get_json",
                               lambda p: {"events": [{"ts": "2026-01-01T00:00:00Z"}]}):
            self.assertEqual(len(S.fetch_events("x", None)), 1)
            self.assertEqual(len(S.fetch_events("x", "2030-01-01T00:00:00Z")), 0)

class SolarFreshnessTests(unittest.TestCase):
    """The solar freshness check, and why its threshold is not 2 minutes.

    This lived only in the operator's 2-hourly prompt — "GET /api/solar?limit=2,
    confirm rows are FRESH (<2 min)" — hand-run every time and never codified.
    Both halves were wrong:

      * the reader uploads in 300 s batches (xanbus_telemetry.UPLOAD_PERIOD_S),
        so lag is a sawtooth 0..300 s. Measured 2026-08-11 at 45 s intervals:
        31, 76, 121, 166, 212, 257, then reset. A 2-minute rule cries wolf
        about 60% of the time.
      * /api/solar returns OLDEST-FIRST, so limit=2 hands back the two OLDEST
        rows of the slice. The recipe measured the wrong rows.
    """

    def _serve(self, rows):
        return mock.patch.object(S, "_get_json", lambda p: {"readings": rows})

    def _row(self, ts, **kw):
        r = {"ts": ts, "schema_version": 2, "pv_v_min": 1.0, "pv_v_max": 2.0,
             "pv_v": 1.5}
        r.update(kw)
        return r

    def _ago(self, secs):
        t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=secs)
        return t.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_one_batch_of_lag_is_normal_not_an_alarm(self):
        """The regression the prompt's 2-minute rule would have produced."""
        with self._serve([self._row(self._ago(240))]):
            notable, lines = S.section_solar("pi-barge")
        self.assertFalse(notable, "240s is inside one 300s batch — not a fault")
        self.assertIn("normal", " ".join(lines))

    def test_a_real_backlog_is_notable(self):
        with self._serve([self._row(self._ago(1800))]):
            notable, lines = S.section_solar("pi-barge")
        self.assertTrue(notable)
        self.assertIn("BACKLOG", " ".join(lines))

    def test_it_uses_the_newest_row_not_the_first(self):
        """OLDEST-FIRST ordering. Taking rows[0] would call this stale."""
        rows = [self._row(self._ago(9000)), self._row(self._ago(30))]
        with self._serve(rows):
            notable, lines = S.section_solar("pi-barge")
        self.assertFalse(notable, "took the oldest row instead of the newest")
        self.assertIn("lag 3", " ".join(lines))

    def test_schema_skew_is_caught(self):
        with self._serve([self._row(self._ago(30), pv_v_min=None)]):
            notable, lines = S.section_solar("pi-barge")
        self.assertTrue(notable)
        self.assertIn("pv_v_min", " ".join(lines))
        with self._serve([self._row(self._ago(30), schema_version=1)]):
            notable, lines = S.section_solar("pi-barge")
        self.assertTrue(notable)
        self.assertIn("skew", " ".join(lines))

    def test_no_rows_is_notable(self):
        with self._serve([]):
            notable, lines = S.section_solar("pi-barge")
        self.assertTrue(notable)

    def test_threshold_is_derived_from_the_reader_not_hardcoded(self):
        """If UPLOAD_PERIOD_S changes, this check must move with it."""
        import xanbus_telemetry as X
        self.assertEqual(X.UPLOAD_PERIOD_S, 300)
        src = inspect.getsource(S.section_solar)
        self.assertIn("UPLOAD_PERIOD_S", src,
                      "batch threshold must come from the reader's constant")

class TimerCheckTests(unittest.TestCase):
    """Timers were never checked at all until 2026-08-12.

    `_parse_units` looks only at services, on the reasoning that a timer being
    inactive between firings is normal. True, and it meant nothing watched the
    timers themselves — the latch guard and the config watch are both timers,
    either could be disabled, and this tool would still print a quiet window.
    Third instance of the volthium-logger precedent in one file.
    """

    def _out(self, *rows):
        return "\n".join(f"TIMER {a} {b} {c}" for a, b, c in rows) + "\n"

    def test_all_active_is_quiet(self):
        notable, lines = S._check_timers(self._out(
            ("volthium-latch-guard.timer", "active", "300"),
            ("volthium-config-watch.timer", "active", "2580")))
        self.assertFalse(notable)
        self.assertIn("2 of 2 ACTIVE", " ".join(lines))

    def test_a_disabled_guard_is_NOTABLE(self):
        """The failure the check exists for. Must not stay green."""
        notable, lines = S._check_timers(self._out(
            ("volthium-latch-guard.timer", "inactive", "300"),
            ("volthium-config-watch.timer", "active", "60")))
        self.assertTrue(notable, "a disarmed latch guard must be flagged")
        text = " ".join(lines)
        self.assertIn("NOT ARMED", text)
        self.assertIn("volthium-latch-guard.timer", text)

    def test_failed_state_is_notable(self):
        notable, lines = S._check_timers(self._out(
            ("volthium-config-watch.timer", "failed", "-1")))
        self.assertTrue(notable)
        self.assertIn("NOT ARMED", " ".join(lines))

    def test_empty_probe_is_NOT_treated_as_no_timers(self):
        """'The probe told us nothing' and 'there are no timers' must not read
        the same. Conflating them is how a monitor goes quietly blind."""
        notable, lines = S._check_timers("")
        self.assertTrue(notable)
        self.assertIn("NOT the same", " ".join(lines))

    def test_ages_are_reported_for_eyeballing(self):
        _, lines = S._check_timers(self._out(
            ("volthium-latch-guard.timer", "active", "18000")))
        self.assertIn("300 min ago", " ".join(lines))

    def test_never_fired_says_so(self):
        _, lines = S._check_timers(self._out(
            ("volthium-latch-guard.timer", "active", "-1")))
        self.assertIn("never fired", " ".join(lines))

    def test_age_is_not_silently_thresholded(self):
        """A wildly stale timer is PRINTED, not flagged — the timers here span
        5 min to monthly and any single bound would be wrong. If someone later
        adds a threshold, this test should be replaced deliberately, not left
        to pass by accident."""
        notable, _ = S._check_timers(self._out(
            ("volthium-weekly-reboot.timer", "active", "900000")))
        self.assertFalse(notable)

if __name__ == "__main__":
    unittest.main()


class GitSyncCheckTests(unittest.TestCase):
    """Is the Pi running the code that is in git?

    It drifted for two weeks and nothing noticed: deployments were file copies,
    so the working tree crept forward while HEAD stayed at an early-August
    commit — 143 behind when it was finally caught, and caught by eye rather
    than by any check. "What is on the Pi" was unanswerable from git, which is
    the entire reason git is on the Pi.
    """

    def _probe(self, head, origin, behind, dirty, paths=()):
        return (f"HEAD={head} ORIGIN={origin} BEHIND={behind} DIRTY={dirty}\n"
                + "".join(p + "\n" for p in paths))

    def test_in_sync_is_quiet(self):
        notable, lines = S._check_git_sync(self._probe("19e92e5", "19e92e5", 0, 0))
        self.assertFalse(notable)
        self.assertIn("IN SYNC", " ".join(lines))

    def test_behind_is_NOTABLE(self):
        """The actual failure: HEAD stale, tree never updated."""
        notable, lines = S._check_git_sync(self._probe("4c59d33", "19e92e5", 143, 0))
        self.assertTrue(notable)
        text = " ".join(lines)
        self.assertIn("OUT OF SYNC", text)
        self.assertIn("143", text)

    def test_dirty_is_NOTABLE_even_when_not_behind(self):
        """A hand-edit on a current checkout is the other failure mode — it
        gets silently clobbered by the next sync, so it must be flagged."""
        notable, lines = S._check_git_sync(
            self._probe("19e92e5", "19e92e5", 0, 2,
                        ["scripts/xanbus_telemetry.py", "scripts/log.py"]))
        self.assertTrue(notable)
        text = " ".join(lines)
        self.assertIn("2 code files differ", text)
        self.assertIn("xanbus_telemetry.py", text)

    def test_empty_probe_is_not_silently_fine(self):
        notable, lines = S._check_git_sync("")
        self.assertTrue(notable)
        self.assertIn("cannot confirm", " ".join(lines))

    def test_data_is_excluded_from_the_probe(self):
        """data/ is tracked on purpose and permanently dirty. Without the
        exclusion this cries wolf every run and gets ignored within a day."""
        src = inspect.getsource(S.section_pi)
        self.assertIn("':!data'", src)

    def test_a_FAILED_fetch_can_never_report_in_sync(self):
        """The bug this check itself had on 2026-08-15.

        The probe wrote `git fetch ... 2>/dev/null;` and ignored the exit
        status, so when fetch failed (root-owned .git/objects dirs from an old
        sudo'd git run, group-unwritable, unpack-objects refused) the
        comparison ran against a STALE origin/main and printed
        'IN SYNC with 19e92e5' while the Pi was 4 commits behind.

        A stale ref makes BEHIND and DIRTY meaningless, so the only honest
        answer is UNKNOWN.
        """
        notable, lines = S._check_git_sync(
            "FETCH=128 HEAD=19e92e5 ORIGIN=19e92e5 BEHIND=0 DIRTY=0\n"
            "fatal: failed to write object\n")
        self.assertTrue(notable)
        text = " ".join(lines)
        self.assertIn("UNKNOWN", text)
        self.assertNotIn("IN SYNC", text)
        self.assertIn("failed to write object", text)

    def test_a_successful_fetch_still_reports_normally(self):
        notable, lines = S._check_git_sync(
            "FETCH=0 HEAD=bac6ba8 ORIGIN=bac6ba8 BEHIND=0 DIRTY=0\n")
        self.assertFalse(notable)
        self.assertIn("IN SYNC", " ".join(lines))
