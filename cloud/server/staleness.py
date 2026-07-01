"""Staleness monitor — fires a webhook when a source's telemetry goes stale
and again when it recovers.

Background task started from the FastAPI lifespan. Polls the DAO on a fixed
interval (default 60 s) and diffs against in-memory state so we only alert
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
import logging
from datetime import datetime, timezone
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
