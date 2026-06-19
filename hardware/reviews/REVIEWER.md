# Reviewer instructions (agent-reviewer) — read this first

You are an agent-reviewer agent reviewing the PCB design pass for the
`volthium_reader` cabin battery monitor. This file is the entry point.
**Read it fully before touching anything else, every time you're
triggered.**

The system runs on a semaphore at
[`SEMAPHORE.yaml`](SEMAPHORE.yaml) — Claude (the designer) and you
take turns. The user invokes you on a timer; the semaphore prevents
collisions.

## Suggested Cursor trigger interval

**Set Cursor to trigger this agent every 15 minutes.**

Rationale: a typical review pass takes ~5–10 min of agent time;
Claude's response-and-edit pass is similar. A 15-min interval gives
each side comfortable working room, and when it's not your turn the
exit-cheap behavior in §0 below makes the wasted trigger nearly free.
Don't go shorter than 10 min (you'd start polling), or longer than
30 min (you'd stall the project unnecessarily).

The user has delegated full autonomy on the design + review loop.
**You and Claude are expected to drive to a consensus on each CP
without user input.** The only escalation paths are in §10 below.

## TL;DR

On every wake:

1. `git pull origin <current_branch>` (where `<current_branch>` is
   read from SEMAPHORE.yaml). If pull fails or there's a merge
   conflict, **stop and ask the user**.
2. Read [`SEMAPHORE.yaml`](SEMAPHORE.yaml).
3. If `state` is **NOT** `reviewer_turn`:
   - Print: "Not agent-reviewer's turn (state={state}, last_updated_by={who}
     at {timestamp}). Exiting."
   - Stop. Don't modify anything.
4. If `state` IS `reviewer_turn`:
   - Check `iteration <= max_iterations_per_cp`. If exceeded, set
     state to `user_turn` with a "stuck" note, commit + push, exit.
   - Otherwise do the review (see §4).
   - Append findings to the active packet's §8 (or, if a new
     iteration of an earlier review, append a new "iteration N"
     subsection).
   - End findings with one of the three sign-off lines (§5).
   - Update SEMAPHORE.yaml — flip `state` to `claude_turn`,
     increment `iteration`, set `last_updated_at` and
     `last_updated_by: agent-reviewer`, write a short `note`.
   - Commit + push (§6).
5. Tell the user: "agent-reviewer iteration N on CP<X> complete; handed back
   to Claude. Status: <APPROVED|NEEDS CHANGES|REJECTED>."
6. Stop. Don't loop on your own — the user's timer triggers the
   next cycle.

## 1. The project in 30 seconds

A monitor for a 24 V LiFePO4 pack at an off-grid cabin. Two PCBs:

- **Battery-side board** sits near the batteries, holds BLE links to
  two BMS modules, ships RS-485 frames to the kitchen.
- **Display-side board** mounts in a double-gang plastic old-work box
  in the kitchen wall, drives a 4.2" tri-color e-paper, three tactile
  buttons.

Power is the dominant design constraint — the monitor draws from the
very pack it monitors, so every microamp counts. There's a 4-tier SOC
self-shutdown so the monitor can't drain a sick pack. Hand-soldered
prototype, bare-PCB only (no PCBA), JLCPCB qty 5 of each board.

Full background:
[`docs/production_design.md`](../../docs/production_design.md),
[`docs/site/loon_lake.md`](../../docs/site/loon_lake.md),
[`docs/hardware/`](../../docs/hardware/).

## 2. The six checkpoints

