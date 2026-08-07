"""Battery-side placement (CP3) — volthium_reader.

Floorplan (origin top-left, +y down; SOUTH edge y=H = cable edge):

  N edge:  MOD1 ESP32, antenna overhangs N (D-CP3-1); RTC cluster and
           J_EXP expansion east of it
  NW:      quiet sense divider (far from L1), UVLO supervisor cluster
  W:       24 V entry, S->N: J1 Phoenix (west-facing) above the display
           jack; F1 fuse; D1/TVS1 row; V24 switched chain (F2->SSR1->
           R_inrush->U2 R-78HB12) center-west
  center:  U1 LM5166 buck triangle (U1/C1/L1/C2) below MOD1;
           EN/bypass band south of the module
  E:       J3 USB-C (east-facing) -> U-ESD/CC -> U5 LDO -> U6 mux
  S edge, W->E: J2 RJ45 (display link) + U3 THVD1400; J6 RJ45 (Xanbus)
           + U7 TCAN332 + Q5 gate; J10/J11 RJ45 pack reads, each an
           isolated column with ADM2587E spanning the barrier
  SE-mid:  BTN1/C11, J5 ESP-Prog (service access, mid-board)

Every connector orientation is PROBED via core.placed_pads (never
hand-derived); the module body rectangle (x 30..50, y 0..20.5) is a
placement exclusion zone enforced by the courtyard gate.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core

W, H = 100.0, 80.0

NETLIST = HERE.parents[0] / "schematic/build/volthium_reader.net"
PROJECT = "battery_pcb"
OUT = HERE / "build"

# connectors allowed to overhang their designed edge
OVERHANG_OK = {
    "MOD1": "N",     # antenna + Espressif clearance region off-board (D-CP3-1)
    "J1":   "W",     # Phoenix wire-entry face
    "J2":   "S", "J6": "S", "J10": "S", "J11": "S",   # RJ45 mating faces
    "J3":   "E",     # USB-C mating face
}

# Refs whose LIBRARY footprint is contracted to carry a "PCB Edge"
# mating-plane marker (CP4 F17). Deliberately NOT the same set as
# OVERHANG_OK: seven refs here may overhang the outline, but only J3 — the
# GCT USB-C receptacle — encodes a mating plane, so only J3's plane can be
# gated. If a library update drops or adds a marker, the gate now fails
# instead of quietly checking nothing.
EDGE_MARKER_REFS = {"J3"}


def _dims(fpid):
    return core.fplib.FpDims(fpid)


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


P = {}   # ref -> (x, y, rot, side)

# The netlist is the ONLY footprint source. An earlier draft passed a
# footprint id into the placement helper, and a wrong id silently centered
# the part with the wrong courtyard while the gate judged the real one —
# place by ref so that class of drift cannot exist.
NETS, COMPS = core.parse_netlist(NETLIST)


def pl(ref, cx, cy, rot=0, side="F"):
    P[ref] = cc(COMPS[ref]["footprint"], cx, cy, rot, side)

# ---------------------------------------------------------------------------
# NW: quiet sense divider (far from L1) + UVLO supervisor
# ---------------------------------------------------------------------------
pl("R5", 5.0, 9.0, 0)
pl("R6", 9.5, 9.0, 0)
pl("C5", 13.5, 9.0, 0)

pl("C_ct", 4.5, 14.0, 0)
pl("C_sense", 8.0, 14.0, 0)
pl("C_uvdd", 11.5, 14.0, 0)
pl("U4", 9.0, 18.0, 0)
pl("R_uv1", 4.2, 22.5, 90)
pl("R_uv2", 8.0, 22.5, 90)
pl("R_hys", 11.8, 22.5, 90)

# ---------------------------------------------------------------------------
# W: 24 V entry + protection (J1 above J2; flow J1 -> F1 -> D1 row)
# ---------------------------------------------------------------------------
pl("D1", 26.0, 27.0, 0)   # at F1 output end -> V24_FUSED star (self-review)
pl("TVS1", 18.5, 27.0, 0)
pl("F1", 20.0, 34.0, 0)
pl("J1", 7.5, 45.0, 270)          # wire entry west; probed below

# V24 switched chain: F2 -> SSR1 -> R_inrush1/2 -> U2 -> V12_CAT5E
pl("F2", 18.0, 40.5, 0)
pl("SSR1", 28.0, 40.5, 0)
pl("R_opto", 36.5, 40.5, 90)
pl("R_inrush1", 18.0, 47.0, 0)
pl("R_inrush2", 24.0, 47.0, 0)
pl("U2", 33.0, 49.0, 0)
pl("C3", 24.0, 52.0, 0)      # U2 Vin bulk (V24_SW), adjacent pin 1 (affinity review)
pl("C4", 43.0, 50.0, 90)     # V12_CAT5E out bulk
pl("TVS3", 48.0, 46.0, 90)     # V12 clamp

# ---------------------------------------------------------------------------
# Center: U1 LM5166 buck triangle (§11.2 #2) south of the module
# ---------------------------------------------------------------------------
pl("C1", 44.0, 25.2, 90)     # buck INPUT bulk, adjacent U1
pl("U1", 46.0, 30.0, 0)
pl("L1", 51.0, 30.0, 90)
pl("C2", 55.0, 30.0, 90)     # V3V3_BUCK out bulk
pl("R_ILIM", 46.0, 35.5, 0)

# ---------------------------------------------------------------------------
# N: MCU module + decoupling + south control band
# ---------------------------------------------------------------------------
P["MOD1"] = (40.0, 6.75, 0, "F")           # antenna overhangs N (D-CP3-1)
pl("C7", 28.0, 4.5, 90)      # 100n HF decoupler CLOSEST to MOD1 pin 2 (probed at 31.25,2.76)
pl("C6", 28.0, 8.5, 90)      # 10u bulk behind it
# control band south of module body (y 22.3..25.7)
pl("R4", 32.2, 24.0, 90)     # PWR_EN pulldown
pl("R7", 35.4, 24.0, 90)     # EN pull-up
pl("C8", 38.4, 24.0, 90)     # EN cap
pl("R13", 41.2, 24.0, 90)    # BTN pull-up
pl("Q3", 48.5, 24.0, 0)      # UVLO->EN bypass logic
pl("Q4", 52.5, 24.0, 0)
pl("R_byp1", 56.2, 24.6, 90)
pl("R_byp2", 59.7, 24.6, 90)
pl("R_byp2b", 62.7, 24.6, 90)

# RTC cluster east of module
pl("C9", 53.0, 8.0, 90)      # RTC decoupling
pl("RTC1", 56.0, 8.0, 0)
pl("C-bk", 60.5, 8.0, 90)    # VBACKUP reservoir
pl("R8", 64.5, 8.0, 90)      # I2C pulls
pl("R9", 67.5, 8.0, 90)

# ---------------------------------------------------------------------------
# NE: expansion header + power gate
# ---------------------------------------------------------------------------
pl("J_EXP", 78.0, 6.0, 0)
# legend-style stack: 8-11 char refdes cannot live inline at 1.0 mm font
# (JLC floor) — parts in a column, refs manual to the west (self-review)
pl("Q_exp", 60.0, 20.6, 0)
pl("R_exp_pu", 72.0, 10.5, 0)
pl("R_exp_bleed", 72.0, 13.0, 0)
pl("R_exp_scl", 72.0, 15.5, 0)
pl("R_exp_sda", 72.0, 18.0, 0)

# ---------------------------------------------------------------------------
# E: USB-C maintenance power chain (west-flowing: J3 -> ESD -> LDO -> mux)
# ---------------------------------------------------------------------------
# J3 sits so its footprint's Dwgs.User "PCB Edge" line lands ON x=100
# (gate_edge_markers enforces this): shell protrudes 2.51 mm past the
# edge per the GCT USB4085 drawing — a recessed face blocks the plug
# overmold (2.10 mm mated clearance, drawing p.2) on the board edge.
pl("J3", 97.925, 25.0, 90)
pl("U-ESD", 83.0, 21.0, 0)
pl("R_cc1", 83.0, 25.0, 0)
pl("R_cc2", 83.0, 28.0, 0)
pl("C_usb1", 79.0, 21.0, 90)
pl("U5", 75.0, 21.0, 180)   # VIN pins face E toward VBUS (PR-8 review)
pl("C_usb2", 71.0, 21.0, 90)
pl("U6", 67.0, 21.0, 180)   # VIN1/PR1 face E toward U5
pl("C_mux", 64.5, 21.0, 90)

# ---------------------------------------------------------------------------
# S-W: display link (J2 + U3 THVD1400 within 15 mm, §11.2 #4)
# ---------------------------------------------------------------------------
pl("J2", 18.0, 73.0, 180)
pl("U3", 18.0, 58.5, 0)
pl("C10", 22.5, 58.5, 90)    # U3 decoupling
pl("R10", 13.0, 54.0, 90)    # 120R term
pl("J4", 19.5, 52.5, 0)       # term-lift jumper
pl("TVS2", 8.0, 58.0, 0)       # A-B differential clamp

# S-center: Xanbus CAN (J6 + U7 TCAN332 + Q5 power gate)
pl("J6", 39.0, 73.0, 180)
pl("U7", 39.0, 58.5, 0)
pl("C12", 33.0, 56.0, 90)    # U7 VCC (gated) decoupling, at the W (VCC-pin) column
pl("J7", 45.5, 58.5, 0)       # CAN term jumper
pl("R15", 45.9, 53.5, 90)    # 120R CAN term
pl("Q5", 29.0, 56.0, 0)      # CAN_PWR P-FET
pl("R14", 29.0, 60.0, 90)
pl("D2", 33.0, 60.0, 0)      # DNP bus clamp (F03)

# service: BTN1 harness header + debounce in the NE corner beside J_EXP
# (all internal harness connectors grouped top-right); J5 ESP-Prog rot 90
# lies flat between the USB row and the iso logic rows
pl("BTN1", 89.0, 13.0, 0)
pl("C11", 93.0, 13.0, 90)    # BTN debounce
pl("J5", 72.0, 28.5, 90)   # flat, in the band between USB row and iso logic rows

# ---------------------------------------------------------------------------
# S-E: two isolated pack-read channels (columns at x0 = 59, 82)
# ---------------------------------------------------------------------------
def iso_channel(jref, uref, qref, rpwr, rtx, beads, tvs, rs, cs, bridge, x0):
    """One isolated RS-485 read channel. N->S: logic row (gate, pulls,
    VCC bank) -> ADM2587E spanning the barrier -> iso island (supply
    beads + caps, protection, term/bias) -> RJ45 at the edge. C28/C38
    (1 kV bridge) sits beside the package across the barrier."""
    pl(jref, x0, 73.0, 180)
    pl(uref, x0, 47.0, 270)   # 270: logic pins 1-10 NORTH, iso 11-20 SOUTH (probed)
    # logic row (north of U)
    pl(qref, x0 - 6.6, 37.5, 0)
    pl(cs[2], x0 - 3.2, 39.3, 90)   # 0.1u at VCC1 pin 8 (probed x0-3.2)
    pl(rpwr, x0 - 0.8, 37.5, 90)
    pl(rtx, x0 + 1.6, 35.6, 90)   # series TX R above the bank, E of the gate (label pocket open N)
    pl(cs[0], x0 + 3.4, 39.3, 90)   # 0.1u at VCC1 pin 2 (probed x0+4.4)
    pl(cs[1], x0 + 5.8, 39.3, 90)   # 0.01u beside it
    pl(cs[3], x0 - 9.8, 39.3, 90)   # 10u bulk at the row W end (inter-channel gap)
    # bridge cap beside the package, spanning the barrier line
    pl(bridge, x0 + 8.5, 47.0, 90)
    # iso island v2 (self-review, silk-floor respacing): supply row under
    # the iso pins; beads as a W column pair; protection as column pairs
    # with a ref band between (y~60.15) and below (y~63.6, clear of the
    # jack silk at ~64.74)
    pl(cs[5], x0 - 4.6, 54.7, 90)   # 0.1u at V_ISOOUT pin 12 (probed x0-4.4)    # 0.1u V_ISOOUT (HF, at pin 12)
    pl(cs[4], x0 - 1.8, 54.7, 90)    # 10u V_ISOOUT bulk
    pl(cs[6], x0 + 4.2, 54.7, 90)   # 0.1u at V_ISOIN pin 19 (probed x0+4.4)    # 0.1u V_ISOIN (HF, at pin 19)
    pl(cs[7], x0 + 6.6, 54.7, 90)    # 0.01u V_ISOIN
    pl(beads[1], x0 + 9.6, 58.2, 90)  # GND2 bead (E col)
    pl(beads[0], x0 + 9.6, 62.0, 90)  # supply bead (E col)
    pl(rs[5], x0 + 8.5, 51.5, 90)    # 0R pack-ref provisioning (bridge zone)
    pl(rs[0], x0 - 8.4, 58.4, 0)     # 10R protect A
    pl(rs[1], x0 - 8.4, 61.9, 0)     # 10R protect B
    pl(tvs, x0 - 1.5, 58.4, 0)       # SM712
    pl(rs[2], x0 - 1.5, 62.0, 90)    # 120R term
    pl(rs[3], x0 + 6.5, 58.4, 0)     # 560R bias A
    pl(rs[4], x0 + 6.5, 61.9, 0)     # 560R bias B


iso_channel("J10", "U10", "Q10", "R20", "R21",
            ["L10", "L11"], "D10",
            ["R22", "R23", "R24", "R25", "R26", "R27"],
            ["C20", "C21", "C22", "C23", "C24", "C25", "C26", "C27"],
            "C28", 59.5)
iso_channel("J11", "U11", "Q11", "R30", "R31",
            ["L12", "L13"], "D11",
            ["R32", "R33", "R34", "R35", "R36", "R37"],
            ["C30", "C31", "C32", "C33", "C34", "C35", "C36", "C37"],
            "C38", 82.0)

MOUNT = [(4.0, 4.0), (W - 4.0, 4.0), (4.0, H - 4.0), (W - 4.0, H - 4.0)]

NETCLASSES = [
    # (name, track_width, clearance, patterns)  — cp1_battery_side §11.3
    ("Default", 0.2, 0.2, []),
    ("Power-24V", 1.0, 0.3, ["V24_RAW", "V24_FUSED", "V24_SW"]),
    ("Power-12V", 0.5, 0.25, ["V12_CAT5E"]),
    ("Power-3V3", 0.4, 0.2, ["V3V3", "V3V3_BUCK"]),
    ("RS485-diff", 0.25, 0.2, ["RS485_A", "RS485_B", "BUS_A*", "BUS_B*"]),
]

# Scoped DRC exceptions (.kicad_dru). The GCT USB4085 THT pin field has an
# inherent 0.85 mm pitch / 0.15 mm pad gap — legal at JLCPCB (0.127 mm
# copper-copper floor) but below our 0.2 mm ROUTING clearance. Scope the
# lower floor to J3's own pad field only; everything else keeps netclass.
CUSTOM_RULES = """(version 1)
(rule usbc_own_pinfield
  (condition "A.memberOfFootprint('J3') && B.memberOfFootprint('J3')")
  (constraint clearance (min 0.127mm)))
