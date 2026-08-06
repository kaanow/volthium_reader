# Repo-local footprint library (`volthium.pretty`)

Footprints not present in the KiCad 10 stock libraries. The build gate
(`core.py` `_FP_DIRS`) resolves the `volthium:` prefix here; at CP3 the
layout's `fp-lib-table` must add this library under the same nickname.

| Footprint | Part | Provenance |
|-----------|------|------------|
| `J_Wurth_WR-MJ_615008145521.kicad_mod` | Würth 615008145521 WR-MJ RJ45, horizontal shielded EMI-finger 8P8C tab-down (display J1) | **Manufacturer-official**, vendored verbatim from [WurthElektronik/KiCad-Library](https://github.com/WurthElektronik/KiCad-Library) `footprints/Connector_THT_Wurth.pretty/`, commit `fdbe2d0192`, fetched 2026-07-27. sha256 `38db7c97fd9b…899684`. License: Würth `License_Terms_WE_KiCad_library.pdf` (free use for designing with WE products). |
| `ESP32-S3-WROOM-1_HSvia0.3.kicad_mod` | ESP32-S3-WROOM-1 module (both boards, MOD1) | KiCad 10 stock `RF_Module:ESP32-S3-WROOM-1` with ONE delta: the 12 heatsink via-in-pad drills bumped 0.2 → 0.3 mm (pad 0.6 mm → 0.15 mm annular ring). Rationale: JLCPCB 2-layer min drill is 0.3 mm (cp1_battery_side §12); the stock 0.2 mm EP stitching vias violate the fab floor. Found mechanically by the CP3 `pcb/fplib.py` drill scan, 2026-07-29. |
| `ESP32-S3-WROOM-1_HSvia0.3_NoAntKeepout.kicad_mod` | ESP32-S3-WROOM-1 module, **display board only** (MOD1) | Derived from `ESP32-S3-WROOM-1_HSvia0.3` with ONE delta: the F.CrtYd T-shape (body stem + 48 × 21 mm antenna-keepout flare) replaced by a body-hugging 19.50 × 26.50 mm rectangle. Rationale: **D26** dropped the antenna keepout on the display board (radio unused — RS-485 is the only link), so the stock courtyard encodes a constraint this board formally retired, and honouring it would sterilise 36 % of an 85 × 65 mm PCB. The courtyard now means what the placement gate uses it for: physical interference. **Second delta 2026-08-06 (CP4 iter2):** the stock footprint also carried `fp_text user "KEEP-OUT ZONE"` on Cmts.User — an annotation asserting on the board documentation exactly the constraint D26 retired. It surfaced in the CP4 envelope plot and is removed here; the factual "Antenna" label is kept. Verified 2026-08-05: 62/62 pads coordinate-identical to the parent, only graphic delta is F.CrtYd 8 → 4 segments. **The battery board keeps the full-keepout parent — its radio IS used (D25 OTA).** Reversing D26 requires re-placing the display board. |

## Why vendored, and the pin-map verification (2026-07-27)

KiCad stock has no footprint for 615008145521. The datasheet's numbered
top view is ambiguous to read (digits sit in the diagonal gaps of the
staggered field), and this jack's tail fan-out is **non-monotone** — a
hand-derived pattern was rejected in favor of the manufacturer's own:

- far row (8.89 mm from the mounting posts): pins **1, 5, 6, 7** at
  x = 0 / 2.54 / 5.08 / 7.62
- near row (6.35 mm from posts): pins **2, 3, 4, 8** at
  x = −1.27 / 1.27 / 3.81 / 6.35
- x-order across both rows: `2, 1, 3, 5, 4, 6, 8, 7` — NOT the
  monotone-alternating comb of e.g. the Amphenol RJHSE5380 or Würth's
  own 7499010001A magjack.

Cross-checks performed: every official pad coordinate matches the
datasheet Recommended Hole Pattern (rows 2.54 apart, 1.27 stagger,
posts Ø3.2 span 11.43 at 8.89, shield Ø1.7 span 15.50 at 5.84,
signal drills 0.9), and the datasheet's numbered view agrees with the
official map once the label convention is decoded (each digit sits
~1.2 mm right of its own hole).
