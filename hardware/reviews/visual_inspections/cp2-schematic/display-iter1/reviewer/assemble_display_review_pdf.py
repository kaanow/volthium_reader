#!/usr/bin/env python3
"""Assemble the generated display sheets into a reviewer-owned five-page PDF."""

from __future__ import annotations

from pathlib import Path

import fitz


REPO = Path(__file__).resolve().parents[6]
BUILD = REPO / "hardware/kicad/schematic/build_display"
OUT = Path(__file__).resolve().parent / "display_five_sheet_snapshot.pdf"
ROOT = "volthium_display.pdf"
CHILD_SHEETS = (
    "sheet_d_power.pdf",
    "sheet_d_conn.pdf",
    "sheet_d_periph.pdf",
    "sheet_d_mcu.pdf",
)


def main() -> None:
    assembled = fitz.open()
    with fitz.open(BUILD / ROOT) as root:
        if root.page_count == 5:
            assembled.insert_pdf(root)
        else:
            assembled.insert_pdf(root, from_page=0, to_page=0)
            for name in CHILD_SHEETS:
                with fitz.open(BUILD / name) as source:
                    assembled.insert_pdf(source)
    assembled.set_metadata(
        {
            "title": "Volthium display schematic - reviewer five-sheet snapshot",
            "subject": "Independent G9 visual-review input",
        }
    )
    assembled.save(OUT)
    print(f"wrote {OUT} ({assembled.page_count} pages)")


if __name__ == "__main__":
    main()
