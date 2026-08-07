"""FastAPI ingest server + browser dashboard for Volthium telemetry.

Run locally:
    uvicorn cloud.server.main:app --host 0.0.0.0 --port 8000

Run on Railway:
    Procfile is `web: uvicorn cloud.server.main:app --host 0.0.0.0 --port $PORT`

Endpoints:
    POST /ingest           — per-source-token bearer auth; accepts an IngestBatch.
    GET  /healthz          — unauth liveness probe.
    GET  /api/sources      — list of source_ids that have uploaded.
    GET  /api/readings     — query rows; supports ?source_id=…&limit=… (defaults sensible).
    GET  /api/latest       — single most-recent row.
    GET  /api/history/*    — bucketed series, daily energy ledger, hour-of-day
                             profile, outage gaps, lifetime stats (see the
                             history section below).
    GET  /                 — browser dashboard (static HTML; polls /api/readings).
    GET  /history          — historical explorer (static HTML; /api/history/*).

Env vars: see cloud/server/config.py.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from cloud.server.config import Settings, load_settings
from cloud.server.db import AsyncpgReadingsDAO, ReadingsDAO, create_pool
from cloud.server.derive import derive
from cloud.server.staleness import EventAlertMonitor, StalenessMonitor
from cloud.shared.wire import (
    BleEventBatch,
    BleEventIngestResponse,
    IngestBatch,
    IngestResponse,
    Reading,
    SolarIngestBatch,
    SolarIngestResponse,
    XanbusEventBatch,
    XanbusEventIngestResponse,
)


log = logging.getLogger("volthium-cloud")


# Module-level DAO handle — populated by the lifespan hook on startup, swapped
# in tests via app.dependency_overrides. Wrapped in a holder dict so tests can
# replace the value without monkey-patching globals.
_state: dict = {"dao": None, "settings": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: open the asyncpg pool, run migrations, wire the DAO.
    Shutdown: close the pool. Tests bypass this by directly setting
    _state["dao"] before calling endpoints."""
    settings = load_settings()
    _state["settings"] = settings

    if not settings.database_url:
        log.warning(
            "DATABASE_URL is empty — running in DAO-injection mode "
            "(tests only; real deployments must set DATABASE_URL)."
        )
        yield
        return

    pool = await create_pool(settings.database_url)
    if settings.auto_migrate:
        from cloud.server.migrations import apply_all
        n = await apply_all(pool)
        log.info("applied %d migration file(s)", n)
    dao = AsyncpgReadingsDAO(pool)
    _state["dao"] = dao
    log.info(
        "ready: tokens=%d, alpha=%.2f, capacity=%.0fAh, floor=%.0f%%, ceil=%.0f%%",
        len(settings.tokens), settings.ema_alpha, settings.capacity_ah,
        settings.floor_soc, settings.ceiling_soc,
    )
    monitor = StalenessMonitor(
        dao,
        webhook_url=settings.staleness_webhook_url,
        threshold_s=settings.staleness_threshold_s,
        check_interval_s=settings.staleness_check_interval_s,
        events_dao=dao,   # enriches stale alerts with recent wedge diagnostics
    )
    await monitor.start()
    _state["monitor"] = monitor
    event_monitor = EventAlertMonitor(
        dao,
        webhook_url=settings.staleness_webhook_url,
        check_interval_s=settings.staleness_check_interval_s,
    )
    await event_monitor.start()
    _state["event_monitor"] = event_monitor
    try:
        yield
    finally:
        await event_monitor.stop()
        await monitor.stop()
        await pool.close()


app = FastAPI(title="Volthium Cloud", lifespan=lifespan)
# Gzip all responses over 500 B. The JSON telemetry compresses ~13× (measured:
# a 720-row /api/readings response is 538 KB raw → 40 KB gzipped), so this one
# line cuts dashboard + API egress by an order of magnitude across every client.
app.add_middleware(GZipMiddleware, minimum_size=500)


def get_dao() -> ReadingsDAO:
    dao = _state["dao"]
    if dao is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database not initialized",
        )
    return dao


def get_settings() -> Settings:
    s = _state["settings"]
    if s is None:
        # In tests, lifespan may not have run — fall back to env-derived
        # settings so the auth path still works.
        s = load_settings()
        _state["settings"] = s
    return s


# --- /ingest --------------------------------------------------------------

