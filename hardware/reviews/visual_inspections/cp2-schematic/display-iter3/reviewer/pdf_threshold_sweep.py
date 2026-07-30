"""Sweep the PDF collision threshold over current and known-bad child sheets."""

from __future__ import annotations

import itertools
from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
MM = 2.8346
THRESHOLDS = (0.40, 0.42, 0.45, 0.48, 0.49, 0.50)


def unique_words(pdf: Path) -> list[tuple]:
    words: list[tuple] = []
    seen: set[tuple] = set()
    with fitz.open(pdf) as document:
        for word in document[0].get_text("words"):
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
    return words


def collisions(pdf: Path, threshold_mm: float) -> list[str]:
    threshold = threshold_mm * MM
    findings: list[str] = []
    for left, right in itertools.combinations(unique_words(pdf), 2):
        ox = min(left[2], right[2]) - max(left[0], right[0])
        oy = min(left[3], right[3]) - max(left[1], right[1])
        if ox > threshold and oy > threshold:
            findings.append(
                f"{pdf.name}: {left[4]!r} x {right[4]!r} "
                f"{ox / MM:.3f} x {oy / MM:.3f} mm"
            )
    return findings


current = sorted(
    (
        *(
            REPO / "hardware" / "kicad" / "schematic" / "build"
        ).glob("sheet_*.pdf"),
        *(
            REPO / "hardware" / "kicad" / "schematic" / "build_display"
        ).glob("sheet_*.pdf"),
    )
)
poison = (
    HERE / "poison_pdf_battery_sheet_conn.pdf",
    HERE / "poison_pdf_display_sheet_d_conn.pdf",
)

lines = [
    f"current_child_pdfs={len(current)}",
    f"poison_child_pdfs={len(poison)}",
]
for threshold in THRESHOLDS:
    current_findings = [
        finding for pdf in current for finding in collisions(pdf, threshold)
    ]
    poison_findings = [
        finding for pdf in poison for finding in collisions(pdf, threshold)
    ]
    lines.extend(
        (
            f"threshold_mm={threshold:.2f}",
            f"  current_findings={len(current_findings)}",
            *(f"    {finding}" for finding in current_findings),
            f"  poison_findings={len(poison_findings)}",
            *(f"    {finding}" for finding in poison_findings),
        )
    )

output = "\n".join(lines) + "\n"
(HERE / "pdf_threshold_sweep.txt").write_text(
    output, encoding="utf-8", newline="\n"
)
print(output, end="")
