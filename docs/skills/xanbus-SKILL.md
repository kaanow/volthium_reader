---
name: xanbus
description: Read and WRITE the Schneider/Xantrex Xanbus (Conext) CAN network — PGN layouts, address claim, the four-step authorization model for commanding devices, config-record writes with optimistic concurrency, and the MPPT 60 150's diode-clamp latch (detector band, the 45 V cliff, dawn/dusk hunting, suspected current-sensor root cause). Also which meters on this system can be trusted and how far. Use when touching anything on the Conext bus at Barge Inn, decoding CAN captures, writing a latch or energy detector, comparing MPPT against BMS numbers, or extending the reader/writer tooling.
---

# Xanbus (Schneider Conext) — read and write

Everything here was established empirically against real hardware at Barge Inn
(Conext SW 4024 + MPPT 60 150 + InsightHome) and verified on the wire. Where a
thing is unproven it says so.

## The bus

250 kbit/s CAN, 29-bit IDs, NMEA2000-derived. Schneider squats on unassigned
*standard* PDU2 PGN numbers (126990–127177), so canboat and the NMEA spec do
NOT describe them. Nodes at Barge Inn:

| Addr | Device | NAME function | identity |
|---|---|---|---|
| 0 | Conext SW 4024 | 129 (inverter/charger) | 454154 |
| 1 | MPPT 60 150 | 131 (charge controller) | 1682454 |
| 2 | InsightHome | 134 (gateway) | 1993246 |

All are class 30 (Power Management), industry group 0, and re-announce their
Address Claim **once per second**. The `identity` field decodes to the exact
device IDs Schneider's own UI reports — a good check that a NAME decoder is
correct.

### Parsing CAN IDs — the classic mistake

PDU1 (PF < 240) is **destination-specific**: the PS byte is the destination
and is NOT part of the PGN. PDU2 (PF ≥ 240) is broadcast and PS *is* part of
the PGN. Conflating them makes config traffic look like garbage PGNs.

```python
dp = (can_id >> 24) & 1; pf = (can_id >> 16) & 0xFF
ps = (can_id >> 8) & 0xFF; sa = can_id & 0xFF
pgn, dest = ((dp<<16)|(pf<<8), ps) if pf < 240 else ((dp<<16)|(pf<<8)|ps, 255)
```

### Fast packet

Control byte = 3-bit sequence counter + **5-bit** frame index (up to 32
frames). Frame 0 carries the total length + 6 bytes; later frames 7 each;
tail padded 0xFF. berrybms uses a 4/4 nibble split which is indistinguishable
for ≤16-frame messages but cannot reassemble PGN 127166 — we upstreamed a fix
(extrafu/berrybms PR #3).

## Reading — confirmed field layouts

Offsets are into the reassembled payload. Little-endian; V/I are ÷1000; P is W.

| PGN | Name | Fields |
|---|---|---|
| 127172 | BattSts2 | `<BBIii`: status@0, assoc@1, **V u32@2, I s32@6, P s32@10** |
| 127173 | DcSrcSts2 | same layout; **assoc@1: 0x03 = battery/output, 0x15 = PV array** |
| 126990 | ChgSts | chg_mode u16**@12** (769 bulk / 770 absorb / 773 float / 777 qualifying-AC) |
| 127165 | InvSts2 | inverter_status u16@2 (1024 invert / 1025 AC-passthrough) |
| 126998 | AcStsRms | assoc@1: 0x13 gen-in, 0x33 AC loads, 0x43 grid. 49-byte prefix stable |
| 129033 | DateTimeSts | epoch u32@1 |
| 127166 | MpptData | 60 B. **lifetime Ah u32@19, lifetime Wh u32@23, daily Ah u32@46, daily Wh u32@50** (daily pair resets 00:00:45–00:01:21 local) |

PGN 127166's pairs are identified by a ratio test that doubles as a decode
guard: `Wh/Ah` must come out as the pack voltage (~27 V). If a firmware update
moves the layout, that stops holding — check it before trusting the numbers.
Cross-validated against Modbus 30:130-131 on a second transport, mean
difference 2.96 Wh (the 10 s poll lag).

**assoc bytes are Xantrex's official enums** (leaked via the Freedom SW-RVC DGN
guide): 0x03 HOUSE_BAT_BANK1, 0x13 GEN1, 0x15 SOLAR_ARRAY1, 0x33 AC_LOAD1,
0x43 GRID1.

