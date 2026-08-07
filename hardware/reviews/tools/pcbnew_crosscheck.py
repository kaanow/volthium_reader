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
    want = list(exp.get("components", []))
    if board_refs and not want:
        bad.append(f"the board KiCad loaded carries {len(board_refs)} "
                   "footprints but the expected object names no components "
                   "— an empty expectation cannot certify a populated board")
    missing = [r for r in want if r not in board_refs]
    if missing:
        bad.append(f"expected components absent from the board: "
                   f"{sorted(missing)[:12]}")
    if want and len(exp.get("side", {})) != len(want):
        bad.append(f"side map covers {len(exp.get('side', {}))} of "
                   f"{len(want)} expected components — a partial map cannot "
                   "certify the whole board")
    if want and not exp.get("refdes"):
        bad.append(f"no reference positions supplied for {len(want)} "
                   "expected components — nothing would be checked")

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

    # An oracle must not score a pad it never found as agreement (CP4 F13).
    # Absence is a FAILURE, every pad carrying the number is checked (a
    # footprint may repeat one), and the compared count is asserted against
    # the expected map so a truncated map cannot pass quietly.
    expected_pads = exp.get("pads", {})
    compared = 0
    located = set()
    for key, net in expected_pads.items():
        ref, pad = key.split("/", 1)
        fp = b.FindFootprintByReference(ref)
        if fp is None:
            bad.append(f"{ref}.{pad}: our model expects this pad but the "
                       "footprint is absent from the board KiCad loaded")
            continue
        matches = [p_ for p_ in fp.Pads() if p_.GetNumber() == pad]
        if not matches:
            bad.append(f"{ref}.{pad}: our model expects this pad but KiCad's "
                       f"board has no pad numbered {pad!r} on {ref}")
            continue
        located.add(key)
        for p_ in matches:
            compared += 1
            got = p_.GetNetname()
            if got != net:
                bad.append(
                    f"{ref}.{pad} net: our model {net!r}, KiCad {got!r}")

    if len(located) != len(expected_pads):
        bad.append(f"located only {len(located)} of {len(expected_pads)} "
                   "expected pads")

    # Coverage, not just agreement: if our expected map omits net-bound pads
    # that KiCad can see, the oracle is checking a subset while reporting
    # confidence. This is the invariant that the first-four-pins truncation
    # violated while printing "clean".
    board_bound = 0
    for fp in b.GetFootprints():
        for p_ in fp.Pads():
            if p_.GetNetname():
                board_bound += 1
    # Unconditional and EXACT. The truthiness guard that used to sit here
    # is precisely what let an empty map through (F15).
    if compared != board_bound:
        bad.append(f"coverage: KiCad sees {board_bound} net-bound pads but "
                   f"our expected map compared {compared} — the oracle is "
                   "judging a different set than the board actually has")

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
