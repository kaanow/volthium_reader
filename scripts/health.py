"""One-screen Volthium system health summary.

Reads the latest state from every chain — pack, today's harvest,
solar onset cascade, SolarModel, accuracy validations, confidence
log, drift — and prints a compact tabular summary. Replaces the need
to invoke a dozen separate scripts when you just want "is the system
OK?".

Designed for terminal output (~80 cols, monochrome-safe). Each line
is one chain; the layout is intentionally fixed so visual scanning
across days highlights any value that's changed.

CLI:
    python scripts/health.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import calibration_log as cal_mod  # noqa: E402
import confidence_log as conf_mod  # noqa: E402
import projection_log as proj_mod  # noqa: E402
import projection_accuracy as acc_mod  # noqa: E402
import low_soc_accuracy as low_mod  # noqa: E402
import solar_onset as so_mod  # noqa: E402
import today_harvest as today_mod  # noqa: E402

PACK_CSV = Path("data/pack.csv")
WEATHER_CSV = Path("data/weather.csv")

# Staleness thresholds (seconds since latest sample). Pack samples
# at ~10 s cadence, weather at ~30 min. Stale-flag both at ~6× their
# expected cadence so transient single-poll misses don't false-alarm.
PACK_STALE_THRESHOLD_S    = 60      # ~6 pack cycles
WEATHER_STALE_THRESHOLD_S = 60 * 60 # ~2 weather cycles

# Load-surge detection: a "surge" is a stretch where smoothed_i
# dips below -SURGE_CURRENT_THRESHOLD_A for at least SURGE_MIN_DURATION_S.
# Threshold of -20 A catches large transient draws (water heater, big
# inverter load) without picking up routine overnight discharge
# (typically -2 to -8 A). The smoothed_i filter avoids single-sample
# noise spikes.
SURGE_CURRENT_THRESHOLD_A = 20.0
SURGE_MIN_DURATION_S      = 30.0


def _last_pack_row() -> Optional[dict]:
    """Return the final row of pack.csv as a dict, or None."""
    if not PACK_CSV.exists():
        return None
    last: Optional[dict] = None
    with PACK_CSV.open() as f:
        for r in csv.DictReader(f):
            last = r
    return last


def _f(v) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _short_ts(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    return iso[11:16] if "T" in iso and len(iso) >= 16 else iso[:16]


def _staleness_seconds(ts_str: Optional[str],
                       now: Optional[datetime] = None) -> Optional[float]:
    """Return seconds-since `ts_str` (an ISO timestamp), or None if
    parseable check fails. Negative values (future ts) clamp to 0."""
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        return None
    if now is None:
        now = datetime.now()
    delta = (now - ts).total_seconds()
    return max(0.0, delta)


def _fmt_age(seconds: float) -> str:
    """Compact age string: '12 s', '4 min', '2.3 h', '1.5 d'."""
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 60 * 90:
        return f"{int(seconds / 60)} min"
    if seconds < 24 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def today_pack_gap_events(
    pack_csv: Path = PACK_CSV,
    day: Optional[datetime] = None,
    gap_threshold_s: float = PACK_STALE_THRESHOLD_S,
) -> list[tuple[str, str, float]]:
    """Return the day's individual BLE-logger gap events as
    [(gap_start_iso, gap_end_iso, gap_duration_s), ...].

    The start_iso is the LAST sample BEFORE the gap; end_iso is the
    NEXT sample AFTER the gap. Both as ISO timestamps. Useful when
    the day-report wants to enumerate each event, vs the summary
    helper which collapses to counts.

    Returns [] when no gaps, missing file, or no samples for `day`.
    """
    if not pack_csv.exists():
        return []
    if day is None:
        day = datetime.now()
    iso_prefix = day.strftime("%Y-%m-%d")
    prev_ts_dt: Optional[datetime] = None
    prev_ts_str: str = ""
    events: list[tuple[str, str, float]] = []
    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            ts_str = r.get("ts", "")
            if not ts_str.startswith(iso_prefix):
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            if prev_ts_dt is not None:
                delta = (ts - prev_ts_dt).total_seconds()
                if delta > gap_threshold_s:
                    events.append((prev_ts_str, ts_str, delta))
            prev_ts_dt = ts
            prev_ts_str = ts_str
    return events


def compute_today_pack_gaps(
    pack_csv: Path = PACK_CSV,
    day: Optional[datetime] = None,
    gap_threshold_s: float = PACK_STALE_THRESHOLD_S,
) -> tuple[int, float, float, int]:
    """Scan pack.csv for `day` (default today) and return tuple
    (gap_count, max_gap_s, total_gap_s, sample_count) where a "gap"
    is any consecutive-timestamp delta exceeding gap_threshold_s.

    The BLE logger writes pack samples at ~10 s cadence; any delta
    above gap_threshold_s indicates the logger stalled (BLE
    disconnect, sleep, crashed daemon, etc.). Useful as a daily
    reliability metric.

    Returns (0, 0.0, 0.0, 0) on missing file or empty/single-row
    day. `sample_count` lets callers compute uptime percentage.
    """
    if not pack_csv.exists():
        return (0, 0.0, 0.0, 0)
    if day is None:
        day = datetime.now()
    iso_prefix = day.strftime("%Y-%m-%d")
    prev_ts: Optional[datetime] = None
    gap_count = 0
    max_gap = 0.0
    total_gap = 0.0
    sample_count = 0
    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            ts_str = r.get("ts", "")
            if not ts_str.startswith(iso_prefix):
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            sample_count += 1
            if prev_ts is not None:
                delta = (ts - prev_ts).total_seconds()
                if delta > gap_threshold_s:
                    gap_count += 1
                    if delta > max_gap:
                        max_gap = delta
                    total_gap += delta
            prev_ts = ts
    return (gap_count, max_gap, total_gap, sample_count)


def compute_today_uptime_pct(
    pack_csv: Path = PACK_CSV,
    day: Optional[datetime] = None,
    gap_threshold_s: float = PACK_STALE_THRESHOLD_S,
) -> Optional[float]:
    """Return today's BLE-logger uptime as a percentage:
        (day_seconds_so_far − total_gap_s) / day_seconds_so_far × 100

    Where `day_seconds_so_far` is the elapsed time from the day's
    first sample to its most-recent sample. Returns None when there
    aren't enough samples (need >= 2) to span any time.

    Caller can format as "uptime 95.8%" etc.
    """
    if not pack_csv.exists():
        return None
    if day is None:
        day = datetime.now()
    iso_prefix = day.strftime("%Y-%m-%d")
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            ts_str = r.get("ts", "")
            if not ts_str.startswith(iso_prefix):
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            if first_ts is None:
                first_ts = ts
            last_ts = ts
    if first_ts is None or last_ts is None or last_ts <= first_ts:
        return None
    span_s = (last_ts - first_ts).total_seconds()
    _, _, total_gap_s, _ = compute_today_pack_gaps(
        pack_csv=pack_csv, day=day, gap_threshold_s=gap_threshold_s,
    )
    # Clamp to [0, 100] — defensive against pathological data
    pct = max(0.0, min(100.0, (span_s - total_gap_s) / span_s * 100.0))
    return round(pct, 1)


def compute_today_load_surges(
    pack_csv: Path = PACK_CSV,
    day: Optional[datetime] = None,
    current_threshold_a: float = SURGE_CURRENT_THRESHOLD_A,
    min_duration_s: float = SURGE_MIN_DURATION_S,
) -> list[tuple[str, float, float]]:
    """Return list of (start_iso, peak_smoothed_a, duration_s) for
    each load-surge event today.

    A surge is a contiguous stretch of pack.csv samples where
    `smoothed_i` ≤ -current_threshold_a, lasting at least
    `min_duration_s`. `peak_smoothed_a` is the MOST NEGATIVE value
    seen during the event (worst-case load). `start_iso` is the
    first sample of the dip.

    Smoothed_i is used rather than instantaneous pack_i so a single
    BMS noise spike doesn't fire a false-positive — the EMA window
    filters those.
    """
    if not pack_csv.exists():
        return []
    if day is None:
        day = datetime.now()
    iso_prefix = day.strftime("%Y-%m-%d")

    surges: list[tuple[str, float, float]] = []
    in_surge = False
    surge_start_ts: Optional[datetime] = None
    surge_start_iso: str = ""
    surge_peak: float = 0.0   # most-negative smoothed_i during event
    last_below_ts: Optional[datetime] = None

    with pack_csv.open() as f:
        for r in csv.DictReader(f):
            ts_str = r.get("ts", "")
            if not ts_str.startswith(iso_prefix):
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            si = _f(r.get("smoothed_i"))
            if si is None:
                continue
            if si <= -current_threshold_a:
                if not in_surge:
                    in_surge = True
                    surge_start_ts = ts
                    surge_start_iso = ts_str
                    surge_peak = si
                else:
                    if si < surge_peak:    # more negative
                        surge_peak = si
                last_below_ts = ts
            else:
                if in_surge and surge_start_ts is not None:
                    # Close the event
                    end_ts = last_below_ts or surge_start_ts
                    duration = (end_ts - surge_start_ts).total_seconds()
                    if duration >= min_duration_s:
                        surges.append((surge_start_iso,
                                       surge_peak, duration))
                in_surge = False
                surge_start_ts = None
                surge_peak = 0.0
    # Close out an unfinished surge at end of scan
    if in_surge and surge_start_ts is not None:
        end_ts = last_below_ts or surge_start_ts
        duration = (end_ts - surge_start_ts).total_seconds()
        if duration >= min_duration_s:
            surges.append((surge_start_iso, surge_peak, duration))
    return surges


def _fmt_load_surges_line(pack_csv: Path = PACK_CSV,
                          day: Optional[datetime] = None) -> Optional[str]:
    """Return a "LOAD SURGES  N events, max -X A, total Y s today"
    line when today has at least one surge event, else None.
    Mirrors the PACK GAPS line's conditional-render pattern."""
    surges = compute_today_load_surges(pack_csv=pack_csv, day=day)
    if not surges:
        return None
    plural = "" if len(surges) == 1 else "s"
    max_peak = min(s[1] for s in surges)   # most negative
    total_dur = sum(s[2] for s in surges)
    return (f"LOAD SURGES  {len(surges)} event{plural}, "
            f"max {max_peak:.1f} A, "
            f"total {_fmt_age(total_dur)} today")


