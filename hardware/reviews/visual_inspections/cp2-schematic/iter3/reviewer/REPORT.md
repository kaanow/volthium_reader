# CP2 iteration 3 - agent-reviewer evidence

## Rebuild and mechanical preconditions

- Bare Windows `doc_consistency_check.py` passed: 32 manifest parts and 40
  `_verify_` BOM cells checked, clean. Bare `check_requirements.py` returned
  29/29 PASS.
- The exact documented bare Windows build got through KiCad data discovery
  and all prior UTF-8 failure sites, then failed at `build.py:1842` because
  it invokes literal `kicad-cli` and the per-user KiCad installation is not
  on PATH. `bare_build.combined.txt` and `bare_build.exitcode.txt` preserve
  that run.
- The validated Windows launcher from `kicad-cli` skill v1.0.1 resolved
  KiCad 10.0.5 under `%LOCALAPPDATA%`, then the committed generator rebuilt
  all sheets successfully. All eight readability gates, intent-versus-CLI
  netlist comparison, PNG exports, and the generator's two reported ERC
  counters passed.
- A non-destructive CLI smoke test against the fresh root schematic exported
  PDF, netlist, and ERC report while preserving all 19 source/table hashes.
  Normal ERC returned 0 but reported 141 messages; strict
  `--exit-code-violations` returned KiCad rc=5. See `kicad_cli/smoke/`.

## Iteration-2 response verification

- F05 is resolved. The fresh exported netlist identifies J2 as
  `Amphenol_RJHSE-5380` with footprint
  `Connector_RJ:RJ45_Amphenol_RJHSE5380`. An in-memory false exact-part
  contract produced exactly one J2 finding and exit 1.
- F06 is resolved. The requirements runner now proves
  J5.3 same-net MOD1.37 and J5.5 same-net MOD1.36. An in-memory J5.3-to-J5.4
  poison produced exactly one R9 failure and exit 1.
- F07 is only partly resolved. Per-user share-root discovery and explicit
  UTF-8 handling work, but bare executable discovery does not; see the packet
  finding.

## G8 wiring read-back

- Exported-netlist connector read-back:
  J2 = 1/2/3 `V12_CAT5E`, 4 `RS485_A`, 5 `RS485_B`, 6/7/8/shield GND;
  J6 = CANL pin 4, CANH pin 5, shield GND;
  J10/J11 = bus A pin 7, bus B pin 8, separate isolated shields;
  J5 = EN/VDD/target-TXD/GND/target-RXD/IO0 on pins 1..6.
- The exported netlist's pin-function probes show Q5/Q10/Q11/Q_exp as
  gate pin 1, source pin 2 on `V3V3`, and drain pin 3 on each gated load.
  Q3/Q4 read back as the intended two-NMOS UVLO/USB-reset logic.
- The two isolated channels retain separate logic, converter, and bus
  grounds. L11/L13 remain the only converter-to-bus-ground ties; C28/C38
  remain the logic-to-converter-ground bridges. Provisioning networks remain
  visibly DNP.
- The independent discrete-short scan covered 98 R/C/L/D/Q/TVS/F references
  and found zero same-net pin pairs. Full connector/transistor output is in
  `kicad_cli/netlist_readback.txt`.

## ERC second opinion

- `smoke.erc.rpt` contains 141 messages: 138 `lib_symbol_issues`, two
  `isolated_pin_label` warnings for the PACK B-minus labels, and one
  `pin_to_pin` error because U6 VOUT pins 2 and 7 are both typed power output.
- The library warnings say the project library `volthium` was not found at
  `../../libraries/volthium.kicad_sym`. A run from another working directory
  changed the symptom to missing symbols because that library is incomplete;
  this is not fixed by changing the CLI working directory alone.
- `build.py` invokes ERC without `--exit-code-violations`, parses only
  dangling/unconnected and power-pin-not-driven classes, prints both as zero,
  and accepts the report. The strict smoke transcript demonstrates the
  omitted classes are gate-significant.

## Source and object checks

- Xantrex `Xanbus System Installation Guide 975-0136-01-01` was opened at
  its title page and page 18 Table 3. It gives 1/2/7 NET_S, 3/6/8 NET_C,
  4 CAN_L, and 5 CAN_H. Page 19 shows a network power source example rated
  800 mA at 15 VDC.
- Schneider `InsightHome Owner's Guide 990-91410B` was opened at its title
  page, page 15 terminal map, and page 22 network topology instructions.
  The manufacturer, document number, isolated RS-485/CAN terminal identities,
  and no-loop/termination guidance match the on-file object.
- TI `TCAN332` page 5 was opened in the same turn. Its absolute-maximum table
  limits any CAN bus terminal to -14 V through +14 V. That is a damage
  boundary, not an operating guarantee.
- Reviewer-owned page renders are under `source_spotchecks/`; all object
  identity and citation checks above were made against the rendered PDFs.

## G9 and visual inspection

1. Designer layer: the generator's eight readability gates passed.
2. Independent layer: `label_body_audit.py` reported zero geometry findings
   on all eight child sheets. The generic visual-audit wrapper requires a
   display-side PDF and therefore cannot run on this battery-only CP2 packet.
3. Eyes layer: nine fresh 300-DPI pages and 54 overlapping fixed-box crops
   were inspected. J2's exact 5380 value is readable. No collision, clipping,
   ambiguous junction, or unreadable pin field was found.

## Bring-up and traceability walk

- The bring-up guide's J5 recovery drill and UART pins match the exported
  netlist and the corrected R8/R9 requirements.
- The live CP1 battery design document still calls J5 a four-pin debug header
  and assigns RESET# to J5 pin 4, which is GND in the schematic.
- The field note that retires the Xanbus power-pin-miswire caveat is not
  supported: it cites a measured 12 V rail while also acknowledging 15 V
  nominal, but TCAN332's positive bus absolute maximum is +14 V.
