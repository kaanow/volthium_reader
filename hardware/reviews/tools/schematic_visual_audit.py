#!/usr/bin/env python3
"""Generate schematic visual-audit artifacts for D11 review.

This tool creates a reviewer-ready evidence pack:
1) full-page raster renders of each schematic PDF page;
2) dense-region crops for manual readability checks;
3) a markdown report with overlap findings;
4) SHA-256 manifest for all generated artifacts.

Default output path matches the project review convention:
  hardware/reviews/visual_inspections/<cp_slug>/iter<iter>/codex/
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except Exception as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "PyMuPDF is required (import fitz failed). "
        "Install with: .venv/bin/pip install pymupdf"
    ) from exc


REPO = Path(__file__).resolve().parents[3]
DEFAULT_BATTERY_PDF = REPO / "hardware/outputs/battery_side/schematic.pdf"
DEFAULT_DISPLAY_PDF = REPO / "hardware/outputs/display_side/schematic.pdf"
DEFAULT_OUT_ROOT = REPO / "hardware/reviews/visual_inspections"


@dataclass(frozen=True)
class WordBox:
    page_idx: int
    text: str
    rect: fitz.Rect


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cp-slug", required=True, help="e.g. cp5-routing-drc")
    ap.add_argument("--iter", required=True, type=int, help="review iteration number")
    ap.add_argument("--battery-pdf", type=Path, default=DEFAULT_BATTERY_PDF)
    ap.add_argument("--display-pdf", type=Path, default=DEFAULT_DISPLAY_PDF)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--crops-per-page", type=int, default=12)
    ap.add_argument("--crop-margin-pt", type=float, default=20.0)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if text overlaps are detected",
    )
    return ap.parse_args()


def page_matrix(dpi: int) -> fitz.Matrix:
    scale = dpi / 72.0
    return fitz.Matrix(scale, scale)


def words_from_page(page: fitz.Page, page_idx: int) -> list[WordBox]:
    out: list[WordBox] = []
    # tuple: x0, y0, x1, y1, "word", block_no, line_no, word_no
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        t = str(text).strip()
        if not t:
            continue
        out.append(WordBox(page_idx=page_idx, text=t, rect=fitz.Rect(x0, y0, x1, y1)))
    return out


def intersection_area(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    return inter.width * inter.height


def detect_text_overlaps(words: Iterable[WordBox]) -> list[tuple[WordBox, WordBox, float]]:
    # O(n^2) is acceptable at this scale (few thousand words max).
    overlaps: list[tuple[WordBox, WordBox, float]] = []
    word_list = list(words)
    for wa, wb in itertools.combinations(word_list, 2):
        if wa.page_idx != wb.page_idx:
            continue
        area = intersection_area(wa.rect, wb.rect)
        if area <= 0:
            continue
        overlaps.append((wa, wb, area))
    return overlaps


def dense_regions_from_words(words: list[WordBox], max_regions: int) -> list[fitz.Rect]:
    if not words:
        return []
    ranked = []
    for w in words:
        area = max(w.rect.width * w.rect.height, 1.0)
        score = len(w.text) / area
        ranked.append((score, w.rect))
    ranked.sort(reverse=True, key=lambda x: x[0])

    selected: list[fitz.Rect] = []
    guard: list[fitz.Rect] = []
    for _, rect in ranked:
        if any(rect.intersects(g) for g in guard):
            continue
        selected.append(rect)
        guard.append(rect + (-12, -12, 12, 12))
        if len(selected) >= max_regions:
            break
    return selected


def clipped(rect: fitz.Rect, page_rect: fitz.Rect, margin_pt: float) -> fitz.Rect:
    return fitz.Rect(
        max(rect.x0 - margin_pt, page_rect.x0),
        max(rect.y0 - margin_pt, page_rect.y0),
        min(rect.x1 + margin_pt, page_rect.x1),
        min(rect.y1 + margin_pt, page_rect.y1),
    )


def write_manifest(root: Path) -> None:
    lines: list[str] = []
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name != "MANIFEST.sha256"):
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{digest}  {p.relative_to(root)}")
    (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")


def render_pdf(
    pdf_path: Path,
    out_dir: Path,
    prefix: str,
    dpi: int,
    crops_per_page: int,
    margin_pt: float,
) -> tuple[list[WordBox], list[Path]]:
    doc = fitz.open(pdf_path)
    written: list[Path] = []
    all_words: list[WordBox] = []
    mat = page_matrix(dpi)

    for pno, page in enumerate(doc, start=1):
        full_path = out_dir / f"{prefix}_p{pno}_full_{dpi}dpi.png"
        page.get_pixmap(matrix=mat, alpha=False).save(full_path)
        written.append(full_path)

        words = words_from_page(page, pno)
        all_words.extend(words)
        regions = dense_regions_from_words(words, crops_per_page)
        for idx, region in enumerate(regions, start=1):
            clip = clipped(region, page.rect, margin_pt)
            crop_path = out_dir / f"{prefix}_p{pno}_crop_{idx:02d}.png"
            page.get_pixmap(matrix=mat, clip=clip, alpha=False).save(crop_path)
            written.append(crop_path)

    return all_words, written


def write_report(
    out_dir: Path,
    battery_pdf: Path,
    display_pdf: Path,
    battery_words: list[WordBox],
    display_words: list[WordBox],
    battery_overlaps: list[tuple[WordBox, WordBox, float]],
    display_overlaps: list[tuple[WordBox, WordBox, float]],
    crops_per_page: int,
) -> Path:
    report = out_dir / "REPORT.md"

    def summarize_overlaps(
        overlaps: list[tuple[WordBox, WordBox, float]], name: str
    ) -> list[str]:
        lines = [f"### {name} text-overlap findings"]
        if not overlaps:
            lines.append("- No text-text bounding-box overlaps detected.")
            return lines
        lines.append(f"- Detected {len(overlaps)} overlapping word-box pairs.")
        for idx, (a, b, area) in enumerate(overlaps[:50], start=1):
            lines.append(
                f"- {idx}. p{a.page_idx}: `{a.text}` overlaps `{b.text}` "
                f"(intersection area {area:.2f} pt^2)"
            )
        if len(overlaps) > 50:
            lines.append(f"- ... plus {len(overlaps) - 50} additional pairs.")
        return lines

    lines: list[str] = []
    lines.append("# Schematic Visual Audit Report")
    lines.append("")
    lines.append("## Inputs")
    lines.append(f"- Battery PDF: `{battery_pdf}`")
    lines.append(f"- Display PDF: `{display_pdf}`")
    lines.append("")
    lines.append("## Generated Artifacts")
    lines.append("- Full-page renders: `*_full_300dpi.png`")
    lines.append(
        f"- Dense-region crops: up to {crops_per_page} per page (`*_crop_XX.png`)"
    )
    lines.append("- Snapshot copies: `snapshots/*.pdf`")
    lines.append("- Integrity manifest: `MANIFEST.sha256`")
    lines.append("")
    lines.append("## Word Extraction Counts")
    lines.append(f"- Battery words: {len(battery_words)}")
    lines.append(f"- Display words: {len(display_words)}")
    lines.append("")
    lines.extend(summarize_overlaps(battery_overlaps, "Battery schematic"))
    lines.append("")
    lines.extend(summarize_overlaps(display_overlaps, "Display schematic"))
    lines.append("")
    lines.append("## Reviewer Notes")
    lines.append(
        "- This tool detects text-text overlaps via PDF word bounding boxes. "
        "Manual visual review is still required for symbol/wire/text readability."
    )
    lines.append(
        "- Use the generated crops as the codex-owned evidence set in the active CP packet."
    )
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> int:
    args = parse_args()
    cp_dir = args.out_root / args.cp_slug / f"iter{args.iter}" / "codex"
    cp_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = cp_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    if not args.battery_pdf.exists():
        raise SystemExit(f"Battery PDF not found: {args.battery_pdf}")
    if not args.display_pdf.exists():
        raise SystemExit(f"Display PDF not found: {args.display_pdf}")

    battery_snapshot = snapshot_dir / "battery_schematic.pdf"
    display_snapshot = snapshot_dir / "display_schematic.pdf"
    shutil.copy2(args.battery_pdf, battery_snapshot)
    shutil.copy2(args.display_pdf, display_snapshot)

    battery_words, _ = render_pdf(
        pdf_path=args.battery_pdf,
        out_dir=cp_dir,
        prefix="battery",
        dpi=args.dpi,
        crops_per_page=args.crops_per_page,
        margin_pt=args.crop_margin_pt,
    )
    display_words, _ = render_pdf(
        pdf_path=args.display_pdf,
        out_dir=cp_dir,
        prefix="display",
        dpi=args.dpi,
        crops_per_page=args.crops_per_page,
        margin_pt=args.crop_margin_pt,
    )

    battery_overlaps = detect_text_overlaps(battery_words)
    display_overlaps = detect_text_overlaps(display_words)

    report_path = write_report(
        out_dir=cp_dir,
        battery_pdf=battery_snapshot,
        display_pdf=display_snapshot,
        battery_words=battery_words,
        display_words=display_words,
        battery_overlaps=battery_overlaps,
        display_overlaps=display_overlaps,
        crops_per_page=args.crops_per_page,
    )

    write_manifest(cp_dir)

    print(f"Wrote audit artifacts to: {cp_dir}")
    print(f"Report: {report_path}")
    print(
        f"Text-overlap pairs: battery={len(battery_overlaps)}, "
        f"display={len(display_overlaps)}"
    )

    if args.strict and (battery_overlaps or display_overlaps):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

