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
import sys

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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--self-test", action="store_true", help="run doc CRC vectors")
    ap.add_argument("--harvest-names", metavar="DATA_DIR",
                    help="extract node NAMEs from capture corpus (offline)")
    ap.add_argument("--demo", action="store_true",
                    help="show a constructed (non-sendable) message using harvested NAMEs")
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
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
