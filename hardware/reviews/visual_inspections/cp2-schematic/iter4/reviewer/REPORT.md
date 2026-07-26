# CP2 iteration 4 - agent-reviewer evidence

## Rebuild precondition

- `doc_consistency_check.py` passed before review: 32 manifested parts checked,
  40 BOM cells remain `_verify_`, and no stale-token or manifest/PDF/BOM
  inconsistency was found.
- The committed generator was rebuilt on Windows with `KICAD_CLI`,
  `KICAD_SHARE`, both KiCad library overrides, and `PYTHONUTF8` unset, and
  with every KiCad directory removed from `PATH`. It independently found
  KiCad 10.0.5 under `%LOCALAPPDATA%`, passed all eight sheet readability
  gates, exported all PNGs, passed the intent-versus-exported-netlist gate,
  and exited 0. See `bare_rebuild.txt` and `bare_rebuild.exitcode.txt`.
- The build's strict root ERC transcript reports KiCad rc=5 because accepted
  warnings are present: 2 messages, 2 accepted by `ERC_ACCEPTED`, and zero
  unaccounted. A separate direct CLI report is preserved under `kicad_cli/`.

## Iteration-3 response verification

### F08 - strict ERC

- The project now writes `build/volthium.kicad_sym` from the exact flattened
  symbols embedded by the generator and references it through
  `${KIPRJMOD}/volthium.kicad_sym`. The former 138 missing-library/symbol
  warnings do not recur.
- A fresh direct `kicad-cli sch erc --severity-all
  --exit-code-violations` emits exactly two `isolated_pin_label` warnings:
  `PACK1_Bminus` and `PACK2_Bminus`. Both are intentional DNP isolated
  reference-pad provisioning nets and match the exact class/token acceptance
  entries. There are no errors and no other warnings.
- The parser independently counted two report class headers and returned the
  same two messages. An in-memory false acceptance token left both warnings
  unaccounted and reported the false entry stale.
- U6 pins 2 and 7 are one physical TPS2116 VOUT rail. The fresh netlist reads
  both on `V3V3`; pin 2 remains `power_out`, while pin 7 is the passive twin.
  TI TPS2116 page 3 Table 5-1 independently identifies both package pins as
  VOUT outputs. The 148-entry golden table also requires pins 2 and 7 to
  remain on the same net.

F08 is resolved. The electrical-type adjustment suppresses a false
dual-driver report without weakening the same-net or powered-rail contracts.

### F09 - Windows KiCad CLI

The reviewer-owned executable discovery fix remains effective in the bare
acceptance build above, and the designer reports a successful macOS build
through the same resolver. F09 remains closed.

### F10 - stale J5 documentation

- The live battery design document now gives the exact keyed 2x3 ESP-Prog
  map: pin 1 `MCU_EN`, 2 `V3V3`, 3 target `DBG_TXD`, 4 GND, 5 target
  `DBG_RXD`, and 6 `BOOT`.
- The former RESET-on-J5.4 text and four-pin service summary are gone.
- The append-only stale-token registry covers the retired four-pin and
  pin-4 RESET forms. Its fixtures reject both bad forms, accept the corrected
  forms, and do not falsely reject the display board's staged J3 text.
- `doc_consistency_check.py` passes after the response.

F10 is resolved.

### F11 - Xanbus miswire premise

- `DESIGN_REVIEW_ITEMS.md` now withdraws the unsupported survivability
  conclusion and retains the potentially fatal NET_S-to-CAN miswire caveat.
- Bring-up Stage 5 treats measurement as a standing pre-attach control and
  requires repetition after a cable or port change.
- The replacement wording does not treat absolute maximum as an operating
  guarantee and does not infer a NET_S maximum from one 12 V observation.

F11 is resolved.

## G8 wiring read-back

The following narration was re-derived from the fresh exported netlist rather
than inferred from the drawing:

