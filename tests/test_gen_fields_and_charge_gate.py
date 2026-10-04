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
  - The event layer FLAPS AT BOTH ENDS, and the 2026-10-04 run settled this
    rather than merely suggesting it. Shutdown, in 21 seconds:

        16:12:36  gen_start   AND  gen_stop        (same second)
        16:12:36  inverter_mode -> invert, chg_stage -> not_charging
        16:12:53  inverter_mode -> ac_passthrough, chg_stage -> 788
        16:12:54  chg_stage -> bulk, chg_target -> 90 A / 29.2 V
        16:12:56  gen_stop
        16:12:57  inverter_mode -> invert, chg_stage -> not_charging

    The charger genuinely re-entered bulk for ~3 s mid-shutdown. A gate
    built on these transitions has to resolve a same-second start/stop pair
    and a re-entry, and get the boundary right; dc_a just goes to zero.
    Startup flapped the same way on 2026-10-03 (a spurious pair 15 s before
    the real start).
  - Measured against the device's own declaration over 14 days: 410 of 411
    charging rows fall inside the declared window, and the single exception
    is at 00:29:30 — five seconds BEFORE `bulk` was announced, already
    drawing +14.69 A. The measurement LEADS the declaration. Gating on the
    announcement would have silently dropped that bucket.
  - And it reconciles: over the 2026-10-04 run the gate summed 440 Wh of
    charge energy, matching an independent integration of the same rows to
    the watt-hour, at 84.4% of the 521 Wh that went in on the AC side.

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

    def test_the_frequency_is_now_decoded_from_the_right_offset(self):
        """RESOLVED 2026-10-04. It read a constant 30.00 at every record
        including gen_stop at 0 V, because offset 41 is block 2's rel-13
        field, where the device parks a hard 0x0BB8 = 3000 — the AC INPUT
        CURRENT LIMIT, 30.00 A, the Conext SW default. Not a frequency.

        The real value is block-relative 11, which reads 0.00 stopped and a
        median 59.94 Hz under a verified 1.6 kW load across 3492 payloads.
        So it is published as gen_hz again, and the provisional name is gone.
        """
        src = self._ac_src()
        self.assertRegex(src, r'"gen_hz"\s*:',
                         "the verified frequency should be published as gen_hz")
        self.assertNotIn("gen_hz_unverified", src,
                         "the provisional name outlived the uncertainty")

    def test_the_frequency_is_not_read_from_the_old_constant_offset(self):
        """Offset 41 holds 3000 forever. Reading it again would reinstate the
        exact field-that-cannot-vary this project keeps finding."""
        src = self._ac_src()
        self.assertNotRegex(src, r"unpack_from\([^)]*,\s*41\)",
                            "offset 41 is the input current limit, not ac2_f")
        self.assertIn('"hz"', src, "the frequency must come from the block parser")

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
        # SCOPE TO THE ROW BUILDER. Scanning the whole module let the EVENT
        # payload's `"gen_a": round(i1 + i2, 2)` satisfy "emitted", so
        # deleting gen_a from the row dict — the exact original bug — passed.
        # The question is only ever whether flush_bucket emits it.
        row_src = inspect.getsource(xt.Decoder.flush_bucket)
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


class RowSchemaTests(unittest.TestCase):
    """The reader's half of the two-step deploy.

    The server must know gen_v/gen_a/gen_va BEFORE the reader sends them,
    because SolarReading sets extra="forbid" and an unknown field 422s the
    whole batch. The version is how anyone reading the data later knows which
    half of that deploy a given row came from, so forgetting the bump is a
    silent loss of that distinction — and nothing caught it.
    """

    def _row_src(self) -> str:
        return inspect.getsource(xt.Decoder.flush_bucket)

    def test_the_schema_version_matches_what_the_row_CARRIES(self):
        """Tied to CAPABILITY, not pinned to a number.

        This asserted `schema_version: 3` as a literal and broke the moment
        schema 4 shipped — the same defect I had just fixed in status_check's
        skew check, reintroduced in a test one commit later. What actually
        matters is that the declared version is not BELOW the fields present,
        because the version is how a later reader knows which decoder wrote a
        row.
        """
        src = self._row_src()
        m = re.search(r'"schema_version":\s*(\d+)', src)
        self.assertIsNotNone(m, "the row must declare a schema version")
        ver = int(m.group(1))
        needs = {3: ("gen_v", "gen_a", "gen_va"),
                 4: ("load_v", "load_a", "load_va")}
        for min_ver, fields in needs.items():
            if any(f'"{f}"' in src for f in fields):
                self.assertGreaterEqual(
                    ver, min_ver,
                    f"the row emits {fields} but declares schema {ver}; "
                    f"those fields are schema {min_ver}+")

    def test_the_row_emits_all_three_generator_fields(self):
        src = self._row_src()
        for f in ("gen_v", "gen_a", "gen_va"):
            self.assertRegex(src, rf'"{f}":\s*m\("{f}"',
                             f"flush_bucket does not emit {f}")

    def test_gen_a_is_sampled_even_when_the_generator_reads_stopped(self):
        """The ramp is the interesting part: the one sample that disagreed
        with the charger's own declaration was 5 s BEFORE it announced bulk.
        Gating gen_a on `running` would drop the bucket that straddles the
        start, which is the original discard bug in miniature."""
        src = inspect.getsource(xt.Decoder._ac_sts_rms)
        m = re.search(r'self\._agg\("gen_a"\)\.add', src)
        self.assertIsNotNone(m, "gen_a is never aggregated")
        # the aggregation must not sit inside the `if running:` block
        block = src[:m.start()].rsplit("\n", 2)[-2:]
        self.assertNotRegex(
            "\n".join(block), r"if running:",
            "gen_a aggregation is gated on `running` — the straddling bucket "
            "is exactly the one worth keeping")


if __name__ == "__main__":
    unittest.main()
