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
  SE front: J-USB vertical USB-C bench/recovery port (D27/D40), opening
           +Z, reachable once the faceplate and module come away
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
    # J-USB is VERTICAL since D40 — it opens +Z off the front face, so
    # it overhangs nothing and has no "PCB Edge" marker to satisfy.
}

NETCLASSES = [
    # (name, track_width, clearance, patterns) — cp1_display_side §10.3
    ("Default", 0.2, 0.2, []),
    ("Power-12V", 0.5, 0.25, ["V12_CAT5E", "V12_PROT"]),
    ("Power-3V3", 0.4, 0.2, ["V3V3", "V3V3_REG"]),
    ("RS485-diff", 0.25, 0.2, ["RS485_A", "RS485_B"]),
]

# J-USB's own pad field is finer than the routing netclass clearance
CUSTOM_RULES = """(version 1)
(rule "usbc_own_pad_field"
  (constraint clearance (min 0.127mm))
  (condition "A.memberOfFootprint('J-USB') && B.memberOfFootprint('J-USB')"))
"""

DRC_ACCEPTED = {
    "unconnected_items": "placement-only board; routing is CP5",
    "silk_edge_clearance": "J1 RJ45 designed W-edge mating overhang",
    # Instance-scoped: the two vendored variants and the flipped SIP. Each
    # needs the CP3-style pad-diff evidence in the packet before hand-off.
    ("lib_footprint_mismatch", "ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout"): 0,
    ("lib_footprint_mismatch", "J_Wurth_WR-MJ_615008145521"): 0,
    ("lib_footprint_mismatch", "USB_C_Receptacle_GCT_USB4115-03-C"): 0,
    ("lib_footprint_mismatch", "Converter_DCDC_RECOM_R-78E-0.5_THT"): 0,
}

NETS, COMPS = core.parse_netlist(NETLIST)
P = {}


def cc(fpid, cx, cy, rot, side="F"):
    """Anchor placement so the footprint's courtyard CENTRE lands at (cx, cy).

    Delegates the mirror to core._xf so there is exactly ONE back-side
    transform in the project. This helper previously carried its own copy
    that negated X while the writer and gates negate Y (CP4 F01) — the
    fourth site of the same convention, and the one nobody swept. A
    duplicated transform is the bug; sharing it is the fix.
    """
    d = core.fplib.FpDims(fpid)
    x0, y0, x1, y1 = d.courtyard
    mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    rx, ry = core._xf(mid, 0.0, 0.0, rot, side == "B")
    return (cx - rx, cy - ry, rot, side)


def pl(ref, cx, cy, rot=0, side="F"):
    """Place by courtyard centre. Footprint comes from the netlist only."""
    P[ref] = cc(COMPS[ref]["footprint"], cx, cy, rot, side)


# ---------------------------------------------------------------------------
# BACK side (B) — faces the box floor, generous depth. Only the two parts
# that would blow the front standoff gap live here (§10.2 #4).
# ---------------------------------------------------------------------------
# J1 RJ45 right-angle, mating face W: in-wall Cat5e enters from the side so
# the cable does not push the box forward (§10.2 #5). 13.6 mm tall.
pl("J1", 11.0, 30.0, 90, "B")
# U1 R-78E3.3 SIP (~11 mm) on the back, pointing into the box (§10.2 #4)
pl("U1", 12.0, 48.0, 0, "B")

# ---------------------------------------------------------------------------
# FRONT side (F) — faces the faceplate/module across the standoff gap
# ---------------------------------------------------------------------------
# N edge: J2 e-paper header, side-entry (D39). rot 0 puts the pin row NORTH
# of the body, so the opening (and cable) faces SOUTH over the board rather
# than into the ~5 mm gap between board edge and box wall. PROBED, not assumed.
pl("J2", 42.0, 6.0, 0)

# MOD1 centre, no antenna keepout (D26/D39): courtyard x 32.25..51.75,
# y 14.00..40.50 — the placement exclusion every other front part respects.
pl("MOD1", 42.0, 27.0, 0)

# --- W column: 12 V entry chain J1 -> F1 -> TVS1/C1 -> U1 (on the back) ---
pl("F1", 13.0, 8.0, 0)
pl("C1", 12.5, 13.5, 0)
pl("TVS1", 23.5, 8.0, 0)

# --- RS-485 front end, left of the module ---
pl("TVS2", 23.5, 13.5, 0)
pl("U2", 25.5, 33.5, 0)          # THVD1400
pl("R3", 21.5, 18.0, 0)          # 330R idle bias (D19/DR-4)
pl("R4", 27.0, 24.5, 0)
pl("R2", 27.0, 29.0, 0)          # 120R termination, gated by J5
pl("J5", 28.0, 20.0, 0)          # TERM jumper

