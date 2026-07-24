# CP2 review packet — battery-side schematic (hw/cp2-schematic)

> **For agent-reviewer.** Skill: `pcb-design-review` **v1.2.0** (the user
> hands it to you — note the NEW §3 rebuild-first precondition and gates
> **G8** (wiring read-back) / **G9** (independent-geometry second opinion);
> they were written from this CP's failure history and are expected to be
> exercised here). Scope: the **battery-side** 9-sheet schematic at CP2.
> Display-side CP2 has not started.

## 1. What you are reviewing

- Branch: `hw/cp2-schematic` (pull first — you run from a separate clone).
- Source of truth: `hardware/kicad/schematic/build.py` (code-generated
  KiCad 10). **Rebuild before reviewing anything**:
  - POSIX: `cd hardware/kicad/schematic && <repo>/.venv/bin/python build.py`
  - Windows: `cd hardware\kicad\schematic && <repo>\.venv\Scripts\python build.py`
  - KiCad data roots are auto-discovered per OS (F04); non-standard installs:
    set `KICAD_SHARE` to the dir containing `symbols/` + `footprints/`
    (or `KICAD10_SYMBOL_DIR` / `KICAD10_FOOTPRINT_DIR` individually).
  — gate-failed sheets are never written, so unbuilt artifacts can be stale.
- Artifacts (after rebuild): `build/volthium_reader.pdf` (9 pages),
  `build/volthium_reader.net` (exported netlist = connectivity ground truth),
  per-sheet `.kicad_sch/.png`.
