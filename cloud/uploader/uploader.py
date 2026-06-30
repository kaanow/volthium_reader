"""Pi-side cloud uploader — tails data/pack.csv and POSTs new rows to Railway.

Runs as a sibling to scripts/log.py. The two are decoupled: log.py owns the
CSV, this script just reads it. If Railway is down or the Pi is offline, the
uploader catches up automatically when it can — the CSV is the durable buffer.

Design notes:
  - Source-of-truth state is a small JSON file next to the CSV:
        data/pack.csv.cloud_state  →  {"offset_bytes": int, "inode": int}
    The inode catches CSV rotation (log.py archives the file on schema
    drift); a smaller current size catches manual truncation.
  - Batches up to BATCH_SIZE rows per POST. Less chatty, easier on the
    Railway free-tier rate limits.
  - Timestamps: pack.csv stores naive LOCAL time. We attach the system's
    local tz here and convert to UTC for the wire (per
    docs/cloud_architecture.md).
  - Cell-voltage columns: pack.csv has 4 columns per battery. We collapse
    them into a list[float] on the wire (or None if all empty).

Run:
    .venv/bin/python -m cloud.uploader.uploader \\
        --csv data/pack.csv \\
        --url https://volthium.up.railway.app \\
        --source-id pi-barge
    # token comes from $READER_TOKEN env var
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx


log = logging.getLogger("volthium-uploader")


BATCH_SIZE = 60
POLL_INTERVAL_S = 5.0
HTTP_TIMEOUT_S = 30.0


def _local_to_utc_z(naive_local_iso: str) -> str:
    """Convert pack.csv's naive local ISO timestamp to wire-format UTC `Z`.

    Pack.csv stamps with `datetime.now().isoformat(timespec='seconds')` — no tz.
    The host's current timezone tells us what zone that was; we attach it,
    then convert to UTC.
    """
    # Parse the naive string, then attach the LOCAL tz (whatever the host's
    # current offset happens to be). `astimezone()` with no arg attaches local.
    dt = datetime.fromisoformat(naive_local_iso)
    if dt.tzinfo is None:
        # `.astimezone()` on a naive dt attaches LOCAL tz (Python 3.6+).
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _maybe_float(v: Optional[str]) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _maybe_int(v: Optional[str]) -> Optional[int]:
    if v in (None, "", "None"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _collect_cells(row: dict, side: str) -> Optional[list[float]]:
    """Return [c1,c2,c3,c4] for side ∈ {'a','b'}, or None if all are missing."""
    vals = []
    for i in range(1, 5):
        v = _maybe_float(row.get(f"cell_{side}_{i}"))
        if v is not None:
            vals.append(v)
    return vals or None


def csv_row_to_wire(row: dict) -> dict:
    """Project one pack.csv row into the wire payload.

    Maps:
      delta_v_a/_b (V, in CSV)  →  delta_v_a/_b (V, on wire)  — same units.
      cell_a_1..4 / cell_b_1..4 (CSV columns)  →  cell_voltages_a/_b (lists).
    """
    return {
        "ts": _local_to_utc_z(row["ts"]),
        "state": row.get("state") or None,
        "v_a": _maybe_float(row.get("v_a")),
        "v_b": _maybe_float(row.get("v_b")),
        "i_a": _maybe_float(row.get("i_a")),
        "i_b": _maybe_float(row.get("i_b")),
        "soc_a": _maybe_float(row.get("soc_a")),
        "soc_b": _maybe_float(row.get("soc_b")),
        "t_a": _maybe_float(row.get("t_a")),
        "t_b": _maybe_float(row.get("t_b")),
        "remaining_ah_a": _maybe_float(row.get("remaining_ah_a")),
        "remaining_ah_b": _maybe_float(row.get("remaining_ah_b")),
        "delta_v_a": _maybe_float(row.get("delta_v_a")),
        "delta_v_b": _maybe_float(row.get("delta_v_b")),
        "name_a": row.get("name_a") or None,
        "name_b": row.get("name_b") or None,
        "problem_code_a": _maybe_int(row.get("problem_code_a")),
        "problem_code_b": _maybe_int(row.get("problem_code_b")),
        "cell_voltages_a": _collect_cells(row, "a"),
        "cell_voltages_b": _collect_cells(row, "b"),
    }


# --- state file ----------------------------------------------------------

def _state_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(csv_path.suffix + ".cloud_state")


def load_state(csv_path: Path) -> dict:
    p = _state_path(csv_path)
    if not p.exists():
        return {"offset_bytes": 0, "inode": None}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"offset_bytes": 0, "inode": None}


def save_state(csv_path: Path, state: dict) -> None:
    p = _state_path(csv_path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(p)


# --- reader --------------------------------------------------------------

def _read_header_line(path: Path) -> list[str]:
    """Pull the header line from the start of the file as a parsed list."""
    with path.open("rb") as f:
        first_bytes = f.readline()
    return next(csv.reader([first_bytes.decode("utf-8", errors="replace").rstrip("\n")]))


def read_new_rows(csv_path: Path, state: dict, max_rows: int) -> tuple[list[dict], dict]:
    """Read up to `max_rows` new rows since the last persisted offset.
    Returns (rows, new_state). On any rotation/truncation, resets to 0.

    Implementation note: we read raw bytes from `offset` to EOF and split on
    newlines ourselves, summing byte lengths as we consume rows. This lets
    us cap at max_rows AND know the resulting byte offset to persist — a
    plain `csv.DictReader` over the file object disables `f.tell()` after
    its first `next()`, so it can't checkpoint mid-batch.
    """
    if not csv_path.exists():
        return ([], state)

    st = csv_path.stat()
    inode = st.st_ino
    size = st.st_size

    # Rotation / truncation detection — reset offset.
    if state.get("inode") is not None and state["inode"] != inode:
        log.warning("CSV inode changed (rotation) — resetting offset")
        state = {"offset_bytes": 0, "inode": inode, "header": None}
    elif size < state.get("offset_bytes", 0):
        log.warning("CSV shrank (truncation) — resetting offset")
        state = {"offset_bytes": 0, "inode": inode, "header": state.get("header")}
    else:
        state = dict(state)
        state["inode"] = inode

    offset = state.get("offset_bytes", 0)
    header = state.get("header")

    if size == offset:
        return ([], state)

    # Ensure we have the header cached, regardless of resume vs first read.
    if header is None:
        header = _read_header_line(csv_path)
        state["header"] = header
        # If offset was 0, advance past the header so we don't reparse it.
        if offset == 0:
            with csv_path.open("rb") as f:
                first_bytes = f.readline()
            offset = len(first_bytes)

    rows: list[dict] = []
    consumed_bytes = 0
    with csv_path.open("rb") as f:
        f.seek(offset)
        for raw in f:
            consumed_bytes += len(raw)
            line = raw.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
            if not line:
                continue
            try:
                values = next(csv.reader([line]))
            except StopIteration:
                continue
            row = dict(zip(header, values))
            rows.append(row)
            if len(rows) >= max_rows:
                break

    state["offset_bytes"] = offset + consumed_bytes
    return (rows, state)


# --- main loop -----------------------------------------------------------

async def post_batch(client: httpx.AsyncClient, url: str, body: dict, token: str) -> tuple[bool, str]:
    """POST one batch. Returns (success, message). Does not raise."""
    try:
        resp = await client.post(
            url.rstrip("/") + "/ingest",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        return (False, f"network error: {type(e).__name__}: {e}")
    if resp.status_code != 200:
        snippet = resp.text[:200]
        return (False, f"HTTP {resp.status_code}: {snippet}")
    try:
        payload = resp.json()
    except ValueError:
        return (False, f"non-JSON 200 response: {resp.text[:120]}")
    return (True, f"accepted={payload.get('accepted')} dup={payload.get('duplicates')}")


async def run(args, token: str) -> None:
    state = load_state(args.csv)
    consec_errors = 0
    async with httpx.AsyncClient() as client:
        while True:
            try:
                rows, next_state = read_new_rows(args.csv, state, BATCH_SIZE)
            except Exception as exc:
                log.warning("CSV read error: %s: %s", type(exc).__name__, exc)
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            if not rows:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            wire_rows = []
            for r in rows:
                try:
                    wire_rows.append(csv_row_to_wire(r))
                except Exception as exc:
                    log.warning("skipping malformed row (%s): %s", type(exc).__name__, exc)

            if not wire_rows:
                # All rows were unparseable — advance offset so we don't loop.
                state = next_state
                save_state(args.csv, state)
                continue

            body = {"source_id": args.source_id, "readings": wire_rows}

            if args.dry_run:
                log.info("[dry-run] would POST %d rows (first ts=%s, last ts=%s)",
                         len(wire_rows), wire_rows[0]["ts"], wire_rows[-1]["ts"])
                # In-memory advance only — do NOT persist. A dry-run must be
                # idempotent: re-running it shouldn't shift where the live
                # uploader will start. Switching to live mode after a dry-run
                # picks up from offset 0 as expected.
                state = next_state
                continue

            ok, msg = await post_batch(client, args.url, body, token)
            if ok:
                log.info("uploaded %d rows: %s", len(wire_rows), msg)
                state = next_state
                save_state(args.csv, state)
                consec_errors = 0
            else:
                consec_errors += 1
                log.warning("upload failed (%d in a row): %s", consec_errors, msg)
                # Exponential backoff capped at 5 min — keep retrying forever.
                await asyncio.sleep(min(300.0, 5.0 * consec_errors))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", type=Path, required=True,
                    help="path to pack.csv (the same one scripts/log.py writes)")
    ap.add_argument("--url", required=True, help="Railway base URL, e.g. https://x.up.railway.app")
    ap.add_argument("--source-id", required=True, help="source identifier, e.g. pi-barge")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + print but don't POST; useful for first runs")
    ap.add_argument("--log", type=Path, help="optional log file")
    args = ap.parse_args(argv)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if args.log:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )

    token = os.environ.get("READER_TOKEN", "")
    if not args.dry_run and not token:
        log.error("READER_TOKEN env var is empty — refusing to upload without auth")
        return 2

    try:
        asyncio.run(run(args, token))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
