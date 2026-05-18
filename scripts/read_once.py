"""Connect to one or two batteries and dump a single reading. Smoke test."""

import argparse
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path
from pprint import pprint

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.pack import read_battery, read_pack


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", help="address of battery A")
    ap.add_argument("--b", help="address of battery B (optional)")
    args = ap.parse_args()

    if not args.a:
        ap.error("--a is required (run scripts/scan.py first)")

    if args.b:
        pack = await read_pack(args.a, args.b)
        print(f"Battery {pack.a.label}:")
        pprint(asdict(pack.a))
        print(f"\nBattery {pack.b.label}:")
        pprint(asdict(pack.b))
        print(
            f"\nPack: {pack.pack_voltage:.2f} V, "
            f"{pack.pack_current:+.2f} A, "
            f"{pack.pack_power:+.1f} W, "
            f"SOC {pack.min_soc:.0f}–{pack.max_soc:.0f}%"
        )
    else:
        r = await read_battery(args.a)
        pprint(asdict(r))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
