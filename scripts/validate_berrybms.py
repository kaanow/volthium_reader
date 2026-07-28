"""Validate berrybms's reverse-engineered Conext Xanbus PGN layouts against our
own captured corpus + known ground truth. Runs OFF the Pi against a pulled dir.

Checks the two open questions from the CAN research:
  1. fast-packet split: standard NMEA2000 (seq=b0>>5, idx=b0&0x1F) vs berrybms
     nibble (seq=b0>>4, idx=b0&0x0F). We pick whichever yields sane voltages.
  2. the priority PGN layouts: 127172/127173 = <BBIii (status, assoc, V u32 /1000,
     I s32 /1000, P s32); assoc@1 on 127173 flags 0x03 battery / 0x15 PV.

Usage: python3 scripts/validate_berrybms.py [--data-dir captures] [--hours 6]
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics
import struct
import time
from collections import defaultdict

# PGN -> label; arb id base = 0x18000000|dp<<24|pf<<16|ps<<8, +src. All PDU2 pri6.
PGN_IDS = {
    127172: "BattSts2 (battery DC)",
    127173: "DcSrcSts2 (DC source; assoc 0x03=batt 0x15=PV)",
    127003: "BattMonSts (SOC/Ah)",
}


def _pgn_of(arb: int):
    pf = (arb >> 16) & 0xFF
    ps = (arb >> 8) & 0xFF
    dp = (arb >> 24) & 0x3
    if pf < 240:
        return (dp << 16) | (pf << 8)
    return (dp << 16) | (pf << 8) | ps


def _src_of(arb: int):
    return arb & 0xFF


def _read(data_dir: str, hours: float):
    cutoff = time.time() - hours * 3600
    seqs = defaultdict(list)      # arb_hex -> [(t, bytes)]
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
                    arb = int(e["id"], 16)
                    if _pgn_of(arb) in PGN_IDS:
                        seqs[e["id"]].append((t, bytes.fromhex(e["d"])))
                        kept += 1
        except OSError:
            continue
        if kept == 0 and seqs:
            break
    for v in seqs.values():
        v.sort()
    return seqs


def reassemble(seq, nibble: bool):
    """Fast-packet reassembly with a selectable seq/idx split."""
    shift, mask = (4, 0x0F) if nibble else (5, 0x1F)
    msgs = []
    cur = None
    counter = expected = size = 0
    for t, p in seq:
        if not p:
            continue
        idx, ctr = p[0] & mask, p[0] >> shift
        if idx == 0:
            size = p[1]
            cur = (t, bytearray(p[2:]))
            counter, expected = ctr, 1
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
    """<BBIii head: status u8, assoc u8, V u32 /1000, I s32 /1000, P s32."""
    if len(payload) < 14:
        return None
    status, assoc, v, i, p = struct.unpack_from("<BBIii", payload, 0)
    return status, assoc, v / 1000.0, i / 1000.0, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="captures")
    ap.add_argument("--hours", type=float, default=6.0)
    args = ap.parse_args()

    seqs = _read(args.data_dir, args.hours)
    print(f"loaded {sum(len(v) for v in seqs.values())} frames across "
          f"{len(seqs)} ids for PGNs {sorted(PGN_IDS)}\n")

    for split_name, nibble in (("standard(>>5)", False), ("berrybms-nibble(>>4)", True)):
        print(f"=== fast-packet split: {split_name} ===")
        for arb_hex, seq in sorted(seqs.items()):
            arb = int(arb_hex, 16)
            pgn, src = _pgn_of(arb), _src_of(arb)
            msgs = reassemble(seq, nibble)
            vs, assocs = [], defaultdict(int)
            for _, payload in msgs:
                d = decode_vip(payload)
                if d:
                    vs.append(d[2])
                    assocs[d[1]] += 1
            if not vs:
                continue
            vmed = statistics.median(vs)
            sane = "  <-- SANE ~26V" if 20 <= vmed <= 32 else ""
            amap = " ".join(f"0x{a:02x}:{c}" for a, c in sorted(assocs.items()))
            print(f"  PGN {pgn} src{src} ({PGN_IDS[pgn]}): "
                  f"{len(msgs)} msgs, V median={vmed:.2f}V{sane}")
            print(f"      assoc-byte@1 histogram: {amap}")
        print()


if __name__ == "__main__":
    main()
