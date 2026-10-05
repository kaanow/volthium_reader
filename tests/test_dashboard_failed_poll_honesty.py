"""A failed poll must not leave the page looking live.

The dashboard's catch block was:

    } catch (e) {
      setText("state-value", "fetch failed");
    }

One small label on the state badge. SOC, voltage, current, power, the sunrise
projection, the peaks and the event list all kept rendering their last
successful values with nothing to mark them frozen — so hours after the data
source became unreachable the page still read like live telemetry. It polls
every 5 s, so this is the normal appearance of an outage.

updateStaleBanner had the same inversion twice more: a missing timestamp and
an unparseable timestamp both HID the banner, rendering "I cannot tell how old
this is" identically to "this is current".
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DASH = REPO / "scripts/dashboard.py"


def _src() -> str:
    return DASH.read_text()


def test_the_catch_block_marks_the_whole_page_not_one_label():
    src = _src()
    m = re.search(r"\}\s*catch\s*\(e\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "the tick() catch block is gone or restructured"
    body = m.group(1)
    assert "page-stale" in body, (
        f"a failed poll no longer marks the page stale; every tile would go "
        f"on displaying frozen values as if live:\n{body}")
    assert "stale-banner" in body, "a failed poll raises no banner"


def test_the_failure_message_says_how_old_the_values_are():
    """"fetch failed" alone does not tell the reader whether the numbers are
    5 seconds or 5 hours old."""
    src = _src()
    assert "lastPollOkAt" in src, "nothing tracks the last successful poll"
    m = re.search(r"\}\s*catch\s*\(e\)\s*\{(.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "lastPollOkAt" in body and "fmtAge" in body, (
        "the failure path does not report the age of what is on screen")


def test_a_successful_poll_clears_the_stale_marking():
    """A sticky banner would be its own lie, in the other direction."""
    src = _src()
    assert re.search(r'classList\.remove\("page-stale"\)', src), (
        "nothing ever clears page-stale, so one transient failure would mark "
        "the page stale forever")
    assert re.search(r"lastPollOkAt\s*=\s*Date\.now\(\)", src), (
        "lastPollOkAt is never updated on success")


def test_the_dimming_rule_matches_elements_that_exist():
    """A dimming rule that dims nothing is the no-op this change exists to
    stop. An earlier draft listed `.harv-wrap`, which matches nothing."""
    src = _src()
    rule = re.search(r"body\.page-stale[^{]*\{[^}]*opacity[^}]*\}", src, re.S)
    assert rule, "the page-stale dimming rule is gone"
    selectors = re.findall(r"body\.page-stale\s+([.#][\w-]+)", rule.group(0))
    assert selectors, "the rule has no element selectors"
    for sel in selectors:
        if sel.startswith("#"):
            assert f'id="{sel[1:]}"' in src, (
                f"page-stale targets {sel}, which does not exist in the markup")
        else:
            assert f'class="{sel[1:]}"' in src or f'{sel[1:]}"' in src, (
                f"page-stale targets {sel}, which does not exist in the markup")


def test_missing_and_unparseable_timestamps_raise_the_banner():
    src = _src()
    m = re.search(r"function updateStaleBanner\(latestTs\)\s*\{(.*?)\n\}",
                  src, re.S)
    assert m, "updateStaleBanner is gone"
    body = m.group(1)
    # Neither early-return may hide the banner any more.
    assert "age unknown" in body, (
        "a missing timestamp still renders as fresh")
    assert "unparseable" in body, (
        "an unparseable timestamp still renders as fresh")
    hides = len(re.findall(r'banner\.style\.display\s*=\s*"none"', body))
    assert hides == 1, (
        f"expected exactly one path that hides the banner (genuinely fresh "
        f"data); found {hides} — an 'I cannot tell' branch is hiding it again")
