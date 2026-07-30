"""Shared placement-generator core for the CP3+ PCB pass.

Same doctrine as ../schematic/core.py: explicit hand layout as DATA, all
gates in the same chokepoint as the writes, every external export
transactional, every gate poison-tested at build start.

Board writes use kiutils Board.create_new() (kiutils cannot READ a
routed KiCad-10 board — the generate-fresh flow is the only supported
path; see DESIGNER.md §12b). Mechanics inherited from the pass-1
generator (archive/pass1_pcb) where they were hard-won:
  - B.Cu placement must cascade-flip every child layer + mirror text
  - footprint-drawn Edge.Cuts must be relocated (they'd cut the board)
  - pass-1 SILENTLY SKIPPED unplaced refs; here parity is a hard gate
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import importlib.util as _ilu


def _load_module(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_KDIR = Path(__file__).resolve().parents[1]
# schematic core under a distinct module name (plain `import core` would
# resolve to THIS file); reused for KICAD_CLI/KICAD_SHARE same-root pairing
sch = _load_module("sch_core", _KDIR / "schematic" / "core.py")
fplib = _load_module("fplib", _KDIR / "pcb" / "fplib.py")
from kiutils.board import Board
from kiutils.footprint import Footprint
from kiutils.items.common import Justify, Net, Position
from kiutils.items.fpitems import FpText
from kiutils.items.gritems import GrLine
from kiutils.items.zones import Hatch, KeepoutSettings, Zone, ZonePolygon

KICAD_CLI = sch.KICAD_CLI
HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# configure() — per-board state (same pattern as schematic core)
# ---------------------------------------------------------------------------
PROJECT = None
OUT = None
NETLIST = None


def configure(project, out_dirname, netlist_path):
    global PROJECT, OUT, NETLIST
    PROJECT = project
    OUT = HERE / out_dirname
    OUT.mkdir(exist_ok=True)
    NETLIST = Path(netlist_path)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def _rot(px, py, deg):
    """Rotate a point by deg CCW in KiCad's frame (+y down, so visual CW)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (px * c + py * s, -px * s + py * c)


