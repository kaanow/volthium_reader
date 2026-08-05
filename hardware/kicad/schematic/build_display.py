#!/usr/bin/env python3
"""CP2 schematic — DISPLAY-side board entry point (volthium_display project).

All mechanics + the full gate stack live in core.py (shared with the
battery-side build.py). This file holds only the display board's design:
block drawings, sheet composition, and the per-board contract tables
(GOLDEN / EXACT_PARTS / ERC_ACCEPTED). Design source: cp1_display_side.md
(D26/D27/D29/D30/D34, F12 DNP bias, F15 wake architecture) + decisions
made at display CP2 (packet §15): J3 debug header upgraded to the keyed
2x3 ESP-Prog per DR-32 (same deep-sleep recovery argument as battery J5);
net names normalized to the battery-side convention (UART_TX_3V3 ->
RS485_DI, UART_RX_3V3 -> RS485_RO, DE -> RS485_DE, /RE -> RS485_nRE).

Run: <repo>/.venv/bin/python build_display.py   (from this directory)
"""
import sys

import core
from core import snap


# ---------------------------------------------------------------------------
# Power path
# ---------------------------------------------------------------------------

def blk_d_input(s, cx, cy):
    """Board input protection: V12_CAT5E (from J1 pins 1-3) -> F1 (MF-R025
    ~0.25 A PTC, DR-11) -> V12_PROT; TVS1 (SMAJ15A-13-F, unidirectional)
    clamp + C1 22uF input bulk on the protected rail. (cx,cy) = F1 centre."""
    yr = cy
    yg = snap(cy + 13.97)
    xin, xf1 = snap(cx - 16.51), cx
    xtv, xc1, xout = snap(cx + 15.24), snap(cx + 27.94), snap(cx + 38.1)
    f1 = s.place("Polyfuse", "F1", "MF-R025",
                 "volthium:Fuse_Bourns_MF-R025_THT_P5.08mm",
                 (xf1, yr), angle=90, tanchor="ud")
    fL = min(f1.values(), key=lambda p: p[0]); fR = max(f1.values(), key=lambda p: p[0])
    s.label("V12_CAT5E", (xin, yr), justify_h="right")
    s.wire((xin, yr), fL)
    # TVS1 is UNIDIRECTIONAL: D_TVS drawn cathode-up to the rail (same
    # convention as the approved battery-side TVS3 SMAJ15A, blk_u2).
    tv = s.place("D_TVS", "TVS1", "SMAJ15A-13-F", "D_SMA",
                 (xtv, snap(yr + 6.35)), angle=90, tanchor="r")
    tvT = min(tv.values(), key=lambda p: p[1]); tvB = max(tv.values(), key=lambda p: p[1])
    c1 = s.place("C", "C1", "22µF 25V", "C_1210_3225Metric",
                 (xc1, snap(yr + 3.81)), angle=0, tanchor="r")
    s.wire(fR, (xtv, yr)); s.wire((xtv, yr), c1["1"])
    s.wire(c1["1"], (xout, yr))
    s.label("V12_PROT", (xout, yr), justify_h="left")
    s.wire((xtv, yr), tvT); s.wire(tvB, (xtv, yg))
    s.wire(c1["2"], (xc1, yg))
    xgl = snap(xtv - 10.16)
    s.wire((xgl, yg), (xc1, yg))
    s.label("GND", (xgl, yg), justify_h="right")


def blk_d_reg(s, cx, cy):
    """12 V -> 3.3 V conversion: U1 Recom R-78E3.3-0.5 (SIP3 module, no
    inductor BOM); C2 10uF output bulk. Output rail V3V3_REG feeds the
    TPS2116 mux VIN2 (D29) — it is NOT the system V3V3. (cx,cy)=U1."""
    yg = snap(cy + 13.97)
    u1 = s.place("R-78E3.3-0.5", "U1", "R-78E3.3-0.5",
                 "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT",
                 (cx, cy), angle=0, tanchor="u", tgap=2.0)
    IN, GND, OUT = u1["1"], u1["2"], u1["3"]
    xin = snap(cx - 22.86)
    s.label("V12_PROT", (xin, IN[1]), justify_h="right")
    s.wire((xin, IN[1]), IN)
    xc2, xout = snap(cx + 15.24), snap(cx + 25.4)
    s.wire(OUT, (xc2, OUT[1]))
    c2 = s.place("C", "C2", "10µF", "C_0805_2012Metric",
                 (xc2, snap(OUT[1] + 3.81)), tanchor="r")
    s.wire((xc2, OUT[1]), (xout, OUT[1]))
    s.label("V3V3_REG", (xout, OUT[1]), justify_h="left")
    s.wire(c2["2"], (xc2, yg))
    xgl = snap(cx - 10.16)
    s.wire((xgl, yg), (xc2, yg)); s.wire(GND, (GND[0], yg))
    s.label("GND", (xgl, yg), justify_h="right")


