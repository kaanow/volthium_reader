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

# F07: Windows redirected output defaults to cp1252, which cannot encode the
# Ω/↔/— glyphs this tool prints. Pin stdout/stderr to UTF-8 where supported.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Scope: docs whose CURRENT prose must not contain unmarked stale tokens.
# /archive/ and the review packet (pure history) are out of scope.
# ---------------------------------------------------------------------------
LIVE_DOCS = [
    "docs/hardware/bom.md",
    "docs/hardware/power_budget.md",
    "docs/hardware/cat5e_pinout.md",
    # F81 (iter-49): block_diagrams carried a live Q1 P-FET load switch +
    # a stale SN65HVD3082 the checker never saw — it was out of scope.
    # It is a current block-level doc now, so scan it. (schematic_*.md stay
    # OUT: they carry end-to-end SUPERSEDED banners — pure history, like
    # /archive/ and the review packet.)
    "docs/hardware/block_diagrams.md",
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
    # CP2 iter-1: new living docs created at CP2 — scan from day one.
    "hardware/layout/requirements.md",
    "docs/hardware/bringup_guide.md",
]

# Files that are history-bearing records end-to-end: hits allowed.
HISTORY_FILES = {"hardware/reviews/DESIGN_REVIEW_ITEMS.md"}
# decisions.md: append-only narrative; allowed if a supersession marker
# is within this many lines of the hit (bracket-note convention).
NEARBY_WINDOW = 5

