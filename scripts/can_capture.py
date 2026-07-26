"""Xanbus (CAN) raw capture — logs every frame to rotating, gzip'd JSONL.

`can0` must be up listen-only @ 250 kbit/s (the systemd unit's ExecStartPre does
that). Reads a raw AF_CAN socket (no can-utils needed) and appends compact lines
    {"t": epoch, "id": "0xHEX", "ext": bool, "d": "hex"}
to data/xanbus/xanbus.jsonl, rotating to xanbus-<ts>.jsonl.gz at a size cap and
pruning to a fixed count. Purpose: the raw record + the ground-truth CAN stream
to correlate against Modbus, so we can decode Schneider's proprietary PGNs and
eventually retire the Insight Home. See memory: wired-integration.
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

CAN_FRAME = "=IB3x8s"                 # can_id(4), dlc(1), pad(3), data(8)
OUTDIR = Path("data/xanbus")
CUR = OUTDIR / "xanbus.jsonl"
ROTATE_BYTES = 20 * 1024 * 1024       # 20 MB per raw file (~10x smaller gzip'd)
KEEP_GZ = 60                          # rotated files to retain

_stop = False


def _sig(*_a):
    global _stop
    _stop = True


def _rotate(f):
    f.close()
    ts = time.strftime("%Y%m%d-%H%M%S")
    gz = OUTDIR / f"xanbus-{ts}.jsonl.gz"
    with open(CUR, "rb") as src, gzip.open(gz, "wb") as dst:
        dst.writelines(src)
    CUR.unlink()
    for old in sorted(glob.glob(str(OUTDIR / "xanbus-*.jsonl.gz")))[:-KEEP_GZ]:
        try:
            os.unlink(old)
        except OSError:
            pass
    return open(CUR, "a")


def main() -> int:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _sig)
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind(("can0",))
    sock.settimeout(1.0)
    f = open(CUR, "a")
    n = 0
    try:
        while not _stop:
            try:
                frame = sock.recv(16)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(1.0)
                continue
            cid, dlc, data = struct.unpack(CAN_FRAME, frame)
            eff = bool(cid & socket.CAN_EFF_FLAG)
            arb = cid & (socket.CAN_EFF_MASK if eff else socket.CAN_SFF_MASK)
            f.write(json.dumps({"t": round(time.time(), 3), "id": "0x%X" % arb,
                                "ext": eff, "d": data[:dlc].hex()}) + "\n")
            n += 1
            if n % 1000 == 0:
                f.flush()
                if CUR.stat().st_size >= ROTATE_BYTES:
                    f = _rotate(f)
    finally:
        f.flush()
        f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
