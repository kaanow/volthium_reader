# CP4 reviewer evidence - iteration 15

Reviewed designer commit: `f1c1a20194f2137493f4fa075de4d8508c6985ae`.

## Preconditions

- skillz synchronized; kicad 0.9.0 and pcb-design 0.19.0 installed byte-for-byte.
- Mandatory document consistency check clean.
- Fresh Windows display build exit 0: 43 footprints, 57 nets, 39/39 refs, 39/39 sides, 191/191 net-bound physical pads.
- Full handoff run bare and CLEAN across all four generators.
- Board SHA256 values remain `dc28b2fe36e6...` display and `448d59a276df...` battery.

## Delta re-verification

- Full oracle control clean.
- Partial refdes, wrong same-size side set, wrong same-size pad set, wrong declared mechanical set, and literal-empty poisons all fail.
- Hidden 38-of-39 visible-reference poison fails exact parse coverage.
- Empty courtyard geometry produces both courtyard and outline findings.
- New adjacent defect: a caller-declared edge connector with a markerless loaded footprint passes `gate_edge_markers()` with no findings.

## Board checks

- Strict direct DRC: 2 documented footprint mismatch warnings and 123 placement-only unconnected items; `drc.rpt`.
- Independent serialized-board geometry and J1 B.SilkS reference probes pass.
- Fresh top/bottom renders and J1/U1 plus J3/J-USB crops inspected; no visual placement regression.
- Four on-file manufacturer-PDF citation/object-identity checks pass.
- No manifest row, SKU cell, selected part, connectivity, or board blob changed; no SKU `/resolve` sweep triggered.

## Verdict

NEEDS CHANGES: one IMPORTANT gate-scope finding. F16 is closed, but the mating-plane gate still infers its expected marker set from the footprint it is judging and can certify nothing. CP5 was not started.
