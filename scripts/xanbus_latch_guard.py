#!/usr/bin/env python3
"""Unattended MPPT diode-clamp latch guard: detect, clear, record.

THE FAILURE IT FIXES
--------------------
When array current demand exceeds what the panels can supply, the operating
point slides down the IV curve until the array sits at battery voltage plus a
diode drop. A buck converter cannot restart without input headroom, so it
stays latched: real power keeps flowing through the body diode, UNREGULATED
and unmetered, until demand ceases. On 2026-08-01..05 this cost five days of
regulated charging and roughly 40% of available production.

The verified clearance is Standby -> Operating, which opens the PV input and
lets the array fly to Voc so the tracker can re-acquire. We can now issue it
ourselves (scripts/xanbus_node.py), so this guard closes the loop when no
human and no agent is watching.

DESIGN FOR UNATTENDED OPERATION
-------------------------------
This transmits to hardware that keeps a remote site alive, on a timer, with
nobody looking. Every rule below exists to make the failure mode of THIS
SCRIPT boring:

  * Acts only on a sustained clamp in daylight — never on a transient.
  * Cooldown between attempts, and a hard daily cap. A latch it cannot fix
    must not become a device toggling every five minutes forever.
  * Refuses to run if the array is already healthy — the fix is a no-op then,
    but the discipline matters more than the no-op.
  * Verifies afterwards and records whether the fix WORKED, so a fix that
    stops working shows up in the data instead of silently flapping.
  * Every decision, including every decision NOT to act, is logged to the
    event stream and reaches the dashboard.
  * On any unexpected error: log and exit non-zero. Never retry in a loop.

We do not fully understand what triggers the slide yet, so the guard is
deliberately conservative and heavily instrumented rather than clever.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xanbus_node import (  # noqa: E402
    ADDR_GLOBAL, PGN_ADDRESS_CLAIMED, XanbusNode, decode_name, encode_name,
    parse_id, unpack_frame,
)
import socket  # noqa: E402

STATE_PATH = Path("data/latch_guard_state.json")
EVENT_SPOOL = Path("data/solar/events.jsonl")

SAMPLE_S = 45.0            # how long to watch before deciding
# A diode clamp pins the array JUST ABOVE the output (one diode drop), so
# this is a BAND. An upper bound alone also matches NEGATIVE deltas — a dark
# array sitting below battery voltage, which cannot conduct through the diode
# at all. That misread dusk as a latch on 2026-08-05.
# The ceiling must also clear the MPPT's reporting dither (~1.1 V on pv_v
# against a steady out_v), or a continuous clamp samples as intermittent and
# never reaches CLAMP_FRACTION. See xanbus_telemetry.LATCH_DELTA_MAX_V.
CLAMP_DELTA_MIN_V = 0.3
CLAMP_DELTA_MAX_V = 4.0
DAYLIGHT_V = 20.0          # a dark string still floats a few volts
CLAMP_FRACTION = 0.9       # this much of the sample must be clamped
AMBIGUOUS_FRACTION = 0.3   # above this but below CLAMP_FRACTION = report it
COOLDOWN_S = 45 * 60       # minimum gap between fix attempts
MAX_FIXES_PER_DAY = 4      # hard cap; a latch we can't fix must not loop
VERIFY_S = 60.0            # watch this long after a fix to judge it
RECOVERED_DELTA_V = 10.0   # array this far above output = tracking again

PGN_DC_SRC_STS2 = 0x1F0C5
SRC_MPPT = 1


def emit(event: str, data: dict) -> None:
    """Append to the telemetry spool so it uploads with everything else."""
    try:
        EVENT_SPOOL.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_SPOOL.open("a") as f:
            f.write(json.dumps({"t": time.time(), "event": event,
                                "data": data}, separators=(",", ":")) + "\n")
    except OSError as exc:
        print(f"warn: could not write event: {exc}", file=sys.stderr)
    print(f"{event}: {json.dumps(data)}", flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st))
    except OSError as exc:
        print(f"warn: could not save state: {exc}", file=sys.stderr)


def sample_array(iface: str, seconds: float) -> dict:
    """Listen (read-only) and summarise the MPPT's array vs output voltage."""
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((iface,))
    sock.settimeout(1.0)
    asm: dict = {}
    pv_v = out_v = None
    n = clamped = 0
    pv_samples: list[float] = []
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            try:
                can_id, payload = unpack_frame(sock.recv(16))
            except (socket.timeout, OSError):
                continue
            pgn, _dest, src = parse_id(can_id)
            if pgn != PGN_DC_SRC_STS2 or src != SRC_MPPT:
                continue
            seq, fid = payload[0] >> 5, payload[0] & 0x1F
            if fid == 0:
                asm[seq] = [payload[1], bytearray(payload[2:])]
            elif seq in asm:
                asm[seq][1] += payload[1:]
                total, buf = asm[seq]
                if len(buf) >= total:
                    p = bytes(buf[:total])
                    del asm[seq]
                    if len(p) >= 14:
                        _st, assoc, v, _i, _w = struct.unpack_from("<BBIii", p, 0)
                        if assoc == 0x15:
                            pv_v = v / 1000
                            pv_samples.append(pv_v)
                        elif assoc == 0x03:
                            out_v = v / 1000
                    if pv_v is not None and out_v is not None:
                        n += 1
                        if (pv_v > DAYLIGHT_V and
                                CLAMP_DELTA_MIN_V <= (pv_v - out_v) <= CLAMP_DELTA_MAX_V):
                            clamped += 1
    finally:
        sock.close()
    return {
        "n": n,
        "clamped": clamped,
        "fraction": (clamped / n) if n else 0.0,
        "pv_v": round(pv_v, 1) if pv_v is not None else None,
        "out_v": round(out_v, 2) if out_v is not None else None,
        "pv_v_max": round(max(pv_samples), 1) if pv_samples else None,
        "daylight": bool(pv_v and pv_v > DAYLIGHT_V),
    }


