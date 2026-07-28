#!/usr/bin/env python3
"""Independent G8 read-back of the exported display-board netlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[6]
SCHEMATIC = REPO / "hardware/kicad/schematic"
NETLIST = SCHEMATIC / "build_display/volthium_display.net"

sys.path.insert(0, str(SCHEMATIC))
import core  # noqa: E402
import build_display  # noqa: E402


def net_lookup(nets: dict[str, frozenset[tuple[str, str]]]) -> dict[tuple[str, str], str]:
    return {node: name for name, nodes in nets.items() for node in nodes}


def parse_exported_netlist() -> dict[str, frozenset[tuple[str, str]]]:
    text = NETLIST.read_text(encoding="utf-8")
    nets: dict[str, frozenset[tuple[str, str]]] = {}
    pos = 0
    while True:
        pos = text.find("(net", pos)
        if pos < 0:
            break
        if text[pos + 4] not in " \n\t":
            pos += 4
            continue
        depth = 0
        end = pos
        while end < len(text):
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        block = text[pos : end + 1]
        pos = end + 1
        name = re.search(r'\(name "([^"]*)"\)', block)
        if name:
            nodes = frozenset(
                re.findall(r'\(node\s+\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', block)
            )
            nets[name.group(1)] = nodes
    return nets


def exact_part_issues(
    contracts: dict[str, tuple[str, str]] | None = None,
) -> list[str]:
    old_out = core.OUT
    try:
        core.OUT = NETLIST.parent
        return core.check_exact_parts(
            "volthium_display.kicad_sch",
            contracts if contracts is not None else build_display.EXACT_PARTS,
        )
    finally:
        core.OUT = old_out


def main() -> int:
    nets = parse_exported_netlist()
    net_of = net_lookup(nets)

    golden_issues = core.check_golden(nets, build_display.GOLDEN)
    poisoned = list(build_display.GOLDEN)
    poisoned.append(("on", ("J1", "1"), "GND", "intentional poison"))
    poison_issues = core.check_golden(nets, poisoned)

    short_issues: list[str] = []
    by_ref: dict[str, dict[str, str]] = {}
    for (ref, pin), net in net_of.items():
        by_ref.setdefault(ref, {})[pin] = net
    for ref, pins in sorted(by_ref.items()):
        if not re.match(r"^(?:R|C|L|D|Q|TVS|F)(?:[0-9_]|$)", ref):
            continue
        seen: dict[str, str] = {}
        for pin, net in pins.items():
            if net.startswith("unconnected-"):
                continue
            if net in seen:
                short_issues.append(f"{ref} pins {seen[net]}+{pin} both on {net}")
            seen[net] = pin

    print("G8 INDEPENDENT EXPORTED-NETLIST READ-BACK")
    print(f"netlist={NETLIST.relative_to(REPO)}")
    print(f"nets={len(nets)} golden_contracts={len(build_display.GOLDEN)}")
    print(f"golden_issues={len(golden_issues)}")
    for issue in golden_issues:
        print(f"  {issue}")
    print(f"poison_issues={len(poison_issues)} (expected exactly 1)")
    for issue in poison_issues:
        print(f"  {issue}")
    print(f"discrete_short_issues={len(short_issues)}")
    for issue in short_issues:
        print(f"  {issue}")
    variant_issues = exact_part_issues()
    print(f"exact_part_issues={len(variant_issues)}")
    for issue in variant_issues:
        print(f"  {issue}")
    poisoned_parts = dict(build_display.EXACT_PARTS)
    poisoned_parts["J2"] = (
        "JST_B8B-PH-K-S",
        "Connector_JST:JST_PH_B8B-PH-K_1x08_P2.00mm_Horizontal",
    )
    variant_poison_issues = exact_part_issues(poisoned_parts)
    print(f"exact_part_poison_issues={len(variant_poison_issues)} (expected exactly 1)")
    for issue in variant_poison_issues:
        print(f"  {issue}")

    print("\nPIN-TO-NET NARRATION INPUT")
    refs = (
        "J1", "F1", "TVS1", "U1", "U3-LDO", "U4-MUX", "J-USB", "U-ESD",
        "U2", "TVS2", "J5", "J2", "BTN1", "BTN2", "BTN3", "J3", "MOD1",
    )
    for ref in refs:
        pins = by_ref.get(ref, {})
        ordered = sorted(pins.items(), key=lambda item: (not item[0].isdigit(), int(item[0]) if item[0].isdigit() else item[0]))
        print(f"{ref}: " + ", ".join(f"{pin}={net}" for pin, net in ordered))

    ok = (
        not golden_issues
        and len(poison_issues) == 1
        and "intentional poison" in poison_issues[0]
        and not short_issues
        and not variant_issues
        and len(variant_poison_issues) == 1
        and "J2" in variant_poison_issues[0]
    )
    print(f"\nRESULT={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
