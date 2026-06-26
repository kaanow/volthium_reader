# Datasheet manifest

Local datasheet store for active BOM parts. Fetched via the parts API proxy (`GET http://eridani.zt:8787/datasheet`), which reaches manufacturer hosts directly. Supports the COTS interface-reality gate.

| MPN | file | provider | source URL | sha256 (first 12) |
|-----|------|----------|-----------|-------------------|
| LM5166YDRCR | — (HTTP 502) | — | — | — |
| R-78HB12-0.5 | R-78HB12-0.5.pdf (1.8M) | digikey | https://recom-power.com/pdf/Innoline/R-78HB-0.5.pdf | 457ccbb2825f |
| R-78E3.3-0.5 | R-78E3.3-0.5.pdf (632K) | digikey | https://recom-power.com/pdf/Innoline/R-78E-0.5.pdf | d3855b950078 |
| SN65HVD3082EDR | SN65HVD3082EDR.pdf (1.3M) | digikey | https://www.ti.com/lit/ds/symlink/sn65hvd3082e.pdf?ts=1639755616460&ref_url=https%253A%252F%252Fwww.ti.com%252Fsitesearch%252Fdocs%252Funiversalsearch.tsp%253FlangPref%253Den-US%2526searchTerm%253Dsn65hvd3082edr%2526nr%253D16 | ec138afa78b3 |
| TPS389030DSER | — (HTTP 502) | — | — | — |
| AP2112K-3.3TRG1 | AP2112K-3.3TRG1.pdf (740K) | digikey | https://www.diodes.com/assets/Datasheets/AP2112.pdf | ef8d376f2ec3 |
| TPS2116DRLR | TPS2116DRLR.pdf (2.8M) | digikey | https://www.ti.com/lit/ds/symlink/tps2116.pdf | 5babd88afb84 |
| ZXMP6A13FTA | ZXMP6A13FTA.pdf (248K) | digikey | https://www.diodes.com/assets/Datasheets/ZXMP6A13F.pdf | bb474f827be4 |
| 2N7002 | 2N7002.pdf (304K) | digikey | https://diotec.com/request/datasheet/2n7002.pdf | 4904d73f5fb8 |
| BZX84C12LT1G | — (HTTP 502) | — | — | — |
| SS26-E3/52T | SS26-E3_52T.pdf (152K) | digikey | https://www.vishay.com/docs/88748/ss22.pdf | 4bcd8bc129f3 |
| SMAJ33CA | — (HTTP 502) | — | — | — |
| SMAJ12CA | — (HTTP 502) | — | — | — |
| SMAJ15A | — (HTTP 502) | — | — | — |
| ESP32-S3-WROOM-1-N16R8 | ESP32-S3-WROOM-1-N16R8.pdf (1.2M) | digikey | https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf | 27d71971da07 |
| USBLC6-2SC6Y | — (HTTP 500) | — | — | — |
| 0215001.MXP | — (HTTP 502) | — | — | — |
| RJHSE-5380 | RJHSE-5380.pdf (104K) | digikey | https://cdn.amphenol-cs.com/media/wysiwyg/files/drawing/rjhsex380.pdf | 3254d85eaaa6 |
| 1757242 | — (HTTP 502) | — | — | — |
| 1727010 | — (HTTP 502) | — | — | — |
| MF-R025 | MF-R025.pdf (1.0M) | digikey | https://www.bourns.com/docs/product-datasheets/mf-r.pdf | ad20425ca080 |
| 615008145521 | 615008145521.pdf (848K) | digikey | https://www.we-online.com/components/products/datasheet/615008145521.pdf | da03e4ed6257 |
| B8B-PH-K-S | B8B-PH-K-S.pdf (104K) | digikey | https://www.jst-mfg.com/product/pdf/eng/ePH.pdf | 447624f4f2f7 |
| RV-3028-C7 | — (HTTP 502) | — | — | — |

## Not yet retrieved (proxy 502/500 — host blocked or URL-resolution failed)

These returned a non-200 from the proxy on two attempts (2026-06-25). The
parts API resolved a URL but the fetch failed — likely manufacturer-host
blocks or a bad resolved URL. To obtain: retry later, or fetch manually
(user/API-agent help offered). None are blocking CP1; needed for the
COTS interface-reality archive + a couple of CP2 checks (esp. TPS389030
SENSE threshold).

| MPN | proxy code | likely host | needed for |
|-----|-----------|-------------|-----------|
| LM5166YDRCR | 502 | TI | reference |
| TPS389030DSER | 502 | TI | **CP2: SENSE threshold → UVLO divider sizing** |
| BZX84C12LT1G | 502 | onsemi | reference |
| SMAJ33CA | 502 | Littelfuse | clamp VC curve (already have VC=53.3 V) |
| SMAJ12CA | 502 | Littelfuse | reference |
| SMAJ15A | 502 | Littelfuse | clamp VC (already have 24.4 V) |
| USBLC6-2SC6Y | 500 | ST | reference |
| 0215001.MXP | 502 | Littelfuse | fuse I²t (already have 1.52 A²s) |
| 1757242 | 502 | Phoenix | reference |
| 1727010 | 502 | Phoenix | reference |
| RV-3028-C7 | 502 | Micro Crystal | VBACKUP/trickle (ambiguous MPN — use QA order code) |