def blk_d_usb_power(s, cx, cy):
    """USB maintenance power (D29, mirrors the approved battery blk_usb_power).
    U3-LDO AP2112 (VBUS->3V3_USB) wired directly into U4-MUX TPS2116 priority
    mux: MODE/PR1 -> VIN1 (USB preferred); VIN2 = V3V3_REG (from U1); OUT =
    the system V3V3 rail. No UVLO bypass chain — the display has no
    supervisor (it is shed by the battery side). (cx,cy) = U3-LDO centre."""
    yg = snap(cy + 20.32)
    u5 = s.place("AP2112K-3.3", "U3-LDO", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
                 (cx, cy), angle=0, tanchor="u", tgap=3.0)
    VIN, GND5, EN5, VOUT5 = u5["1"], u5["2"], u5["3"], u5["5"]
    s.no_connect(u5["4"])
    xcu1, xvbus = snap(cx - 15.24), snap(cx - 25.4)
    cu1 = s.place("C", "C_usb1", "1µF", "C_0603_1608Metric", (xcu1, snap(VIN[1] + 3.81)), tanchor="l")
    s.label("VBUS", (xvbus, VIN[1]), justify_h="right")
    s.wire((xvbus, VIN[1]), cu1["1"]); s.wire(cu1["1"], VIN); s.wire(cu1["2"], (xcu1, yg))
    s.wire(EN5, VIN); s.wire(GND5, (GND5[0], yg))
    u6 = s.place("TPS2116DRL", "U4-MUX", "TPS2116DRLR", "Package_TO_SOT_SMD:SOT-583-8",
                 (snap(cx + 40.64), cy), angle=0, tanchor="u", tgap=3.0)
    GND6, VOUT6, VIN1, PR1, MODE, VIN2, ST = u6["1"], u6["2"], u6["3"], u6["4"], u6["5"], u6["6"], u6["8"]
    s.no_connect(ST)
    # 3V3_USB bus: U3-LDO VOUT + C_usb2 -> U4-MUX VIN1/PR1/MODE (local wires)
    xb = snap(cx + 17.78)
    s.wire(VOUT5, (xb, VOUT5[1]))
    s.wire((xb, VIN1[1]), (xb, MODE[1]))
    s.wire((xb, VIN1[1]), VIN1); s.wire((xb, PR1[1]), PR1); s.wire((xb, MODE[1]), MODE)
    cu2 = s.place("C", "C_usb2", "1µF", "C_0603_1608Metric", (snap(cx + 10.16), snap(VOUT5[1] + 3.81)), tanchor="r")
    s.wire(cu2["1"], (cu2["1"][0], VOUT5[1])); s.wire(cu2["2"], (cu2["1"][0], yg))
    # VIN2 <- V3V3_REG ; OUT -> V3V3 (+ C_mux bulk for RCB on hot-plug)
    s.wire(VIN2, (VIN2[0], snap(VIN2[1] + 6.35)))
    s.wire((VIN2[0], snap(VIN2[1] + 6.35)), (snap(VIN2[0] - 2.54), snap(VIN2[1] + 6.35)))
    s.label("V3V3_REG", (snap(VIN2[0] - 2.54), snap(VIN2[1] + 6.35)), justify_h="right")
    s.wire(VOUT6, (snap(VOUT6[0] + 8.89), VOUT6[1]))
    s.label("V3V3", (snap(VOUT6[0] + 15.24), VOUT6[1]), justify_h="left")
    s.wire((snap(VOUT6[0] + 8.89), VOUT6[1]), (snap(VOUT6[0] + 15.24), VOUT6[1]))
    xcm = snap(VOUT6[0] + 8.89)
    cm = s.place("C", "C_mux", "47µF", "C_0805_2012Metric", (xcm, snap(VOUT6[1] + 6.35)), tanchor="l")
    s.wire(cm["1"], (xcm, VOUT6[1])); s.wire(cm["2"], (xcm, yg))
    s.wire(u6["7"], (xcm, u6["7"][1]))   # VOUT twin (pin 7) joins the output node
    s.wire(GND6, (GND6[0], yg))
    s.wire((snap(xcu1 - 5.08), yg), (xcm, yg))
    s.label("GND", (snap(xcu1 - 5.08), yg), justify_h="right")


def blk_d_pwr_flags(s, cx, cy):
    """PWR_FLAGs: nets driven by board-input connectors or through passives
    (V12_CAT5E from J1, V12_PROT past the PTC, VBUS from USB-C) + GND ref."""
    for i, net in enumerate(("V12_CAT5E", "V12_PROT", "VBUS", "GND")):
        x = snap(cx + i * 17.78)
        # tanchor="u": ref + value both ABOVE the glyph so the net-label flag
        # below can't print over the "PWR_FLAG" value text (F15).
        pf = s.place("PWR_FLAG", f"#FLG{i+1}", "PWR_FLAG", "", (x, cy), angle=0, tanchor="u")
        pin = pf["1"]
        s.wire(pin, (pin[0], snap(pin[1] + 5.08)))
        s.label(net, (pin[0], snap(pin[1] + 5.08)), justify_h="left")


# ---------------------------------------------------------------------------
# Connectors & I/O
# ---------------------------------------------------------------------------

def blk_d_j1_rj45(s, cx, cy):
    """J1 RJ45 to the battery side (Würth 615008145521 WR-MJ, right-angle
    tab-down, shielded, magnetics-free — DR-10, datasheet-verified). T568B
    per cat5e_pinout: 1-3 = V12_CAT5E, 4 = RS485_A, 5 = RS485_B, 6-8 = GND.
    Shield drain NC at THIS end — single-point bond lives at the battery
    side (DR-19). Footprint = manufacturer-official (repo-local lib, see
    hardware/kicad/footprints/README.md). (cx,cy)=J1 centre."""
    j1 = s.place("RJ45_Shielded", "J1", "Wurth_615008145521",
                 "volthium:J_Wurth_WR-MJ_615008145521", (cx, cy), angle=0,
                 tanchor="u", tgap=6.35)
    NET = {"1": "V12_CAT5E", "2": "V12_CAT5E", "3": "V12_CAT5E", "4": "RS485_A",
           "5": "RS485_B", "6": "GND", "7": "GND", "8": "GND"}
    for num, net in NET.items():
        p = j1[num]; s.wire(p, (snap(p[0] + 10.16), p[1]))
        s.label(net, (snap(p[0] + 10.16), p[1]), justify_h="left")
    s.no_connect(j1["SH"])   # DR-19: shield bonded at the battery end only