- Input power runs J1 `V24_RAW` through F1 and series D1 to `V24_FUSED`;
  TVS1 returns that protected rail to GND. U1 converts it through L1 to
  `V3V3_BUCK`. SSR1 and F2 feed the two series inrush resistors and
  `V24_SW`; U2 converts that branch to `V12_CAT5E`.
- U4 senses `V24_FUSED` through the 5.16 M/100 k divider, receives hysteresis
  feedback through 11.5 M, and drives `UVLO_RESET`. R5/R6 separately produce
  `V24_SENSE`.
- USB VBUS feeds U5; U5 output reaches U6 VIN1. U6 VIN2 is `V3V3_BUCK`, and
  both U6 VOUT pins form `V3V3`. Q3/Q4 implement the intended USB-present
  UVLO bypass chain into `MCU_EN`.
- MOD1 receives `MCU_EN`, USB D+/D-, UART, both isolated-channel controls,
  CAN TX/RX and power control, RTC I2C, the button input, and expansion
  control on the documented GPIO nets.
- U3 drives display RS-485 A/B with termination inserted through J4. U7
  drives Xanbus CAN_H/CAN_L to J6 pins 5/4 with termination inserted through
  J7. RTC1 is always powered and its backup pin reaches C-bk.
- Each ADM2587E channel has a separate gated primary supply, converter-ground
  island, bus-ground island, and RJ45. L11/L13 are the only
  converter-to-bus-ground ties; C28/C38 bridge primary GND only to the
  converter-ground side. The DNP bus-protection networks remain open.
- J5 reads EN/VDD/target-TXD/GND/target-RXD/IO0 on pins 1..6. J2 reads
  1/2/3=`V12_CAT5E`, 4=`RS485_A`, 5=`RS485_B`, and 6/7/8/shield=GND.
  J10/J11 retain A=7, B=8 and their separate isolated shield domains.

Probe-derived transistor mappings are in `g8_netlist_checks.txt`. Q5, Q10,
Q11, and Q_exp each read gate/source/drain as pins 1/2/3, with source on
`V3V3` and drain on a distinct gated load. Q3/Q4 read back as the intended
NMOS reset chain.

All 148 golden contracts pass. A deliberately false U6-on-`POISON_NOT_V3V3`
contract produces exactly one failure. The independent scan covers 98
R/C/L/D/Q/TVS/F references and finds zero same-net pin groups. The
requirements runner returns 29/29 PASS.

## Source and object checks

- TI `TPS2116DRLR.pdf` page 3 was opened in this turn. Table 5-1 identifies
  pins 2 and 7 as VOUT output-power pins. Full SHA-256 begins `5babd88afb84`,
  matching the manifest.
- TI `TCAN332.pdf` page 5 was opened in this turn. The absolute-maximum table
  limits any bus terminal to -14 V through +14 V and identifies those limits
  as damage boundaries. Full SHA-256 begins `aeda66d5fca9`, matching the
  manifest.
- Xantrex `Xanbus System Installation Guide 975-0136-01-01` pages 18 and 19
  were opened in this turn. Table 3 gives NET_S=1/2/7, NET_C=3/6/8,
  CAN_L=4, CAN_H=5; page 19 gives a 15 VDC network-power-source example.
  Full SHA-256 begins `0a99b0ebcb6c`, matching the on-file vendor record.

The reviewer-owned page renders are under `source_spotchecks/`.

## G9 geometry second opinion

1. Designer gate: all eight generator readability gates passed.
2. Independent tool: `label_body_audit.py` reported zero geometry findings
   on all eight child sheets. Its unchanged advisories concern nearby
   same-net labels and visible free crossings, not collisions.
3. Eyes: nine fresh 300-DPI full pages and 54 overlapping fixed-box crops
   were inspected. The U6 region is clear, both VOUT wires visibly join
   `V3V3`, and no collision, clipping, ambiguous junction, or unreadable pin
   field was found.

## Verdict

APPROVED. F08, F10, and F11 are resolved; F09 remains closed. No new
blocker, important, nit, or question finding was identified.