# F67 (iter-41): the bare arrow → / -> was REMOVED as a history marker.
# A signal-flow arrow ("Q2 drain → Q1 gate") is not a supersession and must
# not legalize a stale value on that line. Genuine "old → new" history lines
# still pass via the current-token-in-line check in _allowed() (they name the
# new part explicitly), not via the arrow itself.
HISTORY_MARKERS = re.compile(
    r"(supersed|was\b|Δ|retired?|retain|history|erratum|evidence|"
    r"first[- ]cut|mistakenly|earlier|prior|previously|replace[sd]?\b|replacement|"
    r"instead of|not the|caught|flagged|regressed|never\b|pivot|swap|corrected|"
    r"removed|un-sourceable|~~)",  # ~~ = strikethrough: struck text is by definition superseded
    re.IGNORECASE,
)
# F81 (iter-49): the bare arrow → was REMOVED here too. A nearby signal-flow
# or "F60→F76" arrow must not legalize a stale gate-driver token five lines
# away — the exemption is now scoped to an actual supersession word in the
# window, not any arrow. (Parallels F67's removal of → from HISTORY_MARKERS.)
NEARBY_MARKERS = re.compile(
    r"(\[Supersed|supersed|revised|Δ|replaced?\b|retired?\b|was\b|"
    r"removed|corrected|prior|earlier|instead of|history|saga)",
    re.IGNORECASE,
)

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
    (r"AO3401A", "Si2309CDS", "Q1 → ZXMP6A13F 60 V (D19/DR-4) → Si2309CDS (iter-38 F57)"),
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
    # (Amended iter-36: the "$56"/"$248" value-alternates were removed from
    # this row — after the F51 switch simplification the CURRENT correct
    # totals are ~$56.4 / ~$248.4, adjacent to the old wrong values; the
    # error-specific tokens below still guard the original F50 mistake.)
    (r"Q_exp \$0\.20|~\$55\.7",
     "recompute mechanically from populated BOM rows",
     "F50: delta had mis-summed switch lines ($0.40 for two pairs, Q_exp "
     "$0.20); always recompute from the canonical rows"),
    # 2026-07-16 same-day: owner committed the original thread (.eml) +
    # pack/cable photographs — the F45 interim "unresolved" forms resolve:
    # (Amended iter-36 per F55: the "owner-reported" alternate was removed
    # from this row — F55 makes "owner-reported" the CORRECT label for the
    # uncommitted photo evidence, so it is no longer a stale token.)
    (r"CAN (RJ45 )?mapping (is )?UNRESOLVED",
     "battery-side pins 1/2 (thread) / RJ45 4/5 (label) — two domains",
     "F45 closed: transcript committed (orig .eml sha 37df1ab1…); "
     "'pin 1 and 2' = battery-side connector domain — consistent with "
     "the label's RJ45 4/5"),
    (r"connector family unresolved|4-socket M12-style|M12[- ]style plug",
     "4-pin circular threaded-collar aviation-style (photographed)",
     "Owner photos 2026-07-16 (rung-1): two 4-pin threaded sockets per "
     "pack; vendor cable = mating 4-pin threaded plug → RJ45 female; "
     "vendor 'XLR' is colloquial; exact PN = on-site caliper"),
    # iter-35 reviewer findings (F51-F55, addressed iter-36):
    (r"512-2N7002|_verify_ 2N7002",
     "2N7002LT1G / 863-2N7002LT1G",
     "F51: ordered-object identity — Q2/Q3/Q4 re-pinned to onsemi "
     "2N7002LT1G (Mouser 863-2N7002LT1G, exact /resolve 2026-07-17); the "
     "Diotec 2N7002.pdf was the wrong manufacturer's doc → 2N7002_onsemi.pdf"),
    (r"ZXMP6A13F( P-FET)? \+ 2N7002|2N7002 gate (pull|drive)",
     "direct-GPIO-driven ZXMP6A13F (no level shifter on 3V3-source switches)",
     "F51: Q_exp + both channel switches have source = 3V3 = GPIO domain — "
     "the 2N7002 level shifter is removed; gate pull-up 100k, active-LOW "
     "enable (Q1/Q2 on the 24 V domain still legitimately use a 2N7002)"),
    (r"≤ ?1\.5 µA ≈ ≤ ?5 µW|both on-file datasheet bounds, 60 V test points",
     "25 °C test point + ≤5 µA allocation + bench acceptance limit",
     "F51: IDSS rows are TJ=25 °C test points, not full-range maxima — "
     "the binding off-state number is the bring-up acceptance measurement"),
    (r"71-CRCW0805100KFKEA",
     "71-CRCW0805-100K-E3",
     "F54: the suffixless Mouser cell resolves ambiguously "
     "(CRCW0805100KFKEAC vs -EAHP); exact SKU = 71-CRCW0805-100K-E3 "
     "(resolve 2026-07-17, 296k stock)"),
    (r"mate-side product spec PS-51021-009|closed (at )?mate-side|"
     r"PS-51021-024.{0,40}(requested from( the)? owner|not proxy-fetchable)",
     "PS-51021-024 Rev AD on file (header-system spec)",
     "F53: PS-51021-009 is the wire-to-wire sibling and does not list "
     "53398 — the header rating claim must cite PS-51021-024 "
     "(sha b7d3ec9b74b9, owner upload 2026-07-17)"),
    (r"A and B measured w\.r\.t\. the adapter's|"
     r"1 MΩ bleed from\s+ISO_BUS_GND to that pack's B line|"
     r"bleed from ISO_BUS_GND to .{0,25}B line",
     "two-domain CM matrix + per-channel REF conductor fallback",
     "F52: common-mode is defined at each receiver against ITS OWN local "
     "ground (pack B− during reader TX; ISO_BUS_GND during pack TX); a "
     "bleed to a signal wire the reader drives references nothing"),
    (r"ORIGINAL THREAD ON FILE|original (email )?thread (is )?now\s+committed|"
     r"committed original thread",
     "owner-supplied redacted transcript (original off-file)",
     "F55: the committed artifact is a derivative redacted transcript; "
     "uncommitted photo evidence is labeled owner-reported inspection"),
    # iter-37 reviewer findings (F56-F59, addressed iter-38):
    (r"ZXMP6A13F",
     "Si2309CDS (Q1) / DMG3415U (3V3-domain switches)",
     "F56/F57: Diodes marks ZXMP6A13F NRND, distributor stock "
     "unsubstantiated, and no RDS(on) is guaranteed below VGS=-4.5 V — "
     "replaced iter-38 (Si2309CDS has a -10 V guaranteed row + 55 C "
     "leakage row; DMG3415U has a -2.5 V guaranteed row)"),
    (r"1 ?MΩ[^\n|]{0,25}bleed|bleed to a bus line|iso-GND↔bus|"
     r"bleeds barrier leakage",
     "per-channel REF conductor to pack B- (fallback)",
     "F52/F58: a bleed to a signal line the reader drives references "
     "nothing during reader TX — every bus-line-bleed form is retired"),
    (r"[Nn]o battery-negative|[Nn]othing lands on a battery negative|"
     r"no reference wire is required",
     "2-wire primary CONDITIONAL on the §7 matrix; fallback = REF wire",
     "F58: the no-reference property is the §7 matrix's conclusion, not "
     "a premise — state it as conditional"),
    (r"optionally through ~?100 kΩ",
     "direct REF link (0 Ω default; series-R footprint DNP)",
     "F58: no series resistance may be claimed without a bounded "
     "reference current"),
    (r"~\$56\.4|~\$248\.4",
     "~$57.4 delta / ~$249.4 total",
     "F57 repricing: DMG3415U $0.72 x3 + Si2309CDS $1.39 replaced the "
     "NRND ZXMP6A13F lines"),
    # 2026-07-17 owner bench measurements (cable in hand — post-iter-38):
    (r"follow the RJ45-side label \(4/5\)",
     "measured map of the in-service cable (battery 1/2=CAN-H/L -> RJ45 4/6)",
     "Owner beep-out 2026-07-17: the purchased cable wires CAN-L to RJ45 6, "
     "not 5 — the Pro-Series label describes a different product"),
    (r"via a straight patch cable|patch-cable straight-through|"
     r"RJ45 patch → our",
     "vendor cable ends in an RJ45 MALE plug — direct mate, no patch",
     "Owner cable photos 2026-07-17: the purchased cable's client end is "
     "RJ45 male; the email's RJ45-female description was the $10 variant"),
    (r"caliper( the pack connector|/ID)? on-site|on-site caliper|"
     r"caliper on-site",
     "measured 2026-07-17: M12-pattern, ~12.3 mm coupling-thread ID",
     "Connector family/dimensions closed on the bench; only "
     "which-socket-per-pack remains an on-site item"),
    (r"threaded[- ]collar aviation[- ]style|aviation-style (metal )?plug",
     "M12-pattern screw-coupling (measured; photos on file)",
     "The 12.3 mm thread + numbered molded insert identify the M12 "
     "pattern; 'aviation-style' was the interim family guess"),
    # iter-39 reviewer findings (F60-F63, addressed iter-40):
    (r"\bDMG3415U\b",
     "NTR4171P",
     "F61: Diodes marks DMG3415U NRND despite distributor Active/stock "
     "→ onsemi NTR4171P (150 mΩ max @ -2.5 V, Vgs ±12 V, elevated-temp "
     "leakage row); distributor lifecycle field is not authoritative"),
    (r"600 ?mΩ|0\.6 ?Ω.{0,20}-?4\.5|400 ?mΩ.{0,20}-?10|DS32014|"
     r"the FET's ±12 ?V",
     "Si2309CDS 450/345 mΩ, ±20 V Vgs (Vishay 68980)",
     "F62: cp1_battery_side carried the retired ZXMP6A13F RDS(on) "
     "(600/400 mΩ), its DS32014 citation, and a ±12 V Vgs — all wrong "
     "for the Si2309CDS (450/345 mΩ, ±20 V)"),
    (r"~?1 ?kΩ.{0,40}(gate|Rg)|Rg.{0,20}~?1 ?kΩ|works with DZ1 to clamp",
     "Rg 150 kΩ divider-set (F60)",
     "F60: the 1 kΩ Rg made the Zener clamp a continuous ~0.5 W path "
     "when Q1 ON; raised to 150 kΩ (divider sets Vgs, 3.4 mW burden, "
     "DZ1 = transient backstop)"),
    (r"RJ45 side is 4/5 per\s+the label; consistent|"
     r"does not conflict.{0,60}4/5|4/5[ —-]+one cable\s+maps one to the other|"
     r"different connectors, one cable maps one to the other",
     "in-service cable measures RJ45 4/6; label's 4/5 is a different product",
     "F63: the 2026-07-17 beep-out measures CAN on RJ45 4/6; the "
     "Pro-Series label's 4/5 is a different cable — the maps are NOT "
     "consistent"),
    # iter-41 reviewer findings (F64-F67, addressed iter-42):
    (r"Rg\D{0,12}150 ?kΩ|150 ?kΩ\D{0,18}(Rg|gate)|RMCF0805FT150K|"
     r"71-CRCW0805-150K",
     "Rg 33 kΩ / R3 10 kΩ",
     "F64: the iter-40 150 kΩ Rg relied on DZ1 to clamp the 53.3 V surge "
     "at ~0.14 mA (below its characterized rows) and left Q2 leakage "
     "unbounded → R3 10 kΩ / Rg 33 kΩ, divider is the bracket"),
    (r"100 ?kΩ[^|]{0,20}\(Q1 gate pull-up|R3 100 ?kΩ|R3\(100k\)|"
     r"100 kΩ / Rg 150",
     "R3 10 kΩ (F64)",
     "F64: R3 100 kΩ → 10 kΩ so Q2 OFF-leakage Vgs (=I_L·R3) stays below "
     "the min Vth across temperature"),
    (r"IDSS ≤?100 nA @25|100 nA @25 °C / ≤?1 µA @(TJ=)?55|"
     r"IDSS ≤100 nA.{0,15}≤1 µA @55",
     "Si2309CDS IGSS 100 nA; IDSS 1 µA@25 / 10 µA@55 (F65)",
     "F65: the 100 nA/1 µA pair conflated IGSS (gate) with IDSS (drain); "
     "IDSS is 1 µA @25 °C / 10 µA @55 °C (68980 p.2)"),
    (r"≤ ?0\.5 µA IDSS × 100 kΩ|R_exp_bleed = 100 kΩ|100 kΩ, EXP_3V3|"
     r"parked rail sits ≤ ?100 mV|parks the rail ≤ ?100 mV",
     "R_exp_bleed 10 kΩ → ≤50 mV @85 °C (F66)",
     "F66: the 100 kΩ bleed gave 500 mV at the NTR4171P 5 µA/85 °C limit "
     "(and an older row cited the retired ZXMP 0.5 µA/50 mV) → 10 kΩ, "
     "≤50 mV @85 °C"),
    (r"Si2309CDS / DMG3415U|display side.{0,10}0 *\|",
     "REVIEWER part list = NTR4171P; State-4 Q1-OFF ≠ 0",
     "F67: REVIEWER.md still named DMG3415U; State-4 treated Q1-OFF as "
     "zero (it has Q1/Q2 leakage terms)"),
    # iter-43 reviewer findings (F68-F71, addressed iter-44):
    (r"gate-driver N-FET|Q2 = \*\*60 V N-FET|Q2 \(2N7002, 60|"
     r"Q2 \[N-FET|60 V N-FET.{0,10}\(2N7002",
     "Q2 = MMBT5551 NPN BJT (F68)",
     "F68: the 2N7002 gate driver had no guaranteed on-state at 3.3 V and "
     "no temp-bounded off-leakage → MMBT5551 BJT (VCE(sat) guaranteed, "
     "ICBO ≤100 nA@100 °C). (2N7002 stays LIVE for Q3/Q4 — do not "
     "blanket-replace.)"),
    (r"Vgs_off = I_L\(Q2\)·R3.{0,40}2N7002L|0\.42 V @ ?85 °C.{0,20}2N7002|"
     r"2N7002L IDSS envelope",
     "BJT ICBO ≤100 nA@100 °C (F68)",
     "F68: the 2N7002 OFF-leakage interpolation is retired; the BJT's "
     "ICBO is a guaranteed 100 °C row"),
    (r"100 kΩ pull-up: Q1 gate|R3 \[100 kΩ|DZ1 \[12V\] clamps|"
     r"DZ1 clamps Vgs|holds (Q1 )?Vgs ≤ ?12 V|DZ1 12 V clamp scheme unchanged",
     "R3 10 kΩ; DZ1 redundant backstop (F64/F70)",
     "F70: stale R3=100k and DZ1-clamps-Vgs claims across battery-side/"
     "bom/manifest → R3 10 kΩ, DZ1 is a redundant backstop"),
    (r"~?1\.08 mW|~?1\.5 mW @ ?60 °C|~?0\.45 mW @ ?60 °C",
     "~1.13 mW @25 °C guaranteed / ≤~2.3 mW @100 °C ceiling",
     "F69: the ~1.08 mW headline predated the Q1/Q2 leakage rows; the "
     "'~1.5 mW @60 °C' was an interpolation → guaranteed 55 °C bound"),
    (r"\(same as R3\)|R4.{0,20}same as R3",
     "explicit reverse-resolved SKU",
     "F71: forbid same-as inheritance when the referenced row's value "
     "changed (R4 100k inherited R3's new 10k cells)"),
    # iter-45 reviewer findings (F72-F75, addressed iter-46):
    (r"ICBO ≤ ?100 nA|Vgs_off = ICBO·R3 ≤ ?\*\*1 mV|VCE\(sat\) ≤ ?0\.25 V.{0,15}(guaranteed|our)",
     "ICBO ≤50 µA@100 °C; Vgs_off ≤0.34 V; VCE(sat) 0.15/0.20 V (F72)",
     "F72: MMBT5551 ICBO is 50 nA@25/50 µA@100 (nA→µA unit misread), "
     "VCE(sat) 0.15/0.20 V (0.25 is the MMBT5550); R_be bleeder added so "
     "leakage isn't amplified"),
    (r"R3 10 ?kΩ / Rg 33 ?kΩ|R3 = 10 kΩ, Rg = 33 kΩ|divider R3 10k/Rg 33k|"
     r"R_base = ?47 ?kΩ|R_base 47 ?kΩ",
     "R3 6.8k / Rg 22k / R_base+R_be 10k (F72)",
     "F72: gate network re-valued — R3 10k→6.8k, Rg 33k→22k, R_base "
     "47k→10k, + R_be 10k bleeder"),
    (r"Q2 \(2N7002|Q2 = ?\*?\*?2N7002|Q2 drain|Q2 source|Q2 gate\b|"
     r"gate ◄── Rg \[33k\]|N-FET AO3400",
     "Q2 = MMBT5551 BJT; base/emitter/collector terminals (F74)",
     "F74: Q2 is a BJT now — use base/emitter/collector, not "
     "drain/source/gate; 2N7002 stays only for Q3/Q4"),
    # iter-48: the whole discrete Q1 gate driver → AQY212EH PhotoMOS SSR
    # (F76 resolution, user-approved). Q1/Q2/R3/Rg/R_base/R_be/DZ1 retired.
    (r"MMBT5551(?!.{0,80}(retired|superseded|replaced|removed|Retired))|"
     r"Si2309CDS(?!.{0,120}(retired|superseded|replaced|removed|Retired))|"
     r"R_be\b|R_base\b|gate-source divider|Vgs_off = ICBO|"
     r"BJT (driver|saturates)|divider is the (safety )?bracket",
     "AQY212EH PhotoMOS SSR (F76)",
     "F76: the discrete Q1 P-FET + Q2 BJT gate driver was replaced by the "
     "AQY212EH PhotoMOS SSR (no discrete driver could be datasheet-"
     "guaranteed OFF at temperature). Si2309CDS/MMBT5551/BZX84C12 retired"),
    (r"~?1\.13 mW @25 °C guaranteed|≤ ?~?2\.3 mW @100 °C|"
     r"~?1\.35 mW @55 °C",
     "hard-cut ~1.1 mW (SSR ≤1 µA)",
     "F76: the SSR's ≤1 µA off-leakage removed the Q1 IDSS + Q2 ICBO "
     "State-4 terms → hard-cut ~1.1 mW"),
    # iter-49 reviewer findings (F79-F82, addressed iter-50):
    # F79 — AQY212EH data were read off the AQY211EH sibling / 25 °C-only.
    # NOTE: bare "390 Ω" is LIVE (the RS-485 idle-bias resistor), so the
    # R_opto 390 form is scoped to opto/LED/PWR_EN context only.
    (r"Ron[^|]{0,6}0\.25|0\.25 ?Ω[^|]{0,12}(typ|SSR|AQY|Ron)|"
     r"R_opto[^|]{0,8}390|390 ?Ω[^|]{0,20}(opto|LED|PWR_EN|I_F)|"
     r"(opto|LED|PWR_EN|I_F)[^|]{0,20}390 ?Ω|4\.57 ?mA|"
     # SSR off-leakage claimed guaranteed/bounded at a HOT temp (85/100 °C):
     # scoped to SSR/off-leakage context so the saga's generic "a guaranteed
     # hot leakage [that discrete FETs lack]" (decisions.md) is NOT flagged.
     r"(AQY212|SSR|opto-?isolat|off-?leakage|off-?state)[^|]{0,45}"
     r"(guaranteed|bounded|≤ ?1 ?µA)[^|]{0,25}(85|100) ?°C",
     "Ron 0.85/2.5 Ω; R_opto 330 Ω; leakage ≤1 µA @25 °C (F79)",
     "F79: AQY212EH Ron is 0.85 typ / 2.5 max (0.25 Ω was the AQY211EH "
     "sibling row); R_opto 390→330 Ω for worst-case I_F ≥5 mA; hot "
     "off-leakage is NOT bounded — the spec is ≤1 µA @25 °C only "
     "(non-amplifying because there is no gate divider)"),
    # F80 — the SSR closes onto 22 µF C3; its 1.5 A/100 ms peak is one-shot.
    # Structural guard: the CURRENT series path is
    # "V24_FUSED → R_inrush → V24_SW"; the direct (pre-fix) path is stale.
    (r"V24_FUSED\s*→\s*(\*\*)?V24_SW|"
     r"1\.5 ?A ?/ ?100 ?ms[^|]{0,25}(continuous|steady|rating)(?![^|]{0,20}one-shot)|"
     r"closes? directly onto[^|]{0,20}(22 ?µF|C3)(?![^|]{0,40}R_inrush)",
     "V24_FUSED → R_inrush (22 Ω) → V24_SW; inrush ≤1.33 A (F80)",
     "F80: R_inrush 22 Ω 1206 hard-caps SSR turn-on inrush into C3 to "
     "≤1.33 A @29 V even at Ron=0, under the 1.5 A/100 ms one-shot peak; "
     "the direct V24_FUSED→V24_SW path (no limiter) is retired"),
    # F81 — generic discrete gate-driver topology forms. R3 stays LIVE as
    # the RS-485 idle-bias resistor, so ONLY R3-in-gate-context is stale;
    # DZ1 and the Q2 gate transistor are fully removed (bare forms safe).
    (r"\bQ1\b[^|]{0,30}(P-?FET|P-?MOSFET|load switch|gate)|"
     r"(P-?FET|P-?MOSFET|load switch)[^|]{0,12}\(?Q1\)?|"
     r"(drives|opens?|holds?|via|behind|re-?engages?|closes?|switched behind)\s+Q1\b|"
     r"\bQ1\b\s+(ON|OFF|is OFF|conducts|stays)|"
     r"Q2\s+(drain|source|gate|base|collector|pulls)|"
     r"\bQ2\b[^|]{0,30}(BJT|N-?FET|MMBT|gate driver)|"
     r"\bDZ1\b|"
     r"gate[- ]?clamp[^|]{0,10}(Zener|DZ1)|"
     r"(Q1 )?gate pull-?up[^|]{0,10}R3|R3[^|]{0,15}(Q1 )?gate",
     "SSR1 / AQY212EH PhotoMOS SSR (F81)",
     "F81: generic discrete gate-driver topology forms — Q1 as a "
     "P-FET/load switch, its ON/OFF operating state, the Q2 gate "
     "transistor terminals, the DZ1 gate-clamp Zener, and R3-as-gate-"
     "pullup — must read SSR1/AQY212EH. R3 remains LIVE as the RS-485 "
     "idle bias, so only R3-in-gate-context is flagged"),
    # F82 — the ordered SMAJ TVS objects are Diodes Inc -13-F, not
    # Littelfuse. The FUSE (0215001.MXP) IS Littelfuse — do NOT flag it,
    # so the pattern is scoped to "Littelfuse" adjacent to a TVS token.
    (r"Littelfuse\s+SMAJ|SMAJ\w*\s*[—-]\s*Littelfuse|"
     r"Littelfuse[^|]{0,18}(TVS|bidirectional|clamp)|"
     r"(TVS|bidirectional)[^|]{0,18}Littelfuse",
     "Diodes Incorporated SMAJxx-13-F (DS19005 = SMAJ_Diodes.pdf)",
     "F82: the ordered SMAJ TVS parts are Diodes Inc -13-F "
     "(SMAJ_Diodes.pdf = DS19005), not Littelfuse. The FUSE 0215001.MXP "
     "IS genuinely Littelfuse — this pattern is scoped to SMAJ/TVS "
     "context so the fuse row is never flagged"),
    # iter-51 reviewer findings (F83-F85, addressed iter-52):
    # F83 — the SSR 25 °C ≤1 µA leakage was carried as a temperature-bounded
    # State-4 term. Catch the specific "(bounded" framing and the un-caveated
    # "≤1 µA (spec) … −40…+85 °C" that presents 25 °C data as a hot bound.
    (r"≤ ?0\.024 mW \(bounded|bounded[,;]? ≤ ?0\.024 mW|"
     r"clean \*{0,2}~?1\.1 mW\*{0,2} with a bounded|"
     r"rises modestly but is bounded|"
     r"≤ ?1 µA \(spec\)\*{0,2}, rated −40",
     "≤1 µA @25 °C only; hot = estimate + <5 mW acceptance test (F83)",
     "F83: the SSR 25 °C ≤1 µA / ≤0.024 mW leakage was framed as a "
     "temperature-bounded State-4 term; the datasheet publishes no hot "
     "max → label 25 °C-only + carry an explicit hot estimate (no "
     "≤/bounded) + a <5 mW State-4 leakage acceptance test"),
    # F84 — R_inrush 22 Ω relied on the SSR one-shot for the recurring
    # inrush and had no downstream-short coordination. Retired: the 22 Ω
    # value/SKUs and the ≤1.33 A one-shot-referenced inrush claim.
    (r"RMCF1206FT22R0|71-CRCW1206-22-E3|"
     r"R_inrush[^|]{0,4}=?\s?22 ?Ω|22 ?Ω[^|]{0,12}(1206|R_inrush|inrush)|"
     r"(inrush|SSR turn-on)[^|]{0,15}22 ?Ω|"
     r"≤ ?1\.33 A|1\.33 A @ ?29|1\.09 A @ ?24",
     "R_inrush = 2× 75 Ω 1206-HP series (=150 Ω) + F2 80 mA (F84/F86/F87)",
     "F84: R_inrush 22 Ω limited inrush only against the SSR's one-shot "
     "1.5 A/100 ms peak (a recurring event) and had no fault coordination "
     "→ the coordinated 2× 75 Ω 1206-HP series + 80 mA fuse network"),
    # F86/F87/F88/F89 (iter-53) — the 220 Ω and single-150 Ω R_inrush, the
    # 62 mA fuse, and the non-resolving Mouser SKU were superseded iter-54.
    # Guard the exact retired MPNs/SKUs (unambiguous — no bare "62 mA",
    # which is live as F87 history like "not the 62 mA I first used").
    (r"CRCW1206220RFKEAHP|CRCW1206150RFKEAHP|71-CRCW1206150RFKEAHP|"
     r"541-150UTR-ND|R_inrush[^|]{0,6}220 ?Ω|220 ?Ω[^|]{0,12}(pulse|R_inrush|1206-HP)|"
     r"0451\.062MRL|F3153TR-ND|576-0451\.062MRL|"
     r"single 1206-HP (survives|is guaranteed)|9\.4 W/5 s at (the )?1\.5 W",
     "2× 75 Ω 1206-HP (CRCW120675R0FKEAHP, 541-75.0UTR-ND / "
     "71-CRCW120675R0FKEAH) + 80 mA fuse 0451.080MRL (F86-F89)",
     "F89: 220 Ω/single-150 Ω R_inrush + 62 mA fuse were intermediate; "
     "F86: §8.1 uses P70=0.75 W (4.69 W), a single 1206-HP fails → 2× 75 Ω; "
     "F88: 71-CRCW1206150RFKEAHP resolves none → 71-CRCW120675R0FKEAH"),
    # F91 (iter-55) — the Littelfuse 0451.080MRL fuse is a 2-SMD Square-End-
    # Block 6.10×2.69 mm body with its own p.4 land pattern, NOT a 1206 chip.
    # Scoped to F2/451/fuse context so the legitimate 1206 R_inrush is not hit.
    # Precise: the fuse's Part cell (…451 Nano2 SMF… / 0451.0xx) immediately
    # followed by a Pkg cell that is exactly "1206" (one | crossing). This
    # catches the mislabel without hitting the corrected "451 SMF … not 1206"
    # forms (Pkg cell is not "1206") or the F2→R_inrush-1206 flow lines.
    (r"(451 Nano2 SMF|0451\.0[0-9]{2})[^|]{0,35}\|\s*1206\s*\|",
     "F2 = Littelfuse 451 SMF, 6.10×2.69 mm dedicated land pattern (NOT 1206)",
     "F91: the 0451.080MRL is a 2-SMD Square-End-Block ~6.10×2.69 mm body "
     "with its own recommended land pattern (datasheet p.4), not a 1206 "
     "chip — using the 1206 footprint at CP2 would be wrong"),
    # F85 — the retired 390 Ω R_opto SKUs (F79 value change left the exact
    # old SKU pair live in D19). Distance-limited F79 pattern missed them.
    (r"RMCF0805FT390RCT-ND|71-CRCW0805390RFKEA|CRCW0805390",
     "R_opto 330 Ω: RMCF0805FT330RCT-ND / 71-CRCW0805-330-E3 (F79/F85)",
     "F85: the retired 390 Ω R_opto SKUs (worst-case 4.57 mA < the 5 mA "
     "recommended min) → the 330 Ω pair"),
    # CP2 iter-1 F01 — J5 was a 1×6 pin strip claiming "exact ESP-Prog
    # order"; the real Program interface is a keyed 2×3 with GND on pin 4
    # and target-perspective TXD/RXD (ESP-Prog SCH V2.1 on file).
    (r"EN/VDD/TXD/RXD/IO0/GND|1×6.{0,25}ESP-Prog|ESP-Prog.{0,25}1×6|"
     r"PinHeader_1x06.{0,20}J5|J5.{0,30}6-pin 2\.54 mm header(?!.{0,40}(keyed|2×3))",
     "keyed 2×3: EN/VDD/TXD/GND/RXD/IO0 (F01)",
     "F01: the J5 1×6 'exact ESP-Prog order' claim was wrong — the Program "
     "interface is a keyed 2×3 (1 EN / 2 VDD / 3 TXD / 4 GND / 5 RXD / "
     "6 IO0, target-perspective TXD/RXD per ESP-Prog SCH V2.1)"),
    # CP2 iter-1 F03 — D2 CAN TVS populated-by-default with a protection
    # claim; the NUP2105L clamps far above the TCAN332 ±14 V abs-max.
    (r"Belt-and-braces on the field cable|"
     r"NUP2105L[^|]{0,40}(coordinat|brackets? U7|protects U7)",
     "D2 = DNP, no coordination claimed (F03)",
     "F03: NUP2105L (VBR 26.2–32 V, clamp to 40/44 V) cannot bracket the "
     "TCAN332 ±14 V bus abs-max → DNP footprint, protection = on-chip ESD "
     "(same call as the RS-485 ports, F44)"),
    # CP2 iter-2 F05 — the RJHSE-538X placeholder (and its no-hyphen KiCad
    # footprint name) is the 2-LED sibling with pads 9-12; the ordered part
    # is the LED-less RJHSE-5380. Footprint existence passed the wrong
    # variant → [exact-part] contract in build.py + this token guard.
    (r"RJHSE-?538X",
     "RJHSE-5380 / Connector_RJ:RJ45_Amphenol_RJHSE5380 (F05)",
     "F05: RJHSE-538X is the 2-LED variant (16 pads); the selected part is "
     "the LED-less RJHSE-5380 (12 pads) — exact value+footprint pinned by "
     "the [exact-part] build contract on J2/J6/J10/J11"),
    # CP2 iter-3 F10 — the ORIGINAL pre-F01 J5 (4-pin debug UART with
    # RESET# on pin 4) survived in cp1_battery_side.md: the F01 registry
    # rows guarded the 1×6/order-string forms but not this older shape.
    (r"TX/RX/GND/RESET#|ESP EN pin / J5 pin 4\b|"
     r"J5 pin 4[^|]{0,25}RESET|RESET#[^|]{0,25}J5 pin 4",
     "keyed 2×3 ESP-Prog: EN=pin 1, GND=pin 4, BOOT=pin 6 (F01/F10)",
     "F10: the 4-pin debug-UART J5 (TX/RX/GND/RESET#) and RESET#-on-J5.4 "
     "forms are retired — J5 is the keyed 2×3 ESP-Prog Program header; EN "
     "is pin 1 and pin 4 is GND"),
    # CP2 display-iter1 F13 — the GCT USB4085 is a THT ("Dip Type, PCB Top
    # Mount") connector; every BOM/design row that classifies the USB-C
    # receptacle as SMD is wrong (the KiCad footprint has 20 THT pads).
    (r"USB.?4085[^\n]{0,60}\|\s*SMD\s*\||USB-C receptacle[^\n]{0,80}\|\s*SMD\s*\|",
     "THT top-mount",
     "F13: USB4085 is through-hole (GCT exact drawing p.1: Dip Type, PCB "
     "Top Mount; footprint = 20 THT pads) — 'SMD' package cells are wrong"),
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
    "MSTBA 2,5/2-G-5,08 (1757242, J1 board header)": "1757242",
    "LCD1 Waveshare 4.2\" e-Paper Module (B)": "Waveshare",
    "8125SHZBE (BTN1 battery override)": "8125SHZBE",
    "RJHSE-5380": "RJHSE5380",
    "AP2112K-3.3TRG1": "AP2112K-3.3",
    "ZXMP6A13FTA": "ZXMP6A13F",
    "BZX84C12LT1G": "BZX84C12",
    "0215001.MXP": "0215001",
    "2N7002LT1G (onsemi)": "2N7002LT1G",
    "USB4085-GF-A (exact drawing)": "USB4085-GF-A",
    # PS-51021-024 covers the whole PicoBlade W/B system; the BOM row is
    # the header (J_EXP) which cites the spec by document number:
    "53398/53261 + 51021/50079/50058 system": "PS-51021-024",
}


