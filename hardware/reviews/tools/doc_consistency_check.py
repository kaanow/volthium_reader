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
    "hardware/layout/cp1_rs485_battery_read.md",
    "hardware/layout/decisions.md",
    "hardware/reviews/DESIGN_REVIEW_ITEMS.md",
    "hardware/reviews/REVIEWER.md",
    "docs/firmware/architecture.md",
    "docs/firmware/state_machine.md",
    "docs/firmware/ble_flap_recovery.md",
    # iter-34 F46: the vendor docs carried live M12/CAN-4-5 drift the
    # checker couldn't see — they are live interface references, scan them.
    "docs/vendor/README.md",
    "docs/vendor/volthium-rs485-correspondence-2024.md",
]

# Files that are history-bearing records end-to-end: hits allowed.
HISTORY_FILES = {"hardware/reviews/DESIGN_REVIEW_ITEMS.md"}
# decisions.md: append-only narrative; allowed if a supersession marker
# is within this many lines of the hit (bracket-note convention).
NEARBY_WINDOW = 5

HISTORY_MARKERS = re.compile(
    r"(supersed|was\b|Δ|retired?|retain|history|erratum|evidence|"
    r"first[- ]cut|mistakenly|earlier|prior|previously|replace[sd]?\b|instead of|not the|"
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
    # 2026-07-14 full-BOM SKU sweep (every DK+Mouser cell resolved via API
    # after the fuse-clip phantom proved the class was systemic):
    (r"EG4527-ND", "EG1932-ND",
     "BTN1 DK SKU pointed at a different E-Switch part (LS0851503F040C1A)"),
    (r"1965-ESP32-S3-WROOM|356-ESP32S3WROOM1N16R8",
     "5407-ESP32-S3-WROOM-1-N16R8CT-ND",
     "MOD1 SKUs malformed → DK 5407-…CT-ND / Mouser 356-ESP32S3WRM1N16R8"),
    (r"1276-1023-1-ND|GRM21BR61C106KE15L", "CL21B106KOQNNNE",
     "C6 10µF: DK SKU was a 22 pF C0G; Murata OOS → Samsung CL21B106KOQNNNE"),
    (r"311-1086-1-ND|GRM155R71H104KE14D", "CL05B104KO5NNNC",
     "C7 100nF 0402: DK SKU was a 22 nF 0603; Murata OOS → Samsung"),
    (r"311-1361-1-ND|GRM188R71H105KA93D", "TMK107B7105KA-T",
     "C8 1µF: DK SKU was a Y5V 0805 100 nF; Murata unlisted → Taiyo Yuden"),
    (r"311-1141-1-ND|GRM188R71H104KA93D", "C0603C104K5RACTU",
     "C5 100nF 0603: DK SKU was an 0805 part; Murata Obsolete → KEMET"),
    (r"36-9774-ND", "970050354",
     "standoff DK SKU was a phantom → Würth WA-SBRII M3×5 (710-970050354)"),
    (r"1738-1135-ND|992-19094", "waveshare.com",
     "LCD1 DK SKU = DFRobot DFR0290, Mouser SKU phantom; module not "
     "stocked at DK/Mouser → Waveshare direct or Amazon"),
    (r"455-B8B-PH-K-S", "455-1710-ND",
     "455- is the DK prefix; Mouser doesn't list B8B-PH-K-S"),
    (r"945-R-78E3\.3", "945-1661-5-ND", "U1 DK cell was malformed"),
    (r"512-BZX84C12", "863-BZX84C12LT1G", "DZ1 Mouser prefix was wrong"),
    (r"78-(SS26|SMAJ12CA|SMAJ15A)-E3|78-SMAJ33CA", None,
     "Mouser doesn't list these Vishay variants (2026-07-14 sweep); "
     "DK cells verified — Mouser cell = '—'; TVS standardized on Diodes Inc"),
    # 2026-07-14 datasheet-claims audit (every number/citation re-read from
    # the on-file PDFs after the SKU sweep proved fabrication was systemic):
    (r"Table 5-3", "Table 3-1",
     "ESP32-S3-WROOM datasheet has no Table 5-3; pin defs are Table 3-1"),
    (r"§ ?5\.4|5\.4 table", "Table 6-7",
     "Espressif low-power currents are Table 6-7; '§5.4' was fabricated"),
    (r"200 nA per Micro Crystal|≤ ?200 nA|application-note-cited",
     "60 nA",
     "RV-3028 datasheet EC table: 45 typ / 60 nA max @3V; the 'AN' max "
     "citation was to an off-file document"),
    (r"~?14 µA( Iq| at 24 V| idle)?", "9.7 µA",
     "LM5166 IQ-SLEEP is 9.7 µA typ / 15 µA max (§6.5); '~14 µA' was "
     "unsourced"),
    # iter-23 reviewer findings (F20/F22/F23):
    (r"SMAJ(33CA|15A|12CA)-13(?!-F)", "-13-F",
     "F20: Diodes non-F -13 variants are Obsolete/zero-stock → -13-F"),
    (r"SMAJ(33CA|15A|12CA)DICT-ND", "-FDICT-ND",
     "F20: cut-tape SKUs of the obsolete non-F variants → SMAJxx-FDICT-ND"),
    (r"RP3502|EG1932-ND", "8125SHZBE",
     "F22: BTN1 → C&K 8125SHZBE (gold, 0.4 VA @ 20 V logic-level rating; "
     "RP3502MABLK had no dry-circuit rating)"),
    (r"DK carries (it|the Waveshare)|single-line vendor for most",
     "waveshare.com",
     "F23: neither DK nor Mouser lists the Waveshare module — order "
     "direct/Amazon; multi-cart order strategy"),
    # iter-29 reviewer findings (F28/F33):
    (r"72 mA @ 3\.3|72 mA.{0,10}3\.3 V", "90 mA",
     "F28: ADM2587E 3.3V/100Ω ICC is 90 mA; 72 mA is the 5 V row"),
    (r"below the µW floor|<\s?µW", "1.5 mW",
     "F28: gated RS-485 avg ≈ 1.5 mW, not below the µW floor"),
    (r"WM7626[A-Z-]*\b.{0,30}vertical|vertical.{0,30}WM7626",
     "WM7612",
     "F33: PicoBlade vertical 53398-0871 = WM7612*; WM7626 is the r/a 53261"),
    # iter-31 reviewer findings (F40 — superseded delta topology forms):
    (r"wire-OR(.{0,20}(RX|RO|pull-up))?|shared[- ]DI\b|fanned to both ADM2587E",
     "dedicated per-channel DI/DE/RO",
     "F30/F40: shared-UART fan-out retired → dedicated per-channel pins, "
     "matrix-muxed, inactive high-Z"),
    (r"series[- ]ferrite'?d?.{0,20}3V3|3V3.{0,20}budget-counting|"
     r"always-on 3V3 (via|through) (a )?ferrite",
     "load-switched default-OFF",
     "F34/F40: raw/ferrited always-on EXP_3V3 retired → load-switched, "
     "default-OFF, force-OFF in State 4"),
    (r"VISOIN pin 11|VISOOUT pin 12 ↔ VISOIN",
     "GND2 pin 11 / VISOIN pin 19",
     "F35: pin 11 is GND2 (not VISOIN); VISOIN is pin 19"),
    # iter-33 reviewer findings (F43-F50, addressed iter-34):
    (r"11\+14 → PCB isolated ground|GND2 isoPower return \(Fig 35\)",
     "GND2_DCDC / ISO_BUS_GND",
     "F43: isolated grounds are TWO nets — GND2_DCDC (11+14) and "
     "ISO_BUS_GND (16+20 + plane), L2 the only tie (Rev H p.8/p.17)"),
    (r"series R as a coordinated pair|re-verify residual < ?14 V|"
     r"needs series R to protect",
     "DNP / intentionally unprotected",
     "F44: a series R cannot coordinate into a high-Z pin (no published "
     "ADM2587E injection rating); port is DNP + honestly unprotected"),
    (r"correspondence.{0,60}\(authoritative\)|authoritative vendor statement",
     "owner-supplied summary",
     "F45: the vendor-email Markdown is an owner-written summary — "
     "'owner-reported' evidence until the original thread is committed"),
    (r"CAN[- ]?H/L on (pins )?4/5(?!.{0,80}unresolved)|"
     r"pins? 1/2 \(vendor-confirmed|CAN is on pins 1 \(H\)",
     "CAN mapping UNRESOLVED",
     "F45/F46: photo label says RJ45 4/5; email says 'pin 1 and 2' with "
     "the connector unnamed — neither is a confirmed fact yet"),
    (r"4-socket M12(?![- ]style)|two M12 sockets",
     "connector family unresolved (on-site ID)",
     "F46: email says XLR, photo shows M12-style — describe as "
     "'M12-style (photographed)' and keep the family open until on-site"),
    (r"no longer topology-gating|no circuit change (is )?expected",
     "TOPOLOGY-GATING on-site test",
     "F47: the on-site top-pack/common-mode test decides the reference/"
     "bleed question — D36/DR-26 stay gated until it passes (design §7)"),
    (r"≤ ?1\.65 µW|rail is \*?dead\*? in (State 4|hard-cut)",
     "≤5 µW testable off-state contract",
     "F48: budget must count 2N7002 IDSS (≤1 µA) + P-FET (≤0.5 µA); "
     "'dead' replaced by pull-ups-on-switched-rail + high-Z + bleed + "
     "≤50 mV/≤1.5 µA acceptance contract"),
    (r"≤ ?50 mA rail|1 A/ckt|50079-class pre-crimp",
     "PS-51021-009: 1.0 A @ AWG 26-28; mate = 0151340801 OTS assembly",
     "F49: no 50 mA limiter exists; rating now sourced from PS-51021-009 "
     "(on file); loose 50079-8000 has 25k MOQ — qty-1 mate is the OTS "
     "cable assembly 0151340801 (DK WM15273-ND)"),
    (r"Q_exp \$0\.20|~\$55\.7|\+~\$56\b|(?<!\d)\$248\b",
     "~$57 delta / ~$249 total",
     "F50: delta recomputed from populated BOM rows — two full FET pairs "
     "$1.00 + Q_exp $0.50 (+R_exp_bleed) → ~$56.7 ≈ $57"),
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
    "8125SHZBE (BTN1 battery override)": "8125SHZBE",
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
