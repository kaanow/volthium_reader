"""Pi-side BLE events uploader — drains sealed segments to Railway.

Runs alongside `scripts/log.py` and the readings uploader as a third,
independent process. It only touches SEALED segment files
(`<log>.NNNN.sealed`) — never the live one being appended to — so writes and
uploads can't race.

Design:
  - No offset state. A sealed segment is one-shot: POST it all, then delete
    on success. If the POST fails, the file stays; we'll try again next tick.
  - Batches to `/api/events/ingest`, chunked to stay under the server's
    per-batch limit.
  - Never gives up. Exponential-backoff on network / server errors.
  - Owns nothing on the writer side. If the writer stops or crashes, the
    uploader just drains what's already sealed and idles.

Run:
    .venv/bin/python -m cloud.uploader.events_uploader \\
        --log-dir /run/volthium \\
        --log-base ble_events.jsonl \\
        --url https://volts.alti2.de \\
        --source-id pi-barge
    # READER_TOKEN env var required (same token as the readings uploader).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

import httpx


log = logging.getLogger("volthium-events-uploader")


# Server caps a batch at 5000 events (see cloud/shared/wire.py:BleEventBatch).
# 4000 leaves margin for future tightening without a client change.
BATCH_SIZE = 4000
POLL_INTERVAL_S = 15.0        # HARDWARE-DEP: Pi 3B — could be shorter on faster storage
HTTP_TIMEOUT_S = 60.0


def _sealed_segments(log_dir: Path, base_name: str) -> list[Path]:
    """Return sealed segment files in oldest-first order. Sealed files have
    a suffix `.NNNN.sealed` (monotonic sequence). Never returns the live
    file — the writer owns that."""
    if not log_dir.exists():
        return []
    candidates = sorted(log_dir.glob(f"{base_name}.*.sealed"))
    return candidates


def _read_events(path: Path) -> Iterable[dict]:
    """Yield parsed event dicts from a sealed segment.

    Lines that don't parse as JSON are skipped with a warning — better to
    lose a corrupt event than to loop forever on it. In practice the writer
    always emits complete lines (single write() per record) so this should
    be rare.
    """
    with path.open("r") as f:
        for i, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except Exception as exc:
                log.warning("skipping malformed event in %s line %d: %s",
                            path.name, i, exc)


def _to_wire(rec: dict) -> dict:
    """Reshape a writer-side event record into the wire schema.

    Writer emits `{"ts": ..., "event": ..., <arbitrary fields...>}` — every
    non-{ts,event} key gets folded into `data`. The wire schema is strict
    about top-level fields (`extra="forbid"` on BleEvent) so this reshape
    is mandatory.
    """
    ts = rec.get("ts")
    event = rec.get("event")
    if ts is None or event is None:
        raise ValueError("event missing ts or event")
    data = {k: v for k, v in rec.items() if k not in ("ts", "event")}
    return {"ts": ts, "event": event, "data": data}


async def _post_batch(client: httpx.AsyncClient, url: str, body: dict, token: str) -> tuple[bool, str]:
    try:
        resp = await client.post(
            url.rstrip("/") + "/api/events/ingest",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        return (False, f"network: {type(e).__name__}: {e}")
    if resp.status_code != 200:
        return (False, f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        j = resp.json()
    except ValueError:
        return (False, f"non-JSON 200: {resp.text[:120]}")
    return (True, f"accepted={j.get('accepted')}")


async def _drain_segment(
    client: httpx.AsyncClient,
    seg: Path,
    url: str,
    source_id: str,
    token: str,
) -> bool:
    """Read + POST + delete one sealed segment. Returns True on full success.
    On any failure the file is left in place for the next tick to retry."""
    wire_rows: list[dict] = []
    for rec in _read_events(seg):
        try:
            wire_rows.append(_to_wire(rec))
        except Exception as exc:
            log.warning("skipping unshapeable event in %s: %s", seg.name, exc)
    if not wire_rows:
        # Empty or all-garbage segment — drop it so we don't loop.
        log.info("empty segment, discarding: %s", seg.name)
        seg.unlink(missing_ok=True)
        return True

    total = len(wire_rows)
    for i in range(0, total, BATCH_SIZE):
        chunk = wire_rows[i:i + BATCH_SIZE]
        body = {"source_id": source_id, "events": chunk}
        ok, msg = await _post_batch(client, url, body, token)
        if not ok:
            log.warning("segment %s: batch %d/%d failed: %s",
                        seg.name, i // BATCH_SIZE + 1,
                        (total + BATCH_SIZE - 1) // BATCH_SIZE, msg)
            return False
    log.info("uploaded %s (%d events, %d batches) — deleting",
             seg.name, total, (total + BATCH_SIZE - 1) // BATCH_SIZE)
    seg.unlink(missing_ok=True)
    return True


async def run(args, token: str) -> None:
    log_dir = Path(args.log_dir)
    consec_errors = 0
    async with httpx.AsyncClient() as client:
        while True:
            segs = _sealed_segments(log_dir, args.log_base)
            if not segs:
                await asyncio.sleep(POLL_INTERVAL_S)
                continue

            ok_any = False
            for seg in segs:
                ok = await _drain_segment(client, seg, args.url, args.source_id, token)
                if ok:
                    consec_errors = 0
                    ok_any = True
                else:
                    consec_errors += 1
                    break   # don't hammer a broken pipe; try again next tick

            if ok_any:
                await asyncio.sleep(POLL_INTERVAL_S)
            else:
                # Exponential backoff, capped at 5 min — same shape as readings uploader.
                await asyncio.sleep(min(300.0, 5.0 * max(consec_errors, 1)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--log-dir", type=Path, default=Path("/run/volthium"),
                    help="directory containing sealed segments (default: /run/volthium)")
    ap.add_argument("--log-base", default="ble_events.jsonl",
                    help="base name of the log; sealed segments are <base>.NNNN.sealed")
    ap.add_argument("--url", required=True, help="Railway base URL")
    ap.add_argument("--source-id", required=True, help="source identifier, e.g. pi-barge")
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
    if not token:
        log.error("READER_TOKEN env var is empty — refusing to upload without auth")
        return 2

    try:
        asyncio.run(run(args, token))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
