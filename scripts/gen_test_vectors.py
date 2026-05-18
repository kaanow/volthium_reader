"""Generate canonical Python-encoded wire-protocol frames + an
expected-decode manifest. The C cross-validation test
(firmware/common/volthium_lib/test_cross_validation.c) reads these
and asserts both:

    1. Python-encoded bytes can be decoded in C with matching fields.
    2. The C encoder of the same fields produces byte-identical output.

Run from repo root:
    .venv/bin/python scripts/gen_test_vectors.py

Output: firmware/common/volthium_lib/test_vectors/case_*.bin
        firmware/common/volthium_lib/test_vectors/expected.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.wire_protocol import (
    FLAG_CHARGING_FETS,
    FLAG_DISCHARGING_FETS,
    FLAG_A_UNREACHABLE,
    WireFrame,
    encode,
)


# Cases must be in the same order in the C test.
CASES: list[tuple[str, WireFrame]] = [
    (
        "charging_realistic",
        WireFrame(
            seq=42, uptime_ms=12345, state="charging",
            pack_v=26.71, pack_i=16.30, pack_p=435,
            soc_a=68, soc_b=66,
            v_a=13.353, v_b=13.357, i_a=16.50, i_b=16.10,
            temp_a=23, temp_b=23,
            remaining_ah_a=156.0, remaining_ah_b=138.0,
            delta_v_a_mv=9, delta_v_b_mv=7,
            minutes_remaining=229,
            flags=FLAG_CHARGING_FETS | FLAG_DISCHARGING_FETS,
        ),
    ),
    (
        "discharging_with_negatives",
        WireFrame(
            seq=128, uptime_ms=999999, state="discharging",
            pack_v=26.40, pack_i=-15.50, pack_p=-410,
            soc_a=80, soc_b=78,
            v_a=13.200, v_b=13.200, i_a=-15.40, i_b=-15.60,
            temp_a=-5, temp_b=-5,                            # negative temps
            remaining_ah_a=160.0, remaining_ah_b=158.0,
            delta_v_a_mv=12, delta_v_b_mv=10,
            minutes_remaining=600,
            flags=FLAG_DISCHARGING_FETS,
        ),
    ),
    (
        "full_state",
        WireFrame(
            seq=255, uptime_ms=42, state="full",
            pack_v=27.40, pack_i=0.50, pack_p=14,
            soc_a=95, soc_b=96,
            v_a=13.700, v_b=13.700, i_a=0.50, i_b=0.50,
            temp_a=25, temp_b=25,
            remaining_ah_a=210.0, remaining_ah_b=208.0,
            delta_v_a_mv=4, delta_v_b_mv=5,
            minutes_remaining=0,
            flags=FLAG_CHARGING_FETS | FLAG_DISCHARGING_FETS,
        ),
    ),
    (
        "battery_a_offline",
        WireFrame(
            seq=1, uptime_ms=100, state="unknown",
            pack_v=None, pack_i=None, pack_p=None,            # all sentinels
            soc_a=None, soc_b=72,
            v_a=None, v_b=13.300, i_a=None, i_b=-3.20,
            temp_a=None, temp_b=22,
            remaining_ah_a=None, remaining_ah_b=140.0,
            delta_v_a_mv=None, delta_v_b_mv=8,
            minutes_remaining=None,
            flags=FLAG_A_UNREACHABLE,
        ),
    ),
]


def main() -> int:
    out_dir = Path("firmware/common/volthium_lib/test_vectors")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines: list[str] = ["# Reference frames — Python-encoded, hex-dumped."]
    for name, frame in CASES:
        wire = encode(frame)
        assert len(wire) == 43, f"frame must be 43 bytes, got {len(wire)}"
        (out_dir / f"{name}.bin").write_bytes(wire)
        manifest_lines.append(f"{name} {wire.hex()}")
        print(f"  wrote {name}.bin ({len(wire)} bytes)")

    (out_dir / "expected.txt").write_text("\n".join(manifest_lines) + "\n")
    print(f"  wrote expected.txt ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
