#!/usr/bin/env python3
"""Xanbus live telemetry — decodes the Conext CAN bus into 15 s solar rows
and on-change events, spools to disk, uploads to Railway. One process.

The production sibling of the offline tools (`xanbus_reader.py` decodes
pulled corpora; this decodes the live socket). Field layouts and their
validation story: docs/xanbus-decode.md. Cloud side: /api/solar/ingest and
/api/xanbus_events/ingest (cloud/server/main.py), tables in migration 0003.

Design (per plan 2026-07-30):
  - Continuous AF_CAN read (same zero-dependency socket as can_capture.py;
    coexists with it — kernel fans frames out to every open socket).
  - Aggregates each wall-clock-aligned 15 s bucket to mean(/min/max on the
    two power channels) so transients survive the cadence reduction.
  - Sparse event stream for things that CHANGE (charge stage, inverter
    mode, generator start/stop, charger-target moves, node dropouts) —
    never sampled, so quiet days cost ~nothing.
  - Sealed-segment spool (events_uploader.py pattern): writer renames the
    live spool to *.NNNN.sealed every UPLOAD_PERIOD_S; an uploader thread
    drains sealed files and deletes on success. Railway down = data waits
    on disk. Crash = at most the unsealed tail is re-read on restart
    (idempotent ingest dedupes).
  - Memory: reassembly buffers are pruned by age, buckets are fixed-size,
    the spool lives on disk. Steady-state RSS ~20 MB; the unit caps at 60.

Sign conventions (schema_version=1):
  - solar_w / solar_a: MPPT->battery output, always >= 0 (the MPPT's raw
    current reads negative; we take abs — see berrybms's same finding).
  - dc_*: RAW decoded values from the inverter's BattSts2. The +=charging
    sign audit is still open (berrybms has the same TODO); v1 logs raw and
    the first week of data settles it server-side. schema_version bumps if
    interpretation changes.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from solar_geometry import (   # noqa: E402
    MIN_SUN_ELEVATION_DEG, sun_elevation_deg,
)

log = logging.getLogger("xanbus-telemetry")

BUCKET_S = 15
UPLOAD_PERIOD_S = 300          # seal + upload cadence (5 min batches)
DROPOUT_S = 60                 # node silent this long -> node_dropout event

# MPPT diode-clamp latch detection (root-caused 2026-08-05). When array
# current demand exceeds what the (smoke-dimmed) panels can supply, the
# operating point slides down the IV curve until the array sits at battery
# voltage + a diode drop. A buck converter cannot restart without input
# headroom, so it stays latched: real power keeps flowing through the body
# diode, UNREGULATED and unmetered, until demand ceases (battery full, or
# sunset). Verified fix: Operating Mode -> Standby -> Operating, which opens
# the PV input and lets the array fly to Voc so the tracker can re-acquire.
# A diode clamp pins the array JUST ABOVE the output — one diode drop. So the
# test is a BAND, not an upper bound. The original `delta < 2.5` also matched
# NEGATIVE deltas, which is the opposite condition: at dusk the array decays
# BELOW battery voltage (dark, non-conducting) and that read as a latch. It
# fired a false positive at 21:24 on 2026-08-05 with delta -15.7 V and 0 W.
# Deliberately WIDE. The bank lives at 26-28 V and nothing in 11 days of
# production data left that range except one glitch, so a tight 18-32 V window
# is tempting — but the 2026-07 capture corpus contains a validated frame that
# decodes to 54.16 V, and I do not know what that represents. Rejecting data I
# have not proven wrong is how a sanity check starts eating real measurements.
# So bound only what is unarguable: this is a low-voltage DC bus, not a
# 143 kV transmission line. Catches the observed failure and nothing else.
BUS_V_MIN, BUS_V_MAX = 5.0, 120.0

# With |current| below 0.5 A the w ~ v*i ratio is meaningless, but the
# MAGNITUDE is not: at the bus's 5-120 V range, 0.5 A cannot exceed 60 W. A
# generous 200 W ceiling therefore catches garbage without policing anything
# real. This replaces an exemption that skipped the check entirely and so was
# live only on corrupt frames.
NEAR_ZERO_MAX_W = 200.0
LATCH_DELTA_MIN_V = 0.3        # below this the array isn't driving the diode
# The ceiling must clear the MPPT's own reporting dither, or a real latch
# reads as intermittent. Measured during the unbroken 2026-08-06 10:20 local
# clamp: pv_v hops over a ~1.1 V range (27.5-29.9) against a rock-steady
# out_v, so the delta swings 0.90-3.44 V second to second. At 2.5 V, 47% of
# 15 s buckets contained at least one out-of-band sample — enough to clear
# the latched flag 25 s after raising it. 4.0 V covers the observed dither
# with margin and is still nowhere near a healthy operating point: the
# smallest delta seen while genuinely tracking that day was 8.2 V, and
# 13 V+ during real production.
LATCH_DELTA_MAX_V = 4.0        # above this the tracker has real headroom
# pv_v > 20 V was the ONLY daylight test here until 2026-08-09, and it is not
# sufficient. At dusk the MPPT hunts: it repeatedly tries to start, drags the
# array down to battery voltage, fails for want of power, and lets it fly back
# to open circuit. A single 60 s bucket at 20:19 local that evening held
# pv_v min 26.81 and max 89.74 — every sample above 20 V, and the ones near
# the bottom sitting a diode drop above a 26.51 V bus. Indistinguishable from
# a clamp, sample by sample.
#
# The same blind spot already caused a real incident on the OTHER detector:
# the guard bounced the MPPT at 21:01 local, sun elevation -3.6 deg, and was
# fixed by gating on elevation (commit 26010b1, 2026-08-06). That fix was
# never applied here, because this detector only records and does not act.
#
# Recording still matters. These events are the raw material for the cliff
# table and every latch statistic in docs/xanbus-unknowns.md, so one false
# dusk latch corrupts a published finding. The only thing standing between
# that and the record was LATCH_CONFIRM_S: on 2026-08-09 the array sat near
# 28 V with an in-band delta for 13 minutes against a 10 minute confirmation.
# That is not margin, that is luck.
LATCH_DAYLIGHT_V = 20.0        # array must at least exceed a dark panel string
LATCH_CONFIRM_S = 600          # sustained this long before we call it
LATCH_RELEASE_S = 120          # ...and sustained THIS long before we clear it
LATCH_TRAIL_S = 1200           # seconds of 1 Hz history kept for forensics
# The AC-load decode WORKS as of 2026-10-04 (block 3, verified against 7378
# payloads), so this is a plain sampling period, not an edge-trigger on a
# broken decode. 5 min matches the solar upload batch.
AC_LOAD_PERIOD_S = 300
AC_LOAD_HEARTBEAT_S = 6 * 3600  # AC-load decode is broken and edge-triggered;
                                # this only proves it is still being decoded
ASM_MAX_AGE_S = 5.0            # abandon half-reassembled fast-packets
SPOOL_DIR = Path("data/solar")
KEEP_SEALED = 2000             # absolute disk bound if Railway dies for weeks

CAN_FRAME = "=IB3x8s"
CAN_EFF_FLAG = 0x80000000

# PGNs (17-bit, DP bit included) — see docs/xanbus-decode.md.
PGN_BATT_STS2 = 0x1F0C4        # 127172 — inverter's DC-bus view (src 0)
PGN_DC_SRC_STS2 = 0x1F0C5      # 127173 — assoc 0x03 MPPT out / 0x15 PV array
PGN_CHG_STS = 0x1F00E          # 126990 — charge stage + charger targets
PGN_INV_STS2 = 0x1F0BD         # 127165 — single-frame, inverter mode
PGN_AC_STS_RMS = 0x1F016       # 126998 — assoc 0x13 gen-in / 0x33 loads
PGN_MPPT_DATA = 0x1F0BE        # 127166 — MPPT energy counters (src 1)

# PGN 127166 field offsets, decoded 2026-08-06 and completed 2026-08-09
# (docs/xanbus-unknowns.md #6). 60-byte fast packet from the MPPT.
#
# The daily pair resets at LOCAL midnight; the lifetime pair never does. Both
# satisfy wh/ah == pack voltage, which is how they were identified and is
# re-checked at decode time as a guard.
#
# Why carry them at all: every daily-energy figure this system reports is an
# integral of 15 s samples, so it silently loses whatever the pipeline drops —
# a restart, a spool backlog, an outage. This counter accumulates inside the
# MPPT and is merely read, so it has none of those failure modes. On
# 2026-08-09 the two agreed to 0.44%, which is how we know the pipeline is
# currently lossless; the point is to keep knowing that.
#
# NOT more accurate, though, and the distinction matters. It inherits the
# MPPT's front-end current-sensor error and tracks the integral of solar_w to
# 1-3%, so both share the same ~22-25% under-report against the BMS.
# Gap-immune, not truth.
MPPT_LIFE_AH_OFF, MPPT_LIFE_WH_OFF = 19, 23
MPPT_DAY_AH_OFF, MPPT_DAY_WH_OFF = 46, 50
MPPT_ENERGY_PERIOD_S = 900     # snapshot cadence while the counter is moving
MPPT_WH_PER_AH_MIN, MPPT_WH_PER_AH_MAX = 20.0, 35.0   # decode sanity: bus volts

FAST_PACKET_PGNS = {PGN_BATT_STS2, PGN_DC_SRC_STS2, PGN_CHG_STS, PGN_AC_STS_RMS,
                    PGN_MPPT_DATA}

SRC_SW, SRC_MPPT = 0, 1        # node addresses on our bus

# 786 (0x312) is named for what it was OBSERVED to do, not for what it means —
# its semantics are undecoded. It has appeared exactly 4 times, always as a
# one-second transient on the absorption -> float handoff (08-08 17:32:38-39
# and 08-09 13:41:33-34), and only on the two days since the charge ceiling
# was lowered to 28.0 V that got as far as float. Note 0x312 == 0x302
# (absorption) with bit 4 set, which is suggestive of an "absorption complete"
# sub-state, but that is a guess and the name deliberately does not assert it.
# Mapping it at all is only so the event stream shows something legible
# instead of a bare integer; unmapped codes still fall through to the int.
CHG_STAGE_NAMES = {768: "not_charging", 769: "bulk", 770: "absorption",
                   773: "float", 777: "qualifying_ac",
                   786: "absorption_to_float_transient"}
INV_STATUS_NAMES = {1024: "invert", 1025: "ac_passthrough"}

_stop = False


def _sig(*_a):
    global _stop
    _stop = True


def parse_can_id(can_id: int) -> tuple[int, int, int]:
    """29-bit id -> (pgn, dest, src). PDU1 (PF<240) is unicast: PS is the
    destination and excluded from the PGN. PDU2 is broadcast."""
    dp = (can_id >> 24) & 1
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    sa = can_id & 0xFF
    if pf < 240:
        return (dp << 16) | (pf << 8), ps, sa
    return (dp << 16) | (pf << 8) | ps, 255, sa


class Reassembler:
    """NMEA2000 fast-packet reassembly, standard 3-bit-seq/5-bit-frame split."""

    def __init__(self):
        # (pgn,src,seq) -> [total, bytes, t, next_expected_fid]
        self._buf: dict[tuple, list] = {}
        # Out-of-order / duplicated fast-packet frames DISCARDED, so the rate
        # is observable instead of being inferred from corrupt output. The
        # measured rate on this bus is 21 in 194,392 frames (0.011%).
        self.bad_asm_seq = 0
        # Total frames offered, so bad_asm_seq can be expressed as a RATE.
        # A bare count is unjudgeable: 19 discards is alarming or routine
        # depending entirely on whether the denominator is 200 or 200,000.
        self.fed_total = 0

    def feed(self, pgn: int, src: int, data: bytes, t: float):
        """Returns the reassembled payload or None."""
        self.fed_total += 1
        seq, fid = data[0] >> 5, data[0] & 0x1F
        key = (pgn, src, seq)
        if fid == 0:
            # [declared_len, payload, last_seen, next_expected_fid]
            self._buf[key] = [data[1], bytearray(data[2:]), t, 1]
            return None
        ent = self._buf.get(key)
        if ent is None:
            return None
        # FRAME INDEX CONTINUITY. Only the byte COUNT was checked, and `fid`
        # was tested solely for == 0, so a stale partial buffer could be
        # completed by frames from a LATER message carrying the same 3-bit
        # sequence number.
        #
        # ASM_MAX_AGE_S = 5.0 s is LONGER than that sequence number's wrap
        # time for five of the six fast-packet PGNs — AC_STS_RMS and
        # DC_SRC_STS2 wrap in 2.0 s, BATT_STS2 and CHG_STS in 4.0 s — so the
        # collision window is wide open, and measured frame-index
        # discontinuity on this bus is 21 in 194,392 frames (0.011%).
        #
        # BattSts2 puts dc_v at offsets 2-5 (frame 0, so the voltage range
        # check never fires) and dc_a/dc_w at 6-13 (later frames, shiftable),
        # which is exactly the signature of the corrupt rows on record:
        # plausible voltage, garbage current, garbage power.
        #
        # A mis-ordered or duplicated frame now DISCARDS the buffer rather
        # than silently splicing foreign bytes into it.
        if fid != ent[3]:
            del self._buf[key]
            self.bad_asm_seq += 1
            return None
        ent[3] += 1
        ent[1] += data[1:]
        ent[2] = t
        if len(ent[1]) >= ent[0]:
            payload = bytes(ent[1][:ent[0]])
            del self._buf[key]
            return payload
        return None

    def prune(self, now: float):
        stale = [k for k, v in self._buf.items() if now - v[2] > ASM_MAX_AGE_S]
        for k in stale:
            del self._buf[k]


class Agg:
    """mean/min/max accumulator."""
    __slots__ = ("n", "sum", "min", "max")

    def __init__(self):
        self.n, self.sum, self.min, self.max = 0, 0.0, None, None

    def add(self, v: float):
        self.n += 1
        self.sum += v
        self.min = v if self.min is None else min(self.min, v)
        self.max = v if self.max is None else max(self.max, v)

    @property
    def mean(self):
        return self.sum / self.n if self.n else None


class Decoder:
    """Pure decode + aggregate logic. feed() takes one raw frame and returns
    a list of event dicts; flush_bucket() returns a solar row when a bucket
    boundary has passed. No I/O — testable off-Pi with synthetic frames."""

    def __init__(self):
        self.asm = Reassembler()
        self.bucket_start: float | None = None
        self.aggs: dict[str, Agg] = {}
        # change-tracked state: key -> last value (emit event on change)
        self.state: dict[str, object] = {}
        self.last_seen: dict[int, float] = {}
        self.dropped: set[int] = set()
        self.last_ac_load_sample = 0.0
        self.last_ac_load = 0.0
        self.last_mppt_energy = 0.0       # last mppt_energy emission
        self.last_day_wh: int | None = None   # for midnight-reset detection
        self.last_day_ah: int | None = None
        self.bad_mppt_energy = 0          # decodes failing the volts sanity test
        # latch detection state (see LATCH_* constants)
        self.pv_v: float | None = None
        self.mppt_out_v: float | None = None
        self.mppt_out_w: float | None = None
        self.mppt_status: int | None = None
        self.bad_dc_v = 0          # rejected out-of-range bus voltages
        self.bad_dc_w = 0          # rejected internally-inconsistent DC power
        self.bad_solar_w = 0       # rejected internally-inconsistent MPPT power
        # WHEN we last reported the rejection counters. They were write-only:
        # incremented here, read ONLY by unit tests, never logged, emitted or
        # uploaded. So a decoder rejecting EVERYTHING is indistinguishable
        # from a quiet bus — "I looked and it was fine" and "I could not
        # decode a single frame" produce the same silence.
        #
        # The concrete scenario: an MPPT firmware update moves the energy
        # counter layout, every decode fails the ratio test, mppt_energy and
        # mppt_daily_total simply stop arriving, and the standing pipeline
        # audit (mppt_counter_wh) goes blind with nothing to say so.
        self.last_reject_report = 0.0
        self.reject_reported: dict = {}
        self.clamp_since: float | None = None
        self.clamp_clear_since: float | None = None
        self.latched = False
        # Rolling 1 Hz history so a latch event can carry the run-up with it.
        # We do NOT yet understand what triggers the slide — whether it is a
        # load step, a cloud edge, an SOC threshold or something in the
        # controller — so capture the approach, not just the arrival.
        self.trail: list[tuple] = []
        self._last_trail = 0.0

    # -- helpers -----------------------------------------------------------

    def _agg(self, name: str) -> Agg:
        a = self.aggs.get(name)
        if a is None:
            a = self.aggs[name] = Agg()
        return a

    def _changed(self, key: str, value, t: float, event: str,
                 data_extra: dict | None = None) -> list[dict]:
        prev = self.state.get(key)
        self.state[key] = value
        if prev is None or prev == value:
            return []
        d = {"from": prev, "to": value}
        if data_extra:
            d.update(data_extra)
        return [{"t": t, "event": event, "data": d}]

    # -- per-PGN decode ----------------------------------------------------

    def _batt_sts2(self, src: int, p: bytes, t: float) -> list[dict]:
        if src != SRC_SW or len(p) < 14:
            return []
        _st, _assoc, v, i, w = struct.unpack_from("<BBIii", p, 0)
        dc_v = v / 1000
        # Reject physically impossible bus voltages. One frame on 2026-08-01
        # decoded as ~143 kV and dragged a whole 15 min bucket's mean to
        # 2412 V — one bad sample in 855 buckets, but dc_v is the reference
        # the latch detector differences against, and a corrupted stored mean
        # is permanent. The release hysteresis already stops a single sample
        # flipping the detector; this stops it reaching the database at all.
        if not (BUS_V_MIN <= dc_v <= BUS_V_MAX):
            self.bad_dc_v += 1
            return []
        dc_a = i / 1000
        dc_w = float(w)
        # The frame carries its own redundancy: across 3005 buckets, dc_w
        # tracks |dc_v * dc_a| at a ratio of 0.995-0.997. So a consistency
        # check beats a range bound — it catches subtle corruption a plausible
        # range would wave through.
        #
        # Caught one on 2026-08-09 10:10: dc_w decoded as -27844 W while dc_v
        # (27.00) and dc_a (-4.4) were both perfectly fine, so a per-field
        # range check on voltage alone — which is all we had — missed it. It
        # reached the database and showed up as a +28 kW surplus.
        #
        # The 2x window is enormously generous against an observed 0.5%
        # spread; it is there to catch garbage, not to police calibration.
        #
        # THE `abs(dc_a) > 0.5` EXEMPTION USED TO SIT HERE AND IT ADMITTED
        # EXACTLY THE CORRUPTION THIS GUARD EXISTS TO REJECT.
        #
        # A corrupt sample reached a stored mean forty days AFTER the guard
        # shipped: 2026-09-18T00:35:45Z, dc_v 26.871, dc_a -3.951,
        # dc_w -2226.07, dc_w_min -65281. Solving against the twelve clean
        # neighbouring rows (k = dc_w/|dc_v*dc_a| measured at 0.995, dc_v
        # rock-steady throughout, which rules out a corrupt voltage) puts the
        # corrupt frame's dc_a at -0.2538 A — so the exemption was TRUE and
        # the check never ran. Had it run: expected 6.8 W, window
        # [3.4, 13.6] W against |dc_w| 65281, rejected by 4800x.
        #
        # And the exemption is unreachable in normal operation: across 82,466
        # raw BattSts2 frames passing the voltage range, |dc_a| <= 0.5 occurs
        # ZERO times. Its only live effect was on corrupt frames.
        #
        # So the near-zero case is handled by an ABSOLUTE floor instead of by
        # skipping the check. Below 0.5 A the ratio really is meaningless, but
        # the magnitude is not: at the bus's 5-120 V range, 0.5 A cannot
        # produce more than 60 W, so anything past a generous 200 W with a
        # near-zero current is garbage regardless of ratio.
        expected = abs(dc_v * dc_a)
        if abs(dc_a) > 0.5:
            ok = 0.5 * expected <= abs(dc_w) <= 2.0 * expected
        else:
            ok = abs(dc_w) <= NEAR_ZERO_MAX_W
        if not ok:
            self.bad_dc_w += 1
            return []
        self._agg("dc_v").add(dc_v)
        self._agg("dc_a").add(dc_a)
        self._agg("dc_w").add(dc_w)
        return []

    def _dc_src_sts2(self, src: int, p: bytes, t: float) -> list[dict]:
        if src != SRC_MPPT or len(p) < 14:
            return []
        _st, assoc, v, i, w = struct.unpack_from("<BBIii", p, 0)
        if assoc == 0x03:        # MPPT -> battery: THE production channel
            # CROSS-CHECK, which this channel had none of — no range bound and
            # no w ~ v*i test — despite solar_w being the sole input to every
            # solar energy figure this system reports. The redundancy is here
            # and is TIGHTER than the one the dc_w guard relies on: measured
            # |w|/|v*i| = 0.9853..1.0000, mean 0.9929, sd 0.0043 over 3297
            # samples. The exact defect class that produced the -27844 W dc_w
            # row was simply unguarded on the headline channel.
            #
            # Same shape as the dc_w guard, including the near-zero floor, so
            # the two cannot drift in reasoning.
            out_v, out_a, out_w = v / 1000, abs(i / 1000), abs(float(w))
            exp = out_v * out_a
            if out_a > 0.5:
                ok = 0.5 * exp <= out_w <= 2.0 * exp
            else:
                ok = out_w <= NEAR_ZERO_MAX_W
            if not ok:
                self.bad_solar_w += 1
                return []
            self._agg("solar_a").add(out_a)
            self._agg("solar_w").add(out_w)
            self.mppt_out_v = v / 1000
            self.mppt_out_w = abs(float(w))
            self.mppt_status = _st       # status byte — meaning still unknown,
                                         # logged so we can correlate it later
        elif assoc == 0x15:      # PV array side: only voltage is real
            # (no input-side current sensor on this model: I and P are
            # structurally 0 — see docs/xanbus-decode.md)
            self._agg("pv_v").add(v / 1000)
            self.pv_v = v / 1000
        return []

    def _chg_sts(self, src: int, p: bytes, t: float) -> list[dict]:
        if len(p) < 15:
            return []
        target_v, target_i = struct.unpack_from("<ii", p, 2)
        mode = struct.unpack_from("<H", p, 12)[0]
        who = "mppt" if src == SRC_MPPT else "sw"
        out = self._changed(
            f"chg_stage_{who}", CHG_STAGE_NAMES.get(mode, mode), t,
            "chg_stage", {"node": who})
        # charger target/limit (semantics still under study — 29.8 V vs the
        # 28.4 config value; logged so changes are visible either way)
        out += self._changed(f"chg_target_{who}",
                             (target_v // 10, target_i // 10), t,
                             "chg_target",
                             {"node": who, "target_v": target_v / 1000,
                              "target_a": target_i / 1000})
        return out

    def _inv_sts2(self, src: int, data: bytes, t: float) -> list[dict]:
        if src != SRC_SW or len(data) < 4:
            return []
        status = struct.unpack_from("<H", data, 2)[0]
        return self._changed("inv_status",
                             INV_STATUS_NAMES.get(status, status), t,
                             "inverter_mode")

    def _mppt_data(self, src: int, p: bytes, t: float) -> list[dict]:
        """MPPT energy counters — the only production figure on this system
        that does not come from integrating our own samples.

        Emitted sparsely, matching the rest of this decoder: a snapshot at
        most every 15 min and only while the daily counter is actually
        moving, so a quiet night costs nothing. Plus one event at the
        midnight rollover carrying the day's final total, which is the
        number worth having — gap-immune, and directly comparable against
        the integrated figure to measure what the pipeline lost.
        """
        if src != SRC_MPPT or len(p) < MPPT_DAY_WH_OFF + 4:
            return []
        try:
            life_ah, life_wh = (struct.unpack_from("<I", p, MPPT_LIFE_AH_OFF)[0],
                                struct.unpack_from("<I", p, MPPT_LIFE_WH_OFF)[0])
            day_ah, day_wh = (struct.unpack_from("<I", p, MPPT_DAY_AH_OFF)[0],
                              struct.unpack_from("<I", p, MPPT_DAY_WH_OFF)[0])
        except struct.error:
            return []
        if 0xFFFFFFFF in (life_ah, life_wh, day_ah, day_wh):
            return []

        # Decode guard, and it is the same test that identified these fields:
        # Wh/Ah must come out as the pack voltage. If a future firmware moves
        # the layout, this catches it instead of silently logging nonsense.
        # Only checked on the lifetime pair — the daily one divides by zero
        # for the first amp-hour of every morning.
        if life_ah > 0:
            volts = life_wh / life_ah
            if not (MPPT_WH_PER_AH_MIN <= volts <= MPPT_WH_PER_AH_MAX):
                self.bad_mppt_energy += 1
                return []

        # THE DAILY PAIR NEEDS ITS OWN GUARD, and 2026-08-16 06:15:16 is why.
        # The MPPT emitted day_wh = 8388607 (0x7FFFFF) with
        # day_ah = 4286578687 (0xFF7FFFFF) — both saturation patterns — and
        # every existing check passed it:
        #
        #   the 0xFFFFFFFF test    neither value is exactly all-ones
        #   the ratio test         only looks at the LIFETIME pair, which was
        #                          fine at 327313/12059 = 27.14 V
        #
        # The corrupt sample then became `prev`, and on the next reading the
        # rollover branch below saw day_wh DROP and published 8388607 Wh as
        # "the final daily total" — 8.4 MWh from a 750 W array, latched into
        # the ledger by a MAX() that had no bound either.
        #
        # The guard is an INVARIANT, not a threshold: a daily counter can never
        # exceed the lifetime counter it contributes to. No number to tune, and
        # it cannot go stale as the array or the season changes. It catches both
        # corrupt fields here by a factor of 25 and 350,000.
        if day_wh > life_wh or day_ah > life_ah:
            self.bad_mppt_energy += 1
            return []

        events: list[dict] = []
        prev = self.last_day_wh

        # Midnight rollover: the daily counter drops. Carry the FINAL value,
        # not the new zero — that is the whole point of the event.
        if prev is not None and day_wh < prev:
            events.append({"t": t, "event": "mppt_daily_total", "data": {
                "day_wh": prev, "day_ah": self.last_day_ah,
                "life_wh": life_wh, "life_ah": life_ah,
                "note": "final daily total, captured at the counter's reset",
            }})
            self.last_mppt_energy = t     # no snapshot straight after a reset

        self.last_day_wh, self.last_day_ah = day_wh, day_ah

        moving = prev is None or day_wh != prev
        if moving and t - self.last_mppt_energy >= MPPT_ENERGY_PERIOD_S:
            self.last_mppt_energy = t
            events.append({"t": t, "event": "mppt_energy", "data": {
                "day_wh": day_wh, "day_ah": day_ah,
                "life_wh": life_wh, "life_ah": life_ah,
            }})
        return events

    # PGN 126998 is 3 header bytes followed by THREE 25-byte line blocks.
    # Reading them by name instead of by hand-written absolute offsets is the
    # whole fix here: the previous code read blocks 1 and 2 with six separate
    # literals and never touched block 3 at all.
    AC_BLOCK_BASE = 3
    AC_BLOCK_LEN = 25

    @classmethod
    def _ac_block(cls, p: bytes, n: int) -> dict | None:
        """One line block: V (u32 mV), I (i16 mA), F (u16 centiHz), VA (i16).

        Field identification VERIFIED against 7378 reassembled payloads from
        the 2026-10-04 capture: |VA| matches |V*I| to -0.57% mean on the load
        block and -0.21% on the generator block.
        """
        o = cls.AC_BLOCK_BASE + cls.AC_BLOCK_LEN * n
        if len(p) < o + 17:
            return None
        return {
            "v": struct.unpack_from("<I", p, o + 2)[0] / 1000,
            "a": struct.unpack_from("<h", p, o + 6)[0] / 1000,
            "hz": struct.unpack_from("<H", p, o + 11)[0] / 100,
            "va": struct.unpack_from("<h", p, o + 15)[0],
        }

    def _ac_sts_rms(self, src: int, p: bytes, t: float) -> list[dict]:
        # Bound PER BLOCK, not by one assumed frame size. Our own capture is
        # consistently 78 bytes, but a 55-byte AC2Sts sample exists in the
        # project's reference material, and a blanket `len(p) < 70` would
        # silently drop the generator — which lives in block 1 and is fully
        # present in the short form. _ac_block() returns None for a block the
        # payload does not reach, so each read guards itself.
        if src != SRC_SW or len(p) < self.AC_BLOCK_BASE + 17:
            return []
        assoc = p[1]
        out: list[dict] = []

        if assoc == 0x13:        # AC2 = generator input (official enum GEN1)
            # BLOCK 1 carries it; blocks 2 and 3 are structurally zero here.
            # The old code summed blocks 1 and 2, which was right only because
            # block 2 is always zero.
            b = self._ac_block(p, 0)
            if b is None:
                return []
            running = b["v"] > 50.0
            # gen_hz IS NOW CORRECT, and was not. The old offset 41 is block
            # 2's rel-13 field, which holds a hard constant 0x0BB8 = 3000 ->
            # the famous "exactly 30.00" that never varied even at 0 V. It is
            # the AC INPUT CURRENT LIMIT (30.00 A, the Conext SW default), not
            # a frequency. The real value is at block-relative 11, and reads
            # 0.00 stopped and a median 59.94 Hz under a verified 1.6 kW load.
            out += self._changed(
                "gen_running", running, t,
                "gen_start" if running else "gen_stop",
                {"gen_v": round(b["v"], 1), "gen_a": round(b["a"], 2),
                 "gen_va": abs(b["va"]), "gen_hz": round(b["hz"], 2)})
            if running:
                self._agg("gen_v").add(b["v"])
                self._agg("gen_va").add(abs(b["va"]))
            self._agg("gen_a").add(b["a"])

        elif assoc == 0x33:      # AC OUT — the cabin's own load
            # THIS IS THE MEASUREMENT THE PROJECT HAS BEEN WORKING AROUND.
            # The old code read blocks 1 and 2 and reported 0 V / 0 A / 0 VA,
            # and concluded in a comment that "this decode does not work: it
            # reports 0 while the inverter is demonstrably producing AC". The
            # device reports it fine — on BLOCK 3, which was never read.
            #
            # Measured over the same capture: 233.1 V, 0.87 A, 59.95 Hz,
            # 202 VA, with |VA| matching |V*I| to -0.57%. 233 V is the
            # 240 V split-phase output, not a decode error.
            #
            # docs/what-to-distrust.md treats cabin AC load as unmeasurable,
            # and that premise drives task #32, the load_wh argument and the
            # fridge-split work. It is measurable, and has been all along.
            b = self._ac_block(p, 2)
            if b is None:
                return []
            live = b["v"] > 50.0
            if live:
                self._agg("load_v").add(b["v"])
                self._agg("load_a").add(abs(b["a"]))
                self._agg("load_va").add(abs(b["va"]))
            if t - self.last_ac_load >= AC_LOAD_PERIOD_S:
                self.last_ac_load = t
                out.append({"t": t, "event": "ac_load_sample", "data": {
                    "load_v": round(b["v"], 1), "load_a": round(b["a"], 2),
                    "load_hz": round(b["hz"], 2), "load_va": abs(b["va"]),
                    "heartbeat": True,
                }})
        return out

    def _chg_sts(self, src: int, p: bytes, t: float) -> list[dict]:
        if len(p) < 15:
            return []
        target_v, target_i = struct.unpack_from("<ii", p, 2)
        mode = struct.unpack_from("<H", p, 12)[0]
        who = "mppt" if src == SRC_MPPT else "sw"
        out = self._changed(
            f"chg_stage_{who}", CHG_STAGE_NAMES.get(mode, mode), t,
            "chg_stage", {"node": who})
        # charger target/limit (semantics still under study — 29.8 V vs the
        # 28.4 config value; logged so changes are visible either way)
        out += self._changed(f"chg_target_{who}",
                             (target_v // 10, target_i // 10), t,
                             "chg_target",
                             {"node": who, "target_v": target_v / 1000,
                              "target_a": target_i / 1000})
        return out

    def _inv_sts2(self, src: int, data: bytes, t: float) -> list[dict]:
        if src != SRC_SW or len(data) < 4:
            return []
        status = struct.unpack_from("<H", data, 2)[0]
        return self._changed("inv_status",
                             INV_STATUS_NAMES.get(status, status), t,
                             "inverter_mode")

    def _mppt_data(self, src: int, p: bytes, t: float) -> list[dict]:
        """MPPT energy counters — the only production figure on this system
        that does not come from integrating our own samples.

        Emitted sparsely, matching the rest of this decoder: a snapshot at
        most every 15 min and only while the daily counter is actually
        moving, so a quiet night costs nothing. Plus one event at the
        midnight rollover carrying the day's final total, which is the
        number worth having — gap-immune, and directly comparable against
        the integrated figure to measure what the pipeline lost.
        """
        if src != SRC_MPPT or len(p) < MPPT_DAY_WH_OFF + 4:
            return []
        try:
            life_ah, life_wh = (struct.unpack_from("<I", p, MPPT_LIFE_AH_OFF)[0],
                                struct.unpack_from("<I", p, MPPT_LIFE_WH_OFF)[0])
            day_ah, day_wh = (struct.unpack_from("<I", p, MPPT_DAY_AH_OFF)[0],
                              struct.unpack_from("<I", p, MPPT_DAY_WH_OFF)[0])
        except struct.error:
            return []
        if 0xFFFFFFFF in (life_ah, life_wh, day_ah, day_wh):
            return []

        # Decode guard, and it is the same test that identified these fields:
        # Wh/Ah must come out as the pack voltage. If a future firmware moves
        # the layout, this catches it instead of silently logging nonsense.
        # Only checked on the lifetime pair — the daily one divides by zero
        # for the first amp-hour of every morning.
        if life_ah > 0:
            volts = life_wh / life_ah
            if not (MPPT_WH_PER_AH_MIN <= volts <= MPPT_WH_PER_AH_MAX):
                self.bad_mppt_energy += 1
                return []

        # THE DAILY PAIR NEEDS ITS OWN GUARD, and 2026-08-16 06:15:16 is why.
        # The MPPT emitted day_wh = 8388607 (0x7FFFFF) with
        # day_ah = 4286578687 (0xFF7FFFFF) — both saturation patterns — and
        # every existing check passed it:
        #
        #   the 0xFFFFFFFF test    neither value is exactly all-ones
        #   the ratio test         only looks at the LIFETIME pair, which was
        #                          fine at 327313/12059 = 27.14 V
        #
        # The corrupt sample then became `prev`, and on the next reading the
        # rollover branch below saw day_wh DROP and published 8388607 Wh as
        # "the final daily total" — 8.4 MWh from a 750 W array, latched into
        # the ledger by a MAX() that had no bound either.
        #
        # The guard is an INVARIANT, not a threshold: a daily counter can never
        # exceed the lifetime counter it contributes to. No number to tune, and
        # it cannot go stale as the array or the season changes. It catches both
        # corrupt fields here by a factor of 25 and 350,000.
        if day_wh > life_wh or day_ah > life_ah:
            self.bad_mppt_energy += 1
            return []

        events: list[dict] = []
        prev = self.last_day_wh

        # Midnight rollover: the daily counter drops. Carry the FINAL value,
        # not the new zero — that is the whole point of the event.
        if prev is not None and day_wh < prev:
            events.append({"t": t, "event": "mppt_daily_total", "data": {
                "day_wh": prev, "day_ah": self.last_day_ah,
                "life_wh": life_wh, "life_ah": life_ah,
                "note": "final daily total, captured at the counter's reset",
            }})
            self.last_mppt_energy = t     # no snapshot straight after a reset

        self.last_day_wh, self.last_day_ah = day_wh, day_ah

        moving = prev is None or day_wh != prev
        if moving and t - self.last_mppt_energy >= MPPT_ENERGY_PERIOD_S:
            self.last_mppt_energy = t
            events.append({"t": t, "event": "mppt_energy", "data": {
                "day_wh": day_wh, "day_ah": day_ah,
                "life_wh": life_wh, "life_ah": life_ah,
            }})
        return events

    def feed(self, can_id: int, data: bytes, t: float) -> list[dict]:
        pgn, _dest, src = parse_can_id(can_id)
        events: list[dict] = []

        if src in (SRC_SW, SRC_MPPT):
            if src in self.dropped:
                self.dropped.discard(src)
                events.append({"t": t, "event": "node_return",
                               "data": {"node": "sw" if src == SRC_SW else "mppt"}})
            self.last_seen[src] = t

        if pgn in FAST_PACKET_PGNS:
            payload = self.asm.feed(pgn, src, data, t)
            if payload is not None:
                if pgn == PGN_BATT_STS2:
                    events += self._batt_sts2(src, payload, t)
                elif pgn == PGN_DC_SRC_STS2:
                    events += self._dc_src_sts2(src, payload, t)
                elif pgn == PGN_CHG_STS:
                    events += self._chg_sts(src, payload, t)
                elif pgn == PGN_AC_STS_RMS:
                    events += self._ac_sts_rms(src, payload, t)
                elif pgn == PGN_MPPT_DATA:
                    events += self._mppt_data(src, payload, t)
        elif pgn == PGN_INV_STS2:
            events += self._inv_sts2(src, data, t)
        return events

    def housekeeping(self, now: float) -> list[dict]:
        """Call ~1/s: prunes reassembly, detects node dropouts + MPPT latch."""
        self.asm.prune(now)
        self._record_trail(now)
        events = self.reject_report(now)
        for src, name in ((SRC_SW, "sw"), (SRC_MPPT, "mppt")):
            seen = self.last_seen.get(src)
            if seen is not None and src not in self.dropped \
                    and now - seen > DROPOUT_S:
                self.dropped.add(src)
                events.append({"t": now, "event": "node_dropout",
                               "data": {"node": name,
                                        "silent_s": round(now - seen)}})
        events += self._check_latch(now)
        return events

    def _record_trail(self, now: float) -> None:
        """Keep ~20 min of 1 Hz array/converter state for latch forensics."""
        if now - self._last_trail < 1.0 or self.pv_v is None:
            return
        self._last_trail = now
        self.trail.append((round(now, 1), round(self.pv_v, 1),
                           round(self.mppt_out_v or 0, 2),
                           round(self.mppt_out_w or 0, 1),
                           self.mppt_status))
        if len(self.trail) > LATCH_TRAIL_S:
            del self.trail[:len(self.trail) - LATCH_TRAIL_S]

    def _check_latch(self, now: float) -> list[dict]:
        """Diode-clamp detector: array pinned within a diode drop of the
        output while the sun is up means the converter has stopped
        switching and power is bypassing it unregulated."""
        if self.pv_v is None or self.mppt_out_v is None:
            return []
        delta = self.pv_v - self.mppt_out_v
        clamped = (self.pv_v > LATCH_DAYLIGHT_V
                   and LATCH_DELTA_MIN_V <= delta <= LATCH_DELTA_MAX_V
                   and sun_elevation_deg(now) >= MIN_SUN_ELEVATION_DEG)
        if not clamped:
            # Hysteresis applies on the way IN as well as out. Zeroing
            # clamp_since on the first out-of-band sample means one brief
            # excursion restarts the whole 600 s confirmation, and a real
            # latch can then never be reported: on 2026-08-06 the array sat
            # clamped 16:35-17:00 local, twitched to delta 4.19 V once around
            # 16:50, and the detector emitted nothing for the entire 25 min.
            # The guard's fraction-over-a-window test caught it; this
            # continuous-run test did not. Same grace both directions.
            if self.clamp_clear_since is None:
                self.clamp_clear_since = now
            if now - self.clamp_clear_since < LATCH_RELEASE_S:
                return []                       # brief excursion: hold state
            self.clamp_since = None             # sustained: accumulation void
            if not self.latched:
                return []
            self.latched = False
            self.clamp_clear_since = None
            return [{"t": now, "event": "mppt_unlatched",
                     "data": {"pv_v": round(self.pv_v, 1),
                              "delta_v": round(delta, 2)}}]
        self.clamp_clear_since = None
        if self.clamp_since is None:
            self.clamp_since = now
        if not self.latched and now - self.clamp_since >= LATCH_CONFIRM_S:
            self.latched = True
            # Ship the run-up with the event. Decimated to ~5 s so the payload
            # stays a few KB while still showing the shape of the slide.
            trail = [t for i, t in enumerate(self.trail) if i % 5 == 0]
            return [
                {"t": now, "event": "mppt_latched",
                 "data": {"pv_v": round(self.pv_v, 1),
                          "out_v": round(self.mppt_out_v, 2),
                          "delta_v": round(delta, 2),
                          # NOT exposure, and it has been misread as exposure.
                          # This line only runs on the sample where
                          # `now - clamp_since >= LATCH_CONFIRM_S` first holds,
                          # so it reports LATCH_CONFIRM_S every time — 600..608 s
                          # across all 12 latches on record. Total exposure spans
                          # this event and mppt_unlatched; measure it with
                          # scripts/latch_exposure.py (median ~20 min, not 10).
                          "clamped_s": round(now - self.clamp_since),
                          "status_byte": self.mppt_status,
                          "fix": "Operating Mode -> Standby -> Operating"}},
                {"t": now, "event": "mppt_latch_context",
                 "data": {"note": "1Hz array trail preceding the latch, "
                                  "decimated to 5s: [t, pv_v, out_v, out_w, status]",
                          "samples": len(trail),
                          "trail": trail}},
            ]
        return []

    # How often to report rejections, and only when the count MOVED. A
    # periodic zero would be noise; silence after a non-zero report would be
    # ambiguous again. Reporting the DELTA means the stream says "n frames
    # were discarded since last time" exactly when that is true.
    REJECT_REPORT_S = 1800

    # Fast-packet frame loss has a NON-ZERO BASELINE: 21 in 194,392 frames
    # (0.011%) measured on this bus. At 7,077 frames/min that is ~23 discards
    # per 30 min, so alerting on any non-zero count pages on normal operation
    # — which it did, within hours of shipping, reporting 19 against an
    # expected 23. Noise is how an operator learns to ignore the channel, and
    # removing that is most of what today was about.
    #
    # So bad_asm_seq is judged as a RATE against a generous multiple of the
    # measured baseline. The other counters are different in kind: a rejected
    # dc_w or solar_w is a CORRUPT FRAME, whose expected rate is zero, so any
    # movement there is worth knowing about.
    ASM_BASELINE_PCT = 0.011
    ASM_ALERT_PCT = 0.11            # 10x baseline: a real change in the bus

    def reject_report(self, now: float) -> list[dict]:
        """Surface the rejection counters, which were otherwise write-only."""
        fields = ("bad_dc_v", "bad_dc_w", "bad_solar_w", "bad_mppt_energy")
        cur = {f: getattr(self, f, 0) for f in fields}
        cur["bad_asm_seq"] = getattr(self.asm, "bad_asm_seq", 0) \
            if hasattr(self, "asm") else 0
        if now - self.last_reject_report < self.REJECT_REPORT_S:
            return []
        delta = {k: v - self.reject_reported.get(k, 0) for k, v in cur.items()}
        self.last_reject_report = now
        self.reject_reported = dict(cur)
        moved = {k: v for k, v in delta.items() if v}
        if not moved:
            return []
        fed = getattr(self.asm, "fed_total", 0) if hasattr(self, "asm") else 0
        fed_delta = fed - self.reject_reported.get("_fed", 0)
        self.reject_reported["_fed"] = fed
        asm_pct = (100.0 * delta.get("bad_asm_seq", 0) / fed_delta
                   if fed_delta else 0.0)
        # NOTABLE is what the alert rule keys on. Corrupt-frame counters have
        # an expected rate of zero, so any movement counts; frame loss does
        # not, so it must clear a multiple of its measured baseline.
        corrupt = any(delta.get(f, 0) for f in fields)
        notable = bool(corrupt or asm_pct > self.ASM_ALERT_PCT)
        return [{"t": now, "event": "decode_rejections", "data": {
            **moved,
            "notable": notable,
            "asm_pct": round(asm_pct, 4),
            "asm_baseline_pct": self.ASM_BASELINE_PCT,
            "frames": fed_delta,
            "window_s": self.REJECT_REPORT_S,
            "note": "frames DISCARDED by the decoder's sanity checks. A "
                    "sustained non-zero rate means the bus or the decode has "
                    "changed; these counters were previously invisible, so "
                    "a decoder rejecting everything looked like a quiet bus.",
        }}]

    def flush_bucket(self, now: float) -> dict | None:
        """If a 15 s wall-aligned bucket has completed, return its row."""
        cur = int(now // BUCKET_S) * BUCKET_S
        if self.bucket_start is None:
            self.bucket_start = cur
            return None
        if cur == self.bucket_start:
            return None
        row_ts, aggs = self.bucket_start, self.aggs
        self.bucket_start, self.aggs = cur, {}
        if not aggs:
            return None

        def m(name, nd=2):
            a = aggs.get(name)
            return round(a.mean, nd) if a and a.n else None

        solar = aggs.get("solar_w")
        dc = aggs.get("dc_w")
        pv = aggs.get("pv_v")
        n = solar.n if solar else (dc.n if dc else 0)
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(row_ts)),
            # 4: load_v/load_a/load_va — the cabin's own AC load, which this
            # system believed it could not measure until the block-3 decode
            # was fixed. The server must know these fields BEFORE this bump
            # reaches the Pi — see migrations 0006 and 0007.
            "schema_version": 4,
            "solar_w": m("solar_w"),
            "solar_w_min": round(solar.min, 2) if solar and solar.n else None,
            "solar_w_max": round(solar.max, 2) if solar and solar.n else None,
            "solar_a": m("solar_a", 3),
            "pv_v": m("pv_v"),
            # v2: array-voltage extremes. The diode-clamp latch is a SLIDE down
            # the IV curve, and a bucket mean hides how far it moved within the
            # interval — min/max is what shows the approach and the recovery.
            "pv_v_min": round(pv.min, 2) if pv and pv.n else None,
            "pv_v_max": round(pv.max, 2) if pv and pv.n else None,
            "dc_v": m("dc_v", 3),
            "dc_a": m("dc_a", 3),
            "dc_w": m("dc_w"),
            "dc_w_min": round(dc.min, 2) if dc and dc.n else None,
            "dc_w_max": round(dc.max, 2) if dc and dc.n else None,
            # The generator's AC side. None on every bucket where the
            # generator was not seen, which is almost all of them.
            "gen_v": m("gen_v", 1),
            "gen_a": m("gen_a", 2),
            "gen_va": m("gen_va", 1),
            # The cabin's AC load. None whenever the inverter is not
            # producing, which is the honest answer rather than 0 W.
            "load_v": m("load_v", 1),
            "load_a": m("load_a", 2),
            "load_va": m("load_va", 1),
            "sample_n": n,
        }
        return row


# --------------------------------------------------------------------------
# Spool + upload (I/O shell)

class Spool:
    """Append-then-seal JSONL spool, one per stream."""

    def __init__(self, base: Path):
        self.live = base
        self.base = base.name
        self.dir = base.parent
        self.dir.mkdir(parents=True, exist_ok=True)
        self._f = open(self.live, "a")

    def append(self, obj: dict):
        self._f.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self._f.flush()

    def seal(self):
        """Rename the live file to the next .NNNN.sealed (if non-empty)."""
        if self._f.tell() == 0 and not (self.live.exists() and self.live.stat().st_size):
            return
        self._f.close()
        seqs = [int(m.group(1)) for p in self.dir.glob(f"{self.base}.*.sealed")
                if (m := re.search(r"\.(\d+)\.sealed$", p.name))]
        nxt = (max(seqs) + 1) if seqs else 1
        self.live.rename(self.dir / f"{self.base}.{nxt:05d}.sealed")
        # absolute disk bound: drop OLDEST beyond KEEP_SEALED
        sealed = sorted(self.dir.glob(f"{self.base}.*.sealed"))
        for old in sealed[:-KEEP_SEALED]:
            old.unlink(missing_ok=True)
        self._f = open(self.live, "a")

    def sealed_files(self) -> list[Path]:
        return sorted(self.dir.glob(f"{self.base}.*.sealed"))


# A POISON BATCH IS NOT AN OUTAGE, and treating them alike stalls the stream.
#
# `except Exception: return False` made a 422 indistinguishable from a 502, so
# a batch the server will NEVER accept was retried forever and blocked every
# segment behind it. That is the 2026-08-05 incident — one unknown field,
# extra="forbid", 43 minutes of stalled solar ingest — and only the DEPLOY
# ORDER was ever mitigated, not the mechanism.
#
# It is worse than 43 minutes now: Spool.seal() prunes the OLDEST sealed file
# at KEEP_SEALED=2000 x 300 s, so a poison segment produces a 6.9-DAY silent
# outage that then "self-heals" by unlinking five minutes of data with no log
# line at all.
#
# 4xx (except 408/429) means the server has judged the CONTENT. Retrying it is
# pointless; what is needed is to quarantine that segment, say so loudly, and
# keep the stream moving.
POST_OK = "ok"
POST_RETRY = "retry"          # transient: 5xx, timeout, connection refused
POST_POISON = "poison"        # permanent: the server rejected the content


def _post(url: str, token: str, body: dict, timeout: float = 60.0) -> str:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return POST_OK if 200 <= resp.status < 300 else POST_RETRY
    except urllib.error.HTTPError as exc:
        # 408 Request Timeout and 429 Too Many Requests ARE worth retrying;
        # every other 4xx is a verdict on the bytes we sent.
        if 400 <= exc.code < 500 and exc.code not in (408, 429):
            log.error("POST %s REJECTED http=%d — poison batch, quarantining",
                      url, exc.code)
            return POST_POISON
        log.warning("POST %s failed: %s", url, exc)
        return POST_RETRY
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return POST_RETRY


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def uploader_loop(rows_spool: Spool, events_spool: Spool,
                  base_url: str, token: str, source_id: str):
    """Drains sealed segments. Runs as a daemon thread; never raises.

    That sentence used to be a CLAIM with no mechanism behind it — there was
    no try/except anywhere in the function. Reachable throws include
    FileNotFoundError from _read_jsonl when the KEEP_SEALED prune unlinks a
    segment between sealed_files() and the read (precisely the file this loop
    takes first), and any OSError from the SD card going read-only.

    When it threw, the thread died, the CAN loop kept decoding and spooling
    forever, `Restart=always` did nothing because the PROCESS was alive, and
    there is no WatchdogSec anywhere. Upload stopped permanently and silently.
    Now the claim has a mechanism.
    """
    backoff = 30.0
    while not _stop:
        time.sleep(15.0)
        try:
            backoff = _drain_once(rows_spool, events_spool, base_url, token,
                                  source_id, backoff)
        except Exception:
            # Log and CARRY ON. A transient filesystem error must not retire
            # the uploader for the lifetime of the process.
            log.exception("uploader pass failed; retrying")
            time.sleep(min(backoff, 600.0))
            backoff *= 2
    return


def _drain_once(rows_spool: Spool, events_spool: Spool, base_url: str,
                token: str, source_id: str, backoff: float) -> float:
    """One drain pass. Split out so uploader_loop's guard wraps everything."""
    if True:
        ok_all = True
        for spool, endpoint, kind, key in (
                (rows_spool, "/api/solar/ingest", "readings", "readings"),
                (events_spool, "/api/xanbus_events/ingest", "events", "events")):
            for path in spool.sealed_files():
                if _stop:
                    return
                items = _read_jsonl(path)
                if items:
                    if kind == "events":
                        items = [{"ts": time.strftime(
                                      "%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime(e.pop("t"))),
                                  "event": e["event"],
                                  "data": e.get("data", {})}
                                 for e in items]
                    verdict = POST_OK
                    for i in range(0, len(items), 500):
                        body = {"source_id": source_id,
                                key: items[i:i + 500]}
                        verdict = _post(base_url + endpoint, token, body)
                        if verdict != POST_OK:
                            break
                    if verdict == POST_POISON:
                        # QUARANTINE rather than retry or delete. Retrying
                        # blocks the stream forever; deleting destroys the one
                        # copy of whatever exposed a schema mismatch. Moved
                        # aside so the queue drains and the evidence survives.
                        bad = path.with_suffix(path.suffix + ".poison")
                        try:
                            path.rename(bad)
                            log.error("quarantined %s -> %s", path.name,
                                      bad.name)
                        except OSError as exc:
                            log.error("could not quarantine %s: %s",
                                      path.name, exc)
                            ok_all = False
                            break
                        continue
                    if verdict != POST_OK:
                        ok_all = False
                        break          # keep file; retry next pass
                path.unlink(missing_ok=True)
        if not ok_all:
            time.sleep(min(backoff, 600.0))
            return backoff * 2
        return 30.0


# --------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, _sig)

    base_url = os.environ.get("VOLTHIUM_URL", "https://volts.alti2.de")
    token = os.environ.get("READER_TOKEN", "")
    source_id = os.environ.get("VOLTHIUM_SOURCE_ID", "pi-barge")
    if not token:
        log.error("READER_TOKEN not set (EnvironmentFile missing?)")
        return 2

    rows_spool = Spool(SPOOL_DIR / "rows.jsonl")
    events_spool = Spool(SPOOL_DIR / "events.jsonl")
    threading.Thread(target=uploader_loop,
                     args=(rows_spool, events_spool, base_url, token,
                           source_id),
                     daemon=True).start()

    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind(("can0",))
    sock.settimeout(1.0)
    log.info("decoding can0 -> %s (upload %s as %s)",
             SPOOL_DIR, base_url, source_id)

    dec = Decoder()
    last_house = last_seal = time.time()
    while not _stop:
        try:
            frame = sock.recv(16)
            now = time.time()
            can_id, dlc, data = struct.unpack(CAN_FRAME, frame)
            if can_id & CAN_EFF_FLAG:
                for ev in dec.feed(can_id & 0x1FFFFFFF, data[:dlc], now):
                    events_spool.append(ev)
        except socket.timeout:
            now = time.time()
        except OSError as exc:
            log.warning("CAN read error: %s (retrying)", exc)
            time.sleep(2.0)
            now = time.time()

        if now - last_house >= 1.0:
            last_house = now
            for ev in dec.housekeeping(now):
                events_spool.append(ev)
            row = dec.flush_bucket(now)
            if row is not None:
                rows_spool.append(row)
            if now - last_seal >= UPLOAD_PERIOD_S:
                last_seal = now
                rows_spool.seal()
                events_spool.seal()

    rows_spool.seal()
    events_spool.seal()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
