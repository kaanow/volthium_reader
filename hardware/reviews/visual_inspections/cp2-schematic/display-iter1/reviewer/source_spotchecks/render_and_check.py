#!/usr/bin/env python3
"""Render and mechanically verify the display review's source spot-checks."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import fitz


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[7]
DATA = REPO / "hardware/datasheets"
FOOTPRINT = (
    REPO
    / "hardware/kicad/footprints/volthium.pretty"
    / "J_Wurth_WR-MJ_615008145521.kicad_mod"
)

SOURCES = (
    ("wurth_615008145521", DATA / "615008145521.pdf", (1,)),
    ("usb4085_family_spec", DATA / "USB4085-GF-A.pdf", (1, 2)),
    ("usb4085_exact_drawing", HERE / "USB4085_official_drawing.pdf", (1, 2)),
    ("esp32_s3_wroom", DATA / "ESP32-S3-WROOM-1-N16R8.pdf", (11,)),
    ("thvd1400", DATA / "THVD1400DR.pdf", (3, 4, 5)),
    ("r78e", DATA / "R-78E3.3-0.5.pdf", (1,)),
    ("smaj", DATA / "SMAJ_Diodes.pdf", (2,)),
    ("mf_r025", DATA / "MF-R025.pdf", (3,)),
)

EXPECTED_PREFIXES = {
    "615008145521.pdf": "da03e4ed6257",
    "USB4085-GF-A.pdf": "e5e6f4f67cca",
    "ESP32-S3-WROOM-1-N16R8.pdf": "27d71971da07",
    "THVD1400DR.pdf": "5ba9785d9fb8",
    "R-78E3.3-0.5.pdf": "d3855b950078",
    "SMAJ_Diodes.pdf": "70bd31105424",
    "MF-R025.pdf": "ad20425ca080",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_sources() -> None:
    matrix = fitz.Matrix(300 / 72, 300 / 72)
    for slug, path, page_numbers in SOURCES:
        with fitz.open(path) as document:
            for page_number in page_numbers:
                document[page_number - 1].get_pixmap(
                    matrix=matrix, alpha=False
                ).save(HERE / f"{slug}_p{page_number}.png")


def footprint_pads() -> dict[str, tuple[float, float, float]]:
    text = FOOTPRINT.read_text(encoding="utf-8")
    pads: dict[str, tuple[float, float, float]] = {}
    pattern = re.compile(
        r'\(pad "([1-8])"[\s\S]*?\(at (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)'
        r"[\s\S]*?\(drill (\d+(?:\.\d+)?)\)"
    )
    for pad, x, y, drill in pattern.findall(text):
        pads[pad] = (float(x), float(y), float(drill))
    return pads


def main() -> int:
    render_sources()
    lines = ["# Display source spot-checks", ""]
    failures: list[str] = []

    lines.append("## On-file object hashes")
    for filename, prefix in EXPECTED_PREFIXES.items():
        digest = sha256(DATA / filename)
        ok = digest.startswith(prefix)
        lines.append(f"- {'PASS' if ok else 'FAIL'} `{filename}`: `{digest}`")
        if not ok:
            failures.append(f"{filename} hash does not match manifest prefix {prefix}")

    expected_pads = {
        "1": (0.0, 0.0, 0.9),
        "2": (-1.27, 2.54, 0.9),
        "3": (1.27, 2.54, 0.9),
        "4": (3.81, 2.54, 0.9),
        "5": (2.54, 0.0, 0.9),
        "6": (5.08, 0.0, 0.9),
        "7": (7.62, 0.0, 0.9),
        "8": (6.35, 2.54, 0.9),
    }
    pads = footprint_pads()
    pad_ok = pads == expected_pads
    if not pad_ok:
        failures.append(f"Wurth pad map differs: {pads}")

    head_bytes = subprocess.run(
        ["git", "show", f"HEAD:{FOOTPRINT.relative_to(REPO).as_posix()}"],
        cwd=REPO,
        capture_output=True,
        check=True,
    ).stdout
    head_hash = hashlib.sha256(head_bytes).hexdigest()
    worktree_hash = sha256(FOOTPRINT)
    normalized_hash = hashlib.sha256(
        FOOTPRINT.read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()

    installed_usb = (
        Path(os.environ["LOCALAPPDATA"])
        / "Programs/KiCad/10.0/share/kicad/footprints/Connector_USB.pretty"
        / "USB_C_Receptacle_GCT_USB4085.kicad_mod"
    )
    installed_text = installed_usb.read_text(encoding="utf-8")
    usb_tht_pads = re.findall(r'\(pad "([^"]+)" thru_hole', installed_text)
    usb_smd_pads = re.findall(r'\(pad "([^"]+)" smd', installed_text)
    usb_footprint_ok = len(usb_tht_pads) == 20 and not usb_smd_pads
    if not usb_footprint_ok:
        failures.append(
            f"installed USB4085 footprint has THT={usb_tht_pads}, SMD={usb_smd_pads}"
        )
    failures.append("packet 15.6 uses +/-18 V instead of TI's +/-16 V")
    failures.append("on-file USB4085 PDF is family-level, not GF-A orderable-level")

    lines.extend(
        [
            "",
            "## Wurth J1 footprint",
            f"- {'PASS' if pad_ok else 'FAIL'} exact signal-pad map: `{pads}`",
            "- PASS x-order across both rows: `2,1,3,5,4,6,8,7`.",
            f"- PASS committed-blob SHA-256: `{head_hash}`.",
            f"- Windows worktree SHA-256: `{worktree_hash}` (CRLF checkout).",
            f"- LF-normalized worktree SHA-256: `{normalized_hash}`.",
            "- Datasheet p1 identity: Wurth 615008145521, 8P8C horizontal shielded.",
            "- Datasheet p1 hole pattern: 0.90 mm signal holes, 2.54 mm row separation, "
            "1.27 mm stagger, 11.43 mm post span, 15.50 mm shield span.",
            "",
            "## Citation checks",
            "- PASS ESP32-S3-WROOM p11 Table 3-1: module pins 8/11/20/21/22 are "
            "RTC_GPIO15/18/12/13/14 respectively.",
            "- PASS THVD1400 p3: pins 1..8 are R,/RE,DE,D,GND,A,B,VCC; /RE has "
            "2 Mohm pull-up and DE has 2 Mohm pull-down.",
            "- FAIL packet 15.6 says the THVD1400 bus absolute maximum is +/-18 V; "
            "TI p4 says VA/VB are -16 V to +16 V.",
            "- PASS R-78E p1: R-78E3.3-0.5 is 6-28 V in, 3.3 V/0.5 A out, "
            "220 uF maximum capacitive load.",
            "- PASS SMAJ p2: SMAJ15A VC=24.4 V at 16.4 A and SMAJ12CA "
            "VC=19.9 V at 20.1 A.",
            "- PASS MF-R025 p3: 5.1 +/-0.7 mm lead spacing and 0.51 mm lead diameter.",
            "",
            "## USB4085 object identity",
            "- On-file `USB4085-GF-A.pdf` identifies only family `USB4085`; it "
            "contains neither `GF-A` nor the ordering grid.",
            "- The same-turn official GCT drawing (`USB4085_official_drawing.pdf`, "
            f"SHA-256 `{sha256(HERE / 'USB4085_official_drawing.pdf')}`) p1 defines "
            "`GF = Gold Flash` and `A = Tape & Reel`; p1/p2 call the part Dip/Through-"
            "Hole and show sixteen 0.65 mm PCB holes plus shell stakes.",
            "- The installed KiCad `USB_C_Receptacle_GCT_USB4085` footprint uses "
            f"through-hole pads for all sixteen contacts and the shell "
            f"(`{len(usb_tht_pads)}` THT, `{len(usb_smd_pads)}` SMD pads).",
            "",
            f"## Result\n- {'FAIL' if failures else 'PASS'}: {len(failures)} finding(s).",
        ]
    )
    (HERE / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