# --- E column: USB-C chain, running N from the SE connector ---
# SE on the FRONT face: vertical USB-C (D40) opening +Z. Sited by the
# buttons so the service points cluster where a hand goes once the
# faceplate and module come away; nothing overhangs a board edge.
pl("J-USB", 72.0, 57.0, 0)
pl("U-ESD", 70.0, 27.0, 0)       # ESD array inboard of the connector
pl("R_cc1", 77.0, 25.5, 0)       # CC pulldowns
pl("R_cc2", 77.0, 29.0, 0)
pl("C_usb1", 62.0, 27.0, 0)      # VBUS bulk
pl("U3-LDO", 70.0, 33.0, 0)      # USB 5 V -> 3V3
pl("C_usb2", 62.0, 33.0, 0)
pl("U4-MUX", 70.0, 38.5, 0)      # priority mux: USB (VIN1) vs R-78E (VIN2)
pl("C_mux", 62.0, 38.5, 0)       # 47 uF on the muxed V3V3 rail
pl("C2", 77.0, 33.0, 0)          # regulator-output bulk (V3V3_REG)

# --- 3V3 decoupling south of the module, clear of its y=40.50 courtyard ---
pl("C3", 34.0, 44.0, 0)
pl("C4", 38.0, 44.0, 0)
pl("C6", 42.0, 44.0, 0)
pl("C7", 46.0, 44.0, 0)

# --- EN / boot support ---
pl("R1", 52.0, 44.0, 0)
pl("C5", 56.0, 44.0, 0)

# --- J3 ESP-Prog: front side, serviceable once faceplate + module come away
pl("J3", 78.0, 44.0, 0)

# --- S edge: buttons at the doc x centres (18 mm pitch, §10.2 #2), each with
# its 1M pullup and 100 nF debounce immediately north ---
for _ref, _bx in (("BTN1", 24.0), ("BTN2", 42.0), ("BTN3", 60.0)):
    pl(_ref, _bx, 57.5, 0)
pl("R5", 16.0, 49.5, 0)
pl("C8", 10.0, 49.5, 0)
pl("R6", 38.0, 49.5, 0)
pl("C9", 46.0, 49.5, 0)
pl("R7", 56.0, 49.5, 0)
pl("C10", 62.5, 49.5, 0)


def orientation_asserts(findings):
    """PROBE every mechanical invariant from the placed geometry — never
    hand-derive a rotation's effect (the CP2 source/drain-swap lesson)."""
    def pads(ref):
        x, y, rot, side = P[ref]
        return core.placed_pads(COMPS[ref]["footprint"], x, y, rot, side)

    def court_center(ref):
        x, y, rot, side = P[ref]
        segs = core.courtyard_segments(COMPS[ref]["footprint"], x, y, rot,
                                       back=(side == "B"))
        pts = [p for s in segs for p in s]
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    # J1: the RJ45 mating face must open WEST.
    #
    # The old form of this assert compared the signal-row X centroid with the
    # courtyard X centroid and was TAUTOLOGICAL — both are symmetric, so it
    # was equal by construction and encoded nothing about direction (CP4 F01).
    #
    # What actually encodes the opening: the signal pads sit at one end of the
    # footprint (local y 0..2.54) and the jack body extends away from them to
    # local y ~20. So the vector from the signal-pad centroid toward the
    # courtyard centre IS the opening direction, and it must point WEST.
    sig = [p for n, p in pads("J1").items() if n.isdigit()]
    sx = sum(p[0] for p in sig) / len(sig)
    sy = sum(p[1] for p in sig) / len(sig)
    ccx, ccy = court_center("J1")
    dx, dy = ccx - sx, ccy - sy
    if not (dx < 0 and abs(dx) > abs(dy)):
        findings.append(
            f"[orient] J1: opening vector (pads -> body) is ({dx:+.1f},{dy:+.1f}) "
            "— the RJ45 must open WEST (predominantly -x) so the in-wall "
            "Cat5e enters from the side (§10.2 #5)")

    # J2: side-entry opening must face SOUTH (cable over the board, not into
    # the box wall) — pin 1 row sits north of the courtyard centre.
    if not pads("J2")["1"][1] < court_center("J2")[1]:
        findings.append("[orient] J2: pin row not north of body — side-entry "
                        "cable would exit over the N board edge")

    # Buttons must be on the FRONT (plungers reach the faceplate, D27)
    for b in ("BTN1", "BTN2", "BTN3"):
        if P[b][3] != "F":
            findings.append(f"[orient] {b} is on the back — plunger cannot "
                            "reach the faceplate")

    # The two tall parts must be on the BACK (depth stack, §10.2 #4)
    for tall in ("J1", "U1"):
        if P[tall][3] != "B":
            findings.append(f"[orient] {tall} is on the front — it exceeds "
                            "the PCB->module standoff gap")


