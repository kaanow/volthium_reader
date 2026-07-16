# Datasheet manifest

Local datasheet store for **every active BOM part** (CP1 gate, decisions D32).
Fetched via the parts-sourcing API `/datasheet` proxy where reachable; the rest
pulled manually. Read + interface-verified per D32.

| MPN | file | provider | source | sha256 (12) |
|-----|------|----------|--------|-------------|
| 0215001.MXP | 0215001.MXP.pdf (763K) | manual | user download 2026-07-01 | 6ea4fed8f791 |
| 1757242 | 1757242.pdf (1388K) | manual | user download 2026-07-01 | 7b6cfef0980a |
| 2N7002 | 2N7002.pdf (303K) | digikey | https://diotec.com/request/datasheet/2n7002.pdf | 4904d73f5fb8 |
| 615008145521 | 615008145521.pdf (844K) | digikey | https://www.we-online.com/components/products/datasheet/615008145521.pdf | da03e4ed6257 |
| AP2112K-3.3TRG1 | AP2112K-3.3TRG1.pdf (737K) | digikey | https://www.diodes.com/assets/Datasheets/AP2112.pdf | ef8d376f2ec3 |
| B8B-PH-K-S | B8B-PH-K-S.pdf (100K) | digikey | https://www.jst-mfg.com/product/pdf/eng/ePH.pdf | 447624f4f2f7 |
| BZX84C12LT1G | BZX84C12LT1G.pdf (464K) | manual | user download 2026-07-01 | f9818d9dfc03 |
| ESP32-S3-WROOM-1-N16R8 | ESP32-S3-WROOM-1-N16R8.pdf (1250K) | digikey | https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf | 27d71971da07 |
| LM5166YDRCR | LM5166YDRCR.pdf (3436K) | digikey | https://www.ti.com/lit/ds/symlink/lm5166.pdf?ts=1782455459808&ref_url=https%253A%252F%252Fwww.ti.com | 1817a5b4f779 |
| MF-R025 | MF-R025.pdf (1059K) | digikey | https://www.bourns.com/docs/product-datasheets/mf-r.pdf | ad20425ca080 |
| R-78E3.3-0.5 | R-78E3.3-0.5.pdf (628K) | digikey | https://recom-power.com/pdf/Innoline/R-78E-0.5.pdf | d3855b950078 |
| R-78HB12-0.5 | R-78HB12-0.5.pdf (1836K) | digikey | https://recom-power.com/pdf/Innoline/R-78HB-0.5.pdf | 457ccbb2825f |
| RJHSE-5380 | RJHSE-5380.pdf (102K) | digikey | https://cdn.amphenol-cs.com/media/wysiwyg/files/drawing/rjhsex380.pdf | 3254d85eaaa6 |
| RV-3028-C7 | RV-3028-C7.pdf (830K) | manual | user download 2026-07-01 | fb5a01874b3e |
| SMAJ12CA-13-F | SMAJ_Diodes.pdf (116K) | mouser (API proxy) | https://www.mouser.com/catalog/specsheets/ds19005.pdf — Diodes DS19005; p.1 ordering row names SMAJxxx(C)A-13-F (iter-23 F20: non-F variants Obsolete); p.2 device table VC 19.9 V @ 20.1 A | 70bd31105424 |
| SMAJ15A-13-F | SMAJ_Diodes.pdf (same file) | " | " — p.2 device table VC 24.4 V @ 16.4 A, matches D19/DR-15 coordination | 70bd31105424 |
| SMAJ33CA-13-F | SMAJ_Diodes.pdf (same file) | " | " — p.2 device table VC 53.3 V @ 7.5 A, matches the ~53 V clamp coordination (SS26 60 V, R-78HB12 72 V) | 70bd31105424 |
| THVD1400DR | THVD1400DR.pdf (1447K) | digikey | https://www.ti.com/lit/ds/symlink/thvd1400.pdf | 5ba9785d9fb8 |
| SS26-E3/52T | SS26-E3_52T.pdf (151K) | digikey | https://www.vishay.com/docs/88748/ss22.pdf | 4bcd8bc129f3 |
| TPS2116DRLR | TPS2116DRLR.pdf (2855K) | digikey | https://www.ti.com/lit/ds/symlink/tps2116.pdf | 5babd88afb84 |
| TPS3808G01DBVR | TPS3808G01DBVR.pdf (2034K) | digikey | https://www.ti.com/lit/ds/symlink/tps3808.pdf | 682abbc06a0c |
| USBLC6-2SC6Y | USBLC6-2SC6Y.pdf (117K) | manual | user download 2026-07-01 | c0352261dede |
| ZXMP6A13FTA | ZXMP6A13FTA.pdf (246K) | digikey | https://www.diodes.com/assets/Datasheets/ZXMP6A13F.pdf | bb474f827be4 |
| MSTB 2,5/2-ST-5,08 (1757019) | 1757019.pdf (2400K) | manual | user upload 2026-07-01 | d849479aae64 |
| LCD1 Waveshare 4.2" e-Paper Module (B) | Waveshare-4.2-ePaper-B.pdf (3.9M — **subordinate bare-panel V2 manual only**, sha 32b126146869: SPI timing, panel specs, active area 84.8×63.6 mm; its p.7 shows the raw 24-contact FPC panel, not the ordered Module). **Module-object evidence (iter-23 F21):** Waveshare-42B-Module-productpage-2026-07-14.html (sha 077451eb4f2f, captured 2026-07-14 from https://www.waveshare.com/4.2inch-e-paper-module-b.htm — "What's on board" + box-contents list **"PH2.0 20cm 8Pin x1"**) + Waveshare-42B-Module-wiki-2026-07-14.html (sha e861c86f6e9f, captured 2026-07-14 from https://www.waveshare.com/wiki/4.2inch_e-Paper_Module_(B)_Manual — 8PIN pin-correspondence tables **VCC/GND/DIN/CLK/CS/DC/RST/BUSY**; FAQ caps cable extension at 20 cm). **Verify at ordering:** the in-box PH2.0 cable's far-end termination — the PH↔PH module↔board cable is a separate BOM purchase (ASPHSPH24K102-class) | 077451eb4f2f / e861c86f6e9f / 32b126146869 |
| 8125SHZBE (BTN1 battery override) | CK_8020_series.pdf (29 pp) | littelfuse via API proxy | https://www.littelfuse.com/assetdocs/littelfuse-c-k-pushbutton-8020-series-datasheet?assetguid=6fa0d834-728f-45bc-ae08-4f1019eb241d — Contact Rating: "B contact material (8X25 Models): 0.4 VA max. @ 20 V AC or DC maximum"; function table 8125 = ON MOM., terminals 1-3 rest / 1-2 pressed; S=plunger, H=0.250" flat bushing, Z=solder lug, E=epoxy seal | 8e748f0b8502 |
| 3517 | Keystone_3517.pdf (170K) | manual | https://www.keyelco.com/userAssets/file/K75p52.pdf | 441b810381ac |
| 970050354 | Wurth_970050354_standoff.pdf | digikey (API proxy) | https://www.we-online.com/components/products/datasheet/970050354.pdf — WA-SBRII brass spacer stud, M3 inner thread, L 5 mm, SW5, nickel | 5530b6984184 |
| 53398-0871 | Molex_53398-0871_PicoBlade_vert.pdf | molex (API proxy) | https://www.molex.com/pdm_docs/sd/533980871_sd.pdf — PicoBlade 1.25 mm, 8-ckt, SMT vertical, 1 A/ckt, tin. R/A alt 53261-0871 (Molex_53261-0871_PicoBlade_RA.pdf, sha 6e1b0968c9ed) | 642bc09ea605 |

