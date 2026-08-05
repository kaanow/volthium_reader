"""Display-side placement (CP4) — volthium_display.

Board 85 x 65 mm in a US double-gang old-work box (D8). Origin top-left,
+y down. The mechanical story dominates this board far more than the
battery side did, so the floorplan is derived from the enclosure, not
from signal convenience:

  FRONT (F.Cu) faces the pop-off faceplate, which carries the e-paper
  MODULE (D27 — the 103 x 78.5 mm module does not fit inside the ~95 mm
  box, so it mounts to the faceplate and the PCB sits behind it). Only
  the ~8 mm standoff gap is available on this side, so F holds the MCU
  module, the small passives, and the three tactile switches whose
  plungers must reach through the faceplate.

  BACK (B.Cu) faces the box floor, where the depth budget is generous
  (~13.6 mm used of ~45 mm total stack). It holds the two tall parts —
  J1 right-angle RJ45 (13.6 mm) and U1 R-78E3.3 SIP (~11 mm) — per
  cp1_display_side §10.2 rule 4, "keep tall parts off the module-facing
  side".

  N edge:  J2 e-paper header (side-entry, D39) — shortest cable run to
           the module directly in front of it
  W edge:  J1 RJ45 (right-angle, tab-down) — in-wall Cat5e enters from
           the side so the cable does not push the box forward (§10.2#5)
  E edge:  J-USB USB-C bench/recovery port (D27), mating face PROUD of
           the edge — the CP3 F-USB lesson, enforced by gate_edge_markers
  S edge:  BTN1/2/3 at x = 24 / 42 / 60 mm (18 mm centres, §10.2#2 —
           the §4.6 table's 22/42/62 was 20 mm centres and was corrected
           at CP4)
  centre:  MOD1 with the D26/D39 no-keepout courtyard; power chain and
           RS-485 transceiver around it

No antenna keepout (D26): the display radio is unused, so MOD1 carries
the body-hugging courtyard variant and nothing is sterilised for RF.

Every connector orientation is PROBED via core.placed_pads — never
hand-derived (the CP2 source/drain-swap lesson).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core

W, H = 85.0, 65.0

NETLIST = HERE.parents[0] / "schematic/build_display/volthium_display.net"
PROJECT = "display_pcb"
OUT = HERE / "build_display"

# M3 mounting holes (cp1_display_side §2)
MOUNT = [(4.0, 4.0), (81.0, 4.0), (4.0, 61.0), (81.0, 61.0)]

# connectors allowed to overhang the edge they mate through
OVERHANG_OK = {
    "J1": "W",       # RJ45 right-angle mating face, in-wall Cat5e (§10.2#5)
    "J-USB": "E",    # USB-C shell must sit PROUD of the edge (CP3 lesson)
}

NETCLASSES = {
    "Power-12V": (0.5, 0.25, ["V12_CAT5E", "V12_PROT"]),
    "Power-3V3": (0.4, 0.20, ["V3V3"]),
    "RS485-diff": (0.25, 0.20, ["RS485_A", "RS485_B"]),
}

# J-USB's own pad field is finer than the routing netclass clearance
CUSTOM_RULES = """(version 1)
(rule "usbc_own_pad_field"
  (constraint clearance (min 0.127mm))
  (condition "A.memberOfFootprint('J-USB') && B.memberOfFootprint('J-USB')"))
"""

DRC_ACCEPTED = {
    "unconnected_items": "placement-only board; routing is CP5",
    "silk_edge_clearance": "designed mating-face overhangs (J1 W, J-USB E)",
}

NETS, COMPS = core.parse_netlist(NETLIST)
P = {}


def cc(fpid, cx, cy, rot, side="F"):
    d = core.fplib.FpDims(fpid)
    x0, y0, x1, y1 = d.courtyard
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    if side == "B":
        mx = -mx
    rx, ry = core._rot(mx, my, rot)
    return (cx - rx, cy - ry, rot, side)


def pl(ref, cx, cy, rot=0, side="F"):
    """Place by courtyard centre. Footprint comes from the netlist only."""
    P[ref] = cc(COMPS[ref]["footprint"], cx, cy, rot, side)
