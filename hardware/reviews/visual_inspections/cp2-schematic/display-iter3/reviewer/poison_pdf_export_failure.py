"""Show whether failed KiCad PDF exports can be accepted from stale artifacts."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


OLD_KCLI = """def kcli(*a):
    return subprocess.run([str(KICAD_CLI), *a], capture_output=True, text=True)
"""
POISONED_KCLI = """def kcli(*a):
    if len(a) >= 3 and tuple(a[:3]) == ("sch", "export", "pdf"):
        print(f"[poison] forced PDF export failure: {' '.join(a)}")
        return subprocess.CompletedProcess(a, 97, "", "intentional PDF export failure")
    return subprocess.run([str(KICAD_CLI), *a], capture_output=True, text=True)
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    evidence = args.evidence_dir.resolve()
    source = repo / "hardware" / "kicad"
    with tempfile.TemporaryDirectory(prefix="pdf-export-poison-") as raw_tmp:
        tree = Path(raw_tmp) / "kicad"
        shutil.copytree(source, tree)
        core = tree / "schematic" / "core.py"
        text = core.read_text(encoding="utf-8")
        if text.count(OLD_KCLI) != 1:
            raise RuntimeError("expected exactly one kcli definition")
        core.write_text(
            text.replace(OLD_KCLI, POISONED_KCLI),
            encoding="utf-8",
            newline="\n",
        )

        conn_pdf = tree / "schematic" / "build_display" / "sheet_d_conn.pdf"
        before_hash = digest(conn_pdf)
        env = os.environ.copy()
        for name in ("KICAD_CLI", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR"):
            env.pop(name, None)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "build_display.py"],
            cwd=tree / "schematic",
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        after_hash = digest(conn_pdf)

    forced_failures = result.stdout.count("[poison] forced PDF export failure:")
    clean_markers = result.stdout.count("pdf-text gate: clean")
    stale_accepted = (
        result.returncode == 0
        and forced_failures == 5
        and clean_markers == 4
        and before_hash == after_hash
    )
    output = (
        f"build_returncode={result.returncode}\n"
        f"forced_pdf_export_failures={forced_failures}\n"
        f"child_pdf_text_clean_markers={clean_markers}\n"
        f"stale_conn_pdf_hash_unchanged={before_hash == after_hash}\n"
        f"stale_pdf_failure_accepted={stale_accepted}\n"
        "----- stdout -----\n"
        f"{result.stdout}"
        "----- stderr -----\n"
        f"{result.stderr}"
    )
    (evidence / "poison_pdf_export_failure.txt").write_text(
        output, encoding="utf-8", newline="\n"
    )
    print(output)
    return 1 if stale_accepted else 0


if __name__ == "__main__":
    raise SystemExit(main())
