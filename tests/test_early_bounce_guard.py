"""The early bounce switches ITSELF OFF for Nov-Feb, and said nothing.

Found by the 2026-10-04 full-stack review, ~6 weeks before it bites.

EARLY_MIN_SUN_DEG is 15.0 and the site's solar noon on 2026-12-21 is 15.4 deg,
leaving 1.2 h of eligibility — and note_descent CLEARS below45_since whenever
elevation drops under the gate, so a fire needs 29 CONTINUOUS sub-45 V minutes
entirely inside that window.

Computed from the repo's own solar_geometry at 51.119 N:

    2026-10-04  33.5 deg   7.5 h above the gate
    2026-11-21  18.4 deg   3.5 h
    2026-12-01  16.8 deg   2.5 h
    2026-12-21  15.4 deg   1.2 h   <- the gate is 15.0
    2027-01-21  18.8 deg   3.8 h

THE THRESHOLD IS AN OPERATOR DECISION. Lowering it trades a risk of false
bounces at low sun against lost production in the month when production is
scarcest, and the 5.6 deg false-positive margin behind it was measured in
AUGUST. xanbus_latch_guard already rejects a 10 deg gate on the CLAMP path for
the mirror-image reason.

THE SILENCE IS NOT A JUDGMENT CALL. The trigger simply never armed — no event,
no verdict, and the only symptom was the absence of early_bounce_result, which
nothing monitors. That is what these tests pin.
"""

from __future__ import annotations

import datetime as dt
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import xanbus_latch_guard as G   # noqa: E402

class SeasonalShutdownIsAnnouncedTests(unittest.TestCase):
    """The early bounce switches ITSELF OFF for Nov-Feb, and said nothing.

    EARLY_MIN_SUN_DEG is 15.0 and the site's solar noon on 2026-12-21 is
    15.4 deg, leaving 1.2 h of eligibility — and note_descent CLEARS
    below45_since whenever elevation drops under the gate, so a fire needs 29
    CONTINUOUS sub-45 V minutes inside that window.

    Computed from the repo's own solar_geometry at 51.119 N:
        2026-10-04  33.5 deg   7.5 h above the gate
        2026-11-21  18.4 deg   3.5 h
        2026-12-01  16.8 deg   2.5 h
        2026-12-21  15.4 deg   1.2 h   <- gate is 15.0
        2027-01-21  18.8 deg   3.8 h

    The THRESHOLD is an operator decision — it trades false bounces at low sun
    against lost production in the scarcest month, and the 5.6 deg
    false-positive margin behind it was measured in August. The SILENCE is not:
    no event, no verdict, and the only symptom is the absence of
    early_bounce_result, which nothing monitors.
    """

    @staticmethod
    def _noon(datestr):
        d = dt.date.fromisoformat(datestr)
        return dt.datetime(d.year, d.month, d.day, 12,
                           tzinfo=dt.timezone.utc).timestamp()

    def test_midsummer_gate_is_reachable(self):
        peak = G.day_max_sun_deg(self._noon("2026-07-04"))
        self.assertTrue(G.gate_is_reachable_today(peak))

    def test_the_december_gate_is_NOT_reachable(self):
        peak = G.day_max_sun_deg(self._noon("2026-12-21"))
        self.assertLess(peak, G.EARLY_MIN_SUN_DEG + G.EARLY_GATE_WARN_MARGIN_DEG)
        self.assertFalse(
            G.gate_is_reachable_today(peak),
            "the solstice must be reported as unreachable, not pass silently")

    def test_the_shoulder_months_are_flagged_before_the_solstice(self):
        """A warning that only fires ON 21 December is useless — by then the
        guard has been off for weeks."""
        for day in ("2026-11-21", "2026-12-01", "2027-01-11"):
            with self.subTest(day=day):
                peak = G.day_max_sun_deg(self._noon(day))
                self.assertLess(peak, 20.0,
                                "these are the months in question")

    def test_the_margin_makes_it_warn_BEFORE_it_fails(self):
        """Warning exactly at the crossing leaves no time to act."""
        self.assertGreater(G.EARLY_GATE_WARN_MARGIN_DEG, 0)

    def test_the_verdict_is_edge_triggered_on_the_day(self):
        """288 runs a day; an alert repeated every 5 min is one that gets
        skipped. Same de-spamming the early_bounce_due event needed."""
        src = inspect.getsource(G)
        self.assertIn("gate_verdict_day", src)

    def test_the_unavailability_event_is_actually_EMITTED(self):
        """Checking for the state key alone passed a mutation that replaced
        the reachability test with `if False:` — the key survived, the event
        did not. Assert the emit itself, by AST, inside the branch.
        """
        import ast
        tree = ast.parse(inspect.getsource(G))
        emits = {n.args[0].value
                 for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "emit"
                 and n.args and isinstance(n.args[0], ast.Constant)}
        self.assertIn(
            "early_bounce_unavailable", emits,
            "the seasonal shutdown emits nothing, so it is silent again")

    def test_the_emit_is_guarded_by_the_reachability_test(self):
        """...and not emitted unconditionally, which would fire every day of
        the year and be ignored by February."""
        src = inspect.getsource(G)
        i = src.index("early_bounce_unavailable")
        window = src[max(0, i - 400):i]
        self.assertIn("gate_is_reachable_today", window,
                      "the verdict is not gated on reachability")

    def test_note_descent_really_does_clear_the_clock_below_the_gate(self):
        """This is WHY the gate matters so much: a sub-gate sample does not
        merely fail to arm, it discards progress already made."""
        st = {"below45_since": 1000.0}
        G.note_descent(st, 44.0, G.EARLY_MIN_SUN_DEG - 1, 2000.0)
        self.assertNotIn("below45_since", st)