def _check_token(request: Request, source_id: str, settings: Settings) -> None:
    """Bearer-token auth. Returns 401 on any malformed/wrong token.

    Per docs/cloud_architecture.md: per-device tokens, one env var per source.
    Adding the ESP32 doesn't re-key the Pi.
    """
    expected = settings.tokens.get(source_id)
    if not expected:
        raise HTTPException(401, "unknown source_id or no token configured")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = auth.split(None, 1)[1].strip()
    # constant-time compare to avoid trivial timing leaks
    import hmac
    if not hmac.compare_digest(token, expected):
        raise HTTPException(401, "invalid token")


@app.post("/ingest", response_model=IngestResponse)
async def ingest(
    batch: IngestBatch,
    request: Request,
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> IngestResponse:
    _check_token(request, batch.source_id, settings)

    # Sort by ts so the EMA threads forward correctly even if the uploader
    # batched out-of-order rows after a retry.
    readings = sorted(batch.readings, key=lambda r: r.ts)

    prev_i, prev_p = await dao.latest_smoothed(batch.source_id, readings[0].ts)
    deriveds = []
    for r in readings:
        d = derive(
            r,
            prev_smoothed_i=prev_i, prev_smoothed_p=prev_p,
            alpha=settings.ema_alpha,
            capacity_ah=settings.capacity_ah,
            floor_soc=settings.floor_soc,
            ceiling_soc=settings.ceiling_soc,
            idle_current_a=settings.idle_current_a,
        )
        deriveds.append(d)
        prev_i, prev_p = d.smoothed_i, d.smoothed_p

    accepted, duplicates = await dao.insert(batch.source_id, readings, deriveds)
    return IngestResponse(accepted=accepted, duplicates=duplicates)


@app.post("/api/events/ingest", response_model=BleEventIngestResponse)
async def ingest_events(
    batch: BleEventBatch,
    request: Request,
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> BleEventIngestResponse:
    """Bulk-append BLE diagnostic events. Uses the same per-source bearer
    token as /ingest — the events pipeline shares auth with the readings
    pipeline because the reader itself owns both streams."""
    _check_token(request, batch.source_id, settings)
    inserted = await dao.insert_events(batch.source_id, batch.events)
    return BleEventIngestResponse(accepted=inserted)


@app.get("/api/events")
async def api_events(
    source_id: Optional[str] = Query(default=None),
    event: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=10000),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Debug / dashboard readback for BLE events. Filters: optional
    source_id and optional event-kind. Newest first."""
    # No dedicated DAO method yet — a plain query is fine while the shape
    # is stabilizing. Add one when the dashboard actually consumes it.
    rows = []
    if isinstance(dao, AsyncpgReadingsDAO):
        clauses, params = [], []
        if source_id:
            params.append(source_id)
            clauses.append(f"source_id = ${len(params)}")
        if event:
            params.append(event)
            clauses.append(f"event = ${len(params)}")
        params.append(limit)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT source_id, ts, event, data FROM ble_events "
            f"{where} ORDER BY ts DESC LIMIT ${len(params)}"
        )
        async with dao.pool.acquire() as conn:
            for r in await conn.fetch(sql, *params):
                d = dict(r)
                ts = d.get("ts")
                if ts is not None and hasattr(ts, "isoformat"):
                    d["ts"] = ts.isoformat().replace("+00:00", "Z")
                # asyncpg returns JSONB as a str; parse for API clients
                if isinstance(d.get("data"), str):
                    import json as _json
                    try:
                        d["data"] = _json.loads(d["data"])
                    except Exception:
                        pass
                rows.append(d)
    return {"events": rows, "count": len(rows)}


# --- read endpoints -------------------------------------------------------

@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"


@app.get("/api/sources")
async def api_sources(dao: ReadingsDAO = Depends(get_dao)) -> dict:
    return {"sources": await dao.sources()}


@app.get("/api/readings")
async def api_readings(
    source_id: Optional[str] = Query(default=None),
    limit: int = Query(default=720, ge=1, le=10000),   # 720 = 2h @ 10 s
    since: Optional[str] = Query(
        default=None,
        description="ISO timestamp; return only readings STRICTLY AFTER it, "
        "oldest-first. Lets the dashboard poll incrementally (fetch only new "
        "rows) and status_check fetch just its window instead of the full "
        "history — the fix for the 9 GB/day egress from full re-downloads.",
    ),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    if since is not None and isinstance(dao, AsyncpgReadingsDAO):
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since: not an ISO datetime")
        rows = await dao.recent_since(source_id, since_dt, limit)  # oldest-first
    else:
        rows = await dao.recent(source_id, limit)
        # Newest-first from DAO; the dashboard wants oldest-first for charting.
        rows = list(reversed(rows))
    # Render datetimes as the wire's UTC-Z format so the browser parses cleanly.
    for r in rows:
        ts = r.get("ts")
        if ts is not None and hasattr(ts, "isoformat"):
            r["ts"] = ts.isoformat().replace("+00:00", "Z")
    return {"readings": rows, "count": len(rows)}


@app.get("/api/latest")
async def api_latest(
    source_id: Optional[str] = Query(default=None),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    rows = await dao.recent(source_id, 1)
    if not rows:
        return {"latest": None}
    r = rows[0]
    ts = r.get("ts")
    if ts is not None and hasattr(ts, "isoformat"):
        r["ts"] = ts.isoformat().replace("+00:00", "Z")
    return {"latest": r}


# --- solar (Xanbus/CAN) -----------------------------------------------------
# Independent telemetry stream read straight off the Conext CAN bus by the
# Pi's xanbus-reader service. Same auth (per-source bearer token), same
# idempotent-insert and since=-incremental patterns as readings.

@app.post("/api/solar/ingest", response_model=SolarIngestResponse)
async def ingest_solar(
    batch: SolarIngestBatch,
    request: Request,
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> SolarIngestResponse:
    _check_token(request, batch.source_id, settings)
    if not isinstance(dao, AsyncpgReadingsDAO):
        return SolarIngestResponse(accepted=0, duplicates=0)
    readings = sorted(batch.readings, key=lambda r: r.ts)
    accepted, duplicates = await dao.insert_solar(batch.source_id, readings)
    return SolarIngestResponse(accepted=accepted, duplicates=duplicates)


@app.post("/api/xanbus_events/ingest", response_model=XanbusEventIngestResponse)
async def ingest_xanbus_events(
    batch: XanbusEventBatch,
    request: Request,
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> XanbusEventIngestResponse:
    _check_token(request, batch.source_id, settings)
    if not isinstance(dao, AsyncpgReadingsDAO):
        return XanbusEventIngestResponse(accepted=0)
    inserted = await dao.insert_xanbus_events(batch.source_id, batch.events)
    return XanbusEventIngestResponse(accepted=inserted)


@app.get("/api/solar")
async def api_solar(
    source_id: Optional[str] = Query(default=None),
    limit: int = Query(default=240, ge=1, le=10000),  # 240 = 1h @ 15s
    since: Optional[str] = Query(
        default=None,
        description="ISO timestamp; return only rows STRICTLY AFTER it, "
        "oldest-first — incremental polling, same contract as /api/readings.",
    ),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"readings": [], "count": 0}
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since: not an ISO datetime")
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
    rows = await dao.solar_since(source_id, since_dt, limit)
    for r in rows:
        ts = r.get("ts")
        if ts is not None and hasattr(ts, "isoformat"):
            r["ts"] = ts.isoformat().replace("+00:00", "Z")
    return {"readings": rows, "count": len(rows)}


@app.get("/api/solar/series")
async def api_solar_series(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0, gt=0, le=24 * 400),
    bucket_s: int = Query(default=300, ge=15, le=86400),
    before: Optional[str] = Query(default=None),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Bucketed solar series — history_series's solar sibling. Egress is
    bounded by bucket_s regardless of underlying row count."""
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"series": [], "bucket_s": bucket_s}
    until = datetime.now(timezone.utc)
    if before:
        try:
            until = datetime.fromisoformat(before.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(422, "before: not an ISO datetime")
    src = await _resolve_solar_source(dao, source_id)
    if src is None:
        return {"series": [], "bucket_s": bucket_s}
    since = max(until - timedelta(hours=hours), SYSTEM_EPOCH)
    rows = await dao.solar_series(src, since, until, bucket_s)
    return {"series": _rows_out(rows), "bucket_s": bucket_s, "source_id": src}


@app.get("/api/xanbus_events")
async def api_xanbus_events(
    source_id: Optional[str] = Query(default=None),
    event: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"events": [], "count": 0}
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "since: not an ISO datetime")
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
    rows = await dao.recent_xanbus_events(source_id, event, since_dt, limit)
    return {"events": _rows_out(rows), "count": len(rows)}


async def _resolve_solar_source(
    dao: "AsyncpgReadingsDAO", source_id: Optional[str]
) -> Optional[str]:
    if source_id:
        return source_id
    rows = await dao.solar_since(None, None, 1)
    return rows[0].get("source_id") if rows else None


@app.get("/api/solar/energy")
async def api_solar_energy(
    source_id: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=400),
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Daily energy ledger with the solar split (production physics-inferred
    where the MPPT under-reports — see db.solar_energy_daily)."""
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"days": [], "tz": settings.display_tz}
    src = await _resolve_solar_source(dao, source_id)
    if src is None:
        return {"days": [], "tz": settings.display_tz}
    rows = await dao.solar_energy_daily(src, days, settings.display_tz)
    return {"days": _rows_out(rows), "tz": settings.display_tz, "source_id": src}


@app.get("/api/solar/dc_load")
async def api_dc_load(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0, gt=0, le=24 * 30),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Characterise the unmetered DC load (the fridge) from dark-hours data.
    Measured, not modelled — see db.dc_load_profile."""
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"profile": {}}
    src = await _resolve_solar_source(dao, source_id)
    if src is None:
        return {"profile": {}}
    return {"profile": await dao.dc_load_profile(src, hours), "source_id": src}


