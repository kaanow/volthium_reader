#!/usr/bin/env python3
"""doc_consistency_check.py — mechanical G5 + D32 gate (D35).

Replaces "remember which tokens were superseded and grep for them" with a
persistent registry: every part/value swap ever made in this project stays
in SUPERSEDED forever and is re-checked on every run. Also executes the
D32 datasheet gate as code instead of as a prose claim.

Run from repo root:  python3 hardware/reviews/tools/doc_consistency_check.py
Exit 0 = clean. Exit 1 = findings (printed). Run before EVERY semaphore
flip (DESIGNER.md pre-handoff checklist; SOP gate G5).

Classification rules (mirrors SOP G5's a/b/c triage):
  - a hit is ALLOWED history if the line carries a history marker
    (was/Δ/superseded/replaced/pivot/...), or the line also names the
    CURRENT part (self-evident was→now comparison), or the file is a
    history-bearing record (DR log), or — decisions.md only — a
    supersession marker appears within ±5 lines (bracket-note convention).
  - anything else is a live contradiction and fails the gate.

History (why this exists): the 2026-07-14 user audit found EG1218 (BTN1,
superseded by RP3502MABLK) and a phantom 680 Ω battery-side bias row still
live in docs/hardware/bom.md, plus a false "gate CLOSED — every active
part" claim in the datasheet manifest, months after the underlying
decisions. Same failure class as reviewer findings F13/F14/F16.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Scope: docs whose CURRENT prose must not contain unmarked stale tokens.
# /archive/ and the review packet (pure history) are out of scope.
# ---------------------------------------------------------------------------
LIVE_DOCS = [
    "docs/hardware/bom.md",
    "docs/hardware/power_budget.md",
    "docs/hardware/cat5e_pinout.md",
    "hardware/layout/cp1_bom.md",
    "hardware/layout/cp1_battery_side.md",
    "hardware/layout/cp1_display_side.md",
    "hardware/layout/decisions.md",
    "hardware/reviews/DESIGN_REVIEW_ITEMS.md",
    "hardware/reviews/REVIEWER.md",
    "docs/firmware/architecture.md",
    "docs/firmware/state_machine.md",
    "docs/firmware/ble_flap_recovery.md",
]

# Files that are history-bearing records end-to-end: hits allowed.
HISTORY_FILES = {"hardware/reviews/DESIGN_REVIEW_ITEMS.md"}
# decisions.md: append-only narrative; allowed if a supersession marker
# is within this many lines of the hit (bracket-note convention).
NEARBY_WINDOW = 5

HISTORY_MARKERS = re.compile(
    r"(supersed|was\b|Δ|retired?|retain|history|erratum|evidence|"
    r"first[- ]cut|mistakenly|earlier|replace[sd]?\b|instead of|not the|"
    r"caught|flagged|regressed|never\b|pivot|swap|corrected|removed|"
    r"un-sourceable|→|->)",
    re.IGNORECASE,
)
NEARBY_MARKERS = re.compile(r"(\[Supersed|supersed|revised|Δ|→)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Persistent superseded-token registry. APPEND-ONLY: every swap this project
# ever makes gets a row here at the time the swap is made (G5 discipline).
# (stale_pattern, current_token — None if valueless, hint)
# ---------------------------------------------------------------------------
SUPERSEDED: list[tuple[str, str | None, str]] = [
    (r"EG1218", "RP3502MABLK", "BTN1 → E-Switch RP3502MABLK (COTS sweep)"),
    (r"SN65HVD3082E", "THVD1400", "RS-485 → THVD1400DR (D34, iter-8 F05)"),
    (r"ISL3175E", "THVD1400", "RS-485 → THVD1400DR (D34, iter-10 F08)"),
    (r"LM5166X", "LM5166Y", "buck → LM5166YDRCR — 3.3 V, never X=5 V (F01)"),
    (r"TPS3890", "TPS3808", "UVLO → TPS3808G01DBVR (D33/DR-24)"),
    (r"\bSS24\b", "SS26", "reverse diode → SS26-E3/52T (DR-3)"),
    (r"AO3401A", "ZXMP6A13F", "Q1 → ZXMP6A13F 60 V (D19/DR-4)"),
    (r"AO3400A", "2N7002", "Q2 → 2N7002 60 V (D19/DR-4)"),
    (r"R-78E12", "R-78HB12", "12 V buck → R-78HB12-0.5 72 V-in (D19/DR-3)"),
    (r"SMAJ30CA", "SMAJ33CA", "24 V TVS → SMAJ33CA (D19/DR-2)"),
    (r"1727010|MKDS", "1757242", "J1 → MSTBA 1757242 + MSTB 1757019 (D32)"),
    (r"SUYIN|100362", "615008145521", "display RJ45 → Würth 615008145521 (DR-10)"),
    (r"DS3231", "RV-3028", "RTC → RV-3028-C7 (D23/DR-8)"),
    (r"FH12-24S", "B8B-PH-K-S", "e-paper conn → JST-PH B8B-PH-K-S (DR-7)"),
    (r"USBLC6-2SC6\b(?!Y)", "USBLC6-2SC6Y", "ESD → -2SC6Y variant (API sweep)"),
    (r"680\s*[ΩR].{0,40}bias|bias.{0,40}680\s*[ΩR]", None,
     "battery-side bias removed (D19/DR-4b); display bias DNP (F12)"),
    (r"populated at ~?330", "DNP", "display bias R3/R4 = DNP by default (F12)"),
    (r"UART[- ](RX[- ])?wake (works|path stays valid)", "ext1",
     "Deep-sleep wake = ext1 ANY_LOW + BREAK (F11/F15), not UART wake"),
    (r"ext0 \(or ext1\)", "ANY_LOW", "wake API selected: ext1 ANY_LOW (F15)"),
    (r"tP[HL]Z\s*≤?\s*65\s*ns", "200 ns",
     "THVD1400 §6.7: 200 ns max disable; 10 µs receiver-fail-safe (F19)"),
    (r"F1465|31MJ005", "3517",
     "fuse-clip SKUs were phantoms (no such parts anywhere, user-caught "
     "2026-07-14) → Keystone 3517 (DK 36-3517-ND / Mouser 534-3517)"),
]

# ---------------------------------------------------------------------------
# D32: manifest ↔ PDF ↔ BOM cross-check
# ---------------------------------------------------------------------------
MANIFEST = REPO / "hardware/datasheets/manifest.md"
DATASHEET_DIR = REPO / "hardware/datasheets"
CANONICAL_BOM = REPO / "hardware/layout/cp1_bom.md"

# Manifest rows whose MPN token won't literally appear in the BOM text
# (module/manual naming differences) — map to the token that should.
MANIFEST_TO_BOM_ALIAS = {
    "MSTB 2,5/2-ST-5,08 (1757019)": "1757019",
    "LCD1 Waveshare 4.2\" e-Paper Module (B)": "Waveshare",
    "RP3502MABLK (BTN1 battery override)": "RP3502MABLK",
    "RJHSE-5380": "RJHSE5380",
    "AP2112K-3.3TRG1": "AP2112K-3.3",
    "ZXMP6A13FTA": "ZXMP6A13F",
    "BZX84C12LT1G": "BZX84C12",
    "0215001.MXP": "0215001",
}


def _allowed(line: str, lines: list[str], idx: int, rel: str,
             current: str | None) -> bool:
    if rel in HISTORY_FILES:
        return True
    if HISTORY_MARKERS.search(line):
        return True
    if current and current in line:
        return True  # names old AND new part → self-evident comparison
    if rel.endswith("decisions.md"):
        lo, hi = max(0, idx - NEARBY_WINDOW), min(len(lines), idx + NEARBY_WINDOW + 1)
        if any(NEARBY_MARKERS.search(lines[j]) for j in range(lo, hi) if j != idx):
            return True
    return False


def check_stale_tokens() -> list[str]:
    findings = []
    for rel in LIVE_DOCS:
        path = REPO / rel
        if not path.exists():
            findings.append(f"[scope] {rel}: file missing — update LIVE_DOCS")
            continue
        lines = path.read_text().splitlines()
        for idx, line in enumerate(lines):
            for pattern, current, hint in SUPERSEDED:
                if re.search(pattern, line) and not _allowed(
                        line, lines, idx, rel, current):
                    findings.append(
                        f"[stale] {rel}:{idx + 1}: /{pattern}/ live "
                        f"(should be: {hint})\n    > {line.strip()[:140]}"
                    )
    return findings


def check_d32_manifest() -> list[str]:
    findings = []
    if not MANIFEST.exists():
        return [f"[d32] manifest missing: {MANIFEST}"]
    text = MANIFEST.read_text()
    active_section = text.split("## Still needed")[0]
    rows = re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|", active_section, re.M)
    bom_text = CANONICAL_BOM.read_text()
    n = 0
    for mpn, pdf_cell in rows:
        mpn, pdf_cell = mpn.strip(), pdf_cell.strip()
        if mpn in ("MPN",) or mpn.startswith(":-") or mpn.startswith("--"):
            continue
        n += 1
        m = re.match(r"(\S+\.pdf)", pdf_cell)
        if not m:
            findings.append(f"[d32] manifest row '{mpn}': no PDF filename")
            continue
        if not (DATASHEET_DIR / m.group(1)).exists():
            findings.append(f"[d32] manifest '{mpn}': {m.group(1)} not on disk")
        bom_token = MANIFEST_TO_BOM_ALIAS.get(mpn, mpn)
        if bom_token not in bom_text:
            findings.append(
                f"[d32] manifest part '{mpn}' (token '{bom_token}') absent "
                f"from {CANONICAL_BOM.name} — stale manifest or BOM drift"
            )
    n_verify = len(re.findall(r"_verify", bom_text))
    print(f"  info: {n} manifest parts checked; {n_verify} BOM cells still "
          f"at _verify_ (MPN not chosen — D32 applies when chosen)")
    return findings


def main() -> int:
    findings = check_stale_tokens()
    findings += check_d32_manifest()
    if findings:
        print(f"\n{len(findings)} finding(s):\n")
        for f in findings:
            print("  " + f)
        return 1
    print("clean: no unmarked stale tokens; D32 manifest ↔ PDF ↔ BOM consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
