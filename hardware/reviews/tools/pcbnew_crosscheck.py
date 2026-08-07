#!/usr/bin/env python3
"""Independent readback of a generated board using KiCad's OWN engine.

Every analytic gate in pcb/core.py reads the board with the same
assumptions that wrote it, so a wrong transform agrees with itself and
stays green. That correlation is exactly how CP4 F01 (parts 18 mm off
their stated centres) and F09 (a designator emitted inside a neighbouring
body) both survived until an independent probe broke the tie.

This runs under KiCad's bundled Python — a different implementation, by a
different author — and re-derives the facts our gates assert:
  * every footprint's side and position
  * every reference designator's board position
  * pad -> net bindings

Usage: pcbnew_crosscheck.py <board.kicad_pcb> <expected.json>
where expected.json is emitted by the generator. Exit 1 on disagreement.
Best-effort by design: if KiCad's Python cannot be located the caller
should report SKIPPED rather than PASS — an oracle that silently did not
run is worse than none.
"""
import json
import sys

TOL_MM = 0.01


def main():
    board_path, expected_path = sys.argv[1], sys.argv[2]
    import pcbnew
    b = pcbnew.LoadBoard(board_path)
    exp = json.load(open(expected_path))
    bad = []

    # An EMPTY expectation must never certify a populated board (CP4 F15).
    # The previous cut guarded its coverage test with `if expected_pads`,
    # so an empty object exited 0 while reporting "0 of 191 net-bound pads"
    # as clean — the guard itself created the vacuous pass. Expectations are
    # therefore anchored to the caller's component set, not inferred from
    # whatever happened to be in the file being judged.
    board_refs = {fp.GetReference() for fp in b.GetFootprints()}
    want = set(exp.get("components", []))
    mech = set(exp.get("mechanical", []))
    if board_refs and not want:
        bad.append(f"the board KiCad loaded carries {len(board_refs)} "
                   "footprints but the expected object names no components "
                   "— an empty expectation cannot certify a populated board")

    # IDENTITY, not cardinality (CP4 F16). A 1-of-39 map and a same-size map
    # with one member swapped both satisfied the previous count tests while
    # judging the wrong set. Counts below are diagnostics inside the
    # message, never the test.
    def same_set(label, got, expect):
        got, expect = set(got), set(expect)
        if got == expect:
            return
        miss, extra = sorted(expect - got), sorted(got - expect)
        bad.append(f"{label}: set mismatch — {len(got)} present vs "
                   f"{len(expect)} expected; missing {miss[:10]}, "
                   f"unexpected {extra[:10]}")

    same_set("board footprints", board_refs, want | mech)
    same_set("refdes map", exp.get("refdes", {}), want)
    same_set("side map", exp.get("side", {}), want)

    for ref, e in exp.get("refdes", {}).items():
        fp = b.FindFootprintByReference(ref)
        if fp is None:
            bad.append(f"{ref}: absent from the board KiCad loaded")
            continue
        p = fp.Reference().GetPosition()
        gx, gy = p.x / 1e6, p.y / 1e6
        if abs(gx - e[0]) > TOL_MM or abs(gy - e[1]) > TOL_MM:
            bad.append(f"{ref} refdes: our model ({e[0]:.3f},{e[1]:.3f}) vs "
                       f"KiCad ({gx:.3f},{gy:.3f})")

    for ref, side in exp.get("side", {}).items():
        fp = b.FindFootprintByReference(ref)
        if fp is None:
            bad.append(f"{ref}: side expected but the footprint is absent "
                       "from the board KiCad loaded")
            continue
        got = "B" if fp.IsFlipped() else "F"
        if got != side:
            bad.append(f"{ref} side: our model {side}, KiCad {got}")

    # Pads by IDENTITY (CP4 F16). Build KiCad's net-bound
    # (ref, pad-number) -> [netname, ...] multimap and require its KEY SET to
    # equal the expected key set. Counting physical occurrences let a
    # same-size map pass after swapping a required net-bound pad for an
    # unrelated unbound one: the total stayed 191, so the count agreed while
    # the sets did not.
    expected_pads = exp.get("pads", {})
    board_map = {}
    for fp in b.GetFootprints():
        for p_ in fp.Pads():
            net = p_.GetNetname()
            if net:
                board_map.setdefault(
                    f"{fp.GetReference()}/{p_.GetNumber()}", []).append(net)

    same_set("net-bound pads", expected_pads, board_map)

    # An expected pad with an empty net name asserts nothing (F16).
    blank = sorted(k for k, v in expected_pads.items() if not v)
    if blank:
        bad.append(f"expected pads carry an EMPTY net name, which asserts "
                   f"nothing: {blank[:10]}")

    compared = 0
    for key, net in expected_pads.items():
        got_list = board_map.get(key)
        if got_list is None:
            ref, pad = key.split("/", 1)
            fp = b.FindFootprintByReference(ref)
            why = ("the footprint is absent from the board KiCad loaded"
                   if fp is None else
                   f"KiCad's board has no NET-BOUND pad numbered {pad!r} "
                   f"on {ref}")
            bad.append(f"{key}: our model expects this pad but {why}")
            continue
        # every PHYSICAL occurrence must match, not just the first
        for got in got_list:
            compared += 1
            if got != net:
                bad.append(f"{key} net: our model {net!r}, KiCad {got!r}")

    board_bound = sum(len(v) for v in board_map.values())
    if compared != board_bound:
        bad.append(f"coverage: KiCad sees {board_bound} net-bound pad "
                   f"occurrences but our expected map compared {compared} — "
                   "the oracle is judging a different set than the board has")

    if bad:
        print(f"CROSSCHECK: FAIL ({len(bad)})")
        for x in bad[:30]:
            print("  ", x)
        return 1
    n = len(exp.get("refdes", {}))
    print(f"CROSSCHECK: clean — {n} references, {len(exp.get('side', {}))} "
          f"sides, {compared} pad-nets (of {board_bound} net-bound pads "
          "KiCad sees) agree with KiCad's own engine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
