"""The latch detector must not act on a remembered reading.

pv_v and mppt_out_v are plain attributes, updated when an MPPT frame arrives.
When the MPPT stops talking they KEEP THEIR LAST VALUES, and both consumers
ran regardless:

  * _record_trail appended the frozen pair once a second, manufacturing a
    1 Hz "trail" indistinguishable from live data — the forensic record used
    to reconstruct a latch afterwards would be entirely fiction.
  * _check_latch kept evaluating them, so a node that went silent while the
    array happened to sit in the clamp band would hold clamped=True for the
    rest of the afternoon.

This is not merely a wrong number on a page. The latch guard ACTS on it,
writing Operating Mode -> Standby -> Operating. Bouncing the MPPT on hours-old
readings is a physical action taken on fiction.

MPPT_STALE_S is ~15x the measured cadence: PGN 127166 arrives every 1.00 s
with a maximum observed inter-arrival of 1.00 s across 2423 captured frames.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import xanbus_telemetry as xt  # noqa: E402


def _clamped_decoder(t: float) -> xt.Decoder:
    """A decoder whose inputs sit squarely in the clamp band at time t."""
    dec = xt.Decoder()
    dec.pv_v = xt.LATCH_DAYLIGHT_V + 5.0
    dec.mppt_out_v = dec.pv_v - (
        (xt.LATCH_DELTA_MIN_V + xt.LATCH_DELTA_MAX_V) / 2.0)
    dec.mppt_out_w = 10.0
    dec.mppt_status = 0
    dec.pv_sample_at = t
    dec.mppt_sample_at = t
    return dec


def test_freshness_predicate_boundaries():
    t = 10_000.0
    dec = _clamped_decoder(t)
    assert dec._latch_inputs_fresh(t) is True
    assert dec._latch_inputs_fresh(t + xt.MPPT_STALE_S) is True
    assert dec._latch_inputs_fresh(t + xt.MPPT_STALE_S + 0.01) is False


def test_missing_stamp_is_not_fresh():
    """A value with no arrival time must not be trusted — that is the state
    the attributes were in before this change."""
    t = 10_000.0
    dec = _clamped_decoder(t)
    dec.pv_sample_at = None
    assert dec._latch_inputs_fresh(t) is False


def test_trail_is_not_fabricated_from_a_frozen_reading():
    t = 10_000.0
    dec = _clamped_decoder(t)
    # Fresh: the trail grows.
    for k in range(5):
        dec._record_trail(t + k * 1.1)
    grew = len(dec.trail)
    assert grew >= 4, f"the live path stopped recording ({grew} samples)"

    # Now the MPPT goes silent. Wall clock advances; nothing new arrives.
    before = len(dec.trail)
    for k in range(60):
        dec._record_trail(t + xt.MPPT_STALE_S + 10 + k * 1.1)
    assert len(dec.trail) == before, (
        f"{len(dec.trail) - before} fabricated samples were appended from a "
        f"frozen reading — this is the forensic record for a latch")


def test_latch_is_not_declared_from_a_stale_reading(monkeypatch):
    """The dangerous one: the guard writes to the device on this verdict."""
    monkeypatch.setattr(xt, "sun_elevation_deg",
                        lambda now: xt.MIN_SUN_ELEVATION_DEG + 10)
    t = 10_000.0
    dec = _clamped_decoder(t)

    # Confirm the fixture really is in the clamp band while fresh, by running
    # the detector long enough to clear its confirmation window.
    fresh_events = []
    for k in range(0, int(xt.LATCH_CONFIRM_S) + 60, 5):
        now = t + k
        # A LIVE MPPT re-stamps every second. Without this the "fresh" arm
        # goes stale after MPPT_STALE_S too and the comparison is vacuous —
        # which is exactly how it failed on the first run.
        dec.pv_sample_at = now
        dec.mppt_sample_at = now
        fresh_events += dec._check_latch(now)
    assert fresh_events, (
        "the fixture never triggers a latch even when fresh — the stale test "
        "below would then prove nothing")

    # Same readings, same clamp band, but now unmistakably stale.
    dec2 = _clamped_decoder(t)
    stale_events = []
    base = t + xt.MPPT_STALE_S + 60
    for k in range(0, int(xt.LATCH_CONFIRM_S) + 600, 5):
        stale_events += dec2._check_latch(base + k)
    assert stale_events == [], (
        f"a latch was declared from readings over {xt.MPPT_STALE_S}s old: "
        f"{stale_events[:2]}")


def test_arrival_stamps_are_set_by_the_decoder_not_only_by_tests():
    """If _mppt_data stopped stamping, every latch input would read as stale
    and the detector would silently never fire again — a quiet regression in
    the opposite direction. Assert the stamping is wired structurally."""
    import ast
    tree = ast.parse((REPO / "scripts/xanbus_telemetry.py").read_text())
    # The latch inputs are decoded in _dc_src_sts2 (PGN 127173, by `assoc`),
    # NOT in _mppt_data — I asserted the wrong function first and the test
    # correctly failed.
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_dc_src_sts2")
    assigned = {
        t.attr for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Attribute)
    }
    assert "pv_sample_at" in assigned, "_dc_src_sts2 no longer stamps pv_v"
    assert "mppt_sample_at" in assigned, (
        "_dc_src_sts2 no longer stamps mppt_out_v")
    # And the pairing must hold: a value updated without its stamp is the
    # original bug in a new place.
    assert {"pv_v", "mppt_out_v"} <= assigned


def test_the_dc_v_guard_no_longer_claims_the_latch_uses_dc_v():
    """The guard's comment justified itself with "dc_v is the reference the
    latch detector differences against". _check_latch differences
    pv_v - mppt_out_v; dc_v appears nowhere in it. A false rationale is worse
    than none, because it also implied pv_v/mppt_out_v were covered."""
    import ast
    src = (REPO / "scripts/xanbus_telemetry.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_check_latch")
    body = ast.dump(fn)
    assert "dc_v" not in body, (
        "_check_latch now references dc_v — if that is deliberate, the "
        "corrected comment needs revisiting")
    # NOT a string search for the old sentence: the correction deliberately
    # QUOTES the false claim so the record of it survives, and an earlier
    # version of this test failed on the corrective comment itself. The
    # durable invariant is structural — _check_latch differences pv_v against
    # mppt_out_v and touches dc_v nowhere.
    diffed = {n.left.attr for n in ast.walk(fn)
              if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub)
              and isinstance(n.left, ast.Attribute)}
    assert "pv_v" in diffed, (
        f"_check_latch no longer differences pv_v; it differences {diffed}")


def test_mppt_stale_s_stays_tied_to_the_measured_cadence():
    """M5 of the mutation pass widened MPPT_STALE_S to 3600 and EVERY test
    still passed, because the others express their bounds relative to the
    constant. A guard whose threshold can be loosened to an hour without a
    single failure is not a guard.

    The bound is derived, not magic: PGN 127166 arrives every 1.00 s with a
    maximum observed inter-arrival of 1.00 s over 2423 captured frames, and
    PGN 127173 every 0.49 s. Anything above ~10x that cadence stops being
    "this reading is current" and starts being "this reading is remembered".
    It must also stay well inside DROPOUT_S — there is no reason to keep
    trusting a value for the full minute it takes to declare a node gone.
    """
    observed_max_interarrival_s = 1.00
    assert xt.MPPT_STALE_S >= 5 * observed_max_interarrival_s, (
        f"MPPT_STALE_S={xt.MPPT_STALE_S} is too tight — normal bus jitter "
        f"would trip it and the latch detector would go permanently blind")
    assert xt.MPPT_STALE_S <= 30 * observed_max_interarrival_s, (
        f"MPPT_STALE_S={xt.MPPT_STALE_S} is far above the "
        f"{observed_max_interarrival_s}s measured cadence; at that age a "
        f"reading is "
        f"remembered, not current, and the latch guard WRITES to the device "
        f"on it")
    assert xt.MPPT_STALE_S < xt.DROPOUT_S, (
        f"MPPT_STALE_S={xt.MPPT_STALE_S} is not tighter than "
        f"DROPOUT_S={xt.DROPOUT_S}: the latch path would still be trusting "
        f"values from a node already considered dropped")