def run_fix(iface: str, dest: int, wait: float) -> bool:
    """Issue the Standby -> Operating bounce. Returns True if both ACKed."""
    fields = decode_name(__import__("xanbus_node").OUR_NAME)
    fields["function"] = 134            # gateway: required for command authority
    name = encode_name(**fields)
    with XanbusNode(iface=iface, name=name, verbose=True) as node:
        if not node.claim():
            emit("latch_fix_aborted", {"reason": "could not claim an address"})
            return False
        node.pump(6.0)                  # let discovery complete first
        node.set_mode(dest, 0x02)       # standby
        node.pump(wait)
        node.set_mode(dest, 0x03)       # operating
        node.pump(8.0)
        acks = [a for a in node.acks if a[2] == 0x14000]
        denied = [a for a in acks if a[1] == 2]
        if denied:
            emit("latch_fix_denied", {"acks": acks})
            return False
        return len([a for a in acks if a[1] == 0]) >= 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iface", default="can0")
    ap.add_argument("--dest", type=int, default=1)
    ap.add_argument("--wait", type=float, default=15.0)
    ap.add_argument("--sample", type=float, default=SAMPLE_S)
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and log, but never transmit")
    args = ap.parse_args()

    before = sample_array(args.iface, args.sample)
    st = load_state()
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if st.get("day") != today:
        st = {"day": today, "fixes": 0, "last_attempt": 0}

    # --- decide, and record every reason for NOT acting -------------------
    if before["n"] < 5:
        emit("latch_guard_skipped", {"reason": "no MPPT data on the bus",
                                     **before})
        return 0
    if not before["daylight"]:
        return 0                                    # night: quiet, no event
    if before["fraction"] < CLAMP_FRACTION:
        if st.pop("clamp_seen_at", None):           # healthy again — reset
            save_state(st)
        # Bailing SILENTLY here is how a five-hour latch stayed invisible on
        # 2026-08-06: the ceiling was tighter than the MPPT's dither, so a
        # continuous clamp sampled at ~0.5 and fell out with no trace. A
        # partial clamp is the interesting case — report it. Fully healthy
        # (fraction near zero) stays quiet, so this costs no routine egress.
        if before["fraction"] >= AMBIGUOUS_FRACTION:
            emit("latch_guard_ambiguous",
                 {"reason": "some samples clamped but below the acting "
                            "threshold — partial clamp or a moving tracker",
                  "threshold": CLAMP_FRACTION, **before})
        return 0                                    # healthy: quiet, no event
    # A clamp seen ONCE is not a latch. At dawn and dusk the array voltage
    # passes through battery voltage on its way up/down, so darkness looks
    # exactly like a clamp for ~5-10 minutes (observed 2026-08-05 20:40:
    # pv_v 28.7 vs out 26.5, a 2.2 V delta, with 1 W of production). Runs are
    # 20 min apart, so requiring two CONSECUTIVE confirmations excludes that
    # window while a real latch — which persists for hours — sails through.
    # This matters beyond a wasted bounce: a spurious fix at dawn would burn a
    # daily-cap slot, start a 45 min cooldown, and could mask the real latch.
    prev_seen = st.get("clamp_seen_at", 0)
    if now - prev_seen > 2.5 * 60 * 60:      # stale confirmation, restart
        prev_seen = 0
    if not prev_seen:
        st["clamp_seen_at"] = now
        save_state(st)
        emit("latch_guard_pending",
             {"reason": "clamp seen once — needs a second consecutive "
                        "confirmation before acting (dawn/dusk exclusion)",
              **before})
        return 0

    if now - st.get("last_attempt", 0) < COOLDOWN_S:
        emit("latch_guard_skipped",
             {"reason": "cooldown",
              "since_last_s": round(now - st["last_attempt"]), **before})
        return 0
    if st.get("fixes", 0) >= MAX_FIXES_PER_DAY:
        emit("latch_guard_skipped",
             {"reason": "daily cap reached — latch is not clearing, needs a human",
              "fixes_today": st["fixes"], **before})
        return 0

    emit("latch_detected", {**before, "dry_run": args.dry_run})
    if args.dry_run:
        return 0

    st["last_attempt"] = now
    st["fixes"] = st.get("fixes", 0) + 1
    save_state(st)

    try:
        acked = run_fix(args.iface, args.dest, args.wait)
    except Exception as exc:                        # noqa: BLE001 — never loop
        emit("latch_fix_error", {"error": f"{type(exc).__name__}: {exc}"})
        return 1

    after = sample_array(args.iface, VERIFY_S)
    recovered = bool(after["pv_v"] and after["out_v"]
                     and (after["pv_v"] - after["out_v"]) > RECOVERED_DELTA_V)
    emit("latch_fix_result", {
        "acked": acked, "recovered": recovered,
        "attempt_today": st["fixes"],
        "before": before, "after": after,
    })
    return 0 if recovered else 1


if __name__ == "__main__":
    sys.exit(main())