# F85 (iter-51): the history exemption must apply to the matched token's OWN
# clause, not any history word elsewhere on the line. A table row's Part cell
# can carry a stale "Ron 0.25 Ω" while the Notes cell (a different clause) says
# "replaced …" — the old whole-line check wrongly exempted it. Clause = the
# table cell (| … |) containing the match, further split by sentence/clause
# delimiters (; and sentence-final ". ") so distinct statements in one cell
# don't cross-exempt. NOT the em-dash — it joins a clause to its parenthetical
# ("corrected to 330 Ω — 390 Ω gave 4.57 mA"), so splitting on it severs a
# marker from the token it governs.
CLAUSE_DELIM = re.compile(r";|\.\s")


def _clause_around(line: str, start: int, end: int) -> str:
    cs = line.rfind("|", 0, start) + 1          # table-cell left bound
    ce = line.find("|", end)
    if ce == -1:
        ce = len(line)
    cell = line[cs:ce]
    s, e = start - cs, end - cs
    left = 0                                     # sub-clause within the cell
    for m in CLAUSE_DELIM.finditer(cell[:s]):
        left = m.end()
    m = CLAUSE_DELIM.search(cell, e)
    right = m.start() if m else len(cell)
    return cell[left:right]


def _in_strikethrough(line: str, start: int, end: int) -> bool:
    return any(m.start() <= start and end <= m.end()
               for m in re.finditer(r"~~.+?~~", line))


