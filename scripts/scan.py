"""Scan for Volthium batteries and print their addresses.

Run this first. Copy the two addresses into a .env or pass them to monitor.py.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.pack import discover_volthium


async def main() -> int:
    print("Scanning for Volthium batteries (8s)...")
    devices = await discover_volthium(timeout=8.0)
    if not devices:
        print("No batteries found. Make sure they're in BLE range and not")
        print("currently connected to the Volthium phone app.")
        return 1
    print(f"\nFound {len(devices)}:")
    for dev, name in sorted(devices, key=lambda x: x[1]):
        print(f"  {dev.address}   {name}")
    if len(devices) == 2:
        a, b = sorted(devices, key=lambda x: x[1])
        print("\nTo monitor the pack:")
        print(f"  ./scripts/monitor.py --a {a[0].address} --b {b[0].address}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
