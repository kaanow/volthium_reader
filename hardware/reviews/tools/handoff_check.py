#!/usr/bin/env python3
"""Pre-handoff gate: no semaphore flip to reviewer_turn without this at 0.

Born from CP3 F01: verification done DURING work went stale by handoff —
regenerated artifacts drifted from committed ones, and packet hashes
recorded early were never refreshed. With deterministic builds
(uuid5 sequences, pinned tedit/date stamps) staleness is now a checkable
property:

  1. rebuild every generator (battery sch, display sch, battery pcb)
  2. every deterministic artifact the rebuild produced must be TRACKED
     by git — an ignored/untracked input (CP3 finding 05: the pcb build
     consumed an ignored netlist) is invisible to `git status` and
     absent in a fresh clone, so "committed" claims about it are void
  3. compare every rebuilt artifact byte-for-byte with its HEAD blob —
     ANY difference means the committed artifacts don't match the
     committed generators: FAIL
  4. every 12-hex hash quoted in the active packet must match the
     file's HEAD BLOB — not its worktree bytes. The reviewer checks out
     the blob; worktree bytes are host-dependent (CP3 finding 06: the
     reviewer's autocrlf worktree hashed differently from the
     byte-identical committed board). The cited file must also be
     tracked and unmodified, else the HEAD blob isn't what's on disk.
  5. doc_consistency_check must be clean

Run from the repo root AFTER committing, right before the semaphore
flip. Renders/PNGs/PDFs are volatile (tool timestamps) and excluded
from the diff check — their CONTENT is gated in-build.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VENV_POSIX = REPO / ".venv/bin/python"
VENV_WIN = REPO / ".venv/Scripts/python.exe"
PY = str(VENV_WIN if os.name == "nt" else VENV_POSIX)

BUILDS = [
    REPO / "hardware/kicad/schematic/build.py",
    REPO / "hardware/kicad/schematic/build_display.py",
    REPO / "hardware/kicad/pcb/build.py",
]
# deterministic source-of-truth artifacts; renders are volatile
DETERMINISTIC_GLOBS = ["*.kicad_sch", "*.net", "*.kicad_pcb", "*.kicad_pro",
                       "*.kicad_sym", "*.kicad_dru", "fp-lib-table"]
BUILD_DIRS = ["hardware/kicad/schematic/build",
              "hardware/kicad/schematic/build_display",
              "hardware/kicad/pcb/build"]


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def head_blob(rel):
    r = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "blob", f"HEAD:{rel}"],
        capture_output=True)
    return r.stdout if r.returncode == 0 else None


def main():
    fails = []
    env = dict(os.environ, SKIP_RENDER="1")
    for b in BUILDS:
        r = sh(PY, str(b), env=env)
        tag = b.parent.name + "/" + b.name
        if r.returncode != 0:
            fails.append(f"[rebuild] {tag} rc={r.returncode}")
            print(r.stdout[-500:])
        else:
            print(f"[rebuild] {tag}: rc=0")
    if fails:
        print("\n".join(fails))
        print("HANDOFF: FAIL (rebuild)")
        return 1

    paths = []
    for d in BUILD_DIRS:
        for g in DETERMINISTIC_GLOBS:
            paths += [p.relative_to(REPO).as_posix()
                      for p in (REPO / d).glob(g)]
    tracked = set(sh("git", "-C", str(REPO), "ls-files", "--",
                     *paths).stdout.splitlines())
    untracked = sorted(set(paths) - tracked)
    if untracked:
        fails.append("[untracked] deterministic artifacts a fresh clone "
                     "won't have (ignored or never added):\n  "
                     + "\n  ".join(untracked))
    stale = []
    for rel in paths:
        if rel in untracked:
            continue
        blob = head_blob(rel)
        worktree = REPO / rel
        if blob is None or not worktree.exists() or \
                worktree.read_bytes() != blob:
            stale.append(rel)
    if stale:
        fails.append("[stale] rebuilt artifacts differ byte-for-byte "
                     "from their HEAD blobs:\n  " + "\n  ".join(stale))

    sem = (REPO / "hardware/reviews/SEMAPHORE.yaml").read_text(
        encoding="utf-8")
    pm = re.search(r"active_packet:\s*(\S+)", sem)
    packet = REPO / pm.group(1)
    ptext = packet.read_text(encoding="utf-8")
    for m in re.finditer(r"`([\w./-]+)`\s*\n?\s*\(sha256 `([0-9a-f]{12})…?`",
                         ptext):
        rel = m.group(1)
        if sh("git", "-C", str(REPO), "ls-files", "--error-unmatch", "--",
              rel).returncode != 0:
            fails.append(f"[hash] packet cites UNTRACKED file {rel} — "
                         "a hash claim about a file git doesn't have is "
                         "unverifiable by the reviewer")
            continue
        blob = head_blob(rel)
        f = REPO / rel
        if blob is None or not f.exists() or f.read_bytes() != blob:
            fails.append(f"[hash] {rel} differs byte-for-byte from HEAD — "
                         "commit the current deterministic artifact before "
                         "hashing; the packet must describe HEAD")
            continue
        # hash the HEAD blob (what a checkout delivers), never worktree
        # bytes — those vary with the host's eol config
        actual = hashlib.sha256(blob).hexdigest()[:12]
        if actual != m.group(2):
            fails.append(f"[hash] packet hash {m.group(2)} != HEAD blob "
                         f"{actual} for {rel}")

    r = sh(PY, str(REPO / "hardware/reviews/tools/"
                    "doc_consistency_check.py"))
    if r.returncode != 0:
        fails.append("[consistency] doc_consistency_check failed:\n"
                     + r.stdout[-400:])

    if fails:
        print("\n".join(fails))
        print("HANDOFF: FAIL")
        return 1
    print("HANDOFF: CLEAN — artifacts fresh, hashes true, consistency ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
