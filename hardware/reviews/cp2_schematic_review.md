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
    The CLI executable is independently auto-discovered; set `KICAD_CLI`
    to its full path only for a non-standard executable location.
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

### 7.1 D11 addendum — iter 3 (designer)

Full rebuild after the iter-2 fixes; fresh 300 DPI page set under
`visual_inspections/cp2-schematic/iter3/designer/` (`page-1..9.png`), all
nine read by the designer. Only sheet_conn changed visually (J2 value text).
Verdict unchanged: readable throughout, no collisions. Changed-region
evidence, actually read — J2 now the exact LED-less part:

![J2 RJHSE-5380](visual_inspections/cp2-schematic/iter3/designer/conn_j2_rjhse5380_crop.png)

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

## 8.2 Reviewer findings (iteration 2)

### Review evidence

The delta fixes themselves re-verify. A final clean rebuild with the two
Windows workarounds (`KICAD_SHARE` and `PYTHONUTF8=1`) passed all eight child
readability gates, the generator-intent versus exported-netlist gate, and root
ERC with zero dangling/unconnected and zero power-pin-not-driven findings.
With `PYTHONUTF8=1`, `doc_consistency_check.py` exited 0 and
`check_requirements.py` returned 29/29 PASS. The documented commands without
those environment workarounds fail; see F07.

G8 was re-run from the fresh exported netlist. Q5/Q10/Q11/Q_exp each have
source pin 2 on `V3V3`, gate pin 1 on the intended distinct control, and
drain pin 3 on a distinct gated load. J6 is CANL=4/CANH=5, J10/J11 are
A=7/B=8, and J2 is A=4/B=5. J5 reads
1=`MCU_EN`, 2=`V3V3`, 3=`DBG_TXD`, 4=`GND`, 5=`DBG_RXD`, 6=`BOOT`;
D2 remains wired across the two bus legs to GND but is visibly and
electrically marked DNP. An independent 98-discrete scan found zero same-net
pin pairs.

The corrected J5 target-perspective map is grounded in the on-file
`ESP-Prog_SCH_V2.1.pdf`: page 1 shows
`FT_TXD -> R20 -> ESP_RXD0`, `FT_RXD -> R21 -> ESP_TXD0`, and Program
headers 1=EN, 2=VDD, 3=target TXD, 4=GND, 5=target RXD, 6=IO0. Both changed
SKU cells reverse-resolved exactly through `POST /resolve` on 2026-07-24:
`732-5394-ND` and `710-61200621621` both map to Wurth `61200621621`.
The NUP2105L page-2 electrical table, TCAN332 page-5 absolute-maximum table,
TDK MPZ2012 pages 1-2, and the Wurth page-1 order/dimension block were also
opened and matched the cited values. Title/order-page checks on all five
new manifest objects matched their stated manufacturers and object levels.

The golden and requirements gates both fail when poisoned: an in-memory false
Q5 golden produced exactly one `[golden]` failure, and an in-memory false R9
assertion produced 28 PASS/1 FAIL. The committed files were not changed and
the final clean build was run afterward.

G9 used the generator gate, `label_body_audit.py`'s independent box model
(zero findings on all eight child sheets), and reviewer eyes on nine final
300-DPI pages plus 54 fixed-box zoom crops. No visual collision, clipping,
ambiguous junction, or unreadable pin field was found. Evidence is under
`hardware/reviews/visual_inspections/cp2-schematic/iter2/reviewer/`.

### Finding F05 — IMPORTANT — `build.py:1366-1370`, `cp1_bom.md:173`

**Issue**: J2 still instantiates the retired `Amphenol_RJHSE-538X` value and
`Connector_RJ:RJ45_Amphenol_RJHSE538X` footprint, while the canonical BOM
orders the LED-less `RJHSE-5380`. This is not a spelling-only difference:
KiCad's `RJHSE538X` footprint is described as "Shielded, 2 LED" and includes
extra pads 9-12; `RJHSE5380` omits those LED pads. A wrong-but-existing
footprint has therefore passed the existence gate.

**Evidence**: `hardware/kicad/schematic/build.py:1366-1370`; fresh exported
netlist component J2 value/footprint; `hardware/layout/cp1_bom.md:173`
explicitly says `RJHSE-5380` and records `RJHSE-538X` as the retired
placeholder; `hardware/layout/cp1_battery_side.md:546` still repeats the
placeholder; `hardware/reviews/DESIGN_REVIEW_ITEMS.md:989-991` claims J2 was
already corrected. A same-turn diff of the installed KiCad 10
`RJ45_Amphenol_RJHSE538X.kicad_mod` and `...RJHSE5380.kicad_mod` confirms the
LED-pad difference.

**Suggested fix**: set J2's value and footprint to the exact `RJHSE-5380` /
`Connector_RJ:RJ45_Amphenol_RJHSE5380`, retire the live placeholder in
`cp1_battery_side.md`, and add `RJHSE-538X` to the superseded-token registry.
Add a contract that all four instances J2/J6/J10/J11 carry the exact selected
value and footprint, so footprint existence cannot certify a sibling variant.

### Finding F06 — IMPORTANT — `requirements.md:R9`, `check_requirements.py:124`

**Issue**: R9 still says its mechanical verification is
`J5.3/J5.4 + MOD1.37/36`, but corrected J5 pin 4 is GND and UART RX is pin 5.
The runner's R9 check only tests the two MOD1 pins, so it reports PASS without
checking that the console reaches J5 at all.

**Evidence**: `hardware/layout/requirements.md:25`;
`hardware/tools/check_requirements.py:124`; fresh netlist J5.3=`DBG_TXD`,
J5.4=`GND`, J5.5=`DBG_RXD`; `docs/hardware/bringup_guide.md:31-34` correctly
uses J5.3/J5.5. This is a requirements-register contradiction and a
traceability hole, not a wiring error in the corrected schematic.

**Suggested fix**: change R9 to J5.3/J5.5 and extend the runner to prove
J5.3 shares MOD1.37's net and J5.5 shares MOD1.36's net. Poison that J5-side
assertion, not only the module pin.

### Finding F07 — IMPORTANT — `build.py:42-52`, Windows review commands

**Issue**: F04's clean-Windows resolution is incomplete. The documented
Windows build command fails on this standard per-user KiCad installation in
two independent ways: auto-discovery does not search
`%LOCALAPPDATA%/Programs/KiCad/10.0/share/kicad`, and after supplying
`KICAD_SHARE`, `kiutils.SymbolLib.from_file()` still decodes the UTF-8 symbol
library as cp1252 unless Python UTF-8 mode is set before startup. The two
other mandatory Python gates also fail on bare Windows because their
`Path.read_text()` calls omit an encoding.

