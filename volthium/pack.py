"""Two Volthium 12V batteries wired in series → one logical 24V pack."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiobmsble import BMSSample
from aiobmsble.bms.ej_bms import BMS as VolthiumBMS
from bleak import BleakScanner
from bleak.backends.device import BLEDevice


# SC12200G4DPH advertises as "V-12V200Ah-<serial>"
ADV_NAME_PREFIX = "V-12V"


# --- Structured BLE diagnostics ------------------------------------------------
# A per-cycle JSONL trace of everything the radio does: discovery results with
# per-battery RSSI, connect/read/disconnect timings, classified read errors, and
# — most important — the *wedge signature*: a battery that's absent from the
# discovery scan yet still shows a live controller connection. That state is the
# proven failure mode (a leaked BleakClient pins a single-connection BMS so it
# stops advertising; see docs/reliability_failure_modes.md, FM-8). We log it with
# the raw `hcitool con` evidence so a future outage is self-diagnosing rather than
# needing a live operator with bluetoothctl.
#
# The writer uses sealed-segment rotation:
#   - Live file: <path>              (writer appends here)
#   - Sealed:    <path>.NNNN.sealed  (immutable; uploader drains + deletes)
# The uploader never touches the live file so writer and uploader can't race.
# Rotation triggers at 5 MB or after 10 min of accumulation (whichever first),
# so the round-trip Pi → Railway latency is bounded even when the pack is idle.
# HARDWARE-DEP: Pi 3B — default path is a tmpfs (/run/volthium/). Originally
# because the on-board SU16G SD card couldn't sustain the write rate; the
# 2026-07-09 upgrade to a Samsung PRO Endurance 64 GB card removed that
# constraint, but we keep tmpfs because it also gives a clean rotate/upload
# boundary (writer never touches sealed segments, uploader never touches the
# live file, and event logs vanish on reboot — a virtue for privacy).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVENT_LOG = Path(
    os.environ.get("VOLTHIUM_BLE_EVENT_LOG", _REPO_ROOT / "data" / "ble_events.jsonl")
)

# Rotation tunables — small enough to keep tmpfs footprint modest, large enough
# that segments amortize the HTTP overhead on the uploader side.
_MAX_SEGMENT_BYTES = 5_000_000     # 5 MB per sealed segment
_MAX_SEGMENT_AGE_S = 600.0         # force rotate every 10 min so latency is bounded
_MAX_SEALED_KEEP = 8               # 8 * 5 MB = 40 MB ceiling if uploader is way behind


class _EventLogWriter:
    """Sealed-segment log writer for BLE diagnostics.

    Instantiate once per process (module-level `_writer` below). All state is
    on the instance so tests can construct fresh writers with a temp path.
    """

    def __init__(
        self,
        log_path: Path,
        max_segment_bytes: int = _MAX_SEGMENT_BYTES,
        max_segment_age_s: float = _MAX_SEGMENT_AGE_S,
        max_sealed_keep: int = _MAX_SEALED_KEEP,
    ) -> None:
        self.log_path = log_path
        self.max_segment_bytes = max_segment_bytes
        self.max_segment_age_s = max_segment_age_s
        self.max_sealed_keep = max_sealed_keep
        self._fh = None
        self._size = 0
        self._opened_at = 0.0
        self._next_seq: Optional[int] = None

    def write_line(self, line: str) -> None:
        """Append one JSONL line; may trigger rotation. Never raises — the
        read loop must survive a broken diagnostics pipeline."""
        try:
            if self._fh is None:
                self._open()
            assert self._fh is not None
            self._fh.write(line)
            self._fh.flush()
            self._size += len(line.encode("utf-8"))
            now = time.monotonic()
            over_size = self._size >= self.max_segment_bytes
            aged_out = (
                self._size > 0
                and (now - self._opened_at) >= self.max_segment_age_s
            )
            if over_size or aged_out:
                self._rotate()
        except Exception:
            # Diagnostics must never propagate — try to recover on next call.
            try:
                if self._fh is not None:
                    self._fh.close()
            except Exception:
                pass
            self._fh = None

    def _open(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.log_path.open("a")
        try:
            self._size = self.log_path.stat().st_size
        except OSError:
            self._size = 0
        self._opened_at = time.monotonic()
        # Inherit the age of pre-existing content. Without this, a crash-looping
        # process resets the age clock every respawn and the age-based rotation
        # NEVER fires — which is exactly how 14 h of wedge diagnostics sat
        # unshipped on the Pi during the 2026-07-12/13 outage (each 5-min-lived
        # process thought its segment was 0 minutes old). Age = now minus the
        # first line's `ts`, so the 10-min latency bound holds across restarts.
        if self._size > 0:
            age = self._first_line_age_s()
            if age is not None and age > 0:
                self._opened_at = time.monotonic() - age
        if self._next_seq is None:
            self._next_seq = self._discover_next_seq()
        # If we're opening onto an already-oversized or already-aged-out live
        # file (e.g. previous process died before it could rotate), seal it
        # right away — then reopen so the caller's pending write still lands
        # (rotate leaves _fh None for the normal in-loop path).
        if self._size >= self.max_segment_bytes or (
            self._size > 0
            and (time.monotonic() - self._opened_at) >= self.max_segment_age_s
        ):
            self._rotate()
            self._fh = self.log_path.open("a")

    def _first_line_age_s(self) -> Optional[float]:
        """Age in seconds of the oldest event in the live file, from its `ts`
        field. Best-effort — None if the line is unreadable/unparseable."""
        try:
            with self.log_path.open("r") as f:
                first = f.readline()
            ts = json.loads(first).get("ts", "")
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt).total_seconds()
            # Clamp to sanity: a corrupt/future ts must not produce a bogus age.
            return age if 0 <= age <= 7 * 86400 else None
        except Exception:
            return None

    def close(self) -> None:
        """Close the live file handle without sealing (tests, shutdown).
        The next write_line() reopens transparently."""
        try:
            if self._fh is not None:
                self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None

    def seal_now(self) -> None:
        """Seal the live segment immediately regardless of size/age, so the
        events uploader can ship it. Called on process exit — a logger that's
        about to die for a wedge restart must not take its evidence with it.
        Never raises."""
        try:
            if self._fh is None:
                try:
                    if not self.log_path.exists() or self.log_path.stat().st_size == 0:
                        return
                except OSError:
                    return
                self._open()
            if self._size > 0:
                self._rotate()
        except Exception:
            pass

    def _discover_next_seq(self) -> int:
        max_seq = 0
        for p in self.log_path.parent.glob(f"{self.log_path.name}.*.sealed"):
            # <base>.NNNN.sealed — take the second-to-last dotted component
            try:
                seq = int(p.name.rsplit(".", 2)[-2])
                max_seq = max(max_seq, seq)
            except (ValueError, IndexError):
                pass
        return max_seq + 1

    def _rotate(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.close()
        except Exception:
            pass
        self._fh = None
        # Enforce the sealed-file cap: if the uploader is behind, drop the
        # oldest sealed file to make room. Older diagnostics are less useful
        # than dropping the whole pipeline into a wedge state.
        self._enforce_cap()
        # Seal the live file by rename. Uploader never touches sealed files
        # until we've done this, so no race.
        assert self._next_seq is not None
        sealed = self.log_path.parent / f"{self.log_path.name}.{self._next_seq:04d}.sealed"
        try:
            if self.log_path.exists():
                self.log_path.rename(sealed)
        except OSError:
            pass
        self._next_seq += 1
        # Reopen fresh — next write_line() will create the live file if needed.
        self._size = 0
        self._opened_at = time.monotonic()

    def _enforce_cap(self) -> None:
        existing = sorted(self.log_path.parent.glob(f"{self.log_path.name}.*.sealed"))
        while len(existing) >= self.max_sealed_keep:
            try:
                existing[0].unlink()
            except OSError:
                break
            existing = existing[1:]


_writer = _EventLogWriter(_EVENT_LOG)


def _reset_writer_for_tests(path: Path) -> _EventLogWriter:
    """Test helper — swap the module-level writer to a fresh path. Returns
    the new writer so tests can also close/inspect it explicitly. Closes the
    outgoing writer's handle so its temp dir can be deleted (Windows can't
    remove open files)."""
    global _writer
    _writer.close()
    _writer = _EventLogWriter(path)
    return _writer


def seal_event_log() -> None:
    """Seal the live event segment so the uploader ships it now rather than
    on the next rotation. Call before any deliberate process exit."""
    try:
        _writer.seal_now()
    except Exception:
        pass


def _event(event: str, **fields) -> None:
    """Append one structured BLE record as JSON. Best-effort — diagnostics must
    never break the read loop, so every failure here is swallowed."""
    try:
        rec = {
            "ts": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "event": event,
            **fields,
        }
        _writer.write_line(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


# --- Raw BLE frame capture ------------------------------------------------
# Env-gated: VOLTHIUM_CAPTURE_RAW=1 turns on notify-frame taps in the read
# path, streaming hex-encoded BMS responses through the same _event() log for
# later lab replay. Auto-caps at _CAPTURE_CYCLE_CAP pack cycles per process
# so a long-running logger doesn't drown the pipeline in raw traffic.
#
# NOT a hardware-dependent workaround — this exists to gather samples for
# building an offline BMS simulator. As of 2026-07-09 the corpus at
# `data/simulator/pi-barge_raw_frames.jsonl` (~3.9k frames, ~550 full BMS
# records across both batteries) is sufficient for simulator work, so the
# flag is off in production. Turn it back on temporarily to grow the
# corpus for a specific scenario (e.g. a charging-cycle span). Each process
# restart opens a fresh 30-cycle capture window.
_CAPTURE_CYCLE_CAP = 30
_capture_pack_cycles = 0


def _capture_active() -> bool:
    return (
        os.environ.get("VOLTHIUM_CAPTURE_RAW", "0") == "1"
        and _capture_pack_cycles < _CAPTURE_CYCLE_CAP
    )


class _VolthiumBMSTapped(VolthiumBMS):
    """VolthiumBMS with a raw-frame tap on the notify path.

    Overriding `_notification_handler` gives us the raw bytes as bleak
    delivers them — after HCI reassembly but before aiobmsble decodes into
    a BMSSample. Perfect for lab replay: capture (RX bytes, timing) tuples,
    replay them back into a mock BleakClient to reconstruct a session.
    """
    _raw_addr: str = ""

    def _notification_handler(self, *args, **kwargs):
        try:
            # bleak calls (BleakGATTCharacteristic, bytearray). Be defensive.
            data = args[1] if len(args) > 1 else kwargs.get("data", b"")
            _event(
                "raw_frame",
                address=self._raw_addr,
                direction="rx",
                data_hex=bytes(data).hex(),
                data_len=len(bytes(data)),
            )
        except Exception:
            # A broken tap must never break the read.
            pass
        return super()._notification_handler(*args, **kwargs)


def _make_bms(dev: BLEDevice, address: str, keep_alive: bool = True):
    """Construct the BMS instance for a single read cycle, choosing between
    the tapped and plain classes based on whether raw capture is active."""
    if _capture_active():
        bms = _VolthiumBMSTapped(ble_device=dev, keep_alive=keep_alive)
        bms._raw_addr = address.upper()
        return bms
    return VolthiumBMS(ble_device=dev, keep_alive=keep_alive)


async def _run(cmd: list[str], *, timeout: float = 8.0) -> str:
    """Run a short BlueZ CLI command and return combined stdout/stderr. Used for
    observational connection-state checks (no discovery), so it can't collide
    with the single-adapter scan. Never raises — returns an error marker."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return out.decode(errors="replace")
    except Exception as exc:  # noqa: BLE001 — diagnostics, must not propagate
        return f"<cmd {' '.join(cmd)} failed: {type(exc).__name__}: {exc}>"