### Trust the right meters

- **P is computed as V×I**, not measured — verified across 942 records. It
  inherits any current-sensor error.
- The **MPPT 60 150 has no PV-side current sensor at all**: `assoc 0x15` I and
  P are structurally 0 on both CAN and Modbus. Array voltage is real.
  Production must come from the **`assoc 0x03` output channel**.
- The MPPT's **output current under-reads**, badly in some regimes (0.33 A
  while ~14 A flowed). Prefer `battery power + inverter draw` over the MPPT's
  self-report — but see the caveats below, which are newer and sharper.

**Updated 2026-08-10 — no meter here has passed an absolute check.** Treat the
old advice "the BMS shunts are the trustworthy reference" as *least bad*, not
as truth:

| meter | self-consistency | vs the others |
|---|---|---|
| MPPT output | **0.99** — accumulator matches its own instantaneous reading | reads ~22-25% low |
| BMS shunts | **0.875 / 0.890** — `remaining_ah` moves ~12% further than integrating its own current, both units, both directions | the reference, with a 12% asterisk |
| inverter `dc_w` | n/a | the outlier: claims 113 W where the BMS says 81 and the MPPT says 66 |

The BMS discrepancy is symmetric in charge and discharge, which rules out a
coulombic-efficiency correction (that would be asymmetric) and points at a
scale factor. So `pack_p` may itself be ~12% low.

Two same-instrument tests worth reusing on any new meter, because cross-meter
arithmetic on this system has been wrong every single time it was tried:
integrate the device's reported rate and compare against the device's own
accumulator; and measure in a regime where a term drops out (float with a
neutral battery makes `solar_w` equal total DC load exactly, no battery term).

Full evidence and the site-visit test that settles it:
`docs/xanbus-unknowns.md` #5 and #11.

## Writing — the four-step authorization model

Each step was discovered by its own distinct failure. All four are required.

