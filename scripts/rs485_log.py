"""Headless WIRED logger — polls both batteries over RS-485 and appends to the
same CSV the BLE logger writes, so the existing cloud uploader ships it unchanged.

Why wired: the BLE path suffers dormancy/wedge failure modes (a leaked GATT
link, a deaf adapter, a BMS BLE radio that hangs for hours). RS-485 is a
separate BMS interface that stays alive through all of that — validated
2026-07-25 reading a battery that was simultaneously BLE-dormant. This logger
is the "record from RS-485 instead of BLE" path; it deliberately has NONE of the
BLE recovery machinery (adapter resets, ambient scanner, wedge ladder) because
none of it applies to a wire.

Serial handles are held open and reopened on error. On any exit the event
segment is sealed so diagnostics reach Railway.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.estimator import Estimator
from volthium.pack import PackReading, _event, _missing_reading, decode_alarms, seal_event_log
from volthium.rs485 import open_port, read_battery

# Reuse the exact CSV schema / writer / charger thresholds from the BLE logger so
# the on-disk format and the uploader are identical. (Importing `log` pulls in the
# BLE stack, which is harmless — we just don't use it.)
from log import (  # noqa: E402
    CHARGER_DEBOUNCE_CYCLES,
    CHARGER_DIVERGENCE_A,
    _archive_if_schema_drift,
    _present,
    append_csv,
)

_STOP = False


def _on_signal(signum, _frame):
    global _STOP
    _STOP = True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-port", required=True, help="serial device for battery A")
    ap.add_argument("--b-port", required=True, help="serial device for battery B")
    ap.add_argument("--a-addr", default="09:01:00:14:7E:DC")
    ap.add_argument("--b-addr", default="09:01:00:11:55:DF")
    ap.add_argument("--a-name", default="V-12V200AH-0533")
    ap.add_argument("--b-name", default="V-12V200AH-0667")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--log", type=Path, help="human-readable progress log")
    args = ap.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    log = logging.getLogger("volthium-rs485")
    log.info("starting RS485: csv=%s interval=%.1fs A=%s(%s) B=%s(%s)",
             args.csv, args.interval, args.a_port, args.a_name, args.b_port, args.b_name)
    _archive_if_schema_drift(args.csv, log)
    _event("rs485_start", a_port=args.a_port, b_port=args.b_port, interval=args.interval)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    est = Estimator()
    ports: dict[str, Optional[serial.Serial]] = {"a": None, "b": None}
    cfg = {"a": (args.a_port, args.a_addr, args.a_name),
           "b": (args.b_port, args.b_addr, args.b_name)}

    def read_one(key):
        """Return (BatteryReading|None). Reopens the port on a serial error."""
        port, addr, name = cfg[key]
        try:
            if ports[key] is None:
                ports[key] = open_port(port)
            return read_battery(ports[key], addr, name)
        except (serial.SerialException, OSError) as exc:
            _event("rs485_port_error", battery=key.upper(), port=port,
                   error_type=type(exc).__name__, error_str=str(exc)[:120])
            try:
                if ports[key]:
                    ports[key].close()
            except Exception:  # noqa: BLE001
                pass
            ports[key] = None
            return None

    n = 0
    consec_fail = 0
    prev_present = None
    charger_on = False
    chg_hi = chg_lo = 0
    prev_flags: dict[str, tuple] = {}

    try:
        while not _STOP:
            t0 = time.monotonic()
            ra = read_one("a")
            rb = read_one("b")

            if ra is None and rb is None:
                consec_fail += 1
                _event("read_fail", note="neither battery answered RS485",
                       consec=consec_fail)
                if consec_fail in (1, 5, 30) or consec_fail % 60 == 0:
                    log.warning("RS485 read failed (%d in a row)", consec_fail)
                time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))
                continue
            if consec_fail:
                log.info("RS485 recovered after %d failures", consec_fail)
            consec_fail = 0

            pack = PackReading(a=ra or _missing_reading(args.a_addr),
                               b=rb or _missing_reading(args.b_addr), wedged=[])
            estimate = est.update(pack)
            append_csv(args.csv, pack, estimate)
            n += 1

            for key, br in (("A", ra), ("B", rb)):
                if br is not None:
                    _event("read_ok", address=br.address.upper(), soc=br.soc,
                           voltage=br.voltage, current=br.current, temp=br.temperature,
                           problem_code=br.problem_code, transport="rs485")

            present = (_present(pack.a), _present(pack.b))
            if present != prev_present:
                log.warning("battery presence: A=%s B=%s", "up" if present[0] else "DOWN",
                            "up" if present[1] else "DOWN")
                prev_present = present

            # Charger / manual-balance detection — identical logic to the BLE logger.
            ia, ib = pack.a.current, pack.b.current
            if ia is not None and ib is not None:
                if abs(ia - ib) >= CHARGER_DIVERGENCE_A:
                    chg_hi += 1; chg_lo = 0
                else:
                    chg_lo += 1; chg_hi = 0
                if not charger_on and chg_hi >= CHARGER_DEBOUNCE_CYCLES:
                    charger_on = True
                    target = "B" if ib > ia else "A"
                    log.warning("charger detected — balancing %s (i_a=%+.1f i_b=%+.1f)", target, ia, ib)
                    _event("charger_state", state="on", charging=target, i_a=ia, i_b=ib,
                           divergence_a=round(abs(ia - ib), 1))
                elif charger_on and chg_lo >= CHARGER_DEBOUNCE_CYCLES:
                    charger_on = False
                    log.info("charger removed (i_a=%+.1f i_b=%+.1f)", ia, ib)
                    _event("charger_state", state="off", i_a=ia, i_b=ib)

            # BMS flags — edge-triggered (baseline at start + on change), like the BLE logger.
            for br in (pack.a, pack.b):
                if not _present(br):
                    continue
                k = br.address.upper()
                cur = (tuple(br.alarms), br.heater, bool(br.balancer))
                prev = prev_flags.get(k)
                if prev is None or cur != prev:
                    if br.alarms and (prev is None or set(br.alarms) - set(prev[0])):
                        log.warning("BMS alarm on %s: %s", k, br.alarms)
                    _event("bms_flags", address=k, alarms=br.alarms or None, heater=br.heater,
                           balancing=bool(br.balancer), balancer_raw=br.balancer,
                           baseline=prev is None or None)
                prev_flags[k] = cur

            if n == 1 or n % 30 == 0:
                p = pack.pack_power
                log.info("n=%d  %s  SOC %s-%s  state=%s", n,
                         ("%.2fV %+.1fA %.0fW" % (pack.pack_voltage, pack.pack_current, p))
                         if p is not None else "partial",
                         pack.a.soc, pack.b.soc, estimate.state)

            time.sleep(max(0.0, args.interval - (time.monotonic() - t0)))
    finally:
        for s in ports.values():
            try:
                if s:
                    s.close()
            except Exception:  # noqa: BLE001
                pass
        _event("rs485_stop", cycles=n)
        seal_event_log()
    return 0


if __name__ == "__main__":
    sys.exit(main())
