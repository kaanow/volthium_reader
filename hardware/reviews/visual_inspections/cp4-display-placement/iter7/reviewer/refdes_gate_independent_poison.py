"""Independent poisons for the CP4 iteration-6 refdes gates.

This intentionally does not modify the generator. It exercises the public
gate functions with transforms and geometry that expose their blind spots.
"""

from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[6]
PCB_DIR = ROOT / "hardware" / "kicad" / "pcb"
sys.path.insert(0, str(PCB_DIR))

import core  # noqa: E402


def paired_transform_poison():
    """Make both model helpers agree on the old, serializer-wrong mirror."""
    placement = {"J1": (20.22, 33.175, 90, "B")}
    selected = (11.0, 19.025)

    def wrong_inverse(bx, by, x, y, rot, side):
        dx, dy = bx - x, by - y
        if rot:
            dx, dy = core.core_rot_inv(dx, dy, rot)
        if side == "B":
            dx = -dx
        return round(dx, 3), round(dy, 3)

    def paired_wrong_forward(lx, ly, x, y, rot, side):
        if side == "B":
            lx = -lx
        rx, ry = core._rot(lx, ly, rot)
        return x + rx, y + ry

    wrong_local = wrong_inverse(*selected, *placement["J1"])
    emitted_by_serializer = core.refdes_local_to_board(
        *wrong_local, *placement["J1"]
    )

    original_forward = core.refdes_local_to_board
    original_selected = dict(core._REFDES_SELECTED)
    findings = []
    try:
        core.refdes_local_to_board = paired_wrong_forward
        core._REFDES_SELECTED.clear()
        core._REFDES_SELECTED["J1"] = selected
        core.assert_refdes_roundtrip(
            {"J1": {}}, placement, {"J1": (*wrong_local, 0)}, findings
        )
    finally:
        core.refdes_local_to_board = original_forward
        core._REFDES_SELECTED.clear()
        core._REFDES_SELECTED.update(original_selected)

    print("POISON 1: coupled wrong inverse + forward model")
    print(f"  selected board point={selected}")
    print(f"  wrong local value={wrong_local}")
    print(f"  gate findings={findings}")
    print(
        "  actual serializer-frame landing="
        f"({emitted_by_serializer[0]:.3f}, {emitted_by_serializer[1]:.3f})"
    )
    escaped = not findings and any(
        abs(a - b) > 0.01 for a, b in zip(emitted_by_serializer, selected)
    )
    print(f"  RESULT={'ESCAPED' if escaped else 'CAUGHT'}")
    return escaped


def anchor_only_poison():
    """Put a text anchor outside a body while the text rectangle overlaps."""
    components = {
        "R1": {"footprint": "fake:R1"},
        "U1": {"footprint": "fake:U1"},
    }
    placement = {
        "R1": (0.0, 0.0, 0, "F"),
        "U1": (5.0, 5.0, 0, "F"),
    }
    overrides = {"R1": (3.9, 5.0, 0)}

    original_dims = core.fplib.FpDims
    try:
        core.fplib.FpDims = lambda _fpid: SimpleNamespace(
            fab_bbox=(-1.0, -1.0, 1.0, 1.0), courtyard=None
        )
        findings = core.refdes_over_body_findings(
            components, placement, overrides
        )
    finally:
        core.fplib.FpDims = original_dims

    body = (4.0, 4.0, 6.0, 6.0)
    # The generator's own nominal horizontal model for a two-character ref:
    # width=max(2*0.95, 1.8)=1.90 mm, height=1.45 mm.
    text_box = (2.95, 4.275, 4.85, 5.725)
    print("POISON 2: anchor outside, visible text rectangle overlaps")
    print("  anchor=(3.900, 5.000)")
    print(f"  text_box={text_box}")
    print(f"  other_body={body}")
    print(f"  gate findings={findings}")
    escaped = not findings and text_box[2] > body[0]
    print(f"  RESULT={'ESCAPED' if escaped else 'CAUGHT'}")
    return escaped


def own_body_poison():
    """Exercise the PR-2 case that the gate explicitly skips."""
    components = {"U1": {"footprint": "fake:U1"}}
    placement = {"U1": (5.0, 5.0, 0, "F")}
    overrides = {"U1": (0.0, 0.0, 0)}

    original_dims = core.fplib.FpDims
    try:
        core.fplib.FpDims = lambda _fpid: SimpleNamespace(
            fab_bbox=(-1.0, -1.0, 1.0, 1.0), courtyard=None
        )
        findings = core.refdes_over_body_findings(
            components, placement, overrides
        )
    finally:
        core.fplib.FpDims = original_dims

    print("POISON 3: reference anchor at its own component body centre")
    print("  anchor=(5.000, 5.000)")
    print("  own_body=(4.0, 4.0, 6.0, 6.0)")
    print(f"  gate findings={findings}")
    escaped = not findings
    print(f"  RESULT={'ESCAPED' if escaped else 'CAUGHT'}")
    return escaped


if __name__ == "__main__":
    escaped = [
        paired_transform_poison(),
        anchor_only_poison(),
        own_body_poison(),
    ]
    print(f"SUMMARY: {sum(escaped)}/3 independent poisons escaped")
    raise SystemExit(0 if all(escaped) else 1)
