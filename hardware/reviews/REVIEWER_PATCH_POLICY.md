# Reviewer Patch Authority (RPA)

The reviewer may commit **fixes**, not just findings, in one narrow
situation: a defect the designer cannot reasonably resolve because it
only manifests on the reviewer's host.

Origin: CP3 findings 08 and 10 — two Windows-only defects (CRLF writes,
transient `EINVAL`) that cost three round-trips each, because the
designer could only guess at a fix and the reviewer could only describe
the failure. One-off user authorization worked (iteration 5). This
policy makes it a standing, bounded mechanism.

## When RPA applies

Exactly one trigger: **the fix's acceptance depends on a host or
environment the designer cannot exercise.** In practice: OS-specific IO
behavior, toolchain-version behavior, host transients, path/permission
semantics.

Either side may open it:
- **Designer invites** — write `HOST-LIMITED: invites reviewer patch`
  in the finding response. Do this instead of guessing at a fix you
  cannot test.
- **Reviewer declares** — a finding whose repro is host-specific may be
  patched in the same turn; say so in the finding.

RPA does **not** apply to anything else. A defect the designer can
reproduce is a finding, always — even if the reviewer knows the fix.
That boundary is what keeps review independent: the reviewer must not
become the author of the work they audit.

## The zero-delta invariant (the load-bearing rule)

**A reviewer patch must not move one byte of a design artifact.**

A host-adaptation fix changes how bytes get written, never what they
say. So every deterministic artifact (`.kicad_pcb`, `.net`,
`.kicad_sch`, …) must be byte-identical between the patch commit and
its parent. If a fix cannot satisfy this, it is a design change: file
it as a finding and hand it back.

This is the rule that makes bounded write access safe, and it is
mechanically enforced — no judgment call.

## Protocol

**Reviewer**
1. Commit the fix ALONE (no semaphore flip, no unrelated edits), with
   trailers:
   ```
   Reviewer-Patch: F10
   Patch-Reason: host-limited — <one line: what only reproduces there>
   ```
2. Commit acceptance evidence under
   `visual_inspections/<cp>/iter<N>/reviewer/` — the failure before,
   the pass after, on your host.
3. State it in the finding: the patch exists, and it is unaccepted
   until the designer signs off.
4. Run `python hardware/reviews/tools/reviewer_patch_check.py` before
   handing back. It must not report VIOLATION.

**Designer (next turn, mandatory)**
1. Re-review the patch as you would any reviewer-suggested fix —
   verify the premise, sweep for what it missed. It is a fix by someone
   who cannot run your gates; treat it as a draft with authority, not
   as truth. (In CP3 iteration 6 this found two writers the patch
   missed.)
2. Record acceptance in the packet response:
   `RPA-ACCEPTED: F10 da48679` — finding id, patch sha.
   To reject, say why and hand back; the reviewer may not re-patch the
   same finding without new host evidence.
3. `handoff_check.py` fails while any RPA commit is unaccepted.

## Scope (enforced by `reviewer_patch_check.py`)

Allowed to touch: generator/tool Python, the review tools, protocol and
packet markdown, evidence directories, repo-level file-handling config.

Never: `hardware/layout/**` (decisions, requirements, BOM),
`hardware/datasheets/**`, `hardware/kicad/footprints/**`, `CLAUDE.md`,
`SEMAPHORE.yaml` (turn control stays with the semaphore's own commit),
and **the whole of every build directory** — those trees are 100 %
generated, so a correct patch never contains one of their files. (This
is deliberately a directory rule, not a file-suffix list: PNG, PDF, SVG,
`.rpt` and `.json` outputs are generated too, and a suffix list silently
let them through — CP3 finding 12.)

Reviewer-authored commits that touch code WITHOUT the trailer are
flagged as unauthorized: the trailer is what makes the patch
reviewable, so an untrailered fix is an unreviewed one. Your own
analysis programs under `visual_inspections/**` are evidence, not
product code, and are never flagged.

Each patch must carry **host evidence** in the same commit — a patch
the designer cannot check on the host where it matters is not
reviewable.

## Enforcement epoch

RPA binds commits from the policy's own commit forward
(`rpa_policy_base` in `SEMAPHORE.yaml` — an immutable sha). A policy
cannot bind commits made before it existed, and a mutable ref like
`origin/main` would make the verdict depend on which clone runs the
gate — the reviewer's clone flagged five pre-policy commits the
designer's clone never saw (CP3 finding 11). Pre-policy patches are
legitimized by an `RPA-ACCEPTED` line, never by moving the base.

## Patching the mechanism itself

The gate, this policy, and `handoff_check.py` are all patchable under
RPA — that code is host-sensitive too, and findings 11/12 were fixes to
it. But a patch touching them prints a **SCRUTINY** line: read that diff
line by line before signing off, because it can weaken every other
check. Bounded authority that can silently rewrite its own bounds is
not bounded.
