# Xanbus decoding — retiring the Insight Home

**Goal:** read the solar/inverter telemetry we currently get from the Insight
Home's Modbus/TCP server directly off the raw Xanbus (Schneider Conext CAN
network), so the Insight Home can be retired.

**Status (2026-07-27): essentially solved for the priority fields.** Both halves
of the puzzle are now known rather than guessed, and the key layouts are
validated against our own hardware. Battery + PV instantaneous power decode from
known layouts; only the cumulative energy counters (PGN 127166) still need
correlation.

## How we got here — two independent sources + our own validation

1. **CAN field layouts** come from [`extrafu/berrybms`](https://github.com/extrafu/berrybms),
   a GPLv3 project that sniffs a live Conext Xanbus and had already
   reverse-engineered these exact PGNs. (Our PGNs are absent from the canboat
   database and are not standard NMEA2000 — Schneider squats on unassigned
   *standard* PDU2 numbers 126990–127177, so no published NMEA layout covers
   them.)
2. **Modbus register meanings** come from Schneider's Conext Modbus Maps (SW =
   doc 503-0244, MPPT 60 150 = 503-0248), cross-checked against a machine-parsed
   gist and live code (`shorawitz/conext-api`).
3. **We validated (1) against (2)** on our own capture corpus by correlation:
   `scripts/xanbus_reader.py --validate` decodes each CAN field and correlates it
   against the Schneider-mapped Modbus register.

The capture services stay on the Pi; **all decoding runs OFF the Pi** against a
corpus pulled by `scripts/pull_captures.sh` (decoding on the 1 GB Pi caused the
2026-07-26 outage — see `CLAUDE.md`).

## The bus — 2 source nodes

`src 0` = Conext SW 4024 inverter, `src 1` = Conext MPPT 60 150 charge
controller (also `src 2` seen only in ISO Address Claims). Modbus slaves:
gateway = 1, MPPT60 = **30**, SW inverter = **90** (BattMon 190 returns no data —
there is **no separate battery monitor**, so there is no Conext coulomb-counted
SOC; we already get SOC from the Volthium BMS over RS485).

## Confirmed CAN field layouts

Offsets are into the **reassembled fast-packet payload** (header stripped). All
little-endian. Voltage/current raw ÷1000; power raw = W; temp = raw ÷100 − 273.

| PGN | Name | Field layout | Confidence |
|---|---|---|---|
| **127172** | BattSts2 (battery DC) | `<BBIii`: status u8@0, **assoc u8@1**, **V u32@2 ÷1000**, **I s32@6 ÷1000**, **P s32@10** | HIGH — validated |
| **127173** | DcSrcSts2 (DC source) | same `<BBIii`; **assoc@1 = 0x03 battery / 0x15 PV array** | HIGH — validated |
| **126990** | ChgSts | `<BB…HB`: **chg_mode u16@13** (768 base: 769 bulk / 770 absorb / 773 float) | HIGH |
| **127165** | InvSts2 | `<BBHBB`: **inverter_status u16@2** (1024 base: 1024 invert / 1025 AC-passthru) | HIGH |
| **129033** | DateTimeSts | `<BIhx`: epoch-seconds u32@1, tz-offset-min s16@5 | HIGH |
| **127003** | BattMonSts | `<BBIiHHHbbH`: V u32@2, I s32@6, temp u16@10, cap_removed u16@12, cap_remain u16@14, **SOC s8@16**, ttd-min u16@18 | HIGH (only if a BattMon exists — ours doesn't) |
| **127166** | "MPPT Data" | **>16-frame fast-packet**, cumulative energy counters — *undecoded by berrybms*; partial field offsets via our correlation (see below) | LOW/PARTIAL |

## Validation on our hardware (`xanbus_reader.py --validate`, 46 h corpus)

- **Battery voltage — confirmed exact.** CAN 127172 → 26.52 V vs Modbus `90:79`
  26.50 V, **r = +0.98**.
- **PV array voltage — confirmed.** CAN 127173 `assoc 0x15` decodes a real
  ~54 V array voltage, **r = +0.90** vs the MPPT PV-voltage register. (Day/night
  sampling makes the all-sample medians differ; daytime peaks/sweep confirm it.)
- PV current/power: layout identical to voltage; corpus skews nighttime so they
  read ~0 — a clean daytime window finalizes their scale.

## Fast-packet reassembly — a note (and our contribution to berrybms)

berrybms reassembles with a **nibble split** (`seq = b0>>4`, `frame = b0&0x0F`),
which caps at 16 frames; their code explicitly notes this **cannot reassemble
PGN 127166**, which sends >16 frames. Our decoder uses the **standard NMEA2000
split** (`seq = b0>>5`, `frame = b0&0x1F`, up to 32 frames), which handles 127166.
For the short priority PGNs (127172/127173, ≤16 frames) both splits reassemble
identically — verified. See `docs/xanbus-berrybms-contribution.md`.

## Modbus ground-truth register map (anchors)

Schneider Conext maps list registers by raw 0-based PDU address; there is a
well-known ±1 addressing quirk. Empirically on our reader:

- **SW inverter (90):** battery V @ `79` (÷1000, confirmed 26.5 V), battery I @
  `81` (s32 ÷1000), battery P @ `83`, charger stage @ `85` (768 base), load AC
  power @ `133`.
- **MPPT 60 150 (30):** PV array V @ `76` (÷1000, tracks CAN r0.9), PV I @ `78`,
  PV power @ `80`, charger stage @ `73`/`74`, energy-from-PV counters ~`103`+.

## What's left

1. **Finalize PV I/P scale** against one clean daytime window (0→peak sweep).
2. **Correlation-decode 127166** cumulative energy (daily/lifetime kWh yield),
   labelled via the Modbus energy registers — nice-to-have; can also be had by
   integrating PV power.
3. **Build the live reader path** (`xanbus_reader.py` live mode reads can0
   directly, streaming — safe to run on the Pi) and cut telemetry over to it.
4. **Retire the Insight Home** once the reader is trusted.
