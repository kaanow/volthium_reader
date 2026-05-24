#!/usr/bin/env python3
"""CP3 PCB build script — project-local footprint cache + smoke test.

By default this script resolves footprints from the committed
hardware/kicad/libraries/volthium.pretty/ directory. The host KiCad
install is only touched when invoked with --rebuild-footprints, which
re-extracts a curated set of .kicad_mod files from the host KiCad
footprint tree into the project-local cache.

This mirrors the CP2 symbol-library pattern (volthium.kicad_sym +
build_schematics.py --rebuild-library) and makes PCB generation
reproducible across machines: anyone with this repo + .venv can run
this script without any KiCad install at all (KiCad is still needed
for the GUI and for kicad-cli, but not for python-side generation).

Run from repo root:
  .venv/bin/python hardware/kicad/build_pcbs.py
  .venv/bin/python hardware/kicad/build_pcbs.py --rebuild-footprints
"""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJ_FP = REPO / "hardware/kicad/libraries/volthium.pretty"
SMOKE = REPO / "hardware/kicad/_smoke"

# Host KiCad footprint roots, tried in order. Only used when
# --rebuild-footprints is passed.
HOST_FP_ROOTS = [
    Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),
    Path("/usr/share/kicad/footprints"),
    Path("/usr/local/share/kicad/footprints"),
    Path("/opt/homebrew/share/kicad/footprints"),
]

# Curated set of footprints the project needs. Each entry is
# (host_lib_name, footprint_name). At iter 3 this list grows to cover
# every Footprint field referenced by the CP2 schematics.
STOCK_FOOTPRINTS = [
    ("Resistor_SMD", "R_0805_2012Metric"),
]


def _find_host_root() -> Path:
    for root in HOST_FP_ROOTS:
        if root.is_dir():
            return root
    raise SystemExit(
        "ERROR: could not find a host KiCad footprint tree. Tried:\n  "
        + "\n  ".join(str(r) for r in HOST_FP_ROOTS)
        + "\nInstall KiCad 10 (or pass --skip-rebuild) to proceed."
    )


def rebuild_footprint_cache() -> None:
    """Re-extract STOCK_FOOTPRINTS from host KiCad into volthium.pretty/.

    This is the only function in this script that touches the host
    KiCad install. All other paths read from PROJ_FP only.
    """
    host = _find_host_root()
    PROJ_FP.mkdir(parents=True, exist_ok=True)
    n = 0
    for lib_name, fp_name in STOCK_FOOTPRINTS:
        src = host / f"{lib_name}.pretty" / f"{fp_name}.kicad_mod"
        if not src.is_file():
            raise SystemExit(f"ERROR: host footprint not found: {src}")
        dst = PROJ_FP / f"{fp_name}.kicad_mod"
        shutil.copy(src, dst)
        n += 1
    print(f"rebuilt {n} footprint(s) into {PROJ_FP.relative_to(REPO)}/")


def resolve_footprint(fp_name: str) -> Path:
    """Return path to a footprint .kicad_mod from the project-local cache.

    Never touches the host KiCad install. If the requested footprint is
    not cached, the error message tells the operator how to fix it.
    """
    p = PROJ_FP / f"{fp_name}.kicad_mod"
    if not p.is_file():
        raise SystemExit(
            f"ERROR: footprint '{fp_name}' not in {PROJ_FP.relative_to(REPO)}/.\n"
            f"Add it to STOCK_FOOTPRINTS in {Path(__file__).name} and re-run "
            f"with --rebuild-footprints to extract from host KiCad."
        )
    return p


def build_smoke() -> None:
    """Build the CP3 smoke-test PCB using project-local footprint cache only."""
    from kiutils.board import Board
    from kiutils.footprint import Footprint
    from kiutils.items.common import Position, Net
    from kiutils.items.gritems import GrLine
    from kiutils.items.fpitems import FpText

    SMOKE.mkdir(parents=True, exist_ok=True)
    b = Board.create_new()

    def edge(x1, y1, x2, y2):
        return GrLine(
            start=Position(X=x1, Y=y1),
            end=Position(X=x2, Y=y2),
            layer="Edge.Cuts",
            width=0.05,
        )

    if b.graphicItems is None:
        b.graphicItems = []
    b.graphicItems.extend([
        edge(0, 0, 50, 0),
        edge(50, 0, 50, 30),
        edge(50, 30, 0, 30),
        edge(0, 30, 0, 0),
    ])

    b.nets = [
        Net(number=0, name=""),
        Net(number=1, name="RAW"),
        Net(number=2, name="GND"),
    ]

    fp = Footprint.from_file(str(resolve_footprint("R_0805_2012Metric")))
    fp.libraryNickname = "volthium"
    fp.entryName = "R_0805_2012Metric"
    fp.libId = "volthium:R_0805_2012Metric"
    fp.position = Position(X=25, Y=15, angle=0)
    fp.layer = "F.Cu"
    for txt in (fp.graphicItems or []):
        if isinstance(txt, FpText):
            if txt.type == "reference":
                txt.text = "R1"
            elif txt.type == "value":
                txt.text = "10k"
    if fp.pads:
        fp.pads[0].net = Net(number=1, name="RAW")
        fp.pads[1].net = Net(number=2, name="GND")

    if b.footprints is None:
        b.footprints = []
    b.footprints.append(fp)

    out = SMOKE / "smoke.kicad_pcb"
    b.to_file(str(out))
    print(f"wrote {out.relative_to(REPO)} ({out.stat().st_size} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rebuild-footprints",
        action="store_true",
        help="Re-extract STOCK_FOOTPRINTS from host KiCad into volthium.pretty/. "
        "Only needed when adding new footprints or refreshing the cache.",
    )
    ap.add_argument(
        "--smoke",
        action="store_true",
        default=True,
        help="Build the CP3 smoke-test PCB (default).",
    )
    args = ap.parse_args()

    if args.rebuild_footprints:
        rebuild_footprint_cache()

    if args.smoke:
        build_smoke()

    return 0


if __name__ == "__main__":
    sys.exit(main())
