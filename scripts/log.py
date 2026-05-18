"""Headless logger — polls both batteries on a fixed interval and appends to CSV.

Designed to run unattended for hours/days. Survives BLE flaps by backing off and
retrying. Writes a separate human-readable progress log so we can scan it without
parsing CSV.
"""

import argparse
import asyncio
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.estimator import Estimator
from volthium.pack import read_pack


CSV_FIELDS = [
    "ts", "state",
    "pack_v", "pack_i", "pack_p",
    "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
    "t_a", "t_b",
    "remaining_ah_a", "remaining_ah_b",
    "delta_v_a", "delta_v_b",
    "smoothed_i", "smoothed_p", "minutes_remaining",
    "name_a", "name_b",   # BMS-reported advertised names; display layer derives labels
]


def append_csv(path: Path, pack, est) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "state": est.state,
            "pack_v": pack.pack_voltage,
            "pack_i": pack.pack_current,
            "pack_p": pack.pack_power,
            "soc_a": pack.a.soc, "soc_b": pack.b.soc,
            "v_a": pack.a.voltage, "v_b": pack.b.voltage,
            "i_a": pack.a.current, "i_b": pack.b.current,
            "t_a": pack.a.temperature, "t_b": pack.b.temperature,
            "remaining_ah_a": pack.a.remaining_ah,
            "remaining_ah_b": pack.b.remaining_ah,
            "delta_v_a": pack.a.delta_voltage,
            "delta_v_b": pack.b.delta_voltage,
            "smoothed_i": est.smoothed_current,
            "smoothed_p": est.smoothed_power,
            "minutes_remaining": est.minutes_remaining,
            "name_a": pack.a.name,
            "name_b": pack.b.name,
        })


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--log", type=Path, help="human-readable progress log")
    args = ap.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    log = logging.getLogger("volthium-logger")
    log.info("starting: csv=%s interval=%.1fs a=%s b=%s",
             args.csv, args.interval, args.a, args.b)

    est = Estimator()
    consec_errors = 0
    n = 0

    while True:
        t0 = time.monotonic()
        try:
            pack = await read_pack(args.a, args.b)
            estimate = est.update(pack)
            append_csv(args.csv, pack, estimate)
            n += 1
            if consec_errors:
                log.info("BLE recovered after %d errors", consec_errors)
            consec_errors = 0
            # every ~5 min at 10s interval, drop a progress line
            if n == 1 or n % 30 == 0:
                log.info(
                    "n=%d  %.2fV  %+.2fA  %+.0fW  SOC %.0f-%.0f%%  state=%s  remain≈%s",
                    n,
                    pack.pack_voltage or 0.0,
                    pack.pack_current or 0.0,
                    pack.pack_power or 0.0,
                    pack.min_soc or 0,
                    pack.max_soc or 0,
                    estimate.state,
                    f"{estimate.minutes_remaining:.0f}m" if estimate.minutes_remaining else "—",
                )
        except Exception as exc:  # noqa: BLE001 — yes, we really do want to catch everything here
            consec_errors += 1
            log.warning("read #%d failed (%d in a row): %s: %s",
                        n + 1, consec_errors, type(exc).__name__, exc)
            # exponential-ish backoff so we don't hammer a flaky link
            if consec_errors > 3:
                await asyncio.sleep(min(60.0, 5.0 * consec_errors))

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, args.interval - elapsed))


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()) or 0)
    except KeyboardInterrupt:
        sys.exit(0)
