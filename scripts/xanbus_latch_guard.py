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
import math
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
# `pv_v > DAYLIGHT_V` was the original "is the sun up" test, on the assumption
# that a dark string floats only a few volts. It does not — it floats most of
# Voc. Measured after sunset on 2026-08-06, sun already below the horizon:
# 70.4 V at 0.9 W, 78.3 V at 1.2 W. And the decay is not monotonic; the array
# thrashes (29 -> 78 -> 54 -> 71 V) as the tracker gives up for the night, so
# it dips through the clamp band repeatedly. At 21:01 that produced a real
# unwanted bounce with the sun at -3.3 deg.
#
# Sun elevation is the physical quantity, it needs no sensor, and the
# separation is enormous: the two genuine latches on 2026-08-06 were cleared
# at +46.6 and +33.1 deg, while every dawn/dusk transient sits BELOW the
# horizon (-0.6, -1.1, -3.3, -3.6).
#
# The threshold is set by WINTER, not by those margins. At 51.12 N the sun
# peaks at only 15.4 deg on 21 Dec, so hours above a given gate are:
#
#     gate     21 Dec   21 Nov   21 Sep   06 Aug
#     10 deg    4.4 h    5.4 h    9.8 h   12.6 h
#      5 deg    6.2 h    6.9 h   10.9 h   13.8 h
#
# A 10 deg gate would quietly switch the guard off for most of a winter day —
# in the month when production is scarcest and a latch costs proportionally
# most. 5 deg restores ~40% more winter coverage and still clears the worst
# observed transient by 8.6 deg. The two-confirmation rule remains underneath
# as defence in depth.
# Both live in solar_geometry so the live telemetry decoder can gate on sun
# elevation too, without importing this module and dragging xanbus_node,
# socket and subprocess into the long-running service. Re-exported here
# because callers and tests have referenced them from this module since the
# gate was added on 2026-08-06.
from solar_geometry import (   # noqa: E402
    MIN_SUN_ELEVATION_DEG, SITE_LAT, SITE_LON, sun_elevation_deg,
)
DAYLIGHT_V = 20.0          # kept as a secondary check: is the array connected?
CLAMP_FRACTION = 0.9       # this much of the sample must be clamped
AMBIGUOUS_FRACTION = 0.3   # above this but below CLAMP_FRACTION = report it
HEALTHY_RUNS_TO_CLEAR = 2  # consecutive clean runs before a pending
                           # confirmation is dropped — symmetric with the two
                           # needed to arm one (see the 2026-08-07 note below)
COOLDOWN_S = 45 * 60       # minimum gap between fix attempts
# Act on a SUSTAINED partial clamp, not just fraction >= CLAMP_FRACTION.
#
# 2026-08-12: the fraction climbed 0.35 -> 1.0 over an HOUR while the array
# bled. CLAMP_FRACTION=0.9 is right for rejecting a dawn/dusk transient and
# exactly wrong for a slow-onset clamp, which is a different failure. Three
# consecutive runs above AMBIGUOUS_FRACTION is 15 minutes of the array being
# partly clamped and not recovering — the streak IS the confirmation, so this
# path skips the clamp_seen_at double-confirm rather than adding to it.
#
# Sized honestly: on 08-12 this fires at 10:48 against an actual fix at 11:05,
# so ~17 min and ~127 Wh. It does NOT recover the other ~310 Wh lost earlier
# that morning — the array was genuinely intermittent then and no guard tuning
# reaches it. Two of eleven incidents on record would have benefited.
#
# False-positive risk measured, not assumed: buckets with sun above the gate
# AND the array oscillating AND in band number 0 of 10,352 over 400 h; all
# oscillating in-band buckets sit at -2.6..-0.6 deg against a 5.0 deg gate.
# That 5.6 deg margin is an AUGUST number — at 51.12 N the December sun climbs
# far more slowly, so re-measure before the first winter.
SUSTAINED_PARTIAL_RUNS = 3
CONFIRM_STALE_S = 2.5 * 60 * 60   # a pending confirmation older than this restarts
# Raised 4 -> 6 on 2026-08-08. Observed clamp EPISODES per day run 1-7 (seven
# on 08-03), and three of the last ten days hit four — 08-08 used three with an
# hour of daylight still to go. A cap that binds on a bright afternoon is
# expensive: the measured cost of an unfixed clamp at peak sun is ~400 Wh/hour.
#
# What justifies the raise is that the original rationale has weakened. "A
# latch we can't fix must not loop" assumed fixes might not work; in daylight
# they are **7 for 7**. The one recovered=false (08-06 21:03, 28.1 -> 25.8 V)
# was the spurious NIGHT bounce from the dusk-detection bug, with no sun to
# recover to, and the elevation gate now prevents that class entirely. A fix
# that genuinely fails, or the cap being reached, both page the operator now.
#
# It is NOT raised further, and the reason is honest: this detector has had
# four bugs. The cap's remaining job is to bound a spurious-detection loop —
# it protects against me, not against the hardware. Six keeps that bound
# meaningful at 6 x 15 s = 90 s of standby per day.
MAX_FIXES_PER_DAY = 6      # hard cap; bounds a runaway, incl. a detector bug

