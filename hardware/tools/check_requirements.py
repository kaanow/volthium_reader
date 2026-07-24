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
    return nets, values


def main():
    nets, values = parse_netlist(NET)
    net_of = {}
    for nm, nodes in nets.items():
        for rp in nodes:
            net_of[rp] = nm
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
