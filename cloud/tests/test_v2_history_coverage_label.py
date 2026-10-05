"""The coverage caption must not report the query window as the coverage.

/v2/history read:

    const cov = (energy.days || []).length;
    $("cov").textContent = `${cov} days of solar telemetry so far`;

`energy` comes from /api/solar/energy?days=30, so `cov` is bounded by the
WINDOW. Measured against production on 2026-10-04:

    days=7    ->  8 rows
    days=30   -> 31 rows   <- what the page displayed
    days=120  -> 67 rows
    days=365  -> 67 rows   <- the archive's actual extent, 2026-07-30 onward

So the page said "31 days of solar telemetry so far" about a 67-day archive,
understating it by more than half, and would have said 31 forever however much
history accumulated. The phrase "so far" is what makes it a false claim rather
than a terse one.

Fixing it by widening the query would have been worse: a lifetime scan on
/api/solar/energy is already the thing projected to cross the 10 s statement
timeout. So the caption states the window it actually asked for.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "cloud/server/static/v2-history.html"


def _src() -> str:
    return PAGE.read_text()


def _code_only(src: str) -> str:
    """Strip /* ... */ and // comments. Assertions in this repo have repeatedly
    matched their own explanatory comments; the corrected caption's comment
    quotes the old false string, so a bare search would pass on the comment."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return src


def test_the_false_coverage_claim_is_gone_from_the_code():
    code = _code_only(_src())
    assert "days of solar telemetry so far" not in code, (
        "the caption again reports the query window as total coverage")
    assert "so far" not in code, (
        "'so far' implies total archive extent, which this page cannot know")


def test_the_caption_names_the_window_it_requested():
    code = _code_only(_src())
    assert "days shown" in code, "the caption no longer says what it counts"
    assert "days requested" in code, (
        "the caption must disclose the window, or the reader cannot tell a "
        "capped count from a complete one")


def test_window_is_a_single_constant_used_by_both_query_and_caption():
    """The two drifted apart precisely because the caption derived from a
    row count and the query from a literal. One constant, both uses."""
    code = _code_only(_src())
    assert re.search(r"const\s+LEDGER_DAYS\s*=\s*\d+", code), (
        "LEDGER_DAYS is gone — the window is a bare literal again")
    # The query must interpolate it, not hardcode a number.
    assert re.search(r"/api/solar/energy\?days=\$\{LEDGER_DAYS\}", code), (
        "the energy query no longer uses LEDGER_DAYS")
    assert not re.search(r"/api/solar/energy\?days=\d", code), (
        "a hardcoded days= literal is back in the energy query")
    # And the caption must reference it too.
    caption = re.search(r'\$\("cov"\)\.textContent[^;]+;', code, re.S)
    assert caption, "could not find the coverage caption assignment"
    assert "LEDGER_DAYS" in caption.group(0), (
        "the caption does not reference LEDGER_DAYS, so changing the window "
        "would leave it lying again")


def test_the_page_is_actually_the_one_served_at_v2_history():
    """Earlier in this session a fix was shipped to v2-history.html when
    /history serves history.html. Pin the route to the file so this test is
    about the page a reader sees."""
    main = (REPO / "cloud/server/main.py").read_text()
    route = re.search(r'@app\.get\("/v2/history"\).*?FileResponse\('
                      r'STATIC_DIR / "([^"]+)"\)', main, re.S)
    assert route, "the /v2/history route is gone or restructured"
    assert route.group(1) == PAGE.name, (
        f"/v2/history serves {route.group(1)}, not {PAGE.name} — this test is "
        f"asserting against a page nobody loads")
