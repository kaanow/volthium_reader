"""PGN 127166 energy counters — the one production figure not derived from
our own samples.

Every daily-energy number this system reports is an integral of 15 s samples,
so it silently loses whatever the pipeline drops. This counter accumulates
inside the MPPT and is merely read. On 2026-08-09 the two agreed to 0.44%,
which is how the pipeline was shown to be lossless across a day containing a
telemetry restart, an uploader restart and a 35 minute Railway outage.

Payloads below are REAL, lifted from data/xanbus captures on the Pi
(xanbus-20260809-110905 and -20260810-000028) — not hand-built, so the offsets
are exercised against bytes the MPPT actually sent.

The thing most worth guarding is the sparseness. This decoder's whole design
is that quiet periods cost nothing; a counter that emits every frame would put
~5700 events a day into a table whose value is that it only holds changes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xanbus_telemetry import (   # noqa: E402
    MPPT_ENERGY_PERIOD_S, Decoder,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_xanbus_telemetry import feed_fastpacket   # noqa: E402

# Real 60-byte payload, 2026-08-09 10:41 local: life 11660 Ah / 316468 Wh,
# day 15 Ah / 424 Wh.
REAL = bytes.fromhex(
    "0303ffffffff00ffffff7fffffff7fffffff7f8c2d000034d40400"
    "ffffffffffff04ffffff7fffffff7fffffff7f0f000000a80100007d280000c601")


def payload(life_ah, life_wh, day_ah, day_wh):
    b = bytearray(REAL)
    b[19:23] = int(life_ah).to_bytes(4, "little")
    b[23:27] = int(life_wh).to_bytes(4, "little")
    b[46:50] = int(day_ah).to_bytes(4, "little")
    b[50:54] = int(day_wh).to_bytes(4, "little")
    return bytes(b)


def feed(dec, p, t):
    return [e for e in feed_fastpacket(dec, 0x1F0BE, 1, p, t)
            if e["event"].startswith("mppt_")]


class DecodeTests(unittest.TestCase):

    def test_real_payload_decodes_to_the_published_values(self):
        """The exact numbers in docs/xanbus-unknowns.md #6."""
        dec = Decoder()
        evs = feed(dec, REAL, 1000.0)
        self.assertEqual(len(evs), 1)
        d = evs[0]["data"]
        self.assertEqual((d["life_ah"], d["life_wh"]), (11660, 316468))
        self.assertEqual((d["day_ah"], d["day_wh"]), (15, 424))

    def test_lifetime_ratio_is_the_pack_voltage(self):
        d = feed(Decoder(), REAL, 1000.0)[0]["data"]
        self.assertAlmostEqual(d["life_wh"] / d["life_ah"], 27.1, places=1)

    def test_only_the_mppt_is_believed(self):
        """The inverter does not send this PGN; if it ever does, it is not
        this quantity."""
        self.assertEqual(feed_fastpacket(Decoder(), 0x1F0BE, 0, REAL, 1000.0), [])


class SparsenessTests(unittest.TestCase):
    """This decoder's design promise is that quiet periods cost nothing."""

    def test_a_moving_counter_emits_at_most_once_per_period(self):
        dec = Decoder()
        feed(dec, payload(11660, 316468, 15, 424), 1000.0)
        n = 0
        for i in range(1, 60):          # one minute of frames, counter moving
            n += len(feed(dec, payload(11660, 316468 + i, 15, 424 + i),
                          1000.0 + i))
        self.assertEqual(n, 0, "emitted inside the quiet period")

    def test_it_does_emit_once_the_period_elapses(self):
        dec = Decoder()
        feed(dec, payload(11660, 316468, 15, 424), 1000.0)
        evs = feed(dec, payload(11660, 316600, 15, 556),
                   1000.0 + MPPT_ENERGY_PERIOD_S + 1)
        self.assertEqual([e["event"] for e in evs], ["mppt_energy"])

    def test_a_still_counter_emits_nothing_however_long_it_waits(self):
        """Overnight the counter is frozen. That must cost zero events, not
        one every 15 minutes until dawn."""
        dec = Decoder()
        feed(dec, payload(11660, 316468, 55, 1503), 1000.0)
        n = 0
        for h in range(1, 10):
            n += len(feed(dec, payload(11660, 316468, 55, 1503), 1000.0 + h * 3600))
        self.assertEqual(n, 0)


class MidnightResetTests(unittest.TestCase):
    """The reset is the moment the day's total is knowable, so it is the one
    event that must never be missed."""

    def test_reset_reports_the_FINAL_total_not_the_new_zero(self):
        dec = Decoder()
        feed(dec, payload(11660, 317547, 55, 1503), 1000.0)
        evs = feed(dec, payload(11660, 317547, 0, 0), 2000.0)
        self.assertEqual([e["event"] for e in evs], ["mppt_daily_total"])
        d = evs[0]["data"]
        self.assertEqual(d["day_wh"], 1503)   # 2026-08-09's actual total
        self.assertEqual(d["day_ah"], 55)
        self.assertEqual(d["life_wh"], 317547)

    def test_reset_does_not_also_emit_a_snapshot_of_the_zero(self):
        """A 0 Wh snapshot straight after the total is noise, and worse, it
        reads like the counter failed."""
        dec = Decoder()
        feed(dec, payload(11660, 317547, 55, 1503), 1000.0)
        evs = feed(dec, payload(11660, 317547, 0, 0),
                   1000.0 + MPPT_ENERGY_PERIOD_S + 1)
        self.assertEqual([e["event"] for e in evs], ["mppt_daily_total"])


