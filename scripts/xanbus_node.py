#!/usr/bin/env python3
"""A conforming Xanbus (J1939/NMEA2000) node: claims an address, then commands.

WHY THIS EXISTS
---------------
On 2026-08-05 we transmitted a device-mode command byte-identical to the one
the Insight Home uses — same PGN, destination, priority and payload, differing
only in source address — and every device on the bus ignored it. That was
correct behaviour on their part, not a fault: SAE J1939/81 requires that a
controller application "successfully claim an address ... prior to sending any
message on the network". Our 0x80 had never claimed, so our frames were noise.

This module makes us a real node:

  1. Broadcast Address Claimed (PGN 60928) with an 8-byte NAME.
  2. Watch ~250 ms for a competing claim on the same address. J1939 arbitration
     is "lowest NAME wins" — our NAME is deliberately built to be the HIGHEST
     possible in its class, so if a real device ever wants our address we lose
     and stand down. We can never displace hardware keeping the site alive.
  3. Hold the address: answer Requests for Address Claimed (PGN 59904 asking
     for 60928) and re-announce on the ~1 Hz cadence this bus already uses.
  4. Only then send commands.

The claim lapses when the process exits, which is exactly what we want from a
one-shot repair tool: no lingering phantom node on the bus.

SAFETY
------
Nothing here transmits unless the caller explicitly opts in. The default
address (0x80) is unused on our bus — verified across the entire capture
corpus, where only 0x00 (SW), 0x01 (MPPT) and 0x02 (Insight) ever appear.
"""
from __future__ import annotations

import argparse
import select
import socket
import struct
import sys
import time

CAN_EFF_FLAG = 0x80000000
CAN_FRAME_FMT = "=IB3x8s"

PGN_ADDRESS_CLAIMED = 0x0EE00      # 60928, broadcast
PGN_REQUEST = 0x0EA00              # 59904, request-for-PGN
PGN_ACK = 0x0E800                  # 59392, ISO Acknowledgment
PGN_DEVICE_MODE = 0x14000          # Conext device mode (02=standby 03=operating)

# Discovery PGNs the Insight interrogates a new node with, within ~1.3 s of
# its address claim (observed 2026-08-05). A node that answers none of these
# is a ghost on the network; these are our replies.
PGN_STS = 0x1F00F                  # generic device status (single frame)
PGN_PROD_INFO = 0x1F014            # model + part number (fast packet)
PGN_SW_VER = 0x1F80E               # software version (fast packet)
PGN_HW_REV = 0x1F810               # hardware revision + serial (fast packet)

ACK_CONTROL = {0: "ACK", 1: "NAK", 2: "ACCESS DENIED", 3: "CANNOT RESPOND"}

ADDR_NULL = 0xFE                   # J1939 "cannot claim"
ADDR_GLOBAL = 0xFF
CLAIM_SETTLE_S = 0.30              # spec says 250 ms; a little margin
CLAIM_REFRESH_S = 1.0              # match the cadence the bus already uses

MODE_STANDBY, MODE_OPERATING = 0x02, 0x03


# --------------------------------------------------------------- NAME ------

def encode_name(*, identity: int, manufacturer: int, ecu_instance: int,
                function_instance: int, function: int, vehicle_system: int,
                vehicle_system_instance: int, industry_group: int,
                arbitrary_address_capable: int) -> bytes:
    """Pack a J1939 NAME into its 8 little-endian wire bytes.

    Bit layout (LSB first): identity 0-20, manufacturer 21-31, ecu-instance
    32-34, function-instance 35-39, function 40-47, reserved 48,
    vehicle-system 49-55, vehicle-system-instance 56-59, industry-group 60-62,
    arbitrary-address-capable 63.
    """
    v = (identity & 0x1FFFFF)
    v |= (manufacturer & 0x7FF) << 21
    v |= (ecu_instance & 0x7) << 32
    v |= (function_instance & 0x1F) << 35
    v |= (function & 0xFF) << 40
    v |= (vehicle_system & 0x7F) << 49
    v |= (vehicle_system_instance & 0xF) << 56
    v |= (industry_group & 0x7) << 60
    v |= (arbitrary_address_capable & 1) << 63
    return v.to_bytes(8, "little")


