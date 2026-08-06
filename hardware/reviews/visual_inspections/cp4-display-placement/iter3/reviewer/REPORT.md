# CP4 display placement - agent-reviewer iteration 3 evidence

Reviewed design commit: `1a357eaa75c69198713498393e31f8a1cf7ad70e`.
Reviewer host: Windows 11; KiCad 10 CLI through the repository discovery helper.

## Rebuild and enforcement preconditions

- `doc_consistency_check.py`: exit 0 at review start.
- Mandatory fresh `build_display_pcb.py`: exit 0; 43 footprints, 57 nets;
  accepted DRC categories were `lib_footprint_mismatch` x2 and placement-only
  `unconnected_items` x123.
- Full pre-patch `handoff_check.py`: all four generators exited 0, then the RPA
  checker crashed while decoding UTF-8 git history with Windows cp1252.
- Reviewer patch `80387419563e6dcc2a6baf6006e0461db10ca22f` supplies explicit
  UTF-8 subprocess decoding. Direct RPA and the complete handoff then exited 0
  before the patch commit. The patch is now intentionally PENDING until the
  designer signs off by finding id and SHA.

Before/after host transcripts are in `rpa_utf8_windows_before.txt` and
`rpa_utf8_windows_after.txt`.

## Independent geometry (G9)

`independent_geometry.py` reads the serialized `.kicad_pcb` through kiutils and
uses conservative axis-aligned boxes. It does not import the generator or its
geometry helpers. Results in `independent_geometry.txt`:

- J1, U1, U2, and R2 courtyard centers equal their requested centers with
  0.000000 mm error.
- J1 signal-pads-to-body vector is `(-7.950, +0.000)` mm: west.
- No changed-part courtyard or back-side THT-pad AABB collision was found.

The other two required geometry layers also ran: the designer's analytic gates
and DRC passed in the fresh build, and the reviewer inspected `render_top.png`,
`render_bottom.png`, all eight quadrant crops, and `doc_envelopes.png` at crop
zoom. No placement or mechanical-envelope collision is visible. The tall-part
labels show J1 13.6 mm back, U1 11.0 mm back, J-USB 9.3 mm front, J3 9.1 mm
front, J2 7.6 mm front, and BTN1-3 15.0 mm front.

## Changed facts and citation spot-checks

Live SKU resolution is recorded in `sku_resolve.txt`; both corrected cells are
exact matches to the selected MPNs.

Four direct checks against the on-file manufacturer PDFs:

1. `USB4115_drawing.pdf`, SHA256 `8e3448f72b96...`, p.1 title block identifies
   GCT USB4115 as a vertical SMT receptacle with H=9.30 mm.
2. `TS02_tactile.pdf`, SHA256 `fe5026f60ec3...`, p.1 defines `150` as 15.0 mm,
   `160` as 160 gf, and `SCR` as short crimped; p.2 shows the SCR recommended
   layout as 6.5 x 4.5 mm, four 1.0 mm holes, and 0.7 +/-0.1 mm terminals.
3. `B8B-PH-K-S.pdf`, SHA256 `447624f4f2f7...`, p.1 states 8 mm top-entry mated
   height; p.3 lists S8B-PH-K-S as the side-entry family and dimensions its body
   height at 7.6 mm.
4. `615008145521.pdf`, SHA256 `da03e4ed6257...`, p.1 identifies Wurth order
   code 615008145521 as horizontal, shielded, tab-down 8P8C and dimensions the
   height at 13.60 +/-0.25 mm.

Object identities and the cited values match the packet's changed mechanical
claims.

## Findings surfaced by the pass

- The mandatory D13 scorecard remains explicitly deferred in packet section 7.
  Packet section 5 also still says one footprint mismatch while the fresh DRC
  and section 4.5 establish two. Mechanical evidence improved, but the required
  binary sign-off was not completed.
- `cp1_bom.md:290` places the complete C6 component row after the J2 notes on
  the same physical Markdown line. Line 314 does the same to U-ESD after J-USB.
  The row-scoped consistency check exits 0 on both malformed rows.
- The new single-transform guard was poison-tested. It catches an external
  `x = -x`, but misses an external `y = -y`, the actual project convention; see
  `transform_guard_poison.txt`.
- The Windows enforcement repair is valid on this host but remains an
  unaccepted RPA patch until designer review.

G8 schematic wiring read-back is not reopened by this placement-only delta;
netlist/board parity, orientation, and pad binding ran in the fresh build.
Routing-quality gates remain CP5 scope.
