# archive/pass1_pcb — first design pass placement/routing (SUPERSEDED)

Retired 2026-07-29 at CP3 kickoff of the re-baselined design.

This is the first design pass's PCB toolchain, kept for history:

| Item | What it was |
|------|-------------|
| `build_pcbs.py` | Placement + autoroute + fab-output generator for the pass-1 boards (kiutils `Board.create_new()` + Freerouting + pcbnew zone fills). |
| `battery_side/`, `display_side/` | Pass-1 per-board KiCad project dirs (`.kicad_pro` + lib tables). |
| `_smoke/` | Minimal smoke-test board fixture for the pass-1 flow. |
| `outputs/` | Pass-1 build outputs tree (`hardware/outputs/` at the time). |
| `dedupe_pdf_text.py` | Pass-1 PDF post-processor (duplicate text objects); the current pass handles dedup inside the pdf-text gate in `schematic/core.py`. |

The pass-1 design itself (through CP6 fab-ready) lives on the
`retired/hw-*` branches. The re-baselined design's placement toolchain
is `hardware/kicad/pcb/` (shared-core pattern, CP3+).

Do not build from these files; paths and environment assumptions are
stale by design.
