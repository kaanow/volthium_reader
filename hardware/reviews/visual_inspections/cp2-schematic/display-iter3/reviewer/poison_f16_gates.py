"""Independent F16 poison tests for the analytic and rendered-text gates."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import fitz


OLD_SHIELD = '(pin passive line (at -10.16 -15.24 0) (length 2.54)'
NEW_SHIELD = '(pin passive line (at -10.16 -12.7 0) (length 2.54)'


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def make_tree(source: Path, destination: Path, permissive_analytic: bool) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("build", "build_display", "__pycache__"),
    )
    replace_once(
        destination / "libraries" / "volthium.kicad_sym",
        NEW_SHIELD,
        OLD_SHIELD,
    )
    if permissive_analytic:
        core = destination / "schematic" / "core.py"
        replace_once(core, "GLYPH_ADV = 1.29", "GLYPH_ADV = 0.85")
        replace_once(core, "GLYPH_H = 1.91", "GLYPH_H = 1.27")


def run_build(tree: Path, entrypoint: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in ("KICAD_CLI", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR"):
        env.pop(name, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, entrypoint],
        cwd=tree / "schematic",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def save_log(path: Path, result: subprocess.CompletedProcess[str]) -> str:
    body = (
        f"command_returncode={result.returncode}\n"
        "----- stdout -----\n"
        f"{result.stdout}"
        "----- stderr -----\n"
        f"{result.stderr}"
    )
    path.write_text(body, encoding="utf-8", newline="\n")
    return body


def measure_shield_gnd(pdf: Path) -> list[str]:
    doc = fitz.open(pdf)
    seen: set[tuple[float, float, float, float, str]] = set()
    words: list[tuple[float, float, float, float, str]] = []
    for raw in doc[0].get_text("words"):
        word = (raw[0], raw[1], raw[2], raw[3], raw[4])
        key = (
            round(word[0], 2),
            round(word[1], 2),
            round(word[2], 2),
            round(word[3], 2),
            word[4],
        )
        if key not in seen:
            seen.add(key)
            words.append(word)
    lines: list[str] = []
    for shield in (word for word in words if word[4] == "SHIELD"):
        for gnd in (word for word in words if word[4] == "GND"):
            ox = min(shield[2], gnd[2]) - max(shield[0], gnd[0])
            oy = min(shield[3], gnd[3]) - max(shield[1], gnd[1])
            if ox > 0 and oy > 0:
                lines.append(
                    f"SHIELD x GND overlap={ox / 2.8346:.3f} x "
                    f"{oy / 2.8346:.3f} mm; "
                    f"SHIELD={tuple(round(v, 2) for v in shield[:4])}; "
                    f"GND={tuple(round(v, 2) for v in gnd[:4])}"
                )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    source = args.repo.resolve() / "hardware" / "kicad"
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    summary: list[str] = []
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="f16-poison-") as raw_tmp:
        tmp = Path(raw_tmp)
        cases = (
            ("analytic", False, "READABILITY GATE FAILED", "[glyph-glyph]"),
            ("pdf", True, "PDF-TEXT GATE FAILED", "[pdf-text]"),
        )
        builds = (
            ("battery", "build.py"),
            ("display", "build_display.py"),
        )
        for case_name, permissive, gate_marker, finding_marker in cases:
            tree = tmp / case_name / "kicad"
            make_tree(source, tree, permissive)
            for board_name, entrypoint in builds:
                result = run_build(tree, entrypoint)
                body = save_log(
                    evidence / f"poison_{case_name}_{board_name}.txt",
                    result,
                )
                gate_count = body.count(gate_marker)
                finding_lines = [
                    line.strip()
                    for line in body.splitlines()
                    if finding_marker in line
                ]
                skipped = "[NETLIST gate] SKIPPED" in body
                passed = (
                    result.returncode != 0
                    and gate_count == 1
                    and len(finding_lines) == 2
                    and skipped
                )
                summary.append(
                    f"{case_name}/{board_name}: rc={result.returncode}, "
                    f"gate_markers={gate_count}, findings={len(finding_lines)}, "
                    f"netlist_skipped={skipped}, expected_failure={passed}"
                )
                summary.extend(f"  {line}" for line in finding_lines)
                if case_name == "pdf":
                    out_dir = tree / "schematic" / (
                        "build" if board_name == "battery" else "build_display"
                    )
                    child = (
                        "sheet_conn" if board_name == "battery" else "sheet_d_conn"
                    )
                    for suffix in (".kicad_sch", ".pdf", ".png"):
                        source_artifact = out_dir / f"{child}{suffix}"
                        if source_artifact.exists():
                            shutil.copy2(
                                source_artifact,
                                evidence / f"poison_pdf_{board_name}_{child}{suffix}",
                            )
                    pdf = out_dir / f"{child}.pdf"
                    measured = measure_shield_gnd(pdf) if pdf.exists() else []
                    summary.append(
                        f"  rendered_SHIELD_GND_intersections={len(measured)}"
                    )
                    summary.extend(f"  {line}" for line in measured)
                if not passed:
                    failures.append(f"{case_name}/{board_name}")

    summary.append(f"overall={'FAIL' if failures else 'PASS'}")
    if failures:
        summary.append("unexpected cases=" + ", ".join(failures))
    output = "\n".join(summary) + "\n"
    (evidence / "poison_f16_summary.txt").write_text(
        output, encoding="utf-8", newline="\n"
    )
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(output, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