def _allowed(line: str, lines: list[str], idx: int, rel: str,
             current: str | None, start: int, end: int) -> bool:
    if rel in HISTORY_FILES:
        return True
    if _in_strikethrough(line, start, end):
        return True                              # struck text = superseded
    clause = _clause_around(line, start, end)
    if HISTORY_MARKERS.search(clause):
        return True                              # marker in the MATCH's clause
    # A bare history WORD must be in the token's clause (above) — but if the
    # line literally names the CURRENT part token (a real "old → new"
    # comparison / evolution chain), that is self-evident regardless of column,
    # so the current-token check stays at LINE scope. This is the key F85
    # distinction: "replaced" alone in another cell no longer exempts a stale
    # value (the reviewer's Ron 0.25 bug — the row never named the right 0.85),
    # but "R-78E12 … | R-78HB12" or "AO3401A → … → Si2309CDS" still does.
    if current and current in line:
        return True
    if rel.endswith("decisions.md"):
        # decisions.md is an append-only narrative; a bracket-note's
        # supersession marker may sit a few lines above the matched token
        # (the "history section" allowance). Kept, but scoped to a real
        # supersession word (NEARBY_MARKERS, F81) within the window.
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
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines):
            for pattern, current, hint in SUPERSEDED:
                for m in re.finditer(pattern, line):
                    if not _allowed(line, lines, idx, rel, current,
                                    m.start(), m.end()):
                        findings.append(
                            f"[stale] {rel}:{idx + 1}: /{pattern}/ live "
                            f"(should be: {hint})\n    > {line.strip()[:140]}"
                        )
                        break  # one finding per (pattern, line) is enough
    return findings


