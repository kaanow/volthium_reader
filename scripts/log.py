"""Headless logger — polls both batteries on a fixed interval and appends to CSV.

Designed to run unattended for hours/days. Survives BLE flaps by backing off and
retrying. Writes a separate human-readable progress log so we can scan it without
parsing CSV.

Timestamp policy: this writer stamps `ts` as naive local time (ISO-8601 without
tz). The cloud uploader converts to UTC `Z` on its way out per the project-wide
convention documented in docs/cloud_architecture.md.
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
from volthium.pack import DiscoveryWedgeError, read_pack, recover_adapter


# Per-pack cell count for the SC12200G4DPH (12V LiFePO4 = 4 cells in series).
CELLS_PER_BATTERY = 4

# After this many consecutive TOTAL-read failures, exit so systemd respawns us
# with a fresh BlueZ client (self-heals adapter wedges without an operator).
# With ~10s interval + backoff this is on the order of ~15+ min of hard outage.
RESTART_AFTER_CONSEC_ERRORS = 30

# After this many consecutive cycles with the SAME battery wedged (absent from
# discovery but still holding a controller connection — FM-8), exit for a clean
# restart. This is the *proven* cure: the wedge is a leaked in-process BleakClient
# that pins the battery's radio and auto-reconnects when force-disconnected, so a
# Pi-side disconnect can't shake it but a fresh process drops it instantly (B
# recovered in <10s this way on 2026-06-30). ~6 cycles ≈ 1 min — fast, because we
# KNOW the cure and a restart only costs a single missed sample. Genuinely-off
# batteries never show as connected, so they can't trip this into a restart loop.
RESTART_AFTER_WEDGE_CYCLES = 6

# Stuck-adapter-discovery (FM-3) escalation ladder. A wedged discovery session
# (org.bluez.Error.InProgress) lives in bluetoothd, NOT our process, so a process
# restart can't clear it — the adapter itself must be reset. Escalate by count of
# consecutive discovery failures: soft HCI reset → full bluetooth.service restart
# → finally give up to a process restart (last resort, in case the loop itself is
# the problem). Each level only fires once (==) so we climb the ladder.
ADAPTER_SOFT_RESET_AFTER = 3    # consecutive scan failures → hciconfig reset
ADAPTER_HARD_RESET_AFTER = 6    # still failing → restart bluetooth.service
RESTART_AFTER_SCAN_WEDGE = 15   # adapter resets didn't help → exit for respawn


CSV_FIELDS = [
    "ts", "state",
    "pack_v", "pack_i", "pack_p",
    "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
    "t_a", "t_b",
    "remaining_ah_a", "remaining_ah_b",
    "delta_v_a", "delta_v_b",
    "smoothed_i", "smoothed_p", "minutes_remaining",
    "name_a", "name_b",   # BMS-reported advertised names; display layer derives labels
    # Schema additions 2026-06: per-battery problem code + cell-resolution voltages.
    # Cell columns are 1-indexed (cell_a_1..cell_a_4); empty when the BMS doesn't
    # report them. See docs/cloud_architecture.md for why cells are stored as
    # separate CSV columns but an array on the cloud wire.
    "problem_code_a", "problem_code_b",
    "cell_a_1", "cell_a_2", "cell_a_3", "cell_a_4",
    "cell_b_1", "cell_b_2", "cell_b_3", "cell_b_4",
]


def _cell_columns(cells: list[float] | None) -> dict[str, float | None]:
    """Return {cell_X_1: v, ...} for a single battery, padded/truncated to
    CELLS_PER_BATTERY. Called twice per row (once for A, once for B)."""
    out = [None] * CELLS_PER_BATTERY
    if cells:
        for i, v in enumerate(cells[:CELLS_PER_BATTERY]):
            out[i] = v
    return out


def _present(br) -> bool:
    """True if this battery actually reported data this cycle (vs. an all-None
    placeholder for a battery that dropped off BLE)."""
    return br.soc is not None or br.voltage is not None or br.current is not None


def _archive_if_schema_drift(path: Path, log: logging.Logger) -> None:
    """If `path` exists but its header doesn't match the current CSV_FIELDS,
    rotate it to `path.vN-HHMM` (matching the existing data/pack.csv.v0-1512
    convention) and let the next write start a fresh file.

    Schema drift here means: the on-disk header was written by an older logger
    that didn't know about the columns we added below. Appending new rows with
    extra columns to a file with a shorter header would silently corrupt the
    CSV alignment.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r", newline="") as f:
        first = f.readline().strip()
    on_disk = first.split(",") if first else []
    if on_disk == CSV_FIELDS:
        return
    # Find the next free version slot, e.g. v1-1530 → v2-1530 if collision
    suffix = datetime.now().strftime("%H%M")
    n = 1
    while True:
        candidate = path.with_suffix(path.suffix + f".v{n}-{suffix}")
        if not candidate.exists():
            break
        n += 1
    path.rename(candidate)
    log.warning(
        "CSV schema drift: archived old file with %d cols → %s; "
        "new file will use the current %d-col schema",
        len(on_disk), candidate.name, len(CSV_FIELDS),
    )