def _fmt_pack_gaps_line(pack_csv: Path = PACK_CSV,
                        day: Optional[datetime] = None) -> Optional[str]:
    """Return a "PACK GAPS  N events, max X, total Y today,
    uptime Z%" line when today has at least one logger gap above
    threshold, else None (caller skips the line — no gap is the
    happy path)."""
    gap_count, max_gap, total_gap, _ = compute_today_pack_gaps(
        pack_csv=pack_csv, day=day,
    )
    if gap_count == 0:
        return None
    plural = "" if gap_count == 1 else "s"
    uptime = compute_today_uptime_pct(pack_csv=pack_csv, day=day)
    uptime_str = (f", uptime {uptime:.1f}%" if uptime is not None else "")
    return (f"PACK GAPS    {gap_count} event{plural}, "
            f"max {_fmt_age(max_gap)}, "
            f"total {_fmt_age(total_gap)} today{uptime_str}")


def _fmt_pack_line(row: Optional[dict],
                   now: Optional[datetime] = None) -> str:
    if not row:
        return "PACK         (no pack.csv yet)"
    soc_a = _f(row.get("soc_a"))
    soc_b = _f(row.get("soc_b"))
    pack_i = _f(row.get("pack_i"))
    smoothed_i = _f(row.get("smoothed_i"))
    pack_v = _f(row.get("pack_v"))
    state = (row.get("state") or "?").strip()
    soc_str = (f"{int(soc_a):d}/{int(soc_b):d}" if (soc_a is not None and soc_b is not None) else "—")
    i_str = (f"{pack_i:+.1f} A" if pack_i is not None else "—")
    smi_str = (f"smoothed {smoothed_i:+.1f} A" if smoothed_i is not None else "")
    v_str = (f"{pack_v:.2f} V" if pack_v is not None else "—")
    # Staleness: if the latest sample is older than the threshold,
    # surface a tier-1 warning. The system has caught a real BLE-
    # logger stall by this signal before — see STATUS.md 2026-05-19
    # 11:10 loop note for the diagnostic story.
    stale = _staleness_seconds(row.get("ts"), now=now)
    stale_str = ""
    if stale is not None and stale > PACK_STALE_THRESHOLD_S:
        stale_str = f"  ⚠ STALE: {_fmt_age(stale)} since last sample"
    return (f"PACK         SOC {soc_str}  {state}  "
            f"{i_str}  {smi_str}  {v_str}{stale_str}")


