# Hardware Design SOP — the standing standard

This is the distilled standard for designing a board in this repo: the gates,
principles, and tooling that every checkpoint must satisfy. Each rule here was
earned — but this document is deliberately **forward-looking**: it states the
rule, not the incident. The history (which defect taught which gate) lives in
[`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md) and the decisions log
([`../layout/decisions.md`](../layout/decisions.md)); read those only when you
need the *why* behind an edge case. To **do** the work, this page is enough.

Role playbooks: [`DESIGNER.md`](DESIGNER.md) (Claude), [`REVIEWER.md`](REVIEWER.md)
(agent-reviewer), [`README.md`](README.md) (packet + cycle mechanics).

---

## Governing principles

These are the "why" behind every gate; when a gate is ambiguous at an edge
case, decide the way these principles point.

1. **Power-first.** The pack must outlive the electronics by orders of
   magnitude. Minimize *every* continuous draw — no indicator LEDs, no idle
   bias on an always-on rail, no µA left on the table in the low-SOC tiers.
   A part's quiescent current is a first-class selection criterion, not a
   footnote.
2. **Replace, don't patch.** When a part or choice turns out to misfit, swap
   it for a genuinely better one — never bolt a workaround onto a bad choice.
   A fixed-output variant beats an adjustable one plus a divider you have to
   babysit; the right connector beats an adapter.
3. **Verify the object, not your model of it.** The errors that reach the user
   are wrong *premises* about real purchased parts, not arithmetic. Open the
   datasheet. "It's obviously a 2.54 mm header" is exactly how a wrong
   connector ships through both design and review.
4. **Design-complete before handoff.** A reviewer is a second set of eyes on
   *finished* work, never a way to get the work done. Every question you hand
   over must already have your answer on record for them to check against.
5. **Domain-complete.** Cover *every* domain each pass — electrical,
   mechanical, thermal, RF, serviceability. A deep dive in one domain does not
   excuse silence in another; the classic miss is a rigorous power review that
   never looks at the enclosure.
6. **Correctness ≠ legality.** ERC-clean + DRC-clean + readable is *not* the
   same as right. Those gates check that the drawing is legal and legible, not
   that it is the correct circuit with the correct parts, coordinated and
   derated. The engineering-correctness gate (G1) is the one that asks the
   real question.
7. **Excellence over expedience.** Prefer a clean artifact and a one-time cost
   over an expedient shortcut that leaves residue. Pay the cost once.

---

## Checkpoint flow

Design advances through six checkpoints; each may not begin until the prior is
reviewer-approved. The **user must explicitly clear** entry into the next CP.

| CP  | Phase                        | Advance gate (must pass) |
|-----|------------------------------|--------------------------|
| CP1 | Architecture / baseline      | G1 (architecture) · G2 · G3 · G4-flag · G5 · G7 |
| CP2 | Schematic capture            | G1 (per-part) · G3/G2 re-verify · G6 |
| CP3 | Placement (battery)          | G4 (footprints/thermal-pad/vias) · G6 · mechanical re-verify |
| CP4 | Placement (display)          | as CP3 |
| CP5 | Routing + DRC                | DRC ground-truth clean (G-tools) · G6 |
| CP6 | Fab-ready                    | full re-verify · **user sign-off before fab order** |

Mechanical/physical constraints set at CP1 are *re-verified* downstream — a
constraint is "met" only when the latest artifact still satisfies it.

---

## The gates

Run every applicable gate each pass. The **designer** runs them and records the
result before flipping the semaphore; the **reviewer independently re-derives**
— a designer's "PASS" is not evidence.

### G1 — Engineering-correctness (CP1 architecture + CP2 per-part)
First-principles, per net / block: threat & operating model → clean-sheet
topology (name it, then measure the design against it) → part-class + rating →
**coordination** (protective parts must *bracket* what they protect: clamp <
downstream abs-max; standoff > Vmax-charge; fuse < trace/connector limit; gate
drive within FET Vgs) → derating → polarity/direction → worst-case margin
verdict. Full method + per-domain checklist:
[`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md). (Canonical: decisions **D17**.)

### G2 — COTS interface-reality + datasheet-on-hand (CP1)
For **every** active BOM part — module, connector, mechanical part — store its
datasheet in [`../datasheets/`](../datasheets/) (manifest: MPN → file → source
→ sha256) **and read it**, verifying against the design: (1) exact connector
**PN + pitch + pinout**; (2) **what's in the box** (included cables/accessories,
and that the board-side mate is the correct PN); (3) mechanical envelope +
mount; (4) operating/interface specs (thresholds, ratings, magnetics). Fetch via
the parts-sourcing API `/datasheet` proxy; pull WAF-blocked hosts manually. **An
absent or unread datasheet is an unverified premise — CP1 does not sign off on
those.** When a datasheet reveals a poor fit, **retire the part** (principle 2).
(Canonical: decisions **D32**.)

### G3 — Part availability, early
Sanity-check **stock + lifecycle (Active vs NRND/EOL/LTB) + the exact orderable
variant** the moment you pick a part — not only at BOM-lock. The variant that's
*in stock* may differ from the one you had in mind (output voltage, package,
current grade). Catch a phantom/obsolete/wrong-variant part while the choice is
still cheap, before layout is built around it. Re-verify live stock at BOM-lock.
Tool: the parts-sourcing API (see Tooling).

### G4 — Assembly & solderability
Decide the **assembly method explicitly** and design to it. This is a one-off,
hand-assembled build (qty = 1): iron for leaded parts, and **hot-air / oven +
paste stencil** for leadless/bottom-terminated parts and modules. Rules:
- **Fix hard-to-solder packages at the assembly layer first.** A paste stencil
  deposits an exact, repeatable paste volume per aperture — it solves "the right
  amount of solder on tiny pads," which is the real pain, not the footprint.
  Put a stencil in the fab order.
