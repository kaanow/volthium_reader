from __future__ import annotations

import itertools
from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
PDFS = {
    "battery": REPO / "hardware/kicad/schematic/build/volthium_reader.pdf",
    "display": (
        REPO / "hardware/kicad/schematic/build_display/volthium_display.pdf"
    ),
}


def rounded_box(word: tuple) -> tuple[float, float, float, float]:
    return tuple(round(value, 3) for value in word[:4])


lines: list[str] = []
total_cross_object = 0
for name, path in PDFS.items():
    raw_count = 0
    duplicate_count = 0
    overlaps: list[str] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            unique: dict[tuple[str, tuple[float, ...]], tuple] = {}
            for word in page.get_text("words"):
                raw_count += 1
                key = (word[4], rounded_box(word))
                if key in unique:
                    duplicate_count += 1
                else:
                    unique[key] = word

            for left, right in itertools.combinations(unique.values(), 2):
                intersection = fitz.Rect(left[:4]) & fitz.Rect(right[:4])
                if intersection.is_empty:
                    continue
                area = intersection.get_area()
                overlaps.append(
                    f"  p{page_number}: {left[4]!r} x {right[4]!r} "
                    f"area={area:.3f} pt^2 "
                    f"left={rounded_box(left)} right={rounded_box(right)}"
                )

    total_cross_object += len(overlaps)
    lines.extend(
        (
            f"[{name}]",
            f"pdf={path}",
            f"raw_words={raw_count}",
            f"exact_duplicate_boxes_removed={duplicate_count}",
            f"cross_object_intersections={len(overlaps)}",
        )
    )
    lines.extend(overlaps or ("  none",))

lines.append(f"total_cross_object_intersections={total_cross_object}")
(HERE / "pdf_wordbox_second_opinion.txt").write_text(
    "\n".join(lines) + "\n", encoding="utf-8"
)
print("\n".join(lines))
