"""Solar harvest model — predicts Ah delivered to the pack tomorrow
given today's (or a forecast's) total irradiance Wh/m².

The class is intentionally simple:

    model = SolarModel.default()           # constant-coefficient stub
    ah = model.predict_ah(kwh_per_m2=5.34) # ~37 Ah

    # Once we have ≥3 full-day rows from scripts/daily_summary.py:
    model = SolarModel.fit_from_daily_summary(rows)
    # — same predict_ah() interface, but the coefficient is now
    # learned from real (irradiance, solar_ah_estimated) pairs.

Future refinements (deferred until data justifies them):
  - Hour-of-day weighting to capture the west-facing array's late-
    afternoon bias instead of treating the day as one bulk Ah number.
  - Cloud-cover bucket per-hour vs. clear-sky baseline.
  - Temperature derating coefficient.

For now: one number, anchored on the first observed data point.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, Optional


# First empirical anchor — see scripts/daily_summary.py output and
# docs/STATUS.md 03:42 entry. 21.4 Ah of solar over partial late-
# afternoon observation of a 7.19 kWh/m² day. Scaled to a full day:
# implies roughly 7 Ah/(kWh/m²) for our west-facing array.
DEFAULT_AH_PER_KWH_PER_M2 = 7.0

# Sanity rails so a bad fit doesn't blow up downstream predictions.
MIN_REASONABLE_COEFFICIENT = 2.0    # heavy overcast, panels dusty, etc.
MAX_REASONABLE_COEFFICIENT = 15.0   # perfect alignment, near-ideal site


@dataclass
class SolarModel:
    """Linear-coefficient solar harvest predictor.

    predict_ah = irradiance_kwh_m2 × coefficient

    `n_observations` and `fit_residual_mad` tell callers how much to
    trust this instance (higher n + lower MAD → higher confidence).
    """
    coefficient_ah_per_kwh_m2: float
    n_observations: int = 0
    fit_residual_mad: Optional[float] = None
    notes: str = ""

    # ---------- prediction ----------
    def predict_ah(self, kwh_per_m2: float) -> float:
        """Return the expected Ah delivered to the pack for an entire
        day of `kwh_per_m2` total ground-irradiance."""
        if kwh_per_m2 <= 0:
            return 0.0
        return kwh_per_m2 * self.coefficient_ah_per_kwh_m2

    # ---------- confidence ----------
    @property
    def confidence(self) -> str:
        if self.n_observations >= 7:
            return "high"
        if self.n_observations >= 3:
            return "medium"
        return "low"

    # ---------- factories ----------
    @classmethod
    def default(cls) -> "SolarModel":
        return cls(
            coefficient_ah_per_kwh_m2=DEFAULT_AH_PER_KWH_PER_M2,
            n_observations=0,
            notes="default constant — anchored on 2026-05-17 partial-day observation",
        )

    @classmethod
    def fit_from_pairs(
        cls,
        pairs: Iterable[tuple[float, float]],
    ) -> "SolarModel":
        """Fit from (kwh_per_m2, observed_ah) pairs.

        Forces the line through the origin (zero sunlight → zero Ah),
        so the fitted coefficient = mean(ah / kwh) weighted by kwh.
        Falls back to the default when there are no usable points.
        """
        usable = [(k, a) for (k, a) in pairs if k is not None and a is not None and k > 0 and a > 0]
        if not usable:
            m = cls.default()
            m.notes = "no usable observations yet; using default"
            return m

        # Per-day ratios; median is robust against any single weird day
        # (e.g. a partial-data row, or a generator-misclassified-as-solar day).
        ratios = [a / k for (k, a) in usable]
        coef = statistics.median(ratios)
        # Clamp to sanity rails
        coef_clamped = max(MIN_REASONABLE_COEFFICIENT,
                           min(MAX_REASONABLE_COEFFICIENT, coef))

        # MAD as a residual confidence proxy
        residuals = [r - coef for r in ratios]
        mad = statistics.median(abs(r) for r in residuals) if len(residuals) > 1 else None

        note = (f"fit from {len(usable)} observations; "
                f"median ratio {coef:.2f}")
        if coef != coef_clamped:
            note += f" (clamped to {coef_clamped:.2f})"
        return cls(
            coefficient_ah_per_kwh_m2=coef_clamped,
            n_observations=len(usable),
            fit_residual_mad=mad,
            notes=note,
        )

    @classmethod
    def fit_from_daily_summary(cls, daily_rows: Iterable[dict]) -> "SolarModel":
        """Build a model from rows produced by scripts/daily_summary.py.

        Selects rows with:
          - partial=False        (complete day; see daily_summary.py for
                                  why the old `duration_h > 12` rule was
                                  wrong — it tripped at noon for a
                                  midnight-start logger)
          - weather_kwh_m2 > 0
          - solar_ah_estimated > 0
        and fits via fit_from_pairs.

        Backwards-compatibility: rows without a `partial` column (older
        files) fall back to a duration check of >= 20 h.
        """
        pairs = []
        for r in daily_rows:
            partial_raw = r.get("partial")
            if partial_raw not in (None, ""):
                # CSV stores as 'True' / 'False'
                is_partial = str(partial_raw).lower() in ("true", "1", "yes")
            else:
                duration_h = _num(r.get("duration_h"))
                is_partial = duration_h is None or duration_h < 20.0
            if is_partial:
                continue
            kwh = _num(r.get("weather_kwh_m2"))
            ah  = _num(r.get("solar_ah_estimated"))
            if kwh is None or ah is None:
                continue
            pairs.append((kwh, ah))
        return cls.fit_from_pairs(pairs)


def _num(v) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
