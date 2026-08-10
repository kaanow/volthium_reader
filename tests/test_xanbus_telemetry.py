"""Unit tests for the xanbus_telemetry decode/aggregate core.

Frames are REAL payloads from the 2026-07 capture corpus (see
docs/xanbus-decode.md) fed through the same fast-packet split the wire uses.
No socket, no I/O — exercises Decoder/Reassembler/flush_bucket only.
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import xanbus_telemetry            # noqa: E402
from xanbus_telemetry import (   # noqa: E402
    BUCKET_S, MIN_SUN_ELEVATION_DEG, Decoder, parse_can_id,
)


def fastpacket_frames(payload: bytes, seq: int = 3) -> list[bytes]:
    """Encode a payload as standard NMEA2000 fast-packet frames."""
    frames = [bytes([(seq << 5), len(payload)]) + payload[:6]]
    pos, idx = 6, 1
    while pos < len(payload):
        chunk = payload[pos:pos + 7]
        chunk += b"\xff" * (7 - len(chunk))
        frames.append(bytes([(seq << 5) | idx]) + chunk)
        pos += 7
        idx += 1
    return frames


def can_id(pgn: int, src: int, dest: int = 255, prio: int = 6) -> int:
    """Build a 29-bit id from a 17-bit PGN (with DP bit) + src (+dest for PDU1)."""
    dp = (pgn >> 16) & 1
    pf = (pgn >> 8) & 0xFF
    ps = pgn & 0xFF if pf >= 240 else dest
    return (prio << 26) | (dp << 24) | (pf << 16) | (ps << 8) | src


def feed_fastpacket(dec: Decoder, pgn: int, src: int, payload: bytes,
                    t: float) -> list[dict]:
    events = []
    cid = can_id(pgn, src)
    for f in fastpacket_frames(payload):
        events += dec.feed(cid & 0x1FFFFFFF, f, t)
    return events


# Real reassembled payloads from the corpus:
# 127172 src0 at 26.5 V / discharging (validated vs Modbus r=0.98)
BATT_STS2 = bytes.fromhex(
    "030390d3000098710000260600000000ffffff00ffff41")[:14] + b"\xff" * 22
# 127173 src1 assoc 0x03 (MPPT->battery), raw current negative: -1.43 A, 37 W
MPPT_OUT = bytes.fromhex("0303") + (26540).to_bytes(4, "little") + \
    (-1430).to_bytes(4, "little", signed=True) + (37).to_bytes(4, "little") + \
    b"\xff" * 7
# 127173 src1 assoc 0x15 (PV array), 59.1 V, I/W fields dead on this hardware
PV_IN = bytes.fromhex("0315") + (59100).to_bytes(4, "little") + \
    b"\x00" * 8 + b"\xff" * 7
# 126990 ChgSts (mppt, bulk): target 29.80 V / 60 A, mode 769 @ offset 12
CHG_STS = bytes.fromhex("0303") + (29800).to_bytes(4, "little") + \
    (60000).to_bytes(4, "little") + bytes([0x00, 0x02]) + \
    (769).to_bytes(2, "little") + bytes([0x03]) + b"\xff" * 2
# 126998 assoc 0x13 gen-on sample from berrybms's capture comments (55 B)
GEN_ON = bytes.fromhex(
    "0313fc010452c001004269ffffff6d177017abeeffff85eeffffff7f"
    "020458bf01008869ffffffffff7017c9eeffffb6eeffffff7fffff")
# same shape, gen off: AC2 voltage zeroed
GEN_OFF = bytes.fromhex("0313fc0104") + b"\x00" * 6 + GEN_ON[11:]


class ParseIdTests(unittest.TestCase):
    def test_pdu2_broadcast(self):
        pgn, dest, src = parse_can_id(can_id(0x1F0C5, 1) & 0x1FFFFFFF)
        self.assertEqual((pgn, dest, src), (0x1F0C5, 255, 1))

    def test_pdu1_unicast(self):
        # config read reply seen live 2026-07-29: id 0x191B0201 =
        # PGN 0x11B00 (equalize record), dest 2, src 1
        pgn, dest, src = parse_can_id(0x191B0201 & 0x1FFFFFFF)
        self.assertEqual((pgn, dest, src), (0x11B00, 2, 1))


class DecodeTests(unittest.TestCase):
    def test_impossible_bus_voltage_is_rejected(self):
        """One frame on 2026-08-01 decoded as ~143 kV and dragged a whole
        15 min bucket's mean to 2412 V. dc_v is what the latch detector
        differences against, and a corrupted stored mean is permanent."""
        dec = Decoder()
        good = bytes.fromhex("0303") + (26540).to_bytes(4, "little") + \
            (-1430).to_bytes(4, "little", signed=True) + \
            (37).to_bytes(4, "little") + b"\xff" * 22
        bad = bytes.fromhex("0303") + (143_157_000).to_bytes(4, "little") + \
            (-1430).to_bytes(4, "little", signed=True) + \
            (37).to_bytes(4, "little") + b"\xff" * 22
        feed_fastpacket(dec, 0x1F0C4, 0, good, t=1000.0)
        feed_fastpacket(dec, 0x1F0C4, 0, bad, t=1001.0)
        feed_fastpacket(dec, 0x1F0C4, 0, good, t=1002.0)
        self.assertEqual(dec.bad_dc_v, 1)
        # The mean must be the two good samples only, not dragged upward.
        self.assertAlmostEqual(dec.aggs["dc_v"].mean, 26.54, places=2)

    def test_inconsistent_dc_power_is_rejected(self):
        """2026-08-09 10:10: dc_w decoded as -27844 W while dc_v (27.00) and
        dc_a (-4.4) were both fine, so the voltage-only range check missed it
        and a +28 kW surplus reached the database. The frame carries its own
        redundancy — dc_w tracks |dc_v*dc_a| to within 0.5% over 3005 buckets."""
        dec = Decoder()

        def frame(w):
            return bytes.fromhex("0303") + (27000).to_bytes(4, "little") + \
                (-4400).to_bytes(4, "little", signed=True) + \
                int(w).to_bytes(4, "little", signed=True) + b"\xff" * 22

        feed_fastpacket(dec, 0x1F0C4, 0, frame(119), t=1000.0)      # sane
        feed_fastpacket(dec, 0x1F0C4, 0, frame(-27844), t=1001.0)   # the glitch
        feed_fastpacket(dec, 0x1F0C4, 0, frame(119), t=1002.0)      # sane
        self.assertEqual(dec.bad_dc_w, 1)
        self.assertAlmostEqual(dec.aggs["dc_w"].mean, 119.0, places=1)
        # and the good samples' voltage still went in
        self.assertAlmostEqual(dec.aggs["dc_v"].mean, 27.0, places=2)

    def test_low_current_skips_the_consistency_check(self):
        """Near zero amps the ratio is meaningless and would reject good data."""
        dec = Decoder()
        p = bytes.fromhex("0303") + (26500).to_bytes(4, "little") + \
            (100).to_bytes(4, "little", signed=True) + \
            (3).to_bytes(4, "little", signed=True) + b"\xff" * 22
        feed_fastpacket(dec, 0x1F0C4, 0, p, t=1000.0)
        self.assertEqual(dec.bad_dc_w, 0)
        self.assertIn("dc_w", dec.aggs)

    def test_batt_sts2_aggregates_dc(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F0C4, 0, BATT_STS2, t=1000.0)
        self.assertAlmostEqual(dec.aggs["dc_v"].mean, 54.16, places=2)

    def test_mppt_out_is_abs(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F0C5, 1, MPPT_OUT, t=1000.0)
        self.assertAlmostEqual(dec.aggs["solar_a"].mean, 1.43, places=3)
        self.assertAlmostEqual(dec.aggs["solar_w"].mean, 37.0, places=1)

    def test_pv_array_voltage_only(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F0C5, 1, PV_IN, t=1000.0)
        self.assertAlmostEqual(dec.aggs["pv_v"].mean, 59.1, places=2)
        self.assertNotIn("solar_w", dec.aggs)

    def test_chg_stage_change_event(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F00E, 1, CHG_STS, t=1000.0)   # first: no event
        absorb = CHG_STS[:12] + (770).to_bytes(2, "little") + CHG_STS[14:]
        evs = feed_fastpacket(dec, 0x1F00E, 1, absorb, t=1010.0)
        stage = [e for e in evs if e["event"] == "chg_stage"]
        self.assertEqual(len(stage), 1)
        self.assertEqual(stage[0]["data"]["from"], "bulk")
        self.assertEqual(stage[0]["data"]["to"], "absorption")

    def test_unmapped_charge_stage_falls_through_to_the_int(self):
        """An undecoded code must stay visible as a number rather than be
        silently dropped or guessed at — that is how 786 was found at all."""
        dec = Decoder()
        feed_fastpacket(dec, 0x1F00E, 1, CHG_STS, t=1000.0)
        odd = CHG_STS[:12] + (999).to_bytes(2, "little") + CHG_STS[14:]
        evs = feed_fastpacket(dec, 0x1F00E, 1, odd, t=1010.0)
        stage = [e for e in evs if e["event"] == "chg_stage"]
        self.assertEqual(stage[0]["data"]["to"], 999)

    def test_786_is_named_by_behaviour_not_meaning(self):
        """786 is a 1 s transient on the absorption->float handoff, seen 4
        times, semantics undecoded. It is mapped only so the stream is
        legible; the name must not claim to know what it is."""
        dec = Decoder()
        absorb = CHG_STS[:12] + (770).to_bytes(2, "little") + CHG_STS[14:]
        feed_fastpacket(dec, 0x1F00E, 1, absorb, t=1000.0)
        odd = CHG_STS[:12] + (786).to_bytes(2, "little") + CHG_STS[14:]
        evs = feed_fastpacket(dec, 0x1F00E, 1, odd, t=1001.0)
        stage = [e for e in evs if e["event"] == "chg_stage"]
        self.assertEqual(stage[0]["data"]["from"], "absorption")
        self.assertEqual(stage[0]["data"]["to"], "absorption_to_float_transient")

    def test_gen_start_stop(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F016, 0, GEN_OFF, t=1000.0)
        evs = feed_fastpacket(dec, 0x1F016, 0, GEN_ON, t=1010.0)
        starts = [e for e in evs if e["event"] == "gen_start"]
        self.assertEqual(len(starts), 1)
        self.assertGreater(starts[0]["data"]["gen_v"], 100)   # ~115 V line
        evs = feed_fastpacket(dec, 0x1F016, 0, GEN_OFF, t=1020.0)
        self.assertEqual(len([e for e in evs if e["event"] == "gen_stop"]), 1)

    def _ac_out(self, v_mv: int, i_ma: int = 0, va: int = 0) -> bytes:
        """An AC2Sts frame with assoc 0x33 (AC out / cabin loads)."""
        p = bytearray(b"\x00" * 49)
        p[1] = 0x33
        struct.pack_into("<I", p, 5, v_mv)
        struct.pack_into("<h", p, 9, i_ma)
        struct.pack_into("<h", p, 18, va)
        struct.pack_into("<h", p, 41, 6000)      # 60.00 Hz
        return bytes(p)

    def test_broken_ac_load_decode_stays_quiet(self):
        """assoc 0x33 reports 0 V / 0 A while the inverter is demonstrably
        producing AC. Emitting that every 300 s was 288 records/day of
        confirmed zeros — 45% of the event stream, carrying nothing. It must
        be silent while the value is unchanging."""
        dec = Decoder()
        evs = feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0), t=1000.0)
        first = [e for e in evs if e["event"] == "ac_load_sample"]
        self.assertEqual(len(first), 0)          # nothing on the very first
        for i in range(1, 40):                   # ~3 h of identical zeros
            evs = feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0),
                                  t=1000.0 + i * 300)
            self.assertEqual([e for e in evs
                              if e["event"] == "ac_load_sample"], [])

    def test_ac_load_decode_speaks_the_moment_it_works(self):
        """The reason it is kept rather than deleted: if 0x33 ever produces
        real numbers, that is the cabin AC load we have no other way to see."""
        dec = Decoder()
        feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0), t=1000.0)
        feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0), t=1300.0)
        evs = feed_fastpacket(dec, 0x1F016, 0,
                              self._ac_out(119_800, 4200, 500), t=1600.0)
        got = [e for e in evs if e["event"] == "ac_load_sample"]
        self.assertEqual(len(got), 1)
        self.assertGreater(got[0]["data"]["to"][0], 100)   # ~119.8 V line

    def test_ac_load_heartbeat_proves_it_is_still_decoded(self):
        """Silence must not be ambiguous between 'unchanged' and 'gone'."""
        dec = Decoder()
        feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0), t=1000.0)
        evs = feed_fastpacket(dec, 0x1F016, 0, self._ac_out(0),
                              t=1000.0 + 6 * 3600 + 1)
        beats = [e for e in evs if e["event"] == "ac_load_sample"]
        self.assertEqual(len(beats), 1)
        self.assertTrue(beats[0]["data"].get("heartbeat"))

    def test_inverter_mode_change(self):
        dec = Decoder()
        cid = can_id(0x1F0BD, 0) & 0x1FFFFFFF
        dec.feed(cid, bytes.fromhex("0333000441150000"), 1000.0)
        evs = dec.feed(cid, bytes.fromhex("0333010441150000"), 1010.0)
        modes = [e for e in evs if e["event"] == "inverter_mode"]
        self.assertEqual(len(modes), 1)
        self.assertEqual(modes[0]["data"]["from"], "invert")
        self.assertEqual(modes[0]["data"]["to"], "ac_passthrough")

    def test_node_dropout_and_return(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F0C5, 1, MPPT_OUT, t=1000.0)
        evs = dec.housekeeping(1100.0)
        self.assertEqual([e["event"] for e in evs], ["node_dropout"])
        evs = feed_fastpacket(dec, 0x1F0C5, 1, MPPT_OUT, t=1101.0)
        self.assertIn("node_return", [e["event"] for e in evs])


class BucketTests(unittest.TestCase):
    def test_flush_produces_aligned_row(self):
        dec = Decoder()
        t0 = 1785400000 // BUCKET_S * BUCKET_S + 1        # inside a bucket
        dec.flush_bucket(t0)                               # arms bucket_start
        feed_fastpacket(dec, 0x1F0C5, 1, MPPT_OUT, t=t0)
        feed_fastpacket(dec, 0x1F0C4, 0, BATT_STS2, t=t0 + 2)
        self.assertIsNone(dec.flush_bucket(t0 + 5))        # same bucket
        row = dec.flush_bucket(t0 + BUCKET_S)
        self.assertIsNotNone(row)
        self.assertTrue(row["ts"].endswith("Z"))
        self.assertEqual(row["solar_w"], 37.0)
        self.assertEqual(row["sample_n"], 1)
        self.assertAlmostEqual(row["dc_v"], 54.16, places=1)
        # next bucket starts clean
        self.assertEqual(dec.aggs, {})

    def test_empty_bucket_produces_no_row(self):
        dec = Decoder()
        dec.flush_bucket(1785400001.0)
        self.assertIsNone(dec.flush_bucket(1785400001.0 + BUCKET_S))



# 2026-08-09 19:00 UTC = 12:00 local, sun 51.9 deg up.
NOON = 1786302000.0
# 2026-08-09 03:19 UTC = 20:19 local, sun 1.5 deg up — the exact minute the
# MPPT was hunting between 26.81 and 89.74 V.
DUSK = 1786245540.0


class LatchDetectionTests(unittest.TestCase):
    """The diode-clamp latch that cost five days of regulated charging
    (2026-08-01..05). Array pinned at output voltage + a diode drop while
    the sun is up = converter not switching.

    The sun is stubbed high for this class. These tests are about the clamp
    logic — confirmation windows, hysteresis, dither — and their timestamps
    are relative (1000.0, +601, ...), not real epochs. Before the elevation
    gate existed that did not matter; afterwards those values landed in
    January 1970 and every test failed for a reason unrelated to what it was
    testing. Stubbing states the assumption instead of encoding it in magic
    timestamps. The gate itself is tested in DuskGateTests below, against real
    epochs."""

    def setUp(self):
        self._real_sun = xanbus_telemetry.sun_elevation_deg
        xanbus_telemetry.sun_elevation_deg = lambda _t=None: 50.0

    def tearDown(self):
        xanbus_telemetry.sun_elevation_deg = self._real_sun

    def _clamped(self, dec, t):
        # array 27.9 V, output 26.7 V -> delta 1.2 V, daylight
        pv = bytes.fromhex("0315") + (27900).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26700).to_bytes(4, "little") + \
            (-330).to_bytes(4, "little", signed=True) + \
            (8).to_bytes(4, "little") + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, t)
        feed_fastpacket(dec, 0x1F0C5, 1, out, t)

    def _clamped_at(self, dec, t, pv_mv):
        """A clamp at a specific array voltage, for replaying real dither."""
        pv = bytes.fromhex("0315") + int(pv_mv).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26500).to_bytes(4, "little") + \
            (-330).to_bytes(4, "little", signed=True) + \
            (8).to_bytes(4, "little") + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, t)
        feed_fastpacket(dec, 0x1F0C5, 1, out, t)

    def _healthy(self, dec, t):
        pv = bytes.fromhex("0315") + (89500).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (27060).to_bytes(4, "little") + \
            (-23070).to_bytes(4, "little", signed=True) + \
            (624).to_bytes(4, "little") + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, t)
        feed_fastpacket(dec, 0x1F0C5, 1, out, t)

    def test_latch_needs_sustained_clamp(self):
        dec = Decoder()
        self._clamped(dec, 1000.0)
        self.assertEqual(dec.housekeeping(1010.0), [])      # too brief
        self.assertFalse(dec.latched)

    def test_latch_fires_after_confirm_window(self):
        dec = Decoder()
        self._clamped(dec, 1000.0)
        dec.housekeeping(1001.0)
        evs = [e for e in dec.housekeeping(1000.0 + 601)
               if e["event"].startswith("mppt_")]
        self.assertEqual([e["event"] for e in evs],
                         ["mppt_latched", "mppt_latch_context"])
        self.assertIn("Standby", evs[0]["data"]["fix"])
        self.assertTrue(dec.latched)

    def test_latch_event_carries_the_run_up(self):
        """We don't yet know what triggers the slide, so the event must ship
        the preceding array history, not just the moment of arrival."""
        dec = Decoder()
        t = 1000.0
        for i in range(60):            # a minute of 1 Hz history
            self._clamped(dec, t + i)
            dec.housekeeping(t + i)
        evs = [e for e in dec.housekeeping(t + 601)
               if e["event"] == "mppt_latch_context"]
        self.assertEqual(len(evs), 1)
        trail = evs[0]["data"]["trail"]
        self.assertGreater(len(trail), 5)
        for row in trail:              # [t, pv_v, out_v, out_w, status]
            self.assertEqual(len(row), 5)
        self.assertLessEqual(len(dec.trail), 1200)   # bounded memory

    def test_healthy_array_never_latches(self):
        dec = Decoder()
        self._healthy(dec, 1000.0)
        dec.housekeeping(1001.0)
        self.assertEqual([e for e in dec.housekeeping(1000.0 + 601)
                          if e["event"].startswith("mppt_")], [])
        self.assertFalse(dec.latched)

    def test_unlatch_needs_a_sustained_exit(self):
        """Recovery must be held, for the same reason the ceiling is wide:
        one dithered sample above the band is not the tracker climbing out."""
        dec = Decoder()
        self._clamped(dec, 1000.0)
        dec.housekeeping(1001.0)
        dec.housekeeping(1601.0)
        self.assertTrue(dec.latched)
        self._healthy(dec, 1700.0)
        self.assertEqual([e for e in dec.housekeeping(1701.0)
                          if e["event"].startswith("mppt_")], [])
        self.assertTrue(dec.latched)                 # not yet — needs 120 s
        self._healthy(dec, 1830.0)
        evs = [e for e in dec.housekeeping(1831.0)
               if e["event"].startswith("mppt_")]
        self.assertEqual([e["event"] for e in evs], ["mppt_unlatched"])
        self.assertFalse(dec.latched)

    def test_a_single_dithered_sample_does_not_unlatch(self):
        """Regression for 2026-08-06: the latch was declared at 17:28:03 and
        retracted 25 s later on delta 2.96 V, while the array stayed clamped
        for hours. One sample out of band must not clear the flag."""
        dec = Decoder()
        self._clamped(dec, 1000.0)
        dec.housekeeping(1001.0)
        dec.housekeeping(1601.0)
        self.assertTrue(dec.latched)
        self._healthy(dec, 1610.0)                   # one stray sample
        dec.housekeeping(1611.0)
        self._clamped(dec, 1612.0)                   # ...clamped again
        self.assertEqual([e for e in dec.housekeeping(1613.0)
                          if e["event"].startswith("mppt_")], [])
        self.assertTrue(dec.latched)

    def test_brief_excursion_does_not_restart_confirmation(self):
        """Regression for 2026-08-06 16:35-17:00 local: the array sat clamped
        for 25 min, twitched out of band once around 16:50, and the detector
        emitted NOTHING for the whole episode because that one sample zeroed
        clamp_since. The guard's fraction test caught the latch; this one had
        to be told that hysteresis applies on the way in too."""
        dec = Decoder()
        t = 1000.0
        for i in range(400):                      # 400 s clamped
            self._clamped(dec, t + i)
            dec.housekeeping(t + i)
        self.assertFalse(dec.latched)
        self._healthy(dec, t + 400)               # one brief excursion
        dec.housekeeping(t + 401)
        evs = []
        for i in range(402, 620):                 # clamped again
            self._clamped(dec, t + i)
            evs += [e for e in dec.housekeeping(t + i)
                    if e["event"] == "mppt_latched"]
        self.assertEqual(len(evs), 1)             # 600 s reached despite it
        self.assertTrue(dec.latched)

    def test_sustained_exit_still_voids_the_accumulation(self):
        """The grace must not become amnesia: a genuinely healthy stretch
        longer than the release window resets the confirmation clock."""
        dec = Decoder()
        t = 1000.0
        for i in range(400):
            self._clamped(dec, t + i)
            dec.housekeeping(t + i)
        for i in range(400, 600):                 # 200 s healthy > 120 s
            self._healthy(dec, t + i)
            dec.housekeeping(t + i)
        for i in range(600, 900):                 # only 300 s clamped again
            self._clamped(dec, t + i)
            dec.housekeeping(t + i)
        self.assertFalse(dec.latched)             # must NOT have latched
        self.assertEqual([e for e in dec.housekeeping(t + 900)
                          if e["event"] == "mppt_latched"], [])

    def test_real_dither_keeps_the_latch_asserted(self):
        """Replay of the measured 2026-08-06 clamp: out_v steady at 26.50 V
        while pv_v hops 27.5 <-> 29.9, swinging the delta 1.0-3.4 V second
        to second. At the old 2.5 V ceiling this sampled as intermittent and
        both the detector and the guard lost the latch."""
        dec = Decoder()
        observed = [27500, 29900, 28300, 29800, 27600, 29600, 28100, 29900]
        t = 1000.0
        for i in range(700):
            self._clamped_at(dec, t + i, observed[i % len(observed)])
            dec.housekeeping(t + i)
        self.assertTrue(dec.latched)
        # ...and it must never have been retracted along the way.
        self._clamped_at(dec, t + 700, 29900)        # worst-case 3.4 V delta
        self.assertEqual([e for e in dec.housekeeping(t + 701)
                          if e["event"] == "mppt_unlatched"], [])

    def test_dusk_decay_does_not_latch(self):
        """The real 2026-08-05 21:24 false positive: array at 10.9 V while the
        output sits at 26.5 V -- a delta of -15.7 V and zero production. An
        upper-bound-only test matched that; a clamp BAND must not."""
        dec = Decoder()
        pv = bytes.fromhex("0315") + (10900).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26540).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, 1000.0)
        feed_fastpacket(dec, 0x1F0C5, 1, out, 1000.0)
        dec.housekeeping(1001.0)
        self.assertEqual([e for e in dec.housekeeping(1601.0)
                          if e["event"].startswith("mppt_")], [])
        self.assertFalse(dec.latched)

    def test_real_clamp_still_latches(self):
        """The genuine signature: array pinned ~1.2 V ABOVE the output."""
        dec = Decoder()
        self._clamped(dec, 1000.0)
        dec.housekeeping(1001.0)
        evs = [e for e in dec.housekeeping(1601.0)
               if e["event"] == "mppt_latched"]
        self.assertEqual(len(evs), 1)

    def test_night_does_not_latch(self):
        dec = Decoder()
        pv = bytes.fromhex("0315") + (200).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26100).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, 1000.0)
        feed_fastpacket(dec, 0x1F0C5, 1, out, 1000.0)
        dec.housekeeping(1001.0)
        self.assertEqual([e for e in dec.housekeeping(1601.0)
                          if e["event"].startswith("mppt_")], [])

class DuskGateTests(unittest.TestCase):
    """A clamp-shaped voltage at dusk is not a clamp.

    At dusk the MPPT hunts: it tries to start, drags the array down to battery
    voltage, fails for want of power, and lets it fly back to open circuit. On
    2026-08-09 a single 60 s bucket at 20:19 local held pv_v min 26.81 and max
    89.74 against a 26.51 V bus. Every sample cleared LATCH_DAYLIGHT_V, and
    the ones near the bottom sat a diode drop above the output — sample by
    sample, indistinguishable from a real clamp.

    That blind spot already bit the other detector for real: the guard bounced
    the MPPT at 21:01 local, sun elevation -3.6 deg (commit 26010b1). This
    detector never acts, but its events are the raw material for the cliff
    table and every latch statistic in docs/xanbus-unknowns.md, so a false
    dusk latch corrupts a published finding. Until the gate, the only thing
    preventing one was LATCH_CONFIRM_S — and that evening the array held an
    in-band delta for 13 minutes against a 10 minute confirmation.
    """

    def _clamp_shaped(self, dec, t):
        """pv 27.9 / out 26.7 — delta 1.2 V, squarely in the clamp band."""
        pv = bytes.fromhex("0315") + (27900).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26700).to_bytes(4, "little") + \
            (-330).to_bytes(4, "little", signed=True) + \
            (8).to_bytes(4, "little") + b"\xff" * 7
        feed_fastpacket(dec, 0x1F0C5, 1, pv, t)
        feed_fastpacket(dec, 0x1F0C5, 1, out, t)

    def _run(self, base):
        dec = Decoder()
        self._clamp_shaped(dec, base)
        dec.housekeeping(base + 1)
        evs = []
        for k in range(2, 20):        # well past the 600 s confirmation
            self._clamp_shaped(dec, base + k * 60)
            evs += dec.housekeeping(base + k * 60)
        return dec, [e["event"] for e in evs if e["event"].startswith("mppt_")]

    def test_dusk_hunting_does_not_report_a_latch(self):
        dec, evs = self._run(DUSK)
        self.assertEqual(evs, [])
        self.assertFalse(dec.latched)

    def test_the_identical_signal_at_noon_does(self):
        """Same voltages, same duration — only the sun differs. Without this
        the test above would pass just as well on a detector that never fires."""
        dec, evs = self._run(NOON)
        self.assertIn("mppt_latched", evs)
        self.assertTrue(dec.latched)

    def test_the_two_epochs_really_are_dusk_and_noon(self):
        """Pin the fixtures, so a wrong constant cannot make the pair vacuous."""
        from solar_geometry import sun_elevation_deg as sun
        self.assertLess(sun(DUSK), MIN_SUN_ELEVATION_DEG)
        self.assertGreater(sun(DUSK), -5.0)      # genuinely dusk, not midnight
        self.assertGreater(sun(NOON), 45.0)



if __name__ == "__main__":
    unittest.main()