async def _connected_targets(targets: set[str]) -> set[str]:
    """Of `targets`, which does the controller currently hold an LE connection
    to? Parses `hcitool con`. A target here that we could NOT discover/read this
    cycle is wedged: pinned by a leaked connection so it can't advertise."""
    out = await _run(["hcitool", "con"])
    up = out.upper()
    return {t for t in targets if t.upper() in up}


async def _force_disconnect(addr: str) -> str:
    """Best-effort release of a wedged battery's radio from the Pi side. Clears
    a BlueZ-level lingering connection; an in-process leaked client may re-grab
    it (the logger's wedge self-restart is the backstop for that case).

    HARDWARE-DEP: Pi 3B — this exists because BlueZ leaks connections after
    certain error paths. A cleaner BT stack (e.g. NimBLE on an ESP32 or a
    dedicated USB dongle with a modern controller) wouldn't need this ladder.
    """
    return (await _run(["bluetoothctl", "disconnect", addr], timeout=15.0)).strip()


# Bounds for one battery read. The read is capped so a hung GATT exchange can't
# park a live connection; the disconnect is capped AND verified because
# aiobmsble's disconnect() (basebms.py) has no timeout and silently swallows
# BleakError, while keep_alive=True leaves the link open after a read — together
# the exact recipe that leaks a client and wedges a single-connection BMS (FM-8).
# These were originally conservative because the on-board BCM43438 combo
# chip's HCI transport drops frames under Wi-Fi coexistence pressure (dozens
# of `Frame reassembly failed (-84)` in dmesg per bad session). Since
# 2026-07-09 the reader has been pinned to the TP-Link UB500 dongle
# (RTL8761B on its own USB controller — no Wi-Fi coexistence), so these
# could tighten to ~5 s / ~3 s. Left as-is for headroom against random
# BlueZ hiccups; revisit if we ever want faster per-cycle turnaround.
_READ_TIMEOUT = 15.0
_DISCONNECT_TIMEOUT = 10.0


