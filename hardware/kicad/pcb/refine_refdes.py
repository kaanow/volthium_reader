"""Empirical refdes refinement: DRC is the glyph-geometry oracle.

The placer's analytic text-box model approximates KiCad's stroke font;
rather than hand-tuning the model against every descender and
underscore, this loop lets the REAL geometry judge: build, read the DRC
silk findings, ban each refuted refdes position, rebuild. Converges to
zero silk findings or reports the refs that ran out of candidates.
The final ban set persists in build/refdes_bans.json (committed — it is
placement data, like the manual spots).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANS = HERE / "build" / "refdes_bans.json"
RPT = HERE / "build" / "drc.rpt"
PY = sys.executable


def silk_ref_findings():
    text = RPT.read_text(encoding="utf-8")
    out = []
    blocks = re.split(r'\n(?=\[)', text)
    for b in blocks:
        if not b.startswith(("[silk_overlap]", "[silk_over_copper]")):
            continue
        for m in re.finditer(
                r'@\(([\d.]+) mm, ([\d.]+) mm\): Reference field of (\S+)', b):
            out.append((m.group(3), float(m.group(1)), float(m.group(2))))
    return out


def main():
    bans = {}
    if BANS.exists():
        bans = json.loads(BANS.read_text(encoding="utf-8"))
    env = dict(os.environ, SKIP_RENDER="1")
    for it in range(1, 15):
        RPT.unlink(missing_ok=True)   # transactional: never judge a stale report
        r = subprocess.run([PY, str(HERE / "build.py")], env=env,
                           capture_output=True, text=True)
        # label-adjacency findings fail the build BEFORE DRC — parse them
        # from stdout and ban both partners' positions
        adj = re.findall(
            r"\[label-adjacency\] (\S+)@\(([\d.]+),([\d.]+)\) x "
            r"(\S+)@\(([\d.]+),([\d.]+)\)", r.stdout)
        other = [l for l in r.stdout.splitlines()
                 if l.strip().startswith("[")
                 and "[label-adjacency]" not in l and "refdes]" not in l]
        if other:
            print(f"iter {it}: NON-adjacency gate findings present "
                  f"(fix before/with label work):")
            print("\n".join(other[:10]))
        if adj:
            newban = 0
            for ra, xa, ya, rb, xb, yb in adj:
                for ref, x, y in ((ra, float(xa), float(ya)),
                                  (rb, float(xb), float(yb))):
                    lst = bans.setdefault(ref, [])
                    if [x, y] not in lst:
                        lst.append([x, y])
                        newban += 1
            with BANS.open("w", encoding="utf-8", newline="\n") as _f:
                _f.write(json.dumps(bans, indent=1))
            print(f"iter {it}: {len(adj)} label-adjacency pair(s), "
                  f"banned {newban} spots: "
                  f"{sorted({p[0] for p in adj} | {p[3] for p in adj})}")
            if not newban:
                print("  adjacency pairs immovable (manual/fallback) — "
                      "hand attention needed:")
                for ra, xa, ya, rb, xb, yb in adj:
                    print(f"    {ra} x {rb}")
                return
            continue
        if not RPT.exists():
            print(f"iter {it}: build died BEFORE DRC (rc={r.returncode}) — "
                  "gate findings:")
            print("\n".join(l for l in r.stdout.splitlines()
                            if l.strip().startswith("[")) or r.stdout[-400:])
            return
        finds = silk_ref_findings()
        n_silk = sum(1 for line in RPT.read_text(encoding="utf-8").splitlines()
                     if line.startswith(("[silk_overlap]",
                                         "[silk_over_copper]")))
        print(f"iter {it}: rc={r.returncode} silk={n_silk} "
              f"ref-findings={len(finds)}")
        if not finds:
            if n_silk:
                print("non-refdes silk findings remain:")
                print("\n".join(l for l in RPT.read_text(encoding="utf-8").splitlines()
                                if l.startswith("[silk_")))
            break
        newban = 0
        for ref, x, y in finds:
            lst = bans.setdefault(ref, [])
            if [x, y] not in lst:
                lst.append([x, y])
                newban += 1
        with BANS.open("w", encoding="utf-8", newline="\n") as _f:
            _f.write(json.dumps(bans, indent=1))
        print(f"  banned {newban} new spots: "
              f"{sorted({f[0] for f in finds})}")
        if not newban:
            print("  no new bans possible — stuck; manual attention needed")
            break
    # final full build with renders
    r = subprocess.run([PY, str(HERE / "build.py")], capture_output=True,
                       text=True)
    print("final build rc:", r.returncode)
    print(r.stdout[-600:])


if __name__ == "__main__":
    main()