"""

# Hand-picked refdes spots where the greedy placer has no clear ring
# (board-frame position + text angle + compact font)
MANUAL_REFDES = {
    # expansion legend labels (west of the part column)
    "R_exp_pu": (76.8, 10.5, 0),
    "R_exp_bleed": (78.2, 12.7, 0),
    "R_exp_scl": (77.5, 14.6, 0),
    "R_exp_sda": (77.5, 16.5, 0),
    # stuck-set manual spots (DRC-oracle refuted every auto candidate)
    "R_inrush2": (21.5, 45.1, 0),
    "R_inrush1": (21.5, 48.9, 0),
    "SSR1": (33.7, 40.5, 90),
    "Q5": (25.9, 56.0, 90),
    "Q_exp": (56.4, 20.6, 90),
    "R_byp1": (54.7, 27.0, 0),
    "R_byp2": (59.2, 29.5, 90),
    "D10": (55.4, 58.4, 90),
    "C2": (55.0, 33.2, 0),
    "C24": (59.3, 54.7, 90),
    "C34": (81.8, 54.7, 90),
    "U5": (74.6, 18.6, 0),
    "R20": (58.5, 35.0, 0),
    "R30": (80.6, 35.0, 0),
    "C_usb1": (81.6, 17.9, 0),
    "C_mux": (64.5, 17.9, 0),
    "RTC1": (56.0, 4.9, 0),
    "C9": (51.6, 8.0, 90),
    "D11": (77.9, 58.4, 90),
    "R_byp2b": (62.7, 30.1, 90),
}

# DRC accepted classes at PLACEMENT stage (no routing yet)
DRC_ACCEPTED = {
    "unconnected_items": "CP3 is placement-only; routing lands at CP5",
    "silk_edge_clearance":
        "designed overhangs only: the 4 RJ45 mating faces + MOD1 antenna "
        "silk cross the edge by construction (per-instance list in the CP3 "
        "packet; anything else clipping silk at the edge is a defect)",
    ("lib_footprint_mismatch", "ESP32-S3-WROOM-1_HSvia0.3"):
        "board copy vs volthium lib: 62/62 pads coordinate-identical and "
        "all graphic counts equal (token diff on record, CP3 packet); the "
        "delta is kiutils serialization normalization only (dropped "
        "'(unlocked yes)' on fp_texts, stroke/fill order, embedded_fonts "
        "token) — non-geometric",
}


def orientation_asserts(findings):
    """Spec-level orientation invariants, probed from placed geometry."""
    def pads(ref):
        fpid = COMPS[ref]["footprint"]
        x, y, rot, side = P[ref]
        return core.placed_pads(fpid, x, y, rot, side)

    def court_center(ref):
        fpid = COMPS[ref]["footprint"]
        x, y, rot, side = P[ref]
        d = _dims(fpid)
        cx0, cy0, cx1, cy1 = d.courtyard
        return core._xf(((cx0 + cx1) / 2, (cy0 + cy1) / 2),
                        x, y, rot, side == "B")

    def mean_xy(vals):
        pts = []
        for v in vals:
            pts += v if isinstance(v, list) else [v]
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))

    # every RJ45 opening faces SOUTH: npth posts south of the signal rows
    for j in ("J2", "J6", "J10", "J11"):
        pp = pads(j)
        posty = mean_xy([pp[""]])[1]
        sigy = mean_xy([pp[str(n)] for n in range(1, 9)])[1]
        if not posty > sigy:
            findings.append(f"[orient] {j}: posts not south of pin field — "
                            "opening does not face the S edge")
    # Phoenix wire entry faces WEST: pads east of courtyard center
    pp = pads("J1")
    padx = mean_xy([pp["1"], pp["2"]])[0]
    if not padx > court_center("J1")[0]:
        findings.append("[orient] J1: pads not east of body — wire entry "
                        "does not face W edge")
    # USB-C mating face EAST: pads west of courtyard center
    pp = pads("J3")
    if not mean_xy(list(pp.values()))[0] < court_center("J3")[0]:
        findings.append("[orient] J3: pads not west of body — USB opening "
                        "does not face E edge")
    # ADM2587E barrier axis: logic pins (1-10) NORTH, iso pins (11-20)
    # SOUTH, so the CP5 pour split can follow the package barrier and the
    # iso island sits wholly on the bus side
    for u in ("U10", "U11"):
        pp = pads(u)
        logic_y = sum(pp[str(n)][1] for n in range(1, 11)) / 10
        iso_y = sum(pp[str(n)][1] for n in range(11, 21)) / 10
        if not logic_y < iso_y:
            findings.append(f"[orient] {u}: logic pin row is not north of "
                            "the iso row — barrier axis wrong")
    # MOD1 antenna overhangs N: module at rot 0 with body top at y=0
    x, y, rot, side = P["MOD1"]
    if not (rot == 0 and 5.0 <= y <= 9.0):
        findings.append("[orient] MOD1: antenna does not overhang N edge "
                        f"(y={y}, rot={rot})")


def main():
    core.configure(PROJECT, "build", NETLIST)
    core.assert_single_back_transform()
    if not core.selftest_gates():
        print("[selftest] FAILED — refusing to build")
        return 2

    bb = core.BoardBuilder(W, H, NETS, COMPS, P, overhang_ok=OVERHANG_OK,
                           edge_marker_refs=EDGE_MARKER_REFS)
    bb.place_all()
    bb.add_mounting_holes(MOUNT)
    orientation_asserts(bb.findings)
    # courtyard/outline/edge-marker/fab/readback/label-adjacency gates
    # all run inside bb.write() — the chokepoint, not per-build calls
    # (finding 09). Board-specific checks stay here: orientation
    # asserts above, DRC accepted registry below.

    OUT.mkdir(exist_ok=True)
    pcb = OUT / f"{PROJECT}.kicad_pcb"
    bans_file = OUT / "refdes_bans.json"
    bans = {}
    if bans_file.exists():
        import json as _json
        bans = {k: [tuple(v) for v in vs]
                for k, vs in _json.loads(
                    bans_file.read_text(encoding="utf-8")).items()}
    refdes_ov, refdes_unplaced = core.auto_refdes(
        COMPS, P, W, H, manual=MANUAL_REFDES, banned=bans)
    if refdes_unplaced:
        print(f"[refdes] library-fallback (no clear auto spot): {refdes_unplaced}")
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
        core.export_svg(pcb, OUT / "doc_top.svg",
                        "F.Cu,F.SilkS,F.Mask,Edge.Cuts,F.CrtYd")
    print(f"[ok] {pcb.name}: {len(bb.b.footprints)} footprints, "
          f"{len(bb.b.nets)} nets, DRC clean (accepted: "
          f"{ {k: counts.get(k, 0) for k in DRC_ACCEPTED} })")
    return 0


if __name__ == "__main__":
    sys.exit(main())
