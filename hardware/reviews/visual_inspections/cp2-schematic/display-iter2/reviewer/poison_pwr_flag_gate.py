from __future__ import annotations

import sys
from pathlib import Path


repo = Path(__file__).resolve().parents[6]
source = repo / "hardware/kicad/schematic/build_display.py"
text = source.read_text(encoding="utf-8")
old = 'tanchor="u")'
poison = 'tanchor="ud")'

if text.count(old) != 1:
    raise SystemExit(f"expected exactly one display PWR_FLAG anchor, found {text.count(old)}")

sys.path.insert(0, str(source.parent))
globals_for_exec = {
    "__file__": str(source),
    "__name__": "__main__",
    "__package__": None,
}
exec(compile(text.replace(old, poison), str(source), "exec"), globals_for_exec)
