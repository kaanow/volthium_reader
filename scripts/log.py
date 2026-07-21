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
from volthium.pack import (
    DiscoveryWedgeError,
    _event,  # for recovery_skipped events
    ambient_burst_check,
    ambient_mode,
    ambient_says_peers_silent,
    ambient_scanner_loop,
    emit_stack_health,
    invalidate_adapter_cache,
    maybe_repair_primary,
    read_pack,
    recover_adapter,
    seal_event_log,
    snapshot_stack,
)


# Per-pack cell count for the SC12200G4DPH (12V LiFePO4 = 4 cells in series).
CELLS_PER_BATTERY = 4

# After this many consecutive TOTAL-read failures, exit so systemd respawns us
# with a fresh BlueZ client (self-heals adapter wedges without an operator).
# With ~10s interval + backoff this is on the order of ~15+ min of hard outage.
# HARDWARE-DEP: Pi 3B / BlueZ — this whole self-restart mechanism exists
# because the in-process BleakClient leaks connections and only a fresh
# process can drop them. On a stack that doesn't leak, restart-on-wedge
# becomes unnecessary and this constant + its call site can go.
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

# Stuck-adapter-discovery (FM-3/FM-9) escalation ladder. A wedged discovery
# session (org.bluez.Error.InProgress) lives in bluetoothd, NOT our process, so a
# process restart can't clear it — the adapter itself must be reset. Escalate by
# count of consecutive discovery failures: soft HCI reset → full
# bluetooth.service restart → software USB replug of the dongle (full
# re-enumeration + firmware reload — the only remote cure for the FM-9
# kernel-sees-it-but-bluetoothd-doesn't state) → finally give up to a process
# restart (last resort, in case the loop itself is the problem). Each level only
# fires once (==) so we climb the ladder. Note the fallback adapter
# (VOLTHIUM_FALLBACK_ADAPTER) usually keeps reads flowing before the ladder even
# climbs — these rungs matter when BOTH adapters are unusable.
# HARDWARE-DEP: Pi 3B — every rung here is a workaround for the BT stack
# getting stuck. Modern controllers with clean state management shouldn't need
# this; this whole ladder + the recover_adapter() function it calls can be
# removed on hardware upgrade.
ADAPTER_SOFT_RESET_AFTER = 3    # consecutive scan failures → hciconfig reset
ADAPTER_HARD_RESET_AFTER = 6    # still failing → restart bluetooth.service
ADAPTER_USB_REPLUG_AFTER = 9    # still failing → software-replug the USB dongle
RESTART_AFTER_SCAN_WEDGE = 15   # adapter resets didn't help → exit for respawn

# Trigger one wedge_snapshot on the "neither battery found in scan" streak so
# a Level-1 read-failure loop is diagnosable without having to force a
# snapshot by hand. Distinct threshold from the recovery ladder because this
# is the *other* wedge kind (scan succeeded but returned zero peers — often
# an RF / power / peer-side issue, not a BlueZ state issue).
CONSEC_ERR_SNAPSHOT_AT = 5

# Baseline stack_health probe cadence. Every ~5 min at interval=5s (=60
# cycles) we emit power/thermal + adapter/BlueZ state even without a wedge,
# so any incident has a clean "before" to diff against and Pi under-voltage
# becomes visible from Railway the moment it starts.
HEALTH_SNAPSHOT_EVERY_CYCLES = 60

