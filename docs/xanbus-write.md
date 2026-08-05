# Writing to the Xanbus — standing objective

**Goal:** command Conext devices over CAN ourselves, so the Insight Home can
be retired without losing the ability to change settings or clear an MPPT
diode-clamp latch. Read side: `docs/xanbus-decode.md`.

## Where we are

| Milestone | State |
|---|---|
| Physically transmit on the bus | ✅ done — `can0` out of listen-only, 68+ frames, zero errors |
| Claim an address (J1939/81) | ✅ done — 0x80 claimed uncontested, network sees us |
| Be interrogated by the network | ✅ observed — Insight requests 4 identity PGNs within 1.3 s |
| Answer the interrogation | ✅ implemented (`--identify`), field test pending |
| Have a command accepted | ✅ **ACK — solved 2026-08-05** |

## SOLVED: command authority is the NAME `function` field

A node presenting **function 134 (gateway)** is permitted to command. Any
other function is refused with ACCESS DENIED. Nothing else needed changing —
same address, same claim, same discovery answers, same command bytes:

```
function 130 (generic)  -> <- node 1: ACCESS DENIED for PGN 0x14000
function 134 (gateway)  -> <- node 1: ACK           for PGN 0x14000
```

That is the whole authorization model as it applies to us: the MPPT asks
"are you a gateway?" and believes the answer. Use `--function 134`.

Our NAME still loses every arbitration (vehicle_system_instance = 15 sits
above `function` in NAME ordering), so declaring gateway class cannot let us
evict the real Insight; the tool refuses any override that would.

## The blocker, precisely

The MPPT does not ignore our command — it answers it:

```
PGN 0x0E800 (59392, ISO Acknowledgment)  from node 1 -> us
payload: 02 fb ff ff ff 00 40 01
         ^^                ^^^^^^^^
         control byte 2    PGN 0x14000 (our device-mode command)
         = ACCESS DENIED
```

Xanbus carries an authorization model: IEA-PVPS T11-04 §5.3 (written with
Xantrex) describes configuration messages with **user / service / factory
access levels**. Command authority appears to be granted, not assumed.

## Known-good command format

Captured twice from the real Insight while it fixed a latched MPPT:

```
PGN 0x14000, destination-specific, 1-byte payload
  0x02 = Standby      0x03 = Operating
e.g. id 0x19400102  (prio 6, dest 1 = MPPT, src 2 = Insight)
```

No CRC, no preceding handshake. The Insight sends it, then requests PGN
0x1F00F to confirm the result.

## Ranked ideas

1. ~~Answer discovery~~ — implemented; necessary-looking but not sufficient.
2. ~~Low address~~ — untested, unnecessary: 0x80 works.
3. ~~Function 134~~ — **this was it.**
4. RV-C proprietary path: DEVICE_MODE_CONFIGURATION inside DGN 0xEF00 with the
   NAME-seeded CRC-CCITT (implemented, 14/14 doc vectors pass). Speculative
   for Conext, but the CRC is literally a prove-who-you-are mechanism.
5. Hunt for an access-level/unlock exchange in the Insight's traffic at
   connect time or first write after login.
6. Unpack XWConfig / InsightHome firmware for the PGN dictionary and access
   logic ("PyXanBus" lineage).

## Tools

`scripts/xanbus_node.py` — claims, defends, identifies, commands, decodes
ACKs. Its NAME is built to LOSE every arbitration so it can never evict real
hardware (enforced by test against the three captured NAMEs). Nothing
transmits without `--send`.

Modes: `--decode-names` (read-only) · `--claim-only` · `--identify` ·
`--bounce` (the latch fix).

## Gotchas

- Our own transmitted frames do **not** appear in our capture (gs_usb
  loopback quirk). Trust the interface TX counter.
- The gs_usb adapter rejects `restart-ms`, so there is **no bus-off
  auto-recovery**; a wedged controller needs `ip link set can0 down/up`.
