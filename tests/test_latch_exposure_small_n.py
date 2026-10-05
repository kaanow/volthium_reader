"""One episode cannot establish that a value is constant.

latch_exposure printed, from a single latch/unlatch pair:

    **reported `clamped_s`: 600..600 s across 1 latches, spread 0 s vs
    LATCH_CONFIRM_S=600** — a CONSTANT. It measures the confirmation
    threshold, not exposure
    **TRUE exposure: median 14.8, mean 14.8, max 14.8 minutes** (n=1)

Both halves are wrong in the same way. With n=1 the spread is 0 BY
CONSTRUCTION, so the constancy verdict fired on arithmetic rather than
evidence — it was unfalsifiable. And median/mean/max of one observation are
three copies of that observation presented as a distribution. `n=1` was
printed, but a reader scanning for the headline does not reconstruct from it
that the median of one sample is just the sample.
"""
from __future__ import annotations

import io
import contextlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import latch_exposure as le  # noqa: E402


def _render(rows, monkeypatch, unpaired=0):
    """Drive main() with a fixed set of paired episodes."""
    monkeypatch.setattr(le, "fetch_events", lambda *a, **k: object())
    monkeypatch.setattr(le, "pair", lambda ev: (rows, unpaired))
    monkeypatch.setattr(sys, "argv", ["latch_exposure.py"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        le.main()
    return buf.getvalue()


def _row(at_min, reported_s, exposure_s):
    import datetime as dt
    base = dt.datetime(2026, 8, 6, 16, 0)
    return {"at": base + dt.timedelta(minutes=at_min),
            "cleared": base + dt.timedelta(minutes=at_min + 20),
            "reported_s": reported_s, "exposure_s": exposure_s}


def test_single_episode_does_not_claim_a_constant(monkeypatch):
    out = _render([_row(0, 600, 888)], monkeypatch)
    assert "a CONSTANT" not in out, (
        f"constancy claimed from one episode, where spread is 0 by "
        f"construction:\n{out}")
    assert "NOT ENOUGH EPISODES" in out
    assert "by construction" in out


def test_single_episode_reports_the_value_not_a_distribution(monkeypatch):
    out = _render([_row(0, 600, 888)], monkeypatch)
    # Not a bare word search — the disclaimer itself says "no median, mean or
    # max is meaningful here", and an earlier version of this test failed on
    # that sentence. What must not appear is a median VALUE presented as a
    # statistic.
    import re
    assert not re.search(r"median\s+[\d.]", out), (
        f"median of a single observation was printed as a statistic:\n{out}")
    assert not re.search(r"mean\s+[\d.]", out)
    assert "SINGLE episode" in out
    assert "14.8 minutes" in out, "the actual value must still be reported"


def test_two_episodes_are_still_not_enough(monkeypatch):
    """Two identical values is weak evidence of a constant and strong
    evidence of nothing. The threshold is 3."""
    out = _render([_row(0, 600, 888), _row(60, 600, 900)], monkeypatch)
    assert "a CONSTANT" not in out
    assert "NOT ENOUGH EPISODES" in out


def test_three_identical_episodes_do_claim_a_constant(monkeypatch):
    """The fix must not have been bought by disabling the finding — the
    constancy of clamped_s is the whole point of this script."""
    out = _render([_row(0, 600, 888), _row(60, 601, 900), _row(120, 600, 950)],
                  monkeypatch)
    assert "a CONSTANT" in out, (
        f"three episodes with 1 s of jitter should still read as constant:\n{out}")
    assert "NOT ENOUGH EPISODES" not in out
    import re
    assert re.search(r"median\s+[\d.]", out), (
        "a real distribution must still be summarised")


def test_three_varying_episodes_report_variation(monkeypatch):
    out = _render([_row(0, 300, 888), _row(60, 900, 900), _row(120, 600, 950)],
                  monkeypatch)
    assert "VARIES" in out
    assert "a CONSTANT" not in out


def test_no_pairs_at_all_says_so(monkeypatch):
    out = _render([], monkeypatch)
    assert "no completed latch/unlatch pairs" in out
