from __future__ import annotations

from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
DISPLAY_PDF = (
    REPO / "hardware/kicad/schematic/build_display/volthium_display.pdf"
)
BATTERY_PDF = REPO / "hardware/kicad/schematic/build/volthium_reader.pdf"


def expanded_union(rects: list[fitz.Rect], margin: float) -> fitz.Rect:
    clip = fitz.Rect(rects[0])
    for rect in rects[1:]:
        clip.include_rect(rect)
    clip.x0 -= margin
    clip.y0 -= margin
    clip.x1 += margin
    clip.y1 += margin
    return clip


with fitz.open(DISPLAY_PDF) as document:
    page = document[3]
    words = page.get_text("words")
    anchors = [
        fitz.Rect(word[:4])
        for word in words
        if word[4] in {"U-ESD", "USBLC6-2SC6Y"}
    ]
    if len(anchors) != 2:
        raise SystemExit(f"expected two U-ESD anchors, found {len(anchors)}")

    clip = expanded_union(anchors, 70)
    nearby = [
        word
        for word in words
        if fitz.Rect(word[:4]).intersects(clip)
    ]

    lines = [
        f"display_pdf={DISPLAY_PDF}",
        "page=4",
        f"clip={tuple(round(value, 3) for value in clip)}",
        "nearby_word_boxes:",
    ]
    for word in sorted(nearby, key=lambda item: (item[1], item[0])):
        box = tuple(round(value, 3) for value in word[:4])
        lines.append(f"  {word[4]!r}: {box}")

    target_words = [
        word
        for word in nearby
        if word[4] in {"U-ESD", "USBLC6-2SC6Y", "6", "NC"}
    ]
    lines.append("pairwise_intersections:")
    for index, left in enumerate(target_words):
        left_rect = fitz.Rect(left[:4])
        for right in target_words[index + 1 :]:
            right_rect = fitz.Rect(right[:4])
            intersection = left_rect & right_rect
            if not intersection.is_empty:
                lines.append(
                    f"  {left[4]!r} x {right[4]!r}: "
                    f"{intersection.get_area():.3f} pt^2"
                )

    (HERE / "display_p4_u_esd_geometry.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    page.get_pixmap(
        matrix=fitz.Matrix(600 / 72, 600 / 72),
        clip=clip,
        alpha=False,
    ).save(HERE / "display_p4_u_esd_600dpi.png")

print("\n".join(lines))

focus_regions = (
    (
        DISPLAY_PDF,
        1,
        fitz.Rect(220, 320, 330, 405),
        "display_p2_pin4_vout_600dpi.png",
    ),
    (
        DISPLAY_PDF,
        3,
        fitz.Rect(105, 340, 215, 425),
        "display_p4_gnd_shield_600dpi.png",
    ),
    (
        BATTERY_PDF,
        1,
        fitz.Rect(535, 145, 635, 230),
        "battery_p2_ilim_gnd_600dpi.png",
    ),
)
for pdf_path, page_index, focus_clip, output_name in focus_regions:
    with fitz.open(pdf_path) as document:
        document[page_index].get_pixmap(
            matrix=fitz.Matrix(600 / 72, 600 / 72),
            clip=focus_clip,
            alpha=False,
        ).save(HERE / output_name)

with fitz.open(DISPLAY_PDF) as document:
    document[3].get_pixmap(
        matrix=fitz.Matrix(1200 / 72, 1200 / 72),
        clip=fitz.Rect(135, 365, 180, 405),
        alpha=False,
    ).save(HERE / "display_p4_gnd_shield_1200dpi.png")
