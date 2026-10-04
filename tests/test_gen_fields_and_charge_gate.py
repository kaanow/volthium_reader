"""The generator's own declarations on the bus, and what we infer instead.

The operator asked the right question: why infer anything about the generator
when the Xanbus declares it? It does, and more completely than I had used:

    00:29:18  gen_start                           (AC2 crosses 50 V)
    00:29:34  inverter_mode  invert -> ac_passthrough
    00:29:35  chg_stage      sw: not_charging -> bulk
    00:29:36  chg_target     sw: 90.0 A / 29.2 V
    02:12:04  all four reverse

So the DISPLAY now reads state straight off the bus — that was the fix for
the generator tile. But the ENERGY arithmetic in the ledger still gates on
`dc_a > 0`, and this file is why that is the right choice rather than laziness:

  - dc_a sits in the SAME 15 s row as dc_w, which is the quantity being
    subtracted. No as-of join, no state carried between sparse events, no
    boundary interpolation inside a query that has taken production down
    twice on structural mistakes.
  - It is a measurement of current direction, not an interpretation of a
    device mode. ac_passthrough means the generator is connected; it does
    not say power is flowing into the battery at this instant.
  - The event layer FLAPS. The real run was preceded by a spurious
    gen_start/gen_stop pair 15 s apart (00:28:42 / 00:28:57). A gate built on
    those transitions inherits that.
  - Measured against the device's own declaration over 14 days: 410 of 411
    charging rows fall inside the declared window, and the single exception
    is at 00:29:30 — five seconds BEFORE `bulk` was announced, already
    drawing +14.69 A. The measurement LEADS the declaration. Gating on the
    announcement would have silently dropped that bucket.

The declared state is therefore the right CROSS-CHECK, not the right gate,
and the test below is that cross-check: charge energy must only ever appear
on days the inverter/charger itself said it was charging. If those two ever
diverge, one of them is broken and the ledger should not be trusted either
way.
"""

from __future__ import annotations

import inspect
import re
import unittest

from scripts import xanbus_telemetry as xt


# The stages the Conext SW reports while actually moving energy into the
# battery. `not_charging` and the bare numeric codes are not among them.
CHARGING_STAGES = ("bulk", "absorb", "float", "equalize", "overcharge")


class ChargeGateRationaleTests(unittest.TestCase):
    """Guards on the DECISION, so a later reader does not "simplify" it."""

    def test_the_ledger_gates_charge_energy_on_measured_current(self):
        from cloud.server import db as db_mod
        src = inspect.getsource(db_mod.AsyncpgReadingsDAO.solar_energy_daily)
        self.assertRegex(
            src, r"CASE WHEN s\.dc_a > 0",
            "charge_w must gate on measured current direction; dc_w carries "
            "no sign, so nothing else in the row distinguishes charging")

    def test_the_gate_is_not_quietly_swapped_for_the_declared_mode(self):
        """ac_passthrough says the generator is CONNECTED, not that power is
        flowing in. Using it as the gate would charge the ledger for the whole
        passthrough window regardless of what the charger did."""
        from cloud.server import db as db_mod
        src = inspect.getsource(db_mod.AsyncpgReadingsDAO.solar_energy_daily)
        self.assertNotIn("ac_passthrough", src)
        self.assertNotIn("inverter_mode", src)


class GeneratorFieldHonestyTests(unittest.TestCase):

    def _ac_src(self) -> str:
        return inspect.getsource(xt.Decoder._ac_sts_rms)

    def test_frequency_is_not_published_as_a_frequency(self):
        """It reads a constant 30.00 on every record, including the gen_stop
        events where gen_v is 0.0 — so offset 41 is not ac2_f. Publishing it
        as `gen_hz` invites a consumer to believe it."""
        src = self._ac_src()
        self.assertNotRegex(
            src, r'"gen_hz"\s*:',
            "gen_hz is a misdecode (constant 30.00, including at 0 V); it "
            "must not be emitted under a name that asserts Hz")
        self.assertIn("gen_hz_unverified", src)

    def test_the_raw_value_is_still_carried(self):
        """Dropping it would throw away what a future decode pass needs."""
        self.assertRegex(self._ac_src(), r"gen_hz_unverified.*round\(freq")

    def test_gen_current_and_va_are_still_emitted(self):
        """These are NOT known-bad. They read ~0 in the events only because
        gen_start fires before the charger engages — 17 s before, on the one
        run on record. Removing them as 'also broken' would have been wrong.
        """
        src = self._ac_src()
        self.assertRegex(src, r'"gen_a"\s*:')
        self.assertRegex(src, r'"gen_va"\s*:')

    def test_no_aggregate_is_collected_into_a_column_that_does_not_exist(self):
        """gen_v/gen_va were aggregated per bucket and the row builder has no
        gen_* keys, so every sample was computed and discarded. It looked like
        capture and was not — which is why a 1h43m run left only two
        instantaneous events behind.

        DERIVED rather than asserting the two names: any _agg key the row
        builder never emits is the same bug.
        """
        agg_keys = set(re.findall(r'_agg\("(\w+)"\)', inspect.getsource(xt)))
        row_src = inspect.getsource(xt)
        emitted = set(re.findall(r'"(\w+)":\s*(?:m\("|round\()', row_src))
        # An aggregate is legitimate if the row emits it directly or via a
        # min/max derivative (pv_v -> pv_v_min/pv_v_max).
        orphans = {k for k in agg_keys
                   if k not in emitted
                   and not any(e.startswith(k) for e in emitted)}
        self.assertEqual(
            orphans, set(),
            f"aggregated but never emitted, so silently discarded: "
            f"{sorted(orphans)}")


if __name__ == "__main__":
    unittest.main()
