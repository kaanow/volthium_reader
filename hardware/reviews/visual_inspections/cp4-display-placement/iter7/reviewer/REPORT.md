# CP4 display placement - agent-reviewer iteration 7 evidence

Reviewed commit: `0b7ed2027653954973bf4eefec2cca7b3b1597b8`.

## Preconditions

- Published and installed skill hashes match: pcb-design-review v1.6.0 and
  kicad v0.6.0.
- `doc_consistency_check.py`: exit 0.
- Fresh `build_display_pcb.py`: exit 0; 43 footprints / 57 nets; DRC classes
  `lib_footprint_mismatch` x2 and placement-only `unconnected_items` x123.
- Full `handoff_check.py`: exit 0; all four generators rebuilt and handoff was
  CLEAN with fresh artifacts, true hashes, and consistency clean.
- Direct strict KiCad PCB DRC completed with rc=5, two accepted violations and
  123 placement-only unconnected items; report is `drc.rpt`.
- `reviewer_patch_check.py`: exit 0, accepted F07 reviewer patch clean.

## F09 actual repair

The independent serialized-board probe now places J1's B.SilkS anchor at
`(11.000,19.025)` mm, outside U1's body. The fresh bottom render and targeted
crop show `J1` readable above its own body and clear of U1. The independent
placement AABB audit also remains clean.

## F09 regression-gate audit

Three independent poisons escape the new gates. First, a mutually consistent
but serializer-wrong inverse/forward pair makes `assert_refdes_roundtrip()`
return clean while the serialized anchor lands at the old bad
`(11.000,47.325)` mm point. The gate consumes in-memory overrides and its own
forward model, not the emitted board text. Second, `refdes_over_body_findings()`
returns clean when an anchor is 0.1 mm outside another body even though the
nominal 1.90 x 1.45 mm text rectangle overlaps it. Third, the body gate
explicitly skips `other == ref`, so a reference centered on its own component
body also passes despite PR-2. See the independent poison script and
transcript.

## F10 trace audit

PR-13 is now present, but its no-JTAG/CAN explanation belongs to the battery
board. The display baseline assigns no CAN pins and explicitly carries native
USB/JTAG through J-USB. J5 is termination, not debug. See `pr13_trace.md`.

## Citation and visual coverage

Four on-file manufacturer PDFs were checked directly; all selected source
claims pass. Fresh full top/bottom renders and targeted J1/U1 and J3/J-USB
crops were inspected. The actual placement is visually sound; the open items
are regression-gate completeness and scorecard factual accuracy. CP5 was not
started.
