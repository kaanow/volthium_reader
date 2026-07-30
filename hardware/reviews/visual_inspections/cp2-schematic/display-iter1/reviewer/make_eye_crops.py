#!/usr/bin/env python3
"""Create deterministic 3x2 crops for the G9 human-at-zoom layer."""

from __future__ import annotations

from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
AUDIT = HERE / "g9/display/iter1/reviewer"
PDF = HERE / "display_five_sheet_snapshot.pdf"


def main() -> None:
    with fitz.open(PDF) as document:
        for page_index, page in enumerate(document):
            rect = page.rect
            for row in range(2):
                for col in range(3):
                    clip = fitz.Rect(
                        rect.x0 + rect.width * col / 3,
                        rect.y0 + rect.height * row / 2,
                        rect.x0 + rect.width * (col + 1) / 3,
                        rect.y0 + rect.height * (row + 1) / 2,
                    )
                    index = row * 3 + col + 1
                    page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), clip=clip, alpha=False).save(
                        HERE / f"eye_p{page_index + 1}_grid_{index:02d}.png"
                    )
    print("wrote 30 deterministic eye-at-zoom crops")


if __name__ == "__main__":
    main()
