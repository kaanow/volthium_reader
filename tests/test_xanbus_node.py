"""Tests for the address-claiming Xanbus node.

The NAME codec is validated against the three REAL NAMEs captured from the
bus, so the bit layout is checked against ground truth rather than my reading
of the spec. The claim logic is exercised against a fake socket, so the
arbitration rules (including "we always lose") are proven without hardware.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import xanbus_node as xn  # noqa: E402
from xanbus_node import (  # noqa: E402
    ADDR_GLOBAL, ADDR_NULL, MODE_OPERATING, MODE_STANDBY, OUR_NAME,
    PGN_ADDRESS_CLAIMED, PGN_DEVICE_MODE, PGN_REQUEST, XanbusNode,
    build_id, decode_name, encode_name, pack_frame, parse_id, unpack_frame,
)

# Captured verbatim from the bus (PGN 60928 payloads).
REAL_NAMES = {
    0x00: bytes.fromhex("0aeee6ff00813c80"),   # Conext SW 4024
    0x01: bytes.fromhex("16acf9ff00833c80"),   # MPPT 60 150
    0x02: bytes.fromhex("1e6afeff00863c80"),   # InsightHome
}


class NameCodecTests(unittest.TestCase):
    def test_roundtrip_real_names(self):
        for addr, raw in REAL_NAMES.items():
            f = decode_name(raw)
            self.assertEqual(encode_name(**f), raw, f"roundtrip failed for 0x{addr:02X}")

    def test_decodes_known_device_identities(self):
        # All three are Power Management (class 30), Global industry group,
        # arbitrary-address-capable — and their functions differ per device.
        for addr, raw in REAL_NAMES.items():
            f = decode_name(raw)
            self.assertEqual(f["vehicle_system"], 30, f"class for 0x{addr:02X}")
            self.assertEqual(f["industry_group"], 0)
            self.assertEqual(f["arbitrary_address_capable"], 1)
        self.assertEqual(decode_name(REAL_NAMES[0x00])["function"], 129)  # inverter/charger
        self.assertEqual(decode_name(REAL_NAMES[0x01])["function"], 131)  # charge controller
        self.assertEqual(decode_name(REAL_NAMES[0x02])["function"], 134)  # gateway

    def test_our_name_loses_every_arbitration(self):
        """The safety property: we can never evict a real device."""
        ours = int.from_bytes(OUR_NAME, "little")
        for addr, raw in REAL_NAMES.items():
            self.assertLess(int.from_bytes(raw, "little"), ours,
                            f"we would WIN against 0x{addr:02X} — unsafe")

    def test_our_name_is_well_formed(self):
        f = decode_name(OUR_NAME)
        self.assertEqual(f["vehicle_system"], 30)     # belongs on this bus
        self.assertEqual(f["arbitrary_address_capable"], 1)
        self.assertNotIn(f["function"], (129, 131, 134))   # impersonates nobody


class FramingTests(unittest.TestCase):
    def test_pdu1_destination_specific(self):
        cid = build_id(PGN_DEVICE_MODE, src=0x80, dest=1)
        self.assertEqual(cid, 0x19400180)
        self.assertEqual(parse_id(cid), (PGN_DEVICE_MODE, 1, 0x80))

    def test_pdu1_matches_insight_capture(self):
        # the Insight's real command frame, byte for byte
        self.assertEqual(build_id(PGN_DEVICE_MODE, src=2, dest=1), 0x19400102)

    def test_pdu2_broadcast_keeps_ps_in_pgn(self):
        cid = build_id(PGN_ADDRESS_CLAIMED, src=0x80, dest=ADDR_GLOBAL)
        pgn, dest, src = parse_id(cid)
        self.assertEqual((pgn, dest, src), (PGN_ADDRESS_CLAIMED, ADDR_GLOBAL, 0x80))

    def test_frame_roundtrip(self):
        cid = build_id(PGN_DEVICE_MODE, src=0x80, dest=1)
        got_id, payload = unpack_frame(pack_frame(cid, b"\x02"))
        self.assertEqual(got_id, cid)
        self.assertEqual(payload, b"\x02")


class FakeSock:
    """Minimal AF_CAN stand-in: records TX, replays a scripted RX."""

    def __init__(self, inbox=()):
        self.sent = []
        self.inbox = list(inbox)

    def send(self, raw):
        self.sent.append(unpack_frame(raw))

    def recv(self, n):
        return self.inbox.pop(0)

    def settimeout(self, t): pass
    def bind(self, a): pass
    def close(self): pass

    def sent_pgns(self):
        return [parse_id(cid)[0] for cid, _ in self.sent]


def _node(inbox=()):
    n = XanbusNode(verbose=False)
    n.sock = FakeSock(inbox)
    # deterministic: select() always reports data iff the inbox has some
    xn.select.select = lambda r, w, x, t: ((r if n.sock.inbox else []), [], [])
    return n


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self._real_select = xn.select.select

    def tearDown(self):
        xn.select.select = self._real_select

    def test_uncontested_claim_succeeds_and_announces(self):
        n = _node()
        self.assertTrue(n.claim())
        self.assertTrue(n.claimed)
        self.assertEqual(n.sock.sent_pgns(), [PGN_ADDRESS_CLAIMED])
        cid, payload = n.sock.sent[0]
        self.assertEqual(payload, OUR_NAME)
        self.assertEqual(parse_id(cid)[2], n.addr)          # from our address

    def test_stands_down_against_lower_name(self):
        """A real device wanting our address must always win."""
        rival = REAL_NAMES[0x01]                             # lower than ours
        frame = pack_frame(build_id(PGN_ADDRESS_CLAIMED, src=0x80,
                                    dest=ADDR_GLOBAL), rival)
        n = _node([frame])
        self.assertFalse(n.claim())
        self.assertFalse(n.claimed)
        # last thing we sent must be the Cannot-Claim (source = null address)
        cid, _ = n.sock.sent[-1]
        self.assertEqual(parse_id(cid)[2], ADDR_NULL)

    def test_keeps_address_against_higher_name(self):
        weaker = encode_name(**{**decode_name(OUR_NAME), "identity": 0x1FFFFF,
                                "function": 200})
        self.assertGreater(int.from_bytes(weaker, "little"),
                           int.from_bytes(OUR_NAME, "little"))
        frame = pack_frame(build_id(PGN_ADDRESS_CLAIMED, src=0x80,
                                    dest=ADDR_GLOBAL), weaker)
        n = _node([frame])
        self.assertTrue(n.claim())

    def test_other_addresses_do_not_contest_us(self):
        frame = pack_frame(build_id(PGN_ADDRESS_CLAIMED, src=0x01,
                                    dest=ADDR_GLOBAL), REAL_NAMES[0x01])
        n = _node([frame])
        self.assertTrue(n.claim())
        self.assertIn(0x01, n.peers)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self._real_select = xn.select.select

    def tearDown(self):
        xn.select.select = self._real_select

    def test_refuses_to_command_before_claiming(self):
        n = _node()
        with self.assertRaises(RuntimeError):
            n.set_mode(1, MODE_STANDBY)
        self.assertEqual(n.sock.sent, [])                    # nothing on the wire

    def test_mode_command_after_claim_matches_insight_shape(self):
        n = _node()
        n.claim()
        n.sock.sent.clear()
        n.set_mode(1, MODE_OPERATING)
        cid, payload = n.sock.sent[0]
        pgn, dest, src = parse_id(cid)
        self.assertEqual((pgn, dest, src), (PGN_DEVICE_MODE, 1, n.addr))
        self.assertEqual(payload, b"\x03")

    def test_refuses_unknown_mode(self):
        n = _node()
        n.claim()
        for bad in (0x00, 0x01, 0x04, 0xFF):
            with self.assertRaises(ValueError):
                n.set_mode(1, bad)


if __name__ == "__main__":
    unittest.main()
