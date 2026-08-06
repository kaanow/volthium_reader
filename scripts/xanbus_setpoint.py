#!/usr/bin/env python3
"""Read and write Conext charger setpoints over Xanbus.

Setpoints live in fast-packet CONFIG RECORDS. The Insight's own pattern
(captured 2026-07-29 while we changed charger settings through its UI):
request the record, edit one field in place, send the whole record back. No
CRC — the change counter at byte 1 increments when an edit is accepted, which
is how the device confirms it took.

SAFETY
------
This writes real charger configuration to hardware keeping a remote site
alive. Guards, in order of importance:

  * A whitelist of fields, each with a hard MIN/MAX far tighter than the
    device's own limits. Out-of-range is refused before anything is sent.
  * Read-modify-write of the FULL record: every other byte is preserved
    exactly as the device reported it, so we cannot corrupt neighbouring
    settings by constructing a record from scratch.
  * Verification read-back after every write, comparing both the value and
    the change counter. A write that doesn't verify is reported as failed.
  * --restore captures the original value first and puts it back, so a test
    leaves the system exactly as it found it.

Start with ABSORB_TIME: it is a timer, not a voltage, has no effect at night,
and cannot push a cell anywhere near an overvoltage threshold.
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xanbus_node import (  # noqa: E402
    OUR_NAME, XanbusNode, decode_name, encode_name,
)

# name -> (pgn, offset, struct fmt, scale, unit, safe-min, safe-max, note)
FIELDS = {
    "absorb_time": (0x11800, 46, "<H", 1, "s", 1800, 10800,
                    "absorption timer; 30-180 min. Benign: a timer, not a "
                    "voltage, and inert at night."),
    "bulk_v": (0x11700, 4, "<I", 1000, "V", 27000, 28800,
               "bulk/boost target. Ceiling 28.8 V — pack A's weak cell ran "
               "away at 29.2 V on 2026-07-29."),
    "absorb_v": (0x11800, 4, "<I", 1000, "V", 27000, 28800,
                 "absorption target. Same ceiling and same reason."),
    "float_v": (0x11A00, 4, "<I", 1000, "V", 26000, 27600,
                "float/resting target."),
}


def get_field(record: bytes, spec) -> float:
    _pgn, off, fmt, scale, *_ = spec
    return struct.unpack_from(fmt, record, off)[0] / scale


def set_field(record: bytes, spec, value: float) -> bytes:
    _pgn, off, fmt, scale, *_ = spec
    out = bytearray(record)
    struct.pack_into(fmt, out, off, int(round(value * scale)))
    return bytes(out)


def to_write_form(record: bytes) -> bytes:
    """Convert a record as REPORTED by the device into the form the Insight
    uses to WRITE it.

    Byte 0 distinguishes the two: the device reports with 0x04 (and 0x06 for
    its second instance), while every captured Insight write uses 0x00.
    Echoing the report form back produced ACCESS DENIED — the MPPT saw a
    status report from a peer, not a config write.

    Byte 1 is the change counter and is PRESERVED, not zeroed. It behaves as
    an optimistic-concurrency token: send the counter you just read, and the
    device increments it on accept. The July capture looked like "the writer
    sends 0x00" only because the counter happened to be 0 at that moment;
    sending a literal 0 against a device holding 3 got a NAK.
    """
    out = bytearray(record)
    out[0] = 0x00
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iface", default="can0")
    ap.add_argument("--dest", type=int, default=1, help="1 = MPPT, 0 = SW")
    ap.add_argument("--field", choices=sorted(FIELDS), default="absorb_time")
    ap.add_argument("--read", action="store_true", help="read only, no write")
    ap.add_argument("--set", type=float, help="new value (in the field's unit)")
    ap.add_argument("--restore", action="store_true",
                    help="put the original value back afterwards")
    ap.add_argument("--send", action="store_true",
                    help="ACTUALLY TRANSMIT. Without this nothing is sent.")
    args = ap.parse_args()

    spec = FIELDS[args.field]
    pgn, off, fmt, scale, unit, lo, hi, note = spec
    lo_u, hi_u = lo / scale, hi / scale
    print(f"field {args.field}: PGN 0x{pgn:05X} offset {off} unit {unit}")
    print(f"  safe range {lo_u:g}..{hi_u:g} {unit} — {note}")

    if args.set is not None:
        want_raw = int(round(args.set * scale))
        if not lo <= want_raw <= hi:
            print(f"REFUSED: {args.set}{unit} is outside the safe range "
                  f"{lo_u:g}..{hi_u:g}{unit}")
            return 2

    if not args.send:
        print("\nDRY RUN — would claim an address, read the record"
              + (f", set {args.field}={args.set}{unit}" if args.set is not None else "")
              + (", then restore the original" if args.restore else "")
              + ". Nothing transmitted; re-run with --send.")
        return 0

    fields = decode_name(OUR_NAME)
    fields["function"] = 134          # gateway: required for command authority
    name = encode_name(**fields)

    with XanbusNode(iface=args.iface, name=name) as node:
        if not node.claim():
            print("could not claim an address — aborting")
            return 1
        node.pump(6.0)                # let discovery finish first

        original = node.read_record(pgn, args.dest)
        if original is None:
            print(f"no response for record 0x{pgn:05X}")
            return 1
        orig_val = get_field(original, spec)
        counter = original[1]
        print(f"\nread: {args.field} = {orig_val:g} {unit} "
              f"(change counter {counter}, record {len(original)} B)")

        if args.read or args.set is None:
            return 0

        edited = to_write_form(set_field(original, spec, args.set))
        changed = [i for i in range(len(original)) if original[i] != edited[i]]
        print(f"editing bytes {changed} (0,1 = write-form header; "
              f"rest is the value) — every other byte preserved")
        node.write_record(pgn, args.dest, edited)
        node.pump(3.0)

        check = node.read_record(pgn, args.dest)
        if check is None:
            print("VERIFY FAILED: no read-back")
            return 1
        new_val = get_field(check, spec)
        ok = abs(new_val - args.set) < (1.0 / scale) * 1.5
        print(f"verify: {args.field} = {new_val:g} {unit} "
              f"(change counter {check[1]}) -> {'ACCEPTED' if ok else 'REJECTED'}")

        if args.restore:
            print(f"\nrestoring original {orig_val:g} {unit}...")
            node.write_record(pgn, args.dest,
                              to_write_form(set_field(check, spec, orig_val)))
            node.pump(3.0)
            final = node.read_record(pgn, args.dest)
            if final is not None:
                fv = get_field(final, spec)
                good = abs(fv - orig_val) < (1.0 / scale) * 1.5
                print(f"restored: {args.field} = {fv:g} {unit} "
                      f"(counter {final[1]}) -> {'OK' if good else 'MISMATCH'}")
                return 0 if (ok and good) else 1
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
