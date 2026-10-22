"""Is the primary spool WHOLE, not merely fresh?

Two silent failures in one month, neither noticed by anything:

  2026-10-04  A `git checkout -- data/` on the Pi restored the COMMITTED
              data/pack.csv over the live one. The committed copy is a June
              truncation (47e60c7 cut 16,715 rows to 2,330), so three months
              of local history vanished and the file came back 0644
              kaan:users, crash-looping the logger for 70 minutes.
  2026-10-11  Two unclean reboots left a 1753-byte run of NUL bytes mid-file.
              Every tool that parsed the CSV row-by-row crashed for ten days.

Both are invisible to a freshness check, which is all this tool had. The
logger keeps appending, so the LAST row stays current while the middle of the
file is a hole or a block of zeros. "Fresh" and "whole" are different
questions and only one was being asked.

The per-day histogram is what makes the 2026-10-04 case legible: the dates
jump straight from 2026-06-30 to 2026-10-04, which no amount of looking at the
tail would reveal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from status_check import (  # noqa: E402
    PACK_ROWS_PER_DAY,
    PACK_THIN_DAY_FRACTION,
    _check_pack_integrity,
)

FULL = PACK_ROWS_PER_DAY


def _probe(nuls: int, days: list[tuple[str, int]]) -> str:
    return "\n".join([f"NULS {nuls}"]
                     + [f"DAY {d} {n}" for d, n in days])


def _healthy(n_days: int = 6) -> list[tuple[str, int]]:
    return [(f"2026-10-{5 + k:02d}", FULL) for k in range(n_days)]


# ------------------------------------------------------- the real production state

def test_the_two_real_failures_are_both_reported():
    """The exact shape measured on the Pi 2026-10-21."""
    days = [("2026-06-29", 57), ("2026-06-30", 2272), ("2026-10-04", 1836)]
    days += [(f"2026-10-{d:02d}", FULL) for d in range(5, 21)]
    notable, lines = _check_pack_integrity(_probe(1753, days))
    body = "\n".join(lines)
    assert notable
    assert "1753 NUL byte(s)" in body, "the physical damage was not reported"
    assert "95 day(s) MISSING" in body, (
        f"the 95-day hole between 2026-06-30 and 2026-10-04 was not "
        f"reported:\n{body}")
    assert "2026-06-30" in body and "2026-10-04" in body


def test_a_whole_spool_is_quiet():
    notable, lines = _check_pack_integrity(_probe(0, _healthy()))
    assert not notable, f"a healthy spool was flagged: {lines}"
    assert "spool is whole" in "\n".join(lines)


# ------------------------------------------------------------- each signal alone

def test_nul_bytes_alone_are_notable():
    notable, lines = _check_pack_integrity(_probe(1, _healthy()))
    assert notable
    assert "NUL byte(s)" in "\n".join(lines)


def test_a_missing_day_is_notable():
    days = [("2026-10-05", FULL), ("2026-10-07", FULL)]
    notable, lines = _check_pack_integrity(_probe(0, days))
    assert notable
    assert "1 day(s) MISSING" in "\n".join(lines)


def test_a_thin_middle_day_is_notable():
    days = [("2026-10-05", FULL), ("2026-10-06", 100), ("2026-10-07", FULL)]
    notable, lines = _check_pack_integrity(_probe(0, days))
    assert notable
    assert "only 100 rows" in "\n".join(lines)


def test_the_first_and_last_days_may_be_partial():
    """The record starts mid-day and today is in progress. Flagging those
    would make the check fire every single run, which is how an operator
    learns to ignore it."""
    days = [("2026-10-05", 120), ("2026-10-06", FULL), ("2026-10-07", 90)]
    notable, lines = _check_pack_integrity(_probe(0, days))
    assert not notable, (
        f"a partial first/last day was treated as damage: {lines}")


def test_a_brief_outage_does_not_trip_the_thin_day_check():
    """The 70-minute outage of 2026-10-04 cost ~840 rows. A check that fires
    on one bad hour is noise; this must only catch hours-to-days losses."""
    lost = int(70 * 60 / 5)
    days = [("2026-10-05", FULL), ("2026-10-06", FULL - lost),
            ("2026-10-07", FULL)]
    notable, lines = _check_pack_integrity(_probe(0, days))
    assert not notable, (
        f"a 70-minute outage ({lost} rows) tripped the thin-day check: {lines}")
    # ...but losing most of a day must still trip it.
    days[1] = ("2026-10-06", int(FULL * PACK_THIN_DAY_FRACTION) - 1)
    notable, _ = _check_pack_integrity(_probe(0, days))
    assert notable


# --------------------------------------------------- uniq -c splits a day in two

def test_duplicate_date_runs_are_aggregated():
    """`uniq -c` collapses only ADJACENT runs, and the NUL block split
    2026-10-11 into two of them on the real Pi (5696 rows, then 1033).
    Unaggregated, the thin-day check fires twice for one day and the gap
    arithmetic sees a zero-length step between the halves. I misread the raw
    histogram that way and briefly concluded the day had lost 15 hours."""
    # Chosen so the two behaviours DISAGREE on the verdict: each run is below
    # the thin threshold on its own, but together they clear it. A first draft
    # used runs that summed to a full day, where last-wins and summing both
    # happen to pass — so a mutation replacing `+= n` with `= n` survived
    # every test.
    half = int(FULL * PACK_THIN_DAY_FRACTION)
    a, b = half - 2000, 2500            # a < threshold, a + b > threshold
    assert a < half and b < half and a + b > half
    days = [("2026-10-10", FULL),
            ("2026-10-11", a), ("2026-10-11", b),
            ("2026-10-12", FULL)]
    notable, lines = _check_pack_integrity(_probe(0, days))
    body = "\n".join(lines)
    assert body.count("2026-10-11") <= 1, (
        f"one day was reported twice because the runs were not merged:\n{body}")
    assert not notable, (
        f"the two runs summed to a full day but were flagged anyway:\n{body}")


# ----------------------------------------------------------- cannot-look cases

def test_an_empty_probe_is_unverified_not_clean():
    """'I could not look' must never render as 'everything is fine' — the
    recurring failure mode throughout this tool."""
    notable, lines = _check_pack_integrity("")
    assert notable
    assert "UNVERIFIED" in "\n".join(lines)


def test_missing_nul_count_is_unverified():
    notable, lines = _check_pack_integrity("DAY 2026-10-05 17280")
    assert notable
    assert "UNVERIFIED" in "\n".join(lines)


def test_garbage_is_unverified():
    notable, lines = _check_pack_integrity("hello\nworld\n")
    assert notable
    assert "UNVERIFIED" in "\n".join(lines)


def test_unparseable_dates_do_not_crash_the_gap_math():
    notable, lines = _check_pack_integrity(
        "NULS 0\nDAY not-a-date 17280\nDAY 2026-10-05 17280")
    assert isinstance(notable, bool)
    assert lines
