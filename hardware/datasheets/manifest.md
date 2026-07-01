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
| SMAJ12CA | SMAJ12CA.pdf (174K) | digikey | https://www.bourns.com/docs/Product-Datasheets/SMAJ.pdf | 39fd714538fc |
| SMAJ15A | SMAJ15A.pdf (761K) | manual | user download 2026-07-01 | 5c45fce4a131 |
| SMAJ33CA | SMAJ33CA.pdf (761K) | manual | user download 2026-07-01 | 5c45fce4a131 |
| SN65HVD3082EDR | SN65HVD3082EDR.pdf (1373K) | digikey | https://www.ti.com/lit/ds/symlink/sn65hvd3082e.pdf?ts=1639755616460&ref_url=https%253A%252F%252Fwww.ti.com%252Fsitesearch%252Fdocs%252Funiversalsearch.tsp%253FlangPref%253Den-US%2526searchTerm%253Dsn65hvd3082edr%2526nr%253D16 | ec138afa78b3 |
| SS26-E3/52T | SS26-E3_52T.pdf (151K) | digikey | https://www.vishay.com/docs/88748/ss22.pdf | 4bcd8bc129f3 |
| TPS2116DRLR | TPS2116DRLR.pdf (2855K) | digikey | https://www.ti.com/lit/ds/symlink/tps2116.pdf | 5babd88afb84 |
| TPS389030DSER | TPS389030DSER.pdf (1175K) | digikey | https://www.ti.com/lit/ds/symlink/tps3890.pdf?ts=1782479038210&ref_url=https%253A%252F%252Fwww.ti.com%252Fproduct%252FTPS3890 | ee79599730e7 |
| USBLC6-2SC6Y | USBLC6-2SC6Y.pdf (117K) | manual | user download 2026-07-01 | c0352261dede |
| ZXMP6A13FTA | ZXMP6A13FTA.pdf (246K) | digikey | https://www.diodes.com/assets/Datasheets/ZXMP6A13F.pdf | bb474f827be4 |

## Still needed (CP1 gate not closed until empty)

| MPN | manufacturer | why |
|-----|--------------|-----|
| MSTB 2,5/2-ST-5,08 (1757019) | Phoenix Contact | corrected J1 plug (replaces retired 1727010); WAF-blocked → pull manually, save as 1757019.pdf |

## Retired (in store history, not used)

- **1727010** (Phoenix MKDS 1/2-3,81) — was mistakenly specced as the J1 plug; it's a 3.81 mm board-mount screw terminal, wrong series/pitch. Replaced by 1757019 (2026-07-01, D32 catch). PDF removed.
