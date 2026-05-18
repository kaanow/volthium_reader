"""Two Volthium 12V batteries wired in series → one logical 24V pack."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from aiobmsble import BMSSample
from aiobmsble.bms.ej_bms import BMS as VolthiumBMS
from bleak import BleakScanner
from bleak.backends.device import BLEDevice


# SC12200G4DPH advertises as "V-12V200Ah-<serial>"
ADV_NAME_PREFIX = "V-12V"


@dataclass
class BatteryReading:
    """One battery's snapshot. None on any field means the BMS didn't send it."""
    address: str
    name: str
    voltage: Optional[float]          # V (sum of cell voltages)
    current: Optional[float]          # A (positive = charging)
    soc: Optional[float]              # %
    remaining_ah: Optional[float]     # Ah remaining (from cycle_charge)
    temperature: Optional[float]      # °C
    cycles: Optional[int]
    cell_voltages: Optional[list[float]]
    delta_voltage: Optional[float]    # max - min cell V
    charging_fet: Optional[bool]
    discharging_fet: Optional[bool]
    problem_code: Optional[int]

    @property
    def label(self) -> str:
        """Glanceable battery ID — last two digits of the BMS serial.

        'V-12V200AH-0533' → '33', 'V-12V200AH-0667' → '67'. Falls back to
        last 4 chars of the BLE address if the name isn't structured as
        expected.
        """
        if self.name and "-" in self.name:
            tail = self.name.rsplit("-", 1)[1]
            if tail and tail[-2:].isdigit():
                return tail[-2:]
        return self.address[-4:] if self.address else "??"

    @classmethod
    def from_sample(cls, address: str, name: str, s: BMSSample) -> "BatteryReading":
        return cls(
            address=address,
            name=name,
            voltage=s.get("voltage"),
            current=s.get("current"),
            soc=s.get("battery_level"),
            remaining_ah=s.get("cycle_charge"),
            temperature=(s["temp_values"][0] if s.get("temp_values") else None),
            cycles=s.get("cycles"),
            cell_voltages=s.get("cell_voltages"),
            delta_voltage=s.get("delta_voltage"),
            charging_fet=s.get("chrg_mosfet"),
            discharging_fet=s.get("dischrg_mosfet"),
            problem_code=s.get("problem_code"),
        )


@dataclass
class PackReading:
    """Combined view of two batteries in series.

    In a series pack the same current flows through both batteries, but each
    cell-group can drift in SOC. For runtime estimation the worst battery
    bounds the pack:
      - charging is finished when the FIRST battery hits 100%
      - discharging is finished when the FIRST battery hits the floor SOC
    """
    a: BatteryReading
    b: BatteryReading

    @property
    def pack_voltage(self) -> Optional[float]:
        if self.a.voltage is None or self.b.voltage is None:
            return None
        return self.a.voltage + self.b.voltage

    @property
    def pack_current(self) -> Optional[float]:
        # Series → same current. Average to suppress per-BMS noise.
        vals = [x for x in (self.a.current, self.b.current) if x is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def pack_power(self) -> Optional[float]:
        if self.pack_voltage is None or self.pack_current is None:
            return None
        return self.pack_voltage * self.pack_current

    @property
    def avg_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def min_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return min(vals) if vals else None

    @property
    def max_soc(self) -> Optional[float]:
        vals = [x for x in (self.a.soc, self.b.soc) if x is not None]
        return max(vals) if vals else None


async def discover_volthium(timeout: float = 8.0) -> list[tuple[BLEDevice, str]]:
    """Return [(BLEDevice, advertised_name)] for every Volthium battery in range."""
    found: dict[str, tuple[BLEDevice, str]] = {}

    def cb(dev: BLEDevice, adv) -> None:
        name = adv.local_name or dev.name or ""
        if name.startswith(ADV_NAME_PREFIX):
            found[dev.address] = (dev, name)

    scanner = BleakScanner(detection_callback=cb)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    return list(found.values())


async def read_battery(address: str, *, timeout: float = 20.0) -> BatteryReading:
    """Connect to one battery by address, read one sample, disconnect."""
    dev = await BleakScanner.find_device_by_address(address, timeout=timeout)
    if dev is None:
        raise RuntimeError(f"battery {address} not found in scan")
    async with VolthiumBMS(ble_device=dev) as bms:
        sample = await bms.async_update()
    name = dev.name or ""
    return BatteryReading.from_sample(address, name, sample)


async def read_pack(addr_a: str, addr_b: str) -> PackReading:
    """Read both batteries concurrently."""
    a, b = await asyncio.gather(read_battery(addr_a), read_battery(addr_b))
    return PackReading(a=a, b=b)
