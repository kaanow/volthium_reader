# Candidate datasheets

PDFs for parts under consideration but **not ordered**. They live here, not
in the active store, because `doc_consistency_check` enforces a real
invariant on `hardware/datasheets/`: every PDF there corresponds to a part
in the canonical BOM (D32/F75). A candidate has no BOM row by definition,
so parking it here keeps that invariant meaningful instead of weakening the
checker to accommodate an exception.

When a candidate is chosen, move its PDF up into `hardware/datasheets/`,
add the manifest provenance row, and update the BOM in the same commit.

| File | Part | Raised by | Status |
|------|------|-----------|--------|
| `USB4120.pdf` | GCT USB4120-03-C — USB2.0 Type-C receptacle, 16 contacts, **vertical**, SMT, **H=6.5 mm** (p.1 title block; Rev A2 15/07/24; sha256 `816ea8c0b1db…`; fetched 2026-08-05 from https://gct.co/files/specs/usb4120-spec.pdf) | **DR-35 option B** — a front-face service port that is reachable with the faceplate off and costs no depth | OPEN — awaiting the user's call |