def _latest_weather_ts() -> Optional[str]:
    """Return the ts of the newest weather.csv row, or None."""
    if not WEATHER_CSV.exists():
        return None
    last: Optional[str] = None
    with WEATHER_CSV.open() as f:
        for r in csv.DictReader(f):
            ts = r.get("ts")
            if ts:
                last = ts
    return last


def _fmt_today_line(now: Optional[datetime] = None) -> str:
    try:
        snap = today_mod.snapshot(PACK_CSV, WEATHER_CSV)
    except Exception:
        return "TODAY        (snapshot failed)"
    ah_so_far = snap.get("solar_ah_so_far")
    ah_forecast = snap.get("solar_ah_forecast")
    pct = snap.get("pct_of_forecast")
    lr = snap.get("live_ratio_ah_per_kwh_m2")
    kwh_so_far = snap.get("irradiance_kwh_m2_so_far")
    # Cold start: pack.csv missing OR weather forecast missing
    if ah_so_far is None or ah_forecast is None:
        return "TODAY        (no harvest data yet)"
    pct_str = f"{pct:.0f}%" if pct is not None else "—"
    lr_str = (f"live_ratio {lr:.2f}" if lr is not None
              else f"live_ratio — (kWh/m² {kwh_so_far:.2f})" if kwh_so_far is not None
              else "live_ratio —")
    stale = _staleness_seconds(_latest_weather_ts(), now=now)
    stale_str = ""
    if stale is not None and stale > WEATHER_STALE_THRESHOLD_S:
        stale_str = f"  ⚠ weather stale {_fmt_age(stale)}"
    return (f"TODAY        solar {ah_so_far:+.1f} Ah / "
            f"{ah_forecast:.1f} forecast ({pct_str})  {lr_str}{stale_str}")


