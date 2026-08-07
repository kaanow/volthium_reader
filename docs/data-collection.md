# What we collect, and why

Reviewed 2026-08-07. The test applied to each stream was blunt: **name
something it taught us.** Streams that could not answer were pruned or bounded.

## Keep — these have paid for themselves

| stream | rate | what it bought |
|---|---|---|
| `solar_readings` (15 s buckets, CAN) | 5760 rows/day | The whole latch story. `pv_v_min`/`pv_v_max` in particular exposed the sensor dither that was defeating the detector. |
| `readings` (5 s, RS485 BMS) | 17k rows/day | `pack_p` is the only trustworthy DC power meter. `dv_a`/`dv_b` found the 100%-SOC imbalance cliff. `soc_a`/`soc_b` settled the rebalance question. |
| `chg_stage` / `chg_target` | ~350/day | Edge-triggered, and genuinely busy — ~40 bulk↔not_charging cycles in 11 h. `chg_target` is how we noticed the 28.6 V reported target vs the 28.0 V config. |
| latch guard events | a few/day | The entire Unknown #2 record: detection, fix, verification, and the night-bounce bug. |
| `xanbus_config_watch` | 1/hour, silent unless changed | Nothing yet — but it is insurance against a 4.0 V/cell equalize setting returning unnoticed. Silence is the product. |
| Modbus poll (`data/modbus/`) | 21 MB, self-rotating | Decoded the whole daily/weekly/monthly counter block via the midnight rollover (#6). |
| Raw CAN capture (`data/xanbus/`) | 65 MB/day | Every PGN decode came from here. Self-bounds at `KEEP_GZ=1000` ≈ 1.3 GB / ~22 days against 47 GB free — checked, not assumed. |

## Pruned 2026-08-07

**`ac_load_sample`** — was 288 records/day, **45% of the entire event stream**,
every one of them zeros. The `assoc 0x33` decode does not work: it reports
0 V / 0 A while the inverter is demonstrably producing AC. Now edge-triggered
with a 6 h heartbeat (~4/day). Kept rather than deleted because if that decode
ever starts working it is the cabin AC load we have no other way to see —
silent while broken, loud the moment it isn't, and the heartbeat stops silence
from being ambiguous between "unchanged" and "gone".

**`data/uploader.log`** — plain `FileHandler`, had reached 45 MB and rising at
one line per upload every 5 s, forever. Now rotates at 5 MB × 2.

## Deliberately NOT added

Every open hunch is already answerable from what exists, so a new logger would
add cost without adding information:

- **Meter-offset drift** (is the 33 W BMS-vs-inverter gap stable?) — derive
  from `readings` + `solar_readings` over any dark, fridge-off window.
- **Tracker starting state** (the dusk-bounce hypothesis, #41) — `pv_v` at
  first light is already in `solar_readings`; whether a bounce happened is in
  the guard events.
- **Cell-imbalance trend** — `dv_a` vs `soc_a` is already there, and that is
  exactly how the 100% cliff was found.

The gap in this system was never coverage. It was **retention and noise**.

## The rule that keeps earning

Prefer **same-meter comparisons** over cross-meter arithmetic. Every derivation
that differenced the BMS against the inverter was wrong (the `/v2` dark path,
the daily ledger, one hand analysis); the one that compared `pack_p` against
itself — `dc_load_profile`'s Otsu split — was right. When a question can be
posed as "has this meter changed" rather than "do these two meters agree", pose
it that way.