def decode_name(raw: bytes) -> dict:
    """Inverse of encode_name — used to read the other nodes' identities."""
    v = int.from_bytes(raw, "little")
    return {
        "identity": v & 0x1FFFFF,
        "manufacturer": (v >> 21) & 0x7FF,
        "ecu_instance": (v >> 32) & 0x7,
        "function_instance": (v >> 35) & 0x1F,
        "function": (v >> 40) & 0xFF,
        "vehicle_system": (v >> 49) & 0x7F,
        "vehicle_system_instance": (v >> 56) & 0xF,
        "industry_group": (v >> 60) & 0x7,
        "arbitrary_address_capable": (v >> 63) & 1,
    }


# Our NAME. Every field is chosen so this node is a well-behaved guest:
#   * vehicle_system 30 (Power Management) + industry_group 0 (Global) match
#     the rest of this bus, so we look like what we are.
#   * function 130 sits beside the real devices (129 SW inverter/charger,
#     131 MPPT, 134 gateway) without claiming to be any of them.
#   * vehicle_system_instance is MAX (15) where every real device uses 0.
#     This is the safety property, and it has to live in a HIGH-order field:
#     J1939 arbitration is lowest-NAME-wins on the whole 64-bit value, so
#     only a field ABOVE `function` (bits 40-47) can guarantee we lose. An
#     earlier version differentiated on `function` alone and would have
#     WON against the MPPT and evicted it — caught by
#     test_our_name_loses_every_arbitration before it ever reached the bus.
#   * identity / manufacturer / instances are maxed for the same reason.
OUR_NAME = encode_name(
    identity=0x1FFFFF, manufacturer=0x7FF, ecu_instance=0x7,
    function_instance=0x1F, function=130, vehicle_system=30,
    vehicle_system_instance=0xF, industry_group=0, arbitrary_address_capable=1,
)
DEFAULT_ADDR = 0x80


# ---------------------------------------------------------- CAN framing ----

def build_id(pgn: int, src: int, dest: int = ADDR_GLOBAL, prio: int = 6) -> int:
    """29-bit CAN id. PDU1 (PF<240) is destination-specific: the destination
    rides in the PS byte and is NOT part of the PGN. PDU2 is broadcast."""
    dp = (pgn >> 16) & 1
    pf = (pgn >> 8) & 0xFF
    ps = (pgn & 0xFF) if pf >= 240 else dest
    return (prio << 26) | (dp << 24) | (pf << 16) | (ps << 8) | src


def parse_id(can_id: int) -> tuple[int, int, int]:
    """29-bit id -> (pgn, dest, src)."""
    dp = (can_id >> 24) & 1
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    sa = can_id & 0xFF
    if pf < 240:
        return (dp << 16) | (pf << 8), ps, sa
    return (dp << 16) | (pf << 8) | ps, ADDR_GLOBAL, sa


def pack_frame(can_id: int, payload: bytes) -> bytes:
    return struct.pack(CAN_FRAME_FMT, can_id | CAN_EFF_FLAG,
                       len(payload), payload.ljust(8, b"\x00"))


def fast_packet_frames(payload: bytes, seq: int = 0) -> list[bytes]:
    """Split a payload into NMEA2000 fast-packet frames.

    Control byte is a 3-bit sequence counter plus a 5-bit frame index; frame 0
    also carries the total length and 6 data bytes, later frames carry 7 each.
    Unused tail bytes are 0xFF, matching what the real devices emit."""
    if not 0 <= len(payload) <= 223:
        raise ValueError(f"payload of {len(payload)} B does not fit a fast packet")
    frames = [bytes([(seq & 0x7) << 5, len(payload)]) + payload[:6].ljust(6, b"\xff")]
    pos, idx = 6, 1
    while pos < len(payload):
        chunk = payload[pos:pos + 7]
        frames.append(bytes([((seq & 0x7) << 5) | (idx & 0x1F)])
                      + chunk.ljust(7, b"\xff"))
        pos += 7
        idx += 1
    return frames


def _ascii_field(text: str, width: int) -> bytes:
    """Fixed-width NUL-padded ASCII, the convention the Conext devices use
    for model and part-number strings."""
    return text.encode("ascii", "replace")[:width].ljust(width, b"\x00")


def unpack_frame(raw: bytes) -> tuple[int, bytes]:
    can_id, dlc, data = struct.unpack(CAN_FRAME_FMT, raw)
    return can_id & 0x1FFFFFFF, data[:dlc]


# ------------------------------------------------------------- the node ----