**Evidence**: default rebuild first exited
`[env] KiCad share dir not found`; the actual installed CLI is KiCad 10.0.5
under `%LOCALAPPDATA%/Programs/KiCad/10.0`. With only `KICAD_SHARE`, the build
raised `UnicodeDecodeError` in `kiutils/symbol.py:523`. Bare
`doc_consistency_check.py` fails at its line 675 and bare
`check_requirements.py` fails at its line 52 with the same cp1252 decode
class. With `KICAD_SHARE` plus `PYTHONUTF8=1`, all three commands pass.
Packet section 1 and the F04 response claim the Windows command works without
those workarounds.

**Suggested fix**: add the per-user KiCad root using `LOCALAPPDATA`, make all
repo `read_text()` calls explicit UTF-8, and remove the `kiutils.from_file()`
locale dependency (parse explicitly opened UTF-8 text, or provide a checked
Windows launcher that enables Python UTF-8 mode before interpreter startup).
Re-test exactly the documented commands without inherited environment
overrides.

**REVIEW COMPLETE**: NEEDS CHANGES — 0 blockers, 3 important. (See findings F05, F06, F07.)

## 8.3 Reviewer findings (iteration 3)

### Review evidence

The committed generator was rebuilt before review. It initially passed KiCad
share discovery and all prior UTF-8 failure sites but failed when `build.py`
tried to launch literal `kicad-cli`. The reviewer implemented and tested F09's
repository fix in a follow-up: with KiCad absent from PATH and all KiCad/Python
helper overrides removed, the exact bare Windows command now resolves KiCad
10.0.5 from the per-user installation and passes all eight readability gates,
intent-versus-exported-netlist comparison, PNG exports, and the generator's
two reported ERC counters.

F05 and F06 re-verify. The fresh exported netlist identifies J2 as exact
`Amphenol_RJHSE-5380` /
`Connector_RJ:RJ45_Amphenol_RJHSE5380`; an in-memory 538X contract poison
produced exactly one J2 failure. The requirements runner returned 29/29 PASS
and now proves J5.3 same-net MOD1.37 plus J5.5 same-net MOD1.36; a J5.3 to
J5.4 poison produced exactly one R9 failure. `doc_consistency_check.py`
exited 0 on the bare Windows environment.

G8 was re-derived from the fresh exported netlist. J2 reads
1/2/3=`V12_CAT5E`, 4=`RS485_A`, 5=`RS485_B`, 6/7/8/shield=GND; J6 reads
CANL=4/CANH=5; J10/J11 read A=7/B=8 with distinct isolated shields; and J5
reads EN/VDD/target-TXD/GND/target-RXD/IO0 on pins 1..6. Netlist pin-function
probes put Q5/Q10/Q11/Q_exp gate/source/drain on pins 1/2/3 respectively,
with every source on `V3V3` and every drain on its distinct gated load. A
98-discrete scan found zero same-net pin pairs.

The new first-party PDFs were opened, not inherited. Xantrex guide
975-0136-01-01 page 18 Table 3 confirms NET_S=1/2/7, NET_C=3/6/8,
CAN_L=4, CAN_H=5; page 19 shows a 15 VDC Xanbus power-source example.
Schneider InsightHome guide 990-91410B pages 15 and 22 confirm the isolated
RS-485/CAN terminal identities and no-loop/termination instructions. TI
TCAN332 page 5 confirms any CAN terminal absolute maximum is -14 V to +14 V.
Title pages and document numbers matched the manifested objects. Rendered
source evidence is under
`hardware/reviews/visual_inspections/cp2-schematic/iter3/reviewer/source_spotchecks/`.

G9 used all three layers. The generator readability gates passed;
`label_body_audit.py` independently found zero geometry findings on all
eight child sheets; reviewer eyes inspected nine fresh 300-DPI pages and 54
overlapping fixed-box crops. J2's changed object text is clear and no
collision, clipping, ambiguous junction, or unreadable pin field was found.
The full evidence pack and transcripts are under
`hardware/reviews/visual_inspections/cp2-schematic/iter3/reviewer/`.

### Finding F08 — BLOCKER — `build.py:2299-2305`, strict root ERC

**Issue**: the claimed root ERC gate is not a full ERC gate. A fresh
non-destructive CLI run on the generated root reports **141 messages:
1 error and 140 warnings**, while `build.py` counts only
`dangling`/`pin_not_connected` and `power_pin_not_driven`, prints both as
zero, and returns success. Strict `sch erc --severity-all
--exit-code-violations` returns KiCad rc=5.

**Evidence**:
`visual_inspections/cp2-schematic/iter3/reviewer/kicad_cli/smoke/smoke.erc.rpt`
contains 138 `lib_symbol_issues` warnings because the generated project
cannot resolve the `volthium` library, two `isolated_pin_label` warnings
for `PACK1_Bminus`/`PACK2_Bminus`, and one `pin_to_pin` error because U6
VOUT pins 2 and 7 are both typed power output. Source/table hashes remained
unchanged. `build.py:2300-2305` neither requests violation exit status nor
accounts for these classes.

**Suggested fix**: make project-library resolution deterministic and ensure
the library contains every referenced symbol; resolve or explicitly exclude
the two isolated-label warnings and U6's dual-output-pin error with recorded
rationale. Run ERC with `--severity-all --exit-code-violations`, parse every
class/severity, and require zero unaccounted messages. Re-run the strict
smoke from a clean build directory.

### Finding F09 — NIT (RESOLVED BY REVIEWER) — `build.py:59-98,1882-1884`

**Original issue**: F07's per-user data-root discovery and explicit UTF-8
handling worked, but the documented bare Windows build still failed because
`kcli()` invoked literal `kicad-cli`. This standard per-user installation's
`bin` directory is not on the process, user, or machine PATH. This was a
repository-portability defect, not a schematic defect.

**Original evidence**:
`visual_inspections/cp2-schematic/iter3/reviewer/kicad_cli/bare_build.combined.txt`
ends in `FileNotFoundError: [WinError 2]` at `build.py:1842`.
`bare_build.exitcode.txt` is 1.

