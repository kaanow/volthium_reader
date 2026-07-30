#!/usr/bin/env python3
"""Requirements compliance check — hardware/layout/requirements.md [M] rows.

Re-derives every mechanically-verifiable requirement from the BUILD ARTIFACTS
(the exported netlist = KiCad ground truth, component values from the comps
section, and the BOM), NOT from the generator's intent. Run after any
schematic change. Exit 0 = all PASS.

Usage: python3 hardware/tools/check_requirements.py
"""
import re, sys, pathlib

# F07: Windows redirected output defaults to cp1252, which cannot encode the
# Ω/↔/— glyphs this tool prints. Pin stdout/stderr to UTF-8 where supported.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


ROOT = pathlib.Path(__file__).resolve().parents[2]
NET = ROOT / "hardware/kicad/schematic/build/volthium_reader.net"
DNET = ROOT / "hardware/kicad/schematic/build_display/volthium_display.net"
BOM = ROOT / "hardware/layout/cp1_bom.md"


def parse_netlist(path):
    txt = path.read_text(encoding="utf-8")
    nets, i = {}, 0
    while True:
        i = txt.find("(net", i)
        if i < 0:
            break
        if txt[i + 4] not in " \n\t":
            i += 4
            continue
        d, j = 0, i
        while j < len(txt):
            if txt[j] == "(":
                d += 1
            elif txt[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        blk = txt[i:j + 1]
        i = j + 1
        nm = re.search(r'\(name "([^"]*)"\)', blk).group(1)
        nodes = frozenset(re.findall(r'\(ref "([^"]+)"\)[\s\S]*?\(pin "([^"]+)"\)', blk))
        nets[nm] = nodes
    values = dict(re.findall(r'\(comp\s*\n\s*\(ref "([^"]+)"\)\s*\n\s*\(value "([^"]*)"\)', txt))
    # DNP refs: comp blocks carrying a (property (name "dnp")) marker
    dnp = set()
    for m in re.finditer(r'\(comp\s*\n\s*\(ref "([^"]+)"\)([\s\S]*?)\n\t\t\)', txt):
        if '(name "dnp")' in m.group(2):
            dnp.add(m.group(1))
    return nets, values, dnp


def _lookup(nets):
    net_of = {}
    for nm, nodes in nets.items():
        for rp in nodes:
            net_of[rp] = nm
    return net_of


def main():
    nets, values, _ = parse_netlist(NET)
    net_of = _lookup(nets)
    dnets, dvalues, ddnp = parse_netlist(DNET)
    dnet_of = _lookup(dnets)
    bom = BOM.read_text(encoding="utf-8")
    results = []

    def check(req, desc, ok):
        results.append((req, desc, bool(ok)))

    def on(ref, pin, net):
        return net_of.get((ref, pin)) == net

    def same(a, b):
        na = net_of.get(a)
        return na is not None and na == net_of.get(b)

    def diff(a, b):
        na, nb = net_of.get(a), net_of.get(b)
        return na is not None and nb is not None and na != nb

    # display-board variants of the same helpers (volthium_display netlist)
    def don(ref, pin, net):
        return dnet_of.get((ref, pin)) == net

    def dsame(a, b):
        na = dnet_of.get(a)
        return na is not None and na == dnet_of.get(b)

    def ddiff(a, b):
        na, nb = dnet_of.get(a), dnet_of.get(b)
        return na is not None and nb is not None and na != nb

    # R1 barrier integrity (both channels)
    check("R1", "GND1 never meets either iso ground (ch1)",
          diff(("U10", "1"), ("U10", "11")) and diff(("U10", "1"), ("U10", "16")))
    check("R1", "GND1 never meets either iso ground (ch2)",
          diff(("U11", "1"), ("U11", "11")) and diff(("U11", "1"), ("U11", "16")))
    check("R1", "per-channel iso grounds are distinct nets",
          diff(("U10", "16"), ("U11", "16")) and diff(("U10", "11"), ("U11", "11")))
    check("R1", "L2 ties the two islands (each channel)",
          on("L11", "1", "GND2_DCDC1") and on("L11", "2", "ISO_BUS_GND1")
          and on("L13", "1", "GND2_DCDC2") and on("L13", "2", "ISO_BUS_GND2"))
    check("R1", "C_stitch bridges GND1<->GND2_DCDC only",
          on("C28", "1", "GND") and on("C28", "2", "GND2_DCDC1")
          and on("C38", "1", "GND") and on("C38", "2", "GND2_DCDC2"))
    # R2 vendor battery pinout
    check("R2", "battery RJ45: A=7 B=8 (both channels)",
          on("J10", "7", "BUS_A1") and on("J10", "8", "BUS_B1")
          and on("J11", "7", "BUS_A2") and on("J11", "8", "BUS_B2"))
    # R3 display link
    check("R3", "Cat5e: A=4 B=5 12V=1 GND=8",
          on("J2", "4", "RS485_A") and on("J2", "5", "RS485_B")
          and on("J2", "1", "V12_CAT5E") and on("J2", "8", "GND"))
    check("R3", "display termination goes THROUGH J4",
          same(("R10", "2"), ("J4", "1")) and same(("J4", "2"), ("U3", "7"))
          and diff(("R10", "2"), ("U3", "7")))
    # R4 power gates: source on rail, drain isolated from rail, 100k pull-ups
    for q, load in (("Q10", ("U10", "2")), ("Q11", ("U11", "2")),
                    ("Q5", ("U7", "3")), ("Q_exp", ("J_EXP", "2"))):
        check("R4", f"{q}: source on V3V3, load NOT on V3V3",
              on(q, "2", "V3V3") and same((q, "3"), load) and diff((q, "3"), (q, "2")))
    check("R4", "gate pull-ups are 100k",
          all(values.get(r) == "100k" for r in ("R20", "R30", "R14", "R_exp_pu", "R_byp1")))
    # R5 UVLO values
    check("R5", "UVLO divider 5.16M/100k + R_hys 11.5M",
          values.get("R_uv1") == "5.16M" and values.get("R_uv2") == "100k"
          and values.get("R_hys") == "11.5M")
    # R6 USB maintenance + ESD
    check("R6", "USB power chain U5->U6, VIN2 from buck, OUT=V3V3",
          on("U5", "1", "VBUS") and same(("U5", "5"), ("U6", "3"))
          and on("U6", "6", "V3V3_BUCK") and on("U6", "2", "V3V3"))
    check("R6", "fail-safe bypass Q3/Q4 chain",
          on("Q3", "3", "MCU_EN") and on("Q3", "2", "UVLO_RESET")
          and same(("Q3", "1"), ("Q4", "3")) and on("R_byp2", "1", "VBUS"))
    check("R6", "ESD array on DP/DM/VBUS",
          on("U-ESD", "1", "USB_DP") and on("U-ESD", "3", "USB_DM")
          and on("U-ESD", "5", "VBUS"))
    # R7 native USB to the module
    check("R7", "USB D+/D- reach MOD1 pins 14/13",
          on("MOD1", "14", "USB_DP") and on("MOD1", "13", "USB_DM"))
    # R8 ESP-Prog Program pinout (keyed 2x3; target-perspective TXD/RXD —
    # ESP-Prog SCH V2.1: FT_TXD->ESP_RXD0, FT_RXD->ESP_TXD0)
    check("R8", "J5 = ESP-Prog Program: EN/VDD/TXD/GND/RXD/IO0, IO0 strap wired",
          on("J5", "1", "MCU_EN") and on("J5", "2", "V3V3") and on("J5", "3", "DBG_TXD")
          and on("J5", "4", "GND") and on("J5", "5", "DBG_RXD") and on("J5", "6", "BOOT")
          and on("MOD1", "27", "BOOT"))
    # R9 console — prove the HEADER connection end-to-end, not just the module
    # pins (F06: a MOD1-only check passes even if the console never reaches J5)
    check("R9", "UART0 console reaches J5: J5.3<->MOD1.37, J5.5<->MOD1.36",
          same(("J5", "3"), ("MOD1", "37")) and same(("J5", "5"), ("MOD1", "36"))
          and on("MOD1", "37", "DBG_TXD") and on("MOD1", "36", "DBG_RXD"))
    # R10 Xanbus
    check("R10", "Xanbus polarity CAN_L=4 CAN_H=5",
          same(("U7", "6"), ("J6", "4")) and same(("U7", "7"), ("J6", "5"))
          and diff(("U7", "7"), ("J6", "4")))
    check("R10", "CAN termination through J7; 120R; NET pins NC",
          same(("R15", "2"), ("J7", "1")) and same(("J7", "2"), ("U7", "6"))
          and diff(("R15", "2"), ("U7", "6")) and values.get("R15") == "120"
          and all(net_of.get(("J6", p), "unconnected-").startswith("unconnected-")
                  or ("J6", p) not in net_of for p in ("1", "2", "3", "6")))
    check("R10", "CAN gated: TWAI pins + CAN_PWR",
          on("U7", "1", "CAN_TXD") and on("U7", "4", "CAN_RXD")
          and on("Q5", "1", "CAN_PWR") and on("MOD1", "35", "CAN_PWR"))
    # R11 RTC
    check("R11", "RTC always-on + backup cap",
          on("RTC1", "7", "V3V3") and same(("RTC1", "6"), ("C-bk", "1")))
    # R12 expansion contract
    check("R12", "EXP switched rail + bleed + header power",
          on("Q_exp", "3", "EXP_3V3") and on("R_exp_bleed", "1", "EXP_3V3")
          and on("J_EXP", "2", "EXP_3V3") and values.get("R_exp_bleed") == "10k")
    # R13 button
    check("R13", "BTN1 override wiring + pull-up",
          on("BTN1", "2", "BTN_OVERRIDE") and on("BTN1", "1", "GND")
          and on("R13", "1", "V3V3") and values.get("R13") == "1M")
    # R14 input protection
    check("R14", "fuse->diode->clamp chain, T-rated",
          on("F1", "1", "V24_RAW") and same(("F1", "2"), ("D1", "2"))
          and on("D1", "1", "V24_FUSED") and on("TVS1", "2", "V24_FUSED")
          and values.get("F1") == "1A T")
    # R15 solderability waiver documented
    check("R15", "SOT-583 waiver documented in BOM",
          "SOT-583" in bom and ("DR-24" in bom or "D33" in bom))
    # R16 GPIO budget note recorded
    check("R16", "GPIO-exhausted note recorded in BOM",
          "GPIO budget now exhausted" in bom)

    # ---- display-side board (volthium_display netlist) ----
    # R17 Cat5e link pinout mirrors the battery J2; shield NC at this end
    check("R17", "display J1: 12V=1-3, A=4, B=5, GND=6-8",
          all(don("J1", p, "V12_CAT5E") for p in ("1", "2", "3"))
          and don("J1", "4", "RS485_A") and don("J1", "5", "RS485_B")
          and all(don("J1", p, "GND") for p in ("6", "7", "8")))
    check("R17", "display J1 shield drain NC (bond lives at battery end)",
          ("J1", "SH") not in dnet_of
          or dnet_of[("J1", "SH")].startswith("unconnected-"))
    # R18 bus terminus: 120R through the lift jumper; idle bias DNP (F12)
    check("R18", "display termination goes THROUGH J5, 120R",
          dsame(("R2", "1"), ("U2", "6")) and dsame(("R2", "2"), ("J5", "1"))
          and dsame(("J5", "2"), ("U2", "7")) and ddiff(("R2", "2"), ("U2", "7"))
          and dvalues.get("R2") == "120")
    check("R18", "idle-bias R3/R4 present at 330 but DNP by default",
          dvalues.get("R3") == "330" and dvalues.get("R4") == "330"
          and {"R3", "R4"} <= ddnp)
    # R19 Deep-sleep wake architecture (F09/F15): /RE + RO + all 3 buttons on
    # RTC-capable GPIOs (IO15=pin8, IO18=pin11, IO12/13/14=pins 20/21/22)
    check("R19", "wake inputs on RTC GPIOs: nRE=IO15, RO=IO18, BTNs=IO12-14",
          dsame(("MOD1", "8"), ("U2", "2")) and dsame(("MOD1", "11"), ("U2", "1"))
          and don("MOD1", "20", "BTN1_IN") and don("MOD1", "21", "BTN2_IN")
          and don("MOD1", "22", "BTN3_IN"))
    check("R19", "button pull-ups 1M (power-first) + 100nF debounce",
          all(dvalues.get(r) == "1M" for r in ("R5", "R6", "R7"))
          and all(dvalues.get(c) == "100nF" for c in ("C8", "C9", "C10")))
    # R20 USB maintenance power (D29) + ESD + CC advertisement
    check("R20", "display USB chain U3-LDO -> U4-MUX, VIN2=V3V3_REG, OUT=V3V3",
          don("U3-LDO", "1", "VBUS") and dsame(("U3-LDO", "5"), ("U4-MUX", "3"))
          and don("U4-MUX", "6", "V3V3_REG") and don("U4-MUX", "2", "V3V3")
          and ddiff(("U4-MUX", "2"), ("U4-MUX", "6")))
    check("R20", "display ESD array on DP/DM/VBUS + 5.1k CC pull-downs",
          don("U-ESD", "1", "USB_DP") and don("U-ESD", "3", "USB_DM")
          and don("U-ESD", "5", "VBUS")
          and dsame(("J-USB", "A5"), ("R_cc1", "1")) and don("R_cc1", "2", "GND")
          and dsame(("J-USB", "B5"), ("R_cc2", "1")) and don("R_cc2", "2", "GND")
          and dvalues.get("R_cc1") == "5.1k" and dvalues.get("R_cc2") == "5.1k")
    check("R20", "display native USB D+/D- reach MOD1 pins 14/13",
          don("MOD1", "14", "USB_DP") and don("MOD1", "13", "USB_DM"))
    # R21 forced-download recovery parity with battery R8 (DR-32)
    check("R21", "display J3 = ESP-Prog Program pinout, IO0 strap wired",
          don("J3", "1", "MCU_EN") and don("J3", "2", "V3V3")
          and don("J3", "3", "DBG_TXD") and don("J3", "4", "GND")
          and don("J3", "5", "DBG_RXD") and don("J3", "6", "BOOT")
          and don("MOD1", "27", "BOOT"))
    check("R21", "display console reaches J3 end-to-end (TXD0/RXD0)",
          dsame(("J3", "3"), ("MOD1", "37")) and dsame(("J3", "5"), ("MOD1", "36")))
    # R22 e-paper interface: canonical Waveshare 8-pin order on the PH2.0 header
    check("R22", "J2 pin order VCC/GND/DIN/CLK/CS/DC/RST/BUSY -> right GPIOs",
          don("J2", "1", "V3V3") and don("J2", "2", "GND")
          and dsame(("MOD1", "18"), ("J2", "3")) and dsame(("MOD1", "17"), ("J2", "4"))
          and dsame(("MOD1", "5"), ("J2", "5")) and dsame(("MOD1", "6"), ("J2", "6"))
          and dsame(("MOD1", "7"), ("J2", "7")) and dsame(("MOD1", "12"), ("J2", "8")))
    # R23 input protection: PTC -> protected rail; clamp + bulk; reg chain
    check("R23", "display input chain PTC->V12_PROT->R-78E->V3V3_REG",
          don("F1", "1", "V12_CAT5E") and don("F1", "2", "V12_PROT")
          and don("TVS1", "2", "V12_PROT") and don("TVS1", "1", "GND")
          and don("U1", "1", "V12_PROT") and don("U1", "3", "V3V3_REG")
          and ddiff(("U1", "3"), ("U4-MUX", "2")))

    width = max(len(d) for _, d, _ in results) + 2
    fails = 0
    cur = None
    for req, desc, ok in results:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        prefix = req if req != cur else " " * len(req)
        cur = req
        print(f"{prefix:5s} {desc:<{width}s} {tag}")
    print(f"\n{len(results)} checks, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
