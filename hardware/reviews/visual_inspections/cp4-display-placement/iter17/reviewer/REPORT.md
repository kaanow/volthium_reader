# CP4 reviewer evidence - iteration 17

Reviewed designer commit: `300b959c61e439297dc67fec80af472f8483cb39`.

## Preconditions

- Shared skills synchronized; pcb-design v0.20.0 installed byte-for-byte.
- Mandatory document-consistency check clean.
- Fresh Windows battery and display builds exit 0. Crosschecks cover 123/123
  and 39/39 references, plus 480/480 and 191/191 net-bound physical pads.
- Full four-generator handoff check exits 0 and reports CLEAN.

## Delta re-verification

- F17 is closed independently: current battery/display controls are clean;
  expected-marker disappearance, unexpected-marker appearance, and same-size
  J1-for-J3 scope substitution all fail.
- The new typed-through-hole/no-drill invariant fails its poison while a
  drill-less SMD negative control stays clean.
- The adjacent `assert_refdes_roundtrip()` repair is incomplete. Its anchor
  regex accepts a descendant Reference-property `(at ...)` when the top-level
  footprint anchor is malformed. With real library-fallback ref `C_sense`,
  `sel is None` then silently skips the footprint and the one-footprint poison
  returns no finding. See `gate_recheck.py` and `gate_recheck.txt`.

## Placement and evidence checks

- Independent serialized-board AABB geometry and J1 B.SilkS probes pass.
- Fresh top/bottom renders and J3/J-USB plus J1/U1 crops inspected; no visual
  placement regression.
- Four on-file manufacturer-PDF citation/object-identity checks pass.
- No selected part, manifest row, SKU cell, connectivity, placement, or board
  blob changed. CP5 was not started.

## Verdict

NEEDS CHANGES: one IMPORTANT defect in the adjacent round-trip gate repair.
F17 itself is closed.