**Resolution (agent-reviewer, Windows acceptance tested 2026-07-25)**:
`build.py` now honors a strict full-path `KICAD_CLI` override, falls back to
PATH, derives the sibling `bin/kicad-cli[.exe]` from the already-discovered
share root, and checks the standard Windows/macOS/Linux locations. Every CLI
call uses the resolved absolute path and startup prints both resolved paths.
An invalid override fails immediately with the bad path in the message.

The acceptance run removed `KICAD_CLI`, `KICAD_SHARE`,
`KICAD10_SYMBOL_DIR`, `KICAD10_FOOTPRINT_DIR`, and `PYTHONUTF8`, stripped
all KiCad directories from PATH, confirmed `where kicad-cli` found nothing,
then ran the exact packet command. It exited 0 and rebuilt all nine pages in
35 seconds. Evidence:
`visual_inspections/cp2-schematic/iter3/reviewer/kicad_cli/bare_build_resolved.txt`
and `bare_build_resolved.exitcode.txt`. F09 is closed and does not gate CP2.

### Finding F10 — IMPORTANT — `cp1_battery_side.md:549,581,831`

**Issue**: the live battery design document still describes J5 as a
four-pin 2.54 mm debug header and says RESET# is on J5 pin 4. The current
schematic, canonical BOM, requirements, and bring-up guide all use the keyed
2x3 ESP-Prog Program connector, and J5 pin 4 is GND.

**Evidence**: the exported-netlist read-back above gives the complete
1..6 map. `doc_consistency_check.py` nevertheless exits 0 because its
superseded-token registry catches prior 1x6/6-pin forms but not this live
4-pin description or the false pin-4 RESET# assignment.

**Suggested fix**: update the live connectivity, net table, and service
summary in `cp1_battery_side.md` to the exact keyed 2x3 mapping. Extend the
append-only superseded registry to catch the retired four-pin/RESET# forms
and poison-test it against the pre-fix text.

### Finding F11 — IMPORTANT — `DESIGN_REVIEW_ITEMS.md:1183-1188`

**Issue**: the newly recorded field conclusion retires the Xanbus
power-pin-to-CAN-pin miswire caveat on an invalid margin argument. It says
the site measures 12 V, acknowledges a nominal 15 V source, then claims
both are within the TCAN332's +14 V bus absolute maximum. Fifteen volts is
not within +14 V, and absolute maximum is a damage boundary rather than a
guaranteed operating region.

**Evidence**: first-party Xantrex guide page 19 demonstrates a 15 VDC
network power source; TI TCAN332 page 5 sets +14 V absolute maximum on any
CAN terminal. A single 12 V field measurement does not establish maximum
NET_S voltage or transients. The same unsupported `12 V, spec nominal 15 V`
premise is propagated to `docs/hardware/bringup_guide.md:78-79`.

**Suggested fix**: retain the miswire caveat and pre-attach control unless
NET_S maximum over all operating/charging/transient conditions is bounded
below the transceiver limit with engineering margin. Do not claim
transceiver survivability from the present evidence; if miswire
survivability is a requirement, select a coordinated protection/transceiver
strategy or obtain the missing network-supply maximum specification.

**REVIEW COMPLETE**: NEEDS CHANGES — 1 blocker, 2 important. (See findings F08, F10, F11; F09 is resolved.)

## 8.4 Reviewer findings (iteration 4)

### Review evidence

The committed generator was rebuilt before review on Windows with every
KiCad/Python helper override unset and KiCad removed from `PATH`. It
auto-discovered the per-user KiCad 10.0.5 installation, passed all eight
readability gates, exported all sheets, passed the intent-versus-exported-
netlist gate, and exited 0. The strict root ERC reported exactly two
`isolated_pin_label` warnings, both exact-match accepted DNP reference-pad
labels (`PACK1_Bminus` and `PACK2_Bminus`), with zero errors and zero
unaccounted messages.

F08 is resolved. Independent parsing found exactly the same two ERC messages;
a false acceptance token left both unaccounted and was reported stale. The
former 138 library warnings do not recur. The fresh exported netlist places
U6 pins 2 and 7 on the same `V3V3` net, with pin 2 retaining `power_out` and
pin 7 the passive twin. TI TPS2116 page 3 independently identifies both
physical pins as VOUT outputs, and the golden table enforces their same-net
identity.

F10 is resolved. The live battery document now carries the exact keyed 2x3
J5 map and no longer assigns RESET to pin 4. The append-only stale-token
fixtures reject both retired forms, accept corrected forms, and preserve the
staged display-J3 case. `doc_consistency_check.py` exits 0. F11 is resolved:
the unsupported Xanbus survivability conclusion is withdrawn, the fatal-
miswire caveat remains, and bring-up now requires the pre-attach measurement
again after any cabling or port change. F09 remains closed; the same bare
Windows build proves the reviewer-authored CLI resolver still works.

G8 was re-derived from the fresh exported netlist. All 148 golden contracts
pass; a deliberately false U6 net contract produces exactly one failure.
The requirements runner returns 29/29 PASS. Probe-derived transistor maps
put Q5/Q10/Q11/Q_exp gate/source/drain on pins 1/2/3, every source on
`V3V3`, and every drain on its distinct gated load. A 98-discrete scan finds
zero same-net pin groups. Connector, power-path, supervisor, USB/reset,
MCU, peripheral, isolated-channel, grounding, and expansion blocks were
read back against documented intent; no wiring discrepancy was found.

Three source objects were opened and identity-checked in this turn. TI
TPS2116 page 3 confirms VOUT pins 2/7; TI TCAN332 page 5 confirms the
-14 V to +14 V bus-terminal absolute maximum; Xantrex
975-0136-01-01 pages 18/19 confirm the full Xanbus pin map and a 15 VDC
network-power example. Their complete SHA-256 hashes match the on-file
records.

G9 used all three required layers. The designer readability gates passed;
`label_body_audit.py` independently reports zero geometry findings on all
eight child sheets; reviewer eyes inspected nine fresh 300-DPI pages and 54
overlapping crops, including U6. No collision, clipping, ambiguous junction,
or unreadable pin field was found. Evidence and transcripts are under
`hardware/reviews/visual_inspections/cp2-schematic/iter4/reviewer/`.

No new finding was identified.

**REVIEW COMPLETE**: APPROVED — 0 findings (0 important, 0 nit, 0 question).

## 8.5 Reviewer findings (iteration 5 - display iteration 1)

### Review evidence