## Still needed (CP1 datasheet gate)

**Gate re-opened 2026-07-14 (user audit): the 2026-07-01 "CLOSED — every
active part" claim was false.** RP3502MABLK (BTN1) had no stored
datasheet; when fetched and read it exposed the dry-circuit gap that
reviewer iter-23 F22 then escalated — the part is **superseded by C&K
8125SHZBE** (gold contacts, published 0.4 VA @ 20 V logic-level rating;
see the active-table row). D-OPEN-13 is moot with the supersession
(unsealed accepted for the IP5x indoor enclosure).

Remaining gaps (parts with a chosen MPN but no stored datasheet): none.

- ~~5×20 mm fuse clip~~ — **resolved 2026-07-14 (user-caught).** The BOM's
  SKUs "DK F1465-ND / Mouser 530-31MJ005H" were **phantoms** — zero hits on
  Mouser, DigiKey *and* Octopart via the parts API, and nothing on the
  retailers' own sites (user check). Replaced with **Keystone 3517**
  (5 mm/3AG PC-mount snap-in clip w/ end stops, tin-plated brass,
  UL E354010): DK **36-3517-ND** (85,711 in stock, Active) / Mouser
  **534-3517** (54,324 in stock), ~CA$0.48 ea. Datasheet fetched, read,
  verified: 5 mm fuse diameter ✓ (fits the 5×20 0215001.MXP body), THT
  snap-in legs, end stops (with-end-stop parts are the UL-recognized
  ones), rated ≥ 6.3 A ≫ 1 A fuse. Optional cover = 3517C.

