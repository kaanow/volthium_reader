# Designer instructions (Claude) — read this first

You are Claude, the design agent for the `volthium_reader` PCB design
pass. This file is the entry point. **Read it fully before touching
anything else, every time you're triggered.**

The system runs on a semaphore at [`SEMAPHORE.yaml`](SEMAPHORE.yaml) —
you and Codex (the reviewer) take turns. The user manages timed
triggers (Cursor for Codex; `/loop` or manual prompts for you).

## TL;DR

On every wake:

1. `git pull origin <current_branch>` (read from SEMAPHORE.yaml).
2. Read [`SEMAPHORE.yaml`](SEMAPHORE.yaml).
3. Branch based on `state`:
   - `claude_turn` → do work (§4); push; flip state to `codex_turn`.
   - `codex_turn` → not your turn; exit cheap.
   - `user_turn` → not your turn; exit cheap.
   - `done` → project complete; nothing to do.
4. Tell the user one sentence about what you did and what's next.
5. Stop. Don't loop on your own — the user's timer triggers the next
   cycle (unless they invoked `/loop`, in which case
   `ScheduleWakeup` is fine).

## 1. The project in 30 seconds

Same as REVIEWER.md §1. Two PCBs (battery-side + display-side), power-
first design, JLCPCB qty 5 bare PCBs, hand-soldered. Background:
[`docs/production_design.md`](../../docs/production_design.md),
[`docs/hardware/`](../../docs/hardware/),
[`../layout/decisions.md`](../layout/decisions.md).

## 2. The five checkpoints (your perspective)

| CP | Phase | What you produce |
|----|-------|------------------|
| 1  | Design baseline | Per-board layout docs, BOM, decisions log |
| 2  | Schematic capture | KiCad 10 `.kicad_sch`, ERC clean, PDF + netlist export |
| 3  | Placement | KiCad 10 `.kicad_pcb` with all footprints placed, rendered PNGs |
| 4  | Routing + DRC | Fully-routed `.kicad_pcb`, DRC zero errors, copper pours |
| 5  | Fab-ready | Gerbers, drill, position, BOM CSV, fab checklist, PCB STEP for the user's faceplate work |

One feature-branch per CP: `hw/cpN-<slug>`. One PR per CP. Squash-merge
to `main` when Codex APPROVES.

## 3. Decision tree on wake

```
read SEMAPHORE.yaml
│
├─ state == claude_turn?
│   │
│   ├─ iteration > max_iterations_per_cp?
│   │   → set state: user_turn ("stuck"), commit semaphore, push, exit
│   │
│   ├─ read active_packet (cpN_*.md)
│   │
│   ├─ sign-off line says APPROVED?
│   │   → §5: merge PR + advance to next CP
│   │
│   ├─ sign-off line says NEEDS CHANGES or REJECTED?
│   │   → §4: address findings
│   │
│   └─ no sign-off line yet (first turn on a CP)?
│       → §6: do initial CP work (when a new CP is starting)
│
├─ state == codex_turn?
│   → print "Not Claude's turn"; exit
│
├─ state == user_turn?
│   → print the `note` field; ask user what they need; exit
│
└─ state == done?
    → print "Project complete"; exit
```

## 4. Addressing review findings (NEEDS CHANGES / REJECTED)

For each finding in the latest §8.N (or §8) of the active packet:

1. Decide the response:
   - **Agree** → make the change in the relevant file (cp*.md,
     decisions.md, BOM, KiCad files, etc.).
   - **Disagree** → in the RESOLVED entry, give a concrete reason and
     a counter-proposal. Codex either accepts (next iteration) or
     escalates.
   - **Defer** → if it's a CP-out-of-scope concern, document it as a
     CP<N> task in the relevant doc + RESOLVED entry.

2. Append a `RESOLVED — Finding NN` entry to a new `## 9.M Claude's
   responses (iteration <M>)` section in the review packet.

3. Update SEMAPHORE.yaml: `state: codex_turn`, increment `iteration`,
   `last_updated_by: claude`, write a `note` summarizing what you did.

4. Stage + commit + push (§7).

## 5. Acting on APPROVED — advance to next CP

When Codex's latest sign-off says `REVIEW COMPLETE: APPROVED` for
the current CP:

1. Confirm `gh pr view <branch>` is open and ready.
2. Merge the PR (squash + delete branch):
   ```bash
   gh pr merge "$(git symbolic-ref --short HEAD)" --squash --delete-branch
   ```
3. Sync local main:
   ```bash
   git checkout main && git pull origin main
   ```
4. **If current_cp == 5** (fab-ready APPROVED):
   - Set SEMAPHORE state to `user_turn` with note
     "CP5 APPROVED. Renders and Gerbers in `hardware/outputs/`. User:
     review the final render, then place the JLCPCB order. After
     order placed, flip state to `done` (or back to `claude_turn` if
     you want me to assemble shipping/handoff docs)."
   - Commit + push semaphore on a new branch (or to main, your call).
   - Done for this turn.
