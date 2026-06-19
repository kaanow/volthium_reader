"""Battery-side board — SKiDL source.

Generates a KiCad-compatible netlist when run on a machine that has the
KiCad symbol+footprint libraries available. See hardware/kicad/HANDOFF.md
for setup steps.

The intent of this file is to be the *source of truth* for the
schematic. The KiCad .kicad_sch is generated downstream and treated as
build output. Edit this file, not the .kicad_sch.

Run:
    python battery_side.py
Output:
    outputs/battery_side.net  (KiCad netlist; import into PCB editor)

Cross-references:
    docs/hardware/schematic_battery_side.md  — human-readable netlist + GPIO map
    docs/hardware/bom.md                     — part numbers
    docs/hardware/block_diagrams.md          — visual orientation
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

# Target tool. SKiDL supports KICAD6/7/8. Pick the latest stable.
set_default_tool(KICAD8)

# --- Nets -------------------------------------------------------------------

# Power
V24_RAW = Net("V24_RAW")        # straight from the 24V pack tap (before fuse)
V24_FUSED = Net("V24_FUSED")    # downstream of F1 + D1 reverse-protect
V24_SW = Net("V24_SW")          # switched by P-FET Q1 — kill switch for the whole rail
V3V3 = Net("3V3_SW")            # MCU rail, off TPS62933
V12_CAT5E = Net("V12_CAT5E")    # 12V going out the RJ45 to the kitchen
GND = Net("GND")

# 24V sense (un-switched — must survive deep sleep)
V24_SENSE = Net("V24_SENSE")    # ADC input, divided down from V24_RAW

# I²C
I2C_SDA = Net("I2C_SDA")
I2C_SCL = Net("I2C_SCL")

# UART to RS-485 (3.3V side)
UART_TX_3V3 = Net("UART_TX_3V3")
UART_RX_3V3 = Net("UART_RX_3V3")
DE_RE = Net("DE_RE")            # active high = transmit

# RS-485 differential pair (goes out RJ45)
RS485_A = Net("RS485_A")
RS485_B = Net("RS485_B")

# MOSFET hard-cut path
PWR_EN_N = Net("PWR_EN_N")      # ESP32 GPIO4, active-LOW enables Q1
Q1_GATE = Net("Q1_GATE")

# Override pushbutton
BTN_OVERRIDE = Net("BTN_OVERRIDE")   # ESP32 GPIO7 (RTC-wake capable)

# Onboard debug LED
LED_DEBUG = Net("LED_DEBUG")

# --- Component templates ----------------------------------------------------
#
# Use TEMPLATE pattern so we can spawn many of the same generic R/C without
# duplicating the library/footprint references.

R_template = Part("Device", "R", dest=TEMPLATE, footprint="Resistor_SMD:R_0603_1608Metric")
C_small = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0603_1608Metric")
C_bulk_0805 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_0805_2012Metric")
C_bulk_1210 = Part("Device", "C", dest=TEMPLATE, footprint="Capacitor_SMD:C_1210_3225Metric")

# --- MOD1: ESP32-S3-WROOM-1-N16R8 ------------------------------------------
# Symbol: RF_Module:ESP32-S3-WROOM-1
# Footprint: RF_Module:ESP32-S2-WROOM-1 (same module footprint family)

esp = Part(
    "RF_Module", "ESP32-S3-WROOM-1",
    footprint="RF_Module:ESP32-S2-WROOM-1",
    value="ESP32-S3-WROOM-1-N16R8",
)

# Power
esp["GND"] += GND
esp["3V3"] += V3V3
esp["EN"] += V3V3   # held high; RC reset network optional, kept simple here

# UART1 (to RS-485)
esp["IO17"] += UART_TX_3V3
esp["IO18"] += UART_RX_3V3

# RS-485 driver-enable
esp["IO2"] += DE_RE

# I²C to DS3231
esp["IO5"] += I2C_SDA
esp["IO6"] += I2C_SCL

# Voltage sense
esp["IO1"] += V24_SENSE

# Hard-cut MOSFET control
esp["IO4"] += PWR_EN_N

# Override button
esp["IO7"] += BTN_OVERRIDE

# Debug LED
esp["IO15"] += LED_DEBUG

# ESP module decoupling (close to VCC pin)
C_esp_bulk = C_bulk_0805(value="10uF")
C_esp_decoupling = C_small(value="100nF")
for cap in (C_esp_bulk, C_esp_decoupling):
    cap[1] += V3V3
    cap[2] += GND

# --- F1: 1A fuse on 24V input ----------------------------------------------
F1 = Part("Device", "Fuse", footprint="Fuse:Fuse_Blade_ATO_Littelfuse-0287", value="1A")
F1[1] += V24_RAW
F1[2] += Net("V24_F1OUT")

# --- D1: SS24 reverse-protect Schottky -------------------------------------
D1 = Part("Diode", "SS24", footprint="Diode_SMD:D_SMA", value="SS24")
D1["K"] += F1[2]   # cathode toward the load
D1["A"] += Net("V24_F1OUT")  # SS24 in series? Actually we want anti-reverse:
# rethink: typical anti-reverse is a P-FET-with-Schottky or a series diode.
# Series diode is fine at our 40 mA current. Use as: F1 -> D1 anode -> cathode -> V24_FUSED
# Reattach with explicit nets.

# undo the above quick attempt — do it explicitly
F1[2].name = "V24_AFTER_FUSE"
D1["A"] += F1[2]
D1["K"] += V24_FUSED

# --- TVS3: 24V input transient suppressor ----------------------------------
TVS3 = Part("Diode", "SMAJ15A", footprint="Diode_SMD:D_SMA", value="SMAJ15A")
TVS3[1] += V24_FUSED
TVS3[2] += GND

# --- U1: TPS62933 buck — 24V -> 3.3V ---------------------------------------
# Symbol: Regulator_Switching:TPS62933F
U1 = Part("Regulator_Switching", "TPS62933F", footprint="Package_SON:Texas_S-PDSO-N6_1.6x1.6mm")
U1["VIN"]  += V24_FUSED
U1["GND"]  += GND
U1["EN"]   += V24_FUSED       # always-on (hard-cut handled separately via Q1 path on V24_SW)
U1["SW"]   += Net("U1_SW")
U1["FB"]   += V3V3            # internal divider; TPS62933 fixed-3.3 variant ties FB to VOUT

L1 = Part("Device", "L", footprint="Inductor_SMD:L_0805_2012Metric", value="2.2uH")
L1[1] += U1["SW"]
L1[2] += V3V3

C_u1_in  = C_bulk_1210(value="22uF")
C_u1_out = C_bulk_1210(value="22uF")
C_u1_in[1]  += V24_FUSED;  C_u1_in[2]  += GND
C_u1_out[1] += V3V3;       C_u1_out[2] += GND

# --- U2: Recom R-78E12-1.0 buck — 24V -> 12V -------------------------------
# Recom modules are 3-pin (VIN, GND, VOUT). Use a generic 3-pin connector
# symbol, or a custom symbol — for the netlist a generic "MODULE" stub is
# enough; future session can swap to a proper Recom symbol if available
# in their library.
U2 = Part(
    "Regulator_Switching", "R-78E-1.0",
    footprint="Converter_DCDC:Converter_DCDC_RECOM_R-78E-1.0_THT",
    value="R-78E12-1.0",
)
U2["VIN"]  += V24_FUSED
U2["GND"]  += GND
U2["VOUT"] += V12_CAT5E

C_u2_in  = C_bulk_1210(value="22uF")
C_u2_out = C_bulk_1210(value="22uF")
C_u2_in[1]  += V24_FUSED; C_u2_in[2]  += GND
C_u2_out[1] += V12_CAT5E; C_u2_out[2] += GND

# --- 24V → 3.3V sense divider (R5/R6) --------------------------------------
R5 = R_template(value="100k")
R6 = R_template(value="11k")
R5[1] += V24_FUSED
R5[2] += V24_SENSE
R6[1] += V24_SENSE
R6[2] += GND

# Small filter cap on the ADC node
C_sense = C_small(value="100nF")
C_sense[1] += V24_SENSE
C_sense[2] += GND

# --- Q1/Q2 P-FET load switch ------------------------------------------------
# Q1 P-FET passes 24V to V24_SW when its gate is pulled to GND by Q2.
# Q2 N-FET driven by ESP32 PWR_EN_N (set LOW to enable; HIGH = pack disabled).
Q1 = Part("Transistor_FET", "AO3401A", footprint="Package_TO_SOT_SMD:SOT-23")
Q2 = Part("Transistor_FET", "AO3400A", footprint="Package_TO_SOT_SMD:SOT-23")

Q1["S"] += V24_FUSED
Q1["D"] += V24_SW
Q1["G"] += Q1_GATE

# Q1 default-OFF pull-up: Q1 gate to source (V24_FUSED) through R4
R4 = R_template(value="10k")
R4[1] += V24_FUSED
R4[2] += Q1_GATE

Q2["D"] += Q1_GATE
Q2["S"] += GND
Q2["G"] += PWR_EN_N

# (Optional) gate-source pulldown for Q2 to keep it off when PWR_EN_N is floating
R_q2_pulldown = R_template(value="100k")
R_q2_pulldown[1] += PWR_EN_N
R_q2_pulldown[2] += GND

# --- RTC1: DS3231 -----------------------------------------------------------
# Symbol: Timer_RTC:DS3231M (DS3231M is close enough to DS3231SN for the netlist)
RTC1 = Part("Timer_RTC", "DS3231M", footprint="Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm")
RTC1["VCC"] += V3V3
RTC1["GND"] += GND
RTC1["SDA"] += I2C_SDA
RTC1["SCL"] += I2C_SCL
RTC1["VBAT"] += Net("V_BAT_RTC")

# I²C pull-ups on V3V3
R_sda = R_template(value="4.7k"); R_sda[1] += I2C_SDA; R_sda[2] += V3V3
R_scl = R_template(value="4.7k"); R_scl[1] += I2C_SCL; R_scl[2] += V3V3

# CR2032 backup
BAT1 = Part("Battery", "Battery_Cell", footprint="Battery:BatteryHolder_Keystone_1066_1x12mm", value="CR2032")
BAT1[1] += Net("V_BAT_RTC")
BAT1[2] += GND

C_rtc = C_small(value="100nF"); C_rtc[1] += V3V3; C_rtc[2] += GND

# --- U3: SN65HVD3082 RS-485 transceiver ------------------------------------
U3 = Part("Interface_UART", "SN65HVD3082E", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
U3["R"]     += UART_RX_3V3   # receiver output → MCU RX
U3["RE"]    += DE_RE         # tied to DE so we have a single "transmit-enable" pin
U3["DE"]    += DE_RE
U3["D"]     += UART_TX_3V3   # driver input ← MCU TX
U3["VCC"]   += V3V3
U3["GND"]   += GND
U3["A"]     += RS485_A
U3["B"]     += RS485_B

C_u3 = C_small(value="100nF"); C_u3[1] += V3V3; C_u3[2] += GND

# 120Ω termination at this end of the bus (lift via jumper if not terminus)
R1 = R_template(value="120", footprint="Resistor_SMD:R_0805_2012Metric")
R1[1] += RS485_A
R1[2] += RS485_B

# Idle bias — pull A high, B low so the bus has a defined state when idle
R2 = R_template(value="680"); R2[1] += RS485_A; R2[2] += V3V3
R3 = R_template(value="680"); R3[1] += RS485_B; R3[2] += GND

# TVS1: differential clamp across A/B
TVS1 = Part("Diode", "SMAJ12CA", footprint="Diode_SMD:D_SMA", value="SMAJ12CA")
TVS1[1] += RS485_A
TVS1[2] += RS485_B

# --- BTN1: override pushbutton (panel-mount) --------------------------------
BTN1 = Part("Switch", "SW_Push", footprint="Button_Switch_SMD:SW_SPST_PRTH1JOH", value="OVERRIDE")
BTN1[1] += BTN_OVERRIDE
BTN1[2] += GND

R_btn = R_template(value="10k"); R_btn[1] += BTN_OVERRIDE; R_btn[2] += V3V3
C_btn = C_small(value="100nF"); C_btn[1] += BTN_OVERRIDE; C_btn[2] += GND

# --- LED + current-limit resistor -------------------------------------------
LED1 = Part("Device", "LED", footprint="LED_SMD:LED_0805_2012Metric", value="GREEN")
R_led = R_template(value="1k")

LED_DEBUG_DRIVE = Net("LED_DEBUG_DRIVE")
LED1["A"] += V3V3
LED1["K"] += LED_DEBUG_DRIVE
R_led[1] += LED_DEBUG_DRIVE
R_led[2] += LED_DEBUG   # ESP GPIO15 sinks to light the LED

# --- J1: RJ45 keystone (Cat5e to display end) ------------------------------
# T568B pinout — see docs/hardware/cat5e_pinout.md
J1 = Part("Connector", "RJ45", footprint="Connector_RJ:RJ45_Amphenol_RJHSE5380", value="J1")
J1[1] += V12_CAT5E   # white-orange
J1[2] += V12_CAT5E   # orange
J1[3] += V12_CAT5E   # white-green (paralleled +12)
J1[4] += RS485_A     # blue
J1[5] += RS485_B     # white-blue
J1[6] += GND         # green
J1[7] += GND         # white-brown
J1[8] += GND         # brown
# Shield: bonded to chassis ground at this end (covered by mounting; left
# uncalled here so we don't accidentally create a second GND net).

# --- J2: 2-pin terminal block for 24V pack tap -----------------------------
J2 = Part("Connector", "Conn_01x02", footprint="TerminalBlock:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", value="J2")
J2[1] += V24_RAW
J2[2] += GND

# --- Generate ---------------------------------------------------------------

if __name__ == "__main__":
    import os
    os.makedirs("outputs", exist_ok=True)
    generate_netlist(file_="outputs/battery_side.net")
    # If running KiCad 8 with eeschema support installed, also emit a .kicad_sch:
    try:
        generate_schematic(file_="outputs/battery_side.kicad_sch")
    except Exception as exc:
        print(f"(schematic gen skipped: {exc})")
    print("OK — wrote outputs/battery_side.net")