@app.get("/api/solar/load_heatmap")
async def api_solar_load_heatmap(
    source_id: Optional[str] = Query(default=None),
    days: int = Query(default=21, ge=1, le=120),
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not isinstance(dao, AsyncpgReadingsDAO):
        return {"cells": [], "tz": settings.display_tz}
    src = await _resolve_solar_source(dao, source_id)
    if src is None:
        return {"cells": [], "tz": settings.display_tz}
    rows = await dao.load_heatmap(src, days, settings.display_tz)
    return {"cells": _rows_out(rows), "tz": settings.display_tz, "source_id": src}


# The current logger/hardware went live 2026-06-29; a handful of stray
# readings predate it (an old bring-up rig). History views floor their range
# here so the "90 d" / "all" spans aren't padded with a ~6-week empty gap.
SYSTEM_EPOCH = datetime(2026, 6, 29, tzinfo=timezone.utc)

# Alarm bit map — mirrors volthium/pack.py::_ALARM_BITS (the server can't import
# the reader package). problem_code carries status-word bits 2-11.
_ALARM_BITS: tuple[tuple[int, str], ...] = (
    (0x004, "cell_overvoltage"), (0x008, "cell_undervoltage"),
    (0x010, "charge_overcurrent"), (0x020, "short_circuit"),
    (0x040, "discharge_overcurrent_1"), (0x080, "discharge_overcurrent_2"),
    (0x100, "charge_overtemp"), (0x200, "charge_undertemp"),
    (0x400, "discharge_overtemp"), (0x800, "discharge_undertemp"),
)


def _decode_alarms(code: Optional[int]) -> list[str]:
    if not code:
        return []
    return [name for bit, name in _ALARM_BITS if code & bit]


# --- history / analytics ----------------------------------------------------
# Read-only aggregate endpoints behind the /history page. All follow the
# /api/events pattern: real SQL lives on AsyncpgReadingsDAO; with any other
# DAO (tests) they return well-formed empty shapes.

def _iso_z(v):
    """Datetime/date → wire string; passthrough for everything else."""
    if hasattr(v, "isoformat"):
        s = v.isoformat()
        return s.replace("+00:00", "Z") if "T" in s else s
    return v


def _rows_out(rows: list[dict]) -> list[dict]:
    return [{k: _iso_z(v) for k, v in r.items()} for r in rows]


async def _resolve_source(dao: ReadingsDAO, source_id: Optional[str]) -> Optional[str]:
    if source_id:
        return source_id
    rows = await dao.recent(None, 1)
    return rows[0].get("source_id") if rows else None


@app.get("/api/history/series")
async def api_history_series(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0, gt=0, le=24 * 400),
    bucket_s: int = Query(default=300, ge=10, le=86400),
    before: Optional[str] = Query(default=None,
                                  description="ISO end of range (default now)"),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Bucketed min/avg/max series for the range explorer. `before` lets the
    page zoom to a past window (e.g. one day clicked in the energy ledger)."""
    until = datetime.now(timezone.utc)
    if before:
        try:
            until = datetime.fromisoformat(before.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(422, "before: not an ISO datetime")
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"series": [], "bucket_s": bucket_s}
    since = max(until - timedelta(hours=hours), SYSTEM_EPOCH)
    rows = await dao.history_series(src, since, until, bucket_s)
    return {"series": _rows_out(rows), "bucket_s": bucket_s, "source_id": src}


@app.get("/api/history/daily")
async def api_history_daily(
    source_id: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=400),
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Per-local-day energy ledger (Wh in/out, SOC + temp range, coverage)."""
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"days": [], "tz": settings.display_tz}
    rows = await dao.history_daily(src, days, settings.display_tz)
    return {"days": _rows_out(rows), "tz": settings.display_tz, "source_id": src}


