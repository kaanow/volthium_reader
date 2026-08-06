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
import threading
import time
from pathlib import Path

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
LATCH_DAYLIGHT_V = 20.0        # array must at least exceed a dark panel string
LATCH_CONFIRM_S = 600          # sustained this long before we call it
LATCH_RELEASE_S = 120          # ...and sustained THIS long before we clear it
LATCH_TRAIL_S = 1200           # seconds of 1 Hz history kept for forensics
AC_LOAD_SAMPLE_S = 300         # provisional AC-load snapshot cadence
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

FAST_PACKET_PGNS = {PGN_BATT_STS2, PGN_DC_SRC_STS2, PGN_CHG_STS, PGN_AC_STS_RMS}

SRC_SW, SRC_MPPT = 0, 1        # node addresses on our bus

CHG_STAGE_NAMES = {768: "not_charging", 769: "bulk", 770: "absorption",
                   773: "float", 777: "qualifying_ac"}
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
        self._buf: dict[tuple, list] = {}   # (pgn,src,seq) -> [total, bytes, t]

    def feed(self, pgn: int, src: int, data: bytes, t: float):
        """Returns the reassembled payload or None."""
        seq, fid = data[0] >> 5, data[0] & 0x1F
        key = (pgn, src, seq)
        if fid == 0:
            self._buf[key] = [data[1], bytearray(data[2:]), t]
            return None
        ent = self._buf.get(key)
        if ent is None:
            return None
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
        # latch detection state (see LATCH_* constants)
        self.pv_v: float | None = None
        self.mppt_out_v: float | None = None
        self.mppt_out_w: float | None = None
        self.mppt_status: int | None = None
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
        self._agg("dc_v").add(v / 1000)
        self._agg("dc_a").add(i / 1000)
        self._agg("dc_w").add(float(w))
        return []

    def _dc_src_sts2(self, src: int, p: bytes, t: float) -> list[dict]:
        if src != SRC_MPPT or len(p) < 14:
            return []
        _st, assoc, v, i, w = struct.unpack_from("<BBIii", p, 0)
        if assoc == 0x03:        # MPPT -> battery: THE production channel
            self._agg("solar_a").add(abs(i / 1000))
            self._agg("solar_w").add(abs(float(w)))
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

    def _ac_sts_rms(self, src: int, p: bytes, t: float) -> list[dict]:
        if src != SRC_SW or len(p) < 49:
            return []
        assoc = p[1]
        v1 = struct.unpack_from("<I", p, 5)[0] / 1000
        i1 = struct.unpack_from("<h", p, 9)[0] / 1000
        va_a = struct.unpack_from("<h", p, 18)[0]
        v2 = struct.unpack_from("<I", p, 30)[0] / 1000
        i2 = struct.unpack_from("<h", p, 34)[0] / 1000
        freq = struct.unpack_from("<h", p, 41)[0] / 100   # ac2_f
        va_b = struct.unpack_from("<h", p, 43)[0]
        va = abs(va_a + va_b)
        out: list[dict] = []
        if assoc == 0x13:        # AC2 = generator input (official enum GEN1)
            running = v1 > 50.0
            out += self._changed(
                "gen_running", running, t,
                "gen_start" if running else "gen_stop",
                {"gen_v": round(v1, 1), "gen_a": round(i1 + i2, 2),
                 "gen_va": va, "gen_hz": round(freq, 2)})
            if running:
                self._agg("gen_v").add(v1)
                self._agg("gen_va").add(va)
        elif assoc == 0x33:      # AC out / cabin loads — PROVISIONAL decode
            if t - self.last_ac_load_sample >= AC_LOAD_SAMPLE_S:
                self.last_ac_load_sample = t
                out.append({"t": t, "event": "ac_load_sample",
                            "data": {"load_v": round(v1, 1),
                                     "load_a": round(i1 + i2, 3),
                                     "load_va": va,
                                     "load_hz": round(freq, 2),
                                     "provisional": True}})
        return out

    # -- public ------------------------------------------------------------

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
        elif pgn == PGN_INV_STS2:
            events += self._inv_sts2(src, data, t)
        return events

    def housekeeping(self, now: float) -> list[dict]:
        """Call ~1/s: prunes reassembly, detects node dropouts + MPPT latch."""
        self.asm.prune(now)
        self._record_trail(now)
        events = []
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
                   and LATCH_DELTA_MIN_V <= delta <= LATCH_DELTA_MAX_V)
        if not clamped:
            self.clamp_since = None
            if not self.latched:
                return []
            # Releasing needs hysteresis for the same reason the ceiling was
            # raised: a single dithered sample is not a recovery. Requiring a
            # sustained exit means "unlatched" reports a tracker that actually
            # climbed back out, not one quantisation step of noise.
            if self.clamp_clear_since is None:
                self.clamp_clear_since = now
            if now - self.clamp_clear_since < LATCH_RELEASE_S:
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
            "schema_version": 2,
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


def _post(url: str, token: str, body: dict, timeout: float = 60.0) -> bool:
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("POST %s failed: %s", url, exc)
        return False


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
    """Drains sealed segments. Runs as a daemon thread; never raises."""
    backoff = 30.0
    while not _stop:
        time.sleep(15.0)
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
                    ok = True
                    for i in range(0, len(items), 500):
                        body = {"source_id": source_id,
                                key: items[i:i + 500]}
                        if not _post(base_url + endpoint, token, body):
                            ok = False
                            break
                    if not ok:
                        ok_all = False
                        break          # keep file; retry next pass
                path.unlink(missing_ok=True)
        if not ok_all:
            time.sleep(min(backoff, 600.0))
            backoff *= 2
        else:
            backoff = 30.0


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