### 1. Interface must not be listen-only
`ip link set can0 type can bitrate 250000 listen-only off`.
**`restart-ms` is rejected by the gs_usb adapter** ("Device doesn't support
restart from Bus Off") and failing ExecStartPre leaves can0 DOWN. There is no
bus-off auto-recovery; recovery is `ip link set can0 down/up`.

### 2. Claim an address — or you are ignored
J1939/81: a CA must claim before sending **any** message. Unclaimed frames are
silently discarded (no NAK, nothing). Broadcast Address Claimed (PGN 60928)
with an 8-byte NAME, watch ~250 ms for contention, then hold it by answering
Requests for Address Claimed at the bus's 1 Hz cadence.

**Safety invariant:** arbitration is *lowest NAME wins*. Build your NAME to
LOSE against every real device so you can never evict hardware keeping the
site alive — and put the distinguishing field **above `function`** in NAME
ordering (use `vehicle_system_instance`). A NAME differentiated on `function`
alone can accidentally sort lower and win.

### 3. Answer the discovery interrogation
Within ~1.3 s of your claim the gateway requests four PGNs from you:
`0x1F00F` (Sts, 6 B single-frame), `0x1F810` (HwRevSts, 22 B), `0x1F014`
(ProdInfoSts, 43 B), `0x1F80E` (SwVerSts, 25 B). Answer all four (fast packet
for the last three). Mirror the real records' structure but **do not
impersonate Schneider** — use your own identity strings.

### 4. Present NAME function 134 (gateway) — this is the authorization gate
```
function 130 -> ACCESS DENIED for PGN 0x14000
function 134 -> ACK
```
Command authority is a **self-declared role**, not a credential. The device
asks "are you a gateway?" and believes the answer.

## Commands vs configuration — two different message classes

### Device mode (a command)
```
PGN 0x14000, destination-specific, 1-byte payload
  0x02 = Standby      0x03 = Operating
```
No CRC, no handshake. Send it, then request `0x1F00F` to confirm.

### Config records (setpoints)
Fast-packet records, read-modify-write:

| PGN | Record | Fields |
|---|---|---|
| 0x11700 | ChgCfgBulk | value u32@4 (mV) |
| 0x11800 | ChgCfgAbsorp | value u32@4 (mV); **time u16@46 (SECONDS)** |
| 0x11A00 | ChgCfgFloat | value u32@4 (mV) |
| 0x11B00 | ChgCfgEqualize | enable flag@1; equalize V u16@4 |

Three things will bite you, in the order they bit us:

1. **Instances.** The same PGN arrives as multiple records distinguished by
   byte 0 — `0x04` is the live config, `0x06` is factory defaults. Select
   explicitly; editing one and writing it into the other's slot gets a NAK.
2. **Write form.** The device *reports* with `byte[0] = 0x04`; a *write* uses
   `byte[0] = 0x00`. Echoing the report form back gets ACCESS DENIED — the
   device sees a status report from a peer, not a config write.
3. **The change counter at byte 1 is an optimistic-concurrency token.** Echo
   back the counter you just read. The device increments it on accept and
   NAKs a stale one. Zeroing it gets a NAK. (July captures *look* like
   "writers send 0x00" only because the counter was 0 that day.)

Always read-modify-write the **full** record so neighbouring settings are
preserved byte-for-byte, and verify by read-back comparing value AND counter.

## Reading the refusals

ISO Acknowledgment, PGN 59392 (`0x0E800`), sent to your address:

```
payload: [control, group_fn, ff, ff, ff, pgn_lo, pgn_mid, pgn_hi]
control: 0 = ACK   1 = NAK   2 = ACCESS DENIED   3 = CANNOT RESPOND
```

The distinction matters and is diagnostic: **ACCESS DENIED = you may not do
this**; **NAK = you may, but the request is malformed or stale**.

## Known failure mode: the MPPT diode-clamp latch

When array current demand exceeds what the panels can supply, the operating
point slides down the IV curve until the array sits at **battery voltage plus
a diode drop** (~1–2 V above output). A buck converter cannot restart without
input headroom, so it **latches**: real power keeps flowing through the body
diode, unregulated and unmetered, until demand ceases (battery full, or
sunset). Cost when it happened: five days, ~40% of available production, plus
unregulated charging that tripped a BMS cell-overvoltage disconnect.

- **Detect — the naive test is wrong, and this is the corrected one.** A clamp
  pins the array *just above* the output, so it is a **BAND**, not an upper
  bound: `0.3 V ≤ pv_v − out_v ≤ 4.0 V` while `pv_v > 20 V` **and the sun is
  above 5°**, sustained ~10 min with hysteresis on the way out too.

  Four separate bugs came from getting this wrong, all of them shipped:
  - `delta < 2.5` also matches **negative** deltas. At dusk the array decays
    *below* battery voltage and that read as a latch — false positive at 21:24
    with delta −15.7 V and 0 W. Hence the 0.3 V floor.
  - 2.5 V is **below the MPPT's own reporting dither** (delta swings 0.90–3.44
    V second to second during a genuine clamp), so a real latch read as
    intermittent and cleared itself 25 s after firing. Hence 4.0 V.
  - No hysteresis on ENTRY meant one out-of-band sample voided 15 minutes of
    accumulation, so a real 25-minute clamp produced no event at all. Apply
    the same grace in both directions.
  - A voltage test alone is not a daylight test. At dawn and dusk the MPPT
    **hunts** — tries to start, drags the array to battery voltage, fails,
    releases it to Voc, repeatedly. One 60 s bucket held pv_v min 26.81 and
    max 89.74. Sample by sample that is indistinguishable from a clamp, and it
    made the guard bounce the MPPT at 21:01 local with the sun 3.6° *below*
    the horizon. Gate on sun elevation (`scripts/solar_geometry.py`, clock
    only, no sensor).

  If you need to tell hunting from a real descent in *aggregated* data where
  elevation is not available: **a real walk-down is pinned, hunting
  oscillates.** Spread of pv_v inside one 5 min bucket is ~5 V for a genuine
  descent against ~41–49 V for hunting.