@app.get("/api/history/profile")
async def api_history_profile(
    source_id: Optional[str] = Query(default=None),
    days: int = Query(default=14, ge=1, le=400),
    dao: ReadingsDAO = Depends(get_dao),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Average power by local hour-of-day — the pack's daily rhythm."""
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"profile": [], "tz": settings.display_tz}
    rows = await dao.history_profile(src, days, settings.display_tz)
    return {"profile": _rows_out(rows), "tz": settings.display_tz, "source_id": src}


@app.get("/api/history/gaps")
async def api_history_gaps(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0 * 30, gt=0, le=24 * 400),
    min_gap_s: float = Query(default=300.0, ge=60.0),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Telemetry outages in the window, each decorated with the wedge
    classification the reader recorded nearest the gap start (if any) —
    so the timeline can say WHY, not just when."""
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"gaps": []}
    since = max(datetime.now(timezone.utc) - timedelta(hours=hours), SYSTEM_EPOCH)
    gaps = await dao.history_gaps(src, since, min_gap_s)
    wedges = await dao.recent_events(src, "wedge_snapshot", since, limit=500)
    for g in gaps:
        cls = None
        for w in wedges:
            wts = w.get("ts")
            try:
                wdt = datetime.fromisoformat(str(wts).replace("Z", "+00:00"))
            except ValueError:
                continue
            # Wedge evidence may land shortly after readings resume (upload
            # latency), so accept a 15-min tail past the gap end.
            if g["gap_start"] <= wdt and (
                g["gap_end"] is None
                or wdt <= g["gap_end"] + timedelta(minutes=15)
            ):
                cls = (w.get("data") or {}).get("classification")
                break
        g["classification"] = cls
    return {"gaps": _rows_out(gaps), "source_id": src}


@app.get("/api/history/charger_intervals")
async def api_history_charger_intervals(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0, gt=0, le=24 * 400),
    before: Optional[str] = Query(default=None),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Absolute [start, end, battery] charger sessions for the imbalance-chart
    overlay — resolution-independent, so a short balance session shades at any
    zoom level (the bucketed charger_frac dilutes below threshold when coarse)."""
    until = datetime.now(timezone.utc)
    if before:
        try:
            until = datetime.fromisoformat(before.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(422, "before: not an ISO datetime")
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"intervals": []}
    since = max(until - timedelta(hours=hours), SYSTEM_EPOCH)
    intervals = await dao.history_charger_intervals(src, since, until)
    return {"intervals": _rows_out(intervals), "source_id": src}


