"""Render reviewer-owned 1200 DPI SHIELD/GND crops from current child PDFs."""

from __future__ import annotations

from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
PDFS = {
    "battery": REPO / "hardware/kicad/schematic/build/sheet_conn.pdf",
    "display": REPO / "hardware/kicad/schematic/build_display/sheet_d_conn.pdf",
}


for board, pdf in PDFS.items():
    with fitz.open(pdf) as document:
        page = document[0]
        words = page.get_text("words")
        shields = [word for word in words if word[4] == "SHIELD"]
        grounds = [word for word in words if word[4] == "GND"]
        if len(shields) != 1:
            raise SystemExit(f"{board}: expected one SHIELD word, found {len(shields)}")
        shield = shields[0]
        sx = (shield[0] + shield[2]) / 2
        sy = (shield[1] + shield[3]) / 2
        nearest = sorted(
            grounds,
            key=lambda word: (
                ((word[0] + word[2]) / 2 - sx) ** 2
                + ((word[1] + word[3]) / 2 - sy) ** 2
            ),
        )[:4]
        clip = fitz.Rect(shield[:4])
        for word in nearest:
            clip.include_rect(fitz.Rect(word[:4]))
        clip.x0 -= 12
        clip.y0 -= 12
        clip.x1 += 12
        clip.y1 += 12
        page.get_pixmap(
            matrix=fitz.Matrix(1200 / 72, 1200 / 72),
            clip=clip,
            alpha=False,
        ).save(HERE / f"{board}_shield_gnd_1200dpi.png")
        print(
            f"{board}: clip={tuple(round(value, 2) for value in clip)} "
            f"nearest_gnd={len(nearest)}"
        )