# --- EARLY BOUNCE at the 29-minute mark (task #48) ------------------------
#
# The guard above waits for the CLAMP, by which time the array has spent a
# median 43 min walking down producing almost nothing. The early bounce acts
# during the descent instead. Two things had to be settled first, and both now
# are:
#
#   1. Does a still-TRACKING array recover from a bounce? Every one of the 16
#      bounces on record started from a CLAMPED array at 27-30 V. Tested
#      2026-08-14 at 41.8 V: recovered to 93.1 V in one minute, 25 W -> 103 W,
#      no walk-back for 53 min. Yes.
#   2. WHEN to fire. Not at the 45 V crossing: 8 of 32 episodes recover on
#      their own and all of those resolve within 15 min, so firing at the
#      crossing wastes a bounce on a quarter of episodes. At 29 minutes the
#      record is 24 clamps for 24 — every fire is justified.
#
# 29 min is the OBSERVED CLAMP FLOOR, not a tuned value. The natural recovery
# distribution tops out at 15 min and the clamp distribution starts at 29, so
# 15..29 is a 14-minute empty band. Firing at 29 stays out of it: acting
# earlier would act where there is no evidence in either direction. If an
# episode ever lands in that band, revisit.
EARLY_CROSS_V = 45.0             # the cliff
EARLY_REARM_V = 48.0             # must climb back here to reset the clock
EARLY_AFTER_S = 29 * 60          # the observed clamp floor
EARLY_MIN_SUN_DEG = 15.0         # higher than the clamp guard's 5: a 45 V
                                 # crossing at low sun is dusk, not a walk-down
EARLY_MAX_PER_DAY = 6            # SEPARATE budget — an early bounce must never
                                 # starve the clamp fix, which is the one that
                                 # recovers a fully stuck array
EARLY_MIN_INTERVAL_S = 30 * 60   # each bounce restores the array and it walks
                                 # down again; this bounds the resulting cycle
EARLY_REARM_RUNS = 2             # two consecutive runs above EARLY_REARM_V to
                                 # clear, mirroring HEALTHY_RUNS_TO_CLEAR — one
                                 # spike must not reset a 29-minute clock
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


def note_healthy_run(st: dict) -> bool:
    """Record one below-threshold run. Returns True if the state changed and
    should be persisted.

    Pulled out of main() and made pure because this bookkeeping is where the
    guard keeps going wrong, and inline it is untestable without a CAN bus.
    """
    st["healthy_runs"] = st.get("healthy_runs", 0) + 1
    if not st.get("clamp_seen_at"):
        return False                      # nothing pending; nothing to persist
    if st["healthy_runs"] >= HEALTHY_RUNS_TO_CLEAR:
        st.pop("clamp_seen_at", None)     # genuinely recovered — drop it
    return True


def note_clamped_run(st: dict) -> None:
    """Record one at-or-above-threshold run: the healthy streak is broken."""
    st["healthy_runs"] = 0