class XanbusNode:
    """Claim an address, hold it, send commands. Use as a context manager."""

    def __init__(self, iface: str = "can0", addr: int = DEFAULT_ADDR,
                 name: bytes = OUR_NAME, verbose: bool = True):
        self.iface, self.addr, self.name = iface, addr, name
        self.verbose = verbose
        self.sock: socket.socket | None = None
        self.claimed = False
        self._last_refresh = 0.0
        self._fp_seq = 0
        self.peers: dict[int, bytes] = {}
        self.answered: dict[int, int] = {}     # discovery PGN -> times answered
        self.acks: list[tuple[int, int, int]] = []   # (src, control, pgn)

    # -- plumbing --------------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, flush=True)

    def __enter__(self) -> "XanbusNode":
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.bind((self.iface,))
        self.sock.settimeout(0.2)
        return self

    def __exit__(self, *exc) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def _send(self, can_id: int, payload: bytes) -> None:
        self.sock.send(pack_frame(can_id, payload))

    def _send_fast(self, pgn: int, dest: int, payload: bytes) -> None:
        """Transmit a multi-frame fast-packet message."""
        can_id = build_id(pgn, self.addr, dest)
        for f in fast_packet_frames(payload, self._fp_seq):
            self._send(can_id, f)
        self._fp_seq = (self._fp_seq + 1) & 0x7

    # -- identity: what we answer discovery with -------------------------
    #
    # Structures mirror the real devices byte-for-byte (verified against
    # captured ProdInfoSts / HwRevSts / SwVerSts payloads); only the identity
    # strings are ours. We describe ourselves honestly — this is a Volthium
    # monitor, not an impersonation of Schneider hardware.

    def _prod_info(self) -> bytes:
        # 07 | 16B model | 12B part number | 0xFF filler  (43 B total)
        return (bytes([0x07]) + _ascii_field("VolthiumMon", 16)
                + _ascii_field("VOLTHIUM-1", 12) + b"\xff" * 14)

    def _hw_rev(self) -> bytes:
        # 07 | ffff | rev | 12B serial | filler  (22 B total)
        return (bytes([0x07, 0xFF, 0xFF, 0x01, 0x00, 0x00])
                + _ascii_field("VOLTHIUMPI01", 12) + b"\xff" * 4)

    def _sw_ver(self) -> bytes:
        # 25 B, same shape as the real SwVerSts records
        return (bytes([0x07, 0xF0, 0x02]) + struct.pack("<I", 1)
                + bytes([0x01, 0x00, 0xF0, 0x00, 0xA1, 0x28, 0x00, 0x00])
                + bytes([0x01, 0x00, 0xF0, 0x03, 0x10, 0x27, 0x00, 0x00])
                + b"\xff" * 6)[:25]

    def _sts(self) -> bytes:
        # Both real devices emit this identical 6-byte "operating" status.
        return bytes.fromhex("030403030200")

    def _discovery_table(self) -> dict:
        return {
            PGN_STS: (False, self._sts),
            PGN_PROD_INFO: (True, self._prod_info),
            PGN_SW_VER: (True, self._sw_ver),
            PGN_HW_REV: (True, self._hw_rev),
        }

    def _answer_request(self, req_pgn: int, requester: int) -> bool:
        """Reply to a Request for one of our identity PGNs. Returns True if
        we answered."""
        entry = self._discovery_table().get(req_pgn)
        if entry is None:
            return False
        is_fast, build = entry
        payload = build()
        if is_fast:
            self._send_fast(req_pgn, ADDR_GLOBAL, payload)
        else:
            self._send(build_id(req_pgn, self.addr, ADDR_GLOBAL), payload)
        self.answered[req_pgn] = self.answered.get(req_pgn, 0) + 1
        self._log(f"  answered request for 0x{req_pgn:05X} from {requester} "
                  f"({len(payload)} B)")
        return True

    def _recv(self, timeout: float):
        """Yield (pgn, dest, src, payload) for `timeout` seconds."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            r, _, _ = select.select([self.sock], [], [], left)
            if not r:
                return
            try:
                can_id, payload = unpack_frame(self.sock.recv(16))
            except (OSError, struct.error):
                return
            pgn, dest, src = parse_id(can_id)
            yield pgn, dest, src, payload

    # -- address claim ---------------------------------------------------
    def _announce(self) -> None:
        self._send(build_id(PGN_ADDRESS_CLAIMED, self.addr, ADDR_GLOBAL), self.name)
        self._last_refresh = time.monotonic()

    def claim(self) -> bool:
        """Announce and defend. Returns True if the address is ours.

        Loses deliberately: any competing claim on our address with a NAME
        that sorts lower than ours (J1939: lowest wins) makes us stand down
        and emit Cannot Claim, so we never evict a real device."""
        self._log(f"claiming address 0x{self.addr:02X} with NAME {self.name.hex()}")
        self._announce()
        for pgn, dest, src, payload in self._recv(CLAIM_SETTLE_S):
            if pgn == PGN_ADDRESS_CLAIMED and len(payload) == 8:
                self.peers[src] = payload
                if src == self.addr:
                    ours = int.from_bytes(self.name, "little")
                    theirs = int.from_bytes(payload, "little")
                    if theirs < ours:                 # they win
                        self._log(f"  contested by a lower NAME ({payload.hex()}) "
                                  f"— standing down")
                        self._send(build_id(PGN_ADDRESS_CLAIMED, ADDR_NULL,
                                            ADDR_GLOBAL), self.name)
                        self.claimed = False
                        return False
                    self._log(f"  contested by a higher NAME — we keep it")
        self.claimed = True
        self._log(f"  address 0x{self.addr:02X} claimed "
                  f"(peers seen: {sorted(self.peers)})")
        return True

    def pump(self, duration: float) -> None:
        """Hold the address for `duration`: answer Requests for Address
        Claimed, re-announce periodically, and yield if out-arbitrated."""
        end = time.monotonic() + duration
        while time.monotonic() < end:
            for pgn, dest, src, payload in self._recv(0.2):
                if pgn == PGN_REQUEST and len(payload) >= 3:
                    req = payload[0] | (payload[1] << 8) | (payload[2] << 16)
                    if req == PGN_ADDRESS_CLAIMED and dest in (self.addr, ADDR_GLOBAL):
                        self._announce()
                    elif dest == self.addr:
                        self._answer_request(req, src)
                elif pgn == PGN_ACK and dest == self.addr and len(payload) >= 8:
                    # A device is telling us what it made of our last message.
                    ctl = payload[0]
                    acked = payload[5] | (payload[6] << 8) | (payload[7] << 16)
                    self.acks.append((src, ctl, acked))
                    self._log(f"  <- node {src}: {ACK_CONTROL.get(ctl, ctl)} "
                              f"for PGN 0x{acked:05X}")
                elif (pgn == PGN_ADDRESS_CLAIMED and src == self.addr
                      and len(payload) == 8 and payload != self.name):
                    if int.from_bytes(payload, "little") < int.from_bytes(self.name, "little"):
                        self._log("  lost the address mid-session — standing down")
                        self.claimed = False
                        return
            if time.monotonic() - self._last_refresh >= CLAIM_REFRESH_S:
                self._announce()

    # -- commands --------------------------------------------------------
    def command(self, pgn: int, dest: int, payload: bytes) -> None:
        if not self.claimed:
            raise RuntimeError("refusing to command without a claimed address")
        self._send(build_id(pgn, self.addr, dest), payload)
        self._log(f"  sent PGN 0x{pgn:05X} -> node {dest}: {payload.hex()}")

    def set_mode(self, dest: int, mode: int) -> None:
        if mode not in (MODE_STANDBY, MODE_OPERATING):
            raise ValueError(f"refusing unknown mode 0x{mode:02X}")
        self.command(PGN_DEVICE_MODE, dest, bytes([mode]))


# ------------------------------------------------------------------ CLI ----

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iface", default="can0")
    ap.add_argument("--addr", type=lambda s: int(s, 0), default=DEFAULT_ADDR)
    ap.add_argument("--function", type=int, default=None,
                    help="override the NAME function field (129 inverter/charger, "
                         "131 charge controller, 134 gateway). For testing whether "
                         "command authority is tied to device function.")
    ap.add_argument("--dest", type=int, default=1, help="target node (1 = MPPT)")
    ap.add_argument("--wait", type=float, default=15.0,
                    help="seconds held in standby during --bounce")
    ap.add_argument("--hold", type=float, default=20.0,
                    help="seconds to hold the address after the last command")
    ap.add_argument("--claim-only", action="store_true",
                    help="claim and hold, send no commands (safe bus test)")
    ap.add_argument("--identify", action="store_true",
                    help="claim, then answer discovery interrogation. No "
                         "commands — pure request/response (safe bus test)")
    ap.add_argument("--bounce", action="store_true",
                    help="the MPPT latch fix: standby, wait, operating")
    ap.add_argument("--decode-names", action="store_true",
                    help="listen and decode every Address Claimed NAME (read-only)")
    ap.add_argument("--send", action="store_true",
                    help="ACTUALLY TRANSMIT. Without this nothing is sent.")
    args = ap.parse_args()

    name = OUR_NAME
    if args.function is not None:
        fields = decode_name(OUR_NAME)
        fields["function"] = args.function
        name = encode_name(**fields)
        # Safety invariant: whatever we present, we must still LOSE every
        # arbitration against the real devices so we can never evict one.
        # vehicle_system_instance=15 sits above `function` in NAME ordering,
        # which is what preserves this across a function override.
        ours = int.from_bytes(name, "little")
        for peer in (0x0AEEE6FF00813C80, 0x16ACF9FF00833C80, 0x1E6AFEFF00863C80):
            peer_le = int.from_bytes(peer.to_bytes(8, "big"), "little")
            if peer_le >= ours:
                print(f"REFUSING: NAME {name.hex()} would win arbitration "
                      f"against a real device")
                return 2
        print(f"using NAME {name.hex()} (function={args.function})")

    if args.decode_names:
        with XanbusNode(args.iface, args.addr, name) as node:
            print("listening 5 s for Address Claimed...")
            seen = {}
            for pgn, dest, src, payload in node._recv(5.0):
                if pgn == PGN_ADDRESS_CLAIMED and len(payload) == 8:
                    seen[src] = payload
            for src, raw in sorted(seen.items()):
                f = decode_name(raw)
                print(f"  addr 0x{src:02X}: {raw.hex()}  "
                      f"function={f['function']} class={f['vehicle_system']} "
                      f"mfr={f['manufacturer']} id={f['identity']} "
                      f"aac={f['arbitrary_address_capable']}")
            print(f"\nour NAME would be {OUR_NAME.hex()} "
                  f"(int {int.from_bytes(OUR_NAME,'little')})")
            for src, raw in sorted(seen.items()):
                rel = ("we LOSE to" if int.from_bytes(raw, "little")
                       < int.from_bytes(OUR_NAME, "little") else "we beat")
                print(f"  arbitration vs 0x{src:02X}: {rel} it")
        return 0

    if not (args.bounce or args.claim_only or args.identify):
        ap.print_help()
        return 0

    if not args.send:
        print("DRY RUN — would claim 0x%02X with NAME %s" % (args.addr, name.hex()))
        if args.bounce:
            for name, mode in (("standby", MODE_STANDBY), ("operating", MODE_OPERATING)):
                cid = build_id(PGN_DEVICE_MODE, args.addr, args.dest)
                print(f"  then {name:9s} id=0x{cid:08X} data={mode:02x}")
        print("(nothing transmitted; re-run with --send)")
        return 0

    with XanbusNode(args.iface, args.addr, name) as node:
        if not node.claim():
            print("could not claim an address — aborting, nothing commanded")
            return 1
        node.pump(1.0)                      # settle, prove we hold it
        if args.claim_only:
            print(f"holding address for {args.hold:.0f}s (no commands)")
            node.pump(args.hold)
            return 0
        if args.identify:
            print(f"answering discovery for {args.hold:.0f}s (no commands)")
            node.pump(args.hold)
            print(f"\ndiscovery PGNs answered: "
                  f"{ {hex(k): v for k, v in node.answered.items()} or 'none asked'}")
            for src, ctl, pgn in node.acks:
                print(f"  ack from node {src}: {ACK_CONTROL.get(ctl, ctl)} "
                      f"for 0x{pgn:05X}")
            return 0
        # Let discovery complete before commanding — the network interrogates
        # a new node within ~1.3 s and we want to have answered first.
        node.pump(6.0)
        node.set_mode(args.dest, MODE_STANDBY)
        node.pump(args.wait)
        node.set_mode(args.dest, MODE_OPERATING)
        node.pump(args.hold)
        denied = [a for a in node.acks if a[1] == 2]
        if denied:
            print(f"\nACCESS DENIED for {[hex(p) for _, _, p in denied]} "
                  f"— the device refused the command")
        print("done — check pv_v on the dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
