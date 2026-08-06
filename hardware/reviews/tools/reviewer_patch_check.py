#!/usr/bin/env python3
"""Reviewer Patch Authority gate — see ../REVIEWER_PATCH_POLICY.md.

Bounded write access for the reviewer is only safe if its boundary is
mechanical. This checks every reviewer-authored commit in a range:

  1. code changes by a reviewer author MUST carry `Reviewer-Patch: <id>`
     (an untrailered fix is an unreviewed one)
  2. the finding id must exist in the active packet
  3. changed paths within the allowed scope, none in the denied set —
     which denies the BUILD DIRECTORIES WHOLESALE, not a suffix list
     (F12: PNG/PDF/SVG/report/JSON outputs are generated too)
  4. ZERO-DELTA: no generated artifact differs between the patch commit
     and its parent — a host-adaptation fix changes how bytes are
     written, never what they say. This is the invariant that makes the
     whole mechanism safe.
  5. host evidence committed alongside the patch (a patch the designer
     cannot check is not reviewable)
  6. designer sign-off `RPA-ACCEPTED: <id> <sha>` present in the packet

Enforcement epoch: the range defaults to `POLICY_BASE..HEAD`, pinned in
this file — an immutable sha, because a policy cannot bind commits made
before it existed, and because a mutable ref like `origin/main` makes
the verdict depend on which clone runs it (F11). This module is the ONLY
owner of epoch selection: callers pass no range (F13), and the
reviewer-writable SEMAPHORE copy is documentary and equality-checked
(F14 — a guard whose scope the guarded party sets is not a guard).
Sign-off is checked by git AUTHORSHIP as RECORDED, not by the line's
presence: the packet is reviewer-writable, so a patch could otherwise
accept itself. Note the limit — author names are free-form commit data,
not authenticated identity (F15). That is a deliberate stopping point,
not an oversight: see the threat model in ../REVIEWER_PATCH_POLICY.md
and DR-34. This check stops accidental self-acceptance; it does not
withstand a deliberate one, and nothing short of signed commits would.

Exit 0 clean · 1 VIOLATION (scope/invariant breach) · 2 PENDING
(a valid patch awaiting designer acceptance).

Usage: reviewer_patch_check.py [<git-range>]
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# --- enforcement constants: pinned HERE, never read from SEMAPHORE.yaml ---
# A guard whose scope is set by the guarded party is not a guard. The
# reviewer must rewrite SEMAPHORE.yaml every turn (that is turn control,
# their job), so anything load-bearing that lives there is theirs to
# change — setting the epoch to HEAD, or emptying the author list, made
# this gate report clean while hiding every patch (CP3 F14 + the designer
# sweep that followed it). These live in enforcement code instead, which
# is in SELF below: a reviewer patch touching it raises SCRUTINY.
# SEMAPHORE keeps documentary copies; they are equality-checked at run.
POLICY_BASE = "3e4c097d891d4f516f7b51e264308a679d7f3995"
REVIEWER_AUTHORS = ("voxelisKW",)

# Generated trees: nothing in them is authored, so a reviewer patch may
# never contain one. _assert_build_dirs_in_sync() holds this list equal
# to handoff_check.BUILD_DIRS at every run.
BUILD_DIRS = [
    "hardware/kicad/schematic/build/",
    "hardware/kicad/schematic/build_display/",
    "hardware/kicad/pcb/build/",
    "hardware/kicad/pcb/build_display/",
]
ALLOW = [
    "hardware/kicad/",          # generator/tool python (see DENY)
    "hardware/reviews/",        # review tools, protocols, packet, evidence
    ".gitattributes",
    ".gitignore",
]
DENY = [
    "hardware/layout/",             # decisions, requirements, BOM
    "hardware/datasheets/",         # part evidence
    "hardware/kicad/footprints/",   # library data
    "hardware/reviews/SEMAPHORE.yaml",   # turn control: its own commit
    "CLAUDE.md",
] + BUILD_DIRS
# reviewer-owned evidence: theirs to write, never product code
EVIDENCE = "hardware/reviews/visual_inspections/"
# the mechanism's own enforcement surface — patchable, but never silently
SELF = ("hardware/reviews/tools/reviewer_patch_check.py",
        "hardware/reviews/REVIEWER_PATCH_POLICY.md",
        "hardware/reviews/tools/handoff_check.py")


def _assert_build_dirs_in_sync():
    """The zero-delta boundary and the handoff gate's freshness check must
    cover the SAME trees, or one of them silently stops protecting a
    directory the other watches. Fail loudly rather than drift."""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "handoff_check", Path(__file__).with_name("handoff_check.py"))
    hc = ilu.module_from_spec(spec)
    spec.loader.exec_module(hc)
    mine = {d.rstrip("/") for d in BUILD_DIRS}
    theirs = {d.rstrip("/") for d in hc.BUILD_DIRS}
    if mine != theirs:
        raise SystemExit(
            "[rpa] BUILD_DIRS drifted from handoff_check.BUILD_DIRS: "
            f"only here={sorted(mine - theirs)} only there="
            f"{sorted(theirs - mine)}")


def sh(*a):
    return subprocess.run(
        a, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(REPO))


def sem_field(pattern, required=True):
    sem = (REPO / "hardware/reviews/SEMAPHORE.yaml").read_text(encoding="utf-8")
    m = re.search(pattern, sem)
    if not m and required:
        raise SystemExit(f"[rpa] SEMAPHORE.yaml lacks {pattern}")
    return m.group(1) if m else None


def is_generated(path):
    return any(path.startswith(d) for d in BUILD_DIRS)


def in_scope(path):
    if is_generated(path):
        return (f"generated artifact in a reviewer patch: {path} — a host "
                "fix must not change design output (zero-delta)")
    if any(path == d or path.startswith(d) for d in DENY):
        return f"denied path (design data / turn control): {path}"
    if not any(path.startswith(a) or path == a for a in ALLOW):
        return f"outside the allowed patch scope: {path}"
    return None


def _check_documentary_copies():
    """SEMAPHORE.yaml restates the epoch and the author list for humans.
    Documentation may not disagree with enforcement — and since the
    reviewer owns that file, a drift is exactly how the guard would be
    widened. Require equality; fail on any difference."""
    declared = sem_field(r"rpa_policy_base:\s*(\S+)", required=False)
    if declared and not POLICY_BASE.startswith(declared.rstrip(".")):
        raise SystemExit(
            f"[rpa] SEMAPHORE rpa_policy_base {declared!r} disagrees with the "
            f"pinned epoch {POLICY_BASE[:7]!r} — enforcement is pinned in "
            "reviewer_patch_check.py; fix the documentation, not the gate")
    da = sem_field(r"reviewer_git_authors:\s*\[([^\]]*)\]", required=False)
    if da is not None:
        got = tuple(s.strip() for s in da.split(",") if s.strip())
        if got != REVIEWER_AUTHORS:
            raise SystemExit(
                f"[rpa] SEMAPHORE reviewer_git_authors {list(got)} disagrees "
                f"with the pinned list {list(REVIEWER_AUTHORS)}")


def signed_off_by(packet_rel, line_no):
    """WHO is RECORDED as adding this RPA-ACCEPTED line. The packet is
    reviewer-writable — they add findings to it every turn — so the
    line's presence proves nothing; recorded authorship at least
    distinguishes the two actors (designer sweep after CP3 F14).
    Limit, stated deliberately: git author names are free-form, so this
    catches accidental self-acceptance, not a deliberate one (F15 /
    DR-34). Authenticating it needs signed commits and a key the
    reviewer cannot reach — a user decision, not an agent one."""
    r = sh("git", "blame", "--line-porcelain", "-L", f"{line_no},{line_no}",
           "HEAD", "--", packet_rel)
    if r.returncode != 0:
        return None
    m = re.search(r"^author (.+)$", r.stdout, re.M)
    return m.group(1) if m else None


def main():
    _assert_build_dirs_in_sync()
    _check_documentary_copies()
    rng = sys.argv[1] if len(sys.argv) > 1 else f"{POLICY_BASE}..HEAD"
    authors = list(REVIEWER_AUTHORS)
    packet_rel = sem_field(r"active_packet:\s*(\S+)")
    packet = REPO / packet_rel
    if sh("git", "ls-files", "--error-unmatch", "--",
          packet_rel).returncode != 0:
        raise SystemExit(f"[rpa] active_packet {packet_rel} is not tracked")
    ptext = packet.read_text(encoding="utf-8")

    def accepted_by_designer(pattern):
        """True only if a matching sign-off line exists AND a non-reviewer
        committed it."""
        for m in re.finditer(pattern, ptext, re.M):
            line_no = ptext.count("\n", 0, m.start()) + 1
            who = signed_off_by(packet_rel, line_no)
            if who is None:
                print(f"[rpa] INFO sign-off on packet line {line_no} is not "
                      "committed yet — commit the packet, then re-run")
                continue
            if who in authors:
                print(f"[rpa] VIOLATION sign-off on packet line {line_no} was "
                      f"written by {who!r}, a reviewer author — a patch "
                      "cannot accept itself; the designer must sign off")
                return False
            return True
        return False

    r = sh("git", "log", "--format=%H%x1f%an%x1f%P%x1f%B%x1e", rng)
    if r.returncode != 0:
        raise SystemExit(f"[rpa] bad range {rng}: {r.stderr.strip()}")
    violations, pending, scrutiny, patches = [], [], [], []

    for rec in [c for c in r.stdout.split("\x1e") if c.strip()]:
        sha, author, parents, body = rec.strip().split("\x1f", 3)
        short = sha[:7]
        if len(parents.split()) > 1:      # merges introduce no authored change
            continue
        files = sh("git", "show", "--name-only", "--format=", sha
                   ).stdout.split()
        trailer = re.search(r"^Reviewer-Patch:\s*(\S+)", body, re.M)
        # "code" = product/tool source, NOT the reviewer's own evidence
        # programs under visual_inspections (F11)
        code = [f for f in files
                if not f.startswith(EVIDENCE)
                and (f.endswith(".py") or f in (".gitattributes", ".gitignore"))]

        if author not in authors:
            if trailer:
                violations.append(
                    f"{short}: Reviewer-Patch trailer on a commit by "
                    f"{author!r}, who is not a reviewer author")
            continue
        if not trailer:
            if not code:
                continue
            # A patch can be legitimized after the fact: the designer
            # re-reviews it and signs off by sha — the same scrutiny a
            # trailered patch gets.
            if accepted_by_designer(rf"^RPA-ACCEPTED:\s*\S+\s+{short}"):
                print(f"[rpa] INFO {short}: untrailered reviewer patch, "
                      "accepted retroactively by designer sign-off")
                continue
            violations.append(
                f"{short}: reviewer commit changes code {code} with no "
                "Reviewer-Patch trailer — an untrailered fix is an "
                "unreviewed one (REVIEWER_PATCH_POLICY.md). If this "
                "predates the policy or was authorized ad hoc, re-review "
                f"it and add `RPA-ACCEPTED: <finding> {short}` to the packet.")
            continue

        fid = trailer.group(1)
        patches.append((short, fid))
        if not re.search(r"^Patch-Reason:\s*\S", body, re.M):
            violations.append(f"{short}: Reviewer-Patch without Patch-Reason")
        # accept either the short token (F11) or the packet's prose form
        # ("Finding 11") — the ids are written both ways by both agents,
        # and a gate that only knows one spelling fails on a real patch
        num = re.match(r"F(\d+)$", fid)
        forms = [re.escape(fid)] + ([rf"Finding\s+0*{num.group(1)}\b"]
                                    if num else [])
        if not any(re.search(f, ptext, re.I) for f in forms):
            violations.append(
                f"{short}: finding {fid} not found in the active packet")
        for f in files:
            why = in_scope(f)
            if why:
                violations.append(f"{short} ({fid}): {why}")
        if not any(f.startswith(EVIDENCE) for f in files):
            violations.append(
                f"{short} ({fid}): no host evidence committed under "
                f"{EVIDENCE} — a patch the designer cannot check on the "
                "host where it matters is not reviewable")
        touched_self = [f for f in files if f in SELF]
        if touched_self:
            scrutiny.append(
                f"{short} ({fid}): patches the enforcement mechanism itself "
                f"{touched_self} — legitimate (that code is host-sensitive "
                "too), but read this diff line by line before signing off: "
                "it can weaken every check above.")

        # zero-delta: no generated artifact may differ commit^ -> commit
        changed = sh("git", "diff", "--name-only", f"{sha}^", sha).stdout.split()
        moved = [f for f in changed if is_generated(f)]
        if moved:
            violations.append(
                f"{short} ({fid}): ZERO-DELTA BREACH — generated artifacts "
                f"differ from the parent commit: {moved}. A host fix must "
                "not change design output; file this as a finding instead.")

        if not accepted_by_designer(
                rf"^RPA-ACCEPTED:\s*{re.escape(fid)}\s+{short}"):
            pending.append(
                f"{short} ({fid}): awaiting designer sign-off — add "
                f"`RPA-ACCEPTED: {fid} {short}` to the packet response "
                "after re-reviewing the patch")

    for s in scrutiny:
        print(f"[rpa] SCRUTINY {s}")
    for v in violations:
        print(f"[rpa] VIOLATION {v}")
    for p in pending:
        print(f"[rpa] PENDING {p}")
    if violations:
        print(f"RPA: VIOLATION ({len(violations)})")
        return 1
    if pending:
        print(f"RPA: PENDING ({len(pending)})")
        return 2
    print(f"RPA: clean — {len(patches)} reviewer patch(es) in {rng}, "
          "all in scope, zero-delta, accepted"
          if patches else f"RPA: clean — no reviewer patches in {rng}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
