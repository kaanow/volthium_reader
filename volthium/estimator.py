"""Time-to-full / time-to-empty estimator with smoothing."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

from .pack import PackReading


@dataclass
class Estimate:
    state: str                 # "charging" | "discharging" | "idle" | "full"
    smoothed_current: float    # A, positive = charging
    smoothed_power: float      # W
    minutes_remaining: Optional[float]   # to full (charging) or to floor (discharging)
    target_label: str          # "full" | "10%" | "—"
    displayed_ah: Optional[float] = None  # only populated in hybrid mode


class Estimator:
    """Exponential moving average on current + power, then linear extrapolation.

    Two heuristics worth knowing:
      - We extrapolate against the limiting battery: the *higher* SOC bounds
        charging time, the *lower* SOC bounds discharging time.
      - Anything under |I| ≈ 0.5 A is treated as idle so the time doesn't go
        to ±infinity when the inverter is off and there's no sun.
    """

    def __init__(
        self,
        capacity_ah: float = 200.0,    # per battery; same for a series pack
        floor_soc: float = 10.0,       # % — "empty" floor
        ceiling_soc: float = 95.0,     # % — "full" for time-remaining math.
                                       # 95 % matches LiFePO4 absorption-onset
                                       # and is what we banner "FULL" at.
                                       # The remaining 5 % is CV-taper time
                                       # which is hard to predict linearly.
        idle_current_a: float = 0.5,
        alpha: float = 0.15,           # EMA smoothing — lower = smoother
        window: int = 20,              # also keep a window for diagnostics
        current_calibration: float = 1.0,  # multiplier on reported pack current
                                       # when computing time-to-X.
                                       # Empirical finding on the Barge Inn
                                       # pair: BMS-reported Ah accumulation
                                       # is non-linear vs current — see
                                       # docs/hardware/bms_calibration.md.
                                       # A single multiplier can't capture
                                       # the sign flip between bulk-charge
                                       # (ratio 1.12) and trickle (0.94).
                                       # Use hybrid mode below for the
                                       # right answer.
        use_remaining_ah_anchor: bool = False,
                                       # If True, maintain an internal
                                       # remaining_ah estimator that
                                       # integrates pack_current * dt
                                       # between samples and re-anchors
                                       # to the BMS-reported remaining_ah
                                       # whenever it ticks. This gives
                                       # smooth UI updates while staying
                                       # honest to the BMS's coulomb-
                                       # counting truth. Recommended for
                                       # production firmware.
        anchor_integrator_weight: float = 0.8,
                                       # When the BMS ticks remaining_ah,
                                       # we blend new_displayed_ah =
                                       #   w * integrator + (1-w) * anchor.
                                       # 0.8 = trust integrator 80%,
                                       # use anchor as a slow correction.
                                       # Lower = snap harder to BMS truth.
    ) -> None:
        self.capacity_ah = capacity_ah
        self.floor_soc = floor_soc
        self.ceiling_soc = ceiling_soc
        self.idle_current_a = idle_current_a
        self.alpha = alpha
        self.current_calibration = current_calibration
        self.use_remaining_ah_anchor = use_remaining_ah_anchor
        self.anchor_integrator_weight = anchor_integrator_weight
        self._ema_i: Optional[float] = None
        self._ema_p: Optional[float] = None
        self._recent: deque[float] = deque(maxlen=window)
        # Hybrid-mode state:
        self._displayed_ah: Optional[float] = None
        self._last_anchor_ah: Optional[float] = None
        self._last_ts: Optional[float] = None        # seconds (monotonic or unix)

    def update(
        self,
        reading: PackReading,
        ts: Union[datetime, float, None] = None,
    ) -> Estimate:
        """Step the estimator with a new reading.

        ts: optional timestamp for hybrid-mode time-integration. Accepts
        a datetime, a unix/monotonic float, or None (uses time.monotonic()).
        """
        i = reading.pack_current
        p = reading.pack_power

        if i is None:
            return Estimate("unknown", 0.0, 0.0, None, "—")

        self._ema_i = i if self._ema_i is None else (
            self.alpha * i + (1 - self.alpha) * self._ema_i
        )
        if p is not None:
            self._ema_p = p if self._ema_p is None else (
                self.alpha * p + (1 - self.alpha) * self._ema_p
            )
        self._recent.append(i)

        si = self._ema_i
        sp = self._ema_p or 0.0

        # Hybrid mode bookkeeping (runs regardless of state — the
        # integrator should never lose track of what's flowing).
        displayed_ah = self._update_hybrid(reading, i, ts) if self.use_remaining_ah_anchor else None

        if abs(si) < self.idle_current_a:
            return Estimate("idle", si, sp, None, "—", displayed_ah)

        # Effective current for time-remaining math: apply our calibration
        # factor. Reported (raw) current is what we display; effective is
        # what the BMS's own Ah counter would imply.
        eff_i = si * self.current_calibration

        if si > 0:  # charging — limited by the battery that's already higher
            soc = reading.max_soc
            if soc is None:
                return Estimate("charging", si, sp, None, "full", displayed_ah)
            # Already at or past the "full" threshold — banner it and stop predicting.
            if soc >= self.ceiling_soc:
                return Estimate("full", si, sp, 0.0, "full", displayed_ah)
            # Ah needed: hybrid mode uses displayed Ah; fallback uses SOC%.
            if displayed_ah is not None:
                ah_needed = (self.capacity_ah * self.ceiling_soc / 100.0) - displayed_ah
            else:
                ah_needed = self.capacity_ah * (self.ceiling_soc - soc) / 100.0
            minutes = (ah_needed / eff_i) * 60.0 if eff_i > 0 and ah_needed > 0 else None
            return Estimate("charging", si, sp, minutes, "full", displayed_ah)

        # discharging — limited by the battery that's already lower
        soc = reading.min_soc
        if soc is None:
            return Estimate("discharging", si, sp, None, f"{self.floor_soc:g}%", displayed_ah)
        if displayed_ah is not None:
            ah_left = displayed_ah - (self.capacity_ah * self.floor_soc / 100.0)
        else:
            ah_left = self.capacity_ah * (soc - self.floor_soc) / 100.0
        minutes = (ah_left / -eff_i) * 60.0 if eff_i < 0 and ah_left > 0 else None
        return Estimate("discharging", si, sp, minutes, f"{self.floor_soc:g}%", displayed_ah)

    def _update_hybrid(
        self,
        reading: PackReading,
        current: float,
        ts: Union[datetime, float, None],
    ) -> Optional[float]:
        """Maintain self._displayed_ah by integrating current*dt between
        samples, then blending with the BMS anchor whenever it ticks.
        Returns the current displayed_ah for this sample."""
        # Resolve ts → seconds
        if ts is None:
            now_s = time.monotonic()
        elif isinstance(ts, datetime):
            now_s = ts.timestamp()
        else:
            now_s = float(ts)

        # Compute the BMS anchor (avg of two batteries, if both report)
        a_ah = reading.a.remaining_ah if reading.a else None
        b_ah = reading.b.remaining_ah if reading.b else None
        anchor = (a_ah + b_ah) / 2.0 if a_ah is not None and b_ah is not None else None

        # First update: seed the displayed value from the anchor
        if self._displayed_ah is None:
            if anchor is not None:
                self._displayed_ah = anchor
                self._last_anchor_ah = anchor
            self._last_ts = now_s
            return self._displayed_ah

        # Integrate current * dt to advance displayed value
        if self._last_ts is not None:
            dt = now_s - self._last_ts
            # cap dt to avoid huge jumps from clock changes / gaps
            if 0 < dt < 600:
                self._displayed_ah += current * dt / 3600.0
        self._last_ts = now_s

        # Re-anchor whenever the BMS reports a different value than last seen
        if anchor is not None and anchor != self._last_anchor_ah:
            w = self.anchor_integrator_weight
            self._displayed_ah = w * self._displayed_ah + (1.0 - w) * anchor
            self._last_anchor_ah = anchor

        return self._displayed_ah


def format_minutes(m: Optional[float]) -> str:
    if m is None:
        return "—"
    if m < 0:
        return "—"
    if m < 60:
        return f"{m:.0f} min"
    h, mm = divmod(m, 60)
    if h < 48:
        return f"{int(h)}h {int(mm):02d}m"
    d, h = divmod(h, 24)
    return f"{int(d)}d {int(h):02d}h"
