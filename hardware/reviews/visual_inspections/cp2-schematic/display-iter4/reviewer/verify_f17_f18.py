"""Independent reviewer verification for display-iter4 F17/F18 fixes."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
SCHEMATIC = REPO / "hardware" / "kicad" / "schematic"
PRIOR = (
    REPO
    / "hardware"
    / "reviews"
    / "visual_inspections"
    / "cp2-schematic"
    / "display-iter3"
    / "reviewer"
)

sys.path.insert(0, str(SCHEMATIC))
import core  # noqa: E402


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


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one replacement target, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("KICAD_CLI", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR"):
        env.pop(name, None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_build(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "build_display.py"],
        cwd=tree / "schematic",
        env=build_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def main() -> int:
    lines: list[str] = []
    failures: list[str] = []
    fixture_names = (
        "poison_pdf_battery_sheet_conn.pdf",
        "poison_pdf_display_sheet_d_conn.pdf",
    )

    lines.append("F17 FIXTURE IDENTITY AND THRESHOLD HOLD")
    for fixture_name in fixture_names:
        fixture = SCHEMATIC / "testdata" / fixture_name
        prior = PRIOR / fixture_name
        current_hash = digest(fixture)
        prior_hash = digest(prior)
        at_045 = core._pdf_text_collisions(fixture, thresh_mm=0.45)
        at_050 = core._pdf_text_collisions(fixture, thresh_mm=0.50)
        intended = (
            len(at_045) == 2
            and all("SHIELD" in item and "GND" in item for item in at_045)
        )
        identity = current_hash == prior_hash
        held = intended and len(at_050) != 2
        lines.extend(
            (
                f"{fixture_name}:",
                f"  sha256={current_hash}",
                f"  exact_prior_reviewer_fixture={identity}",
                f"  threshold_0.45_findings={len(at_045)}",
            )
        )
        lines.extend(f"    {item}" for item in at_045)
        lines.append(f"  threshold_0.50_findings={len(at_050)}")
        lines.extend(f"    {item}" for item in at_050)
        lines.append(f"  intended_pair_identity={intended}")
        lines.append(f"  threshold_hold_is_load_bearing={held}")
        if not (identity and held):
            failures.append(f"fixture threshold/identity: {fixture_name}")

    lines.append("")
    lines.append("F18 CHECKED-EXPORT UNIT POISONS")
    original_kcli = core.kcli
    try:
        with tempfile.TemporaryDirectory(prefix="checked-export-unit-") as raw_tmp:
            tmp = Path(raw_tmp)
            target = tmp / "out.pdf"
            source = tmp / "source.kicad_sch"

            target.write_bytes(b"%PDF-stale")
            core.kcli = lambda *args: subprocess.CompletedProcess(args, 97, "", "fail")
            nonzero_ok = core._checked_pdf_export(source, target)
            nonzero_pass = not nonzero_ok and not target.exists()
            lines.append(
                "nonzero_exit_with_preseeded_stale: "
                f"accepted={nonzero_ok} target_exists={target.exists()} "
                f"expected_rejection={nonzero_pass}"
            )
            if not nonzero_pass:
                failures.append("nonzero export rejection")

            target.write_bytes(b"%PDF-stale")
            core.kcli = lambda *args: subprocess.CompletedProcess(args, 0, "", "")
            zero_no_write_ok = core._checked_pdf_export(source, target)
            zero_no_write_pass = not zero_no_write_ok and not target.exists()
            lines.append(
                "zero_exit_without_new_artifact: "
                f"accepted={zero_no_write_ok} target_exists={target.exists()} "
                f"expected_rejection={zero_no_write_pass}"
            )
            if not zero_no_write_pass:
                failures.append("rc0/no-output export rejection")

            def successful_export(*args: str) -> subprocess.CompletedProcess[str]:
                output = Path(args[args.index("-o") + 1])
                output.write_bytes(b"%PDF-fresh")
                return subprocess.CompletedProcess(args, 0, "", "")

            core.kcli = successful_export
            success_ok = core._checked_pdf_export(source, target)
            success_pass = success_ok and target.read_bytes() == b"%PDF-fresh"
            lines.append(
                "zero_exit_with_new_nonempty_artifact: "
                f"accepted={success_ok} bytes={target.stat().st_size} "
                f"expected_acceptance={success_pass}"
            )
            if not success_pass:
                failures.append("fresh export acceptance")
    finally:
        core.kcli = original_kcli

    with tempfile.TemporaryDirectory(prefix="f17-f18-build-poison-") as raw_tmp:
        tmp = Path(raw_tmp)
        source = REPO / "hardware" / "kicad"

        threshold_tree = tmp / "threshold" / "kicad"
        shutil.copytree(
            source,
            threshold_tree,
            ignore=shutil.ignore_patterns("build", "build_display", "__pycache__"),
        )
        threshold_core = threshold_tree / "schematic" / "core.py"
        replace_once(
            threshold_core,
            "def _pdf_text_collisions(pdf, thresh_mm=0.45):",
            "def _pdf_text_collisions(pdf, thresh_mm=0.50):",
        )
        threshold_result = run_build(threshold_tree)
        threshold_marker = "threshold/gate regression (F17)" in threshold_result.stdout
        threshold_build_pass = threshold_result.returncode == 2 and threshold_marker
        lines.extend(
            (
                "",
                "F17 WHOLE-BUILD THRESHOLD POISON",
                f"returncode={threshold_result.returncode}",
                f"regression_marker={threshold_marker}",
                f"expected_rejection={threshold_build_pass}",
                "----- stdout -----",
                threshold_result.stdout.rstrip(),
                "----- stderr -----",
                threshold_result.stderr.rstrip(),
            )
        )
        if not threshold_build_pass:
            failures.append("whole-build threshold poison")

        export_tree = tmp / "export" / "kicad"
        shutil.copytree(source, export_tree)
        export_core = export_tree / "schematic" / "core.py"
        replace_once(export_core, OLD_KCLI, POISONED_KCLI)
        stale = export_tree / "schematic" / "build_display" / "sheet_d_conn.pdf"
        before_hash = digest(stale)
        export_result = run_build(export_tree)
        forced = export_result.stdout.count("[poison] forced PDF export failure:")
        clean = export_result.stdout.count("pdf-text gate: clean")
        stale_removed = not stale.exists()
        export_build_pass = (
            export_result.returncode == 2
            and forced == 5
            and clean == 0
            and stale_removed
            and "[NETLIST gate] SKIPPED" in export_result.stdout
        )
        lines.extend(
            (
                "",
                "F18 WHOLE-BUILD FORCED EXPORT FAILURE",
                f"preseeded_conn_sha256={before_hash}",
                f"returncode={export_result.returncode}",
                f"forced_pdf_failures={forced}",
                f"pdf_text_clean_markers={clean}",
                f"stale_conn_removed={stale_removed}",
                f"netlist_skipped={'[NETLIST gate] SKIPPED' in export_result.stdout}",
                f"expected_rejection={export_build_pass}",
                "----- stdout -----",
                export_result.stdout.rstrip(),
                "----- stderr -----",
                export_result.stderr.rstrip(),
            )
        )
        if not export_build_pass:
            failures.append("whole-build export poison")

    lines.extend(("", f"OVERALL={'FAIL' if failures else 'PASS'}"))
    if failures:
        lines.append("unexpected=" + ", ".join(failures))
    output = "\n".join(lines) + "\n"
    (HERE / "verify_f17_f18.txt").write_text(
        output, encoding="utf-8", newline="\n"
    )
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(output, end="")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
