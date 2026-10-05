"""A day with no telemetry must not archive as the best possible day.

end_of_day_report writes a durable Markdown file to data/reports/. It is the
artifact someone reads weeks later to reconstruct what happened while nobody
was at the cabin. Its gap section had two branches on one ambiguous value:

    try:    events = health.today_pack_gap_events(...)
    except: events = []
    if not events: "**Clean day** — ... held a continuous BLE link ..."

today_pack_gap_events documents itself as returning [] "when no gaps, missing
file, or no samples for `day`". With the bare except that is four distinct
conditions, and all four rendered as **Clean day**. Reproduced on 2026-10-04:
this laptop's pack.csv has no rows for today, and the report archived

    **Clean day** — no BLE-logger gaps over 60 s ... The cabin's Volthium
    Monitor.app held a continuous BLE link to both batteries.

Two false claims in one sentence: there was no link, and the BLE logger it
credits was retired on 2026-07-26.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import health as health_mod  # noqa: E402

HDR = ("ts,state,pack_v,pack_i,pack_w,soc_a,soc_b,v_a,v_b,i_a,i_b,"
       "t_a,t_b,remaining_ah_a,remaining_ah_b,dc_w\n")


def _write_pack(path: Path, stamps) -> None:
    rows = [HDR]
    for t in stamps:
        rows.append(f"{t.isoformat(timespec='seconds')},discharging,26.4,-3.0,"
                    f"-79.2,80,90,13.2,13.2,-3.0,-3.0,25,25,180,185,-79.2\n")
    path.write_text("".join(rows))


def test_sample_count_distinguishes_silence_from_success(tmp_path):
    day = datetime(2026, 10, 4, 0, 0, 0)
    pack = tmp_path / "pack.csv"

    _write_pack(pack, [])
    assert health_mod.today_pack_sample_count(pack_csv=pack, day=day) == 0

    stamps = [day + timedelta(hours=1) + timedelta(seconds=5 * i)
              for i in range(12)]
    _write_pack(pack, stamps)
    assert health_mod.today_pack_sample_count(pack_csv=pack, day=day) == 12
    # No gaps, and that now means something, because samples exist.
    assert health_mod.today_pack_gap_events(pack_csv=pack, day=day) == []


def test_missing_file_counts_zero_not_a_crash(tmp_path):
    assert health_mod.today_pack_sample_count(
        pack_csv=tmp_path / "nope.csv", day=datetime(2026, 10, 4)) == 0


def test_other_days_rows_are_not_counted(tmp_path):
    day = datetime(2026, 10, 4)
    pack = tmp_path / "pack.csv"
    _write_pack(pack, [datetime(2026, 10, 3, 12, 0, 0),
                       datetime(2026, 10, 5, 12, 0, 0)])
    assert health_mod.today_pack_sample_count(pack_csv=pack, day=day) == 0


# ------------------------------------------------- the rendered report itself

def _render(tmp_path: Path, stamps, day: datetime) -> str:
    """Run the real report against a synthetic pack.csv for `day`."""
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    _write_pack(work / "data" / "pack.csv", stamps)
    # Carry over whatever other data files the report reads; it tolerates
    # missing ones, and we only assert on the gap section.
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/end_of_day_report.py"),
         "--stdout", "--date", day.strftime("%Y-%m-%d")],
        cwd=work, capture_output=True, text=True, timeout=180)
    return proc.stdout + proc.stderr


def _gap_section(text: str) -> str:
    marker = "## Telemetry logger reliability"
    assert marker in text, f"section heading missing from report:\n{text[:800]}"
    rest = text.split(marker, 1)[1]
    return rest.split("\n## ", 1)[0]


def test_zero_samples_is_reported_as_no_telemetry_not_clean(tmp_path):
    day = datetime(2026, 10, 4)
    section = _gap_section(_render(tmp_path, [], day))
    assert "Clean day" not in section, (
        f"a day with ZERO samples still archived as a clean day:\n{section}")
    assert "NO TELEMETRY" in section


def test_a_real_gap_is_still_reported(tmp_path):
    """The honest branches must not have been bought by breaking detection."""
    day = datetime(2026, 10, 4)
    stamps = [day + timedelta(hours=1) + timedelta(seconds=5 * i)
              for i in range(10)]
    stamps += [s + timedelta(minutes=70) for s in stamps]   # a 70 min hole
    section = _gap_section(_render(tmp_path, stamps, day))
    assert "Clean day" not in section
    assert "NO TELEMETRY" not in section
    assert "gap" in section.lower()


def test_a_genuinely_clean_day_still_says_clean(tmp_path):
    day = datetime(2026, 10, 4)
    stamps = [day + timedelta(hours=1) + timedelta(seconds=5 * i)
              for i in range(200)]
    section = _gap_section(_render(tmp_path, stamps, day))
    assert "Clean day" in section, (
        f"a genuinely gapless day no longer reads as clean:\n{section}")
    assert "200 samples" in section, "clean must state the evidence it rests on"


def test_the_report_no_longer_credits_the_retired_ble_link(tmp_path):
    """BLE was retired 2026-07-26; RS485 is the live path. A report crediting
    'Volthium Monitor.app held a continuous BLE link' names a mechanism that
    cannot have produced the day's samples."""
    day = datetime(2026, 10, 4)
    stamps = [day + timedelta(hours=1) + timedelta(seconds=5 * i)
              for i in range(200)]
    section = _gap_section(_render(tmp_path, stamps, day))
    assert "Monitor.app" not in section
    assert "BLE link" not in section
    assert "RS485" in section
