"""Insight Home Modbus/TCP poller — records register snapshots for decoding.

Polls the Schneider Conext gateway (192.168.1.71:503) every INTERVAL s and reads
the holding registers from the responsive slaves (gateway=1, MPPT60=30,
SW-inv=90 — BattMon 190 has no data). Because the server exceptions on any
invalid address in a block, it reads small 16-register chunks and merges the
readable ones into a per-slave {addr: value} snapshot, appended to
data/modbus/modbus.jsonl (rotating gzip).

This is both the "record Modbus/TCP" stream and the ground-truth timeseries to
correlate against the Xanbus CAN capture (decode Schneider's proprietary PGNs →
retire the Insight Home). Access requires the Pi's IP whitelisted on the
Insight Home Modbus config. See memory: wired-integration.
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import signal
import socket
import struct
import time
from pathlib import Path

HOST, PORT = "192.168.1.71", 503
SLAVES = (1, 30, 90)                   # gateway, MPPT60, SW inverter
SCAN_END = 384                         # sweep registers 0..SCAN_END in 16-reg chunks
CHUNK = 16
INTERVAL = 10.0
OUTDIR = Path("data/modbus")
CUR = OUTDIR / "modbus.jsonl"
ROTATE_BYTES = 10 * 1024 * 1024
# Match the CAN capture's generous retention (~months here; modbus is small).
# 1000 gz × ≤1 MB ≈ 1 GB worst case — trivial vs the 49 GB free.
KEEP_GZ = 1000

_stop = False
_tid = 0


def _sig(*_a):
    global _stop
    _stop = True


def _read_block(slave: int, base: int, count: int, timeout: float = 1.2):
    """Read `count` holding registers at `base` from `slave`. Returns a list of
    u16, or None on exception/no-response (e.g. an invalid address in the block)."""
    global _tid
    _tid = (_tid + 1) & 0xFFFF
    try:
        s = socket.create_connection((HOST, PORT), timeout=3)
        s.settimeout(timeout)
    except OSError:
        return None
    pdu = bytes([3, (base >> 8) & 255, base & 255, (count >> 8) & 255, count & 255])
    try:
        s.sendall(struct.pack(">HHHB", _tid, 0, len(pdu) + 1, slave) + pdu)
        r = s.recv(600)
    except OSError:
        r = b""
    finally:
        s.close()
    if len(r) >= 9 and r[7] == 3:
        data = r[9:9 + r[8]]
        return list(struct.unpack(">%dH" % (len(data) // 2), data))
    return None


def _snapshot(slave: int) -> dict:
    """Merge all readable 16-reg chunks into {addr: value} for one slave."""
    regs: dict[str, int] = {}
    for base in range(0, SCAN_END, CHUNK):
        block = _read_block(slave, base, CHUNK)
        if block is None:
            continue
        for i, v in enumerate(block):
            regs[str(base + i)] = v
    return regs


def _rotate(f):
    f.close()
    ts = time.strftime("%Y%m%d-%H%M%S")
    gz = OUTDIR / f"modbus-{ts}.jsonl.gz"
    with open(CUR, "rb") as src, gzip.open(gz, "wb") as dst:
        dst.writelines(src)
    CUR.unlink()
    for old in sorted(glob.glob(str(OUTDIR / "modbus-*.jsonl.gz")))[:-KEEP_GZ]:
        try:
            os.unlink(old)
        except OSError:
            pass
    return open(CUR, "a")


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _sig)
    f = open(CUR, "a")
    n = 0
    while not _stop:
        t0 = time.time()
        for slave in SLAVES:
            regs = _snapshot(slave)
            if regs:
                f.write(json.dumps({"t": round(time.time(), 3), "slave": slave, "regs": regs}) + "\n")
        f.flush()
        n += 1
        if n % 50 == 0 and CUR.exists() and CUR.stat().st_size >= ROTATE_BYTES:
            f = _rotate(f)
        end = time.time() + max(0.0, INTERVAL - (time.time() - t0))
        while time.time() < end and not _stop:
            time.sleep(0.5)
    f.flush()
    f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