- Canonical BOM: `hardware/layout/cp1_bom.md`. Requirements:
  `hardware/layout/requirements.md` (R1–R16). Decisions: `decisions.md`;
  review items: `DESIGN_REVIEW_ITEMS.md` (DR-26, DR-30, DR-31, DR-32 are
  this CP's core). Bring-up: `docs/hardware/bringup_guide.md`.

## 2. Scope delta since the CP1 sign-off

1. Full battery-side schematic captured: power path, supervisor, USB
   maintenance, MCU, peripherals (display RS-485 + RTC + **Xanbus CAN**),
   2× isolated RS-485 battery-read channels, connectors.
2. **DR-31 Xanbus CAN read** (user-approved requirements change): TCAN332DR,
   power-gated (CAN_PWR), termination through J7 jumper, CAN_L=4/CAN_H=5 per
   LYNK II 805-0052 §4.2.1, NET-power pins NC. Datasheet on file.
3. **DR-32 programming/bring-up**: J5 = 6-pin programming header; IO0 strap
   wired as BOOT. *(As submitted at iter-1 this was a 1×6 pin strip — F01
   corrected it to the real keyed 2×3 ESP-Prog Program connector,
   EN/VDD/TXD/GND/RXD/IO0 with target-perspective TXD/RXD; see §9.)*
4. Iso sheets redrawn as signal flow (wires-first, drawn isolation barrier,
   boxed DNP annex) — connectivity held identical through the redraw.
5. Requirements register + mechanical compliance runner
   (`hardware/tools/check_requirements.py`, 29/29 PASS, poison-tested).

## 3. Evidence on record (verify, don't inherit)

- Build gate suite green: readability/glyph/title-block gates ×8 sheets;
  netlist intent==actual; **GOLDEN table** (~150 doc-derived connectivity
  contracts in build.py) clean; `[part-short]` rule clean; footprint
  existence+normalization enforced in `place()`; ERC dangling 0 /
  power-pin 0.
- Independent audits clean: `hardware/reviews/tools/label_body_audit.py`
  (0 findings ×8), `doc_consistency_check.py` (clean),
  `check_requirements.py` (29/29).
- Known gate-history this CP (why G8/G9 exist): a consistent-but-wrong
  power gate (Q5 S/D swap) passed every mechanical diff and was caught only
  by wiring read-back; the "dangling=19 ERC baseline" turned out to be real
  broken nets from missing root-uuid instance paths; six phantom footprints
  shipped past a claimed footprint check. All fixed + regression-proven —
  but treat every green gate as a claim to spot-audit, not a fact.

## 4. Reviewer asks (beyond your standard gates)

1. **G8 read-back on the four power gates** (Q10/Q11/Q5/Q_exp) and both
   comms polarities (Xanbus 4/5, battery RJ45 7/8, Cat5e 4/5) — from the
   exported netlist, against decisions/DR/vendor docs.
2. **Poison-test one golden and one requirements check** yourself.
3. Engineering pass per ENGINEERING_REVIEW.md (D17) on the NEW blocks:
   CAN (TCAN332 bias/termination/CM budget), J5/boot strapping (IO0 net
   effects at boot), the iso-sheet redraw (fig-35 fidelity: bead placement,
   cap-on-which-side-of-bead, C_stitch return).
4. Challenge premises, not just math: LYNK-II-derived Xanbus pinout
   (third-party doc — is the inference sound?), C_stitch functional-vs-
   safety call (DR-30, user-decided), bead impedance open item (DS p.17
   ~2 kΩ vs 600 Ω pick — DR-30).

## 5. Open items already known (don't re-find them)

- DR-26 §7 two-domain bench test — gates iso population (CP5).
- Bead impedance verification at BOM-lock (DR-30, logged 2026-07-23).
- 40 BOM cells at `_verify_` — pre-BOM-lock by process (D32 applies when
  MPNs are chosen).
- Bench-class requirement rows (R1/R5/R7/R10/R12 [B] parts) — CP5, staged
  in the bring-up guide.

## 6. Findings protocol

Per SOP/REVIEWER.md: numbered findings (continue the F-series), each with
severity, evidence, and the exact artifact+line; flip the semaphore to
`claude_turn` when your pass is written.

## 7 D11 visual inspection — iter 2 (designer)

Protocol: full rebuild after the iter-1 fixes, then designer eyes on every
page of `build/volthium_reader.pdf` (rendered at 300 DPI), plus high-zoom
region crops of the two sheets that changed this iteration. Evidence under
`visual_inspections/cp2-schematic/iter2/designer/` (`page-1.png` …
`page-9.png` + the crops embedded below).

**Read verdict (all 9 pages, designer, 2026-07-24): every reference, value,
pin number, pin name, and label is readable; no text/symbol/wire collisions;
junction dots unambiguous; DNP parts (iso annex, R_exp_sda/scl, and now D2)
render with explicit red DNP crosses.**

Changed-region evidence, actually read:

- **J5 (sheet_conn)** — keyed 2×3 in the verified ESP-Prog Program map:
  left column 1/3/5 = `MCU_EN`/`DBG_TXD`/`DBG_RXD`, right column 2/4/6 =
  `V3V3`/`GND`/`BOOT`:

  ![J5 ESP-Prog 2×3](visual_inspections/cp2-schematic/iter2/designer/conn_j5_espprog_crop.png)

- **D2 (sheet_periph)** — TVS footprint now valued `DNP (F03)`, drawn with
  DNP crosses; K-K on the CANH/CANL rails, A → GND; R15/J7 term bridge
  unchanged:

  ![D2 DNP](visual_inspections/cp2-schematic/iter2/designer/periph_d2_dnp_crop.png)

## 8 Reviewer findings (iteration 1)

### Review evidence

The committed generator was rebuilt before review and again after poison
testing. Final transcript: all eight sheet readability gates clean; exported
netlist intent match clean; root ERC rc=0 with 0 dangling/unconnected and 0
power-pin-not-driven. `doc_consistency_check.py` exited 0 and the requirements
runner returned 29/29 PASS.

G8 was performed from `build/volthium_reader.net`, not the drawing. Q5/Q10/
Q11/Q_exp all read back source=V3V3, distinct gated drains, and the intended
active-low control nets. J6 reads CAN_L=4/CAN_H=5; J10/J11 read A=7/B=8; J2
reads A=4/B=5. The two ADM2587E channels retain separate logic, converter,
and bus grounds; L11/L13 are the only converter-to-bus-ground ties and
C28/C38 are the only logic-to-converter-ground bridges. An independent
symbol probe reproduced all three PMOS rotations. A 96-discrete netlist scan
found zero same-net pin shorts. The full block-by-block read-back is in
`visual_inspections/cp2-schematic/iter1/reviewer/REPORT.md`.

Six golden/source groups were visually spot-checked against the on-file PDFs:
TCAN332 pp.4/5/8, NTR4171P p.1, ADM2587E pp.8/17, TPS3808 p.4, C&K 8020
pp.2/26, and ESP32-S3-WROOM p.13. The Discover 805-0052 Schneider/Xanbus
manual was independently opened at the manufacturer URL: section 4.2.1
does specify CAN_L=RJ45 4, CAN_H=RJ45 5, and no CAN ground. That third-party
inference is sound for this Xanbus interface; the pre-live-attach polarity
measurement remains an appropriate bench gate.

Poison tests were effective. A temporary false Q5 golden made the complete
build exit 2 with exactly one `[golden]` failure; a temporary false R16
requirement made the requirements runner exit 1 with exactly one failed row.
Both temporary copies were removed and the committed generator/checker were
run clean afterward.

G9 used three independent layers: the designer build gate; all eight child
sheets through `label_body_audit.py` (0 geometry findings); and reviewer eyes
on nine 300-DPI full pages plus 54 fixed-box zoom crops. No visible collision,
clipping, unreadable pin field, or ambiguous junction was found. Reviewer
evidence and hashes are under
`hardware/reviews/visual_inspections/cp2-schematic/iter1/reviewer/`.

The ADM2587E Figure-35 implementation is electrically faithful: VISOOUT caps
are on the device side of L10/L12, VISOIN caps are on the bus side, L11/L13
split converter and bus grounds, and C28/C38 return GND1 to converter GND2.
The 600-ohm-vs-about-2-kohm bead question is already logged for BOM lock and
is not duplicated here. BTN1 also passes the dry-circuit check: the netlist
uses terminals 1-2 and the C&K p.2 function table makes that pair open at
rest/closed momentarily; p.26 qualifies B contacts for dry-circuit service.

### Finding F01 — BLOCKER — `build.py:1195-1206`, `requirements.md:R8`

**Issue**: J5 is not an ESP-Prog Program connector despite every repo contract
calling it the "exact ESP-Prog order." The exported netlist confirms the
drawn 1x6 header is 1=EN, 2=VDD, 3=target TXD, 4=target RXD, 5=IO0, 6=GND.
Espressif's Program interface is a keyed 2x3 connector with 1=ESP_EN, 2=VDD,
3=ESP_TXD, 4=GND, 5=ESP_RXD, 6=ESP_IO0. A standard ribbon cannot mate to the
1x6 footprint; if adapted pin-for-pin, it puts GND/IO0/UART on the wrong pins
and connects TX-to-TX rather than programmer TX to target RX.

**Evidence**: `hardware/kicad/schematic/build.py:1195-1206` and
`:2118-2123`; `hardware/tools/check_requirements.py:117-122`;
`hardware/layout/requirements.md:24`; `hardware/layout/cp1_bom.md:177`;
`docs/hardware/bringup_guide.md:29-32,90`; exported-netlist read-back in the
reviewer `REPORT.md`. Manufacturer source:
https://docs.espressif.com/projects/esp-dev-kits/en/latest/other/esp-prog/user_guide.html
and its Program-interface/reference section (DC3-6P keyed connector).

**Suggested fix**: either (preferred) draw a keyed 2x3 ESP-Prog-compatible
header and map target nets 1=MCU_EN, 2=V3V3, 3=DBG_RXD, 4=GND,
5=DBG_TXD, 6=BOOT, or explicitly make J5 a generic flying-lead header and
remove every direct-ribbon/"exact order"/auto-program claim. Update the
goldens, R8/R9 runner, BOM, and bring-up pin numbers from the manufacturer
contract, then poison the corrected R8 check.

### Finding F02 — BLOCKER — `cp2_schematic_review.md:D11 evidence`

**Issue**: The packet has no `D11 visual inspection — iter 1` section and no
designer-owned embedded screenshots. A scripted readability claim without
that section is not a valid D11 sign-off under the binding reviewer protocol.

**Evidence**: this packet ended at section 6 before this reviewer append;
`hardware/reviews/REVIEWER.md:221-229` explicitly makes a missing D11 section
a finding. No CP2 designer visual-inspection artifacts exist in the committed
tree.

**Suggested fix**: after fixing F01 and rebuilding, add the required designer
D11 section with full-page and dense-region screenshots from the final PDF,
and record the manual 100%-zoom reading verdict.

- **Agent-reviewer visual evidence**:
  `hardware/reviews/visual_inspections/cp2-schematic/iter1/reviewer/battery_p1_full_300dpi.png`
  through `battery_p9_full_300dpi.png`, and each page's
  `battery_pN_eye_crop_01.png` through `_06.png`; reviewer verdict is visually
  clean, but it does not substitute for designer sign-off.

### Finding F03 — IMPORTANT — `cp1_bom.md:D2`, `manifest.md:remaining gaps`

**Issue**: The populated-by-default NUP2105L does not form a coordinated
protection bracket around U7. U7 permits only +/-14 V at CANH/CANL, while the
NUP2105L does not start breakdown until 26.2-32 V and is specified to clamp
as high as 40 V at 5 A / 44 V at 8 A. It therefore cannot guarantee the bus
pins stay below U7 absolute maximum. The exact NUP2105L PDF is also absent
from `hardware/datasheets/`, despite the manifest claiming no chosen-MPN
gaps; the current consistency checker only checks rows that already exist.

**Evidence**: `hardware/layout/cp1_bom.md:188,190`;
`hardware/kicad/schematic/build.py:930`;
`hardware/datasheets/TCAN332.pdf` p.5 (reviewer render
`source_spotchecks/TCAN332_p5.png`); `hardware/datasheets/manifest.md:52,82`.
Manufacturer NUP2105L electrical table:
https://www.onsemi.com/download/data-sheet/pdf/nup2105l-d.pdf.

**Suggested fix**: since TCAN332 already guarantees 12 kV IEC contact ESD,
the cleanest resolution is likely to omit/DNP D2 and stop claiming external
coordination. Otherwise select a low-capacitance CAN protector whose
guaranteed clamp stays below +/-14 V at the declared threat current. Store
and manifest the exact PDF, and extend `doc_consistency_check.py` to compare
all chosen BOM MPNs against manifest coverage rather than only validating
present rows.

### Finding F04 — IMPORTANT — `build.py:42,334,1933`

**Issue**: The mandatory rebuild is not reproducible from a clean Windows
clone. The generator hardcodes the macOS KiCad symbol and footprint roots and
reads UTF-8 artifacts without declaring an encoding. On this reviewer host,
the packet command required an OS-specific interpreter path, temporary
filesystem junctions that impersonated `/Applications/...`, and
`PYTHONUTF8=1`; without those workarounds it failed before the review gates.

**Evidence**: `hardware/kicad/schematic/build.py:42,334,1933`; packet section
1's only rebuild command is the Unix `.venv/bin/python` form. The final clean
build did pass after provisioning those external workarounds, so this is a
reproducibility defect rather than an allegation against the final netlist.

**Suggested fix**: discover KiCad data roots from a documented environment
variable/KiCad installation, allow an explicit override, and use
`encoding="utf-8"` for source/netlist reads. Document both POSIX and Windows
venv commands and make a clean-clone rebuild part of CI.

**REVIEW COMPLETE**: NEEDS CHANGES — 2 blockers, 2 important. (See findings F01, F02, F03, F04.)

## 9 Designer responses (iteration 1) — 2026-07-24

### F01 — RESOLVED (accepted, with one premise correction)

Accepted in full: the 1×6 was not an ESP-Prog connector and every "exact
order" claim was wrong. J5 is now the **keyed 2×3** (Würth 61200621621
WR-BHD, DK 732-5394-ND 15.6k stock / Mouser 710-61200621621 18.1k, API
2026-07-24; drawing on file, sha 6474a7ec48fc — standard IDC odd/even
numbering, 1:1 with the ribbon).

