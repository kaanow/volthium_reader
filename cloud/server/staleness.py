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


class StalenessMonitor:
    """Watches every source in the readings table for freshness.

    In-memory state is per-process (fine for a single Railway service; would
    need Redis / DB-backed state for multi-replica deployments).
    """

    def __init__(
        self,
        dao: _RecentSourcesDAO,
        webhook_url: str,
        threshold_s: float,
        check_interval_s: float,
    ) -> None:
        self.dao = dao
        self.webhook_url = webhook_url
        self.threshold_s = threshold_s
        self.check_interval_s = check_interval_s
        # source_id -> "is currently considered stale"
        self._state: dict[str, bool] = {}
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
            latest_rows = await self.dao.recent(source_id, 1)
            if not latest_rows:
                # Never received data for this source yet — skip; we can't
                # judge stale if we've never seen fresh.
                continue
            ts = _parse_ts(latest_rows[0].get("ts"))
            if ts is None:
                continue
            age_s = (now - ts).total_seconds()
            is_stale = age_s > self.threshold_s
            was_stale = self._state.get(source_id, False)
            if is_stale != was_stale:
                self._state[source_id] = is_stale
                await self._fire(client, source_id, is_stale, age_s)

    async def _fire(
        self,
        client: httpx.AsyncClient,
        source_id: str,
        is_stale: bool,
        age_s: float,
    ) -> None:
        if is_stale:
            payload = {
                "title": f"Volthium: {source_id} stale",
                "message": (
                    f"No fresh telemetry for {int(age_s)}s "
                    f"(threshold {int(self.threshold_s)}s)"
                ),
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

    # Cooldowns prevent a stuck reader from spamming the operator. Each
    # source has independent cooldowns per event kind.
    PIN_FAIL_COOLDOWN = timedelta(hours=1)
    WEDGE_COOLDOWN = timedelta(minutes=30)

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
            await self._fire(
                client,
                title=f"Volthium: {source_id} wedge L{lvl} — {classification}",
                message=(
                    f"BLE stack wedged; recovery ladder at level {lvl}. "
                    f"Trigger: {reason}"
                ),
                priority=4,
                tags=["warning"],
                context=f"source={source_id} kind=wedge_snapshot level={lvl}",
            )
            st["last_wedge_ts_alerted"] = ts
            st["last_wedge_alert_at"] = now
            break  # one alert per check window

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
