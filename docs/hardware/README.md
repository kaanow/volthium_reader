# Hardware design — index

| Doc                                           | Contents                                          |
|-----------------------------------------------|---------------------------------------------------|
| [`block_diagrams.md`](block_diagrams.md)      | Top-level system + per-board block diagrams       |
| [`bom.md`](bom.md)                            | Full BoM with Digi-Key / Mouser part numbers      |
| [`schematic_battery_side.md`](schematic_battery_side.md) | Battery-side board: GPIO map, netlist, layout hints |
| [`schematic_display_side.md`](schematic_display_side.md) | Display-side board: GPIO map, netlist, layout hints |
| [`power_budget.md`](power_budget.md)          | Quantified draw per shutdown tier; wire losses    |
| [`cat5e_pinout.md`](cat5e_pinout.md)          | T568B pinout, shield bonding, cable QA            |
| [`bms_calibration.md`](bms_calibration.md)    | Empirical finding: BMS coulomb-counter bias is non-linear (1.12 fast charge, 0.91 trickle). Recommended firmware approach. |

## What's left before ordering parts

1. **Confirm the existing in-wall Cat5e is shielded** (user mentioned it
   is — worth verifying with a multimeter on the drain wire before
   committing). If not, design still works; we just lose some EMI
   margin.
2. **Decide proto vs PCB-first.** Default recommendation: build battery
   side on the ESP32-S3-DevKitC-1 + breadboard for ~1 week to debug the
   BMS polite-poll firmware. Order the PCBs as soon as that's stable.
3. **KiCad project**: the GPIO maps and netlists in the schematic docs
   are structured to enter into KiCad as a schematic. Each `.md` file is
   approximately one schematic sheet.

## Open hardware questions

- **e-paper substrate temperature**: the cabin gets cold in winter.
  Standard e-paper is rated 0–40 °C operating; the kitchen probably
  stays above 0 °C if the cabin is occupied. If we leave the cabin
  unheated, partial-refresh ghosting may become visible. Worth noting in
  the firmware: avoid refreshes below 0 °C, fall back to full-refresh-only.
- **Battery-side enclosure ventilation**: the regulators (U1 LM5165
  always-on µA-Iq buck + U2 R-78HB12 12 V, per D19) dissipate well under
  ~150 mW combined at typical load. The enclosure handles that easily; if
  we add heavier-current circuits later we may need a thermal pad to the
  box lid.
- **Cable strain relief at the in-wall keystone**: shoulder-mount the
  RJ45 keystone so the patch cable comes out without stressing the
  punch-down.
