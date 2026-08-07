#!/usr/bin/env python3
"""Watch the Conext charge-config records and shout if any byte changes.

Motivation: equalize was set to 32 V — **4.0 V/cell on an LFP bank** — and was
ENABLED until 2026-07-29. It is one UI click from returning and nothing on the
system alarms about it. Neither does anything alarm if a charge ceiling moves.

Deliberately watches the WHOLE record rather than a decoded flag. We tried to
locate the equalize enable bit on 2026-08-06 and could not: diffing live
config (byte[0]=0x04) against factory defaults (0x06) showed the only
substantive difference at **offset 8** (27.0 V live vs 32.0 V default), while
the offset we map as `equalize_v` (offset 4) reads 32.0 V in BOTH — i.e. it
has never been changed and is probably not the field that governs anything.
Until that mapping is settled, "any byte moved" is the honest test, and it
cannot miss a change by looking in the wrong place.

Read-only: claims an address, reads records, transmits nothing else.
Emits `xanbus_config_changed` (and `xanbus_config_baseline` on first run) into
the same spool the rest of the telemetry uploads through.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from xanbus_node import (  # noqa: E402
    OUR_NAME, XanbusNode, decode_name, encode_name,
)

STATE_PATH = Path("data/xanbus_config_baseline.json")
EVENT_SPOOL = Path("data/solar/events.jsonl")

# (label, pgn, dest). Records the charge algorithm actually runs from.
WATCHED = [
    ("mppt_bulk",     0x11700, 1),
    ("mppt_absorb",   0x11800, 1),
    ("mppt_float",    0x11A00, 1),
    ("mppt_equalize", 0x11B00, 1),
    ("sw_bulk",       0x11700, 0),
    ("sw_absorb",     0x11800, 0),
    ("sw_float",      0x11A00, 0),
    ("sw_equalize",   0x11B00, 0),
]

# byte[1] is the change counter: it increments on every accepted write, so it
# differs whenever a value differs and would double-report. Compare without it.
COUNTER_OFFSET = 1


def emit(event: str, data: dict) -> None:
    try:
        EVENT_SPOOL.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_SPOOL.open("a") as fh:
            fh.write(json.dumps({"t": time.time(), "event": event,
                                 "data": data}) + "\n")
    except OSError as exc:
        print(f"warn: could not spool {event}: {exc}", file=sys.stderr)
    print(f"{event}: {json.dumps(data)}")


def digest(record: bytes) -> str:
    body = bytearray(record)
    body[COUNTER_OFFSET] = 0
    return hashlib.sha256(bytes(body)).hexdigest()[:16]


def load_baseline() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_baseline(b: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(b, indent=1))
    except OSError as exc:
        print(f"warn: could not save baseline: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", default="can0")
    ap.add_argument("--adopt", action="store_true",
                    help="accept current values as the new baseline "
                         "(use after a deliberate change)")
    args = ap.parse_args()

    fields = decode_name(OUR_NAME)
    fields["function"] = 134
    name = encode_name(**fields)

    baseline = load_baseline()
    seen: dict = {}
    changes = []
    unreadable = []

    with XanbusNode(iface=args.iface, name=name) as node:
        if not node.claim():
            emit("xanbus_config_watch_failed",
                 {"reason": "could not claim an address"})
            return 1
        node.pump(6.0)                      # answer discovery first

        for label, pgn, dest in WATCHED:
            rec = node.read_record(pgn, dest)
            if rec is None:
                unreadable.append(label)
                continue
            h = digest(rec)
            seen[label] = {"digest": h, "hex": rec.hex(), "counter": rec[1]}
            prev = baseline.get(label)
            if prev and prev.get("digest") != h:
                changes.append({
                    "field": label, "pgn": f"0x{pgn:05X}", "dest": dest,
                    "was": prev.get("hex"), "now": rec.hex(),
                    "changed_offsets": [
                        i for i in range(min(len(rec), len(prev.get("hex", "")) // 2))
                        if bytes.fromhex(prev["hex"])[i] != rec[i]
                        and i != COUNTER_OFFSET
                    ],
                })

    if unreadable:
        emit("xanbus_config_unreadable", {"fields": unreadable})

    if not baseline or args.adopt:
        save_baseline(seen)
        emit("xanbus_config_baseline",
             {"reason": "adopted" if args.adopt else "first run",
              "fields": {k: v["digest"] for k, v in seen.items()}})
        return 0

    if changes:
        # Loud on purpose. A silent charge-config change is how a 4.0 V/cell
        # equalize gets re-enabled on an LFP bank without anyone noticing.
        emit("xanbus_config_changed", {"changes": changes})
        save_baseline(seen)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
