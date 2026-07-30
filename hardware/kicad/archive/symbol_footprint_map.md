# Symbol / footprint assignment audit table

Every component on both boards, with its KiCad symbol and footprint
reference. Confidence column flags items where I'm not 100% sure the
exact library symbol exists in stock KiCad 8 — the future session
should verify these first and substitute if needed.

Statuses:
- **stock** = in standard KiCad 8 libraries
- **likely** = standard but exact name may vary; verify
- **check-vendor** = may need a vendor-provided or community symbol
- **custom** = needs to be drawn in KiCad Symbol Editor

## Battery-side board

| Ref       | Description                | KiCad symbol                          | KiCad footprint                                                                  | Status        |
|-----------|----------------------------|---------------------------------------|----------------------------------------------------------------------------------|---------------|
| MOD1      | ESP32-S3-WROOM-1-N16R8     | `RF_Module:ESP32-S3-WROOM-1`          | `RF_Module:ESP32-S2-WROOM-1` (same module footprint)                              | **stock**     |
| U1        | TPS62933F buck             | `Regulator_Switching:TPS62933F`        | `Package_SON:Texas_S-PDSO-N6_1.6x1.6mm`                                          | **likely** — confirm exact part suffix (F vs FDRLR) |
| U2        | Recom R-78E12-1.0          | `Regulator_Switching:R-78E-1.0`        | `Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT`                              | **check-vendor** — symbol may not be in stock KiCad; Recom provides one |
| U3        | SN65HVD3082E RS-485        | `Interface_UART:SN65HVD3082E`          | `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`                                            | **stock**     |
| RTC1      | DS3231M (DS3231SN# is equiv) | `Timer_RTC:DS3231M`                  | `Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm`                                         | **stock**     |
| Q1        | AO3401A P-MOSFET           | `Transistor_FET:AO3401A`               | `Package_TO_SOT_SMD:SOT-23`                                                       | **stock**     |
| Q2        | AO3400A N-MOSFET           | `Transistor_FET:AO3400A`               | `Package_TO_SOT_SMD:SOT-23`                                                       | **stock**     |
| D1        | SS24 Schottky              | `Diode:SS24`                           | `Diode_SMD:D_SMA`                                                                | **stock**     |
| TVS1      | SMAJ12CA TVS               | `Diode:SMAJ12CA`                        | `Diode_SMD:D_SMA`                                                                | **likely** — generic `Diode:TVS_Bidir_SMA` if exact part absent |
| TVS3      | SMAJ15A TVS                | `Diode:SMAJ15A`                         | `Diode_SMD:D_SMA`                                                                | **likely** — fall back to `Diode:TVS_Unidir_SMA` |
| F1        | 1A fuse + ATO holder       | `Device:Fuse`                          | `Fuse:Fuse_Blade_ATO_Littelfuse-0287`                                            | **likely**    |
| L1        | 2.2µH 3A inductor          | `Device:L`                             | `Inductor_SMD:L_0805_2012Metric`                                                 | **stock**     |
| BAT1      | CR2032 holder              | `Battery:Battery_Cell`                  | `Battery:BatteryHolder_Keystone_1066_1x12mm`                                     | **stock**     |
| BTN1      | Panel-mount override       | `Switch:SW_Push`                        | `Button_Switch_SMD:SW_SPST_PRTH1JOH`                                             | **check-vendor** — exact panel-mount footprint depends on switch you order |
| LED1      | Green LED 0805             | `Device:LED`                           | `LED_SMD:LED_0805_2012Metric`                                                    | **stock**     |
| J1        | RJ45 keystone              | `Connector:RJ45`                       | `Connector_RJ:RJ45_Amphenol_RJHSE5380`                                           | **likely** — alternative: `Connector_RJ:RJ45_Cui_MJ-66H-DG_Horizontal` |
| J2        | 2-pin terminal block       | `Connector:Conn_01x02`                  | `TerminalBlock:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal`   | **likely**    |
| R*, C*    | passives                   | `Device:R`, `Device:C`                  | `Resistor_SMD:R_0603_1608Metric`, `Capacitor_SMD:C_0603_1608Metric` (etc.)        | **stock**     |

## Display-side board

| Ref       | Description                | KiCad symbol                          | KiCad footprint                                                                  | Status        |
|-----------|----------------------------|---------------------------------------|----------------------------------------------------------------------------------|---------------|
| MOD2      | ESP32-S3-WROOM-1-N16R8     | `RF_Module:ESP32-S3-WROOM-1`          | `RF_Module:ESP32-S2-WROOM-1`                                                      | **stock**     |
| U10       | Recom R-78E3.3-0.5         | `Regulator_Switching:R-78E-0.5`        | `Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT`                              | **check-vendor** |
| U11       | SN65HVD3082E               | `Interface_UART:SN65HVD3082E`          | `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm`                                            | **stock**     |
| F2        | PTC polyfuse 0.5A          | `Device:Polyfuse`                      | `Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal`                  | **likely**    |
| TVS3      | SMAJ15A                    | `Diode:SMAJ15A`                         | `Diode_SMD:D_SMA`                                                                | **likely**    |
| TVS4      | SMAJ12CA                   | `Diode:SMAJ12CA`                        | `Diode_SMD:D_SMA`                                                                | **likely**    |
| J3        | 24-pin 0.5mm FFC for e-paper | `Connector_Generic:Conn_01x24`        | `Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal`             | **check-vendor** — exact part: Hirose FH12-24S-0.5SH(55) (Mouser 798-FH12-24S-0.5SH55). Verify pin numbering before fab. |
| BTN10-12  | 6×6 tactile, SMD or THT    | `Switch:SW_Push`                        | `Button_Switch_SMD:SW_SPST_TL3300`                                               | **likely** — alternatives: `Button_Switch_THT:SW_PUSH_6mm` |
| LED1      | Green LED 0805             | `Device:LED`                           | `LED_SMD:LED_0805_2012Metric`                                                    | **stock**     |
| J11       | RJ45 keystone              | `Connector:RJ45`                       | `Connector_RJ:RJ45_Amphenol_RJHSE5380`                                           | **likely**    |
| R*, C*    | passives                   | `Device:R`, `Device:C`                  | `Resistor_SMD:R_0603_1608Metric`, etc.                                            | **stock**     |

## First-pass verification checklist (for the future session)

When KiCad is installed, run these in order to surface missing symbols
*before* spending time on PCB layout:

```bash
cd hardware/kicad
./run.sh
```

Errors will be like:
> `WARNING: Couldn't find part: 'Regulator_Switching:R-78E-1.0'`

For each warning:

1. Open KiCad's symbol editor (`kicad --no-arg-session` then File → Symbol Editor).
2. Search the symbol library for the closest match.
3. If found: edit the SKiDL file to use that exact name.
4. If not found:
   a. **Option A — use Recom's own library**: Recom provides KiCad
      libraries at https://www.recom-power.com/en/services/design-tools/
      Download, place under `hardware/kicad/lib/recom/`, and add the
      lib path to a project-local table.
   b. **Option B — generate a stub symbol**: use KiCad's Symbol Editor
      to make a 3-pin module symbol named `R-78E-1.0` with pins VIN,
      GND, VOUT — takes 5 minutes.

Either way, re-run `./run.sh` until it completes without errors.

## Custom symbols / footprints needed

Items currently `check-vendor` will likely need custom symbols. Plan for
~30 minutes of symbol/footprint editing in KiCad's Symbol Editor:

1. **Recom R-78E12-1.0 / R-78E3.3-0.5**: 3-pin SIP modules. Symbol is
   trivial (VIN, GND, VOUT); footprint is THT 3-pin with 2.54 mm pitch,
   pins on bottom. Reference: Recom datasheet "R-78E-1.0 Series".

2. **Hirose FH12-24S-0.5SH FFC connector**: 24-pin 0.5 mm pitch. KiCad's
   `Connector_FFC-FPC` library has similar parts — closest match is
   likely a 24-pin 0.5 mm SMT FFC. Verify pin numbering against
   datasheet (FFC connectors can have ambiguous pin 1 indication).

3. **EG1218 panel-mount pushbutton** (or whichever override switch you
   choose): may need a footprint that matches your enclosure cut-out.
   Often easiest to just draw one in the Footprint Editor.
