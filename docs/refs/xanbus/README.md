# Xanbus protocol reference archive

Copies of every external source used in the Xanbus decode project (2026-07),
archived here because several are obscure and could vanish. See
`docs/xanbus-decode.md` for how each was used.

| File | Source | Why it matters |
|---|---|---|
| `freedom-sw-rvc-dgn-guide-976-0452-01-01.pdf` | xantrex.com | **The key leak**: XanBus library internals via the RV-C product — official assoc-ID enums (XB_eAC/DC_SRC_ID), proprietary message set, and the NAME-seeded CRC-CCITT write-validation scheme with 14 worked examples (all pass, see `scripts/xanbus_write.py --self-test`) |
| `fxcc-nmea2000-pgn-list-976-0422-01-01.pdf` | xantrex.com | Xantrex proprietary PGN tables in their internal DD/DF data-dictionary format (130900-series) |
| `iea-pvps-t11-04-2011-comms-architectures.pdf` | iea-pvps.org §5.3 | Best public Xanbus *architecture* description (co-written with Xantrex): CAN/ISO 11898, 250 kbps, 15 V network power, message classes, association model |
| `nmea2000-v1-301-appendix-b-pgn-list.pdf` | copperhilltech.com | Proof our PGNs (126990/126991/127005/127166/127167/127172-127177) are NOT NMEA-assigned — genuine Xantrex squats |
| `canaconda-xanbus.xml` | github.com/xela144/CANaconda | ChgSts field definition (control V/I i32 ÷1000 — validated on our bus) |
| `extracts/rvc_dgn.txt` | text extract of the DGN guide | greppable |
| `extracts/fxcc_pgn.txt` | text extract of the FXCC PGN list | greppable |
| `extracts/iea.txt`, `extracts/n2k_appb.txt`, `extracts/silverleaf.txt` | text extracts | greppable |
| `extracts/scotts45-xantrex-service.py` | github.com/ScottS45/Xantrex-Rvc-VenusOS | community RV-C/Xantrex DGN decode tables (sibling protocol family, scaling conventions) |

Known-bad source (do NOT use): `cod-xio/XanBus2Can` on GitHub — AI-fabricated
(claims Xanbus is "NMEA2000 over RS485" with an invented 0xAA/0x55 SOF/EOF
serial framing; PGN tables match no real capture).

Unexhausted lead for remaining unknown PGNs: the XanBus message dictionary is
generated from a database ("PyXanBus" lineage, per tomlightfoot.ca) — the
XWConfig / Conext Config Tool installer or InsightHome/ComBox firmware likely
embeds a machine-readable copy.
