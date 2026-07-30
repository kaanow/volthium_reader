"""Independent rendered-word collision audit for every current child sheet."""

from __future__ import annotations

import itertools
from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
MM = 2.8346
THRESHOLD_MM = 0.45


def deduplicated_words(pdf: Path) -> list[tuple]:
    words: list[tuple] = []
    seen: set[tuple] = set()
    with fitz.open(pdf) as document:
        for page in document:
            for word in page.get_text("words"):
                key = (
                    word[4],
                    *(round(value, 2) for value in word[:4]),
                )
                if key not in seen:
                    seen.add(key)
                    words.append(word)
    return words


def main() -> int:
    pdfs = sorted(
        path
        for folder in (
            REPO / "hardware" / "kicad" / "schematic" / "build",
            REPO / "hardware" / "kicad" / "schematic" / "build_display",
        )
        for path in folder.glob("*.pdf")
        if not path.stem.startswith("volthium_")
    )
    lines = [
        "INDEPENDENT RENDERED-WORD SECOND OPINION",
        f"threshold_mm={THRESHOLD_MM}",
        f"child_pdfs={len(pdfs)}",
    ]
    total_bad = 0
    for pdf in pdfs:
        words = deduplicated_words(pdf)
        bad: list[str] = []
        nearest: list[tuple[float, str]] = []
        for left, right in itertools.combinations(words, 2):
            overlap_x = min(left[2], right[2]) - max(left[0], right[0])
            overlap_y = min(left[3], right[3]) - max(left[1], right[1])
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            overlap_mm = min(overlap_x, overlap_y) / MM
            detail = (
                f"{left[4]!r} x {right[4]!r} "
                f"overlap={overlap_x / MM:.3f}x{overlap_y / MM:.3f} mm"
            )
            if overlap_mm > THRESHOLD_MM:
                bad.append(detail)
            elif overlap_mm >= 0.30:
                nearest.append((overlap_mm, detail))
        total_bad += len(bad)
        lines.append(
            f"{pdf.parent.name}/{pdf.name}: words={len(words)} "
            f"findings={len(bad)}"
        )
        lines.extend(f"  FINDING {item}" for item in bad)
        for _, item in sorted(nearest, reverse=True)[:3]:
            lines.append(f"  benign-near-threshold {item}")

    lines.append(f"TOTAL_FINDINGS={total_bad}")
    output = "\n".join(lines) + "\n"
    (HERE / "pdf_wordbox_second_opinion.txt").write_text(
        output, encoding="utf-8", newline="\n"
    )
    print(output, end="")
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
