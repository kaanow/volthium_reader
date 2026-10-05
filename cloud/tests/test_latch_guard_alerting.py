"""The latch guard's documented safety net did not exist.

xanbus_latch_guard.py states: "A fix that genuinely fails, or the cap being
reached, both page the operator now." Neither did. EventAlertMonitor's
XANBUS_RULES held only xanbus_config_changed, latch_fix_denied,
latch_fix_aborted and xanbus_config_watch_failed — none of the guard's own
outcome events appeared anywhere in cloud/server/.

THE SCENARIO: the bounce stops working (can0 brought up listen-only, an MPPT
firmware change, address-claim contention). The guard burns its 6 fixes, then
emits latch_guard_skipped every 5 minutes for the rest of each day, while the
array sits clamped at roughly 40% of production — for weeks, at a site nobody
visits, with nothing paging.

The hard part is that these events fire ROUTINELY in their success shape:
latch_fix_result is 36 successes out of 37 on record, and early_bounce_result
fires ~1.8x/day and has never failed. Alerting on the event NAME would page
daily on self-healing, which is how an operator learns to ignore the channel —
the exact reasoning the existing "deliberately NOT alerted" note gives. So
these are matched on the FAILING shape only.
"""

from __future__ import annotations

import datetime as dt
import unittest

from cloud.server.staleness import EventAlertMonitor


class _Client:
    def __init__(self): self.posts = []
    async def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        class _R: status_code = 200
        return _R()


class _Dao:
    """Enough DAO for EventAlertMonitor. The other _check_* probes read
    `recent_events`; they return nothing here so the xanbus path is isolated."""
    def __init__(self, rows): self._rows = rows
    async def sources(self): return ["pi-barge"]
    async def recent_events(self, src, event, since, limit=20): return []
    async def recent_xanbus_events(self, src, names, since, limit):
        want = set(names.split(","))
        return [r for r in self._rows if r["event"] in want]


def _ev(name, **data):
    return {"event": name,
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "data": data}


def _mon(rows):
    return EventAlertMonitor(_Dao(rows), webhook_url="https://x.invalid/t",
                             check_interval_s=60)


class ConditionalRulesTests(unittest.IsolatedAsyncioTestCase):

    async def _titles(self, rows):
        c = _Client()
        m = _mon(rows)
        await m.check_once(c)
        return " | ".join(p.get("title", "") for p in c.posts)

    async def test_a_fix_that_did_not_recover_pages(self):
        t = await self._titles([_ev("latch_fix_result", recovered=False)])
        self.assertIn("DID NOT RECOVER", t)

    async def test_a_SUCCESSFUL_fix_does_not_page(self):
        """36 of 37 on record. Paging here buries the one that matters."""
        t = await self._titles([_ev("latch_fix_result", recovered=True)])
        self.assertNotIn("DID NOT RECOVER", t)

    async def test_an_early_bounce_that_did_not_recover_pages(self):
        t = await self._titles([_ev("early_bounce_result", recovered=False)])
        self.assertIn("DID NOT RECOVER", t)

    async def test_a_result_with_NO_recovered_field_does_not_page(self):
        """early_bounce_result carries no `recovered` field at all today, so
        treating absent as false would page on every successful bounce —
        about 1.8 a day. Absent means 'cannot judge'."""
        t = await self._titles([_ev("early_bounce_result", pv_v=52.1)])
        self.assertNotIn("DID NOT RECOVER", t)

    async def test_the_budget_being_exhausted_pages(self):
        t = await self._titles([
            _ev("latch_guard_skipped", reason="daily cap reached")])
        self.assertIn("BUDGET EXHAUSTED", t)

    async def test_an_ordinary_skip_does_not_page(self):
        """Cooldown skips are routine and constant."""
        t = await self._titles([
            _ev("latch_guard_skipped", reason="cooldown, 12 min remaining")])
        self.assertNotIn("BUDGET EXHAUSTED", t)

    async def test_guard_errors_page(self):
        for name in ("latch_fix_error", "early_bounce_error"):
            with self.subTest(event=name):
                t = await self._titles([_ev(name, detail="boom")])
                self.assertIn("ERRORED", t)

    async def test_the_seasonal_dormancy_is_announced_once(self):
        t = await self._titles([
            _ev("early_bounce_unavailable", day_max_sun_deg=15.4)])
        self.assertIn("DORMANT", t)

    async def test_routine_latching_still_does_not_page(self):
        """The existing deliberate exclusions must survive this change."""
        t = await self._titles([_ev("mppt_latched", clamped_s=601),
                                _ev("latch_detected")])
        self.assertEqual(t.strip(" |"), "")

    async def test_every_conditional_event_is_actually_requested(self):
        """A rule that is never queried cannot fire. The query is built from
        XANBUS_RULES; the conditional names must be added to it too."""
        # ALL calls, not the last: _check_config_blind also queries
        # recent_xanbus_events (for xanbus_config_unreadable) and runs after
        # _check_xanbus, so recording only the most recent one measured the
        # wrong probe entirely.
        asked: set = set()

        class _D(_Dao):
            async def recent_xanbus_events(self, src, names, since, limit):
                asked.update(names.split(","))
                return []
        m = EventAlertMonitor(_D([]), webhook_url="https://x.invalid/t",
                              check_interval_s=60)
        await m.check_once(_Client())
        for name, *_ in EventAlertMonitor.XANBUS_CONDITIONAL:
            self.assertIn(name, asked,
                          f"{name} has a rule but is never fetched")


if __name__ == "__main__":
    unittest.main()


class DecodeRejectionNoiseTests(unittest.IsolatedAsyncioTestCase):
    """Fast-packet loss has a NON-ZERO baseline, so any-non-zero is noise.

    Shipped as an unconditional rule and paged within hours: 19 discarded
    frames against a measured expectation of ~23 per window. The bus loses
    0.011% of 7,077 frames/min; 19 in 212,320 is 0.0089% — BELOW baseline.

    Only the reader knows the denominator, so it sets `notable` and the rule
    keys on that. A corrupt dc_w or solar_w is different in kind: its expected
    rate is zero, so any movement is notable.
    """

    async def _titles(self, rows):
        c = _Client()
        await _mon(rows).check_once(c)
        return " | ".join(p.get("title", "") for p in c.posts)

    async def test_baseline_frame_loss_does_not_page(self):
        t = await self._titles([_ev("decode_rejections", bad_asm_seq=19,
                                    asm_pct=0.0089, notable=False)])
        self.assertNotIn("DISCARDING", t,
                         "normal bus loss must not page — this is the alert "
                         "that fired on its first day in production")

    async def test_a_real_rate_change_pages(self):
        t = await self._titles([_ev("decode_rejections", bad_asm_seq=500,
                                    asm_pct=0.2355, notable=True)])
        self.assertIn("DISCARDING", t)

    async def test_a_corrupt_frame_pages_even_at_count_one(self):
        """dc_w/solar_w rejections have an expected rate of ZERO."""
        t = await self._titles([_ev("decode_rejections", bad_dc_w=1,
                                    asm_pct=0.0, notable=True)])
        self.assertIn("DISCARDING", t)

    async def test_an_event_without_the_flag_does_not_page(self):
        """Absent is not false — but for this rule, absent means an older
        reader that cannot judge, and guessing would reintroduce the noise."""
        t = await self._titles([_ev("decode_rejections", bad_asm_seq=19)])
        self.assertNotIn("DISCARDING", t)
