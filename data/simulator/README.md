# Raw BMS frame corpus

`pi-barge_raw_frames.jsonl` — 3,921 raw BLE notify frames captured from the
two Barge-Inn batteries between 2026-07-01 and 2026-07-09, exported from the
Railway `ble_events` table (`event='raw_frame'`) via `/api/events`.

## Schema

One JSON object per line, sorted ascending by `ts`:

```
{
  "ts":       "2026-07-01T17:33:15.879000Z",   // capture time (UTC Z)
  "source_id":"pi-barge",                       // reader that captured it
  "address":  "09:01:00:11:55:DF",              // battery BLE address
  "direction":"rx",                             // notify chunks are only ever rx
  "data_hex": "3a30303832333130303843…",        // notify chunk payload (hex)
  "data_len": 20                                // byte count of that chunk
}
```

## Reconstruction

BLE notify chunks arrive in 20-byte pieces; the BMS record framing is
`:...<hex>...~` (colon-prefixed ASCII-hex, `~` = 0x7e = record terminator).
Concatenate all `rx` payloads for one address in `ts` order, then split on
`b"\x7e"` to recover the record stream:

```python
import json
frames = [json.loads(l) for l in open("pi-barge_raw_frames.jsonl")]
def records_for(addr):
    hexblob = "".join(f["data_hex"] for f in frames
                      if f["address"] == addr and f["direction"] == "rx")
    return [r.decode("ascii", errors="replace")
            for r in bytes.fromhex(hexblob).split(b"\x7e") if r]
```

Both batteries yield ~275 complete `:008231008C…` records — the E&J
Technology master status frame that carries pack voltage, current, SOC,
per-cell voltages, temperatures, cycle count and fault code in one shot.

## Why this exists

Enough real-world material to build an offline BMS simulator (a mock
`BleakClient` that replays these frames on demand), so the reader path
and estimator can be exercised without live batteries. Capture is currently
**off** on the Pi — flip `VOLTHIUM_CAPTURE_RAW=1` on the logger unit if a
future run needs to grow the corpus (e.g. capturing a charging-cycle span).
