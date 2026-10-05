"""Who is on the bus, and noticing when one of ours is not.

Two defects, both found 2026-10-04 by measuring the live bus rather than
reading the code's assumptions:

1. `node_dropout` could NEVER fire for a node that was already silent when the
   process started. `last_seen` begins empty, so `seen is not None` was False
   and the check skipped that node forever. The reader restarts routinely —
   there is a volthium-weekly-reboot timer — so an MPPT that died overnight
   came back from the reboot INVISIBLE rather than reported.

2. `_chg_sts` labelled its node `"mppt" if src == SRC_MPPT else "sw"`, so
   every other address on the bus would be written into the SW inverter's
   series. Measured over 40,000 live frames there really is a third node:

       src=0   25653 frames   SW inverter
       src=1   14011 frames   MPPT 60
       src=2     336 frames   not ours (PGN 60928 Address Claim + 129033
                              Local Time Offset — the Insight Home gateway)

   Node 2 does not currently emit PGN_CHG_STS, so nothing was mislabelled in
   practice. This is a latent fault, and the tests below say so rather than
   overclaiming. Every OTHER decoder already had a strict `src != SRC_X`
   guard; _chg_sts was the single permissive one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import xanbus_telemetry as xt  # noqa: E402


# ------------------------------------------------------------ node identity

def test_node_name_refuses_to_guess():
    assert xt.node_name(xt.SRC_SW) == "sw"
    assert xt.node_name(xt.SRC_MPPT) == "mppt"
    # The measured third node, and anything else, must come back None so a
    # caller has to decide instead of inheriting the "sw" fallback.
    assert xt.node_name(2) is None
    assert xt.node_name(99) is None


def test_chg_sts_rejects_a_foreign_node_instead_of_calling_it_sw():
    dec = xt.Decoder()
    # A plausible CHG_STS payload: target_v, target_i (i32 LE) then mode.
    import struct
    payload = (b"\x00\x00" + struct.pack("<ii", 29200, 9000)
               + b"\x00\x00\x00\x00" + struct.pack("<H", 1) + b"\x00\x00")
    assert len(payload) >= 15

    out_sw = dec._chg_sts(xt.SRC_SW, payload, 1000.0)
    nodes = {e["data"].get("node") for e in out_sw if "data" in e}
    assert nodes <= {"sw"}, f"SW frame produced {nodes}"

    before = dec.foreign_frames
    out_foreign = dec._chg_sts(2, payload, 1001.0)
    assert out_foreign == [], "a foreign node's charger status was accepted"
    assert dec.foreign_frames == before + 1, (
        "the foreign frame was dropped silently — it must be counted")


def test_every_decoder_constrains_its_source():
    """Structural: no decoder may take src and ignore it. _chg_sts was the
    only one that did, and it took measuring the bus to notice."""
    import ast
    tree = ast.parse((REPO / "scripts/xanbus_telemetry.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = [a.arg for a in node.args.args]
        if "src" not in args or node.name in ("feed", "node_name"):
            continue
        body = ast.dump(node)
        # Either compared against a SRC_ constant, or routed through node_name.
        constrained = ("SRC_SW" in body or "SRC_MPPT" in body
                       or "node_name" in body)
        if not constrained:
            offenders.append(f"{node.name}:{node.lineno}")
    assert not offenders, (
        f"these take a source address and never constrain it, so frames from "
        f"any node on the bus land in our series: {offenders}")


# ------------------------------------------------------------ node dropout

def test_dropout_fires_for_a_node_silent_since_startup():
    """THE REGRESSION. Nothing is ever fed, so last_seen stays empty."""
    dec = xt.Decoder()
    t0 = 5000.0
    assert dec.housekeeping(t0) == [] or True   # first call just anchors time
    events = []
    for k in range(1, 8):
        events += [e for e in dec.housekeeping(t0 + k * 20.0)
                   if e.get("event") == "node_dropout"]
    names = {e["data"]["node"] for e in events}
    assert names == {"sw", "mppt"}, (
        f"a node absent since startup was never reported dropped; got {names}")
    for e in events:
        assert e["data"]["never_seen"] is True
        # Must be a duration measured from startup, not an epoch timestamp.
        assert 0 < e["data"]["silent_s"] < 1000, (
            f"silent_s={e['data']['silent_s']} looks like a timestamp, "
            f"not a duration")


def test_dropout_does_not_fire_before_the_threshold():
    dec = xt.Decoder()
    t0 = 5000.0
    dec.housekeeping(t0)
    out = dec.housekeeping(t0 + xt.DROPOUT_S - 5)
    assert [e for e in out if e.get("event") == "node_dropout"] == []


def test_a_live_node_is_not_reported_dropped(monkeypatch):
    """The fix must not have been bought by firing for healthy nodes."""
    dec = xt.Decoder()
    t0 = 5000.0
    dec.housekeeping(t0)
    # Keep SW alive, let MPPT stay absent.
    for k in range(1, 8):
        t = t0 + k * 20.0
        dec.last_seen[xt.SRC_SW] = t
        out = [e for e in dec.housekeeping(t)
               if e.get("event") == "node_dropout"]
        for e in out:
            assert e["data"]["node"] != "sw", "a live node was reported dropped"
    assert xt.SRC_MPPT in dec.dropped


def test_dropout_fires_once_not_every_tick():
    dec = xt.Decoder()
    t0 = 5000.0
    dec.housekeeping(t0)
    n = 0
    for k in range(1, 30):
        n += len([e for e in dec.housekeeping(t0 + k * 20.0)
                  if e.get("event") == "node_dropout"])
    assert n == 2, f"expected one dropout per node, got {n} events"


# --------------------------------------------- foreign frames must not page

def test_foreign_frames_are_reported_but_never_notable():
    """A node persistently emitting a PGN we decode would otherwise page every
    30 minutes forever. Noise is how an operator learns to ignore the channel,
    which is the failure this reader already had once today."""
    dec = xt.Decoder()
    dec.foreign_frames = 7
    dec.last_reject_report = 0.0
    out = dec.reject_report(10_000.0)
    assert out, "a moved counter produced no report at all"
    data = out[0]["data"]
    assert data["foreign_frames"] == 7, "the counter was not surfaced"
    assert data["notable"] is False, (
        "foreign frames paged the operator; they are informational, not "
        "corruption")


def test_a_corrupt_counter_is_still_notable():
    dec = xt.Decoder()
    dec.bad_dc_w = 3
    dec.last_reject_report = 0.0
    out = dec.reject_report(10_000.0)
    assert out and out[0]["data"]["notable"] is True, (
        "a corrupt-frame counter must still page — expected rate is zero")
