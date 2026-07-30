"""CP3 placement-quality review: net affinity + decoupler adjacency.

Not a build gate — a review instrument. Two measurements from the same
geometry the generator uses:

1. Net spread: per-net minimum spanning tree length over its pad
   positions (the routing this placement implies). Worst offenders =
   parts placed far from their electrical neighbours.
2. Decoupler adjacency: every 2-pin C whose netlist neighbours include
   an IC supply pin — distance from the cap to that pin. The classic
   silent placement defect (cap 'near' the wrong thing).
"""
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import core
import build as B


def pad_positions():
    """{(ref, pad): (x, y)} for every bound pad."""
    out = {}
    for ref, meta in B.COMPS.items():
        if ref not in B.P:
            continue
        x, y, rot, side = B.P[ref]
        pp = core.placed_pads(meta["footprint"], x, y, rot, side)
        for pad, pos in pp.items():
            if isinstance(pos, list):
                pos = pos[0]
            out[(ref, pad)] = pos
    return out


def mst_len(points):
    if len(points) < 2:
        return 0.0
    n = len(points)
    in_tree = [False] * n
    dist = [float("inf")] * n
    dist[0] = 0.0
    total = 0.0
    for _ in range(n):
        u = min((d, i) for i, d in enumerate(dist) if not in_tree[i])[1]
        in_tree[u] = True
        total += dist[u]
        for v in range(n):
            if not in_tree[v]:
                d = math.dist(points[u], points[v])
                if d < dist[v]:
                    dist[v] = d
    return total


def main():
    pads = pad_positions()
    nets = {}
    for ref, meta in B.COMPS.items():
        for pad, net in meta["pins"].items():
            if net.startswith("unconnected") or (ref, pad) not in pads:
                continue
            nets.setdefault(net, []).append((ref, pad, pads[(ref, pad)]))

    print("== worst net spreads (MST mm; POWER/GND excluded — pours) ==")
    rows = []
    for net, members in nets.items():
        if net in ("GND", "V3V3", "V24_FUSED"):
            continue
        pts = [m[2] for m in members]
        rows.append((mst_len(pts), net, len(members)))
    for L, net, n in sorted(rows, reverse=True)[:12]:
        print(f"  {L:7.1f} mm  {net:24s} ({n} pads)")

    print("\n== decoupler adjacency (cap -> nearest same-net IC pin) ==")
    ics = {r for r, m in B.COMPS.items()
           if r.startswith(("U", "MOD", "RTC")) and r in B.P}
    caps = [r for r, m in B.COMPS.items()
            if r.startswith("C") and len(m["pins"]) == 2 and r in B.P]
    flagged = 0
    for c in sorted(caps):
        m = B.COMPS[c]
        supply = [n for n in m["pins"].values() if n != "GND"
                  and not n.startswith("unconnected")]
        if not supply:
            continue
        net = supply[0]
        cpos = pads[(c, "1")]
        best = None
        for (ref, pad), pos in pads.items():
            if ref in ics and B.COMPS[ref]["pins"].get(pad) == net:
                d = math.dist(cpos, pos)
                if best is None or d < best[0]:
                    best = (d, ref, pad)
        if best and best[0] > 6.0:
            flagged += 1
            print(f"  {c:8s} {B.COMPS[c]['value']:10s} net {net:22s} "
                  f"-> {best[1]}.{best[2]} at {best[0]:5.1f} mm")
    if not flagged:
        print("  all supply-connected caps within 6 mm of an IC pin")


if __name__ == "__main__":
    main()