def check_d32_manifest() -> list[str]:
    findings = []
    if not MANIFEST.exists():
        return [f"[d32] manifest missing: {MANIFEST}"]
    text = MANIFEST.read_text(encoding="utf-8")
    active_section = text.split("## Still needed")[0]
    rows = re.findall(r"^\| ([^|]+?) \| ([^|]+?) \|", active_section, re.M)
    bom_text = CANONICAL_BOM.read_text(encoding="utf-8")
    n = 0
    # CP3 F02: a duplicated identity slipped through — same PDF referenced
    # by two rows, one carrying a stale hash the checker never verified.
    # Uniqueness + hash-verification are now mechanical.
    seen_pdfs: dict[str, str] = {}
    hash_rows = re.findall(
        r"^\| ([^|]+?) \| ([^|]+?) \|[^|]*\|[^|]*\| ([0-9a-f]{12}) \|",
        active_section, re.M)
    file_hashes: dict[str, set] = {}
    for mpn, pdf_cell, h12 in hash_rows:
        m = re.match(r"(\S+\.pdf)", pdf_cell.strip())
        if not m:
            continue
        file_hashes.setdefault(m.group(1), set()).add(h12)
        f = DATASHEET_DIR / m.group(1)
        if f.exists():
            import hashlib
            actual = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
            if actual != h12:
                findings.append(
                    f"[d32] manifest '{mpn.strip()}': recorded hash {h12} != "
                    f"actual {actual} for {m.group(1)} — stale identity row")
    # one file, two recorded hashes = a stale duplicate identity (F02's
    # exact shape); a family PDF backing several variant rows with ONE
    # hash is legitimate
    for fname, hs in file_hashes.items():
        if len(hs) > 1:
            findings.append(
                f"[d32] conflicting hashes recorded for {fname}: "
                f"{sorted(hs)} — collapse to one canonical identity row")
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
    # F75 (iter-45): reverse check — every PDF in the active store must be
    # referenced by a manifest row (or the Retired section). An unmanifested
    # PDF is exactly the stale-object shape D32 exists to prevent.
    # match basenames only (word/dot/plus/hyphen) so leading "(" or a
    # path prefix or backtick does not corrupt the compare (F75).
    manifested = set(re.findall(r"([\w.+-]+\.pdf)", text))
    for pdf in sorted(DATASHEET_DIR.glob("*.pdf")):
        if pdf.name not in manifested:
            findings.append(
                f"[d32] orphan PDF in active store: {pdf.name} has no "
                f"manifest row — remove it or add a provenance row (F75)"
            )
    n_verify = len(re.findall(r"_verify", bom_text))
    print(f"  info: {n} manifest parts checked; {n_verify} BOM cells still "
          f"at _verify_ (MPN not chosen — D32 applies when chosen)")
    return findings


