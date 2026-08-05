#!/usr/bin/env python3
"""Xanbus write-path groundwork — CONSTRUCTION ONLY, NO TRANSMIT.

Implements the XanBus-library proprietary-message write scheme disclosed in
the Xantrex "Freedom SW-RVC DGN Reference Guide" (976-0452-01-01 Rev B, see
docs/refs/xanbus/). The Freedom RV-C product reuses the same XanBus library as
the Conext line, and the guide documents the piece the forums only rumored:
configuration writes are validated by a CRC-CCITT keyed on the *device NAMEs*
(first 5 bytes of each unit's ISO Address Claim) of both endpoints.

What is KNOWN (doc-verified, unit-tested below):
  - CRC: CRC-CCITT-FALSE (poly 0x1021, init 0xFFFF, MSB-first, no reflect,
    no final xor) over: destNAME[0:5] + message bytes + srcNAME[0:5].
    All 14 worked examples from the guide pass (see self-test).
  - Message set (Message ID + payload <=5 bytes, CRC16 appended after):
    0x01 ASSOCIATION_CONFIG(assocType, assocInst, srcId)
    0x02 PROPRIETARY_MESSAGE_REQUEST(reqId, p1, p2)
    0x03 ASSOCIATION_STATUS  0x04 DEVICE_MODE_CONFIGURATION(mode)
    0x05 DEVICE_MODE_REQUEST 0x06 DEVICE_MODE_STATUS
    0x08 SW_VERSION_STATUS   0x09 REMOTE_PROCEDURE_CALL (private)
  - NAMEs: harvestable passively from our own capture corpus (ISO Address
    Claim, PGN 59904-answered 60928 / CAN id 0x18EEFF<src>) — see harvest_names().

What is NOT known (why this must not be transmitted yet):
  - The Freedom product carries these in RV-C DGN 0xEF00. Which Xanbus PGN
    wraps the same messages on Conext is UNDOCUMENTED (candidates: one of the
    request/ack PGNs we see — 0x0EA01/59904 ISO Request traffic exists on our
    bus; or a proprietary PGN). Sending a guess could reconfigure or fault a
    charge controller keeping a remote site alive.
  - Byte order of the appended CRC16 on the wire (guide gives values, not
    ordering; assumed big-endian below, flagged in build output).

Per project direction (2026-07-29): construction + validation only.
THERE IS DELIBERATELY NO SOCKET/TRANSMIT CODE IN THIS FILE.
"""
import argparse
import glob
import gzip
import json
import os
import socket
import struct
import sys
import time

# ---------------------------------------------------------------- CRC ------

def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-CCITT-FALSE: poly 0x1021, MSB-first, no reflection, no final xor."""
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def message_crc(dest_name5: bytes, msg: bytes, src_name5: bytes) -> int:
    """The guide's scheme: CRC over destNAME[0:5] + message + srcNAME[0:5]."""
    if len(dest_name5) != 5 or len(src_name5) != 5:
        raise ValueError("NAMEs must be exactly 5 bytes (first 5 of Address Claim)")
    return crc16_ccitt(dest_name5 + msg + src_name5)

# All worked examples from 976-0452-01-01 Rev B pp.45-46 (raw crc input -> CRC).
_DOC_VECTORS = [
    ("8412F7641802050 0BB32E7640 8".replace(" ", ""), 0xB81B),
    ("8412F76418020600BB32E76408", 0x6099),
    ("BB32E7640802050084 12F76418".replace(" ", ""), 0x25FD),
    ("BB32E76408020600 8412F76418".replace(" ", ""), 0xFD7F),
    ("BB32E764080402 8412F76418".replace(" ", ""), 0xDA28),
    ("BB32E76408010500038412F76418", 0x9426),
    ("BB32E76408030500038412F76418", 0x5241),
    ("8412F7641805BB32E76408", 0xE639),
    ("BB32E764080603 8412F76408".replace(" ", ""), 0xED5A),   # doc's own bytes
    ("8412F764100402BB32E76408", 0x82B2),
    ("8412F764100403BB32E76408", 0xC712),
    ("8412F7641001030003BB32E76408", 0x1F56),
    ("8412F7640801030004BB32E76408", 0x09CA),
    ("8412F764080901 09F702AB BB32E76408".replace(" ", ""), 0xA01D),
]


