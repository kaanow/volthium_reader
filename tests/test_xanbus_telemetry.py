"""Unit tests for the xanbus_telemetry decode/aggregate core.

Frames are REAL payloads from the 2026-07 capture corpus (see
docs/xanbus-decode.md) fed through the same fast-packet split the wire uses.
No socket, no I/O — exercises Decoder/Reassembler/flush_bucket only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from xanbus_telemetry import (   # noqa: E402
    BUCKET_S, Decoder, parse_can_id,
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

    def test_gen_start_stop(self):
        dec = Decoder()
        feed_fastpacket(dec, 0x1F016, 0, GEN_OFF, t=1000.0)
        evs = feed_fastpacket(dec, 0x1F016, 0, GEN_ON, t=1010.0)
        starts = [e for e in evs if e["event"] == "gen_start"]
        self.assertEqual(len(starts), 1)
        self.assertGreater(starts[0]["data"]["gen_v"], 100)   # ~115 V line
        evs = feed_fastpacket(dec, 0x1F016, 0, GEN_OFF, t=1020.0)
        self.assertEqual(len([e for e in evs if e["event"] == "gen_stop"]), 1)

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



class LatchDetectionTests(unittest.TestCase):
    """The diode-clamp latch that cost five days of regulated charging
    (2026-08-01..05). Array pinned at output voltage + a diode drop while
    the sun is up = converter not switching."""

    def _clamped(self, dec, t):
        # array 27.9 V, output 26.7 V -> delta 1.2 V, daylight
        pv = bytes.fromhex("0315") + (27900).to_bytes(4, "little") + \
            b"\x00" * 8 + b"\xff" * 7
        out = bytes.fromhex("0303") + (26700).to_bytes(4, "little") + \
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
        self.assertEqual([e["event"] for e in evs], ["mppt_latched"])
        self.assertIn("Standby", evs[0]["data"]["fix"])
        self.assertTrue(dec.latched)

    def test_healthy_array_never_latches(self):
        dec = Decoder()
        self._healthy(dec, 1000.0)
        dec.housekeeping(1001.0)
        self.assertEqual([e for e in dec.housekeeping(1000.0 + 601)
                          if e["event"].startswith("mppt_")], [])
        self.assertFalse(dec.latched)

    def test_unlatch_event_on_recovery(self):
        dec = Decoder()
        self._clamped(dec, 1000.0)
        dec.housekeeping(1001.0)
        dec.housekeeping(1601.0)
        self.assertTrue(dec.latched)
        self._healthy(dec, 1700.0)
        evs = [e for e in dec.housekeeping(1701.0)
               if e["event"].startswith("mppt_")]
        self.assertEqual([e["event"] for e in evs], ["mppt_unlatched"])
        self.assertFalse(dec.latched)

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


if __name__ == "__main__":
    unittest.main()
