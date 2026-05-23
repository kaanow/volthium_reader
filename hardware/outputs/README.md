# `hardware/outputs/` — build artifacts (fab deliverables)

Per-board subdirectories with the artifacts a PCB fab needs. Filled in
at CP4 (renders) and CP5 (gerbers, BOM CSV, position files).

```
outputs/
├── battery_side/
│   ├── gerbers/        — *.gbr files (one per layer)
│   ├── drill/          — *.drl + *.gtl
│   ├── bom.csv         — flat BOM for fab/PCBA
│   ├── pos.csv         — pick-and-place (unused for hand-solder; present for completeness)
│   ├── render_top.png  — visual reference
│   ├── render_bot.png  — visual reference
│   └── schematic.pdf   — schematic for the assembler
└── display_side/
    └── (same files)
```

All files in this folder are **regenerable** from the KiCad sources via
`kicad-cli`. They are committed to the repo at CP5 only — the version
that ships to the fab. Earlier CP renders live in the review packets,
not here.