def self_test() -> int:
    bad = 0
    for hexstr, want in _DOC_VECTORS:
        got = crc16_ccitt(bytes.fromhex(hexstr))
        ok = got == want
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {hexstr}  want {want:04X} got {got:04X}")
    print(f"self-test: {len(_DOC_VECTORS) - bad}/{len(_DOC_VECTORS)} doc vectors pass")
    return 1 if bad else 0

# ------------------------------------------------------- message builders --

MSG_ASSOCIATION_CONFIG = 0x01
MSG_PROPRIETARY_MESSAGE_REQUEST = 0x02
MSG_ASSOCIATION_STATUS = 0x03
MSG_DEVICE_MODE_CONFIGURATION = 0x04
MSG_DEVICE_MODE_REQUEST = 0x05
MSG_DEVICE_MODE_STATUS = 0x06
MSG_SW_VERSION_STATUS = 0x08

# XB_eASSN_TYPE
ASSN_DC_INPUT, ASSN_DC_OUT, ASSN_DC_INPUT_OUT = 1, 2, 3
ASSN_AC_INPUT, ASSN_AC_OUT, ASSN_AC_INPUT_OUT = 5, 6, 7
# XB_eAC_SRC_ID / XB_eDC_SRC_ID highlights (full tables in docs/refs/xanbus/)
AC_SRC_SHORE1, AC_SRC_GEN1, AC_SRC_AC_LOAD1, AC_SRC_GRID1 = 3, 19, 51, 67
DC_SRC_HOUSE_BAT_BANK1, DC_SRC_SOLAR_ARRAY1 = 3, 21
# XB_eCTRL_MODE
MODE_SAFE, MODE_OPERATING = 2, 3


def build_proprietary(dest_name5: bytes, src_name5: bytes, msg: bytes) -> bytes:
    """Return message + CRC16 (CRC byte order on the wire is UNVERIFIED —
    big-endian assumed). This is the DGN-0xEF00 *body* per the Freedom guide;
    the Conext/Xanbus wrapping PGN is unknown, so this is not a sendable frame."""
    crc = message_crc(dest_name5, msg, src_name5)
    return msg + bytes([crc >> 8, crc & 0xFF])


def build_device_mode_config(dest5, src5, mode=MODE_SAFE):
    return build_proprietary(dest5, src5, bytes([MSG_DEVICE_MODE_CONFIGURATION, mode]))


def build_association_config(dest5, src5, assn_type, inst, src_id):
    return build_proprietary(dest5, src5, bytes([MSG_ASSOCIATION_CONFIG, assn_type, inst, src_id]))

# ------------------------------------------------------------ NAME harvest --

def harvest_names(data_dir: str):
    """Extract each node's 8-byte NAME from ISO Address Claims in our own
    passive capture corpus (PGN 60928: CAN id 0x18EEFF<src>). Purely offline."""
    names = {}
    for fp in sorted(glob.glob(os.path.join(data_dir, "xanbus", "*.jsonl.gz"))):
        with gzip.open(fp, "rt") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                can_id = int(r["id"], 16)
                if (can_id >> 8) & 0x1FFFF != 0x0EEFF:
                    continue
                src = can_id & 0xFF
                d = bytes.fromhex(r["d"])
                if len(d) == 8:
                    names[src] = d
    return names


# ---------------------------------------------------------- mode command --
#
# The ONE write we fully understand, captured from the real Insight Home
# twice on 2026-08-05 while it fixed a latched MPPT:
#
#   id 0x19400102  ->  PGN 0x14000, dest 1 (MPPT), src 2 (Insight), prio 6
#   payload: a single byte, 0x02 = Standby, 0x03 = Operating
# (verbatim from the capture; test_xanbus_write.py pins the exact bytes)
#
# No CRC, no record echo, no change counter — the simplest primitive on the
# bus. (The NAME-seeded CRC scheme above belongs to the Freedom RV-C
# proprietary DGN family; these Conext config PGNs don't use it.)
#
# Why this command first: the Standby->Operating bounce is the verified
# remote fix for the diode-clamp latch (docs/xanbus-decode.md). It is a
# command we actively WANT to issue, whose success is unambiguous on the
# bus within ~60 s, and whose worst case (device parked in Standby) is
# undoable from the Insight UI in two clicks.