def courtyard_segments(fpid, x, y, deg, back=False):
    """Courtyard line segments of a placed footprint, in board coords.
    Back-side placement mirrors x (KiCad flip = mirror about the y axis
    through the anchor)."""
    fp = fplib.load(fpid)
    segs = []
    for g in fp.graphicItems:
        if getattr(g, "layer", "") not in ("F.CrtYd", "B.CrtYd"):
            continue
        t = type(g).__name__
        if t == "FpLine":
            pts = [(g.start.X, g.start.Y), (g.end.X, g.end.Y)]
        elif t == "FpRect":
            x0, y0, x1, y1 = g.start.X, g.start.Y, g.end.X, g.end.Y
            segs.extend(_seg_loop([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                  x, y, deg, back))
            continue
        else:
            continue
        segs.append(tuple(_xf(p, x, y, deg, back) for p in pts))
    return segs


def _xf(p, x, y, deg, back):
    px, py = p
    if back:
        px = -px
    rx, ry = _rot(px, py, deg)
    return (x + rx, y + ry)


def _seg_loop(pts, x, y, deg, back):
    tp = [_xf(p, x, y, deg, back) for p in pts]
    return [(tp[i], tp[(i + 1) % len(tp)]) for i in range(len(tp))]


def _seg_intersect(a, b):
    (x1, y1), (x2, y2) = a
    (x3, y3), (x4, y4) = b
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9


def _point_in_loop(pt, segs):
    """Even-odd ray cast against an unordered closed segment set."""
    px, py = pt
    hits = 0
    for (x1, y1), (x2, y2) in segs:
        if (y1 > py) != (y2 > py):
            xi = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if xi > px:
                hits += 1
    return hits % 2 == 1


def courtyards_collide(segs_a, segs_b):
    """Two courtyard outlines collide if any segments cross or one
    contains the other."""
    for a in segs_a:
        for b in segs_b:
            if _seg_intersect(a, b):
                return True
    if segs_a and segs_b:
        if _point_in_loop(segs_a[0][0], segs_b):
            return True
        if _point_in_loop(segs_b[0][0], segs_a):
            return True
    return False


def placed_pads(fpid, x, y, deg, side="F"):
    """{padnum: (board_x, board_y)} for a placed footprint — PROBE this
    for orientation invariants; never hand-derive a rotation's effect
    (schematic-era source/drain-swap lesson)."""
    fp = fplib.load(fpid)
    out = {}
    for p in fp.pads:
        out.setdefault(p.number, []).append(
            _xf((p.position.X, p.position.Y), x, y, deg, side == "B"))
    return {k: v[0] if len(v) == 1 else v for k, v in out.items()}


# ---------------------------------------------------------------------------
# Netlist (ground truth from the CP2 export)
# ---------------------------------------------------------------------------
def parse_netlist(net_path):
    """(nets, components): nets = [(code, name)]; components[ref] =
    {value, footprint, pins: {padnum: netname}}. Paren-tolerant enough for
    kicad-cli's pretty-printed .net output."""
    if not Path(net_path).exists():
        raise SystemExit(
            f"[netlist] input missing: {net_path}\n"
            "This is a tracked artifact — a fresh clone has it. If you "
            "deleted the build tree, regenerate the upstream schematic "
            "first: python hardware/kicad/schematic/build.py")
    text = Path(net_path).read_text(encoding="utf-8")
    comp_pat = re.compile(
        r'\(comp\s+\(ref\s+"([^"]+)"\)\s+\(value\s+"([^"]+)"\)\s*'
        r'\(footprint\s+"([^"]+)"\)', re.S)
    components = {r: {"value": v, "footprint": f, "pins": {}}
                  for r, v, f in comp_pat.findall(text)}
    if not components:
        raise SystemExit(f"[netlist] no components parsed from {net_path}")
    net_pat = re.compile(
        r'\(net\s+\(code\s+"?(\d+)"?\)\s+\(name\s+"([^"]*)"\)(.*?)'
        r'(?=\(net\s+\(code|\)\s*\)\s*$)', re.S)
    node_pat = re.compile(r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)')
    nets = []
    for code, name, body in net_pat.findall(text):
        nets.append((int(code), name))
        for ref, pin in node_pat.findall(body):
            if ref in components:
                components[ref]["pins"][pin] = name
    if not nets:
        raise SystemExit(f"[netlist] no nets parsed from {net_path}")
    return nets, components


# ---------------------------------------------------------------------------
# Board assembly
# ---------------------------------------------------------------------------
_F_TO_B = {"F.Cu": "B.Cu", "F.Mask": "B.Mask", "F.Paste": "B.Paste",
           "F.SilkS": "B.SilkS", "F.Fab": "B.Fab", "F.Adhes": "B.Adhes",
           "F.CrtYd": "B.CrtYd"}
_B_TO_F = {v: k for k, v in _F_TO_B.items()}


def _flip_layer(name):
    return _F_TO_B.get(name, _B_TO_F.get(name, name))


def _flip_to_back(fp):
    """Cascade-flip a kiutils footprint to the back side (pass-1 lesson:
    fp.layer alone does NOT flip pads/graphics — that shipped B.Cu parts
    physically on F.Cu)."""
    for pad in (fp.pads or []):
        pad.layers = [_flip_layer(l) for l in (pad.layers or [])]
    for gi in (fp.graphicItems or []):
        if hasattr(gi, "layer") and gi.layer:
            new = _flip_layer(gi.layer)
            if (new.startswith("B.") and gi.layer.startswith("F.")
                    and getattr(gi, "effects", None) is not None):
                if gi.effects.justify is None:
                    gi.effects.justify = Justify(mirror=True)
                else:
                    gi.effects.justify.mirror = True
            gi.layer = new
    props = fp.properties
    if isinstance(props, list):
        for p in props:
            if hasattr(p, "layer") and p.layer:
                p.layer = _flip_layer(p.layer)


class BoardBuilder:
    def __init__(self, w, h, nets, components, placement, overhang_ok=()):
        """placement: ref -> (x, y, rot_deg, side) with side in {'F','B'}.
        overhang_ok: refs whose courtyard may cross the board outline
        (edge connectors), each with the DESIGNED overhang direction."""
        self.w, self.h = w, h
        self.components = components
        self.placement = placement
        self.overhang_ok = dict(overhang_ok)
        self.findings = []

        self.b = Board.create_new()
        self.b.nets = [Net(number=0, name="")]
        self.nets_by_name = {"": 0}
        for code, name in nets:
            self.b.nets.append(Net(number=code, name=name))
            self.nets_by_name[name] = code
        self._edge()

    def _edge(self):
        def e(x1, y1, x2, y2):
            return GrLine(start=Position(X=x1, Y=y1), end=Position(X=x2, Y=y2),
                          layer="Edge.Cuts", width=0.1)
        self.b.graphicItems = [e(0, 0, self.w, 0), e(self.w, 0, self.w, self.h),
                               e(self.w, self.h, 0, self.h), e(0, self.h, 0, 0)]

    def place_all(self):
        # G1 parity — both directions, hard findings (pass-1 silently
        # skipped; that class ends here).
        missing = sorted(set(self.components) - set(self.placement))
        extra = sorted(set(self.placement) - set(self.components))
        for r in missing:
            self.findings.append(f"[parity] {r} in netlist but not placed")
        for r in extra:
            self.findings.append(f"[parity] {r} placed but not in netlist")
        for ref in sorted(set(self.components) & set(self.placement)):
            self._place_one(ref)

    def _place_one(self, ref):
        meta = self.components[ref]
        fpid = meta["footprint"]
        x, y, rot, side = self.placement[ref]
        assert side in ("F", "B"), f"{ref}: side must be F or B"
        src = fplib.resolve(fpid)
        fp = Footprint.from_file(str(src), encoding="utf-8")
        lib, _, name = fpid.partition(":")
        fp.libraryNickname = lib
        fp.entryName = name
        fp.libId = fpid
        fp.position = Position(X=x, Y=y, angle=rot)
        fp.layer = "F.Cu" if side == "F" else "B.Cu"
        if side == "B":
            _flip_to_back(fp)
        # KiCad file semantics: a pad/text angle is the TOTAL angle
        # (footprint + local). kiutils leaves the local angle untouched, so
        # a rotated footprint renders pad positions rotated but pad BODIES
        # unrotated — L-pads 0.15 mm apart shipped to DRC that way. Compose
        # the angles ourselves.
        if rot:
            for pad in (fp.pads or []):
                pad.position.angle = ((pad.position.angle or 0) + rot) % 360
            for gi in (fp.graphicItems or []):
                if isinstance(gi, FpText):
                    gi.position.angle = ((gi.position.angle or 0) + rot) % 360
        for gi in (fp.graphicItems or []):
            if getattr(gi, "layer", None) == "Edge.Cuts":
                gi.layer = "F.Fab" if side == "F" else "B.Fab"
        if fp.properties is None:
            fp.properties = {}
        fp.properties["Reference"] = ref
        fp.properties["Value"] = meta["value"]
        # ${REFERENCE}/${VALUE} user texts stay as templates — KiCad
        # substitutes from the properties; rewriting them to literals makes
        # every instance diff against its library copy
        # ([lib_footprint_mismatch] x76).
        for txt in (fp.graphicItems or []):
            if isinstance(txt, FpText):
                if txt.type == "reference":
                    txt.text = ref
                elif txt.type == "value":
                    txt.text = meta["value"]
        # pad→net binding, with per-pad gate: a netlist pin that has no
        # matching pad number is a broken footprint-symbol mapping.
        pin_to_net = dict(meta["pins"])
        padnums = {p.number for p in (fp.pads or [])}
        for pin in pin_to_net:
            if pin not in padnums:
                self.findings.append(
                    f"[pinmap] {ref}: netlist pin {pin!r} has no pad in {fpid}")
        for pad in (fp.pads or []):
            netname = pin_to_net.get(pad.number)
            if netname:
                pad.net = Net(number=self.nets_by_name[netname], name=netname)
            else:
                pad.net = Net(number=0, name="")
        if self.b.footprints is None:
            self.b.footprints = []
        self.b.footprints.append(fp)

    def add_mounting_holes(self, coords, drill_fp="MountingHole_3.2mm_M3"):
        src = None
        for d in fplib.FP_DIRS:
            p = Path(d) / "MountingHole.pretty" / f"{drill_fp}.kicad_mod"
            if p.exists():
                src = p
                break
        if src is None:
            raise SystemExit(f"[mount] {drill_fp} not found")
        # holes participate in the courtyard/outline gates like any part
        # (the first DRC run caught a hole x jack overlap the analytic gate
        # was blind to — holes lived outside the placement dict)
        self._extra_courtyards = getattr(self, "_extra_courtyards", [])
        for i, (x, y) in enumerate(coords, start=1):
            self._extra_courtyards.append(
                (f"H{i}", "F",
                 courtyard_segments(f"MountingHole:{drill_fp}", x, y, 0)))
        for i, (x, y) in enumerate(coords, start=1):
            fp = Footprint.from_file(str(src), encoding="utf-8")
            fp.libraryNickname = "MountingHole"
            fp.entryName = drill_fp
            fp.libId = f"MountingHole:{drill_fp}"
            fp.position = Position(X=x, Y=y, angle=0)
            fp.layer = "F.Cu"
            if fp.properties is None:
                fp.properties = {}
            fp.properties["Reference"] = f"H{i}"
            fp.properties["Value"] = "M3"
            self.b.footprints.append(fp)

    def add_keepout(self, x, y, w, h, name):
        zone = Zone(
            net=0, netName="", layers=["F.Cu", "B.Cu"], name=name,
            hatch=Hatch(style="edge", pitch=0.508),
            keepoutSettings=KeepoutSettings(
                tracks="not_allowed", vias="not_allowed", pads="allowed",
                copperpour="not_allowed", footprints="allowed"),
            polygons=[ZonePolygon(coordinates=[
                Position(X=x, Y=y), Position(X=x + w, Y=y),
                Position(X=x + w, Y=y + h), Position(X=x, Y=y + h)])])
        if self.b.zones is None:
            self.b.zones = []
        self.b.zones.append(zone)

    # -- gates ------------------------------------------------------------
    def gate_courtyards(self):
        """Pairwise courtyard collision — analytic, from the same library
        geometry the board embeds. DRC re-checks this externally."""
        placed = list(getattr(self, "_extra_courtyards", []))
        for ref in sorted(set(self.components) & set(self.placement)):
            fpid = self.components[ref]["footprint"]
            x, y, rot, side = self.placement[ref]
            segs = courtyard_segments(fpid, x, y, rot, back=(side == "B"))
            placed.append((ref, side, segs))
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                ra, sa, a = placed[i]
                rb, sb, b = placed[j]
                if sa != sb:
                    continue  # opposite sides: courtyards independent
                if courtyards_collide(a, b):
                    self.findings.append(f"[courtyard] {ra} x {rb} ({sa} side)")

    def gate_outline(self):
        """Courtyards inside the outline, except whitelisted edge
        connectors, which may overhang ONLY on their declared edge."""
        eps = 1e-6
        for ref in sorted(set(self.components) & set(self.placement)):
            fpid = self.components[ref]["footprint"]
            x, y, rot, side = self.placement[ref]
            segs = courtyard_segments(fpid, x, y, rot, back=(side == "B"))
            pts = [p for s in segs for p in s]
            if not pts:
                continue
            x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
            y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
            out = []
            if x0 < -eps: out.append("W")
            if x1 > self.w + eps: out.append("E")
            if y0 < -eps: out.append("N")
            if y1 > self.h + eps: out.append("S")
            allowed = self.overhang_ok.get(ref, "")
            bad = [d for d in out if d not in allowed]
            if bad:
                self.findings.append(
                    f"[outline] {ref} courtyard crosses board edge {bad} "
                    f"(allowed: {allowed or 'none'})")

    def gate_fab_rules(self, min_drill=0.3, min_annular=0.13):
        for fp in self.b.footprints:
            ref = fp.properties.get("Reference", "?")
            for pad in (fp.pads or []):
                if pad.drill is None or not pad.drill.diameter:
                    continue
                d = pad.drill.diameter
                if d < min_drill - 1e-9:
                    self.findings.append(
                        f"[fab] {ref} pad {pad.number}: drill {d} < {min_drill}")
                if pad.type == "thru_hole":
                    ann = (min(pad.size.X, pad.size.Y) - d) / 2
                    if ann < min_annular - 1e-9:
                        self.findings.append(
                            f"[fab] {ref} pad {pad.number}: annular "
                            f"{ann:.3f} < {min_annular}")

    # -- write + readback -------------------------------------------------
    def write(self, path, prop_overrides=None):
        self.b.to_file(str(path), encoding="utf-8")
        if not Path(path).exists() or Path(path).stat().st_size == 0:
            raise SystemExit(f"[write] {path} missing/empty after to_file")
        # kiutils (KiCad-6 era) parses KiCad-10's "(remove_unused_layers no)"
        # as a bare flag and re-emits "(remove_unused_layers)" — which KiCad
        # reads as YES: semantics inverted on every THT pad, and every such
        # footprint diffs against its library ([lib_footprint_mismatch]).
        # Restore the explicit "no" textually at the write chokepoint.
        text = Path(path).read_text(encoding="utf-8")
        text = text.replace("(remove_unused_layers)",
                            "(remove_unused_layers no)")
        # kiutils stamps serialization time into (tedit ...) — the one
        # nondeterminism in the board build. Pin it so rebuild == committed
        # is a checkable handoff property (KiCad 10 ignores this legacy field).
        text = re.sub(r"\(tedit [0-9A-Fa-f]+\)", "(tedit 0)", text)
        text = _restore_properties(text, prop_overrides)
        Path(path).write_text(text, encoding="utf-8")

    def gate_readback(self, path):
        """Judge the WRITTEN artifact: re-parse the .kicad_pcb text and
        diff (ref, pad, net) triples against the netlist, both ways."""
        text = Path(path).read_text(encoding="utf-8")
        board = set()
        chunks = re.split(r'\n  \(footprint ', text)[1:]
        for ch in chunks:
            refm = re.search(r'\(property "Reference" "([^"]+)"', ch)
            if not refm:
                continue
            ref = refm.group(1)
            # walk pad blocks: each runs to the next pad (or chunk end);
            # its (net N "name") — if bound — lives inside that span
            pads = list(re.finditer(r'\(pad "([^"]*)"', ch))
            for i, pm in enumerate(pads):
                end = pads[i + 1].start() if i + 1 < len(pads) else len(ch)
                span = ch[pm.start():end]
                nm = re.search(r'\(net \d+ "([^"]*)"\)', span)
                if nm and nm.group(1):   # net 0 "" = unbound mech/npth pad
                    board.add((ref, pm.group(1), nm.group(1)))
        want = set()
        for ref, meta in self.components.items():
            for pin, net in meta["pins"].items():
                want.add((ref, pin, net))
        placed_refs = set(self.components) & set(self.placement)
        want = {t for t in want if t[0] in placed_refs}
        missing = want - board
        for t in sorted(missing):
            self.findings.append(f"[readback] net binding missing in file: {t}")
        # extras: board pads bound to a net the netlist doesn't give them
        extra = {t for t in board if t[0] in placed_refs} - want
        for t in sorted(extra):
            self.findings.append(f"[readback] unexpected binding in file: {t}")


def write_project(out_dir, project, netclasses, custom_rules=""):
    """Emit <project>.kicad_pro (net classes per cp1 §11.3) + fp-lib-table
    so the volthium: footprint links resolve for GUI/CLI opens. custom_rules
    (KiCad .kicad_dru text) carries scoped exceptions, e.g. a fine-pitch
    connector's own pad field below the routing netclass clearance."""
    if custom_rules:
        (Path(out_dir) / f"{project}.kicad_dru").write_text(
            custom_rules, encoding="utf-8")
    pro = {
        "board": {"design_settings": {"defaults": {}, "rules": {
            "min_copper_edge_clearance": 0.3}}},
        "meta": {"filename": f"{project}.kicad_pro", "version": 3},
        "net_settings": {
            "classes": [
                {"name": name, "wire_width": 6, "bus_width": 12,
                 "track_width": tw, "clearance": cl, "via_diameter": 0.8,
                 "via_drill": 0.4, "uvia_diameter": 0.3, "uvia_drill": 0.1,
                 "diff_pair_width": tw, "diff_pair_gap": 0.25,
                 "pattern": pats}
                for name, tw, cl, pats in netclasses],
            "meta": {"version": 4},
        },
    }
    (Path(out_dir) / f"{project}.kicad_pro").write_text(
        json.dumps(pro, indent=2), encoding="utf-8")
    (Path(out_dir) / "fp-lib-table").write_text(
        '(fp_lib_table\n  (version 7)\n'
        '  (lib (name "volthium")(type "KiCad")'
        '(uri "${KIPRJMOD}/../../footprints/volthium.pretty")'
        '(options "")(descr "repo-local"))\n)\n', encoding="utf-8")


# ---------------------------------------------------------------------------
# Library-fidelity property restoration (kiutils loss repair)
# ---------------------------------------------------------------------------
_PROPCACHE = {}


def _balanced(s, start):
    d = 0
    k = start
    while True:
        if s[k] == "(":
            d += 1
        elif s[k] == ")":
            d -= 1
            if d == 0:
                return k + 1
        k += 1


def _lib_property_blocks(fpid):
    """Raw '(property \"Name\" ...)' blocks from the .kicad_mod, uuid
    stripped, collapsed to one line. kiutils models KiCad-10 properties as
    bare name->string, silently dropping position/layer/font/hide — every
    refdes then renders at the anchor in default font. Restore from the
    library text."""
    if fpid in _PROPCACHE:
        return _PROPCACHE[fpid]
    text = fplib.resolve(fpid).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'\(property "([^"]+)"', text):
        end = _balanced(text, m.start())
        block = text[m.start():end]
        block = re.sub(r'\(uuid "[^"]*"\)', '', block)
        block = re.sub(r'\s+', ' ', block).replace('( ', '(').strip()
        out[m.group(1)] = block
    _PROPCACHE[fpid] = out
    return out


