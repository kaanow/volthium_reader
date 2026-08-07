"""Build an equal-cardinality wrong pad set using KiCad's own board model."""

import copy
import json
from pathlib import Path
import sys

import pcbnew


HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[6]
BOARD = REPO / "hardware" / "kicad" / "pcb" / "build_display" / "display_pcb.kicad_pcb"

expected = json.loads((HERE / "full_expected.json").read_text(encoding="utf-8"))
board = pcbnew.LoadBoard(str(BOARD))

bound_single = []
unbound_single = []
for footprint in board.GetFootprints():
    ref = footprint.GetReference()
    if ref not in expected["components"]:
        continue
    by_number = {}
    for pad in footprint.Pads():
        by_number.setdefault(pad.GetNumber(), []).append(pad)
    for number, pads in by_number.items():
        key = f"{ref}/{number}"
        if len(pads) != 1:
            continue
        if key in expected["pads"] and pads[0].GetNetname():
            bound_single.append((key, pads[0].GetNetname()))
        if key not in expected["pads"] and not pads[0].GetNetname():
            unbound_single.append(key)

if not bound_single or not unbound_single:
    raise RuntimeError("board lacks the required bound/unbound single-pad controls")

removed, removed_net = sorted(bound_single)[0]
added = sorted(unbound_single)[0]
poison = copy.deepcopy(expected)
poison["pads"].pop(removed)
poison["pads"][added] = ""
(HERE / "wrong_pad_set_expected.json").write_text(
    json.dumps(poison, indent=2) + "\n", encoding="utf-8", newline="\n")

print(f"removed net-bound expected pad: {removed} -> {removed_net!r}")
print(f"added unrelated unbound pad: {added} -> ''")
print(f"pad-key count: control={len(expected['pads'])} poison={len(poison['pads'])}")
print("written wrong_pad_set_expected.json")