PGN_DEVICE_MODE = 0x14000
MODE_STANDBY, MODE_OPERATING = 0x02, 0x03
DEFAULT_SRC_ADDR = 0x80        # unused on our bus (nodes are 0,1,2)


def build_mode_frame(dest: int, mode: int, src: int = DEFAULT_SRC_ADDR,
                     prio: int = 6) -> tuple[int, bytes]:
    """Return (can_id, payload) for a device-mode command. PDU1 (PF<240),
    so the destination address rides in the PS byte and is excluded from
    the PGN — matching the captured 0x18140102 exactly."""
    if mode not in (MODE_STANDBY, MODE_OPERATING):
        raise ValueError(f"refusing unknown mode 0x{mode:02X}")
    pf = (PGN_DEVICE_MODE >> 8) & 0xFF
    dp = (PGN_DEVICE_MODE >> 16) & 1
    can_id = (prio << 26) | (dp << 24) | (pf << 16) | (dest << 8) | src
    return can_id, bytes([mode])


CAN_EFF_FLAG = 0x80000000


def pack_frame(can_id: int, payload: bytes) -> bytes:
    """SocketCAN frame bytes for an extended-ID frame. Pure — unit-tested
    without hardware (see tests/test_xanbus_write.py)."""
    return struct.pack("=IB3x8s", can_id | CAN_EFF_FLAG, len(payload),
                       payload.ljust(8, b"\x00"))


def send_frame(can_id: int, payload: bytes, iface: str = "can0") -> None:
    """Transmit one extended-ID CAN frame. The ONLY function in this file
    that touches the wire; everything else is construction/inspection."""
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        sock.bind((iface,))
        sock.send(pack_frame(can_id, payload))
    finally:
        sock.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true", help="run doc CRC vectors")
    ap.add_argument("--harvest-names", metavar="DATA_DIR",
                    help="extract node NAMEs from capture corpus (offline)")
    ap.add_argument("--demo", action="store_true",
                    help="show a constructed (non-sendable) message using harvested NAMEs")
    ap.add_argument("--mode", choices=("standby", "operating"),
                    help="build a device-mode command (prints it; sends only with --send)")
    ap.add_argument("--bounce", action="store_true",
                    help="the latch fix: standby, wait, operating (needs --send)")
    ap.add_argument("--dest", type=int, default=1, help="target node (1 = MPPT)")
    ap.add_argument("--src", type=lambda s: int(s, 0), default=DEFAULT_SRC_ADDR)
    ap.add_argument("--iface", default="can0")
    ap.add_argument("--wait", type=float, default=15.0,
                    help="seconds in standby during --bounce")
    ap.add_argument("--send", action="store_true",
                    help="ACTUALLY TRANSMIT. Without this nothing touches the bus.")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.harvest_names:
        names = harvest_names(args.harvest_names)
        for src, name in sorted(names.items()):
            print(f"src {src}: NAME {name.hex()}  (CRC key: {name[:5].hex()})")
        if args.demo and len(names) >= 2:
            (s0, n0), (s1, n1) = sorted(names.items())[:2]
            body = build_device_mode_config(n1[:5], n0[:5], MODE_OPERATING)
            print(f"\ndemo DEVICE_MODE_CONFIGURATION src{s0}->src{s1} "
                  f"(body only, NOT sendable): {body.hex()}")
        return 0

    if args.bounce or args.mode:
        seq = ([("standby", MODE_STANDBY), ("operating", MODE_OPERATING)]
               if args.bounce else
               [(args.mode, MODE_STANDBY if args.mode == "standby" else MODE_OPERATING)])
        for i, (name, mode) in enumerate(seq):
            can_id, payload = build_mode_frame(args.dest, mode, args.src)
            print(f"{'SEND' if args.send else 'DRY '}  {name:9s} "
                  f"id=0x{can_id:08X} dlc={len(payload)} data={payload.hex()}")
            if args.send:
                send_frame(can_id, payload, args.iface)
                if i + 1 < len(seq):
                    print(f"      waiting {args.wait:.0f}s in standby...")
                    time.sleep(args.wait)
        if not args.send:
            print("\n(dry run — nothing was transmitted. Re-run with --send,\n"
                  " and note can0 must NOT be in listen-only mode to transmit.)")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