# Charger / manual-balance detection. In the series pack both batteries carry
# the same current, so |i_a - i_b| ≈ 0; a charger clamped across one battery
# drives them apart (the operator's "tell").
#
# Threshold + debounce are empirical (2026-07-20, ~8400 charger-off samples).
# The SUSTAINED off-state mismatch stays under ~1.8 A even at 10 A+ loads
# (it's just per-BMS sensor tolerance) — but high-load current STEPS produce
# brief read-timing-skew spikes up to ~65 A (A and B sampled seconds apart
# across a load switch, pack peaks ~68 A). The debounce, not the threshold,
# is what rejects those: a charger sustains its offset for hours, a transient
# lasts a reading or two. So the threshold need only clear the sustained
# floor (2.5 A > 1.8 A p99, well under a real charger's ~6.6 A), and the
# debounce demands the offset persist ~30-50 s.
CHARGER_DIVERGENCE_A = 2.5
CHARGER_DEBOUNCE_CYCLES = 5


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
    ap.add_argument("--interval", type=float, default=5.0)
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

    # Passive "second opinion" scanner on the ambient adapter (env-gated;
    # unset = no-op). See docs/investigations/2026-07-16-bt-wedge-causation.md
    # — this is the single most decisive signal for splitting "chip failing"
    # from "we're leaking connections" from "BMS itself went silent".
    ambient_task = asyncio.create_task(
        ambient_scanner_loop({args.a, args.b})
    )
    try:
        return await _loop(args, log)
    finally:
        ambient_task.cancel()
        try:
            await ambient_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 — must not mask the real exit reason
            log.warning("ambient scanner cleanup raised: %s", exc)
        # Whatever way we exit — wedge restart, total-read-failure restart,
        # crash — seal the live event segment so the events uploader ships the
        # evidence NOW. Without this, a crash-looping logger resets the
        # age-rotation clock every respawn and diagnostics never leave the Pi
        # (the 2026-07-12/13 outage ran 14 h with zero events reaching Railway).
        seal_event_log()


