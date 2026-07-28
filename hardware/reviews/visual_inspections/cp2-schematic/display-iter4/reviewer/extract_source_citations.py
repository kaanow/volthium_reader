"""Render the on-file source pages used for iteration-8 citation checks."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
DATA = REPO / "hardware" / "datasheets"
SOURCES = (
    ("thvd1400", DATA / "THVD1400DR.pdf", (4, 5)),
    ("usb4085_drawing", DATA / "USB4085_drawing.pdf", (1, 2)),
)

lines: list[str] = []
matrix = fitz.Matrix(300 / 72, 300 / 72)
for slug, path, pages in SOURCES:
    lines.append(f"{path.name} sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")
    with fitz.open(path) as document:
        lines.append(f"{path.name} pages={document.page_count}")
        for page_number in pages:
            page = document[page_number - 1]
            (HERE / f"{slug}_p{page_number}.txt").write_text(
                page.get_text("text"), encoding="utf-8", newline="\n"
            )
            page.get_pixmap(matrix=matrix, alpha=False).save(
                HERE / f"{slug}_p{page_number}.png"
            )

footprint = (
    Path(os.environ["LOCALAPPDATA"])
    / "Programs"
    / "KiCad"
    / "10.0"
    / "share"
    / "kicad"
    / "footprints"
    / "Connector_USB.pretty"
    / "USB_C_Receptacle_GCT_USB4085.kicad_mod"
)
footprint_text = footprint.read_text(encoding="utf-8")
tht = re.findall(r'\(pad "([^"]+)" thru_hole', footprint_text)
smd = re.findall(r'\(pad "([^"]+)" smd', footprint_text)
lines.extend(
    (
        f"installed_USB4085_footprint={footprint}",
        f"installed_USB4085_THT_pads={len(tht)}",
        f"installed_USB4085_SMD_pads={len(smd)}",
    )
)
(HERE / "source_identity.txt").write_text(
    "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
)
print("\n".join(lines))