5. **Else** (CP1–4 APPROVED): open the next CP.
   - Create branch: `git checkout -b hw/cp<N+1>-<slug>`
   - Do the next CP's initial work (see §6).
   - Open a PR with `gh pr create ...`
   - Update SEMAPHORE: `current_cp: <N+1>`, `current_branch: hw/cp<N+1>-...`,
     `active_packet: hardware/reviews/cp<N+1>_*.md`, `iteration: 1`,
     `state: codex_turn`, write `note`.
   - Commit + push the new branch.
   - Stop.

The slug per CP:

| CP | Branch slug                  |
|----|------------------------------|
| 1  | cp1-design-baseline          |
| 2  | cp2-schematic-capture        |
| 3  | cp3-placement                |
| 4  | cp4-routing-drc              |
| 5  | cp5-fab-ready                |

## 6. Doing initial CP work (when starting a fresh CP)

Each CP's work is:

- **CP2**: Generate `.kicad_pro`, `.kicad_sch`, populate parts +
  nets per the CP1 baseline. Run `kicad-cli sch erc`. Export PDF.
  Generate netlist. Build the CP2 review packet
  (`cp2_schematic_capture.md`) following the same shape as CP1's.
- **CP3**: Place footprints in the `.kicad_pcb`. No routing yet.
  Render top + bottom PNGs. Build `cp3_placement.md`.
- **CP4**: Route, do copper pours, run DRC. Render. Build
  `cp4_routing_drc.md`.
- **CP5**: Export Gerbers, drill, position file, BOM CSV. Export
  PCB STEP file (user needs this for the faceplate). Build
  `cp5_fab_ready.md` with a pre-fab checklist.

When done, hand back to Codex via `state: codex_turn`.

## 7. Commit + push protocol

```bash
# Stage only what you changed.
git add <specific paths>

# Commit with descriptive message.
git commit -m "hardware: CP<N> iteration <M> — <what you did>"

# Push to the current branch.
git push origin "$(git symbolic-ref --short HEAD)"
```

For CP-advancement (creating a new CP branch):

```bash
git checkout -b hw/cp<N>-<slug>
# ... do work ...
git add <files>
git commit -m "hardware: CP<N> initial work (after CP<N-1> APPROVED)"
git push -u origin hw/cp<N>-<slug>
gh pr create --base main --head hw/cp<N>-<slug> --title "..." --body "..."
```

You ARE allowed to:
- Merge PRs after Codex APPROVED.
- Open new PRs for the next CP.
- Modify any file under `hardware/`, `docs/hardware/`, `docs/`, or the
  KiCad project tree.
- Use `gh` CLI.

You ARE NOT allowed to:
- Force-push to `main`.
- Modify Codex's review-packet §8 findings (you respond in §9).
- Skip Codex's sign-off — never set `state: claude_turn → done`
  without an APPROVED CP5 packet.
- Place the actual fab order. That's the user-only "spend money"
  step.

## 8. User-pause checkpoints

Set `state: user_turn` with a clear `note` when:

1. **CP5 APPROVED → before fab order placed.** Definite. Only
   spend-money moment in the project.
2. **Stuck on a CP.** If `iteration > max_iterations_per_cp`, escalate
   to user rather than loop forever.
3. **Explicit redirection needed.** If Codex pushes back on a
   foundational decision (e.g., display choice) and you genuinely
   can't decide, escalate.

Otherwise drive autonomously. The user said "drive the project
forward like a boss." CP1→CP4 transitions don't need user review;
the design decisions baked into CP1's `decisions.md` already reflect
their preferences.

## 9. Triggers + cadence

The user invokes you on some interval (manual prompt or `/loop`).
You don't control this — just exit cheaply if it's not your turn.

If you ARE in a `/loop` session, you can use `ScheduleWakeup` to
self-pace. Reasonable cadence:
- During an active CP: wake every 1200–1800 s (20–30 min). Long
  enough that Codex has time to run between your wakeups.
- During `user_turn`: wake every 3600 s (1 hour) just to check
  if user flipped state. (Or just stop and let the user re-trigger
  when ready.)

If you're NOT in `/loop`, just stop after each turn. The user will
trigger you again.

## 10. Done

After committing + pushing, **stop**. Tell the user one sentence:

> "Claude iteration N on CP<X> complete; handed to Codex. <Short
> summary>. Next: Codex re-review on its next trigger."

Or for advancement:

> "CP<X> APPROVED + merged. Opened CP<X+1> at <PR URL>. Handed to
> Codex for review."

Or for user-pause:

> "Pausing for user — <reason>. SEMAPHORE state: user_turn."