Parts still at `_verify_` (MPN not yet chosen — D32 applies when chosen):
L1 buck inductor, USB-C receptacles (J3 battery / J-USB display),
display tactile buttons BTN1–3 (plunger height locked at CP3/CP5).


## Proposed CP1-delta additions (D36/D37) — datasheets on file, fold into the active table at CP2

Not yet in the active table above (these parts are in the RS-485 /
expansion design docs, pending the CP1-delta review; they move to the
active table + `cp1_bom.md` when CP2 folds them in). Datasheets stored,
read, and interface-verified now so the D32 gate closes when they land.

| MPN | file | provider | source | sha256 (12) | read-verified |
|-----|------|----------|--------|-------------|---------------|
| ADM2587EBRWZ | ADM2582E_2587E.pdf (1291K) | user upload 2026-07-16 | analog.com/media/en/technical-documentation/data-sheets/adm2582e-2587e.pdf (Rev H) | 77a52a9e6036 | 2500 Vrms iso (1 min); CMTI >25 kV/µs; ±15 kV ESD on bus pins; open/short fail-safe RX; 3.3 V op; **ADM2587E = 500 kbps** slew-limited; **ICC 72 mA @ 3.3 V, 100 Ω load** (isoPower DC-DC dominates whenever VCC applied); supplies ~15 mA on VISOO |
| SM712.TCT | SM712.pdf (465K) | user upload 2026-07-16 | smc-diodes.com/propdf/SM712 N2270 REV.C.pdf | e2bc628df997 | asymmetric RS-485 TVS, **VRWM 12 V / 7 V** (matches −7/+12); VBR 13.3 / 7.5 V min; VC 20 V/12 V @ 5 A (26/14 @ 15 A); Cj 75 pF; SOT-23 |

## Retired (in store history, not used)

- **RP3502MABLK** (BTN1) — retired at reviewer iter-23 F22 (2026-07-14):
  AC power switch (3 A @ 120 VAC) with **no published dry-circuit /
  minimum-load rating**; unqualifiable for the 3.3 V/µA override input,
  and the C11 100 nF discharge (0.54 µJ) is not a vendor wetting
  qualification. Superseded by **C&K 8125SHZBE** (explicit "0.4 VA max
  @ 20 V" low-level rating, gold contacts). PDF removed.

- **SMAJ12CA.pdf (Bourns) / SMAJ15A.pdf + SMAJ33CA.pdf (one Littelfuse
  family PDF stored under two names — identical sha)** — retired
  2026-07-14 audit: the datasheets on file were from manufacturers we
  don't order (BOM DK SKUs are **Diodes Inc** SMAJxxCA-13). Replaced by
  the single Diodes DS19005 family datasheet matching the orderable
  parts; per-variant VC values re-read from it and confirmed identical
  to the values used in the D19 coordination analysis. PDFs removed.

- **1727010** (Phoenix MKDS 1/2-3,81) — was mistakenly specced as the J1 plug; it's a 3.81 mm board-mount screw terminal, wrong series/pitch. Replaced by 1757019 (2026-07-01, D32 catch). PDF removed.
- **TPS389030DSER** (U4 UVLO supervisor) — WSON 1.5×1.5 leadless; repackaged to **TPS3808G01DBVR (SOT-23-6, leaded)** for hand-assembly (2026-07-01, D33/DR-24). Functional superset at ~same Iq. PDF removed.
- **SN65HVD3082EDR** (U2/U3 RS-485 transceiver) — was a 5 V part being run outside its recommended VCC = 4.5–5.5 V window on V3V3 (reviewer iter-8 F05). Superseded by **THVD1400DR** (D34, revised iter-10 F08). PDF retained temporarily in `hardware/datasheets/SN65HVD3082EDR.pdf` as the record of the F05 evidence — can be removed at the next housekeeping pass once the review record is archived.
- **ISL3175EIBZ** (U2/U3 RS-485 transceiver) — iter-8 first-cut replacement for SN65HVD3082E, but iter-10 F08 correctly caught that its 10 nA shutdown Iq was *typical* and the maximum is 12 µA (1200× higher). Superseded by **THVD1400DR** on max-to-max comparison. PDF retained temporarily in `hardware/datasheets/ISL3175EIBZ.pdf` as the record of the iter-10 max-to-max evidence — can be removed once the review record is archived.
