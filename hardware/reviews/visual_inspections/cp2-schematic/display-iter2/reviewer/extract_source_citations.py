from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import fitz


here = Path(__file__).resolve().parent
repo = Path(__file__).resolve().parents[6]
data = repo / "hardware/datasheets"

sources = (
    ("thvd1400", data / "THVD1400DR.pdf", (4, 5)),
    ("usb4085_drawing", data / "USB4085_drawing.pdf", (1, 2)),
)

lines: list[str] = []
matrix = fitz.Matrix(300 / 72, 300 / 72)
for slug, path, pages in sources:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{path.name} sha256={digest}")
    with fitz.open(path) as document:
        lines.append(f"{path.name} pages={document.page_count}")
        for page_number in pages:
            page = document[page_number - 1]
            text = page.get_text("text")
            (here / f"{slug}_p{page_number}.txt").write_text(
                text, encoding="utf-8"
            )
            page.get_pixmap(matrix=matrix, alpha=False).save(
                here / f"{slug}_p{page_number}.png"
            )

footprint = (
    Path(os.environ["LOCALAPPDATA"])
    / "Programs/KiCad/10.0/share/kicad/footprints/Connector_USB.pretty"
    / "USB_C_Receptacle_GCT_USB4085.kicad_mod"
)
footprint_text = footprint.read_text(encoding="utf-8")
tht = re.findall(r'\(pad "([^"]+)" thru_hole', footprint_text)
smd = re.findall(r'\(pad "([^"]+)" smd', footprint_text)
lines.append(f"installed_USB4085_footprint={footprint}")
lines.append(f"installed_USB4085_THT_pads={len(tht)}")
lines.append(f"installed_USB4085_SMD_pads={len(smd)}")

(here / "source_identity.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
