"""Wire-protocol models for the Railway ingest endpoint.

Single source of truth: imported by `cloud.server` to validate incoming POSTs
AND by `cloud.uploader` to build the JSON it sends. If a column ever drifts
between the two, this module is the place to fix it — there's no parallel
schema definition anywhere else.

See `docs/cloud_architecture.md` for the on-the-wire shape and the timestamp
convention (ISO-8601 UTC with a trailing `Z`).

The future ESP32 firmware will emit the same JSON shape — keep field names
in lockstep with the C struct that builds the payload there.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Per-pack cell count for the SC12200G4DPH (12V LiFePO4 = 4 cells).
CELLS_PER_BATTERY = 4


class Reading(BaseModel):
    """A single timestamped sample. Mirrors the raw-only subset of
    `volthium.pack.BatteryReading` × 2 — the server derives anything
    computable (pack_v, pack_i, pack_p, smoothed_*, minutes_remaining).
    """

    model_config = ConfigDict(extra="forbid")

    # Device-stamped UTC, ISO-8601, trailing Z. The validator coerces it to
    # a tz-aware datetime so downstream code (asyncpg, derivation) sees a
    # real datetime — but JSON output always re-emits with the Z suffix.
    ts: datetime

    state: str   # "charging" | "discharging" | "idle" | "full" | "unknown"

    # Per-battery raw fields. Optional because the BMS occasionally drops
    # fields on a noisy link; the server stores NULL and the dashboard
    # renders a dash.
    v_a: Optional[float] = None
    v_b: Optional[float] = None
    i_a: Optional[float] = None
    i_b: Optional[float] = None
    soc_a: Optional[float] = None
    soc_b: Optional[float] = None
    t_a: Optional[float] = None
    t_b: Optional[float] = None
    remaining_ah_a: Optional[float] = None
    remaining_ah_b: Optional[float] = None
    delta_v_a: Optional[float] = None    # V (not mV — matches pack.csv)
    delta_v_b: Optional[float] = None
    name_a: Optional[str] = None
    name_b: Optional[str] = None

    # Per-battery additions confirmed for v1 (see chat 2026-06-18).
    problem_code_a: Optional[int] = None
    problem_code_b: Optional[int] = None
    # Cell voltages: a list of CELLS_PER_BATTERY floats, or None on dropouts.
    # The CSV stores them as separate columns; the wire uses arrays because
    # JSON has them natively and the ESP32 builds them as an array too.
    cell_voltages_a: Optional[List[float]] = None
    cell_voltages_b: Optional[List[float]] = None

    @field_validator("ts", mode="before")
    @classmethod
    def _parse_ts(cls, v):  # noqa: D401 — validator, not docstring-driven
        # Accept both ISO-8601 strings and datetime objects. Strings without
        # tz are rejected — per the project convention they should always
        # carry a Z. Strings with +00:00 are normalized to UTC.
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError("naive datetime — wire format requires UTC with Z")
            return v.astimezone(timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                raise ValueError("missing timezone — wire format requires UTC with Z")
            return dt.astimezone(timezone.utc)
        raise TypeError(f"unsupported ts type: {type(v).__name__}")

    @field_validator("cell_voltages_a", "cell_voltages_b")
    @classmethod
    def _check_cells(cls, v):
        if v is None:
            return v
        if len(v) > CELLS_PER_BATTERY:
            # Be lenient: trim, don't reject. A misconfigured edge firmware
            # sending too many cells is fixed in firmware; meanwhile, ingest
            # should keep flowing.
            return v[:CELLS_PER_BATTERY]
        return v


class IngestBatch(BaseModel):
    """A single POST /ingest request."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    readings: List[Reading] = Field(min_length=1, max_length=1000)


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int = 0


# --- BLE events ----------------------------------------------------------
#
# Structured diagnostic stream — every read attempt, RSSI on discovery,
# wedge signatures, and (when VOLTHIUM_CAPTURE_RAW=1) base64 raw BLE frames
# for lab replay. The reader writes these as JSONL to /run/volthium/ on the
# Pi (tmpfs), rotated into sealed segments; the events uploader drains
# sealed segments to /api/events/ingest and this table.
#
# Kept intentionally schema-loose (arbitrary `data: dict`) because the event
# taxonomy is still evolving as we learn new failure modes. Postgres JSONB
# gives us query flexibility without schema migrations for each new field.


class BleEvent(BaseModel):
    """One structured event from the reader's BLE stack."""

    model_config = ConfigDict(extra="forbid")

    # UTC-Z on the wire — same convention as Reading. Reader emits with
    # millisecond precision; server accepts any ISO-8601 that survives
    # `_parse_ts` below.
    ts: datetime

    # Event kind: scan_result, teardown, read_ok, read_fail, read_exception,
    # cycle_done, wedge_detected, force_disconnect, adapter_recovery,
    # scan_error, raw_frame, ... (schema-loose so new kinds don't need a
    # server change).
    event: str = Field(min_length=1, max_length=64)

    # All other fields flow through as a JSON blob. Postgres stores as
    # JSONB so the dashboard can filter on any field without a migration.
    data: dict = Field(default_factory=dict)

    @field_validator("ts", mode="before")
    @classmethod
    def _parse_ts(cls, v):
        # Same parsing rules as Reading.ts — kept as a separate validator
        # (rather than referencing Reading._parse_ts) because Pydantic v2
        # doesn't let field_validators be shared cleanly.
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError("naive datetime — wire format requires UTC with Z")
            return v.astimezone(timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                raise ValueError("missing timezone — wire format requires UTC with Z")
            return dt.astimezone(timezone.utc)
        raise TypeError(f"unsupported ts type: {type(v).__name__}")


class BleEventBatch(BaseModel):
    """A single POST /api/events/ingest request."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=64)
    events: List[BleEvent] = Field(min_length=1, max_length=5000)


class BleEventIngestResponse(BaseModel):
    accepted: int