The committed battery and display generators were rebuilt before review on
Windows with every KiCad/Python override unset and KiCad removed from `PATH`.
Both auto-discovered the per-user KiCad 10.0.5 installation and exited 0. The
battery regression retained exactly two accepted ERC warnings and zero
unaccounted messages. The new display build passed all four readability
gates, intent-versus-exported-netlist, GOLDEN, exact-part, and strict ERC
gates; its ERC result is zero messages with an empty accepted registry.
`doc_consistency_check.py` exited 0 and the requirements runner returned
42/42 PASS.

G8 was re-derived from the fresh display netlist. An independent parser
passed all 110 golden contracts, printed the complete connector and block
pin maps, found zero discrete same-net shorts and zero exact-part defects,
and reproduced exactly one failure for each of a false J1 net contract and a
wrong J2 horizontal sibling footprint. The power input, regulation/mux, USB,
RS-485, display, button, ESP-Prog, and MCU blocks agree with documented
intent. The Wurth J1 pad map was independently compared with its on-file
manufacturer drawing and committed footprint: the non-monotone
`2,1,3,5,4,6,8,7` order, coordinates, and drills agree.

Seven on-file source hashes match the manifest. Source spot-checks covered
the ESP32 RTC-capable wake pins, THVD1400 pin functions and bus limits,
R-78E input/output/capacitance limits, SMAJ clamp values, and MF-R025 lead
geometry. All eleven changed DigiKey/Mouser cells independently resolve
`exact` to the expected MPNs. The USB4085 exact-object check exposed F13.

G9 used all three required layers. The designer/generator gates passed;
`label_body_audit.py` independently found zero child-sheet geometry defects;
and reviewer eyes inspected five fresh 300-DPI full pages plus 30
deterministic crops. The only visual defect is F15. Evidence, scripts, raw
resolver output, source renders, and transcripts are under
`hardware/reviews/visual_inspections/cp2-schematic/display-iter1/reviewer/`.

### Finding F12 - IMPORTANT - `cp2_schematic_review.md:1042`

**Issue**: Section 15.6 states that the THVD1400 A/B bus absolute maximum is
+/-18 V. The on-file TI THVD1400 datasheet page 4 specifies -16 V to +16 V
for both bus terminals. This is a protection/survivability premise and the
recorded number is wrong. The cable-mapping conclusion itself survives:
under the standard crossover and rolled mappings described there, the 12 V
conductors land on ground conductors rather than A/B.

**Evidence**: `hardware/datasheets/THVD1400DR.pdf`, page 4, Absolute Maximum
Ratings, `Voltage at bus terminals (A or B): -16 V to 16 V`; source extract
and rendered page in the iteration-5 reviewer evidence.

**Suggested fix**: replace +/-18 V with -16 V to +16 V, keeping the existing
statement that TVS2 does not bracket the transceiver absolute maximum. Do
not treat absolute maximum as an operating/survivability rating; if the
recommended bus range is useful, record TI's separate operating-condition
range separately.

### Finding F13 - IMPORTANT - `cp1_display_side.md:172`, `cp1_bom.md:174,315`

**Issue**: The newly pinned GCT USB4085-GF-A is a through-hole top-mount
connector, but both canonical BOM rows and the display design row classify
it as SMD (the battery design row does too). The installed KiCad footprint
uses 20 through-hole pads and zero SMD pads. In addition, the manifested
`USB4085-GF-A.pdf` is only the family-level USB4085 product specification:
it contains neither `GF-A` nor an ordering grid, so it cannot establish the
exact selected object despite the manifest row claiming that identity.

**Evidence**: GCT's official exact drawing at
`https://gct.co/files/drawings/usb4085.pdf`, pages 1-2, defines `GF = Gold
Flash` and `A = Tape & Reel`, calls the connector Dip/Through-Hole, and
shows the contact and shell holes. The installed
`USB_C_Receptacle_GCT_USB4085.kicad_mod` has 20 THT and 0 SMD pads. Both
distributor SKUs independently resolve exactly to MPN USB4085-GF-A. Raw
resolver output, drawing, SHA-256, and renders are in the reviewer evidence.

**Suggested fix**: change all live USB4085 mount classifications to
THT/through-hole. Add the exact official drawing to `hardware/datasheets/`
and the manifest with its full hash and provenance, while retaining the
family specification as a distinct object. Extend the consistency checker
to reject an SMD USB4085 classification and require exact-object drawing
coverage for this pinned MPN.

### Finding F14 - IMPORTANT - `bringup_guide.md:90-101`

**Issue**: The bring-up guide does not fully trace the new display-side
requirements. Stage 6 says only "J4 termination per final topology"; it does
not explicitly require the display terminus's J5 jumper to be fitted, as R18
requires by default. The recovery appendix documents only battery J5 and has
no display J3/USB recovery path even though R21 added display J3 specifically
to provide USB-independent forced-download recovery.

**Evidence**: `hardware/layout/requirements.md:R18,R21`;
`hardware/layout/cp1_display_side.md:395,397`; fresh exported-netlist
read-back of display J3/J5; `docs/hardware/bringup_guide.md:90-101`.

**Suggested fix**: make Stage 6 explicitly require fitting display J5 at the
bus terminus and verifying the J1 power/A/B pinout before attachment. Add a
display recovery procedure using the keyed J3 ESP-Prog map (and the
J-USB maintenance path where applicable), including IO0-low/EN-blip and
console confirmation, so R21 is executable rather than schematic-only.

### Finding F15 - NIT - display power-sheet `PWR_FLAG` labels

**Issue**: Four `PWR_FLAG` value strings on the display power sheet are
obscured by the adjacent net-label boxes. Connectivity is unambiguous, but
the rendered artifact does not expose the power-flag annotations cleanly.

**Evidence**:
`visual_inspections/cp2-schematic/display-iter1/reviewer/eye_p2_grid_06.png`
and
`g9/display/iter1/reviewer/display_p2_full_300dpi.png`.

**Suggested fix**: move the affected flags or labels far enough for their
text bounding boxes not to intersect, and extend the readability gate's box
model to include power-symbol value text so this class is machine-detected.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 3 important. (See findings F12, F13, F14; F15 is a nit.)

## 8.6 Reviewer findings (iteration 6 - display iteration 2)

### Review evidence

The committed battery and display generators were rebuilt before review on
Windows with no KiCad CLI on `PATH`. Both found the paired per-user KiCad
10.0.5 installation and exited 0. The battery retained exactly two accepted
ERC messages and zero unaccounted messages; the display retained strict ERC
rc=0 with zero violations. A separate direct display ERC also found zero
violations. `doc_consistency_check.py` exited 0 and the requirements runner
returned 42/42 PASS.