def blk_d_usbc(s, cx, cy):
    """USB-C bench/recovery port J-USB (D27; GCT USB4085, same SKU as the
    battery board's J3). VBUS/GND 4 pads each (spread in the symbol); D± ->
    native ESP USB; CC1/CC2 5.1k UFP pull-downs; SBU unused; shield -> GND.
    U-ESD USBLC6-2SC6Y on D+/D-/VBUS. (cx,cy)=J-USB."""
    yg = snap(cy + 30.48)
    j = s.place("USB_C_16P", "J-USB", "USB4085-GF-A",
                "Connector_USB:USB_C_Receptacle_GCT_USB4085", (cx, cy), angle=0, tanchor="u", tgap=3.0)

    def bus(pins, net, dx=10.16):
        xb = snap(max(p[0] for p in pins) + dx)
        for p in pins: s.wire(p, (xb, p[1]))
        y0, y1 = min(p[1] for p in pins), max(p[1] for p in pins)
        s.wire((xb, y0), (xb, y1))
        s.wire((xb, y0), (snap(xb + 7.62), y0)); s.label(net, (snap(xb + 7.62), y0), justify_h="left")
    bus([j[n] for n in ("A4", "A9", "B4", "B9")], "VBUS")
    bus([j["A7"], j["B7"]], "USB_DM", 7.62)
    bus([j["A6"], j["B6"]], "USB_DP", 7.62)
    for pin, ref, dx in (("A5", "R_cc1", 40.64), ("B5", "R_cc2", 27.94)):
        p = j[pin]; xr = snap(p[0] + dx); s.wire(p, (xr, p[1]))
        r = s.place("R", ref, "5.1k", "R_0805_2012Metric", (xr, snap(p[1] + 6.35)), tanchor="r")
        s.wire((xr, p[1]), r["1"]); s.wire(r["2"], (xr, snap(r["2"][1] + 2.54)))
        s.label("GND", (xr, snap(r["2"][1] + 2.54)), justify_h="left")
    s.no_connect(j["A8"]); s.no_connect(j["B8"])         # SBU unused
    ux, uy = snap(cx + 50.8), snap(cy - 40.64)
    ue = s.place("USBLC6-2SC6", "U-ESD", "USBLC6-2SC6Y", "Package_TO_SOT_SMD:SOT-23-6",
                 (ux, uy), angle=0, tanchor="r")
    s.wire(ue["1"], (snap(ue["1"][0] - 7.62), ue["1"][1]))
    s.label("USB_DP", (snap(ue["1"][0] - 7.62), ue["1"][1]), justify_h="right")
    s.wire(ue["3"], (snap(ue["3"][0] - 7.62), ue["3"][1]))
    s.label("USB_DM", (snap(ue["3"][0] - 7.62), ue["3"][1]), justify_h="right")
    s.wire(ue["5"], (ue["5"][0], snap(ue["5"][1] - 5.08)))
    s.label("VBUS", (ue["5"][0], snap(ue["5"][1] - 5.08)), justify_h="left")
    s.wire(ue["2"], (ue["2"][0], snap(ue["2"][1] + 5.08)))
    s.label("GND", (ue["2"][0], snap(ue["2"][1] + 5.08)), justify_h="left")
    s.no_connect(ue["6"]); s.no_connect(ue["4"])
    gp = [j[n] for n in ("A1", "A12", "B1", "B12")]
    for p in gp: s.wire(p, (p[0], yg))
    gxs = sorted(p[0] for p in gp)
    s.wire((snap(gxs[0] - 7.62), yg), (gxs[-1], yg))
    s.label("GND", (snap(gxs[0] - 7.62), yg), justify_h="right")
    sh = j["SH"]; s.wire(sh, (snap(sh[0] - 7.62), sh[1]))
    s.label("GND", (snap(sh[0] - 7.62), sh[1]), justify_h="right")


def blk_d_dbg(s, cx, cy):
    """J3 debug/programming header — keyed 2x3 IDC, the REAL ESP-Prog
    "Program" connector, upgraded from CP1's 4-pin UART header at display
    CP2 (DR-32: the same deep-sleep recovery argument as the battery J5 —
    this board Deep-sleeps between frames, so a USB-independent
    force-download path is required). 1=EN, 2=VDD, 3=TXD(target), 4=GND,
    5=RXD(target), 6=IO0. Names are TARGET-perspective (ESP-Prog SCH V2.1
    on file: FT_TXD->0R->ESP_RXD0). (cx,cy) = J3 centre."""
    j = s.place("Conn_02x03_Odd_Even", "J3", "ESP-Prog",
                "Connector_IDC:IDC-Header_2x03_P2.54mm_Vertical",
                (cx, cy), angle=0, tanchor="u", tgap=3.0)
    for pn, net in (("1", "MCU_EN"), ("3", "DBG_TXD"), ("5", "DBG_RXD")):
        pin = j[pn]; e = (snap(pin[0] - 10.16), pin[1])
        s.wire(pin, e); s.label(net, e, justify_h="right")
    for pn, net in (("2", "V3V3"), ("4", "GND"), ("6", "BOOT")):
        pin = j[pn]; e = (snap(pin[0] + 10.16), pin[1])
        s.wire(pin, e); s.label(net, e, justify_h="left")


# ---------------------------------------------------------------------------
# RS-485, e-paper, buttons
# ---------------------------------------------------------------------------

