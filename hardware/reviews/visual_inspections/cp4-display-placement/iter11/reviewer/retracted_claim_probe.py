"""Independent positive/negative controls for check_retracted_claims()."""

from pathlib import Path
import sys
import tempfile


REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "hardware" / "reviews" / "tools"))

import doc_consistency_check as check  # noqa: E402


def run_case(name: str, text: str, under_reviewer: bool = False) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        role = "reviewer" if under_reviewer else "designer"
        path = root / "hardware" / "reviews" / "visual_inspections" / role / "claim.txt"
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        original_repo = check.REPO
        try:
            check.REPO = root
            findings = check.check_retracted_claims()
        finally:
            check.REPO = original_repo
        print(f"{name}: findings={len(findings)}")
        for finding in findings:
            print("  " + finding.replace("\n", "\n  "))


run_case("unmarked", "Two real defects\n")
run_case("marked", "*** SUPERSEDED: false conclusion below ***\nTwo real defects\n")
run_case("reviewer-excluded", "Two real defects\n", under_reviewer=True)
