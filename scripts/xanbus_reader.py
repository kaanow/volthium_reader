"""Xanbus (Conext CAN) telemetry reader — decode solar/inverter values directly
off the bus, to replace the Insight Home Modbus path.

Field layouts are from berrybms (github.com/extrafu/berrybms), cross-checked
against Schneider's Conext Modbus maps and validated against our own capture
corpus. All multi-byte values little-endian; the fast-packet payload is the
reassembled buffer (header stripped by reassembly), so offsets are into that.

Priority fields (all HIGH confidence):
  PGN 127172  battery DC status   V u32@2 /1000 V, I s32@6 /1000 A, P s32@10 W
  PGN 127173  DC source status    same layout; assoc byte@1 selects the source:
                                   0x03 = battery, 0x15 = PV array (from MPPT)
  PGN 126990  charge status       chg_mode u16@13 (768 base; see CHARGE_STAGE)
  PGN 127165  inverter status     u16@2 (1024 base; see INVERTER_STATUS)

Two modes:
  --validate DIR   decode a pulled corpus and correlate each CAN-decoded field
                   against the Schneider-mapped Modbus register (proves the
                   decode on our hardware, off the Pi).
  (default/live)   decode live can0 and print labeled snapshots — this is the
                   lightweight, streaming form that will run on the Pi.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import struct
import time
from collections import defaultdict

CHARGE_STAGE = {768: "not-charging", 769: "bulk", 770: "absorption", 771: "overcharge",
                772: "equalize", 773: "float", 774: "no-float", 775: "constant-VI",
                776: "disabled", 777: "qualifying-AC", 779: "engaging", 780: "fault",
                781: "suspend", 782: "AC-good", 784: "AC-fault", 785: "charge"}
INVERTER_STATUS = {1024: "invert", 1025: "AC-passthrough", 1026: "APS-only",
                   1027: "load-sense", 1028: "disabled", 1029: "load-sense-ready",
                   1030: "engaging", 1031: "fault", 1032: "standby", 1033: "grid-tied",
                   1034: "grid-support", 1035: "gen-support", 1036: "sell-to-grid"}

ASSOC_BATTERY, ASSOC_PV = 0x03, 0x15


def parse_id(arb: int):
    """29-bit arbitration id -> (pgn, src)."""
    pf, ps = (arb >> 16) & 0xFF, (arb >> 8) & 0xFF
    dp = (arb >> 24) & 0x3
    pgn = (dp << 16) | (pf << 8) | (ps if pf >= 240 else 0)
    return pgn, arb & 0xFF


def reassemble(seq):
    """NMEA2000 fast-packet reassembly -> [(t, full_payload)]. (Standard and
    berrybms nibble splits are identical for these <=16-frame PGNs.)"""
    msgs, cur = [], None
    counter = expected = size = 0
    for t, p in seq:
        if not p:
            continue
        idx, ctr = p[0] & 0x1F, p[0] >> 5
        if idx == 0:
            size, cur, counter, expected = p[1], (t, bytearray(p[2:])), ctr, 1
        elif cur is not None and ctr == counter and idx == expected:
            cur[1].extend(p[1:])
            expected += 1
        else:
            cur = None
            continue
        if cur is not None and len(cur[1]) >= size:
            msgs.append((cur[0], bytes(cur[1][:size])))
            cur = None
    return msgs


def decode_vip(payload: bytes):
    """(status, assoc, V, I, P) from a 127172/127173 payload, or None."""
    if len(payload) < 14:
        return None
    status, assoc, v, i, p = struct.unpack_from("<BBIii", payload, 0)
    return status, assoc, v / 1000.0, i / 1000.0, float(p)


# ------------------------- validation against corpus -------------------------

# Schneider-mapped Modbus registers to check each CAN-decoded field against.
# (slave, [candidate raw-PDU registers], scale) — we auto-pick the register that
# actually tracks, which also pins the known Schneider +/-1 addressing quirk.
MODBUS_CHECK = {
    "batt_V": (90, [78, 79], 0.001),      # SW inverter battery voltage
    "pv_V":   (30, [76, 77], 0.001),      # MPPT PV array voltage
    "pv_I":   (30, [78, 79], 0.001),      # MPPT PV array current
    "pv_W":   (30, [80, 81], 1.0),        # MPPT PV input power
}


def _read_can(data_dir, cutoff):
    seqs = defaultdict(list)
    files = [f"{data_dir}/xanbus/xanbus.jsonl"] + sorted(
        glob.glob(f"{data_dir}/xanbus/xanbus-*.jsonl.gz"), reverse=True)
    for fn in files:
        op = gzip.open if fn.endswith(".gz") else open
        kept = 0
        try:
            with op(fn, "rt") as f:
                for ln in f:
                    try:
                        e = json.loads(ln)
                    except ValueError:
                        continue
                    t = e.get("t")
                    if t is None or t < cutoff:
                        continue
                    pgn, src = parse_id(int(e["id"], 16))
                    if pgn in (127172, 127173):
                        seqs[(pgn, src)].append((t, bytes.fromhex(e["d"])))
                        kept += 1
        except OSError:
            continue
        if kept == 0 and seqs:
            break
    for v in seqs.values():
        v.sort()
    return seqs


def _read_modbus(data_dir, cutoff):
    series = defaultdict(list)
    files = [f"{data_dir}/modbus/modbus.jsonl"] + sorted(
        glob.glob(f"{data_dir}/modbus/modbus-*.jsonl.gz"), reverse=True)
    for fn in files:
        op = gzip.open if fn.endswith(".gz") else open
        kept = 0
        try:
            with op(fn, "rt") as f:
                for ln in f:
                    try:
                        e = json.loads(ln)
                    except ValueError:
                        continue
                    t, slave, regs = e.get("t"), e.get("slave"), e.get("regs", {})
                    if t is None or t < cutoff:
                        continue
                    for r, val in regs.items():
                        series[(slave, int(r))].append((t, val))
                    kept += 1
        except OSError:
            continue
        if kept == 0 and series:
            break
    for v in series.values():
        v.sort()
    return series


def _pearson(xs, ys):
    n = len(xs)
    if n < 10:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    return sxy / (sxx * syy) ** 0.5 if sxx > 0 and syy > 0 else 0.0


def _nearest(seq, t, lag=3.0):
    best = None
    for tt, v in seq:
        if tt <= t and t - tt <= lag:
            best = v
        elif tt > t:
            break
    return best


def _decoded_series(seqs, pgn, want_assoc):
    """time-ordered (t, {V,I,P}) for one PGN/source filtered by assoc byte."""
    out = []
    for (p, src), seq in seqs.items():
        if p != pgn:
            continue
        for t, payload in reassemble(seq):
            d = decode_vip(payload)
            if d and d[1] == want_assoc:
                out.append((t, {"V": d[2], "I": d[3], "P": d[4]}))
    out.sort(key=lambda x: x[0])
    return out


def validate(data_dir, hours):
    cutoff = time.time() - hours * 3600
    print(f"loading corpus '{data_dir}' (last {hours:g}h)...")
    seqs = _read_can(data_dir, cutoff)
    modbus = _read_modbus(data_dir, cutoff)
    print(f"  {sum(len(v) for v in seqs.values())} CAN frames, "
          f"{len(modbus)} modbus register-series\n")

    # CAN-decoded series: battery from 127172 (assoc 0x03), PV from 127173 (0x15).
    batt = _decoded_series(seqs, 127172, ASSOC_BATTERY)
    pv = _decoded_series(seqs, 127173, ASSOC_PV)
    can_series = {"batt_V": [(t, d["V"]) for t, d in batt],
                  "pv_V": [(t, d["V"]) for t, d in pv],
                  "pv_I": [(t, d["I"]) for t, d in pv],
                  "pv_W": [(t, d["P"]) for t, d in pv]}

    print(f"{'field':8} {'pairs':>7} {'reg':>8} {'r':>7} "
          f"{'CAN peak':>9} {'mb peak':>9} {'CAN day-med':>11} {'mb day-med':>11}")
    for field, cs in can_series.items():
        slave, regs, scale = MODBUS_CHECK[field]
        if not cs:
            print(f"{field:8} {'0':>7}  (no CAN data)")
            continue
        best = None
        for reg in regs:
            ms = modbus.get((slave, reg), [])
            xs, ys = [], []
            for t, cv in cs:
                mv = _nearest(ms, t)
                if mv is not None:
                    xs.append(cv)
                    ys.append(mv * scale)
            if len(xs) >= 10:
                r = _pearson(xs, ys)
                if best is None or abs(r) > abs(best[1]):
                    best = (reg, r, xs, ys)
        if best is None:
            print(f"{field:8} {len(cs):>7}  (no overlapping modbus samples)")
            continue
        reg, r, xs, ys = best
        # Daytime = the pairs where THIS field is active (top tercile of |CAN|),
        # so PV isn't washed out by night zeros. Peaks show the 0->max sweep.
        thr = sorted(abs(x) for x in xs)[int(len(xs) * 0.67)]
        day = [(x, y) for x, y in zip(xs, ys) if abs(x) >= max(thr, 1e-6)]
        cday = sorted(x for x, _ in day)
        mday = sorted(y for _, y in day)
        cmed = cday[len(cday) // 2] if cday else 0.0
        mmed = mday[len(mday) // 2] if mday else 0.0
        print(f"{field:8} {len(xs):>7} {f'{slave}:{reg}':>8} {r:>+7.3f} "
              f"{max(xs):>9.2f} {max(ys):>9.2f} {cmed:>11.2f} {mmed:>11.2f}")
    print("\n(r near +1 and matching day-medians/peaks = decode confirmed.)")


def live(interval):  # pragma: no cover - runs on the Pi
    import socket
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind(("can0",))
    sock.settimeout(1.0)
    seqs = defaultdict(list)
    last = time.time()
    while True:
        try:
            frame = sock.recv(16)
        except socket.timeout:
            frame = None
        if frame:
            cid, dlc, data = struct.unpack("=IB3x8s", frame)
            arb = cid & 0x1FFFFFFF
            pgn, src = parse_id(arb)
            if pgn in (127172, 127173, 126990, 127165):
                seqs[(pgn, src)].append((time.time(), data[:dlc]))
                if len(seqs[(pgn, src)]) > 64:
                    seqs[(pgn, src)] = seqs[(pgn, src)][-64:]
        if time.time() - last >= interval:
            snap = {}
            for (pgn, src), seq in seqs.items():
                for _, payload in reassemble(seq)[-1:]:
                    d = decode_vip(payload) if pgn in (127172, 127173) else None
                    if d and pgn == 127172:
                        snap["batt_V"], snap["batt_I"], snap["batt_W"] = d[2], d[3], d[4]
                    elif d and pgn == 127173 and d[1] == ASSOC_PV:
                        snap["pv_V"], snap["pv_I"], snap["pv_W"] = d[2], d[3], d[4]
            print(json.dumps({"t": round(time.time(), 1), **snap}))
            last = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", metavar="DIR", help="validate against a pulled corpus")
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    if args.validate:
        validate(args.validate, args.hours)
    else:
        live(args.interval)


if __name__ == "__main__":
    main()
