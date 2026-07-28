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
| **126990** | ChgSts | **chg_setpoint_V i32@2 ÷1000, chg_limit_I i32@6 ÷1000** (charger config setpoints — MPPT reads 29.80 V / 60.00 A; source: CANaconda Xanbus.xml, validated 2026-07-28), **chg_mode u16@12** (768 base: 769 bulk / 770 absorb / 773 float; NB offset is 12, not 13 as previously written) | HIGH |
| **127165** | InvSts2 | `<BBHBB`: **inverter_status u16@2** (1024 base: 1024 invert / 1025 AC-passthru) | HIGH |
| **129033** | DateTimeSts | `<BIhx`: epoch-seconds u32@1, tz-offset-min s16@5 | HIGH |
| **127003** | BattMonSts | `<BBIiHHHbbH`: V u32@2, I s32@6, temp u16@10, cap_removed u16@12, cap_remain u16@14, **SOC s8@16**, ttd-min u16@18 | HIGH (only if a BattMon exists — ours doesn't) |
| **127166** | "MPPT Data" | **>16-frame fast-packet**, cumulative energy counters — *undecoded by berrybms*; partial field offsets via our correlation (see below) | LOW/PARTIAL |

## Validation on our hardware (`xanbus_reader.py --validate`, 46 h corpus)

- **Battery voltage — confirmed exact.** CAN 127172 vs Modbus `90:79` match on
  both peak (27.66 / 27.55 V) and daytime median (27.04 / 27.02 V), **r = +0.98**.
  Decode airtight.
- **PV array voltage — confirmed.** CAN 127173 `assoc 0x15` decodes a real array
  voltage (dawn peak ~99–119 V, pulled down toward the MPP as the MPPT loads it).
  Modbus mirror: `30:76/77` = u32 mV (76 = high word) — tracked the same 0→65 V
  dawn ramp on 2026-07-28.
- **PV-input current/power — DO NOT EXIST on this hardware (resolved 2026-07-28).**
  During a morning that peaked at **134 W / 5 A delivered to the battery**, the
  `assoc 0x15` I/P fields stayed hard-zero on the wire (raw bytes `00`), and the
  Insight Home's own Modbus PV-current regs `30:78/79` were zero too. The
  **MPPT 60 150 does not measure PV-side current on any interface** (berrybms's
  unit that populates these is a bigger MPPT; ours also sends a 21-byte 0x15
  payload vs their 27). **Solar production = the MPPT output channel**: 127173
  `assoc 0x03` from src 1 — self-consistent (V×I=W ✓, e.g. 26.54 V × 1.43 A ≈ 37 W)
  and pure CAN. Drop `pv_I/pv_W` from the field list; keep `pv_V` for array
  diagnostics; `mppt_out_I/W` is *the* production field.
- **Bonus (Modbus, for reference only): MPPT energy counters.** `30:131/135/139/143`
  are cumulative Wh counters at different epochs (all ticked +115 Wh across the
  2026-07-28 morning); `30:133/137` count operating-seconds; `30:127` ≈ output W.
  These label the CAN 127166 correlation if we ever bother — or just integrate
  `mppt_out_W`.

## Fast-packet reassembly — a note (and our contribution to berrybms)

berrybms reassembles with a **nibble split** (`seq = b0>>4`, `frame = b0&0x0F`),
which caps at 16 frames; their code explicitly notes this **cannot reassemble
PGN 127166**, which sends >16 frames. Our decoder uses the **standard NMEA2000
split** (`seq = b0>>5`, `frame = b0&0x1F`, up to 32 frames), which handles 127166.
For the short priority PGNs (127172/127173, ≤16 frames) both splits reassemble
identically — verified. See `docs/xanbus-berrybms-contribution.md`.

## Association IDs — officially confirmed (2026-07-28)

The `assoc` byte in DcSrcSts2/BattSts2/AcStsRms/ChgSts is Xantrex's official
association-ID enum, leaked via the Freedom SW-RVC DGN Reference Guide
(976-0452-01-01, which documents the shared XanBus library's `XB_eAC_SRC_ID` /
`XB_eDC_SRC_ID` tables). Our empirically-observed values match it exactly:

| assoc | enum | our usage |
|---|---|---|
| 0x03 (3) | HOUSE_BAT_BANK1 / SHORE1 | battery DC channel |
| 0x13 (19) | GEN1 | generator AC input (so the gen fields are official, not inferred) |
| 0x15 (21) | SOLAR_ARRAY1 | PV array channel |
| 0x33 (51) | AC_LOAD1 | AC output / loads |
| 0x43 (67) | GRID1 | AC1 grid input (dead on our barge) |

Full enums (SHORE1..16=3..18, GEN1..16=19..34, AC1..16=35..50, AC_LOAD=51..66,
GRID=67..82; DC: HOUSE_BAT 3..8, START_BAT 9..14, SOLAR_ARRAY 21..36) in the
guide, along with the NAME-seeded CRC-CCITT that protects *writes* (we only
listen). Key research refs:

- Freedom SW-RVC DGN Guide: xantrex.com/wp-content/uploads/2022/09/Freedom-SW-RVC-DGN-Reference-Guide-976-0452-01-01_Rev-B_ENG.pdf
- FXCC NMEA2000 PGN list (DD/DF-coded proprietary PGN tables): xantrex.com/wp-content/uploads/2021/12/976-0422-01-01_Rev-ANMEA2000-PGN-List-for-FXCC_ENG.pdf
- CANaconda Xanbus.xml (ChgSts control V/I definition): github.com/xela144/CANaconda
- Unexhausted lead for the remaining unknowns (127005/126991/127166/127167/
  127174/127177 — no public source defines them): XWConfig / Conext Config Tool
  installer or InsightHome/ComBox firmware likely embeds the machine-readable
  PGN dictionary ("PyXanBus" lineage, per tomlightfoot.ca/engineering/xantrex/).
- Known bad source: cod-xio/XanBus2Can on GitHub is AI-fabricated (claims
  Xanbus is RS485, invents PGNs). Ignore it.

## Modbus ground-truth register map (anchors)

Schneider Conext maps list registers by raw 0-based PDU address; there is a
well-known ±1 addressing quirk. Empirically on our reader:

- **SW inverter (90):** battery V @ `79` (÷1000, confirmed 26.5 V), battery I @
  `81` (s32 ÷1000), battery P @ `83`, charger stage @ `85` (768 base), load AC
  power @ `133`.
- **MPPT 60 150 (30):** PV array V @ `76` (÷1000, tracks CAN r0.9), PV I @ `78`,
  PV power @ `80`, charger stage @ `73`/`74`, energy-from-PV counters ~`103`+.

## What's left

1. ~~Finalize PV I/P scale~~ **Resolved 2026-07-28**: the fields don't exist on
   this MPPT; production comes from the `assoc 0x03` output channel instead.
2. **Correlation-decode 127166** cumulative energy (daily/lifetime kWh yield),
   labelled via the Modbus energy registers (`30:131` +siblings) — nice-to-have;
   can also be had by integrating `mppt_out_W`.
3. **Build the live reader path** (`xanbus_reader.py` live mode reads can0
   directly, streaming — safe to run on the Pi) and cut telemetry over to it.
4. **Retire the Insight Home** once the reader is trusted.
