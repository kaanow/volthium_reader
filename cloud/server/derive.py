"""Server-side derivation: turn raw per-battery readings into the pack-level
+ smoothed + projected fields that the dashboard needs.

This is the moral equivalent of volthium.estimator.Estimator, lifted out of
the edge so the ESP32 firmware doesn't need to ship it. Same defaults; same
formulas. Keep them in sync — see volthium/estimator.py.

Stateless on its own; callers thread the prior smoothed values in via
`prev_smoothed_*` (typically read from the most recent stored row for the
same source_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cloud.shared.wire import Reading


@dataclass
class Derived:
    pack_v: Optional[float]
    pack_i: Optional[float]
    pack_p: Optional[float]
    smoothed_i: Optional[float]
    smoothed_p: Optional[float]
    minutes_remaining: Optional[float]


def _avg(*vals: Optional[float]) -> Optional[float]:
    nums = [v for v in vals if v is not None]
    return sum(nums) / len(nums) if nums else None


def _sum(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a + b


def derive(
    r: Reading,
    *,
    prev_smoothed_i: Optional[float],
    prev_smoothed_p: Optional[float],
    alpha: float,
    capacity_ah: float,
    floor_soc: float,
    ceiling_soc: float,
    idle_current_a: float,
) -> Derived:
    """Compute Derived for one reading given the prior EMA state.

    Mirrors Estimator.update() exactly so the local CSV and the cloud row
    agree to within float rounding. The only deliberate divergence is the
    hybrid-mode anchor integrator (use_remaining_ah_anchor) — it's not
    implemented server-side yet because it needs per-source persistent state
    beyond just smoothed_i/p, and v1 doesn't need it.
    """

    pack_v = _sum(r.v_a, r.v_b)
    pack_i = _avg(r.i_a, r.i_b)
    pack_p = pack_v * pack_i if (pack_v is not None and pack_i is not None) else None

    # EMA on current and power.
    if pack_i is None:
        # No usable current — pass priors through unchanged so we don't
        # corrupt the moving average with a None blend.
        return Derived(
            pack_v=pack_v, pack_i=pack_i, pack_p=pack_p,
            smoothed_i=prev_smoothed_i, smoothed_p=prev_smoothed_p,
            minutes_remaining=None,
        )

    si = pack_i if prev_smoothed_i is None else (
        alpha * pack_i + (1 - alpha) * prev_smoothed_i
    )
    if pack_p is None:
        sp = prev_smoothed_p
    elif prev_smoothed_p is None:
        sp = pack_p
    else:
        sp = alpha * pack_p + (1 - alpha) * prev_smoothed_p

    minutes_remaining: Optional[float] = None

    if abs(si) < idle_current_a:
        # idle — no meaningful projection
        return Derived(pack_v, pack_i, pack_p, si, sp, None)

    if si > 0:
        # charging — limited by the higher-SOC battery
        socs = [v for v in (r.soc_a, r.soc_b) if v is not None]
        if not socs:
            return Derived(pack_v, pack_i, pack_p, si, sp, None)
        soc = max(socs)
        if soc >= ceiling_soc:
            return Derived(pack_v, pack_i, pack_p, si, sp, 0.0)
        ah_needed = capacity_ah * (ceiling_soc - soc) / 100.0
        if ah_needed > 0:
            minutes_remaining = (ah_needed / si) * 60.0
    else:
        # discharging — limited by the lower-SOC battery
        socs = [v for v in (r.soc_a, r.soc_b) if v is not None]
        if not socs:
            return Derived(pack_v, pack_i, pack_p, si, sp, None)
        soc = min(socs)
        ah_left = capacity_ah * (soc - floor_soc) / 100.0
        if ah_left > 0 and si < 0:
            minutes_remaining = (ah_left / -si) * 60.0

    return Derived(pack_v, pack_i, pack_p, si, sp, minutes_remaining)