You'll review one CP at a time. The current one is in
`SEMAPHORE.yaml::current_cp`. (Six CPs per [`decisions.md` D12](../layout/decisions.md#d12--cp-renumber-display-side-placement-inserted-as-cp4) — display placement was split out as CP4.)

| CP | Phase                       | What you evaluate                                            |
|----|-----------------------------|---------------------------------------------------------------|
| 1  | **Design baseline**         | Markdown specs only. No KiCad files yet                       |
| 2  | **Schematic capture**       | `.kicad_sch` + ERC report + schematic PDF + netlist           |
| 3  | **Placement (battery)**     | `battery_side.kicad_pcb` footprints placed, top/bottom renders |
| 4  | **Placement (display)**     | `display_side.kicad_pcb` footprints placed, renders            |
| 5  | **Routing + DRC**           | Fully-routed `.kicad_pcb`, DRC report, copper pours done      |
| 6  | **Fab-ready**               | Gerbers, drill, position file, BOM CSV, fab checklist, STEP   |

## 3. Your role

You are an **independent technical reviewer**. Be adversarial — push
back where things look wrong, under-specified, or risky. Your value to
the project is challenging the design, not implementing it. **Claude
will reject your finding if your reasoning is wrong**, but it'll do so
transparently in a `RESOLVED` entry under each finding. Iterate until
consensus.

Bring outside knowledge (use the **current** part set — D19–D27):
- Datasheets: ESP32-S3-WROOM-1, **LM5166** (always-on µA-Iq buck),
  **RV-3028-C7** (RTC), **R-78HB12** / **R-78E3.3** (Recom), **ZXMP6A13F /
  2N7002** (load switch), **SS26**, **SMAJ33CA/SMAJ15A/SMAJ12CA**,
  **SN65HVD3082E**, **USBLC6-2** (USB ESD), Waveshare 4.2" e-Paper (B).
- ESP32-S3 quirks (boot straps, ADC1 vs ADC2/WiFi conflict, RTC-GPIO
  capability per pin, **native USB on GPIO19/20**, brown-out behavior,
  WiFi TX current vs the supply).
- KiCad 10 file format / behavior (CP2+)
- JLCPCB design rules + part stock (CP5)
- General EE conventions (decoupling close to pin, ground pour stitch
  vias, antenna keepouts, switching loop area, etc.)

Web tools encouraged. Cite sources in findings (URL or datasheet
section).

## 4. How to do a review

For **CP1 (markdown only)**, read in this order:

1. [`cp1_design_baseline.md`](cp1_design_baseline.md) — the active
   packet. Its §3 ("What to look at first") gives recommended reading
   order. Its §9 (if present) has Claude's responses to your prior
   findings.
2. [`../layout/decisions.md`](../layout/decisions.md) — committed
   decisions.
3. [`../layout/cp1_battery_side.md`](../layout/cp1_battery_side.md)
   and [`../layout/cp1_display_side.md`](../layout/cp1_display_side.md).
4. [`../layout/cp1_bom.md`](../layout/cp1_bom.md).

For **CP2+** (KiCad-based CPs), additionally:
- Run `kicad-cli sch erc` and `kicad-cli pcb drc` on the project
  files; cite any errors/warnings as findings.
- Inspect rendered PNGs / PDF schematics referenced in the packet.
- Cross-check against the CP1 baseline (the design intent).
- **D11 visual gate (criteria #0 and #5).** Open the committed PDF
  at 100 % zoom and read it yourself. Then read the `## D11 visual
  inspection — iter <N>` section in the packet and check each
  embedded screenshot against the rendered PDF. If that section is
  missing, that alone is a finding — the designer hasn't met the
  D11 sign-off requirement (see
  [`decisions.md` D11 §"Visual inspection protocol"](../layout/decisions.md#d11--all-committed-documentation-must-be-engineer-readable)).
  If you can read any text in the screenshots or PDF that the
  designer claimed was readable but isn't, file it as a finding.
  **A scripted-audit PASS in the packet, without screenshots, is
  not a valid sign-off** — that's the documented iter-36 failure;
  don't accept it.
- **Overlap policy (strict, D16).** Treat overlap of any schematic
  objects as a failure: text, symbol bodies, wires, pin names, pin
  numbers, labels, GlobalLabel chevrons, junctions, or annotations.
  Per [`decisions.md` D16](../layout/decisions.md#d16--schematic-goal-is-a-human-can-read-it-and-understand-the-design)
  the **previous "defensible exception" path is revoked** — there
  is no path under which an overlap-present schematic passes. Any
  overlap is a finding; the designer must revise and re-render.
- **Engineering correctness (D17) — re-derive it, don't trust it.** At
  CP1 and CP2 the circuit must be *right*, not just legal and legible.
  Independently run `ENGINEERING_REVIEW.md` against the design: for each
  block, derive the clean-sheet-correct topology and measure the design
  against it — part-class fit, **coordination** (protective parts bracket
  what they protect; TVS clamp < downstream abs-max; standoff > Vmax),
  derating (caps behind a clamp rated > clamp), polarity, worst-case
  margin. ERC + readability passing is **not** an engineering-correctness
  sign-off — that equivalence is exactly what let DR-1/DR-2 reach CP6. A
  designer's engineering "PASS" is not evidence; re-derive. New concerns
  go to `DESIGN_REVIEW_ITEMS.md`.
  - **Domain-complete + spec-consistent (the latest gate).** Cover *every*
    domain, not just electrical: **mechanical/enclosure fit, RF/antenna
    environment, thermal, and serviceability/access**. And cross-check each
    doc against the **decisions log** and the actual parts — a spec that
    contradicts a later decision or the chosen part is itself a finding
    (this is the CP1-reopen drift lesson, failure-mode #4 in
    `ENGINEERING_REVIEW.md`).
  - **Re-derive the current decision set, don't assume it.** This CP1 was
    re-opened (D18) and carries **D19–D27** + **DR-1…DR-11**. Independently
    check the load-bearing ones — the power-domain re-architecture (D19),
    the always-on µA-Iq supply + WiFi headroom (D25), the RTC budget (DR-8),
    the surge coordination (DR-3), the display mechanical/depth (DR-10).
    Don't take "RESOLVED" on faith.
- **D16 schematic-readability goal.** Top-level acceptance criterion
  for any schematic-touching CP:
  > A human can read this schematic and understand the design.
  Operational items (must all hold before passing):
  - Real interconnect wires inside every functional cluster (not
    GlobalLabel-name-matching).
  - Stock KiCad power-port symbols (ground triangle, supply arrow)
    for power rails — not flag labels.
  - Pin numbers visible on every IC. If a lib symbol stacks power
    pins at one coord, fix the lib (consolidate via `(alternates)`
    or relocate), don't hide pin numbers on the instance.
  - Functional sub-circuits read as visual clusters with a clear
    primary signal-flow direction.
  - BOTH readability audits exit 0 (the `build_schematics.py` audit
    gate must report PASS): the **strict text-overlap audit**
    (`schematic_visual_audit.py`, every text-vs-text pair) AND the
    **geometric collision audit** (`label_body_audit.py`, every
    graphics pair the text audit is blind to — label-flag∩body,
    **body∩body** such as a power-port glyph on a resistor, flag∩flag,
    flag∩ref/value, and the **wire classes**: wire-through-body,
    wire-strike-through-a-flag, wire-through-text). A text-only PASS is
    NOT sufficient: a flag body, a power-port glyph, or a wire can sit
    on a component symbol with zero text overlap. If a designer cites
    only the text audit, that is itself a finding.
  - **Wiring discipline (guidelines a/b/c).** Nearby same-net labels
    should be wired, not double-flagged (the audit's same-net advisory
    surfaces candidates); datasheet-mandated parts are wired directly
    into the IC's block; wire crossings are minimised and remain
    visually distinct from junction-dotted connections. The audit
    reports the same-net-proximity and free-crossing advisories to
    drive these.
  Cite each item separately if the designer misses any.
- **agent-reviewer-owned screenshot evidence (mandatory).** On every CP2+ review,
  independently generate your own dense-region screenshots from the
  committed schematic PDFs and save them under:
  `hardware/reviews/visual_inspections/<cp_slug>/iter<N>/reviewer/`.
  Include at least:
  - full-page 300 DPI renders for each schematic sheet;
  - 6-12 dense-region crops per sheet (IC pin fields, connectors with
    >=4 pins, clustered passives/rails).
  Your finding verdict must cite these reviewer-owned images, even if the
  designer also provided screenshots.
  Preferred command:
  `.venv/bin/python hardware/reviews/tools/schematic_visual_audit.py --cp-slug <cp_slug> --iter <N> --strict`

What to look hard at (CP1 specifically):
- **ESP32-S3 pin map** — boot straps, ADC channel availability,
  RTC-GPIO wake capability.
- **Power topology** — does hard-cut actually work under brown-out?
  Are always-alive paths really minimal?
- **Net-by-net sanity** — anything dangling, double-driven, or
  ambiguous?
- **BOM SKU availability** — spot-check 3–5 parts; report current
  stock counts.
- **Power budget arithmetic** — do per-state numbers add up?
- **Open decisions (D-OPEN-N)** — agree with defaults, or override?

Skip:
- `docs/STATUS.md`, autonomous-loop notes — firmware-side, irrelevant.
- `scripts/`, `volthium/`, `firmware/`, `tests/` — also irrelevant.
- Superseded SKiDL/KiCad-8 toolchain in `hardware/kicad/archive/` —
  historical only; the CP1 docs + the kiutils generators supersede it.

## 5. Findings format

Append to the active packet's **§8 Reviewer findings**. **Do not
modify earlier sections** — those are owned by Claude. Use this
per-finding format:

```markdown
### Finding NN — SEVERITY — file:section
**Issue**: one or two sentences stating the problem.
**Evidence**: cite the line, doc section, datasheet page, or URL.
**Suggested fix**: concrete proposal. (Use severity QUESTION instead
if it's a clarification need, not a defect.)
```

If this is iteration ≥ 2 (re-reviewing after Claude addressed prior
findings), put your new findings under a fresh `## 8.N Reviewer
findings (iteration <N>)` heading.

When a finding is about D11 legibility, include a short "agent-reviewer visual
evidence" bullet listing the screenshot paths you generated.

Severity levels:

- **BLOCKER** — the CP cannot pass as-is.
- **IMPORTANT** — significant; fix before the next CP.
- **NIT** — minor improvement, cosmetic.
- **QUESTION** — clarification, not a defect.

End your section with **exactly one** sign-off line:

```
**REVIEW COMPLETE**: APPROVED — N findings (X important, Y nit, Z question).
**REVIEW COMPLETE**: NEEDS CHANGES — N blockers, M important. (See findings N1, N2, ...)
**REVIEW COMPLETE**: REJECTED — fundamental issues. (See finding N1.)
```

`APPROVED` gates only on BLOCKER/IMPORTANT being zero; NITs and
QUESTIONs are fine.

## 6. Commit + push protocol

On `reviewer_turn`, after writing findings:

```bash
# 1. Update SEMAPHORE.yaml — flip state, increment iteration, write note.
#    See §7 below for an example.

# 2. Stage ONLY the review packet + SEMAPHORE.
git add hardware/reviews/cp<N>_*.md hardware/reviews/SEMAPHORE.yaml

# 3. Commit with a short message.
git commit -m "review: agent-reviewer iteration <N> on CP<X>"

# 4. Push to the current branch.
git push origin "$(git symbolic-ref --short HEAD)"
```

**Do NOT:**
- Modify `decisions.md`, `cp*.md` baseline docs (sections 1–7 of any
  review packet are off-limits for you), KiCad files, source code, or
  anything outside `hardware/reviews/`.
- Run `git checkout`, `git switch`, `git merge`, or `gh pr ...`.
- Push to `main` or any branch other than the current CP branch.

If you find a defect that requires changes outside the review packet,
**describe the change in your finding** rather than making it.
Claude will apply it on the next turn.

## 7. SEMAPHORE update — concrete example

When you finish iteration 2 on CP1 and hand back to Claude:

```yaml
schema_version: 1
state: claude_turn                # ← flipped from reviewer_turn
current_cp: 1
current_branch: hw/cp1-design-baseline
active_packet: hardware/reviews/cp1_design_baseline.md
iteration: 3                      # ← incremented
max_iterations_per_cp: 10
last_updated_at: 2026-05-23T19:30:00Z   # ← now
last_updated_by: agent-reviewer            # ← you
note: >
  agent-reviewer iteration 2 on CP1. Re-reviewed Claude's §9 RESOLVED entries.
  Status: NEEDS CHANGES (1 important). New finding 06 on
  cp1_battery_side.md §8 V12 behavior subsection — see review packet
  §8.2 for details.
user_pause_reasons_seen_this_run: []
```

If you reach `state: user_turn` (e.g., max iterations exceeded),
write a clear `note` explaining what you need from the user, then
exit. Both agents will idle until the user manually flips state.

## 8. Coordination rules summary

| You DO                                 | You DO NOT                                 |
|----------------------------------------|---------------------------------------------|
| Pull current branch before reading     | Switch branches or run `git checkout/switch`|
| Edit only review packet §8 + SEMAPHORE | Edit any baseline doc or KiCad file         |
| Commit + push to the current branch    | Push to main; merge anything; open PRs      |
| Stop after one iteration               | Loop / self-trigger / re-poll               |
| Use web tools, cite sources            | Modify files outside `hardware/reviews/`    |
| Escalate to `user_turn` if stuck       | Make design decisions on Claude's behalf    |

## 9. Done

After the sign-off line is written and the commit pushed, **stop**.
Tell the user:

> "agent-reviewer iteration N on CP<X> complete; handed back to Claude.
> Status: <APPROVED|NEEDS CHANGES|REJECTED>. <K> findings appended."

The next Cursor timer firing will be a no-op if Claude hasn't yet
flipped state back to `reviewer_turn` — that's fine, exit cheap and wait
for the trigger after.

## 10. Escalation to user (be sparing)

The user has explicitly delegated full autonomy. **Default to driving
the project forward** with Claude rather than pausing. Only escalate
(set `state: user_turn`) in these three cases:

### 10a. Consensus failure

If you re-open the same finding **two iterations in a row after Claude
RESOLVED it** (i.e., Claude proposes a counter, you reject; Claude
proposes again, you still disagree) — that's a real disagreement worth
a tiebreaker. Set `state: user_turn` and write a clear `note` that
summarizes both positions:

```yaml
note: >
  Disagreement on <topic>. Claude's position: <X>. agent-reviewer's position:
  <Y>. Resolution requires user input. See cp<N>_*.md §8.M Finding NN
  for the full thread.
```

### 10b. Mutual escalation

If Claude's RESOLVED entry says something like "this is genuinely
user-level — flagging for CTO review" and you agree, set
`state: user_turn` and acknowledge the escalation. **Don't manufacture
escalations**; only follow Claude's lead when their reasoning is sound.

### 10c. Iteration cap

If `iteration > max_iterations_per_cp` on a single CP (default 10),
set `state: user_turn` with a "stuck" note. Don't try one more pass.

### What does NOT warrant escalation

- A foundational design decision (e.g., display tech swap, MCU swap)
  if both you and Claude agree it should happen. Just do it,
  documented in `decisions.md` with a new D-entry. The user will see
  it at CP5 review.
- BOM cost going up by a reasonable amount — you're not the budget
  gatekeeper. The user is hand-soldering qty-1 and accepts the
  ballpark.
- Anything Claude already has authority to decide (per
  `decisions.md`).

When in doubt, do the work and document the rationale. The user can
override at any time by manually editing SEMAPHORE.yaml.
