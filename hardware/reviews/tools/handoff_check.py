#!/usr/bin/env python3
"""Pre-handoff gate: no semaphore flip to reviewer_turn without this at 0.

Born from CP3 F01: verification done DURING work went stale by handoff —
regenerated artifacts drifted from committed ones, and packet hashes
recorded early were never refreshed. With deterministic builds
(uuid5 sequences, pinned tedit/date stamps) staleness is now a checkable
property:

  1. rebuild every generator (battery sch, display sch, battery pcb)
  2. `git status` on the build trees — ANY diff means the committed
     artifacts don't match the committed generators: FAIL
  3. every 12-hex hash quoted in the active packet must match a real
     committed file: FAIL otherwise
  4. doc_consistency_check must be clean

Run from the repo root. Renders/PNGs/PDFs are volatile (tool timestamps)
and excluded from the diff check — their CONTENT is gated in-build.
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
            paths += [str(p.relative_to(REPO))
                      for p in (REPO / d).glob(g)]
    r = sh("git", "-C", str(REPO), "status", "--porcelain", "--", *paths)
    if r.stdout.strip():
        fails.append("[stale] committed artifacts differ from a fresh "
                     "rebuild of the committed generators:\n" + r.stdout)

    sem = (REPO / "hardware/reviews/SEMAPHORE.yaml").read_text(
        encoding="utf-8")
    pm = re.search(r"active_packet:\s*(\S+)", sem)
    packet = REPO / pm.group(1)
    ptext = packet.read_text(encoding="utf-8")
    for m in re.finditer(r"`([\w./-]+)`\s*\n?\s*\(sha256 `([0-9a-f]{12})…?`",
                         ptext):
        f = REPO / m.group(1)
        if not f.exists():
            fails.append(f"[hash] packet cites missing file {m.group(1)}")
            continue
        actual = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        if actual != m.group(2):
            fails.append(f"[hash] packet hash {m.group(2)} != actual "
                         f"{actual} for {m.group(1)}")

    r = sh("python3", str(REPO / "hardware/reviews/tools/"
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