def needs_second_confirmation(st: dict, now: float,
                              sustained_partial: bool) -> bool:
    """Should the guard wait one more run before acting?

    Normally yes: a clamp seen once could be a sampling artefact, so the first
    sighting only arms a pending confirmation. But a SUSTAINED PARTIAL streak
    is already three consecutive runs of evidence — requiring the double
    confirm on top would make it five runs and give back most of the time the
    rule exists to save. So the streak IS the confirmation.

    Extracted from main() and made pure because it is the branch that decides
    whether the new path is worth anything, and a mutation flipping it went
    undetected when it lived inline.
    """
    if sustained_partial:
        return False
    prev = st.get("clamp_seen_at", 0)
    if now - prev > CONFIRM_STALE_S:
        prev = 0
    return not prev


def note_descent(st: dict, pv_v: float, sun_deg: float, now: float) -> bool:
    """Track a sub-45 V descent across runs; True when it has run EARLY_AFTER_S.

    Pure, and out of main(), for the same reason note_healthy_run and
    note_partial_run are: this bookkeeping is where the guard keeps going
    wrong, and inline it cannot be tested without a CAN bus.

    The array must climb back above EARLY_REARM_V for EARLY_REARM_RUNS
    consecutive runs to clear the clock. A single sample above it is the
    sawtooth the cliff table already had to defend against — a dip that aborts
    and returns does not reset a genuine walk-down.
    """
    if sun_deg < EARLY_MIN_SUN_DEG:
        st.pop("below45_since", None)
        st.pop("early_rearm_runs", None)
        st.pop("early_due_emitted", None)
        return False
    if pv_v >= EARLY_REARM_V:
        st["early_rearm_runs"] = st.get("early_rearm_runs", 0) + 1
        if st["early_rearm_runs"] >= EARLY_REARM_RUNS:
            st.pop("below45_since", None)
            st.pop("early_due_emitted", None)
        return False
    st["early_rearm_runs"] = 0
    if pv_v >= EARLY_CROSS_V:
        return False                      # between 45 and 48: hold, do not arm
    since = st.get("below45_since")
    if since is None:
        st["below45_since"] = now
        st.pop("early_due_emitted", None)
        return False
    return (now - since) >= EARLY_AFTER_S


def early_due_is_new(st: dict) -> bool:
    """True once per episode, not once per run.

    `below45_since` is only cleared by a re-arm or a fix, so `note_descent`
    keeps returning True on every subsequent 5-minute run for as long as the
    descent lasts. In observe-only mode nothing clears it at all, and the
    result was 57 events across 5 episodes over four days — 11x noise in a
    stream whose entire design principle is that quiet periods cost nothing
    (one episode alone produced 18).

    Armed, the cooldown limits actual BOUNCES but not the logging, and a
    blocked-by-cooldown run would re-emit every 5 minutes too.

    So the event fires on the transition, and the flag is cleared wherever the
    clock is.
    """
    if st.get("early_due_emitted"):
        return False
    st["early_due_emitted"] = True
    return True


def early_bounce_allowed(st: dict, now: float) -> tuple[bool, str]:
    """Budget and spacing checks, separate from the clamp path's."""
    if st.get("early_fixes", 0) >= EARLY_MAX_PER_DAY:
        return False, f"early-bounce daily cap {EARLY_MAX_PER_DAY} reached"
    last = st.get("last_early_at", 0)
    if now - last < EARLY_MIN_INTERVAL_S:
        return False, (f"early-bounce interval "
                       f"{(EARLY_MIN_INTERVAL_S - (now - last)) / 60:.0f} min "
                       f"remaining")
    return True, ""


