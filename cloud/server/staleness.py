"""Staleness monitor — fires a webhook when a source's telemetry goes stale
and again when it recovers.

Also hosts the EventAlertMonitor, which watches `ble_events` for specific
event kinds emitted by the reader (adapter_pin_failed, wedge_snapshot) and
fires the same webhook when they cross a "worth paging on" threshold.

Background tasks started from the FastAPI lifespan. Poll the DAO on a fixed
interval (default 60 s) and diff against in-memory state so we only alert
on transitions, not every check.

Webhook payload is JSON with `title` / `message` / `priority` / `tags`
fields chosen to be directly ntfy.sh-compatible (POST to https://ntfy.sh/<topic>
with these fields "just works"). For other services (Discord, Slack, Pushover),
put a simple relay in front.

Env vars (all optional; alerting disabled unless webhook_url is set):
  STALENESS_WEBHOOK_URL      — HTTP endpoint to POST alerts to
  STALENESS_THRESHOLD_S      — how old before "stale" (default 300)
  STALENESS_CHECK_INTERVAL_S — how often to check (default 60)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

import httpx


log = logging.getLogger("volthium-staleness")


class _RecentSourcesDAO(Protocol):
    """Subset of ReadingsDAO that the staleness monitor uses. Explicit so
    tests can inject a minimal fake without pulling in the whole DAO."""

    async def sources(self) -> list[str]: ...

    async def recent(self, source_id: Optional[str], limit: int) -> list[dict]: ...


def _parse_ts(v) -> Optional[datetime]:
    """Accept either a tz-aware datetime or an ISO-8601 string. Return
    None on anything unparseable — never raises into the check loop."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else None
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# One-line operator hints per wedge classification — the mini-runbook that
# rides inside the stale push so a non-SSH reader of the alert knows what's
# going on and how urgent it is. Keep these short: ntfy renders them on a
# phone lock screen.
_CLASSIFICATION_HINTS = {
    "kernel_usb_reset_chip_hung": (
        "USB dongle firmware hung and the kernel reset it. The reader "
        "auto-replugs it (recovery L3); if this repeats, the dongle may be "
        "failing."
    ),
    "chip_firmware_hci_unresponsive": (
        "Dongle firmware unresponsive — reader will escalate to a USB "
        "replug on its own."
    ),
    "adapter_rx_deaf": (
        "Dongle scans but hears nothing (RX died after a firmware hang) — "
        "reader auto-replugs it (recovery L3); data resumes within minutes."
    ),
    "ub500_dongle_missing_from_usb": (
        "USB dongle is GONE from the bus — needs a physical reseat at the Pi."
    ),
    "adapter_down_or_bd_null": (
        "Adapter powered down / not communicating — reader is power-cycling it."
    ),
    "bluez_discovery_state_stuck": (
        "BlueZ discovery state stuck — usually cleared by the reader's "
        "bluetoothd restart (recovery L2)."
    ),
    "bluez_adapter_object_missing": (
        "Kernel sees the adapter but bluetoothd doesn't (post-USB-reset "
        "state) — reader auto-replugs the dongle (recovery L3); it should "
        "also be reading via the fallback adapter meanwhile."
    ),
    "bms_peer_not_responding": (
        "Radio is fine; the battery BMS isn't answering — usually RF or "
        "battery-side, tends to self-resolve."
    ),
    "power_under_voltage_active": (
        "Pi is UNDER-VOLTAGE — check the PSU/cable. Software can't fix this."
    ),
    "unclassified": "No clear layer identified — see the wedge_snapshot event.",
}


