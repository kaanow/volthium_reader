"""The battery row must not mix an instantaneous current with a smoothed power.

drawSystem renders the Battery row as V from pack_v, A from pack_i, W from
battW(). battW() returned smoothed_p — an EMA — so the row put an
instantaneous current beside a smoothed power. Measured over 5000 daytime
readings from production on 2026-10-04, they disagreed in SIGN 74 times
(1.48%):

    16:12:45Z   pack_i = -4.10 A   but   smoothed_p = +860.8 W
    16:12:50Z   pack_i = -4.10 A   but   smoothed_p = +715.4 W
    15:50:40Z   pack_i = +14.80 A  but   smoothed_p = -57.5 W

A row stating the battery discharged at 4 A while charging at 861 W, during
the generator shutdown.

The same EMA broke the fridge display in a less visible way. dcLoadW() tests
`battW() <= p.split_w`, and split_w is computed server-side from pack_p in
db.dc_load_profile. The client comment asserted "split_w and battW() are both
pack_p, so they compare directly" — false, and the entire correctness argument
for preferring the Otsu split depends on it: comparing pack_p against ITSELF is
what makes the split immune to the ~33 W offset between the two DC meters.

pack_p equals pack_v * pack_i to 0.000% across 4801 production samples, so it
is the exact consistent partner, and both columns are null-free over the same
window.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "cloud/server/static/v2.html"


def _code_only(src: str) -> str:
    """Comments in this file quote the defect they describe, so every
    assertion below must run on code only. Bare string searches have produced
    false passes in this repo more than once."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


def test_battw_returns_pack_p_not_the_ema():
    code = _code_only(PAGE.read_text())
    m = re.search(r"function\s+battW\s*\(\s*\)\s*\{(.*?)\}", code, re.S)
    assert m, "battW() is gone or was restructured"
    body = m.group(1)
    assert "pack_p" in body, f"battW() no longer reads pack_p: {body.strip()}"
    assert "smoothed_p" not in body, (
        f"battW() is back on the smoothed EMA, which contradicts pack_i in "
        f"the same row and breaks the pack_p-vs-pack_p fridge split: "
        f"{body.strip()}")


def test_the_battery_row_uses_one_consistent_basis():
    """V, A and W in one row must all be instantaneous."""
    code = _code_only(PAGE.read_text())
    m = re.search(r"const\s+battA\s*=.*?;", code, re.S)
    assert m, "the battery row assignment is gone"
    line = m.group(0)
    assert "pack_i" in line and "pack_v" in line
    assert "battW()" in line, "the row no longer sources W from battW()"
    # And battW() is pack_p, asserted above — so all three are instantaneous.


def test_split_w_is_still_derived_from_pack_p_server_side():
    """If the server moved split_w onto another column, the client would be
    comparing two bases again — from the other end. This is the pairing the
    fridge display's correctness argument rests on."""
    db = (REPO / "cloud/server/db.py").read_text()
    m = re.search(r"async def dc_load_profile.*?(?=\n    async def |\n    def )",
                  db, re.S)
    assert m, "dc_load_profile is gone or was renamed"
    body = m.group(0)
    assert "pack_p" in body, (
        "dc_load_profile no longer reads pack_p, so split_w and battW() are "
        "on different bases again")
    assert "smoothed_p" not in body, (
        "dc_load_profile switched to the EMA; battW() is pack_p, so the "
        "fridge split would be comparing two different signals")


def test_dc_load_compares_battw_against_split_w():
    code = _code_only(PAGE.read_text())
    assert re.search(r"battW\(\)\s*<=\s*p\.split_w", code), (
        "the fridge on/off test no longer compares battW() to split_w — if "
        "that is deliberate, the basis argument needs rewriting")