- **Clear:** Standby → wait 15 s → Operating. Standby opens the PV input so
  the array flies to Voc and the tracker can re-acquire. Verified: array
  86 → 108.5 V during standby, then re-sweeps to MPP with full output.
- Automated in `scripts/xanbus_latch_guard.py` (systemd timer, 5 min).

### The 45 V cliff — the operationally useful part

`pv_v` falling below ~45 V while tracking is the point of no return: **16 of
16 recorded crossings ended in a clamp, none recovered.** Time to clamp 30–115
min, median 68, and **not predictable** from anything measured so far (deficit
depth correlates at r = +0.28). Derived by `scripts/cliff_table.py` — do not
hand-maintain those numbers, an earlier hand-built table drifted three ways at
once and had missed every afternoon crossing.

That is why an *early* bounce at the crossing is attractive: it acts a median
68 min before the clamp forms, and on a bright day the descent window is worth
80–210 Wh. Gated on a supervised test — every bounce on record started from an
already-clamped array at 28 V, and nobody has yet bounced a still-tracking one.

### Suspected root cause (2026-08-10, unproven)

Probably the output current sensor, and specifically its **offset**, not its
under-report. A pure scale error cannot cause this — `argmax(k·P) = argmax(P)`
— but the measured error is `true ≈ 1.35 × reported + 2.2 A`, and at the 25
recorded crossings the reported current was a **median 1.40 A against that
2.2 A offset**. The error term is larger than the signal exactly where the
latch forms, which is the only hypothesis so far that explains why this
happens only in dim light. With no PV-side current sensor on this model, every
tracking decision rests on that one measurement.

If it holds, the guard and the early-bounce trigger are both symptom
treatments and the repair is a recalibrated or replaced controller. The
decisive test is a clamp meter on the **MPPT output during a dim morning at
low current** — not the bright-sun reading, where the offset is negligible.

## Tooling in this repo

| Script | Purpose |
|---|---|
| `xanbus_telemetry.py` | production reader: decode → 15 s buckets → events → Railway |
| `xanbus_node.py` | conforming node: claim, identify, command, config read/write |
| `xanbus_setpoint.py` | guarded setpoint read/modify/write with restore |
| `xanbus_latch_guard.py` | unattended latch detect + clear |
| `xanbus_decode.py` | offline correlation search (refuses to run on the Pi) |
| `pull_captures.sh` | rsync the capture corpus off the Pi |
| `solar_geometry.py` | sun elevation from the clock alone; the daylight gate both detectors use |
| `cliff_table.py` | regenerate the 45 V cliff table — the numbers in the docs must come from here |
| `meter_offset.py` | the dark-hours BMS-vs-`dc_w` offset |
| `float_calibration.py` | the neutral-battery test that gives a third opinion on the meters |
| `bms_coulomb_check.py` | BMS reported current vs its own coulomb counter |

Every one of these refuses to do heavy work on the Pi, and each carries its
controls inline (coverage gaps, independent-counter checks) so a re-run
re-validates rather than just recomputing.

## Working method that actually finds things

**Marker-and-diff.** Record epoch + byte offset of the live capture, perform
one action (ideally via the Insight UI, so it's a known-good reference), then
pull only the bytes since the marker and diff reassembled payloads. Every
protocol fact above came from this.

Two gotchas: our own transmitted frames do **not** appear in our own capture
(gs_usb loopback quirk) — trust the interface TX counter instead. And decoding
must run **off** the Pi; a heavy job on that 1 GB box caused a multi-day
outage.

## Hard-won rules

- Never assume silence means "ignored" — check for an ISO ACK first.
- Never send a command whose effect you can't predict and undo.
- Verify physical effect, not just the ACK. A device can accept and no-op.
- Test the arbitration-loses property *before* transmitting, not after.
