"""A stale forecast must not be allowed to recommend the generator.

Both consumers of weather.csv project SOC forward using sunrise/sunset taken
FROM THE FORECAST ROW. So when the row is stale its sun times are stale too,
no simulated hour matches daylight, and the whole horizon is modelled as
darkness. The projection then falls monotonically into its clamp and the
advisor crosses the comfort floor.

Measured on the real pack history with a 72 h-old forecast (see the table in
generator_advisor.main): across a 60-80 % start-SOC band the unguarded code
said RUN GENERATOR while the pack had 32-52 points of headroom. At 60 % start
it reported a clamped 0.0 %.

This is a remote cabin. A false RUN GENERATOR costs a drive out or a tank of
propane, and the cabin-internet outage that makes weather.csv stale is exactly
when the operator most needs the advice to be honest.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import weather as weather_mod  # noqa: E402
from health import WEATHER_STALE_THRESHOLD_S  # noqa: E402


# --------------------------------------------------------------- age helper

def test_row_age_s_reads_the_ts_column_weather_csv_actually_has():
    """data/weather.csv's first column is `ts`. If row_age_s stopped reading
    it, every caller would get None and every staleness guard would be a
    no-op that still looked present."""
    header = (REPO / "data/weather.csv").read_text().split("\n", 1)[0]
    first_col = header.split(",")[0].strip()
    assert first_col in weather_mod.TS_KEYS, (
        f"weather.csv's timestamp column is {first_col!r} but row_age_s only "
        f"looks at {weather_mod.TS_KEYS} — the guards would silently never fire")

    now = datetime(2026, 10, 4, 12, 0, 0)
    row = {first_col: (now - timedelta(hours=3)).isoformat()}
    assert weather_mod.row_age_s(row, now=now) == pytest.approx(3 * 3600)


def test_row_age_s_returns_none_rather_than_zero_when_unstamped():
    """None means "unknown", which callers treat as "don't refuse". Returning
    0.0 would mean "fresh" and would whitewash a row with no stamp at all."""
    assert weather_mod.row_age_s({"sunrise_iso": "2026-10-04T06:12:00"}) is None
    assert weather_mod.row_age_s({}) is None
    assert weather_mod.row_age_s(None) is None


def test_row_age_s_handles_a_tz_aware_stamp_without_crashing():
    now = datetime(2026, 10, 4, 12, 0, 0)
    aware = {"ts": "2026-10-04T11:00:00+00:00"}
    age = weather_mod.row_age_s(aware, now=now)
    assert age is not None and age == pytest.approx(
        (now - datetime.fromisoformat(aware["ts"]).astimezone()
         .replace(tzinfo=None)).total_seconds())


def test_dashboard_and_advisor_share_one_definition_of_stale():
    """Two independent copies is how this shipped unguarded twice. Assert the
    duplication is gone structurally, not by reading the comments."""
    dash = (REPO / "scripts/dashboard.py").read_text()
    adv = (REPO / "scripts/generator_advisor.py").read_text()
    for name, src in (("dashboard", dash), ("generator_advisor", adv)):
        assert "row_age_s" in src, f"{name} no longer uses the shared helper"
    # Neither may hand-roll its own fromisoformat-based age walk again.
    tree = ast.parse(dash)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_weather_age_s":
            body_src = ast.dump(node)
            assert "fromisoformat" not in body_src, (
                "dashboard._weather_age_s has grown its own parsing again — "
                "it must delegate to weather.row_age_s")


# ------------------------------------------------------- the advisor refuses

def _fixture(tmp_path: Path, age_h: float, soc: float) -> tuple[Path, Path]:
    """Real pack history + a synthetic tail at `soc`, and a forecast whose
    stamp AND sun times are `age_h` old."""
    import csv

    now = datetime.now()
    pack_rows = list(csv.DictReader((REPO / "data/pack.csv").open()))
    tail = dict(pack_rows[-1])
    tail["ts"] = now.isoformat(timespec="seconds")
    tail["soc_a"] = tail["soc_b"] = str(soc)
    pack = tmp_path / "pack.csv"
    with pack.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pack_rows[0].keys()))
        w.writeheader()
        w.writerows(pack_rows + [tail])

    wx_rows = list(csv.DictReader((REPO / "data/weather.csv").open()))
    old = dict(wx_rows[-1])
    stamp = now - timedelta(hours=age_h)
    old["ts"] = stamp.isoformat(timespec="seconds")
    old["sunrise_iso"] = stamp.replace(
        hour=6, minute=12, second=0, microsecond=0).isoformat()
    old["sunset_iso"] = stamp.replace(
        hour=18, minute=40, second=0, microsecond=0).isoformat()
    wx = tmp_path / "weather.csv"
    with wx.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(wx_rows[0].keys()))
        w.writeheader()
        w.writerows(wx_rows + [old])
    return pack, wx


def _advise(tmp_path: Path, age_h: float, soc: float):
    pack, wx = _fixture(tmp_path, age_h, soc)
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts/generator_advisor.py"),
         "--pack-csv", str(pack), "--weather-csv", str(wx),
         # Without this the advisor appends a synthetic entry to the REAL
         # data/projection_log.csv, which projection_accuracy then reads.
         "--log-dir", str(tmp_path / "logs")],
        cwd=REPO, capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


@pytest.mark.parametrize("soc", [80, 72, 68, 64, 60])
def test_stale_forecast_cannot_recommend_the_generator(tmp_path, soc):
    """These are precisely the start-SOCs where the unguarded code flipped to
    a false RUN GENERATOR. None may produce a recommendation at all now."""
    rc, out = _advise(tmp_path, age_h=72, soc=soc)
    assert "RUN GENERATOR" not in out.upper(), (
        f"a 72 h-old forecast still recommends the generator at {soc}% SOC:\n{out}")
    assert rc == 1 and "refusing to advise" in out, (
        f"expected an explicit refusal naming the age, got rc={rc}:\n{out}")
    assert "72.0 h old" in out, (
        f"the refusal must state HOW stale, so the operator can judge:\n{out}")


def test_a_fresh_forecast_still_gets_a_real_recommendation(tmp_path):
    """The guard must not have been bought by breaking the working path. A
    refusal that fires always is not a fix."""
    rc, out = _advise(tmp_path, age_h=0, soc=32)
    assert "refusing to advise" not in out, f"refused a FRESH forecast:\n{out}"
    assert "RUN GENERATOR" in out.upper(), (
        f"fresh forecast at 32% SOC should still recommend the generator:\n{out}")


def test_a_forecast_inside_the_threshold_is_not_refused(tmp_path):
    """Just under the limit must pass, or the guard is really a different,
    tighter threshold than the one health.py documents."""
    age_h = (WEATHER_STALE_THRESHOLD_S / 3600) * 0.5
    rc, out = _advise(tmp_path, age_h=age_h, soc=32)
    assert "refusing to advise" not in out, (
        f"refused at {age_h} h, inside the {WEATHER_STALE_THRESHOLD_S / 3600} h "
        f"threshold:\n{out}")


def test_sun_times_are_advanced_by_a_loop_not_a_single_step():
    """Defence in depth for >48 h. A single `+= timedelta(days=1)` cannot
    reach the future from a 3-day-old row; this is the mechanism itself, so
    assert the loop structurally rather than trusting the comment."""
    src = (REPO / "scripts/generator_advisor.py").read_text()
    tree = ast.parse(src)
    advanced = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.AugAssign)
                    and isinstance(inner.target, ast.Name)
                    and inner.target.id in ("sunrise_dt", "sunset_dt")):
                advanced.add(inner.target.id)
    assert advanced == {"sunrise_dt", "sunset_dt"}, (
        f"only {sorted(advanced)} are advanced inside a loop; a single step "
        f"cannot reach the future from a forecast older than 48 h")


# -------------------------------------------- --log-dir must actually isolate

@pytest.mark.parametrize("mod_name", ["projection_log", "confidence_log",
                                      "calibration_log"])
def test_log_path_is_resolved_at_call_time_not_def_time(mod_name):
    """`def f(path: Path = LOG_PATH)` captures the Path at IMPORT time, so
    rebinding the module's LOG_PATH afterwards is silently ignored.

    This is not hypothetical: --log-dir was first written that way and was a
    complete no-op. It reported success while every test run appended a
    synthetic row to the real data/projection_log.csv — which
    projection_accuracy reads, so the advisor's own accuracy statistics were
    being polluted by its tests. A mutation reverting one signature was NOT
    caught by any other test here, which is why this one exists.
    """
    import importlib
    mod = importlib.import_module(mod_name)
    tree = ast.parse(Path(mod.__file__).read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for arg, default in zip(
                node.args.args[-len(node.args.defaults):] if node.args.defaults
                else [], node.args.defaults):
            if arg.arg != "path":
                continue
            if isinstance(default, ast.Name) and default.id == "LOG_PATH":
                offenders.append(node.name)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if arg.arg == "path" and isinstance(default, ast.Name) \
                    and default.id == "LOG_PATH":
                offenders.append(node.name)
    assert not offenders, (
        f"{mod_name}: {offenders} bind LOG_PATH as a def-time default, so "
        f"rebinding it (generator_advisor --log-dir) is silently ignored and "
        f"the real log is written anyway")


def test_log_dir_leaves_the_real_logs_untouched(tmp_path):
    """End-to-end proof, not just a structural one: run the advisor with
    --log-dir and assert the real files did not change."""
    real = [REPO / "data" / f"{n}.csv" for n in
            ("projection_log", "confidence_log", "calibration_log")]
    before = {p: (p.read_bytes() if p.exists() else None) for p in real}
    rc, out = _advise(tmp_path, age_h=0, soc=32)
    assert "refusing to advise" not in out
    for p in real:
        after = p.read_bytes() if p.exists() else None
        assert after == before[p], (
            f"--log-dir did not isolate {p.name}: the advisor wrote to the "
            f"real log anyway")
    assert (tmp_path / "logs").exists(), "--log-dir was never used at all"
