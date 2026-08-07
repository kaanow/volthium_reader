# CP4 display placement - agent-reviewer iteration 9 evidence

Reviewed commit: `24deb4ae8bf6d5f348816f34fde2287fb7b92c86`.

## Preconditions and accepted repairs

- Published/installed skill hashes match: kicad v0.7.0, pcb-design v0.14.0,
  pcb-design-review v1.6.0.
- `doc_consistency_check.py`: exit 0.
- Fresh `build_display_pcb.py`: exit 0; emitted-text gates clean; pcbnew
  cross-check reports 39 references, 39 sides, and 97 pad-nets; DRC classes
  remain `lib_footprint_mismatch` x2 and `unconnected_items` x123.
- Bare `handoff_check.py`: exit 0; all four generators rebuilt and handoff was
  CLEAN with fresh artifacts, true hashes, and consistency clean.
- Direct strict KiCad PCB DRC completed with rc=5 and the documented two
  accepted footprint violations plus 123 placement-only unconnected items.
- `reviewer_patch_check.py`: exit 0; accepted F07 reviewer patch clean.
- Independent emitted-text recheck: clean control; moved emitted anchor,
  text-box edge overlap, own-body overlap, and empty-selection poisons all
  caught; MOD1 body independently parses as 18.00 x 25.50 mm.
- F12 is corrected: packet PR-13 now describes J3 ESP-Prog recovery and J-USB
  native USB Serial/JTAG without battery CAN or J5 claims.

## Open findings

The new pcbnew oracle does not fail when an expected pad is missing. A wrong
net on existing J1.1 fails as a positive control, while nonexistent
J1/NO_SUCH_PAD passes and is counted as one agreement. The committed board has
191 net-bound pads according to pcbnew, but the generator supplies only 97 to
the oracle because it slices each component to its first four pins.

The committed iteration-8 refdes poison transcript also ends with the now-
retracted claim that J-USB/TVS2 were real live defects fixed by manual
overrides. The current generator explicitly has an empty `MANUAL_REFDES` and
the packet says those were parser artifacts. The evidence file must be marked
superseded or replaced; the consistency checker currently misses it.

## Visual and source coverage

Fresh full top/bottom renders and targeted J1/U1 and J3/J-USB crops were
inspected; placement remains visually sound. Independent serialized-board AABB
geometry remains clean. Four on-file manufacturer-PDF claims were checked and
pass. Connectivity and selected parts did not change; CP5 was not started.