@app.get("/api/history/alarms")
async def api_history_alarms(
    source_id: Optional[str] = Query(default=None),
    hours: float = Query(default=24.0 * 400, gt=0, le=24 * 400),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Alarm episodes (decoded from stored problem_code), newest first."""
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"alarms": []}
    since = max(datetime.now(timezone.utc) - timedelta(hours=hours), SYSTEM_EPOCH)
    episodes = await dao.history_alarms(src, since)
    out = []
    for e in episodes:
        d = dict(e)
        d["flags"] = _decode_alarms(d.get("codes"))
        out.append(d)
    out.reverse()  # newest first
    return {"alarms": _rows_out(out), "source_id": src}


@app.get("/api/history/stats")
async def api_history_stats(
    source_id: Optional[str] = Query(default=None),
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
    """Lifetime records: totals and extremes with their timestamps."""
    src = await _resolve_source(dao, source_id)
    if src is None or not isinstance(dao, AsyncpgReadingsDAO):
        return {"stats": None}
    stats = await dao.history_stats(src)
    return {
        "stats": {k: _iso_z(v) for k, v in stats.items()} or None,
        "source_id": src,
    }


# --- dashboard ------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    """The live screen: SOC hero + power flow. Promoted from /v2 on
    2026-08-06 after a week of running alongside the old page."""
    return FileResponse(STATIC_DIR / "v2.html")


@app.get("/history")
async def history_page() -> FileResponse:
    """Daily energy ledger, load heatmap, cell-imbalance drift, events."""
    return FileResponse(STATIC_DIR / "v2-history.html")


# The pre-2026-08 pages. Kept reachable rather than deleted: they read the
# same API, so they are a zero-cost second opinion if the new screen ever
# shows something implausible.
@app.get("/v1")
async def v1_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/v1/history")
async def v1_history_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "history.html")


# Old links keep working.
@app.get("/v2")
async def v2_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "v2.html")


@app.get("/v2/history")
async def v2_history_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "v2-history.html")
