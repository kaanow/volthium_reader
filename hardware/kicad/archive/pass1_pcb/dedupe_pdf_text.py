#!/usr/bin/env python3
"""Post-process a KiCad-generated schematic PDF to remove duplicate
text-drawing operations at identical positions.

KiCad's PDF exporter (10.0.3 / 10.0.4) emits each Property text
(Reference, Value, pin name) twice in the page content stream — same
`cm` transform matrix, same `BT … Tj … ET` block, identical bytes.
PyMuPDF (`get_text("words")`) and the strict schematic audit see this
as two SAME-TEXT identical-bbox word spans at the same pixel,
inflating the audit pair count by ~30 pairs per schematic. The
duplicates are pixel-perfect, so a human reads the text exactly once —
the audit flag is a PDF-content-stream artifact, not a real overlap.

This script rewrites the page content stream in place, keeping the
first occurrence of every unique
    (cm-matrix, BT … Tj … ET) saved-state block
and dropping any byte-identical subsequent occurrence. The resulting
PDF renders the same as the input visually; PyMuPDF sees each text
span once.

Usage:
    .venv/bin/python hardware/kicad/dedupe_pdf_text.py <input.pdf>
    .venv/bin/python hardware/kicad/dedupe_pdf_text.py <input.pdf> --out <output.pdf>
"""

from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


# Match a complete saved-state text drawing block:
#   q <6 cm matrix numbers> cm BT … Tj … ET Q
# Captures the entire block (so the dedup key is the byte-identical
# substring). KiCad emits each character as its own q/Q block, so the
# block boundaries are clean.
_BLOCK_RE = re.compile(
    rb"q\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+cm"
    rb"\s+BT[^Q]*?ET\s+Q",
    re.DOTALL,
)


def dedupe_content_stream(stream: bytes) -> tuple[bytes, int]:
    """Return (deduped stream, number of duplicates removed)."""
    seen: set[bytes] = set()
    removed = 0

    def replace(match: re.Match[bytes]) -> bytes:
        nonlocal removed
        block = match.group(0)
        if block in seen:
            removed += 1
            return b""  # drop the duplicate
        seen.add(block)
        return block

    new_stream = _BLOCK_RE.sub(replace, stream)
    return new_stream, removed


def dedupe_pdf(in_path: Path, out_path: Path) -> int:
    doc = fitz.open(in_path)
    total_removed = 0
    for page in doc:
        xrefs = page.get_contents()
        for xref in xrefs:
            stream = doc.xref_stream(xref)
            new_stream, removed = dedupe_content_stream(stream)
            if removed:
                doc.update_stream(xref, new_stream)
                total_removed += removed
    # PyMuPDF refuses overwrite-in-place; write to a tmp path and atomic-rename.
    tmp = out_path.with_suffix(out_path.suffix + ".dedupetmp")
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    import os
    os.replace(tmp, out_path)
    return total_removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="input PDF path")
    ap.add_argument("--out", type=Path, default=None,
                    help="output PDF path (default: overwrite input)")
    args = ap.parse_args()

    out = args.out or args.input
    removed = dedupe_pdf(args.input, out)
    print(f"  [dedupe] removed {removed} duplicate text-drawing blocks → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