def _fmt_solar_onset_line() -> str:
    today_str = datetime.now().date().isoformat()
    records = so_mod.read_log()
    today_rec = next((r for r in records if r.date == today_str), None)
    if today_rec is None or today_rec.is_empty():
        return f"SOLAR ONSET  ({today_str}: pre-onset, no milestones yet)"
    parts = [
        f"zero {_short_ts(today_rec.first_zero_iso)}" if today_rec.first_zero_iso else None,
        f"idle {_short_ts(today_rec.first_idle_iso)}" if today_rec.first_idle_iso else None,
        f"pos {_short_ts(today_rec.first_positive_iso)}" if today_rec.first_positive_iso else None,
        f"net+ {_short_ts(today_rec.first_net_positive_iso)}" if today_rec.first_net_positive_iso else None,
    ]
    cascade = " → ".join(p for p in parts if p)
    soc_tail = ""
    if today_rec.soc_avg_at_net_positive is not None:
        soc_tail = f"  SOC {today_rec.soc_avg_at_net_positive:.1f}%"
    return f"SOLAR ONSET  {cascade}{soc_tail}"


def _fmt_solar_model_line() -> str:
    entries = cal_mod.read_log()
    if not entries:
        return "SOLAR MODEL  (no calibration_log entries yet)"
    # Pick the chronologically-latest entry (the production log is
    # append-only by ts, but defensive sort handles out-of-order
    # appends from test fixtures or manual edits)
    e = max(entries, key=lambda r: r.ts)
    return (f"SOLAR MODEL  coef {e.coefficient:.3f}  "
            f"({e.n_observations} obs, {e.confidence} conf, "
            f"fit {e.ts[:16]})")


def _fmt_confidence_line() -> str:
    entries = conf_mod.read_log()
    if not entries:
        return "CONFIDENCE   (no transitions logged yet)"
    # Pick the chronologically-latest entry (defensive against
    # out-of-order appends; production is append-only by ts)
    e = max(entries, key=lambda r: r.ts)
    lifted = "lifted" if e.lifted else "not lifted"
    ae = (f"±{e.recent_abs_error_pp:.2f} pp" if e.recent_abs_error_pp is not None
          else "—")
    return (f"CONFIDENCE   {e.base} → {e.resolved}  {lifted}  "
            f"n={e.recent_n} {ae}")


def _fmt_accuracy_line(label: str,
                      summary: dict,
                      latest_err: Optional[float] = None) -> str:
    if not summary or summary.get("n", 0) == 0:
        return f"{label:<12} (no validatable records yet)"
    n = summary["n"]
    mean = summary["mean_error"]
    abs_e = summary["mean_abs_error"]
    lo = summary["min_error"]
    hi = summary["max_error"]
    latest = ""
    if latest_err is not None:
        latest = f"  latest {latest_err:+.1f}"
    return (f"{label:<12} n={n}, mean {mean:+.2f} pp, abs {abs_e:.2f}  "
            f"[{lo:+.1f}..{hi:+.1f}]{latest}")