class DecodeGuardTests(unittest.TestCase):

    def test_a_shifted_layout_is_rejected_not_logged_as_nonsense(self):
        """The Wh/Ah ratio IS the pack voltage — that is how these fields were
        identified. If firmware moves the layout the ratio stops being ~27,
        and we would rather emit nothing than publish a wrong lifetime."""
        dec = Decoder()
        self.assertEqual(feed(dec, payload(11660, 3_164_680, 15, 424), 1000.0), [])
        self.assertEqual(dec.bad_mppt_energy, 1)

    def test_unset_fields_are_ignored(self):
        dec = Decoder()
        self.assertEqual(
            feed(dec, payload(0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),
                 1000.0), [])
        self.assertEqual(dec.bad_mppt_energy, 0)   # unset != misdecoded

    def test_zero_lifetime_does_not_divide_by_zero(self):
        dec = Decoder()
        feed(dec, payload(0, 0, 0, 0), 1000.0)     # must not raise


if __name__ == "__main__":
    unittest.main()


class CorruptDailyPairTests(unittest.TestCase):
    """The daily pair needs its own guard, and 2026-08-16 06:15:16 is why.

    The MPPT emitted day_wh = 8388607 (0x7FFFFF) with day_ah = 4286578687
    (0xFF7FFFFF) — both saturation patterns — and every existing check passed:

      the 0xFFFFFFFF test   neither value is exactly all-ones
      the ratio test        only looks at the LIFETIME pair, which was fine
                            at 327313/12059 = 27.14 V

    The corrupt sample became `prev`, and on the next reading the rollover
    branch saw day_wh DROP and published 8388607 Wh as "the final daily total"
    — 8.4 MWh from a 750 W array, latched into the ledger by an unbounded MAX().

    The guard is an INVARIANT, not a threshold: a daily counter cannot exceed
    the lifetime counter it contributes to. Nothing to tune, and it cannot go
    stale as the array or the season changes.
    """

    # The exact values the MPPT sent.
    LIFE_AH, LIFE_WH = 12059, 327313
    BAD_AH, BAD_WH = 4286578687, 8388607

    def test_the_real_corrupt_sample_is_rejected(self):
        dec = Decoder()
        out = feed(dec, payload(self.LIFE_AH, self.LIFE_WH,
                                self.BAD_AH, self.BAD_WH), 1000.0)
        self.assertEqual(out, [], "the 2026-08-16 sample must be rejected")

    def test_it_is_counted_as_bad_rather_than_silently_dropped(self):
        dec = Decoder()
        feed(dec, payload(self.LIFE_AH, self.LIFE_WH,
                          self.BAD_AH, self.BAD_WH), 1000.0)
        self.assertEqual(dec.bad_mppt_energy, 1)

    def test_a_corrupt_sample_cannot_become_the_rollover_value(self):
        """The actual harm: it was not the bad reading that reached the ledger,
        it was the NEXT one, when the rollover branch published the corrupt
        `prev` as an authoritative daily total."""
        dec = Decoder()
        feed(dec, payload(self.LIFE_AH, self.LIFE_WH, 50, 1400), 1000.0)
        feed(dec, payload(self.LIFE_AH, self.LIFE_WH,
                          self.BAD_AH, self.BAD_WH), 2000.0)
        out = feed(dec, payload(self.LIFE_AH, self.LIFE_WH, 55, 1500), 3000.0)
        totals = [e for e in out if e["event"] == "mppt_daily_total"]
        self.assertEqual(totals, [],
                         "a rejected sample must not trigger a rollover, and "
                         "must never be published as a daily total")

    def test_the_guard_catches_either_field_alone(self):
        for ah, wh in ((self.BAD_AH, 1400), (50, self.BAD_WH)):
            with self.subTest(day_ah=ah, day_wh=wh):
                dec = Decoder()
                self.assertEqual(
                    feed(dec, payload(self.LIFE_AH, self.LIFE_WH, ah, wh),
                         1000.0), [])

    def test_a_PLAUSIBLE_day_still_passes(self):
        """The guard must not eat real data — that is how a sanity check starts
        deleting measurements. A normal day is far below the lifetime totals."""
        dec = Decoder()
        out = feed(dec, payload(self.LIFE_AH, self.LIFE_WH, 71, 1939), 1000.0)
        self.assertTrue(out, "a normal daily reading must be accepted")
        self.assertEqual(out[0]["data"]["day_wh"], 1939)

    def test_the_equality_edge_is_allowed(self):
        """On the very first day of the counter's life, daily == lifetime. The
        invariant is <=, not <, or a fresh MPPT would log nothing."""
        dec = Decoder()
        out = feed(dec, payload(100, 2700, 100, 2700), 1000.0)
        self.assertTrue(out, "day == life must be allowed")
