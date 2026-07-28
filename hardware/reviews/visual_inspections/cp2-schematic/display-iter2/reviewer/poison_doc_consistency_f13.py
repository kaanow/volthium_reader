from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


repo = Path(__file__).resolve().parents[6]
checker_path = repo / "hardware/reviews/tools/doc_consistency_check.py"
spec = importlib.util.spec_from_file_location("doc_consistency_check", checker_path)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

with tempfile.TemporaryDirectory(prefix="volthium-f13-poison-") as td:
    temp = Path(td)
    poison_doc = temp / "poison.md"
    checker.REPO = temp
    checker.LIVE_DOCS = ["poison.md"]

    poison_doc.write_text(
        "| J-USB | USB-C receptacle GCT USB4085-GF-A | SMD | 1 |\n",
        encoding="utf-8",
    )
    stale_poison = checker.check_stale_tokens()

    poison_doc.write_text(
        "| J-USB | USB-C receptacle GCT USB4085-GF-A | THT top-mount | 1 |\n",
        encoding="utf-8",
    )
    stale_control = checker.check_stale_tokens()

    checker.MANIFEST = temp / "manifest.md"
    checker.CANONICAL_BOM = temp / "cp1_bom.md"
    checker.DATASHEET_DIR = temp / "datasheets"
    checker.DATASHEET_DIR.mkdir()

    live_manifest = (repo / "hardware/datasheets/manifest.md").read_text(
        encoding="utf-8"
    )
    live_bom = (repo / "hardware/layout/cp1_bom.md").read_text(encoding="utf-8")
    checker.MANIFEST.write_text(live_manifest, encoding="utf-8")
    checker.CANONICAL_BOM.write_text(live_bom, encoding="utf-8")
    (checker.DATASHEET_DIR / "USB4085_drawing.pdf").write_bytes(b"control")
    object_control = checker.check_bom_mpn_coverage()

    poisoned_manifest = "\n".join(
        line for line in live_manifest.splitlines()
        if "USB4085_drawing.pdf" not in line
    )
    checker.MANIFEST.write_text(poisoned_manifest + "\n", encoding="utf-8")
    (checker.DATASHEET_DIR / "USB4085_drawing.pdf").unlink()
    object_poison = checker.check_bom_mpn_coverage()

print(f"smd_poison_findings={len(stale_poison)}")
for finding in stale_poison:
    print(finding)
print(f"tht_control_findings={len(stale_control)}")
print(f"exact_object_control_findings={len(object_control)}")
print(f"exact_object_poison_findings={len(object_poison)}")
for finding in object_poison:
    print(finding)

expected = (
    len(stale_poison) == 1
    and not stale_control
    and not object_control
    and len(object_poison) == 2
    and all("[exact-object]" in finding for finding in object_poison)
)
raise SystemExit(0 if expected else 1)