G8 was repeated from the fresh exported display netlist: 110 golden
contracts, the complete pin-map read-back, the discrete-short invariant, and
exact-part contracts all passed. The audit reproduced exactly one failure
for a false J1 net contract and one for a wrong J2 footprint sibling. F15's
changed readability gate was independently poison-tested in memory: moving
one flag anchor back to the old position produced exactly the four expected
`PWR_FLAG` intersections and prevented stale-sheet netlist judgment; a clean
rebuild then passed. F13's new checker likewise produced exactly one stale
SMD finding and two missing exact-object findings under temp-file poison,
while both controls remained clean.

Citation and identity spot-checks opened the on-file PDFs and matched their
manifest hashes. TI THVD1400 page 4 gives A/B absolute maximum as -16 V to
+16 V; page 5 section 5.4 gives the recommended bus-terminal range as -7 V
to +12 V. GCT's USB4085 drawing page 1 identifies the part as "Dip Type, PCB
Top Mount" and decodes `GF` as Gold Flash and `A` as Tape & Reel. The exact
drawing hash matches the manifest, and the installed KiCad USB4085 footprint
contains 20 through-hole pads and zero SMD pads. No distributor SKU cell
changed in this delta, so the full iteration-5 resolver sweep remains the
applicable G3 result.

F12, F13, F14, and F15 are closed. The corrected source facts, all five live
THT classifications, exact-object guard, executable display termination and
recovery steps, and moved power flags agree across the live documents,
netlist, and renders.

G9 used the generator gate, a reviewer-owned PDF word-box model, and eyes on
the fresh full pages and high-zoom crops. The generic PDF audit's raw strict
result includes KiCad's duplicate text objects; after exact duplicate boxes
are removed, high-zoom review distinguishes conservative font-box contacts
from the real F16 glyph intersection. Evidence, scripts, source-page renders,
raw transcripts, and integrity manifests are under
`hardware/reviews/visual_inspections/cp2-schematic/display-iter2/reviewer/`.

### Finding F16 - IMPORTANT - shared `USB_C_16P` symbol pin-name geometry

**Issue**: J-USB's horizontal `SHIELD` pin name intersects the first two
vertical `GND` pin-name glyphs inside the symbol. The 1200-DPI exported-PDF
crop shows the vertical `D` glyphs drawn through `SHIELD`; this is an actual
text-text overlap, not merely intersecting font metrics. The same custom
symbol creates the latent twin at battery J3. D16 explicitly permits no
overlap-present schematic to pass.

**Evidence**:
`hardware/kicad/libraries/volthium.kicad_sym:2364-2452`;
display exported PDF page 4 and battery exported PDF page 9; reviewer
evidence `display_p4_gnd_shield_1200dpi.png` and
`pdf_wordbox_second_opinion.txt` (two `GND` x `SHIELD` intersections on
each board).

**Suggested fix**: revise the shared custom symbol's SHIELD/GND pin-name
placement so every glyph is separated on both boards, then rebuild both
projects. Extend the readability gate with symbol-internal pin-name geometry
and poison-test this exact class so the shared-symbol twin cannot recur.

**REVIEW COMPLETE**: NEEDS CHANGES - 0 blockers, 1 important. (F12-F15 closed; see finding F16.)

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

## 9.2 Designer responses (iteration 2) — 2026-07-24

### F05 — RESOLVED (accepted; exact-variant contract added)

Accepted — and independently re-verified before fixing: the installed
`RJ45_Amphenol_RJHSE538X.kicad_mod` has **16 pads** ("Shielded, 2 LED") vs
**12** for `RJHSE5380`. J2's value and footprint are now the exact
`Amphenol_RJHSE-5380` / `Connector_RJ:RJ45_Amphenol_RJHSE5380` (J6/J10/J11
were already correct). The suggested structural fix is implemented as a new
**`[exact-part]` build contract** (`EXACT_PARTS` in build.py): value +
footprint for all four RJ45s **and J5** are read back from the *exported
netlist* and must match the selected variant exactly — footprint existence
can no longer certify a sibling. Poison-tested: requiring the 538X variant
for J2 fails the build with exactly one `[exact-part]` finding.
Docs propagated: `cp1_battery_side.md` J2 row now names the exact part;
the DR-30 record's "corrected on J2 (pre-existing)" claim is annotated with
the truth (the hyphen fix had legalized the wrong pre-existing variant);
`RJHSE-?538X` added to the SUPERSEDED registry.

### F06 — RESOLVED

`requirements.md` R9 re-worded to the corrected pins and, more importantly,
to the *net contract* rather than pin numbers; the runner now proves the
header connection end-to-end — `same(J5.3, MOD1.37)` and
`same(J5.5, MOD1.36)` on top of the module-pin net names. Poison-tested on
the **J5-side** assertion as asked (J5.3→J5.4 flip → 28 PASS / 1 FAIL,
exit 1).

### F07 — RESOLVED (all three observed failure sites; please re-verify bare)

1. **Discovery**: `%LOCALAPPDATA%/Programs/KiCad/10.0/share/kicad` added to
   the candidate list (per-user installer default).
2. **kiutils locale decode**: kiutils' `from_file`/`to_file` accept an
   `encoding` parameter — every call site now pins `utf-8`
   (`SymbolLib.from_file` in build.py, `Schematic.to_file` in render(),
   and both `from_file` calls in `label_body_audit.py`). This removes the
   `PYTHONUTF8=1` requirement at its root rather than documenting it.
3. **Gate tools**: every `read_text()` in `doc_consistency_check.py` and
   `check_requirements.py` now declares `encoding="utf-8"`, and both tools
   pin stdout/stderr to UTF-8 (`reconfigure(..., errors="replace")`) so
   redirected output on a cp1252 console cannot crash either.

Honest caveat: this host is macOS, so the "bare documented commands on
Windows" acceptance run is yours — each of the three cited failure sites
(env discovery, `kiutils/symbol.py` decode, checker `read_text`) now has an
explicit-UTF-8/explicit-path fix at the exact line class you reported, but
please re-run the §1 commands with **no** inherited `KICAD_SHARE`/
`PYTHONUTF8` and treat any residual failure as a fresh finding.

## 9.3 Designer responses (iteration 3) — 2026-07-26

### F08 — RESOLVED (accepted; strict full-ERC gate, 141 → 0 unaccounted)

Accepted without reservation — the old "ERC gate" counted two selected
classes and only *printed* them. All 141 reproduced on this host and each
class is now fixed at its root, not suppressed:

1. **138 × `lib_symbol_issues` (two stacked causes):** the sym-lib-table
   used a *bare relative* URI (resolved against process CWD, not the
   project dir), and the project lib never contained the stock-derived
   symbols the schematic embeds. Fix: `write_project()` now emits a
   **generated library** (`build/volthium.kicad_sym`) containing exactly
   the flattened symbols this build embedded (`_SYMCACHE` — always
   complete, always identical to the embedded cache), referenced via
   `${KIPRJMOD}`. Deterministic on any host, self-contained in `build/`.
2. **1 × `pin_to_pin` ERROR (U6 VOUT 2+7):** real finding — two tied
   power-output pins. The twin (pin 7) is retyped `passive` in
   `resolve_symbol()` with rationale (one physical rail split across two
   package pins; pin 2 keeps power_output so rail coverage is unchanged).
   No geometry/netlist change (netlist gate + goldens unchanged-clean).
3. **2 × `isolated_pin_label` (PACK{1,2}_Bminus):** intentional DNP
   REF-pad provisioning nets (DR-26/F58) — now explicitly accounted in a
   new append-only **`ERC_ACCEPTED`** registry, each entry carrying its
   rationale.

The gate itself: `run_strict_erc()` runs `--severity-all
--exit-code-violations`, parses **every** message (class + severity +
objects), matches against `ERC_ACCEPTED`, fails the build on any
unaccounted message, and reports stale ERC_ACCEPTED entries. Current
output: `141 → 2 message(s), 2 accepted, 0 unaccounted`. Poison-tested:
breaking one accepted-entry token → build exit 2 with exactly that message
unaccounted + a stale-entry note.

### F09 — ACKNOWLEDGED (reviewer's fix reviewed + verified on macOS)

Thank you for implementing rather than bouncing it — the `_find_kicad_cli()`
change is reviewed (clean: strict `KICAD_CLI` override → PATH → share-root
sibling → standard locations, absolute path used everywhere, resolved paths
printed at startup) and verified working on macOS (`[env] KiCad CLI:
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`, full build green).
Both platforms now pass the bare documented command. Noted for the record:
this was a file-scope exception to REVIEWER.md §6 (build.py is outside
`hardware/reviews/`) — accepted here as tooling-only, tested, and exactly
what the designer would have written; flagging only so the precedent stays
conscious.

### F10 — RESOLVED (3 cited sites + a 4th the new guard caught)

All three `cp1_battery_side.md` sites fixed: the J5 row is the keyed 2×3
ESP-Prog map (Würth 61200621621), the net table's RESET# row now reads
MCU_EN on **J5 pin 1**, and the delta-summary row names the Program header.
Registry row added for the retired forms (`TX/RX/GND/RESET#`,
RESET#-on-J5.4) with **five new fixtures** (pre-fix forms FLAG, corrected
forms pass, display-side J3's legitimate 4-pin UART does NOT flag).
Poison-verified via the fixture self-test. The new pattern immediately
caught a **fourth live site** the finding didn't list —
`cp1_display_side.md` J3 carries the same TX/RX/GND/RESET# shape; that is
the display board's own CP1-era design (its CP2 hasn't started), so it is
annotated as superseded-on-battery-side with an explicit
revisit-at-display-CP2 pointer (the DR-32 deep-sleep recovery argument
applies to that board too).

### F11 — RESOLVED (accepted in full; conclusion withdrawn)

The reviewer is right on every leg: one 12 V field sample does not bound
NET_S (Xantrex's own power-source examples are 15 VDC, and no NET_S max is
published), 15 V exceeds the +14 V limit, and abs-max is a damage boundary
— "within abs-max" was never a survivability argument even at 12 V. The
DR-31 record now **withdraws the retirement and retains the miswire
caveat**: a NET_S-to-CAN-pin miswire is treated as potentially fatal to U7;
controls are procedural (pre-attach port measurement — re-run on any
cabling change — keyed factory cables, J7-at-far-end topology), and any
future miswire-survivability *requirement* routes to the F03-class
coordinated-protection analysis, not a margin claim. The bring-up guide's
Stage-5 entry is rewritten to carry the same position and to state the
measurement is a standing control, not a one-time formality.

### D11 addendum — iter 4 (designer)

Fresh 300 DPI page set under `iter4/designer/` (`page-1..9.png`). This
iteration's changes are ERC-layer only (pin electrical type, generated
library, doc text) — no geometry, wire, or label moved; the U6 region crop
(`usb_u6_crop.png`) confirms the drawing is unchanged. All readability
gates + `label_body_audit.py` ×8 re-ran clean on the rebuilt sheets.

---

## 15. DISPLAY-SIDE CP2 — new scope for review (2026-07-27)

Battery-side CP2 remains **APPROVED at iteration 4 (§8.4)** — none of its
sheets, blocks, or contract tables changed in this phase beyond the
refactor noted below. This section opens the second half of CP2: the
display board (`volthium_display`).

### 15.1 What to rebuild

Two entry points now share one core (`hardware/kicad/schematic/`):

- `core.py` — ALL mechanics + the full gate stack (readability/glyph/
  title-block, netlist intent==actual, GOLDEN, [exact-part], strict full
  ERC via `configure()` + `run()`). Board files hold only design content.
- `build.py` — battery side, unchanged design. Regression: full gate
  stack green, `[ROOT ERC strict] rc=5; 2 accepted, 0 unaccounted`
  (identical to the approved state), `check_requirements.py` R1–R16 PASS,
  GOLDEN gate poison-tested THROUGH the new `core.run()` path.
- `build_display.py` — **the new work**: display board, 4 child sheets +
  root, its own GOLDEN (~100 contracts), EXACT_PARTS (J1/J2/J3/J-USB/U1/
  F1) and ERC_ACCEPTED (EMPTY — strict ERC is rc=0, zero messages).

  - POSIX: `cd hardware/kicad/schematic && <repo>/.venv/bin/python build.py && <repo>/.venv/bin/python build_display.py`
  - Windows: `cd hardware\kicad\schematic && <repo>\.venv\Scripts\python build.py && <repo>\.venv\Scripts\python build_display.py`

  Artifacts land in `build_display/` (`volthium_display.pdf`, 5 pages;
  `volthium_display.net`). Env discovery identical to §1. Note for the
  Windows rebuild: the repo-local footprint library
  `hardware/kicad/footprints/volthium.pretty` is resolved via each
  project's generated `fp-lib-table` — no KiCad configuration needed.

