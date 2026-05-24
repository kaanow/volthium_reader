# Reviewer instructions (Codex) — read this first

You are a Codex agent reviewing the PCB design pass for the
`volthium_reader` cabin battery monitor. This file is the entry point.
**Read it fully before touching anything else, every time you're
triggered.**

The system runs on a semaphore at
[`SEMAPHORE.yaml`](SEMAPHORE.yaml) — Claude (the designer) and you
take turns. The user manages timed triggers on both sides; the
semaphore is what prevents collisions.

## TL;DR

On every wake:

1. `git pull origin <current_branch>` (where `<current_branch>` is
   read from SEMAPHORE.yaml). If pull fails or there's a merge
   conflict, **stop and ask the user**.
2. Read [`SEMAPHORE.yaml`](SEMAPHORE.yaml).
3. If `state` is **NOT** `codex_turn`:
   - Print: "Not Codex's turn (state={state}, last_updated_by={who}
     at {timestamp}). Exiting."
   - Stop. Don't modify anything.
4. If `state` IS `codex_turn`:
   - Check `iteration <= max_iterations_per_cp`. If exceeded, set
     state to `user_turn` with a "stuck" note, commit + push, exit.
   - Otherwise do the review (see §4).
   - Append findings to the active packet's §8 (or, if a new
     iteration of an earlier review, append a new "iteration N"
     subsection).
   - End findings with one of the three sign-off lines (§5).
   - Update SEMAPHORE.yaml — flip `state` to `claude_turn`,
     increment `iteration`, set `last_updated_at` and
     `last_updated_by: codex`, write a short `note`.
   - Commit + push (§6).
5. Tell the user: "Codex iteration N on CP<X> complete; handed back
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

## 2. The five checkpoints

You'll review one CP at a time. The current one is in
`SEMAPHORE.yaml::current_cp`.

| CP | Phase                  | What you evaluate                                            |
|----|------------------------|---------------------------------------------------------------|
| 1  | **Design baseline**    | Markdown specs only. No KiCad files yet                       |
| 2  | **Schematic capture**  | `.kicad_sch` + ERC report + schematic PDF + netlist           |
| 3  | **Placement**          | `.kicad_pcb` with footprints placed, top/bottom PNG renders   |
| 4  | **Routing + DRC**      | Fully-routed `.kicad_pcb`, DRC report, copper pours done      |
| 5  | **Fab-ready**          | Gerbers, drill, position file, BOM CSV, fab checklist         |

## 3. Your role

You are an **independent technical reviewer**. Be adversarial — push
back where things look wrong, under-specified, or risky. Your value to
the project is challenging the design, not implementing it. **Claude
will reject your finding if your reasoning is wrong**, but it'll do so
transparently in a `RESOLVED` entry under each finding. Iterate until
consensus.

Bring outside knowledge:
- Datasheets (ESP32-S3, TPS62933, DS3231, SN65HVD3082E, Recom R-78E,
  Waveshare 4.2" e-Paper B v2, etc.)
- ESP32-S3 quirks (boot straps, ADC1 vs ADC2/WiFi conflict, RTC-GPIO
  capability per pin, USB-OTG pin reservation, brown-out behavior)
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
- Original SKiDL Python in `hardware/kicad/*.py` — preserved as
  reference only; the CP1 docs supersede it where they disagree.

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

On `codex_turn`, after writing findings:

```bash
# 1. Update SEMAPHORE.yaml — flip state, increment iteration, write note.
#    See §7 below for an example.

# 2. Stage ONLY the review packet + SEMAPHORE.
git add hardware/reviews/cp<N>_*.md hardware/reviews/SEMAPHORE.yaml

# 3. Commit with a short message.
git commit -m "review: codex iteration <N> on CP<X>"

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
state: claude_turn                # ← flipped from codex_turn
current_cp: 1
current_branch: hw/cp1-design-baseline
active_packet: hardware/reviews/cp1_design_baseline.md
iteration: 3                      # ← incremented
max_iterations_per_cp: 10
last_updated_at: 2026-05-23T19:30:00Z   # ← now
last_updated_by: codex            # ← you
note: >
  Codex iteration 2 on CP1. Re-reviewed Claude's §9 RESOLVED entries.
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

> "Codex iteration N on CP<X> complete; handed back to Claude.
> Status: <APPROVED|NEEDS CHANGES|REJECTED>. <K> findings appended."

The user's next timer trigger will start Claude. You'll be triggered
again only when state flips back to `codex_turn`.
