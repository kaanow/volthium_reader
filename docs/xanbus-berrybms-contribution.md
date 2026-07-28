# Contribution back to berrybms

[`extrafu/berrybms`](https://github.com/extrafu/berrybms) (GPLv3) is where we got
the Conext Xanbus PGN layouts. Our reverse-engineering produced findings worth
sending back. This file stages that contribution; it becomes a GitHub issue/PR
against berrybms (pending review before anything is pushed publicly).

## 1. PGN 127166 (`0x1F0BE`, "MPPT Data") needs the standard fast-packet split

berrybms reassembles Xanbus fast-packets with a **nibble split**
(`XanbusMessage.append_bytes`: `sequence_id = b0 >> 4`, `frame_id = b0 & 0x0F`),
which caps a message at 16 frames. The code already flags the consequence:

> `# Disabled for now, that won't work for PGN 1f0be since it'll send packets
>  that are larger than 16 chunks`

PGN 127166 is a >16-frame message, so it can't currently be reassembled. The
**standard NMEA2000 fast-packet split** — `sequence_counter = b0 >> 5`,
`frame_index = b0 & 0x1F` (up to 32 frames) — reassembles it cleanly. We
verified that for the short PGNs (127172/127173, ≤16 frames) **both splits
produce byte-identical payloads**, so switching to the standard split is safe for
every PGN, not just 127166.

Suggested fix in `XanbusMessage.append_bytes`:

```python
first_byte = message.data[0]
sequence_id = first_byte >> 5      # was >> 4
frame_id    = first_byte & 0x1F    # was & 0x0F
```

(and the sequence-id continuity check can then be re-enabled, since 127166 no
longer overflows the counter.)

## 2. Independent confirmation of the 127172 / 127173 / 126990 layouts

We validated berrybms's layouts against a **second, independent Conext system**
(Volthium/Schneider install) by correlating decoded CAN fields against the
Insight Home Modbus ground truth:

- **127172 BattSts2** `<BBIii`: battery voltage decoded = 26.52 V vs Modbus DC
  voltage 26.50 V, **r = 0.98**. Confirmed.
- **127173 DcSrcSts2** `<BBIii` with **assoc@1 = 0x03 battery / 0x15 PV**: the
  `0x15` channel decodes a real ~54 V PV-array voltage, **r = 0.90** vs the MPPT
  PV-voltage Modbus register. Confirms the assoc discriminator and the layout.

## 3. Partial field offsets for 127166 (work in progress)

Once reassembled with the standard split, correlation against Schneider Modbus
registers gives candidate field offsets in 127166 (cumulative MPPT energy
counters). These are not yet clean enough to publish — several are cumulative
counters that need multi-day / anti-drift filtering to separate. We'll offer
them once solid.

## How we found it

Correlation tool + method: `scripts/xanbus_decode.py` (searches every CAN
offset/width/endian/sign against each varying Modbus register, with a
first-difference gate to reject drift artifacts) and `scripts/xanbus_reader.py`
(decodes the known layouts and validates against Modbus). Data captured with
`scripts/can_capture.py` + `scripts/modbus_poll.py`.
