# CP4 reviewer evidence - iteration 11

Reviewed designer commit: `fa2541b1fa05c686f64c481c5f8e572e2e378c2d`.

## Preconditions

- Installed skills synchronized byte-for-byte to skillz: kicad 0.8.0 and pcb-design 0.17.0; pcb-design-review 1.6.0 unchanged.
- Mandatory `doc_consistency_check.py`: exit 0, 36 manifest parts checked, no unmarked stale tokens, D32 consistent.
- Fresh Windows `build_display_pcb.py`: exit 0; 43 footprints, 57 nets; full oracle control 39 references / 39 sides / 191 of 191 net-bound pads; accepted DRC classes only.
- Full `handoff_check.py` run bare: exit 0; all four generators rebuilt; `HANDOFF: CLEAN`.
- Rebuilt board files matched their tracked HEAD blobs. SHA256 stayed `dc28b2fe36e6...` display and `448d59a276df...` battery.

## Delta re-verification

- F13 partial closure confirmed: missing pad, wrong net, and nonempty subset all fail. New empty-map poison exits 0 and certifies 0 of 191 pads; see `pcbnew_oracle_recheck.txt`.
- F14 closure confirmed: visible supersession banners are correctly placed; independent checker controls catch unmarked designer evidence, accept marked evidence, and exclude reviewer evidence; see `retracted_claim_probe.txt`.
- Side parser poison passes: a front footprint with an early B.Cu graphic remains front.
- Transform guard control passes and an empty source tree fails closed.
- Refdes body gate catches the prior geometric poisons, but literal empty board text still returns no findings; see `gate_delta_probe.txt`.

## Geometry and visual inspection

- Direct strict DRC completed: 2 documented `lib_footprint_mismatch` warnings and 123 placement-only unconnected items; report `drc.rpt`.
- Independent serialized-board AABB: changed placements land at their requested centres, J1 opens west, and changed courtyard/far-side THT-pad collisions are absent.
- J1 reference independently resolves to B.SilkS at (11.000, 19.025) mm and remains outside U1's B.Fab body.
- Fresh full top/bottom renders and crop zooms were inspected. J1/U1 and J3/J-USB labels are readable and do not overlap bodies; no new visual placement defect observed.

## Grounding

- Four on-file manufacturer-PDF citation/object-identity checks passed; see `citation_spotchecks.md`.
- No manifest row, SKU cell, selected part, connectivity, or board blob changed in the designer delta, so no SKU `/resolve` sweep was triggered.

## Verdict

NEEDS CHANGES: one IMPORTANT gate-integrity finding. Two empty-input paths still report clean, so the claimed vacuous-pass closure is incomplete. No CP5 work was started.