- **Swap a part for solderability only on merit.** If an equal-or-better part
  exists in an easier package, take it (free win). If the only easier-package
  option costs the design's core metric — e.g. a leaded mux drawing 57× the
  Iq — **keep the harder part and stencil-reflow it.** Never downgrade the
  design to dodge a package.
- **Flag every leadless part at CP1** so CP3 placement gets its
  footprint/thermal-pad/via/keep-out right. Nothing about assembly should be a
  surprise at fab. (Canonical: decisions **D33**.)

### G5 — Spec-consistency sweep (run mechanically, not by noticing)
After **any** decision that supersedes a part / value / enclosure / connector /
net name / dimension, build an alternation of the **superseded tokens** and
`grep -rniE` it across the whole repo (quote `--include='*.md'` so zsh doesn't
expand it; exclude `/archive/`). Classify every hit: (a) intentional `was→now`
history — leave; (b) a generator/output a later CP owns — note, don't fix; (c) a
live contradiction in a current doc — fix now. Report a clean bill or the exact
remaining list. **Opportunistic discovery is the failure mode; the mechanical
sweep is the gate.** Also cross-check each CP doc against the decisions log and
the actual chosen parts — internal drift is as real a defect as a wrong value.

### G6 — Documentation readability (CP2 onward)
Schematic/PDF readability is a first-class deliverable. **Inspect at high
resolution** — per-region crops at Matrix(12–14), never a judgment from a
full-page render — and run the audit tools ([`tools/`](tools/)); a passing
*script* is not a passing *look*, and a passing *look* is not a passing script.
Sign off with a binary, per-criterion scorecard, and never justify a row on a
false premise. Full acceptance bar: [`DESIGNER.md`](DESIGNER.md) §0.
(Canonical: decisions **D11 / D13 / D16**.)

### G7 — Design-complete before handoff
Read each item in your "request to the reviewer" aloud. If it's phrased as a
question you don't know the answer to ("is a fixed variant orderable?", "does
the stack fit?", "is the divider impedance OK?"), it is a **design step you
skipped**, not a review item — a FAIL. Go compute the number / resolve the part
/ dimension the stack, put the answer on record, *then* ask the reviewer to
independently re-derive and confirm. Asking for an independent re-derivation of
something high-stakes is good; handing over an open design question is not.

---

## Per-domain checklist (G1 detail)

Run all of it, every pass — see [`ENGINEERING_REVIEW.md`](ENGINEERING_REVIEW.md)
for the full text.

- **Power input** — over-current (fuse/PTC); reverse polarity; surge TVS
  (standoff > Vmax-charge, clamp < downstream abs-max); bulk caps rated > clamp;
  cabled inputs → ESD.
- **Regulation** — VIN rating > (bus max **and** surge clamp); Vout/Iout margin;
  all support present + valued (L, I/O caps, BOOT, FB, comp); thermal at max
  load & VIN.
- **Comms** — termination, idle bias, fail-safe; ESD on cable-exposed lines;
  voltage-domain match.
- **MCU** — decoupling per pin; boot-strap / EN / reset states; brown-out;
  supply-current budget vs regulator.
- **Sensing** — divider ratio vs ADC range; anti-alias/filter; input protection;
  source loading.
- **Connectors** — pinout, keying, per-pin current/voltage rating, mating-cable
  assumptions (⇒ G2).
- **Physical/mechanical** — enclosure type/material/IP and its interaction with
  the board (plastic vs metal drives the antenna choice); RF keep-outs matched
  to the *actual* module variant; thermal paths; mounting; serviceability
  (program/debug/replace-fuse without disassembly where required). **Board
  outline is an output of placement** — don't fix a size before parts are placed.

---

## Tooling

- **Parts-sourcing API** — `http://eridani.zt:8787` (curl over **plain http**;
  do not use a fetcher that force-upgrades to https). `POST /query|/batch` for
  stock / CAD price / lifecycle / package / parametrics across
  Mouser+DigiKey+Octopart; `GET /datasheet?mpn=…` proxy returns the PDF with
  `X-Datasheet-SHA256` / `-Source-Url` headers; `GET /guide` for the current
  contract. Use it for G2 and G3.
- **Datasheet store** — [`../datasheets/`](../datasheets/) + `manifest.md`
  (MPN → file → provider → source URL → sha). One PDF per active part; retire a
  PDF when its part is retired.
- **Datasheet text extraction** — the repo `.venv` has PyMuPDF; extract with
  `./.venv/bin/python` + `fitz` (the Read tool's PDF page-render path needs
  poppler, which isn't installed — use text extraction).
- **Audit scripts** — [`tools/`](tools/): `schematic_visual_audit.py`,
  `label_body_audit.py` (the strict text-overlap audit is blind to
  text-vs-graphics — run the label-body audit too).
- **DRC/ERC ground truth** — regenerate from the *committed* board and count
  errors from that; never trust an in-memory or pre-route number. Details:
  [`DESIGNER.md`](DESIGNER.md) §12.

---

## Two-agent workflow

Designer and reviewer coordinate through
[`SEMAPHORE.yaml`](SEMAPHORE.yaml) (`claude_turn` / `reviewer_turn` /
`user_turn` / `done`). The designer does the work, self-runs the gates above,
writes a **self-contained** review packet (the reviewer reads the packet, not
the whole repo), and flips the semaphore. The reviewer independently re-derives
and appends findings; clear errors are fixed, judgment/human-decision items go
to [`DESIGN_REVIEW_ITEMS.md`](DESIGN_REVIEW_ITEMS.md) (OPEN → RESOLVED). Cycle
mechanics: [`README.md`](README.md).