def note_partial_run(st: dict, fraction: float) -> bool:
    """Track consecutive runs sitting in the PARTIAL clamp band.

    Returns True once the streak reaches SUSTAINED_PARTIAL_RUNS, meaning a
    slow-onset clamp that will never reach CLAMP_FRACTION on any single run
    but is not recovering either. Pure, and out of main(), for the same reason
    note_healthy_run is: this bookkeeping is where the guard keeps going wrong
    and inline it cannot be tested without a CAN bus.

    A run below AMBIGUOUS_FRACTION breaks the streak — the array genuinely
    came back, so the clock restarts.
    """
    if fraction < AMBIGUOUS_FRACTION:
        st.pop("partial_runs", None)
        return False
    st["partial_runs"] = st.get("partial_runs", 0) + 1
    return st["partial_runs"] >= SUSTAINED_PARTIAL_RUNS


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
    ap.add_argument("--act-on-early", action="store_true",
                    help="ARM the 29-minute early bounce. Without it that path "
                         "only logs early_bounce_due with would_act=true and "
                         "changes nothing.")
    ap.add_argument("--act-on-sustained", action="store_true",
                    help="ARM the sustained-partial-clamp rule. Without it "
                         "that path only logs latch_guard_sustained_partial "
                         "with would_act=true and changes nothing.")
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and log, but never transmit")
    args = ap.parse_args()

    st = load_state()
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if st.get("day") != today:
        st = {"day": today, "fixes": 0, "last_attempt": 0,
              "early_fixes": 0, "last_early_at": 0}

    # Elevation first, BEFORE the 45 s listen. Nothing below the gate can act,
    # so sampling there is pure cost — and at a 10 min cadence that would be
    # ~50 pointless CAN listens every night. Also drop any pending
    # confirmation: leaving it armed across darkness is what let a dusk sample
    # pair with a later one and bounce the MPPT at night on 2026-08-06.
    elevation = sun_elevation_deg(now)
    if elevation < MIN_SUN_ELEVATION_DEG:
        if st.pop("clamp_seen_at", None):
            save_state(st)
        return 0                                    # night: quiet, no event

    before = sample_array(args.iface, args.sample)

    # --- decide, and record every reason for NOT acting -------------------
    if before["n"] < 5:
        emit("latch_guard_skipped", {"reason": "no MPPT data on the bus",
                                     **before})
        return 0
    # Secondary check: the array must also be electrically awake. Elevation is
    # already handled above, before sampling.
    if not before["daylight"]:
        if st.pop("clamp_seen_at", None):
            save_state(st)
        return 0                                    # night: quiet, no event
    sustained_partial = False
    if before["fraction"] < CLAMP_FRACTION:
        # Clearing a pending confirmation on ONE healthy run is too eager, and
        # it cost real energy on 2026-08-07: the array clamped at 09:40,
        # confirmed once at 09:51, wobbled to a 5.9 V delta for a single
        # sample at 10:00 — still at 31 V making 20 W, nowhere near recovered —
        # and that one run wiped the confirmation. The sequence restarted and
        # the fix landed at 10:21 instead of 10:01. **20 minutes at ~255 W,
        # about 85 Wh, thrown away by a 5-minute wobble.**
        #
        # So require TWO consecutive healthy runs to clear, mirroring the two
        # required to arm. This is the same hysteresis the reader's detector
        # got on 08-06; the guard was left binary. It does make the guard
        # marginally quicker to act, which is bounded by the elevation gate,
        # the 45 min cooldown, the 4/day cap, and the fact that a bounce is
        # cheap and demonstrably harmless. The 2.5 h staleness check below is
        # still the backstop against a confirmation lingering forever.
        if note_healthy_run(st):
            save_state(st)
        # Bailing SILENTLY here is how a five-hour latch stayed invisible on
        # 2026-08-06: the ceiling was tighter than the MPPT's dither, so a
        # continuous clamp sampled at ~0.5 and fell out with no trace. A
        # partial clamp is the interesting case — report it. Fully healthy
        # (fraction near zero) stays quiet, so this costs no routine egress.
        sustained_partial = note_partial_run(st, before["fraction"])

        # EARLY BOUNCE. The array is TRACKING here (fraction below the clamp
        # threshold), which is exactly the state the 2026-08-14 test validated
        # and the state no bounce had ever been issued from before it.
        due = note_descent(st, before["pv_v"], elevation, now)
        save_state(st)
        if due and early_due_is_new(st):
            ok, why = early_bounce_allowed(st, now)
            mins = (now - st.get("below45_since", now)) / 60
            emit("early_bounce_due",
                 {"reason": f"tracking below {EARLY_CROSS_V} V for "
                            f"{mins:.0f} min (>= {EARLY_AFTER_S / 60:.0f}); "
                            f"24 of 24 episodes past this mark clamped",
                  "below45_min": round(mins),
                  "armed": args.act_on_early,
                  "would_act": not args.act_on_early,
                  "blocked": None if ok else why,
                  "sun_deg": round(elevation, 1), **before})
            if ok and args.act_on_early:
                st["last_early_at"] = now
                st["early_fixes"] = st.get("early_fixes", 0) + 1
                # Clear the clock: the bounce restores the array, so the next
                # descent is a NEW episode, not a continuation of this one.
                st.pop("below45_since", None)
                st.pop("early_due_emitted", None)
                save_state(st)
                try:
                    acked = run_fix(args.iface, args.dest, args.wait)
                except Exception as exc:            # noqa: BLE001
                    emit("early_bounce_error",
                         {"error": f"{type(exc).__name__}: {exc}"})
                    return 1
                after = sample_array(args.iface, args.sample)
                emit("early_bounce_result",
                     {"acked": acked, "before": before, "after": after})
                return 0
            return 0
        if before["fraction"] >= AMBIGUOUS_FRACTION:
            emit("latch_guard_ambiguous",
                 {"reason": "some samples clamped but below the acting "
                            "threshold — partial clamp or a moving tracker",
                  "threshold": CLAMP_FRACTION,
                  "partial_runs": st.get("partial_runs", 0),
                  "sustained_at": SUSTAINED_PARTIAL_RUNS, **before})
        if not sustained_partial:
            return 0                                # healthy: quiet, no event
        # Sustained: fall through to the SAME cooldown / daily-cap / dry-run
        # gates the full-clamp path uses. Nothing bypasses those.
    else:
        # A full clamp supersedes any partial streak.
        st.pop("partial_runs", None)
    # A clamp seen ONCE is still not acted on. The dawn/dusk transient this
    # originally guarded is now excluded by the elevation gate above, which is
    # both stricter and free; this remains as a second opinion against a
    # one-off sampling artefact. Runs are 5 min apart, so a real latch — which
    # persists for hours — costs at most one extra cycle, while a spurious fix
    # would burn a daily-cap slot and start a 45 min cooldown.
    note_clamped_run(st)
    if sustained_partial:
        # OBSERVE-ONLY UNLESS EXPLICITLY ARMED. Deploying the code must not
        # change what the guard does. The existing --dry-run flag disables the
        # WHOLE guard, which would switch off the working latch fix, so it is
        # useless for staging this. Instead the new path logs what it would
        # have done and returns, until --act-on-sustained is passed.
        #
        # Compare these timestamps against the following latch_fix_result over
        # a few days: if would_act consistently precedes the real fix by
        # 10-20 min and never fires on a morning that resolved on its own,
        # arm it.
        emit("latch_guard_sustained_partial",
             {"reason": f"fraction >= {AMBIGUOUS_FRACTION} for "
                        f"{SUSTAINED_PARTIAL_RUNS} consecutive runs — a "
                        f"slow-onset clamp, would act without waiting for "
                        f"fraction >= {CLAMP_FRACTION}",
              "armed": args.act_on_sustained,
              "would_act": not args.act_on_sustained,
              **before})
        if not args.act_on_sustained:
            return 0
    prev_seen = st.get("clamp_seen_at", 0)
    if now - prev_seen > CONFIRM_STALE_S:    # stale confirmation, restart
        prev_seen = 0
    if needs_second_confirmation(st, now, sustained_partial):
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
    # Clear the partial streak, or a sustained-partial fix would re-arm itself
    # on the very next run and burn the daily cap in three cycles.
    st.pop("partial_runs", None)
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
