"""The generator tile must not depend on row order, and should prefer a
measurement over a transition notice.

The Xanbus event stream FLAPS at both ends of a run. The 2026-10-04 shutdown
emitted gen_start AND gen_stop in the SAME SECOND (16:12:36). The dashboard
asked for them with:

    /api/xanbus_events?limit=1&event=gen_start,gen_stop

and the server ordered only `ts DESC`. With two rows sharing a timestamp,
which one comes back is unspecified — so the same shutdown could render as
"running" or "stopped" across refreshes with no change in the underlying data.

Two fixes, because they address different things:

  * `ORDER BY ts DESC, id DESC` makes the answer STABLE and, since id is
    BIGSERIAL, orders a same-second pair by true arrival — the reader's
    emission order, which is the sequence that actually occurred.
  * The tile now prefers the row's own gen_v (the generator's AC voltage,
    against the same 50 V floor the reader uses) over the event. Stable is
    not the same as correct, and a measurement of the thing being asked
    about beats a transition notice about it. Guarded on the same 900 s
    freshness threshold used elsewhere for solar rows.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "cloud/server/db.py"
PAGE = REPO / "cloud/server/static/v2.html"


def _code_only(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


def test_xanbus_events_ordering_is_deterministic():
    src = DB.read_text()
    m = re.search(r"FROM xanbus_events.*?ORDER BY ([^\n]*?)LIMIT", src, re.S)
    assert m, "the xanbus_events query is gone or was restructured"
    order = m.group(1)
    assert "id DESC" in order, (
        f"ORDER BY is `{order.strip()}` — with no tie-break, a same-second "
        f"gen_start/gen_stop pair resolves arbitrarily and the generator tile "
        f"flips between refreshes")


def test_the_tiebreak_column_is_actually_a_monotonic_key():
    """id DESC is only a meaningful arrival order if id is a serial. If the
    column were, say, a random uuid, the ordering would be stable but
    meaningless."""
    sql = (REPO / "cloud/server/migrations/0003_solar.sql").read_text()
    m = re.search(r"CREATE TABLE IF NOT EXISTS xanbus_events\s*\((.*?)\);",
                  sql, re.S)
    assert m, "the xanbus_events table definition is gone"
    assert re.search(r"id\s+BIGSERIAL", m.group(1), re.I), (
        "xanbus_events.id is no longer a BIGSERIAL, so ORDER BY id DESC no "
        "longer means arrival order")


def test_the_tile_prefers_the_measured_gen_voltage():
    code = _code_only(PAGE.read_text())
    m = re.search(r"st\.gen\s*=\s*(.*?);", code, re.S)
    assert m, "st.gen is no longer assigned"
    expr = m.group(1)
    assert "gen_v" in expr, (
        f"the generator tile still derives state purely from the ambiguous "
        f"event pair rather than the row's measured AC voltage: {expr}")
    assert "50" in expr, (
        "the 50 V floor the reader uses to call AC2 live is not applied")


def test_the_measurement_is_freshness_guarded():
    """A stale row's gen_v is a remembered value. Trusting it is the same
    defect as the latch detector acting on frozen MPPT readings."""
    code = _code_only(PAGE.read_text())
    assert "genRowFresh" in code, "the gen measurement has no freshness gate"
    m = re.search(r"genRowFresh\s*=\s*([^;]*);", code)
    assert m, "genRowFresh is not computed"
    assert "900" in m.group(1), (
        f"the freshness window is not the 900 s used elsewhere for solar "
        f"rows: {m.group(1)}")


def test_the_event_remains_the_fallback():
    """Pre-schema-3 rows have null gen_v; dropping the event path entirely
    would make the tile permanently blank for them."""
    code = _code_only(PAGE.read_text())
    m = re.search(r"st\.gen\s*=\s*(.*?);", code, re.S)
    expr = m.group(1)
    assert "gen_start" in expr, (
        f"the declared-state fallback is gone, so a row with null gen_v has "
        f"no answer at all: {expr}")
    assert "gen_v != null" in expr or "gen_v !== null" in expr, (
        f"nothing distinguishes 'no measurement' from 'measured zero': {expr}")
