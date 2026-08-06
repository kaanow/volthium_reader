#!/usr/bin/env python3
"""Independent CP4 geometry probe over the serialized board.

This intentionally does not import the PCB generator or its geometry helpers.
It parses the committed board copy with kiutils, transforms the geometry stored
inside each footprint, and uses conservative axis-aligned boxes as a second
model for the changed placement.
"""
import math
from pathlib import Path

from kiutils.board import Board


ROOT = Path(__file__).resolve().parents[6]
BOARD = ROOT / "hardware/kicad/pcb/build_display/display_pcb.kicad_pcb"
TARGETS = {
    "J1": (11.0, 30.0),
    "U1": (12.0, 48.0),
    "U2": (25.5, 33.5),
    "R2": (27.0, 29.0),
}


def ref(fp):
    return fp.properties["Reference"]


def world(fp, point):
    """Transform geometry already serialized in the board footprint."""
    angle = math.radians(fp.position.angle or 0.0)
    c, s = math.cos(angle), math.sin(angle)
    x, y = point.X, point.Y
    return fp.position.X + x * c + y * s, fp.position.Y - x * s + y * c


def primitive_points(item):
    name = type(item).__name__
    if name == "FpRect":
        x0, y0 = item.start.X, item.start.Y
        x1, y1 = item.end.X, item.end.Y
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if name == "FpCircle":
        cx, cy = item.center.X, item.center.Y
        radius = math.hypot(item.end.X - cx, item.end.Y - cy)
        return [(cx + radius * math.cos(a), cy + radius * math.sin(a))
                for a in [i * math.pi / 8 for i in range(16)]]
    points = []
    for attr in ("start", "mid", "end", "center", "position"):
        point = getattr(item, attr, None)
        if point is not None and hasattr(point, "X"):
            points.append((point.X, point.Y))
    points.extend((p.X, p.Y) for p in (getattr(item, "coordinates", None) or []))
    return points


def courtyard_box(fp):
    points = []
    for item in fp.graphicItems:
        if getattr(item, "layer", "").endswith(".CrtYd"):
            for x, y in primitive_points(item):
                class Point:
                    X, Y = x, y
                points.append(world(fp, Point))
    if not points:
        raise RuntimeError(f"{ref(fp)} has no courtyard geometry")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def pad_box(fp):
    boxes = []
    for pad in fp.pads:
        x, y = world(fp, pad.position)
        boxes.append((x - pad.size.X / 2, y - pad.size.Y / 2,
                      x + pad.size.X / 2, y + pad.size.Y / 2))
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def center(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def intersects(a, b, epsilon=1e-6):
    return min(a[2], b[2]) - max(a[0], b[0]) > epsilon and \
        min(a[3], b[3]) - max(a[1], b[1]) > epsilon


def main():
    board = Board().from_file(str(BOARD))
    fps = {ref(fp): fp for fp in board.footprints}
    courts = {name: courtyard_box(fp) for name, fp in fps.items()}

    print(f"board={BOARD.relative_to(ROOT).as_posix()}")
    print("model=serialized-footprint geometry + conservative AABB")
    print("centres:")
    for name, target in TARGETS.items():
        actual = center(courts[name])
        error = math.hypot(actual[0] - target[0], actual[1] - target[1])
        print(f"  {name}: target=({target[0]:.3f},{target[1]:.3f}) "
              f"actual=({actual[0]:.3f},{actual[1]:.3f}) error={error:.6f} mm")
        if error > 0.01:
            raise SystemExit(f"FAIL: {name} centre error")

    j1 = fps["J1"]
    signal = []
    for pad in j1.pads:
        if pad.number.isdigit():
            signal.append(world(j1, pad.position))
    sx = sum(p[0] for p in signal) / len(signal)
    sy = sum(p[1] for p in signal) / len(signal)
    cx, cy = center(courts["J1"])
    dx, dy = cx - sx, cy - sy
    print(f"J1 pads-to-body vector=({dx:+.3f},{dy:+.3f}) mm")
    if not (dx < 0 and abs(dx) > abs(dy)):
        raise SystemExit("FAIL: J1 does not open predominantly west")

    collisions = []
    changed = set(TARGETS)
    for name in changed:
        fp = fps[name]
        for other, other_fp in fps.items():
            if other == name:
                continue
            if fp.layer == other_fp.layer and intersects(courts[name], courts[other]):
                collisions.append(f"courtyard AABB {name} x {other}")

    for back_name in ("J1", "U1"):
        through = pad_box(fps[back_name])
        for other, other_fp in fps.items():
            if other_fp.layer == "F.Cu" and intersects(through, courts[other]):
                collisions.append(f"through-pad AABB {back_name} x {other}")

    collisions = sorted(set(collisions))
    if collisions:
        print("collisions:")
        for item in collisions:
            print(f"  {item}")
        raise SystemExit("FAIL: independent AABB collision")
    print("collisions=none for changed courtyards and back-side THT pad fields")
    print("RESULT=PASS")


if __name__ == "__main__":
    main()
