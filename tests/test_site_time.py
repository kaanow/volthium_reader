"""The site's offset is not a constant, and the named zone cannot be trusted.

Eight analysis scripts hardcoded `LOCAL_OFFSET_H = -7` (PDT). Every one
becomes wrong by an hour on 2026-11-01 and at every transition after. They are
read-only tools, so the cost is MISATTRIBUTION rather than loss — but
misattribution is how the 1356 Wh wrong-day bug happened: the MPPT daily
counter resets at 06:18-07:50 UTC = 23:18-00:50 PDT, already straddling local
midnight, so a one-hour shift moves it across the date boundary.

AND THE ZONE NAME LIES ON THIS HARDWARE. Checked 2026-10-04 on both the laptop
and the Pi: ZoneInfo("America/Vancouver") resolves to a zone reporting MST
-0700 in January AND July. Vancouver is never MST, and a zone with no
summer/winter difference is not Pacific at all. America/Los_Angeles — same
rules — resolves correctly on the same machines.

Replacing a hardcoded -7 with a broken zone would have been the same bug in
better clothing, so the zone is validated before use.

Postgres is unaffected: it has its own tz database, resolves Vancouver
correctly, and complete days report coverage exactly 1.0 — so the ledger's
day boundaries are 24 h apart. This is Python-side only.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import site_time as S   # noqa: E402


def _utc(s): return dt.datetime.fromisoformat(s + "T20:00:00+00:00")


class ZoneValidationTests(unittest.TestCase):

    def test_a_zone_that_observes_dst_was_chosen(self):
        jan = S.local_offset_h(_utc("2027-01-15"))
        jul = S.local_offset_h(_utc("2027-07-15"))
        self.assertNotEqual(
            jan, jul,
            f"the chosen zone ({S.TZ_SOURCE}) reports the same offset in "
            f"January and July, so it is not Pacific — this is exactly the "
            f"America/Vancouver breakage the picker exists to catch")

    def test_the_offsets_are_the_pacific_ones(self):
        self.assertEqual(S.local_offset_h(_utc("2027-01-15")), -8)   # PST
        self.assertEqual(S.local_offset_h(_utc("2027-07-15")), -7)   # PDT

    def test_it_reports_which_zone_it_settled_on(self):
        """Silently substituting a different zone would be the dishonest fix."""
        self.assertIn(S.TZ_SOURCE, (S.SITE_TZ, S._EQUIVALENT_TZ))


class TransitionTests(unittest.TestCase):

    def test_the_autumn_transition_is_honoured(self):
        """The date the hardcoded -7 would have gone wrong."""
        self.assertEqual(S.local_offset_h(_utc("2026-10-31")), -7)
        self.assertEqual(S.local_offset_h(_utc("2026-11-02")), -8)

    def test_the_spring_transition_is_honoured(self):
        self.assertEqual(S.local_offset_h(_utc("2027-03-01")), -8)
        self.assertEqual(S.local_offset_h(_utc("2027-03-15")), -7)

    def test_the_mppt_reset_window_straddles_local_midnight(self):
        """THE REASON ANY OF THIS MATTERS. The MPPT's daily counter resets
        somewhere in 06:18-07:50 UTC, which in PDT is 23:18-00:50 — it lands
        on BOTH sides of local midnight. Attributing it with the wrong offset
        is what produced 1356 Wh against a day that made 6 Wh.

        My first version of this test asserted the wrong side: 07:30 UTC is
        00:30 PDT on the SAME local day, not the previous one.
        """
        early = dt.datetime.fromisoformat("2026-10-04T06:18:00+00:00")
        late = dt.datetime.fromisoformat("2026-10-04T07:50:00+00:00")
        self.assertEqual(S.local_date(early), dt.date(2026, 10, 3),
                         "06:18Z is 23:18 the previous local day")
        self.assertEqual(S.local_date(late), dt.date(2026, 10, 4),
                         "07:50Z is 00:50 the same local day")

    def test_the_straddle_MOVES_across_the_dst_transition(self):
        """In PST the same UTC window is 22:18-23:50 — entirely on the
        PREVIOUS day. So the offset decides which day the counter lands on,
        which is precisely the bug a hardcoded -7 would reintroduce."""
        early = dt.datetime.fromisoformat("2026-12-04T06:18:00+00:00")
        late = dt.datetime.fromisoformat("2026-12-04T07:50:00+00:00")
        self.assertEqual(S.local_date(early), dt.date(2026, 12, 3))
        self.assertEqual(S.local_date(late), dt.date(2026, 12, 3),
                         "under PST both ends fall on the previous day")


class CallersAreWiredTests(unittest.TestCase):

    SCRIPTS = ("cliff_table", "descent_profile", "energy_balance",
               "latch_exposure", "bounce_value", "imbalance_ceiling",
               "ledger_gate_compare")

    def test_no_script_still_hardcodes_the_dst_offset(self):
        root = Path(__file__).resolve().parents[1] / "scripts"
        for name in self.SCRIPTS:
            with self.subTest(script=name):
                src = (root / f"{name}.py").read_text()
                code = "\n".join(l for l in src.splitlines()
                                 if not l.lstrip().startswith("#"))
                self.assertNotIn(
                    "LOCAL_OFFSET_H = -7", code,
                    f"{name} still pins PDT and goes wrong on 2026-11-01")

    def test_every_script_agrees_with_the_helper(self):
        for name in self.SCRIPTS:
            with self.subTest(script=name):
                mod = __import__(name)
                self.assertEqual(mod.LOCAL_OFFSET_H, S.local_offset_h())
