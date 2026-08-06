# CP4 display placement - agent-reviewer iteration 5 evidence

Reviewed commit: `f4ea4f1`. Reviewer host: Windows 11, native KiCad 10 CLI.

## Preconditions and gate results

- Published/installed skills synchronized: kicad v0.6.0, pcb-design v0.13.0,
  pcb-design-review v1.6.0.
- `doc_consistency_check.py`: exit 0 at review start.
- Fresh `build_display_pcb.py`: exit 0; 43 footprints / 57 nets; accepted DRC
  categories were `lib_footprint_mismatch` x2 and placement-only
  `unconnected_items` x123.
- Full `handoff_check.py`: exit 0; all four generators rebuilt, deterministic
  artifacts matched HEAD, consistency passed, RPA clean.
- `reviewer_patch_check.py`: exit 0. Patch `8038741` is accepted by designer
  authorship, in scope, and zero-delta.

## Re-review of iteration-3 findings

- F06: C6 and U-ESD are separate BOM rows again; the pre-existing TVS2 extra
  column is folded into Notes. Independent temporary-copy poisons show the new
  table-shape gate rejects both prior row mergers and accepts the control.
- F07: accepted correctly. Both text subprocess helpers specify UTF-8; the
  remaining `head_blob()` subprocess is intentionally binary.
- F08: the revised AST guard catches external self-negation of X and Y forms,
  including all four independent poisons in `checker_reprobes.txt`.
- F05: the DRC count is corrected and a D13 table now exists, but its visual
  claims and criterion coverage are not yet complete; see findings below.

## Independent geometry and visual inspection

The serialized-board AABB second opinion still passes: all four changed centers
have 0.000000 mm error, J1 opens west, and no changed-part/THT collision exists.
See `independent_geometry.txt`.

Fresh `render_top.png`, `render_bottom.png`, eight quadrant crops, and targeted
J1/USB zooms were inspected. Front-side placement remains readable. On the back,
U1 is readable but J1 has no visible refdes. The independent serialized-board
probe places J1's B.SilkS text anchor at `(11.000,47.325)` mm, inside U1's B.Fab
body `(6.205,43.750)..(17.805,52.250)` mm. The physical U1 therefore covers the
J1 reference after assembly, exactly as the bottom render shows.

The generator source explains the displacement: `auto_refdes()` selects a
board-space point, converts it to local coordinates, then negates `dx` for a
back-side part at `core.py:954-956`, despite the established back transform
negating Y. Its post-write label gate checks label adjacency, not label-vs-body,
so the generated build stays green.

## Citation quota

Three on-file manufacturer documents were checked directly. Results are in
`citation_spotchecks.md`; all checked claims pass.

## Verdict basis

The functional placement, connectivity, artifact-freshness, BOM-shape, RPA,
and external transform-ownership repairs pass. CP4 cannot yet approve because
D13 PR-1/PR-2 falsely mark the hidden J1 reference PASS, and the mandatory
PR-13 row is absent. Routing remains CP5 scope and was not started.
