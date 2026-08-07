"""Independent probes for iteration-18 direct-child field parsing."""

from pathlib import Path
import re
import sys


REPO = Path(__file__).resolve().parents[6]
PCB = REPO / "hardware" / "kicad" / "pcb"
sys.path.insert(0, str(PCB))

import core  # noqa: E402


def footprint_chunk(text, ref):
    for match in re.finditer(r'\n  \(footprint "([^"]+)"', text):
        start = match.start() + 1
        end = core._balanced(text, start + 2)
        chunk = text[start:end]
        if f'(property "Reference" "{ref}"' in chunk:
            return chunk
    raise RuntimeError(f"footprint {ref} not found")


battery_text = (PCB / "build" / "battery_pcb.kicad_pcb").read_text(
    encoding="utf-8"
)
fallback_chunk = footprint_chunk(battery_text, "C_sense")
fallback_bad_anchor = re.sub(
    r"\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)",
    "(at BAD BAD)",
    fallback_chunk,
    count=1,
)

saved_selected = core._REFDES_SELECTED
saved_fallback = core._REFDES_FALLBACK
try:
    core._REFDES_SELECTED = {"__probe__": (0.0, 0.0)}
    core._REFDES_FALLBACK = {"C_sense"}
    fallback_control = []
    core.assert_refdes_roundtrip("\n" + fallback_chunk, fallback_control)
    fallback_poison = []
    core.assert_refdes_roundtrip(
        "\n" + fallback_bad_anchor, fallback_poison
    )
finally:
    core._REFDES_SELECTED = saved_selected
    core._REFDES_FALLBACK = saved_fallback


front = """(footprint "X"
  (layer "F.Cu")
  (at 1 2 0)
  (pad "1" smd rect (at 0 0) (layers "B.Cu")))"""
back = front.replace('(layer "F.Cu")', '(layer "B.Cu")', 1)
missing_layer = front.replace('  (layer "F.Cu")\n', "", 1)
malformed_layer = front.replace('(layer "F.Cu")', '(layer BAD)', 1)
non_copper_layer = front.replace('(layer "F.Cu")', '(layer "Dwgs.User")', 1)


def safe_parse(chunk):
    try:
        return {
            "anchor": core.sexp_anchor(chunk),
            "is_back": core._footprint_is_back(chunk),
            "error": None,
        }
    except Exception as exc:  # evidence should report, not hide, parser crashes
        return {
            "anchor": None,
            "is_back": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


quoted_close = """(footprint "X"
  (descr "legal text containing a ) parenthesis")
  (layer "B.Cu")
  (at 1 2 90))"""
quoted_open = """(footprint "X"
  (descr "legal text containing an ( parenthesis")
  (layer "B.Cu")
  (at 1 2 90))"""

cases = {
    "front": safe_parse(front),
    "back": safe_parse(back),
    "missing_layer": safe_parse(missing_layer),
    "malformed_layer": safe_parse(malformed_layer),
    "non_copper_layer": safe_parse(non_copper_layer),
    "quoted_close": safe_parse(quoted_close),
    "quoted_open": safe_parse(quoted_open),
}

checks = {
    "f18_fallback_control_clean": fallback_control == [],
    "f18_fallback_anchor_rejected": len(fallback_poison) == 1
    and "no parseable top-level anchor" in fallback_poison[0],
    "front_control": cases["front"]["is_back"] is False,
    "back_control": cases["back"]["is_back"] is True,
    # Unknown is not front. The direct-child reader must preserve that state
    # so callers can reject it instead of silently applying front transforms.
    "missing_layer_is_unknown": cases["missing_layer"]["is_back"] is None,
    "malformed_layer_is_unknown": cases["malformed_layer"]["is_back"] is None,
    "non_copper_layer_is_unknown": cases["non_copper_layer"]["is_back"] is None,
    # Parentheses inside a quoted S-expression string are data, not nesting.
    "quoted_close_preserves_fields": cases["quoted_close"] == {
        "anchor": (1.0, 2.0, 90.0), "is_back": True, "error": None
    },
    "quoted_open_preserves_fields": cases["quoted_open"] == {
        "anchor": (1.0, 2.0, 90.0), "is_back": True, "error": None
    },
}

print("f18/fallback_control:", fallback_control)
print("f18/fallback_bad_anchor:", fallback_poison)
for name, result in cases.items():
    print(f"direct-child/{name}: {result}")
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'} {name}")

failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("independent direct-child recheck failed: " + ", ".join(failed))