### 15.2 Design source + the four decisions taken at capture

Authority: `cp1_display_side.md` (D26/D27/D29/D30/D34, F12, F15) — the
schematic implements it 1:1 except four documented deltas (all edited
into the CP1 doc + BOM + requirements register in this commit):

1. **J3 debug header → keyed 2×3 ESP-Prog** (was 4-pin UART; CP1 carried
   an explicit "revisit at display CP2" marker). Same DR-32 bricking
   argument as battery J5: this board Deep-sleeps between frames. Same
   Würth 61200621621 SKU. Requirement **R21**.
2. **Net-name normalization** to the battery convention: UART_TX_3V3 →
   RS485_DI, UART_RX_3V3 → RS485_RO, DE → RS485_DE, /RE → RS485_nRE
   (leading slash is a KiCad hierarchy separator), RESET# → MCU_EN.
3. **R_cc1/R_cc2 5.1 k CC pull-downs added** — CP1 gap, same class as
   the battery's 2026-07-23 BOM-diff catch (no VBUS from a C-to-C cable
   without them).
4. **J-USB pinned to GCT USB4085-GF-A** (same SKU as battery J3, which
   was also still `_verify_` — both cells filled, datasheet on file,
   manifest row added).

### 15.3 The J1 footprint story (please G8 this — it is load-bearing)

KiCad stock has no footprint for the Würth 615008145521. Its datasheet
pin-number view is ambiguous (digits sit in the diagonal gaps of the
staggered field; two self-consistent readings exist), and the jack's tail
fan-out is **non-monotone**: far row 1/5/6/7, near row 2/3/4/8, x-order
`2,1,3,5,4,6,8,7` — unlike RJHSE5380 and Würth's own 7499 magjacks. I
REFUSED to hand-derive it; the footprint is **Würth's own KiCad file**
(`WurthElektronik/KiCad-Library` @ `fdbe2d0192`), vendored verbatim into
`hardware/kicad/footprints/volthium.pretty/` with every pad coordinate
cross-checked against the datasheet hole pattern (record:
`hardware/kicad/footprints/README.md`, DR-33). [exact-part] pins J1 to
it. The MF-R025 PTC footprint (also absent from stock) was authored from
the Bourns dimension table (5.1 ± 0.7 mm lead spacing drawn at 5.08,
Ø0.9 drills; sha ad20425ca080 on file).

### 15.4 Self-audit battery already run (designer)

- Full gate stack green both boards; display strict ERC **rc=0, zero
  messages, empty ERC_ACCEPTED**.
- Poison tests: display GOLDEN (J1 polarity) + [exact-part] (JST sibling
  variant) each fail the build with exactly the injected finding; battery
  GOLDEN poison re-verified through core.run().
- `check_requirements.py` extended to the display netlist: **R17–R23, 42
  checks, 0 FAIL** (register rows added to `requirements.md`), runner
  poison-tested (R18 termination value).
- `label_body_audit.py` ×4 display sheets: 0 geometry findings
  (advisories = the same per-pin RJ45 label pattern approved on battery).
- D11 designer visual pass: 13 region crops at Matrix-13 + 4 full pages
  + root, ALL read individually, under
  `visual_inspections/cp2-schematic/display-iter1/designer/`. Verdict:
  readable throughout; DNP crosses render on R3/R4.
- Availability (API 2026-07-27): all 8 display-critical MPNs exact-match,
  Active, stocked (B8B-PH-K-S recovered 16 → 8,264).
- `doc_consistency_check.py` clean after the doc edits.

### 15.5 Suggested review focus

- G8 wiring read-back of the display GOLDEN table against
  `cp1_display_side.md` §5/§6 (esp. the F15 wake-path pins: nRE=IO15,
  RO=IO18, BTNs=IO12/13/14 — all RTC-capable).
- The §15.3 footprint provenance chain (independent re-derivation
  welcome — the non-monotone claim is checkable against the vendored
  file + datasheet page 1).
- The four §15.2 deltas: is each properly reflected in CP1 doc + BOM +
  requirements + schematic?
- Anything the battery review's F-classes (F01–F11) would catch here:
  exact variants, strict-ERC completeness, premise verification.

**Iteration counter for this scope starts at display-iter1. Semaphore →
reviewer_turn.**

### 15.6 D17 engineering-correctness walk (designer, post-packet addendum)

Run per `ENGINEERING_REVIEW.md` after the §15 handoff was written (the
user's audit question caught that this gate + the full-page reads were
not yet on record — both now closed; the reviewer should still re-derive
independently, a designer PASS is not evidence).

**Threat model & coordination (numbers on record):**
- Input node sees the battery-side R-78HB12's regulated 12 V (not raw
  pack 24 V) over ≤30 m Cat5e; source current is bounded by the battery
  U2's ~0.5 A foldback. TVS1 SMAJ15A: Vrwm 15 V > 12 V rail; VC 24.4 V @
  16.4 A < U1 R-78E VIN(max) 28 V ✓ bracketed. C1 rated 25 V ≥ VC (VC
  reached only during a 10/1000 µs surge; steady state = 48 % of rating)
  — the identical coordination approved on the battery board's TVS3/C4.
- F1 MF-R025: Ihold 0.25 A ≥ load (~40 mA avg / ~150 mA refresh peak);
  Vmax 60 V; trips below the battery U2 foldback (DR-11 rationale).
- **Cable-miswire case walked:** a T568 crossover or rolled cable lands
  12 V pins (1-3) on GND pins (6-8) → dead short cleared by F1 (PTC,
  resettable) + battery-side foldback; in no standard miswire does 12 V
  reach A/B — worst case the bus pins see GND or each other, inside
  THVD1400's **−16 V to +16 V bus-terminal absolute maximum** (TI
  datasheet p.4 Absolute Maximum Ratings; abs-max is a damage boundary,
  not an operating rating — the separate §5.4 Recommended Operating
  Conditions row "Input voltage at any bus terminal" is **−7 V to
  +12 V**). *(F12 correction: this line originally said ±18 V, a
  from-memory number. Both figures now re-derived from the on-file
  PDF pages 4/5.)* No
  reverse-polarity source exists (the far end is a regulated + rail,
  not a battery terminal).
- TVS2 SMAJ12CA across A-B: surge clamp only, no abs-max bracketing
  claimed — the same F44-pattern position approved for the battery's
  identical arrangement.

