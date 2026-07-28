# CP2 display iteration 3 reviewer evidence

Verdict: NEEDS CHANGES. The current F16 symbol geometry is clean, but the
new PDF acceptance layer fails two independent poisons (F17 and F18).

## Rebuild and electrical checks

- `doc_consistency_start.txt`: clean starting precondition.
- `battery_build.txt`, `display_build.txt`, and `build_exitcodes.txt`:
  committed-generator rebuilds; both boards pass their full gates.
- `display_direct_erc.txt` and `display_direct.erc.rpt`: independent display
  ERC, zero violations.
- `g8_netlist_audit.txt`: 110 goldens, exact parts, discrete-short invariant,
  complete pin narration, and targeted poisons all pass.
- `requirements_check.txt`: R1-R23, 42 checks, zero failures.
- `windows_popup_*.txt`: no new KiCad application-error event and no
  remaining KiCad process during the pass.

## F16 and gate poisons

- `poison_f16_gates.py` and `poison_f16_*.txt`: old SH coordinate tested
  separately against the analytic and PDF gates. Analytic catches exactly
  two pairs per board; the 0.5 mm PDF gate misses both pairs per board.
- `poison_pdf_{battery,display}_*_conn.*`: preserved known-bad child
  schematics, PDFs, PNGs, and 1200-DPI crops.
- `pdf_threshold_sweep.*`: 0.45 mm is clean across all 12 current child
  PDFs and catches all four poison intersections; 0.49/0.50 misses them.
- `poison_pdf_export_failure.*`: all five display PDF exports forced to
  return 97; stale artifacts were accepted and the build still exited 0.
- `current_*_usb_crop.png`: reviewer-owned current-geometry crops, clean on
  both boards.

## Geometry and sources

- `g9/`: independent 300-DPI full-page/crop geometry audit and manifest.
- `pdf_wordbox_second_opinion.*`: exact duplicate PDF objects removed;
  current GND/SHIELD intersections are zero.
- `label_body_audit_changed_sheets.txt`: zero source-native findings on both
  changed connector sheets.
- `citation_spotchecks.md`, `source_identity.txt`, and source-page renders:
  four on-file PDF checks plus exact USB4085 footprint identity.