async def _teardown(bms: VolthiumBMS, address: str) -> None:
    """Guarantee a battery's link is released after a read. This is the
    source-level cure for FM-8: no read may ever leave a connection open.

    Four layers:
      1. Bound aiobmsble's disconnect so a hung teardown can't stall the loop.
      2. Also disconnect the raw BleakClient directly. aiobmsble's disconnect
         silently swallows BleakError and has no timeout on the inner
         _client.disconnect() call (see basebms.py::disconnect); an in-flight
         BleakError can leave the client in a state that auto-reconnects the
         moment the external link drops. Calling bleak directly with our own
         timeout — even if aiobmsble already returned — is what actually
         cleans up its internal state.
      3. Verify at the controller level (`hcitool con`) because both of the
         above can lie.
      4. If the link is somehow still up, force it down via BlueZ.
    Never raises — teardown failures are logged, not propagated.
    """
    key = address.upper()
    t0 = time.monotonic()
    disconnect_error: Optional[str] = None
    inner_disconnect_error: Optional[str] = None
    try:
        await asyncio.wait_for(bms.disconnect(), timeout=_DISCONNECT_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — teardown must never raise into the loop
        disconnect_error = f"{type(exc).__name__}: {exc}"
    # Belt-and-suspenders: also call the raw BleakClient's disconnect. Idempotent
    # in bleak, but critically it clears the client's internal connection state
    # even if aiobmsble's own disconnect silently failed. Without this, the
    # leaked-client-auto-reconnects-after-external-drop path (FM-8's proven
    # failure mode) can still bite us. HARDWARE-DEP: Pi 3B / BlueZ — needed
    # while aiobmsble's disconnect swallows BleakError; on a stack where the
    # library's own disconnect is reliable, this layer becomes redundant.
    try:
        client = getattr(bms, "_client", None)
        if client is not None:
            await asyncio.wait_for(client.disconnect(), timeout=5.0)
    except Exception as exc:  # noqa: BLE001
        inner_disconnect_error = f"{type(exc).__name__}: {exc}"
    forced = False
    still_connected = False
    try:
        if await _connected_targets({key}):
            await _force_disconnect(address)
            forced = True
            still_connected = bool(await _connected_targets({key}))
    except Exception:  # noqa: BLE001 — verification/force is best-effort
        pass
    _event(
        "teardown",
        address=key,
        teardown_s=round(time.monotonic() - t0, 2),
        disconnect_error=disconnect_error,
        inner_disconnect_error=inner_disconnect_error,
        forced=forced,
        still_connected=still_connected,
    )


class DiscoveryWedgeError(RuntimeError):
    """Discovery itself failed — classically org.bluez.Error.InProgress, a stuck
    adapter-level discovery session (FM-3). Distinct from a both-batteries-absent
    read failure: this is an adapter/bluetoothd wedge that a process restart will
    NOT clear (it survives across restarts), so the logger must reset the adapter.
    """


async def _default_adapter() -> str:
    """Best-effort name of the BLE controller (e.g. 'hci0') for adapter recovery
    (`hciconfig <hci> reset`). Distinct from the scan/connect adapter selection
    in `_resolve_configured_adapter()` — this one just needs *some* live hci
    name to pass to CLI recovery tools.

    If `VOLTHIUM_ADAPTER` is set and resolved, prefer it: the recovery ladder
    should target the *actual* reader adapter, not whichever one hciconfig
    lists first. Otherwise fall through to the first hci name in `hciconfig`
    output. Ultimate fallback is `hci0`."""
    pinned = await _resolve_configured_adapter()
    if pinned:
        return pinned
    out = await _run(["hciconfig"], timeout=8.0)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("hci") and ":" in line:
            return line.split(":", 1)[0]
    return "hci0"


# --- Adapter pinning + fallback -------------------------------------------
# `VOLTHIUM_ADAPTER=<mac>` or `=<hci_name>` pins every scan and connect call
# to a specific BLE controller. This matters because bleak/BlueZ picks a
# default adapter by index (usually `hci0`) which is fragile when a machine
# has more than one — e.g. this Pi has both a built-in BCM43438 chip and a
# USB dongle (TP-Link UB500). Their `hci*` numbers even swapped between two
# reboots we observed on 2026-07-09; without pinning, a stray boot could
# route the reader to the flaky internal chip instead of the reliable dongle.
#
# The env vars accept either form:
#   VOLTHIUM_ADAPTER=20:E1:5D:68:30:8B   → resolved to whichever hci owns
#                                          that BD address right now
#   VOLTHIUM_ADAPTER=hci0                → passed straight through
#
# `VOLTHIUM_FALLBACK_ADAPTER` (same forms) names a second-choice controller
# (on the Pi: the internal BCM43438) that the reader switches to WHILE the
# primary is unusable, and automatically switches back off when the primary
# recovers. Degraded but flowing beats a 14-hour outage.
#
# Two lessons from the 2026-07-12/13 outage are baked in here:
#   1. Resolution must verify the adapter with *bluetoothd* (D-Bus), not just
#      `hciconfig` (kernel). After a kernel USB reset the chip can re-enumerate
#      in a state bluetoothd fails to initialize — the kernel lists it, bleak
#      (which talks D-Bus) throws `adapter not found` forever.
#   2. Resolution must be re-verified over time (VERIFY_TTL_S), not cached for
#      the process lifetime — hci indexes change when a dongle re-enumerates.
#
# Unset (macOS dev rig, or a single-adapter Linux box) → the scan/connect
# calls omit the `adapter` kwarg and bleak uses its per-platform default.
_ADAPTER_ENV = "VOLTHIUM_ADAPTER"
_FALLBACK_ADAPTER_ENV = "VOLTHIUM_FALLBACK_ADAPTER"
# VID:PID of the primary adapter's USB dongle, for the replug rung when the
# hci is gone entirely. Default is the TP-Link UB500.
_ADAPTER_USB_ID_ENV = "VOLTHIUM_ADAPTER_USB_ID"
_DEFAULT_ADAPTER_USB_ID = "2357:0604"


def _looks_like_mac(s: str) -> bool:
    """True for `XX:XX:XX:XX:XX:XX` or `XX-XX-XX-XX-XX-XX`, any case."""
    parts = s.replace("-", ":").split(":")
    return len(parts) == 6 and all(
        len(p) == 2 and all(c in "0123456789abcdefABCDEF" for c in p)
        for p in parts
    )


async def _hci_owning_mac(bd_addr: str) -> Optional[str]:
    """Return the hci* name whose BD address matches `bd_addr`, by parsing
    `hciconfig`. Case-insensitive. Returns None if not found (or hciconfig
    is unavailable, e.g. on macOS)."""
    target = bd_addr.replace("-", ":").upper()
    out = await _run(["hciconfig"], timeout=5.0)
    current_hci: Optional[str] = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("hci") and ":" in line:
            current_hci = line.split(":", 1)[0]
            continue
        if current_hci and line.upper().startswith("BD ADDRESS:"):
            token = line.split(":", 1)[1].strip().split()[0].upper()
            if token == target:
                return current_hci
    return None


async def _bluez_controllers() -> Optional[set[str]]:
    """BD addresses of the controllers bluetoothd exposes on D-Bus, from
    `bluetoothctl list` — bleak's actual universe of usable adapters. Returns
    None when bluetoothctl is unavailable (macOS dev rig), so callers skip
    the check rather than failing everything."""
    out = await _run(["bluetoothctl", "list"], timeout=5.0)
    if out.startswith("<cmd "):
        return None
    macs: set[str] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Controller" and _looks_like_mac(parts[1]):
            macs.add(parts[1].upper())
    return macs


class _AdapterManager:
    """Owns which BLE controller the reader is using right now.

    Responsibilities:
      - Resolve the primary pin (`VOLTHIUM_ADAPTER`) to an hci name, verified
        against BOTH the kernel (`hciconfig`) and bluetoothd (`bluetoothctl
        list`) views. Kernel-only visibility means bleak can't use it.
      - When the primary is unusable, switch to `VOLTHIUM_FALLBACK_ADAPTER`
        (powering it on if needed) so telemetry keeps flowing degraded.
      - Re-verify on a TTL and switch back to the primary automatically the
        moment it's healthy again — then return the fallback to its
        documented steady state (DOWN).
      - While on the fallback, periodically try to *repair* the primary with
        a software USB replug (`maybe_repair_primary`), rate-limited.
    """

    VERIFY_TTL_S = 60.0
    REPLUG_MIN_INTERVAL_S = 600.0

    def __init__(self) -> None:
        self.active: Optional[str] = None       # hci name in use; None = bleak default
        self.active_is_fallback = False
        # None sentinels (not 0.0): time.monotonic() is system uptime on
        # Linux, so a freshly booted Pi has small values and a 0.0 sentinel
        # would make the first minutes look "already verified/attempted".
        self._verified_at: Optional[float] = None
        self._last_replug_at: Optional[float] = None
        self._pin_fail_reported = False         # one adapter_pin_failed per streak
        self._last_emitted: Optional[tuple] = None  # (hci, is_fallback) last announced
        self._lock: Optional[asyncio.Lock] = None

    def invalidate(self) -> None:
        """Force a fresh resolution on the next call — used after any recovery
        action, because hci indexes change when a dongle re-enumerates."""
        self._verified_at = None

    def _cache_fresh(self) -> bool:
        return (
            self._verified_at is not None
            and (time.monotonic() - self._verified_at) < self.VERIFY_TTL_S
        )

    async def resolve(self) -> Optional[str]:
        raw_primary = os.environ.get(_ADAPTER_ENV, "").strip()
        if not raw_primary:
            return None  # unpinned (macOS dev rig) — bleak default
        if self._cache_fresh():
            return self.active
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._cache_fresh():
                return self.active
            return await self._resolve_locked(raw_primary)

    async def _resolve_locked(self, raw_primary: str) -> Optional[str]:
        hci, why = await self._probe(raw_primary)
        if hci is not None:
            was_fallback = self.active_is_fallback
            self.active, self.active_is_fallback = hci, False
            self._verified_at = time.monotonic()
            self._pin_fail_reported = False
            if self._last_emitted != (hci, False):
                _event(
                    "adapter_restored" if was_fallback else "adapter_pinned",
                    configured=raw_primary,
                    resolved=hci,
                    by="mac" if _looks_like_mac(raw_primary) else "name",
                )
                self._last_emitted = (hci, False)
                if was_fallback:
                    await self._power_down_fallback()
            return hci

        # Primary unusable — report once per streak, then try the fallback.
        if not self._pin_fail_reported:
            self._pin_fail_reported = True
            _event("adapter_pin_failed", configured=raw_primary, reason=why)
        raw_fb = os.environ.get(_FALLBACK_ADAPTER_ENV, "").strip()
        if raw_fb:
            fhci = await self._probe_fallback(raw_fb)
            if fhci is not None:
                self.active, self.active_is_fallback = fhci, True
                self._verified_at = time.monotonic()
                if self._last_emitted != (fhci, True):
                    _event(
                        "adapter_fallback_active",
                        configured=raw_fb,
                        resolved=fhci,
                        primary=raw_primary,
                        primary_fail_reason=why,
                        note=(
                            "reading on the fallback controller while the "
                            "primary is repaired — degraded but flowing"
                        ),
                    )
                    self._last_emitted = (fhci, True)
                return fhci

        # Nothing usable — bleak default. Cache the outcome for a TTL so we
        # don't hammer probes every read cycle while everything is broken.
        _event(
            "adapter_fallback",
            configured=raw_primary,
            pin_failed_reason=why,
            fallback_hci=None,
            fallback_bd_address=None,
            note="no configured adapter usable; bleak default until one returns",
        )
        self.active, self.active_is_fallback = None, False
        self._verified_at = time.monotonic()
        self._last_emitted = (None, False)
        return None

    async def _probe(self, raw: str) -> tuple[Optional[str], str]:
        """(hci, "") when `raw` maps to a controller both the kernel AND
        bluetoothd can see; (None, reason) otherwise."""
        if _looks_like_mac(raw):
            mac = raw.replace("-", ":").upper()
            hci = await _hci_owning_mac(mac)
            if hci is None:
                return None, "no hci with matching BD address"
            controllers = await _bluez_controllers()
            if controllers is not None and mac not in controllers:
                return None, (
                    f"kernel sees {hci} but bluetoothd does not "
                    "(D-Bus adapter object missing — bleak can't use it)"
                )
            return hci, ""
        if raw.startswith("hci"):
            out = await _run(["hciconfig", raw], timeout=5.0)
            if "no such device" in out.lower():
                return None, "no such hci device"
            return raw, ""
        return None, "not a MAC or hci name"

    async def _probe_fallback(self, raw_fb: str) -> Optional[str]:
        """Resolve the fallback controller, powering it on if it's sitting in
        its steady-state DOWN. Returns None if it's unusable too."""
        fhci, _why = await self._probe(raw_fb)
        if fhci is None:
            return None
        if not await _adapter_is_up(fhci):
            await _power_on_adapter(fhci)
            if not await _adapter_is_up(fhci):
                return None
        return fhci

    async def _power_down_fallback(self) -> None:
        """Primary is back — return the fallback controller to its documented
        steady state (DOWN) so its wedge-prone scan state can't confuse BlueZ
        (the internal chip was left UP-and-wedged after the 2026-07-12 episode)."""
        raw_fb = os.environ.get(_FALLBACK_ADAPTER_ENV, "").strip()
        if not raw_fb:
            return
        if _looks_like_mac(raw_fb):
            fhci = await _hci_owning_mac(raw_fb)
        elif raw_fb.startswith("hci"):
            fhci = raw_fb
        else:
            fhci = None
        if fhci and fhci != self.active:
            out = await _run(["sudo", "-n", "hciconfig", fhci, "down"], timeout=10.0)
            _event("fallback_powered_down", hci=fhci, output=out.strip()[:200])

    async def maybe_repair_primary(self) -> Optional[str]:
        """While surviving on the fallback, try to bring the primary back with
        a software USB replug. Rate-limited to one attempt per
        REPLUG_MIN_INTERVAL_S. Returns a description when a replug ran, None
        otherwise. Called every read cycle by the logger — cheap no-op unless
        we're actually degraded and due for an attempt."""
        if not self.active_is_fallback:
            return None
        now = time.monotonic()
        if (
            self._last_replug_at is not None
            and (now - self._last_replug_at) < self.REPLUG_MIN_INTERVAL_S
        ):
            return None
        raw = os.environ.get(_ADAPTER_ENV, "").strip()
        if not raw:
            return None
        # Cheap re-check first — bluetoothd may have recovered it on its own,
        # in which case the next resolve() switches back without a replug.
        hci, _why = await self._probe(raw)
        if hci is not None:
            self.invalidate()
            return None
        self._last_replug_at = now
        action = await replug_usb_adapter()
        self.invalidate()
        return action


_adapter_mgr = _AdapterManager()


def _reset_adapter_state_for_tests() -> _AdapterManager:
    """Swap in a fresh manager (module-level state otherwise leaks between
    tests). Returns it for direct inspection."""
    global _adapter_mgr
    _adapter_mgr = _AdapterManager()
    return _adapter_mgr


async def _resolve_configured_adapter() -> Optional[str]:
    """The adapter the reader should use right now (primary, fallback, or
    None for bleak's default). Kept as a thin wrapper — callers predate the
    manager."""
    return await _adapter_mgr.resolve()


async def maybe_repair_primary() -> Optional[str]:
    """Module-level convenience for the logger loop — see
    _AdapterManager.maybe_repair_primary."""
    return await _adapter_mgr.maybe_repair_primary()


async def _adapter_kwargs() -> dict:
    """kwargs to splat into bleak scan/connect calls. `{"adapter": "hciN"}`
    when a configured adapter resolved; `{}` otherwise (bleak picks its
    per-platform default — the right thing on macOS)."""
    adapter = await _resolve_configured_adapter()
    return {"adapter": adapter} if adapter else {}


async def _adapter_is_up(hci: str) -> bool:
    """True iff the adapter appears in `hciconfig <hci>` and is not marked
    `DOWN`. Best-effort; a parse failure returns False so we err on the side
    of trying to power it up."""
    out = (await _run(["hciconfig", hci], timeout=5.0)).upper()
    if "NO SUCH DEVICE" in out or hci.upper() not in out:
        return False
    # `DOWN` appears in the status line for a powered-off adapter, `UP` for on.
    if "DOWN" in out:
        return False
    return "UP" in out


async def _power_on_adapter(hci: str) -> str:
    """Bring the adapter up + power it via bluetoothctl. Called after level 1
    or level 2 recovery leaves the controller unpowered — we saw this happen
    live on 2026-07-01 after `systemctl restart bluetooth`.

    Two-step because they cover different failure modes:
      - `hciconfig <hci> up` clears controller-level DOWN state (kernel side)
      - `bluetoothctl power on` sets bluetoothd's managed power flag

    Best-effort; never raises; logs the outcome.
    """
    hci_out = (await _run(["sudo", "-n", "hciconfig", hci, "up"], timeout=15.0)).strip()
    await asyncio.sleep(1.0)
    bt_out = (await _run(["sudo", "-n", "bluetoothctl", "power", "on"], timeout=15.0)).strip()
    _event(
        "adapter_power_on",
        hci=hci,
        hciconfig_up=hci_out[:200],
        bluetoothctl_power=bt_out[:200],
    )
    return f"hciconfig {hci} up; bluetoothctl power on"


# --- USB replug (recovery ladder Level 3) -----------------------------------
# The 2026-07-12/13 outage proved a failure mode no HCI reset or bluetoothd
# restart can fix: the dongle's firmware hangs, the kernel USB-resets it, and
# it re-enumerates in a state bluetoothd can't initialize ("Failed to set
# privacy: Rejected (0x0b)") — kernel-visible, D-Bus-invisible, dead to bleak.
# The only remote cure is a full USB re-enumeration with a fresh firmware
# load, which sysfs `authorized` 0→1 provides (a software unplug/replug).
# Verified live 2026-07-13: readings resumed within seconds.
#
# Scoped strictly to the adapter's own USB device dir — never a hub or any
# other device — so it cannot affect connectivity (the Pi's network is on
# wlan0, not USB, but we don't rely on that).


def _usb_device_dir_for_hci(
    hci: str, base: Path = Path("/sys/class/bluetooth")
) -> Optional[Path]:
    """sysfs USB *device* dir (e.g. .../1-1.5) for a USB-attached hci, by
    following /sys/class/bluetooth/<hci>/device → the USB interface, whose
    parent is the device. None for non-USB adapters or on any error."""
    try:
        real = (base / hci / "device").resolve()
    except OSError:
        return None
    dev = real.parent
    return dev if (dev / "authorized").is_file() else None


def _usb_device_dir_by_id(
    usb_id: str, base: Path = Path("/sys/bus/usb/devices")
) -> Optional[Path]:
    """sysfs USB device dir matching `vid:pid` — the fallback lookup for when
    the dongle is on the bus but its hci is gone entirely."""
    try:
        vid, pid = usb_id.lower().split(":")
    except ValueError:
        return None
    try:
        candidates = list(base.iterdir())
    except OSError:
        return None
    for d in candidates:
        try:
            if (
                (d / "idVendor").read_text().strip().lower() == vid
                and (d / "idProduct").read_text().strip().lower() == pid
                and (d / "authorized").is_file()
            ):
                return d
        except OSError:
            continue
    return None


async def _find_replug_target() -> Optional[Path]:
    """Locate the primary adapter's USB device dir. Prefer following the hci's
    own sysfs link (exact, works when bluetoothd lost the adapter); fall back
    to a VID:PID scan (works when even the hci is gone)."""
    raw = os.environ.get(_ADAPTER_ENV, "").strip()
    if _looks_like_mac(raw):
        hci = await _hci_owning_mac(raw)
        if hci:
            d = _usb_device_dir_for_hci(hci)
            if d is not None:
                return d
    elif raw.startswith("hci"):
        d = _usb_device_dir_for_hci(raw)
        if d is not None:
            return d
    usb_id = os.environ.get(_ADAPTER_USB_ID_ENV, _DEFAULT_ADAPTER_USB_ID)
    return _usb_device_dir_by_id(usb_id)


async def replug_usb_adapter() -> str:
    """Software unplug/replug of the primary USB BLE adapter via its sysfs
    `authorized` toggle — full re-enumeration + fresh firmware load, same
    effect as physically reseating the dongle. Best-effort; never raises;
    emits a `usb_replug` event with the before/after evidence."""
    target = await _find_replug_target()
    if target is None:
        _event(
            "usb_replug",
            ok=False,
            note="no USB device dir found for the primary adapter — "
            "not a USB dongle, or it fell off the bus entirely",
        )
        return "usb replug skipped (no sysfs target)"
    auth = target / "authorized"
    before = await _run(["hciconfig"], timeout=5.0)
    out0 = await _run(["sudo", "-n", "sh", "-c", f"echo 0 > {auth}"], timeout=10.0)
    await asyncio.sleep(2.0)
    out1 = await _run(["sudo", "-n", "sh", "-c", f"echo 1 > {auth}"], timeout=10.0)
    # Re-enumeration + RTL firmware download takes a few seconds; give
    # bluetoothd a moment to register the new controller too.
    await asyncio.sleep(6.0)
    after = await _run(["hciconfig"], timeout=5.0)
    _event(
        "usb_replug",
        ok=True,
        usb_dev=target.name,
        deauthorize=out0.strip()[:150],
        reauthorize=out1.strip()[:150],
        hciconfig_before=before.strip()[:400],
        hciconfig_after=after.strip()[:400],
    )
    _adapter_mgr.invalidate()
    return f"usb replug of {target.name} (authorized 0→1)"


async def _dmesg_bt_tail(since: str = "5min", limit: int = 40) -> list[str]:
    """Kernel-log tail filtered to lines relevant to a BLE / USB wedge.
    Widened beyond just BT/hci to also catch USB bus events, hub errors,
    power/current spikes, and thermal warnings — any of these can be the
    proximate cause of a chip firmware hang.

    `journalctl -k` is readable without sudo on Ubuntu; falls back to
    `sudo -n dmesg` if not. Best-effort — returns [] on any failure so
    callers get an empty snapshot, not an exception."""
    interesting = (
        "Bluetooth:", "hci0", "hci1", "hci2",
        "usb ", "Resetting usb", "Frame reassembly",
        "reset full-speed", "reset high-speed",
        "over-current", "over-voltage", "under-voltage", "power budget",
        "thermal", "throttl", "hub_port_status",
        "btusb", "brcm",
    )
    for cmd in (
        ["journalctl", "-k", "-q", "--no-pager", f"--since={since} ago"],
        ["sudo", "-n", "dmesg", "-T", "--nopager"],
    ):
        try:
            out = await _run(cmd, timeout=3.0)
        except Exception:
            continue
        if not out or "not found" in out.lower() and cmd[0] != "sudo":
            continue
        lines = [ln for ln in out.splitlines()
                 if any(tok in ln for tok in interesting)]
        if lines:
            return lines[-limit:]
        # Empty match but command worked — return [] rather than trying next
        if out.strip():
            return []
    return []


async def _hciconfig_snapshot(hci: str) -> dict:
    """Adapter state right now: up/down, powered address, RX/TX counters.
    Blank BD address (00:00:00:00:00:00) or DOWN state is a strong signal
    the chip is not communicating."""
    try:
        out = await _run(["hciconfig", hci], timeout=2.5)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if not out.strip():
        return {"error": "empty hciconfig output"}
    up = "UP RUNNING" in out.upper()
    down = "DOWN" in out.upper() and not up
    bd = ""
    for ln in out.splitlines():
        s = ln.strip()
        if s.upper().startswith("BD ADDRESS:"):
            bd = s.split(":", 1)[1].strip().split()[0]
            break
    return {
        "up": up,
        "down": down,
        "bd_address": bd,
        "bd_null": bd == "00:00:00:00:00:00",
        "raw": out.strip()[:500],
    }


async def _bluetoothctl_snapshot() -> str:
    """`bluetoothctl show` — Powered/Discovering/UUIDs of the default
    controller. `Discovering: yes` while the reader thinks it's not scanning
    is the classic BlueZ-state-stuck (FM-3) fingerprint."""
    try:
        out = await _run(["bluetoothctl", "show"], timeout=3.0)
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"
    return out.strip()[:800]


async def _lsusb_ub500() -> Optional[bool]:
    """True if the UB500 (VID 2357, PID 0604) is currently on the USB bus,
    False if not, None if lsusb failed. Chip-firmware-hang and dongle-fell-off
    look identical up-stack — this splits them apart."""
    try:
        out = await _run(["lsusb", "-d", "2357:0604"], timeout=2.0)
    except Exception:
        return None
    return bool(out.strip())


async def _power_and_thermal() -> dict:
    """Sample the Pi's throttled register and SoC temperature. The throttled
    register is a bit-mask that latches under-voltage / freq-cap / temp-cap
    events — an exact source-of-truth "did the PSU sag?" answer that we can't
    get from dmesg alone. Non-zero on a wedge is diagnostic gold: it says the
    USB dongle was probably brownout-hung, not firmware-hung."""
    out = {"throttled_hex": None, "throttled_flags": [], "soc_temp_c": None}
    try:
        raw = (await _run(["vcgencmd", "get_throttled"], timeout=2.0)).strip()
        if "=" in raw:
            hexv = raw.split("=", 1)[1].strip()
            out["throttled_hex"] = hexv
            try:
                bits = int(hexv, 16)
            except ValueError:
                bits = 0
            # Per Pi documentation:
            #   bit  0: under-voltage detected NOW
            #   bit  1: arm freq capped NOW
            #   bit  2: currently throttled
            #   bit  3: soft temp limit active NOW
            #   bit 16: under-voltage has occurred since boot
            #   bit 17: arm freq cap has occurred since boot
            #   bit 18: throttling has occurred since boot
            #   bit 19: soft temp limit has occurred since boot
            flag_names = {
                0: "under_voltage_now",
                1: "freq_capped_now",
                2: "throttled_now",
                3: "soft_temp_limit_now",
                16: "under_voltage_since_boot",
                17: "freq_capped_since_boot",
                18: "throttled_since_boot",
                19: "soft_temp_limit_since_boot",
            }
            out["throttled_flags"] = [
                n for b, n in flag_names.items() if bits & (1 << b)
            ]
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            out["soc_temp_c"] = int(f.read().strip()) / 1000.0
    except Exception:
        pass
    return out


def _classify_wedge(
    reason: str,
    dmesg: list[str],
    hci_state: dict,
    bctl: str,
    ub500_present: Optional[bool],
    pinned_in_kernel: Optional[str] = None,
    pinned_in_bluez: Optional[bool] = None,
) -> str:
    """Heuristic layer label for the wedge. The raw fields are the source of
    truth; this string is a triage shortcut for the runbook and dashboards.

    Order matters — most specific evidence first, so a chip hang that also
    causes a "not found" up-stack still classifies as chip-layer."""
    dm = "\n".join(dmesg)
    if "Resetting usb device" in dm or "reset full-speed" in dm:
        return "kernel_usb_reset_chip_hung"
    if "tx timeout" in dm or "Frame reassembly failed" in dm:
        return "chip_firmware_hci_unresponsive"
    if ub500_present is False:
        return "ub500_dongle_missing_from_usb"
    # Direct kernel-vs-D-Bus comparison — the 2026-07-12/13 signature: the
    # kernel lists the pinned adapter but bluetoothd never initialized it, so
    # bleak throws `adapter not found` while hciconfig looks perfectly healthy.
    # Cured by a USB replug (recovery Level 3), not by HCI/bluetoothd resets.
    if pinned_in_kernel and pinned_in_bluez is False:
        return "bluez_adapter_object_missing"
    if hci_state.get("bd_null") or (hci_state.get("down") and not hci_state.get("up")):
        return "adapter_down_or_bd_null"
    if "Discovering: yes" in bctl:
        return "bluez_discovery_state_stuck"
    if "InProgress" in reason or "org.bluez.Error.InProgress" in reason:
        return "bluez_discovery_state_stuck"
    if "adapter" in reason.lower() and "not found" in reason.lower():
        return "bluez_adapter_object_missing"
    if "TimeoutError" in reason and hci_state.get("up") and ub500_present:
        return "bms_peer_not_responding"
    return "unclassified"


async def _collect_stack_evidence(reason: str) -> dict:
    """Fan out to every layer's state probe in parallel and return one
    normalized evidence dict. Shared by wedge and health snapshots so they
    speak identical JSON — analysis tooling can treat both event kinds the
    same way and just look at the `event` field to know why it fired."""
    hci = await _default_adapter()
    dmesg, hci_state, bctl, ub500, hcicon, ptherm, bluez_macs = await asyncio.gather(
        _dmesg_bt_tail(),
        _hciconfig_snapshot(hci),
        _bluetoothctl_snapshot(),
        _lsusb_ub500(),
        _run(["hcitool", "con"], timeout=2.0),
        _power_and_thermal(),
        _bluez_controllers(),
        return_exceptions=True,
    )
    dmesg = dmesg if isinstance(dmesg, list) else []
    hci_state = hci_state if isinstance(hci_state, dict) else {"error": str(hci_state)}
    bctl = bctl if isinstance(bctl, str) else str(bctl)
    hcicon = hcicon if isinstance(hcicon, str) else str(hcicon)
    ptherm = ptherm if isinstance(ptherm, dict) else {}
    bluez_macs = bluez_macs if isinstance(bluez_macs, (set, type(None))) else None
    # Kernel-vs-D-Bus comparison for the pinned adapter (see _classify_wedge).
    pinned_raw = os.environ.get(_ADAPTER_ENV, "").strip()
    pinned_in_kernel: Optional[str] = None
    pinned_in_bluez: Optional[bool] = None
    if _looks_like_mac(pinned_raw):
        mac = pinned_raw.replace("-", ":").upper()
        try:
            pinned_in_kernel = await _hci_owning_mac(mac)
        except Exception:
            pinned_in_kernel = None
        if bluez_macs is not None:
            pinned_in_bluez = mac in bluez_macs
    classification = _classify_wedge(
        reason, dmesg, hci_state, bctl, ub500,
        pinned_in_kernel=pinned_in_kernel,
        pinned_in_bluez=pinned_in_bluez,
    )
    # If Pi throttling is currently active, upgrade the classification —
    # any recent under-voltage strongly implies the chip hang was electrical,
    # not firmware. Preserve the original label as a hint field.
    thermal_hint: Optional[str] = None
    if ptherm.get("throttled_flags"):
        if "under_voltage_now" in ptherm["throttled_flags"]:
            thermal_hint = classification
            classification = "power_under_voltage_active"
        elif any(f.endswith("_since_boot") for f in ptherm["throttled_flags"]):
            thermal_hint = "throttling_history_present"
    return {
        "reason": reason[:400],
        "classification": classification,
        "classification_notes": thermal_hint,
        "hci": hci,
        "dmesg_bt_tail": dmesg,
        "hciconfig": hci_state,
        "bluetoothctl_show": bctl,
        "ub500_present": ub500,
        "hcitool_con": hcicon.strip()[:500],
        "power_thermal": ptherm,
        "bluez_controllers": sorted(bluez_macs) if bluez_macs is not None else None,
        "pinned_adapter": pinned_raw or None,
        "pinned_in_kernel": pinned_in_kernel,
        "pinned_in_bluez": pinned_in_bluez,
        "active_adapter": _adapter_mgr.active,
        "on_fallback_adapter": _adapter_mgr.active_is_fallback,
    }


async def snapshot_stack(reason: str, level: int) -> None:
    """Gather every layer's state at the moment of a wedge and emit one
    `wedge_snapshot` event containing all of it. Called from every code path
    where the reader gives up on a read cycle — the recovery ladder rungs AND
    the "neither battery found" streak — so nothing that hurts operational
    data quality goes undiagnosed.

    All probes run in parallel with tight timeouts so the snapshot itself
    can't stall the loop for more than ~3 s in the worst case."""
    evidence = await _collect_stack_evidence(reason)
    _event("wedge_snapshot", recovery_level=level, **evidence)


async def emit_stack_health(reason: str = "periodic") -> None:
    """Emit a `stack_health` event with the same evidence a wedge would
    capture. Fires on a slow cadence (~every 5 min) whether or not anything
    is wrong — the point is to establish a baseline so a future incident
    has "healthy state" to diff against, and so under-voltage becomes
    visible the moment it starts rather than only when it breaks reads."""
    evidence = await _collect_stack_evidence(reason)
    _event("stack_health", **evidence)


async def recover_adapter(level: int) -> str:
    """Escalating adapter recovery for a stuck discovery (FM-3/FM-9) that a
    process restart can't fix.
      level 1 — HCI controller reset (clears a wedged discovery session, fast)
      level 2 — full bluetooth.service restart (the proven heavy hammer —
                verified to clear `Discovering: yes` on 2026-06-30)
      level 3 — software USB replug of the primary dongle (full re-enumeration
                + firmware reload; the only remote cure when the chip came
                back from a kernel USB reset in a state bluetoothd can't
                initialize — the 2026-07-12/13 outage)
    Uses passwordless sudo. Best-effort; logs a structured event; never raises.

    Levels 1-2 can leave the adapter powered off (observed live 2026-07-01
    after a level 2 recovery — the logger then loops on "No powered Bluetooth
    adapters found" until manual intervention). To close that gap the recovery
    verifies the adapter is up afterward and calls `hciconfig <hci> up +
    bluetoothctl power on` if not. Level 3 changes the hci index, so it skips
    that check and instead invalidates the adapter cache (all levels do).

    HARDWARE-DEP: BlueZ / RTL8761B — the entire adapter-recovery ladder exists
    because this platform's BT stack periodically wedges at some layer. On a
    healthier stack this function shouldn't need to exist; when we swap
    hardware, this whole function and its callers in scripts/log.py can go.
    """
    if level >= 3:
        action = await replug_usb_adapter()
        _event("adapter_recovery", level=level, action=action, output="")
        return action
    hci = await _default_adapter()
    if level <= 1:
        action = f"hciconfig {hci} reset"
        out = await _run(["sudo", "-n", "hciconfig", hci, "reset"], timeout=20.0)
        await asyncio.sleep(2.0)  # let the controller re-init before next scan
    else:
        action = "systemctl restart bluetooth"
        out = await _run(
            ["sudo", "-n", "systemctl", "restart", "bluetooth"], timeout=30.0
        )
        await asyncio.sleep(5.0)  # bluetoothd + adapter need a moment to come back
    _event("adapter_recovery", level=level, action=action, output=out.strip()[:500])
    # Verify the adapter came back powered. If not, explicitly bring it up —
    # this is the FM-3 gap we just closed after the 2026-07-01 incident.
    if not await _adapter_is_up(hci):
        power_action = await _power_on_adapter(hci)
        action = f"{action}; {power_action}"
    # hci indexes and D-Bus registration can change under any recovery — make
    # the next read cycle re-resolve rather than trusting a stale pin.
    _adapter_mgr.invalidate()
    return action


@dataclass
class BatteryReading:
    """One battery's snapshot. None on any field means the BMS didn't send it."""
    address: str
    name: str
    voltage: Optional[float]          # V (sum of cell voltages)
    current: Optional[float]          # A (positive = charging)
    soc: Optional[float]              # %
    remaining_ah: Optional[float]     # Ah remaining (from cycle_charge)
    temperature: Optional[float]      # °C
    cycles: Optional[int]
    cell_voltages: Optional[list[float]]
    delta_voltage: Optional[float]    # max - min cell V
    charging_fet: Optional[bool]
    discharging_fet: Optional[bool]
    problem_code: Optional[int]

    @property
    def label(self) -> str:
        """Glanceable battery ID — last two digits of the BMS serial.

        'V-12V200AH-0533' → '33', 'V-12V200AH-0667' → '67'. Falls back to
        last 4 chars of the BLE address if the name isn't structured as
        expected.
        """
        if self.name and "-" in self.name:
            tail = self.name.rsplit("-", 1)[1]
            if tail and tail[-2:].isdigit():
                return tail[-2:]
        return self.address[-4:] if self.address else "??"

    @classmethod
    def from_sample(cls, address: str, name: str, s: BMSSample) -> "BatteryReading":
        return cls(
            address=address,
            name=name,
            voltage=s.get("voltage"),
            current=s.get("current"),
            soc=s.get("battery_level"),
            remaining_ah=s.get("cycle_charge"),
            temperature=(s["temp_values"][0] if s.get("temp_values") else None),
            cycles=s.get("cycles"),
            cell_voltages=s.get("cell_voltages"),
            delta_voltage=s.get("delta_voltage"),
            charging_fet=s.get("chrg_mosfet"),
            discharging_fet=s.get("dischrg_mosfet"),
            problem_code=s.get("problem_code"),
        )


@dataclass
class PackReading:
    """Combined view of two batteries in series.

    In a series pack the same current flows through both batteries, but each
    cell-group can drift in SOC. For runtime estimation the worst battery
    bounds the pack:
      - charging is finished when the FIRST battery hits 100%
      - discharging is finished when the FIRST battery hits the floor SOC
    """
    a: BatteryReading
    b: BatteryReading
    # Addresses detected wedged this cycle: absent from discovery but still
    # holding a controller connection (leaked-link signature). The logger uses
    # this to escalate to a self-restart — the proven cure — when a force-
    # disconnect won't free an in-process leaked client.
    wedged: list[str] = field(default_factory=list)

    @property
    def pack_voltage(self) -> Optional[float]:
        if self.a.voltage is None or self.b.voltage is None:
            return None
        return self.a.voltage + self.b.voltage

    @property
    def pack_current(self) -> Optional[float]:
        # Series → same current. Average to suppress per-BMS noise.
        vals = [x for x in (self.a.current, self.b.current) if x is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def pack_power(self) -> Optional[float]:
        if self.pack_voltage is None or self.pack_current is None:
            return None
        return self.pack_voltage * self.pack_current

    @property
    def avg_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def min_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return min(vals) if vals else None

    @property
    def max_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return max(vals) if vals else None


async def discover_volthium(timeout: float = 8.0) -> list[tuple[BLEDevice, str]]:
    """Return [(BLEDevice, advertised_name)] for every Volthium battery in range."""
    found: dict[str, tuple[BLEDevice, str]] = {}

    def cb(dev: BLEDevice, adv) -> None:
        name = adv.local_name or dev.name or ""
        if name.startswith(ADV_NAME_PREFIX):
            found[dev.address] = (dev, name)

    scanner = BleakScanner(detection_callback=cb, **(await _adapter_kwargs()))
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    return list(found.values())


async def _read_device(dev: BLEDevice, address: str) -> BatteryReading:
    """Connect to an already-discovered device, read one sample, and ALWAYS
    release the link (bounded + verified — see _teardown / FM-8).

    Uses explicit lifecycle rather than `async with`: the context manager's
    __aexit__ disconnect is unbounded and swallows errors, so a hung/failed
    teardown there leaks the client and wedges the BMS. Here the read is
    time-bounded and teardown runs in `finally` no matter how the read exits
    (success, error, or timeout cancellation).
    """
    key = address.upper()
    t0 = time.monotonic()
    # keep_alive=True so async_update() leaves the link open and WE own teardown.
    # keep_alive=True is a workaround for aiobmsble's unbounded disconnect()
    # path — the swallowed-BleakError bug is upstream, not tied to the BT
    # stack. Now on the UB500 (2026-07-09) but the aiobmsble teardown quirk
    # persists, so we still own the disconnect explicitly.
    bms = _make_bms(dev, address, keep_alive=True)
    read_s: Optional[float] = None
    try:
        sample = await asyncio.wait_for(bms.async_update(), timeout=_READ_TIMEOUT)
        read_s = round(time.monotonic() - t0, 2)
    except Exception as exc:  # noqa: BLE001 — re-raised; logged with timing for triage
        _event(
            "read_exception",
            address=key,
            error_type=type(exc).__name__,
            error_str=str(exc),
            elapsed_s=round(time.monotonic() - t0, 2),
        )
        raise
    finally:
        await _teardown(bms, address)
    name = dev.name or ""
    reading = BatteryReading.from_sample(address, name, sample)
    _event(
        "read_ok",
        address=key,
        read_s=read_s,
        total_s=round(time.monotonic() - t0, 2),
        voltage=reading.voltage,
        current=reading.current,
        soc=reading.soc,
        temp=reading.temperature,
        problem_code=reading.problem_code,
    )
    return reading


async def read_battery(address: str, *, timeout: float = 20.0) -> BatteryReading:
    """Connect to one battery by address, read one sample, disconnect."""
    dev = await BleakScanner.find_device_by_address(
        address, timeout=timeout, **(await _adapter_kwargs())
    )
    if dev is None:
        raise RuntimeError(f"battery {address} not found in scan")
    return await _read_device(dev, address)


async def _discover_addresses(
    addresses: set[str], *, timeout: float = 20.0
) -> dict[str, BLEDevice]:
    """Resolve several addresses to BLEDevices in a *single* discovery scan.

    BlueZ permits only one discovery session per adapter, so two concurrent
    `find_device_by_address` scans collide with org.bluez.Error.InProgress
    (CoreBluetooth tolerates it, which is why this only bites on Linux/Pi).
    One shared scan sidesteps that and returns as soon as every target is
    seen, rather than waiting the full timeout.
    """
    wanted = {a.upper() for a in addresses}
    found: dict[str, BLEDevice] = {}
    rssi: dict[str, int] = {}
    names: dict[str, str] = {}
    packets: dict[str, int] = {}
    done = asyncio.Event()
    t0 = time.monotonic()

    def cb(dev: BLEDevice, adv) -> None:
        key = dev.address.upper()
        if key not in wanted:
            return
        # Track RSSI/adv-name/packet-count every time we hear this battery — the
        # RSSI trend leading into a dropout distinguishes a link-budget fade
        # (signal sags toward the floor) from a clean wedge (cuts out at strong
        # signal). adv.rssi is the per-advertisement value (dev.rssi is deprecated).
        rssi[key] = getattr(adv, "rssi", None)
        nm = (getattr(adv, "local_name", None) or dev.name or "")
        if nm:
            names[key] = nm
        packets[key] = packets.get(key, 0) + 1
        if key not in found:
            found[key] = dev
            if wanted <= set(found):
                done.set()

    scanner = BleakScanner(detection_callback=cb, **(await _adapter_kwargs()))
    await scanner.start()
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await scanner.stop()
    scan_s = round(time.monotonic() - t0, 2)
    for key in sorted(wanted):
        _event(
            "scan_result",
            address=key,
            seen=key in found,
            rssi=rssi.get(key),
            adv_name=names.get(key),
            adv_packets=packets.get(key, 0),
            scan_s=scan_s,
        )
    return found


def _missing_reading(address: str) -> BatteryReading:
    """Placeholder for a battery that wasn't found / couldn't be read this
    cycle. All telemetry fields are None, so PackReading's properties treat it
    as absent and the CSV/wire/cloud/dashboard render it blank (a dash)."""
    return BatteryReading(
        address=address, name="", voltage=None, current=None, soc=None,
        remaining_ah=None, temperature=None, cycles=None, cell_voltages=None,
        delta_voltage=None, charging_fet=None, discharging_fet=None,
        problem_code=None,
    )


async def read_pack(addr_a: str, addr_b: str, *, timeout: float = 20.0) -> PackReading:
    """Read both batteries, tolerating a single-battery dropout.

    A single shared discovery resolves both addresses (BlueZ allows only one
    discovery per adapter, so we can't scan for each battery concurrently),
    then the present batteries are read sequentially on the one radio. A missing
    or unreadable battery becomes an all-None placeholder so the *other*
    battery's telemetry still flows to the CSV/cloud/dashboard — PackReading's
    properties are null-safe, and for a series pack the present battery's current
    is the pack current. Raises only if NEITHER battery can be read, so the
    logger still treats a total blackout as a failed cycle (no empty row).
    """
    global _capture_pack_cycles
    # Snapshot the cycle-cap boundary BEFORE reads run — the reads themselves
    # bump _writer through raw_frame events, but we only advance the pack-cycle
    # counter once per read_pack call so the cap counts pack cycles, not batteries.
    capture_was_active = _capture_active()
    try:
        devs = await _discover_addresses({addr_a, addr_b}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — log then re-raise; keeps FM-3 self-diagnosing
        # A discovery that throws (classically org.bluez.Error.InProgress — a
        # stuck adapter-level discovery session, FM-3) never reaches the per-
        # cycle events below, so record it here. Note this is an adapter/bluetoothd
        # wedge, NOT the connection-leak wedge (FM-8): a process restart won't
        # clear it — it needs an adapter reset (the watchdog's job).
        _event(
            "scan_error",
            error_type=type(exc).__name__,
            error_str=str(exc),
            note="discovery failed (likely stuck adapter discovery, FM-3 — "
            "needs adapter reset, not a process restart)",
        )
        raise DiscoveryWedgeError(f"{type(exc).__name__}: {exc}") from exc
    readings: dict[str, Optional[BatteryReading]] = {}
    for addr in (addr_a, addr_b):
        dev = devs.get(addr.upper())
        if dev is None:
            readings[addr] = None
            continue
        try:
            readings[addr] = await _read_device(dev, addr)
        except Exception as exc:  # noqa: BLE001 — one battery's failure must not sink the other
            _event(
                "read_fail",
                address=addr.upper(),
                error_type=type(exc).__name__,
                error_str=str(exc),
                error_repr=repr(exc),
            )
            readings[addr] = None

    # Wedge detection + leak backstop. Any battery we did NOT read this cycle
    # but that the controller still holds a connection to is wedged: a leaked /
    # half-open link is pinning its single-connection BMS so it can't advertise
    # (the proven FM-8 failure). Record the raw evidence, try to free its radio,
    # and surface the address so the logger can escalate to a self-restart (the
    # cure we verified) if a force-disconnect won't shake an in-process leak.
    unread = {addr_a.upper(), addr_b.upper()} - {
        addr.upper() for addr, r in readings.items() if r is not None
    }
    wedged: list[str] = []
    if unread:
        connected = await _connected_targets(unread)
        if connected:
            evidence = (await _run(["hcitool", "con"])).strip()
            for addr in sorted(connected):
                wedged.append(addr)
                _event(
                    "wedge_detected",
                    address=addr,
                    note="absent from discovery but controller still connected "
                    "— leaked link pinning the BMS radio (FM-8)",
                    hcitool_con=evidence,
                )
                result = await _force_disconnect(addr)
                _event("force_disconnect", address=addr, result=result)

    # Advance the raw-capture pack-cycle counter (once per read_pack call, not
    # per battery). Emit a boundary marker on the cycle that flips capture off
    # so a downstream consumer can find the end of the sample stream cleanly.
    if capture_was_active:
        _capture_pack_cycles += 1
        if _capture_pack_cycles >= _CAPTURE_CYCLE_CAP:
            _event(
                "raw_capture_exhausted",
                cycles_captured=_capture_pack_cycles,
                cap=_CAPTURE_CYCLE_CAP,
                note="raw capture disabled until next process restart",
            )

    if readings[addr_a] is None and readings[addr_b] is None:
        _event("cycle_done", outcome="both_down", wedged=wedged)
        raise RuntimeError(f"neither battery found in scan (a={addr_a} b={addr_b})")
    _event(
        "cycle_done",
        outcome="ok" if (readings[addr_a] and readings[addr_b]) else "partial",
        a_read=readings[addr_a] is not None,
        b_read=readings[addr_b] is not None,
        wedged=wedged,
    )
    return PackReading(
        a=readings[addr_a] or _missing_reading(addr_a),
        b=readings[addr_b] or _missing_reading(addr_b),
        wedged=wedged,
    )