**Regulation:** U1 VIN 7–28 V ✓; 0.5 A vs worst load ~0.35 A boot peak
(RF disabled per D26), ~50 mA run ✓; output cap on V3V3_REG = 10 µF
(within Recom's cap-load limit; the 58 µF V3V3 bank sits behind the
mux). AP2112 600 mA / TPS2116 2.5 A ✓; priority mode (MODE=VIN1) per
datasheet; C_mux 47 µF carries the battery F11 RCB analysis unchanged.

**MCU:** decoupling + EN RC (10k/1 µF) mirror the approved battery
values; straps IO0 (WPU + BOOT header), IO3/45/46 NC-with-internal-
defaults (F05); brown-out = ESP internal BOD — no supervisor is a
DESIGN decision (D29: this board is shed by the battery side).

**Connectors (per-pin ratings):** WE RJ45 1.5 A/contact vs ≤15 mA per
12 V pin; JST-PH 2 A vs ~25 mA panel refresh; IDC 1 A; USB4085 VBUS
5 A collective. Keying: RJ45, PH (keyed by design), keyed IDC, USB-C.
Mating-cable assumptions documented (T568B straight-through;
in-box PH↔PH cable with pin-order check at assembly — CP1 §13.1).

**Domain-complete:** mechanical/serviceability constraints are
CP1-resolved and the schematic is consistent with them (right-angle J1,
board-edge USB-C behind the pop-off faceplate, internal J3/J5, no
antenna keepout per D26, plunger height deferred to CP3 by design);
thermal is trivial (R-78E ~0.1 W worst part); RF n/a (radio disabled).

**Spec-consistency sweep (mechanical grep, per the gate):** two live
drifts found and FIXED in this addendum's commit — (1)
`docs/firmware/architecture.md` still described the retired 4-pin
GND/TX/RX/RESET# debug header (now the keyed 2×3 ESP-Prog on both
boards); (2) `cp1_battery_side.md` §nets still named the display-link
UART nets UART_TX/RX_3V3 while the APPROVED battery schematic labels
them RS485_DI/RS485_RO (pre-existing drift that survived the battery
review — reconciled). Class-(b) noted, not fixed (pre-CP1 original-
intent docs, same treatment as the approved battery cycle):
`docs/hardware/schematic_battery_side.md` / `schematic_display_side.md`.

**Design-complete check:** every §15.5 ask re-read — each is a
re-derivation request against a recorded answer, none an open design
question. PASS.

### D11 addendum — full-page reads

All four `sheet_d_*.full.png` pages + `root.full.png` read end-to-end
(designer) in addition to the 13 region crops: no inter-block
collisions, nothing enters any title block, root hierarchy boxes
correct. Verdict unchanged: readable throughout.

## 9.5 Designer responses (display-iter1 findings F12–F15) — 2026-07-28

### F12 — RESOLVED (accepted; the exact failure class the doctrine names)

±18 V was a from-memory number — re-derived from the on-file
`THVD1400DR.pdf`: p.4 abs-max "Voltage at bus terminals: **−16 V to
16 V**"; and while correcting it I nearly committed a second recalled
number for the operating range, which the same PDF check caught — §5.4
"Input voltage at any bus terminal" is **−7 V to +12 V** (not the
−14/+14 I first typed). §15.6 now carries both figures with page cites
and keeps the no-bracketing statement for TVS2. Repo-swept: the ±18
appeared nowhere else.

### F13 — RESOLVED (accepted in full: docs + exact object + guard)

- All five live "SMD" cells → **THT top-mount**: `cp1_bom.md` (battery
  J3 + display J-USB), `cp1_display_side.md`, `cp1_battery_side.md`,
  and the parallel `docs/hardware/bom.md` (the doc-sites-must-agree
  class).
- **Exact object on file:** `USB4085_drawing.pdf` (sha `39afb82c5104`,
  fetched direct with a browser UA — gct.co serves HTML to bare curl)
  — independently re-verified: "Dip Type, PCB Top Mount", ordering grid
  `GF = Gold Flash (Standard)`, `A = Tape & Reel`; footprint counted at
  20 THT / 0 SMD pads. Manifest now carries BOTH objects, with the
  family-spec row re-worded to say it does NOT establish the -GF-A
  identity (that claim was mine and wrong).
- **Checker extended** exactly as suggested: a SUPERSEDED pattern
  rejects any USB4085/USB-C-receptacle row classified SMD (3 new
  fixtures; poison-proven against the live BOM → 1 finding, restored
  clean), plus a new `[exact-object]` check requiring the drawing row +
  PDF whenever the BOM pins USB4085.
- Process note: the iteration-5 reviewer evidence directory
  (`display-iter1/reviewer/`) is cited in §8.5 but was not in the
  pushed commit (63285de touches only the packet + semaphore) — please
  push it so the record is complete.

### F14 — RESOLVED (accepted; R18/R21 now executable)

`bringup_guide.md` Stage 6 rewritten: pre-attach J1 pin-map
verification (T568B beep-out, 12 V=1-3/A=4/B=5/GND=6-8), **display J5
shunt FITTED** as the bus terminus (R18), exactly-two-ends termination
rule, R3/R4 stay DNP absent CP5 evidence. New appendix section
"Display-board recovery (R21)": J3 ESP-Prog map with the manual
force-download sequence (J3.6→J3.4, blip J3.1), J-USB
USB-only bench power path (R20 chain), no-V3V3 triage for both feeds,
and a wake-path checklist (J5 fitted / ≥50 ms BREAK / gpio_hold on
IO15 / RO→IO18).

### F15 — RESOLVED (fixed, machine-guarded, and back-ported)

Gate first: `core.py`'s label-overlap check now includes annotation
symbols' VALUE text (only their auto-ref text stays exempt) — rebuilt
display and the gate reproduced exactly the reviewer's four
`[label-overlap] … × #FLGn:PWR_FLAG` defects before any layout change
(the extension is self-poison-tested by reality). Then both flag
blocks moved ref+value above the glyph (`tanchor="u"`): display
`sheet_d_power` fixed, and the identical latent defect on the APPROVED
battery `sheet_power` fixed under the same gate (the only battery
drawing change in this iteration; region evidence
`battery_sheet_power.flags_fixed.png` + display
`sheet_d_power.flags_fixed.png` under `display-iter1/designer/`).
Both boards rebuilt green: display strict ERC rc=0 / 0 messages,
battery rc=5 / 2 accepted / 0 unaccounted, requirements 42/42,
`label_body_audit` 0 findings on both changed sheets,
`doc_consistency_check` clean.

**All four findings closed. Semaphore → reviewer_turn for display-iter2.**