**One premise in the suggested remap was itself inverted** — it proposed
3=DBG_RXD / 5=DBG_TXD, which would have recreated the TX-to-TX fault one
level deeper. The Program-connector names are **target-perspective**:
in the ESP-Prog reference schematic (SCH V2.1, fetched to
`hardware/datasheets/ESP-Prog_SCH_V2.1.pdf`, sha ab1f074c7b6c) the FT2232
routes **FT_TXD →0R(R20)→ ESP_RXD0** and **FT_RXD →0R(R21)→ ESP_TXD0** —
the programmer does the UART cross internally, and its J3/J5 headers put
ESP_TXD0 (= the **target's** TXD) on pin 3. Implemented map, exported-netlist
verified: **1=MCU_EN, 2=V3V3, 3=DBG_TXD (module TXD0), 4=GND,
5=DBG_RXD (module RXD0), 6=BOOT**. Please G8 this against the SCH trace —
it is the load-bearing fact of the fix.

Propagated: goldens re-pinned (poison-tested: one flipped J5 golden → build
exit 2, exactly one `[golden]` failure); R8 runner re-pinned (poisoned pin-4
→ exit 1, one FAIL); `requirements.md` R8, BOM row (new MPN + SKUs),
`bringup_guide.md` recovery-drill pins (jumper 6→4, blip 1),
DR-32 defect record, manifest rows (ESP-Prog SCH + Würth drawing), and two
new SUPERSEDED registry rows guard the retired order-string and 1×6 forms.
CP3 note recorded: key-notch orientation set at placement so ribbon pin 1 =
our pin 1.

### F02 — RESOLVED

§7 above: designer D11 section with the full-page set
(`iter2/designer/page-1..9.png`, 300 DPI, all nine read by the designer
after the final rebuild) and embedded high-zoom crops of the two changed
regions. Read verdict recorded there.

### F03 — RESOLVED (accepted; DNP + gate extension)

Accepted: the coordination claim was false. Re-verified from the on-file
TCAN332 PDF p.5 (V(BUS) abs-max ±14 V; bus-pin ESD ±25 kV HBM / ±12 kV IEC
contact) and the **onsemi** NUP2105L datasheet, now fetched and manifested
(sha bf93369469d4; note: the bare "NUP2105L" MPN resolves to a **Diotec
second-source PDF** at DigiKey — the orderable NUP2105LT1G query returns the
onsemi doc): V_RWM 24 V, V_BR 26.2–32 V, V_C to 40/44 V @5/8 A. The
coordination window is empty by construction (standing off ±12 V CM ⇒
clamping ≫14 V), which is the same impossibility already ruled on for the
RS-485 ports (F44/SM712). Same resolution applied: **D2 → DNP** (schematic
dnp attribute + red cross + `DNP (F03)` value; BOM qty 0, footprint kept as
a fit-on-evidence option), protection = TCAN332 on-chip ESD, no coordination
claimed. DR-31 records the reasoning incl. the unprotectable-24 V-miswire
caveat (mitigated by the Stage-5 pre-attach polarity check).

Checker extended as asked: new `check_bom_mpn_coverage()` in
`doc_consistency_check.py` — every canonical-BOM row with a chosen DK SKU
must be covered by a manifest row or an explicit `NO_DATASHEET_OK`
jellybean exemption (append-only, reason required). Poison-tested (fake
chosen-SKU row → `[bom-cov]` finding, exit 1). Closing the latent gaps it
exposed, three more docs were fetched + manifested: TDK MPZ2012 catalog
(bead — its |Z| curve also puts data on the DR-30 bead question: S601A
~600 Ω at the 150–200 MHz peak, no MPZ2012 reaches the ADM's ~2 kΩ
guidance; S601A-vs-S102A stays a BOM-lock call), KEMET C1009 HV C0G
(C_stitch 1 kV claim), Würth 61200621621 (J5).

### F04 — RESOLVED (code + docs; CI deferred with rationale)

`build.py` now discovers the KiCad data root per OS (macOS / Windows
`C:/Program Files/KiCad/10.0/share/kicad` / Linux `/usr/share/kicad`) with
env overrides — `KICAD_SHARE`, or `KICAD10_SYMBOL_DIR` /
`KICAD10_FOOTPRINT_DIR` individually — and every artifact read/write
declares `encoding="utf-8"` (netlist read, ERC report read, project/table/
root writes). §1 above documents both POSIX and Windows rebuild commands.
**CI deferred**: this qty-1 repo has no CI infrastructure, and installing
KiCad in a runner is a heavier build than the project warrants; the §3
rebuild-first precondition (review skill v1.2.0) makes every review pass a
clean-clone rebuild on a second OS, which is the check CI would buy. If a
third platform enters the loop, revisit. Flag if you disagree — happy to
stand up a KiCad container job instead.
