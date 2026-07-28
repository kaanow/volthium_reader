# Standing gate self-test fixtures

Used by `core.selftest_gates()`, which runs at the START of every build —
a gate that cannot demonstrably fail is not a gate (display-iter3 F17/F18).

| File | What it is | Provenance |
|------|------------|------------|
| `poison_pdf_battery_sheet_conn.pdf` | battery sheet_conn rendered with the PRE-F16 SHIELD pin position — contains exactly 2 real SHIELD×GND ink collisions (0.489 mm min-axis on the reviewer's KiCad 10.0.5) | reviewer-generated, display-iter3 evidence (`poison_f16_gates.py`), sha `47851b58f4a4…` |
| `poison_pdf_display_sheet_d_conn.pdf` | display sheet_d_conn, same poison, same 2 collisions | same, sha `4b9f24dd088f…` |

The self-test requires `_pdf_text_collisions()` to find **exactly 2**
pairs in each fixture at the live threshold — so any future threshold
loosening (the F17 class: 0.5 mm silently missed the 0.489 mm poison)
fails the build immediately. The clean-side control is the live check of
every current sheet PDF during the same build. The self-test also proves
the checked-PDF-export contract (F18): a deliberately failing export
against a pre-seeded stale PDF must be rejected, not silently accepted.