def _norm_text_angle(a):
    a %= 360
    if 90 < a <= 270:
        a = (a + 180) % 360
    return a


def _restore_properties(board_text, prop_overrides=None):
    """For every footprint chunk: swap kiutils' collapsed
    (property "N" "v") lines for the library's full block, with the value
    substituted and the text angle composed with the footprint rotation
    (normalized to read bottom/right, like the GUI's keep-upright).
    prop_overrides: {ref: (dx, dy, angle)} — explicit refdes text
    placement in the footprint's local frame (silk engineering data)."""
    prop_overrides = prop_overrides or {}
    out = []
    pos = 0
    for m in re.finditer(r'\n  \(footprint "([^"]+)"', board_text):
        start = m.start() + 1
        end = _balanced(board_text, start + 2)
        out.append(board_text[pos:start])
        chunk = board_text[start:end]
        fpid = m.group(1)
        try:
            lib_props = _lib_property_blocks(fpid)
        except SystemExit:
            lib_props = {}
        atm = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', chunk)
        rot = float(atm.group(3)) if atm and atm.group(3) else 0.0
        refm = re.search(r'\(property "Reference" "([^"]+)"', chunk)
        ref = refm.group(1) if refm else None

        def sub_prop(pm):
            name, val = pm.group(1), pm.group(2)
            lib = lib_props.get(name)
            if not lib:
                return pm.group(0)
            # substitute the instance text into the library block
            blk = re.sub(r'^\(property "[^"]+" "[^"]*"',
                         f'(property "{name}" "{val}"', lib)
            if name == "Reference" and fpid.startswith("MountingHole"):
                # convention: mounting holes carry no silk refdes (H1/H2
                # rendered off-board at the corner holes otherwise)
                if "(hide yes)" not in blk:
                    blk = blk.replace("(effects", "(hide yes) (effects", 1)
            ov = prop_overrides.get(ref) if name == "Reference" else None
            bat = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
            if ov:
                dx, dy, ang = ov[:3]
                blk = blk.replace(bat.group(0), f'(at {dx} {dy} {ang})', 1)
                if len(ov) > 3:   # explicit font (floored at fab minimum)
                    f = max(ov[3], 1.0)
                    blk = re.sub(r'\(size [\d.]+ [\d.]+\)',
                                 f'(size {f} {f})', blk, count=1)
            elif bat and rot:
                la = float(bat.group(3)) if bat.group(3) else 0.0
                na = _norm_text_angle(la + rot)
                blk = blk.replace(
                    bat.group(0),
                    f'(at {bat.group(1)} {bat.group(2)} {na:g})', 1)
            return blk

        chunk = re.sub(r'\(property "([^"]+)" "([^"]*)"\)', sub_prop, chunk)
        out.append(chunk)
        pos = end
    out.append(board_text[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Refdes silk auto-placement
# ---------------------------------------------------------------------------
def _rects_overlap(a, b, margin=0.15):
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0]
                or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def auto_refdes(components, placement, board_w, board_h,
                extra_rects=(), big_area=80.0,
                char_w=0.95, text_h=1.45, manual=None, banned=None):
    """Greedy refdes placement on silk. For each part (row order), try the
    candidate spots N/S/E/W of the courtyard (3 offset rings) plus, for
    large parts, the body center; take the first spot clear of every pad
    field, every OTHER part's body, every already-placed refdes box, and
    the board edge. Returns ({ref: (dx, dy, angle)} in footprint-local
    frame for _restore_properties, [unplaced refs])."""
    parts = []
    for ref in sorted(set(components) & set(placement)):
        fpid = components[ref]["footprint"]
        x, y, rot, side = placement[ref]
        d = fplib.FpDims(fpid)
        # obstacle/candidate geometry = the PHYSICAL body (fab outline),
        # not the courtyard: the ESP32 module's courtyard carries a 48 mm
        # antenna keep-out arm that would otherwise veto every refdes near
        # the module
        cb = d.fab_bbox or d.courtyard or d.overall
        corners = [core_xf(p, x, y, rot, side == "B") for p in
                   [(cb[0], cb[1]), (cb[2], cb[1]), (cb[2], cb[3]),
                    (cb[0], cb[3])]]
        xs = [p[0] for p in corners]; ys = [p[1] for p in corners]
        # silk outlines run ~0.1-0.3 mm outside the fab outline; inflate the
        # obstacle so text never kisses a neighbour's (or its own) silk
        body = (min(xs) - 0.25, min(ys) - 0.25, max(xs) + 0.25, max(ys) + 0.25)
        pb = d.pads_bbox
        pcorners = [core_xf(p, x, y, rot, side == "B") for p in
                    [(pb[0], pb[1]), (pb[2], pb[1]), (pb[2], pb[3]),
                     (pb[0], pb[3])]] if pb else corners
        pxs = [p[0] for p in pcorners]; pys = [p[1] for p in pcorners]
        pads = (min(pxs), min(pys), max(pxs), max(pys))
        parts.append((ref, fpid, x, y, rot, side, body, pads))

    pad_rects = [p[7] for p in parts] + list(extra_rects)
    body_by_ref = {p[0]: p[6] for p in parts}
    placed_text = []
    overrides = {}
    unplaced = []

    # manual spots first: {ref: (board_x, board_y, angle[, font])} —
    # reserved before the greedy pass so auto text routes around them
    manual = manual or {}
    byref = {p[0]: p for p in parts}
    for ref, mv in manual.items():
        bx, by, ang = mv[:3]
        font = mv[3] if len(mv) > 3 else None
        cw = char_w
        th = text_h
        tw = max(len(ref) * cw, 1.8)
        hw, hh = (tw / 2, th / 2) if ang == 0 else (th / 2, tw / 2)
        placed_text.append((bx - hw, by - hh, bx + hw, by + hh))
        _, _, x, y, rot, side, _, _ = byref[ref]
        dx, dy = bx - x, by - y
        if rot:
            dx, dy = core_rot_inv(dx, dy, rot)
        if side == "B":
            dx = -dx
        ov = (round(dx, 3), round(dy, 3), ang)
        overrides[ref] = ov if font is None else ov + (font,)

    for ref, fpid, x, y, rot, side, body, pads in sorted(
            parts, key=lambda p: (p[6][1], p[6][0])):
        if ref in manual:
            continue
        bx0, by0, bx1, by1 = body
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        area = (bx1 - bx0) * (by1 - by0)
        chosen = None
        # single font tier: JLCPCB's silk floor is 1.0 mm height / 0.15 mm
        # stroke ("characters less than this will be unidentifiable" —
        # capability page, fetched 2026-07-30). A 0.8 mm 'compact' tier
        # shipped here briefly and died in self-review.
        for cw, th, font in ((char_w, text_h, None),):
            tw = max(len(ref) * cw, 1.8)
            cands = []
            # N/S rings must be >= a text height apart or adjacent rows'
            # candidates overlap and dense rows exhaust their spots
            for ring in (0.45, 0.45 + th + 0.2, 0.45 + 2 * (th + 0.2)):
                cands.append((cx, by0 - ring - th / 2, 0))          # N
                cands.append((cx, by1 + ring + th / 2, 0))          # S
            for ring in (0.45, 0.9, 1.6, 2.3):
                cands.append((bx1 + ring + tw / 2, cy, 0))          # E
                cands.append((bx0 - ring - tw / 2, cy, 0))          # W
                # vertical text in the horizontal gaps
                cands.append((bx1 + ring + th / 2, cy, 90))
                cands.append((bx0 - ring - th / 2, cy, 90))
            if area >= big_area:
                # own body LAST: legal, but invisible once the part is
                # soldered — prefer a spot that survives assembly
                cands.append((cx, cy, 0))
            for tcx, tcy, ang in cands:
                hw, hh = (tw / 2, th / 2) if ang == 0 else (th / 2, tw / 2)
                rect = (tcx - hw, tcy - hh, tcx + hw, tcy + hh)
                if rect[0] < 0.5 or rect[1] < 0.5 or \
                   rect[2] > board_w - 0.5 or rect[3] > board_h - 0.5:
                    continue
                # DRC-refuted spots (empirical calibration — the refine
                # loop bans positions the real glyph geometry rejected)
                if banned and any(abs(tcx - bx) < 0.8 and abs(tcy - by) < 0.8
                                  for bx, by in banned.get(ref, ())):
                    continue
                if any(_rects_overlap(rect, pr) for pr in pad_rects):
                    continue
                own_center = area >= big_area and (tcx, tcy) == (cx, cy)
                if not own_center and any(
                        _rects_overlap(rect, b)
                        for r2, b in body_by_ref.items() if r2 != ref):
                    continue
                if not own_center and _rects_overlap(rect, body):
                    continue
                if any(_rects_overlap(rect, t) for t in placed_text):
                    continue
                chosen = (tcx, tcy, ang, rect, font)
                break
            if chosen:
                break
        if chosen is None:
            unplaced.append(ref)
            continue
        tcx, tcy, ang, rect, font = chosen
        placed_text.append(rect)
        # convert board-frame center to footprint-local (inverse transform)
        dx, dy = tcx - x, tcy - y
        if rot:
            dx, dy = core_rot_inv(dx, dy, rot)
        if side == "B":
            dx = -dx
        ov = (round(dx, 3), round(dy, 3), ang)
        overrides[ref] = ov if font is None else ov + (font,)
    return overrides, unplaced


def core_xf(p, x, y, deg, back):
    return _xf(p, x, y, deg, back)


def core_rot_inv(dx, dy, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    # forward is rotateCCW in KiCad frame: (x*c + y*s, -x*s + y*c)
    return (dx * c - dy * s, dx * s + dy * c)


def refdes_boxes_from_board(board_text):
    """Rendered-box estimate for every VISIBLE Reference property in the
    WRITTEN board (anchor + angle + font from the file; measured-mean
    advance). Covers auto, manual, AND library-fallback refs — the
    fallback class was invisible to the placer's own checks (CP3 F03)."""
    boxes = []
    pos = 0
    for m in re.finditer(r'\n  \(footprint "([^"]+)"', board_text):
        start = m.start() + 1
        end = _balanced(board_text, start + 2)
        ch = board_text[start:end]
        atm = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', ch)
        if not atm:
            pos = end
            continue
        fx, fy = float(atm.group(1)), float(atm.group(2))
        frot = float(atm.group(3)) if atm.group(3) else 0.0
        pm = re.search(r'\(property "Reference" "([^"]+)"', ch)
        if pm:
            blk = ch[pm.start():_balanced(ch, pm.start())]
            if "(hide yes)" not in blk:
                bat = re.search(
                    r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', blk)
                fs = re.search(r'\(size ([\d.]+) [\d.]+\)', blk)
                ref = pm.group(1)
                dx, dy = float(bat.group(1)), float(bat.group(2))
                ta = float(bat.group(3)) if bat.group(3) else 0.0
                font = float(fs.group(1)) if fs else 1.0
                bx, by = _xf((dx, dy), fx, fy, frot, False)
                tw = max(len(ref) * 0.95 * font, 1.5)
                th = 1.45 * font
                hw, hh = ((tw / 2, th / 2) if ta % 180 == 0
                          else (th / 2, tw / 2))
                boxes.append((ref, (bx - hw, by - hh, bx + hw, by + hh)))
        pos = end
    return boxes


def label_adjacency_findings(boxes, run_gap=0.7, stack_gap=0.30):
    """Concatenation model (calibrated to the reviewer-confirmed failure:
    0.16 mm x-gap at ~45% line overlap read as "L10R23"): two labels
    merge when they share a baseline (>=40% overlap on the reading axis'
    perpendicular) and the along-reading gap is under ~one character
    advance (run_gap); stacked lines touching within stack_gap also
    fail. Mere diagonal proximity is NOT concatenation — DRC's silk
    clearance owns actual overlap, eyes parse offset baselines fine
    (first cut of this gate fired on 25 such pairs and made dense rows
    unsolvable)."""
    out = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ra, a = boxes[i]
            rb, b = boxes[j]
            gx = max(a[0], b[0]) - min(a[2], b[2])
            gy = max(a[1], b[1]) - min(a[3], b[3])
            ovy = min(a[3], b[3]) - max(a[1], b[1])
            ovx = min(a[2], b[2]) - max(a[0], b[0])
            minh = min(a[3] - a[1], b[3] - b[1])
            minw = min(a[2] - a[0], b[2] - b[0])
            same_line = ovy >= 0.4 * minh and gx < run_gap
            stacked = ovx >= 0.4 * minw and 0 <= gy < stack_gap
            if same_line or stacked:
                ca = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
                cb = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
                kind = "same-line" if same_line else "stacked"
                out.append(f"[label-adjacency] {ra}@({ca[0]:.2f},{ca[1]:.2f})"
                           f" x {rb}@({cb[0]:.2f},{cb[1]:.2f}): {kind}, gap "
                           f"{max(gx, gy):.2f} — reads as one refdes")
    return out


# ---------------------------------------------------------------------------
# External ground truth: DRC (transactional, strict parse)
# ---------------------------------------------------------------------------
def run_drc(pcb_path, accepted, out_rpt):
    """kicad-cli pcb drc, transactional. Returns list of unaccounted
    findings (empty = clean). accepted: {category: rationale} classes or
    (category, object-substring) pairs."""
    rpt = Path(out_rpt)
    rpt.unlink(missing_ok=True)
    r = subprocess.run(
        [str(KICAD_CLI), "pcb", "drc", "--severity-all",
         "--exit-code-violations", "-o", str(rpt), str(pcb_path)],
        capture_output=True, text=True)
    if r.returncode not in (0, 5):
        raise SystemExit(f"[drc] kicad-cli failed rc={r.returncode}: "
                         f"{r.stderr[-400:]}")
    if not rpt.exists() or rpt.stat().st_size == 0:
        raise SystemExit("[drc] report missing/empty after run — refusing "
                         "to judge a stale artifact")
    text = rpt.read_text(encoding="utf-8")
    entries = re.findall(r'^\[(\w+)\]: (.*)$', text, re.M)
    unaccounted = []
    counts = {}
    for cat, msg in entries:
        counts[cat] = counts.get(cat, 0) + 1
        if cat in accepted:
            continue
        if any(isinstance(k, tuple) and k[0] == cat and k[1] in msg
               for k in accepted):
            continue
        unaccounted.append((cat, msg))
    return unaccounted, counts


# ---------------------------------------------------------------------------
# Renders (transactional)
# ---------------------------------------------------------------------------
def render_board(pcb_path, out_png, side):
    p = Path(out_png)
    p.unlink(missing_ok=True)
    r = subprocess.run(
        [str(KICAD_CLI), "pcb", "render", "--side", side, "--quality", "high",
         "--width", "2400", "--height", "1800", "-o", str(p), str(pcb_path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not p.exists() or p.stat().st_size == 0:
        raise SystemExit(f"[render] {side} failed rc={r.returncode}: "
                         f"{r.stderr[-300:]}")


def export_svg(pcb_path, out_svg, layers):
    p = Path(out_svg)
    p.unlink(missing_ok=True)
    r = subprocess.run(
        [str(KICAD_CLI), "pcb", "export", "svg", "--layers", layers,
         "--page-size-mode", "2", "--exclude-drawing-sheet",
         "-o", str(p), str(pcb_path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not p.exists() or p.stat().st_size == 0:
        raise SystemExit(f"[svg] failed rc={r.returncode}: {r.stderr[-300:]}")


# ---------------------------------------------------------------------------
# Build-start self-test: every analytic gate must demonstrably fail
# ---------------------------------------------------------------------------
def selftest_gates():
    ok = True
    # courtyard collision must fire on two overlapping 0603s and stay
    # quiet at a clean spacing
    fp = "Resistor_SMD:R_0603_1608Metric"
    a = courtyard_segments(fp, 10, 10, 0)
    b_hot = courtyard_segments(fp, 11, 10, 0)     # 1 mm apart: overlaps (2.96 wide)
    b_cold = courtyard_segments(fp, 14, 10, 0)    # 4 mm apart: clean
    if not courtyards_collide(a, b_hot):
        print("[selftest] courtyard gate FAILED to fire on overlap")
        ok = False
    if courtyards_collide(a, b_cold):
        print("[selftest] courtyard gate false-fired on clean spacing")
        ok = False
    # rotation must move the collision: a 0603 rotated 90 at 1.0 mm x-offset
    # is narrower in x — still colliding at 0.5 mm
    b_rot = courtyard_segments(fp, 10.5, 10, 90)
    if not courtyards_collide(a, b_rot):
        print("[selftest] courtyard gate FAILED on rotated overlap")
        ok = False
    # containment case: tiny courtyard fully inside a big one (no edge
    # crossings) must still collide
    small = courtyard_segments("Capacitor_SMD:C_0402_1005Metric", 10, 10, 0)
    big = courtyard_segments("Connector_RJ:RJ45_Amphenol_RJHSE5380", 8, 8, 0)
    if not courtyards_collide(small, big):
        print("[selftest] courtyard gate FAILED on containment")
        ok = False
    # label-adjacency gate: concatenating pair fires, spaced pair doesn't
    hot = [("L10", (10, 10, 12, 11.4)), ("R23", (12.16, 10, 14.6, 11.4))]
    cold = [("L10", (10, 10, 12, 11.4)), ("R23", (13.2, 10, 15.6, 11.4))]
    if not label_adjacency_findings(hot):
        print("[selftest] label-adjacency FAILED to fire on 0.16 mm gap")
        ok = False
    if label_adjacency_findings(cold):
        print("[selftest] label-adjacency false-fired on 1.2 mm gap")
        ok = False
    # DRC transactional contract: a forced-failing invocation against a
    # pre-seeded stale report must raise, not judge the stale file
    with tempfile.TemporaryDirectory() as td:
        stale = Path(td) / "drc.rpt"
        stale.write_text("** Drc report — STALE **\n", encoding="utf-8")
        try:
            run_drc(Path(td) / "nonexistent.kicad_pcb", {}, stale)
            print("[selftest] DRC contract FAILED: judged a stale report")
            ok = False
        except SystemExit:
            pass
    return ok
