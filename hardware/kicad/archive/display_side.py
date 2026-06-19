"""Display-side board — SKiDL source.

Same conventions as battery_side.py — this file is the source of truth,
the .kicad_sch is generated downstream.

Run:
    python display_side.py
Output:
    outputs/display_side.net

Cross-references:
    docs/hardware/schematic_display_side.md
    docs/hardware/bom.md
    docs/hardware/block_diagrams.md
"""

from skidl import (
    Net,
    Part,
    TEMPLATE,
    generate_netlist,
    generate_schematic,
    set_default_tool,
    KICAD8,
)

set_default_tool(KICAD8)

# --- Nets -------------------------------------------------------------------

V12_CAT5E = Net("V12_CAT5E")   # inbound from Cat5e from battery side
V3V3 = Net("3V3_RAIL")
GND = Net("GND")

# UART
UART_TX_3V3 = Net("UART_TX_3V3")
UART_RX_3V3 = Net("UART_RX_3V3")
DE_RE = Net("DE_RE")

# RS-485
RS485_A = Net("RS485_A")
RS485_B = Net("RS485_B")

# E-paper SPI
EPD_CS   = Net("EPD_CS")
EPD_DC   = Net("EPD_DC")
EPD_RST  = Net("EPD_RST")
EPD_BUSY = Net("EPD_BUSY")
SPI_MOSI = Net("SPI_MOSI")
SPI_SCK  = Net("SPI_SCK")

# Buttons (active-low; ESP32 GPIOs)
BTN_REFRESH = Net("BTN_REFRESH")
BTN_NEXT    = Net("BTN_NEXT")
BTN_RELEASE = Net("BTN_RELEASE")

# Debug LED
LED_DEBUG = Net("LED_DEBUG")

# --- Templates --------------------------------------------------------------

R_template = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0603_1608Metric")
C_small    = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0603_1608Metric")
C_bulk_0805 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0805_2012Metric")
C_bulk_1210 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_1210_3225Metric")

