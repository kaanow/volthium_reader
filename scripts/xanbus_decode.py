"""Xanbus deciphering tool — correlate CAN payloads against Modbus ground truth.

Goal: read the same telemetry from the raw Xanbus (CAN) that we currently get
from the Insight Home's Modbus server, so the Insight Home can be retired. It
works by correlation: the Modbus poller gives labelled, timestamped values
(e.g. SW-inv reg 79 = DC bus voltage); the CAN capture gives raw frames. For
each Modbus register that *varies* over time, this searches every
(CAN id, byte offset, width, endianness, signedness) candidate for the extracted
series that best tracks it (Pearson r + clean linear fit), and prints the winning
decode map: which CAN frame + byte field encodes each value, with its scale.

Pure Python (no numpy). Reads data/xanbus/*.jsonl[.gz] and data/modbus/*.jsonl[.gz].
Correlation needs the values to MOVE — it sharpens a lot with daytime solar and
load swings, so re-run as data accumulates.

Usage: python3 scripts/xanbus_decode.py [--min-r 0.95] [--max-lag 2.0]
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
from collections import defaultdict

# Registers we've already identified, for nicer labels in the output.
KNOWN = {(90, 79): "SW DC bus voltage (x0.001)", (1, 157): "gateway DC voltage (x0.001)"}

# Standard NMEA2000 PGNs relevant to a Conext power system. Schneider also uses
# manufacturer-proprietary PGNs (126720 / 61184) that won't be named here — those
# get decoded by correlation against Modbus. Names are advisory labels only.
KNOWN_PGN = {
    59904: "ISO Request", 60928: "ISO Address Claim", 126720: "Manufacturer Proprietary",
    126992: "System Time", 126996: "Product Information", 126998: "Config Information",
    127500: "Load Controller Conn State", 127501: "Binary Status Report",
    127502: "Switch Bank Control", 127505: "Fluid Level", 127506: "DC Detailed Status",
    127507: "Charger Status", 127508: "Battery Status", 127509: "Inverter Status",
    127510: "Charger Config", 127511: "Inverter Config", 127513: "Battery Config",
    61184: "Manufacturer Proprietary (PDU1)", 65280: "Manufacturer Proprietary (PDU2)",
    130306: "Wind Data",
}


def _parse_id(arb: int):
    """29-bit J1939/NMEA2000 arbitration id -> (priority, pgn, src, dest)."""
    priority = (arb >> 26) & 0x7
    src = arb & 0xFF
    pf = (arb >> 16) & 0xFF
    ps = (arb >> 8) & 0xFF
    dp = (arb >> 24) & 0x3            # data page + reserved bit
    if pf < 240:                     # PDU1: ps is the destination address
        pgn = (dp << 16) | (pf << 8)
        dest = ps
    else:                            # PDU2: broadcast, ps folds into the pgn
        pgn = (dp << 16) | (pf << 8) | ps
        dest = 0xFF
    return priority, pgn, src, dest


def catalog(can):
    """Print the bus map: distinct PGN/source, frame rate, fast-packet, payload."""
    groups = {}
    span = [None, None]
    for cid, seq in can.items():
        try:
            arb = int(cid, 16)
        except ValueError:
            continue
        pri, pgn, src, dest = _parse_id(arb)
        g = groups.setdefault((pgn, src), {"n": 0, "pri": pri, "dest": dest, "ids": set(),
                                           "samples": [], "fp": False, "t0": None, "t1": None})
        g["n"] += len(seq)
        g["ids"].add(cid)
        for t, payload in seq:
            g["t0"] = t if g["t0"] is None else min(g["t0"], t)
            g["t1"] = t if g["t1"] is None else max(g["t1"], t)
            span[0] = t if span[0] is None else min(span[0], t)
            span[1] = t if span[1] is None else max(span[1], t)
            if payload and payload[0] < 0x20 and len(payload) == 8:
                pass  # heuristic only; leave fast-packet flag to the sequence check below
            if len(g["samples"]) < 3:
                g["samples"].append(payload.hex())
        # fast-packet: a PGN whose first data byte increments 0x00,0x01,... across frames
        firsts = [p[0] for _, p in seq[:6] if p]
        if firsts and firsts == list(range(firsts[0], firsts[0] + len(firsts))):
            g["fp"] = True

    dur = (span[1] - span[0]) if span[0] is not None else 0.0
    print(f"=== Xanbus bus map ({len(groups)} PGN/source groups over {dur/60:.1f} min) ===")
    print(f"{'PGN':>7} {'src':>3} {'dest':>4} {'pri':>3} {'rate/s':>7}  fp  name / sample payloads")
    for (pgn, src), g in sorted(groups.items(), key=lambda kv: -kv[1]["n"]):
        rate = g["n"] / dur if dur > 0 else 0.0
        name = KNOWN_PGN.get(pgn, "proprietary/unknown")
        print(f"{pgn:>7} {src:>3} {'0x%02X'%g['dest']:>4} {g['pri']:>3} {rate:>7.2f}  "
              f"{'Y' if g['fp'] else ' '}   {name}")
        for s in g["samples"]:
            print(f"{'':>30}   {s}")
    print()


def _load(pattern_glob: str, cur: str):
    files = sorted(glob.glob(pattern_glob)) + [cur]
    for fn in files:
        op = gzip.open if fn.endswith(".gz") else open
        try:
            with op(fn, "rt") as f:
                for ln in f:
                    try:
                        yield json.loads(ln)
                    except (ValueError, json.JSONDecodeError):
                        continue
        except OSError:
            continue


def load_can():
    """id -> sorted [(t, bytes)]."""
    by_id: dict[str, list] = defaultdict(list)
    for e in _load("data/xanbus/xanbus-*.jsonl.gz", "data/xanbus/xanbus.jsonl"):
        try:
            by_id[e["id"]].append((e["t"], bytes.fromhex(e["d"])))
        except (KeyError, ValueError):
            continue
    for v in by_id.values():
        v.sort()
    return by_id


def load_modbus():
    """(slave, reg) -> sorted [(t, value_u16)] for registers that appear."""
    series: dict[tuple, list] = defaultdict(list)
    for e in _load("data/modbus/modbus-*.jsonl.gz", "data/modbus/modbus.jsonl"):
        t, slave, regs = e.get("t"), e.get("slave"), e.get("regs", {})
        if t is None:
            continue
        for r, v in regs.items():
            series[(slave, int(r))].append((t, v))
    for v in series.values():
        v.sort()
    return series


def _nearest_before(seq, t, max_lag):
    """Latest (t', payload) with t' <= t and t - t' <= max_lag, via a moving cursor."""
    lo, hi = 0, len(seq)
    while lo < hi:
        mid = (lo + hi) // 2
        if seq[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    i = lo - 1
    if i < 0 or t - seq[i][0] > max_lag:
        return None
    return seq[i][1]


def _extract(payload: bytes, off: int, width: int, big: bool, signed: bool):
    if off + width > len(payload):
        return None
    return int.from_bytes(payload[off:off + width], "big" if big else "little", signed=signed)


def _pearson(xs, ys):
    n = len(xs)
    if n < 20:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def _fit(xs, ys):
    """Least-squares ys ~ a*xs + b -> (a, b)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    a = sxy / sxx if sxx else 0.0
    return a, my - a * mx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-r", type=float, default=0.95)
    ap.add_argument("--max-lag", type=float, default=2.0)
    ap.add_argument("--min-samples", type=int, default=20)
    args = ap.parse_args()

    can = load_can()
    modbus = load_modbus()
    print(f"loaded: {sum(len(v) for v in can.values())} CAN frames across {len(can)} IDs; "
          f"{len(modbus)} modbus register-series\n")

    catalog(can)

    # Only bother with Modbus registers that actually move.
    varying = {}
    for key, seq in modbus.items():
        vals = [v for _, v in seq]
        if len(vals) >= args.min_samples and (max(vals) - min(vals)) > 0:
            varying[key] = seq
    print(f"{len(varying)} modbus registers vary (searchable)\n")

    matches = []
    for (slave, reg), mseq in varying.items():
        mvals = [v for _, v in mseq]
        best = None
        for cid, cseq in can.items():
            # align: modbus value at time t vs latest CAN payload for this id <= t
            xs, ys, payload_len = [], [], 0
            aligned = []
            for t, mv in mseq:
                p = _nearest_before(cseq, t, args.max_lag)
                if p is not None:
                    aligned.append((mv, p))
                    payload_len = max(payload_len, len(p))
            if len(aligned) < args.min_samples:
                continue
            for off in range(payload_len):
                for width in (1, 2, 4):
                    for big in (True, False):
                        for signed in (False, True):
                            xs, ys = [], []
                            for mv, p in aligned:
                                cv = _extract(p, off, width, big, signed)
                                if cv is None:
                                    xs = []
                                    break
                                xs.append(cv)
                                ys.append(mv)
                            if not xs or (max(xs) - min(xs)) == 0:
                                continue
                            r = _pearson(xs, ys)
                            if abs(r) >= args.min_r and (best is None or abs(r) > abs(best[0])):
                                a, b = _fit(xs, ys)
                                best = (r, cid, off, width, big, signed, a, b, len(xs))
        if best:
            matches.append(((slave, reg), best))

    matches.sort(key=lambda m: -abs(m[1][0]))
    if not matches:
        print("no confident CAN<->Modbus correlations yet — need more time-varying data "
              "(re-run after a few hours, ideally spanning daytime solar/load swings).")
        return 0
    print(f"{len(matches)} decode candidates (|r| >= {args.min_r}):\n")
    for (slave, reg), (r, cid, off, width, big, signed, a, b, n) in matches:
        label = KNOWN.get((slave, reg), "")
        endian = "BE" if big else "LE"
        sgn = "s" if signed else "u"
        print(f"  modbus[{slave}:{reg}]{' '+label if label else '':<28} "
              f"<- CAN {cid} byte {off} {sgn}{width*8}{endian}  "
              f"r={r:+.3f}  modbus≈{a:.4g}*can+{b:.4g}  (n={n})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
