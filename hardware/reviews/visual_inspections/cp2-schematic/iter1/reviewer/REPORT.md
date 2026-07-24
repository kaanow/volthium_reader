# CP2 iteration 1 - agent-reviewer evidence

## Preconditions and mechanical gates

- Final clean rebuild from committed `hardware/kicad/schematic/build.py`:
  eight sheet readability gates clean; intent-vs-KiCad netlist clean; root
  ERC rc=0, dangling/unconnected=0, power-pin-not-driven=0.
- `doc_consistency_check.py`: exit 0 (32 manifest rows checked; 40 BOM cells
  remain `_verify_`).
- `check_requirements.py`: 29 checks, 0 failures.
- Independent `label_body_audit.py`: 0 geometry findings on all eight child
  sheets. Free-crossing and nearby-label advisories were inspected visually.
- Independent discrete-short scan of the exported netlist: 96 R/C/L/D/Q/TVS
  references, 0 references with two pins on one net.

## G8 exported-netlist read-back

- Power input/regulation: `V24_RAW -> F1 -> D1 -> V24_FUSED`; TVS1 returns
  fused input to GND; U1 produces `V3V3_BUCK`; SSR1/F2 feed `V24_SW`; U2
  produces `V12_CAT5E`.
- Supervisor: U4 SENSE is driven by the 5.16 M/100 k divider, RESET is
  `UVLO_RESET`, and 11.5 M feedback returns RESET to SENSE. MR is NC, CT has
  its timing capacitor, and VDD is `V3V3`.
- USB maintenance: U5 converts VBUS to the U6 priority input; U6 selects that
  input over `V3V3_BUCK` and drives `V3V3`. Q3/Q4 implement the VBUS UVLO
  bypass. USB D+/D- reach MOD1 pins 14/13 through U-ESD.
- MCU: MOD1 GPIO nets agree with the requirements register. GPIO0 is BOOT;
  UART0 is `DBG_TXD/DBG_RXD`; the four default-off gate controls are on
  distinct GPIOs.
- Four PMOS gates:
  - Q5: pin 2 source=`V3V3`, pin 1 gate=`CAN_PWR`, pin 3 drain feeds U7.3.
  - Q10: pin 2 source=`V3V3`, pin 1 gate=`CH1_PWR`, pin 3 drain=`VCC1`.
  - Q11: pin 2 source=`V3V3`, pin 1 gate=`CH2_PWR`, pin 3 drain=`VCC2`.
  - Q_exp: pin 2 source=`V3V3`, pin 1 gate=`EXP_PWR_EN`, pin 3 drain=`EXP_3V3`.
- Comms polarity: J6.4=CANL/J6.5=CANH; J10/J11.7=A and .8=B; J2.4=A and
  .5=B. Each termination resistor reaches the opposite bus leg only through
  its jumper.
- Isolation channels: U10/U11 logic grounds remain GND; converter grounds
  `GND2_DCDC1/2` remain distinct from bus grounds `ISO_BUS_GND1/2`; L11/L13
  are the only converter-ground-to-bus-ground ties; C28/C38 alone bridge GND
  to converter ground. VISOOUT caps are before L10/L12 and VISOIN caps after.
- Connectors/button: BTN1 uses terminals 1-2, open at rest and closed when
  pressed; J_EXP matches D37. J5 electrically matches the repo's own golden
  table, but that table is not the actual ESP-Prog Program interface (F01).

Symbol-pin probes independently reproduced the PMOS placement assumptions:
angle 90 gives source right/drain left/gate bottom; angle 270 gives source
left/drain right/gate top; angle 0 keeps gate left, source below, drain above.

## Golden-table source spot-checks

1. `TCAN332.pdf` p.4: TCAN332 pins 1/2/3/4/5/6/7/8 are
   TXD/GND/VCC/RXD/NC/CANL/CANH/NC. Pp.5/8 confirm +/-14 V bus absolute max,
   +/-12 V receiver common mode, and power-off leakage.
2. `NTR4171P_onsemi.pdf` p.1: pins 1/2/3 are gate/source/drain.
3. `ADM2582E_2587E.pdf` pp.8/17: pin 12 VISOOUT reaches pin 19 VISOIN through
   L1; 10 uF + 0.1 uF are on the VISOOUT/device side, 0.1 uF + 0.01 uF on
   VISOIN; converter GND pins 11/14 reach bus GND pins 16/20 through L2;
   two-layer C_stitch is GND1 pin 10 to converter GND2 pin 11.
4. `TPS3808G01DBVR.pdf` p.4: SOT-23 pins 1/2/3/4/5/6 are
   RESET/GND/MR/CT/SENSE/VDD.
5. `CK_8020_series.pdf` pp.2/26: 8125 is SPDT ON-MOM; 1-3 are connected at
   rest and 1-2 momentarily; B contacts are low-level/dry-circuit rated.
6. `ESP32-S3-WROOM-1-N16R8.pdf` p.13: GPIO0 is a boot strap with a weak
   internal pull-up.

Rendered source pages are in `source_spotchecks/`.

## Poison tests

- A temporary false Q5 golden (`Q5.2=__POISON_GOLDEN__`) made the complete
  generator exit 2 with exactly that netlist-gate failure. The temporary copy
  was removed, then the committed generator was rebuilt clean.
- A temporary false R16 requirement produced 28 PASS/1 FAIL and exit 1. The
  temporary copy was removed; the committed checker then returned 29/29 PASS.

## G9 independent geometry opinion

1. Designer layer: the generator's readability/glyph/title-block gates pass.
2. Independent tool layer: `label_body_audit.py` uses a separate
   body/flag/wire box model and reports 0 findings on all eight child sheets.
3. Eyes layer: nine final full-page 300-DPI renders plus six fixed-box,
   overlapping zoom crops per page (54 crops) were read manually. No visible
   text collision, wire-through-body, clipped title block, ambiguous
   junction, or unreadable pin field was found.

The packet does not contain the separately required designer-owned D11
screenshot section; see F02. Reviewer images are `battery_p1...p9_full_300dpi`
and `battery_p1...p9_eye_crop_01...06`.

## Bring-up guide walk

Stages 0 and 2-6 have reachable measurement/control points and agree with the
exported netlist. Stage 1's native-USB first flash remains valid, but the
claimed direct ESP-Prog ribbon/auto-program and listed recovery pin numbers
are not valid for the drawn J5; see F01.