def _fmt_drift_line(latest_proj: Optional[proj_mod.LogEntry]) -> str:
    """Compute current drift from the latest harvest snapshot + the
    SolarModel's current coefficient."""
    try:
        snap = today_mod.snapshot(PACK_CSV, WEATHER_CSV)
    except Exception:
        snap = {}
    lr = snap.get("live_ratio_ah_per_kwh_m2")
    coef = latest_proj.solar_model_coefficient if latest_proj else None
    if lr is None or coef is None or coef <= 0:
        return "DRIFT        (live_ratio pending or no model fit)"
    drift = (lr - coef) / coef * 100.0
    flag = "⚠ advisory" if abs(drift) >= 20.0 else "within threshold"
    return (f"DRIFT        {drift:+.1f}% "
            f"(live {lr:.2f} vs model {coef:.2f}) — {flag}")


def _fmt_projection_and_advisory(latest_proj: Optional[proj_mod.LogEntry]) -> tuple[str, str]:
    if latest_proj is None:
        return ("PROJECTION   (no projection_log entries yet)", "ADVISORY     (no recommendation)")
    proj_line = (
        f"PROJECTION   start {latest_proj.start_soc_pct:.1f} → "
        f"sunrise {latest_proj.projected_sunrise_soc:.1f} → "
        f"low {latest_proj.projected_low_soc:.1f} → "
        f"eve {latest_proj.projected_tomorrow_evening_soc:.1f} (next 24h)"
    )
    # Re-run the advisor's verdict via a fresh invocation would be expensive;
    # instead reuse the harvest snap's "is the projected low above comfort?" check.
    # Comfort floor default is 25 %.
    if latest_proj.projected_low_soc < 25.0:
        adv_line = (f"ADVISORY     ▶ RUN GENERATOR  "
                    f"projected low {latest_proj.projected_low_soc:.0f}% "
                    f"below 25% comfort floor")
    elif latest_proj.projected_low_soc < 50.0:
        adv_line = (f"ADVISORY     ⚠ morning watch  "
                    f"projected low {latest_proj.projected_low_soc:.0f}%")
    else:
        adv_line = (f"ADVISORY     ✓ no generator needed  "
                    f"projected low {latest_proj.projected_low_soc:.0f}%")
    return proj_line, adv_line


def render_summary() -> str:
    """Build the full summary text. Returns the multi-line string."""
    now = datetime.now()
    lines: list[str] = []
    lines.append(f"=== Volthium pack health summary "
                 f"({now:%Y-%m-%d %H:%M}) ===")
    lines.append("")
    lines.append(_fmt_pack_line(_last_pack_row(), now=now))
    # PACK GAPS appears only when today has BLE logger gaps — the
    # happy path is silence.
    gaps_line = _fmt_pack_gaps_line(day=now)
    if gaps_line is not None:
        lines.append(gaps_line)
    # LOAD SURGES similarly only appears when today saw any sustained
    # large discharge events. Same conditional-render pattern.
    surges_line = _fmt_load_surges_line(day=now)
    if surges_line is not None:
        lines.append(surges_line)
    lines.append(_fmt_today_line(now=now))
    lines.append(_fmt_solar_onset_line())
    lines.append("")
    lines.append(_fmt_solar_model_line())
    lines.append(_fmt_confidence_line())
    # Sunrise accuracy
    try:
        all_proj = proj_mod.read_log()
        pack_samples = acc_mod._load_pack_samples(PACK_CSV)
        sunrise_records = acc_mod.compute_accuracy_records(all_proj, pack_samples)
    except Exception:
        sunrise_records = []
    s_sum = acc_mod.summarize(sunrise_records) if sunrise_records else {}
    latest_sunrise_err = (sunrise_records[-1].error_pct_points
                          if sunrise_records else None)
    lines.append(_fmt_accuracy_line("SUNRISE ACC", s_sum, latest_sunrise_err))
    # Morning-low accuracy
    try:
        onsets = so_mod.read_log()
        low_records = low_mod.compute_accuracy_records(all_proj, onsets)
    except Exception:
        low_records = []
    l_sum = low_mod.summarize(low_records) if low_records else {}
    latest_low_err = (low_records[-1].error_pct_points
                      if low_records else None)
    lines.append(_fmt_accuracy_line("MORN-LOW ACC", l_sum, latest_low_err))
    latest_proj = all_proj[-1] if all_proj else None
    lines.append(_fmt_drift_line(latest_proj))
    lines.append("")
    proj_line, adv_line = _fmt_projection_and_advisory(latest_proj)
    lines.append(proj_line)
    lines.append(adv_line)
    return "\n".join(lines) + "\n"


def main() -> int:
    print(render_summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
