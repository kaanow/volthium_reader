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
# HARDWARE-DEP: Pi 3B — default path is a tmpfs (/run/volthium/) because the
# on-board SU16G SD card can't sustain the write rate. On faster storage
# (USB SSD / NVMe / a newer Pi with proper block-layer perf), setting
# VOLTHIUM_BLE_EVENT_LOG to a real disk path would be safe and free us
# from the rotation-and-upload pipeline for smaller footprints.
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
        if self._next_seq is None:
            self._next_seq = self._discover_next_seq()
        # If we're opening onto an already-oversized live file (e.g. previous
        # process died before it could rotate), seal it right away.
        if self._size >= self.max_segment_bytes:
            self._rotate()

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
    the new writer so tests can also close/inspect it explicitly."""
    global _writer
    _writer = _EventLogWriter(path)
    return _writer


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
# building an offline BMS simulator. Toggle on/off via systemd env-var; new
# 30-cycle window on every process restart.
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
# HARDWARE-DEP: Pi 3B — these are conservative because the on-board BCM43438
# combo chip's HCI transport drops frames under Wi-Fi coexistence pressure
# (dozens of `Frame reassembly failed (-84)` in dmesg per bad session). With a
# dedicated USB BLE dongle these could tighten to ~5 s and ~3 s respectively.
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
    """Best-effort name of the BLE controller (e.g. 'hci0'). Falls back to hci0,
    the Raspberry Pi onboard adapter."""
    out = await _run(["hciconfig"], timeout=8.0)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("hci") and ":" in line:
            return line.split(":", 1)[0]
    return "hci0"


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


async def recover_adapter(level: int) -> str:
    """Escalating adapter recovery for a stuck discovery (FM-3) that a process
    restart can't fix. level 1 = HCI controller reset (clears the wedged
    discovery session, fast); level >= 2 = full bluetooth.service restart (the
    proven heavy hammer — verified to clear `Discovering: yes` on 2026-06-30).
    Uses passwordless sudo. Best-effort; logs a structured event; never raises.

    Both recovery paths can leave the adapter powered off (observed live
    2026-07-01 after a level 2 recovery — the logger then loops on
    "No powered Bluetooth adapters found" until manual intervention). To
    close that gap the recovery now verifies the adapter is up afterward
    and calls `hciconfig <hci> up + bluetoothctl power on` if not.

    HARDWARE-DEP: Pi 3B / BlueZ — the entire adapter-recovery ladder exists
    because bluetoothd on this platform periodically gets stuck in
    `Discovering: yes` and refuses new sessions. On a healthier stack this
    function shouldn't need to exist; when we swap hardware, this whole
    function and its callers in scripts/log.py can go.
    """
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

    scanner = BleakScanner(detection_callback=cb)
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
    # HARDWARE-DEP: Pi 3B — keep_alive=True is a workaround for aiobmsble's
    # unbounded disconnect() path. With a healthier BT stack and dedicated USB
    # dongle we could let the context manager handle teardown normally.
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
    dev = await BleakScanner.find_device_by_address(address, timeout=timeout)
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

    scanner = BleakScanner(detection_callback=cb)
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
