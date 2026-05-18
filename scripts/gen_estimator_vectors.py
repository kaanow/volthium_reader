"""Generate Python → C cross-validation vectors for the estimator.

The estimator is implemented twice: `volthium/estimator.py` is the spec
and `firmware/common/volthium_lib/estimator.{h,c}` is the C port. Both
already have unit tests, but until now they were tested independently —
nothing forced them to agree against the same inputs.

This script feeds a series of hand-crafted scenarios through the Python
reference and writes the expected outputs to a plain-text file. The
companion C test in `firmware/common/volthium_lib/test_estimator_cross.c`
parses the same file, re-runs the C estimator, and asserts every output
matches within a tight floating-point tolerance.

Tolerances are deliberately small (1e-4 on currents, 0.1 min on
minutes_remaining) — the two implementations should be in lock-step;
any larger drift means a real bug.

Run from repo root:
    .venv/bin/python scripts/gen_estimator_vectors.py

Output: firmware/common/volthium_lib/test_vectors/estimator_scenarios.txt

File format (text, line-oriented):
    # comment
    scenario: <name>
    config: capacity=NNN,floor=NN,ceiling=NN,idle=N.N,alpha=N.NN,
            calibration=N.N,hybrid=0|1,blend=N.N
    step:   ts_ms,pack_i_a,has_pack_p,pack_p_w,
            has_max_soc,max_soc_pct,has_min_soc,min_soc_pct,
            has_rem_ah,rem_ah_avg
    expect: state_code,smoothed_i_a,smoothed_p_w,
            has_min,minutes_remaining,
            has_disp,displayed_ah
    end

State codes match `est_state_t` in estimator.h:
    unknown=0, idle=1, charging=2, discharging=3, full=4
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from volthium.estimator import Estimator
from volthium.pack import BatteryReading, PackReading


STATE_CODE = {
    "unknown":     0,
    "idle":        1,
    "charging":    2,
    "discharging": 3,
    "full":        4,
}


@dataclass
class Step:
    """One observation pushed into the estimator.

    Note: pack_power is NOT a free parameter — PackReading.pack_power is
    computed as pack_voltage * pack_current. We fix per-battery voltage
    at 13.2 V (so pack_voltage = 26.4 V) and emit the resulting power
    into the scenarios file so the C test reads the exact same value.
    """
    ts_ms: int
    pack_i_a: float
    max_soc_pct: Optional[float] = None
    min_soc_pct: Optional[float] = None
    rem_ah_avg: Optional[float] = None      # average of the two batteries

    def to_pack_reading(self) -> PackReading:
        """Build the synthetic PackReading the Python estimator expects.

        Per-battery current is pack_current / 2 so that the average
        recovers pack_i_a. Voltage is fixed at 13.2 V each (26.4 V pack).
        rem_ah is split equally so the estimator's avg(a, b) anchor
        compute recovers rem_ah_avg.
        """
        # Series pack: same current flows through both batteries, so both
        # report the full pack current. PackReading.pack_current AVERAGES
        # the two (not sums), giving back pack_i_a. Same for rem_ah_avg.
        rem_a = rem_b = self.rem_ah_avg
        a = BatteryReading(
            address="aa:aa:aa:aa:aa:aa",
            name="V-12V200AH-0033",
            voltage=13.2,
            current=self.pack_i_a,
            soc=self.max_soc_pct,
            remaining_ah=rem_a,
            temperature=23.0,
            cycles=0,
            cell_voltages=None,
            delta_voltage=0.010,
            charging_fet=True,
            discharging_fet=True,
            problem_code=0,
        )
        b = BatteryReading(
            address="bb:bb:bb:bb:bb:bb",
            name="V-12V200AH-0067",
            voltage=13.2,
            current=self.pack_i_a,
            soc=self.min_soc_pct,
            remaining_ah=rem_b,
            temperature=23.0,
            cycles=0,
            cell_voltages=None,
            delta_voltage=0.010,
            charging_fet=True,
            discharging_fet=True,
            problem_code=0,
        )
        return PackReading(a=a, b=b)


@dataclass
class Scenario:
    name: str
    capacity_ah: float
    floor_soc: float
    ceiling_soc: float
    idle_current_a: float
    alpha: float
    calibration: float
    hybrid: bool
    blend: float
    steps: list[Step]


def make_estimator(s: Scenario) -> Estimator:
    return Estimator(
        capacity_ah=s.capacity_ah,
        floor_soc=s.floor_soc,
        ceiling_soc=s.ceiling_soc,
        idle_current_a=s.idle_current_a,
        alpha=s.alpha,
        current_calibration=s.calibration,
        use_remaining_ah_anchor=s.hybrid,
        anchor_integrator_weight=s.blend,
    )


# ---------------------------------------------------------------------------
# Scenarios — chosen for coverage of behavior, not exhaustive
# ---------------------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    # 1. Plain charging, SOC-based mode. Tests EMA buildup and SOC math.
    Scenario(
        name="steady_charge_soc_mode",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.0,
        hybrid=False, blend=0.8,
        steps=[
            Step(ts_ms=0,     pack_i_a=+15.0, max_soc_pct=68, min_soc_pct=66),
            Step(ts_ms=10000, pack_i_a=+16.0, max_soc_pct=68, min_soc_pct=66),
            Step(ts_ms=20000, pack_i_a=+15.5, max_soc_pct=68, min_soc_pct=66),
            Step(ts_ms=30000, pack_i_a=+16.0, max_soc_pct=68, min_soc_pct=66),
            Step(ts_ms=40000, pack_i_a=+16.0, max_soc_pct=69, min_soc_pct=67),
        ],
    ),
    # 2. Plain discharging, SOC-based. Tests floor math + negative current.
    Scenario(
        name="steady_discharge_soc_mode",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.0,
        hybrid=False, blend=0.8,
        steps=[
            Step(ts_ms=0,     pack_i_a=-8.0, max_soc_pct=72, min_soc_pct=70),
            Step(ts_ms=10000, pack_i_a=-7.5, max_soc_pct=72, min_soc_pct=70),
            Step(ts_ms=20000, pack_i_a=-8.0, max_soc_pct=72, min_soc_pct=70),
            Step(ts_ms=30000, pack_i_a=-9.0, max_soc_pct=72, min_soc_pct=70),
            Step(ts_ms=40000, pack_i_a=-8.5, max_soc_pct=71, min_soc_pct=69),
        ],
    ),
    # 3. Idle (very small currents) — state should be "idle", no minutes.
    Scenario(
        name="idle_state",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.0,
        hybrid=False, blend=0.8,
        steps=[
            Step(ts_ms=0,     pack_i_a=+0.1, max_soc_pct=80, min_soc_pct=78),
            Step(ts_ms=10000, pack_i_a=-0.2, max_soc_pct=80, min_soc_pct=78),
            Step(ts_ms=20000, pack_i_a=+0.0, max_soc_pct=80, min_soc_pct=78),
        ],
    ),
    # 4. Full state — charging but SOC already at ceiling. Output minutes=0.
    Scenario(
        name="full_state",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.0,
        hybrid=False, blend=0.8,
        steps=[
            Step(ts_ms=0,     pack_i_a=+5.0, max_soc_pct=95, min_soc_pct=94),
            Step(ts_ms=10000, pack_i_a=+5.0, max_soc_pct=96, min_soc_pct=95),
        ],
    ),
    # 5. Hybrid mode charging — exercises seed-from-anchor, integrate,
    #    re-anchor blending on next tick.
    Scenario(
        name="hybrid_charging_with_anchor",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.0,
        hybrid=True, blend=0.8,
        steps=[
            Step(ts_ms=0,      pack_i_a=+20.0,
                 max_soc_pct=70, min_soc_pct=68, rem_ah_avg=150.0),
            Step(ts_ms=10000,  pack_i_a=+20.0,
                 max_soc_pct=70, min_soc_pct=68, rem_ah_avg=150.0),
            Step(ts_ms=60000,  pack_i_a=+20.0,
                 max_soc_pct=71, min_soc_pct=69, rem_ah_avg=150.3),
            Step(ts_ms=120000, pack_i_a=+18.0,
                 max_soc_pct=72, min_soc_pct=70, rem_ah_avg=150.6),
        ],
    ),
    # 6. Current-calibration multiplier ≠ 1.0. Smoothed current stays
    #    RAW (no calibration); only minutes_remaining math uses eff_i.
    Scenario(
        name="charging_with_calibration",
        capacity_ah=215.0, floor_soc=10.0, ceiling_soc=95.0,
        idle_current_a=0.5, alpha=0.15, calibration=1.2,
        hybrid=False, blend=0.8,
        steps=[
            Step(ts_ms=0,     pack_i_a=+30.0, max_soc_pct=70, min_soc_pct=68),
            Step(ts_ms=10000, pack_i_a=+30.0, max_soc_pct=70, min_soc_pct=68),
            Step(ts_ms=20000, pack_i_a=+30.0, max_soc_pct=70, min_soc_pct=68),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def f(v: Optional[float], fmt: str = ".6f") -> str:
    """Format a float for emission, or return '-' for None."""
    if v is None:
        return "-"
    return format(v, fmt)


def emit(scenarios: list[Scenario]) -> str:
    """Run each scenario through the Python estimator and emit the
    text-format scenarios file."""
    out: list[str] = []
    out.append("# Python → C estimator cross-validation vectors.")
    out.append("# Generated by scripts/gen_estimator_vectors.py — do not edit by hand.")
    out.append("# State codes: unknown=0 idle=1 charging=2 discharging=3 full=4")
    out.append("#")
    out.append("# step:   ts_ms,pack_i_a,has_pack_p,pack_p_w,"
               "has_max_soc,max_soc_pct,has_min_soc,min_soc_pct,"
               "has_rem_ah,rem_ah_avg")
    out.append("# expect: state_code,smoothed_i_a,smoothed_p_w,"
               "has_min,minutes_remaining,has_disp,displayed_ah")
    out.append("")

    for s in scenarios:
        est = make_estimator(s)

        out.append(f"scenario: {s.name}")
        out.append(
            f"config: capacity={s.capacity_ah:.3f},floor={s.floor_soc:.3f},"
            f"ceiling={s.ceiling_soc:.3f},idle={s.idle_current_a:.3f},"
            f"alpha={s.alpha:.6f},calibration={s.calibration:.6f},"
            f"hybrid={int(s.hybrid)},blend={s.blend:.3f}"
        )
        for step in s.steps:
            # Build the reading once. pack_power comes from voltage*current
            # inside PackReading — emit that exact value so the C test sees
            # the same number we fed to the Python EMA.
            reading = step.to_pack_reading()
            derived_p = reading.pack_power
            has_p = 1 if derived_p is not None else 0
            has_max = 1 if step.max_soc_pct is not None else 0
            has_min = 1 if step.min_soc_pct is not None else 0
            has_rem = 1 if step.rem_ah_avg is not None else 0
            out.append(
                "step: "
                f"{step.ts_ms},"
                f"{step.pack_i_a:.6f},"
                f"{has_p},{(derived_p if derived_p is not None else 0.0):.6f},"
                f"{has_max},{(step.max_soc_pct if step.max_soc_pct is not None else 0.0):.6f},"
                f"{has_min},{(step.min_soc_pct if step.min_soc_pct is not None else 0.0):.6f},"
                f"{has_rem},{(step.rem_ah_avg if step.rem_ah_avg is not None else 0.0):.6f}"
            )
            # run Python reference
            ts_s = step.ts_ms / 1000.0
            est_out = est.update(reading, ts=ts_s)
            has_minutes = 1 if est_out.minutes_remaining is not None else 0
            has_disp = 1 if est_out.displayed_ah is not None else 0
            minutes = est_out.minutes_remaining if est_out.minutes_remaining is not None else 0.0
            disp = est_out.displayed_ah if est_out.displayed_ah is not None else 0.0
            out.append(
                "expect: "
                f"{STATE_CODE[est_out.state]},"
                f"{est_out.smoothed_current:.6f},"
                f"{est_out.smoothed_power:.6f},"
                f"{has_minutes},{minutes:.4f},"
                f"{has_disp},{disp:.6f}"
            )
        out.append("end")
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    out_path = Path(__file__).resolve().parents[1] / \
        "firmware/common/volthium_lib/test_vectors/estimator_scenarios.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = emit(SCENARIOS)
    out_path.write_text(text)
    print(f"wrote {out_path}")
    print(f"  {len(SCENARIOS)} scenarios, "
          f"{sum(len(s.steps) for s in SCENARIOS)} total step/expect pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
