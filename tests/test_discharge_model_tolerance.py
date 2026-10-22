"""One corrupt row must not take out every local analysis tool.

On 2026-10-11 the Pi rebooted and left a **1753-byte run of NUL bytes** in
data/pack.csv — buffered writes that were never flushed, ending mid-row at
`2026-10-11T07:54:38-07:00`. `discharge_model.load()` did
`datetime.fromisoformat(r["ts"])` with no guard, so from that moment
generator_advisor crashed on startup:

    File "scripts/discharge_model.py", line 69, in load
        ts=datetime.fromisoformat(r["ts"]),
    ValueError: Invalid isoformat string: '\\x00\\x00\\x00...2026-10-11T07:54:38-07:00'

It stayed broken for TEN DAYS and nothing noticed — the failure was a
traceback on a tool nobody was running, not a wrong number on a page someone
reads. The cloud record was complete throughout; only the local copy was
damaged, and only 1753 bytes of a 77 MB / 296,000-row file.

Losing a handful of samples out of 296,000 changes no model. Losing every
local tool because of them is the actual damage.

I first assumed the NUL run broke the csv module itself (`_csv.Error: line
contains NUL`) and wrote a stripping layer for it. The test below DISPROVED
that: Python 3.11's csv parses a NUL-bearing line happily and hands it on,
which is exactly why the production failure surfaced from fromisoformat. The
stripping layer was therefore unnecessary — and harmful, since removing the
NULs turns the torn row into a VALID timestamp and resurrects a row whose
other fields were destroyed. The guard that matters is at the row level.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import discharge_model as dm  # noqa: E402

HDR = "ts,state,pack_v,pack_i,pack_p,soc_a,soc_b,smoothed_i\n"


def _row(ts: datetime, i: float = -4.0) -> str:
    return (f"{ts.isoformat(timespec='seconds')},discharging,26.1,{i},"
            f"-104.4,70,68,{i}\n")


def _good_file(tmp_path: Path, n: int = 50) -> Path:
    base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    p = tmp_path / "pack.csv"
    p.write_text(HDR + "".join(_row(base + timedelta(seconds=10 * k))
                               for k in range(n)))
    return p


# --------------------------------------------------------- the real artifact

def test_the_exact_nul_corruption_from_2026_10_11(tmp_path):
    """Reproduce the production artifact: a NUL run ending mid-row, with
    healthy data on both sides of it."""
    base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    before = "".join(_row(base + timedelta(seconds=10 * k)) for k in range(20))
    after = "".join(_row(base + timedelta(seconds=10 * (k + 40)))
                    for k in range(20))
    # 1753 NULs, exactly as measured, then a valid timestamp — the torn row.
    torn = "\x00" * 1753 + "2026-10-11T07:54:38-07:00\n"
    p = tmp_path / "pack.csv"
    p.write_text(HDR + before + torn + after)

    samples = dm.load(p, quiet=True)

    assert len(samples) == 40, (
        f"expected the 40 healthy rows on either side of the damage, got "
        f"{len(samples)}")
    assert dm.LAST_LOAD.nul_lines >= 1, "the NUL line was not detected"
    assert dm.LAST_LOAD.skipped >= 1, "the torn row was not counted as skipped"
    # And the healthy data must be intact, not merely present.
    assert all(s.pack_i == -4.0 for s in samples)
    assert samples[0].ts < samples[-1].ts


def test_csv_tolerates_nuls_so_the_ts_guard_is_what_saves_us(tmp_path):
    """I wrote this test expecting `_csv.Error: line contains NUL`, and it
    DISPROVED that premise: Python 3.11's csv parses a NUL-bearing line
    happily and hands it on. That is precisely why the production failure
    surfaced as `ValueError: Invalid isoformat string` from fromisoformat.

    So the row-level timestamp guard is the fix, and a NUL-stripping layer
    would have been both unnecessary and harmful."""
    import csv as _csv
    p = tmp_path / "pack.csv"
    p.write_text(HDR + "\x00" * 100 + "\n")
    with p.open() as f:
        rows = list(_csv.DictReader(f))          # must NOT raise
    assert rows, "csv returned nothing; the premise of this test has changed"
    assert "\x00" in (rows[0].get("ts") or ""), (
        "the NULs did not reach the ts field, so this no longer reproduces "
        "the production shape")


def test_nuls_are_not_stripped_into_a_resurrected_row(tmp_path):
    """The torn row is `<NULs>2026-10-11T07:54:38-07:00`. Stripping the NULs
    makes that a VALID timestamp, which would resurrect a row whose other
    fields were destroyed. Reconstructing data that was never written is
    worse than dropping it."""
    p = tmp_path / "pack.csv"
    p.write_text(HDR + "\x00" * 1753 + "2026-10-11T07:54:38-07:00\n")
    with pytest.raises(ValueError, match="no parseable rows"):
        dm.load(p, quiet=True)
    assert dm.LAST_LOAD.nul_lines == 1, "the physical damage was not counted"
    # The torn row carries ONE field (no commas survived), so "missing fields"
    # is the correct bucket — not bad-ts. Asserting the bucket was my error;
    # the invariant is that it is skipped and counted, never parsed.
    assert dm.LAST_LOAD.skipped == 1, "the torn row was not skipped"
    assert dm.LAST_LOAD.parsed == 0, (
        "a row was parsed out of pure damage — check that NULs are not being "
        "stripped into a valid timestamp")


# ------------------------------------------------------ skips are not silent

def test_skips_are_counted_and_reported(tmp_path, capsys):
    p = _good_file(tmp_path, n=10)
    with p.open("a") as f:
        f.write("not-a-timestamp,discharging,26.1,-4.0,-104.4,70,68,-4.0\n")
    samples = dm.load(p)
    assert len(samples) == 10
    assert dm.LAST_LOAD.skipped_bad_ts == 1
    err = capsys.readouterr().err
    assert "skipped 1 unparseable row" in err, (
        f"a skipped row was swallowed silently; that moves the failure from "
        f"loud to invisible:\n{err}")


def test_a_clean_file_reports_nothing(tmp_path, capsys):
    """The warning must not fire on healthy input or it becomes noise, which
    is how an operator learns to ignore a channel."""
    p = _good_file(tmp_path, n=25)
    samples = dm.load(p)
    assert len(samples) == 25
    assert dm.LAST_LOAD.skipped == 0
    assert capsys.readouterr().err == ""


def test_stats_are_reset_between_loads(tmp_path):
    """Stale counts would make a clean file look damaged."""
    bad = tmp_path / "bad.csv"
    bad.write_text(HDR + "zzz,discharging,26.1,-4.0,-104.4,70,68,-4.0\n"
                   + _row(datetime.now().replace(hour=12, minute=0, second=0,
                                                 microsecond=0)))
    dm.load(bad, quiet=True)
    assert dm.LAST_LOAD.skipped == 1
    dm.load(_good_file(tmp_path, n=5), quiet=True)
    assert dm.LAST_LOAD.skipped == 0, "LAST_LOAD carried over a previous load"


# ------------------------------------------------- an empty result is refused

def test_a_file_with_nothing_parseable_raises(tmp_path):
    """Returning [] would let a caller fit a model on zero samples and present
    the result as an answer. That is not degraded, it is absent."""
    p = tmp_path / "pack.csv"
    p.write_text(HDR + "zzz,discharging,1,1,1,1,1,1\n" * 5)
    with pytest.raises(ValueError, match="no parseable rows"):
        dm.load(p, quiet=True)


def test_missing_required_fields_are_skipped_not_crashed(tmp_path):
    p = _good_file(tmp_path, n=5)
    with p.open("a") as f:
        f.write(",,,,,,,\n")                      # empty row
    samples = dm.load(p, quiet=True)
    assert len(samples) == 5
    assert dm.LAST_LOAD.skipped_missing == 1


# ------------------------------------------- the model itself is unchanged

def test_fit_is_unaffected_by_tolerating_the_damage(tmp_path):
    """The point is to lose the corrupt rows, not to change the model. A file
    with damage must fit identically to the same file without it."""
    base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    rows = "".join(_row(base + timedelta(seconds=10 * k), i=-4.0 - (k % 3))
                   for k in range(60))
    clean = tmp_path / "clean.csv"
    clean.write_text(HDR + rows)
    dirty = tmp_path / "dirty.csv"
    dirty.write_text(HDR + rows + "\x00" * 1753
                     + "2026-10-11T07:54:38-07:00\n")

    fit_clean = dm.fit(dm.load(clean, quiet=True))
    fit_dirty = dm.fit(dm.load(dirty, quiet=True))
    assert fit_clean == fit_dirty, (
        "tolerating the NUL run changed the fitted model; it must only drop "
        "the unparseable rows")


def test_a_nul_inside_an_otherwise_intact_row_is_not_repaired(tmp_path):
    """THE DISCRIMINATING CASE for NUL-stripping, which the torn-row test
    above cannot provide.

    A mutation that strips NULs passed every other test here, because the real
    1753-byte artifact loses its commas too — so the row is dropped for
    missing fields whether or not NULs are removed, and nothing distinguishes
    the two behaviours.

    This row keeps every comma and hides a NUL INSIDE the timestamp. Strip it
    and the timestamp becomes valid, so a complete, plausible sample is
    reconstructed out of corrupted bytes and fed to the model as if the logger
    had written it. Leave it and the row is skipped, which is the truth.
    """
    p = tmp_path / "pack.csv"
    p.write_text(HDR + "2026-10-11T07:5\x004:38-07:00,discharging,26.1,-4.0,"
                       "-104.4,70,68,-4.0\n")
    assert dm.LAST_LOAD is not None
    with pytest.raises(ValueError, match="no parseable rows"):
        dm.load(p, quiet=True)
    assert dm.LAST_LOAD.nul_lines == 1
    assert dm.LAST_LOAD.skipped_bad_ts == 1, (
        "the NUL was stripped and the timestamp silently repaired — a sample "
        "invented from damaged bytes")
    assert dm.LAST_LOAD.parsed == 0
