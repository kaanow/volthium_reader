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
    GET  /                 — browser dashboard (static HTML; polls /api/readings).

Env vars: see cloud/server/config.py.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from cloud.server.config import Settings, load_settings
from cloud.server.db import AsyncpgReadingsDAO, ReadingsDAO, create_pool
from cloud.server.derive import derive
from cloud.shared.wire import (
    BleEventBatch,
    BleEventIngestResponse,
    IngestBatch,
    IngestResponse,
    Reading,
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
    _state["dao"] = AsyncpgReadingsDAO(pool)
    log.info(
        "ready: tokens=%d, alpha=%.2f, capacity=%.0fAh, floor=%.0f%%, ceil=%.0f%%",
        len(settings.tokens), settings.ema_alpha, settings.capacity_ah,
        settings.floor_soc, settings.ceiling_soc,
    )
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="Volthium Cloud", lifespan=lifespan)


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
    dao: ReadingsDAO = Depends(get_dao),
) -> dict:
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


# --- dashboard ------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