class StalenessMonitor:
    """Watches every source in the readings table for freshness.

    When a source goes stale, the alert is enriched with a diagnosis derived
    from the reader's recent `ble_events` (wedge classifications, adapter
    fallback state) — so the push itself says WHAT broke and whether the
    reader is already fixing it, not just "no data".

    In-memory state is per-process (fine for a single Railway service; would
    need Redis / DB-backed state for multi-replica deployments).
    """

    # How far back to look for reader diagnostics when composing the
    # stale-alert hint. Generous: the reader batches events (≤10 min latency).
    DIAGNOSIS_WINDOW = timedelta(minutes=45)

    # Per-battery silence: how long one battery must be absent from otherwise-
    # flowing telemetry before we page. Battery B misses single scan cycles
    # constantly (marginal RSSI — hundreds of 8-10 s blips in the record), so
    # this must comfortably exceed a blip; the events that matter are the
    # minutes-to-hours BLE dormancies (FM-6).
    BATTERY_SILENT_THRESHOLD_S = 15 * 60
    # How many recent rows to scan for per-battery presence — must cover the
    # threshold at the ~8 s sample cadence with margin.
    PRESENCE_WINDOW_ROWS = 150

    def __init__(
        self,
        dao: _RecentSourcesDAO,
        webhook_url: str,
        threshold_s: float,
        check_interval_s: float,
        events_dao: Optional["_EventsSourceDAO"] = None,
    ) -> None:
        self.dao = dao
        self.events_dao = events_dao
        self.webhook_url = webhook_url
        self.threshold_s = threshold_s
        self.check_interval_s = check_interval_s
        # source_id -> "is currently considered stale"
        self._state: dict[str, bool] = {}
        # (source_id, "a"|"b") -> {"silent": bool, "since": datetime|None}
        self._batt_state: dict[tuple[str, str], dict] = {}
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not self.webhook_url:
            log.info("STALENESS_WEBHOOK_URL not set — alerting disabled")
            return
        log.info(
            "staleness monitor: threshold=%ss interval=%ss -> %s",
            int(self.threshold_s),
            int(self.check_interval_s),
            self.webhook_url,
        )
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    await self.check_once(client)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("staleness check error: %s", exc)
                await asyncio.sleep(self.check_interval_s)

    async def check_once(self, client: httpx.AsyncClient) -> None:
        """Do one full sweep — public so tests can drive it directly without
        spinning the background task."""
        now = datetime.now(timezone.utc)
        for source_id in await self.dao.sources():
            rows = await self.dao.recent(source_id, self.PRESENCE_WINDOW_ROWS)
            if not rows:
                # Never received data for this source yet — skip; we can't
                # judge stale if we've never seen fresh.
                continue
            ts = _parse_ts(rows[0].get("ts"))
            if ts is None:
                continue
            age_s = (now - ts).total_seconds()
            is_stale = age_s > self.threshold_s
            was_stale = self._state.get(source_id, False)
            if is_stale != was_stale:
                self._state[source_id] = is_stale
                await self._fire(client, source_id, is_stale, age_s)
            # Per-battery silence only means something while pack telemetry
            # itself is flowing (a stale source already has its own alert).
            if not is_stale:
                await self._check_battery_presence(client, source_id, rows, now)

    @staticmethod
    def _battery_present(row: dict, suffix: str) -> Optional[bool]:
        """True/False if the row carries evidence about battery `suffix`
        ("a"/"b"); None when the row has none of the fields at all (minimal
        test fakes) so the presence check disengages rather than guessing."""
        keys = (f"soc_{suffix}", f"v_{suffix}", f"i_{suffix}")
        if not any(k in row for k in keys):
            return None
        return any(row.get(k) is not None for k in keys)

    async def _check_battery_presence(
        self, client: httpx.AsyncClient, source_id: str,
        rows: list[dict], now: datetime,
    ) -> None:
        """Fire when ONE battery vanishes from otherwise-flowing telemetry
        (FM-6: the BMS BLE goes dormant, or a phone app holds its single
        connection slot) — and again when it returns, with the outage
        duration. `rows` are newest-first."""
        for suffix, label in (("a", "A"), ("b", "B")):
            # Find the newest row where this battery reported anything.
            last_present_ts: Optional[datetime] = None
            engaged = False
            for r in rows:
                present = self._battery_present(r, suffix)
                if present is None:
                    continue
                engaged = True
                if present:
                    last_present_ts = _parse_ts(r.get("ts"))
                    break
            if not engaged:
                continue
            silent_age = (
                (now - last_present_ts).total_seconds()
                if last_present_ts is not None
                else self.BATTERY_SILENT_THRESHOLD_S + 1  # absent all window
            )
            is_silent = silent_age > self.BATTERY_SILENT_THRESHOLD_S
            st = self._batt_state.setdefault(
                (source_id, suffix), {"silent": False, "since": None},
            )
            if is_silent and not st["silent"]:
                st["silent"] = True
                st["since"] = last_present_ts or now
                name = next(
                    (r.get(f"name_{suffix}") for r in rows
                     if r.get(f"name_{suffix}")), None,
                )
                await self._fire_raw(
                    client,
                    title=f"Volthium: {source_id} battery {label} silent",
                    message=(
                        f"Battery {label}"
                        + (f" ({name})" if name else "")
                        + f" has sent nothing for {int(silent_age // 60)} min "
                        "while the pack keeps reporting — its BMS BLE is "
                        "dormant (FM-6) or a phone app is holding its only "
                        "connection slot. Self-resolves within minutes-to-"
                        "hours; B's episodes have historically ended at the "
                        "next zero-load window, A's first one ended mid-"
                        "charge. Manual cure if urgent: open the inverter "
                        "breakers ~30 s (a forced quiet-bus reset)."
                    ),
                    priority=4,
                    tags=["battery", "warning"],
                    context=f"source={source_id} battery={label} silent",
                )
            elif not is_silent and st["silent"]:
                st["silent"] = False
                since = st.get("since")
                dur = ""
                if isinstance(since, datetime):
                    mins = int((now - since).total_seconds() // 60)
                    dur = (f" after ~{mins} min" if mins < 120
                           else f" after ~{mins / 60:.1f} h")
                st["since"] = None
                await self._fire_raw(
                    client,
                    title=f"Volthium: {source_id} battery {label} back",
                    message=f"Battery {label} is advertising again{dur}.",
                    priority=3,
                    tags=["battery", "white_check_mark"],
                    context=f"source={source_id} battery={label} recovered",
                )

    async def _fire_raw(
        self, client, *, title: str, message: str, priority: int,
        tags: list[str], context: str,
    ) -> None:
        payload = {
            "title": title, "message": message,
            "priority": priority, "tags": tags,
        }
        try:
            resp = await client.post(self.webhook_url, json=payload, timeout=10.0)
            log.info("alert posted: %s http=%d", context, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert POST failed (%s): %s", context, exc)

    async def _diagnose(self, source_id: str) -> str:
        """Compose a one-paragraph likely-cause hint from the reader's recent
        diagnostics events. Best-effort — any failure returns a generic line
        rather than blocking the alert."""
        if self.events_dao is None:
            return ""
        try:
            now = datetime.now(timezone.utc)
            since = now - self.DIAGNOSIS_WINDOW

            def _age_str(ts) -> str:
                dt = _parse_ts(ts)
                if dt is None:
                    return "?"
                mins = int((now - dt).total_seconds() // 60)
                return f"{mins}m ago"

            wedges = await self.events_dao.recent_events(
                source_id, "wedge_snapshot", since, limit=3,
            )
            fallback = await self.events_dao.recent_events(
                source_id, "adapter_fallback_active", since, limit=1,
            )
            replug = await self.events_dao.recent_events(
                source_id, "usb_replug", since, limit=1,
            )
            health = await self.events_dao.recent_events(
                source_id, "stack_health", since, limit=1,
            )

            parts: list[str] = []
            if wedges:
                d = wedges[0].get("data", {})
                cls = d.get("classification", "unclassified")
                lvl = d.get("recovery_level", "?")
                hint = _CLASSIFICATION_HINTS.get(cls, "")
                parts.append(
                    f"Likely cause: {cls} (wedge L{lvl}, {_age_str(wedges[0]['ts'])})."
                    + (f" {hint}" if hint else "")
                )
            if fallback:
                parts.append(
                    f"Reader switched to its fallback adapter "
                    f"{_age_str(fallback[0]['ts'])} — degraded but should be "
                    "flowing; if still stale, the fallback is failing too."
                )
            if replug:
                ok = replug[0].get("data", {}).get("ok")
                parts.append(
                    f"Auto USB-replug attempted {_age_str(replug[0]['ts'])}"
                    + (" (no sysfs target found)." if ok is False else ".")
                )
            if not parts:
                if health:
                    parts.append(
                        f"Reader diagnostics still arriving (last "
                        f"{_age_str(health[0]['ts'])}) with no wedge recorded — "
                        "BLE reads may be fine; suspect the CSV uploader or the "
                        "readings path instead."
                    )
                else:
                    parts.append(
                        "No reader diagnostics received in the last "
                        f"{int(self.DIAGNOSIS_WINDOW.total_seconds() // 60)}m "
                        "either — Pi may be offline (power/network) or "
                        "crash-looping before it can upload."
                    )
            return " ".join(parts)
        except Exception as exc:  # noqa: BLE001 — the alert must still fire
            log.warning("stale-alert diagnosis failed for %s: %s", source_id, exc)
            return ""

    async def _fire(
        self,
        client: httpx.AsyncClient,
        source_id: str,
        is_stale: bool,
        age_s: float,
    ) -> None:
        if is_stale:
            message = (
                f"No fresh telemetry for {int(age_s)}s "
                f"(threshold {int(self.threshold_s)}s)"
            )
            diagnosis = await self._diagnose(source_id)
            if diagnosis:
                message += "\n" + diagnosis
            payload = {
                "title": f"Volthium: {source_id} stale",
                "message": message,
                "priority": 4,
                "tags": ["warning"],
            }
        else:
            payload = {
                "title": f"Volthium: {source_id} recovered",
                "message": "Telemetry flowing again.",
                "priority": 3,
                "tags": ["white_check_mark"],
            }
        try:
            resp = await client.post(self.webhook_url, json=payload, timeout=10.0)
            log.info(
                "alert posted: source=%s is_stale=%s http=%d",
                source_id, is_stale, resp.status_code,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("alert POST failed for %s: %s", source_id, exc)


# --- Event-driven incident alerts -----------------------------------------
# The staleness monitor above catches "no data at all" outages. This one
# catches "reader is limping, alert the operator before it gets worse":
# - `adapter_pin_failed` streaks: the reader wanted the UB500 but couldn't
#   find it → we're on the fallback adapter (or worse, no adapter). Fires on
#   the first pin-fail after a quiet period; clears on the next successful
#   `adapter_pinned`.
# - `wedge_snapshot` at recovery_level >= 2: the BLE stack wedged badly
#   enough that a plain HCI reset didn't clear it. Fires with the
#   classification hint from the reader so the push tells you WHICH layer
#   is misbehaving without needing to SSH in first.


class _EventsSourceDAO(Protocol):
    """Subset of the DAO for the event monitor. Kept narrow so tests can
    inject a fake without pulling in the whole readings machinery."""

    async def sources(self) -> list[str]: ...

    async def recent_events(
        self,
        source_id: str,
        event: str,
        since: datetime,
        limit: int,
    ) -> list[dict]: ...


class EventAlertMonitor:
    """Watches `ble_events` for reader-side incident events and pushes ntfy.

    Alert-worthy events (all logged by volthium/pack.py):
      - adapter_pin_failed  → primary BLE adapter unresolvable. Fires once
        per streak; clears on the next adapter_pinned event.
      - wedge_snapshot @ recovery_level >= 2 → wedge that survived a plain
        HCI reset. Fires with the classification hint attached.
    """

    # Only alert on Level >= 2 wedges. Level 1 is transient — soft resets
    # usually clear the wedge and reads resume within seconds; paging on
    # every Level 1 would produce false-positive noise.
    WEDGE_MIN_LEVEL = 2

    # Classifications that fire an alert IMMEDIATELY regardless of level or
    # event kind (wedge_snapshot or stack_health). Power under-voltage is
    # the canonical case: it's a hardware/wiring problem the operator has
    # to fix; the reader can't self-heal. Waiting for Level 2 or waiting
    # for the "stale" push is losing information.
    URGENT_CLASSIFICATIONS = ("power_under_voltage_active",)

    # Cooldowns prevent a stuck reader from spamming the operator. Each
    # source has independent cooldowns per event kind.
    PIN_FAIL_COOLDOWN = timedelta(hours=1)
    WEDGE_COOLDOWN = timedelta(minutes=30)
    POWER_COOLDOWN = timedelta(hours=2)

    # --- Xanbus / solar rules (added 2026-08-08) --------------------------
    #
    # This monitor watched only `ble_events`, which are the BLE-era failure
    # modes; it predates the entire solar path and read a table that path does
    # not write to. So `xanbus_config_watch.py` — built specifically because a
    # 4.0 V/cell equalize setting is one UI click from returning "and nothing
    # currently alarms on it" — detected changes into a table nothing watched.
    # The bell was working the whole time; it just was not wired up.
    #
    # (event, priority, tag, title) — priority follows the ntfy 1..5 scale.
    XANBUS_RULES: tuple[tuple[str, int, str, str], ...] = (
        ("xanbus_config_changed", 5, "rotating_light",
         "CHARGE SETPOINT CHANGED"),
        ("latch_fix_denied", 4, "no_entry", "MPPT refused our command"),
        ("latch_fix_aborted", 4, "no_entry", "MPPT fix could not start"),
    )

    # Deliberately NOT alerted: mppt_latched, latch_detected, and a successful
    # latch_fix_result. Those happen most days and the guard clears them
    # unattended in ~20 min. Paging on routine self-healing is how an operator
    # learns to ignore the channel, and then the one message that matters
    # arrives buried in noise. Only the cases needing a HUMAN are above, plus
    # the two conditional rules handled in code below.
    XANBUS_COOLDOWN = timedelta(minutes=30)
    CONFIG_COOLDOWN = timedelta(minutes=5)   # near-immediate; this one is safety

    # --- BMS protection alarms (added 2026-08-09) -------------------------
    #
    # These were decoded and shown on /history from the start, and paged
    # nobody. 16 episodes were already on record — every one `cell_overvoltage`
    # on battery A, across 07-19, 07-20, 07-27, 07-29 and 08-01 — including the
    # disconnects that started the whole MPPT investigation. The battery hit its
    # own protection limit at least eight separate times in silence.
    #
    # Every one of these means the pack had to protect itself. None is routine.
    BMS_ALARM_PRIORITY = {
        "cell_overvoltage": 5, "cell_undervoltage": 5, "short_circuit": 5,
        "charge_overcurrent": 4, "discharge_overcurrent_1": 4,
        "discharge_overcurrent_2": 4, "charge_overtemp": 4,
        "discharge_overtemp": 4,
        # Winter matters here: this is a lakeside cabin at 51 N and LFP must not
        # be charged below freezing. Summer baseline is 16-26 C, so this has
        # never fired — but it is the one that will, months from now, with
        # nobody on site.
        "charge_undertemp": 4, "discharge_undertemp": 3,
    }
    # One real event fragments into several episodes (08-01 produced four
    # inside three minutes), so collapse per battery+flag.
    BMS_ALARM_COOLDOWN = timedelta(minutes=30)

    def __init__(
        self,
        dao: _EventsSourceDAO,
        webhook_url: str,
        check_interval_s: float,
    ) -> None:
        self.dao = dao
        self.webhook_url = webhook_url
        self.check_interval_s = check_interval_s
        # Per-source state:
        #   pin_failed_alerted_at: when we last fired a pin-fail alert
        #   pin_failed_streak_start: earliest pin-fail ts in the current
        #     streak (None = no streak)
        #   last_wedge_ts_alerted: ts of the most recent wedge_snapshot we
        #     already pushed (avoid double-pushing the same event)
        #   last_wedge_alert_at: cooldown gate for wedge alerts
        self._state: dict[str, dict] = {}
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not self.webhook_url:
            log.info("EventAlertMonitor: webhook_url empty — event alerts disabled")
            return
        log.info(
            "event alert monitor: interval=%ss -> %s",
            int(self.check_interval_s), self.webhook_url,
        )
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    await self.check_once(client)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("event alert check error: %s", exc)
                await asyncio.sleep(self.check_interval_s)

    def _get_source_state(self, source_id: str) -> dict:
        st = self._state.get(source_id)
        if st is None:
            st = {
                "pin_failed_alerted_at": None,
                "pin_failed_streak_start": None,
                "last_wedge_ts_alerted": None,
                "last_wedge_alert_at": None,
            }
            self._state[source_id] = st
            st.setdefault("last_power_alert_at", None)
            st.setdefault("last_power_ts_alerted", None)
        st.setdefault("last_fallback_ts_alerted", None)
        st.setdefault("last_restored_ts_alerted", None)
        return st

    async def check_once(self, client: httpx.AsyncClient) -> None:
        """One full sweep across all sources. Public so tests can drive it."""
        now = datetime.now(timezone.utc)
        # Only look at events from the last check window (plus one for jitter)
        window = timedelta(seconds=self.check_interval_s * 2)
        since = now - window
        for source_id in await self.dao.sources():
            st = self._get_source_state(source_id)
            await self._check_pin_failed(client, source_id, st, since, now)
            await self._check_wedges(client, source_id, st, since, now)
            await self._check_xanbus(client, source_id, st, since, now)
            await self._check_bms_alarms(client, source_id, st, since, now)
            await self._check_urgent_classification(client, source_id, st, since, now)
            await self._check_adapter_fallback(client, source_id, st, since, now)

    async def _check_adapter_fallback(
        self, client, source_id: str, st: dict, since: datetime, now: datetime,
    ) -> None:
        """Informational pushes for the degraded-mode transitions:
        `adapter_fallback_active` (reading on the second-choice controller
        while the primary is being auto-repaired) and `adapter_restored`
        (back on the primary). The reader emits each only on an actual
        transition, so no cooldown is needed — just dedup by ts."""
        fallback = await self.dao.recent_events(
            source_id, "adapter_fallback_active", since, limit=1,
        )
        if fallback:
            ts = _parse_ts(fallback[0]["ts"])
            if not (st["last_fallback_ts_alerted"] and ts is not None
                    and ts <= st["last_fallback_ts_alerted"]):
                d = fallback[0].get("data", {})
                await self._fire(
                    client,
                    title=f"Volthium: {source_id} on FALLBACK adapter",
                    message=(
                        f"Primary adapter unusable "
                        f"({d.get('primary_fail_reason', '?')}). Reading via "
                        f"{d.get('resolved', '?')} instead — data keeps flowing, "
                        "degraded. The reader auto-repairs the primary (USB "
                        "replug) and will switch back by itself."
                    ),
                    priority=3,
                    tags=["yellow_circle"],
                    context=f"source={source_id} kind=adapter_fallback_active",
                )
                st["last_fallback_ts_alerted"] = ts
        restored = await self.dao.recent_events(
            source_id, "adapter_restored", since, limit=1,
        )
        if restored:
            ts = _parse_ts(restored[0]["ts"])
            if not (st["last_restored_ts_alerted"] and ts is not None
                    and ts <= st["last_restored_ts_alerted"]):
                d = restored[0].get("data", {})
                await self._fire(
                    client,
                    title=f"Volthium: {source_id} primary adapter restored",
                    message=(
                        f"Back on the primary adapter "
                        f"({d.get('resolved', '?')}); fallback powered down."
                    ),
                    priority=3,
                    tags=["white_check_mark"],
                    context=f"source={source_id} kind=adapter_restored",
                )
                st["last_restored_ts_alerted"] = ts

    async def _check_pin_failed(
        self, client, source_id: str, st: dict, since: datetime, now: datetime,
    ) -> None:
        """Pin-fail transitions.

        Streak logic: if pin_failed events are being seen but we haven't
        alerted (or the last alert is past cooldown), alert. If a fresh
        adapter_pinned event follows the streak, clear state and push a
        recovery notification."""
        pin_fails = await self.dao.recent_events(
            source_id, "adapter_pin_failed", since, limit=1,
        )
        pinned = await self.dao.recent_events(
            source_id, "adapter_pinned", since, limit=1,
        )

        if pin_fails and st["pin_failed_streak_start"] is None:
            # Start of a new streak
            st["pin_failed_streak_start"] = _parse_ts(pin_fails[0]["ts"])

        cooldown_ok = (
            st["pin_failed_alerted_at"] is None
            or (now - st["pin_failed_alerted_at"]) > self.PIN_FAIL_COOLDOWN
        )
        if pin_fails and cooldown_ok:
            cfg = pin_fails[0].get("data", {}).get("configured", "?")
            reason = pin_fails[0].get("data", {}).get("reason", "?")
            await self._fire(
                client,
                title=f"Volthium: {source_id} adapter pin failing",
                message=(
                    f"Reader can't find its pinned adapter ({cfg}). "
                    f"Reason: {reason}. "
                    "Likely falling back to another adapter — SSH in and check "
                    "hciconfig / dmesg."
                ),
                priority=4,
                tags=["warning"],
                context=f"source={source_id} kind=adapter_pin_failed",
            )
            st["pin_failed_alerted_at"] = now

        if pinned and st["pin_failed_alerted_at"] is not None:
            # Streak recovered
            await self._fire(
                client,
                title=f"Volthium: {source_id} adapter re-pinned",
                message="Pinned adapter is back on the bus.",
                priority=3,
                tags=["white_check_mark"],
                context=f"source={source_id} kind=adapter_pinned",
            )
            st["pin_failed_alerted_at"] = None
            st["pin_failed_streak_start"] = None

    async def _check_wedges(
        self, client, source_id: str, st: dict, since: datetime, now: datetime,
    ) -> None:
        """Alert on wedge_snapshot at recovery_level >= WEDGE_MIN_LEVEL. Each
        wedge event is a discrete incident, so we don't debounce on transitions
        the way we do for pin-fails — we debounce on cooldown + already-seen
        timestamp instead."""
        cooldown_ok = (
            st["last_wedge_alert_at"] is None
            or (now - st["last_wedge_alert_at"]) > self.WEDGE_COOLDOWN
        )
        if not cooldown_ok:
            return
        wedges = await self.dao.recent_events(
            source_id, "wedge_snapshot", since, limit=5,
        )
        for w in wedges:
            d = w.get("data", {})
            lvl = d.get("recovery_level", 0)
            if lvl < self.WEDGE_MIN_LEVEL:
                continue
            ts = _parse_ts(w["ts"])
            if st["last_wedge_ts_alerted"] and ts <= st["last_wedge_ts_alerted"]:
                continue
            classification = d.get("classification", "unclassified")
            reason = str(d.get("reason", ""))[:120]
            hint = _CLASSIFICATION_HINTS.get(classification, "")
            await self._fire(
                client,
                title=f"Volthium: {source_id} wedge L{lvl} — {classification}",
                message=(
                    f"BLE stack wedged; recovery ladder at level {lvl}. "
                    f"Trigger: {reason}"
                    + (f"\n{hint}" if hint else "")
                ),
                priority=4,
                tags=["warning"],
                context=f"source={source_id} kind=wedge_snapshot level={lvl}",
            )
            st["last_wedge_ts_alerted"] = ts
            st["last_wedge_alert_at"] = now
            break  # one alert per check window

    async def _check_urgent_classification(
        self, client, source_id: str, st: dict, since: datetime, now: datetime,
    ) -> None:
        """Fire on any wedge_snapshot OR stack_health event whose classification
        is in URGENT_CLASSIFICATIONS. These are conditions where the reader
        can't self-heal — waiting for a Level-2 wedge or a stale-push is
        losing time. Independent cooldown; independent last-alerted ts."""
        cooldown_ok = (
            st["last_power_alert_at"] is None
            or (now - st["last_power_alert_at"]) > self.POWER_COOLDOWN
        )
        if not cooldown_ok:
            return
        # Fetch recent events of BOTH kinds and pick the newest one that
        # matches an urgent classification. We can't filter by classification
        # at the SQL layer (it's inside JSONB), so pull the last few and
        # filter in Python — trivial since events are rare.
        candidates = []
        for kind in ("stack_health", "wedge_snapshot"):
            candidates.extend(
                await self.dao.recent_events(source_id, kind, since, limit=10)
            )
        candidates.sort(key=lambda e: e["ts"], reverse=True)
        for evt in candidates:
            d = evt.get("data", {})
            cls = d.get("classification", "")
            if cls not in self.URGENT_CLASSIFICATIONS:
                continue
            ts = _parse_ts(evt["ts"])
            if st["last_power_ts_alerted"] and ts <= st["last_power_ts_alerted"]:
                continue
            pt = d.get("power_thermal", {}) or {}
            flags = pt.get("throttled_flags", [])
            temp = pt.get("soc_temp_c")
            temp_str = f"{temp:.1f}°C" if isinstance(temp, (int, float)) else "?"
            await self._fire(
                client,
                title=f"Volthium: {source_id} POWER — {cls}",
                message=(
                    f"Pi under-voltage detected. Throttled flags: "
                    f"{', '.join(flags) or 'none'}. SoC {temp_str}. "
                    "Check the Pi's PSU / cable — reader can't self-heal from "
                    "an under-powered host."
                ),
                priority=5,
                tags=["rotating_light"],
                context=f"source={source_id} kind={evt['event']} cls={cls}",
            )
            st["last_power_alert_at"] = now
            st["last_power_ts_alerted"] = ts
            break

    async def _check_xanbus(
        self, client, source_id: str, st: dict,
        since: datetime, now: datetime,
    ) -> None:
        """Alert on the Xanbus incident events that need a human.

        Best-effort by design: a DAO without `recent_xanbus_events` (the
        in-memory one used by tests and by a DB-less deploy) simply skips
        this, exactly as the rest of this monitor degrades.
        """
        getter = getattr(self.dao, "recent_xanbus_events", None)
        if getter is None:
            return
        wanted = ",".join(name for name, _p, _t, _title in self.XANBUS_RULES)
        try:
            rows = await getter(source_id, wanted, since, 40)
        except Exception as exc:  # noqa: BLE001
            log.warning("xanbus alert query failed: %s", exc)
            return

        by_name = {name: (p, tag, title)
                   for name, p, tag, title in self.XANBUS_RULES}
        seen: set = st.setdefault("xanbus_ts_alerted", set())
        for row in rows:
            name = row.get("event")
            rule = by_name.get(name)
            if rule is None:
                continue
            ts = row.get("ts")
            key = (name, str(ts))
            if key in seen:          # same event, later poll — do not re-page
                continue
            cooldown = (self.CONFIG_COOLDOWN
                        if name == "xanbus_config_changed"
                        else self.XANBUS_COOLDOWN)
            last = st.get(f"last_{name}_at")
            if last is not None and now - last < cooldown:
                continue
            priority, tag, title = rule
            seen.add(key)
            st[f"last_{name}_at"] = now
            await self._fire(
                client,
                title=f"{title} — {source_id}",
                message=self._xanbus_message(name, row),
                priority=priority, tags=[tag],
                context=f"source={source_id} kind={name}",
            )

    # Kept in step with _ALARM_BITS in main.py. Duplicated rather than imported
    # because staleness.py must not depend on the FastAPI app module.
    _ALARM_BITS = (
        (0x004, "cell_overvoltage"), (0x008, "cell_undervoltage"),
        (0x010, "charge_overcurrent"), (0x020, "short_circuit"),
        (0x040, "discharge_overcurrent_1"), (0x080, "discharge_overcurrent_2"),
        (0x100, "charge_overtemp"), (0x200, "charge_undertemp"),
        (0x400, "discharge_overtemp"), (0x800, "discharge_undertemp"),
    )

    async def _check_bms_alarms(
        self, client, source_id: str, st: dict,
        since: datetime, now: datetime,
    ) -> None:
        """Page when a battery has had to protect itself."""
        getter = getattr(self.dao, "history_alarms", None)
        if getter is None:
            return
        try:
            episodes = await getter(source_id, since)
        except Exception as exc:  # noqa: BLE001
            log.warning("bms alarm query failed: %s", exc)
            return

        for ep in episodes:
            code = ep.get("codes") or ep.get("code") or 0
            bat = ep.get("bat") or ep.get("battery") or "?"
            flags = [n for bit, n in self._ALARM_BITS if code & bit]
            if not flags:
                continue
            worst = max(flags, key=lambda f: self.BMS_ALARM_PRIORITY.get(f, 3))
            prio = self.BMS_ALARM_PRIORITY.get(worst, 3)
            key = f"last_bms_{bat}_{worst}_at"
            last = st.get(key)
            if last is not None and now - last < self.BMS_ALARM_COOLDOWN:
                continue
            st[key] = now
            await self._fire(
                client,
                title=f"Battery {bat} protection: {worst} — {source_id}",
                message=(
                    f"Battery {bat} raised {', '.join(flags)}. The pack cut in "
                    f"to protect itself; this is not a routine event. "
                    f"Check the cell-imbalance chart on /history — pack A's "
                    f"cell 4 reaches ~3.83 V at the top of charge and has "
                    f"tripped this before."),
                priority=prio, tags=["battery"],
                context=f"source={source_id} bms={bat}/{worst}",
            )

    @staticmethod
    def _xanbus_message(name: str, row: dict) -> str:
        """One line the operator can act on, not a JSON dump."""
        d = row.get("data") or {}
        if name == "xanbus_config_changed":
            fields = ", ".join(
                c.get("field", "?") for c in (d.get("changes") or [])) or "?"
            return (f"A charge setpoint changed that we did not change: {fields}. "
                    f"Check the Insight UI — equalize on this LFP bank is 32 V "
                    f"(4.0 V/cell) and must stay disabled.")
        if name in ("latch_fix_denied", "latch_fix_aborted"):
            return (f"The MPPT latch guard could not act ({name}). The array may "
                    f"stay clamped until someone bounces it by hand: Insight → "
                    f"MPPT → Operating Mode → Standby → 15 s → Operating.")
        return f"{name}: {d}"

    async def _fire(
        self, client, *, title: str, message: str, priority: int,
        tags: list[str], context: str,
    ) -> None:
        payload = {
            "title": title, "message": message,
            "priority": priority, "tags": tags,
        }
        try:
            resp = await client.post(self.webhook_url, json=payload, timeout=10.0)
            log.info("event alert posted: %s http=%d", context, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            log.warning("event alert POST failed (%s): %s", context, exc)
