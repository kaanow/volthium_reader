# CP4 reviewer evidence - iteration 19

Reviewed designer commit: `cb824465d950f227b3f56d66a9e5ff4d2da96da0`.

## Preconditions

- Shared skills synchronized; kicad v0.10.0 installed from the exact
  `origin/main` blob without altering the skillz feature branch.
- Mandatory document-consistency check clean.
- Fresh Windows battery and display builds exit 0. Crosschecks cover 123/123
  and 39/39 references, plus 480/480 and 191/191 net-bound physical pads.

## Delta re-verification

- F18 is closed independently: the real `C_sense` fallback control is clean
  and a malformed top-level anchor now produces the intended finding.
- Front and back direct-layer controls classify correctly.
- Missing, malformed, and non-copper top-level layers all return boolean
  `False`, indistinguishable from a valid F.Cu footprint. Callers therefore
  silently apply front-side transforms and geometry instead of rejecting an
  unknown side.
- `_top_level_children()` uses the quote-unaware `_balanced()` for each child.
  Legal unmatched `)` or `(` inside a quoted description hides the later
  top-level layer and anchor. KiCad 10 independently accepts the temporary
  `)` case and writes a strict DRC report (rc 5, 27005 bytes).

## Placement and evidence checks

- Independent serialized-board AABB geometry and J1 B.SilkS probes pass.
- Fresh top/bottom renders and J3/J-USB plus J1/U1 crops inspected; no visual
  placement regression.
- Four on-file manufacturer-PDF citation/object-identity checks pass.
- No selected part, manifest row, SKU cell, connectivity, placement, or board
  blob changed. CP5 was not started.

## Verdict

NEEDS CHANGES: one IMPORTANT direct-child parser finding. F18 itself is
closed.