def blk_d_rs485(s, cx, cy):
    """RS-485 link to the battery side (U2 THVD1400, D34). Control: RO/nRE/
    DE/DI -> MCU (GPIO18/15/2/17; nRE latched LOW in Deep-sleep via RTC hold
    so the receiver can wake ext1 — F09/F15). A/B -> J1 pins 4/5 with the
    120R terminator R2 in SERIES with the J5 lift jumper (this end is the
    bus terminus -> J5 fitted by default), TVS2 across the pair, and the
    R3/R4 idle-bias footprints DNP by default (F12: THVD1400 full fail-safe
    RX needs no static bias; stuff at CP5 bench only if EMI shows a need).
    C7 decoupling. (cx,cy)=U2 centre."""
    u2 = s.place("THVD1400D", "U2", "THVD1400DR", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                 (cx, cy), angle=0, tanchor="u", tgap=5.08)
    RO, nRE, DE, DI = u2["1"], u2["2"], u2["3"], u2["4"]
    GND, A, B, VCC = u2["5"], u2["6"], u2["7"], u2["8"]

    xlbl = snap(cx - 25.4)
    for pin, net in ((RO, "RS485_RO"), (nRE, "RS485_nRE"), (DE, "RS485_DE"), (DI, "RS485_DI")):
        s.label(net, (xlbl, pin[1]), justify_h="right")
        s.wire((xlbl, pin[1]), pin)

    # VCC -> V3V3 (always-on while the board has power); C7 decoupling
    yv = snap(VCC[1] - 3.81)
    xc7 = snap(cx - 20.32)
    xv3 = snap(cx - 27.94)
    s.wire(VCC, (VCC[0], yv))
    s.wire((VCC[0], yv), (xc7, yv)); s.wire((xc7, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="right")
    c7 = s.place("C", "C7", "100nF", "C_0603_1608Metric",
                 (xc7, snap(yv + 3.81)), angle=0, tanchor="l")
    ygc = snap(c7["2"][1] + 2.54)
    s.wire(c7["2"], (xc7, ygc)); s.label("GND", (xc7, ygc), justify_h="right")
    ygp = snap(GND[1] + 2.54)
    s.wire(GND, (GND[0], ygp)); s.label("GND", (GND[0], ygp), justify_h="left")

    # A/B bus (right): R2-through-J5 termination + TVS2 across, then bias
    # legs R3 (A->V3V3) and R4 (B->GND), both DNP, then out to J1.
    yA, yB = A[1], snap(A[1] + 15.24)
    xstep = snap(cx + 12.7)
    xbr1, xbr2 = snap(cx + 17.78), snap(cx + 33.02)
    xb3, xlblB = snap(cx + 40.64), snap(cx + 48.26)
    s.wire(A, (xbr1, yA))
    s.wire(B, (xstep, B[1]))
    s.wire((xstep, B[1]), (xstep, yB)); s.wire((xstep, yB), (xbr1, yB))
    nT = snap(yA + 7.62)
    r2 = s.place("R", "R2", "120", "R_0805_2012Metric",
                 (xbr1, snap(yA + 3.81)), angle=0, tanchor="r", bw=2.0)
    j5 = s.place("Conn_01x02", "J5", "TERM",
                 "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                 (snap(xbr1 + 5.08), snap(yA + 10.16)), angle=0, tanchor="r")
    j5t = min(j5.values(), key=lambda p: p[1]); j5b = max(j5.values(), key=lambda p: p[1])
    s.wire((xbr1, nT), j5t); s.wire(j5b, (xbr1, yB))
    tvs = s.place("D_TVS", "TVS2", "SMAJ12CA-13-F", "D_SMA", (xbr2, snap((yA + yB) / 2)), angle=90, tanchor="r")
    tvT = min(tvs.values(), key=lambda p: p[1]); tvB = max(tvs.values(), key=lambda p: p[1])
    s.wire((xbr1, yA), (xbr2, yA)); s.wire((xbr2, yA), (xb3, yA))
    s.wire((xbr1, yB), (xbr2, yB)); s.wire((xbr2, yB), (xb3, yB))
    s.wire((xbr2, yA), tvT); s.wire((xbr2, yB), tvB)
    # R3/R4 idle-bias legs, DNP (F12). R3: A rail up to V3V3; R4: B rail
    # down to GND. Footprints stay for a CP5 bench stuff at ~330R.
    r3 = s.place("R", "R3", "330", "R_0805_2012Metric",
                 (xb3, snap(yA - 6.35)), angle=0, tanchor="r", dnp=True)
    s.wire((xb3, yA), r3["2"]); s.wire(r3["1"], (xb3, snap(r3["1"][1] - 2.54)))
    s.label("V3V3", (xb3, snap(r3["1"][1] - 2.54)), justify_h="right")
    r4 = s.place("R", "R4", "330", "R_0805_2012Metric",
                 (xb3, snap(yB + 6.35)), angle=0, tanchor="r", dnp=True)
    s.wire((xb3, yB), r4["1"]); s.wire(r4["2"], (xb3, snap(r4["2"][1] + 2.54)))
    s.label("GND", (xb3, snap(r4["2"][1] + 2.54)), justify_h="right")
    s.wire((xb3, yA), (xlblB, yA)); s.wire((xb3, yB), (xlblB, yB))
    s.label("RS485_A", (xlblB, yA), justify_h="left")
    s.label("RS485_B", (xlblB, yB), justify_h="left")


def blk_d_epd(s, cx, cy):
    """J2 e-paper interface: JST-PH 2.0 mm 8-pin (S8B-PH-K-S), matching the
    Waveshare 4.2" (B) Module's own PH2.0 connector (DR-7/F21 evidence on
    file) -> off-the-shelf PH<->PH cable, keyed, no crimp tool. Canonical
    Waveshare SPI pin order. C6 1uF panel-VCC bulk against refresh dips.
    (cx,cy)=J2 centre."""
    # CP4/D39: SIDE-entry (S8B), not top-entry (B8B). Datasheet ePH p.1:
    # the top-entry version's MATED height is 8.0 mm, which is the entire
    # PCB-front -> module-back gap (cp1_display_side §2.1) with nothing
    # left for the cable. Side-entry is a 7.6 mm header whose cable exits
    # HORIZONTALLY. Widening the gap instead would push the button plunger
    # to ~17.5 mm, past the 6x6xN catalog range.
    j2 = s.place("Conn_01x08", "J2", "JST_S8B-PH-K-S",
                 "Connector_JST:JST_PH_S8B-PH-K_1x08_P2.00mm_Horizontal",
                 (cx, cy), angle=0, tanchor="u", tgap=3.0)
    NET = {"1": "V3V3", "2": "GND", "3": "SPI_MOSI", "4": "SPI_SCK",
           "5": "EPD_CS", "6": "EPD_DC", "7": "EPD_RST", "8": "EPD_BUSY"}
    for num, net in NET.items():
        p = j2[num]; s.wire(p, (snap(p[0] - 10.16), p[1]))
        s.label(net, (snap(p[0] - 10.16), p[1]), justify_h="right")
    # C6: panel VCC bulk, its own column right of J2
    xc6 = snap(cx + 12.7)
    c6 = s.place("C", "C6", "1µF", "C_0603_1608Metric",
                 (xc6, snap(cy - 2.54)), angle=0, tanchor="r")
    s.wire(c6["1"], (xc6, snap(c6["1"][1] - 2.54)))
    s.label("V3V3", (xc6, snap(c6["1"][1] - 2.54)), justify_h="left")
    s.wire(c6["2"], (xc6, snap(c6["2"][1] + 2.54)))
    s.label("GND", (xc6, snap(c6["2"][1] + 2.54)), justify_h="left")


def blk_d_btns(s, cx, cy):
    """User input: BTN1-3 tall-actuator THT tactiles (bottom edge, D7),
    active-LOW into RTC-capable GPIO12/13/14 (ext1 wake mask, F15). Per
    button: R5/6/7 1M pull-up to V3V3 (power-first Iq) + C8/9/10 100nF RC
    debounce (~100 ms, D-OPEN-10) + switch to GND. Exact plunger height is
    locked at CP3 from the depth stack (footprint pattern is the 6x6 THT
    family). (cx,cy) = middle button column top."""
    for i, (bref, rref, cref, net) in enumerate((
            ("BTN1", "R5", "C8", "BTN1_IN"),
            ("BTN2", "R6", "C9", "BTN2_IN"),
            ("BTN3", "R7", "C10", "BTN3_IN"))):
        x = snap(cx + (i - 1) * 38.1)
        yv3 = snap(cy - 12.7)          # V3V3 label anchor
        yn = cy                        # BTNn_IN node rail
        yg = snap(cy + 19.05)          # GND rail per column
        r = s.place("R", rref, "1M", "R_0805_2012Metric",
                    (x, snap(cy - 6.35)), angle=0, tanchor="l")
        s.wire(r["1"], (x, yv3)); s.label("V3V3", (x, yv3), justify_h="right")
        s.wire(r["2"], (x, yn))
        xlbl = snap(x + 11.43)
        s.wire((x, yn), (xlbl, yn)); s.label(net, (xlbl, yn), justify_h="left")
        # button: node -> pin 1 (top at angle 270 — probed, not hand-derived:
        # at angle 90 the machine put pin 2 on top), pin 2 -> GND
        bt = s.place("SW_Push", bref, "6x6 tall-actuator",
                     "Button_Switch_THT:SW_PUSH_6mm_H13mm",
                     (snap(x - 3.81), snap(cy + 8.89)), angle=270, tanchor="r", bh=8.0)
        btT = min(bt.values(), key=lambda p: p[1]); btB = max(bt.values(), key=lambda p: p[1])
        s.wire(btT, (btT[0], yn)); s.wire((btT[0], yn), (x, yn))
        s.wire(btB, (btB[0], yg))
        # debounce cap across the button (node -> GND), own column left
        xc = snap(x - 12.7)
        c = s.place("C", cref, "100nF", "C_0603_1608Metric",
                    (xc, snap(cy + 8.89)), angle=0, tanchor="l")
        s.wire((x, yn), (xc, yn)); s.wire((xc, yn), c["1"])
        s.wire(c["2"], (xc, yg))
        s.wire((xc, yg), (btB[0], yg))
        s.label("GND", (snap(xc - 5.08), yg), justify_h="right")
        s.wire((snap(xc - 5.08), yg), (xc, yg))


# ---------------------------------------------------------------------------
# MCU
# ---------------------------------------------------------------------------

def blk_d_mcu(s, cx, cy):
    """MOD1 ESP32-S3-WROOM-1-N16R8 (D31: same SKU as battery; D26: radio
    unused, RF disabled in firmware, no antenna keepout). GPIO map per
    cp1_display_side.md §6 with the CP2 net-name normalization: EPD SPI on
    IO5-10, buttons IO12/13/14 (RTC ext1 wake), RS-485 DE=IO2, nRE=IO15
    (RTC hold in Deep-sleep), DI=IO17, RO=IO18 (ext1 wake), native USB
    D-/D+ = IO19/20, UART0 -> J3 debug, IO0 strap -> BOOT (J3.6). Straps
    IO3/IO45/IO46 left NC (internal defaults, F05). EN: R1 10k pull-up +
    C5 1uF soft-start. (cx,cy)=module centre."""
    mod = s.place("ESP32-S3-WROOM-1", "MOD1", "ESP32-S3-WROOM-1-N16R8",
                  "volthium:ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout", (cx, cy), angle=0, tanchor="u", tgap=9.0)
    NETS = {"3": "MCU_EN",
            "5": "EPD_CS", "6": "EPD_DC", "7": "EPD_RST", "12": "EPD_BUSY",
            "17": "SPI_SCK", "18": "SPI_MOSI",
            "20": "BTN1_IN", "21": "BTN2_IN", "22": "BTN3_IN",
            "38": "RS485_DE", "8": "RS485_nRE", "10": "RS485_DI", "11": "RS485_RO",
            "13": "USB_DM", "14": "USB_DP",
            "27": "BOOT", "37": "DBG_TXD", "36": "DBG_RXD"}
    for num, net in NETS.items():
        pin = mod[num]
        if pin[0] < cx:
            lbl = (snap(pin[0] - 16.51), pin[1]); s.label(net, lbl, justify_h="right")
        else:
            lbl = (snap(pin[0] + 16.51), pin[1]); s.label(net, lbl, justify_h="left")
        s.wire(lbl, pin)
    # 3V3 -> rail left, C3/C4 decoupling
    v3 = mod["2"]; yv = snap(v3[1] - 7.62)
    s.wire(v3, (v3[0], yv))
    xc3, xc4, xv3 = snap(cx - 15.24), snap(cx - 27.94), snap(cx - 38.1)
    s.wire((v3[0], yv), (xc3, yv)); s.wire((xc3, yv), (xc4, yv)); s.wire((xc4, yv), (xv3, yv))
    s.label("V3V3", (xv3, yv), justify_h="right")
    for xc, ref, val in ((xc3, "C3", "10µF"), (xc4, "C4", "100nF")):
        c = s.place("C", ref, val, "C_0805_2012Metric" if ref == "C3" else "C_0603_1608Metric",
                    (xc, snap(yv - 3.81)), tanchor="l")
        s.wire(c["1"], (xc, snap(c["1"][1] - 2.54)))
        s.label("GND", (xc, snap(c["1"][1] - 2.54)), justify_h="right")
    # GND: 3 bottom pins (1/40/41 spread in the symbol) -> short rail
    yg = snap(mod["1"][1] + 6.35)
    gxs = sorted(mod[n][0] for n in ("1", "40", "41"))
    for n in ("1", "40", "41"):
        s.wire(mod[n], (mod[n][0], yg))
    s.wire((snap(gxs[0] - 7.62), yg), (gxs[-1], yg))
    s.label("GND", (snap(gxs[0] - 7.62), yg), justify_h="right")
    # EN network below the module: R1 pull-up + C5 soft-start
    yrail = snap(cy + 43.18); ylbl = snap(yrail + 11.43)
    xr1 = snap(cx - 7.62)
    s.label("V3V3", (snap(xr1 - 8.89), yrail), justify_h="right")
    s.wire((snap(xr1 - 8.89), yrail), (xr1, yrail))
    r1 = s.place("R", "R1", "10k", "R_0805_2012Metric", (xr1, snap((yrail + ylbl) / 2)), tanchor="l")
    s.wire(r1["1"], (xr1, yrail))
    s.wire(r1["2"], (xr1, ylbl)); s.label("MCU_EN", (xr1, ylbl), justify_h="left")
    xc5 = snap(cx + 7.62)
    c5 = s.place("C", "C5", "1µF", "C_0603_1608Metric", (xc5, snap((yrail + ylbl) / 2)), tanchor="l")
    s.wire(c5["1"], (xc5, yrail)); s.label("MCU_EN", (xc5, yrail), justify_h="left")
    s.wire(c5["2"], (xc5, ylbl)); s.label("GND", (xc5, ylbl), justify_h="left")
    # unused GPIOs (incl. straps IO3/45/46 per F05) -> no-connect
    used = set(NETS) | {"2", "1", "40", "41"}
    for num, pin in mod.items():
        if num not in used:
            s.no_connect(pin)


# ---- sheet composition ------------------------------------------------------
SHEETS = [
    ("sheet_d_power", "Display — Power path", [
        (blk_d_input, 60, 62), (blk_d_reg, 190, 62),
        (blk_d_usb_power, 95, 130), (blk_d_pwr_flags, 185, 130)]),
    ("sheet_d_conn", "Display — Connectors & I/O", [
        (blk_d_j1_rj45, 205, 60), (blk_d_usbc, 60, 120), (blk_d_dbg, 185, 135)]),
    ("sheet_d_periph", "Display — RS-485, e-paper, buttons", [
        (blk_d_rs485, 85, 62), (blk_d_epd, 205, 62), (blk_d_btns, 140, 135)]),
    ("sheet_d_mcu", "Display — MCU (ESP32-S3)", [(blk_d_mcu, 145, 105)]),
]


# ---- GOLDEN connectivity contracts — hand-written FROM THE DESIGN DOCS ------
# (cp1_display_side.md nets/pinouts + datasheet pin tables), independently of
# the drawing code, checked against kicad-cli's exported netlist every build.
GOLDEN = [
    # -- input protection chain (DR-11/DR-15)
    ("on",   ("J1", "1"), "V12_CAT5E",  "Cat5e 12V on RJ45 1"),
    ("on",   ("J1", "2"), "V12_CAT5E",  "Cat5e 12V on RJ45 2"),
    ("on",   ("J1", "3"), "V12_CAT5E",  "Cat5e 12V on RJ45 3"),
    ("on",   ("J1", "4"), "RS485_A",    "Cat5e: A on 4 (matches battery J2.4)"),
    ("on",   ("J1", "5"), "RS485_B",    "Cat5e: B on 5 (matches battery J2.5)"),
    ("on",   ("J1", "6"), "GND",        "Cat5e grounds 6-8"),
    ("on",   ("J1", "7"), "GND",        "Cat5e grounds 6-8"),
    ("on",   ("J1", "8"), "GND",        "Cat5e grounds 6-8"),
    ("diff", ("J1", "SH"), ("J1", "8"), "shield drain NC at display end (DR-19)"),
    ("on",   ("F1", "1"), "V12_CAT5E",  "PTC from the jack"),
    ("on",   ("F1", "2"), "V12_PROT",   "PTC -> protected rail"),
    ("on",   ("TVS1", "2"), "V12_PROT", "clamp cathode on the protected rail"),
    ("on",   ("TVS1", "1"), "GND",      "clamp return"),
    ("on",   ("C1", "1"), "V12_PROT",   "input bulk on the protected rail"),
    # -- regulator (R-78E3.3: 1=VIN 2=GND 3=VOUT)
    ("on",   ("U1", "1"), "V12_PROT",   "R-78E VIN behind PTC+TVS"),
    ("on",   ("U1", "2"), "GND",        "R-78E GND"),
    ("on",   ("U1", "3"), "V3V3_REG",   "R-78E OUT feeds the mux, NOT V3V3"),
    ("on",   ("C2", "1"), "V3V3_REG",   "output bulk"),
    # -- USB power mux (D29; TPS2116: 1=GND 2/7=VOUT 3=VIN1 4=PR1 5=MODE 6=VIN2)
    ("on",   ("U3-LDO", "1"), "VBUS",   "LDO from USB"),
    ("same", ("U3-LDO", "5"), ("U4-MUX", "3"), "LDO out -> mux VIN1 (local wire)"),
    ("same", ("U4-MUX", "3"), ("U4-MUX", "4"), "PR1 tied to VIN1"),
    ("same", ("U4-MUX", "3"), ("U4-MUX", "5"), "MODE tied to VIN1 (priority mode)"),
    ("on",   ("U4-MUX", "6"), "V3V3_REG", "mux VIN2 from the R-78E"),
    ("on",   ("U4-MUX", "2"), "V3V3",   "mux OUT = the system rail"),
    ("same", ("U4-MUX", "2"), ("U4-MUX", "7"), "both VOUT pins joined"),
    ("diff", ("U4-MUX", "2"), ("U4-MUX", "6"), "mux must separate VIN2 from OUT"),
    ("diff", ("U4-MUX", "2"), ("U4-MUX", "3"), "mux must separate VIN1 from OUT"),
    ("on",   ("C_mux", "1"), "V3V3",    "OUT bulk (RCB on hot-plug)"),
    ("diff", ("U1", "3"), ("U4-MUX", "2"), "V3V3_REG never shorts to V3V3"),
    # -- USB-C port (D27)
    ("same", ("J-USB", "A5"), ("R_cc1", "1"), "CC1 5.1k"),
    ("same", ("J-USB", "B5"), ("R_cc2", "1"), "CC2 5.1k"),
    ("on",   ("R_cc1", "2"), "GND",     "UFP advertisement"),
    ("on",   ("R_cc2", "2"), "GND",     "UFP advertisement"),
    ("on",   ("U-ESD", "1"), "USB_DP",  "ESD on D+"),
    ("on",   ("U-ESD", "3"), "USB_DM",  "ESD on D-"),
    ("on",   ("U-ESD", "5"), "VBUS",    "ESD rail clamp"),
    ("on",   ("U-ESD", "2"), "GND",     "ESD return"),
    ("on",   ("MOD1", "13"), "USB_DM",  "native USB D- = IO19"),
    ("on",   ("MOD1", "14"), "USB_DP",  "native USB D+ = IO20"),
    # -- RS-485 (THVD1400: 1=RO 2=/RE 3=DE 4=DI 5=GND 6=A 7=B 8=VCC; D34)
    ("on",   ("U2", "8"), "V3V3",       "transceiver on the system rail"),
    ("on",   ("U2", "5"), "GND",        "transceiver GND"),
    ("on",   ("U2", "6"), "RS485_A",    "A line"),
    ("on",   ("U2", "7"), "RS485_B",    "B line"),
    ("on",   ("U2", "1"), "RS485_RO",   "RO -> MCU RX"),
    ("on",   ("U2", "2"), "RS485_nRE",  "/RE <- MCU (RTC-held LOW in sleep)"),
    ("on",   ("U2", "3"), "RS485_DE",   "DE <- MCU"),
    ("on",   ("U2", "4"), "RS485_DI",   "DI <- MCU TX"),
    ("same", ("MOD1", "11"), ("U2", "1"), "RO -> IO18 (ext1 wake mask member)"),
    ("same", ("MOD1", "8"), ("U2", "2"),  "/RE on IO15 (RTC-capable, gpio_hold)"),
    ("same", ("MOD1", "38"), ("U2", "3"), "DE on IO2 (internal pull-down safe)"),
    ("same", ("MOD1", "10"), ("U2", "4"), "DI on IO17"),
    ("same", ("R2", "1"), ("U2", "6"),  "term top on A"),
    ("same", ("R2", "2"), ("J5", "1"),  "term in SERIES with the J5 lift"),
    ("same", ("J5", "2"), ("U2", "7"),  "J5 returns to B"),
    ("diff", ("R2", "2"), ("U2", "7"),  "term must go THROUGH the jumper"),
    ("same", ("R3", "2"), ("U2", "6"),  "bias leg (DNP) lands on A"),
    ("on",   ("R3", "1"), "V3V3",       "bias top (DNP) to the rail"),
    ("same", ("R4", "1"), ("U2", "7"),  "bias leg (DNP) lands on B"),
    ("on",   ("R4", "2"), "GND",        "bias bottom (DNP) to GND"),
    ("on",   ("C7", "1"), "V3V3",       "U2 decoupling"),
    # -- e-paper J2 (canonical Waveshare 8-pin order, DR-7)
    ("on",   ("J2", "1"), "V3V3",       "EPD VCC"),
    ("on",   ("J2", "2"), "GND",        "EPD GND"),
    ("on",   ("J2", "3"), "SPI_MOSI",   "DIN"),
    ("on",   ("J2", "4"), "SPI_SCK",    "CLK"),
    ("on",   ("J2", "5"), "EPD_CS",     "CS"),
    ("on",   ("J2", "6"), "EPD_DC",     "DC"),
    ("on",   ("J2", "7"), "EPD_RST",    "RST"),
    ("on",   ("J2", "8"), "EPD_BUSY",   "BUSY"),
    ("same", ("MOD1", "18"), ("J2", "3"), "MOSI = IO10"),
    ("same", ("MOD1", "17"), ("J2", "4"), "SCK = IO9"),
    ("same", ("MOD1", "5"), ("J2", "5"),  "CS = IO5"),
    ("same", ("MOD1", "6"), ("J2", "6"),  "DC = IO6"),
    ("same", ("MOD1", "7"), ("J2", "7"),  "RST = IO7"),
    ("same", ("MOD1", "12"), ("J2", "8"), "BUSY = IO8"),
    ("on",   ("C6", "1"), "V3V3",       "panel bulk"),
    # -- buttons (D7; RTC-capable IO12/13/14 for the ext1 wake mask)
    ("on",   ("BTN1", "2"), "GND",      "switch to ground when pressed"),
    ("on",   ("BTN2", "2"), "GND",      "switch to ground when pressed"),
    ("on",   ("BTN3", "2"), "GND",      "switch to ground when pressed"),
    ("on",   ("BTN1", "1"), "BTN1_IN",  "button node"),
    ("on",   ("BTN2", "1"), "BTN2_IN",  "button node"),
    ("on",   ("BTN3", "1"), "BTN3_IN",  "button node"),
    ("on",   ("R5", "1"), "V3V3",       "1M pull-up (power-first)"),
    ("on",   ("R5", "2"), "BTN1_IN",    "pull-up bottom"),
    ("on",   ("R6", "2"), "BTN2_IN",    "pull-up bottom"),
    ("on",   ("R7", "2"), "BTN3_IN",    "pull-up bottom"),
    ("on",   ("C8", "1"), "BTN1_IN",    "debounce"),
    ("on",   ("C9", "1"), "BTN2_IN",    "debounce"),
    ("on",   ("C10", "1"), "BTN3_IN",   "debounce"),
    ("on",   ("MOD1", "20"), "BTN1_IN", "IO12 (RTC)"),
    ("on",   ("MOD1", "21"), "BTN2_IN", "IO13 (RTC)"),
    ("on",   ("MOD1", "22"), "BTN3_IN", "IO14 (RTC)"),
    # -- debug header J3 (ESP-Prog Program pinout, DR-32; target-perspective)
    ("on",   ("J3", "1"), "MCU_EN",     "ESP-Prog 1 = ESP_EN"),
    ("on",   ("J3", "2"), "V3V3",       "ESP-Prog 2 = VDD"),
    ("on",   ("J3", "3"), "DBG_TXD",    "ESP-Prog 3 = ESP_TXD (target TX out)"),
    ("on",   ("J3", "4"), "GND",        "ESP-Prog 4 = GND"),
    ("on",   ("J3", "5"), "DBG_RXD",    "ESP-Prog 5 = ESP_RXD (target RX in)"),
    ("on",   ("J3", "6"), "BOOT",       "ESP-Prog 6 = ESP_IO0 force-download"),
    ("on",   ("MOD1", "27"), "BOOT",    "IO0 strap reaches the header"),
    ("on",   ("MOD1", "37"), "DBG_TXD", "UART0 TXD0"),
    ("on",   ("MOD1", "36"), "DBG_RXD", "UART0 RXD0"),
    # -- EN network
    ("on",   ("MOD1", "3"), "MCU_EN",   "EN"),
    ("on",   ("R1", "1"), "V3V3",       "EN pull-up top"),
    ("on",   ("R1", "2"), "MCU_EN",     "EN pull-up bottom"),
    ("on",   ("C5", "1"), "MCU_EN",     "EN soft-start"),
    ("on",   ("C5", "2"), "GND",        "EN soft-start return"),
    ("on",   ("MOD1", "2"), "V3V3",     "module 3V3"),
    # decoupling caps hang ABOVE the 3V3 rail (battery blk_mcu convention):
    # bottom pin (2) on the rail, top pin (1) to the GND label
    ("on",   ("C3", "2"), "V3V3",       "ESP bulk on the rail"),
    ("on",   ("C3", "1"), "GND",        "ESP bulk return"),
    ("on",   ("C4", "2"), "V3V3",       "ESP HF decoupling on the rail"),
    ("on",   ("C4", "1"), "GND",        "ESP HF decoupling return"),
]


# ---- exact-variant contracts (footprint existence can't certify the variant)
EXACT_PARTS = {
    "J1":    ("Wurth_615008145521", "volthium:J_Wurth_WR-MJ_615008145521"),
    # D39 (CP4): side-entry — top-entry's 8.0 mm mated height consumes the
    # whole PCB->module gap; see the placement note in _sheet_epaper().
    "J2":    ("JST_S8B-PH-K-S", "Connector_JST:JST_PH_S8B-PH-K_1x08_P2.00mm_Horizontal"),
    "J3":    ("ESP-Prog", "Connector_IDC:IDC-Header_2x03_P2.54mm_Vertical"),
    "J-USB": ("USB4085-GF-A", "Connector_USB:USB_C_Receptacle_GCT_USB4085"),
    "U1":    ("R-78E3.3-0.5", "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT"),
    "F1":    ("MF-R025", "volthium:Fuse_Bourns_MF-R025_THT_P5.08mm"),
}


# ---- strict-ERC accounted exclusions (append-only; rationale required) ------
ERC_ACCEPTED = {
}


def main():
    core.configure("volthium_display", "build_display",
                   "Volthium reader — display-side (root)")
    # CP4/D26: the display board uses the no-antenna-keepout courtyard variant
    # (radio unused; see footprints/README.md). Battery board keeps the parent.
    core.SYMBOL_FP_OVERRIDES["ESP32-S3-WROOM-1"] = \
        "volthium:ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout"  # libpart field == comp records
    return core.run(SHEETS, GOLDEN, EXACT_PARTS, ERC_ACCEPTED)

if __name__ == "__main__":
    sys.exit(main())