# --- Mechanical envelope annotation (reviewer F03) -------------------------
# The load-bearing mechanical claims of this board — cable-entry direction,
# the 9.7 mm front standoff gap, the 13.6 mm back depth, faceplate reach —
# rest on parts whose 3D bodies do NOT render: J1 points at Wurth's own
# ${WE_3DMODEL_DIR}, which is not bound in this install, and the stock USB
# footprint names a STEP absent from KiCad 10. Rather than hand-author 3D
# solids, draw the committed, dimensioned envelope on Cmts.User so the
# geometry is text in the board file, deterministic, and visible in the
# exported documentation plot.
#
# heights: source of each number is named so none of this is recalled.
ENVELOPES = {
    "J1":    (13.6, "Wurth 615008145521 RJ45, right-angle; cp1_display_side "
                    "2.1 datasheet-confirmed. BACK side, opens WEST"),
    "U1":    (11.0, "R-78E3.3-0.5 SIP, cp1_display_side 2.1. BACK side"),
    "J-USB": (9.30, "GCT USB4115-03-C vertical, drawing p.1 H=9.30. FRONT, "
                    "opens +Z — sets the standoff gap"),
    "J3":    (9.10, "Wurth 61200621621 box header, drawing p.1. FRONT"),
    "J2":    (7.60, "JST S8B-PH-K-S side entry, ePH p.3. FRONT"),
    "BTN1":  (15.0, "TS02-66-150 actuator 15.0 mm above PCB. FRONT"),
    "BTN2":  (15.0, "TS02-66-150 actuator 15.0 mm above PCB. FRONT"),
    "BTN3":  (15.0, "TS02-66-150 actuator 15.0 mm above PCB. FRONT"),
}


def annotate_envelopes(bb):
    """Draw each tall part's body outline + height on Cmts.User."""
    from kiutils.items.gritems import GrRect, GrText
    from kiutils.items.common import Position, Effects, Font
    for ref, (h, src) in sorted(ENVELOPES.items()):
        x, y, rot, side = P[ref]
        d = core.fplib.FpDims(COMPS[ref]["footprint"])
        fx0, fy0, fx1, fy1 = d.fab_bbox or d.courtyard
        pts = [core._xf((px, py), x, y, rot, side == "B")
               for px, py in ((fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1))]
        x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
        y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
        bb.b.graphicItems.append(GrRect(
            start=Position(X=round(x0, 3), Y=round(y0, 3)),
            end=Position(X=round(x1, 3), Y=round(y1, 3)),
            layer="Cmts.User", width=0.05, fill="none"))
        bb.b.graphicItems.append(GrText(
            text=f"{ref} h={h:.1f}mm {'(B)' if side == 'B' else '(F)'}",
            position=Position(X=round((x0 + x1) / 2, 3),
                              Y=round(y0 - 0.9, 3), angle=0),
            layer="Cmts.User",
            effects=Effects(font=Font(width=0.7, height=0.7, thickness=0.12))))


def main():
    core.configure(PROJECT, "build_display", NETLIST)
    if not core.selftest_gates():
        print("[selftest] FAILED — refusing to build")
        return 2

    bb = core.BoardBuilder(W, H, NETS, COMPS, P, overhang_ok=OVERHANG_OK)
    bb.place_all()
    bb.add_mounting_holes(MOUNT)
    orientation_asserts(bb.findings)
    # courtyard / outline / edge-marker / fab / readback / label-adjacency
    # all run inside bb.write() — the chokepoint (CP3 F09)

    OUT.mkdir(exist_ok=True)
    pcb = OUT / f"{PROJECT}.kicad_pcb"
    bans_file = OUT / "refdes_bans.json"
    bans = {}
    if bans_file.exists():
        import json as _json
        bans = {k: [tuple(v) for v in vs]
                for k, vs in _json.loads(
                    bans_file.read_text(encoding="utf-8")).items()}
    refdes_ov, refdes_unplaced = core.auto_refdes(COMPS, P, W, H, banned=bans)
    if refdes_unplaced:
        print(f"[refdes] library-fallback: {refdes_unplaced}")
    annotate_envelopes(bb)
    bb.write(pcb, prop_overrides=refdes_ov)

    if bb.findings:
        print(f"== {len(bb.findings)} finding(s) ==")
        for f in bb.findings:
            print(" ", f)
        return 1

    core.write_project(OUT, PROJECT, NETCLASSES, CUSTOM_RULES)
    unaccounted, counts = core.run_drc(pcb, DRC_ACCEPTED, OUT / "drc.rpt")
    print("[drc] categories:", counts)
    if unaccounted:
        print(f"[drc] {len(unaccounted)} unaccounted:")
        for cat, msg in unaccounted[:40]:
            print(f"  [{cat}] {msg}")
        return 1

    import os as _os
    if not _os.environ.get("SKIP_RENDER"):
        core.render_board(pcb, OUT / "render_top.png", "top")
        core.render_board(pcb, OUT / "render_bottom.png", "bottom")
        core.export_svg(pcb, OUT / "doc_envelopes.svg",
                        "F.Cu,F.SilkS,Edge.Cuts,F.CrtYd,Cmts.User")
    print(f"[ok] {pcb.name}: {len(bb.b.footprints)} footprints, "
          f"{len(bb.b.nets)} nets, DRC clean (accepted: "
          f"{ {k: counts.get(k, 0) for k in DRC_ACCEPTED} })")
    return 0


if __name__ == "__main__":
    sys.exit(main())
