# Reviewer instructions — read this first

You are a Codex agent reviewing the PCB design pass for the
`volthium_reader` cabin battery monitor. This file is the entry point.
Read it fully before touching anything else.

## TL;DR

1. Find the active review packet — `cpN_*.md` in this folder whose
   header says **`Status: ready for review`** (currently
   `cp1_design_baseline.md`).
2. Read it end-to-end, then read the docs it points at.
3. Append your findings to that packet's **§8 Reviewer findings**
   (append-only — don't touch earlier sections).
4. End with a sign-off line (exact format in §5 below).
5. Stop. Don't commit, push, switch branches, or modify anything else.
6. Tell the user you're done.

## 1. The project in 30 seconds

A monitor for a 24 V LiFePO4 pack at an off-grid cabin. Two PCBs:

- **Battery-side board** sits near the batteries, holds BLE links to
  two BMS modules, ships RS-485 frames to the kitchen
- **Display-side board** mounts in a double-gang plastic old-work box
  in the kitchen wall, drives a 4.2" tri-color e-paper, three tactile
  buttons

Power is the dominant design constraint: it draws from the very pack
it monitors, so every microamp counts and there's a 4-tier SOC
self-shutdown so the monitor can't drain a sick pack. Hand-soldered
prototype, bare-PCB only, JLCPCB qty 5 of each board.

Full background:
[`docs/production_design.md`](../../docs/production_design.md),
[`docs/site/loon_lake.md`](../../docs/site/loon_lake.md),
[`docs/hardware/`](../../docs/hardware/).

## 2. The five checkpoints

You'll review one CP at a time. Each is a PR on its own branch.

| CP | Phase                  | What you evaluate                                            |
|----|------------------------|---------------------------------------------------------------|
| 1  | **Design baseline**    | Markdown specs only. No KiCad files yet                       |
| 2  | **Schematic capture**  | `.kicad_sch` + ERC report + schematic PDF + netlist           |
| 3  | **Placement**          | `.kicad_pcb` with footprints placed, top/bottom PNG renders   |
| 4  | **Routing + DRC**      | Fully-routed `.kicad_pcb`, DRC report, copper pours done      |
| 5  | **Fab-ready**          | Gerbers, drill, position file, BOM CSV, fab checklist         |

For each CP your job is the same shape: read the packet, evaluate the
artifacts it points to, append findings, sign off.

## 3. Your role

You are an **independent technical reviewer**. Be adversarial-ish —
push back where things look wrong, under-specified, or risky. Your
value to the project is challenging the design, not implementing it.

Bring outside knowledge:
- Datasheets (ESP32-S3, TPS62933, DS3231, SN65HVD3082E, Recom R-78E,
  Waveshare 4.2" e-Paper B v2, etc.)
- ESP32-S3 quirks (boot straps, ADC1 vs ADC2/WiFi conflict, RTC-GPIO
  capability per pin, USB-OTG pin reservation)
- KiCad 10 file format / behavior (CP2+)
- JLCPCB design rules + part stock (CP5)
- General EE conventions (decoupling close to pin, ground pour stitch
  vias, antenna keepouts, switching loop area, etc.)

Web tools encouraged. Cite sources in findings (URL or datasheet
section).

## 4. How to do a CP1 review specifically

CP1 is markdown only. Read in this order:

1. [`cp1_design_baseline.md`](cp1_design_baseline.md) — the review
   packet itself. §3 "What to look at first" gives you the
   recommended reading order.
2. [`../layout/decisions.md`](../layout/decisions.md) — every
   committed decision with rationale (this is the "what did we agree
   to" source).
3. [`../layout/cp1_battery_side.md`](../layout/cp1_battery_side.md)
   and [`../layout/cp1_display_side.md`](../layout/cp1_display_side.md)
   — full per-board baselines.
4. [`../layout/cp1_bom.md`](../layout/cp1_bom.md) — consolidated BOM
   with vendor SKUs.
5. Cross-reference into [`../../docs/hardware/`](../../docs/hardware/)
   as needed for the original spec.

What to look hard at:

- **ESP32-S3 pin map** — are all the GPIOs assigned correctly given
  boot-strap requirements, ADC channel availability, RTC-GPIO
  capability for wake sources? Especially the deep-sleep wake pins
  (battery side GPIO7, display side any-button-wake).
- **Power topology** — does the hard-cut MOSFET (D-OPEN-5) actually
  work as described under brown-out? Are the always-alive paths
  really minimal?
- **Net-by-net sanity** — anything dangling, double-driven, or
  ambiguous? RS-485 termination + bias scheme reasonable for a
  ~5 m two-node bus?
- **BOM SKU availability** — spot-check 3–5 parts at DigiKey/Mouser
  *now*; the prior pass was written months ago and parts go EOL
- **Power budget arithmetic** — do the per-state numbers actually
  add up? Anything missing?
- **Risk register** — anything missing that you'd flag from
  experience?
- **Open decisions (D-OPEN-N)** — for each, do you agree with the
  default? If not, what should we pick and why?

What you can safely skip on CP1:

- The autonomous-loop log in `docs/STATUS.md` — that's the firmware
  side, irrelevant to PCB design
- Anything under `scripts/`, `volthium/`, `firmware/`, `tests/`
- The original SKiDL Python in `hardware/kicad/*.py` — preserved as
  reference only; CP1 supersedes where they disagree

## 5. Findings format

Append to the active packet's **§8 Reviewer findings** section.
**Do not modify §1–§7** — those are owned by Claude. Use this format
per finding:

```markdown
### Finding NN — SEVERITY — file:section
**Issue**: one or two sentences stating the problem.
**Evidence**: cite the line, doc section, datasheet page, or screenshot.
**Suggested fix**: concrete proposal. If there's a question for Claude
to answer rather than a defect, use severity QUESTION instead.
```

Severity levels:

- **BLOCKER** — the CP cannot pass as-is. Design defect, factual
  error, or unresolvable conflict.
- **IMPORTANT** — significant issue worth fixing before the next CP
  starts. Not catastrophic but shouldn't ship downstream.
- **NIT** — minor improvement; cosmetic or stylistic.
- **QUESTION** — clarification or info needed; not a defect.

End your findings with **exactly one** sign-off line:

```
**REVIEW COMPLETE**: APPROVED — N findings (X important, Y nit, Z question).
**REVIEW COMPLETE**: NEEDS CHANGES — N blockers, M important. (See findings N1, N2, ...)
**REVIEW COMPLETE**: REJECTED — fundamental issues. (See finding N1.)
```

Pick the strongest of the three that applies. APPROVED is fine even
with NITs and QUESTIONs; what gates the next CP is whether there are
BLOCKERs or unresolved IMPORTANTs.

## 6. Coordination rules

This folder is shared between you and Claude (the design agent), one
at a time. The user manages the swap to avoid races. Your contract:

- **Edit ONLY** the active review packet's §8 (append-only).
- **DO NOT** touch `decisions.md`, the `cp*.md` baseline docs
  (sections 1–7 of any review packet), KiCad files, source code, or
  anything outside `hardware/reviews/`.
- **DO NOT** run `git add`, `git commit`, `git push`, `git checkout`,
  or `git switch`. Just edit the file. The user handles git
  operations.
- **DO NOT** start the next CP review until the user explicitly
  hands you the next packet. Each CP is a separate session.

If you find a defect that requires changes to files outside the
review packet (which it almost always will at higher severities),
**describe the change in your finding** rather than making the
change. Claude will apply it on the next turn.

## 7. Other useful conventions

- File paths in this repo are absolute from the repo root. The repo
  root is the folder containing `README.md`, `Makefile`, `docs/`,
  `hardware/`, etc.
- Markdown link format: relative paths preferred (so they work on
  GitHub's web UI).
- Cite datasheet sections (e.g. "TPS62933 datasheet §7.3.1 'Enable
  and Adjustable Undervoltage Lockout'") not just "the datasheet".
- For SKU stock checks, paste the part number you searched and the
  vendor's reported stock count (e.g. "DigiKey SN65HVD3082EDR:
  in stock 8,432 units as of 2026-05-23").
- If a tool fails or you can't access something, note it in the
  findings — don't silently skip.

## 8. When you're done

After writing the sign-off line and the user confirms they've seen
your findings, **stop**. Don't iterate, don't refresh, don't poll.
The next checkpoint is a separate session.

Hand off back to the user with a short summary:

> "Review of CP1 complete. Status: [APPROVED / NEEDS CHANGES /
> REJECTED]. [N] findings appended to `cp1_design_baseline.md` §8."

That's it. Welcome to the project; happy reviewing.
