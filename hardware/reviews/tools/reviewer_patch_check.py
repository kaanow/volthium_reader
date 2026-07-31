#!/usr/bin/env python3
"""Reviewer Patch Authority gate — see ../REVIEWER_PATCH_POLICY.md.

Bounded write access for the reviewer is only safe if its boundary is
mechanical. This checks every reviewer-authored commit in a range:

  1. code changes by a reviewer author MUST carry `Reviewer-Patch: <id>`
     (an untrailered fix is an unreviewed one)
  2. the finding id must exist in the active packet
  3. changed paths within the allowed scope, none in the denied set
  4. ZERO-DELTA: no deterministic design artifact differs between the
     patch commit and its parent — a host-adaptation fix changes how
     bytes are written, never what they say. This is the invariant that
     makes the whole mechanism safe.
  5. designer sign-off `RPA-ACCEPTED: <id> <sha>` present in the packet

Exit 0 clean · 1 VIOLATION (scope/invariant breach) · 2 PENDING
(a valid patch awaiting designer acceptance).

Usage: reviewer_patch_check.py [<git-range>]   (default: origin/main..HEAD)
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

ALLOW = [
    "hardware/kicad/",          # generator/tool python (see DENY + zero-delta)
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
]
# generated artifacts: a correct patch never contains one (zero-delta)
ARTIFACT_SUFFIXES = (".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_sym",
                     ".kicad_dru", ".net")


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, cwd=str(REPO))


def reviewer_authors():
    sem = (REPO / "hardware/reviews/SEMAPHORE.yaml").read_text(
        encoding="utf-8")
    m = re.search(r"reviewer_git_authors:\s*\[([^\]]*)\]", sem)
    if not m:
        raise SystemExit("[rpa] SEMAPHORE.yaml lacks reviewer_git_authors")
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


def packet_path():
    sem = (REPO / "hardware/reviews/SEMAPHORE.yaml").read_text(
        encoding="utf-8")
    return REPO / re.search(r"active_packet:\s*(\S+)", sem).group(1)


def in_scope(path):
    if any(path == d or path.startswith(d) for d in DENY):
        return f"denied path (design data / turn control): {path}"
    if path.endswith(ARTIFACT_SUFFIXES):
        return (f"generated artifact in a reviewer patch: {path} — a "
                "host fix must not change design output (zero-delta)")
    if not any(path.startswith(a) or path == a for a in ALLOW):
        return f"outside the allowed patch scope: {path}"
    return None


def main():
    rng = sys.argv[1] if len(sys.argv) > 1 else "origin/main..HEAD"
    authors = reviewer_authors()
    ptext = packet_path().read_text(encoding="utf-8")

    r = sh("git", "log", "--format=%H%x1f%an%x1f%B%x1e", rng)
    if r.returncode != 0:
        raise SystemExit(f"[rpa] bad range {rng}: {r.stderr.strip()}")
    violations, pending, patches = [], [], []

    for rec in [c for c in r.stdout.split("\x1e") if c.strip()]:
        sha, author, body = rec.strip().split("\x1f", 2)
        short = sha[:7]
        files = sh("git", "show", "--name-only", "--format=", sha
                   ).stdout.split()
        trailer = re.search(r"^Reviewer-Patch:\s*(\S+)", body, re.M)
        code = [f for f in files
                if f.endswith(".py") or f in (".gitattributes", ".gitignore")]

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
            # re-reviews it and signs off by sha. That is the same
            # scrutiny a trailered patch gets, so it closes the gap —
            # it also covers patches predating this policy.
            if re.search(rf"^RPA-ACCEPTED:\s*\S+\s+{short}", ptext, re.M):
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
        if fid not in ptext:
            violations.append(
                f"{short}: finding {fid} not found in the active packet")
        for f in files:
            why = in_scope(f)
            if why:
                violations.append(f"{short} ({fid}): {why}")

        # zero-delta: no deterministic artifact may differ commit^ -> commit
        changed = sh("git", "diff", "--name-only", f"{sha}^", sha).stdout.split()
        moved = [f for f in changed if f.endswith(ARTIFACT_SUFFIXES)]
        if moved:
            violations.append(
                f"{short} ({fid}): ZERO-DELTA BREACH — design artifacts "
                f"differ from the parent commit: {moved}. A host fix must "
                "not change design output; file this as a finding instead.")

        if not re.search(rf"^RPA-ACCEPTED:\s*{re.escape(fid)}\s+{short}",
                         ptext, re.M):
            pending.append(
                f"{short} ({fid}): awaiting designer sign-off — add "
                f"`RPA-ACCEPTED: {fid} {short}` to the packet response "
                "after re-reviewing the patch")

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