# --- F2: PTC resettable fuse on the 12V inbound ----------------------------
F2 = Part("Device", "Polyfuse", footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", value="MF-R050")
F2[1] += V12_CAT5E
F2[2] += Net("V12_PROT")

# --- TVS3: 12V transient suppressor -----------------------------------------
TVS3 = Part("Diode", "SMAJ15A", footprint="Diode_SMD:D_SMA", value="SMAJ15A")
TVS3[1] += Net("V12_PROT")
TVS3[2] += GND

# --- U10: Recom R-78E3.3-0.5 buck — 12V -> 3.3V -----------------------------
U10 = Part(
    "Regulator_Switching", "R-78E-0.5",
    footprint="Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
    value="R-78E3.3-0.5",
)
U10["VIN"]  += Net("V12_PROT")
U10["GND"]  += GND
U10["VOUT"] += V3V3

C_u10_in  = C_bulk_1210(value="22uF")
C_u10_out = C_bulk_0805(value="10uF")
C_u10_in[1]  += Net("V12_PROT");  C_u10_in[2]  += GND
C_u10_out[1] += V3V3;              C_u10_out[2] += GND

# --- MOD2: ESP32-S3-WROOM-1-N16R8 ------------------------------------------
esp = Part(
    "RF_Module", "ESP32-S3-WROOM-1",
    footprint="RF_Module:ESP32-S2-WROOM-1",
    value="ESP32-S3-WROOM-1-N16R8",
)
esp["GND"] += GND
esp["3V3"] += V3V3
esp["EN"]  += V3V3

# UART1 (to RS-485)
esp["IO17"] += UART_TX_3V3
esp["IO18"] += UART_RX_3V3
esp["IO2"]  += DE_RE

# E-paper SPI
esp["IO5"]  += EPD_CS
esp["IO6"]  += EPD_DC
esp["IO7"]  += EPD_RST
esp["IO8"]  += EPD_BUSY
esp["IO9"]  += SPI_SCK
esp["IO10"] += SPI_MOSI

# Buttons
esp["IO12"] += BTN_REFRESH
esp["IO13"] += BTN_NEXT
esp["IO14"] += BTN_RELEASE

# Debug LED
esp["IO15"] += LED_DEBUG

# Decoupling close to module
C_esp_bulk = C_bulk_0805(value="10uF")
C_esp_decoupling = C_small(value="100nF")
for cap in (C_esp_bulk, C_esp_decoupling):
    cap[1] += V3V3
    cap[2] += GND

# --- U11: SN65HVD3082 RS-485 transceiver ------------------------------------
U11 = Part("Interface_UART", "SN65HVD3082E", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
U11["R"]   += UART_RX_3V3
U11["RE"]  += DE_RE
U11["DE"]  += DE_RE
U11["D"]   += UART_TX_3V3
U11["VCC"] += V3V3
U11["GND"] += GND
U11["A"]   += RS485_A
U11["B"]   += RS485_B

C_u11 = C_small(value="100nF"); C_u11[1] += V3V3; C_u11[2] += GND

# 120Ω termination — this end is always the bus terminus, so populated
R10 = R_template(value="120", footprint="Resistor_SMD:R_0805_2012Metric")
R10[1] += RS485_A
R10[2] += RS485_B

# Idle bias — optional (battery side already does this; doubled bias is harmless)
R11 = R_template(value="680"); R11[1] += RS485_A; R11[2] += V3V3
R12 = R_template(value="680"); R12[1] += RS485_B; R12[2] += GND

TVS4 = Part("Diode", "SMAJ12CA", footprint="Diode_SMD:D_SMA", value="SMAJ12CA")
TVS4[1] += RS485_A
TVS4[2] += RS485_B

# --- J3: 24-pin 0.5mm FFC connector for e-paper ribbon ---------------------
# Generic 24-pin FFC connector — exact symbol/footprint may need replacement
# with a Hirose FH12-24S or similar from a vendor lib.
J3 = Part(
    "Connector_Generic", "Conn_01x24",
    footprint="Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal",
    value="EPD_FFC_24",
)
# Pin mapping below matches the Waveshare 4.2" e-Paper (B) V2 panel cable:
# (See panel datasheet for exact pin order — corrections welcome.)
# This is a placeholder mapping; the future session must verify against the
# specific panel datasheet before sending to fab.
J3[1]  += GND        # GND (placeholder)
J3[2]  += V3V3       # VCC (placeholder)
J3[3]  += V3V3       # 3V3 logic
J3[4]  += GND
J3[5]  += EPD_BUSY
J3[6]  += EPD_RST
J3[7]  += EPD_DC
J3[8]  += EPD_CS
J3[9]  += SPI_SCK
J3[10] += SPI_MOSI
# pins 11..24 — extras (some panels use them for VCOM caps, BS pin for SPI mode, etc.)
# Wire-up TBD against datasheet:
for pin in range(11, 25):
    J3[pin] += Net(f"EPD_NC_{pin}")

# --- Tactile buttons --------------------------------------------------------

def make_button(net, value):
    sw = Part("Switch", "SW_Push", footprint="Button_Switch_SMD:SW_SPST_TL3300", value=value)
    sw[1] += net
    sw[2] += GND
    # 10k pull-up
    rp = R_template(value="10k")
    rp[1] += net
    rp[2] += V3V3
    # debounce cap
    cd = C_small(value="100nF")
    cd[1] += net
    cd[2] += GND

make_button(BTN_REFRESH, "REFRESH")
make_button(BTN_NEXT,    "NEXT")
make_button(BTN_RELEASE, "RELEASE_BLE")

# --- LED + current-limit resistor -------------------------------------------
LED1 = Part("Device", "LED", footprint="LED_SMD:LED_0805_2012Metric", value="GREEN")
R_led = R_template(value="1k")
LED_DEBUG_DRIVE = Net("LED_DEBUG_DRIVE")
LED1["A"] += V3V3
LED1["K"] += LED_DEBUG_DRIVE
R_led[1] += LED_DEBUG_DRIVE
R_led[2] += LED_DEBUG

# --- J11: RJ45 keystone (inbound Cat5e) -------------------------------------
J11 = Part("Connector", "RJ45", footprint="Connector_RJ:RJ45_Amphenol_RJHSE5380", value="J11")
J11[1] += V12_CAT5E   # white-orange
J11[2] += V12_CAT5E   # orange
J11[3] += V12_CAT5E   # white-green
J11[4] += RS485_A
J11[5] += RS485_B
J11[6] += GND
J11[7] += GND
J11[8] += GND
# Shield NOT bonded at this end (single-point bond at battery side).

# --- Generate ---------------------------------------------------------------

if __name__ == "__main__":
    import os
    os.makedirs("outputs", exist_ok=True)
    generate_netlist(file_="outputs/display_side.net")
    try:
        generate_schematic(file_="outputs/display_side.kicad_sch")
    except Exception as exc:
        print(f"(schematic gen skipped: {exc})")
    print("OK — wrote outputs/display_side.net")