async def _loop(args, log: logging.Logger) -> int:
    est = Estimator()
    consec_errors = 0
    consec_scan_errors = 0              # consecutive discovery-wedge failures (FM-3)
    n = 0
    prev_present: tuple[bool, bool] | None = None
    wedge_streak: dict[str, int] = {}   # address → consecutive wedged cycles
    charger_on = False                  # external charger on one battery?
    chg_hi = chg_lo = 0                 # debounce counters for charger detection
    # address → (alarms tuple, heater, balancing-active bool). Edge-triggered
    # so BMS flags are logged only on change, never per cycle (data bloat).
    prev_flags: dict[str, tuple] = {}

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

            # Charger / manual-balance detection. In the series pack the SAME
            # current flows through both batteries, so i_a ≈ i_b. A charger
            # clamped across ONE battery breaks that symmetry (one reads several
            # amps, the other ~0) — the operator's "tell" for an external
            # charger doing a manual top-balance. Debounced so sensor noise
            # can't flip it; logs a charger_state event on each on/off edge.
            ia, ib = pack.a.current, pack.b.current
            if ia is not None and ib is not None:
                if abs(ia - ib) >= CHARGER_DIVERGENCE_A:
                    chg_hi += 1
                    chg_lo = 0
                else:
                    chg_lo += 1
                    chg_hi = 0
                if not charger_on and chg_hi >= CHARGER_DEBOUNCE_CYCLES:
                    charger_on = True
                    target = "B" if ib > ia else "A"
                    log.warning("charger detected — balancing %s (i_a=%+.1f "
                                "i_b=%+.1f)", target, ia, ib)
                    _event("charger_state", state="on", charging=target,
                           i_a=round(ia, 2), i_b=round(ib, 2),
                           divergence_a=round(abs(ia - ib), 2))
                elif charger_on and chg_lo >= CHARGER_DEBOUNCE_CYCLES:
                    charger_on = False
                    log.warning("charger removed — currents symmetric again "
                                "(i_a=%+.1f i_b=%+.1f)", ia, ib)
                    _event("charger_state", state="off",
                           i_a=round(ia, 2), i_b=round(ib, 2))

            # BMS flags — logged EDGE-TRIGGERED only (never per cycle). We track
            # the active alarm set, the heater, and whether the internal cell
            # balancer is engaged (non-zero status word). Balancer is collapsed
            # to active/inactive so per-cell toggling near full charge doesn't
            # spam the log; the alarm SET and heater log on any change.
            for br in (pack.a, pack.b):
                if not _present(br):
                    continue
                key = br.address.upper()
                bal_on = bool(br.balancer)
                cur = (tuple(br.alarms), br.heater, bal_on)
                prev = prev_flags.get(key)
                # Emit a baseline on first sighting (per battery, per logger
                # start — 2 events, negligible) so the current flag state is
                # always known, then only on change thereafter.
                if prev is None or cur != prev:
                    if br.alarms and (prev is None or set(br.alarms) - set(prev[0])):
                        log.warning("BMS alarm on %s: %s", key, br.alarms)
                    _event(
                        "bms_flags",
                        address=key,
                        alarms=br.alarms or None,
                        heater=br.heater,
                        balancing=bal_on,
                        balancer_raw=br.balancer,
                        baseline=prev is None or None,
                    )
                prev_flags[key] = cur

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
            # Periodic health snapshot — see HEALTH_SNAPSHOT_EVERY_CYCLES.
            # Emit AFTER the first cycle so we always have a baseline
            # `stack_health` event right after startup.
            if n == 1 or n % HEALTH_SNAPSHOT_EVERY_CYCLES == 0:
                await emit_stack_health(
                    reason=f"periodic n={n}",
                    peers={args.a.upper(), args.b.upper()},
                )

            # Degraded-mode self-repair: when reads are surviving on the
            # fallback adapter, periodically try to fix the primary (USB
            # replug). Rate-limited inside — a cheap no-op almost always.
            repair = await maybe_repair_primary()
            if repair:
                log.warning("primary adapter repair attempted while on "
                            "fallback: %s", repair)

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
            # Re-resolve the adapter from scratch on every retry: hci indexes
            # move when the dongle re-enumerates (kernel reset or our own
            # replug), and trusting the 60 s cache here costs minutes of
            # scanning a dead index (seen live 2026-07-14 21:20).
            invalidate_adapter_cache()
            # --- Ambient-gated recovery (Phase 2A, docs/investigations/…) ----
            # Before firing anything past the (cheap) L1 rung, consult the
            # ambient scanner on hci1. If the second radio ALSO can't hear
            # the batteries, the wedge is peer-side or environmental — L2/3/4
            # (bluetoothd restart / USB replug / process exit) can't fix that,
            # and each level churns adapter state. Skip and just wait.
            peers = {args.a.upper(), args.b.upper()}

            async def _peers_silent_gate() -> bool:
                # burst mode: the second radio is normally off — bring it
                # up for one ~12 s scan to answer the question, then it
                # goes back down. continuous mode: read the always-on
                # scanner's rolling state (free).
                if ambient_mode() == "burst":
                    verdict = await ambient_burst_check(
                        peers,
                        trigger=(f"recovery_gate scan_errors="
                                 f"{consec_scan_errors}: {str(exc)[:120]}"),
                    )
                else:
                    verdict = ambient_says_peers_silent(peers)
                if verdict is True:
                    log.warning(
                        "recovery escalation skipped — ambient (%s) "
                        "confirms both peers silent (scan-errors=%d); "
                        "waiting for peers to return rather than churning "
                        "adapter state", ambient_mode(), consec_scan_errors,
                    )
                    _event(
                        "recovery_skipped",
                        reason="ambient_confirms_peers_silent",
                        ambient_mode=ambient_mode(),
                        scan_errors=consec_scan_errors,
                        trigger=str(exc)[:200],
                    )
                    return True
                return False

            if consec_scan_errors == ADAPTER_SOFT_RESET_AFTER:
                log.error("discovery wedged %d× — resetting the HCI controller",
                          consec_scan_errors)
                # In burst mode, take a second opinion BEFORE the snapshot so
                # every wedge gets a peers-or-us verdict — most wedges clear
                # at L1, so waiting for L2+ would leave the common case
                # undiagnosed. L1 itself stays unconditional (cheap, and it
                # clears real reader-side wedges); the burst only informs.
                if ambient_mode() == "burst":
                    await ambient_burst_check(
                        peers, trigger=f"L1 wedge: {str(exc)[:120]}",
                    )
                # Snapshot BEFORE the recovery runs so the event captures the
                # wedge state itself. We label the level of recovery about to
                # be taken so downstream analysis can correlate.
                await snapshot_stack(reason=str(exc), level=1, peers=peers)
                # L1 is cheap and often clears real reader-side wedges — run
                # unconditionally even if ambient says peers silent (rules
                # nothing out, adds no risk).
                action = await recover_adapter(1)
                log.info("adapter recovery (soft): %s", action)
            elif consec_scan_errors == ADAPTER_HARD_RESET_AFTER:
                log.error("discovery still wedged %d× — restarting bluetooth.service",
                          consec_scan_errors)
                # Gate BEFORE the snapshot: in burst mode the gate runs a
                # fresh ambient scan, so the snapshot then carries real
                # ambient_peer_ages_s instead of nulls.
                silent = await _peers_silent_gate()
                await snapshot_stack(reason=str(exc), level=2, peers=peers)
                if not silent:
                    action = await recover_adapter(2)
                    log.info("adapter recovery (hard): %s", action)
            elif consec_scan_errors == ADAPTER_USB_REPLUG_AFTER:
                log.error("discovery still wedged %d× — software-replugging "
                          "the USB adapter (full re-enumeration)",
                          consec_scan_errors)
                silent = await _peers_silent_gate()
                await snapshot_stack(reason=str(exc), level=3, peers=peers)
                if not silent:
                    action = await recover_adapter(3)
                    log.info("adapter recovery (usb replug): %s", action)
            elif consec_scan_errors >= RESTART_AFTER_SCAN_WEDGE:
                log.error("discovery wedged %d× despite adapter resets — exiting "
                          "for a clean systemd restart (last resort)",
                          consec_scan_errors)
                # Last-resort snapshot: the wedge survived every ladder rung —
                # the surviving evidence is what makes this incident learnable.
                silent = await _peers_silent_gate()
                await snapshot_stack(reason=str(exc), level=4, peers=peers)
                if silent:
                    # Peers still silent — respawning the process won't help
                    # any more than the previous rungs. Skip the exit, keep
                    # looping (with backoff below) so we don't hammer systemd
                    # with pointless restart cycles.
                    pass
                else:
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
            # Fire ONE snapshot on the streak so the diagnosis (RF /
            # power / peer / BlueZ) lands on Railway BEFORE the process
            # eventually exits. Without this, the "neither battery found"
            # class of outage stays silent (it went undiagnosed until we
            # forced a snapshot by hand — 2026-07-10).
            if consec_errors == CONSEC_ERR_SNAPSHOT_AT:
                # Burst mode: sample the air before snapshotting — "neither
                # battery readable" is exactly the case where peers-or-us
                # is the whole diagnosis.
                if ambient_mode() == "burst":
                    await ambient_burst_check(
                        {args.a.upper(), args.b.upper()},
                        trigger=f"consec_read_failures={consec_errors}",
                    )
                await snapshot_stack(
                    reason=f"{type(exc).__name__}: {exc}", level=1,
                    peers={args.a.upper(), args.b.upper()},
                )
            # Self-heal without an operator: after a long run of *total* failures
            # (read_pack only raises here when BOTH batteries are unreadable — a
            # single dropout now yields a partial row), exit so systemd
            # (Restart=always) respawns us with a fresh BlueZ client. A genuine
            # RF blackout just restart-loops harmlessly until a battery returns.
            if consec_errors >= RESTART_AFTER_CONSEC_ERRORS:
                log.error("%d consecutive total-read failures — exiting for a "
                          "clean systemd restart to reset the BLE stack",
                          consec_errors)
                # Ambient gate: process restart won't help if peers are silent.
                # Reset the counter to avoid the check firing every subsequent
                # cycle and just keep looping — reads will resume the moment
                # peers come back. Gate runs BEFORE the snapshot so a burst's
                # fresh peer ages land in the snapshot fields.
                peers = {args.a.upper(), args.b.upper()}
                if ambient_mode() == "burst":
                    verdict = await ambient_burst_check(
                        peers,
                        trigger=f"total_read_failures={consec_errors}",
                    )
                else:
                    verdict = ambient_says_peers_silent(peers)
                # Last-resort snapshot before exit — same rationale as
                # the discovery-wedge Level-4 case.
                await snapshot_stack(
                    reason=f"{type(exc).__name__}: {exc}", level=4,
                    peers=peers,
                )
                if verdict is True:
                    log.warning("process restart skipped — ambient (%s) "
                                "confirms peers silent; continuing to loop",
                                ambient_mode())
                    _event(
                        "recovery_skipped",
                        reason="ambient_confirms_peers_silent",
                        ambient_mode=ambient_mode(),
                        consec_errors=consec_errors,
                        would_have="process_exit",
                    )
                    consec_errors = 0
                else:
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
