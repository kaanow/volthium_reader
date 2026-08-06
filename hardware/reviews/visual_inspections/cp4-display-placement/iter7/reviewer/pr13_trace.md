# PR-13 trace check

- Packet section 7 says there is `No SWD/JTAG` because the ESP32-S3 JTAG pins
  were forfeited to the CAN gate under DR-31.
- `hardware/layout/decisions.md` DR-31 assigns IO40/IO41/IO42 to CAN on the
  battery board and says that board's JTAG pins were forfeited.
- The display-side pin map in `hardware/layout/cp1_display_side.md` section 6
  has no CAN assignment. It assigns GPIO19/20 to native USB through J-USB and
  identifies GPIO3 as the USB-JTAG-select strap.
- `hardware/layout/decisions.md` D27 independently defines display J-USB as
  native ESP32-S3 USB and J3 as the internal UART/recovery header.
- The exported display netlist contains J-USB and J3, and contains no U7 or
  CAN net. J5 is the RS-485 termination jumper, not a debug header.

Verdict: the placement can satisfy PR-13, but the row's no-JTAG/CAN rationale
is copied from the wrong board. The display debug paths are J3 ESP-Prog and
native USB-JTAG through J-USB.
