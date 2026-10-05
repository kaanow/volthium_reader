"""The detector for the permission drift that cost 70 minutes of telemetry.

On 2026-10-04 an ad-hoc SSH command as `kaan` recreated data/pack.csv as
kaan:users 0644. The services run as `claude`, so the primary RS485 logger
lost append permission and crash-looped 593 times, leaving pack.csv frozen
between 03:16:39Z and 04:26:59Z.

Prevention now exists in three places (UMask=0002 on the units, umask 0002 in
the operator's shell, setgid on data/). This tests the DETECTOR, because every
other invariant in status_check.py that was merely "prevented" decayed and
then reported green for months.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from status_check import _check_data_perms  # noqa: E402


def test_the_exact_file_state_that_caused_the_outage_is_flagged():
    notable, lines = _check_data_perms(
        "kaan users 644 /srv/volthium_reader/data/pack.csv\n"
        "claude users 664 /srv/volthium_reader/data/weather.csv\n")
    assert notable, "the 0644 pack.csv that crash-looped the logger was not flagged"
    body = "\n".join(lines)
    assert "pack.csv" in body and "644" in body
    assert "weather.csv" not in body, "a healthy 0664 file should not be listed"
    assert "chmod g+w" in body, "must say how to fix it"


def test_all_group_writable_is_quiet_and_says_so():
    notable, lines = _check_data_perms(
        "claude users 664 /srv/volthium_reader/data/pack.csv\n"
        "kaan users 664 /srv/volthium_reader/data/weather.csv\n"
        "claude users 666 /srv/volthium_reader/data/x.jsonl\n")
    assert not notable
    body = "\n".join(lines)
    assert "all 3 data file(s) group-writable" in body


def test_root_owned_is_reported_but_does_not_page():
    """The xanbus and latch-guard services run as root and own their state by
    design. Flagging those as failures would make the check cry wolf, and
    chmod g+w does not help when the group is root anyway."""
    notable, lines = _check_data_perms(
        "root root 644 /srv/volthium_reader/data/latch_guard_state.json\n"
        "claude users 664 /srv/volthium_reader/data/pack.csv\n")
    assert not notable, "root-owned service state must not page"
    body = "\n".join(lines)
    assert "root-owned" in body and "latch_guard_state.json" in body


def test_a_root_owned_file_does_not_mask_a_real_offender():
    notable, lines = _check_data_perms(
        "root root 644 /srv/volthium_reader/data/latch_guard_state.json\n"
        "kaan users 644 /srv/volthium_reader/data/pack.csv\n")
    assert notable, "a genuinely unwritable file was swallowed by the root branch"
    assert "pack.csv" in "\n".join(lines)


def test_empty_output_is_unverified_not_clean():
    """'I could not look' must never render as 'everything is fine' — the
    recurring failure mode throughout this tool."""
    notable, lines = _check_data_perms("")
    assert notable
    assert "UNVERIFIED" in "\n".join(lines)


def test_setgid_four_digit_mode_is_parsed_from_the_right_end():
    """A setgid directory stats as 2775. Reading the mode from the left would
    treat the leading 2 as the group digit and silently invert the verdict."""
    notable, lines = _check_data_perms(
        "kaan users 2775 /srv/volthium_reader/data/subdir\n")
    assert not notable, f"2775 is group-writable (775) but was flagged: {lines}"

    notable, lines = _check_data_perms(
        "kaan users 2745 /srv/volthium_reader/data/subdir\n")
    assert notable, "2745 has no group-write bit and must be flagged"


def test_malformed_lines_are_skipped_not_counted_as_healthy():
    notable, lines = _check_data_perms(
        "garbage\n"
        "kaan users notanumber /srv/volthium_reader/data/x.csv\n")
    assert notable, "nothing parseable must read as UNVERIFIED, not clean"
    assert "UNVERIFIED" in "\n".join(lines)
