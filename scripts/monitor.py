"""Live dashboard for the 24V Volthium pack.

Polls both batteries on an interval, displays SOC / V / A / W / temperature
and a smoothed time-to-full or time-to-empty estimate. Optionally logs every
sample to CSV.
"""

import argparse
import asyncio
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from volthium.estimator import Estimator, format_minutes
from volthium.pack import PackReading, read_pack


def render(pack: PackReading, est, last_error: str | None) -> Panel:
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="dim")
    t.add_column()

    pv = pack.pack_voltage
    pi = pack.pack_current
    pp = pack.pack_power

    state_color = {
        "charging": "green",
        "discharging": "yellow",
        "idle": "white",
        "unknown": "red",
    }.get(est.state, "white")

    t.add_row(
        "state",
        Text(est.state.upper(), style=f"bold {state_color}"),
    )
    t.add_row("pack V", f"{pv:6.2f} V" if pv is not None else "—")
    t.add_row(
        "pack I",
        f"{pi:+6.2f} A  (smoothed {est.smoothed_current:+.2f} A)"
        if pi is not None else "—",
    )
    t.add_row(
        "pack P",
        f"{pp:+7.1f} W  (smoothed {est.smoothed_power:+.1f} W)"
        if pp is not None else "—",
    )
    if pack.min_soc is not None:
        t.add_row(
            "SOC",
            f"min {pack.min_soc:5.1f}%   max {pack.max_soc:5.1f}%   "
            f"avg {pack.avg_soc:5.1f}%",
        )

    time_str = format_minutes(est.minutes_remaining)
    if est.state == "charging":
        t.add_row("time to full", Text(time_str, style="bold green"))
    elif est.state == "discharging":
        t.add_row(
            f"time to {est.target_label}",
            Text(time_str, style="bold yellow"),
        )
    else:
        t.add_row("time", "—")

    t.add_row("", "")

    per_batt = Table(show_header=True, header_style="bold", expand=False)
    per_batt.add_column("battery")
    per_batt.add_column("SOC")
    per_batt.add_column("V")
    per_batt.add_column("A")
    per_batt.add_column("T")
    per_batt.add_column("cycles")
    per_batt.add_column("Δcell mV")
    for r in (pack.a, pack.b):
        per_batt.add_row(
            f"{r.label}  {r.name or r.address}",
            f"{r.soc:.0f}%" if r.soc is not None else "—",
            f"{r.voltage:.2f}" if r.voltage is not None else "—",
            f"{r.current:+.2f}" if r.current is not None else "—",
            f"{r.temperature:.0f}°C" if r.temperature is not None else "—",
            f"{r.cycles}" if r.cycles is not None else "—",
            f"{r.delta_voltage * 1000:.0f}" if r.delta_voltage is not None else "—",
        )

    grid = Table.grid()
    grid.add_row(t)
    grid.add_row(per_batt)
    if last_error:
        grid.add_row(Text(last_error, style="red"))

    return Panel(
        grid,
        title=f"The Barge Inn — Volthium 24V pack   {datetime.now():%H:%M:%S}",
        border_style="cyan",
    )


CSV_FIELDS = [
    "ts", "state", "pack_v", "pack_i", "pack_p",
    "soc_a", "soc_b", "v_a", "v_b", "i_a", "i_b",
    "t_a", "t_b", "smoothed_i", "smoothed_p", "minutes_remaining",
]


def append_csv(path: Path, pack: PackReading, est) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "state": est.state,
            "pack_v": pack.pack_voltage,
            "pack_i": pack.pack_current,
            "pack_p": pack.pack_power,
            "soc_a": pack.a.soc, "soc_b": pack.b.soc,
            "v_a": pack.a.voltage, "v_b": pack.b.voltage,
            "i_a": pack.a.current, "i_b": pack.b.current,
            "t_a": pack.a.temperature, "t_b": pack.b.temperature,
            "smoothed_i": est.smoothed_current,
            "smoothed_p": est.smoothed_power,
            "minutes_remaining": est.minutes_remaining,
        })


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="battery A BLE address")
    ap.add_argument("--b", required=True, help="battery B BLE address")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between polls")
    ap.add_argument("--floor", type=float, default=10.0, help="empty-floor SOC %")
    ap.add_argument("--capacity", type=float, default=200.0, help="per-battery Ah")
    ap.add_argument("--csv", type=Path, help="log every sample to this CSV")
    args = ap.parse_args()

    est = Estimator(capacity_ah=args.capacity, floor_soc=args.floor)
    console = Console()
    last_error: str | None = None

    with Live(Panel("Connecting..."), console=console, refresh_per_second=4, screen=False) as live:
        while True:
            t0 = time.monotonic()
            try:
                pack = await read_pack(args.a, args.b)
                estimate = est.update(pack)
                last_error = None
                live.update(render(pack, estimate, last_error))
                if args.csv:
                    append_csv(args.csv, pack, estimate)
            except Exception as exc:
                last_error = f"read failed: {type(exc).__name__}: {exc}"
                # keep the last frame visible; don't replace the whole UI on error
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, args.interval - elapsed))


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print()
        sys.exit(0)
