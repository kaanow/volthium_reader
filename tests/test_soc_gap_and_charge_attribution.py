"""Two claims the data does not support, in a tooltip and a docstring.

1. "A↔B GAP: ... in a healthy series pack this stays under ~3 %. Widening gap
   ... early signal of cell imbalance or one battery aging faster."

   Measured against production:

       2026-09-20   max 15pp   median 14pp
       2026-09-27   max 13pp   median 12pp
       2026-10-01   max 12pp   median 11pp

   0 of 3 sampled days were ever inside the band, and across 5000 readings on
   10-04 the gap ran median 7pp / p95 10pp / max 11pp. A threshold the pack
   has never once met does not diagnose anything; it declares the hardware
   permanently sick, every day, which is how an operator learns to ignore it.

   It is also the wrong invariant. The packs are in SERIES with independent
   BMS SOC estimators, which drift apart by construction. Series forces
   CURRENT to match, and that holds: |i_a - i_b| median 0.60 A, p95 1.60 A.

2. "CHARGING START ... the empirical 'morning shadow cleared' time for this
   west-facing array."

   first_charge_time is the first sample with pack_i > +1 A — source-agnostic.
   A generator run sets it identically, and one ran 15:50-16:13 on 2026-10-04.
   The number cannot support a solar attribution.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

DASH = REPO / "scripts/dashboard.py"
HARVEST = REPO / "scripts/today_harvest.py"

# The measured reality these claims must stay consistent with.
OBSERVED_MEDIAN_GAP_PP = 7
OBSERVED_MAX_GAP_PP = 15


def test_the_three_percent_health_threshold_is_gone():
    for path in (DASH, HARVEST):
        src = path.read_text()
        assert "stays under" not in src or "~3 %" not in src, (
            f"{path.name} still asserts a ~3% healthy band for the A-B SOC "
            f"gap; the pack has never been inside it")
        # The specific diagnostic claim must not return either.
        assert "early signal of cell imbalance" not in src, (
            f"{path.name} again reads a routine {OBSERVED_MEDIAN_GAP_PP}pp "
            f"gap as incipient cell imbalance")


def test_the_gap_is_framed_as_a_trend_against_its_own_baseline():
    for path in (DASH, HARVEST):
        src = path.read_text()
        assert "TREND" in src or "trend" in src, (
            f"{path.name} gives no basis for judging the gap at all")


def test_the_correct_series_invariant_is_named():
    """A correction that only removes the false claim leaves the operator with
    nothing. Current agreement is the check that actually applies."""
    for path in (DASH, HARVEST):
        src = path.read_text()
        assert re.search(r"i_a\s*[-−]\s*i_b", src), (
            f"{path.name} does not point at |i_a - i_b|, the invariant a "
            f"series pack genuinely forces")


def test_charging_start_is_not_attributed_to_the_sun():
    src = DASH.read_text()
    assert "morning shadow cleared' \"" not in src
    # It may be mentioned as the corrected-from wording, but must not be the
    # live claim: the live text has to name the generator as a possible cause.
    m = re.search(r'"CHARGING START:.*?(?=\+ "BEST HOUR)', src, re.S)
    assert m, "the CHARGING START tooltip text is gone or restructured"
    text = m.group(0)
    assert "GENERATOR" in text.upper(), (
        f"the tooltip still implies only solar can start charging:\n{text}")


def test_harvest_docstring_marks_the_field_source_agnostic():
    src = HARVEST.read_text()
    m = re.search(r"first_charge_time.*?peak_soc_gap_pct", src, re.S)
    assert m, "the first_charge_time docstring entry is gone"
    assert "SOURCE-AGNOSTIC" in m.group(0)
    assert "generator" in m.group(0).lower()


def test_the_field_really_is_source_agnostic_in_code():
    """If the implementation ever DID gate on solar, the corrected wording
    would itself become wrong. Pin the behaviour the wording describes."""
    import ast
    tree = ast.parse(HARVEST.read_text())
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.dump(node)
            if "first_charge_time" in body:
                fn = node
                break
    assert fn is not None, "could not find the function computing it"
    body = ast.dump(fn)
    for solar_ish in ("pv_v", "solar_w", "sun_elevation", "gen_v"):
        assert solar_ish not in body, (
            f"first_charge_time now consults {solar_ish}; it is no longer "
            f"source-agnostic and the docstring must be rewritten")
