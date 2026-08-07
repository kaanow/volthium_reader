# CP4 reviewer evidence - iteration 23

Reviewed designer commit: `dd47624b5cb8a9e97979778af10138f65de9db59`.
Reviewer host patch: `042dcd277d1f11b2c75c108b474e8d0cb49aa15b`.

## Preconditions

- Shared skills synchronized; kicad v0.11.0 and pcb-design v0.21.0 installed
  from the exact `origin/main` blobs.
- Mandatory document-consistency check clean.
- Fresh Windows battery and display builds exit 0. Both production mutation
  batteries reject 13/13 submitted cases and complete netlist crosschecks.

## Delta re-verification

- F19 is closed: direct F.Cu/B.Cu, unknown-layer, malformed-layer, and quoted
  unmatched-parenthesis controls all behave correctly.
- The committed evidence runner initially exits 1 on Windows because it
  hardcodes the designer's macOS checkout path. Standalone RPA patch
  `042dcd2` derives the repository root from `__file__`; the full Windows run
  then exits 0 in 442 seconds, including both controls, gate removals,
  liveness, and restored controls. Designer acceptance is pending.
- Independent mutations outside the submitted list change a component Value
  property and remove all four Edge.Cuts objects. Both pass every in-write
  text/readback/pcbnew gate. Strict DRC adds `invalid_outline` only for the
  outline case; the Value case is exactly identical to control DRC. Value
  identity is therefore an end-to-end fail-open gap, not merely proof scope.

## Placement and evidence checks

- Independent serialized-board AABB geometry and J1 B.SilkS probes pass.
- Fresh top/bottom renders and J3/J-USB plus J1/U1 crops inspected; no visual
  placement regression.
- Four on-file manufacturer-PDF citation/object-identity checks pass.
- No selected part, manifest row, SKU cell, connectivity, placement, or board
  blob changed. CP5 was not started.

## Verdict

NEEDS CHANGES: two IMPORTANT items: accept/review the F20 host patch and add
emitted Value identity plus its mutation (F21). F19 is closed.