def append_csv(path: Path, pack, est) -> None:
    new = not path.exists()
    cells_a = _cell_columns(pack.a.cell_voltages)
    cells_b = _cell_columns(pack.b.cell_voltages)
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
            "problem_code_a": pack.a.problem_code,
            "problem_code_b": pack.b.problem_code,
            "cell_a_1": cells_a[0], "cell_a_2": cells_a[1],
            "cell_a_3": cells_a[2], "cell_a_4": cells_a[3],
            "cell_b_1": cells_b[0], "cell_b_2": cells_b[1],
            "cell_b_3": cells_b[2], "cell_b_4": cells_b[3],
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
    _archive_if_schema_drift(args.csv, log)

    est = Estimator()
    consec_errors = 0
    consec_scan_errors = 0              # consecutive discovery-wedge failures (FM-3)
    n = 0
    prev_present: tuple[bool, bool] | None = None
    wedge_streak: dict[str, int] = {}   # address → consecutive wedged cycles

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
            consec_scan_errors = 0
            # Visibility into single-battery dropouts (we now log a partial row
            # rather than failing the whole cycle): announce presence changes.
            present = (_present(pack.a), _present(pack.b))
            if present != prev_present:
                log.warning("battery presence: A=%s B=%s%s",
                            "up" if present[0] else "DOWN",
                            "up" if present[1] else "DOWN",
                            "  (partial row — pack totals unavailable)"
                            if not (present[0] and present[1]) else "")
                prev_present = present

            # Wedge escalation (FM-8): read_pack flags any battery that's absent
            # from discovery but still controller-connected — a leaked link that
            # only a fresh process clears. read_pack already tried a force-
            # disconnect; if the same battery stays wedged for too many cycles,
            # exit so systemd respawns us (the proven cure). Reset the streak for
            # any battery that's no longer wedged.
            for addr in list(wedge_streak):
                if addr not in pack.wedged:
                    wedge_streak.pop(addr, None)
            for addr in pack.wedged:
                wedge_streak[addr] = wedge_streak.get(addr, 0) + 1
                log.warning(
                    "BLE wedge: %s absent from discovery but still connected "
                    "(leaked link, FM-8) — streak %d/%d",
                    addr, wedge_streak[addr], RESTART_AFTER_WEDGE_CYCLES)
            if any(v >= RESTART_AFTER_WEDGE_CYCLES for v in wedge_streak.values()):
                stuck = [a for a, v in wedge_streak.items()
                         if v >= RESTART_AFTER_WEDGE_CYCLES]
                log.error(
                    "BLE wedge persisted ≥%d cycles for %s — exiting for a clean "
                    "systemd restart to drop the leaked connection (the proven "
                    "cure; no DC power-cycle needed)",
                    RESTART_AFTER_WEDGE_CYCLES, ",".join(stuck))
                return 1
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
        except DiscoveryWedgeError as exc:
            # FM-3: discovery itself failed (stuck adapter discovery session).
            # A process restart can't clear this — it lives in bluetoothd — so
            # reset the ADAPTER, escalating soft→hard. Each level fires once as
            # the streak climbs; a successful scan resets the counter.
            consec_scan_errors += 1
            log.warning("discovery wedged (#%d, %d scan-errors in a row): %s",
                        n + 1, consec_scan_errors, exc)
            if consec_scan_errors == ADAPTER_SOFT_RESET_AFTER:
                log.error("discovery wedged %d× — resetting the HCI controller",
                          consec_scan_errors)
                action = await recover_adapter(1)
                log.info("adapter recovery (soft): %s", action)
            elif consec_scan_errors == ADAPTER_HARD_RESET_AFTER:
                log.error("discovery still wedged %d× — restarting bluetooth.service",
                          consec_scan_errors)
                action = await recover_adapter(2)
                log.info("adapter recovery (hard): %s", action)
            elif consec_scan_errors >= RESTART_AFTER_SCAN_WEDGE:
                log.error("discovery wedged %d× despite adapter resets — exiting "
                          "for a clean systemd restart (last resort)",
                          consec_scan_errors)
                return 1
            if consec_scan_errors > 3:
                await asyncio.sleep(min(30.0, 3.0 * consec_scan_errors))
        except Exception as exc:  # noqa: BLE001 — yes, we really do want to catch everything here
            consec_errors += 1
            # Discovery succeeded (not a DiscoveryWedgeError), so the adapter is
            # fine — clear the scan-wedge counter; this is a both-batteries-down
            # read failure instead.
            consec_scan_errors = 0
            log.warning("read #%d failed (%d in a row): %s: %s",
                        n + 1, consec_errors, type(exc).__name__, exc)
            # Self-heal without an operator: after a long run of *total* failures
            # (read_pack only raises here when BOTH batteries are unreadable — a
            # single dropout now yields a partial row), exit so systemd
            # (Restart=always) respawns us with a fresh BlueZ client. A genuine
            # RF blackout just restart-loops harmlessly until a battery returns.
            if consec_errors >= RESTART_AFTER_CONSEC_ERRORS:
                log.error("%d consecutive total-read failures — exiting for a "
                          "clean systemd restart to reset the BLE stack",
                          consec_errors)
                return 1
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