# ---------------------------------------------------------------------------
# CP2 iter-1 F03 (reviewer): the D32 check above only validates manifest rows
# that EXIST — a chosen BOM MPN with no manifest row at all (the NUP2105L)
# sailed through. Reverse direction: every canonical-BOM table row carrying a
# chosen distributor SKU must be covered by a manifest datasheet row, or carry
# an explicit jellybean exemption here. APPEND-ONLY, reason required.
# (ref-cell regex, reason)
# ---------------------------------------------------------------------------
NO_DATASHEET_OK: list[tuple[str, str]] = [
    (r"^(R_opto|R4|R5|R6|R7|R10|R13|R_exp_bleed|R8, R9|R5, R6, R7)$",
     "precision chip resistor — value/tolerance/size commodity; no "
     "interface or abs-max contract beyond the value itself; SKUs "
     "API-resolved 2026-07-14 sweep"),
    (r"^(C5|C6|C7|C8|C9)$",
     "standard X7R MLCC — value/size commodity; SKUs API-resolved "
     "2026-07-14 sweep (the HV C_stitch C28/C38 is NOT exempt — manifested)"),
    (r"^J4$",
     "commodity 2.54 mm 2-pin header + shunt (term-lift jumper) — no "
     "interface contract"),
]


def check_bom_mpn_coverage() -> list[str]:
    findings = []
    man_text = MANIFEST.read_text(encoding="utf-8")
    # Coverage tokens: manifest MPN cells (full + head token) + BOM aliases.
    toks: set[str] = set()
    for m in re.finditer(r"^\| ([^|]+?) \|", man_text, re.M):
        cell = m.group(1).strip()
        if cell in ("MPN", "Ref", "Part") or cell.startswith((":-", "--")):
            continue
        toks.add(cell)
        head = cell.split()[0].rstrip(",(")
        if len(head) > 3:
            toks.add(head)
    toks |= set(MANIFEST_TO_BOM_ALIAS.values())
    for lineno, line in enumerate(CANONICAL_BOM.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("|") or not re.search(r"\b[\w.]+-ND\b", line):
            continue                          # not a chosen-DK-SKU table row
        if "~~" in line or "_verify_" in line or "DNP" in line \
                or "(same as" in line:
            continue                          # struck / unchosen / no-pop rows
        cells = [c.strip() for c in line.split("|")]
        ref = cells[1] if len(cells) > 1 else ""
        if not ref or ref in ("Ref",) or ref.startswith((":-", "--")):
            continue
        if any(tok and tok in line for tok in toks):
            continue                          # covered by a manifest row
        for pat, _reason in NO_DATASHEET_OK:
            if re.match(pat, ref):
                break
        else:
            findings.append(
                f"[bom-cov] {CANONICAL_BOM.name}:{lineno}: chosen-SKU row "
                f"'{ref}' has no manifest datasheet row and no "
                f"NO_DATASHEET_OK exemption (F03 class)\n"
                f"    > {line.strip()[:120]}"
            )
    # F13: parts whose family-level datasheet cannot establish the exact
    # ordered object need the manufacturer's EXACT drawing on file too
    # (the USB4085 family spec has no ordering grid; only the drawing
    # decodes -GF-A). Require both the manifest row and the PDF.
    EXACT_OBJECT_DRAWING = {
        "USB4085": "USB4085_drawing.pdf",
    }
    bom_text = CANONICAL_BOM.read_text(encoding="utf-8")
    for token, drawing in EXACT_OBJECT_DRAWING.items():
        if token in bom_text:
            if drawing not in man_text:
                findings.append(
                    f"[exact-object] BOM pins {token} but the manifest has "
                    f"no {drawing} row (F13: family spec alone cannot "
                    f"identify the exact ordered variant)")
            if not (DATASHEET_DIR / drawing).exists():
                findings.append(
                    f"[exact-object] {drawing} missing from "
                    f"hardware/datasheets/ (F13)")
    return findings


# F85 (iter-51): regression fixtures — the gate fails if any regresses. This
# locks the clause-scoping fix and the retired-SKU rows exactly the way the
# reviewer asked: the pre-fix text must FAIL (flag) and the corrected text
# must PASS (no flag). Each entry is (text, should_flag).
FIXTURES: list[tuple[str, bool]] = [
    # F85: a stale "Ron 0.25 Ω" in the Part cell while the Notes cell says
    # "replaced" — the exact bug the old whole-line exemption suppressed.
    ("| SSR1 | AQY212EH PhotoMOS SSR (60 V / 550 mA, Ron 0.25 Ω) | DIP-4 "
     "| 1 | PCB | $2.81 | F76: replaced the discrete Q1 P-FET + Q2 BJT "
     "gate driver |", True),
    ("| SSR1 | AQY212EH PhotoMOS SSR (60 V / 550 mA, Ron 0.85 Ω typ / "
     "2.5 Ω max) | DIP-4 | 1 | PCB | $2.81 | F76: replaced the discrete "
     "Q1 P-FET + Q2 BJT gate driver |", False),
    # F85: the retired 390 Ω R_opto SKU pair.
    ("R_opto = RMCF0805FT390RCT-ND / 71-CRCW0805390RFKEA (resolve-exact "
     "2026-07-17)", True),
    ("R_opto = RMCF0805FT330RCT-ND / 71-CRCW0805-330-E3 (330 Ω, F79 — "
     "the earlier 390 Ω pair retired)", False),
    # F84: the retired 22 Ω R_inrush + its one-shot-referenced inrush claim.
    ("R_inrush = 22 Ω hard-caps the turn-on inrush to ≤1.33 A @29 V — "
     "under the 1.5 A/100 ms one-shot", True),
    # F89: the retired 220 Ω and single-150 Ω intermediate designs must FLAG.
    ("R_inrush 220 Ω limits the recurring turn-on inrush to 0.134 A — "
     "below the SSR 0.30 A@85 °C continuous", True),
    ("R_inrush 150 Ω 1206-HP; single 1206-HP survives 5.2 W under 9.4 W/5 s "
     "at the 1.5 W rating", True),
    # F88: the non-resolving Mouser SKU must FLAG.
    ("R_inrush 71-CRCW1206150RFKEAHP 541-150UTR-ND", True),
    # The FINAL iter-54 design must PASS (no flag).
    ("R_inrush = 2× 75 Ω 1206-HP (CRCW120675R0FKEAHP, 541-75.0UTR-ND / "
     "71-CRCW120675R0FKEAH) series = 150 Ω; each 2.87 W < 4.69 W/5 s at "
     "P70=0.75 W; F2 80 mA 0451.080MRL clears at 246 %", False),
    # F91: the fuse mislabeled as 1206 must FLAG; the real land pattern passes;
    # the legitimate 1206 R_inrush must NOT flag.
    ("| F2 | 80 mA very-fast SMD fuse (Littelfuse 451 Nano2 SMF) | 1206 | 1 |",
     True),
    ("| F2 | 80 mA (Littelfuse 451 Nano2 SMF) | 451 SMF, 6.10×2.69 mm "
     "(p.4 land pattern, not 1206) | 1 |", False),
    ("| R_inrush (×2) | 2× 75 Ω 1206 pulse-proof (Vishay CRCW-HP) | 1206 | 2 |",
     False),
    # F10: the exact pre-fix cp1_battery_side.md forms must FLAG…
    ("| J5  | 4-pin 2.54 mm pin header, **debug UART** (TX/RX/GND/RESET#) "
     "| THT | 1 | FTDI cable lands here |", True),
    ("| RESET#       | 3.3 V LV    | ESP EN pin / J5 pin 4 | **U4 RESET via "
     "Q3** |", True),
    # …and the corrected forms must PASS (no flag).
    ("| J5  | Keyed 2×3 IDC box header — ESP-Prog Program pinout: 1=MCU_EN, "
     "2=V3V3, 3=DBG_TXD, 4=GND, 5=DBG_RXD, 6=BOOT | THT | 1 |", False),
    ("| MCU_EN (RESET#) | 3.3 V LV | ESP EN pin / J5 pin 1 | U4 RESET via "
     "Q3 |", False),
    # A bare 4-pin UART row with no RESET#/J5-pin-4 token must NOT flag
    # (scope test; the display J3 row this once modeled is now itself a
    # keyed 2×3 ESP-Prog per display-CP2 DR-32).
    ("| J3  | 4-pin 2.54 mm header (UART debug) | THT | 1 | bench only |",
     False),
    # F13: a USB4085 (or generic USB-C receptacle) row classified SMD must
    # FLAG; the corrected THT rows must PASS.
    ("| J-USB | **USB-C receptacle GCT USB4085-GF-A** (native ESP32-S3 USB, "
     "board edge) | SMD | 1 |", True),
    ("| J-USB     | **USB-C receptacle** (native ESP32-S3 USB, board edge) "
     "| SMD | 1 | PCB |", True),
    ("| J3  | **USB-C receptacle GCT USB4085-GF-A** (native ESP32-S3 USB) "
     "| THT top-mount (F13: GCT drawing = \"Dip Type, PCB Top Mount\"; 20 "
     "THT pads) | 1 |", False),
]


def run_fixtures() -> list[str]:
    fails = []
    for text, should_flag in FIXTURES:
        flagged = False
        for pattern, current, _hint in SUPERSEDED:
            for m in re.finditer(pattern, text):
                if not _allowed(text, [text], 0, "__fixture__", current,
                                m.start(), m.end()):
                    flagged = True
                    break
            if flagged:
                break
        if flagged != should_flag:
            fails.append(
                f"[fixture] expected flag={should_flag}, got {flagged}: "
                f"{text[:72]}"
            )
    return fails


def main() -> int:
    findings = run_fixtures()  # self-test first — a broken gate can't certify
    findings += check_stale_tokens()
    findings += check_d32_manifest()
    findings += check_bom_mpn_coverage()
    if findings:
        print(f"\n{len(findings)} finding(s):\n")
        for f in findings:
            print("  " + f)
        return 1
    print("clean: no unmarked stale tokens; D32 manifest ↔ PDF ↔ BOM consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
